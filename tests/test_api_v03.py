from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from aeo import __version__
from aeo.api.main import app
from aeo.project.configuration import initialize_project
from aeo.tasks.service import finish_task, start_task


def test_v03_api_exposes_tasks_runs_and_stats(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='api-demo'\n",
        encoding="utf-8",
    )

    initialize_project(tmp_path)

    config_path = tmp_path / ".aeo" / "project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    config["checks"] = {
        "test": f'"{sys.executable}" -c "raise SystemExit(0)"',
    }

    config_path.write_text(
        json.dumps(config),
        encoding="utf-8",
    )

    start_task(tmp_path, "API telemetry")
    finish_task(tmp_path)

    monkeypatch.chdir(tmp_path)

    client = TestClient(app)

    health = client.get("/health")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["version"] == __version__

    tasks = client.get("/tasks")

    assert tasks.status_code == 200
    assert len(tasks.json()) == 1

    task = tasks.json()[0]

    assert task["title"] == "API telemetry"
    assert task["status"] == "completed"
    assert task["validation_attempts"] == 1
    assert task["validation_status"] == "passed"

    runs = client.get("/runs")

    assert runs.status_code == 200
    assert len(runs.json()) == 1

    run = runs.json()[0]

    assert run["command"] == "check"
    assert run["status"] == "passed"
    assert run["environment"] is not None
    assert run["environment"]["aeo_version"] == __version__

    stats = client.get("/stats")

    assert stats.status_code == 200

    payload = stats.json()

    assert payload["runs"]["total"] == 1
    assert payload["runs"]["passed"] == 1
    assert payload["runs"]["failed"] == 0
    assert payload["runs"]["success_rate"] == 100.0

    assert payload["tasks"]["total"] == 1
    assert payload["tasks"]["completed"] == 1
    assert payload["tasks"]["first_pass_success_rate"] == 100.0
    assert payload["tasks"]["retry_rate"] == 0.0
    assert payload["tasks"]["average_validation_attempts"] == 1.0