# Changelog

## 0.3.0

### Added

- Crash-safe task finalization records
- Persistent validation-attempt history per engineering task
- First-pass success and retry analytics
- Quality-gate pass/fail and duration analytics
- Task history and task detail CLI commands
- Task and richer run API endpoints
- Execution-environment snapshots for every new run
- Additive schema metadata/version guard
- V0.2 validation-link backfill

### Changed

- `aeo task finish` now leaves a task active when quality validation fails
- Re-running `task finish` after a failed validation creates a measured retry
- Re-running after a validation completed but finalization was interrupted reuses the completed run
- `aeo stats` now emphasizes median/P95 latency and engineering outcomes rather than only averages

### Compatibility

V0.3 uses additive SQLite tables and keeps the existing V0.1/V0.2 run/task tables intact.
