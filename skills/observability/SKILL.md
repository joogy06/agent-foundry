---
name: observability
description: >
  Use when designing what to emit (not how to deploy). Produces a signals
  map — SLIs, correlation IDs, span boundaries, alert classes, redaction
  rules, cardinality budget, ownership. Covers the four pillars
  (logging / metrics / tracing / alerting) unified under OTLP in 2026
  with vendor-neutral schemas. Callable by forge or standalone. Trigger
  on: "what should we instrument?", "define our SLIs", "design our
  signals", "add logging", "set up monitoring", "add tracing", "set up
  alerts", "observability contract". NOT for deploying Prometheus /
  Grafana / ELK — that's ubuntu-monitoring / rhel-monitoring. NOT for
  SLO governance — that's delivery-manager. NOT for SPL / vendor
  queries — that's splunk-developer.
---

# Observability — Signal Design

A signal-design primitive. Produces a **signals map** (`signals-map.yaml`) that
declares WHAT a service emits: Service Level Indicators, correlation IDs, span
boundaries, alert classes, redaction rules, cardinality budget, and ownership.
Vendor-neutral by construction: the map is consumed by whichever backend is
deployed (Prometheus+Grafana+Loki+Tempo, Datadog, Honeycomb, Dynatrace, Splunk
Observability, etc.).

**Scope.** Signal design only. Does NOT deploy telemetry infrastructure, does NOT
set SLO targets / error budgets, does NOT write vendor query languages. Those
responsibilities live in other skills (see Boundaries table below).

**Callers.**
- `forge` — Step 1 branching question routes here when the task changes runtime
  behavior, service boundaries, or SLOs. Signals map lands in `shared_context`
  as a constraint for design agents.
- standalone — user invokes directly with "design our signals for X" or one of
  the trigger phrases in the frontmatter.

---

## Core claim

**We own signal design. Platform deployment, SLO governance, and vendor queries
are owned by other skills.** Attempting to cover all three in one skill produced
a thin router in earlier iterations; this skill is scoped to the unique artifact
only — the signals map — because that is where the value lives and the other
skills already do the remaining work well.

---

## Boundaries (what this skill does NOT do)

| Responsibility | Owner | Why here is wrong |
|---|---|---|
| Platform deployment (install / systemd / daemon.json / agent rollout) | `ubuntu-monitoring`, `rhel-monitoring` | OS-dependent ops detail; signals-map is runtime-agnostic |
| SLO governance (targets, error budgets, burn-rate policy) | `delivery-manager` | SLIs defined here are INPUTS to SLOs; the policy layer is elsewhere |
| Vendor query languages (SPL, Datadog DQL, Kusto, LogQL dialects) | `splunk-developer`, per-vendor skills | Queries depend on the backend; signals-map is the contract each backend consumes |
| Capacity math / load testing | `performance` | Observability observes; performance predicts and validates |
| OS event / SIEM analysis | `windows-ps-security`, `rhel-monitoring` | Security observability has its own taxonomy (out of v1 scope) |

If a user asks "how do I install Prometheus on RHEL 9?" — redirect to
`rhel-monitoring`. If they ask "what should we instrument?" or "define our SLIs"
or "design our signals" — stay here.

---

## The four pillars, unified (2026 reality)

In 2020 logs, metrics, traces, and alerts were silos owned by separate vendors
and wired by hand. In 2026 they are **one OpenTelemetry Protocol (OTLP) stream**
with shared identity:

- **Structured JSON logs** carry `trace_id` + `span_id` alongside the message
- **Metrics** carry exemplars linking each bucket back to a sampled trace
- **Traces** propagate W3C Trace Context across every process hop (HTTP, gRPC,
  Kafka headers, Celery tasks, message envelopes)
- **Alerts** reference SLIs defined in metrics, and every alert has a runbook

The signals map declares these linkages explicitly — a service whose logs do
not carry `trace_id` or whose alerts do not reference runbooks is NOT complete
regardless of how much telemetry volume it emits.

The OTel Collector (sidecar or daemonset) is the common receive/transform/export
hop; which backend it exports to is a deployment decision that lives outside
this skill.

---

## Primary artifact — signals map

Every invocation of this skill produces a filled `signals-map.yaml`. Schema,
required fields, completeness-check procedure, and a fully-worked FastAPI
example: see [`references/signals-map-schema.md`](references/signals-map-schema.md).

Skeleton:

```yaml
schema_version: 1
service: <name>
owners: {team, slack, pagerduty}
generated_at: <iso8601>
generated_by: observability@<skill-version>

slis: [...]                 # SERVICE LEVEL INDICATORS (what is measured)
correlation_ids: {...}      # HEADER + generation + propagation channels
span_boundaries: [...]      # WHAT GETS TRACED (entry points and fan-outs)
alerts: [...]               # EACH references an SLI + has a runbook_ref
redaction_rules: [...]      # optional unless PII handling
cardinality_budget: {...}   # per-metric + per-label caps; exile rules
runbook_urls: [...]
```

The map is the handoff to every downstream consumer:

- **`performance` skill** reads `slis` + `span_boundaries` to know what to
  load-test against
- **`delivery-manager`** reads `slis` to attach SLO targets and error budgets
- **Platform teams** read `cardinality_budget` to cap metric labels before they
  explode storage costs
- **On-call engineers** read `alerts[].runbook_ref` to know what to do at 3am

---

## Invocation modes

### Standalone

User invokes the skill directly ("design our signals for checkout-api").
Procedure:

1. Load [`references/signals-questionnaire.md`](references/signals-questionnaire.md)
   and ask the five SRE gatekeeper questions in order (failure mode,
   collector presence, cardinality, backpressure, runbooks).
2. Run the schema-completeness check (every required field from the signals-map
   schema has a concrete value — no placeholders, no "TBD", no "unlimited").
3. Produce `signals-map.yaml` as a YAML code block in the response.
4. If ANY required field is missing a real value, STOP and report the gap
   rather than fabricate. HARD-RULE 3 applies.

### Called by forge

Forge Step 1 detects "changes runtime behavior, service boundaries, or SLOs"
and delegates here. Forge passes `shared_context` (problem statement,
component list, existing architecture notes). Procedure:

1. Read forge's `shared_context`; extract service name, teams, likely
   correlation header (`x-request-id` if none specified), framework hints.
2. Draft the signals map as a CONSTRAINT for the design agents that follow —
   they must respect it (e.g. if the map says `span_boundaries` includes
   `kafka-publish`, design agents cannot propose an async integration that
   skips tracing).
3. Ask only the SRE questions whose answers are not already implied by
   `shared_context`; do not re-ask what forge already captured.
4. Write the signals map to the path forge specifies (or
   `progress/signals-maps/<service>.yaml` by default) and return the path.

---

## HARD-RULEs

1. **No platform deployment.** If the user asks "how do I deploy Prometheus /
   Grafana / Loki / the OTel Collector on Ubuntu / RHEL", redirect to
   `ubuntu-monitoring` or `rhel-monitoring`. This skill does not cover
   installation, systemd units, daemon.json, or OS-level config.
2. **No SLO governance.** SLIs are defined here; SLOs (targets, error budgets,
   burn-rate policy, alert thresholds as policy) live in `delivery-manager`.
   The `alerts[]` section references SLIs; the TARGET each alert fires against
   (e.g. "2% budget burn in 1h") is a policy decision for delivery-manager.
3. **Required fields enforced.** The signals map MUST contain: `service`,
   `slis[]` (≥1), `correlation_ids.header`, `span_boundaries[]` (≥1),
   `alerts[]` (≥1 burn-rate alert if any SLI exists), `cardinality_budget`,
   `ownership.primary_team`, `runbook_urls[]` (≥1). A map missing any of these
   is incomplete; the skill must refuse a "complete" verdict and report the
   gap.
4. **Every alert has a runbook.** No `runbook_ref` = not a complete alert.
   Alerts without runbooks create pager fatigue, which creates alert apathy,
   which creates outages. If the runbook URL is not yet written, record the
   alert as `status: draft` and block completion — do not file a pointer to
   `TBD` or an internal wiki landing page that does not exist.
5. **Cardinality budget is declared, not discovered.** The map must state
   `per_metric_labels_max` and `per_label_distinct_values_max` as concrete
   integers. Claiming "unlimited" is incomplete. High-cardinality items
   (`user_id`, `request_id`, `session_id`, tenant IDs in large-tenant systems)
   go to tracing via `high_cardinality_exile_to: tracing`, NOT to metric
   labels. Discovering cardinality after a backend bill spike is the failure
   mode this rule prevents.

---

## Anti-patterns

| Don't | Why |
|---|---|
| Cardinality explosion — tag metrics with `user_id` or `request_id` | Unbounded label values turn one counter into millions of series; Prometheus OOMs or the SaaS bill triples. Exile per HARD-RULE 5 |
| Dashboard graveyard — ship 40-panel Grafana dashboards as the deliverable | Dashboards are a secondary consumer of signals, not the design. Start from SLIs + alerts; dashboards derive from them |
| ELK in 2026 (cargo-cult) — spec Elasticsearch / Logstash / Kibana because the playbook says so | In 2026 the default stack is OTLP → OTel Collector → (Prometheus / Loki / Tempo) or a SaaS (Datadog / Honeycomb). ELK still fits specific compliance cases but is not the default |
| CPU-threshold alerts without SLO linkage — "alert if CPU > 80%" | CPU at 80% is fine if latency is fine. Alert on USER-FACING failure (SLO burn rate), then investigate CPU as a cause. See HARD-RULE 2 |
| Traces that don't propagate headers — `trace_id` starts fresh at each service | Cross-service traces require W3C Trace Context forwarded through HTTP + message broker + task queue. Declare every hop in `correlation_ids.propagation` |
| `logger.info` in tight loops — emitting per-request debug logs in hot paths | At 1k RPS a tight-loop info log is 1k lines/sec = 86M lines/day = terabytes/month. Use DEBUG level + sampling, or move to tracing |
| Alerts without runbooks — ship an alert rule with a TODO for the runbook | Pager fatigue is the enemy. HARD-RULE 4: no runbook = not a complete alert |
| SLIs defined by what's easy to measure | Start from the user-visible failure mode ("checkout hangs", "page renders blank") and work backwards to the indicator that would catch it. "What's easy to measure" is how you end up with 200 dashboards nobody reads |

---

## References

- [`references/signals-map-schema.md`](references/signals-map-schema.md) —
  schema, required/optional fields, completeness check, FastAPI working example
- [`references/signals-questionnaire.md`](references/signals-questionnaire.md) —
  the five SRE gatekeeper questions + schema-completeness check

For infrastructure deployment: `ubuntu-monitoring` (Ubuntu 24.04) or
`rhel-monitoring` (RHEL 9). For SLO / error-budget policy: `delivery-manager`.
For SPL / Splunk-specific query work: `splunk-developer`. For load-test +
capacity math: `performance`.

---

## Out of scope (v1 spike)

Deferred per design §14 (2026-04-20): per-pillar references
(`logging.md` / `metrics.md` / `tracing.md` / `alerting.md`), stack
catalog (LGTM / Honeycomb / Datadog recipes), SIEM / security
observability, telemetry cost modeling, Python validator scripts, and
`delivery-manager` SLI↔SLO cross-link patches. v1 validation gate:
run this skill against 2-3 real services before investing in v1.1.
