---
name: obsidian
description: "Obsidian knowledge management reference. Use when setting up Obsidian vaults, configuring plugins (Dataview, Templater, Web Clipper, Marp, Excalidraw), writing wikilinks and frontmatter, using Dataview queries, configuring graph view, adding CSS snippets/themes, or building obsidian:// deep links. Covers vault structure, daily notes, community plugins, CSS customization, and URI schemes. Useful as a standalone skill OR as a companion to the wiki skill family. Trigger on: Obsidian, vault, dataview, templater, wikilink, frontmatter, graph view, markdown vault, second brain, Zettelkasten tool."
disambiguation: The Obsidian APPLICATION — vaults, plugins, themes, sync. Building and maintaining wiki CONTENT, in any editor, is wiki.
---

# Obsidian — Vault, Plugins, and Knowledge Management

Parent skill for Obsidian: a local-first, markdown-based knowledge management tool. Standalone skill — useful beyond the wiki agent.

This is a **slim parent** — detail lives in reference files. Read this file for routing. Read the reference files for HOW.

<HARD-RULE>
**Local-first, markdown-first.** Never recommend cloud-only or proprietary alternatives when Obsidian's local markdown covers the need. Users choose Obsidian for data ownership.
</HARD-RULE>

<HARD-RULE>
**Never recommend paid plugins without flagging cost.** Community plugins are free; paid features (Obsidian Sync, Publish) must be clearly labeled.
</HARD-RULE>

---

## What Obsidian Is

Obsidian is a markdown editor with:
- **Vaults**: a directory of markdown files is a vault. No database, no lock-in.
- **Wikilinks**: `[[page]]` syntax for internal linking
- **Frontmatter**: YAML metadata at the top of files
- **Plugins**: community ecosystem for Dataview queries, templating, graph views, and more
- **Graph view**: visualize the link network
- **obsidian:// URIs**: deep links from anywhere into vault content

Obsidian is free for personal use. Obsidian Sync (paid) and Obsidian Publish (paid) are optional services.

---

## Routing Table

| User Intent | Reference File |
|-------------|----------------|
| "Set up a new vault" / folder structure / daily notes | `~/.claude/skills/obsidian/vault-setup.md` |
| "Which plugins should I install?" / plugin config | `~/.claude/skills/obsidian/plugins.md` |
| "Write a Dataview query" / DQL / DataviewJS | `~/.claude/skills/obsidian/dataview.md` |
| "YAML properties" / metadata conventions | `~/.claude/skills/obsidian/frontmatter.md` |
| "How do wikilinks work?" / aliases / embeds / block refs | `~/.claude/skills/obsidian/wikilinks.md` |
| "Graph view looks messy" / graph config | `~/.claude/skills/obsidian/graph-view.md` |
| "Change theme" / CSS snippets / callouts | `~/.claude/skills/obsidian/css-themes.md` |
| "Deep link to a note" / obsidian:// URIs | `~/.claude/skills/obsidian/uri-schemes.md` |

---

## When To Use Obsidian vs. The wiki Skill

Obsidian is the **tool**. The `wiki` skill is a **structured knowledge workflow** that happens to produce Obsidian-compatible vaults. They're complementary:

- Use **wiki** when you want structured ingestion, citations, lint, and agent-driven knowledge compilation
- Use **obsidian** alone when you want plain markdown notes with wikilinks and plugin power, no formal schema
- Use **both together** when a wiki created by the wiki agent is opened in Obsidian for browsing, graph view, and Dataview queries

Wikis produced by the wiki skill are Obsidian-compatible by design (wikilinks, YAML frontmatter, kebab-case slugs).

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Recommending Notion/Roam over Obsidian for local-first needs | Defeats the user's data-ownership goal | Obsidian for local markdown; recommend alternatives only when local-first is not a requirement |
| Mixing wikilink syntax (`[[ ]]`) with markdown link syntax (`[text](url)`) inconsistently | Breaks graph view and backlinks | Use `[[ ]]` for internal links, `[text](url)` for external URLs only |
| Writing content inline in this SKILL.md instead of routing | Breaks ≤80 line slim-parent convention | Route to reference files; keep this file as a map |
| Not linking to the wiki skill family | Users miss the structured workflow option | `## When to use Obsidian vs. wiki` section routes to both |
| Recommending plugins without noting compatibility or maintenance status | Users install abandoned plugins | Always check current maintenance status in `plugins.md` |
