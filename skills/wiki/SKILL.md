---
name: wiki
description: "Knowledge base builder and maintainer for persistent markdown wikis. Use when ingesting sources into structured wiki pages, querying existing knowledge bases, creating new wikis, maintaining wiki quality, or navigating wiki content. Covers 6 domain templates (research, project, personal, business, reading, general), anti-hallucination citations, index-first queries, and lint protocols. Also trigger on: knowledge base, wiki, compile notes, persistent notes, second brain, Zettelkasten, Obsidian vault content. Parent skill for the wiki skill family."
---

# Wiki — Persistent Knowledge Base Skill Family

Parent skill for building and maintaining file-based markdown knowledge bases. Routes operational work to reference files.

This is a **slim parent** — detailed protocols live in reference files. Read this file to understand WHAT wikis are and WHICH reference file handles WHICH operation. Read the reference files for HOW.

<HARD-RULE>
**Cite every claim.** No fact lands in a wiki page without `[Source: raw/<file>, p.<page>]` or equivalent. Hallucination is the #1 failure mode. Lint enforces this at check #3 (source traceability).
</HARD-RULE>

<HARD-RULE>
**Immutable raw layer.** Never modify files in `raw/` after deposit. Re-ingesting a source creates `<slug>-2.<ext>`, `<slug>-3.<ext>`, etc.
</HARD-RULE>

<HARD-RULE>
**Index-first navigation.** Read `index.md` first, then grep, then targeted page reads. Never read the whole wiki into context. Wikis scale to 500+ pages — you can't afford to walk the tree.
</HARD-RULE>

<HARD-RULE>
**Single-writer lock.** Before any write, check `.wiki.lock`. Acquire, write, release in finally. Reads never acquire the lock.
</HARD-RULE>

<HARD-RULE>
**Lint after batch ingest.** Mandatory. Single-source interactive ingests may skip. Batch mode must run `wiki/lint.md` protocol.
</HARD-RULE>

---

## What a Wiki Is

A wiki is a self-contained directory with three layers:

```
<wiki-root>/
  WIKI.md                 # Schema/conventions for THIS wiki
  index.md                # Master content catalog
  log.md                  # Chronological operations log
  raw/                    # IMMUTABLE source files (date-prefixed)
  wiki/                   # LLM-owned content layer (categorized pages)
  _templates/             # Per-wiki instance templates (customizable copy)
  _maintenance/           # Agent operational state (link-index, lint-history, tags)
  .wiki-meta.yaml         # Local registry backup
  .wiki.lock              # Single-writer lock (when present)
```

**Layer ownership:**
- `raw/` — IMMUTABLE. Once deposited, never modified.
- `wiki/` — LLM-owned. Agent writes; humans read. Human edits flagged on lint.
- `WIKI.md` + schema — CO-EVOLVED. Agent proposes, user approves.

Registry: `~/.wiki-registry.yaml` (user home, not in `~/.claude/` — wikis are cross-tool).

---

## Routing Table — Which Reference File For Which Task

| User Intent | Reference File |
|-------------|----------------|
| "Create a new wiki" / "set up wiki for X" | `~/.claude/skills/wiki/schema.md` (bootstrap section) |
| "Ingest this source" / "add X to my wiki" | `~/.claude/skills/wiki/ingest.md` |
| "What does my wiki say about X" / "find Y in wiki" | `~/.claude/skills/wiki/query.md` |
| "Lint wiki" / "check wiki health" / "find broken links" | `~/.claude/skills/wiki/lint.md` |
| "Update schema" / "add new page type" / "evolve WIKI.md" | `~/.claude/skills/wiki/schema.md` (evolution section) |
| Pick a domain template | `~/.claude/skills/wiki/templates/{research,project,personal,business,reading,general}.md` |

Delegating to a reference file means: **read that file into context, then follow its protocol**. Do not re-derive logic here.

---

## Domain Templates (6)

| Template | For | Master File |
|----------|-----|-------------|
| **research** | Papers, concepts, experiments, comparisons | `~/.claude/skills/wiki/templates/research.md` |
| **project** | Architecture, ADRs, API contracts, runbooks | `~/.claude/skills/wiki/templates/project.md` |
| **personal** | Goals, habits, journal, self-model | `~/.claude/skills/wiki/templates/personal.md` |
| **business** | Companies, markets, products, customer segments | `~/.claude/skills/wiki/templates/business.md` |
| **reading** | Books, characters, themes, quotes | `~/.claude/skills/wiki/templates/reading.md` |
| **general** | Minimal fallback when no domain fits | `~/.claude/skills/wiki/templates/general.md` |

**Two template locations — do not conflate:**
- **Master** (this skill family): `~/.claude/skills/wiki/templates/<name>.md` — canonical, updated by alf
- **Per-wiki instance**: `<wiki-root>/_templates/<type>.md` — copied at wiki creation, customizable per wiki

---

## When NOT to Use This Skill

- **Architecture mapping for AI consumption** → use `project-documentation` (PROJECT.md, COMPONENT.md)
- **Session operational log** → use `history.md` (recent) + `history/INDEX.md` (archived) in the project root
- **Personal user memory** → use MEMORY.md auto-memory
- **Live web search / RAG** → wikis are compiled knowledge, not live search
- **Small one-off notes** → just use a markdown file, don't bootstrap a wiki

The wiki is for **persistent domain knowledge that compounds across sources**. Everything else has a better home.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Writing content inline here instead of reference files | SKILL.md exceeds 120-line slim-parent cap, ecosystem conventions broken | Keep routing + hard rules here; detail in `ingest.md`/`query.md`/`lint.md`/`schema.md` |
| Reading the full wiki to answer a query | Context explodes, costs unbounded, answers degrade | Index-first: read `index.md`, grep, targeted page reads |
| Claiming facts without source citations | Wiki becomes unreliable, undetectable hallucination contamination | Every claim cites `[Source: raw/<file>, p.<page>]` — lint check #3 enforces |
| Treating `raw/` as mutable | Breaks provenance, citations stop resolving | Immutable raw layer — new versions get numeric suffixes |
| Skipping lint after batch ingest | Broken links and contradictions accumulate silently | Mandatory lint after batch ops (see `lint.md` mandatory triggers) |
| Bypassing the `.wiki.lock` | Concurrent writes corrupt index.md and link graph | Check → acquire → write → release pattern |
