---
name: saas-architecture
description: Use when designing or building SaaS applications — multi-tenancy models (silo/pool/bridge), tenant isolation, subscription and billing integration (Stripe/Paddle), onboarding flows, feature flags and entitlements, usage metering, API rate limiting, tenant-aware data partitioning, SaaS operational patterns (noisy neighbor, tenant health), and SaaS security (data isolation, compliance, SOC2).
---

# SaaS Architecture & Patterns

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [billing-flags-onboarding-api.md](billing-flags-onboarding-api.md) | subscription/billing integration (Stripe/Paddle), feature flags/entitlements, onboarding flows, and API design patterns |
| [metering-operations-security.md](metering-operations-security.md) | usage metering, operational patterns (scaling, deployment, monitoring), security/compliance, and anti-patterns |
| [tenancy-isolation-partitioning.md](tenancy-isolation-partitioning.md) | multi-tenancy models (silo/pool/bridge), tenant isolation patterns, and data partitioning strategies |

---

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Filter by tenant_id only in application code | One missed filter = data leak. Use RLS + ORM filters as safety nets |
| Use a single API key for all tenants | Compromised key affects everyone. Keys must be tenant-scoped |
| Synchronously provision silo infrastructure on signup | Blocks the request. Use async provisioning with status polling |
| Share encryption keys across tenants | One breach exposes all tenants. Use per-tenant KMS keys |
| Delete tenant data without a grace period | No recovery path. Always queue with 30+ day grace period |
| Skip webhook signature verification | Spoofed events can corrupt tenant state |
| Rate limit by IP instead of tenant | Multiple tenants behind one IP get unfairly limited |
| Store plan/tier logic in the database | Deployment-coupled. Define plans in code, store tenant-plan mapping in DB |
| Run migrations synchronously for schema-per-tenant | Locks the request. Run async, report progress |
| Ignore noisy neighbor signals | One tenant degrades experience for all shared-pool tenants |
