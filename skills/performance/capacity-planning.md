# Capacity Planning

Reference file for `performance` skill. Theoretical headroom math and contention modelling. Consumes load-test output from `load-testing.md` and produces a capacity-model report. Does NOT generate load — test generation is owned by `load-testing.md`.

---

## Scope

Capacity planning answers two questions:

1. **Headroom**: how many additional users / requests / jobs can the current system absorb before any resource hits its ceiling?
2. **Contention**: when multiple workloads share a resource, how do they compete and at what point does one starve another?

Inputs:
- A JSON envelope conforming to § Capacity JSON schema (produced by `scripts/k6-template.js` or `scripts/locust-template.py` with server-side monitoring feeding the `measurements` array)
- Optionally, a growth target (e.g. "plan for +50% MAUs")

Output:
- `capacity-model.md` — tier inventory, per-operation cost, headroom per resource, forecast curves, recommended next load test

---

## Capacity Framing

State capacity in the axes users and product teams actually think in before
running the math. Getting these right up front turns the subsequent
resource-ceiling analysis from a guess into a model.

| Axis | Unit | Example |
|---|---|---|
| Concurrent users | active sessions at p95 | "200 simultaneous editors" |
| Transactions per second | steady-state TPS | "50 TPS avg, 200 TPS peak" |
| Long-running processes | worker / consumer count | "8 Celery workers, 2 streaming consumers" |
| Batch jobs | count × window × duration | "3 nightly ETLs, 2h window, 45 min each" |
| Scheduled jobs | cadence × duration | "every 5 min, <10s each, up to 12 concurrent" |

The headroom math below is only meaningful once these axes are filled in.
DAU / MAU are not substitutes for concurrent-at-p95 — monthly actives
overestimate peak concurrency by 10-100x on most systems. TPS must be
both steady-state AND peak-burst; systems that handle the average but
fall over during bursts are the default failure mode.

For the capture path, see `references/capacity-questionnaire.md`.

---

## Architecture-Based Capacity Model

Before running the math, enumerate the request flow and the cost of each operation at each tier:

```
Request
  → Ingress / LB          (ceiling: connections, TLS handshakes/sec)
  → App worker            (ceiling: CPU, memory, worker count)
  → Cache (Redis / CDN)   (ceiling: memory, network, ops/sec)
  → Database              (ceiling: CPU, connections, disk I/O)
  → External API          (ceiling: quota, rate limit)
  → Queue                 (ceiling: broker throughput, consumer rate)
```

Per operation, estimate or measure:

| Tier | Cost unit | Typical measurement |
|---|---|---|
| LB / ingress | connection | concurrent TCP/TLS |
| App | CPU seconds | per-request CPU% × request time |
| App | memory | RSS per worker |
| Cache | ops/sec, bytes | Redis `INFO stats` |
| DB | connections, CPU, disk I/O | pg_stat_activity, iostat |
| External API | quota | provider dashboard |
| Queue | in-flight messages | broker admin API |

This enumeration is the backbone of the model — the subsequent math is only as good as this inventory.

---

## Resource Ceiling Identification

For each resource, identify its ceiling:

| Resource | Ceiling source |
|---|---|
| CPU | `nproc` × 100% (or reservations / limits in k8s) |
| Memory | host RSS budget minus OS reservation |
| DB connections | Postgres `max_connections` ÷ app instances; MySQL `max_connections`; MongoDB `maxPoolSize` |
| Worker threads / pool | uWSGI `processes × threads`, Gunicorn `workers`, PM2 instances, Tomcat `maxThreads` |
| Network bandwidth | instance network limit (varies by cloud provider SKU) |
| External API quota | provider per-minute / per-day limit |
| Queue broker throughput | broker benchmark at the current config |

A ceiling is not "the number the tool reports right now" — it's the documented limit before degradation. Where the two differ (e.g. a DB pool set to 20 against a DB supporting 100), the pool is the operational ceiling.

---

## Headroom Math

The core calculation:

```
additional_users = (ceiling - current_load) / per_user_cost
```

For each resource, `scripts/capacity-model.py` reports `additional_users` given `current_load` and `per_user_cost`. The lowest value across all resources is the overall headroom — capacity is limited by the first resource to hit its ceiling.

Caveats:
- `per_user_cost` is a linear approximation. Real systems have non-linear effects near the ceiling (queueing, GC pressure, lock contention). Treat the number as a planning floor, not an SLA.
- Measurements must be taken at a stable load point (post-warmup, before saturation) for the cost estimate to be valid.
- Zero `per_user_cost` means "adding more users does not change this resource's load" — usually it means the cost is genuinely zero (e.g. startup-only) or the measurement window missed the cost.

---

## Contention Scenarios

Many performance puzzles disappear when one models who is competing for what.

### 1 user × N processes (process-bounded)

One user issues N concurrent requests (e.g. an admin running a batch import).

- Saturates per-user resources first (session memory, per-user DB connection quota)
- Often hits: worker-pool queueing (requests wait for free workers), per-user rate limits
- Fix targets: queue the work, split into sequential batches, raise per-user limits

### N users × M processes each (user-bounded)

Many users, each issuing a typical number of concurrent requests.

- Saturates global resources: DB connections, worker pool, network
- Often hits: DB `max_connections`, pool exhaustion, LB connection cap
- Fix targets: right-size pool, add pooler (pgbouncer), horizontal scale

### Mixed workload (compute vs I/O competing)

Interactive requests share workers with background jobs or reports.

- Saturates: worker pool (long-running jobs hold workers)
- Often hits: latency spikes in interactive requests when batch runs
- Fix targets: separate worker pools (queue-specific), isolate CPU-intensive endpoints, scheduling windows

The contention matrix should list, per resource:

| Resource | 1×N workload | N×M workload | Mixed workload |
|---|---|---|---|
| CPU | fast saturation | moderate | worst-case saturation |
| DB connections | one-user cap hit | global cap hit | connections held by batch |
| Worker threads | queueing per user | pool exhaustion | pool starvation |

---

## Forecasting

Projection: apply a growth factor to `current_load` for each resource and see which hits ceiling first.

```
projected_load[r] = current_load[r] × (1 + growth)
first_to_break   = argmax_r (projected_load[r] / ceiling[r])
```

`scripts/capacity-model.py --forecast-growth 0.5` returns the resource and its utilisation ratio. A utilisation ≥ 1.0 is a forecast breach.

Interpretation:

| projected / ceiling | Meaning |
|---|---|
| < 0.7 | comfortable headroom; no action |
| 0.7 – 0.85 | monitor; plan a capacity test to confirm |
| 0.85 – 1.0 | pre-saturation; fix before growth is realised |
| ≥ 1.0 | forecast breach; intervention required before this traffic lands |

Forecast curves are helpful when multiple growth scenarios are under discussion. Run the model at growth = 0.25, 0.5, 1.0 and compare.

---

## Capacity JSON Schema

This is the normative schema. `scripts/capacity-model.py` validates incoming files against it and rejects anything missing required fields or using an unknown `resource` name.

```json
{
  "test_metadata": {
    "duration_seconds": 600,
    "scenario": "ramp-to-failure",
    "warmup_seconds": 60,
    "tool": "k6 | locust"
  },
  "measurements": [
    {
      "resource": "cpu | memory | db_connections | worker_threads | network_bandwidth | external_api_quota",
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

Fields:

| Field | Required | Notes |
|---|---|---|
| `test_metadata.duration_seconds` | yes | total measurement duration |
| `test_metadata.scenario` | yes | free-form label matching load-testing.md scenarios |
| `test_metadata.warmup_seconds` | yes | warmup length (excluded from SLO math) |
| `test_metadata.tool` | yes | generator tool name |
| `measurements[].resource` | yes | allow-listed name; see above |
| `measurements[].ceiling` | yes | numeric ceiling in the native unit of the resource |
| `measurements[].current_load` | yes | observed load at steady state in the native unit |
| `measurements[].per_user_cost` | yes | marginal cost of adding one user in the native unit; 0 if truly independent |
| `measurements[].measurement_window_seconds` | yes | length of the steady-state sampling window |
| `measurements[].p50/p95/p99` | yes | percentile samples across the window |
| `concurrency_observed.users` | yes | observed user count at steady state |
| `concurrency_observed.concurrent_processes_per_user_avg` | no | null if unknown (load tool alone cannot observe this) |

---

## Validation Handoff

Capacity-model output is a model. Validate by running the predicted load:

1. `capacity-model.py` says: "DB connections will breach at +50% load."
2. `load-testing.md` designs a stepped-concurrency test at +50% load.
3. Run it. Compare observed pool saturation to the forecast.
4. Update the model if reality differs (usually `per_user_cost` was off).

See `load-testing.md` § Capacity Validation Patterns for the test shapes that validate each forecast type.

---

## Capacity Report Shape

`scripts/capacity-model.py` writes `capacity-model.md` with the following sections (also emitted by invoking this sub-skill directly):

```markdown
# Capacity Model

- Source tool, scenario, duration, warmup
- Observed users, concurrent processes per user

## Per-resource headroom
| resource | ceiling | current | per-user cost | p50 | p95 | p99 | additional users |

## Forecast at +<growth>% load
- First resource to be stressed
- Projected per-resource load table (breach flagged)

## Recommended next load test
- Ramp profile or stepped concurrency matching the forecast
- Cross-link to load-testing.md § Capacity Validation Patterns
```

---

## Synthesis & Improvements

For findings of type `headroom_exhausted` or `resource_ceiling_breach`, consult `references/improvement-catalog.md` filtered by the stressed resource:

- `db_connections` → § 4 Connection pooling, § 10 Read replicas, § 2 Query optimisation
- `worker_threads` → § 12 Right-sizing, § 5 Async processing
- `cpu` → § 5 Async, § 1 Caching, § 12 Scaling
- `memory` → leak review, § 12 Right-sizing, GC tuning
- `network_bandwidth` → § 6 Compression, § 7 CDN
- `external_api_quota` → § 5 Batching, provider upgrade

Stack-aware delegation: pair with the detected stack's domain skill (see `improvement-catalog.md` § Stack-aware delegation).

---

## Anti-patterns

| Don't | Why |
|---|---|
| Model capacity from averages | Ceilings hit during p95/p99 spikes, not on average |
| Assume linear scaling past 70% utilisation | Queueing and contention turn non-linear fast |
| Treat the model as an SLA | It's a planning floor; the load test is the evidence |
| Skip warmup when collecting `current_load` | Cold metrics pollute the cost estimate |
| Plan from CI-tier measurements for a release decision | CI tiers use smaller fixtures; load is not representative |
| Forecast past +100% without validating intermediate steps | Compound linear extrapolation past 1× traffic is usually wrong |
| Generate load scripts from here | That belongs to `load-testing.md`; this file consumes output |
