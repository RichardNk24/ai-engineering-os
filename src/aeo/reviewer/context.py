from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from aeo.domain.enums import GuardCategory, GuardSeverity
from aeo.git.diff import ChangedLine, DiffSnapshot, collect_diff
from aeo.guardian.rules import Finding, analyze_diff
from aeo.project.configuration import load_project_config


@dataclass(frozen=True, slots=True)
class ContextSection:
    file_path: str
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True, slots=True)
class ReviewRisk:
    score: float
    level: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewPacket:
    scope: str
    changed_files: tuple[str, ...]
    omitted_files: tuple[str, ...]
    sections: tuple[ContextSection, ...]
    policy_context: str
    project_context: str
    diff_context: str
    risk: ReviewRisk
    context_chars: int
    context_sha256: str
    guardian_findings: tuple[Finding, ...]


_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(password|passwd|api[_-]?key|secret|access[_-]?token|auth[_-]?token)"
    r"(\s*[:=]\s*)(['\"])([^'\"]+)(['\"])"
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}")
_HIGH_RISK_PATH = re.compile(
    r"(?i)(auth|security|permission|tenant|payment|billing|invoice|migration|schema|database|"
    r"transaction|crypto|token|session|middleware|webhook|concurrency|lock)"
)
_TEST_PATH = re.compile(r"(?i)(^|/)(tests?|specs?)(/|$)|(^|/).*(_test|\.test|\.spec)\.")


def _sanitize_line(value: str) -> str:
    value = _SENSITIVE_ASSIGNMENT.sub(r"\1\2\3[REDACTED]\5", value)
    return _BEARER.sub(r"\1[REDACTED]", value)


def _merge_ranges(numbers: list[int], radius: int = 20) -> list[tuple[int, int]]:
    if not numbers:
        return []
    raw = sorted((max(1, n - radius), n + radius) for n in set(numbers))
    merged: list[tuple[int, int]] = []
    for start, end in raw:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _line_map(lines: list[ChangedLine]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for line in lines:
        result.setdefault(line.file_path, []).append(line.line_number)
    return result


def _priority(path: str, changed_line_count: int) -> tuple[int, int, str]:
    high_risk = 0 if _HIGH_RISK_PATH.search(path) else 1
    return (high_risk, -changed_line_count, path)


def _read_sections(
    root: Path,
    snapshot: DiffSnapshot,
    *,
    max_context_chars: int,
    max_files: int,
    max_file_bytes: int,
) -> tuple[list[ContextSection], list[str]]:
    lines_by_file = _line_map(snapshot.changed_lines)
    ranked_files = sorted(
        snapshot.files,
        key=lambda path: _priority(path, len(lines_by_file.get(path, []))),
    )
    selected_files = ranked_files[:max_files]
    omitted = ranked_files[max_files:]

    sections: list[ContextSection] = []
    used = 0
    for relative in selected_files:
        path = root / relative
        if not path.exists() or not path.is_file():
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                omitted.append(relative)
                continue
            data = path.read_bytes()
            if b"\x00" in data:
                omitted.append(relative)
                continue
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            omitted.append(relative)
            continue

        file_lines = text.splitlines()
        changed_numbers = lines_by_file.get(relative, [])
        if not changed_numbers:
            # Untracked or metadata-only files: include a bounded prefix.
            ranges = [(1, min(len(file_lines), 80))] if file_lines else []
        else:
            ranges = _merge_ranges(changed_numbers)

        for start, end in ranges:
            end = min(end, len(file_lines))
            if start > end:
                continue
            rendered_lines = [
                f"L{number}: {_sanitize_line(file_lines[number - 1])}"
                for number in range(start, end + 1)
            ]
            content = "\n".join(rendered_lines)
            remaining = max_context_chars - used
            if remaining <= 0:
                if relative not in omitted:
                    omitted.append(relative)
                break
            if len(content) > remaining:
                content = content[:remaining]
            sections.append(ContextSection(relative, start, end, content))
            used += len(content)
            if used >= max_context_chars:
                break
        if used >= max_context_chars:
            included = {section.file_path for section in sections}
            omitted.extend(file for file in selected_files if file not in included)
            break

    return sections, list(dict.fromkeys(omitted))


def _read_policy_context(root: Path, configured: list[str], max_chars: int = 12000) -> str:
    candidates = [
        *configured,
        ".aeo/reviewer.md",
        "AGENTS.md",
        "CONTRIBUTING.md",
        "CLAUDE.md",
    ]
    chunks: list[str] = []
    used = 0
    for relative in dict.fromkeys(candidates):
        path = root / relative
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        remaining = max_chars - used
        if remaining <= 0:
            break
        text = text[:remaining]
        chunks.append(f"### {relative}\n{text}")
        used += len(text)
    return "\n\n".join(chunks)



def _render_diff_context(raw_diff: str, max_chars: int) -> str:
    if not raw_diff:
        return ""
    chunks: list[str] = []
    used = 0
    for number, raw_line in enumerate(raw_diff.splitlines(), start=1):
        rendered = f"D{number}: {_sanitize_line(raw_line)}"
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(rendered) > remaining:
            rendered = rendered[:remaining]
        chunks.append(rendered)
        used += len(rendered) + 1
    return "\n".join(chunks)

def _risk(snapshot: DiffSnapshot) -> ReviewRisk:
    score = 0.0
    reasons: list[str] = []
    file_count = len(snapshot.files)
    changed_line_count = len(snapshot.changed_lines)

    if file_count:
        score += min(2.0, file_count / 5)
    if changed_line_count:
        score += min(3.0, changed_line_count / 80)

    high_risk_files = [path for path in snapshot.files if _HIGH_RISK_PATH.search(path)]
    if high_risk_files:
        score += 2.5
        reasons.append(f"high-risk paths changed: {', '.join(high_risk_files[:4])}")

    source_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs")
    has_source = any(path.endswith(source_suffixes) for path in snapshot.files)
    has_tests = any(_TEST_PATH.search(path) for path in snapshot.files)
    if has_source and not has_tests:
        score += 1.0
        reasons.append("source changed without an accompanying test file")

    metadata_files = ("pyproject.toml", "package.json", "uv.lock", "pnpm-lock.yaml")
    if any(path.endswith(metadata_files) for path in snapshot.files):
        score += 0.5
        reasons.append("dependency or build metadata changed")

    score = round(min(10.0, score), 2)
    level = "low"
    if score >= 8:
        level = "critical"
    elif score >= 6:
        level = "high"
    elif score >= 3:
        level = "medium"
    if not reasons:
        reasons.append("ordinary code change")
    return ReviewRisk(score, level, tuple(reasons))


def _unsafe_for_external_review(findings: list[Finding]) -> list[Finding]:
    return [
        finding
        for finding in findings
        if finding.severity == GuardSeverity.BLOCKER
        and finding.category in {GuardCategory.SECURITY, GuardCategory.HYGIENE}
    ]


def build_review_packet(
    root: Path,
    *,
    staged: bool = False,
    max_context_chars: int = 80_000,
    max_files: int = 25,
    max_file_bytes: int = 1_000_000,
) -> ReviewPacket:
    raw_snapshot = collect_diff(root, staged=staged, max_file_bytes=max_file_bytes)
    review_files = [path for path in raw_snapshot.files if not path.startswith(".aeo/")]
    snapshot = DiffSnapshot(
        files=review_files,
        changed_lines=[
            line for line in raw_snapshot.changed_lines if not line.file_path.startswith(".aeo/")
        ],
        untracked_files=[
            path for path in raw_snapshot.untracked_files if not path.startswith(".aeo/")
        ],
        raw_diff=raw_snapshot.raw_diff,
    )
    findings = analyze_diff(snapshot)
    unsafe = _unsafe_for_external_review(findings)
    if unsafe:
        rules = ", ".join(item.rule_id for item in unsafe)
        raise RuntimeError(
            "AI review blocked before model invocation because sensitive or unsafe content was "
            f"detected by deterministic preflight: {rules}. Resolve the Guardian blockers first."
        )

    config = load_project_config(root)
    reviewer_config = config.get("reviewer", {})
    policy_files = [str(item) for item in reviewer_config.get("policy_files", [])]
    diff_budget = min(20_000, max(2_000, max_context_chars // 3))
    diff_context = _render_diff_context(snapshot.raw_diff, diff_budget)
    section_budget = max(1_000, max_context_chars - len(diff_context))
    sections, omitted = _read_sections(
        root,
        snapshot,
        max_context_chars=section_budget,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
    )

    project_context = json.dumps(config.get("project", {}), sort_keys=True)
    policy_context = _read_policy_context(root, policy_files)
    risk = _risk(snapshot)
    manifest = "\n".join(
        [
            f"scope={'staged' if staged else 'working'}",
            f"risk={risk.score}:{risk.level}",
            project_context,
            policy_context,
            diff_context,
            *(
                f"{section.file_path}:{section.start_line}-{section.end_line}\n{section.content}"
                for section in sections
            ),
        ]
    )
    digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()

    return ReviewPacket(
        scope="staged" if staged else "working",
        changed_files=tuple(snapshot.files),
        omitted_files=tuple(omitted),
        sections=tuple(sections),
        policy_context=policy_context,
        project_context=project_context,
        diff_context=diff_context,
        risk=risk,
        context_chars=len(manifest),
        context_sha256=digest,
        guardian_findings=tuple(findings),
    )


def render_review_context(packet: ReviewPacket) -> str:
    chunks = [
        "<repository_metadata>",
        packet.project_context,
        "</repository_metadata>",
        "<risk>",
        f"score={packet.risk.score} level={packet.risk.level}",
        *packet.risk.reasons,
        "</risk>",
    ]
    if packet.policy_context:
        chunks.extend(["<repository_policies>", packet.policy_context, "</repository_policies>"])
    if packet.diff_context:
        chunks.extend(["<git_diff>", packet.diff_context, "</git_diff>"])
    chunks.append("<changed_code>")
    for section in packet.sections:
        chunks.append(
            (
                f"<file path={json.dumps(section.file_path)} "
                f"lines=\"{section.start_line}-{section.end_line}\">\n"
                f"{section.content}\n</file>"
            )
        )
    chunks.append("</changed_code>")
    if packet.omitted_files:
        chunks.extend(
            [
                "<omitted_files>",
                "\n".join(packet.omitted_files),
                "</omitted_files>",
            ]
        )
    return "\n".join(chunks)
