# Project Domain Template

Master template for project wikis: architecture, components, ADRs, API contracts, runbooks, bug reports, patterns. Used by `wiki/schema.md` bootstrap to generate WIKI.md + page templates for new project wikis.

**Template version**: project-v1
**Best for**: software projects (embedded `.wiki/` in repo), system documentation, team knowledge bases, long-running technical projects where decisions compound.

---

## Directory Structure

```
<wiki-root>/
  WIKI.md
  index.md
  log.md
  raw/
    images/
    <YYYY-MM-DD>-<slug>.md              # meeting notes, RFCs
    <YYYY-MM-DD>-<slug>.pdf              # external specs
    <YYYY-MM-DD>-<slug>.png              # architecture diagrams
    <YYYY-MM-DD>-<slug>.json             # API specs, OpenAPI
  wiki/
    architecture/        # System-level architecture docs
    components/          # Per-component descriptions
    api-contracts/       # External/internal API definitions
    decisions/           # ADRs (Architecture Decision Records)
    sprint-notes/        # Sprint retrospectives, planning
    bugs/                # Bug reports and root-cause analyses
    patterns/            # Reusable patterns and conventions
    runbooks/            # Operational procedures
    overviews/           # High-level system views
    comparisons/         # Tech/approach comparisons
  _templates/
    architecture.md
    component.md
    api-contract.md
    decision.md
    sprint-note.md
    bug-report.md
    pattern.md
    runbook.md
    overview.md
    comparison.md
  _maintenance/
    link-index.md
    tag-registry.md
    lint-history.jsonl
    source-manifest.yaml
```

---

## Page Types

| Type | Purpose | Required Frontmatter | Template |
|------|---------|---------------------|----------|
| `architecture` | System-level design | sources, related components | `architecture.md` |
| `component` | One component/module | sources, interfaces, dependencies | `component.md` |
| `api-contract` | API definition | endpoint, methods, schema_url | `api-contract.md` |
| `decision` | ADR: context, options, chosen, consequences | status (proposed/accepted/superseded), date, authors | `decision.md` |
| `sprint-note` | Sprint retro/planning | sprint_id, date | `sprint-note.md` |
| `bug-report` | Incident/RCA | severity, status, affected_versions | `bug-report.md` |
| `pattern` | Reusable code/design pattern | examples, anti_examples | `pattern.md` |
| `runbook` | Operational procedure | on_call_tags, last_verified | `runbook.md` |
| `overview` | System landscape page | related (>=5) | `overview.md` |
| `comparison` | A vs B tech choice | subjects (>=2), decision_ref | `comparison.md` |

---

## Frontmatter Schema (Project-Specific Extensions)

```yaml
---
# Base fields (always required)
type: decision
title: "Use PostgreSQL for primary datastore"
slug: adr-0001-postgres
created: 2026-04-07
updated: 2026-04-07
sources:
  - path: raw/2026-04-07-datastore-evaluation.md
tags: [infra/database, adr]
status: active          # base enum: draft|active|review|archived
confidence: high

# Project/ADR-specific extensions
adr_status: accepted    # proposed|accepted|superseded|deprecated
adr_number: "0001"
deciders: ["alice", "bob"]
consulted: ["charlie"]
informed: ["team-infra"]
decided_on: 2026-04-07
supersedes: []
superseded_by: []

# Component-specific (use on component pages instead of adr fields)
# component_name: auth-service
# language: python
# framework: flask
# interfaces: [rest-api, grpc]
# depends_on: [postgres, redis]
# used_by: [api-gateway]
# sla_p95_ms: 200
# owner: "team-platform"
---
```

---

## Cross-Referencing Conventions

**Wikilinks:**
- `[[component-slug]]` on first mention of any component
- `[[adr-NNNN-<slug>]]` when referencing a decision
- `[[pattern-slug]]` when describing an implementation that uses a documented pattern

**Auto-link rules:**
- New `component` page: backfill wikilinks in architecture and decision pages
- New `decision` page: auto-link to affected components in frontmatter `affected`
- New `api-contract`: link from all components that consume/provide the API
- New `bug-report`: auto-link to affected component(s)

**Related field conventions:**
- Architecture: lists all components it depicts
- Component: lists depends_on (upstream) and used_by (downstream)
- Decision: lists affected components + related decisions (ancestors)
- Runbook: lists components it operates on
- Bug report: lists affected component, triggering release, related bugs

---

## Naming Conventions

- **Decisions**: `adr-NNNN-<kebab-slug>`, zero-padded number (adr-0001, adr-0012, adr-0123)
- **Components**: kebab-case component name, e.g. `auth-service`, `payment-gateway`
- **API contracts**: `<service>-api-<version>`, e.g. `auth-api-v2`, `payment-api-v1`
- **Bugs**: `bug-<YYYY-MM-DD>-<short-slug>` or `incident-<date>-<slug>`
- **Sprint notes**: `sprint-<YYYY>-<WW>`, e.g. `sprint-2026-14`
- **Runbooks**: `runbook-<verb-noun>`, e.g. `runbook-rotate-certs`

---

## Output Formats

**Citations**: `[Source: raw/2026-04-07-datastore-evaluation.md, lines 12-34]`
**Code references**: `see src/auth/jwt.py:42`
**Mermaid defaults for this domain**:
- `graph TD` — component dependency graphs, system diagrams
- `sequenceDiagram` — request flows, transaction choreographies
- `classDiagram` — domain models, API schemas
- `erDiagram` — database schemas
- `stateDiagram-v2` — state machines, workflow states

---

## Maintenance Workflows

- **Lint frequency**: after every batch ingest, weekly during active development
- **Staleness thresholds**: runbooks stale after 90 days without `reviewed_on` update; ADRs never stale (historical); components stale if source code changes significantly (lint check #6 flags)
- **Archive**: superseded ADRs get `adr_status: superseded` + `superseded_by: <new-adr>`, stay discoverable but sorted last
- **Decision lineage**: each new ADR that changes an old one must list `supersedes` AND the old ADR must be updated to list `superseded_by`

---

## Obsidian Compatibility Notes

- Use Dataview plugin for: "all accepted ADRs", "all components owned by team-X", "ADRs affecting auth-service"
- Enable Graph View with category colors (architecture=red, decisions=blue, components=green)
- Frontmatter view shows ADR number, status, deciders at-a-glance

---

## Example Pages (Abbreviated)

### Example: decision (ADR)

```markdown
---
type: decision
title: "Use PostgreSQL for primary datastore"
slug: adr-0001-postgres
adr_status: accepted
adr_number: "0001"
deciders: ["alice", "bob"]
decided_on: 2026-04-07
sources:
  - path: raw/2026-04-07-datastore-evaluation.md
    lines: [1, 50]
tags: [infra/database, adr]
status: active
confidence: high
related: [auth-service, payment-service, adr-0002-redis-cache]
---

# ADR-0001: Use PostgreSQL for Primary Datastore

## Context

Evaluating primary datastore for microservice platform. Need ACID, JSON support, and mature operational tooling [Source: raw/2026-04-07-datastore-evaluation.md, lines 1-10].

## Options Considered

1. **PostgreSQL 16** — row-level security, JSONB, logical replication
2. **MySQL 8** — simpler HA story but weaker JSON + no RLS
3. **DynamoDB** — managed but vendor lock-in, costly for relational workloads

[Source: raw/2026-04-07-datastore-evaluation.md, lines 15-35]

## Decision

**PostgreSQL 16** with logical replication for read replicas.

## Consequences

- Team needs to develop Postgres ops expertise (mitigated by managed offering)
- Migration from prototype MySQL schema required (estimated 2 sprints)
- Enables row-level security for multi-tenant isolation (see [[adr-0007-rls-tenancy]])

## See Also

- [[auth-service]] — Primary consumer of RLS features
- [[adr-0002-redis-cache]] — Caching layer on top of Postgres
```

### Example: component

```markdown
---
type: component
title: "Auth Service"
slug: auth-service
component_name: auth-service
language: python
framework: flask
interfaces: [rest-api]
depends_on: [postgres, redis]
used_by: [api-gateway, payment-service]
sla_p95_ms: 150
owner: "team-platform"
sources:
  - path: raw/2026-04-07-auth-design.md
tags: [component, auth]
status: active
confidence: high
related: [adr-0001-postgres, auth-api-v2]
---

# Auth Service

Handles user authentication, token issuance, and session management [Source: raw/2026-04-07-auth-design.md].

## Responsibilities

- Issue JWTs on successful login
- Validate tokens for downstream services via [[auth-api-v2]]
- Maintain session state in Redis with 24-hour TTL

## Dependencies

- [[postgres]] — user records (see [[adr-0001-postgres]])
- [[redis]] — session cache (see [[adr-0002-redis-cache]])

## Used By

- [[api-gateway]] — token validation
- [[payment-service]] — session context

## SLA

- p95 latency: 150ms
- Availability: 99.95%
```

---

## Anti-Patterns (Project Domain)

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Writing architecture docs without component page cross-links | Components become discoverable only via full-text search | Each architecture page lists `related: [component-slug, ...]` in frontmatter |
| ADRs without `superseded_by` back-pointers | Decision lineage breaks, old decisions appear current | Update old ADR's `superseded_by` whenever new ADR has `supersedes` |
| Component pages without `depends_on` / `used_by` | Impact analysis impossible, blast radius unknown | Bidirectional dependency tracking via frontmatter lists |
| Runbooks without `last_verified` date | Stale runbooks cause incident response failures | Add `reviewed_on` field, lint flags runbooks >90 days unreviewed |
| Decision bodies without cited sources | ADRs become opinion, not decision record | Every rationale cites `raw/` file (design doc, benchmark, spec) |
