from pathlib import Path

from aeo.project.detection import detect_project


def test_detect_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["fastapi", "ruff", "mypy", "pytest"]
""",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")

    detected = detect_project(tmp_path)

    assert "python" in detected.languages
    assert "fastapi" in detected.frameworks
    assert "uv" in detected.package_managers
    assert detected.checks["lint"] == "ruff check ."
    assert detected.checks["types"] == "mypy ."
    assert detected.checks["test"] == "pytest"
