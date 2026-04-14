# Performance Test Contract Template

Reference file for `performance` skill. The contract is the single source of truth that the other performance sub-skills and `scripts/` templates consume. Fill it in once per scope (app-wide or per component), then generate load / CWV / capacity artifacts from it.

---

## YAML Template

Copy this into your project (e.g. `perf/contract.yaml`) and fill every placeholder. Missing required keys fail the contract.

```yaml
contract:
  scope: whole-app | component:<name>
  stack: <auto-detected from context-detection; override allowed>

  slos:
    - metric: api_latency_p95
      target: 200ms
      measurement_window: 5min
    - metric: api_latency_p99
      target: 500ms
      measurement_window: 5min
    - metric: error_rate
      target: <0.1%
      measurement_window: 5min
    - metric: throughput
      target: ">=500 req/s"
      measurement_window: 5min

  # Browser-side SLOs (only fill when scope includes a user-facing UI)
  frontend_slos:
    - metric: lcp_p75_ms
      target: 2500
    - metric: cls_p75
      target: 0.1
    - metric: inp_p75_ms
      target: 200

  concurrency_targets:
    expected_users: 1000
    peak_users: 5000
    expected_concurrent_processes_per_user: 3

  resource_budgets:
    cpu_p95: 70%
    memory_p95: 80%
    db_connections_p95: 60%  # fraction of pool
    worker_threads_p95: 75%  # fraction of max workers

  acceptance_criteria:
    - all_slos_met_under_peak_load
    - no_resource_budget_exceeded
    - error_rate_unchanged_under_load
    - no_memory_leak_over_soak

  test_environment:
    tier: staging | preprod | dedicated-perf
    dataset_volume: production-shape  # >=1M records where production has 1M+
    warmup_duration: 60s
    third_party_mocks: required       # Stripe, Twilio, SendGrid, etc.
    generator_location: separate-host  # same-host | separate-host | cloud

  ci_tier: pr-smoke | nightly | release
```

Required keys: `scope`, `stack`, `slos`, `concurrency_targets`, `resource_budgets`, `acceptance_criteria`, `test_environment`, `ci_tier`. `frontend_slos` is required only when `scope` covers a user-facing UI.

---

## Generation Rules — Contract → Scripts

Given a filled contract, scaffold the scripts under `scripts/` as follows:

| Contract field | Drives | Script |
|---|---|---|
| `slos.api_latency_p95.target` | `P95_MS` env | `k6-template.js`, `locust-template.py` |
| `slos.api_latency_p99.target` | `P99_MS` env | `k6-template.js` |
| `slos.error_rate.target` | `ERROR_RATE` env | `k6-template.js`, `locust-template.py` |
| `concurrency_targets.expected_users` | `VUS` (k6) / `-u` (locust) | both |
| `concurrency_targets.peak_users` | stress / spike scenarios | `k6-template.js` (scenarios) |
| `ci_tier == "pr-smoke"` | `SCENARIO=smoke`, 1–2 min | `k6-template.js` |
| `ci_tier == "nightly"` | `SCENARIO=load`, 5–15 min | `k6-template.js` / `locust-template.py` |
| `ci_tier == "release"` | `SCENARIO=soak` or `spike`, 1–4 h | `k6-template.js` |
| `frontend_slos.lcp_p75_ms` | `LCP_MS` env | `playwright-perf-template.ts`, `lighthouse-ci-template.js` |
| `frontend_slos.cls_p75` | `CLS` env | `playwright-perf-template.ts`, `lighthouse-ci-template.js` |
| `frontend_slos.inp_p75_ms` | `INP_MS` env | `playwright-perf-template.ts`, `lighthouse-ci-template.js` |
| `test_environment.tier` | `PERF_ENV` env (required in every script) | all |
| `test_environment.warmup_duration` | `WARMUP` env | `k6-template.js` |

---

## Capacity JSON Envelope

The load tools emit and `scripts/capacity-model.py` consumes the following JSON. This schema is the bridge between load-testing.md and capacity-planning.md. See `capacity-planning.md` § Capacity JSON schema for the normative specification.

```json
{
  "test_metadata": {
    "duration_seconds": 600,
    "scenario": "ramp-to-failure",
    "warmup_seconds": 60,
    "tool": "k6"
  },
  "measurements": [
    {
      "resource": "cpu",
      "ceiling": 100,
      "current_load": 45,
      "per_user_cost": 0.6,
      "measurement_window_seconds": 60,
      "p50": 38,
      "p95": 72,
      "p99": 89
    }
  ],
  "concurrency_observed": {
    "users": 50,
    "concurrent_processes_per_user_avg": 3.2
  }
}
```

Allowed `resource` values: `cpu`, `memory`, `db_connections`, `worker_threads`, `network_bandwidth`, `external_api_quota`. Any other value fails `capacity-model.py` validation.

---

## Pre-flight Checklist

Before a contract is considered ready for execution:

1. [ ] `test_environment.tier` is NOT production and is reachable from the load generator
2. [ ] `test_environment.third_party_mocks` are in place — verified by a smoke run that hits no external billable endpoints
3. [ ] `dataset_volume` matches production shape (volume and distribution, not just row count)
4. [ ] SLO targets are written down, not inferred from existing measurements
5. [ ] All `resource_budgets` entries exist even if the value is `n/a` (force the conversation)
6. [ ] CI tier matches the test duration: PR smoke ≤ 5 min, nightly ≤ 30 min, release ≤ 4 h

See `test-reality-model.md` for the full pre-flight protocol.

---

## Acceptance Criteria Grammar

`acceptance_criteria` accepts a small list of named conditions:

| Condition | Meaning |
|---|---|
| `all_slos_met_under_peak_load` | Every SLO passes during the peak-user stage |
| `no_resource_budget_exceeded` | p95 of each `resource_budgets` entry stays under target |
| `error_rate_unchanged_under_load` | Error rate at peak does not exceed baseline error rate + 0.1 pp |
| `no_memory_leak_over_soak` | Memory p95 at end-of-soak ≤ p95 at start-of-soak + 10% |
| `recovery_within_30s_post_spike` | p95 returns to baseline ±20% within 30 s of spike end |
| `cwv_pass_at_p75` | Frontend SLOs hold at p75 across the configured iteration count |

Callers may add domain conditions (e.g. `queue_depth_bounded_at_peak`); any unknown condition surfaces in the synthesis section as an unverified manual check.

---

## Example — Minimal API Contract

```yaml
contract:
  scope: component:orders-api
  stack: python-flask
  slos:
    - metric: api_latency_p95
      target: 150ms
      measurement_window: 5min
    - metric: error_rate
      target: <0.1%
      measurement_window: 5min
  concurrency_targets:
    expected_users: 200
    peak_users: 600
    expected_concurrent_processes_per_user: 2
  resource_budgets:
    cpu_p95: 70%
    memory_p95: 75%
    db_connections_p95: 50%
  acceptance_criteria:
    - all_slos_met_under_peak_load
    - no_resource_budget_exceeded
  test_environment:
    tier: preprod
    dataset_volume: production-shape
    warmup_duration: 60s
    third_party_mocks: required
    generator_location: separate-host
  ci_tier: nightly
```

From this, generate:

```bash
PERF_ENV=preprod \
TARGET_URL=https://preprod.example.com/orders \
VUS=200 DURATION=5m P95_MS=150 ERROR_RATE=0.001 \
k6 run scripts/k6-template.js
```

Then feed the resulting `capacity-input.json` to `capacity-model.py` to produce the headroom report.

---

## Anti-patterns

| Don't | Why |
|---|---|
| Treat the contract as "we'll fill it in later" | A missing SLO means every number is negotiable after the fact |
| Copy targets from the existing baseline | Baseline documents current behaviour, not acceptable behaviour |
| Omit `resource_budgets` because "we only care about latency" | Latency SLOs pass right up to the moment the resource ceiling breaks |
| Let the contract drift from the scripts | Re-generate scripts from contract on every change; do not hand-edit |
| Keep the contract out of version control | Contracts are the perf spec; review them like API specs |
