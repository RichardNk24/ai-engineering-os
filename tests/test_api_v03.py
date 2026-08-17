from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from aeo.api.main import app
from aeo.project.configuration import initialize_project
from aeo.tasks.service import finish_task, start_task


def test_v03_api_exposes_tasks_runs_and_stats(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='api-demo'\n", encoding="utf-8")
    initialize_project(tmp_path)
    config_path = tmp_path / ".aeo" / "project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["checks"] = {"test": f'"{sys.executable}" -c "raise SystemExit(0)"'}
    config_path.write_text(json.dumps(config), encoding="utf-8")

    start_task(tmp_path, "API telemetry")
    finish_task(tmp_path)
    monkeypatch.chdir(tmp_path)

    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["version"] == "0.3.0"

    tasks = client.get("/tasks")
    assert tasks.status_code == 200
    assert len(tasks.json()) == 1

    runs = client.get("/runs")
    assert runs.status_code == 200
    assert len(runs.json()) == 1
    assert runs.json()[0]["environment"]["aeo_version"] == "0.3.0"

    stats = client.get("/stats")
    assert stats.status_code == 200
    assert stats.json()["tasks"]["first_pass_success_rate"] == 100.0
