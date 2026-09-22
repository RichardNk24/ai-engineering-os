"""Read-only decision brief. A ready result is checked again when accepting."""

from pathlib import Path

from . import engine, storage
from .gitops import clean, head
from .pipeline import assert_acceptance, fingerprint
from .safety import WorkbenchError, redact


def build_report(root: Path, run_id: str) -> dict:
    run = storage.get(root, run_id)
    reasons = []
    try:
        cfg = storage.config(root)
        if run["status"] != "validated":
            raise WorkbenchError("The run is not validated.")
        if fingerprint([g.model_dump() for g in cfg.gates]) != run.get("gate_config_sha256"):
            raise WorkbenchError("Gate configuration changed.")
        engine.check_artifact(root, run)
        assert_acceptance(root, run, cfg)
        clean(root)
        if head(root) != run["base"]:
            raise WorkbenchError("Source HEAD moved.")
    except WorkbenchError as exc:
        reasons.append(str(exc))
    except (ValueError, OSError):
        reasons.append("Configuration or evidence is missing or invalid.")
    return redact(
        {
            "run_id": run_id,
            "state": run["status"],
            "base": run["base"],
            "patch_sha256": run.get("patch_sha256"),
            "ready_to_accept": not reasons,
            "blocking_reasons": reasons,
            "gates": run.get("gates", []),
            "pipeline": run.get("pipeline"),
            "implementation_usage": run.get("usage"),
            "write_scope": run["writable_paths"],
            "evidence_directory": str(storage.run_dir(root, run_id)),
            "last_error": run.get("error"),
        }
    )
