# Obsidian Frontmatter (Properties)

Reference file for `obsidian` skill. Covers: YAML frontmatter, Obsidian Properties view, type-aware fields, conventions.

---

## What Frontmatter Is

YAML metadata at the top of a markdown file, between `---` fences:

```markdown
---
title: "My Note"
tags: [ideas, draft]
created: 2026-04-07
status: active
---

# My Note

Body content starts here.
```

Obsidian renders frontmatter as **Properties** (in recent versions — a native UI above the note content).

---

## Type-Aware Fields

Obsidian supports these property types:

| Type | Example | Notes |
|------|---------|-------|
| Text | `title: "My Note"` | Default for strings |
| Number | `rating: 5` | Integer or float |
| Checkbox | `done: true` | Boolean |
| Date | `created: 2026-04-07` | ISO 8601 |
| Date & Time | `last_opened: 2026-04-07T14:32:00` | ISO 8601 with time |
| List | `tags: [ideas, draft]` | YAML list |
| Links | `related: ["[[other-note]]"]` | Wikilinks as strings |

Set field types in Settings -> Properties -> set default type per field name.

---

## Tags: Frontmatter vs. Inline

Two ways to tag a note:

- **Frontmatter**: `tags: [ml, transformers]` — no `#` prefix
- **Inline**: `#ml #transformers` anywhere in body text

Both are discoverable in the Tag pane. Prefer frontmatter for canonical tags, inline for contextual.

**Hierarchical tags** (common convention):
- `ml/transformers` — nested tag
- `project/alpha/ui` — three levels
- Max 3 levels deep is a good convention

---

## Common Field Conventions

For wiki-style vaults (and the wiki skill):

| Field | Purpose | Example |
|-------|---------|---------|
| `type` | Page type (paper, decision, habit, etc.) | `type: paper-summary` |
| `title` | Human-readable title | `title: "Dune"` |
| `slug` | File-slug identifier | `slug: dune` |
| `created` | Creation date | `created: 2026-04-07` |
| `updated` | Last update | `updated: 2026-04-07` |
| `tags` | Tag list | `tags: [scifi, classics]` |
| `status` | Workflow state | `status: active` |
| `confidence` | Claim confidence | `confidence: high` |
| `sources` | Source references | `sources: [{path: raw/file.pdf}]` |
| `related` | Related wikilinks | `related: [slug-1, slug-2]` |

---

## Properties View (UI)

Newer Obsidian versions show frontmatter as a native Properties panel above the editor:

- Click a property to edit inline
- Change type with the gear icon
- Add new property with `+ Add property`
- Reorder by drag

**Tip**: Use Properties view for daily editing; the raw YAML is still there for git and scripting.

---

## Dataview Integration

Every frontmatter field becomes a queryable column in Dataview:

```dataview
TABLE status, confidence
FROM "wiki"
WHERE type = "decision"
```

Keep field names consistent across notes — Dataview is case-sensitive.

---

## Escaping and Multi-Line Values

- Wrap strings with special chars in quotes: `title: "It's a test"`
- Multi-line with `|`:
  ```yaml
  description: |
    Line one.
    Line two.
  ```
- YAML lists:
  ```yaml
  tags:
    - ml
    - transformers
  # or inline:
  tags: [ml, transformers]
  ```

---

## Common Pitfalls

- **Tabs in YAML** — YAML requires spaces. Tabs break parsing.
- **Unquoted colons**: `title: 2026: A Look Back` fails. Use `title: "2026: A Look Back"`.
- **Trailing spaces after field name** — sometimes silently break
- **Mixing flow and block style** — pick one

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Inconsistent field names across notes | Dataview queries return partial results | Document field conventions in a vault README or WIKI.md |
| Using hyphenated field names | YAML technically allows but tooling varies | Use snake_case or camelCase for stability |
| Huge frontmatter (20+ fields) | Properties UI becomes noise | Keep frontmatter to ~10 fields; overflow to body sections |
| Mixing frontmatter tags and inline tags inconsistently | Tag pane shows duplicates | Pick one primary location; use the other only for context |
| Storing sensitive data in frontmatter | YAML is plain text, visible everywhere | Keep secrets out of notes entirely; use a password manager |
