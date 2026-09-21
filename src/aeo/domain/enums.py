from enum import StrEnum


class RunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class TaskStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class FinalizationStatus(StrEnum):
    STARTED = "started"
    VALIDATED = "validated"
    COMPLETED = "completed"
    FAILED = "failed"


class GuardSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class GuardCategory(StrEnum):
    QUALITY = "quality"
    SECURITY = "security"
    HYGIENE = "hygiene"
    DEBUG = "debug"
    TESTING = "testing"
    CHANGESET = "changeset"


class GuardStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    BLOCKED = "blocked"


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    RUN_RESUMED = "run_resumed"
    CHECK_STARTED = "check_started"
    CHECK_PASSED = "check_passed"
    CHECK_FAILED = "check_failed"
    GUARD_SCAN_STARTED = "guard_scan_started"
    GUARD_FINDING = "guard_finding"
    GUARD_FIX_STARTED = "guard_fix_started"
    GUARD_FIX_COMPLETED = "guard_fix_completed"
    GUARD_SCAN_COMPLETED = "guard_scan_completed"
    REVIEW_STARTED = "review_started"
    REVIEW_CONTEXT_BUILT = "review_context_built"
    REVIEW_MODEL_CALL = "review_model_call"
    REVIEW_FINDING = "review_finding"
    REVIEW_VERIFICATION = "review_verification"
    REVIEW_COMPLETED = "review_completed"
    RUN_COMPLETED = "run_completed"


class ReviewStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    BLOCKED = "blocked"
    FAILED = "failed"
    DRY_RUN = "dry_run"


class ReviewMode(StrEnum):
    STANDARD = "standard"
    DEEP = "deep"


class ReviewFindingStatus(StrEnum):
    UNVERIFIED = "unverified"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"
    EVIDENCE_INVALID = "evidence_invalid"
