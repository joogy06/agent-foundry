# Signals Questionnaire

Reference file for the `observability` skill. The five SRE gatekeeper questions
the skill asks during a standalone invocation (and uses to fill gaps when
called by forge), plus the schema-completeness check that follows.

These questions are deliberately small in number. Each one blocks a common
failure mode. If the user cannot answer a question, that is the signal —
record the gap and resolve it before claiming the signals map is complete.

---

## Gatekeeper questions

Each question follows this shape:

```yaml
id: <short-id>
label: <the question as asked to the user>
why_asked: <the failure mode this question prevents>
example_answer: <a concrete example of a good answer>
```

### Q1 — Failure mode

```yaml
id: failure-mode
label: >
  If this service is down or slow, what exactly does the user see?
why_asked: >
  SLIs defined from the outside-in (user-visible failure) catch the outages
  that matter. SLIs defined from the inside-out ("CPU high", "queue depth
  up") alert on causes that may or may not be visible to a user, producing
  pager fatigue. Starting from the user experience grounds every subsequent
  signal choice.
example_answer: >
  "A 5xx from POST /checkout means the cart fails to submit; user sees a
  generic error banner and has to retry. A slow response > 2s means the
  checkout button spinner hangs and ~8% of users abandon." Derived SLIs:
  api_availability (5xx rate), api_latency_p95, checkout_completion_rate.
```

### Q2 — Instrumentation

```yaml
id: otel-collector-presence
label: >
  Is the OpenTelemetry Collector (sidecar or daemonset) already in the
  infra spec for this environment, or does the signals map require one
  to be deployed?
why_asked: >
  The signals map assumes an OTLP stream exists. If no collector is
  deployed, the map is aspirational until platform work lands. This
  question surfaces the deployment dependency early so the handoff to
  ubuntu-monitoring / rhel-monitoring (or the SaaS agent rollout) is
  explicit rather than implicit.
example_answer: >
  "Yes, otel-collector runs as a daemonset on every node in prod + staging
  (managed by platform-team via ubuntu-monitoring). Dev environments
  don't have it yet — signals map for dev is deferred until Q3."
```

### Q3 — Cardinality

```yaml
id: cardinality-risk
label: >
  Which labels or attributes on the metrics you emit have a dynamic
  range greater than 1000 distinct values (e.g. user_id, request_id,
  tenant_id in multi-tenant systems, URL path if templated)?
why_asked: >
  Unbounded label cardinality is the #1 cause of observability-backend
  bill shock and OOM outages. Prometheus creates one time series per unique
  label combination; 1M users × 10 label values = 10M series per metric.
  HARD-RULE 5 requires cardinality be declared, and high-cardinality items
  exiled to tracing (where each span is independent, not aggregated).
example_answer: >
  "user_id unbounded (~2M users), tenant_id ~500, url_path ~80 after
  templating /users/{id} patterns. Plan: tenant_id goes in metric labels;
  user_id and request_id exile to tracing via high_cardinality_exile_to:
  tracing; url_path is pre-templated by the middleware."
```

### Q4 — Backpressure

```yaml
id: observability-backend-backpressure
label: >
  What happens to this service if the observability backend (collector,
  Prometheus, Loki, Tempo, or the SaaS agent) is down or throttled —
  does the app drop spans / logs / metrics, block on buffer, or OOM?
why_asked: >
  Observability should not take down the thing it observes. Naive
  instrumentation blocks on send or buffers unbounded until OOM. The
  OTel Collector's OTLP exporter has sending_queue + retry_on_failure +
  memory_limiter settings that turn this from "app outage during
  monitoring outage" into "brief metric gap". This question makes the
  policy explicit.
example_answer: >
  "OTel SDK uses a bounded queue (5000 spans, drop-on-full). Collector
  has memory_limiter set at 80% RAM with drop policy. App never blocks
  on export; worst case we lose 60s of telemetry during a backend blip
  — logged as a counter exemplar we can query after the fact."
```

### Q5 — Runbook

```yaml
id: runbook-per-alert
label: >
  Is there a concrete, non-placeholder URL to a Mitigation / Runbook
  document for every alert this service can fire?
why_asked: >
  HARD-RULE 4: no runbook = not a complete alert. Alerts without runbooks
  create pager fatigue ("I got paged at 3am, I don't know what to do"),
  which leads to alert apathy ("I got paged again, I'll silence it"),
  which leads to real outages being missed. A runbook_ref pointing to a
  wiki landing page that does not exist is equivalent to no runbook.
example_answer: >
  "Yes, each alert references a runbook under runbooks.acme.com/
  checkout-api/<alert-name>.md — each has: 1) what the alert means,
  2) how to confirm the incident is real vs a false positive, 3) first
  mitigation step, 4) escalation path. Drafted runbooks are status:draft
  and block the alert from shipping."
```

---

## Schema-completeness check

After the five questions are answered, the skill walks the 8-item
completeness check defined in [`signals-map-schema.md`](signals-map-schema.md#schema-completeness-check).
Each check names the required field and the HARD-RULE that demands it.

```
[ ] 1. service — non-empty string, lowercase-with-hyphens
[ ] 2. slis[] — ≥1 entry with name, definition, unit, signal_source, metric_name
[ ] 3. correlation_ids.header — non-empty string
[ ] 4. span_boundaries[] — ≥1 entry from the known boundary vocabulary
[ ] 5. alerts[] — ≥1 entry; EVERY alert has runbook_ref; each SLI has a
       slo-burn-rate alert referencing it (HARD-RULE 4)
[ ] 6. cardinality_budget — per_metric_labels_max + per_label_distinct_values_max
       + high_cardinality_exile_to, all concrete (HARD-RULE 5)
[ ] 7. ownership.primary_team — non-empty string
[ ] 8. runbook_urls[] — ≥1 concrete URL (not a TODO / TBD / non-existent
       wiki page)
```

If ANY check fails, the skill's response is:

> "Signals map is INCOMPLETE. Passing: N/8. Blocking gaps: [list item
> numbers and field names]. Next step: resolve the following before
> calling this map production-ready: [gap-specific guidance]."

This is the standalone failure mode. When called by forge, the same rule
applies — the map is written with `status: draft` in its header, forge
is told which fields are unresolved, and design agents receive it as a
PARTIAL constraint with the unresolved axes called out.

The five questions run user-outward → infrastructure-inward (failure
mode → collector → cardinality → backpressure → runbook). Reordering is
fine; skipping any is not.
