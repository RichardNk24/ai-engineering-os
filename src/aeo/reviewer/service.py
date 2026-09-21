from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aeo.db.models import AiReview, AiReviewCall, AiReviewFinding
from aeo.db.session import create_session_factory
from aeo.domain.enums import EventType, ReviewFindingStatus, ReviewMode, ReviewStatus, RunStatus
from aeo.project.configuration import load_project_config
from aeo.reviewer.context import ReviewPacket, build_review_packet
from aeo.reviewer.evidence import validate_finding_evidence
from aeo.reviewer.prompts import (
    PRIMARY_SYSTEM_PROMPT,
    VERIFIER_SYSTEM_PROMPT,
    build_primary_prompt,
    build_verification_prompt,
)
from aeo.reviewer.providers import build_provider
from aeo.reviewer.providers.base import ProviderCallResult, ReviewProvider
from aeo.reviewer.schemas import (
    ReviewFindingDraft,
    ReviewResponse,
    ReviewSeverity,
    VerificationResponse,
    VerificationVerdict,
)
from aeo.telemetry.service import RunRecorder


@dataclass(frozen=True, slots=True)
class ReviewFindingResult:
    index: int
    severity: str
    category: str
    title: str
    file_path: str
    line_start: int
    line_end: int
    evidence_source: str
    confidence: float
    status: str
    recommendation: str
    verifier_confidence: float | None = None
    verifier_rationale: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewResult:
    review_id: str
    run_id: str
    status: str
    provider: str
    model: str
    mode: str
    risk_score: float
    risk_level: str
    context_chars: int
    changed_files: int
    omitted_files: int
    findings: tuple[ReviewFindingResult, ...]
    summary: str
    test_recommendations: tuple[str, ...]
    uncertainties: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    id: str
    run_id: str
    scope: str
    status: str
    provider: str
    model: str
    mode: str
    risk_score: float
    risk_level: str
    candidate_findings: int
    confirmed_findings: int
    rejected_findings: int
    uncertain_findings: int
    unverified_findings: int
    evidence_invalid_findings: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    started_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ReviewSettings:
    provider: str
    model: str
    verification_model: str
    max_context_chars: int
    max_files: int
    max_output_tokens: int
    deep_review_risk_threshold: float
    min_confidence: float


def _fingerprint(finding: ReviewFindingDraft) -> str:
    payload = "|".join(
        [
            finding.severity,
            finding.category,
            finding.file_path.replace("\\", "/"),
            str(finding.line_start),
            str(finding.line_end),
            finding.evidence_source,
            finding.title.strip().lower(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prompt_hash(system_prompt: str, user_prompt: str) -> str:
    return hashlib.sha256(f"{system_prompt}\n{user_prompt}".encode("utf-8")).hexdigest()


def _pricing(config: dict) -> tuple[float | None, float | None]:
    reviewer = config.get("reviewer", {})
    pricing = reviewer.get("pricing", {})
    raw_input = pricing.get("input_per_million_usd")
    raw_output = pricing.get("output_per_million_usd")
    return (
        float(raw_input) if raw_input is not None else None,
        float(raw_output) if raw_output is not None else None,
    )


def _cost(
    input_tokens: int,
    output_tokens: int,
    pricing: tuple[float | None, float | None],
) -> float | None:
    input_price, output_price = pricing
    if input_price is None or output_price is None:
        return None
    value = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    return round(value, 6)


def _record_call(
    session: Session,
    *,
    review_id: str,
    phase: str,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    result: ProviderCallResult,
    pricing: tuple[float | None, float | None],
) -> float | None:
    estimated_cost = _cost(
        result.usage.input_tokens,
        result.usage.output_tokens,
        pricing,
    )
    session.add(
        AiReviewCall(
            review_id=review_id,
            phase=phase,
            provider=provider,
            model=model,
            request_id=result.request_id,
            prompt_sha256=_prompt_hash(system_prompt, user_prompt),
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            latency_ms=result.latency_ms,
            estimated_cost_usd=estimated_cost,
        )
    )
    return estimated_cost


def _persist_finding(
    session: Session,
    *,
    review_id: str,
    index: int,
    finding: ReviewFindingDraft,
    status: ReviewFindingStatus,
) -> AiReviewFinding:
    row = AiReviewFinding(
        review_id=review_id,
        finding_index=index,
        fingerprint=_fingerprint(finding),
        severity=finding.severity,
        category=finding.category,
        title=finding.title,
        description=finding.description,
        file_path=finding.file_path.replace("\\", "/"),
        line_start=finding.line_start,
        line_end=finding.line_end,
        evidence_source=finding.evidence_source,
        evidence=finding.evidence,
        recommendation=finding.recommendation,
        confidence=finding.confidence,
        status=status,
    )
    session.add(row)
    return row


def _verification_targets(
    findings: list[tuple[int, ReviewFindingDraft]],
    *,
    mode: ReviewMode,
) -> list[tuple[int, ReviewFindingDraft]]:
    if mode == ReviewMode.DEEP:
        return findings
    return [
        item
        for item in findings
        if item[1].severity in {ReviewSeverity.ERROR, ReviewSeverity.BLOCKER}
    ]


def _blocking_finding(row: AiReviewFinding) -> bool:
    return row.severity in {ReviewSeverity.ERROR, ReviewSeverity.BLOCKER} and row.status in {
        ReviewFindingStatus.CONFIRMED,
        ReviewFindingStatus.UNCERTAIN,
        ReviewFindingStatus.UNVERIFIED,
    }


def _review_defaults(config: dict) -> ReviewSettings:
    reviewer = config.get("reviewer", {})
    model = str(reviewer.get("model", "gpt-5.6"))
    return ReviewSettings(
        provider=str(reviewer.get("provider", "openai")),
        model=model,
        verification_model=str(reviewer.get("verification_model") or model),
        max_context_chars=int(reviewer.get("max_context_chars", 80_000)),
        max_files=int(reviewer.get("max_files", 25)),
        max_output_tokens=int(reviewer.get("max_output_tokens", 5000)),
        deep_review_risk_threshold=float(reviewer.get("deep_review_risk_threshold", 6.0)),
        min_confidence=float(reviewer.get("min_confidence", 0.55)),
    )


def run_review(
    root: Path,
    *,
    staged: bool = False,
    deep: bool = False,
    verify: bool = True,
    dry_run: bool = False,
    provider_name: str | None = None,
    model: str | None = None,
    verification_model: str | None = None,
    max_context_chars: int | None = None,
    max_files: int | None = None,
    max_output_tokens: int | None = None,
    provider: ReviewProvider | None = None,
) -> ReviewResult:
    config = load_project_config(root)
    defaults = _review_defaults(config)
    resolved_provider = provider_name or defaults.provider
    resolved_model = model or defaults.model
    resolved_verification_model = verification_model or defaults.verification_model
    context_budget = max_context_chars or defaults.max_context_chars
    file_budget = max_files or defaults.max_files
    output_budget = max_output_tokens or defaults.max_output_tokens
    min_confidence = defaults.min_confidence
    pricing = _pricing(config)

    packet = build_review_packet(
        root,
        staged=staged,
        max_context_chars=context_budget,
        max_files=file_budget,
    )
    if not packet.changed_files:
        raise RuntimeError("No changed files are available for AI review.")

    threshold = defaults.deep_review_risk_threshold
    mode = ReviewMode.DEEP if deep or packet.risk.score >= threshold else ReviewMode.STANDARD

    recorder = RunRecorder(root, command="review")
    run = recorder.start()
    factory = create_session_factory(root)

    with factory() as session:
        review = AiReview(
            run_id=run.id,
            scope=packet.scope,
            status=ReviewStatus.RUNNING,
            provider=resolved_provider,
            model=resolved_model,
            verification_model=resolved_verification_model if verify else None,
            mode=mode,
            risk_score=packet.risk.score,
            risk_level=packet.risk.level,
            context_sha256=packet.context_sha256,
            context_chars=packet.context_chars,
            changed_files=len(packet.changed_files),
            omitted_files=len(packet.omitted_files),
        )
        session.add(review)
        session.commit()
        review_id = review.id

    recorder.event(
        EventType.REVIEW_STARTED,
        stage=mode,
        message=f"provider={resolved_provider}; model={resolved_model}; scope={packet.scope}",
    )
    recorder.event(
        EventType.REVIEW_CONTEXT_BUILT,
        stage=packet.risk.level,
        message=(
            f"risk={packet.risk.score}; files={len(packet.changed_files)}; "
            f"omitted={len(packet.omitted_files)}; chars={packet.context_chars}; "
            f"sha256={packet.context_sha256}"
        ),
    )

    if dry_run:
        with factory() as session:
            row = session.get(AiReview, review_id)
            assert row is not None
            row.status = ReviewStatus.DRY_RUN
            row.completed_at = datetime.now(UTC)
            session.commit()
        recorder.event(EventType.REVIEW_COMPLETED, stage="dry_run", message="no model invoked")
        recorder.complete(RunStatus.PASSED)
        return ReviewResult(
            review_id=review_id,
            run_id=run.id,
            status=ReviewStatus.DRY_RUN,
            provider=resolved_provider,
            model=resolved_model,
            mode=mode,
            risk_score=packet.risk.score,
            risk_level=packet.risk.level,
            context_chars=packet.context_chars,
            changed_files=len(packet.changed_files),
            omitted_files=len(packet.omitted_files),
            findings=(),
            summary="Dry run: context built; no model invoked.",
            test_recommendations=(),
            uncertainties=(),
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=None,
        )

    resolved_provider_impl = provider or build_provider(resolved_provider)
    primary_prompt = build_primary_prompt(packet, mode=mode)

    try:
        primary = resolved_provider_impl.review(
            model=resolved_model,
            system_prompt=PRIMARY_SYSTEM_PROMPT,
            user_prompt=primary_prompt,
            max_output_tokens=output_budget,
        )
        if not isinstance(primary.payload, ReviewResponse):
            raise RuntimeError("Review provider returned the wrong primary response type.")

        recorder.event(
            EventType.REVIEW_MODEL_CALL,
            stage="primary",
            message=(
                f"model={resolved_model}; input_tokens={primary.usage.input_tokens}; "
                f"output_tokens={primary.usage.output_tokens}"
            ),
            duration_ms=primary.latency_ms,
        )

        valid_candidates: list[tuple[int, ReviewFindingDraft]] = []
        with factory() as session:
            primary_cost = _record_call(
                session,
                review_id=review_id,
                phase="primary",
                provider=resolved_provider,
                model=resolved_model,
                system_prompt=PRIMARY_SYSTEM_PROMPT,
                user_prompt=primary_prompt,
                result=primary,
                pricing=pricing,
            )
            for index, finding in enumerate(primary.payload.findings):
                evidence = validate_finding_evidence(root, packet, finding)
                if not evidence.valid:
                    status = ReviewFindingStatus.EVIDENCE_INVALID
                elif finding.confidence < min_confidence:
                    status = ReviewFindingStatus.UNCERTAIN
                else:
                    status = ReviewFindingStatus.UNVERIFIED
                    valid_candidates.append((index, finding))
                row = _persist_finding(
                    session,
                    review_id=review_id,
                    index=index,
                    finding=finding,
                    status=status,
                )
                session.flush()
            session.commit()

        targets = _verification_targets(valid_candidates, mode=mode) if verify else []
        verifier_result: ProviderCallResult | None = None
        verifier_cost: float | None = None
        if targets:
            verifier_prompt = build_verification_prompt(packet, targets)
            verifier_result = resolved_provider_impl.verify(
                model=resolved_verification_model,
                system_prompt=VERIFIER_SYSTEM_PROMPT,
                user_prompt=verifier_prompt,
                max_output_tokens=min(output_budget, 3500),
            )
            if not isinstance(verifier_result.payload, VerificationResponse):
                raise RuntimeError("Review provider returned the wrong verification response type.")

            recorder.event(
                EventType.REVIEW_MODEL_CALL,
                stage="verification",
                message=(
                    f"model={resolved_verification_model}; "
                    f"input_tokens={verifier_result.usage.input_tokens}; "
                    f"output_tokens={verifier_result.usage.output_tokens}"
                ),
                duration_ms=verifier_result.latency_ms,
            )

            allowed_indices = {index for index, _ in targets}
            seen_indices: set[int] = set()
            verification_events: list[tuple[int, str, float]] = []
            with factory() as session:
                verifier_cost = _record_call(
                    session,
                    review_id=review_id,
                    phase="verification",
                    provider=resolved_provider,
                    model=resolved_verification_model,
                    system_prompt=VERIFIER_SYSTEM_PROMPT,
                    user_prompt=verifier_prompt,
                    result=verifier_result,
                    pricing=pricing,
                )
                persisted = {
                    row.finding_index: row
                    for row in session.scalars(
                        select(AiReviewFinding).where(AiReviewFinding.review_id == review_id)
                    ).all()
                }
                for verdict in verifier_result.payload.items:
                    if (
                        verdict.finding_index not in allowed_indices
                        or verdict.finding_index in seen_indices
                    ):
                        continue
                    seen_indices.add(verdict.finding_index)
                    row = persisted.get(verdict.finding_index)
                    if row is None:
                        continue
                    row.status = ReviewFindingStatus(verdict.verdict.value)
                    row.verifier_confidence = verdict.confidence
                    row.verifier_rationale = verdict.rationale
                    verification_events.append(
                        (verdict.finding_index, verdict.verdict.value, verdict.confidence)
                    )
                for missing_index in allowed_indices - seen_indices:
                    row = persisted.get(missing_index)
                    if row is not None:
                        row.status = ReviewFindingStatus.UNCERTAIN
                        row.verifier_rationale = "Verifier omitted this candidate finding."
                session.commit()

            # Emit telemetry only after the SQLite write transaction has committed.
            for finding_index, verdict_value, confidence in verification_events:
                recorder.event(
                    EventType.REVIEW_VERIFICATION,
                    stage=str(finding_index),
                    message=f"{verdict_value}; confidence={confidence:.2f}",
                )

        with factory() as session:
            rows = list(
                session.scalars(
                    select(AiReviewFinding)
                    .where(AiReviewFinding.review_id == review_id)
                    .order_by(AiReviewFinding.finding_index)
                ).all()
            )
            confirmed = sum(1 for row in rows if row.status == ReviewFindingStatus.CONFIRMED)
            rejected = sum(1 for row in rows if row.status == ReviewFindingStatus.REJECTED)
            uncertain = sum(1 for row in rows if row.status == ReviewFindingStatus.UNCERTAIN)
            unverified = sum(1 for row in rows if row.status == ReviewFindingStatus.UNVERIFIED)
            evidence_invalid = sum(
                1 for row in rows if row.status == ReviewFindingStatus.EVIDENCE_INVALID
            )
            blocked = any(_blocking_finding(row) for row in rows)
            status = ReviewStatus.BLOCKED if blocked else ReviewStatus.PASSED

            review = session.get(AiReview, review_id)
            assert review is not None
            review.status = status
            review.candidate_findings = len(rows)
            review.confirmed_findings = confirmed
            review.rejected_findings = rejected
            review.uncertain_findings = uncertain
            review.unverified_findings = unverified
            review.evidence_invalid_findings = evidence_invalid
            review.summary = primary.payload.summary
            review.risk_assessment = primary.payload.risk_assessment
            review.test_recommendations_json = json.dumps(primary.payload.test_recommendations)
            review.uncertainties_json = json.dumps(primary.payload.uncertainties)
            review.input_tokens = primary.usage.input_tokens + (
                verifier_result.usage.input_tokens if verifier_result else 0
            )
            review.output_tokens = primary.usage.output_tokens + (
                verifier_result.usage.output_tokens if verifier_result else 0
            )
            costs = [value for value in (primary_cost, verifier_cost) if value is not None]
            review.estimated_cost_usd = round(sum(costs), 6) if costs else None
            review.primary_latency_ms = primary.latency_ms
            review.verifier_latency_ms = verifier_result.latency_ms if verifier_result else None
            review.completed_at = datetime.now(UTC)
            session.commit()

            result_findings = tuple(
                ReviewFindingResult(
                    index=row.finding_index,
                    severity=row.severity,
                    category=row.category,
                    title=row.title,
                    file_path=row.file_path,
                    line_start=row.line_start,
                    line_end=row.line_end,
                    evidence_source=row.evidence_source,
                    confidence=row.confidence,
                    status=row.status,
                    recommendation=row.recommendation,
                    verifier_confidence=row.verifier_confidence,
                    verifier_rationale=row.verifier_rationale,
                )
                for row in rows
            )
            total_input = review.input_tokens
            total_output = review.output_tokens
            total_cost = review.estimated_cost_usd

        for finding in result_findings:
            recorder.event(
                EventType.REVIEW_FINDING,
                stage=f"{finding.severity}:{finding.status}",
                message=(
                    f"{finding.file_path}:{finding.line_start}-{finding.line_end} "
                    f"{finding.title}"
                ),
            )
        recorder.event(
            EventType.REVIEW_COMPLETED,
            stage=status,
            message=(
                f"candidates={len(result_findings)}; confirmed={confirmed}; rejected={rejected}; "
                f"uncertain={uncertain}; unverified={unverified}; "
                f"evidence_invalid={evidence_invalid}"
            ),
        )
        recorder.complete(RunStatus.FAILED if status == ReviewStatus.BLOCKED else RunStatus.PASSED)

        return ReviewResult(
            review_id=review_id,
            run_id=run.id,
            status=status,
            provider=resolved_provider,
            model=resolved_model,
            mode=mode,
            risk_score=packet.risk.score,
            risk_level=packet.risk.level,
            context_chars=packet.context_chars,
            changed_files=len(packet.changed_files),
            omitted_files=len(packet.omitted_files),
            findings=result_findings,
            summary=primary.payload.summary,
            test_recommendations=tuple(primary.payload.test_recommendations),
            uncertainties=tuple(primary.payload.uncertainties),
            input_tokens=total_input,
            output_tokens=total_output,
            estimated_cost_usd=total_cost,
        )
    except Exception:
        with factory() as session:
            review = session.get(AiReview, review_id)
            if review is not None:
                review.status = ReviewStatus.FAILED
                review.completed_at = datetime.now(UTC)
                session.commit()
        recorder.complete(RunStatus.FAILED)
        raise


def list_reviews(root: Path, *, limit: int = 20) -> list[ReviewSummary]:
    factory = create_session_factory(root)
    with factory() as session:
        rows = list(
            session.scalars(
                select(AiReview).order_by(AiReview.started_at.desc()).limit(limit)
            ).all()
        )
        return [
            ReviewSummary(
                id=row.id,
                run_id=row.run_id,
                scope=row.scope,
                status=row.status,
                provider=row.provider,
                model=row.model,
                mode=row.mode,
                risk_score=row.risk_score,
                risk_level=row.risk_level,
                candidate_findings=row.candidate_findings,
                confirmed_findings=row.confirmed_findings,
                rejected_findings=row.rejected_findings,
                uncertain_findings=row.uncertain_findings,
                unverified_findings=row.unverified_findings,
                evidence_invalid_findings=row.evidence_invalid_findings,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                estimated_cost_usd=row.estimated_cost_usd,
                started_at=row.started_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ]


def review_analytics(root: Path) -> dict[str, int | float]:
    factory = create_session_factory(root)
    with factory() as session:
        completed_statuses = [ReviewStatus.PASSED, ReviewStatus.BLOCKED]
        total = session.scalar(
            select(func.count())
            .select_from(AiReview)
            .where(AiReview.status.in_(completed_statuses))
        ) or 0
        passed = session.scalar(
            select(func.count()).select_from(AiReview).where(AiReview.status == ReviewStatus.PASSED)
        ) or 0
        blocked = session.scalar(
            select(func.count())
            .select_from(AiReview)
            .where(AiReview.status == ReviewStatus.BLOCKED)
        ) or 0
        findings = session.scalar(select(func.count()).select_from(AiReviewFinding)) or 0
        confirmed = session.scalar(
            select(func.count())
            .select_from(AiReviewFinding)
            .where(AiReviewFinding.status == ReviewFindingStatus.CONFIRMED)
        ) or 0
        rejected = session.scalar(
            select(func.count())
            .select_from(AiReviewFinding)
            .where(AiReviewFinding.status == ReviewFindingStatus.REJECTED)
        ) or 0
        uncertain = session.scalar(
            select(func.count())
            .select_from(AiReviewFinding)
            .where(AiReviewFinding.status == ReviewFindingStatus.UNCERTAIN)
        ) or 0
        unverified = session.scalar(
            select(func.count())
            .select_from(AiReviewFinding)
            .where(AiReviewFinding.status == ReviewFindingStatus.UNVERIFIED)
        ) or 0
        evidence_invalid = session.scalar(
            select(func.count())
            .select_from(AiReviewFinding)
            .where(AiReviewFinding.status == ReviewFindingStatus.EVIDENCE_INVALID)
        ) or 0
        input_tokens = session.scalar(select(func.sum(AiReview.input_tokens))) or 0
        output_tokens = session.scalar(select(func.sum(AiReview.output_tokens))) or 0
        cost = session.scalar(select(func.sum(AiReview.estimated_cost_usd)))
        avg_primary_latency = session.scalar(select(func.avg(AiReview.primary_latency_ms))) or 0.0

    verified_decisions = confirmed + rejected + uncertain
    return {
        "reviews": total,
        "passed": passed,
        "blocked": blocked,
        "pass_rate": round(passed / total * 100, 2) if total else 0.0,
        "findings": findings,
        "confirmed": confirmed,
        "rejected": rejected,
        "uncertain": uncertain,
        "unverified": unverified,
        "evidence_invalid": evidence_invalid,
        "verifier_rejection_rate": (
            round(rejected / verified_decisions * 100, 2) if verified_decisions else 0.0
        ),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "estimated_cost_usd": round(float(cost), 6) if cost is not None else 0.0,
        "average_primary_latency_ms": round(float(avg_primary_latency), 2),
    }
