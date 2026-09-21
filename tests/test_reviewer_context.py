from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aeo.project.configuration import initialize_project
from aeo.reviewer.context import build_review_packet
from aeo.reviewer.evidence import validate_finding_evidence
from aeo.reviewer.schemas import (
    EvidenceSource,
    ReviewCategory,
    ReviewFindingDraft,
    ReviewSeverity,
)


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='review-demo'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    initialize_project(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "aeo@example.com")
    _git(tmp_path, "config", "user.name", "AEO Test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")
    return tmp_path


def test_review_packet_contains_bounded_line_context(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "app.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    packet = build_review_packet(root, max_context_chars=10_000)

    assert packet.changed_files == ("app.py",)
    assert packet.sections
    assert "L2:     return a / b" in packet.sections[0].content
    assert len(packet.context_sha256) == 64


def test_evidence_validator_rejects_hallucinated_quote(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "app.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    packet = build_review_packet(root)

    finding = ReviewFindingDraft(
        severity=ReviewSeverity.ERROR,
        category=ReviewCategory.CORRECTNESS,
        title="Unsupported finding",
        description="Claims code that is not present.",
        file_path="app.py",
        line_start=2,
        line_end=2,
        evidence="return safe_divide(a, b)",
        recommendation="Use the actual evidence.",
        confidence=0.9,
    )

    validation = validate_finding_evidence(root, packet, finding)
    assert validation.valid is False
    assert "not present" in str(validation.reason)


def test_sensitive_preflight_blocks_external_review_context(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
    (root / "app.py").write_text(
        f"KEY = {private_key_marker!r}\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="blocked before model invocation"):
        build_review_packet(root)


def test_diff_evidence_validates_removed_code(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "app.py").write_text(
        "def value():\n    return 2\n",
        encoding="utf-8",
    )
    packet = build_review_packet(root)
    diff_lines = packet.diff_context.splitlines()
    target_number = next(
        int(line.split(":", 1)[0][1:])
        for line in diff_lines
        if "-    return 1" in line
    )

    finding = ReviewFindingDraft(
        severity=ReviewSeverity.ERROR,
        category=ReviewCategory.CORRECTNESS,
        title="Removed previous behavior",
        description="The patch removes the previous return path.",
        file_path="app.py",
        line_start=target_number,
        line_end=target_number,
        evidence_source=EvidenceSource.DIFF,
        evidence="-    return 1",
        recommendation="Verify that removing this behavior is intentional.",
        confidence=0.9,
    )

    validation = validate_finding_evidence(root, packet, finding)
    assert validation.valid is True
