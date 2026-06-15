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


**Antigravity (agy) for freshness checks:** Use a direct `agy -p "..."` Bash call to verify latest versions, deprecation status, and current best practices. Particularly useful for fast-moving domains where cached knowledge may be stale. `agy` returns plain text on stdout (parse text, not JSON fields). Complements Codex verification — run both in parallel when accuracy is critical. See the `antigravity-cli` skill for the invocation pattern.
```bash
agy -p "Verify current as of 2026: latest stable version, deprecation status, and current best practices for [DOMAIN/LIBRARY]. List sources." < /dev/null
```
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
- **Ambiguity gate — REQUIRED for generation-type skills** (skills whose primary output is an artifact: documents, images, pages, decks, code, posts). The SKILL.md must include a short "ask before generating" gate naming the 2-4 request dimensions that change the output materially, with the instruction to ask ONE compact clarifying question when they're missing rather than silently generating a guessed version. (Pattern precedent: forge Step 3 one-at-a-time questions, career-coach "No advice without context", career-application-writer Stage-0 intake + cold-start rule. Rationale: LLMs confidently answer the version of the question they think was meant; the cheapest quality lever is resolving ambiguity before generation.)
- **FRESHNESS:v1 anchor (Evergreening v1, S041) — MANDATORY for new skills** that carry any version/date/model-ID anchor. Add an HTML-comment `<!-- FRESHNESS:v1 ... -->` block (NEVER frontmatter — works in SKILL.md AND frontmatter-less references) declaring the tool/date/model you verified against, so the evergreen rot scanner can grade the skill instead of treating it as UNANNOTATED. Validate with `python3 ~/.claude/skills/_meta/freshness.py lint <file>` (advisory). Convention spec: `docs/plans/2026-06-04-evergreening-design.md` §6.5. (Same convention applies when the superpowers `writing-skills` plugin authors a skill — the FRESHNESS block is host-agnostic.)

#### Harness-orchestration authoring gate (HO-1..HO-7, S055) — MANDATORY when a skill might fan out

A skill that wants to fan work out across agents/workflows MUST satisfy ALL of these. Full guidance + copy-paste templates: `references/harness-orchestration.md`.

- **HO-1 OPTIONAL** — orchestration is a fast path, never a dependency; the documented MAIN path completes with ZERO orchestration primitives.
- **HO-2 FEATURE-DETECTED** — capability checks via `probe.sh get capabilities.*` ONLY (never inline probing, never raw jq on inventory.json); **`capabilities.*` alone NEVER authorizes orchestration — the context conjunct (`probe.sh context == main-loop` / tool-list check) is mandatory** (session files are shared with subagents).
- **HO-3 FALLBACK-FIRST** — the portable flow is the PRIMARY instructions; the fast path is a clearly-fenced enhancement using the conditional template.
- **HO-4 CONTEXT-AWARE** — the skill states its subagent behavior: portable flow, or emit a plan ARTIFACT (data, never executable JS — S052) and halt.
- **HO-5 SCHEMA TWINS** — canonical JSON Schema in the skill's `schemas/`; the companion workflow embeds the SCHEMA-TWIN-annotated literal (G-W2); the schema is REGISTERED (`_meta/schemas/registry.v1.json`).
- **HO-6 COMPANION WORKFLOW** — ship one ONLY IF: inline-main-loop primary callers AND stable reusable fan-out (≥3 sequential stages or ≥2 parallel agents) AND deterministic stage boundaries AND schema-checkable outputs. MUST NOT when: knowledge-only skill; mid-flow user interaction (G-W4); machinery-under-worktree (G-W6); primary callers are agents. Shipping triggers G-W7 registration.
- **HO-7 HOST-NEUTRAL** — all protocol text names CAPABILITIES, not Claude-only tool names ("the agent-spawn facility (`Agent` on Claude Code; see tool-mapping for Codex/Copilot)"); every plan/report artifact is host-neutral data executable serially by any host; only workflow compilation is described as Claude-main-loop-only; the skill DESCRIPTION never names Workflow/native teams (CSO pollution on other hosts).

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
6. **Symlink to Codex** (mandatory unless the skill dir contains a `.no-codex-symlink` sentinel):
   ```bash
   if [ ! -e "$HOME/.claude/skills/$SKILL_NAME/.no-codex-symlink" ]; then
     ln -sfn "$HOME/.claude/skills/$SKILL_NAME" "$HOME/.codex/skills/$SKILL_NAME"
   fi
   ```
7. Verify skill appears in available skills list

**Symlink gating rule** (single source of truth — no hardcoded list to maintain):
symlink every new skill into `~/.codex/skills/` UNLESS the skill dir contains a `.no-codex-symlink` sentinel file (affordance-advisor precedent — host-gated skills that must not load on other CLIs). To exempt a skill, drop the sentinel: `touch ~/.claude/skills/<name>/.no-codex-symlink`.

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
5. Verify Codex symlink (skip if `.no-codex-symlink` sentinel present): `test -e ~/.claude/skills/<name>/.no-codex-symlink || test -L ~/.codex/skills/<name> || ln -sfn ...`
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

When authoring a skill that must work across multiple AI CLIs (Claude Code, Antigravity CLI (agy), Codex CLI, GitHub Copilot CLI), read `cross-tool-portability/cross-tool-portability.md` first. It contains strict rules for frontmatter (only `name + description`), naming (`^[a-z0-9-]+$`, ≤64 chars), body length (<500 lines), install symlink pattern, AGENTS.md canonicalisation, hooks portability, and the 5 most common breaking mistakes.

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
| `install-matrix.md` | Setting up symlinks across `~/.claude/`, `~/.codex/` (and agy plugin import) |
| `agents-md-canonical.md` | Designing AGENTS.md / CLAUDE.md content |
| `hooks-portability.md` | Authoring hooks (Claude-native; agy equivalent unverified) |
| `headless-invocation.md` | Translating `claude -p` patterns to `agy -p` and `copilot -p` |
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
| Make a skill depend on Workflow/native teams | Breaks Codex/Copilot and all subagent contexts | HO gate (HO-1..HO-7): optional + feature-detected + fallback-first + host-neutral |
