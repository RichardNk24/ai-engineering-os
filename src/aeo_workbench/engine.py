import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import storage
from .gitops import clean, git, head, repo_root, tracked_files
from .models import Proposal, Settings
from .provider import OpenAIProvider, Provider
from .safety import WorkbenchError, digest, inspect_text, safe_path


def context_packet(root: Path, reads: list[str], writes: list[str], cfg: Settings) -> dict:
    if (
        not writes
        or len({p.casefold() for p in writes}) != len(writes)
        or len(writes) > cfg.max_edits
    ):
        raise WorkbenchError("Provide unique --write paths within max_edits.")
    files, total = {}, 0
    tracked = tracked_files(root)
    for name in sorted(set(reads + writes)):
        path = safe_path(root, name)
        if path.exists():
            if name not in tracked or not path.is_file():
                raise WorkbenchError("Context must contain committed regular files only.")
            raw = path.read_bytes()
            if len(raw) > cfg.max_file_bytes:
                raise WorkbenchError("Context file exceeds max_file_bytes; narrow the task.")
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkbenchError("Only UTF-8 source files are supported.") from exc
            inspect_text(content)
            files[name] = content
            total += len(raw)
        elif name not in writes:
            raise WorkbenchError("A --read path does not exist.")
        else:
            files[name] = None
    if total > cfg.max_context_bytes:
        raise WorkbenchError("Context budget exceeded; narrow the selected files.")
    return {"files": files, "writable_paths": writes}


def prepare(
    root: Path,
    task: str,
    reads: list[str],
    writes: list[str],
    *,
    model: str | None = None,
    dry_run: bool = False,
    provider: Provider | None = None,
) -> dict:
    root = repo_root(root)
    with storage.lock(root):
        cfg = storage.config(root)
        if model:
            cfg.model = model
        clean(root)
        base = head(root)
        if not task.strip() or len(task.encode()) > 16000:
            raise WorkbenchError("Task must contain 1–16000 UTF-8 bytes.")
        inspect_text(task)
        packet = context_packet(root, reads, writes, cfg)
        run_id = uuid.uuid4().hex[:12]
        rd = storage.state_dir(root) / "runs" / run_id
        rd.mkdir(parents=True, mode=0o700)
        run = {
            "id": run_id,
            "pipeline_required": cfg.require_pipeline,
            "status": "planning",
            "created_at": storage.now(),
            "base": base,
            "model": cfg.model,
            "context_bytes": len(json.dumps(packet).encode()),
            "context_sha256": digest(json.dumps(packet, sort_keys=True).encode()),
            "task_sha256": digest(task.encode()),
            "writable_paths": writes,
            "usage": None,
            "gates": [],
            "patch_sha256": None,
            "worktree": str(rd / "worktree"),
            "error": None,
        }
        storage.save(root, run)
        if dry_run:
            run["status"] = "dry_run"
            storage.save(root, run)
            return run
        try:
            proposal, usage = (provider or OpenAIProvider()).propose(task, packet, cfg)
            run["usage"] = usage.model_dump()
            validate_proposal(proposal, packet, cfg)
            if not proposal.edits:
                raise WorkbenchError("Provider proposed no edits. Narrow or clarify the task.")
            # Refuse provider-time modifications of the user's repository.
            clean(root)
            if head(root) != base:
                raise WorkbenchError("HEAD changed during generation; create a new proposal.")
            wt = Path(run["worktree"])
            git(root, "worktree", "add", "--detach", str(wt), base)
            run["status"] = "applying"
            storage.save(root, run)
            for edit in proposal.edits:
                target = safe_path(wt, edit.path)
                if edit.operation == "delete":
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(edit.content.encode("utf-8"))
                git(wt, "add", "--", edit.path)
            patch = git(
                wt,
                "diff",
                "--cached",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                base,
                binary=True,
            )
            if not patch:
                raise WorkbenchError("Proposal produced no effective change.")
            (rd / "proposal.json").write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
            (rd / "change.patch").write_bytes(patch)
            run["patch_sha256"] = digest(patch)
            run["status"] = "proposed"
            storage.save(root, run)
            return run
        except BaseException as exc:
            run["status"] = (
                "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
            )
            run["error"] = str(exc) if isinstance(exc, WorkbenchError) else type(exc).__name__
            storage.save(root, run)
            raise


def validate_proposal(proposal: Proposal, packet: dict, cfg: Settings) -> None:
    inspect_text(proposal.model_dump_json())
    names = [edit.path for edit in proposal.edits]
    if len(names) != len({p.casefold() for p in names}) or len(names) > cfg.max_edits:
        raise WorkbenchError("Duplicate paths or edit limit exceeded.")
    total = 0
    for edit in proposal.edits:
        if edit.path not in packet["writable_paths"]:
            raise WorkbenchError("Provider edited a path outside the approved write scope.")
        inspect_text(edit.content)
        size = len(edit.content.encode())
        if size > cfg.max_file_bytes:
            raise WorkbenchError("Generated file exceeds max_file_bytes.")
        total += size
        if edit.operation == "delete" and (edit.content or packet["files"][edit.path] is None):
            raise WorkbenchError("Invalid deletion proposal.")
    if total > cfg.max_context_bytes:
        raise WorkbenchError("Generated content exceeds the total byte budget.")


def check_artifact(root: Path, run: dict) -> bytes:
    rd = storage.run_dir(root, run["id"])
    patch = (rd / "change.patch").read_bytes()
    if digest(patch) != run["patch_sha256"]:
        raise WorkbenchError("Patch changed after generation; create a new proposal.")
    wt = Path(run["worktree"])
    if head(wt) != run["base"]:
        raise WorkbenchError("Worktree HEAD changed; proposal is stale.")
    current = git(wt, "diff", "HEAD", "--binary", "--no-ext-diff", "--no-textconv", binary=True)
    staged = git(
        wt, "diff", "--cached", "HEAD", "--binary", "--no-ext-diff", "--no-textconv", binary=True
    )
    if current != patch or staged != patch or git(wt, "ls-files", "--others", "--exclude-standard"):
        raise WorkbenchError("Worktree changed outside the proposal; create a new proposal.")
    return patch


def execute_gate(wt: Path, gate, log: Path, *, extra_env: dict | None = None) -> dict:
    argv = [sys.executable if arg == "{python}" else arg for arg in gate.argv]
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "LANG",
            "LC_ALL",
            "VIRTUAL_ENV",
        }
    }
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env.update(
        NO_COLOR="1", PYTHONUNBUFFERED="1", PYTHONPATH=os.pathsep.join([str(wt / "src"), str(wt)])
    )
    if extra_env:
        env.update(extra_env)
    start = time.monotonic()
    status, returncode = "failed", None
    with log.open("wb") as stream:
        try:
            process = subprocess.Popen(
                argv,
                cwd=wt,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                shell=False,
                start_new_session=os.name != "nt",
            )
            try:
                returncode = process.wait(timeout=gate.timeout_seconds)
                status = "passed" if returncode == 0 else "failed"
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                if sys.exc_info()[0] is KeyboardInterrupt:
                    raise
                status = "timeout"
        except OSError:
            status = "unavailable"
    return {
        "name": gate.name,
        "status": status,
        "returncode": returncode,
        "duration_ms": round((time.monotonic() - start) * 1000, 2),
    }


def validate(root: Path, run_id: str, *, trust_code: bool = False) -> dict:
    if not trust_code:
        raise WorkbenchError("Review the code, then use --trust-code to execute configured gates.")
    root = repo_root(root)
    with storage.lock(root):
        run = storage.get(root, run_id)
        if run["status"] not in {"proposed", "validation_failed", "validated"}:
            raise WorkbenchError("Run is not available for validation.")
        cfg = storage.config(root)
        if not cfg.gates:
            raise WorkbenchError("No gates configured. Edit the config path printed by aeo6 init.")
        check_artifact(root, run)
        run.update(status="validating", gates=[])
        run["gate_config_sha256"] = digest(
            json.dumps([g.model_dump() for g in cfg.gates], sort_keys=True).encode()
        )
        storage.save(root, run)
        try:
            for i, gate in enumerate(cfg.gates):
                result = execute_gate(
                    Path(run["worktree"]), gate, storage.run_dir(root, run_id) / f"gate-{i}.log"
                )
                run["gates"].append(result)
                storage.save(root, run)
            check_artifact(root, run)
            run["status"] = (
                "validated"
                if all(g["status"] == "passed" for g in run["gates"])
                else "validation_failed"
            )
        except BaseException as exc:
            run["status"] = (
                "interrupted" if isinstance(exc, KeyboardInterrupt) else "validation_failed"
            )
            run["error"] = str(exc) if isinstance(exc, WorkbenchError) else type(exc).__name__
            storage.save(root, run)
            raise
        storage.save(root, run)
        return run


def accept(root: Path, run_id: str) -> dict:
    root = repo_root(root)
    with storage.lock(root):
        run = storage.get(root, run_id)
        if run["status"] != "validated":
            raise WorkbenchError("All configured gates must pass before acceptance.")
        cfg = storage.config(root)
        current_gates = digest(
            json.dumps([g.model_dump() for g in cfg.gates], sort_keys=True).encode()
        )
        if current_gates != run["gate_config_sha256"]:
            raise WorkbenchError("Gate configuration changed; validate again.")
        from .pipeline import assert_acceptance

        assert_acceptance(root, run, cfg)
        check_artifact(root, run)
        clean(root)
        if head(root) != run["base"]:
            raise WorkbenchError("Source HEAD moved; regenerate against the new base.")
        patch = str(storage.run_dir(root, run_id) / "change.patch")
        git(root, "apply", "--check", "--index", patch)
        git(root, "apply", "--index", patch)
        run["status"] = "accepted"
        storage.save(root, run)
        return run


def discard(root: Path, run_id: str) -> dict:
    root = repo_root(root)
    with storage.lock(root):
        run = storage.get(root, run_id)
        if run["status"] == "accepted":
            raise WorkbenchError(
                "Accepted changes belong to your repository; use normal Git review."
            )
        wt = Path(run["worktree"])
        if wt.exists():
            # Explicit discard only; never delete arbitrary paths via shutil.
            git(root, "worktree", "remove", "--force", str(wt))
        run["status"] = "discarded"
        storage.save(root, run)
        return run
