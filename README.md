# AI Engineering OS (AEO) — v0.4

AEO is an observable, risk-aware engineering workflow for AI-assisted software development.

## V0.4 — Repo Guardian

V0.4 introduces the first active engineering protection layer. Guardian is deterministic and
read-only by default. It inspects the current Git change set, runs configured quality gates,
classifies findings, records telemetry, and can apply only explicitly configured safe fixes.

```bash
python -m uv run aeo guard
python -m uv run aeo guard --staged
python -m uv run aeo guard --fix
python -m uv run aeo stats
```

Guardian currently detects high-confidence issues including:

- private-key material and AWS access-key patterns in changed lines
- `.env` files entering a change set
- unresolved merge-conflict markers
- Python breakpoints / `pdb.set_trace()`
- JavaScript/TypeScript `debugger;`
- cache/generated artifacts such as `__pycache__`, `.pyc`, `.pytest_cache`, `.mypy_cache`
- source changes without accompanying test-file changes (informational)
- very large file-count change sets (warning)

### Safe autofix policy

`aeo guard` never edits code by default. `aeo guard --fix` may execute only commands listed
under `fixes` in `.aeo/project.json`. Python projects detected with Ruff receive:

```json
{"fixes": {"lint": "ruff check . --fix"}}
```

Security findings, merge conflicts, secrets, debuggers, and repository-hygiene findings are
never silently rewritten.

## API

```bash
python -m uv run uvicorn aeo.api.main:app --reload --port 8009
```

Relevant endpoints include `/runs`, `/tasks`, `/stats`, and `/guard/scans`.


## V0.5 — Evidence-Backed AI Reviewer

AEO now includes a model-powered reviewer designed around evidence and falsification rather than raw LLM comments.

```powershell
python -m uv sync --extra dev --extra ai
python -m uv run aeo review --dry-run
python -m uv run aeo review
python -m uv run aeo review --deep
python -m uv run aeo reviews
```

The reviewer uses structured output, local line/diff evidence validation, deterministic sensitive-content preflight, risk-aware skeptical verification, and token/latency/cost telemetry. Raw prompts and source-code context are not persisted in the AEO database.

See `docs/AI_REVIEWER_ARCHITECTURE.md` and `docs/adr/005-evidence-backed-ai-reviewer.md`.
