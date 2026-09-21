# Upgrade to AEO v0.5.0 — Evidence-Backed AI Reviewer

V0.5 adds the first model-powered capability to AEO.

## What changes

- `aeo review` — adversarial AI review of working-tree changes.
- `aeo review --staged` — review the Git index only.
- `aeo review --deep` — verify every evidence-valid finding with a skeptical second pass.
- `aeo review --dry-run` — build context, risk, and telemetry without calling a model.
- `aeo reviews` — review history.
- `/reviews` API endpoint.
- Structured review output with exact evidence.
- Local evidence validation before a finding can influence the outcome.
- Risk-aware second-pass verification.
- Prompt-injection boundary: repository content is treated as untrusted data.
- Deterministic privacy preflight blocks sensitive Guardian findings before external model invocation.
- Review telemetry: tokens, latency, request IDs, context hashes, verifier rejection rate, and optional cost estimates.
- Schema version 5 with additive `ai_reviews`, `ai_review_findings`, and `ai_review_calls` tables.

## Install

From the repository root:

```powershell
python -m uv sync --extra dev --extra ai
```

The `ai` extra installs the official OpenAI Python SDK. Core AEO and all unit tests remain usable without it.

## Configure the API key

PowerShell, current session:

```powershell
$env:OPENAI_API_KEY="YOUR_KEY"
```

Do not commit API keys to the repository.

## Validate the upgrade

```powershell
python -m uv run aeo version
python -m uv run ruff check .
python -m uv run mypy .
python -m uv run pytest
```

Expected version:

```text
AEO 0.5.0
```

The packaged release contains 27 tests before your local static gates.

## First safe run

Start with a dry run:

```powershell
python -m uv run aeo review --dry-run
```

Then execute a real review:

```powershell
python -m uv run aeo review
```

For a higher-risk change:

```powershell
python -m uv run aeo review --deep
```

## Provider/model configuration

Existing projects receive reviewer defaults at runtime. A fresh `aeo init` writes:

```json
{
  "reviewer": {
    "provider": "openai",
    "model": "gpt-5.6",
    "verification_model": "gpt-5.6",
    "max_context_chars": 80000,
    "max_files": 25,
    "max_output_tokens": 5000,
    "deep_review_risk_threshold": 6.0,
    "min_confidence": 0.55,
    "policy_files": [],
    "pricing": {
      "input_per_million_usd": null,
      "output_per_million_usd": null
    }
  }
}
```

Pricing is intentionally not hardcoded. If you populate the two pricing values, AEO will calculate estimated review cost from recorded token usage.
