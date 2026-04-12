# Reading Domain Template

Master template for reading companion wikis: books, characters, themes, plot summaries, quotes, locations, analysis.

**Template version**: reading-v1
**Best for**: literature reading, book clubs, course reading lists, interconnected fiction universes.

---

## Directory Structure

```
<wiki-root>/
  WIKI.md
  index.md
  log.md
  raw/
    images/                              # book covers, maps, diagrams
    <YYYY-MM-DD>-<book-slug>.pdf         # the book (if digital)
    <YYYY-MM-DD>-<book-slug>-notes.md    # reading notes
  wiki/
    books/
    characters/
    themes/
    plot-summaries/
    quotes/
    locations/
    analyses/
    connections/    # Inter-book connections (sequels, shared universe, inspiration)
    authors/
    reading-log/    # Dated reading-entry pages
  _templates/
    book.md
    character.md
    theme.md
    plot-summary.md
    quote.md
    location.md
    analysis.md
    connection.md
    author.md
    reading-entry.md
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
| `book` | One book | author, year, genre, status (to-read/reading/read) | `book.md` |
| `character` | A character in one or more books | appears_in (list of book slugs), role | `character.md` |
| `theme` | A thematic element | books (list of book slugs) | `theme.md` |
| `plot-summary` | Plot of one book | book_slug, spoilers: true | `plot-summary.md` |
| `quote` | Memorable quote | book_slug, page/location, speaker (if character) | `quote.md` |
| `location` | Setting (real or fictional) | appears_in, real (bool) | `location.md` |
| `analysis` | Literary analysis | book_slug OR theme_slug, perspective | `analysis.md` |
| `connection` | Connection between books | books (list, >=2), connection_kind | `connection.md` |
| `author` | Author profile | books_written (list), nationality | `author.md` |
| `reading-entry` | Dated reading log | reading_date, book_slug, progress | `reading-entry.md` |

---

## Frontmatter Schema (Reading Extensions)

```yaml
---
# Base fields (always required)
type: book
title: "Dune"
slug: dune
created: 2026-04-07
updated: 2026-04-07
sources:
  - path: raw/2026-04-07-dune-frank-herbert.pdf
tags: [scifi, 1960s, epic]
status: active
confidence: high

# Book-specific extensions
author: "Frank Herbert"
year: 1965
genre: science-fiction
reading_status: read    # to-read|reading|read|dnf
rating: 5               # 1-5, optional
started_on: 2026-01-10
finished_on: 2026-01-28
series: "Dune Chronicles"
series_order: 1
language: english
related: [dune-messiah, paul-atreides, arrakis]
---
```

---

## Cross-Referencing Conventions

- `[[character-slug]]` on first mention in any page
- `[[book-slug]]` when another book references it
- `[[theme-slug]]` when an analysis touches a theme
- `[[author-slug]]` when an author is mentioned

**Spoiler management**: `plot-summary` pages have `spoilers: true` in frontmatter. Query responses warn if spoiler pages are in results.

---

## Naming Conventions

- **Books**: title slug (`dune`, `lord-of-the-rings-fellowship`)
- **Characters**: first-name-last-name (`paul-atreides`, `frodo-baggins`)
- **Themes**: concept kebab-case (`power-and-corruption`, `hero-journey`)
- **Quotes**: `<book>-<short-excerpt>` (`dune-fear-is-the-mind-killer`)
- **Locations**: place kebab-case (`arrakis`, `the-shire`)
- **Connections**: `<book-a>-to-<book-b>-<kind>` (`dune-to-dune-messiah-sequel`)

---

## Output Formats

**Citations**: `[Source: raw/2026-04-07-dune-frank-herbert.pdf, p.42]` or chapter reference `[Source: Dune, ch.3]` if no page (ebook without fixed pagination)
**Mermaid defaults**:
- `graph TD` — character relationships, plot graphs
- `timeline` — reading order, in-universe chronology
- `mindmap` — theme exploration, symbol networks

---

## Maintenance Workflows

- **Lint frequency**: monthly (reading notes accumulate slowly)
- **Staleness thresholds**: never stale (historical by nature)
- **Archive**: DNF books get `reading_status: dnf`, stay in index under "Did Not Finish"

---

## Obsidian Compatibility Notes

- Dataview: "all books by author X", "books tagged scifi rated 4+", "reading log by month"
- Graph view excellent for visualizing character networks and shared universes
- Custom CSS callouts for spoilers (blur effect)

---

## Example Pages

### Example: book

```markdown
---
type: book
title: "Dune"
slug: dune
author: "Frank Herbert"
year: 1965
genre: science-fiction
reading_status: read
rating: 5
started_on: 2026-01-10
finished_on: 2026-01-28
series: "Dune Chronicles"
series_order: 1
sources:
  - path: raw/2026-04-07-dune-frank-herbert.pdf
tags: [scifi, 1960s, epic, classics]
status: active
confidence: high
related: [dune-messiah, paul-atreides, arrakis, power-and-corruption]
---

# Dune

First novel in Frank Herbert's Dune Chronicles, set on the desert planet Arrakis [Source: Dune, ch.1].

## Synopsis (spoiler-free)

Young Paul Atreides inherits his family's stewardship of Arrakis, the only source of the universe's most valuable substance, and finds himself caught between imperial politics and native Fremen culture [Source: Dune, ch.1-2].

## Main Characters

- [[paul-atreides]] — Protagonist, heir to House Atreides
- [[lady-jessica]] — Paul's mother, Bene Gesserit sister
- [[baron-harkonnen]] — Antagonist

## Themes

- [[power-and-corruption]]
- [[ecology-and-survival]]
- [[religion-and-prophecy]]

## See Also

- [[dune-messiah]] — Sequel
- [[arrakis]] — Primary setting
- [[plot-summaries/dune]] (⚠ spoilers)
```

### Example: quote

```markdown
---
type: quote
title: "Fear is the mind-killer"
slug: dune-fear-is-the-mind-killer
book_slug: dune
speaker: paul-atreides
location: "Gom Jabbar test"
sources:
  - path: raw/2026-04-07-dune-frank-herbert.pdf
    pages: [20, 22]
tags: [dune, bene-gesserit-litany]
status: active
confidence: high
related: [dune, paul-atreides, bene-gesserit]
---

# "Fear is the mind-killer"

The Bene Gesserit litany against fear, recited by [[paul-atreides]] during the Gom Jabbar test [Source: raw/2026-04-07-dune-frank-herbert.pdf, p.20].

> I must not fear. Fear is the mind-killer. Fear is the little-death that brings total obliteration. I will face my fear. I will permit it to pass over me and through me. And when it has gone past I will turn the inner eye to see its path. Where the fear has gone there will be nothing. Only I will remain.

[Source: raw/2026-04-07-dune-frank-herbert.pdf, p.22]
```

---

## Anti-Patterns (Reading Domain)

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Mixing spoilers into non-plot-summary pages | Ruins the reading experience for future lookups | Keep spoilers in `plot-summary` pages with `spoilers: true` flag |
| Quote pages without `speaker` field | Loses attribution, character voice muddled | Always identify who speaks the quote (character slug or narrator) |
| Character pages that list every book mention | Becomes noise, hard to track role across books | Use `appears_in` for the key books, not every mention |
| Book pages without `reading_status` | Reading log breaks, "what have I read" queries fail | Required field — to-read / reading / read / dnf |
| Missing page/chapter reference in quote citations | Can't find the quote in the book again | Always cite page (if paginated) or chapter (if ebook) |
