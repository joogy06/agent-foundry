---
name: visual-companion
description: >
  Use when you need to show visual content (mockups, wireframes, architecture
  diagrams, side-by-side layout comparisons) to the user during a design or
  brainstorming conversation. Generates self-contained HTML files in /tmp/ that
  the user opens in their browser. Server-less local replacement for the
  superpowers brainstorming visual companion. Trigger phrases: "show me a mockup",
  "render this diagram", "visual companion", "compare these layouts visually".
---

# Visual Companion (local, server-less)

A local equivalent of the superpowers brainstorming visual companion. Instead of
running a server that watches a directory, this skill writes one self-contained
HTML file per visual question, gives the user the file path, and waits for
verbal/text feedback in the terminal.

## When to use

Decide per-question: would the user understand this better seeing it than reading it?

**Use the visual companion** when content is genuinely visual:
- UI mockups, wireframes, layouts
- Architecture diagrams, data flow, system maps
- Side-by-side visual comparisons (two layouts, two color schemes)
- Spatial relationships, state machines, flowcharts

**Use the terminal** when content is text/tabular:
- Requirements, scope, conceptual choices
- Tradeoff lists, pros/cons
- API design, data modeling
- Anything where the answer is words, not visual preference

## Hard rules

<HARD-RULE>
Never modify the live `~/.claude/` tree. All HTML files go to `/tmp/visual-companion-<session-id>/`. The session-id is the current Unix timestamp on first use; reuse it for the rest of the conversation so all files for one session land in one directory.
</HARD-RULE>

<HARD-RULE>
Use semantic filenames (`layout.html`, `dashboard-mockup.html`, `auth-flow.html`). For iterations, append version (`layout-v2.html`). Never reuse a filename within a session.
</HARD-RULE>

<HARD-RULE>
No client-side JS for selection. The user responds in the terminal. The HTML is read-only from the user's perspective. This eliminates the need for a server, event tracking, or state files.
</HARD-RULE>

## Operations

### `offer` — first time in a session

When the design conversation starts and the upcoming questions are likely visual:

> "Some of what we're working on might be easier to explain if I can show it to you in a web browser — mockups, diagrams, comparisons. Want to try the visual companion? (I'll write HTML files to /tmp/ that you open in your browser.)"

Wait for confirmation. Save the answer in your conversation context — you don't need to ask again.

### `show-options` — A/B/C choice

When you want to present 2-4 visual options for the user to compare:

1. Generate a unique session id if you don't have one yet: `SESSION_ID=$(date +%s)`
2. Create the directory: `mkdir -p /tmp/visual-companion-$SESSION_ID/`
3. Read the template at `~/.claude/skills/visual-companion/templates/options.html`
4. Substitute the placeholders with your content (see template for placeholder names)
5. Write the result to `/tmp/visual-companion-$SESSION_ID/<semantic-name>.html`
6. Tell the user the file path with a clear instruction:

> "I've written 3 layout options to `/tmp/visual-companion-1234567890/layout-options.html`. Open it in your browser, then tell me which option feels right (or describe what you'd change)."

7. Wait for the user's terminal response.

### `show-mockup` — single UI mockup

For a single mockup (not a comparison):

1. Same setup as show-options.
2. Use `templates/mockup.html` instead.
3. Substitute the placeholders.
4. Same prompt-and-wait pattern.

### `show-diagram` — mermaid diagram

For architecture diagrams, flowcharts, sequence diagrams, ER diagrams:

1. Same setup.
2. Use `templates/base.html` and embed your mermaid markup in a `<pre class="mermaid">...</pre>` block.
3. The base template loads mermaid.js from CDN.
4. Same prompt-and-wait pattern.

### `show-comparison` — side-by-side

Use `templates/comparison.html`. Two columns, one mockup per side.

> **Adapter note — avengers `website-ux` profile (auto `show-comparison`).** The
> `avengers` skill's `website-ux` composition profile invokes `show-comparison`
> AUTOMATICALLY at its ROUTE phase (`visual.auto: true`), deliberately overriding
> the `offer`-first default above. Rationale: a UX deliberation's whole point is
> comparing contending layouts, so the offer-first friction is not wanted for that
> one profile — the side-by-side is the payload, not an optional aid. This is a
> documented, profile-scoped exception; every OTHER caller (and every other
> avengers profile) still uses the offer-first default. If `show-comparison` is
> renamed or its `templates/comparison.html` contract changes, update the avengers
> `website-ux` visual track (see `skills/avengers/references/reuse-map.md`).

## File path convention

```
/tmp/visual-companion-<session-id>/
  ├── layout-options.html
  ├── auth-flow-diagram.html
  ├── dashboard-mockup.html
  ├── dashboard-mockup-v2.html      # iteration after feedback
  └── ...
```

The session-id is one Unix timestamp per conversation. If the user starts a new
conversation, generate a new session-id. The user can clean up `/tmp/visual-companion-*`
manually anytime; nothing here is persistent state.

## Templates

All four templates are at `~/.claude/skills/visual-companion/templates/`. They use
double-curly placeholders (`{{TITLE}}`, `{{CONTENT}}`, etc.) that you substitute
with your content using the Edit or Write tools. Each template is fully
self-contained — embedded CSS, no external dependencies except mermaid CDN (only
in `base.html`).

## Anti-patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Running a web server for each session | Process management, port collisions, cleanup pain | Static HTML files, browser opens them via `file://` URL |
| Client-side JS for selection | Adds complexity, requires server to read events back | User responds in terminal — simpler and works offline |
| Reusing filenames | Browser caches stale content | Append version suffix (`layout-v2.html`) |
| Writing to `.claude/` or skill directories | Pollutes the tree | Always `/tmp/visual-companion-<session>/` |
| Showing more than 4 options | Decision fatigue, paradox of choice | 2-4 options max per file |

## When NOT to use this skill

- Conversational/conceptual questions → use the terminal
- Code reviews → use diffs in the terminal
- Long-form text → markdown in the terminal
- Anything where the user's response will be a sentence or paragraph rather than a visual selection
