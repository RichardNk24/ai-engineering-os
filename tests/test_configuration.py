from pathlib import Path

from aeo.project.configuration import initialize_project, load_project_config


def test_initialize_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    initialized = initialize_project(tmp_path)
    loaded = load_project_config(tmp_path)

    assert initialized == loaded
    assert loaded["version"] == 1
    assert loaded["project"]["name"] == tmp_path.name
