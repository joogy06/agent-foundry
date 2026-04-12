# Skill Comparison Engine

Reference for `research-for-skills` Steps 2-4. Describes how to resolve the active skill corpus, build an inventory, and generate comparison shortlists.

## Source Resolution

Resolve active skills from TWO authoritative sources only:

**Custom skills:**
```bash
ls ~/.claude/skills/*/SKILL.md
```

**Plugin skills — resolve from installed_plugins.json, NOT raw cache:**
```bash
# Read active install paths
cat ~/.claude/plugins/installed_plugins.json | grep installPath
```

Why not raw cache? The cache directory contains ALL versions ever downloaded (e.g., `superpowers/5.0.5` AND `superpowers/5.0.6`). Only the version referenced in `installed_plugins.json` is active. Scanning the cache directly double-counts stale versions.

## Inventory Record

Extract a normalized record for each skill:

| Field | Source |
|-------|--------|
| name | YAML frontmatter `name` |
| source | `custom` or `plugin:<marketplace>:<plugin>:<version>` |
| install_path | Full path to SKILL.md |
| description | YAML frontmatter `description` |
| word_count | `wc -w SKILL.md` |
| has_use_when | Description starts with "Use when" |
| has_antipatterns | Contains "Anti-Pattern" or "Don't \| Why" section |
| supporting_files | Other files in skill directory |
| key_terms | Top domain keywords from description + headings |
| compatibility | `shared` (symlinked to Codex), `claude-only`, or `codex-only` |

Cache inventory to `~/.claude/skills/_meta/inventory.json`. Refresh when:
- A new skill is created or updated
- `installed_plugins.json` changes (plugin update)
- Inventory file is older than 7 days

## Shortlisting

Do NOT compare against the full corpus. Generate a shortlist of 3-8 skills:

**Include:**
- **Direct matches** — skills whose key_terms overlap with the target domain
- **Adjacent domains** — skills in related areas (e.g., `docker-networking` when creating `docker-security`)
- **Authoring exemplars** — well-structured skills to emulate (high word efficiency, good CSO, clear anti-patterns)
- **Anti-examples** — poorly structured skills to avoid repeating mistakes

**Search method:**
```bash
# Phase 1: keyword grep (fast)
grep -rl "${TOPIC_KEYWORDS}" ~/.claude/skills/*/SKILL.md

# Phase 2: description semantic match (Codex sidecar)
# Send shortlisted skill descriptions to Codex skill_comparator
```

## Codex skill_comparator

Dispatch Codex to independently analyze shortlisted skills:

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
cat > "$CODEX_WORK/brief-skill-comparison.md" << 'BRIEF'
# Skill Comparison Brief

## Target skill domain
[DOMAIN DESCRIPTION]

## Skills to compare (read these files)
[LIST OF SKILL PATHS]

## Analyze each skill for:
1. Coverage: what topics does it address?
2. Quality: clear triggers, scannable structure, anti-patterns?
3. Reusability: universal vs project-specific? Cross-model wording?
4. Gaps: what's missing that the target skill should cover?

## Output format
- Direct competitors (overlap with target domain)
- Patterns to copy (structural or content patterns worth adopting)
- Patterns to avoid (mistakes to not repeat)
- Uncovered gaps (topics no existing skill covers)
- Recommended differentiation (how target skill should differ)
BRIEF

codex exec --ephemeral -s read-only \
  -o "$CODEX_WORK/skill-comparison.md" \
  "Read $CODEX_WORK/brief-skill-comparison.md and the listed skill files. Execute the comparison."
```

## Output Format

The comparison engine produces a structured output used by Step 6 (Synthesize):

```markdown
## Comparison: [TARGET DOMAIN]

### Direct Competitors
| Skill | Source | Coverage | Strengths | Gaps |
|-------|--------|----------|-----------|------|

### Patterns to Adopt
- [pattern from skill X worth incorporating]

### Patterns to Avoid
- [anti-pattern from skill Y to not repeat]

### Uncovered Gaps
- [topic no existing skill covers]

### Recommended Action
- create new / update existing / skip
- Recommended differentiation: [how to be better than existing coverage]
```

## Decision Matrix

| Situation | Action |
|-----------|--------|
| No existing skill, no plugin skill | Create new (full research) |
| No existing skill, plugin exists but generic | Create superior custom skill, extract good patterns |
| Existing custom skill, outdated | Update with targeted research |
| Existing custom skill, adequate | Skip (inform user) |
| Plugin skill better than custom | Adopt plugin patterns into custom skill |
| Multiple partial coverage | Merge best of both into enhanced custom skill |

The comparison engine collects evidence. It does NOT autonomously decide — the orchestrator (SKILL.md Step 6) makes the final call.
