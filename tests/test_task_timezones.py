from datetime import UTC, datetime

from aeo.tasks.service import _as_utc


def test_as_utc_adds_utc_to_naive_datetime() -> None:
    value = datetime(2026, 8, 17, 10, 0, 0)  # noqa: DTZ001 - intentionally naive
    normalized = _as_utc(value)

    assert normalized.tzinfo is UTC


def test_as_utc_preserves_aware_datetime() -> None:
    value = datetime(2026, 8, 17, 10, 0, 0, tzinfo=UTC)
    normalized = _as_utc(value)

    assert normalized == value
    assert normalized.tzinfo is UTC
