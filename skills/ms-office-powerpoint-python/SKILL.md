---
name: ms-office-powerpoint-python
description: Use when reading, writing, transforming, or converting PowerPoint files from Python — .pptx (python-pptx), generating decks from data / Markdown (python-pptx + pypandoc), converting to PDF or image previews (LibreOffice headless), or Markdown-to-slides flows. Covers OOXML XXE defence, image embedding, slide-layout reuse, and the python-pptx maintenance-mode caveat. Part of the ms-office-python-* skill family.
---

# Microsoft PowerPoint — Python

Companion skill to `ms-office-python` (parent). For other areas see: `ms-office-excel-python`, `ms-office-word-python`, `ms-office-graph-python`, `ms-office-enterprise-sso-python`, `ms-office-security-python`.

---

## Overview

`.pptx` (Office Open XML, OOXML) is a zip of XML parts that PowerPoint understands. `python-pptx` is the dominant Python library for reading and writing `.pptx`; it manipulates the XML model directly without needing PowerPoint installed. The 2026 ecosystem state is **stable but in maintenance mode** — see the Gotchas section.

`python-pptx` does NOT render slides — it manipulates the OOXML model only. Previews, thumbnails, and PDF exports route through PowerPoint itself or LibreOffice headless (`soffice --headless --convert-to pdf`). Plan the pipeline accordingly.

For generating PowerPoint decks from richer content sources (Markdown, data, templates), the production-grade path lives in the `presentation-builder` skill family. This skill covers Python-direct work on the `.pptx` format itself.

## Library Selection

| Library | Purpose | Status (2026-05) | OS support | When to use | When NOT to use |
|---|---|---|---|---|---|
| `python-pptx` | Read + write `.pptx` | **Maintenance mode** (stable, minor releases, no major roadmap) | All | All Python-direct `.pptx` work in 2026 | Rendering / previewing — `python-pptx` manipulates the XML model only; it produces no images / PDFs / thumbnails. For previews, route through LibreOffice headless or PowerPoint COM (Windows-only). |
| `pypandoc` | Markdown / RST → `.pptx` via pandoc | Active | All (requires pandoc binary) | Generating decks from Markdown source | Cell-level layout / animation control |
| LibreOffice (`soffice --headless`) | `.pptx` → PDF / PNG previews / video | Active | All | Cross-platform conversion / preview generation | When you don't have LibreOffice (external binary dependency) |
| `pywin32` (`win32com.client.Dispatch("PowerPoint.Application")`) | Drive PowerPoint via COM | Active | Windows only | Full-fidelity PowerPoint automation on Windows | Linux, headless containers, CI runners; flagged as legacy approach for new code |
| `presentation-builder` skill family (existing) | High-level deck-from-content workflows | Active (skill family) | N/A (Skill orchestration) | When building decks from structured data / outline / styling rules | Cell-level XML edits to a `.pptx` (use `python-pptx`) |
| `defusedxml` | XXE defence | Active | All | Any path that parses OOXML XML you don't fully control | (always include in security-conscious code) |

## Install Commands

### RHEL 9 / AlmaLinux 9 / Rocky 9

```bash
sudo dnf install -y python3.12 python3-pip python3-devel gcc-c++ libxml2-devel libxslt-devel
python3 -m pip install --upgrade pip
python3 -m pip install python-pptx defusedxml
# Optional, for PDF / preview / Markdown:
sudo dnf install -y libreoffice-core libreoffice-impress
python3 -m pip install pypandoc
```

### Debian 12 / Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y python3.12 python3-pip python3-dev build-essential libxml2-dev libxslt1-dev
python3 -m pip install --upgrade pip
python3 -m pip install python-pptx defusedxml
sudo apt install -y libreoffice-core libreoffice-impress
python3 -m pip install pypandoc
```

### Windows 11

```powershell
winget install --id Python.Python.3.12 -e --silent
python -m pip install --upgrade pip
python -m pip install python-pptx defusedxml pypandoc
# Optional, requires PowerPoint installed:
#   python -m pip install pywin32
# Optional, headless conversion (no PowerPoint required):
#   winget install --id LibreOffice.LibreOffice -e --silent
```

## Capability Matrix

| Feature | python-pptx | LibreOffice headless | pypandoc | pywin32 COM |
|---|---|---|---|---|
| Read `.pptx` | yes | yes | yes | yes (PowerPoint required) |
| Write `.pptx` | yes | yes (via conversion) | yes | yes (PowerPoint required) |
| Convert to PDF | no | yes | yes (requires latex / chrome) | yes (PowerPoint required) |
| Convert to PNG / thumbnails | no | yes | partial | yes (PowerPoint required) |
| Embed images | yes | yes | yes | yes |
| Embed charts | partial (basic) | partial | partial | yes (full PowerPoint chart engine) |
| Animations / transitions | no | partial (limited) | no | yes (PowerPoint required) |
| Speaker notes | yes | yes | yes | yes |
| Slide layouts (template reuse) | yes | yes | partial | yes |
| Cross-platform | yes | yes | yes | NO (Windows + PowerPoint) |

## Decision Sections

### When to use `python-pptx` vs `presentation-builder`

| Question | Skill |
|---|---|
| "I have a deck template and need to fill in placeholders from data" | `python-pptx` (direct) |
| "I need an architecture-review deck with narrative + datavis + diagrams" | `presentation-builder` family |
| "I want to programmatically tweak slide N of an existing deck" | `python-pptx` (direct) |
| "I want to render Markdown to a deck with consistent styling" | `pypandoc` OR `presentation-builder` |
| "Preview / thumbnail / PDF of an existing deck" | LibreOffice headless OR (Windows only) PowerPoint COM |

The two paths are complementary, not exclusive. `presentation-builder` orchestrates higher-level pieces; `python-pptx` is the low-level primitive.

### Preview / PDF / thumbnail generation

`python-pptx` produces no images. Three options for getting visual output from a `.pptx`:

1. **LibreOffice headless** — cross-platform, no PowerPoint license required:
   ```bash
   soffice --headless --convert-to pdf deck.pptx --outdir /tmp/out
   soffice --headless --convert-to png deck.pptx --outdir /tmp/out   # first slide only
   ```
2. **PowerPoint COM** (Windows only, requires PowerPoint installed):
   ```python
   import win32com.client
   pp = win32com.client.Dispatch("PowerPoint.Application")
   pp.Visible = 1  # COM contract — required even for "headless" use
   deck = pp.Presentations.Open("deck.pptx", WithWindow=False)
   deck.SaveAs("deck.pdf", FileFormat=32)  # PDF
   deck.Close(); pp.Quit()
   ```
3. **External render service** — Graph endpoint `/sites/.../drives/.../items/{id}/preview` for SharePoint-hosted decks, or commercial APIs (out of scope).

LibreOffice headless contention is the same issue as with Word — use a per-process `UserInstallation` profile in parallel CI runs.

### Slide-layout reuse vs raw shapes

`python-pptx` supports two distinct workflows:

- **Layout-driven (preferred)**: open a template `.pptx`, iterate `prs.slide_layouts`, instantiate slides from layouts, fill in placeholders. Output looks consistent and lives in the same theme.
- **Shape-driven (last resort)**: add raw text frames, rectangles, images at absolute (left, top, width, height) coordinates. Works but produces decks that feel hand-mashed; templates / themes / dark mode handling break.

Always start layout-driven. Fall back to shape-driven only when the template doesn't expose the needed placeholder.

## Canonical Pattern (modified C3)

**Open a template, create slides from data, save** — most common PowerPoint task.

```python
# CONFIDENCE: minimal viable pattern — read references/python-pptx-patterns.md for production-ready code.
from pptx import Presentation
from pptx.util import Inches

prs = Presentation("template.pptx")
title_layout = prs.slide_layouts[0]  # Title slide layout (verify index against your template)
for record in [{"title": "Q1", "subtitle": "Revenue up 12%"}, {"title": "Q2", "subtitle": "Revenue up 18%"}]:
    slide = prs.slides.add_slide(title_layout)
    slide.placeholders[0].text = record["title"]     # title placeholder
    slide.placeholders[1].text = record["subtitle"]  # subtitle placeholder
prs.save("output.pptx")
```

The pattern enforces three things: template-driven layouts (consistent visual), data-driven slide generation (not hand-coded shapes), no rendering side-effects (output is `.pptx` only — preview is a separate step).

## Security Hardening

See `ms-office-security-python` for the consolidated checklist. Area-specific items:

- Pair `python-pptx` with `defusedxml`. `python-pptx` uses `lxml` internally; the OOXML parsing path is XXE-exposed in older `lxml` versions.
- For untrusted `.pptx` input, parse in a sandboxed subprocess or container. Embedded OLE objects, linked media, and external relationships can pull in arbitrary network content if the deck is later opened in PowerPoint.
- Inspect `prs.core_properties` (author, last_modified_by, comments, keywords) before publishing externally — PII / internal usernames live here.
- Slides can carry **slide notes** that are not displayed but ship with the file. When generating decks from internal data, ensure speaker-notes content is intentional — don't leak comments / TODOs.
- Embedded media files (videos, audio) increase deck size and can carry their own malicious payloads. Strip or replace `slide.shapes` of type `Media` before publishing externally if provenance is unclear.
- When converting `.pptx` to PDF via LibreOffice headless, run with `--norestore --nodefault --headless --env:UserInstallation=file:///tmp/lo-user-$$` in parallel CI to avoid lockfile contention.
- Refuse to process decks larger than a hard `MAX_BYTES` cap (e.g. 200 MB). Real decks usually fit; pathological ones don't.
- Embedded fonts (in some templates) carry copyright metadata. Ensure license compatibility before redistributing.

## Selection Cheatsheet

- "Read a .pptx programmatically" → `python-pptx`
- "Generate a deck from data + template" → `python-pptx` with layout-driven flow
- "Generate a deck from Markdown" → `pypandoc` OR the `presentation-builder` skill family
- "Convert .pptx → PDF on Linux" → LibreOffice headless
- "Convert .pptx → PDF on Windows with PowerPoint" → `pywin32` COM (legacy; LibreOffice also works)
- "Generate slide-N thumbnails" → LibreOffice headless or external service (no Python-direct option)
- "Read speaker notes" → `slide.notes_slide.notes_text_frame.text`

## Gotchas

- `python-pptx` is in **maintenance mode** as of 2026-05 — stable, minor releases, no major roadmap. It will continue to work for current OOXML, but if Office formats evolve significantly the response may lag. Pin a known-good version, run `pip-audit` regularly (delegate to `dep-currency-check`), and watch the GitHub repo.
- `python-pptx` does NOT render — no thumbnails, no PDF, no images. This bites every newcomer; plan the rendering step explicitly.
- Slide-layout indices are template-specific. Hardcoding `prs.slide_layouts[0]` works for the default template but breaks the moment someone substitutes a customised template. Look up by `layout.name` for portable code.
- Embedded charts in `python-pptx` are basic (bar, line, pie). Sankeys, treemaps, complex composites must be pre-rendered as images and inserted as `Picture` shapes.
- Speaker notes silently inherit theme fonts; setting `notes.text_frame.text = ...` strips font / colour. Use `notes.text_frame.paragraphs[0].add_run(...)` for styled notes.
- `prs.save(path)` overwrites without warning. Layer file-existence checks if overwrite is undesirable.
- `python-pptx` cannot edit `.ppt` (legacy Office 97-2003 PowerPoint format). Convert through LibreOffice first.

## Update Triggers (per Codex M-1 — alf will scan these)

- Major version bump of: `python-pptx`, `lxml`, `pypandoc`.
- New OOXML / `.pptx` schema change announced by Microsoft (rare but happens).
- CVE published against `lxml` (XXE class).
- LibreOffice CLI flag changes for the `--convert-to` family.
- `python-pptx` moving back to active development (would unlock chart / animation coverage).
- Annual review on: 2027-05-22.

## See Also

| Need | Skill |
|---|---|
| Excel manipulation | `ms-office-excel-python` |
| Word document generation | `ms-office-word-python` |
| Generating a structured presentation (narrative + datavis + diagrams) | `presentation-builder` family (`presentation-narrative`, `presentation-datavis`, `presentation-diagrams`, `presentation-styling`, `presentation-renderer`) |
| Sending a deck through Outlook / posting to Teams via Graph | `ms-office-graph-python` |
| Hardening / validator / checklist | `ms-office-security-python` |
