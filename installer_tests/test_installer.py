import ast
import importlib.util
import tomllib
from pathlib import Path

import pytest

BUNDLE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", BUNDLE / "scripts/install_into.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

CORE = """[project]
name = "ai-engineering-os"
version = "0.5.0"
dependencies = ["fastapi", "sqlalchemy"]
[project.scripts]
aeo = "aeo.cli:app"
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel]
packages = ["src/aeo"]
[tool.ruff]
line-length = 100
"""


def test_metadata_preserves_core_and_is_idempotent():
    first = installer.upgrade_metadata(CORE)
    data = tomllib.loads(first)
    assert data["project"]["name"] == "ai-engineering-os"
    assert data["project"]["version"] == "0.5.0"
    assert data["project"]["dependencies"] == ["fastapi", "sqlalchemy"]
    assert data["project"]["scripts"]["aeo"] == "aeo.cli:app"
    assert data["project"]["scripts"]["aeo7"] == "aeo_workbench.cli:app"
    assert data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/aeo",
        "src/aeo_workbench",
    ]
    assert installer.upgrade_metadata(first) == first


@pytest.mark.parametrize(
    "text",
    [
        CORE.replace("ai-engineering-os", "aeo-workbench"),
        CORE.replace("hatchling.build", "setuptools.build_meta"),
        CORE.replace('packages = ["src/aeo"]', 'packages = ["src/other"]'),
        CORE.replace('aeo = "aeo.cli:app"', 'aeo = "aeo.cli:app"\naeo7 = "other.cli:app"'),
    ],
)
def test_foreign_layout_refused_before_mutation(text):
    with pytest.raises(ValueError):
        installer.upgrade_metadata(text)


def test_cli_mount_preserves_existing_commands():
    source = 'import typer\napp = typer.Typer()\n@app.command()\ndef hello():\n    pass\n\nif __name__ == "__main__":\n    app()\n'
    result = installer.upgrade_cli(source)
    ast.parse(result)
    assert "def hello():" in result
    assert result.index("app.add_typer") < result.index("if __name__")
    assert installer.upgrade_cli(result) == result
