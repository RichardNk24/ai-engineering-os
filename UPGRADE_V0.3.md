# Upgrade to AEO v0.3

V0.3 is designed to upgrade an existing V0.2.x project without deleting `.aeo/aeo.db`.

## 1. Replace the V0.3 source files

Apply the V0.3 upgrade archive over the repository root.

## 2. Keep local telemetry

Do **not** delete:

```text
.aeo/aeo.db
```

The existing V0.1/V0.2 tables are preserved.

## 3. Sync dependencies

```powershell
python -m uv sync --extra dev
```

## 4. Run deterministic validation

```powershell
python -m uv run ruff check .
python -m uv run mypy .
python -m uv run pytest
```

## 5. Trigger schema compatibility setup

Any AEO command that opens the database will create the additive V0.3 tables and backfill legacy validation links. A safe first command is:

```powershell
python -m uv run aeo doctor
```

Then verify:

```powershell
python -m uv run aeo task history
python -m uv run aeo stats
```

## V0.3 additive tables

- `aeo_schema_metadata`
- `execution_environments`
- `task_finalizations`
- `task_validation_attempts`

No existing V0.2 column is removed or renamed.
