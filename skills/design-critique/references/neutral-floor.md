# The neutral floor

The rows a probe can fail. They are measured in the rendered page by the capture, they are the same for every
variant, and they hold nothing about style: a row is here only if a number decides it. The critic reads the
rows and never edits them.

## The rows

Each row is measured at each viewport width (390, 768 and 1280 CSS px) and reported with the viewport and a
short selector for the element it was measured on. `Pass when` compares the measured value with the threshold.

<!-- floor-table:start -->
| Row id | Measures | Element scope | Pass when | Threshold | Unit | Blocking at | Advisory at |
|---|---|---|---|---|---|---|---|
| `contrast-text` | lowest contrast ratio of text below the large-text size against its resolved background | text elements below the large-text size | `>=` | 4.5 | ratio | 390, 768, 1280 | none |
| `contrast-large-text` | lowest contrast ratio of large text against its resolved background | text elements at or above the large-text size | `>=` | 3 | ratio | 390, 768, 1280 | none |
| `contrast-unmeasured` | text elements whose background could not be resolved to a colour | text elements over a raster image | `<=` | 0 | count | none | 390, 768, 1280 |
| `body-size` | smallest computed font size of running body text | paragraphs of the main content | `>=` | 16 | CSS px | 390, 768, 1280 | none |
| `overflow-x` | document scroll width minus viewport width | the document | `<=` | 0 | CSS px | 390, 768, 1280 | none |
| `motion-reduced` | animations and transitions still running once the page has settled, with reduced motion requested | the document | `<=` | 0 | count | 390, 768, 1280 | none |
| `page-weight` | bytes of the files the page loaded | the document | `<=` | 3000000 | bytes | 390, 768, 1280 | none |
| `line-length` | mean characters per line of running body text | paragraphs of three lines or more | `<=` | 100 | characters | 768, 1280 | 390 |
<!-- floor-table:end -->

## How to read a row

- **Blocking.** A variant that fails a blocking row at any viewport is not eligible to win as it stands. It can
  be selected for repair; the repaired page is captured again and judged again before the award is confirmed.
- **Advisory.** The row is reported and does not decide eligibility. The critic may cite it in the rubric
  comparison when the brief makes it matter.
- **`not_run`.** The row was not measured. It is a gap, never a pass, and a blocking row that did not run
  leaves the variant not eligible. Every row is `not_run` when the capture could not run. Two rows are also
  `not_run` on a capture that did run: `contrast-text` when the probe reached no text element on the page, and
  `body-size` when it measured no running body text. That is a page whose words sit where the probe cannot
  read them (a closed shadow root, drawn text in an image, an `<svg>` or a `<canvas>`), and both rows are
  `not_run` as well when a frame of the page went unmeasured. The probe does read open shadow roots and the
  frames of the page.
- **Nothing to measure** is a pass only where the thing is truly absent: a page with no large text passes
  `contrast-large-text`, and a page with no paragraph of three lines passes `line-length`.
- **Latest capture.** A variant that was captured again is judged on that capture: one that passed first and
  fails after a repair is not eligible as it stands.
- **Large text** is text of at least 24 CSS px, or at least 18.66 CSS px and bold (18 pt, or 14 pt bold).
- **Resolved background** is the nearest background colour behind the text. Over a gradient, the stop that
  gives the lowest ratio is used. Over a raster image the ratio is not measured: the element is counted in
  `contrast-unmeasured` and the critic judges it from the tiles or lists it in `could_not_judge`. A closed
  shadow root that holds text beside text the probe did reach is counted in the same row: its text was seen
  to be there and was not measured.
- **Running body text** is the paragraphs a visitor reads in the main content. Captions, labels, table cells
  and navigation are outside `body-size` and `line-length`. A page that has text and no paragraph at all
  (headings, links, short list items) has its `body-size` taken from its other text, so it fails that row
  only on text below the threshold.
- **Settled** means after the page has been scrolled through once and the capture has waited for it. A finite
  animation that has ended by then does not count; one that is still running does.
- **Line length is advisory at 390** because a narrow screen keeps lines short by itself; the number says
  little there.

## Where the thresholds come from

| Row | Source | Kind |
|---|---|---|
| `contrast-text`, `contrast-large-text` | WCAG 2.2, Success Criterion 1.4.3 Contrast (Minimum), Level AA: 4.5:1, and 3:1 for large-scale text (at least 18 point, or 14 point bold). <https://www.w3.org/TR/WCAG22/#contrast-minimum> | standard |
| `overflow-x` | WCAG 2.2, Success Criterion 1.4.10 Reflow, Level AA: no scrolling in two dimensions for vertically scrolling content. The criterion is set at 320 CSS px; this row applies the same test at the three captured widths. <https://www.w3.org/TR/WCAG22/#reflow> | standard, applied at our widths |
| `motion-reduced` | The `prefers-reduced-motion` media feature (Media Queries Level 5, <https://www.w3.org/TR/mediaqueries-5/#prefers-reduced-motion>) and WCAG 2.2, Success Criterion 2.3.3 Animation from Interactions (Level AAA). The threshold of zero running animations is ours. | ours, on a standard signal |
| `line-length` | WCAG 2.2, Success Criterion 1.4.8 Visual Presentation (Level AAA) asks for no more than 80 characters. Ours is looser on purpose, because the measurement is a mean and approximate. <https://www.w3.org/TR/WCAG22/#visual-presentation> | ours, looser than the standard |
| `body-size`, `page-weight`, `contrast-unmeasured` | Ours. Not a WCAG criterion. | ours |

**Freshness anchor.** Checked 2026-10-12 against WCAG 2.2, W3C Recommendation of 12 December 2024
(<https://www.w3.org/TR/2024/REC-WCAG22-20241212/>). Re-check the contrast ratios, the large-text sizes and the
criterion numbers when WCAG 3 becomes a Recommendation or WCAG 2.2 is superseded. The rows marked "ours" are
budgets of this skill: revisit them when the capture or the kind of page it is used on changes.

## What is not in the floor

Nothing about typefaces, colour choices, layout patterns, ornament or the amount of motion a page uses with
motion allowed. Those belong to a variant's direction contract and are judged as tells, against that contract
only. A pattern one school of design refuses is not a floor row, because the floor binds every variant equally.
