---
name: presentation-styling
description: >
  Use when a presentation needs template selection, branding enforcement, color palettes, tone
  profiles, or layout conventions — asset management, consulting slide standards, and visual
  identity enforcement. Part of the presentation-* skill family.
---

# Presentation Styling

Child of `presentation-builder`. This skill owns all visual identity concerns: templates, branding, color palettes, tone profiles, layout conventions, and consulting slide standards. It does NOT own content creation (narrative), data visualization (datavis), diagram generation (diagrams), or final file assembly (renderer).

**Siblings:**

- `presentation-narrative` — Outline generation, storytelling structure, slide sequencing
- `presentation-datavis` — Charts, data visualization, data-driven slides
- `presentation-diagrams` — Architecture diagrams, flowcharts, system visuals
- `presentation-renderer` — Final assembly, PPTX/HTML export, format conversion

---

## When NOT to Use This Skill

| Request | Use Instead |
|---|---|
| Writing slide content, outlines, or narrative arcs | `presentation-narrative` |
| Creating charts or data-driven visuals | `presentation-datavis` |
| Building architecture diagrams or flowcharts | `presentation-diagrams` |
| Exporting to PPTX/HTML or format conversion | `presentation-renderer` |
| Full end-to-end deck creation (intake + routing) | `presentation-builder` |
| Image generation not destined for slides | `nano-banana` or `vertex-banana` |

---

## 1. Asset Repository CRUD

All styling assets live in a two-tier directory structure. Project-local overrides global on matching keys.

### Directory Layout

**Global path:**

```
~/.claude/skills/presentation-builder/assets/
  templates/       # Base slide templates (.pptx, .css, theme.json)
  logos/            # Reusable logos
  palettes/         # Color palettes (JSON)
  tone-profiles/    # Tone definitions (JSON)
```

**Project-local path:**

```
<project>/.presentations/
  templates/       # Project-specific templates
  logos/            # Project / client logos
  palettes/         # Project color palettes
  tone-profiles/    # Project tone overrides
  output/           # Generated presentations
```

### Operations

**List** — Show available templates, logos, palettes, and tone profiles. Merge global and project-local inventories into a single table. Mark each item with its source (global or project-local). When both sources contain an asset with the same name, show only the project-local version (it wins).

**Add** — Copy a user-provided template, logo, palette, or tone profile into the appropriate directory. Default target is project-local. If the user explicitly requests global storage, write to the global assets path instead. Validate the asset format before saving (JSON must parse, images must be a supported format, PPTX must be openable).

**Update** — Replace an existing asset. Confirm the asset exists before overwriting. Back up the previous version by appending `.bak` before replacing.

**Remove** — Delete an asset. Confirm with the user before deleting. If the asset is project-local and a global version exists, inform the user that the global version will now take effect.

---

## 2. Template Management

### PPTX Templates

The user provides a `.pptx` file with master slides and layouts already defined. Store it in the appropriate `templates/` directory. When building a deck, the renderer will apply the template as the base for all slides.

Required layouts in a well-formed PPTX template:

- Title Slide
- Content Slide (action title + body)
- Two-Column Slide
- Section Divider
- Chart / Visual Slide
- Closing Slide

### HTML Themes

CSS themes for reveal.js or Marp. Stored as `.css` files or `theme.json` configuration objects in the `templates/` directory.

A `theme.json` file maps palette tokens to CSS variables:

```json
{
  "name": "corporate-blue",
  "engine": "marp",
  "palette": "corporate-blue",
  "css_file": "corporate-blue.css",
  "font_heading": "Calibri, Arial, sans-serif",
  "font_body": "Calibri, Arial, sans-serif",
  "font_code": "Consolas, 'Courier New', monospace"
}
```

### Template Selection

Match the template to the audience profile received from the parent skill:

| Audience Profile | Default Template |
|---|---|
| Executive | corporate-blue |
| Technical | dark-modern |
| Client / External | corporate-blue |
| Mixed | corporate-blue |
| Banking / Regulatory | corporate-blue |

The user can override the default selection at any time.

### First-Time Setup

If no templates exist in either global or project-local directories, generate minimal defaults:

1. A basic Marp CSS theme with the `corporate-blue` palette applied.
2. A `theme.json` mapping file for the default theme.
3. Log a note recommending the user provide a branded `.pptx` template for higher-fidelity output.

---

## 3. Color Palette System

Palettes are stored as JSON files in the `palettes/` directory.

### Palette Schema

```json
{
  "name": "corporate-blue",
  "primary": "#1B365D",
  "secondary": "#4A90D9",
  "accent": "#E07020",
  "background": "#FFFFFF",
  "text": "#333333",
  "text-light": "#FFFFFF",
  "success": "#2D8B46",
  "warning": "#D4A017",
  "danger": "#C0392B",
  "neutral": "#95A5A6"
}
```

### Default Palettes

Provide three defaults on first-time setup:

**corporate-blue** — Professional blue tones. Primary `#1B365D`, secondary `#4A90D9`, accent `#E07020`.

**dark-modern** — Dark background for technical audiences. Primary `#1E1E2E`, secondary `#89B4FA`, accent `#F38BA8`, background `#1E1E2E`, text `#CDD6F4`, text-light `#FFFFFF`.

**warm-neutral** — Soft warm tones for client-facing decks. Primary `#5C4033`, secondary `#C4A882`, accent `#D4763C`, background `#FAF7F2`, text `#3E3E3E`, text-light `#FFFFFF`.

### RAG Color Standard

Red-Amber-Green status colors are standardized across all palettes and must not be overridden per-palette:

- **Green (success):** `#2D8B46`
- **Amber (warning):** `#D4A017`
- **Red (danger):** `#C0392B`

---

## 4. Tone Profiles

Tone profiles control language formality, data density, slide constraints, and visual style. Stored as JSON files in the `tone-profiles/` directory.

### Tone Profile Schema

```json
{
  "name": "executive",
  "formality": "high",
  "jargon_level": "low",
  "data_density": "headline_metrics_only",
  "slide_count_max": 12,
  "font_size_min": 24,
  "preferred_flows": ["minto-scr", "bluf", "status-risks-next"],
  "title_style": "action_title_mandatory",
  "visual_style": "clean_minimal"
}
```

### Default Tone Profiles

**executive** — High formality, low jargon, headline metrics only, max 12 slides, min font 24pt. Preferred flows: minto-scr, bluf, status-risks-next. Action titles mandatory, clean minimal visuals.

**technical** — Medium formality, high jargon acceptable, detailed data density, max 25 slides, min font 18pt. Preferred flows: problem-solution, deep-dive, architecture-walkthrough. Action titles mandatory, diagram-heavy visuals.

**client-facing** — High formality, low jargon, balanced data density, max 15 slides, min font 22pt. Preferred flows: minto-scr, bluf, value-proposition. Action titles mandatory, polished brand-forward visuals.

**mixed** — Medium formality, moderate jargon, balanced data density, max 18 slides, min font 20pt. Preferred flows: minto-scr, problem-solution, status-risks-next. Action titles mandatory, clean visuals with selective detail.

---

## 5. Layout Conventions

Standard slide layouts that apply across all templates. These are the canonical layouts that the renderer will map to template-specific masters.

### Title Slide

- Centered title (large, bold)
- Subtitle below title (smaller, lighter weight)
- Date below subtitle
- Logo bottom-right
- Optional: author name, department

### Content Slide

- Action title top-left (states the takeaway, not the topic)
- Body content center (bullet points, text, or single visual)
- Source line bottom-left (when data is referenced)

### Two-Column Slide

- Action title top spanning full width
- Left column: text / bullet points
- Right column: visual / chart / diagram
- Source line bottom-left

### Section Divider

- Section name centered vertically and horizontally
- Contrasting background color (use palette `primary` or `secondary`)
- Text in `text-light` color
- No logo, no source line

### Chart Slide

- Action title top (states the chart's takeaway)
- Chart centered, occupying primary visual space
- Callout box highlighting the key data point (positioned near the relevant area of the chart)
- Source line bottom-left

### Closing Slide

- "Thank you" or "Questions?" centered
- Contact information below center text
- Logo centered, larger than on content slides
- Optional: QR code, follow-up links

---

## 6. Consulting Slide Standards

These standards are always applied regardless of template, palette, or audience profile.

### Action Titles

Every slide title states the takeaway, never the topic. Reading the titles across the deck in sequence must tell the complete story (the horizontal flow test).

- BAD: "Q3 Revenue"
- GOOD: "Q3 revenue grew 12% driven by enterprise expansion"

### One Idea Per Slide

Each slide communicates exactly one message. If a slide requires two takeaways, split it into two slides.

### Horizontal Flow

The sequence of action titles, read left to right through the deck, must form a coherent narrative. Test this by listing all titles — they should read like an executive summary.

### Source Lines

Every slide that references data must include a source line at the bottom. Format: `Source: [dataset/report name], [date]`.

### Callout Boxes

Key data points on chart slides get a callout box — a bordered or shaded rectangle highlighting the critical number with a brief label.

### Chart Hygiene

- Minimal grid lines (light gray, not black)
- No chart junk (no 3D effects, no unnecessary decoration)
- Consistent chart position and size across the deck
- Axis labels must be readable at the minimum font size for the tone profile

---

## 7. Logo Placement Rules

### Title Slide

Logo centered or bottom-right, sized appropriately (typically 15-20% of slide width). Must not compete with the title text.

### Content Slides

Logo top-right corner, small (typically 5-8% of slide width). Must not distract from slide content.

### Closing Slide

Logo centered, larger than on content slides (typically 20-30% of slide width).

### Logo Storage

When the user provides a logo file, store it in the appropriate assets directory:

- Project-specific logo: `<project>/.presentations/logos/`
- Reusable logo: `~/.claude/skills/presentation-builder/assets/logos/`

Supported formats: PNG (preferred for transparency), SVG, JPEG.

---

## 8. Hard Rules

1. **Never apply styling that contradicts audience profile norms.** If the tone profile says `formality: high`, do not use casual fonts, bright neon palettes, or informal layouts.
2. **Templates must be reusable.** After creating or customizing a template, save it to the assets repository so it can be reused across presentations.
3. **WCAG AA contrast ratios are mandatory.** All text-on-background color combinations must meet WCAG AA minimum contrast (4.5:1 for normal text, 3:1 for large text). Validate palette combinations before applying.
4. **Font selections need cross-platform fallback chains.** Always specify fallback fonts. Examples:
   - Headings: `"Calibri, Arial, sans-serif"`
   - Body: `"Calibri, Arial, sans-serif"`
   - Code: `"Consolas, 'Courier New', monospace"`
5. **RAG colors are immutable.** The standardized green/amber/red values must not be overridden by any palette or template customization.
6. **Project-local always overrides global.** When resolving any asset, the project-local version wins if it exists.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using more than 3 fonts in a deck | Visual chaos; looks unprofessional; undermines the content credibility | One serif + one sans-serif maximum; use weight/size variations within those two font families |
| Inconsistent color usage across slides | Audiences assign meaning to colors; random color changes break that mental model | Define a palette (primary, secondary, accent, neutral) and use consistently; same color = same meaning throughout |
| Text smaller than 18pt on projected slides | Unreadable from the back of the room; audience squints instead of listening | Minimum 24pt for body text, 32pt+ for titles; if it does not fit, split the slide |
| No whitespace — filling every pixel | Cluttered slides increase cognitive load; no visual hierarchy; everything competes for attention | Use generous margins and padding; whitespace is a design element that directs focus |
| Ignoring the organization's brand guidelines | Deck looks like it was made by an outsider; credibility suffers; brand police flag it in review | Load organization templates first; match exact brand colors, approved fonts, and logo placement rules |
