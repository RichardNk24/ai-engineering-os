import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rich.console import Console
from typer.testing import CliRunner

from aeo_workbench import engine, storage
from aeo_workbench.api import create_app
from aeo_workbench.cli import app
from aeo_workbench.demo import DemoProvider
from aeo_workbench.gitops import git, head
from aeo_workbench.models import Edit, Gate, Proposal, Settings, Usage
from aeo_workbench.safety import WorkbenchError, display_safe, safe_path
from aeo_workbench.ui import THEME, UI


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@localhost")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "score.py").write_text(
        "def average(values):\n    return sum(values) / len(values)\n"
    )
    (tmp_path / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "baseline")
    storage.initialize(tmp_path)
    set_gates(tmp_path, [Gate(name="tests", argv=["{python}", "-m", "unittest", "-v"])])
    return tmp_path


def set_gates(root, gates):
    cfg = storage.config(root)
    cfg.gates = gates
    storage.initialize(root).write_text(cfg.model_dump_json())


def prepare(repo):
    return engine.prepare(
        repo, "Handle empty scores", [], ["score.py", "test_score.py"], provider=DemoProvider()
    )


def test_real_lifecycle_source_unchanged_until_accept(repo):
    baseline = (repo / "score.py").read_bytes()
    initial_head = head(repo)
    run = prepare(repo)
    assert run["status"] == "proposed"
    assert (repo / "score.py").read_bytes() == baseline
    assert not (repo / "test_score.py").exists()
    assert head(repo) == initial_head
    run = engine.validate(repo, run["id"], trust_code=True)
    assert run["status"] == "validated"
    assert run["gates"][0]["returncode"] == 0
    assert engine.accept(repo, run["id"])["status"] == "accepted"
    assert "return None" in (repo / "score.py").read_text()
    assert (repo / "test_score.py").exists()
    assert head(repo) == initial_head  # no automatic commit
    assert git(repo, "diff", "--cached", "--name-only") == "score.py\ntest_score.py"
    assert storage.events(repo, run["id"])[-1]["state"] == "accepted"
    with pytest.raises(WorkbenchError):
        engine.accept(repo, run["id"])


def test_dry_run_never_calls_provider(repo):
    class Never:
        def propose(self, *args):
            pytest.fail("provider called")

    run = engine.prepare(repo, "task", [], ["score.py"], provider=Never(), dry_run=True)
    assert run["status"] == "dry_run"
    assert not Path(run["worktree"]).exists()


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/tmp/escape",
        "C:/escape",
        "a\\b",
        ".git/config",
        ".env",
        "a/../b",
        "a//b",
        "a.key",
        "file\nname",
    ],
)
def test_unsafe_paths(repo, path):
    with pytest.raises(WorkbenchError):
        safe_path(repo, path)


def test_symlink_refused(repo, tmp_path):
    path = repo / "link"
    try:
        path.symlink_to(repo / "score.py")
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(WorkbenchError):
        safe_path(repo, "link")


def test_dirty_repository_refused(repo):
    (repo / "local.txt").write_text("uncommitted")
    with pytest.raises(WorkbenchError, match="Commit or stash"):
        prepare(repo)


def test_secret_preflight(repo):
    (repo / "score.py").write_text('API_KEY = "' + "sk-" + "x" * 35 + '"\n')
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture")
    with pytest.raises(WorkbenchError, match="credential"):
        prepare(repo)
    assert storage.history(repo) == []


def test_out_of_scope_model_edit_is_rejected(repo):
    class Rogue:
        def propose(self, *args):
            return Proposal(
                summary="bad",
                steps=[],
                risks=[],
                edits=[Edit(path="outside.py", operation="write", content="oops")],
            ), Usage()

    with pytest.raises(WorkbenchError, match="scope"):
        engine.prepare(repo, "task", [], ["score.py"], provider=Rogue())
    run = storage.history(repo)[0]
    assert run["status"] == "failed"
    assert not Path(run["worktree"]).exists()
    assert not (storage.state_dir(repo) / "operation.lock").exists()


@pytest.mark.parametrize("kind", ["failed", "timeout", "unavailable"])
def test_gate_failure_cannot_be_accepted(repo, kind):
    args = {
        "failed": ["{python}", "-c", "raise SystemExit(3)"],
        "timeout": ["{python}", "-c", "import time; time.sleep(5)"],
        "unavailable": ["aeo-command-that-does-not-exist"],
    }[kind]
    set_gates(repo, [Gate(name="gate", argv=args, timeout_seconds=1)])
    run = prepare(repo)
    result = engine.validate(repo, run["id"], trust_code=True)
    assert result["status"] == "validation_failed"
    assert result["gates"][0]["status"] == kind
    with pytest.raises(WorkbenchError):
        engine.accept(repo, run["id"])


def test_no_gates_not_pass(repo):
    set_gates(repo, [])
    run = prepare(repo)
    with pytest.raises(WorkbenchError, match="No gates"):
        engine.validate(repo, run["id"], trust_code=True)
    with pytest.raises(WorkbenchError):
        engine.accept(repo, run["id"])


def test_validation_needs_explicit_trust(repo):
    run = prepare(repo)
    with pytest.raises(WorkbenchError, match="trust-code"):
        engine.validate(repo, run["id"])


@pytest.mark.parametrize("target", ["patch", "worktree", "extra", "head", "config"])
def test_stale_acceptance_blocked(repo, target):
    run = prepare(repo)
    engine.validate(repo, run["id"], trust_code=True)
    if target == "patch":
        (storage.run_dir(repo, run["id"]) / "change.patch").write_text("tampered")
    elif target == "worktree":
        (Path(run["worktree"]) / "score.py").write_text("tampered")
    elif target == "extra":
        (Path(run["worktree"]) / "extra.txt").write_text("extra")
    elif target == "head":
        git(repo, "commit", "--allow-empty", "-m", "moved")
    else:
        set_gates(repo, [])
    with pytest.raises(WorkbenchError):
        engine.accept(repo, run["id"])
    assert not (repo / "test_score.py").exists()


def test_tests_that_modify_proposal_invalidate_evidence(repo):
    set_gates(
        repo,
        [
            Gate(
                name="mutating",
                argv=[
                    "{python}",
                    "-c",
                    "from pathlib import Path; Path('score.py').write_text('changed')",
                ],
            )
        ],
    )
    run = prepare(repo)
    with pytest.raises(WorkbenchError, match="changed"):
        engine.validate(repo, run["id"], trust_code=True)
    assert storage.get(repo, run["id"])["status"] == "validation_failed"


def test_lock_blocks_parallel_mutation(repo):
    with storage.lock(repo), pytest.raises(WorkbenchError, match="lock"):
        prepare(repo)
    assert prepare(repo)["status"] == "proposed"


def test_discard_retains_evidence(repo):
    run = prepare(repo)
    engine.discard(repo, run["id"])
    assert not Path(run["worktree"]).exists()
    assert (storage.run_dir(repo, run["id"]) / "change.patch").exists()
    assert storage.get(repo, run["id"])["status"] == "discarded"


def test_api_auth_and_read_only(repo):
    run = prepare(repo)
    token = "test-token-with-at-least-24-characters"
    client = TestClient(create_app(repo, token))
    assert client.get("/workbench/runs").status_code == 401
    assert (
        client.get("/workbench/runs", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    headers = {"Authorization": "Bearer " + token}
    assert client.get("/workbench/runs", headers=headers).json()["runs"][0]["id"] == run["id"]
    assert client.get(f"/workbench/runs/{run['id']}/events", headers=headers).status_code == 200
    assert client.get("/workbench/runs/aaaaaaaaaaaa", headers=headers).status_code == 404
    assert client.get("/workbench/runs?limit=9999", headers=headers).status_code == 422
    assert client.post("/workbench/runs", headers=headers).status_code == 405
    assert client.get("/openapi.json").status_code == 404


def test_json_cli_is_parseable_and_noninteractive(repo, monkeypatch):
    monkeypatch.chdir(repo)
    runner = CliRunner()
    result = runner.invoke(app, ["--json", "feature", "task", "--write", "score.py", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "dry_run"
    result = runner.invoke(app, ["--json", "accept", "aaaaaaaaaaaa"])
    assert result.exit_code == 2
    assert "error" in json.loads(result.output)


def test_terminal_injection_and_narrow_width(repo):
    run = prepare(repo)
    run["error"] = "[bold red]literal[/bold red]\x1b]52;c;evil\x07"
    stream = io.StringIO()
    console = Console(file=stream, width=48, theme=THEME, no_color=True)
    UI(console=console).run(run)
    output = stream.getvalue()
    assert "\x1b" not in output and "\x07" not in output
    assert "literal" in output
    assert all(len(line) <= 48 for line in output.splitlines())
    assert display_safe("hello\x1b[2J") == "hello[2J"


def test_telemetry_contains_hashes_not_source_or_task(repo):
    run = prepare(repo)
    persisted = json.dumps(storage.get(repo, run["id"]))
    assert "Handle empty scores" not in persisted
    assert "def average" not in persisted
    assert run["usage"]["estimated_cost_usd"] is None


def test_context_budget_is_enforced(repo):
    (repo / "score.py").write_text("#" * 200)
    git(repo, "add", ".")
    git(repo, "commit", "-m", "larger fixture")
    with pytest.raises(WorkbenchError, match="max_file_bytes"):
        engine.context_packet(repo, [], ["score.py"], Settings(max_file_bytes=100))


def test_duplicate_scope_refused(repo):
    with pytest.raises(WorkbenchError, match="unique"):
        engine.context_packet(repo, [], ["score.py", "score.py"], Settings())


@pytest.mark.parametrize("path", ["NUL", "foo/CON.txt", "file.", "file ", "a*b"])
def test_windows_aliases_are_refused(repo, path):
    with pytest.raises(WorkbenchError, match="portable"):
        safe_path(repo, path)


def test_delete_edit_and_accept(repo):
    class Deleter:
        def propose(self, *args):
            return Proposal(
                summary="Remove unused file",
                steps=[],
                risks=[],
                edits=[Edit(path="score.py", operation="delete", content="")],
            ), Usage()

    set_gates(
        repo,
        [
            Gate(
                name="check deletion",
                argv=[
                    "{python}",
                    "-c",
                    "from pathlib import Path; assert not Path('score.py').exists()",
                ],
            )
        ],
    )
    run = engine.prepare(repo, "Remove unused score module", [], ["score.py"], provider=Deleter())
    engine.validate(repo, run["id"], trust_code=True)
    engine.accept(repo, run["id"])
    assert not (repo / "score.py").exists()


def test_provider_interruption_persists_state_and_releases_lock(repo):
    class Interrupted:
        def propose(self, *args):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        engine.prepare(repo, "task", [], ["score.py"], provider=Interrupted())
    assert storage.history(repo)[0]["status"] == "interrupted"
    assert not (storage.state_dir(repo) / "operation.lock").exists()


def test_gate_cannot_see_api_key(repo, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-secret")
    set_gates(
        repo,
        [
            Gate(
                name="env",
                argv=["{python}", "-c", "import os; assert 'OPENAI_API_KEY' not in os.environ"],
            )
        ],
    )
    run = prepare(repo)
    assert engine.validate(repo, run["id"], trust_code=True)["status"] == "validated"


def test_mounted_cli(repo, monkeypatch):
    import typer

    monkeypatch.chdir(repo)
    legacy = typer.Typer()
    legacy.add_typer(app, name="workbench")
    response = CliRunner().invoke(legacy, ["workbench", "--json", "doctor"])
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["root"] == str(repo)
