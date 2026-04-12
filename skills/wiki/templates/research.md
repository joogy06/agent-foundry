# Research Domain Template

Master template for research wikis: papers, concepts, methods, experiments, comparisons. Used by `wiki/schema.md` bootstrap to generate WIKI.md + page templates for new research wikis.

**Template version**: research-v1
**Best for**: literature reviews, PhD research, trading strategy research, scientific reading lists, ML paper collections.

---

## Directory Structure

```
<wiki-root>/
  WIKI.md
  index.md
  log.md
  raw/
    images/
    <YYYY-MM-DD>-<author-year-slug>.pdf     # papers
    <YYYY-MM-DD>-<slug>.md                  # notes, blog posts, markdown
    <YYYY-MM-DD>-<slug>.png                 # figures, diagrams
  wiki/
    papers/              # Paper summaries (1 per source paper)
    concepts/            # Reusable ideas (attention, gradient descent, etc.)
    methods/             # Techniques and procedures
    experiments/         # Experimental results and reproductions
    researchers/         # People, labs, institutions
    findings/            # Empirical claims with evidence
    syntheses/           # Multi-source synthesis pages
    comparisons/         # A vs B comparison pages
    questions/           # Open questions, research gaps
    overviews/           # Domain overview pages
  _templates/
    paper-summary.md
    concept.md
    finding.md
    method.md
    experiment.md
    researcher.md
    synthesis.md
    comparison.md
    overview.md
    question.md
  _maintenance/
    link-index.md
    tag-registry.md
    lint-history.jsonl
    source-manifest.yaml
```

---

## Page Types

| Type | Purpose | Required Frontmatter | Template |
|------|---------|---------------------|----------|
| `paper-summary` | Summarize one source paper | sources (1 pdf), authors, venue, year | `paper-summary.md` |
| `concept` | Reusable idea across papers | related, sources (>=1) | `concept.md` |
| `finding` | One empirical claim with evidence | sources (>=1), confidence, magnitude | `finding.md` |
| `method` | Technique / procedure | sources (>=1), inputs, outputs | `method.md` |
| `experiment` | Experimental result / reproduction | sources, dataset, metric, result | `experiment.md` |
| `researcher` | Person / lab / institution | affiliations, sources | `researcher.md` |
| `synthesis` | Multi-source synthesis | sources (>=3), contributing_pages | `synthesis.md` |
| `comparison` | A vs B | subjects (>=2), criteria | `comparison.md` |
| `overview` | Domain landscape | related (>=5) | `overview.md` |
| `question` | Open question / gap | status (open/investigated/answered) | `question.md` |

---

## Frontmatter Schema (Research-Specific Extensions)

Base frontmatter from `schema.md` Part 3, plus research extensions:

```yaml
---
# Base fields (always required)
type: paper-summary
title: "Attention Is All You Need"
slug: attention-is-all-you-need
created: 2026-04-07
updated: 2026-04-07
sources:
  - path: raw/2026-04-07-vaswani-2017.pdf
    pages: [1, 12]
tags: [ml/transformers, ml/attention]
status: active
confidence: high

# Research-specific extensions
authors: ["Vaswani et al."]
venue: "NeurIPS 2017"
year: 2017
doi: "10.48550/arXiv.1706.03762"
url: "https://arxiv.org/abs/1706.03762"
related: [bert, gpt, self-attention]
keywords: [attention, transformers, sequence-modeling]
citation_count: 100000   # Optional, updated manually
replicated: true          # Optional: has been reproduced
disputed: false           # Optional: claims contested by later work
---
```

---

## Cross-Referencing Conventions

**Wikilinks:**
- `[[concept-slug]]` on first mention of any concept
- `[[paper-slug]]` when citing a paper summary elsewhere
- `[[researcher-slug]]` on first author/lab mention

**Auto-link rules:**
- New `concept` page: backfill wikilinks in existing paper-summaries and findings
- New `paper-summary` page: grep for title/author patterns in concept pages
- New `finding` page: auto-link to the source paper-summary

**Related field conventions:**
- Papers: list concepts and methods used
- Concepts: list contributing papers and adjacent concepts
- Findings: list the paper that established it + any replications

---

## Naming Conventions

- **Papers**: `<first-author-year>-<short-title>`, e.g. `vaswani-2017-attention`
- **Concepts**: noun phrases in kebab-case, e.g. `self-attention`, `gradient-descent`
- **Methods**: verb-noun in kebab-case, e.g. `beam-search`, `layer-norm`
- **Researchers**: `<last-name>-<first-name>` or `<lab-name>`, e.g. `vaswani-ashish`, `google-brain`
- **Findings**: short claim slug, e.g. `attention-outperforms-rnn-on-translation`

---

## Output Formats

**Citations**: `[Source: raw/2026-04-07-vaswani-2017.pdf, p.3]`
**Cross-paper claims**: `[Source A: ..., Source B: ...]` when synthesizing
**Equations**: Inline LaTeX `$x = y$` or block `$$\frac{a}{b}$$`

**Mermaid defaults for this domain**:
- `graph TD` — citation networks, concept dependency graphs
- `timeline` — chronological development of an idea/technique
- `mindmap` — domain overview pages

---

## Maintenance Workflows

- **Lint frequency**: after every batch ingest, weekly during active research
- **Staleness thresholds**: papers age gracefully (no auto-staleness); concept pages stale after 180 days if the field is active
- **Archive**: papers never archived (historical record); concept pages archive when `deprecated: true`

---

## Obsidian Compatibility Notes

- Use Dataview plugin for: "all papers from 2024 tagged transformers" queries
- Enable Graph View with tag coloring (ml/transformers = blue, ml/rl = orange)
- Frontmatter view shows `authors`, `year`, `venue` for paper-summaries

---

## Example Pages (Abbreviated)

### Example: paper-summary

```markdown
---
type: paper-summary
title: "Attention Is All You Need"
slug: vaswani-2017-attention
authors: ["Vaswani et al."]
venue: "NeurIPS 2017"
year: 2017
sources:
  - path: raw/2026-04-07-vaswani-2017.pdf
    pages: [1, 12]
tags: [ml/transformers, ml/attention]
status: active
confidence: high
related: [bert, gpt, self-attention]
---

# Attention Is All You Need

Introduces the Transformer architecture, replacing recurrence with self-attention for sequence-to-sequence tasks [Source: raw/2026-04-07-vaswani-2017.pdf, p.1].

## Key Findings

- Self-attention scales better than RNN on long sequences [Source: raw/2026-04-07-vaswani-2017.pdf, p.6]
- State-of-the-art on WMT 2014 English-German translation (28.4 BLEU) [Source: raw/2026-04-07-vaswani-2017.pdf, p.8]

## Method

See [[self-attention]] and [[multi-head-attention]].

## See Also

- [[bert]] — Bidirectional variant (2018)
- [[gpt]] — Autoregressive variant (2018)
```

### Example: concept

```markdown
---
type: concept
title: "Self-Attention"
slug: self-attention
created: 2026-04-07
updated: 2026-04-07
sources:
  - path: raw/2026-04-07-vaswani-2017.pdf
    pages: [3, 4]
tags: [ml/attention]
status: active
confidence: high
related: [multi-head-attention, vaswani-2017-attention]
---

# Self-Attention

A mechanism where each token in a sequence attends to every other token, computing weighted combinations of their representations [Source: raw/2026-04-07-vaswani-2017.pdf, p.3].

## Formulation

Given queries Q, keys K, and values V:
$$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V$$

[Source: raw/2026-04-07-vaswani-2017.pdf, p.4]

## See Also

- [[vaswani-2017-attention]] — Originating paper
- [[multi-head-attention]] — Extension using multiple parallel attention heads
```

---

## Anti-Patterns (Research Domain)

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Writing paper summaries without page citations | Can't verify claims back to source | Every claim gets `[Source: raw/<file>, p.<N>]` |
| Collapsing multiple papers into one summary | Loses individual provenance | One paper-summary per paper; use `synthesis` for multi-source |
| Treating concepts as wiki-of-one-source | Concepts span multiple papers | Concept pages list `sources` as a list, not a single entry |
| Skipping replication status | "Classic" findings may be disputed | Use `replicated` and `disputed` fields; add findings pages for replications |
