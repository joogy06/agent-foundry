# Gap Detection Protocol

Canonical protocol for detecting missing skills and triggering creation. Referenced by forge, bob, team-manager, and any parent skill with sub-skill routing.

---

## 5-Step Protocol

### Step 1: IDENTIFY

What domain/sub-skill does the caller need?

- Parse user request or task requirements
- Match against routing table (if parent skill has one)
- Generate a **gap_key**: `<caller>:<domain>` (e.g., `performance:frontend`, `forge:kubernetes-security`)

### Step 2: SCAN

Check if the skill exists — search ALL locations before declaring a gap:

1. Check `~/.claude/skills/<name>/SKILL.md` (standalone skill)
2. Check `~/.claude/skills/<parent>/<name>.md` (reference file inside parent)
3. Check `~/.codex/skills/<name>/` (Codex-side skills)
4. Check plugin skills list (from system prompt)
5. If `_meta/skill-families.json` exists: cross-reference expected children
6. **Normalize name**: try kebab-case, with/without parent prefix (e.g., `performance-frontend` AND `frontend`)

Only declare a gap if ALL locations return nothing.

### Step 3: CLASSIFY

If not found, classify criticality using this **policy matrix** (not caller gut feeling alone):

| Dimension | Score +1 if... |
|-----------|---------------|
| **Task-blocking** | Task cannot produce correct output without this domain knowledge |
| **Correctness risk** | Wrong approach without skill could break things or mislead user |
| **Reuse frequency** | This domain is likely needed again in future sessions |
| **Fallback confidence** | General knowledge is insufficient (novel/niche domain) |

| Total Score | Criticality |
|-------------|-------------|
| 3-4 | CRITICAL |
| 2 | HELPFUL |
| 0-1 | NICE-TO-HAVE |

Caller provides initial classification + reasoning. The matrix validates it. If caller says CRITICAL but only scores 1, downgrade to HELPFUL and note the override.

### Step 4: ACT

**Before acting, check for duplicates:**

```
Check gap-events.jsonl for existing entries with same gap_key:
  IF gap_key exists AND state == 'declined':
    Suppress offer. Do NOT re-offer within same session.
    Increment count. Proceed with general knowledge.
  IF gap_key exists AND state == 'snoozed' AND snooze_until > now:
    Suppress offer. Proceed with general knowledge.
  IF gap_key exists AND count >= 3 AND state != 'resolved':
    Auto-escalate: "This gap has been detected [N] times. Recommend creating this skill."
  IF gap_key is new OR state == 'open':
    Proceed with normal flow below.
```

**Based on criticality:**

- **ALL**: log to `_meta/gap-events.jsonl` (with dedup — update existing entry if gap_key matches)
- **CRITICAL**:
  1. Proceed with general knowledge immediately
  2. Show **inline notice** in the current response (not deferred):
     > "[Note: No [domain] skill exists. Proceeding with general knowledge. I'll offer to create one when this task completes.]"
  3. At task completion, in the **same response** as the final output, add:
     > "Gap detected: [domain]. Want me to create a skill for this? (y/n/snooze 7d)"
  4. If user says yes → invoke research-for-skills with pre-filled scope
  5. If user says no → update gap state to `declined`
  6. If user says snooze → update gap state to `snoozed`, set `snooze_until`
  7. If session ends without response → update gap state to `offered` (not resolved)

- **HELPFUL**: proceed with general knowledge, log only. No offer.
- **NICE-TO-HAVE**: log only. No offer.

<HARD-RULE>
NEVER block the active task to create a skill. Log, proceed, offer at task completion in the SAME response.
</HARD-RULE>

<HARD-RULE>
NEVER re-offer a gap the user has declined in the same session. Respect the decline.
</HARD-RULE>

### Step 5: LOG

Append to or update `~/.claude/skills/_meta/gap-events.jsonl`:

```jsonl
{"gap_key":"performance:frontend","date":"2026-03-31","caller":"performance","domain":"frontend","skill_name":"performance-frontend","gap_type":"missing_sub_skill","criticality":"helpful","score":2,"decision":"deferred","state":"open","count":1,"first_seen":"2026-03-31","last_seen":"2026-03-31","offer_shown":false,"user_response":null,"session_id":"abc123","context":"user asked about page speed but frontend sub-skill doesn't exist yet"}
```

**Required fields:**

| Field | Purpose |
|-------|---------|
| `gap_key` | Dedup key: `<caller>:<domain>` |
| `date` | Current date |
| `caller` | Skill/agent that detected the gap |
| `domain` | Missing capability area |
| `skill_name` | Expected skill name if known |
| `gap_type` | `missing_skill`, `missing_sub_skill`, `missing_reference` |
| `criticality` | `critical`, `helpful`, `nice-to-have` |
| `score` | Policy matrix total (0-4) |
| `decision` | `deferred`, `offered`, `created`, `declined`, `snoozed` |
| `state` | `open`, `offered`, `declined`, `snoozed`, `auto-create-candidate`, `resolved` |
| `count` | Times this gap_key has been detected |
| `first_seen` | First detection date |
| `last_seen` | Most recent detection date |
| `offer_shown` | Was the creation offer shown to user? |
| `user_response` | `yes`, `no`, `snooze`, `null` (no response / session ended) |
| `session_id` | For dedup across agents in same session |
| `context` | Brief description of why the gap was detected |

**On duplicate detection:** If `gap_key` already exists in the file, update the existing entry: increment `count`, update `last_seen`, update `state` if changed. Do NOT append a new line for the same gap_key — this prevents log bloat.

---

## Gap State Machine

```
  open → offered → declined (suppressed for session)
                 → created (resolved)
                 → snoozed (suppressed until snooze_until)
                 → null response (stays offered, re-offer next session)

  open → auto-create-candidate (count >= 3, auto-escalate)
       → resolved (skill exists now)
```

---

## Pre-Session Proactive Scan

If `_meta/skill-families.json` exists, check all expected sub-skills on session start.

**This is the ONLY context where immediate creation is allowed** — no task is running yet.

```
For each family in skill-families.json:
  For each expected child:
    Check if child exists (SCAN step)
    If missing:
      Log gap event
      Check gap history: is this high-confidence + broadly reusable?
        YES → offer immediate creation: "Missing [skill]. Create now before we start?"
        NO → note and defer: "FYI: [skill] is missing. Will proceed with general knowledge."
```

**Immediate creation criteria (pre-session only):**
- Gap has been detected 3+ times previously (count >= 3)
- Domain is broadly reusable (not project-specific)
- General knowledge fallback is weak for this domain

---

## Integration Notes

- **research-for-skills**: if invoked from gap-detection, scope is pre-filled — skip scoping questions
- **improvement-loop**: reads gap-events.jsonl for pattern detection:
  - 3+ detections, no creation → `auto-create-candidate`
  - Created but never invoked (30+ days) → flag for alf review
  - Same caller, same gap repeatedly → caller's routing table needs updating
- **Parent skills**: add a 3-5 line gap-check preamble before routing to child skills
- **Concurrent agents**: use `gap_key` + `session_id` to deduplicate. If another agent already logged the same gap_key in this session, skip the offer (the first agent owns it).

---

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Block a task to create a skill | Violates HARD-RULE. Log, proceed, offer at completion. |
| Skip logging for NICE-TO-HAVE gaps | Data loss. All gaps get logged for pattern detection. |
| Re-offer a declined gap in the same session | Respect user's decision. Suppress until next session. |
| Classify criticality on gut feeling alone | Use the policy matrix. Score 0-4, map to criticality. |
| Append duplicate entries for same gap_key | Update existing entry. Increment count. Don't bloat the log. |
| Declare a gap after checking only one location | Search all 6 scan locations before declaring missing. |
| Defer the offer to "after task" and hope | Show inline notice NOW, offer at task completion in SAME response. |
| Create skills during active tasks | Even CRITICAL gaps proceed with general knowledge first. Pre-session is the only creation window. |
