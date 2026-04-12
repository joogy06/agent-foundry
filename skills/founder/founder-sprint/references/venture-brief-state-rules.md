# Venture-Brief State Rules

Which fields `founder-sprint` reads and writes per stage. Schema version check and migration
notes for v1 -> v2.

---

## Schema Version

Sprint requires `schema_version: 2`. On encountering version 1:

```
ERROR: venture-brief schema_version is 1; sprint requires 2.
Phase 1 briefs are forward-compatible. To upgrade:
1. Add sprint_state, experiments (Phase 2 format), business_model, forge_brief (Phase 2 format)
   fields with null/empty defaults
2. Set schema_version: 2
3. Phase 1 forge_brief stub fields (constraints, ruled_out_approaches) are superseded by Phase 2
   fields (success_criteria, non_goals, complexity_hint, open_questions)

Sprint will not silently migrate. Run the upgrade explicitly.
```

### Migration: v1 -> v2

Phase 1 briefs (v1) are forward-compatible. New fields default to null/empty:

```yaml
# Add these fields for v2:
schema_version: 2             # was: 1

sprint_state:
  stage: null                 # will be set on first sprint entry
  stage_completed_at: {}
  outcome: null
  abort_reason: null

experiments: []               # Phase 2 format (replaces Phase 1 stub)

business_model: null          # populated by founder-business-model

forge_brief:                  # Phase 2 format supersedes Phase 1
  problem: null               # was: problem (same field, carries over)
  solution: null              # new
  success_criteria: []        # supersedes Phase 1 constraints
  non_goals: []               # supersedes Phase 1 ruled_out_approaches
  complexity_hint: null        # new
  open_questions: []           # new

forge_handoff_ready: false    # same as v1
handoff_at: null              # new
interview_count: 0            # new
pivots: []                    # new
```

Phase 1 field mapping:
- `forge_brief.constraints` -> superseded by `forge_brief.success_criteria` (different semantics)
- `forge_brief.ruled_out_approaches` -> superseded by `forge_brief.non_goals` (different semantics)
- Sprint should ignore v1 field names if present and use only v2 names

---

## Field Access by Stage

### DIAGNOSE

| Action | Fields |
|---|---|
| Read | `ideas_considered[]`, `assumptions[]`, `intake` |
| Write | `sprint_state.stage`, `sprint_state.stage_completed_at.diagnose`, `current_phase: sprint` |
| Validate | ideas_considered has >= 3 entries with data_sources, 1 selected, >= 3 assumptions, >= 3 kill criteria |

### EVIDENCE

| Action | Fields |
|---|---|
| Read | `assumptions[]`, `experiments[]`, `interview_count` |
| Write | `sprint_state.stage`, `sprint_state.stage_completed_at.evidence`, `interview_count` |
| Validate | top-3 assumptions tested, >= 1 interview, no unresolved falsified viability assumptions |

### DECISION

| Action | Fields |
|---|---|
| Read | `business_model`, `forge_brief` |
| Write | `sprint_state.stage`, `sprint_state.stage_completed_at.decision`, `business_model`, `forge_brief` |
| Validate | price set, CM computed, decision rule stated, verdict go/conditional, forge_brief populated |

### HANDOFF

| Action | Fields |
|---|---|
| Read | `sprint_state.stage_completed_at`, `forge_brief` |
| Write | `sprint_state.stage`, `sprint_state.stage_completed_at.handoff`, `forge_handoff_ready`, `handoff_at` |
| Validate | all 3 prior stages completed, forge_brief complete, user confirmation |

### ABORT

| Action | Fields |
|---|---|
| Read | current state |
| Write | `sprint_state.stage: aborted`, `sprint_state.outcome`, `sprint_state.abort_reason` |

### RESET

| Action | Fields |
|---|---|
| Read | current state, target stage |
| Write | `sprint_state.stage: <target>`, clear later `stage_completed_at` entries, add `pivots[]` entry |

---

## Write Discipline

Sprint follows the same write rules as all founder family skills (HR-7):

1. Update `updated: <now>` on every write
2. Update `last_subskill: founder-sprint`
3. Never delete existing content (append-only for content fields)
4. Atomic write via tmp + rename
5. Re-validate after write

Sprint-specific additions:
- Sprint ONLY writes to `sprint_state`, `forge_handoff_ready`, `handoff_at`, `interview_count`,
  `pivots[]`, `current_phase`, and the timing fields
- Sprint does NOT write to `experiments[]`, `assumptions[]`, `business_model` directly — those
  are written by the subskills sprint invokes
- Sprint MAY write to `forge_brief` during the Decision stage (helping the user draft it)
