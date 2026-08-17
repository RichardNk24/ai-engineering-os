from pathlib import Path

from aeo.project.configuration import initialize_project
from aeo.tasks.service import get_active_task, start_task


def test_start_task(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    initialize_project(tmp_path)

    task = start_task(tmp_path, "Implement something")

    assert task.title == "Implement something"
    assert task.status == "active"

    active = get_active_task(tmp_path)
    assert active is not None
    assert active.id == task.id
