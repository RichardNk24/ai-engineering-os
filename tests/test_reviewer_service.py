from __future__ import annotations

import subprocess
from pathlib import Path

from aeo.db.models import AiReviewCall
from aeo.db.session import create_session_factory
from aeo.project.configuration import initialize_project
from aeo.reviewer.providers.base import ProviderCallResult, ProviderUsage
from aeo.reviewer.schemas import (
    ReviewCategory,
    ReviewFindingDraft,
    ReviewResponse,
    ReviewSeverity,
    VerificationItem,
    VerificationResponse,
    VerificationVerdict,
)
from aeo.reviewer.service import review_analytics, run_review


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
    (tmp_path / "app.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    return tmp_path


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        review_response: ReviewResponse,
        verification_response: VerificationResponse | None = None,
    ) -> None:
        self.review_response = review_response
        self.verification_response = verification_response or VerificationResponse(items=[])
        self.review_calls = 0
        self.verify_calls = 0

    def review(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> ProviderCallResult:
        self.review_calls += 1
        assert "UNTRUSTED DATA" in system_prompt
        assert "app.py" in user_prompt
        return ProviderCallResult(
            payload=self.review_response,
            usage=ProviderUsage(input_tokens=1000, output_tokens=200),
            request_id="review-request",
            latency_ms=125.0,
        )

    def verify(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> ProviderCallResult:
        self.verify_calls += 1
        assert "skeptical" in system_prompt.lower()
        return ProviderCallResult(
            payload=self.verification_response,
            usage=ProviderUsage(input_tokens=400, output_tokens=80),
            request_id="verify-request",
            latency_ms=75.0,
        )


def _finding(*, evidence: str = "return a / b") -> ReviewFindingDraft:
    return ReviewFindingDraft(
        severity=ReviewSeverity.ERROR,
        category=ReviewCategory.CORRECTNESS,
        title="Division can raise for zero divisor",
        description="The new function divides by b without guarding b == 0.",
        file_path="app.py",
        line_start=2,
        line_end=2,
        evidence=evidence,
        recommendation="Define or validate the zero-divisor behavior.",
        confidence=0.92,
    )


def _response(finding: ReviewFindingDraft) -> ReviewResponse:
    return ReviewResponse(
        summary="One concrete correctness risk was found.",
        risk_assessment="The change is small but changes runtime behavior.",
        findings=[finding],
        test_recommendations=["Add a zero-divisor test."],
        uncertainties=[],
    )


def test_confirmed_error_blocks_review_and_records_calls(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    provider = FakeProvider(
        _response(_finding()),
        VerificationResponse(
            items=[
                VerificationItem(
                    finding_index=0,
                    verdict=VerificationVerdict.CONFIRMED,
                    confidence=0.96,
                    rationale="The evidence directly performs unguarded division.",
                )
            ]
        ),
    )

    result = run_review(
        root,
        provider=provider,
        provider_name="fake",
        model="review-model",
        verification_model="verify-model",
    )

    assert result.status == "blocked"
    assert result.findings[0].status == "confirmed"
    assert result.input_tokens == 1400
    assert result.output_tokens == 280
    assert provider.review_calls == 1
    assert provider.verify_calls == 1

    session_factory = create_session_factory(root)
    with session_factory() as session:
        calls = session.query(AiReviewCall).all()
    assert {call.phase for call in calls} == {"primary", "verification"}
    assert all(len(call.prompt_sha256) == 64 for call in calls)


def test_verifier_can_reject_false_positive_without_blocking(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    provider = FakeProvider(
        _response(_finding()),
        VerificationResponse(
            items=[
                VerificationItem(
                    finding_index=0,
                    verdict=VerificationVerdict.REJECTED,
                    confidence=0.91,
                    rationale="The API intentionally allows ZeroDivisionError to propagate.",
                )
            ]
        ),
    )

    result = run_review(
        root,
        provider=provider,
        provider_name="fake",
        model="review-model",
    )

    assert result.status == "passed"
    assert result.findings[0].status == "rejected"
    analytics = review_analytics(root)
    assert analytics["reviews"] == 1
    assert analytics["rejected"] == 1
    assert analytics["verifier_rejection_rate"] == 100.0


def test_invalid_model_evidence_is_discarded_before_verification(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    provider = FakeProvider(_response(_finding(evidence="return safe_divide(a, b)")))

    result = run_review(
        root,
        provider=provider,
        provider_name="fake",
        model="review-model",
    )

    assert result.status == "passed"
    assert result.findings[0].status == "evidence_invalid"
    assert provider.verify_calls == 0
    analytics = review_analytics(root)
    assert analytics["evidence_invalid"] == 1
