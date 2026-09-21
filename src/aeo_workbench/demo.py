"""Offline demonstration using real Git operations and a deterministic fixture provider."""

import tempfile
from pathlib import Path

from . import engine, storage
from .gitops import git
from .models import Edit, Gate, Proposal, Settings, Usage


class DemoProvider:
    def propose(self, task, context, settings):
        return Proposal(
            summary="Handle an empty score collection explicitly.",
            steps=["Return None when no scores exist.", "Cover empty and populated inputs."],
            risks=["Offline fixture: this is not an AI-generated response."],
            edits=[
                Edit(
                    path="score.py",
                    operation="write",
                    content=(
                        "def average(values):\n"
                        "    if not values:\n        return None\n"
                        "    return sum(values) / len(values)\n"
                    ),
                ),
                Edit(
                    path="test_score.py",
                    operation="write",
                    content=(
                        "import unittest\nfrom score import average\n\n"
                        "class ScoreTests(unittest.TestCase):\n"
                        "    def test_empty(self):\n        self.assertIsNone(average([]))\n"
                        "    def test_average(self):\n        self.assertEqual(average([2, 4]), 3)\n"
                    ),
                ),
            ],
        ), Usage()


def run_demo() -> tuple[Path, dict]:
    root = Path(tempfile.mkdtemp(prefix="aeo-demo-"))
    git(root, "init")
    git(root, "config", "user.email", "demo@localhost")
    git(root, "config", "user.name", "AEO Demo")
    (root / "score.py").write_text("def average(values):\n    return sum(values) / len(values)\n")
    (root / ".gitignore").write_text("__pycache__/\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "Demo baseline")
    settings = Settings(gates=[Gate(name="unit tests", argv=["{python}", "-m", "unittest", "-v"])])
    storage.initialize(root).write_text(settings.model_dump_json(indent=2))
    run = engine.prepare(
        root, "Handle empty scores", [], ["score.py", "test_score.py"], provider=DemoProvider()
    )
    run = engine.validate(root, run["id"], trust_code=True)
    return root, run
