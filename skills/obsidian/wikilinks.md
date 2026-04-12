# Obsidian Wikilinks

Reference file for `obsidian` skill. Covers: wikilink syntax, aliases, embeds, block references, heading links.

---

## Basic Wikilink

`[[page-name]]` — links to a file named `page-name.md` anywhere in the vault.

Obsidian resolves by:
1. Exact filename match
2. Alias match (see below)
3. Title match (H1 heading)
4. Unresolved: renders as red link (clickable, creates the file on click)

---

## Custom Display Text

`[[page-name|Display Text]]` renders as "Display Text" but links to `page-name.md`.

**Use case**: keep clean prose while linking to technical slugs.

```markdown
The [[attention-is-all-you-need|Transformer paper]] introduced self-attention.
```

---

## Link to Heading

`[[page-name#Heading]]` — links to the specific H2/H3 within a page.

```markdown
See [[dune#Main Characters]] for an overview.
```

**Caution**: heading links break when headings are renamed.

---

## Link to Block

`[[page-name#^block-id]]` — links to a specific block (paragraph) within a page.

**Block IDs**: highlight a paragraph and press `Alt+Shift+D` (or use the context menu) -> Obsidian appends `^unique-id` to the block.

```markdown
See [[dune#^abc123]] — that specific paragraph.
```

**Block links are more stable** than heading links because the ID doesn't depend on heading text.

---

## Embeds

`![[page-name]]` — embeds the entire content of a page inline.

`![[page-name#Heading]]` — embeds just that section.

`![[page-name#^block-id]]` — embeds just that block.

`![[image.png]]` — embeds an image.

`![[audio.mp3]]` — embeds audio player.

`![[document.pdf]]` — embeds PDF viewer.

**Use case**: reuse a canonical definition in multiple notes without duplication.

---

## Aliases

Define aliases in frontmatter:

```yaml
---
title: "Attention Is All You Need"
aliases:
  - "Transformer Paper"
  - "Vaswani 2017"
---
```

Now `[[Transformer Paper]]` and `[[Vaswani 2017]]` both resolve to this file.

**Use case**: link by natural name without exposing the slug.

---

## Link Resolution Order

1. Exact match on filename (without `.md`)
2. Alias match (case-insensitive)
3. H1 title match
4. First folder-local match if ambiguous

**Ambiguity**: if two files share a name, Obsidian resolves to the closest (same folder first, then up the tree). Use full paths `[[folder/subfolder/page]]` to disambiguate.

---

## Wikilinks vs. Markdown Links

Obsidian supports both:

- **Wikilink**: `[[page-name]]` — internal, graph-aware, backlink-tracked
- **Markdown link**: `[Display](page-name.md)` — portable to non-Obsidian tools, but NOT tracked by graph view or backlinks

**Rule**: use wikilinks for internal references. Use markdown links for external URLs.

**Wiki skill compatibility**: the wiki skill uses `[[slug]]` exclusively for internal links, with markdown links reserved for raw/source citations to avoid conflating the two.

---

## Backlinks

Open the Backlinks pane (sidebar or `Ctrl+Shift+B`) to see every note that links to the current note.

Backlinks are automatically computed from wikilinks — you don't maintain them manually.

---

## Unlinked Mentions

Below the Backlinks pane, Obsidian shows "Unlinked mentions" — notes that mention the current note's title but don't have a `[[link]]`.

**Use case**: convert unlinked mentions to real links in batch.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using markdown links for internal references | Breaks graph view and backlinks | Use `[[ ]]` for internal, `[text](url)` for external only |
| Heading links for stable references | Breaks when headings are renamed | Use block references `^id` for stability |
| Linking by display text everywhere | Creates inconsistent link targets, graph clutter | Link by slug, use `|Display` for prose |
| Forgetting aliases on renamed pages | Old links break, search fails | Add old names to `aliases` when renaming |
| Embedding huge pages inline | Reader loses navigation context | Use targeted `#Heading` or `#^block` embeds |
