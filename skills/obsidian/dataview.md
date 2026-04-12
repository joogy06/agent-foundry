# Dataview — Queries Over Your Notes

Reference file for `obsidian` skill. Covers: DQL (Dataview Query Language) basics, common patterns, DataviewJS.

---

## What Dataview Does

Dataview treats your vault's notes as a database. Frontmatter fields become columns; file paths become rows. You can write SQL-like queries inline in any note; they render as live tables/lists.

---

## Query Block Syntax

Write a query in a fenced code block with `dataview` as the language:

````markdown
```dataview
TABLE author, year, rating
FROM "books"
WHERE rating >= 4
SORT year DESC
```
````

---

## Query Types

| Type | Output | Use For |
|------|--------|---------|
| `TABLE` | Tabular view | Lists of notes with columns |
| `LIST` | Bullet list | Simple enumerations |
| `TASK` | Aggregated tasks from `- [ ]` checkboxes | GTD-style task views |
| `CALENDAR` | Calendar heatmap | Time-based data visualization |

---

## Common Patterns

### All notes in a folder

```dataview
LIST FROM "research/papers"
```

### Filter by frontmatter field

```dataview
TABLE author, year
FROM "research/papers"
WHERE year >= 2023
SORT year DESC
```

### Filter by tag

```dataview
LIST FROM #ml/transformers
WHERE !contains(tags, "archived")
```

### Active goals

```dataview
TABLE status, target_date, progress
FROM "goals"
WHERE status = "active"
SORT target_date ASC
```

### All accepted ADRs

```dataview
TABLE adr_number, deciders, decided_on
FROM "decisions"
WHERE adr_status = "accepted"
SORT adr_number ASC
```

### Reading log

```dataview
TABLE file.link AS "Book", author, rating, finished_on
FROM "books"
WHERE reading_status = "read"
SORT finished_on DESC
```

### Journal entries this week

```dataview
LIST FROM "journal"
WHERE entry_date >= date(today) - dur(7 days)
SORT entry_date DESC
```

### Orphan pages (no outgoing links)

```dataview
LIST
WHERE length(file.outlinks) = 0
```

### Untagged pages

```dataview
LIST
WHERE length(file.tags) = 0
```

---

## Field Access

- `file.name` — filename
- `file.path` — full path
- `file.link` — wikilink to the note
- `file.tags` — list of tags (both frontmatter + inline `#tag`)
- `file.outlinks` — list of outgoing wikilinks
- `file.inlinks` — list of incoming wikilinks (backlinks)
- `file.ctime` — created time
- `file.mtime` — modified time
- Any frontmatter field by name: `author`, `rating`, `status`, etc.

---

## Operators

- Comparison: `=`, `!=`, `<`, `<=`, `>`, `>=`
- Logical: `AND`, `OR`, `!` (not)
- List: `contains(list, value)`, `length(list)`
- Date: `date(today)`, `dur(7 days)`, arithmetic on dates
- String: `startswith`, `endswith`, `contains`

---

## DataviewJS (Advanced)

For logic beyond DQL's capabilities, use DataviewJS:

````markdown
```dataviewjs
const pages = dv.pages('"books"').where(p => p.rating >= 4);
dv.table(
  ["Title", "Author", "Rating"],
  pages.map(p => [p.file.link, p.author, p.rating])
);
```
````

**When to use**: calculations, grouping, custom rendering, cross-page aggregation.

**Enable**: Settings -> Dataview -> Enable JavaScript Queries.

---

## Inline Queries

For a single value inline in text, use `=` prefix:

```markdown
I've finished `= length(filter(this.books, (b) => b.status = "read"))` books this year.
```

---

## Performance Tips

- Scope queries with `FROM "folder"` — don't query the whole vault
- Use `LIMIT` to cap results: `SORT ... LIMIT 50`
- Avoid DataviewJS in notes you open frequently (runs on every render)
- Disable auto-refresh if your vault is large

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Un-scoped queries on big vaults | Every open re-scans entire vault, editor freezes | `FROM "folder"` scope every query |
| Querying non-existent frontmatter fields | Silent empty results, hard to debug | Verify fields exist with a simpler query first |
| Using `WHERE file.name = "X"` instead of linking | Breaks when renaming, wikilinks are more stable | Use wikilinks + `file.inlinks` instead |
| Embedding complex DataviewJS in daily notes | Runs on every open, accumulates cost | Cache results in static notes; run expensive queries on-demand |
