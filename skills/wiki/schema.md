# Wiki Schema — WIKI.md Structure, Evolution, Bootstrap

Reference file for `wiki` skill family. Covers: WIKI.md structure, frontmatter validation, schema evolution protocol, wiki bootstrap from template.

Invoked by: the wiki agent, and by other agents that need to create wikis, validate frontmatter, or evolve a schema.

---

## Part 1: Bootstrap a New Wiki

### 1.1 Inputs

- **Wiki name** (slug, kebab-case): e.g. `trading-research`
- **Domain template**: one of {research, project, personal, business, reading, general}
- **Target location**: `~/wikis/<name>/` (personal) or `<project-root>/.wiki/` (project-embedded) or user-specified absolute path
- **Description**: one-line purpose
- **Tags**: optional list for registry classification
- **Visibility**: `private` (default) | `shared`

### 1.2 Bootstrap Protocol

```
1. Validate: name is kebab-case, target location does not already contain a wiki
2. Check for .wiki.lock in target — abort if present (another writer)
3. Create directory structure:
     <wiki-root>/
       raw/
       raw/images/
       wiki/
       _templates/
       _maintenance/
4. Read master template: ~/.claude/skills/wiki/templates/<domain>.md
5. Generate WIKI.md from template (see Part 2 for required sections)
6. Copy template's page types to <wiki-root>/_templates/<type>.md (one per page type)
7. Generate index.md with header + empty category sections
8. Generate log.md with bootstrap entry
9. Create .wiki-meta.yaml with { name, path, domain, template_version, created }
10. Initialize _maintenance/ files:
      - link-index.md (empty table)
      - tag-registry.md (empty)
      - lint-history.jsonl (empty)
      - source-manifest.yaml (empty dict)
      - source-tracking.yaml (empty linked_sources, for linked-mode wikis)
      - wiki-metrics.jsonl (empty — first snapshot written at end of bootstrap)
      - page-events.jsonl (empty — populated as pages are created)
      - archived-sources.yaml (empty — populated when sources are deprecated/archived/removed)
11. Initialize git repo: `git init`, `git add .`, `git commit -m "wiki bootstrap: <name> (v00, <domain> template)"`
12. Tag the initial commit: `git tag wiki-v00`
13. Append baseline snapshot to wiki-metrics.jsonl (event=bootstrap, version=0, page_count=0, source_count=0)
14. Register in ~/.wiki-registry.yaml (create registry file if missing)
15. Write bootstrap entry to log.md
16. Report success with path, WIKI.md path, next steps
```

**Git is mandatory for new wikis.** It is the source of truth for content history. The JSONL files in `_maintenance/` are query-friendly indexes ON TOP of git. If `git` is unavailable, fall back to snapshot directories (see Part 5) and warn loudly — git provides far better diffs, rollback, and history than any file-based scheme.

### 1.3 Registry Entry Format

Append to `~/.wiki-registry.yaml`:

```yaml
wikis:
  <name>:
    path: <absolute path>
    domain: <template-name>
    template: <template-name>-v1
    created: <YYYY-MM-DD>
    last_accessed: <YYYY-MM-DD>
    page_count: 0
    source_count: 0
    description: <one-liner>
    tags: [<tag1>, <tag2>]
    visibility: private
```

**Registry is advisory** — wikis work standalone. `.wiki-meta.yaml` inside the wiki is the authoritative local backup.

---

## Part 2: WIKI.md Structure

WIKI.md is the per-wiki rulebook. **Hard cap: ≤300 lines.** Overflow goes into `_templates/` reference files.

### 2.1 Required Sections (11)

Every WIKI.md must have these 11 sections, in order:

1. **Identity & Purpose** — name, domain, one-paragraph purpose, visibility
2. **Directory Structure** — layer ownership rules (raw immutable, wiki LLM-owned, etc.)
3. **Page Types** — table: type | purpose | required frontmatter | template file
4. **Frontmatter Conventions** — required fields, enums, date format, tag taxonomy
5. **Cross-Referencing Rules** — wikilink format, bidirectional tracking, auto-link rules
6. **Naming Conventions** — slug rules (kebab-case), category prefixes, file naming
7. **Output Formats** — citations, Mermaid triggers, table style, callout style
8. **Maintenance Workflows** — lint frequency, staleness thresholds, archive rules
9. **Obsidian Compatibility** — wikilink syntax notes, frontmatter view, folder layout
10. **Domain-Specific Behavior** — template-specific tuning (what makes this wiki unique)
11. **Evolution Log** — schema version + change history (appended on each evolution)

### 2.2 Schema Version Field

WIKI.md frontmatter must include `schema_version`:

```yaml
---
wiki_name: trading-research
domain: research
template: research-v1
schema_version: 1
created: 2026-04-07
---
```

Schema version is **intentionally unused in v1** (schema is frozen per template). It exists to enable future migration tooling. Do not increment unless following the Evolution Protocol (Part 4).

---

## Part 3: Frontmatter Validation

Every page in `wiki/` must have valid frontmatter. Lint check #1 validates this.

### 3.1 Required Fields (All Pages)

```yaml
---
type: <string>              # Must match a type in WIKI.md Page Types table
title: "<string>"           # Human-readable title
slug: <kebab-case-string>   # Must match filename (without .md)
created: <YYYY-MM-DD>
updated: <YYYY-MM-DD>
sources: <list>             # At least one source (empty list only for 'overview' type)
tags: <list>                # May be empty
status: <enum>              # draft | active | review | archived
confidence: <enum>          # high | medium | low | uncertain
---
```

### 3.2 Enum Validation

| Field | Allowed Values |
|-------|----------------|
| `status` | `draft`, `active`, `review`, `archived` |
| `confidence` | `high`, `medium`, `low`, `uncertain` |
| `type` | Must be in the WIKI.md Page Types table |

Invalid enums fail lint check #1 (structural integrity).

### 3.3 Optional Fields

```yaml
aliases: ["Old Name", "Other Name"]   # Alternative lookup strings
related: [slug1, slug2]                # Related wikilink slugs
deprecated: false                      # True if page has been superseded
superseded_by: <slug>                  # Only if deprecated=true
reviewed_on: <YYYY-MM-DD>              # Last human review date
reviewed_by: <string>                  # Who reviewed
supersedes: [<slug1>, <slug2>]         # Pages this one replaces
contradicts: [<slug>]                  # Pages this one contradicts (see conflict flow)
```

### 3.4 Source Entry Format

Each entry in `sources` list:

```yaml
sources:
  - path: raw/2026-04-07-vaswani-2017.pdf
    pages: [1, 12]        # Optional for non-paginated sources
    lines: [45, 120]      # Optional, alternative to pages
    anchor: "Section 3.2" # Optional, for deep links
```

At least one of `pages`, `lines`, or `anchor` must be present for lint check #3.

---

## Part 4: Schema Evolution Protocol

Schemas MUST co-evolve with user approval. The agent never silently mutates WIKI.md.

### 4.1 Detection Signals

Agent observes schema pressure when:

- User adds the same field manually to 3+ pages
- User renames a field type (e.g., `note-type` -> `category`) consistently
- Domain template no longer fits observed usage patterns
- New page type emerges organically (5+ pages of an unlisted type)
- Existing field becomes unused across 20+ pages

### 4.2 Evolution Proposal

When a signal triggers, agent produces a proposal:

```
Schema Evolution Proposal — <wiki-name>
Current version: <N>
Proposed version: <N+1>

Trigger: <what was observed>
Change: <specific WIKI.md edit>
Affected pages: <count + list of first 10>
Migration plan:
  - [ ] Update WIKI.md section X
  - [ ] Backfill N pages: add missing field with default <value>
  - [ ] Update templates: <list>

Approve? (y/n/details)
```

### 4.3 Applying Evolution

On approval:

```
1. Acquire .wiki.lock
2. Update WIKI.md (edit section)
3. Increment schema_version in frontmatter
4. Append to WIKI.md Evolution Log section:
     - date, version transition, summary, affected_page_count
5. Backfill affected pages (add missing fields with default values)
6. Update _templates/<type>.md files
7. Regenerate _maintenance/link-index.md
8. Log to log.md
9. Release .wiki.lock
10. Run lint to verify — fail if check #1 reports errors
```

### 4.4 Evolution Log Format

Inside WIKI.md Section 11:

```markdown
## Evolution Log

| Version | Date | Change | Affected Pages |
|---------|------|--------|----------------|
| 1 -> 2 | 2026-05-14 | Added `reviewed_by` to frontmatter | 47 |
| 2 -> 3 | 2026-06-22 | New page type: `experiment-log` | 0 (forward-only) |
```

---

## Part 5: Versioning, Source Lifecycle, and Removal

### 5.0 Canonical Lock Primitive (POSIX flock)

**This is the single source of truth for wiki concurrency control. All other skill files MUST delegate to this section.**

**Problem**: Two concurrent wiki operations (e.g., user ingest + alf background sweep) corrupt shared state if both proceed without coordination. Hand-rolled `O_CREAT|O_EXCL` + stale detection has a TOCTOU race between the stale check and unlink — confirmed by Codex review (2026-04-07).

**Solution**: Use **POSIX advisory `flock(2)`** — kernel-managed, race-free by construction, auto-released on process exit (including crash).

**Invariants**:
- **L1**: At most one process holds the wiki lock at any time.
- **L2**: No process deletes a lock it doesn't own.
- **L3**: Crashed processes automatically release the lock (kernel-managed).
- **L4**: Lock is released on every exit path — success, error, signal, crash.
- **L5**: One canonical format across Python and bash. All other files reference this.

**Key properties**:
- Kernel enforces mutual exclusion — no user-space race window.
- Process death (crash, SIGKILL, OOM killer) automatically releases the lock — no stale cleanup logic needed.
- Bash and Python both use the same underlying `flock(2)` syscall — no cross-language drift.
- Requires local filesystem (not NFS < v4). Document this requirement.

#### Canonical Python implementation

```python
import fcntl, contextlib, os, json, time

class LockBusy(Exception):
    """Raised when another process holds the wiki lock."""
    def __init__(self, holder_info):
        self.holder_info = holder_info
        super().__init__(f"Wiki is locked by: {holder_info}")

@contextlib.contextmanager
def wiki_lock(wiki_root, operation):
    """
    Acquire exclusive lock on wiki_root via flock(2).
    - Raises LockBusy(holder_info) if another process holds it.
    - Lock is automatically released on context exit (success, error, crash).
    - Writes a .wiki.lock.info file with holder metadata for human diagnostics.

    Usage:
        with wiki_lock("/path/to/wiki", "refresh"):
            # all mutations here
            ...
        # lock released automatically
    """
    lock_path = os.path.join(wiki_root, ".wiki.lock")
    info_path = lock_path + ".info"
    fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # Another process holds it — read info file for error message
        os.close(fd)
        info = {}
        try:
            with open(info_path) as f:
                info = json.load(f)
        except Exception:
            pass
        raise LockBusy(info)
    # We hold the lock. Write info file for diagnostics.
    info = {
        "agent": "wiki",
        "pid": os.getpid(),
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "operation": operation,
    }
    try:
        with open(info_path, "w") as f:
            json.dump(info, f)
        yield
    finally:
        # Always clean up — runs on success, exception, KeyboardInterrupt, etc.
        try:
            os.unlink(info_path)
        except FileNotFoundError:
            pass
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        # DO NOT unlink .wiki.lock here — that would race with a new acquirer.
        # The file is harmless to leave; flock() on a stale file works fine.
```

#### Canonical bash implementation

```bash
# wiki_lock — acquire exclusive flock on wiki_root/.wiki.lock
# Usage:
#   wiki_lock /path/to/wiki refresh || exit 1
#   # ... mutations ...
#   # lock released automatically by trap on any exit
wiki_lock() {
  local wiki_root=$1
  local operation=$2
  local lock="$wiki_root/.wiki.lock"
  local info="$lock.info"
  # Open FD 9 on the lock file
  exec 9>"$lock" || return 1
  # Acquire exclusive non-blocking flock
  if ! flock -n 9; then
    local holder
    holder=$(cat "$info" 2>/dev/null || echo "unknown")
    echo "LOCK BUSY (held by $holder)" >&2
    exec 9>&-
    return 1
  fi
  # Write info file (best-effort; failures don't break the lock)
  printf '{"agent":"wiki","pid":%d,"operation":"%s","started":"%s"}\n' \
    "$$" "$operation" "$(date -u +%FT%TZ)" > "$info" 2>/dev/null || true
  # Install trap for automatic release on ANY exit (success, error, signal)
  # The trap also runs if an untracked INT or TERM arrives.
  trap "rm -f '$info'; flock -u 9 2>/dev/null; exec 9>&-" EXIT INT TERM
  return 0
}
```

**Both primitives**:
- Return nonzero on contention — callers MUST check the return code (fixes Codex A2).
- Race-free via kernel `flock(2)` — no TOCTOU window (fixes Codex A1).
- Auto-release on every exit path via `finally`/`trap` (fixes Codex I).
- Same JSON `.info` format across Python and bash (fixes Codex A3 cross-file drift).
- No stale detection code — kernel handles it (deletes 80+ lines of fragile logic).

#### Crash recovery semantics

When a process holding the lock dies (crash, SIGKILL, host reboot):
1. Kernel automatically releases the `flock(2)` on the file descriptor.
2. The next process calling `wiki_lock()` succeeds immediately — no waiting, no cleanup.
3. The `.wiki.lock` file may remain on disk — harmless, and deleting it would introduce a race.
4. The `.wiki.lock.info` file may contain stale metadata — next successful lock overwrites it.

There is **no stale detection logic**. There is **no PID liveness check**. The kernel does it for us.

#### NFS caveat

`flock(2)` on NFS < v4 falls back to no-op behavior (silently!) on some kernels. Wiki roots MUST be on local filesystems OR NFSv4+. The wiki agent should check filesystem type on bootstrap and warn if the wiki root is on an unsupported NFS version.

Check with: `stat -f -c %T <wiki-root>` — if the result is `nfs` and the server is NFSv3 or older, fail loudly at bootstrap.

#### Reader-writer semantics

- **Reads do NOT acquire the lock.** Only writes (ingest, refresh, remove, schema-evolve) do.
- **Filesystem readers** (e.g., Obsidian, `cat`) may see transient state during a refresh. This is the weak-consistency read path.
- **Strong-consistency readers** (export, publish, snapshot) should read via `git show wiki-v<NN>:<path>` — git commits are atomic.
- See §5.10 (Consistency Model) for the full statement.

#### Agent doc requirement

`~/.claude/agents/wiki.md` MUST reference this section as the sole authority on lock behavior. Any lock-related description in `wiki.md` that contradicts §5.0 is a bug.

### 5.1 Wiki Version (Monotonic)

In addition to `schema_version`, every wiki has a **`wiki_version`** field in WIKI.md frontmatter. This is a monotonic counter representing the wiki's maturity at a given point in time. It is auto-bumped by the wiki agent on every batch ingest, source removal, schema evolution, or significant restructuring.

```yaml
wiki_id: trading
wiki_version: 20          # monotonic, bumped on every significant operation
schema_version: 1         # only bumped on schema evolution (rare)
```

**When to bump `wiki_version`:**
- Every batch ingest (one bump per batch, not per source)
- Source deprecation/archive/removal (one bump per lifecycle transition)
- Schema evolution (also bumps schema_version)
- Significant restructuring (page renames affecting 5+ pages)

**When NOT to bump:**
- Lint runs (no content change)
- Query operations (read-only)
- Single-page interactive ingest unless explicitly part of a session
- Frontmatter cosmetic fixes by lint --fix

The version number prefixes git tags: `wiki-v00`, `wiki-v01`, ..., `wiki-v20`. Tags let you `git checkout wiki-v15` to see the wiki at that point in time.

### 5.2 Source Lifecycle States

A linked or owned source progresses through states:

```
active           Source is current, tracked, ingested
  ↓ (lint flags or user marks)
deprecated       Source still exists; flagged. Pages get a deprecation banner.
                 Source remains in source-tracking.yaml. Re-ingest still allowed.
  ↓ (after grace period or user confirms)
archived         Source moved from source-tracking.yaml to archived-sources.yaml.
                 Wiki pages get status: archived. Pages still readable, not in main index.
                 Citations to this source still resolve via archived-sources.yaml.
  ↓ (user explicitly purges)
removed          Wiki pages may be deleted (or kept as historical).
                 archived-sources.yaml retains audit metadata (id, last_seen_hash, when, why).
                 Git history retains the actual content forever.
```

**The state never goes backwards.** A removed source can be re-ingested as a NEW source (different ingested_at timestamp) but the original removal record stays in archived-sources.yaml.

### 5.3 archived-sources.yaml Schema

Lives at `<wiki-root>/_maintenance/archived-sources.yaml`:

```yaml
version: 1
archived_sources:
  - id: trading/docs/old-strategy.md
    archived_at: 2026-04-15T10:00:00Z
    archived_by: user
    state: archived          # archived | removed
    reason: "Strategy abandoned, replaced by [[new-strategy]]"
    final_sha256: 3a7b...    # last known hash
    final_mtime: 2026-04-10T08:30:00Z
    wiki_pages_at_time: [wiki/strategies/old-strategy.md]
    wiki_pages_action: archived  # archived | deleted
    superseded_by: trading/docs/new-strategy.md  # optional
```

### 5.4 Source Removal Protocol

The wiki agent's removal protocol (invoked when user says "remove source X" or "deprecate source Y"):

```
1. Resolve source_id from user input (fuzzy match against source-tracking.yaml)
2. Determine target state (deprecated | archived | removed) — default: deprecated
3. Confirm with user — show what pages will be affected
4. Acquire .wiki.lock
5. Apply transition:

   active → deprecated:
     - Add `deprecated: true` and `deprecated_at` to source-tracking entry
     - Add deprecation banner to all wiki_pages of this source
     - Page frontmatter: status remains active, add `deprecated_source: true`
     - Append page-events.jsonl entry per affected page

   deprecated → archived:
     - Move source-tracking entry to archived-sources.yaml
     - Set page status: archived
     - Remove pages from main index.md (move to archived section)
     - Append page-events.jsonl entries

   archived → removed:
     - Confirm with user (irreversible from active wiki POV — only git can recover content)
     - Delete or keep wiki pages (user choice)
     - Update archived-sources.yaml entry: state=removed, wiki_pages_action=...
     - Append page-events.jsonl

6. Bump wiki_version in WIKI.md
7. Append wiki-metrics.jsonl snapshot (event=source_lifecycle)
8. Commit to git: "wiki-vNN: <action> source <id> (reason: ...)"
9. Tag if version was bumped: git tag wiki-vNN
10. Release .wiki.lock
11. Log to log.md
```

**Citation behavior after removal:**
- A wiki page citing an archived/removed source still RESOLVES (citation lookup checks both source-tracking.yaml AND archived-sources.yaml)
- Lint warns about citations to deprecated/archived sources but does not break them
- Removed source's content can be retrieved from git history if needed

### 5.5 page-events.jsonl Schema

Lives at `<wiki-root>/_maintenance/page-events.jsonl`. Append-only. One line per event.

```jsonl
{"ts":"2026-04-07T10:45:00Z","page":"wiki/components/trading-engine.md","event":"create","wiki_version":1,"source_id":"trading/docs/components/trading-engine/COMPONENT.md","trigger":"ingest"}
{"ts":"2026-04-08T14:20:00Z","page":"wiki/components/trading-engine.md","event":"update","wiki_version":2,"source_id":"trading/docs/components/trading-engine/COMPONENT.md","trigger":"source_changed","fields_changed":["body"]}
{"ts":"2026-05-10T09:00:00Z","page":"wiki/strategies/old-strategy.md","event":"deprecate","wiki_version":15,"source_id":"trading/docs/old-strategy.md","reason":"replaced by new-strategy"}
{"ts":"2026-05-15T09:00:00Z","page":"wiki/strategies/old-strategy.md","event":"archive","wiki_version":16}
```

**Event types**: `create`, `update`, `rename`, `deprecate`, `archive`, `remove`, `restore` (re-ingest of a removed source).

### 5.6 wiki-metrics.jsonl Schema

Lives at `<wiki-root>/_maintenance/wiki-metrics.jsonl`. Append-only. One line per significant event.

```jsonl
{"ts":"2026-04-07T10:30:00Z","event":"bootstrap","wiki_version":0,"page_count":0,"source_count":0,"link_count":0}
{"ts":"2026-04-07T10:45:00Z","event":"ingest_batch","wiki_version":1,"page_count":6,"source_count":6,"link_count":24,"sources_added":6,"pages_added":6}
{"ts":"2026-04-07T12:45:00Z","event":"lint","wiki_version":20,"page_count":28,"source_count":30,"link_count":168,"health_score":10.0,"failures":0,"warnings":0}
{"ts":"2026-05-10T09:00:00Z","event":"source_lifecycle","wiki_version":21,"page_count":28,"source_count":29,"action":"deprecate","source_id":"...","pages_affected":1}
```

**Event types**: `bootstrap`, `ingest_batch`, `lint`, `source_lifecycle`, `schema_evolution`, `restructure`.

**Querying historic performance** (examples):
```bash
# Page count over time
jq -r '"\(.ts) v\(.wiki_version) pages=\(.page_count)"' _maintenance/wiki-metrics.jsonl

# Lint scores over time
jq -r 'select(.event=="lint") | "\(.ts) v\(.wiki_version) score=\(.health_score)"' _maintenance/wiki-metrics.jsonl

# All source removals
jq -r 'select(.event=="source_lifecycle" and .action=="remove") | "\(.ts) v\(.wiki_version) \(.source_id)"' _maintenance/wiki-metrics.jsonl
```

### 5.6.5 wiki_version — Git Tag Is the Source of Truth

**Problem**: `wiki_version` appears in both WIKI.md frontmatter AND git tags. Split-brain possible if one update succeeds but not the other. Also: naive `git tag --list` discovery picks the numeric max across ALL tags, even stray ones on orphan branches — Codex finding G (2026-04-07).

**Rule**: The **latest `wiki-vNN` tag reachable from HEAD** is the authoritative wiki version. WIKI.md frontmatter MUST match it EXACTLY (no tolerance). If they disagree, WIKI.md is wrong and the tag wins.

#### Canonical version discovery

```bash
# Find the latest wiki version tag reachable from HEAD
wiki_latest_version() {
  # --merged HEAD ensures stray tags on orphan branches don't hijack us
  git tag --merged HEAD --list 'wiki-v*' \
    | sed 's/wiki-v//' \
    | sort -n \
    | tail -1
}

# Check that the tag sequence has no gaps (v20, v21, v22, v24 with missing v23 is an error)
wiki_check_tag_sequence() {
  local expected=0
  local first=1
  for v in $(git tag --merged HEAD --list 'wiki-v*' | sed 's/wiki-v//' | sort -n); do
    if [ "$first" -eq 1 ]; then
      expected=$v
      first=0
    fi
    if [ "$v" -ne "$expected" ]; then
      echo "GAP: expected wiki-v$expected, got wiki-v$v" >&2
      return 1
    fi
    expected=$((v+1))
  done
  return 0
}
```

Python equivalent:

```python
import subprocess

def wiki_latest_version(wiki_root: str) -> int | None:
    """Return the numeric latest wiki version tag reachable from HEAD, or None."""
    result = subprocess.run(
        ["git", "-C", wiki_root, "tag", "--merged", "HEAD", "--list", "wiki-v*"],
        capture_output=True, text=True, check=True,
    )
    tags = [int(t.removeprefix("wiki-v")) for t in result.stdout.split() if t.startswith("wiki-v")]
    return max(tags) if tags else None

def wiki_check_tag_sequence(wiki_root: str) -> list[int]:
    """Return list of missing version numbers (gaps) in the tag sequence."""
    result = subprocess.run(
        ["git", "-C", wiki_root, "tag", "--merged", "HEAD", "--list", "wiki-v*"],
        capture_output=True, text=True, check=True,
    )
    tags = sorted(int(t.removeprefix("wiki-v")) for t in result.stdout.split() if t.startswith("wiki-v"))
    if not tags:
        return []
    expected = set(range(tags[0], tags[-1] + 1))
    return sorted(expected - set(tags))
```

#### Commit order (strict, used by ingest/refresh/remove/schema-evolve)

See §5.9 for the canonical `wiki_transaction` procedure. In summary:
1. Acquire lock (§5.0)
2. Record `START_COMMIT=$(git rev-parse HEAD)`
3. Verify working tree is clean
4. Make all content changes
5. Compute `NEW_N = $(wiki_latest_version) + 1`
6. Update WIKI.md `wiki_version` = NEW_N
7. `git add -A && git commit -m "wiki-v<NN>: <summary>"` — on failure, `wiki_rollback_to "$START_COMMIT"`
8. `git tag wiki-v<NN>` — on failure, `wiki_rollback_to "$START_COMMIT"`
9. Verify tag matches WIKI.md wiki_version — on mismatch, `wiki_rollback_to "$START_COMMIT"`
10. Release lock (trap/finally)

#### Recovery if WIKI.md drifts from git tag

- Lint Check 12 detects any drift (exact match required, **no ±1 tolerance**).
- Lint Check 12 also detects tag sequence gaps.
- `wiki reconcile-version` operation (new, takes the lock) rewrites WIKI.md's `wiki_version` from `wiki_latest_version`. Not a lint `--fix` operation — it's a mutation and goes through the transactional protocol.
- If there is no tag yet (pre-bootstrap), WIKI.md is the source of truth; the first `wiki-v00` tag is created at bootstrap.

**Previous "±1 tolerance" removed**: Codex confirmed the tolerance was masking the real issue. With the transactional refresh protocol (§5.9) there is no in-flight window outside the lock — drift is a real bug, not a transient. Lint now fails exactly on drift.

### 5.6.6 Three-Field Identity Model

**Problem**: The S012 first-pass combined content_id (fingerprint) and source_id (lineage) into one concept. Codex finding C2 (2026-04-07): refresh updates `sha256` but not `content_id` → drift. Finding C1: dedup (two files with identical content sharing content_id) is undefined.

**Solution**: Three distinct fields, each with one job.

| Field | Purpose | Type | Stable across | Derived from |
|-------|---------|------|---------------|--------------|
| `source_id` | Lineage identifier. Human-readable handle for the file as tracked. | string | re-ingestion at same path | `<source_root>/<rel_path>` |
| `content_id` | Content fingerprint. 16 hex chars of SHA-256. | string | pure renames (same bytes, different path) | `sha256[:16]` |
| `sha256` | Full content hash. Source of truth. | string (64 hex) | byte-for-byte identity | `hashlib.sha256(content).hexdigest()` |

**Rules**:

1. **`sha256` is the ground truth.** Always the full 64-character hex.
2. **`content_id` is ALWAYS derived** from `sha256` as `sha256[:16]`. Never manually set. Lint Check 11 enforces `content_id == sha256[:16]`.
3. **`source_id` is the stable lineage handle.** It can be renamed (via `wiki reconcile-sources`), but the old→new mapping is recorded in page-events.jsonl.
4. **Refresh protocol**: when a source is re-ingested, recompute `sha256`, then recompute `content_id = sha256[:16]` as a REQUIRED trailing step in the same write. Both fields stay in sync by construction.

**Example entry** (canonical):

```yaml
linked_sources:
  - source_id: trading/PROJECT.md                 # lineage handle (stable across re-ingestion)
    content_id: 07e9e2d3d031a668                  # fingerprint (stable across rename)
    sha256: 07e9e2d3d031a66896d001f70beb384051cdbdc2e25db63cd13cf4d249a4e722
    type: file                                    # file | aggregate (§5.12)
    abs_path: /path/to/projects/trading/PROJECT.md
    source_root: trading
    rel_path: PROJECT.md
    size_bytes: 6800
    mtime: 2026-03-31T09:23:57+00:00
    lifecycle_state: active                       # active | deprecated | archived (§5.11)
    ingested_at: 2026-04-07T10:45:00+00:00
    wiki_pages: [wiki/architecture/ai-trading-system-overview.md]
```

**Previous `id:` field**: renamed to `source_id:` for clarity. Migration tooling rewrites old entries.

#### Dedup: identical content, different files

Two source files with identical byte content share the same `content_id`. This is VALID but must be tracked:

- They have distinct `source_id` values (different paths).
- They share `content_id` and `sha256`.
- Lint Check 11.5 (new) reports them as **dedup aliases** at info-level (not a warning).
- Rename detection: if a missing file's content_id matches multiple candidates, the result is `ambiguous` — user must choose.

**Not recommended** but allowed. Avoid ingesting duplicate files; use a single `source_id` with multiple `wiki_pages` instead.

#### Citation resolution chain

When a wiki page cites a source, resolution walks this chain:

1. **Active sources**: look up `content_id` in `source-tracking.yaml`. Return current `abs_path`.
2. **Archived sources**: look up `content_id` in `_maintenance/archived-sources.yaml`. Return archived metadata (content accessible via git history).
3. **Git history fallback**: `git log -S "<content_id>" -- _maintenance/source-tracking.yaml` finds commits where the source was tracked, pointing to historical versions.
4. **Unresolved**: lint flags as broken citation, user decides whether to remove or restore.

**Page frontmatter citations** include both fields:

```yaml
sources:
  - content_id: 07e9e2d3d031a668
    source_id: trading/PROJECT.md
    mode: linked
```

The body citation format remains `[Source: trading/PROJECT.md, lines 12-45]` for human readability. The `content_id` resolves the actual content even if the path has moved.

#### content_id collision risk

First 16 hex of SHA-256 = 64 bits of entropy. Birthday paradox:

| Wiki size | Collision probability |
|-----------|----------------------|
| 100 sources | ~2.7e-16 |
| 1,000 sources | ~2.7e-14 |
| 10,000 sources | ~2.7e-12 |
| 1,000,000 sources | ~2.7e-8 |
| 100,000,000 sources | ~2.7e-4 (starts to matter) |

For practical wiki sizes (thousands of sources), collision risk is negligible. For wikis tracking > 10M sources, widen to 20 or 24 hex prefix via WIKI.md `content_id_bits:` field.

**Note on dedup vs collision**: dedup is "same bytes → same content_id" (intentional). Collision is "different bytes → same content_id by chance" (accidental). Dedup is reported as alias; collision at practical sizes is vanishingly rare.

### 5.6.7 JSONL Schema Headers (Version Envelope)

**Problem**: `wiki-metrics.jsonl` and `page-events.jsonl` have no version marker. If the schema evolves (e.g., adding `agent_id` to every event), old entries become unparseable.

**Solution**: The **first line** of every JSONL file is a schema envelope, not an event. Readers must check the envelope before parsing subsequent lines.

```jsonl
{"_schema": "wiki-metrics", "_version": 1, "_wiki_id": "trading", "_created": "2026-04-07T10:30:00Z"}
{"ts": "2026-04-07T10:30:00Z", "event": "bootstrap", ...}
{"ts": "2026-04-07T10:45:00Z", "event": "ingest_batch", ...}
```

```jsonl
{"_schema": "page-events", "_version": 1, "_wiki_id": "trading", "_created": "2026-04-07T10:30:00Z"}
{"ts": "2026-04-07T10:45:00Z", "page": "...", "event": "create", ...}
```

**Readers**:
1. Open file, read first line
2. If first line starts with `{"_schema":`, parse as envelope. Otherwise, assume legacy (v0) format and warn.
3. Use envelope's `_version` to pick the correct parser
4. Skip the envelope line and process the remaining lines

**Schema evolution** protocol:
- Bump `_version` in the envelope
- Write a migration function that upgrades old entries to the new format (or tolerates old fields)
- Document the version history in this file

**Legacy migration** (retroactive): envelope migration belongs to **refresh/bootstrap only, NOT lint**. Lint is strictly read-only (§5.0 and lint.md). The `wiki refresh` operation (or `wiki migrate-jsonl` — a new refresh variant) takes the lock, prepends the envelope to legacy files, and commits transactionally. Lint Check 10 detects envelope absence and reports it as a Warning, but does NOT fix it.

**Reader compatibility**: example `jq` commands for wiki-metrics.jsonl and page-events.jsonl MUST skip the envelope line:

```bash
# Correct — skip envelope via `has("ts")` filter
jq -r 'select(has("ts")) | "\(.ts) v\(.wiki_version) \(.event)"' _maintenance/wiki-metrics.jsonl

# Wrong — would misinterpret the envelope as an event row
# jq -r '"\(.ts) v\(.wiki_version) \(.event)"' _maintenance/wiki-metrics.jsonl
```

### 5.8 Source Rename / Move Detection

**Scenario**: A linked source file is renamed (`trading/docs/old-name.md → trading/docs/new-name.md`) or moved between source roots (`trading/foo.md → trading02/foo.md`).

**Detection** (during lint Check 11 or refresh):
1. For each entry marked `missing` (abs_path no longer exists):
2. Scan all configured source_roots for files matching the stored `sha256` (or `content_id` as fast prefilter)
3. Classify:
   - **Single match found**: source was RENAMED. Update `abs_path`, `source_root`, `rel_path`. Record in page-events as `{"event":"rename","old_id":"...","new_id":"...","content_id":"..."}`. Citations still resolve via `content_id`.
   - **Multiple matches found**: AMBIGUOUS. Report to user, let them choose. Do NOT auto-select.
   - **No match found**: source was DELETED. Leave as `missing`. Offer to deprecate via the source removal protocol (5.4).
4. Logging: every rename detection is logged to page-events.jsonl with both old and new IDs, and bumps wiki_version

**Performance note**: Rename detection requires re-hashing candidate files, which is expensive. Run it ONLY during:
- User-requested refresh
- Lint `--with-rename-detection` flag (off by default — too expensive for routine lint)
- Explicit `wiki reconcile-sources` operation

The session-start quick scan (mtime-only) does NOT do rename detection.

### 5.9 Transactional Refresh (Atomicity via Git)

**Problem**: Refresh processes N stale sources sequentially. If it crashes after source 3/5, source-tracking.yaml is partially updated, wiki pages are partially updated, JSONL files have partial entries — wiki is in an inconsistent state.

**Codex findings addressed** (round 2, 2026-04-07):
- **B1**: Previous doc used `git reset --hard HEAD~1` on failure — this is destructive when no commit was made (rolls back a VALID prior version).
- **B2**: `git clean -fd` only in per-source error path, not in commit/tag failures.
- **I**: No trap/finally around the lock; git failures leave the lock stranded.

**Solution**: Single canonical `wiki_rollback_to` function. Every error path calls it with the recorded `$START_COMMIT`. Lock is released via `trap/finally` on EVERY exit path (success, error, signal, crash).

#### Canonical rollback function

```bash
# Single canonical rollback — used by EVERY error path.
# Never use 'git reset --hard HEAD~1'. Always use this function.
wiki_rollback_to() {
  local start_commit=$1
  git reset --hard "$start_commit" || return 1
  git clean -fd                    || return 1  # remove any untracked files created during the failed transaction
  return 0
}
```

Python equivalent:

```python
import subprocess

def wiki_rollback_to(wiki_root: str, start_commit: str) -> bool:
    """Reset wiki to pre-transaction state. Called on every error path."""
    try:
        subprocess.run(
            ["git", "-C", wiki_root, "reset", "--hard", start_commit],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", wiki_root, "clean", "-fd"],
            check=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False
```

#### Transactional refresh protocol

```bash
wiki_refresh() {
  local wiki_root=$1

  # Step 1: Acquire lock (§5.0). trap ensures release on EVERY exit.
  wiki_lock "$wiki_root" "refresh" || return 1

  cd "$wiki_root" || return 1

  # Step 2: Record starting commit BEFORE any changes
  local START_COMMIT
  START_COMMIT=$(git rev-parse HEAD) || return 1

  # Step 3: Pre-check — working tree must be clean
  if ! git diff --quiet HEAD || [ -n "$(git status --porcelain)" ]; then
    echo "Working tree has uncommitted changes — manual git cleanup required" >&2
    return 1
    # Lock released by trap
  fi

  # Step 4: Identify stale sources (read-only at this point)
  local stale_sources
  stale_sources=$(find_stale_sources "$wiki_root") || return 1
  local count
  count=$(echo "$stale_sources" | wc -l)

  # Step 5: Process each stale source
  for src in $stale_sources; do
    if ! process_source "$src"; then
      echo "Failed on source: $src — rolling back" >&2
      wiki_rollback_to "$START_COMMIT"
      return 1
      # Lock released by trap
    fi
  done

  # Step 6: Append metrics snapshot
  append_wiki_metrics "$wiki_root" "refresh_batch" "$count" || {
    wiki_rollback_to "$START_COMMIT"
    return 1
  }

  # Step 7: Compute new version (tag-authoritative — see §5.6.5)
  local LAST_N NEW_N NEW_TAG
  LAST_N=$(wiki_latest_version)
  LAST_N=${LAST_N:--1}  # -1 if no tags yet
  NEW_N=$((LAST_N + 1))
  printf -v NEW_TAG "wiki-v%02d" "$NEW_N"

  # Step 8: Update WIKI.md
  bump_wiki_version "$wiki_root" "$NEW_N" || {
    wiki_rollback_to "$START_COMMIT"
    return 1
  }

  # Step 9: Commit (atomic via git)
  git add -A || { wiki_rollback_to "$START_COMMIT"; return 1; }
  git commit -m "$NEW_TAG: refresh ($count sources)" || {
    wiki_rollback_to "$START_COMMIT"
    return 1
  }

  # Step 10: Tag (on failure, rollback the just-made commit too)
  if ! git tag "$NEW_TAG"; then
    wiki_rollback_to "$START_COMMIT"
    return 1
  fi

  # Step 11: Verify tag matches WIKI.md
  local stored_version
  stored_version=$(grep '^wiki_version:' WIKI.md | awk '{print $2}')
  if [ "$stored_version" != "$NEW_N" ]; then
    echo "Version mismatch after commit — rolling back" >&2
    wiki_rollback_to "$START_COMMIT"
    return 1
  fi

  echo "refresh complete: $NEW_TAG ($count sources refreshed)"
  return 0
  # Lock released by trap on normal return as well
}
```

**Key properties**:
- **EVERY** error path calls `wiki_rollback_to "$START_COMMIT"` — never `HEAD~1` (fixes B1)
- **EVERY** rollback includes `git clean -fd` via the canonical function (fixes B2)
- **Lock release on EVERY exit** via `wiki_lock`'s trap (fixes I — not shown here because trap is installed inside `wiki_lock`)
- **`wiki_latest_version`** uses merged-HEAD discovery (§5.6.5) — stray tags can't hijack

#### Consistency model — see §5.10

The question "what can readers see during a refresh?" is covered in §5.10. In summary: git reads are atomic; filesystem reads can see transient state during the refresh window. The lock prevents multiple writers but does not block readers.

#### Non-git wiki fallback

If the wiki is not a git repo (rare — documented as a degraded mode): transactional refresh is NOT AVAILABLE. The refresh operation fails loudly with "git required for transactional refresh — install git or accept non-transactional mode (not recommended)". A future `_maintenance/.refresh-staging-vNN/` + rsync-swap fallback may be added, but is out of scope for v1.

### 5.10 Consistency Model for Readers

**Problem**: §5.0.1 (removed) said readers see atomic states. §5.9 said readers "WILL see in-progress changes in the working tree". Contradiction. Codex finding B3.

**Resolution**: Both statements were about DIFFERENT read paths. State clearly which path provides which guarantee.

**Two read paths**:

| Path | Consistency | How |
|------|------------|-----|
| **Git reads** — `git show wiki-v<NN>:<path>` or `git log <path>` | **Strong** — atomic by git's commit model. At any point in time, a git read returns the state at a specific commit. | Use for: exports, snapshots, automation that requires consistency |
| **Filesystem reads** — `cat <wiki-root>/<path>` | **Weak** — may observe transient state during an in-flight write. | Use for: Obsidian, human browsing, casual reads |

**Rules**:

1. **Git commits are atomic.** The ref update (branch HEAD pointer move) happens as a single filesystem operation. A git reader sees either pre-commit or post-commit state, never in-between.
2. **Filesystem reads** bypass git's atomicity. During a refresh, the working tree contains the new content BEFORE the commit happens. A filesystem reader in that window sees the new state even though it isn't yet "official".
3. **The lock prevents concurrent writers**, not readers. Reads are always allowed, regardless of lock state.
4. **Tools that need strong consistency** should:
   - Read via `git show wiki-v<latest-tag>:<path>`, OR
   - Read the filesystem AFTER verifying no lock is held (optimistic — doesn't actually guarantee consistency, but reduces the window)

5. **Tools that accept weak consistency** (Obsidian, human browsers):
   - Read filesystem directly
   - Accept occasional transient state during refreshes (windows are short — typically seconds)
   - Re-read if the observed state looks inconsistent

**Why not staging + atomic swap?** A staging directory + directory rename would give strong filesystem consistency, but adds significant complexity. Git already provides strong consistency for tools that care; filesystem readers that don't care accept weak consistency. Simpler wins.

### 5.11 Canonical Field Names (Lifecycle + Freshness)

**Problem**: Three different field names represented lifecycle state across files: `status`, `deprecated: true`, `state`. Codex finding H. Impossible to lint-check consistently.

**Resolution**: Two distinct fields, one canonical name each, orthogonal axes.

| Field | Values | Meaning | Persistent |
|-------|--------|---------|-----------|
| `lifecycle_state` | `active`, `deprecated`, `archived` | Where in the source lifecycle | Yes (stored in source-tracking.yaml for active/deprecated, archived-sources.yaml for archived) |
| `freshness` | `current`, `stale`, `missing`, `conflict` | Health check result from last verification | Yes (stored alongside `lifecycle_state`, computed by refresh, read by lint) |

**Removed/renamed fields**:
- `status` (old, ambiguous) → `freshness` (when referring to health) OR `lifecycle_state` (when referring to lifecycle)
- `deprecated: true` (old, boolean) → `lifecycle_state: deprecated` (explicit enum)
- `state` (old, used in Check 12 expectations) → `lifecycle_state` (canonical)

**Invariants**:
- **F1**: Every source entry has EXACTLY one `lifecycle_state` and one `freshness` field.
- **F2**: `lifecycle_state` is mutated only by ingest/refresh/remove operations (takes lock, commits).
- **F3**: `freshness` is mutated only by refresh (lint NEVER writes).
- **F4**: `removed` state means the entry has been moved from source-tracking.yaml to archived-sources.yaml; it does not appear in source-tracking at all.

**Lint enforcement**:
- Check 11 validates `freshness` enum and `lifecycle_state` enum.
- Check 11 NEVER writes back — if current filesystem state differs from stored `freshness`, that's a report-only finding.
- `wiki refresh` is the operation that updates stored `freshness`.

### 5.12 Aggregate Source Type

**Problem**: 8 live entries in the trading wiki use `aggregate_sha256`, `latest_mtime`, `file_count`, no `size_bytes`. Check 11 assumes file-level fields (`sha256`, `mtime`, `size_bytes`). Aggregates fall outside the model. Codex finding J.

**Resolution**: Explicit `type` discriminator. Two source types, each with its own verifier.

| Type | Fields | Verifier |
|------|--------|---------|
| `file` | `sha256`, `content_id`, `size_bytes`, `mtime`, `abs_path` | Tiered discovery: mtime → size → hash |
| `aggregate` | `aggregate_sha256`, `content_id` (first 16 hex of aggregate), `total_bytes`, `file_count`, `latest_mtime`, `abs_path` (directory), `aggregate_glob`, `aggregate_exclude` | Re-hash the directory via canonical recipe, compare |

**Canonical aggregate hash recipe**:

```bash
# Deterministic: list files matching glob, sort, hash each, then hash the combined stream
verify_aggregate() {
  local dir=$1
  local glob=${2:-"*.py"}
  local exclude=${3:-"__pycache__"}
  find "$dir" -type f -name "$glob" ! -path "*$exclude*" ! -name "__init__.py" \
    | sort \
    | xargs sha256sum 2>/dev/null \
    | sha256sum \
    | cut -d' ' -f1
}
```

The `find | sort | xargs sha256sum | sha256sum` pipeline is deterministic: same directory contents → same hash, regardless of filesystem iteration order.

**Aggregate entry example**:

```yaml
linked_sources:
  - source_id: trading/src/trading_engine
    type: aggregate
    content_id: 80b3753ee50fcd49                  # aggregate_sha256[:16]
    aggregate_sha256: 80b3753ee50fcd499b485c9298c38f69b91c98264268053c1ee6b7d3e9736711
    abs_path: /path/to/projects/trading/src/trading_engine
    source_root: trading
    rel_path: src/trading_engine
    aggregate_glob: "*.py"
    aggregate_exclude: ["__pycache__", "__init__.py"]
    total_bytes: 247891
    file_count: 23
    latest_mtime: 2026-04-05T00:51:44+00:00
    lifecycle_state: active
    freshness: current
    ingested_at: 2026-04-07T12:15:00+00:00
    wiki_pages: [wiki/components/code-trading-engine.md]
```

**Rename detection for aggregates**: if the directory moves, scan parent dirs for a directory whose `verify_aggregate` matches. Rare operation; not performance-optimized.

### 5.7 Git as Source of Truth

- The wiki root IS a git repo (initialized at bootstrap)
- Every operation that bumps `wiki_version` ALSO commits and tags
- Commit message format: `wiki-vNN: <operation> (<summary>)`
- Tag format: `wiki-vNN`
- The JSONL files are query indexes — git is the canonical history
- `.gitignore` excludes: `.wiki.lock`, `.wiki.lock.info`, `*.tmp`, `__pycache__/` (if any code)

**Recovering content** (examples):
```bash
# See wiki state at v15
cd <wiki-root> && git checkout wiki-v15

# Diff a page between v10 and v20
git diff wiki-v10 wiki-v20 -- wiki/components/trading-engine.md

# Find when a page was first created
git log --follow --diff-filter=A -- wiki/components/trading-engine.md

# Find when a source was removed
git log --all --grep="remove source"

# Restore a deleted page
git checkout wiki-v18 -- wiki/strategies/old-strategy.md
```

### 5.8 Snapshot Fallback (When Git Unavailable)

If `git` is not available on the host (rare, but possible in restricted environments), the wiki agent falls back to **periodic snapshot directories**:

- `<wiki-root>/_maintenance/snapshots/v<NN>/` — full copy of `wiki/` at version NN
- Created on every wiki_version bump (until git available)
- Storage: ~30KB per page × N pages × M snapshots — can grow fast
- The agent should warn loudly: "Git unavailable — using snapshot fallback. Storage will grow linearly. Install git for proper versioning."

---

## Part 6: Conflict Detection in Bootstrap

If bootstrap detects a pre-existing wiki at target path:

1. Check for `WIKI.md` + `_maintenance/` -> existing wiki detected
2. Report existing wiki details (name, domain, page count)
3. Ask user:
   - "Use this wiki instead?" -> switch context to existing wiki
   - "Overwrite?" -> requires explicit `--force-overwrite` flag, archives old to `<path>.archive-<timestamp>/`
   - "Pick a different path?" -> re-prompt for location
4. Never silently overwrite

---

## Part 7: Integration With Other Reference Files

- `ingest.md` reads this file's frontmatter validation rules when generating pages
- `lint.md` uses this file's enum and required-field definitions for check #1
- `query.md` uses this file's frontmatter field semantics for ranking and filtering
- Domain templates in `templates/` extend the base schema with domain-specific page types

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Silently adding fields to WIKI.md | User loses control over wiki shape, breaks reproducibility | Use Evolution Protocol (Part 4) — propose, approve, apply, log |
| Skipping schema version bump on evolution | Future migration tooling can't detect changes | Increment `schema_version` every evolution, append to Evolution Log |
| Overwriting existing wiki on bootstrap | Destroys prior work silently | Conflict detection (Part 5) — ask user, archive before overwrite |
| Generating pages without required frontmatter fields | Lint fails, citations break, enum validation fails | Use `ingest.md` generation protocol, validate before write |
| Writing new content inside WIKI.md when it exceeds 300 lines | Slim-parent convention broken, file becomes unreadable | Overflow to `_templates/` reference files, link from WIKI.md |
