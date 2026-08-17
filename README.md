# AI Engineering OS (AEO) — v0.3

AEO is a Python-based engineering workflow layer for making AI-assisted software development measurable, reviewable, and progressively agentic.

## V0.3 — Engineering Analytics & Reliability

V0.3 focuses on measurement integrity before autonomous agents are introduced.

### Reliability

- Crash-safe task finalization with a persisted finalization record
- Validation runs are linked to a task before subprocess execution
- A completed validation is reused after a partial failure instead of duplicated
- Failed validation keeps the task active so it can be fixed and retried
- Every validation attempt remains queryable for first-pass and retry analytics
- V0.2 task validation links are backfilled into the V0.3 additive schema

### Engineering analytics

- Task history and task detail views
- First-pass validation success rate
- Validation retry rate
- Per-quality-gate pass/fail counts
- Per-quality-gate average duration
- Average run and task duration

### Environment observability

Each new engineering run captures:

- AEO version
- Python version and implementation
- operating system and release
- machine architecture
- Git version

### Additive schema

V0.3 does not modify existing V0.2 table columns. It adds:

- `execution_environments`
- `task_finalizations`
- `task_validation_attempts`

This allows an existing `.aeo/aeo.db` to be reused.

## Install / upgrade

```bash
python -m uv sync --extra dev
```

Keep your existing `.aeo/aeo.db` if you are upgrading from V0.2.x.

## Core workflow

```bash
python -m uv run aeo doctor
python -m uv run aeo task start "Implement feature X"
# work...
python -m uv run aeo task finish
python -m uv run aeo task history
python -m uv run aeo stats
```

If validation fails, the task remains active. Fix the reported issue and run `task finish` again; AEO records a new validation attempt.

## Task inspection

```bash
python -m uv run aeo task history
python -m uv run aeo task show <TASK_ID>
```

## API

```bash
python -m uv run uvicorn aeo.api.main:app --reload --port 8009
```

Endpoints:

- `GET /health`
- `GET /runs`
- `GET /tasks`
- `GET /tasks/{task_id}`
- `GET /stats`
- `GET /docs`

## Roadmap

V0.4 is planned as the first Repo Guardian layer: deterministic repository intelligence and automated remediation around the quality system built in V0.1–V0.3.
