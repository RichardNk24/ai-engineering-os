# AI Engineering OS (AEO)

AEO is a Python-based engineering workflow layer designed to make AI-assisted
software development measurable, reviewable, and eventually agentic.

## V0.1 goals

- Detect a repository
- Initialize `.aeo/project.json`
- Run deterministic quality checks
- Record engineering runs
- Record event-level telemetry
- Report basic metrics

## Why this comes before the agents

The orchestrator, implementer, reviewer, repo guardian, risk engine and
specialist agents will all emit events into the same run model.

That means we can later answer:

- How much time did the agent actually save?
- Which quality gate fails most often?
- How many retries happened?
- Where did the human intervene?
- What did each successful change cost?
- Do reviewer agents reduce escaped defects?

## Install

```bash
uv sync --extra dev
```

or:

```bash
pip install -e ".[dev]"
```

## CLI

```bash
aeo init
aeo doctor
aeo check
aeo stats
```

## Development status

Current milestone: v0.2 — Git-aware engineering telemetry.

## API

```bash
uvicorn aeo.api.main:app --reload
```

Open:

- http://127.0.0.1:8000/docs
- http://127.0.0.1:8000/health
- http://127.0.0.1:8000/runs
- http://127.0.0.1:8000/stats
```
