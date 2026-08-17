from __future__ import annotations

import json
import sys
from pathlib import Path

from aeo.analytics.service import engineering_analytics
from aeo.db.models import EngineeringRun, EngineeringTask, TaskValidationAttempt
from aeo.db.session import create_session_factory
from aeo.domain.enums import RunStatus, TaskStatus
from aeo.project.configuration import initialize_project
from aeo.tasks.service import finish_task, start_task


def test_analytics_reports_first_pass_success(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    initialize_project(tmp_path)

    config_path = tmp_path / ".aeo" / "project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["checks"] = {"test": f'"{sys.executable}" -c "raise SystemExit(0)"'}
    config_path.write_text(json.dumps(config), encoding="utf-8")

    start_task(tmp_path, "First pass")
    finish_task(tmp_path)

    metrics = engineering_analytics(tmp_path)
    tasks = metrics["tasks"]
    assert isinstance(tasks, dict)
    assert tasks["validated"] == 1
    assert tasks["first_pass_success_rate"] == 100.0
    assert tasks["retry_rate"] == 0.0
    assert tasks["average_validation_attempts"] == 1.0


def _add_completed_task_with_attempts(
    root: Path,
    *,
    title: str,
    statuses: list[RunStatus],
) -> None:
    session_factory = create_session_factory(root)
    with session_factory() as session:
        task = EngineeringTask(
            title=title,
            status=TaskStatus.COMPLETED,
            project_root=str(root),
            duration_ms=1000.0,
        )
        session.add(task)
        session.flush()

        final_run_id: str | None = None
        for attempt_number, status in enumerate(statuses, start=1):
            run = EngineeringRun(
                command="check",
                status=status,
                project_root=str(root),
                duration_ms=100.0,
            )
            session.add(run)
            session.flush()

            session.add(
                TaskValidationAttempt(
                    task_id=task.id,
                    run_id=run.id,
                    attempt_number=attempt_number,
                )
            )
            final_run_id = run.id

        task.validation_run_id = final_run_id
        session.commit()


def test_analytics_retry_integrity_for_completed_tasks(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    initialize_project(tmp_path)

    _add_completed_task_with_attempts(
        tmp_path,
        title="first pass",
        statuses=[RunStatus.PASSED],
    )
    _add_completed_task_with_attempts(
        tmp_path,
        title="one retry",
        statuses=[RunStatus.FAILED, RunStatus.PASSED],
    )
    _add_completed_task_with_attempts(
        tmp_path,
        title="two retries",
        statuses=[RunStatus.FAILED, RunStatus.FAILED, RunStatus.PASSED],
    )

    metrics = engineering_analytics(tmp_path)
    tasks = metrics["tasks"]
    assert isinstance(tasks, dict)

    assert tasks["completed"] == 3
    assert tasks["validated"] == 3
    assert tasks["first_pass_success_rate"] == 33.33
    assert tasks["retry_rate"] == 66.67
    assert tasks["average_validation_attempts"] == 2.0


def test_active_failed_attempt_does_not_distort_outcome_rates(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    initialize_project(tmp_path)

    _add_completed_task_with_attempts(
        tmp_path,
        title="completed",
        statuses=[RunStatus.PASSED],
    )

    session_factory = create_session_factory(tmp_path)
    with session_factory() as session:
        active_task = EngineeringTask(
            title="active",
            status=TaskStatus.ACTIVE,
            project_root=str(tmp_path),
        )
        session.add(active_task)
        session.flush()

        failed_run = EngineeringRun(
            command="check",
            status=RunStatus.FAILED,
            project_root=str(tmp_path),
            duration_ms=100.0,
        )
        session.add(failed_run)
        session.flush()

        session.add(
            TaskValidationAttempt(
                task_id=active_task.id,
                run_id=failed_run.id,
                attempt_number=1,
            )
        )
        session.commit()

    metrics = engineering_analytics(tmp_path)
    tasks = metrics["tasks"]
    assert isinstance(tasks, dict)

    assert tasks["total"] == 2
    assert tasks["completed"] == 1
    assert tasks["active"] == 1
    assert tasks["validated"] == 1
    assert tasks["first_pass_success_rate"] == 100.0
    assert tasks["retry_rate"] == 0.0
    assert tasks["average_validation_attempts"] == 1.0
