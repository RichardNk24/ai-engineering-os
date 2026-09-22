"""Sequential evidence orchestration. No automatic source acceptance or model retry."""

import json
import os
import uuid
from pathlib import Path

from . import engine, storage
from .gitops import git, head, repo_root, tracked_files
from .models import Gate, Settings
from .safety import WorkbenchError, digest, inspect_text, redact, safe_path


def fingerprint(value) -> str:
    return digest(json.dumps(value, sort_keys=True).encode())


def project_config(root: Path) -> bytes:
    path = root / ".aeo" / "project.json"
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        raise WorkbenchError("V0.5 project configuration missing or unsafe: run aeo init first.")
    raw = path.read_bytes()
    if len(raw) > 256_000:
        raise WorkbenchError("V0.5 configuration exceeds the bridge limit.")
    inspect_text(raw.decode("utf-8-sig"))
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise WorkbenchError("V0.5 project configuration must be an object.")
    return raw


def policy_hash(root: Path, cfg: Settings, raw: bytes) -> str:
    return fingerprint({"settings": cfg.model_dump(), "project_config": digest(raw)})


def prepare_bridge(root: Path, run: dict, raw: bytes) -> Path:
    wt = Path(run["worktree"])
    metadata = wt / ".aeo"
    if metadata.is_symlink() or git(wt, "ls-files", "--", ".aeo"):
        raise WorkbenchError("The bridge requires an untracked, ignored .aeo directory.")
    # Require a repository rule; do not edit the shared Git exclude file behind the user's back.
    try:
        ignored = git(wt, "check-ignore", "--", ".aeo/project.json", ".aeo/aeo.db")
    except WorkbenchError as exc:
        raise WorkbenchError("Commit a .aeo/ ignore rule before using the pipeline.") from exc
    if len(ignored.splitlines()) != 2:
        raise WorkbenchError("Commit a .aeo/ ignore rule before using the pipeline.")
    config_path = metadata / "project.json"
    if config_path.is_symlink():
        raise WorkbenchError("Unsafe worktree configuration path.")
    data = json.loads(raw.decode("utf-8-sig"))
    for name in data.get("reviewer", {}).get("policy_files", []):
        path = safe_path(wt, name)
        if name not in tracked_files(wt) or not path.is_file() or path.stat().st_size > 256_000:
            raise WorkbenchError("Reviewer policy file is unavailable or oversized.")
        inspect_text(path.read_text(encoding="utf-8"))
    metadata.mkdir(exist_ok=True)
    config_path.write_bytes(raw)
    return config_path


class LegacyBridge:
    """One short-lived interpreter per stage; installed core remains the trusted checker."""

    fixture = False

    def call(self, stage: str, wt: Path, cfg: Settings, directory: Path) -> dict:
        request = {
            "stage": stage,
            "worktree": str(wt),
            "model": cfg.review_model or cfg.model,
            "max_context_chars": cfg.max_context_bytes,
            "max_files": cfg.max_edits,
            "max_output_tokens": cfg.max_output_tokens,
        }
        request_path = directory / f"{stage}-request.json"
        result_path = directory / f"{stage}-result.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        gate = Gate(
            name=stage,
            argv=[
                "{python}",
                "-I",
                "-m",
                "aeo_workbench.legacy_worker",
                str(request_path),
                str(result_path),
            ],
            timeout_seconds=cfg.bridge_timeout_seconds,
        )
        env = {"OPENAI_API_KEY": os.environ["OPENAI_API_KEY"]} if stage == "reviewer" else {}
        execution = engine.execute_gate(wt, gate, directory / f"{stage}.log", extra_env=env)
        if execution["status"] != "passed":
            raise WorkbenchError(
                f"{stage} bridge {execution['status']}. Check the installed V0.5 core and "
                "the local stage result; no pipeline retry was made."
            )
        if not result_path.is_file() or result_path.stat().st_size > 2_000_000:
            raise WorkbenchError("Invalid bridge response.")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("status"), str):
            raise WorkbenchError("Invalid bridge response.")
        result["duration_ms"] = execution["duration_ms"]
        return redact(result)


def run_pipeline(
    root: Path,
    run_id: str,
    *,
    trust_code: bool = False,
    allow_remote: bool = False,
    bridge=None,
) -> dict:
    if not trust_code or not allow_remote:
        raise WorkbenchError(
            "Review show --diff first. Pipeline needs --trust-code and --allow-remote: "
            "it executes tests and sends changed code, diff, project metadata and configured "
            "policy files to the reviewer."
        )
    root = repo_root(root)
    backend = bridge or LegacyBridge()
    with storage.lock(root):
        run = storage.get(root, run_id)
        if run["status"] not in {"proposed", "validated", "validation_failed", "interrupted"}:
            raise WorkbenchError("Run cannot enter the pipeline.")
        cfg = storage.config(root)
        if not cfg.gates:
            raise WorkbenchError("Configure at least one deterministic gate first.")
        if not getattr(backend, "fixture", False) and (
            not (cfg.review_model or cfg.model) or not os.environ.get("OPENAI_API_KEY")
        ):
            raise WorkbenchError("Configure a model and OPENAI_API_KEY before the pipeline.")
        engine.check_artifact(root, run)
        if head(root) != run["base"]:
            raise WorkbenchError("Source HEAD moved; regenerate the proposal.")
        raw = project_config(root)
        attempt = uuid.uuid4().hex[:12]
        directory = storage.run_dir(root, run_id) / "attempts" / attempt
        directory.mkdir(parents=True)
        proof = {
            "attempt": attempt,
            "status": "running",
            "created_at": storage.now(),
            "patch_sha256": run["patch_sha256"],
            "policy_sha256": policy_hash(root, cfg, raw),
            "fixture": bool(getattr(backend, "fixture", False)),
            "stages": [],
        }
        run.update(
            status="validating", pipeline_required=True, pipeline=proof, gates=[], error=None
        )
        run["gate_config_sha256"] = fingerprint([g.model_dump() for g in cfg.gates])
        storage.save(root, run)

        def persist():
            (directory / "evidence.json").write_text(
                json.dumps(redact(proof), indent=2), encoding="utf-8"
            )
            storage.save(root, run)

        def unchanged():
            engine.check_artifact(root, run)
            if (
                policy_hash(root, storage.config(root), project_config(root))
                != proof["policy_sha256"]
            ):
                raise WorkbenchError("Pipeline policy changed during execution.")
            if config_path.read_bytes() != raw:
                raise WorkbenchError("Worktree configuration changed during execution.")

        try:
            config_path = prepare_bridge(root, run, raw)
            probe = backend.call("probe", Path(run["worktree"]), cfg, directory)
            if probe.get("status") != "passed":
                raise WorkbenchError("V0.5 bridge preflight failed.")
            for i, gate in enumerate(cfg.gates):
                result = engine.execute_gate(
                    Path(run["worktree"]), gate, directory / f"gate-{i}.log"
                )
                run["gates"].append(result)
                persist()
                unchanged()
                if result["status"] != "passed":
                    raise WorkbenchError(
                        "A deterministic gate failed. Remote review was not started."
                    )
            proof["stages"].append({"name": "gates", "status": "passed"})
            persist()
            for stage in ("guardian", "reviewer"):
                unchanged()
                result = backend.call(stage, Path(run["worktree"]), cfg, directory)
                # Persist returned evidence even if the artifact integrity check then fails.
                proof["stages"].append({**result, "name": stage})
                persist()
                unchanged()
                if result.get("status") != "passed":
                    raise WorkbenchError(f"{stage} did not pass. Acceptance remains blocked.")
                if stage == "reviewer" and result.get("omitted_files", 1) != 0:
                    raise WorkbenchError(
                        "Reviewer omitted files. Narrow the proposal before acceptance."
                    )
            proof["status"] = "passed"
            run["status"] = "validated"
        except BaseException as exc:
            proof["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            run["status"] = (
                "interrupted" if isinstance(exc, KeyboardInterrupt) else "validation_failed"
            )
            run["error"] = str(exc) if isinstance(exc, WorkbenchError) else type(exc).__name__
            proof["error"] = run["error"]
            persist()
            raise
        persist()
        run["pipeline_evidence_sha256"] = digest((directory / "evidence.json").read_bytes())
        storage.save(root, run)
        return run


def assert_acceptance(root: Path, run: dict, cfg: Settings) -> None:
    if not (cfg.require_pipeline or run.get("pipeline_required")):
        return
    proof = run.get("pipeline") or {}
    if proof.get("fixture"):
        raise WorkbenchError("Offline fixture evidence cannot authorize acceptance.")
    if proof.get("status") != "passed":
        raise WorkbenchError("Run the complete pipeline before acceptance.")
    if proof.get("patch_sha256") != run["patch_sha256"]:
        raise WorkbenchError("Pipeline evidence belongs to another patch.")
    if proof.get("policy_sha256") != policy_hash(root, cfg, project_config(root)):
        raise WorkbenchError("Pipeline policy changed; run the pipeline again.")
    if [(s.get("name"), s.get("status")) for s in proof.get("stages", [])] != [
        ("gates", "passed"),
        ("guardian", "passed"),
        ("reviewer", "passed"),
    ]:
        raise WorkbenchError("Incomplete pipeline evidence.")
    if (Path(run["worktree"]) / ".aeo" / "project.json").read_bytes() != project_config(root):
        raise WorkbenchError("Worktree configuration changed; run the pipeline again.")
    path = storage.run_dir(root, run["id"]) / "attempts" / proof["attempt"] / "evidence.json"
    if digest(path.read_bytes()) != run.get("pipeline_evidence_sha256"):
        raise WorkbenchError("Pipeline evidence file changed; run the pipeline again.")
