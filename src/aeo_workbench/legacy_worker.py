"""Isolated interpreter entry point: import installed, trusted V0.5 services.

The worktree is a data argument, never added to sys.path here. Only the
reviewer process receives OPENAI_API_KEY; Guardian's test children do not.
"""

import contextlib
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .safety import redact


def dispatch(request: dict) -> dict:
    from aeo.guardian.service import run_guard
    from aeo.reviewer.service import run_review

    if request["stage"] == "probe":
        return {"status": "passed", "bridge": "aeo-v0.5"}
    root = Path(request["worktree"])
    if request["stage"] == "guardian":
        result = run_guard(root, staged=True, fix=False)
    elif request["stage"] == "reviewer":
        result = run_review(
            root,
            staged=True,
            verify=True,
            provider_name="openai",
            model=request["model"],
            verification_model=request["model"],
            max_context_chars=request["max_context_chars"],
            max_files=request["max_files"],
            max_output_tokens=request["max_output_tokens"],
        )
    else:
        raise ValueError("Unknown bridge stage")
    return asdict(result)


def main() -> int:
    request_path, result_path = map(Path, sys.argv[1:3])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        # Services may print diagnostics. Do not echo repository text or credentials.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = dispatch(request)
        result_path.write_text(json.dumps(redact(result), default=str), encoding="utf-8")
        return 0
    except Exception as exc:
        result_path.write_text(
            json.dumps({"status": "error", "error_type": type(exc).__name__}), encoding="utf-8"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
