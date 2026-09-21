from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class EvidenceSource(StrEnum):
    CURRENT_FILE = "current_file"
    DIFF = "diff"


class ReviewCategory(StrEnum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    DATA_INTEGRITY = "data_integrity"
    CONCURRENCY = "concurrency"
    API_CONTRACT = "api_contract"
    PERFORMANCE = "performance"
    TESTING = "testing"
    MAINTAINABILITY = "maintainability"
    ARCHITECTURE = "architecture"


class ReviewFindingDraft(BaseModel):
    severity: ReviewSeverity
    category: ReviewCategory
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=5, max_length=2000)
    file_path: str = Field(min_length=1, max_length=500)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    evidence_source: EvidenceSource = EvidenceSource.CURRENT_FILE
    evidence: str = Field(min_length=1, max_length=1200)
    recommendation: str = Field(min_length=3, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)


class ReviewResponse(BaseModel):
    summary: str = Field(min_length=1, max_length=3000)
    risk_assessment: str = Field(min_length=1, max_length=1000)
    findings: list[ReviewFindingDraft] = Field(default_factory=list, max_length=20)
    test_recommendations: list[str] = Field(default_factory=list, max_length=12)
    uncertainties: list[str] = Field(default_factory=list, max_length=12)


class VerificationVerdict(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


class VerificationItem(BaseModel):
    finding_index: int = Field(ge=0)
    verdict: VerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=1200)


class VerificationResponse(BaseModel):
    items: list[VerificationItem] = Field(default_factory=list, max_length=20)
