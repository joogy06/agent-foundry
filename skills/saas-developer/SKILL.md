---
name: saas-developer
description: Use when implementing SaaS application features — tenant-aware middleware and request context, multi-tenant database queries (Django/Flask/FastAPI with SQLAlchemy), tenant-scoped API endpoints, webhook delivery systems, background job processing per tenant, email and notification systems, file storage isolation (S3 prefix per tenant), caching strategies (Redis key namespacing), testing multi-tenant code, and deployment patterns (blue-green, canary per tier). Complements saas-architecture with hands-on code. Part of the saas-* skill family.
---

# SaaS Developer Patterns

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [api-jobs-webhooks.md](api-jobs-webhooks.md) | tenant-scoped API endpoints, background job processing per tenant, webhook delivery systems |
| [email-storage-testing-deploy.md](email-storage-testing-deploy.md) | email/notification systems, file storage isolation, caching strategies, testing multi-tenant code, and deployment patterns |
| [tenant-context-database.md](tenant-context-database.md) | tenant context middleware, multi-tenant database layer with SQLAlchemy, row-level security |

---

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Pass `tenant_id` as function parameter through 15 layers | Use `contextvars` — set once in middleware, read anywhere |
| Cache with keys like `project:123` (no tenant prefix) | Always `tenant:{tid}:project:123` — prevents cross-tenant cache reads |
| Run Celery tasks without tenant context propagation | Use `TenantTask` base class that injects/restores tenant from headers |
| Generate pre-signed S3 URLs without validating key prefix | Always verify the key starts with `tenant-{tenant_id}/` before signing |
| Use `KEYS *` in Redis for tenant key operations | Use `SCAN` with cursor — `KEYS` blocks Redis on large datasets |
| Run all tenant schema migrations serially | Parallelize with bounded concurrency (5-10 at a time) |
| Write tests that share a single hardcoded tenant_id | Each test gets a fresh `uuid4()` tenant_id via fixture |
| Deploy new features to all tenants simultaneously | Canary by tier: internal, then starter, then pro, then enterprise |
| Store uploaded files at user-chosen paths | Sanitize filenames, prepend UUID, enforce tenant prefix |
| Let one tenant's failed webhook retries consume the entire retry queue | Use per-tenant or per-endpoint retry budgets with circuit breakers |
