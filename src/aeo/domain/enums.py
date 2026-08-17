from enum import StrEnum


class RunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class TaskStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    CHECK_STARTED = "check_started"
    CHECK_PASSED = "check_passed"
    CHECK_FAILED = "check_failed"
    RUN_COMPLETED = "run_completed"
