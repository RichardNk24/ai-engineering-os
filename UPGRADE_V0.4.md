# Upgrade to AEO v0.4

1. Keep `.aeo/aeo.db`; V0.4 upgrades additively from schema 3 to schema 4.
2. Replace the supplied files at repository root.
3. Run:

```powershell
python -m uv sync --extra dev
python -m uv run ruff check .
python -m uv run mypy .
python -m uv run pytest
python -m uv run aeo version
python -m uv run aeo guard
```

Existing `.aeo/project.json` files are backward-compatible. `fixes` and `guardian` defaults are
resolved dynamically; running `aeo init` again is not required.
