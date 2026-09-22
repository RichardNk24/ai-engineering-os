import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_workbench import prepare, repo, set_gates  # noqa: F401
from typer.testing import CliRunner

from aeo_workbench import engine, storage
from aeo_workbench.api import create_app
from aeo_workbench.cli import app
from aeo_workbench.gitops import git
from aeo_workbench.models import Gate, Settings
from aeo_workbench.pipeline import LegacyBridge, run_pipeline
from aeo_workbench.report import build_report
from aeo_workbench.safety import WorkbenchError


class StubBridge:
    """Unit-test service double; real Guardian/Reviewer integration is tested on the host."""

    fixture = False

    def __init__(self, blocked=None, omitted=0):
        self.calls = []
        self.blocked = blocked
        self.omitted = omitted

    def call(self, stage, wt, cfg, directory):
        self.calls.append(stage)
        return {
            "status": "blocked" if stage == self.blocked else "passed",
            "summary": "Service double",
            "omitted_files": self.omitted,
        }


@pytest.fixture
def configured(repo, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.aeo/\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore local runtime metadata")
    (repo / ".aeo").mkdir()
    (repo / ".aeo" / "project.json").write_text(
        json.dumps(
            {
                "version": 1,
                "project": {"name": "fixture"},
                "checks": {},
                "fixes": {},
                "reviewer": {"policy_files": []},
            }
        )
    )
    cfg = storage.config(repo)
    cfg.require_pipeline = True
    cfg.model = "unit-test-model"
    storage.initialize(repo).write_text(cfg.model_dump_json())
    return repo


def pipeline(root, run, bridge=None):
    return run_pipeline(
        root, run["id"], trust_code=True, allow_remote=True, bridge=bridge or StubBridge()
    )


def test_pipeline_real_gates_and_git_service_doubles(configured):
    run = prepare(configured)
    bridge = StubBridge()
    result = pipeline(configured, run, bridge)
    assert bridge.calls == ["probe", "guardian", "reviewer"]
    assert result["pipeline"]["status"] == "passed"
    assert build_report(configured, run["id"])["ready_to_accept"]
    assert engine.accept(configured, run["id"])["status"] == "accepted"


def test_gates_alone_cannot_bypass_pipeline(configured):
    run = prepare(configured)
    engine.validate(configured, run["id"], trust_code=True)
    with pytest.raises(WorkbenchError, match="complete pipeline"):
        engine.accept(configured, run["id"])
    cfg = storage.config(configured)
    cfg.require_pipeline = False
    storage.initialize(configured).write_text(cfg.model_dump_json())
    with pytest.raises(WorkbenchError, match="complete pipeline"):
        engine.accept(configured, run["id"])


@pytest.mark.parametrize("stage", ["probe", "guardian", "reviewer"])
def test_blocking_stage_fails_closed(configured, stage):
    run = prepare(configured)
    bridge = StubBridge(blocked=stage)
    with pytest.raises(WorkbenchError):
        pipeline(configured, run, bridge)
    assert not build_report(configured, run["id"])["ready_to_accept"]
    assert bridge.calls[-1] == stage
    assert storage.get(configured, run["id"])["status"] == "validation_failed"
    with pytest.raises(WorkbenchError):
        engine.accept(configured, run["id"])


def test_failed_gate_never_invokes_remote_review(configured):
    set_gates(configured, [Gate(name="fail", argv=["{python}", "-c", "raise SystemExit(1)"])])
    run = prepare(configured)
    bridge = StubBridge()
    with pytest.raises(WorkbenchError, match="gate failed"):
        pipeline(configured, run, bridge)
    assert bridge.calls == ["probe"]


@pytest.mark.parametrize("target", ["policy", "settings", "worktree_config", "evidence", "index"])
def test_changed_evidence_blocks_acceptance(configured, target):
    run = pipeline(configured, prepare(configured))
    if target == "policy":
        (configured / ".aeo" / "project.json").write_text('{"version": 2}')
    elif target == "settings":
        cfg = storage.config(configured)
        cfg.review_model = "different-model"
        storage.initialize(configured).write_text(cfg.model_dump_json())
    elif target == "worktree_config":
        (Path(run["worktree"]) / ".aeo" / "project.json").write_text("{}")
    elif target == "index":
        git(Path(run["worktree"]), "reset", "HEAD", "--", "score.py")
    else:
        path = storage.run_dir(configured, run["id"]) / "attempts" / run["pipeline"]["attempt"]
        (path / "evidence.json").write_text("{}")
    assert not build_report(configured, run["id"])["ready_to_accept"]
    with pytest.raises(WorkbenchError):
        engine.accept(configured, run["id"])


def test_stage_mutation_does_not_retain_approval(configured):
    class Mutating(StubBridge):
        def call(self, stage, wt, cfg, directory):
            if stage == "guardian":
                (wt / "score.py").write_text("mutated")
            return super().call(stage, wt, cfg, directory)

    run = prepare(configured)
    bridge = Mutating()
    with pytest.raises(WorkbenchError, match="changed"):
        pipeline(configured, run, bridge)
    assert "reviewer" not in bridge.calls


def test_omitted_files_do_not_authorize_acceptance(configured):
    with pytest.raises(WorkbenchError, match="omitted"):
        pipeline(configured, prepare(configured), StubBridge(omitted=1))


def test_retry_preserves_previous_attempt(configured):
    run = prepare(configured)
    with pytest.raises(WorkbenchError):
        pipeline(configured, run, StubBridge(blocked="reviewer"))
    first = storage.get(configured, run["id"])["pipeline"]["attempt"]
    path = storage.run_dir(configured, run["id"]) / "attempts" / first / "evidence.json"
    evidence = path.read_bytes()
    result = pipeline(configured, run)
    assert result["pipeline"]["attempt"] != first
    assert path.read_bytes() == evidence


def test_fixture_is_never_accepted(configured):
    bridge = StubBridge()
    bridge.fixture = True
    run = pipeline(configured, prepare(configured), bridge)
    with pytest.raises(WorkbenchError, match="fixture"):
        engine.accept(configured, run["id"])


def test_pipeline_requires_both_explicit_flags(configured):
    run = prepare(configured)
    for kwargs in [{}, {"trust_code": True}, {"allow_remote": True}]:
        with pytest.raises(WorkbenchError, match="trust-code"):
            run_pipeline(configured, run["id"], bridge=StubBridge(), **kwargs)
    assert storage.get(configured, run["id"])["status"] == "proposed"


def test_report_cli_and_api(configured, monkeypatch):
    run = pipeline(configured, prepare(configured))
    monkeypatch.chdir(configured)
    response = CliRunner().invoke(app, ["--json", "report", run["id"]])
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["ready_to_accept"]
    token = "unit-test-bearer-token-long-enough"
    client = TestClient(create_app(configured, token))
    path = f"/workbench/runs/{run['id']}/report"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer " + token}).json()["ready_to_accept"]


@pytest.mark.parametrize("model", ["sk-" + "x" * 30, " a-model", "bad\x1bmodel"])
def test_model_validation_on_creation_and_assignment(model):
    with pytest.raises(ValidationError):
        Settings(model=model)
    cfg = Settings()
    with pytest.raises(ValidationError):
        cfg.model = model
    with pytest.raises(ValidationError):
        cfg.review_model = model


def test_historical_key_is_redacted_and_bad_config_not_echoed(configured, monkeypatch):
    secret = "sk-" + "x" * 40
    run = prepare(configured)
    with storage.connection(configured) as db:
        run["model"] = secret
        db.execute("UPDATE runs SET data=? WHERE id=?", (json.dumps(run), run["id"]))
    assert secret not in json.dumps(storage.history(configured))
    assert secret not in json.dumps(storage.get(configured, run["id"]))
    cfg_path = storage.initialize(configured)
    data = json.loads(cfg_path.read_text())
    data["model"] = secret
    cfg_path.write_text(json.dumps(data))
    monkeypatch.chdir(configured)
    result = CliRunner().invoke(app, ["--json", "doctor"])
    assert result.exit_code == 2
    assert secret not in result.output


def test_bridge_invocation_uses_isolated_interpreter_and_scoped_key(
    configured, monkeypatch, tmp_path
):
    seen = []

    def execute(wt, gate, log, *, extra_env=None):
        seen.append((gate.argv, extra_env))
        Path(gate.argv[-1]).write_text('{"status":"passed"}')
        return {"status": "passed", "duration_ms": 1}

    monkeypatch.setattr(engine, "execute_gate", execute)
    bridge = LegacyBridge()
    for stage in ["probe", "guardian", "reviewer"]:
        bridge.call(stage, configured, storage.config(configured), tmp_path)
    assert all(argv[1:4] == ["-I", "-m", "aeo_workbench.legacy_worker"] for argv, _ in seen)
    assert seen[0][1] == seen[1][1] == {}
    assert seen[2][1] == {"OPENAI_API_KEY": "unit-test-placeholder"}


def test_worker_calls_real_contract_with_service_doubles(monkeypatch):
    import sys
    import types
    from dataclasses import dataclass

    from aeo_workbench.legacy_worker import dispatch

    calls = []

    @dataclass
    class Result:
        status: str = "passed"

    def guard(root, **kwargs):
        calls.append(("guardian", root, kwargs))
        return Result()

    def review(root, **kwargs):
        calls.append(("reviewer", root, kwargs))
        return Result()

    for name, function, attribute in [
        ("aeo.guardian.service", guard, "run_guard"),
        ("aeo.reviewer.service", review, "run_review"),
    ]:
        module = types.ModuleType(name)
        setattr(module, attribute, function)
        monkeypatch.setitem(sys.modules, name, module)
    request = {"stage": "probe"}
    assert dispatch(request)["status"] == "passed"
    assert not calls
    request.update(
        worktree="/fixture",
        model="test-model",
        max_context_chars=1000,
        max_files=2,
        max_output_tokens=100,
    )
    for stage in ["guardian", "reviewer"]:
        request["stage"] = stage
        assert dispatch(request)["status"] == "passed"
    assert calls[0][2] == {"staged": True, "fix": False}
    assert calls[1][2]["staged"] and calls[1][2]["verify"]
    assert calls[1][2]["verification_model"] == "test-model"


def test_pipeline_offline_demo_is_honest_and_blocked():
    from aeo_workbench.demo import run_demo

    root, run = run_demo(full_pipeline=True)
    report = build_report(root, run["id"])
    assert report["pipeline"]["fixture"] is True
    assert not report["ready_to_accept"]
    assert report["gates"][0]["returncode"] == 0
    engine.discard(root, run["id"])


def test_report_respects_narrow_terminal_and_literal_output(configured):
    import io

    from rich.console import Console

    from aeo_workbench.ui import THEME, UI

    run = pipeline(configured, prepare(configured))
    report = build_report(configured, run["id"])
    report["pipeline"]["stages"][-1]["summary"] = "[bold]literal[/bold]\x1b]52;bad\x07"
    stream = io.StringIO()
    UI(console=Console(file=stream, width=48, theme=THEME, no_color=True)).report(report)
    assert "\x1b" not in stream.getvalue() and "\x07" not in stream.getvalue()
    assert all(len(line) <= 48 for line in stream.getvalue().splitlines())
