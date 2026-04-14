# Workload Taxonomy

Reference file for `performance` skill. Performance approach depends on the shape of the workload, not just the language stack. Pick the row that matches the system under test; route to the linked sub-skill and template.

---

## Taxonomy Table

| Workload | Key metrics | Test approach | Tools | Sub-skill | Template |
|---|---|---|---|---|---|
| HTTP API (sync) | latency p50/p95/p99, throughput (RPS), error rate, connection reuse | smoke → load → stress ramp, constant-rate for SLA | k6, Locust, Artillery, hey, vegeta | `load-testing.md` | `scripts/k6-template.js`, `scripts/locust-template.py` |
| Browser / SPA | LCP p75, CLS p75, INP p75, TTI, JS heap | Lighthouse CI (lab), Playwright programmatic CWV, RUM for field | Lighthouse CI, Playwright, web-vitals lib | `frontend-performance.md` | `scripts/lighthouse-ci-template.js`, `scripts/playwright-perf-template.ts` |
| Background jobs / queues | producer throughput, queue depth, consumer processing latency, redelivery rate | burst producer + monitor consumer scaling; soak for leaks | k6 (for publishing API), queue-native tools (rabbitmqadmin, kafka-producer-perf-test), custom drainers | `load-testing.md` (+ queue section) | `scripts/k6-template.js` for producer; hand-rolled consumer harness |
| Cron / batch | total runtime, resource peak (CPU/memory/disk I/O), output size | scheduled run against production-shape dataset with full monitoring | time wrappers, language profilers (`profiling.md`), APM | `profiling.md` for hotspots, `capacity-planning.md` for resource peaks | none (batch is one-shot; run with monitoring) |
| WebSocket | connection count ceiling, message latency, throughput, reconnect storm behaviour | persistent-connection ramp + message burst + disconnect storm | k6 ws module, Artillery engines (ws/socketio), custom Go clients | `load-testing.md` (+ protocol-specific notes) | `scripts/k6-template.js` extended with `k6/ws` |
| Streaming (SSE, gRPC streaming) | message rate, backpressure handling, stream-establishment time | sustained stream + artificially-slow consumer to test flow control | k6 (gRPC, SSE), custom grpcurl scripts | `load-testing.md` | `scripts/k6-template.js` (swap HTTP for gRPC scenario) |
| Cache-heavy | hit ratio, cold-cache latency, eviction rate, memory residency | warm vs cold scenarios, eviction stress, cache-miss storm | redis-benchmark, memtier_benchmark, custom scripts that bypass cache | `database.md` (data-tier caches), `load-testing.md` (app caches) | none canonical; parameterise from contract |
| Database-bound | query latency p95, plan stability, pool usage, lock contention | query-level profiling + pool saturation load | EXPLAIN ANALYZE, pg_stat_statements, slow-query logs | `database.md` | n/a — query-level |
| CPU-bound compute (ML, encode, crypto) | wall time, CPU%, saturation, vectorisation efficiency | single-request profile then parallel replicas for scaling test | language profilers, `perf`, `py-spy`, async-profiler | `profiling.md` | n/a |
| Memory-bound / leak-prone | RSS growth, GC frequency, peak working set, soak-end delta | long soak with memory sampling at fixed interval | memory profilers (heaptrack, tracemalloc, JFR), APM memory panels | `profiling.md`, soak scenario from `load-testing.md` | `scripts/k6-template.js` with `SCENARIO=soak` |
| External-API-bound | upstream latency, retry/backoff behaviour, quota utilisation | test with mocked upstream at realistic latency + failure injection | mocked upstreams (WireMock, mountebank), Chaos tools | `load-testing.md` (+ mocks per `test-reality-model.md`) | `scripts/k6-template.js` pointed at mock |

---

## Routing Decision Tree

```
What is the request path dominated by?

  HTTP request/response cycle
    ├── sync response to a browser user  → HTTP API row + Browser row (both)
    ├── sync API consumed by another service → HTTP API row only
    └── WebSocket/SSE/gRPC streaming     → streaming rows

  Queue enqueue → deferred work
    └── Background jobs row

  Scheduled invocation (cron, airflow)
    └── Cron / batch row

  One-shot heavy compute (ML inference, render, encode)
    └── CPU-bound compute row (plus HTTP row for the API in front of it)

  Any request that spends >30% of its budget in a database call
    → plus Database-bound row

  Any request whose cache-hit ratio dominates behaviour
    → plus Cache-heavy row
```

A single system typically matches 2–3 rows. Apply all relevant rows — the key metrics are additive, not mutually exclusive.

---

## Workload-Specific Pre-flight Additions

On top of the mandatory `test-reality-model.md` pre-flight:

| Workload | Extra pre-flight |
|---|---|
| Background jobs | Consumer is running, healthy, and at expected replica count; dead-letter queue is empty |
| WebSocket | OS `nofile` / ephemeral-port range sized for the target connection count on the generator host |
| Streaming | Proxy / LB idle timeout exceeds the stream duration |
| Cache-heavy | Cold-cache test starts from flushed cache; warm-cache test starts after documented warmup run |
| Database-bound | Statistics are fresh (ANALYZE/ANALYZE TABLE); no long-running transaction blocking |
| External-API-bound | Mocks are live, not the real upstream; verified by a probe call |
| Cron / batch | Upstream data dependencies are at representative volume for the run window |

---

## Sub-skill Coverage Map

| Sub-skill | Owns | Does not own |
|---|---|---|
| `profiling.md` | CPU/memory profiling, flame graphs, hotspot identification | Load testing, capacity math, frontend CWV |
| `load-testing.md` | Smoke/load/stress/spike/soak scenarios, capacity validation patterns, SLA determination | Profiling internals, frontend CWV, query optimisation |
| `database.md` | Query analysis, N+1 detection, indexes, pool monitoring | Load generation, application profiling, frontend |
| `frontend-performance.md` | CWV (LCP/CLS/INP), animation smoothness, Lighthouse CI, Playwright CWV | Server-side load, query optimisation, capacity math |
| `capacity-planning.md` | Headroom math, contention scenarios, resource-first forecast | Generating load; it consumes load-test output |

If the workload does not match any row, surface it as a gap: log the signal in `_meta/perf-findings.jsonl` with `finding_type: "workload-gap"` and consider whether a new taxonomy row is warranted.

---

## Anti-patterns

| Don't | Why |
|---|---|
| Treat "it's HTTP" as enough to pick a scenario | A bulk-upload endpoint and a read-heavy list endpoint need different mixes |
| Use one load profile for all rows | Queue producers do not behave like sync APIs; soak reveals different problems than spike |
| Apply CWV tests to a JSON-only API | LCP/CLS/INP are visual — they are undefined for non-rendered content |
| Mix workload types in one contract | Keep one contract per workload; bundle reports after, not before |
| Forget that a single request can span multiple rows | An SSR-rendered product page is HTTP + Browser + Database — all three apply |
