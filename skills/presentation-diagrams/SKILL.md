---
name: presentation-diagrams
description: >
  Use when a presentation needs architecture diagrams, flowcharts, sequence diagrams, or system
  visuals — tagged [DIAGRAM] slides from narrative, "add a visual of how X connects to Y", or
  any system overview visualization for slides. Part of the presentation-* skill family.
---

# Presentation Diagrams

Child of `presentation-builder`. Generates architecture diagrams, flowcharts, sequence diagrams, and system visuals for embedding into presentation slides.

## Sibling Skills

- **presentation-narrative** — Outline generation, storytelling structure, slide sequencing
- **presentation-datavis** — Charts, data visualization, data-driven slides
- **presentation-styling** — Templates, branding, colour palettes, typography
- **presentation-renderer** — Final assembly, PPTX/HTML export, format conversion

---

## When NOT to Use This Skill

| Request | Use Instead |
|---|---|
| Standalone image generation (not for slides) | `vertex-banana` |
| Data charts, bar graphs, pie charts, line charts | `presentation-datavis` |
| General diagram not destined for a presentation | Use Mermaid, Graphviz, or PlantUML directly |
| Styling, branding, or layout changes | `presentation-styling` |
| Full presentation build from scratch | `presentation-builder` (parent will route here when needed) |

---

## 1. Tool Selection

Select the rendering tool based on the diagram's purpose. Priority order:

1. **mermaid-cli (mmdc)** — Deterministic flowcharts, sequence diagrams, ER diagrams, state diagrams, class diagrams, Gantt charts
2. **graphviz (dot)** — Architecture/topology diagrams, network diagrams, complex directed/undirected graphs
3. **plantuml** — UML-specific diagrams (activity, component, deployment) when Mermaid lacks coverage
4. **vertex-banana (AI image gen)** — Cover art, illustrative visuals, icons, conceptual images ONLY
5. **ASCII art** — Always works, zero dependencies; use as last resort or for quick inline previews

### Critical Rules

- **Deterministic renderers (mermaid, graphviz, plantuml)** for: architecture diagrams, flowcharts, sequence diagrams, ER diagrams, class diagrams, state diagrams, network diagrams — anything with precise labels and connections.
- **AI image generation (vertex-banana)** ONLY for: cover art, illustrative visuals, icons, conceptual images that do not require precise text labels.
- **NEVER** use AI image generation for architecture diagrams, flowcharts, sequence diagrams, or anything requiring precise text labels. Deterministic renderers only.

---

## 2. Diagram Type Routing

| Diagram Need | Best Tool | Syntax / Entry Point |
|---|---|---|
| Flowchart | mermaid | `graph TD` / `graph LR` |
| Sequence diagram | mermaid | `sequenceDiagram` |
| Class diagram | mermaid | `classDiagram` |
| ER diagram | mermaid | `erDiagram` |
| State diagram | mermaid | `stateDiagram-v2` |
| Gantt chart | mermaid | `gantt` |
| Architecture / topology | graphviz | `digraph { }` |
| Network diagram | graphviz | `graph { }` |
| C4 model | mermaid (C4 plugin) or graphviz | `C4Context` / `C4Container` |
| UML specific | plantuml | `@startuml` |
| Creative / illustrative | vertex-banana | prompt-based |

When the capability map (from `presentation-builder`) shows a tool is unavailable, fall back to the next available tool in the priority list. If no renderer is available, generate ASCII art.

---

## 3. Auto-Generation from Project Context

When a project context exists, automatically generate diagrams from available artifacts:

| Source Artifact | Generated Diagram |
|---|---|
| `PROJECT.md` | System architecture overview diagram |
| `docs/components/*/COMPONENT.md` | Component interaction / dependency diagram |
| Problem statement or proposal doc | Problem-to-solution flow diagram |
| Tech stack / dependency list | Technology stack layer diagram |
| API routes or endpoint definitions | Sequence diagram for key API flows |

### Process

1. Read the source artifact(s).
2. Extract entities, relationships, and data flows.
3. Select the appropriate diagram type from the routing table above.
4. Generate the diagram source file (.mmd, .dot, or .puml).
5. Render to the output format (.svg preferred, .png fallback).
6. Return file paths for `presentation-renderer` to embed.

---

## 4. Generation Patterns

### Mermaid

```bash
# Write the diagram source
cat > .presentations/output/assets/diagram-name.mmd << 'EOF'
graph TD
    A[Service A] --> B[Service B]
    B --> C[(Database)]
EOF

# Render to SVG (dark theme for dark slide backgrounds)
npx @mermaid-js/mermaid-cli -i .presentations/output/assets/diagram-name.mmd \
    -o .presentations/output/assets/diagram-name.svg \
    -t dark

# Or default theme for light slide backgrounds
npx @mermaid-js/mermaid-cli -i .presentations/output/assets/diagram-name.mmd \
    -o .presentations/output/assets/diagram-name.svg \
    -t default
```

### Graphviz

```bash
# Write the diagram source
cat > .presentations/output/assets/diagram-name.dot << 'EOF'
digraph architecture {
    rankdir=LR;
    node [shape=box, style=filled, fillcolor="#e8e8e8", fontsize=14];

    ServiceA -> ServiceB [label="REST"];
    ServiceB -> Database [label="SQL"];
    Database [shape=cylinder];
}
EOF

# Render to SVG
dot -Tsvg .presentations/output/assets/diagram-name.dot > .presentations/output/assets/diagram-name.svg
```

### PlantUML

```bash
# Write the diagram source
cat > .presentations/output/assets/diagram-name.puml << 'EOF'
@startuml
component "Service A" as A
component "Service B" as B
database "Database" as DB

A --> B : REST
B --> DB : SQL
@enduml
EOF

# Render (requires plantuml.jar or plantuml CLI)
plantuml -tsvg .presentations/output/assets/diagram-name.puml
```

### AI Image Generation (Creative Visuals Only)

Invoke the `vertex-banana` skill for illustrative visuals, cover art, or conceptual images. Never for architecture or labeled diagrams.

### Output Location

All outputs are saved to:

```
<project>/.presentations/output/assets/
```

Both the source file (.mmd, .dot, .puml) and the rendered output (.svg, .png) are saved side by side.

---

## 5. Diagram Styling

### Palette Matching

- Query `presentation-styling` for the active colour palette before rendering.
- Apply palette colours to node fills, borders, and connection lines.
- If no palette is set, use a clean neutral palette (greys, blues, whites).

### Shape Conventions

| Entity Type | Shape |
|---|---|
| Service / application | Rectangle |
| Database / data store | Cylinder |
| External system / cloud | Cloud |
| User / actor | Stick figure or rounded rectangle |
| Queue / message broker | Parallelogram or trapezoid |
| Decision point | Diamond |
| Process / action | Rounded rectangle |

### Readability Rules

- Labels must be readable at slide size: **12pt+ equivalent** font size in rendered output.
- Clean, minimal style — no decorative borders, shadows, or gradients.
- Use whitespace and grouping (subgraphs, clusters) to separate logical domains.
- Connection labels should be concise (1-3 words): protocol, data type, or action.
- Limit nodes per diagram to ~15. Split into multiple diagrams if more complex.

### Theme Selection

- Use `-t dark` (Mermaid) or dark-background colours when slides use a dark theme.
- Use `-t default` (Mermaid) or light-background colours when slides use a light theme.
- Match the theme to the presentation palette from `presentation-styling`.

---

## 6. Hard Rules

1. **Never use AI image generation for architecture diagrams.** Deterministic renderers only for anything with labels, connections, or structural meaning.
2. **Always label all nodes and connections.** Unlabeled nodes or unnamed arrows are not permitted.
3. **Diagrams must be self-explanatory without speaker notes.** A viewer should understand the diagram without additional verbal context.
4. **Save both source and rendered output.** Always keep the source file (.mmd, .dot, .puml) alongside the rendered file (.svg, .png) so diagrams can be edited later.
5. **Return file paths for `presentation-renderer` to embed.** Every generated diagram must report its output path so the renderer can include it in the final deck.
6. **One concept per diagram.** Do not overload a single diagram. Split complex systems into multiple focused diagrams.
7. **Verify rendering succeeded.** After running the render command, confirm the output file exists and has non-zero size before reporting success.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Including every system component in one architecture diagram | Visual overload; audience cannot find the relevant parts; key message is lost in complexity | Show only the components relevant to the current discussion; use progressive disclosure across slides |
| Using inconsistent shapes and colors for the same concept | Audiences learn a visual language from the first slide; changing it mid-deck causes confusion | Define a visual key: boxes = services, cylinders = databases, arrows = data flow; maintain consistently |
| No legend or labels on technical diagrams | Only the author knows what the shapes mean; diagram becomes meaningless in two weeks | Always include a legend for shape types; label every component and connection |
| Using screenshots of code instead of sequence diagrams | Code screenshots are unreadable on projected slides; non-developers cannot follow | Use sequence diagrams for flow, activity diagrams for processes; reference code in handouts, not slides |
| Cramming too much into a single flowchart | More than 10-12 nodes on a slide becomes unreadable; audience loses the thread | Split complex flows across multiple slides with clear "you are here" indicators |
