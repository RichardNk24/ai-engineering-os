# Changelog

## 0.4.0

- Add deterministic Repo Guardian command and telemetry.
- Add Git zero-context diff intelligence including untracked text files.
- Add blocker/error/warning/info finding classification.
- Detect high-confidence secret, conflict, debugger, env-file, and cache-artifact risks.
- Run project quality gates as part of Guardian.
- Add opt-in safe autofix policy backed by project configuration.
- Persist guard scans, findings, and fix attempts in additive schema v4 tables.
- Add Guardian analytics and `/guard/scans` API endpoint.

## 0.3.0

- Add engineering analytics, environment snapshots, validation attempts, schema guard,
  and crash-safe task finalization.
