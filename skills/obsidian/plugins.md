# Obsidian Community Plugins

Reference file for `obsidian` skill. Covers essential community plugins and configuration.

---

## Installing Community Plugins

1. Settings -> Community plugins -> Turn on community plugins (one-time confirmation)
2. Browse -> search by name -> Install -> Enable

**Caution**: Community plugins are third-party code. Review popularity, last update date, and GitHub activity before installing.

---

## Essential Plugins

### Dataview
- **Purpose**: SQL-like queries over your notes' frontmatter and content
- **Use case**: "all books by author X", "all ADRs with status: accepted", "habit streak table"
- **Setup**: Install -> Enable -> Settings -> Dataview -> Enable JavaScript Queries (for DataviewJS)
- **Performance**: Indexes all notes on vault open; slow on very large vaults (5000+ notes)
- See `~/.claude/skills/obsidian/dataview.md` for query syntax

### Templater
- **Purpose**: Advanced templating with JavaScript — variables, file creation, scripted logic
- **Use case**: daily notes with dynamic dates, auto-populated frontmatter, file renaming
- **Setup**: Install -> Enable -> Settings -> Templater -> Template folder location: `_templates/`
- **vs. core Templates plugin**: Templater is more powerful; core Templates is simpler — pick one

### Obsidian Web Clipper
- **Purpose**: Save web pages to your vault as markdown
- **Note**: Official extension lives in your browser, not as a community plugin. Install from obsidian.md/clipper
- **Configuration**: maps article content to a target folder + frontmatter template
- **Use case**: reading-list/inbox for later processing

### Excalidraw
- **Purpose**: Draw diagrams, sketches, whiteboards directly in Obsidian
- **Use case**: architecture sketches, mind maps, visual notes
- **Output**: Excalidraw-format files that render as images in reading view
- **Maintenance**: actively maintained, excellent quality

### Marp / Slides
- **Purpose**: Turn markdown into presentations
- **Use case**: technical talks, lecture slides from notes
- **Note**: "Slides" core plugin is basic; Marp community plugin more powerful

### QuickAdd
- **Purpose**: Fast capture templates triggered by hotkeys
- **Use case**: "capture a book to reading list with one keystroke"
- **Pair with**: Templater for maximum power

### Tasks
- **Purpose**: Aggregate `- [ ]` checkboxes across the vault with due dates, priorities
- **Use case**: GTD-style task management inside Obsidian
- **Syntax**: `- [ ] Task description 📅 2026-04-15 ⏫ `

### Calendar
- **Purpose**: Sidebar calendar that ties into daily notes
- **Use case**: visualize journal, jump to any past/future daily note

### Advanced Tables
- **Purpose**: Table editing shortcuts (jump, insert row, sort)
- **Use case**: you write tables a lot

---

## Plugins to Avoid

- **Plugins with no updates in 2+ years** — unmaintained
- **Plugins that "sync" to proprietary services** — defeats local-first
- **Plugins that require Node.js / external runtimes** — fragility

---

## Plugin Loading Order

Obsidian doesn't guarantee plugin load order. If one plugin depends on another (e.g., Templater scripts that call Dataview), make sure the dependency is enabled first.

---

## Performance Notes

Dataview indexes can slow vault-open on large vaults. Workarounds:

- Disable Dataview for journaling vaults that don't need queries
- Use `DATAVIEW_DISABLE_AUTO_REFRESH` via setting to reduce re-indexing
- Split mega-vaults into topical vaults

---

## Obsidian Sync (Paid, Optional)

$8/month. Encrypted end-to-end sync across devices. Alternatives:

- **Git sync**: versioning + sync via any git remote (power user)
- **Syncthing**: P2P sync, free, self-hosted
- **iCloud / Dropbox / OneDrive**: works but can cause sync conflicts on concurrent edits

Flag cost explicitly when recommending Sync.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Installing 30+ plugins "just in case" | Startup slows, plugin conflicts multiply | Install what you'll actually use; curate quarterly |
| Using Dataview on a 5000+ note vault without tuning | Slow vault open, editor lag | Split vault by domain or disable auto-refresh |
| Recommending Obsidian Sync without mentioning cost | User surprised by paywall | Always note $8/month or list free alternatives |
| Installing abandoned plugins | Breakage on Obsidian updates, no fixes coming | Check last commit date before installing |
| Mixing core Templates + Templater | Confusing overlap, template collisions | Pick one; Templater if you need power, core if simple |
