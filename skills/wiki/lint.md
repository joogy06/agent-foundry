# Wiki Lint — Health Check Protocol

Reference file for `wiki` skill family. Covers: the 10-check protocol, output format, health score, auto-fix rules, and mandatory triggers.

Invoked by: the wiki agent, alf (Tier 2 for knowledge freshness lens), any agent before export or cross-agent handoff.

---

## Prerequisites

1. **Wiki resolved** — `<wiki-root>` known
2. **Read-only mode**: lint reads the wiki and reports. `--fix` mode acquires `.wiki.lock` for writes.
3. **Schema loaded**: WIKI.md is the authoritative source for enum values, required fields, and page types.

---

## The 10-Check Protocol

Lint runs all 10 checks in order. Each produces findings at one of three severities:

- **Failure** (must fix before lint passes)
- **Warning** (should fix, doesn't block)
- **Info** (nice to have, informational only)

### Check 1: Structural Integrity

**Goal**: Every page in `wiki/` has valid frontmatter matching WIKI.md schema.

**Procedure:**
1. For each file in `wiki/**/*.md`:
   - Parse frontmatter (YAML between `---` fences)
   - Check required fields present: `type`, `title`, `slug`, `created`, `updated`, `sources`, `status`, `confidence`
   - **Enum validation**:
     - `status` must be in: `draft`, `active`, `review`, `archived`
     - `confidence` must be in: `high`, `medium`, `low`, `uncertain`
     - `type` must be in the WIKI.md Page Types table
   - Slug must match filename (without `.md`)
   - Dates in ISO 8601 format (`YYYY-MM-DD`)
   - `sources` is a list (may be empty only for `overview` type)

**Failures**:
- Missing frontmatter fence
- Invalid YAML
- Missing required field
- Invalid enum value
- Slug/filename mismatch

**Warnings**:
- Future `updated` date
- `created` > `updated`

**Info**:
- `created` == `updated` (never touched since creation)

### Check 2: Index Consistency

**Goal**: `index.md` lists every page; no index entries point to missing pages.

**Procedure:**
1. Read `index.md`, extract all wikilinks (`[[slug]]` patterns)
2. Collect all actual page slugs from `wiki/**/*.md` frontmatter
3. Diff:
   - Pages not in index → **Failure** (missing from index)
   - Index entries with no page → **Failure** (broken index entry)
4. Verify each category section in index.md matches actual category directories

**Auto-fix (--fix)**: Add missing index entries (default category based on page type). Cannot auto-fix broken entries (human judgment needed).

### Check 3: Source Traceability

**Goal**: Every claim has a citation; every citation resolves to a real file in `raw/`.

**Procedure:**
1. For each page:
   - Extract every `sources` entry from frontmatter — verify each `path` exists
   - Extract every inline `[Source: raw/<file>, ...]` citation — verify the file exists
2. Build `raw/` file inventory
3. Cross-check:
   - Citation to non-existent raw file → **Failure**
   - Raw file referenced in `sources` but not in any inline citation → **Warning** (possible unreferenced source)
4. Detect unsourced claim patterns:
   - Paragraphs with factual-looking statements (definitive verbs: "is", "has", "contains", "provides") but no citation
   - Statistical claims (numbers, percentages) without citation → **Warning**

**Auto-fix**: None (cannot fabricate citations).

### Check 4: Cross-Reference Health

**Goal**: All wikilinks resolve; backlinks are bidirectional; no circular clusters dominate the graph.

**Procedure:**
1. Extract all `[[slug]]` and `[[slug|Display]]` wikilinks from every page
2. Build outgoing link map: page -> [linked slugs]
3. Build incoming link map (invert)
4. Checks:
   - Wikilinks pointing to missing slugs → **Failure** (broken link)
   - Page mentioned in body but no outgoing `[[link]]` (entity match via title/aliases) → **Warning** (missing link)
   - Bidirectional backlinks missing in `_maintenance/link-index.md` → **Warning**
   - Cluster detection: if 5+ pages only link to each other with no incoming from the broader wiki → **Info** (isolated cluster)
5. Validate `_maintenance/link-index.md` against actual link graph

**Auto-fix**: Regenerate `_maintenance/link-index.md`. Add missing bidirectional entries. Cannot auto-fix broken links (human judgment).

### Check 5: Contradiction Detection

**Goal**: Surface cross-page contradictions so humans can reconcile.

**Procedure:**
1. Entity-claim extraction:
   - For each page, extract claims in form `<entity> <property> <value>` (grep for comparative/definitive patterns)
   - Build a claim table keyed by `(entity, property)`
2. Compare: if two pages make different `value` claims for same `(entity, property)`:
   - If same source → **Failure** (internal inconsistency)
   - Different sources, no `contradicts` flag → **Warning** (undeclared contradiction)
   - Different sources, `contradicts` flag present → **Info** (known conflict, properly marked)
3. Numerical claims with >5% variance → **Warning**

**Auto-fix**: None. Contradictions require human judgment.

### Check 6: Staleness

**Goal**: Flag pages that may be out of date based on domain volatility and source version.

**Procedure:**
1. Read WIKI.md for domain-specific staleness thresholds
2. Defaults by page type:
   - `runbook`: 90 days
   - `api-contract`: 180 days
   - `component`: 180 days
   - `decision` (ADR): never stale (historical)
   - `paper-summary`: never stale
   - `concept`: 365 days
3. For each page, compare `updated` (or `reviewed_on` if present) to threshold
4. Staleness over threshold → **Warning**
5. Source version drift: if `sources` lists a pinned version and that version has been superseded (tracked in `source-manifest.yaml`) → **Warning**

**Auto-fix**: None — staleness needs content review.

### Check 7: Orphan Detection

**Goal**: Find pages with zero inbound wikilinks.

**Procedure:**
1. From Check 4 incoming link map
2. Pages with 0 inbound links → **Warning** (orphan)
3. Exclude: top-level `overview` pages, `index.md` (orphans are expected there)
4. Exclude: pages with `standalone: true` frontmatter flag

**Auto-fix**: None. Propose backlinks in report.

### Check 8: Gap Detection

**Goal**: Find coverage gaps — concepts mentioned but not pages, red links, topics inferred from tags but absent.

**Procedure:**
1. Red links: `[[unknown-slug]]` that has no corresponding page → **Failure** (broken link)
2. Mention analysis: entities mentioned 3+ times across the wiki but no dedicated page → **Warning** (missing page)
3. Tag analysis: tags used on 5+ pages but no tag index or cluster → **Info** (potential category)
4. Page type distribution: expected types per domain template are absent → **Info**

**Auto-fix**: None — gaps require content creation, not mechanical fixes.

### Check 9: Content Quality

**Goal**: Pages are non-empty, well-formed, render cleanly.

**Procedure:**
1. Empty pages (<50 words after frontmatter) → **Warning** (stub)
2. Invalid Mermaid syntax:
   - Extract ```` ```mermaid ```` blocks
   - Attempt to validate (basic structure — detect unclosed blocks, invalid node syntax)
   - Invalid → **Failure**
3. Malformed markdown:
   - Unclosed code fences → **Failure**
   - Unclosed tables → **Failure**
   - Broken image references → **Warning**
4. Orphaned images in `raw/images/` not referenced by any page → **Info**

**Auto-fix**: None (structural fixes risk data loss).

### Check 10: Convention Compliance

**Goal**: Pages follow WIKI.md naming, frontmatter, and path conventions.

**Procedure:**
1. Slug naming: kebab-case only, no underscores, no leading digits → **Warning**
2. Page in wrong category directory for its type → **Warning**
3. Tag format: lowercase, hierarchical `parent/child`, max 3 levels → **Warning**
4. Image path: all image references under `raw/images/` (not inline base64, not external URLs without cache) → **Info**
5. Human edit detection: if a file in `wiki/` has `git blame` showing recent non-agent edit → **Info** (human touched this — flag for awareness, not failure)

**Auto-fix**: Safe renames (slug normalization) only if unambiguous.

### Check 11: Linked Source Freshness

**Goal**: All linked sources in `_maintenance/source-tracking.yaml` still exist and have not changed since ingestion. Stale or missing sources are reported.

**Skip if**: `source-tracking.yaml` does not exist (wiki uses owned-only mode).

**Procedure:**

1. Read `<wiki-root>/_maintenance/source-tracking.yaml`
2. For each `linked_sources[*]` entry:
   - **Resolve** `abs_path` (use it directly, or reconstruct from `source_root.path` + `rel_path`)
   - **Existence check** — does the file still exist?
   - **Hash check** — compute current SHA-256, compare to stored `sha256`
   - **mtime check** — compare current mtime to stored `mtime` (cheap pre-filter; if mtime unchanged, skip hash)
3. Update each entry's `status`:
   - `current` — exists, hash matches
   - `stale` — exists, hash differs (file content changed since ingestion)
   - `missing` — file does not exist (deleted or moved)
   - `conflict` — exists at expected path BUT a different file with same source ID exists elsewhere (move detection — best effort)
4. Update `last_verified_at` for all entries scanned
5. Aggregate:
   - **Failure** if `missing` count > 0 (broken provenance)
   - **Warning** if `stale` count > 0 (wiki page may be out of date)
   - **Info** if `conflict` (unusual, likely a move)
6. **Do NOT write anything.** Report findings only. If the user wants stored `freshness` updated, they run `wiki refresh` (which takes the lock and commits transactionally per schema.md §5.9). Check 11 is strictly read-only — see "Strict read-only policy" below and schema.md §5.11.

**Output rows include**:
- Source ID, status change (e.g., `current → stale`), wiki pages affected
- Recommendation: "re-ingest source X" for stale entries, "remove citation or restore file" for missing

**Auto-fix**: NONE. Check 11 never mutates files. See "Strict read-only policy" below. Mutating operations (updating status, re-ingesting stale, applying renames) belong to `wiki refresh` and `wiki reconcile-sources`.

**Performance note**: For large source trees (1000+ files), batch hashing in parallel via `xargs -P 8 sha256sum` or Python `concurrent.futures`. Use mtime as a pre-filter to skip unchanged files entirely.

**Session-start integration**: When the wiki agent is invoked at session start with a wiki context, it should run a **tiered** version of Check 11 and report stale-looking sources as a heads-up:

**Tiered discovery** (cheap → expensive):
1. **Tier 1 (mtime)**: for each tracked source, `stat` the file. If mtime matches stored → assume `current`, skip. O(N) with tiny constant.
2. **Tier 2 (size)**: for sources that failed tier 1, compare file size against stored `size_bytes`. If size matches AND mtime differs → usually a touch/git-checkout without content change. If size differs → definitely stale.
3. **Tier 3 (hash)**: for sources that pass tier 2 as "mtime changed but size same" OR user explicitly runs full scan → compute SHA-256 and compare. This is the expensive step but only for suspects.

**Why three tiers matter**: mtime-only misses content-preserving operations (e.g., `touch`, `git checkout` restoring the exact same content with a new mtime). Size+mtime catches most real changes cheaply. Hash is the ground truth, used sparingly.

**Rename/move detection** (expensive, opt-in):
When a source is marked `missing` (abs_path no longer exists), lint can optionally scan all source_roots for files with matching `content_id` (stored SHA-256 prefix):
- Triggered by `lint --with-rename-detection` (NOT default — it's O(total_sources_in_source_roots))
- If exactly one match found: reclassify as `renamed`, report with both old and new paths; the refresh operation will apply the rename
- If multiple matches: report as `ambiguous`, let user choose
- If no match: leave as `missing`, offer deprecation via source removal protocol

**Strict read-only policy**: Check 11 (and all of lint) is READ-ONLY. Lint does NOT write to source-tracking.yaml, page-events.jsonl, wiki-metrics.jsonl, or any wiki content. If the user wants status updates or rename fixes applied, they must run `wiki refresh` (or `wiki reconcile-sources` for rename-only). This separation means lint can run at any time without side effects — you can lint from a read-only filesystem and it will still work.

### Check 12: Versioning & Metrics Freshness

**Goal**: Ensure the wiki has functional versioning infrastructure (git or snapshot fallback) and that metrics/event logs are up to date.

**Procedure:**

1. **Git availability**:
   - `git -C <wiki-root> rev-parse --is-inside-work-tree` should return `true`
   - If not a git repo: **Failure** — recommend `git init` or use snapshot fallback
2. **wiki_version field present** in WIKI.md frontmatter — **Failure** if missing
3. **Tag consistency (EXACT match required)**: the latest `wiki-vNN` tag reachable from HEAD (via `git tag --merged HEAD --list 'wiki-v*'`) MUST match `wiki_version` in WIKI.md exactly. **No tolerance.** **Failure** on any drift. See schema.md §5.6.5 for the canonical `wiki_latest_version` function. Stray tags on orphan branches are ignored (merged-HEAD discovery prevents hijacking). Auto-fix rewrites WIKI.md from the tag via `wiki reconcile-version` (not lint --fix — see read-only policy).
3b. **Tag sequence gap check**: the reachable tag sequence must be contiguous (v20, v21, v22, v23, ...) — **Failure** if there's a gap (e.g., v20, v21, v23 missing v22). See schema.md §5.6.5 `wiki_check_tag_sequence`.
4. **wiki-metrics.jsonl exists** at `_maintenance/wiki-metrics.jsonl` — **Failure** if missing
5. **Last metric snapshot age**: most recent entry should be ≤ 30 days old or within last operation in log.md — **Warning** if older
6. **page-events.jsonl exists** at `_maintenance/page-events.jsonl` — **Failure** if missing (legacy wikis: auto-generate from git history on first lint)
7. **page-events ↔ pages consistency**:
   - Every wiki/**/*.md should have at least one `create` event in page-events.jsonl — **Warning** for orphans (pre-versioning pages)
   - Every `create` event should have a matching wiki page (or a later `archive`/`remove` event) — **Warning** for dangling events
8. **archived-sources.yaml exists** at `_maintenance/archived-sources.yaml` (may be empty) — **Failure** if missing
9. **Source state consistency**: every source in source-tracking.yaml should have state `active` (or `deprecated`); states `archived`/`removed` belong only in archived-sources.yaml — **Failure** on misplacement
10. **JSONL schema envelopes present**: first line of wiki-metrics.jsonl and page-events.jsonl MUST be a schema envelope like `{"_schema":"wiki-metrics","_version":1,...}` — **Failure** if missing, **Warning** if schema version unknown to this lint

**Auto-fix** (`--fix`):
- Initialize git repo if missing (`git init` + initial commit)
- Bootstrap missing JSONL/YAML files with empty schemas (including envelope line)
- Backfill page-events from `git log --diff-filter=A` for pages missing create events
- Append a synthetic metrics snapshot for current state if last snapshot is stale
- Rewrite WIKI.md wiki_version to match latest git tag on drift
- Prepend schema envelope to legacy JSONL files (retroactive migration)

**Strict read-only policy (applies to ALL checks, not just Check 11)**:
Lint is READ-ONLY by contract. The `--fix` mode may edit wiki PAGE content (frontmatter repairs, slug corrections) and bootstrap MISSING infrastructure files (empty JSONL envelopes, `git init`), but it MUST NOT mutate existing operational state in `_maintenance/` files (no updating source statuses, no appending events, no bumping versions). Mutations belong to refresh/ingest/remove operations, which take the lock and commit through the transactional protocol.

**Allowed in lint --fix**: frontmatter field fixes, slug renames, broken wikilink repairs, index.md regeneration, WIKI.md wiki_version realignment to git tag, missing-file bootstrap.

**Forbidden in lint --fix**: updating source-tracking.yaml statuses, appending to wiki-metrics.jsonl, appending to page-events.jsonl, creating/modifying archived-sources.yaml entries, committing/tagging git.

**Performance note**: Check 12 is fast (file existence + git rev-parse + tail of JSONL). Run on every lint.

---

## Output Format

Lint produces a structured report:

```markdown
# Lint Report — <wiki-name>

**Date**: 2026-04-07T14:32:00Z
**Pages scanned**: 47
**Raw sources**: 12
**Duration**: 3.2s

## Health Score: 8.5 / 10

## Summary

- Failures: 2 (must fix)
- Warnings: 7 (should fix)
- Info: 4 (nice to have)

## Failures

### 1. [Check 3: Source Traceability] Broken citation
- **Page**: wiki/papers/vaswani-2017-attention.md
- **Issue**: Cites `raw/2026-04-07-vaswani-2017.pdf` but file does not exist
- **Likely cause**: Typo or file not yet ingested
- **Fix**: Verify path or re-ingest source

### 2. [Check 4: Cross-Reference Health] Broken wikilink
- **Page**: wiki/concepts/self-attention.md
- **Link**: `[[mulit-head-attention]]` (note typo)
- **Suggestion**: Did you mean `[[multi-head-attention]]`?

## Warnings

(similar structure, 7 entries)

## Info

(similar structure, 4 entries)

## Recommendations

1. Run `--fix` to auto-fix 3 warnings (missing index entries, link-index regeneration)
2. Review 2 failures manually
3. Consider filing `self-attention` synthesis page (mentioned 8 times, no page)
```

---

## Health Score Formula

```
base = 10
- (failures * 1.0)
- (warnings * 0.3)
- (info * 0.1)
```

Clamp to `[0, 10]`. Round to 1 decimal place.

**Interpretation:**
- 9-10: excellent
- 7-8: good, minor issues
- 5-6: needs attention
- 0-4: significant rework needed

---

## Auto-Fix Mode (`--fix`)

`--fix` runs lint, then applies **safe** auto-fixes:

| Check | Auto-Fix Action | Safety |
|-------|-----------------|--------|
| 1 | Add missing frontmatter defaults (`status: draft`, `confidence: uncertain`) | Safe — conservative defaults |
| 2 | Add missing index entries | Safe — additive only |
| 2 | Remove index entries pointing to missing pages | Unsafe — prompts user |
| 4 | Regenerate `_maintenance/link-index.md` | Safe — derived file |
| 4 | Add bidirectional backlinks to pages | Safe — additive, no content modification |
| 10 | Normalize slug case (kebab) | Conditional — only if target filename is available |

**Does NOT auto-fix:**
- Contradictions (need human judgment)
- Staleness (needs content review)
- Gaps (need content creation)
- Broken citations (cannot fabricate sources)
- Broken links (cannot pick the right target)

`--fix` acquires `.wiki.lock` for the write phase. Release after completion.

---

## Mandatory Lint Triggers

Lint MUST run automatically in these scenarios:

1. **After every batch ingest** (required by `ingest.md` Step 10 batch mode)
2. **Before user-requested wiki export** (to package a clean wiki)
3. **Before cross-agent handoff** (when wiki is passed as context to another agent)
4. **Before schema evolution apply** (as a pre-check — must pass)
5. **Before schema evolution apply — post-check** (must pass after backfills)

**Not required** (but recommended):
- After single-source interactive ingest
- During development/drafting
- On a schedule (e.g. weekly cron via `loop` skill)

---

## Lint History

Append each lint run to `_maintenance/lint-history.jsonl`:

```jsonl
{"date": "2026-04-07T14:32:00Z", "health_score": 8.5, "failures": 2, "warnings": 7, "info": 4, "duration_s": 3.2, "trigger": "batch-ingest"}
{"date": "2026-04-08T09:15:00Z", "health_score": 9.2, "failures": 0, "warnings": 3, "info": 2, "duration_s": 2.8, "trigger": "manual"}
```

Alf uses this history for the Knowledge Freshness lens.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running auto-fix on contradictions | Fabricates reconciliations, loses information | Contradictions are REPORT-ONLY — human judgment required |
| Skipping lint after batch ingest | Broken links and missing backlinks accumulate silently | Mandatory trigger #1 — batch mode always lints |
| Ignoring warnings | Warnings are early signals of failures | Triage warnings each lint run; promote repeat warnings to fix |
| Computing health score without weighting | All failures become equal, prioritization breaks | Use the formula: failures 1.0, warnings 0.3, info 0.1 |
| Running lint without reading WIKI.md first | Enum validation falls back to defaults, domain-specific rules missed | Load WIKI.md once, use it as the source of truth for schema |
| Auto-fixing slug case without checking targets | Can collide with existing files, breaks links | `--fix` is conditional — check target availability first |
