from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from aeo.checks.runner import create_quality_run, run_all_checks
from aeo.db.models import (
    EngineeringRun,
    EngineeringTask,
    ExecutionEnvironment,
    TaskFinalization,
    TaskValidationAttempt,
)
from aeo.db.session import create_session_factory
from aeo.domain.enums import FinalizationStatus, RunStatus, TaskStatus
from aeo.project.configuration import initialize_project
from aeo.tasks.service import finish_task, get_active_task, start_task


def _project(tmp_path: Path, command: str) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    initialize_project(tmp_path)
    config_path = tmp_path / ".aeo" / "project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["checks"] = {"test": command}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


def _python_exit_command(code: int) -> str:
    return f'"{sys.executable}" -c "raise SystemExit({code})"'


def test_failed_validation_keeps_task_active_and_retry_is_measured(tmp_path: Path) -> None:
    root = _project(tmp_path, _python_exit_command(1))
    task = start_task(root, "Retryable validation")

    with pytest.raises(RuntimeError, match="Quality validation failed"):
        finish_task(root)

    active = get_active_task(root)
    assert active is not None
    assert active.id == task.id
    assert active.validation_attempts == 1
    assert active.validation_status == RunStatus.FAILED

    config_path = root / ".aeo" / "project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["checks"] = {"test": _python_exit_command(0)}
    config_path.write_text(json.dumps(config), encoding="utf-8")

    completed = finish_task(root)
    assert completed.status == TaskStatus.COMPLETED
    assert completed.validation_attempts == 2
    assert completed.validation_status == RunStatus.PASSED


def test_finish_reuses_completed_validation_after_partial_failure(tmp_path: Path) -> None:
    root = _project(tmp_path, _python_exit_command(0))
    task = start_task(root, "Crash-safe finalization")
    session_factory = create_session_factory(root)

    run_id = create_quality_run(root)
    with session_factory() as session:
        finalization = TaskFinalization(
            task_id=task.id,
            status=FinalizationStatus.STARTED,
            validation_run_id=run_id,
            attempts=1,
        )
        session.add(finalization)
        session.add(
            TaskValidationAttempt(task_id=task.id, run_id=run_id, attempt_number=1)
        )
        session.commit()

    result = run_all_checks(root, resume_run_id=run_id)
    assert result.status == RunStatus.PASSED

    completed = finish_task(root)
    assert completed.status == TaskStatus.COMPLETED
    assert completed.validation_attempts == 1
    assert completed.validation_run_id == run_id

    with session_factory() as session:
        attempt_count = session.scalar(
            select(func.count())
            .select_from(TaskValidationAttempt)
            .where(TaskValidationAttempt.task_id == task.id)
        )
    assert attempt_count == 1


def test_run_captures_execution_environment(tmp_path: Path) -> None:
    root = _project(tmp_path, _python_exit_command(0))
    result = run_all_checks(root)
    session_factory = create_session_factory(root)

    with session_factory() as session:
        environment = session.scalar(
            select(ExecutionEnvironment).where(ExecutionEnvironment.run_id == result.run_id)
        )

    assert environment is not None
    assert environment.aeo_version == "0.4.0"
    assert environment.python_version
    assert environment.os_name


def test_v02_validation_link_is_backfilled(tmp_path: Path) -> None:
    root = _project(tmp_path, _python_exit_command(0))
    session_factory = create_session_factory(root)

    with session_factory() as session:
        run = EngineeringRun(
            command="check",
            status=RunStatus.PASSED,
            project_root=str(root),
        )
        session.add(run)
        session.flush()
        task = EngineeringTask(
            title="Legacy V0.2 task",
            status=TaskStatus.COMPLETED,
            project_root=str(root),
            validation_run_id=run.id,
        )
        session.add(task)
        session.commit()
        task_id = task.id
        run_id = run.id

    migrated_factory = create_session_factory(root)
    with migrated_factory() as session:
        finalization = session.scalar(
            select(TaskFinalization).where(TaskFinalization.task_id == task_id)
        )
        attempt = session.scalar(
            select(TaskValidationAttempt).where(TaskValidationAttempt.run_id == run_id)
        )

    assert finalization is not None
    assert finalization.status == FinalizationStatus.COMPLETED
    assert attempt is not None
    assert attempt.attempt_number == 1


def test_schema_version_is_persisted(tmp_path: Path) -> None:
    root = _project(tmp_path, _python_exit_command(0))
    session_factory = create_session_factory(root)

    from aeo.db.models import AeoSchemaMetadata

    with session_factory() as session:
        metadata = session.get(AeoSchemaMetadata, 1)

    assert metadata is not None
    assert metadata.schema_version == 4
