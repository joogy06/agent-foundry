---
name: splunk-developer
description: Use when developing Splunk searches, dashboards, and apps — SPL (Search Processing Language) queries, transforming commands (stats, chart, timechart, eval, rex, spath), knowledge objects (fields, lookups, event types, tags, data models), dashboards (Simple XML, Dashboard Studio), alerts and scheduled searches, data inputs (forwarders, HEC, scripted inputs, modular inputs), index-time vs search-time extractions, macros, workflow actions, custom Splunk apps, and REST API integration. Part of the observability-* skill family.
---

# Splunk Developer

For monitoring/alerting infrastructure see: `rhel-monitoring`, `ubuntu-monitoring`. For log analysis at scale see: `large-file-analysis`.

<HARD-RULE>
Always specify index and sourcetype in every search — searching across all indexes wastes resources and may return unexpected data from indexes you lack permissions to see properly.
</HARD-RULE>

<HARD-RULE>
Never use "join" when stats/eval can accomplish the same result — join is memory-intensive and fails on large datasets; use stats or eventstats instead.
</HARD-RULE>

<HARD-RULE>
Always use tstats with accelerated data models for high-frequency dashboards — raw searches against large indexes cause search concurrency issues.
</HARD-RULE>

<HARD-RULE>
Never store sensitive data (passwords, API keys) in dashboard XML or saved searches — use credential storage or encrypted inputs.
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [advanced-spl-apps-api-security.md](advanced-spl-apps-api-security.md) | advanced SPL patterns, app development, REST API usage, and security/compliance searches |
| [dashboards-alerts-inputs.md](dashboards-alerts-inputs.md) | knowledge objects, dashboard XML (Simple XML and Dashboard Studio), alerts/scheduled searches, and data inputs configuration |
| [spl-commands-extraction.md](spl-commands-extraction.md) | SPL query basics, transforming commands (stats, chart, timechart, eval, rex), data extraction patterns, and lookups |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using wildcards at the beginning of searches (`*error*`) | Splunk scans every event; bypasses index-time field extraction; search takes minutes instead of seconds | Use indexed fields, source, sourcetype, or index as primary filters; wildcards only at the end of terms |
| Running real-time searches on dashboards | Real-time searches consume persistent search slots; do not scale; cause scheduler congestion | Use scheduled searches with acceleration or 1-minute interval searches; real-time only for brief triage |
| Building dashboards without data models | Every panel runs its own raw search; inconsistent field names; no search optimization or acceleration | Create a data model with proper field extraction; build dashboards on pivot or `tstats` for 10-100x faster queries |
| Not using summary indexing for common aggregations | Repeated calculation of the same aggregation across millions of events; slow dashboards, wasted compute | Use `collect` or `tstats` summaries for frequently-queried metrics; pre-compute expensive aggregations |
| Extracting fields at search time when index-time would be appropriate | Search-time extraction runs on every query; high-volume fields waste CPU repeatedly | Use transforms.conf for high-value, high-volume fields; search-time extraction for ad-hoc or low-volume fields |

---

## Related Skills

| Workload | Skill |
|---|---|
| RHEL monitoring (Prometheus, Grafana, ELK) | `rhel-monitoring` |
| Ubuntu monitoring (Prometheus, Grafana, logging) | `ubuntu-monitoring` |
| Large file / log analysis | `large-file-analysis` |
| Docker container logging | `docker-admin` |
| Python SDK development | `python-flask-developer` |
| Data warehouse / data pipeline design | `data-warehouse`, `data-lake` |
