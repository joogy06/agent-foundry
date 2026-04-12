# Venture Brief Schema (`.founder/venture-brief.yaml`)

The canonical venture state file for the founder family. Persisted at project root by default
(`<cwd>/.founder/venture-brief.yaml`). All subskills read it on entry, write on exit (HR-7).

Schema version: `2` (Phase 2)

**Migration from v1:** Phase 1 briefs (v1) are forward-compatible. New fields default to
null/empty. Phase 1 `forge_brief` stub fields (`constraints`, `ruled_out_approaches`) are
superseded by Phase 2 fields (`success_criteria`, `non_goals`, `complexity_hint`,
`open_questions`). Sprint should ignore v1 field names if present and use only v2 names.

---

## File location

Default: `<cwd>/.founder/venture-brief.yaml`

Alternatives (explicit flag):
- `~/.founder/venture-brief.yaml` — cross-project single venture
- `ventures/<slug>/.founder/venture-brief.yaml` — per-venture under a `ventures/` tree

The skill family defaults to project-root. The user can override at intake.

---

## Schema

```yaml
# -- Required header --
venture_id: uuid               # generated at first intake
schema_version: 2              # v2 = Phase 2 (validation, business-model, sprint)
created: timestamp             # ISO 8601 UTC
updated: timestamp             # ISO 8601 UTC (every write)

# -- Intake (required before any routing, HR-8) --
intake:
  biz_type: enum               # software | service | marketplace | hardware | deep-tech |
                               # physical-retail | other
  stage: enum                  # pre-idea | idea-forming | validating | post-validation |
                               # building | scaling
  motion: enum                 # B2B | B2C | B2B2C | creator | community | gov-regulated
  geography: string            # ISO country code(s), comma-separated
  runway: enum                 # solo-bootstrap | small-team | funded | enterprise-spinoff
  intent: enum                 # ideation | validation | business-model | gtm | unknown
  niche: string                # "small accounting firms in UK" — NOT "accountants"
  user_assets:                 # populated during full intake
    skills: list[string]
    networks: list[string]
    distribution: list[string]
    unique_access: list[string]
  stated_constraints: list[string]  # "no VC money", "solo for first 6 months", etc.

# -- Journey state --
current_phase: enum            # ideation | validation | business-model | gtm | sprint |
                               # post-launch
last_subskill: string          # which subskill wrote most recently
forge_handoff_ready: bool      # set true when ready to hand to forge (default false)

# -- Content (versioned, append-only within fields) --
ideas_considered:
  - id: uuid
    content: string            # 1-3 sentence idea description
    source_team: string        # from adversarial brainstorm: "problem-first" | "asset-first" |
                               # "trend-first" | "contrarian" | "hybrid(A+B)"
    generated_at: timestamp
    status: enum               # candidate | validated | killed | shipped | paused
    kill_criteria: list[string]  # min 2 (HR-4)
    first_experiment: string   # (HR-4)
    attack_history:            # from adversarial brainstorm cross-fire
      - from_team: string
        severity: enum         # critical | moderate | minor
        issue: string
        fix_proposed: string
    data_sources: list[string] # reddit:<sub>/<post_id>, gdelt:<event_id>, user_asset:<key>
                               # (HR-5 — must have ≥1)
    confidence: enum           # high | medium | low | speculative
    revisions:                 # from adversarial brainstorm refine round
      - round: int
        before: string
        after: string
        critique_absorbed: list[string]
        critique_rejected: list[string]

assumptions:                   # Phase 2 — populated by founder-validation
  - id: uuid
    claim: string
    confidence: enum           # high | medium | low | speculative
    evidence: list[string]
    disconfirmers: list[string]
    test_designed: bool
    test_ref: string           # pointer to test in `experiments` below

experiments:                   # Phase 2 — populated by founder-validation
  - id: uuid
    hypothesis: string
    method: string             # "Mom Test interview", "landing page split test", etc.
    owner: string              # user or "skill:browser-mcp" or similar
    started_at: timestamp
    deadline: timestamp
    status: enum               # planned | running | completed | abandoned
    result: string             # populated on completion
    learning: string           # populated on completion

decisions:
  - id: uuid
    made_at: timestamp
    decision: string
    reasoning: string
    reversible: bool
    related_idea_ids: list[uuid]

risks:
  - id: uuid
    noted_at: timestamp
    risk: string
    severity: enum             # critical | moderate | minor
    mitigation: string
    owner: string

open_questions:
  - id: uuid
    noted_at: timestamp
    question: string
    blocks: list[string]       # what phase / subskill is blocked by this

# -- Forge handoff --
forge_brief: null              # null until forge_handoff_ready: true
  # When populated (Phase 2 schema — supersedes Phase 1 stub fields):
  # problem: string              # the problem statement to pass to forge
  # solution: string             # proposed solution
  # success_criteria: list[string]  # what "built" means (supersedes v1 constraints)
  # non_goals: list[string]       # explicit scope exclusions (supersedes v1 ruled_out_approaches)
  # complexity_hint: enum         # simple | medium | complex — seeds forge Step 4
  # open_questions: list[string]  # forge asks ONLY these in Step 3

# -- Phase 2 additions (schema_version: 2) --
sprint_state: null             # populated by founder-sprint
  # stage: enum                  # diagnose | evidence | decision | handoff | aborted
  # stage_completed_at: map      # {diagnose: ts, evidence: ts, decision: ts, handoff: ts}
  # outcome: null | string       # set on abort
  # abort_reason: null | string

business_model: null           # populated by founder-business-model
  # price: {value: float, tag: enum}
  # pricing_model: enum
  # unit_econ:
  #   contribution_margin: {low, expected, high}
  #   ltv: {low, expected, high}
  #   cac: {low, expected, high}
  #   payback_months: {low, expected, high}
  #   ltv_cac_ratio: {low, expected, high}
  # decision_rule: string
  # decision_verdict: enum       # green | conditional_go | red
  # needs_more_data: list[string]
  # snapshot_path: string        # .founder/business-model-<slug>.yaml

forge_handoff_ready: false
handoff_at: null | timestamp
interview_count: 0             # incremented by founder-validation
pivots: []                     # list[{from, to, reason, timestamp}]
```

---

## Validation rules

On every load, the reader MUST:

1. **Parse as YAML.** Fail cleanly on syntax error — do not try to auto-fix.
2. **Verify schema_version matches the expected version** (currently `1`). On mismatch:
   - Emit `ERROR: venture-brief schema version X; expected 1`
   - REFUSE to proceed (HR-7) — do not silently migrate
3. **Verify required keys present:** `venture_id`, `schema_version`, `created`, `updated`, `intake`,
   `current_phase`. On missing key: emit `ERROR: missing required key <key>` and refuse.
4. **Verify enums are in valid set:**
   - `biz_type` in {software, service, marketplace, hardware, deep-tech, physical-retail, other}
   - `stage` in {pre-idea, idea-forming, validating, post-validation, building, scaling}
   - `motion` in {B2B, B2C, B2B2C, creator, community, gov-regulated}
   - `runway` in {solo-bootstrap, small-team, funded, enterprise-spinoff}
   - `current_phase` in {ideation, validation, business-model, gtm, sprint, post-launch}
   - `ideas_considered[].status` in {candidate, validated, killed, shipped, paused}
   - `ideas_considered[].confidence` in {high, medium, low, speculative}
5. **Verify idea records have min 2 kill_criteria and non-empty first_experiment** (HR-4)
6. **Verify idea records have ≥1 data_source** (HR-5)
7. **Timestamp monotonicity:** `updated >= created`

On ANY validation failure, the subskill that loaded the file MUST emit a clear error and refuse
to proceed. Do not silently heal. Do not silently migrate. The user needs to see the drift.

---

## Write rules

On every write, the writer MUST:

1. **Update `updated: <now>`**
2. **Update `last_subskill: <skill-name>`**
3. **Never delete existing content.** Content fields (`ideas_considered`, `assumptions`,
   `experiments`, `decisions`, `risks`, `open_questions`) are append-only within the session.
   Status changes (`candidate → validated → killed`) are allowed; content edits are not.
4. **Atomic write via tmp + rename:**
   ```bash
   yq -i '<updates>' .founder/venture-brief.yaml.tmp
   mv .founder/venture-brief.yaml.tmp .founder/venture-brief.yaml
   ```
5. **Re-validate after write.** If the post-write file fails validation, revert from backup.

---

## Initialization

When no file exists, the parent creates one on first intake:

```yaml
venture_id: <uuid>
schema_version: 1
created: <now>
updated: <now>
intake:
  biz_type: <from user>
  stage: <from user>
  motion: <from user>
  geography: <from user>
  runway: <from user>
  intent: <from user>
  niche: <from user>
  user_assets:
    skills: []
    networks: []
    distribution: []
    unique_access: []
  stated_constraints: []
current_phase: ideation
last_subskill: founder
forge_handoff_ready: false
ideas_considered: []
assumptions: []
experiments: []
decisions: []
risks: []
open_questions: []
forge_brief: null
```

---

## Schema migration (Phase 2)

Phase 2 will add:
- `forge_handoff_events[]` — history of handoffs with forge
- `validation_report[]` — populated by `founder-validation`
- `business_model[]` — populated by `founder-business-model`
- `gtm_plan` — populated by `founder-gtm`
- `sprint_state` — populated by `founder-sprint`

When those ship, `schema_version` bumps to `2` and a migration helper (Phase 2) will upgrade
existing files. Phase 1 files will NOT be silently migrated — the user must run the helper
explicitly.

---

## Example fully-populated venture-brief (post-ideation)

```yaml
venture_id: 4f2a8b1c-3d5e-4f6a-9b8c-1d2e3f4a5b6c
schema_version: 1
created: 2026-04-12T14:30:00Z
updated: 2026-04-12T16:45:00Z
intake:
  biz_type: software
  stage: idea-forming
  motion: B2B
  geography: GBR,USA
  runway: solo-bootstrap
  intent: ideation
  niche: "small accounting firms (1-5 employees) in UK and northeast USA"
  user_assets:
    skills: ["accounting background", "Python"]
    networks: ["12-year accounting practice network in UK"]
    distribution: ["small LinkedIn following in accounting sector"]
    unique_access: ["partnership with 2 mid-sized firms for beta testing"]
  stated_constraints:
    - "no VC money in year 1"
    - "solo until revenue supports a hire"
current_phase: ideation
last_subskill: founder-ideation
forge_handoff_ready: false
ideas_considered:
  - id: 11111111-1111-4111-8111-111111111111
    content: "SaaS for automated bank-feed reconciliation specifically for UK practices with multi-currency client portfolios"
    source_team: problem-first
    generated_at: 2026-04-12T16:20:00Z
    status: candidate
    kill_criteria:
      - "Fails if HMRC bank feed API removes multi-currency delta reporting"
      - "Fails if 3+ existing bookkeeping tools add this feature in the next 12 months"
    first_experiment: "Interview 10 UK practices from the user's network, show a 2-minute Figma mockup, measure willingness to pre-pay"
    attack_history:
      - from_team: contrarian
        severity: moderate
        issue: "Xero and QBO are already multi-currency-aware; this is not a wedge"
        fix_proposed: "Narrow to the delta-accounting-treatment of FX gains, which Xero handles badly — this IS the wedge"
      - from_team: trend-first
        severity: minor
        issue: "HMRC Making Tax Digital phase-4 rules change reporting structure, may invalidate the workflow"
        fix_proposed: "Check MTD phase-4 timeline; plan for phase-4 compatibility from day 1"
    data_sources:
      - "reddit:r/Accounting/post_abc123"
      - "reddit:r/UKSmallBusiness/post_def456"
      - "gdelt:1234567890"
      - "user_asset:12-year-accounting-network"
    confidence: medium
    revisions:
      - round: 3
        before: "SaaS for bank-feed reconciliation"
        after: "SaaS for FX-delta-aware bank-feed reconciliation for UK practices with multi-currency clients"
        critique_absorbed:
          - "contrarian: narrow to FX delta"
        critique_rejected: []
assumptions: []
experiments: []
decisions: []
risks: []
open_questions: []
forge_brief: null
```
