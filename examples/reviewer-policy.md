# Example AEO Reviewer Policy

Copy this file to `.aeo/reviewer.md` or list it in `reviewer.policy_files`.

## Architecture invariants

- Tenant-owned data must always be scoped by tenant/enterprise ID.
- Database writes spanning multiple dependent entities should be transactional.
- Public API behavior changes require tests for backwards compatibility.
- Authentication and authorization checks must fail closed.
- Background/retryable operations should be idempotent.

## Review priorities

1. Cross-tenant exposure or authorization bypass.
2. Data corruption and unsafe migrations.
3. Race conditions and non-idempotent retries.
4. Broken API contracts.
5. Missing tests for high-risk behavior.
6. Material performance regressions on hot paths.
