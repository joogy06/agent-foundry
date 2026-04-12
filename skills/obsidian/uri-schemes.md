# Obsidian URI Schemes (obsidian://)

Reference file for `obsidian` skill. Covers: deep-linking into Obsidian from the OS, browser, or scripts.

---

## The `obsidian://` Scheme

Obsidian registers a URI scheme that lets any app or script open a specific note, run a command, or create content. Useful for:

- Calendar apps linking to daily notes
- Shell scripts opening specific pages
- Browser bookmarks jumping into your vault
- Other apps (Raycast, Alfred, Keyboard Maestro) integrating with Obsidian

---

## Basic URI Format

```
obsidian://open?vault=<vault-name>&file=<file-path>
```

**Example**:

```
obsidian://open?vault=research&file=papers%2Fvaswani-2017-attention
```

- `vault`: vault name as shown in Obsidian (URL-encoded)
- `file`: path relative to vault root, without `.md` extension (URL-encoded — `/` becomes `%2F`)

---

## Key Actions

### Open a note

```
obsidian://open?vault=research&file=concepts%2Fself-attention
```

### Create a new note

```
obsidian://new?vault=research&file=ideas%2Fquick-thought&content=First%20line
```

### Search

```
obsidian://search?vault=research&query=transformer
```

### Run an Advanced URI plugin command (requires plugin)

With the "Advanced URI" community plugin, you get:

```
obsidian://advanced-uri?vault=research&commandid=editor:save-file
obsidian://advanced-uri?vault=research&filepath=papers/vaswani&line=5&column=3
obsidian://advanced-uri?vault=research&clipboard=true&mode=append&filepath=inbox/captures
```

---

## URL Encoding

Any `file`, `vault`, or `content` parameter must be URL-encoded:

| Character | Encoded |
|-----------|---------|
| space | `%20` |
| `/` | `%2F` |
| `#` | `%23` |
| `&` | `%26` |
| `?` | `%3F` |

---

## Cross-Platform Notes

- **macOS**: URI scheme works from anywhere (terminal: `open "obsidian://..."`)
- **Linux**: `xdg-open "obsidian://..."` — requires Obsidian desktop entry with URL handler
- **Windows**: from PowerShell `Start-Process "obsidian://..."`
- **iOS/Android**: URIs work from other apps (Shortcuts, Tasker) but not always from browsers

---

## Script Integration Examples

### Bash: open today's daily note

```bash
#!/bin/bash
TODAY=$(date +%Y-%m-%d)
xdg-open "obsidian://open?vault=personal&file=journal%2F${TODAY}"
```

### macOS Shortcut: quick capture

```
Shortcut action: Open URL
URL: obsidian://new?vault=personal&file=inbox/quick&content=[Shortcut text input]
```

### Browser bookmark: open research wiki index

```
obsidian://open?vault=research&file=index
```

---

## Security Note

Any app that can launch URLs can trigger Obsidian actions. Be cautious about:

- Clicking `obsidian://` URIs from untrusted sources
- Creating notes with the `content` parameter from untrusted input (content is written verbatim)
- Running `Advanced URI` commands from URIs — they can execute any command ID

Treat `obsidian://` URIs like shell commands: trusted sources only.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Forgetting URL encoding | URIs with spaces or special chars fail silently | Always URL-encode `file`, `vault`, `query`, `content` params |
| Using Advanced URI from untrusted sources | Can execute arbitrary Obsidian commands | Only accept URIs from trusted apps/scripts |
| Hardcoding vault name in scripts | Breaks when vault is renamed | Source vault name from config, not hardcoded |
| Including sensitive data in URI content params | URIs may be logged (shell history, browser history) | Use Advanced URI clipboard mode instead |
| Assuming URI scheme works on mobile | iOS/Android have limitations on URI launching | Test on target platform; use native share sheet as fallback |
