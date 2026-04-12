---
name: web-research
description: Use when any agent needs deep web research on a topic — gathering, verifying, and structuring information from multiple sources. Covers search strategy, source evaluation, parallel research agents, confidence levels, gap flagging, and structured output. Invoke this instead of ad-hoc searching.
---

# Web Research

## Overview

Structured deep research that produces verified, organised findings with confidence levels and source evaluation. Any agent can invoke this skill when they need information — it replaces ad-hoc searching with a systematic methodology. Output is saved to `research/[topic]/` for reuse.

## When to Use

- Agent needs factual data to make a decision
- Challenger needs to verify claims
- Forge needs domain context before design
- `research-for-skills` needs domain knowledge before writing a skill
- Any task where "I think" should be replaced with "the evidence shows"


## Gemini MCP Integration

When available, `mcp__gemini-cli__ask-gemini` provides an additional research source with Google Search grounding. Use it to:
- Cross-verify findings from WebSearch with a different search backend
- Get Google-grounded answers for freshness-sensitive topics (latest versions, recent changes)
- Run parallel verification: WebSearch + Gemini MCP + Codex (`/codex:rescue`) for triangulation

Gemini's 1M context window is also useful for synthesizing large research outputs that exceed Claude's working context.
## The Research Process

```
1. SCOPE    → Define what we need to know (sub-questions)
2. SEARCH   → Parallel agents search different angles
3. EVALUATE → Apply source evaluation to every finding
4. VERIFY   → Triangulate across 3+ independent sources
5. FLAG     → Mark what was NOT found (gaps)
6. STRUCTURE → Organise with confidence levels
7. SAVE     → Store in research/[topic]/
```

## Step 1: Scope — Decompose the Question

Break the research topic into **4-5 searchable sub-questions** using MECE (Mutually Exclusive, Collectively Exhaustive):

```
Topic: "Is Redis suitable for our session storage?"

Sub-questions:
1. What are Redis's session storage capabilities and limits?
2. What are the alternatives (Memcached, DB, JWT) and trade-offs?
3. What are Redis failure modes and data loss risks?
4. What's the operational cost (hosting, monitoring, maintenance)?
5. What do practitioners report from production use?
```

**Rule:** If you can't break it into sub-questions, the topic is too vague. Refine it first.

## Research Levels

Choose the level BEFORE starting. The calling agent or user specifies the level. When not specified, use the decision guide below.

### SHORT — Quick Verification (seconds to 1 minute)

**Use when:** Verifying a single claim, checking if a library exists, confirming a version number, getting one specific fact.

| Aspect | Detail |
|--------|--------|
| Agents | 0 (inline WebSearch by the requesting agent) |
| Searches | 1-3 targeted queries |
| Source eval | Quick check — is source official/reputable? |
| Triangulation | Not required for factual lookups (docs, versions) |
| Output | Inline answer with source link — no research folder |
| Gap flagging | "Couldn't verify" if not found in 3 searches |

**Examples:** "Does ibm_db support Python 3.14?", "What's the current Flask version?", "Is FAQ schema still generating rich results?"

### MEDIUM — Focused Research (2-5 minutes)

**Use when:** Understanding a specific topic, comparing 2-3 options, getting current best practices for a focused area, verifying multiple related claims.

| Aspect | Detail |
|--------|--------|
| Agents | 1-2 parallel research agents |
| Searches | 5-15 per agent |
| Source eval | SIFT method on key findings |
| Triangulation | Required for claims that inform decisions |
| Output | Brief findings doc — save to research/ if reusable |
| Gap flagging | Required |
| Confidence levels | Required on key findings |

**Examples:** "Best deployment pattern for Flask + Gunicorn in 2026", "Redis vs Memcached for session storage", "Current state of Google FAQ schema support"

### LONG — Deep Research (5-15 minutes)

**Use when:** Creating a new skill, understanding an entire domain, multi-faceted topic with many subtopics, need comprehensive coverage with challenger review.

| Aspect | Detail |
|--------|--------|
| Agents | 3-5 parallel research agents + challenger |
| Searches | 10-30 per agent |
| Source eval | Full SIFT + trust hierarchy on all findings |
| Triangulation | Required on all key claims (3+ sources) |
| Output | Full research folder: INDEX.md + per-subtopic files + sources |
| Gap flagging | Required — explicit "NOT FOUND" table |
| Confidence levels | Required on every finding |
| Challenger | Reviews all findings for contradictions, bias, gaps |

**Examples:** "Full SEO landscape 2026", "Python parallelism patterns", "WooCommerce security best practices", "Docker admin patterns"

### Decision Guide — How to Choose Level

```
Is this a single fact or version check?
  → SHORT

Is this a focused question with 1-2 sub-questions?
  → MEDIUM

Does it have 3+ sub-questions, or will it become a skill?
  → LONG

Still unsure? Ask:
  "How many sub-questions does this break into?"
    1-2  → MEDIUM
    3+   → LONG
    0    → SHORT (it's just a fact check)
```

**Callers can override:** An agent requesting research can specify the level. If not specified, use the decision guide. When in doubt, start MEDIUM — escalate to LONG only if findings are insufficient.

## Step 2: Search — Execute at Chosen Level

### SHORT: Inline Search

No agents spawned. The requesting agent runs 1-3 WebSearch queries directly and returns the answer with source.

### MEDIUM: Focused Agents

Spawn 1-2 research agents, each covering a sub-question:

```
"Research [SUB-QUESTION]. Find:
- Current best practices (2024-2026)
- Data points with specific numbers and sources
- Official documentation references
- Contradicting viewpoints if they exist

For every claim, note the source URL and date.
Flag anything you searched for but couldn't find.
DO NOT make up data. If uncertain, say so."
```

### LONG: Full Research Team

Spawn 3-5 parallel agents + 1 challenger:

```
Research agents (parallel):
"Research [SUB-QUESTION] deeply. Find:
- Current best practices with specific data/tools/versions
- What's changed since 2023-era advice
- Anti-patterns — common mistakes and outdated advice
- Benchmarks/data points to include
- Practitioner experience (Reddit, HN, Stack Overflow)
- Actionable rules an AI agent should follow

Use WebSearch extensively. Be specific — no generic advice.
For every claim, note source URL and date.
Flag anything searched for but not found."

Challenger agent (after research completes):
"Review all findings for contradictions, vendor bias, outdated
claims, and gaps. Verify key statistics. Flag questionable data."
```

## Step 3: Evaluate — Source Assessment

Apply the **SIFT method** (Stop, Investigate, Find better, Trace claims) to every source:

### Source Trust Hierarchy

| Tier | Source Type | Trust | Action |
|------|-----------|-------|--------|
| 1 | Official documentation (Google, MDN, RFCs, specs) | HIGH | Accept, check date |
| 2 | Peer-reviewed / transparent methodology studies | HIGH | Check methods, sample size |
| 3 | Independent research with data (Ahrefs, Semrush with methodology shown) | MEDIUM-HIGH | Note potential vendor bias |
| 4 | Reputable industry publications (Search Engine Journal, Smashing Magazine) | MEDIUM | Cross-reference claims |
| 5 | Blog posts, tutorials, forum answers | MEDIUM-LOW | Verify claims independently |
| 6 | Vendor marketing, press releases, case studies | LOW | Assume biased — seek independent confirmation |
| 7 | Unsourced claims, "everyone knows", AI-generated stats | REJECT | Demand evidence or discard |

### Red Flags in Sources

- No date published (reject for any fast-moving topic)
- Statistics without named study/methodology
- Same stat cited across 10 blogs but no original source (circular citation / citogenesis)
- "Studies show" without naming the study
- Vendor's own case study proving their product works
- Numbers that are too precise for the claim ("exactly 94% accuracy")

## Step 4: Verify — Triangulation

Every key finding must be **triangulated** across 3+ independent sources.

| Triangulation | When |
|---------------|------|
| **Same fact, 3+ independent sources** | Standard verification — fact is reliable |
| **2 sources agree, 1 contradicts** | Note the contradiction, investigate why |
| **Only 1 source** | Mark as "single source — unverified" |
| **Sources disagree fundamentally** | Mark as "contradictory" — present all sides |
| **No sources found** | Mark as "NOT FOUND" — this is valuable information |

**Deliberately search for contradicting evidence:** After finding support for a claim, search for "[claim] wrong", "[claim] criticism", "[claim] debunked".

## Step 5: Flag — Information Gaps

**Explicitly state what you searched for but could NOT find.** This is as valuable as what you did find.

```
### Information Gaps

| Searched For | Result |
|-------------|--------|
| Redis session storage benchmark at 100K concurrent users | NOT FOUND — no public benchmarks at this scale |
| Comparison of Redis vs Valkey for sessions (post-fork) | INSUFFICIENT — only vendor blog posts, no independent comparison |
| GDPR implications of Redis session data in EU | PARTIAL — found general guidance but no Redis-specific legal opinion |
```

## Step 6: Structure — Confidence Levels

Every finding gets a confidence level:

| Level | Meaning | Criteria |
|-------|---------|----------|
| **VERIFIED** | Multiple independent sources agree, official docs confirm | 3+ sources, at least 1 tier-1 |
| **LIKELY** | Good evidence but not fully triangulated | 2 sources or 1 tier-1 source |
| **UNCERTAIN** | Limited evidence, single source, or dated | 1 source, or all sources >12 months old |
| **CONTRADICTORY** | Sources disagree | Present all sides with sources |
| **NOT FOUND** | Searched but no evidence found | Document what was searched |

## Step 7: Save — Research Output

Save all findings to `research/[topic]/`:

```
research/
  [topic]/
    INDEX.md              # Summary of findings + confidence levels
    R1-[subtopic].md      # Detailed findings per sub-question
    R2-[subtopic].md
    sources.md            # Annotated source list
```

### INDEX.md Template

```markdown
# Research: [Topic]

**Date:** [YYYY-MM-DD]
**Requested by:** [Agent/User]
**Sub-questions:** [List]

## Key Findings

| # | Finding | Confidence | Source |
|---|---------|-----------|--------|
| 1 | [Finding] | VERIFIED | [Source + date] |
| 2 | [Finding] | LIKELY | [Source + date] |
| 3 | [Finding] | CONTRADICTORY | [Source A] vs [Source B] |

## Information Gaps

| Searched For | Result |
|-------------|--------|
| [Query] | NOT FOUND / INSUFFICIENT |

## Contradictions Found

| Claim | Source A Says | Source B Says |
|-------|-------------|---------------|
| [Topic] | [Position + source] | [Counter-position + source] |

## Detailed Findings

See individual research files (R1, R2, etc.) for full evidence.
```

## Integration with Other Skills

| Skill | How It Uses web-research |
|-------|------------------------|
| **forge** | Domain context before design phase |
| **challenger** | Verify claims in proposals (self-research capability) |
| **research-for-skills** | Gather domain knowledge before writing a skill |
| **seo-\*** skills | Verify SEO data, check current algorithm status |
| **development-lifecycle** | Research phase before implementation |

## Search Technique Quick Reference

### Google Advanced Operators

| Operator | Purpose | Example |
|----------|---------|---------|
| `site:` | Search within one domain | `site:developers.google.com structured data` |
| `"exact phrase"` | Match exact words | `"Knowledge Graph" entities 2025` |
| `before:` / `after:` | Date restrict | `Redis session storage after:2025-01-01` |
| `filetype:` | Specific file types | `filetype:pdf OWASP top 10 2025` |
| `intitle:` | Words in page title | `intitle:benchmark Redis vs Memcached` |
| `-term` | Exclude results | `Python parallelism -tutorial -beginner` |
| `OR` | Either term | `"Redis sessions" OR "Valkey sessions"` |

### Platform-Specific Searches

| Need | Search Where |
|------|-------------|
| Official documentation | `site:developers.google.com`, `site:docs.python.org` |
| Academic/research | Google Scholar, `site:arxiv.org` |
| Practitioner experience | `site:reddit.com`, `site:news.ycombinator.com` |
| Code examples | `site:github.com`, `site:stackoverflow.com` |
| Security advisories | `site:nvd.nist.gov`, `site:cve.mitre.org` |
| Current news/changes | Google News, `after:` date operator |

## Anti-Patterns

| Don't | Why | Do Instead |
|-------|-----|-----------|
| Accept first search result as truth | First-result bias | Check 3+ sources minimum |
| Only search for confirming evidence | Confirmation bias | Deliberately search for counter-evidence |
| Use undated sources for tech topics | Information decays fast | Require dates on all tech/SEO sources |
| Cite vendor case studies as independent proof | Vendor bias | Flag as "vendor source" and seek independent confirmation |
| Say "no information exists" after 1 search | Insufficient effort | Try 3+ query variations before declaring NOT FOUND |
| Present all findings at same confidence | Misleading | Use confidence levels on every finding |
| Skip gap flagging | Hides ignorance | Explicitly state what wasn't found |
| Re-research what's already in `research/` folder | Waste | Check existing research first |
