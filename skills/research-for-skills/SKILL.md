---
name: research-for-skills
description: Use when a skill gap is identified during task planning, when the user asks to create or improve a skill, or when forge detects no matching skill for a domain.
---

# Research for Skills

Skill creation pipeline with dual-model review and self-learning. Thin orchestrator — delegates research to `web-research`, comparison to Codex sidecars, and testing methodology lives inline in `authoring-rules.md` (TDD enforced via `development-lifecycle`).

## When to Trigger

- Forge's skill gap check finds no matching skill
- User asks to create or improve a skill
- Existing skill flagged `needs_refresh` (see `improvement-loop.md`)
- Plugin version change detected (via local plugin tracker, if maintained)

## Process (10 Steps)

### Step 1: Scope

If invoked from gap-detection (pre-filled scope in prompt):
- Skip scoping questions -- domain, criticality, and context already provided
- Proceed to Step 2 with pre-filled scope

**Ask (one at a time):**
1. What domain/topic? New skill, refresh, or repair?
2. Universal expert-grade or project-specific? (usually universal)
3. Mandatory subtopics?

### Step 2: Resolve Active Corpus

Identify all existing skills that may overlap. See `comparison-engine.md` for full methodology.

```bash
# Custom skills
ls ~/.claude/skills/*/SKILL.md

# Plugin skills — resolve from installed_plugins.json, NOT raw cache
cat ~/.claude/plugins/installed_plugins.json | grep installPath
```

**Critical:** Never scan `~/.claude/plugins/cache/` directly — stale versions will double-count.

### Step 3: Build/Refresh Inventory

Extract normalized records for matched skills. Cache to `~/.claude/skills/_meta/inventory.json`. See `comparison-engine.md` for record format and refresh rules.

### Step 4: Generate Comparison Shortlist

Shortlist 3-8 relevant skills (direct matches, adjacent domains, exemplars). Dispatch Codex `skill_comparator` sidecar in parallel:

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
codex exec --ephemeral -s read-only \
  -o "$CODEX_WORK/skill-comparison.md" \
  "Read these skill files [PATHS] and compare: coverage, patterns, gaps, quality for [DOMAIN]"
```

### Step 5: Research

Delegate to `web-research` — do NOT duplicate research methodology here.

| Task | web-research Level |
|------|-------------------|
| New skill (broad domain) | **LONG** — full parallel research + challenger |
| New skill (focused topic) | **MEDIUM** — 1-2 agents, focused |
| Refresh (outdated sections) | **MEDIUM** — targeted |
| Quick version check | **SHORT** — verify current data |

Optional: dispatch Codex `docs_verifier` sidecar for API/version claims:


**Gemini MCP for freshness checks:** Use `mcp__gemini-cli__ask-gemini` with Google Search grounding to verify latest versions, deprecation status, and current best practices. Particularly useful for fast-moving domains where cached knowledge may be stale. Complements Codex verification — run both in parallel when accuracy is critical.
```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
codex exec --ephemeral -s read-only \
  -o "$CODEX_WORK/docs-verify.md" \
  "Verify these claims are current as of 2026: [SPECIFIC CLAIMS]"
```

### Step 6: Synthesize

Merge comparison + research findings. Extract:
- Best patterns from existing skills to incorporate
- Gaps no existing skill covers
- Decision: create new / update existing / skip

Check `_meta/creation-log.jsonl` for:
- Effective patterns in similar domains to incorporate
- Previous creation attempts for this domain (avoid repeating known failures)
- Failure deltas that indicate what went wrong last time

Check `_meta/gap-events.jsonl` for previous attempts at this domain:
- If domain was deferred 3+ times in 30 days: this is a proven need, prioritize creation
- If domain was created before but marked unhelpful: investigate why before recreating

### Step 7: Draft Skill

Write using rules in `authoring-rules.md`. Key gates:

- Description starts "Use when..." — triggers only, NO workflow summary
- Anti-patterns table mandatory
- Word count: <500 frequent, <1200 standard
- Cross-model compatible language
- Specific data with sources, no vendor marketing as fact

### Step 8: Review Gates

**Local checks:** frontmatter, word count, description format, anti-patterns table, CSO keywords.

**Codex `skill_challenger`** (mandatory for new skills, optional for minor updates):

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
codex exec --ephemeral -s read-only \
  -o "$CODEX_WORK/skill-challenger.md" \
  "Review this skill draft at [PATH]. Check: missing triggers, vague sections,
   outdated claims, structural bloat, CSO quality. Output: deploy / revise / rewrite."
```

Integrate feedback. If "revise": fix and re-run. If "rewrite": return to Step 7.

### Step 9: Deploy

1. **Backup before deploy**: If skill directory already exists, `cp SKILL.md SKILL.md.bak`
2. Save skill to `~/.claude/skills/<name>/SKILL.md`
3. If skill proves defective after deploy: `mv SKILL.md.bak SKILL.md` to restore
4. Log backup action in `creation-log.jsonl`
5. Verify no naming conflicts
6. **Symlink to Codex** (mandatory unless in skip list):
   ```bash
   ln -sfn "$HOME/.claude/skills/$SKILL_NAME" "$HOME/.codex/skills/$SKILL_NAME"
   ```
4. Verify skill appears in available skills list

**Skip list** (Claude-specific — do NOT symlink):
agent-teams, codex-orchestration, forge, nano-banana, vertex-banana, research-for-skills, challenger

### Step 10: Log & Learn

Append to `~/.claude/skills/_meta/creation-log.jsonl`:
```jsonl
{"date":"YYYY-MM-DD","skill":"name","action":"created|updated|refreshed","research_level":"SHORT|MEDIUM|LONG","sources":["..."],"comparison_skills":["..."],"codex_reviews":["skill_comparator","skill_challenger"],"patterns_used":["..."]}
```

See `improvement-loop.md` for failure tracking and refresh thresholds.

## Skill Update Flow

1. Read current skill + all failure deltas from `_meta/failure-deltas.jsonl`
2. Run comparison engine against current plugin versions
3. Run targeted `web-research` for specific gaps
4. Update skill, addressing each promoted eval case
5. Verify Codex symlink: `test -L ~/.codex/skills/<name> || ln -sfn ...`
6. Log update to `creation-log.jsonl`

## Integration with Forge

When forge detects a skill gap:
```
"This task involves [DOMAIN]. No matching skill found.
  A) Research and create a skill first (runs this flow)
  B) Proceed without specialized skill
  C) Skip — general knowledge is enough"
```

If A: run Steps 1-10, return to forge with new skill available.

## Cross-Model Compatibility

See `authoring-rules.md` for full guidelines. Key rule: use tool-agnostic language ("Read the file" not "Use the Read tool").

## Cross-tool portability

When authoring a skill that must work across multiple AI CLIs (Claude Code, Gemini CLI, Codex CLI, GitHub Copilot CLI), read `cross-tool-portability/cross-tool-portability.md` first. It contains strict rules for frontmatter (only `name + description`), naming (`^[a-z0-9-]+$`, ≤64 chars), body length (<500 lines), install symlink pattern, AGENTS.md canonicalisation, hooks portability, and the 5 most common breaking mistakes.

Validate any new cross-tool skill against `cross-tool-portability/scripts/verify-skill-portability.sh` before publishing:

```bash
bash ~/.claude/skills/research-for-skills/cross-tool-portability/scripts/verify-skill-portability.sh \
  ~/.claude/skills/<name>/SKILL.md
```

Exit 0 = portable. Non-zero = fix the reported issue.

The sub-skill files:

| File | When to read |
|---|---|
| `cross-tool-portability.md` | Top-level rulebook — read first |
| `frontmatter-rules.md` | Authoring SKILL.md frontmatter |
| `install-matrix.md` | Setting up symlinks across `~/.claude/`, `~/.gemini/`, `~/.codex/` |
| `agents-md-canonical.md` | Designing AGENTS.md / CLAUDE.md / GEMINI.md content |
| `hooks-portability.md` | Authoring hooks that must work in both Claude and Gemini |
| `headless-invocation.md` | Translating `claude -p` patterns to `gemini -p` and `copilot -p` |
| `verification-first-boot.md` | Validating a new skill on first install |
| `common-mistakes.md` | The five most common breaking mistakes |
| `challenger-concerns.md` | Hook re-entrancy, name collisions, multi-user auth |

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Duplicate web-research methodology | Invoke `web-research` — don't reinvent |
| Create skills without research | Generic advice is harmful; agents follow literally |
| Skip comparison engine | May create inferior duplicate of existing plugin skill |
| Scan raw plugin cache | Stale versions cause double-counting; use `installed_plugins.json` |
| Skip Codex challenger for new skills | Single-model blind spots produce weaker skills |
| Write prose self-learning notes | Use structured JSONL with failure taxonomy |
| Deploy without testing | Apply `development-lifecycle` TDD methodology and the testing patterns in `authoring-rules.md` |
| Summarize workflow in description | Causes Claude to shortcut and skip skill body |
| Write skills >1200 words inline | Use separate reference files for heavy content |
