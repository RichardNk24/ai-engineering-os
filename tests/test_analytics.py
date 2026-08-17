from __future__ import annotations

import json
import sys
from pathlib import Path

from aeo.analytics.service import engineering_analytics
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
