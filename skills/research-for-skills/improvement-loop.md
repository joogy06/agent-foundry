# Improvement Loop

Reference for `research-for-skills` Step 10 and ongoing skill maintenance. Describes how to track skill effectiveness, categorize failures, and promote learnings into actionable improvements.

## Principle

Self-learning is eval-set growth plus a refresh queue — not a prose journal. Every failure record must be structured, categorized, and actionable.

## Failure Taxonomy

Use these fixed categories for ALL failure reports. Structured categories enable analysis across skills.

| Category | Description | Example |
|----------|-------------|---------|
| `trigger_miss` | Skill not found when it should have been | User asked about Docker networking, `docker-networking` skill not suggested |
| `wrong_scope` | Skill found but wrong for the situation | `docker-admin` triggered for a Podman-only task |
| `stale_fact` | Information in skill is outdated | Skill references Docker Compose v1 syntax, v2 is current |
| `missing_antipattern` | Common mistake not covered | Skill doesn't warn about running containers as root |
| `bad_example` | Example is misleading, broken, or outdated | Code sample uses deprecated API |
| `tool_specific_wording` | Cross-model incompatible language | "Use the Read tool" instead of "Read the file" |
| `too_long_skipped` | Agent skipped skill due to excessive length | 2000-word skill ignored in favor of general knowledge |
| `conflicting_guidance` | Contradicts another skill or CLAUDE.md | Skill says X, another skill says not-X |

## When to Log

**On creation/update (Step 10):**
```jsonl
{"date":"2026-03-26","skill":"docker-security","action":"created","research_level":"LONG","sources":["Docker docs","CIS Benchmark"],"comparison_skills":["docker-admin","docker-fundamentals"],"decision":"new","codex_reviews":["skill_challenger"]}
```

**On failure/inadequacy (during any session):**
```jsonl
{"date":"2026-03-28","skill":"docker-security","failure_type":"missing_antipattern","scenario":"user deploying to production","observed":"agent didn't warn about --privileged flag","missing_rule":"warn against --privileged in production","fix_applied":false}
```

**On upstream change (when superpowers-tracked.md detects update):**
```jsonl
{"date":"2026-04-01","event":"plugin_update","plugin":"superpowers","old_version":"5.0.6","new_version":"5.1.0","impacted_skills":["writing-skills"],"comparison_baseline_changed":true}
```

## Storage

All files in `~/.claude/skills/_meta/`:

| File | Format | Purpose |
|------|--------|---------|
| `creation-log.jsonl` | Append-only JSONL | Every skill creation/update event |
| `failure-deltas.jsonl` | Append-only JSONL | Every failure report |
| `inventory.json` | JSON (overwritten on refresh) | Cached skill inventory |
| `evals/<skill>.jsonl` | JSONL per skill | Promoted eval cases |

## Promotion Rules

Do NOT update a skill from a single anecdote. Promote a failure delta into a per-skill eval case when:

- It caused a **real failure** during actual use (not hypothetical)
- It **repeats** (2+ occurrences of same failure type)
- It exposes a **policy contradiction** between skills
- It points to **time-sensitive drift** (confirmed stale fact)

## Gap Event Patterns

Read `_meta/gap-events.jsonl` for ecosystem-level patterns:

- Same domain deferred 3+ times in 30 days: promote to auto-offer on next encounter
- Domain created but never invoked (30+ days): flag for review by alf
- Same caller detects same gap repeatedly: suggests the caller's routing table needs updating

### Compaction Rule

When `gap-events.jsonl` exceeds 500 lines:
- Summarize per-domain counts to `_meta/gap-summary.json`
- Archive raw entries older than 180 days to `_meta/archive/`

---

## Refresh Thresholds

Mark a skill as `needs_refresh` when:

| Condition | Threshold |
|-----------|-----------|
| Distinct deltas in same taxonomy bucket | 2+ |
| High-severity `stale_fact` confirmed | 1 |
| Upstream plugin introduces better pattern | 1 (confirmed by comparison engine) |
| Skill age without refresh | 90 days (check, don't auto-refresh) |

## Refresh Process

When a skill is flagged `needs_refresh`:

1. Read all failure deltas for the skill
2. Read promoted eval cases in `evals/<skill>.jsonl`
3. Run comparison engine against current plugin versions
4. Run targeted `web-research` for the specific gaps
5. Update the skill, addressing each eval case
6. Re-run eval cases to verify fixes
7. Log the update in `creation-log.jsonl`
8. Clear addressed failure deltas (archive, don't delete)

## Effective Patterns Registry

Track what works across skill creation. Append to `creation-log.jsonl` with a `patterns_used` field:

| Pattern | Best For | Why It Works |
|---------|----------|-------------|
| Decision framework tables | Infrastructure, config | Agents need clear routing, not prose |
| Anti-pattern tables with "Why" column | All domains | Prevents mistakes directly |
| Version-pinned commands | Infrastructure | Generic commands break across versions |
| Quick-reference tables | API/tool skills | Scannable during implementation |
| HARD-RULE tags | Discipline skills | Prevents rationalization |

When creating a new skill, check this registry for patterns that worked in similar domains.

## Anti-Patterns for Self-Learning

| Don't | Why |
|-------|-----|
| Write prose notes ("skill was inadequate") | Unstructured, unanalyzable, decays into noise |
| Auto-update skills from single failure | One anecdote != systematic issue |
| Log without taxonomy category | Can't aggregate or detect patterns |
| Let failure-deltas.jsonl grow unbounded | Archive entries older than 180 days |
| Skip logging when a skill works well | Positive signal is valuable for pattern registry |
