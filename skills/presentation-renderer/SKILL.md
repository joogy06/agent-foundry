---
name: presentation-renderer
description: >
  Use when slide outlines, visuals, and styling are ready to compile into final PPTX and/or
  HTML output — export, "generate the file", "give me the PPTX", create HTML slides.
  Part of the presentation-* skill family.
triggers:
  - export
  - generate the file
  - give me the PPTX
  - create HTML slides
  - format conversion
  - final output generation
  - render slides
  - export to PowerPoint
  - build the deck file
family: presentation
---

# Presentation Renderer

Child of `presentation-builder`. This skill handles the final compilation step: taking a structured slide outline (from `presentation-narrative`), visual assets (from `presentation-datavis` and `presentation-diagrams`), and styling tokens (from `presentation-styling`) and producing deliverable PPTX and/or HTML files.

**Siblings:** `presentation-narrative`, `presentation-datavis`, `presentation-diagrams`, `presentation-styling`.

## When NOT to Use

- **Content strategy or outline creation** -- use `presentation-narrative`
- **Chart/graph generation** -- use `presentation-datavis`
- **Architecture or flow diagrams** -- use `presentation-diagrams`
- **Theme design, color palettes, typography** -- use `presentation-styling`
- **Overall orchestration of a deck from scratch** -- use `presentation-builder` (parent)

Use this skill only when the outline and assets are ready and the task is to produce the final file(s).

---

## 1. Engine Selection

Select the rendering engine based on what is available in the environment. Always prefer the highest-ranked option that is confirmed present.

### PPTX Fallback Chain

| Priority | Engine | Notes |
|----------|--------|-------|
| 1 | **python-pptx** | Preferred. Native editable PPTX, full template support, cross-platform. |
| 2 | Apache POI XSLF | Java fallback. Requires JVM. |
| 3 | PowerShell COM | Windows-only. Requires PowerPoint installed. |
| 4 | Marp `--pptx-editable` | Experimental. Markdown source required. |
| 5 | HTML only | If no PPTX engine is available, fall back to HTML output. |

### HTML Fallback Chain

| Priority | Engine | Notes |
|----------|--------|-------|
| 1 | **reveal.js** | Best for agent-controlled output. Offline capable. Single-file possible. |
| 2 | Marp | Fastest markdown-to-slides path. |
| 3 | Raw HTML | Always works. Inline CSS. No dependencies. |

**Capability detection:** Before rendering, verify the engine is available (e.g., `python -c "import pptx"`, check for `marp` on PATH, check for Java). Record the result and proceed down the chain on failure.

---

## 2. Python-pptx Generation Pattern

This is the primary rendering path. All slide types follow the same structure: load template, add slide from layout, populate placeholders, save.

```python
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor

# Load template or create new
prs = Presentation("template.pptx")  # or Presentation()

# --- Title Slide ---
slide = prs.slides.add_slide(prs.slide_layouts[0])
slide.shapes.title.text = "Presentation Title"
slide.placeholders[1].text = "Subtitle — Date — Author"
slide.notes_slide.notes_text_frame.text = "Opening remarks and context."

# --- Content Slide (action title + bullets) ---
slide = prs.slides.add_slide(prs.slide_layouts[1])
slide.shapes.title.text = "Key takeaway as the title"
body = slide.placeholders[1]
tf = body.text_frame
tf.text = "Supporting point 1"
p = tf.add_paragraph()
p.text = "Supporting point 2"
p.level = 0
slide.notes_slide.notes_text_frame.text = "Expand on points 1 and 2."

# --- Two-Column Slide ---
slide = prs.slides.add_slide(prs.slide_layouts[3])  # two-content layout
slide.shapes.title.text = "Comparison Title"
left = slide.placeholders[1]
left.text_frame.text = "Left column content"
right = slide.placeholders[2]
right.text_frame.text = "Right column content"
slide.notes_slide.notes_text_frame.text = "Compare left vs right."

# --- Image / Chart Slide ---
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
slide.shapes.title.text = "Chart Title"  # add title textbox if blank layout
slide.shapes.add_picture(
    "chart.png",
    Inches(1), Inches(1.5),
    Inches(8), Inches(5)
)
# Add source line
from pptx.util import Pt
txBox = slide.shapes.add_textbox(Inches(1), Inches(6.6), Inches(8), Inches(0.3))
txBox.text_frame.text = "Source: Internal analytics, Q4 2025"
txBox.text_frame.paragraphs[0].font.size = Pt(8)
txBox.text_frame.paragraphs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)
slide.notes_slide.notes_text_frame.text = "Explain chart trends and data source."

# --- Table Slide ---
slide = prs.slides.add_slide(prs.slide_layouts[1])
slide.shapes.title.text = "Data Summary"
rows, cols = 4, 3
table_shape = slide.shapes.add_table(rows, cols, Inches(1), Inches(2), Inches(8), Inches(3.5))
table = table_shape.table
# Header row
for col_idx, header in enumerate(["Metric", "Q3", "Q4"]):
    table.cell(0, col_idx).text = header
# Data rows
for row_idx, row_data in enumerate([
    ["Revenue", "$1.2M", "$1.5M"],
    ["Users", "10K", "14K"],
    ["NPS", "72", "78"],
], start=1):
    for col_idx, val in enumerate(row_data):
        table.cell(row_idx, col_idx).text = val
slide.notes_slide.notes_text_frame.text = "Walk through each metric row."

# --- Section Divider ---
slide = prs.slides.add_slide(prs.slide_layouts[2])  # section header layout
slide.shapes.title.text = "Section 2: Deep Dive"
if slide.placeholders.get(1):
    slide.placeholders[1].text = "Transition message"
slide.notes_slide.notes_text_frame.text = "Pause before transitioning."

# --- Closing Slide ---
slide = prs.slides.add_slide(prs.slide_layouts[0])
slide.shapes.title.text = "Thank You"
slide.placeholders[1].text = "Questions? — contact@example.com"
slide.notes_slide.notes_text_frame.text = "Open the floor for Q&A."

# Save
prs.save("output.pptx")
```

**Layout index reference** (common defaults; always verify against the loaded template):

| Index | Typical Layout |
|-------|---------------|
| 0 | Title Slide |
| 1 | Title and Content |
| 2 | Section Header |
| 3 | Two Content |
| 4 | Comparison |
| 5 | Title Only |
| 6 | Blank |

---

## 3. reveal.js HTML Generation Pattern

Generate a single self-contained HTML file. For offline delivery, embed CSS and JS inline.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Presentation Title</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/theme/white.css">
  <style>
    /* Custom overrides from presentation-styling tokens */
    .reveal h1, .reveal h2 { font-family: 'Inter', sans-serif; }
    .reveal .source-line { font-size: 0.5em; color: #888; text-align: right; }
  </style>
</head>
<body>
  <div class="reveal"><div class="slides">

    <!-- Title Slide -->
    <section>
      <h1>Presentation Title</h1>
      <p>Subtitle — Date — Author</p>
      <aside class="notes">Opening remarks and context.</aside>
    </section>

    <!-- Content Slide -->
    <section>
      <h2>Key Takeaway as the Title</h2>
      <ul>
        <li>Supporting point 1</li>
        <li>Supporting point 2</li>
      </ul>
      <aside class="notes">Expand on points 1 and 2.</aside>
    </section>

    <!-- Two-Column Slide -->
    <section>
      <h2>Comparison Title</h2>
      <div style="display: flex; gap: 2em;">
        <div style="flex: 1;"><h3>Left</h3><p>Left column content</p></div>
        <div style="flex: 1;"><h3>Right</h3><p>Right column content</p></div>
      </div>
      <aside class="notes">Compare left vs right.</aside>
    </section>

    <!-- Chart Slide -->
    <section>
      <h2>Chart Title</h2>
      <img src="chart.png" alt="Chart description" style="max-height: 70vh;">
      <p class="source-line">Source: Internal analytics, Q4 2025</p>
      <aside class="notes">Explain chart trends and data source.</aside>
    </section>

    <!-- Section Divider -->
    <section data-background-color="#003366">
      <h2 style="color: white;">Section 2: Deep Dive</h2>
      <aside class="notes">Pause before transitioning.</aside>
    </section>

    <!-- Closing Slide -->
    <section>
      <h1>Thank You</h1>
      <p>Questions? — contact@example.com</p>
      <aside class="notes">Open the floor for Q&A.</aside>
    </section>

  </div></div>

  <script src="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.js"></script>
  <script>
    Reveal.initialize({
      hash: true,
      slideNumber: true,
      showNotes: false,       // set true for presenter view
      transition: 'slide'
    });
  </script>
</body>
</html>
```

**Offline variant:** Replace CDN links with inline `<style>` and `<script>` blocks containing the full reveal.js CSS and JS. This produces a single portable HTML file.

---

## 4. Marp Markdown Pattern

Use when Marp CLI is available and markdown source is preferred.

```markdown
---
marp: true
theme: default
paginate: true
header: "Company Name"
footer: "Confidential"
---

# Presentation Title
Subtitle — Date — Author

<!-- Speaker notes: Opening remarks and context. -->

---

## Key Takeaway as the Title
- Supporting point 1
- Supporting point 2

<!-- Speaker notes: Expand on points 1 and 2. -->

---

<!-- _class: lead -->
## Section 2: Deep Dive

<!-- Speaker notes: Pause before transitioning. -->

---

## Chart Title

![bg right:60%](chart.png)

<small>Source: Internal analytics, Q4 2025</small>

<!-- Speaker notes: Explain chart trends and data source. -->

---

## Data Summary

| Metric  | Q3    | Q4    |
|---------|-------|-------|
| Revenue | $1.2M | $1.5M |
| Users   | 10K   | 14K   |

<!-- Speaker notes: Walk through each metric row. -->

---

# Thank You
Questions? — contact@example.com

<!-- Speaker notes: Open the floor for Q&A. -->
```

**Render commands:**
```bash
marp deck.md -o deck.html          # HTML slides
marp deck.md -o deck.pptx          # PPTX (experimental)
marp deck.md -o deck.pdf           # PDF
marp deck.md --html -o deck.html   # HTML with raw HTML tags enabled
```

---

## 5. Apache POI Pattern (Java)

Use as a PPTX fallback when python-pptx is unavailable but a JVM is present.

```java
import org.apache.poi.xslf.usermodel.*;
import java.io.FileOutputStream;
import java.awt.Rectangle;

XMLSlideShow ppt = new XMLSlideShow();

// Title slide
XSLFSlideLayout titleLayout = ppt.getSlideMasters().get(0)
    .getLayout(SlideLayout.TITLE);
XSLFSlide slide = ppt.createSlide(titleLayout);
slide.getPlaceholder(0).setText("Presentation Title");
slide.getPlaceholder(1).setText("Subtitle — Date — Author");
XSLFNotes notes = ppt.getNotesSlide(slide);
notes.getPlaceholder(1).setText("Opening remarks.");

// Content slide
XSLFSlideLayout contentLayout = ppt.getSlideMasters().get(0)
    .getLayout(SlideLayout.TITLE_AND_CONTENT);
XSLFSlide contentSlide = ppt.createSlide(contentLayout);
contentSlide.getPlaceholder(0).setText("Key Takeaway");
XSLFTextShape body = contentSlide.getPlaceholder(1);
body.clearText();
body.addNewTextParagraph().addNewTextRun().setText("Point 1");
body.addNewTextParagraph().addNewTextRun().setText("Point 2");

// Image slide
XSLFSlide imgSlide = ppt.createSlide();
byte[] imgData = java.nio.file.Files.readAllBytes(
    java.nio.file.Paths.get("chart.png"));
XSLFPictureData pd = ppt.addPicture(imgData, PictureData.PictureType.PNG);
imgSlide.createPicture(pd)
    .setAnchor(new Rectangle(72, 108, 576, 360));

// Save
try (FileOutputStream out = new FileOutputStream("output.pptx")) {
    ppt.write(out);
}
ppt.close();
```

---

## 6. PowerShell COM Pattern (Windows)

Use only on Windows with PowerPoint installed. Note: colors use BGR order, not RGB.

```powershell
$ppt = New-Object -ComObject PowerPoint.Application
$ppt.Visible = $true  # set $false for headless

$pres = $ppt.Presentations.Add()

# Title slide (layout enum: ppLayoutTitle = 1)
$slide = $pres.Slides.Add(1, 1)
$slide.Shapes.Title.TextFrame.TextRange.Text = "Presentation Title"
$slide.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = "Subtitle"
$slide.NotesPage.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = "Opening remarks."

# Content slide (ppLayoutText = 2)
$slide2 = $pres.Slides.Add(2, 2)
$slide2.Shapes.Title.TextFrame.TextRange.Text = "Key Takeaway"
$body = $slide2.Shapes.Placeholders.Item(2).TextFrame.TextRange
$body.Text = "Point 1`r`nPoint 2"
$slide2.NotesPage.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = "Details."

# Image slide (ppLayoutBlank = 12)
$slide3 = $pres.Slides.Add(3, 12)
$slide3.Shapes.AddPicture(
    "$PWD\chart.png",  # file path
    $false,            # LinkToFile
    $true,             # SaveWithDocument
    72, 108, 576, 360  # Left, Top, Width, Height (points)
)

# Save and close
$pres.SaveAs("$PWD\output.pptx")
$pres.Close()
$ppt.Quit()
[System.Runtime.Interopservices.Marshal]::ReleaseComObject($ppt) | Out-Null
```

**BGR color note:** When setting font or shape colors via COM, use BGR hex (e.g., `$shape.TextFrame.TextRange.Font.Color.RGB = 0xBB6600` for RGB `#0066BB`).

---

## 7. Image Embedding

All visual assets are produced by sibling skills and written to `<project>/.presentations/output/assets/`.

| Source Skill | Asset Type | Embed Method |
|-------------|-----------|-------------|
| `presentation-datavis` | Chart PNG | `add_picture()` at specified position |
| `presentation-diagrams` | Diagram SVG/PNG | `add_picture()` (convert SVG to PNG if engine requires) |
| `presentation-styling` | Logo PNG | Place per layout rules (e.g., bottom-right corner) |

**Rules:**
- Reference all images by absolute file path from `.presentations/output/assets/`.
- For PPTX, images are embedded in the file (no external references).
- For HTML, images can be embedded as base64 data URIs for offline portability, or referenced by relative path.
- SVG is preferred for diagrams in HTML; convert to PNG for PPTX (python-pptx does not support SVG natively).

---

## 8. Speaker Notes

Speaker notes are mandatory on every slide, including section dividers and closing slides.

| Engine | Method |
|--------|--------|
| python-pptx | `slide.notes_slide.notes_text_frame.text = "..."` |
| reveal.js | `<aside class="notes">...</aside>` inside `<section>` |
| Marp | HTML comment: `<!-- Speaker notes: ... -->` |
| Apache POI | `ppt.getNotesSlide(slide).getPlaceholder(1).setText("...")` |
| PowerShell COM | `$slide.NotesPage.Shapes.Placeholders.Item(2).TextFrame.TextRange.Text = "..."` |

**Content guidance:** Notes should contain talking points, not a script. Include: what to emphasize, data source references, transition cues.

---

## 9. Output Management

### File Naming
```
YYYY-MM-DD_topic-slug.pptx
YYYY-MM-DD_topic-slug.html
```
Example: `2026-03-27_quarterly-review.pptx`

### Output Directory
```
<project>/.presentations/output/
<project>/.presentations/output/assets/   # charts, diagrams, logos
```

### Post-Render Checklist
1. Verify output file exists at the expected path.
2. Confirm file size is non-zero.
3. Generate both PPTX and HTML when the capability map supports it.
4. Present the final file path(s) to the user.

```python
import os

output_path = ".presentations/output/2026-03-27_quarterly-review.pptx"
assert os.path.exists(output_path), f"Output not found: {output_path}"
assert os.path.getsize(output_path) > 0, f"Output is empty: {output_path}"
print(f"Rendered: {os.path.abspath(output_path)} ({os.path.getsize(output_path):,} bytes)")
```

---

## 10. HARD RULES

1. **Never overwrite existing output without user confirmation.** Check if the target file exists before saving. If it does, ask the user or append a version suffix.
2. **Always validate output file exists and is non-zero.** Run the post-render checklist after every save operation.
3. **Template must be loaded before rendering.** Do not hard-code slide dimensions, fonts, or colors. Load these from the template PPTX or the styling tokens provided by `presentation-styling`.
4. **Speaker notes on every slide.** No exceptions -- even section dividers and closing slides must have at least a brief note.
5. **Source line on every data chart slide.** Any slide containing a chart, graph, or data table must include a visible source attribution (small text, bottom of slide).

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Rendering to PPTX without testing on the target display system | Fonts, animations, and layouts render differently on Mac/Windows/web; broken slides in the meeting | Test rendered output on the actual presentation system; embed fonts; convert custom fonts to paths if needed |
| Including high-resolution images without compression | 50MB+ PPTX files that crash email, take minutes to load, and lag during presentation | Compress images to 150-200 DPI for screen; strip EXIF data; target under 10MB for emailable decks |
| Not including speaker notes in the rendered output | Presenter deck and handout deck are different; rendered file without notes is incomplete | Always include speaker notes in PPTX; generate a separate notes-only PDF for the presenter |
| Rendering without checking slide master consistency | Mixed slide masters produce inconsistent headers, footers, page numbers, and branding | Validate all slides reference the same slide master/layout before rendering; fix orphaned layouts |
| Skipping accessibility checks on final output | Screen readers cannot parse image-heavy slides; colorblind users miss color-coded information | Add alt text to all images; ensure sufficient color contrast; test with accessibility checker |
