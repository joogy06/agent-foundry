# Test Reality Model

Reference file for `performance` skill. Mandatory pre-flight for any load test, capacity validation, or frontend performance measurement. A load test that violates these rules produces numbers that cannot be trusted and cannot be compared.

Applied by: `load-testing.md`, `capacity-planning.md`, `frontend-performance.md`, and every script under `scripts/`.

---

## 1. Environment Isolation

The `PERF_ENV` environment variable is the contract between the skill and the harness. Every script refuses to run without it.

| Tier | What it is | When to use |
|---|---|---|
| `staging` | Long-lived shared non-prod environment | Daily smoke + PR smoke |
| `preprod` | Production-parity environment with production-shape data | Nightly full test + release gates |
| `dedicated-perf` | Isolated environment pinned to perf workloads | Capacity experiments, soak, spike |
| `local-dev` | Developer machine or containerised replica | Investigation only; never compare across machines |
| `prod` | Production | Forbidden. Scripts refuse. Only manual, scheduled, pre-approved runs through an operations channel outside this skill. |

Rules:

1. `PERF_ENV` must be set. Empty is not a tier.
2. Any value matching `prod|production` (case-insensitive) is rejected at script load time.
3. Results from different tiers are not comparable. A baseline captured in `staging` cannot be used as the reference for a `preprod` regression check.
4. The harness must print the tier alongside every report.

---

## 2. Test Data

Production data is 10–100× larger than test data by default. Test data must approximate production volume and distribution before any number is meaningful.

| Requirement | Detail |
|---|---|
| Row count | At least 10% of production per large table, or a known scaled sample that preserves query selectivity |
| Distribution | Hot rows, cold rows, and long-tail keys present. A uniform dataset hides index effectiveness. |
| Anonymisation | PII scrubbed via a reviewed process. Keep referential integrity (foreign keys resolve). |
| Seeding | Idempotent seeding script under version control. "Run this and get the same dataset" is required for regression comparison. |
| Refresh cadence | Re-seed between destructive tests (stress, spike) or the next run is polluted. |

### Seeding strategy

```
1. Snapshot prod → anonymise → store in a seed bucket (one-time).
2. Each perf environment restores from the seed bucket before a release test.
3. Nightly tests run against the daily-refreshed seed copy.
4. PR-smoke runs against a small fixture; never pretend fixture numbers represent production.
```

---

## 3. Warmup

First requests hit cold caches, cold JIT, empty connection pools, cold HTTP/2 connections, uninitialised buffer pools. Warmup is not optional.

| Stack | Minimum warmup | What it warms |
|---|---|---|
| Python (cPython, no JIT) | 30 s | Connection pools, caches, lazily-imported modules |
| Python (PyPy) | 120 s | JIT + pools |
| Node.js / Deno | 60 s | V8 TurboFan, pools, HTTP keep-alive |
| JVM (JIT) | 300 s | JIT compilation tiers — C1 then C2 |
| Go | 30 s | Pools (no JIT, but allocator warms) |
| .NET | 120 s | RyuJIT, pools |
| Rust | 30 s | Pools (no JIT) |

Rules:

1. The warmup stage runs identical traffic to the steady-state stage, just shorter.
2. Metrics from the warmup window are discarded from SLO calculations but kept in the raw trace for debugging.
3. Cold-start measurements are a separate test type, not the baseline.

---

## 4. Third-Party Mocks

Any test that hits real Stripe, Twilio, SendGrid, Plaid, or any billable external API during a load test is unsafe: it costs real money, will trip the provider's rate limits mid-test, and invalidates the results.

Mock protocol:

1. Each external integration has a mock flag (environment variable or DI config).
2. Mocks are feature-equivalent: same request/response shape, same error classes, same latency distribution (not zero — inject `p95 ≈ real provider's p95`).
3. The contract's `third_party_mocks: required` field is a go/no-go gate. If mocks cannot be asserted, the run is cancelled.
4. Mocks must be asserted pre-run (a smoke call that verifies the mock responds, not the real provider).

Providers that must always be mocked during load testing (not exhaustive): payment processors, SMS/email providers, push-notification gateways, identity providers (outside token issuance), map/geocoding APIs, LLM APIs.

---

## 5. Generator Location

Network latency between the load generator and the system under test is part of the measurement.

| Generator location | Effect on measurements |
|---|---|
| Same host (container or localhost) | Network latency ≈ 0 ms. Results are optimistic, do not match user experience. Acceptable for profiling only. |
| Separate host on same LAN/VPC | 0.1–2 ms. Acceptable for backend API testing. |
| Separate cloud region | 20–100+ ms. Realistic for geographically-distributed users but inflates latency numbers — budget accordingly. |
| Developer laptop → cloud | Highly variable. Only for investigation, never for SLO assertions. |

Rules:

1. Record generator location in the test metadata.
2. Compare only like-to-like: same-LAN baseline is not a reference for same-host runs.
3. For frontend / CWV tests, the generator is the browser. Throttle the browser (Lighthouse `throttlingMethod: simulate`) for repeatable runs.

---

## 6. CI Tiers

Performance tests live in three CI lanes. Each lane has a different budget and a different blast radius.

| Tier | Budget | Blast radius | Contents |
|---|---|---|---|
| `pr-smoke` | 1–5 min, on every PR | Blocks merge on error-rate regression only, warns on latency | Smoke scenario, 1–5 VUs, one critical path |
| `nightly` | 15–30 min, scheduled | Opens a regression issue, does not block deploy | Load scenario at expected concurrency, representative scenario mix |
| `release` | 1–4 h, gated before release | Blocks release on any SLO breach | Soak + spike, peak concurrency, full scenario mix |

Rules:

1. Every perf test declares its tier. Scripts refuse to run at the wrong tier (a soak test on a PR is either mis-wired or intentional abuse).
2. Each tier's results are tagged with the tier in storage — baselines are per-tier.
3. Promoting a finding from `nightly` to `release` requires a repeat run at that tier; nightly numbers do not gate release.

---

## 7. Result Comparison

Performance results have no meaning without a reference. Every run is compared to something.

```
Baseline
 ├── Previous release baseline (for regression detection)
 ├── Initial baseline (for first-time characterisation)
 └── Contract target (for acceptance gate)
```

Rules:

1. Store baselines with full metadata: tier, commit sha, dataset version, generator location.
2. Compare only against a baseline captured under identical conditions. A cross-condition comparison is a bug, not a data point.
3. Baseline refresh is an explicit, documented decision — not a silent overwrite.
4. Regression thresholds are per-metric, per-tier. A 10% latency increase on a PR smoke is noise; the same on a nightly may be signal.

Default thresholds (override per contract):

| Metric | Regression at | Action |
|---|---|---|
| `api_latency_p95` | +20% | Investigate |
| `api_latency_p99` | +50% | Investigate tail |
| `throughput_rps` | -10% | Investigate |
| `error_rate` | from 0 to >0 | Immediate fix |
| `memory_p95 (soak)` | +10% over soak window | Leak candidate |
| `lcp_p75` | +15% | Investigate frontend regression |
| `cls_p75` | >0.1 or +0.05 | Investigate layout shifts |
| `inp_p75` | +25% | Investigate interaction latency |

---

## 8. Pre-flight Checklist

Before running any load, capacity, or CWV test:

1. [ ] `PERF_ENV` is set and is not production
2. [ ] Test data volume and distribution match the contract
3. [ ] Seeding script has run (or seed snapshot is fresh)
4. [ ] Warmup stage length matches the stack minimum
5. [ ] Third-party mocks are in place and verified by a dry call
6. [ ] Generator location is recorded and matches the baseline conditions
7. [ ] CI tier is declared and the scenario matches the tier's budget
8. [ ] Baseline to compare against is identified (or this is the explicit first-baseline run)

Missing any item: abort, fix, restart. Do not "run it anyway and treat the numbers as directional" — directional perf numbers usually mis-direct.

---

## Anti-patterns

| Don't | Why |
|---|---|
| Run against production "just this once" | There is no "just this once" — provider rate limits, customer incidents, data writes |
| Skip warmup "to save time" | You measured cold-start, not steady state; SLO violations aren't real |
| Use the baseline "from last month" after a schema change | Conditions changed; the comparison is meaningless |
| Let real Stripe/Twilio through "in small amounts" | A small amount at 500 VUs is a large amount; bills and rate limits are real |
| Compare a container-local run to a cloud run | Different network = different measurement, not the same thing improved |
| Accept a result without recording tier / dataset / generator | An uncharacterised result cannot be reused as a baseline |
