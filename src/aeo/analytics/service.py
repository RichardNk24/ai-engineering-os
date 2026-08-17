from __future__ import annotations

import math
from pathlib import Path

from sqlalchemy import func, select

from aeo.db.models import EngineeringEvent, EngineeringRun, EngineeringTask, TaskValidationAttempt
from aeo.db.session import create_session_factory
from aeo.domain.enums import EventType, RunStatus, TaskStatus
from aeo.guardian.service import guard_analytics


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 2)


def _completed_validation_attempts(
    session,
    completed_tasks: list[EngineeringTask],
) -> dict[str, list[EngineeringRun]]:
    """
    Return ordered validation runs for completed tasks only.

    Outcome metrics intentionally exclude active/cancelled tasks because their
    validation lifecycle is not final yet. Legacy completed tasks that predate
    TaskValidationAttempt are recovered through validation_run_id.
    """
    result: dict[str, list[EngineeringRun]] = {}

    for task in completed_tasks:
        attempts = session.scalars(
            select(TaskValidationAttempt)
            .where(TaskValidationAttempt.task_id == task.id)
            .order_by(TaskValidationAttempt.attempt_number)
        ).all()

        runs: list[EngineeringRun] = []
        for attempt in attempts:
            run = session.get(EngineeringRun, attempt.run_id)
            if run is not None:
                runs.append(run)

        # Backwards compatibility for v0.2/v0.3 tasks.
        if not runs and task.validation_run_id:
            legacy_run = session.get(EngineeringRun, task.validation_run_id)
            if legacy_run is not None:
                runs.append(legacy_run)

        if runs:
            result[task.id] = runs

    return result


def engineering_analytics(root: Path) -> dict[str, object]:
    session_factory = create_session_factory(root)
    with session_factory() as session:
        run_total = session.scalar(select(func.count()).select_from(EngineeringRun)) or 0
        run_passed = session.scalar(
            select(func.count())
            .select_from(EngineeringRun)
            .where(EngineeringRun.status == RunStatus.PASSED)
        ) or 0
        run_failed = session.scalar(
            select(func.count())
            .select_from(EngineeringRun)
            .where(EngineeringRun.status == RunStatus.FAILED)
        ) or 0
        run_durations = [
            float(value)
            for value in session.scalars(
                select(EngineeringRun.duration_ms).where(EngineeringRun.duration_ms.is_not(None))
            ).all()
            if value is not None
        ]

        task_total = session.scalar(select(func.count()).select_from(EngineeringTask)) or 0
        completed_tasks = list(
            session.scalars(
                select(EngineeringTask).where(
                    EngineeringTask.status == TaskStatus.COMPLETED
                )
            ).all()
        )
        task_completed = len(completed_tasks)
        task_active = session.scalar(
            select(func.count())
            .select_from(EngineeringTask)
            .where(EngineeringTask.status == TaskStatus.ACTIVE)
        ) or 0
        task_durations = [
            float(task.duration_ms)
            for task in completed_tasks
            if task.duration_ms is not None
        ]

        completed_validation_runs = _completed_validation_attempts(
            session,
            completed_tasks,
        )

        validated_count = len(completed_validation_runs)
        first_pass_tasks = 0
        retried_tasks = 0
        total_attempts = 0

        for runs in completed_validation_runs.values():
            total_attempts += len(runs)
            if runs[0].status == RunStatus.PASSED:
                first_pass_tasks += 1
            if len(runs) > 1:
                retried_tasks += 1

        gate_rows = session.execute(
            select(
                EngineeringEvent.stage,
                EngineeringEvent.event_type,
                func.count(EngineeringEvent.id),
                func.avg(EngineeringEvent.duration_ms),
            )
            .where(
                EngineeringEvent.event_type.in_(
                    [EventType.CHECK_PASSED, EventType.CHECK_FAILED]
                )
            )
            .group_by(EngineeringEvent.stage, EngineeringEvent.event_type)
        ).all()

    gates: dict[str, dict[str, float | int]] = {}
    for stage, event_type, count, avg_duration in gate_rows:
        if stage is None:
            continue
        gate = gates.setdefault(
            stage,
            {
                "passed": 0,
                "failed": 0,
                "samples": 0,
                "pass_rate": 0.0,
                "average_duration_ms": 0.0,
            },
        )
        key = "passed" if event_type == EventType.CHECK_PASSED else "failed"
        gate[key] = int(count)
        previous_samples = int(gate["samples"])
        new_samples = previous_samples + int(count)
        previous_average = float(gate["average_duration_ms"])
        weighted = previous_average * previous_samples + float(avg_duration or 0.0) * int(count)
        gate["samples"] = new_samples
        gate["average_duration_ms"] = round(weighted / new_samples, 2) if new_samples else 0.0

    for gate in gates.values():
        samples = int(gate["samples"])
        gate["pass_rate"] = round(int(gate["passed"]) / samples * 100, 2) if samples else 0.0

    return {
        "runs": {
            "total": run_total,
            "passed": run_passed,
            "failed": run_failed,
            "success_rate": round(run_passed / run_total * 100, 2) if run_total else 0.0,
            "median_duration_ms": _percentile(run_durations, 0.50),
            "p95_duration_ms": _percentile(run_durations, 0.95),
        },
        "tasks": {
            "total": task_total,
            "completed": task_completed,
            "active": task_active,
            "validated": validated_count,
            "median_duration_ms": _percentile(task_durations, 0.50),
            "p95_duration_ms": _percentile(task_durations, 0.95),
            "first_pass_success_rate": (
                round(first_pass_tasks / validated_count * 100, 2) if validated_count else 0.0
            ),
            "retry_rate": (
                round(retried_tasks / validated_count * 100, 2) if validated_count else 0.0
            ),
            "average_validation_attempts": (
                round(total_attempts / validated_count, 2) if validated_count else 0.0
            ),
        },
        "gates": gates,
        "guardian": guard_analytics(root),
    }
