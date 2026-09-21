from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aeo.checks.runner import CheckResult, execute_check
from aeo.db.models import GuardFinding, GuardFixAttempt, GuardScan
from aeo.db.session import create_session_factory
from aeo.domain.enums import (
    EventType,
    GuardCategory,
    GuardSeverity,
    GuardStatus,
    RunStatus,
)
from aeo.git.diff import collect_diff
from aeo.guardian.rules import Finding, analyze_diff
from aeo.project.configuration import load_project_config
from aeo.telemetry.service import RunRecorder


@dataclass(slots=True)
class GuardResult:
    scan_id: str
    run_id: str
    status: GuardStatus
    findings: list[Finding]
    checks: list[CheckResult]
    fixes_applied: int


@dataclass(slots=True)
class GuardScanSummary:
    id: str
    run_id: str
    scope: str
    status: str
    total_findings: int
    blocking_findings: int
    autofix_requested: bool
    autofix_applied: bool
    started_at: datetime
    completed_at: datetime | None


def _persist_findings(session: Session, scan_id: str, findings: list[Finding]) -> None:
    existing = set(
        session.scalars(
            select(GuardFinding.fingerprint).where(GuardFinding.scan_id == scan_id)
        ).all()
    )
    for finding in findings:
        if finding.fingerprint in existing:
            continue
        session.add(
            GuardFinding(
                scan_id=scan_id,
                rule_id=finding.rule_id,
                severity=finding.severity,
                category=finding.category,
                message=finding.message,
                file_path=finding.file_path,
                line_number=finding.line_number,
                fingerprint=finding.fingerprint,
                autofixable=finding.autofixable,
            )
        )


def _quality_findings(checks: list[CheckResult], fixers: dict[str, str]) -> list[Finding]:
    return [
        Finding(
            rule_id=f"quality.{check.name}",
            severity=GuardSeverity.ERROR,
            category=GuardCategory.QUALITY,
            message=f"Quality gate failed: {check.name} ({check.command}).",
            autofixable=check.name in fixers,
        )
        for check in checks
        if not check.passed
    ]


def _run_quality(root: Path, recorder: RunRecorder) -> list[CheckResult]:
    config = load_project_config(root)
    checks: dict[str, str] = config.get("checks", {})
    results: list[CheckResult] = []
    for name, command in checks.items():
        recorder.event(EventType.CHECK_STARTED, stage=name, message=command)
        result = execute_check(root, name, command)
        results.append(result)
        recorder.event(
            EventType.CHECK_PASSED if result.passed else EventType.CHECK_FAILED,
            stage=name,
            message=result.output[-4000:],
            duration_ms=result.duration_ms,
        )
    return results


def _apply_safe_fixes(
    root: Path,
    scan_id: str,
    failed_checks: list[CheckResult],
    fixers: dict[str, str],
    recorder: RunRecorder,
) -> int:
    applied = 0
    factory = create_session_factory(root)
    for check in failed_checks:
        command = fixers.get(check.name)
        if command is None:
            continue
        recorder.event(EventType.GUARD_FIX_STARTED, stage=check.name, message=command)
        result = execute_check(root, f"fix:{check.name}", command)
        status = "passed" if result.passed else "failed"
        with factory() as session:
            session.add(
                GuardFixAttempt(
                    scan_id=scan_id,
                    rule_id=f"quality.{check.name}",
                    command=command,
                    status=status,
                    duration_ms=result.duration_ms,
                    output=result.output[-4000:] or None,
                )
            )
            session.commit()
        recorder.event(
            EventType.GUARD_FIX_COMPLETED,
            stage=check.name,
            message=status,
            duration_ms=result.duration_ms,
        )
        if result.passed:
            applied += 1
    return applied


def run_guard(root: Path, *, staged: bool = False, fix: bool = False) -> GuardResult:
    config = load_project_config(root)
    if staged and fix:
        raise RuntimeError(
            "`aeo guard --fix --staged` is intentionally unsupported: safe fixers "
            "modify the working tree, not the Git index. Run `aeo guard --fix`, "
            "review the diff, then stage the result."
        )

    guardian_config = config.get("guardian", {})
    raw_max_bytes = guardian_config.get("max_text_file_bytes", 1_000_000)
    max_bytes = int(raw_max_bytes)
    raw_blocking = guardian_config.get("blocking_severities", ["error", "blocker"])
    blocking = {str(value) for value in raw_blocking}
    fixers: dict[str, str] = config.get("fixes", {})

    recorder = RunRecorder(root, command="guard")
    run = recorder.start()
    factory = create_session_factory(root)
    scope = "staged" if staged else "working"

    with factory() as session:
        scan = GuardScan(
            run_id=run.id,
            scope=scope,
            status=GuardStatus.RUNNING,
            autofix_requested=fix,
        )
        session.add(scan)
        session.commit()
        scan_id = scan.id

    recorder.event(
        EventType.GUARD_SCAN_STARTED,
        stage=scope,
        message="guardian scan started",
    )

    try:
        snapshot = collect_diff(root, staged=staged, max_file_bytes=max_bytes)
        static_findings = analyze_diff(snapshot)
        static_blocking = [
            finding
            for finding in static_findings
            if finding.severity.value in blocking
        ]

        # Safety first: do not execute project code when deterministic preflight
        # rules already found a blocker such as a debugger, conflict, or secret.
        checks = [] if static_blocking else _run_quality(root, recorder)
        findings = static_findings + _quality_findings(checks, fixers)

        with factory() as session:
            _persist_findings(session, scan_id, findings)
            session.commit()

        fixes_applied = 0
        if fix and not static_blocking:
            fixes_applied = _apply_safe_fixes(
                root,
                scan_id,
                [check for check in checks if not check.passed],
                fixers,
                recorder,
            )
            if fixes_applied:
                # A safe fixer changed the repository: re-scan and re-run every gate.
                snapshot = collect_diff(root, staged=staged, max_file_bytes=max_bytes)
                static_findings = analyze_diff(snapshot)
                checks = _run_quality(root, recorder)
                final_findings = static_findings + _quality_findings(checks, fixers)
                final_fingerprints = {finding.fingerprint for finding in final_findings}
                with factory() as session:
                    persisted = session.scalars(
                        select(GuardFinding).where(GuardFinding.scan_id == scan_id)
                    ).all()
                    for item in persisted:
                        if item.fingerprint not in final_fingerprints:
                            item.fixed = True
                    _persist_findings(session, scan_id, final_findings)
                    session.commit()
                findings = final_findings

        unresolved_blocking = [
            finding for finding in findings if finding.severity.value in blocking
        ]
        status = GuardStatus.BLOCKED if unresolved_blocking else GuardStatus.PASSED

        with factory() as session:
            persisted_scan = session.get(GuardScan, scan_id)
            assert persisted_scan is not None
            detected_count = session.scalar(
                select(func.count())
                .select_from(GuardFinding)
                .where(GuardFinding.scan_id == scan_id)
            ) or 0
            persisted_scan.status = status
            persisted_scan.autofix_applied = fixes_applied > 0
            persisted_scan.total_findings = detected_count
            persisted_scan.blocking_findings = len(unresolved_blocking)
            persisted_scan.completed_at = datetime.now(UTC)
            session.commit()

        for finding in findings:
            recorder.event(
                EventType.GUARD_FINDING,
                stage=finding.rule_id,
                message=f"{finding.severity}: {finding.message}",
            )
        recorder.event(
            EventType.GUARD_SCAN_COMPLETED,
            stage=scope,
            message=(
                f"status={status}; unresolved={len(findings)}; "
                f"blocking={len(unresolved_blocking)}"
            ),
        )
        recorder.complete(
            RunStatus.PASSED if status == GuardStatus.PASSED else RunStatus.FAILED
        )
        return GuardResult(scan_id, run.id, status, findings, checks, fixes_applied)
    except Exception:
        # Best-effort terminal state: a failed Guardian execution must not leave
        # telemetry looking like a healthy run that is still in progress forever.
        with factory() as session:
            failed_scan = session.get(GuardScan, scan_id)
            if failed_scan is not None:
                failed_scan.status = GuardStatus.BLOCKED
                failed_scan.completed_at = datetime.now(UTC)
                session.commit()
        recorder.complete(RunStatus.FAILED)
        raise


def list_guard_scans(root: Path, *, limit: int = 20) -> list[GuardScanSummary]:
    factory = create_session_factory(root)
    with factory() as session:
        rows = session.scalars(
            select(GuardScan).order_by(GuardScan.started_at.desc()).limit(limit)
        ).all()
        return [
            GuardScanSummary(
                id=row.id,
                run_id=row.run_id,
                scope=row.scope,
                status=row.status,
                total_findings=row.total_findings,
                blocking_findings=row.blocking_findings,
                autofix_requested=row.autofix_requested,
                autofix_applied=row.autofix_applied,
                started_at=row.started_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ]


def guard_analytics(root: Path) -> dict[str, int | float]:
    factory = create_session_factory(root)
    with factory() as session:
        total = session.scalar(select(func.count()).select_from(GuardScan)) or 0
        passed = session.scalar(
            select(func.count())
            .select_from(GuardScan)
            .where(GuardScan.status == GuardStatus.PASSED)
        ) or 0
        blocked = session.scalar(
            select(func.count())
            .select_from(GuardScan)
            .where(GuardScan.status == GuardStatus.BLOCKED)
        ) or 0
        findings = session.scalar(select(func.count()).select_from(GuardFinding)) or 0
        fixed = session.scalar(
            select(func.count()).select_from(GuardFinding).where(GuardFinding.fixed.is_(True))
        ) or 0
        fix_attempts = session.scalar(select(func.count()).select_from(GuardFixAttempt)) or 0
    return {
        "scans": total,
        "passed": passed,
        "blocked": blocked,
        "pass_rate": round(passed / total * 100, 2) if total else 0.0,
        "findings": findings,
        "fixed_findings": fixed,
        "fix_attempts": fix_attempts,
    }
