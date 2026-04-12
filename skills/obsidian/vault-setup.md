# Obsidian Vault Setup

Reference file for `obsidian` skill. Covers: creating a vault, folder structure, attachments, hotkeys, core settings.

---

## Creating a Vault

1. Download Obsidian from https://obsidian.md
2. Open Obsidian, click "Create new vault"
3. Choose a directory — the vault IS the directory. Any folder of markdown files can be a vault.
4. Vault path examples:
   - Personal: `~/vaults/personal/`
   - Research wiki: `~/wikis/trading-research/` (wiki skill compatibility)
   - Project embedded: `/path/to/project/.wiki/` (hidden vault)

**Tip**: Keep vaults small and topical. One giant vault with everything scales poorly vs. several domain-specific vaults.

---

## Recommended Folder Structure

There's no single "right" layout. Two common patterns:

### Pattern 1: PARA (Projects, Areas, Resources, Archives)

```
vault/
  01-projects/    # Active projects with deadlines
  02-areas/       # Ongoing responsibilities (health, finance)
  03-resources/   # Topic references (languages, tools)
  04-archives/    # Inactive items
  _attachments/   # Images, PDFs
  _templates/     # Templater templates
```

### Pattern 2: Category-Based (used by wiki skill)

```
vault/
  WIKI.md              # Schema (if wiki-integrated)
  index.md
  <category-1>/
  <category-2>/
  raw/                 # Source files (wiki skill)
  _templates/
  _maintenance/
```

Pick whichever you'll actually maintain.

---

## Attachment Settings

Settings → Files & Links:

- **Default location for new attachments**: `In subfolder under current folder` — creates `attachments/` next to each note
- **Or** `In the folder specified below` → `_attachments` for a global attachments folder
- **New link format**: `Relative path to file` (survives vault moves better than shortest)
- **Use `[[Wikilinks]]`**: ON (required for graph view backlinks)

For wiki-integrated vaults: attachments go to `raw/images/`, configured via "In the folder specified below".

---

## Core Settings

- **Appearance → Theme**: start with default, change later via `css-themes.md`
- **Editor → Default view for new tabs**: Reading view OR Source mode (personal preference)
- **Editor → Use tabs → ON**
- **Editor → Show line number → ON** (useful for citations)
- **Files & Links → Automatically update internal links → ON** (renames propagate)
- **Files & Links → Detect all file extensions → ON** (show PDFs, CSVs in file explorer)

---

## Daily Notes (Core Plugin)

Enable **Daily Notes** in Settings → Core plugins.

- **New file format**: `YYYY-MM-DD`
- **New file location**: `journal/` (or wherever your daily notes go)
- **Template file location**: `_templates/daily.md`
- Hotkey: `Ctrl+Shift+D` (or `Cmd+Shift+D` on macOS) — opens today's note

Template example for `_templates/daily.md`:
```markdown
---
type: journal
entry_date: {{date:YYYY-MM-DD}}
tags: [daily]
---

# {{date:YYYY-MM-DD}}

## Highlights

## Notes

## Tomorrow
```

---

## Core Plugins to Enable

Required:
- **File explorer** (always on)
- **Search** (always on)
- **Quick switcher** (`Ctrl+O`)
- **Graph view** (`Ctrl+G`)
- **Backlinks** (shows inbound links)
- **Outgoing links** (shows what this note links to)
- **Tag pane** (browse by tag)
- **Page preview** (hover to see linked note preview)

Optional:
- **Daily notes** (if you journal)
- **Templates** or **Templater** (for repeatable patterns)
- **Slash commands**
- **Audio recorder** (voice notes)
- **Workspaces** (save multi-pane layouts)

---

## Hotkeys (Essential)

| Action | Hotkey |
|--------|--------|
| Quick switcher | `Ctrl+O` |
| Command palette | `Ctrl+P` |
| New note | `Ctrl+N` |
| Toggle edit/read | `Ctrl+E` |
| Graph view | `Ctrl+G` |
| Open in new pane | `Ctrl+Click` link |
| Follow link | `Ctrl+Click` link |
| Back / Forward | `Alt+←` / `Alt+→` |
| Global search | `Ctrl+Shift+F` |
| Search in note | `Ctrl+F` |
| Insert template | via Templater or core Templates |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| One giant vault for everything | Graph view explodes, search slows, cognitive load high | Use multiple topical vaults; open one at a time |
| Shortest path link format | Breaks on vault restructure, bidirectional links rot | Use "Relative path to file" in settings |
| Disabling wikilinks in favor of markdown links | Breaks graph view and backlinks core feature | Wikilinks ON (opt-in to both, but wikilinks primary) |
| Attachments scattered across vault | Can't find images, sync conflicts multiply | Global `_attachments/` OR per-folder `attachments/` — pick one, stick with it |
