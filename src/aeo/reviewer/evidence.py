from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from aeo.reviewer.context import ReviewPacket
from aeo.reviewer.schemas import EvidenceSource, ReviewFindingDraft


@dataclass(frozen=True, slots=True)
class EvidenceValidation:
    valid: bool
    reason: str | None = None


_DIFF_LINE = re.compile(r"^D(\d+): (.*)$")


def _validate_diff_evidence(
    packet: ReviewPacket,
    finding: ReviewFindingDraft,
) -> EvidenceValidation:
    parsed: dict[int, str] = {}
    file_at_line: dict[int, str | None] = {}
    current_file: str | None = None
    previous_file: str | None = None

    for rendered in packet.diff_context.splitlines():
        match = _DIFF_LINE.match(rendered)
        if match is None:
            continue
        number = int(match.group(1))
        content = match.group(2)

        if content.startswith("diff --git a/") and " b/" in content:
            current_file = content.split(" b/", 1)[1]
            previous_file = current_file
        elif content.startswith("--- a/"):
            previous_file = content[6:]
            current_file = previous_file
        elif content.startswith("+++ b/"):
            current_file = content[6:]
        elif content == "+++ /dev/null":
            current_file = previous_file

        parsed[number] = content
        file_at_line[number] = current_file

    if finding.line_end < finding.line_start:
        return EvidenceValidation(False, "line_end is before line_start")
    if finding.line_end - finding.line_start > 40:
        return EvidenceValidation(False, "diff evidence range is too broad")

    requested = list(range(finding.line_start, finding.line_end + 1))
    if any(number not in parsed for number in requested):
        return EvidenceValidation(False, "cited diff range is outside the retained diff context")

    normalized_path = finding.file_path.replace("\\", "/")
    if any(file_at_line.get(number) != normalized_path for number in requested):
        return EvidenceValidation(False, "cited diff range does not belong to the claimed file")

    actual = "\n".join(parsed[number] for number in requested)
    expected = " ".join(finding.evidence.split())
    normalized_actual = " ".join(actual.split())
    if expected not in normalized_actual:
        return EvidenceValidation(False, "quoted evidence is not present in the cited diff range")

    return EvidenceValidation(True)


def validate_finding_evidence(
    root: Path,
    packet: ReviewPacket,
    finding: ReviewFindingDraft,
) -> EvidenceValidation:
    if finding.evidence_source == EvidenceSource.DIFF:
        return _validate_diff_evidence(packet, finding)

    normalized_path = finding.file_path.replace("\\", "/")
    changed = {path.replace("\\", "/") for path in packet.changed_files}
    if normalized_path not in changed:
        return EvidenceValidation(False, "finding cites a file outside the reviewed change set")

    if finding.line_end < finding.line_start:
        return EvidenceValidation(False, "line_end is before line_start")
    if finding.line_end - finding.line_start > 40:
        return EvidenceValidation(False, "evidence range is too broad")

    path = root / normalized_path
    if not path.exists() or not path.is_file():
        return EvidenceValidation(False, "cited file does not exist in the working tree")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return EvidenceValidation(False, "cited file is not readable as UTF-8 text")

    if finding.line_start > len(lines) or finding.line_end > len(lines):
        return EvidenceValidation(False, "cited line range is outside the current file")

    actual = "\n".join(lines[finding.line_start - 1 : finding.line_end])
    expected = " ".join(finding.evidence.split())
    normalized_actual = " ".join(actual.split())
    if expected not in normalized_actual:
        return EvidenceValidation(False, "quoted evidence is not present in the cited line range")

    return EvidenceValidation(True)
