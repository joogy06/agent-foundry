# Obsidian CSS Themes & Snippets

Reference file for `obsidian` skill. Covers: themes, CSS snippets, callouts, customization.

---

## Installing a Theme

Settings -> Appearance -> Themes -> Manage -> Browse

**Popular themes** (2026, check current maintenance status):
- **Minimal** — clean, configurable, widely recommended
- **Things** — Apple-inspired, elegant
- **Blue Topaz** — high customization, Chinese-originated
- **AnuPpuccin** — Catppuccin-based, dark/light variants
- **ITS Theme** — inline title styling, callouts

**Switching**: instant. Theme files are CSS in `.obsidian/themes/`.

**Light vs. dark**: most themes support both; toggle with `Ctrl+,` then Appearance -> Base color scheme.

---

## CSS Snippets

Custom CSS that layers over your theme. Settings -> Appearance -> CSS snippets.

**Snippet location**: `<vault>/.obsidian/snippets/<name>.css`

Create a `.css` file, click refresh, toggle the snippet on.

---

## Common Snippet Patterns

### Wider editor

```css
.markdown-source-view.mod-cm6 .cm-content,
.markdown-preview-view {
  max-width: 1000px;
  margin: 0 auto;
}
```

### Highlight active tab

```css
.workspace-tab-header.is-active {
  border-bottom: 2px solid var(--interactive-accent);
}
```

### Colored tags

```css
a.tag[href="#ml/transformers"] {
  background-color: #2d5be3;
  color: white;
}
a.tag[href="#archived"] {
  background-color: #888;
  color: white;
}
```

### Frontmatter highlight

```css
.metadata-container {
  background: var(--background-secondary);
  border-radius: 6px;
  padding: 8px;
}
```

### Custom callout

```css
.callout[data-callout="citation"] {
  --callout-color: 138, 80, 255;
  --callout-icon: quote-glyph;
}
```

Then use it in notes:

```markdown
> [!citation]
> "Fear is the mind-killer" — Dune, p.22
```

---

## Built-in Callouts

Obsidian has native callouts:

```markdown
> [!note]
> This is a note callout.

> [!warning]
> Something to watch out for.

> [!tip]
> A helpful tip.

> [!info]
> Informational.

> [!abstract]
> Summary.

> [!todo]
> Action item.

> [!success]
> Achievement.

> [!question]
> Open question.

> [!failure]
> Failed approach.

> [!danger]
> Serious warning.

> [!example]
> Example.

> [!quote]
> Quotation.
```

Add a title: `> [!warning] Rate Limit Alert`

Collapsible: `> [!note]-` (starts collapsed) or `> [!note]+` (starts expanded)

---

## Custom Variables

Obsidian themes use CSS variables you can override:

```css
.theme-dark, .theme-light {
  --accent-h: 200;
  --accent-s: 80%;
  --accent-l: 50%;
  --font-text: "Inter", sans-serif;
  --font-monospace: "JetBrains Mono", monospace;
}
```

Common variables:
- `--background-primary` — main background
- `--background-secondary` — sidebar, panels
- `--text-normal` — body text
- `--text-accent` — links
- `--text-accent-hover` — hovered links
- `--interactive-accent` — buttons, active states

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Editing theme files directly | Lost on theme update | Use CSS snippets to layer customization on top |
| Copying huge CSS from random blogs without reading | Breaks theme in non-obvious ways | Read the snippet, understand what it does, then enable |
| Overriding font in 10 places | Conflicting rules, unpredictable result | Use CSS variables (`--font-text`) in one place |
| Using a dead/unmaintained theme | Breaks on Obsidian updates | Check theme's last update date before installing |
| Forgetting to disable a snippet before reporting a bug | Snippet masks the real issue | Always disable snippets when filing theme bug reports |
