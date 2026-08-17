import subprocess
from pathlib import Path

from aeo.guardian.service import guard_analytics, run_guard
from aeo.project.configuration import initialize_project


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_guard_blocks_debug_statement_and_persists_analytics(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    initialize_project(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "AEO Test")
    source = tmp_path / "app.py"
    source.write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    source.write_text("x = 1\nbreakpoint()\n", encoding="utf-8")

    result = run_guard(tmp_path)
    assert result.status == "blocked"
    assert any(f.rule_id == "debug.python-breakpoint" for f in result.findings)

    metrics = guard_analytics(tmp_path)
    assert metrics["scans"] == 1
    assert metrics["blocked"] == 1
