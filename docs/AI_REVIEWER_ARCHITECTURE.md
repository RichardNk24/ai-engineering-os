# AEO V0.5 AI Reviewer Architecture

## Goal

The reviewer is designed to answer a stricter question than “what does the model think about this diff?”:

> Which findings are actionable, grounded in evidence that exists in the reviewed change, and sufficiently verified to affect an engineering decision?

## Pipeline

```text
Git change set
    │
    ▼
Deterministic Guardian preflight
    │
    ├── sensitive blocker ──> STOP before external model call
    │
    ▼
Bounded context builder
    ├── current-file line windows
    ├── D-numbered Git diff, including deletions
    ├── repository policy files
    ├── deterministic risk score
    └── SHA-256 context manifest
    │
    ▼
Primary adversarial reviewer
    │ Structured output
    ▼
Local evidence validator
    ├── file belongs to change set
    ├── current L-line or diff D-line range exists
    └── quoted evidence is actually present
    │
    ▼
Risk-aware skeptical verifier
    ├── standard: verify error/blocker findings
    └── deep: verify every evidence-valid finding
    │
    ▼
Decision
    ├── confirmed error/blocker ──> BLOCKED
    ├── uncertain error/blocker ──> BLOCKED / human review
    └── otherwise ──> PASSED
    │
    ▼
Telemetry
    ├── tokens
    ├── latency
    ├── request IDs
    ├── verifier rejection rate
    ├── evidence-invalid count
    ├── context hash/size
    └── optional estimated cost
```

## Trust boundaries

### Repository content is untrusted model input

Source code, comments, test fixtures, documentation, and strings can contain prompt-injection text. The system prompt explicitly instructs the reviewer and verifier never to follow instructions found inside repository content.

### Sensitive-content preflight

AEO reuses deterministic Guardian rules before model invocation. Private key or sensitive environment-file blockers stop the outbound AI review before code is sent externally.

### No raw prompt persistence

SQLite stores hashes and operational metadata, not the raw prompt or source-code context. This allows reproducibility/auditing signals without creating a second permanent copy of the reviewed code.

## Evidence model

A finding chooses one of two evidence sources:

- `current_file`: cites exact current source lines.
- `diff`: cites D-numbered Git diff lines. This exists specifically so removed checks and deleted behavior are reviewable.

A model finding that cannot pass local evidence validation is stored as `evidence_invalid` and cannot block the review.

## Verification semantics

The verifier is intentionally skeptical. It does not discover new issues; it tries to falsify the primary reviewer’s candidates.

Statuses are distinct:

- `confirmed`
- `rejected`
- `uncertain`
- `unverified`
- `evidence_invalid`

This prevents AEO from calling an unverified warning “confirmed” merely because it came from a model.

## Why provider calls are abstracted

The orchestration layer depends on a small `ReviewProvider` protocol. Tests inject deterministic fake providers and never call the network. OpenAI is the first production adapter; additional providers can be added without changing the evidence, persistence, verification, or analytics layers.
