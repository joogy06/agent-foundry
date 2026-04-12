# Wiki Query — Index-First Search & Synthesis Protocol

Reference file for `wiki` skill family. Covers: 3-tier search strategy, synthesis, citation, Mermaid triggers, file-back rules, and coding-agent query patterns.

Invoked by: the wiki agent, forge (Tier 1 direct grep), bob (Tier 2 query for existing decisions), pa (intent router).

---

## Prerequisites

1. **Wiki resolved** — `<wiki-root>` known
2. **No lock needed** — queries are reads, always allowed
3. **Query understood** — what the user is asking for (a fact, a synthesis, a decision, a comparison)

---

## The Three-Tier Search Strategy

### Tier 1: Index Scan (ALWAYS FIRST)

**Goal**: Understand what the wiki contains before searching.

```
1. Read <wiki-root>/index.md ONCE (single file, fast)
2. Scan category headers and page titles
3. Match query terms against:
   - H1 titles
   - Brief hints in bullet lines
   - Section headers (categories)
4. Build a shortlist of 3-10 candidate pages
5. If index alone answers the question (e.g. "list my wikis"), stop here
```

**Budget**: 1 Read call. Index.md is always the first thing read. Never skip.

### Tier 2: Grep Scan

**Goal**: Find pages that contain query terms, ranked by match density.

```
1. For each significant query term (skip stopwords):
     grep -r "<term>" <wiki-root>/wiki/ --include="*.md"
2. Aggregate matches by page path
3. Rank:
     - Frontmatter title/slug match: weight 3
     - H1/H2 header match: weight 2
     - Body match: weight 1
4. Build ranked list of candidate pages (top 5-10)
5. Deduplicate against Tier 1 shortlist
```

**Performance**: Use Grep tool with `files_with_matches` first, then `content` with line numbers only for top candidates.

**Upgrade path**: When qmd MCP is available, replace Tier 2 with semantic search:
- qmd index built offline during lint or ingest
- Query embeddings matched against page embeddings
- Hybrid: semantic top-5 + keyword top-5, deduped

### Tier 3: Targeted Page Read

**Goal**: Read only the pages that will answer the question.

```
1. Read top 3-5 ranked pages from Tier 1 + Tier 2 combined
2. For each page, note:
     - Frontmatter (type, confidence, sources, related)
     - H2/H3 structure
     - Relevant body paragraphs (match against query terms)
3. Follow wikilinks [[slug]] that appear in relevant paragraphs
     - Only follow if the link seems directly relevant
     - Max 2 hops deep — prevent infinite link chasing
4. Collect raw source citations from the relevant paragraphs
```

**Budget**: Target 3-5 Reads in Tier 3. If you need 10+ Reads, the query is too broad — ask the user to narrow it or create a synthesis page.

---

## Synthesis Protocol

After gathering relevant sections:

### Step 1: Gather (with provenance)
For each relevant passage:
- Record: which page, which section, which raw source (from citations)
- Note the confidence level of the source page
- Note the updated date of the source page

### Step 2: Reconcile
If passages conflict:
- **Prefer high-confidence** over low-confidence
- **Prefer recent** (by `updated` date) over stale
- **Prefer reinforced** (multiple pages citing same source) over one-off
- If conflicts remain after ranking: **surface them explicitly** in the answer, don't paper over

### Step 3: Compose
Structure the answer:
1. **Direct answer** (1-3 sentences) — the TL;DR
2. **Supporting evidence** — bullet points with inline citations
3. **Gaps & caveats** — what the wiki doesn't cover
4. **Confidence** — high / medium / low (inherit the weakest source)

### Step 4: Cite (Two-Level Provenance)

Every answer has two layers of citation:

```
[1] [Self-Attention](wiki/concepts/self-attention.md)
    — derived from [Vaswani et al. 2017](raw/2026-04-07-vaswani-2017.pdf), pages 3-4
[2] [Multi-Head Attention](wiki/concepts/multi-head-attention.md)
    — derived from [Vaswani et al. 2017](raw/2026-04-07-vaswani-2017.pdf), pages 4-5
```

**Two-level format** (query -> wiki page -> raw source):
- Query answer references wiki pages
- Wiki pages reference raw sources
- User can trace any claim all the way back to the source PDF/markdown/image

### Step 5: State Confidence

End the answer with a confidence line:

```
Confidence: high (peer-reviewed paper, high-confidence wiki page)
Confidence: medium (synthesized across 3 sources, one uncertain)
Confidence: low (single low-confidence source, topic sparsely covered in wiki)
```

---

## Mermaid Generation Triggers

Generate a Mermaid diagram alongside the prose answer when the query is about:

| Query Topic | Mermaid Type |
|-------------|-------------|
| Architecture / system design | `graph TD` |
| Request flow / sequence of operations | `sequenceDiagram` |
| State transitions / workflow states | `stateDiagram-v2` |
| Class / data model / schema | `classDiagram` |
| Database schema / entities | `erDiagram` |
| Hierarchy / taxonomy | `graph TD` or `mindmap` |
| Timeline / development over time | `timeline` |
| Dependency graph | `graph LR` or `graph TD` |

**Rules:**
- Generate the diagram ONLY if at least 3 entities are involved (fewer = prose is fine)
- Cite the source pages used to construct the diagram
- Keep diagrams ≤20 nodes (>20 suggests a synthesis page is warranted)

**Example trigger**: User asks "how does auth work in our system?" — detect "how does X work" + architecture domain -> generate sequenceDiagram showing login flow.

---

## File-Back Rules — When To Create A New Wiki Page From Query Output

Create a new wiki page from a query answer when **any** of these are true:

1. **Synthesis spans 3+ pages** — the synthesis itself is valuable, worth preserving
2. **User explicitly asks to save** — "save this as a page", "file this"
3. **Query reveals a concept gap** — user asked about X, wiki lacks a dedicated X page, but information exists scattered
4. **Mermaid diagram was generated** — worth persisting as a `overview` or `architecture` page
5. **The answer took 5+ page reads to compose** — context cost is high, future queries benefit from a cached synthesis

**Don't file-back when:**
- The answer came from a single page (that page is already the answer)
- The query was a one-off fact lookup
- The user is exploring, not consolidating

**File-back protocol:**
- Create a `synthesis` type page with:
  - All contributing pages in `sources` (meta-level)
  - Contributing raw files in the actual `sources` list
  - `contributing_pages: [slug1, slug2, slug3]` frontmatter
  - `confidence: medium` (synthesis default)
- Update `index.md` Synthesis or Overview section
- Log the file-back to `log.md`
- Acquire `.wiki.lock` for the write

---

## Coding-Agent Query Patterns

When forge/bob/pa queries the wiki, common patterns:

### Pattern 1: "What was decided about X?"
**Intent**: Find an ADR
**Search**: Tier 1 index for `decisions/` section, Tier 2 grep for topic
**Answer**: Return the decision page with chosen option, consequences, and links to affected components
**File-back**: No — ADR already exists

### Pattern 2: "What's the API contract for service Y?"
**Intent**: Find an api-contract page
**Search**: Tier 1 index for `api-contracts/` section
**Answer**: Return endpoints, schemas, authentication, versioning notes
**File-back**: No — api-contract page already exists

### Pattern 3: "What's the schema for table Z?"
**Intent**: Find component or architecture page with ER diagram
**Search**: Tier 2 grep for table name, Tier 3 follow to component page
**Answer**: Return the Mermaid erDiagram + text description + related components
**File-back**: Maybe — if scattered, consolidate into one `schema` page

### Pattern 4: "Why did we choose A over B?"
**Intent**: Find a comparison or decision page
**Search**: Tier 1 for `comparisons/` and `decisions/` sections
**Answer**: Return the comparison table, decision rationale, and links to affected components
**File-back**: No

### Pattern 5: "What do we know about <topic>?"
**Intent**: Broad synthesis
**Search**: All three tiers, follow wikilinks
**Answer**: Synthesized summary with two-level citations
**File-back**: YES (synthesis triggers rule #1)

---

## Query Response Format

```
## Answer

<1-3 sentence direct answer>

## Evidence

- <Claim 1> [1]
- <Claim 2> [2]
- <Claim 3 with optional code/mermaid/table>

## Gaps

- <What the wiki doesn't cover>
- <Related topics not yet pages>

## Citations

[1] [<Page Title>](wiki/<category>/<slug>.md)
    — derived from [<Source Title>](raw/<date>-<slug>.<ext>), pages <N-M>
[2] [<Page Title>](wiki/<category>/<slug>.md)
    — derived from [<Source Title>](raw/<date>-<slug>.<ext>)

## Confidence

<high | medium | low> — <one-line justification>

## Related (from wiki)

- [[slug1]]
- [[slug2]]
```

---

## Context Discipline Checklist

Before responding to any query:

- [ ] Did I read `index.md` first? (YES is mandatory)
- [ ] Did I grep before reading bodies? (YES for any query not answered by index alone)
- [ ] Did I limit Tier 3 to ≤5 page reads?
- [ ] Am I following wikilinks with budget? (max 2 hops, stop on diminishing returns)
- [ ] Are all claims in my answer cited to a wiki page?
- [ ] Are all wiki-page claims cited to a raw source in those pages' frontmatter?
- [ ] Did I state confidence?
- [ ] Should this synthesis be filed back as a new page?

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Reading the full `wiki/` directory to answer a query | Context explodes at 50+ pages, unbounded cost | Tier 1 index first, Tier 2 grep, Tier 3 targeted reads |
| Skipping `index.md` | You lose the map, end up guessing which files to read | `index.md` is ALWAYS the first Read |
| Walking wikilinks indefinitely | Infinite chain chasing, context explosion | Max 2 hops from primary pages |
| Answering without citations | Query answers look authoritative but are unverifiable | Every claim gets a two-level citation (page -> source) |
| Filing back every query | `wiki/` fills with duplicates, lint flags orphans | Apply file-back rules: synthesis 3+, explicit save, Mermaid, concept gap, expensive queries only |
| Generating Mermaid for 2-entity answers | Diagram adds no value over prose | ≥3 entities or skip the diagram |
| Suppressing conflicts to give a clean answer | User loses awareness of contested claims | Surface conflicts explicitly in "Gaps" section |
