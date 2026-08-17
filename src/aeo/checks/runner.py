from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from aeo.domain.enums import EventType, RunStatus
from aeo.project.configuration import load_project_config
from aeo.telemetry.service import RunRecorder


@dataclass(slots=True)
class CheckResult:
    name: str
    command: str
    return_code: int
    duration_ms: float
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.return_code == 0

    @property
    def output(self) -> str:
        return (self.stdout or self.stderr).strip()


@dataclass(slots=True)
class QualityRunResult:
    run_id: str
    status: RunStatus
    checks: list[CheckResult]


def execute_check(root: Path, name: str, command: str) -> CheckResult:
    started = perf_counter()
    result = subprocess.run(
        command,
        cwd=root,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    duration_ms = (perf_counter() - started) * 1000

    return CheckResult(
        name=name,
        command=command,
        return_code=result.returncode,
        duration_ms=duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def run_all_checks(root: Path, *, resume_run_id: str | None = None) -> QualityRunResult:
    config = load_project_config(root)
    checks: dict[str, str] = config.get("checks", {})

    recorder = RunRecorder(root, command="check")
    run = recorder.resume(resume_run_id) if resume_run_id else recorder.start()

    results: list[CheckResult] = []

    for name, command in checks.items():
        recorder.event(EventType.CHECK_STARTED, stage=name, message=command)

        result = execute_check(root, name, command)
        results.append(result)

        recorder.event(
            EventType.CHECK_PASSED if result.passed else EventType.CHECK_FAILED,
            stage=name,
            message=result.output[-4000:],
            duration_ms=result.duration_ms,
        )

    final_status = (
        RunStatus.PASSED
        if all(result.passed for result in results)
        else RunStatus.FAILED
    )
    recorder.complete(final_status)

    return QualityRunResult(run_id=run.id, status=final_status, checks=results)


def create_quality_run(root: Path) -> str:
    """Persist a resumable quality run before executing any subprocess."""
    recorder = RunRecorder(root, command="check")
    return recorder.start().id
