# Capacity Questionnaire

Reference file for the `performance` skill. The eight capacity-axis questions
the skill asks when invoked to build or review a capacity model. The answers
are the inputs the headroom math in `capacity-planning.md` consumes; without
them the math is running on guesses.

These questions are deliberately framed in the axes product teams and on-call
engineers actually think in (users, TPS, processes, jobs) rather than the
internal resources (CPU, memory, DB connections). The resource axes come from
`capacity-planning.md` § Architecture-Based Capacity Model; the axes below are
the user-facing demand side.

---

## Question format

Each question follows this shape:

```yaml
id: <short-id>
label: <the question as asked to the user>
why_asked: <what the answer unlocks in the capacity model>
example_answer: <a concrete example of a good answer>
```

---

## The eight capacity questions

### Q1 — Concurrent users at peak

```yaml
id: concurrent-users-peak
label: >
  At peak, how many users have an active session at the same moment
  (p95 simultaneous, not monthly actives)?
why_asked: >
  Concurrent users (not DAU, not MAU) drive session memory, open WebSocket
  count, and per-user DB connection demand. Using DAU or MAU overestimates
  peak load by 10-100x; using concurrent-at-p95 grounds the model in the
  actual contention shape.
example_answer: >
  "~200 simultaneous editors at p95 during business hours (EU + US overlap,
  14:00-16:00 UTC). Peak observed via session-count metric; spikes to ~350
  during weekly release demo."
```

### Q2 — Steady-state TPS

```yaml
id: steady-state-tps
label: >
  What is the sustained, averaged-over-15-minutes transactions-per-second
  rate during normal business hours?
why_asked: >
  Steady-state TPS is the baseline the system must handle without
  degradation. Per-request CPU cost × steady TPS gives baseline CPU
  utilization; per-request DB query count × steady TPS gives baseline
  DB load.
example_answer: >
  "50 TPS avg over the 14:00-16:00 UTC business window. Measured over
  last 30 days, p50 window-averaged. Off-hours drops to ~5 TPS."
```

### Q3 — Peak-burst TPS

```yaml
id: peak-burst-tps
label: >
  What is the maximum TPS observed during a spike, and how long does
  the spike last (e.g. "3x steady for 2 minutes")?
why_asked: >
  Headroom math must size for the BURST, not the average. A system that
  handles 50 TPS steady but OOMs at 200 TPS burst fails during the events
  that matter. Burst shape (duration × multiplier) determines whether
  buffering / autoscaling can absorb it or whether the system must be
  sized for peak.
example_answer: >
  "Peak ~200 TPS (4x steady) for 2-3 minutes during marketing email sends
  at 10:00 UTC Tuesdays + Thursdays. Also observed 10x for ~30s at
  launch events (quarterly). Currently absorbed via HPA + queue; latency
  p95 degrades from 120ms to 400ms during bursts."
```

### Q4 — Batch jobs

```yaml
id: batch-jobs
label: >
  What batch jobs run against this system — count, window (when they run),
  and duration each?
why_asked: >
  Batch jobs are the most common cause of "the database slowed down at
  3am last night and nobody knows why" incidents. They consume DB
  connections, hold long-running queries, and compete with interactive
  traffic if the windows overlap. The model needs them explicit.
example_answer: >
  "3 nightly ETLs: user-aggregates (02:00-04:00 UTC, ~2h), report-rollups
  (04:00-05:00 UTC, ~45min), cleanup (05:00-05:15 UTC, ~15min). All hit
  the primary DB. No overlap with EU business hours (~07:00 UTC start)."
```

### Q5 — Scheduled jobs

```yaml
id: scheduled-jobs
label: >
  What scheduled (cron-like) jobs run — cadence, duration, and expected
  concurrency (how many can be running at once)?
why_asked: >
  Scheduled jobs at high cadence (every 1m, 5m) can silently consume
  steady-state capacity. "Every 5m, <10s each, up to 12 concurrent"
  means 24 job-seconds per minute — 40% of a single worker's time just
  in scheduled work.
example_answer: >
  "poll-external-api every 5 min, <10s per run, up to 12 concurrent
  (one per tenant). refresh-cache every 1 min, <2s, single instance.
  reconcile-webhooks every 15 min, ~30s, single instance."
```

### Q6 — Long-running processes

```yaml
id: long-running-processes
label: >
  How many long-running processes (workers, consumers, daemons) does
  this service operate alongside the request-serving app, and what do
  they consume?
why_asked: >
  Celery workers, Kafka/pubsub consumers, streaming daemons all
  pre-allocate DB connections, memory, and sometimes a full worker
  slot. They are often forgotten in capacity math because they are not
  request-serving; including them prevents "we scaled the API but the
  workers OOMed" surprises.
example_answer: >
  "8 Celery workers (4 per availability zone) for async tasks, each
  holding 2 DB connections + ~400MB RSS. 2 Kafka consumers for event
  stream, each 1 DB connection + ~200MB RSS. 1 scheduler daemon,
  negligible resource use."
```

### Q7 — Data volume per user

```yaml
id: data-volume-per-user
label: >
  Per user (or per tenant, whichever is the primary quota unit), what
  data volume does the system store — row count, blob size, retention?
why_asked: >
  Per-user storage × user count forecasts disk growth and backup size.
  This is the axis that turns "we have 10,000 users" into "database is
  40TB in 12 months". Missing this turns capacity math into a
  compute-only exercise and ignores the storage tier.
example_answer: >
  "Per user: ~500 rows across primary tables, ~50MB blobs (profile +
  attachments), ~2GB logs (retained 30d then tiered to cold storage).
  Growth: each user generates ~100MB/month net new blobs."
```

### Q8 — Growth horizon

```yaml
id: growth-horizon
label: >
  What is the 12-month projection — expected % growth in users, TPS,
  data volume?
why_asked: >
  Headroom is a function of TIME. A system at 60% utilization today is
  a crisis in 6 months at +20%/month growth but comfortable at
  +2%/month. The growth rate picks the forecast horizon the capacity
  model should run against (see capacity-planning.md § Forecasting).
example_answer: >
  "Plan: +80% users, +60% TPS, +100% data volume over next 12 months.
  Scaling is nonlinear because enterprise customers (5-50x typical
  per-user volume) are the primary growth vector."
```

---

## For component-specific ceilings, defer to real load testing

No static stack-limits catalog in v1 (deferred per Codex challenger,
2026-04-20): capacity ceilings are architecture / deployment / workload
dependent, not framework dependent, so a "uWSGI handles N requests"
table would bit-rot into false alarms. The replacement is
`capacity-planning.md` § Resource Ceiling Identification plus
`load-testing.md` — capacity models are validated against a real load
test, not a lookup. Under-spec heuristics may be added in v1.1 after
3-5 real sessions surface recurring patterns. See `capacity-planning.md`
§ Validation Handoff for the loop: model → load test → compare → update.
