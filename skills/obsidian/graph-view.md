# Obsidian Graph View

Reference file for `obsidian` skill. Covers: graph view configuration, filters, groups, hubs, orphan detection.

---

## What Graph View Shows

A force-directed graph of your notes, with:
- **Nodes** = notes (size by link count)
- **Edges** = wikilinks between notes
- **Colors** = groups (tag-based, folder-based, or custom)

Open with `Ctrl+G` or the graph view sidebar icon.

---

## Two Views

- **Local Graph**: graph of just the current note and its neighbors (configurable depth)
- **Global Graph**: full vault

Local graph is more useful day-to-day. Global graph is useful for auditing vault health.

---

## Configuration Panels

Graph view has 4 config panels (gear icon):

### Filters

Control which notes appear:

- **Search**: text/tag filter — only nodes matching appear
- **Files**: include/exclude by path glob
- **Tags**: include/exclude by tag
- **Attachments**: show/hide images, PDFs
- **Orphans**: show/hide notes with zero links
- **Existing files only**: hide red-link placeholders

### Groups

Color notes by criteria. Each group has:
- A search query (same syntax as global search)
- A color

**Example groups** for a research vault:
- `path:papers/` -> blue
- `path:concepts/` -> green
- `tag:#archived` -> gray
- `tag:#open-question` -> red

### Display

- **Arrows** — show link direction
- **Text fade threshold** — hide labels when zoomed out
- **Node size** — base size multiplier
- **Line thickness** — edge weight
- **Center force** — how strongly notes cluster to center
- **Repel force** — how strongly notes push apart
- **Link force** — how strongly links pull

**Tip**: high repel + low center force = sprawling clusters. Low repel + high center = tight ball.

### Forces

Physics tuning — adjust until graph is readable.

---

## Interpreting the Graph

### Hubs
Notes with many incoming links. These are your most-referenced concepts. Graph view draws them larger.

**Healthy vault**: 5-20 hubs per 100 notes.

### Orphans
Notes with zero incoming links. Enable "Orphans" filter to highlight them.

**Healthy vault**: <20% orphans. High orphan rate = notes aren't cross-linked enough.

### Clusters
Dense regions of interlinking. These are coherent topic areas.

### Bridges
Notes that connect otherwise-separate clusters. These are often synthesis or overview pages.

**Value**: bridge notes are high-leverage — they show conceptual connections.

---

## Graph View for Wikis (wiki skill)

For wikis produced by the wiki skill:

- Group by category directory (papers=blue, concepts=green, decisions=red, etc.)
- Filter to exclude `raw/` (source files should not be in the conceptual graph)
- Toggle "Show orphans" to catch pages missing backlinks
- Check hub distribution — orphaned hubs indicate schema drift

---

## Common Graph Problems

### Problem: Everything is one giant blob
- **Cause**: Too many generic links, not enough grouping
- **Fix**: Create distinct groups by path/tag. Turn up repel force.

### Problem: Many disconnected clusters
- **Cause**: Not enough cross-cluster links
- **Fix**: Add synthesis notes that bridge clusters

### Problem: Labels unreadable when zoomed out
- **Cause**: Text fade threshold too low
- **Fix**: Increase fade threshold slider

### Problem: Graph too slow on large vaults
- **Cause**: 5000+ notes is heavy
- **Fix**: Use local graph instead of global, reduce physics iterations

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using global graph on vaults >3000 notes | Lag, browser sluggishness | Use local graph (current note + neighbors) |
| Not using groups | All nodes look the same, can't read structure | Set up 3-5 color groups for your main categories |
| Including attachments in graph | Images clutter the graph without adding structure | Disable "Attachments" filter |
| Treating orphans as a bug | Some pages are intentional orphans (overviews, indexes) | Check case-by-case; aim for <20% orphan rate, not 0% |
| Never checking the graph | Miss structural drift and gaps in knowledge linkage | Review global graph monthly as part of vault maintenance |
