# ADR-005: Evidence-Backed AI Review with Skeptical Verification

## Status

Accepted for AEO v0.5.0.

## Context

LLM code review can increase review coverage but introduces failure modes of its own: hallucinated bugs, unsupported severity, prompt injection from repository content, excessive context/cost, and false confidence caused by treating model output as ground truth.

## Decision

AEO will not treat a model response as a merge decision directly.

Every review passes through:

1. deterministic sensitive-content preflight;
2. bounded and hashed repository context;
3. structured primary review;
4. local evidence validation;
5. risk-aware skeptical verification;
6. explicit status semantics and human-visible uncertainty;
7. telemetry without raw prompt persistence.

High-severity findings that are confirmed, uncertain, or explicitly left unverified are blocking. Evidence-invalid findings are never blocking.

## Consequences

### Positive

- Reduces hallucination impact.
- Makes reviewer false positives measurable.
- Allows safe provider replacement.
- Makes deletions reviewable through diff evidence.
- Gives recruitment/interview demos meaningful engineering metrics rather than “AI generated N comments.”

### Trade-offs

- More model calls for high-risk reviews.
- Increased latency and token usage.
- Evidence constraints can reject a conceptually correct finding if the supplied context is insufficient.
- Current pricing must be configured rather than hardcoded because provider pricing is external and changeable.
