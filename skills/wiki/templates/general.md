# General Domain Template

Master template for minimal/general-purpose wikis. Used when no specific domain fits. Smallest footprint, most flexible.

**Template version**: general-v1
**Best for**: mixed-content knowledge bases, early-stage wikis before a specific domain emerges, cross-domain personal wikis.

---

## Directory Structure

```
<wiki-root>/
  WIKI.md
  index.md
  log.md
  raw/
    images/
    <YYYY-MM-DD>-<slug>.<ext>
  wiki/
    entities/        # Named things (people, places, products, tools)
    notes/           # Free-form notes
    sources/         # Source-summary pages (one per raw source)
    comparisons/     # Optional: A vs B pages
    overviews/       # Optional: topic overviews
  _templates/
    entity.md
    note.md
    source-summary.md
    comparison.md
    overview.md
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
| `entity` | Any named thing (person, place, product, tool, concept) | sources, entity_kind | `entity.md` |
| `note` | Free-form note | sources (optional) | `note.md` |
| `source-summary` | 1:1 summary of a raw source | sources (1) | `source-summary.md` |
| `comparison` | A vs B | subjects (>=2) | `comparison.md` |
| `overview` | Topic landscape | related (>=3) | `overview.md` |

---

## Frontmatter Schema

Base fields only — no domain-specific extensions.

```yaml
---
type: entity
title: "Example Entity"
slug: example-entity
created: 2026-04-07
updated: 2026-04-07
sources:
  - path: raw/2026-04-07-source.md
tags: []
status: active
confidence: high
related: []

# Entity-specific (optional)
entity_kind: tool     # person|place|product|tool|concept|other
---
```

---

## Cross-Referencing Conventions

**Wikilinks:** `[[slug]]` anywhere a known entity is mentioned
**Auto-link rules:** On new `entity` creation, backfill wikilinks in notes and source-summaries that mention the entity title
**Related field:** List any related slugs. No strict rules — flexibility over structure.

---

## Naming Conventions

- **Entities**: kebab-case noun phrase
- **Notes**: `<YYYY-MM-DD>-<short-slug>` or topic kebab-case
- **Source summaries**: match the raw filename stem (without date prefix)

---

## Output Formats

**Citations**: `[Source: raw/<file>]` — page/line optional for general template
**Mermaid defaults**: none — generate only when explicitly relevant

---

## Maintenance Workflows

- **Lint frequency**: after batch ingest, monthly otherwise
- **Staleness thresholds**: 180 days for notes (warning, not failure)
- **Archive**: rarely needed — flexible wikis keep everything discoverable

---

## Obsidian Compatibility Notes

General template is minimal — Obsidian works out of the box. Graph View and Dataview optional.

---

## Example Pages

### Example: entity

```markdown
---
type: entity
title: "PostgreSQL"
slug: postgresql
entity_kind: tool
sources:
  - path: raw/2026-04-07-databases-overview.md
tags: [database, open-source]
status: active
confidence: high
related: [sqlite, mysql]
---

# PostgreSQL

Open-source relational database with strong ACID guarantees and rich JSONB support [Source: raw/2026-04-07-databases-overview.md].

## See Also

- [[sqlite]] — Embedded alternative
- [[mysql]] — Another open-source RDBMS
```

### Example: note

```markdown
---
type: note
title: "2026-04-07 Reading notes"
slug: 2026-04-07-reading-notes
sources: []
tags: [daily-notes]
status: active
confidence: medium
---

# 2026-04-07 Reading notes

Free-form notes from the day. May reference [[postgresql]] or other entities.
```

---

## Migration Note

If a general wiki grows and a clearer domain emerges:

1. Run lint to identify clusters of page types
2. Offer user a migration to a specific template (research, project, etc.)
3. On approval: update WIKI.md, backfill new fields, move pages to new category folders
4. See `schema.md` Part 4 (Evolution Protocol) for the mechanics

---

## Anti-Patterns (General Domain)

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using `general` for a clearly-specialized need | Loses the structure benefits of research/project/etc. templates | Pick a specific template if the domain is clear |
| Skipping sources entirely in notes | Notes become free-form text without provenance | Add at least `sources: [raw/<file>]` if any source inspired the note |
| Growing >200 pages in `general` without migration | Discovery degrades, entity/note distinction blurs | Migrate to a specific template (see Migration Note) |
| Using `note` type when `source-summary` is more accurate | Source summaries should be 1:1 with raw files | Use `source-summary` type for direct 1:1 summaries |
