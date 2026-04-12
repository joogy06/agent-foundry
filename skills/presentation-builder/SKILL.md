---
name: presentation-builder
description: >
  Use when the user asks to build a presentation, create slides, make a deck, PowerPoint, PPTX,
  pitch deck, status update deck, architecture review presentation, or steering committee deck.
  Parent skill for the presentation-* skill family.
---

# Presentation Builder

Parent skill that handles intake, environment detection, routing, and asset repository management for the presentation family.

## Companion Skills

- **presentation-narrative** — Outline generation, storytelling structure, slide sequencing
- **presentation-datavis** — Charts, data visualization, data-driven slides
- **presentation-diagrams** — Architecture diagrams, flowcharts, system visuals
- **presentation-styling** — Templates, branding, colour palettes, typography
- **presentation-renderer** — Final assembly, PPTX/HTML export, format conversion

---

## 1. Hard Rules

1. **Never fabricate data.** When data is missing, insert `[PLACEHOLDER: description of needed data]`.
2. **All output goes to `<project>/.presentations/output/`** (or `./presentations/output/` if no project root is detected).
3. **Always generate a slide outline for user approval BEFORE building the full deck.** No exceptions.
4. **Offline-first.** Never assume internet connectivity. Check the capability map first.
5. **Deterministic renderers for diagrams and charts.** Use Mermaid, Graphviz, matplotlib, or similar. AI image generation is permitted only for cover art and illustrations.
6. **Action titles, not topic titles.** Every slide title states the takeaway. One idea per slide.

---

## 2. Environment Detection

Runs **once per session** and caches the result as the capability map.

### Detection Commands

| Capability | Detection Command |
|---|---|
| python3 + python-pptx | `python3 -c "import pptx; print(pptx.__version__)"` |
| Node.js + Marp CLI | `npx @marp-team/marp-cli --version 2>/dev/null` |
| Node.js + mermaid-cli (mmdc) | `npx @mermaid-js/mermaid-cli --version 2>/dev/null` |
| Java (for Apache POI fallback) | `java -version 2>&1` |
| PowerShell | `pwsh --version 2>/dev/null \|\| powershell -Command '$PSVersionTable.PSVersion'` |
| Graphviz | `dot -V 2>&1` |
| Banana / Gemini (image gen) | Check for `nano-banana` or `vertex-banana` skill availability |
| matplotlib | `python3 -c "import matplotlib; print(matplotlib.__version__)"` |
| Internet connectivity | `curl -s --max-time 5 -o /dev/null -w '%{http_code}' https://httpbin.org/get` |

### Capability Map

Produces a JSON object conforming to `capability-map-schema.md` (see Reference Files). Example:

```json
{
  "python_pptx": true,
  "marp_cli": false,
  "mmdc": true,
  "java": false,
  "powershell": false,
  "graphviz": true,
  "image_gen": "nano-banana",
  "matplotlib": true,
  "internet": false,
  "timestamp": "2026-03-27T10:00:00Z"
}
```

### Auto-Install Offer

If critical tools are missing but installable, offer to install them:

- `pip install python-pptx matplotlib`
- `npm install -g @marp-team/marp-cli`
- `npm install -g @mermaid-js/mermaid-cli`

Always ask the user before installing anything.

---

## Gap Detection

Before routing to a child skill:
1. Verify target exists (check `~/.claude/skills/<path>`)
2. If missing: follow gap-detection protocol at `~/.claude/skills/research-for-skills/gap-detection.md`
3. If exists: invoke with context

---

## 3. Intake Process

Adapted from the GROW framework. Gather these four inputs before routing.

### Goal

What are you presenting? Classify the presentation type:

- Status update
- Architecture decision / review
- Sales pitch / proposal
- Problem statement / proposal
- Project kickoff
- Retrospective
- Steering committee briefing
- Custom / other

### Audience

Who sees this? Select the audience profile:

- Executive (C-suite, senior leadership)
- Technical (engineers, architects)
- Client / external stakeholder
- Mixed (technical + non-technical)
- Banking / regulatory

Reference `audience-profiles.md` for tone, depth, and terminology guidance per profile.

### Context

Where does the content come from?

- **Existing project artifacts**: Read `PROJECT.md`, problem statements, design docs, user-provided documents
- **Standalone topic**: User describes the subject; no existing artifacts

### Format

What output format?

- **PPTX** — PowerPoint file (requires python-pptx or Java)
- **HTML** — Marp-based HTML slides (requires Marp CLI)
- **Both** — Generate both formats

If the user does not specify, auto-select based on the capability map (prefer PPTX if python-pptx is available).

---

## 4. Routing Table

After intake is complete, route to the appropriate companion skill.

| User Need | Route To |
|---|---|
| "Build a presentation about X" / narrative / outline | `presentation-narrative` |
| Charts, data visualization, data-driven slides | `presentation-datavis` |
| Architecture diagrams, flowcharts, system visuals | `presentation-diagrams` |
| Template, branding, styling, "make it professional" | `presentation-styling` |
| "Export", "generate the file", format conversion | `presentation-renderer` |

Multiple skills may be invoked in sequence or parallel depending on the request (see Orchestration Flow).

---

## 5. Asset Repository Management

Assets are resolved from a layered structure. Project-local overrides global.

### Global Assets

```
~/.claude/skills/presentation-builder/assets/
  templates/       # Base slide templates
  logos/            # Reusable logos
  palettes/         # Colour palettes (JSON)
  tone-profiles/    # Writing tone definitions
```

### Project-Local Assets

```
<project>/.presentations/
  templates/       # Project-specific templates
  logos/            # Project / client logos
  palettes/         # Project colour palettes
  tone-profiles/    # Project tone overrides
  output/           # Generated presentations
```

### Resolution Order

1. Check `<project>/.presentations/<asset-type>/` first
2. Fall back to `~/.claude/skills/presentation-builder/assets/<asset-type>/`
3. Merge: project-local values override global values for matching keys

### First-Use Setup

On first invocation in a project, create the `.presentations/` directory structure:

```bash
mkdir -p .presentations/{templates,logos,palettes,tone-profiles,output}
```

The parent skill resolves the merged asset context **before** routing to any companion skill.

---

## 6. Orchestration Flow

The standard end-to-end flow for building a presentation:

```
1. Environment scan --> capability map (cached)
2. Intake --> goal, audience, context, format
3. Route to presentation-narrative --> slide outline generated
4. User approves outline (HARD RULE #3)
5. Dispatch in parallel:
   - presentation-diagrams (architecture/flow visuals)
   - presentation-datavis (charts/data slides)
   - presentation-styling (template, branding, layout)
6. All visuals complete --> presentation-renderer assembles final output
7. Output files written to .presentations/output/
```

Steps 5a, 5b, and 5c run in parallel when independent. The renderer waits for all upstream assets before assembly.

---

## 7. When NOT to Use This Skill

| Request | Use Instead |
|---|---|
| Image generation only (not for slides) | `nano-banana` or `vertex-banana` |
| Document or report writing (not slides) | `content-writer` |
| General diagram creation not destined for slides | Use the appropriate diagram tool directly (Mermaid, Graphviz, etc.) |

---

## 8. Reference Files

- `~/.claude/skills/presentation-builder/references/narrative-flows.md` — Narrative arc templates and slide sequencing patterns
- `~/.claude/skills/presentation-builder/references/audience-profiles.md` — Audience-specific tone, depth, and terminology guidance
- `~/.claude/skills/presentation-builder/references/capability-map-schema.md` — JSON schema for the environment capability map

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Starting with slides before defining the narrative | Content-first presentations are disjointed; no storyline means audiences cannot follow the argument | Define audience, purpose, and narrative framework first; slides serve the story, not the other way around |
| Putting everything on one slide | Cognitive overload; audience reads instead of listening; key message is buried in visual noise | One idea per slide; use builds/animations for progressive disclosure; if it needs more, use two slides |
| Using default PowerPoint templates without customization | Signals lack of effort; audience immediately recognizes generic templates; undermines credibility | Apply branding (colors, fonts, logo placement) consistent with your organization; even minimal customization helps |
| Skipping speaker notes | Presenters forget key points; different presenters deliver different messages from the same deck | Write speaker notes for every slide with key talking points, transition phrases, and timing estimates |
| Not tailoring content to the audience | A technical deep-dive for executives or a strategic overview for engineers — both fail | Use the presentation-narrative skill to select audience-appropriate frameworks; match depth to audience |
