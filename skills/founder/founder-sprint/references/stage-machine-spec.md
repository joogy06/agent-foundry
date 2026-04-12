# Stage Machine Specification

Complete state transition diagram for `founder-sprint`. Defines allowed transitions,
forbidden paths, and edge cases.

---

## States

```
DIAGNOSE --> EVIDENCE --> DECISION --> HANDOFF
    |            |            |           |
    v            v            v           v
 ABORTED     ABORTED      ABORTED     PAUSED
```

Additionally, any completed stage can RESET back to itself or an earlier stage.

---

## Allowed Transitions

| From | To | Trigger | Gate required? |
|---|---|---|---|
| (none) | DIAGNOSE | Sprint initialized, no prior state | No |
| DIAGNOSE | EVIDENCE | All diagnose gate criteria pass | Yes |
| DIAGNOSE | ABORTED | All ideas below kill threshold | No (abort is always allowed) |
| EVIDENCE | DECISION | All evidence gate criteria pass | Yes |
| EVIDENCE | ABORTED | Viability assumption falsified, user refuses pivot | No |
| EVIDENCE | DIAGNOSE | User requests reset (pivot to new idea) | No (reset clears later gates) |
| DECISION | HANDOFF | All decision gate criteria pass | Yes |
| DECISION | ABORTED | Calculator RED, user declines to adjust | No |
| DECISION | EVIDENCE | User wants more validation data | No (reset) |
| DECISION | DIAGNOSE | User wants to rethink the idea entirely | No (reset) |
| HANDOFF | (forge) | All handoff gate criteria pass + user confirms | Yes |
| HANDOFF | PAUSED | User changes mind before confirming | No |
| HANDOFF | DECISION | User wants to revise business model | No (reset) |
| PAUSED | HANDOFF | User returns and wants to proceed | No (re-check gates) |
| ABORTED | DIAGNOSE | User starts fresh with new ideas | No (new sprint) |

---

## Forbidden Transitions

| From | To | Why |
|---|---|---|
| DIAGNOSE | DECISION | Skips evidence — no validation performed |
| DIAGNOSE | HANDOFF | Skips 2 stages — no validation or business model |
| EVIDENCE | HANDOFF | Skips decision — no business model evaluation |
| Any | Any (auto-multi-stage) | Sprint advances one stage at a time, never auto-chains |

---

## Reset Behavior

When resetting to an earlier stage:

1. Clear `stage_completed_at` for the reset stage and all later stages
2. Do NOT delete any data (experiments, evidence, business_model, etc.)
3. Record a `pivots[]` entry:
   ```yaml
   pivots:
     - from: <current_stage>
       to: <target_stage>
       reason: <user-stated reason>
       timestamp: <now>
   ```
4. Set `sprint_state.stage: <target_stage>`
5. Re-evaluate gate criteria for the target stage on next entry

---

## Edge Cases

### Sprint resumed after long gap

Read venture-brief fresh. Do not assume prior state is still valid. Check all gate criteria
from scratch because evidence may have become stale or new experiments may have been run
outside of sprint context.

### Multiple aborts

Allowed. Each abort is recorded with its own outcome and reason. The user can restart from
DIAGNOSE after any abort. Historical aborts remain in the venture-brief for context.

### Subskill invoked outside of sprint

Users can invoke `founder-validation` or `founder-business-model` directly without going
through sprint. Sprint detects this on next entry by checking venture-brief state. If
evidence or business_model data has appeared since last sprint run, sprint acknowledges it
and checks gates with the new data.

### Concurrent sprint on same brief

Not supported. Sprint reads and writes the same venture-brief. If two sprint sessions run
concurrently, the last writer wins. Sprint does not implement locking.
