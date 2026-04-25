# Signals Map Schema

Reference file for the `observability` skill. Defines the `signals-map.yaml`
contract: structure, required vs optional fields, completeness check procedure,
and a fully-worked FastAPI example the skill can use as a template.

---

## Purpose

The signals map is the vendor-neutral artifact that declares WHAT a service
emits. It is consumed by:

- Platform teams that deploy the backend (Prometheus / Loki / Tempo / OTel
  Collector, or a SaaS equivalent)
- `delivery-manager` to attach SLO targets and error budgets to each SLI
- `performance` to know what to load-test against
- On-call engineers who read `alerts[].runbook_ref` at 3am

A map that passes the completeness check below is the contract. A map that does
not pass is a draft; the skill reports the gap rather than produce it.

---

## Schema structure

```yaml
schema_version: 1                # integer, currently 1
service: <name>                  # lowercase-with-hyphens identifier
owners:
  team: <team-name>              # owning team name
  slack: "#channel"              # on-call Slack channel
  pagerduty: <url>               # PagerDuty service URL (or equivalent)
repository: <url>                # optional but recommended
generated_at: <iso8601>          # e.g. 2026-04-20T00:00:00Z
generated_by: observability@<skill-version>

slis:                            # list, ≥1 entry
  - name: <identifier>           # e.g. api_availability
    definition: <text>           # human-readable, 1 sentence, no jargon
    unit: ratio | milliseconds | count | bytes_per_second | ...
    signal_source: metric | metric_histogram | log_derived | trace_derived
    metric_name: <otlp metric name>

correlation_ids:
  header: <header name>          # e.g. x-request-id
  generation: <scheme>           # w3c-trace-context | custom | uuidv4
  propagation:                   # list of transport hops
    - http
    - celery-task
    - kafka-header
    - grpc-metadata
    - redis-stream

span_boundaries:                 # list, ≥1 entry, what gets traced
  - http-entry
  - db-query
  - redis-call
  - external-api-call
  - message-publish
  - message-consume

alerts:                          # list, ≥1 burn-rate alert per SLI
  - class: slo-burn-rate | saturation | absence | anomaly
    sli_ref: <sli name>          # required for slo-burn-rate class
    window: multi-window-multi-burn-rate | 5m | 1h | 24h
    severity: page | ticket | info
    runbook_ref: <url>           # REQUIRED — HARD-RULE 4
    metric: <metric name>        # required for saturation/anomaly classes
    threshold: <expression>      # required for saturation/anomaly classes

redaction_rules:                 # optional unless PII handled
  - field: <field name>
    rule: hash-sha256 | drop | mask | encrypt

cardinality_budget:              # REQUIRED — HARD-RULE 5
  per_metric_labels_max: <int>   # e.g. 1000
  per_label_distinct_values_max: <int>  # e.g. 100
  high_cardinality_exile_to: tracing | logs | dropped

ownership:
  primary_team: <team name>
  slack_channel: <channel>
  pagerduty: <url>

runbook_urls:                    # ≥1 entry; service-level landing page
  - <url>
```

---

## Required vs optional fields

### Required (HARD-RULE 3)

The signals map MUST contain concrete values for all of these. `TBD`,
`TODO`, empty strings, and null values are all equivalent to missing.

1. `service` — the service identifier
2. `slis[]` — at least one SLI
3. `correlation_ids.header` — the propagated header name
4. `span_boundaries[]` — at least one span boundary
5. `alerts[]` — at least one alert IF any SLI exists (burn-rate class
   required for each SLI that is not explicitly marked
   `alerting: deferred`)
6. `cardinality_budget` — both `per_metric_labels_max` and
   `per_label_distinct_values_max` as concrete integers
7. `ownership.primary_team` — team name
8. `runbook_urls[]` — at least one service-level runbook URL

### Optional

- `repository` — recommended, not blocking
- `redaction_rules` — required only if the service handles PII per project
  policy. If the service handles PII and no rules are specified, the map is
  incomplete.
- `owners.pagerduty` — recommended; may be an empty string for pre-launch
  services, but must be filled by production handoff
- Per-alert `metric` and `threshold` fields — required only for the
  `saturation` / `anomaly` classes (not for `slo-burn-rate` which uses
  `sli_ref` + `window`)

---

## Schema-completeness check

Before reporting the map complete, the skill walks the following 8-item
checklist. Any failing item blocks completion; the skill reports the specific
gap rather than producing a "ship-ready" verdict.

```
[ ] 1. service — non-empty string, lowercase-with-hyphens form
[ ] 2. slis[] — length ≥ 1; each entry has name, definition, unit,
       signal_source, metric_name (all non-empty, no placeholders)
[ ] 3. correlation_ids.header — non-empty string
[ ] 4. span_boundaries[] — length ≥ 1; each entry is a known boundary
       name from {http-entry, http-egress, db-query, redis-call,
       external-api-call, message-publish, message-consume,
       celery-task-execute, scheduled-job, grpc-call, graphql-field}
[ ] 5. alerts[] — length ≥ 1; EVERY alert has a non-empty runbook_ref;
       for each SLI there is at least one slo-burn-rate alert
       referencing it by sli_ref
[ ] 6. cardinality_budget.per_metric_labels_max — positive integer
       AND cardinality_budget.per_label_distinct_values_max — positive
       integer AND cardinality_budget.high_cardinality_exile_to — one
       of {tracing, logs, dropped}
[ ] 7. ownership.primary_team — non-empty string
[ ] 8. runbook_urls[] — length ≥ 1; each entry is a concrete URL,
       not a pointer to an internal wiki landing page that does not
       exist (HARD-RULE 4)
```

When reporting, the skill surfaces the count of passing items (e.g.
"6 / 8 checks passed; blocking gaps: items 5, 8"). The gap message names the
missing field and quotes the HARD-RULE that requires it.

---

## Working example — FastAPI checkout-api

Fully filled, passes all 8 checks. The skill uses this as a template — replace
names, URLs, and specific values to match the service at hand, but keep the
structure.

```yaml
schema_version: 1
service: checkout-api
owners:
  team: platform-team
  slack: "#platform-oncall"
  pagerduty: https://acme.pagerduty.com/services/P12345
repository: https://github.com/acme/checkout-api
generated_at: 2026-04-20T00:00:00Z
generated_by: observability@1.0.0-spike

# Service Level Indicators — what we MEASURE.
# SLOs governing these live in delivery-manager (HARD-RULE 2).
slis:
  - name: api_availability
    definition: "5xx rate < 0.1% over 5m rolling window"
    unit: ratio
    signal_source: metric
    metric_name: http_requests_total
  - name: api_latency_p95
    definition: "p95 request latency < 250ms over 5m rolling window"
    unit: milliseconds
    signal_source: metric_histogram
    metric_name: http_request_duration_seconds
  - name: checkout_completion_rate
    definition: "% of checkout-start requests that reach checkout-complete within 10m"
    unit: ratio
    signal_source: trace_derived
    metric_name: checkout_funnel_completion_total

# Correlation — how signals thread across async boundaries.
# Every hop in propagation[] is a place we MUST forward the header.
correlation_ids:
  header: x-request-id
  generation: w3c-trace-context
  propagation:
    - http
    - celery-task
    - kafka-header
    - grpc-metadata

# Span boundaries — what gets traced. Missing a boundary here = a blind spot.
span_boundaries:
  - http-entry
  - db-query
  - redis-call
  - external-api-call
  - message-publish
  - message-consume

# Alert classes — each references an SLI AND has a runbook (HARD-RULE 4).
alerts:
  - class: slo-burn-rate
    sli_ref: api_availability
    window: multi-window-multi-burn-rate
    severity: page
    runbook_ref: https://runbooks.acme.com/checkout-api/availability
  - class: slo-burn-rate
    sli_ref: api_latency_p95
    window: multi-window-multi-burn-rate
    severity: ticket
    runbook_ref: https://runbooks.acme.com/checkout-api/latency
  - class: slo-burn-rate
    sli_ref: checkout_completion_rate
    window: 1h
    severity: page
    runbook_ref: https://runbooks.acme.com/checkout-api/completion-rate
  - class: saturation
    metric: redis_connections_in_use
    threshold: "> 80% of pool"
    severity: ticket
    runbook_ref: https://runbooks.acme.com/checkout-api/redis-saturation
  - class: saturation
    metric: postgres_connections_used
    threshold: "> 85% of max_connections"
    severity: ticket
    runbook_ref: https://runbooks.acme.com/checkout-api/db-saturation

# Data hygiene — PII and secrets out of logs/metrics/traces.
redaction_rules:
  - field: email
    rule: hash-sha256
  - field: api_key
    rule: drop
  - field: payment_card_number
    rule: drop
  - field: session_cookie
    rule: drop
  - field: authorization_header
    rule: drop

# Cardinality budget — declared, not discovered (HARD-RULE 5).
cardinality_budget:
  per_metric_labels_max: 1000
  per_label_distinct_values_max: 100
  high_cardinality_exile_to: tracing  # user_id, request_id, tenant_id → traces

# Ownership and operations.
ownership:
  primary_team: platform-team
  slack_channel: "#platform-oncall"
  pagerduty: https://acme.pagerduty.com/services/P12345
runbook_urls:
  - https://runbooks.acme.com/checkout-api/
```

### Verifying the example against the 8-item check

All 8 checks pass: `service` present (check 1); 3 SLIs with all fields
filled (2); `correlation_ids.header` is `x-request-id` (3); 6 known span
boundaries (4); 5 alerts, each with runbook_ref, each of the 3 SLIs has
a slo-burn-rate alert (5); cardinality budget is 1000/100 with
tracing-exile (6); primary_team is `platform-team` (7); one concrete
runbook URL (8). Result: 8/8 — complete, ready for platform handoff.

Backend-specific configuration (Prometheus / Grafana / Loki / Tempo or a
SaaS equivalent) is produced from this map by the deployment skill; see
the Boundaries table in the observability SKILL.md for the routing.
