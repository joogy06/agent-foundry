# Gate Criteria

Detailed checklist per gate with specific evidence artifacts required and pass/fail rubrics.

---

## Diagnose Gate

**Must pass ALL of the following:**

| # | Criterion | Evidence artifact | Pass | Fail |
|---|---|---|---|---|
| D1 | >= 3 ranked ideas in venture-brief | `ideas_considered[].rank` exists for >= 3 entries | 3+ ideas with rank values | < 3 ideas or no ranks |
| D2 | Each idea has data citation | `ideas_considered[].data_sources` non-empty per idea (HR-5) | All ideas have >= 1 data source | Any idea has empty data_sources |
| D3 | 1 idea selected | An idea marked as selected for validation | Exactly 1 idea flagged | 0 or ambiguous selection |
| D4 | >= 3 assumptions listed | `assumptions[]` has >= 3 entries | 3+ assumptions | < 3 assumptions |
| D5 | >= 3 kill criteria on selected idea | `ideas_considered[selected].kill_criteria` count >= 3 (HR-4) | 3+ kill criteria | < 3 kill criteria |

**How to check:**
```
Read venture-brief.yaml
Count ideas_considered where rank is not null → D1
For each idea, check data_sources is non-empty → D2
Check for a selected idea marker → D3
Count assumptions → D4
Count kill_criteria on selected idea → D5
```

---

## Evidence Gate

**Must pass ALL of the following:**

| # | Criterion | Evidence artifact | Pass | Fail |
|---|---|---|---|---|
| E1 | Top-3 riskiest assumptions each have >= 1 experiment | `assumptions[].test_ref` links to `experiments[]` with evidence | Each of top-3 has a completed experiment | Any of top-3 has no experiment |
| E2 | >= 1 real interview logged | `interview_count >= 1` AND a `capture_evidence` entry with type `interview` (HR-V2) | interview_count >= 1 | interview_count == 0 |
| E3 | No high-risk viability assumption falsified without resolution | Falsified assumptions have either `pivoted` or `accepted_risk` status | All falsified high-risk assumptions resolved | Falsified without resolution |

**Risk ranking for E1:**
- Sort assumptions by `risk_level` (high > medium > low)
- Among same risk level, sort by `category` priority: problem > solution > pricing > market > channel > technical > regulatory
- Take top 3

**How to check:**
```
Sort assumptions by risk_level and category → identify top 3
For each top-3: check test_ref points to an experiment with non-null evidence → E1
Read interview_count → E2
Filter assumptions where status == 'falsified' AND risk_level == 'high':
  For each: check status is 'pivoted' or 'accepted_risk' → E3
```

---

## Decision Gate

**Must pass ALL of the following:**

| # | Criterion | Evidence artifact | Pass | Fail |
|---|---|---|---|---|
| DC1 | Price set with tag | `business_model.price.value` is not null, `business_model.price.tag` is valid enum | Price present with tag | No price or missing tag |
| DC2 | Unit economics computed | `business_model.unit_econ.contribution_margin` has low/expected/high values | CM range present | CM missing |
| DC3 | Decision rule stated | `business_model.decision_rule` is non-empty string | Rule present | No rule |
| DC4 | Decision verdict GREEN or CONDITIONAL_GO with user ack | `business_model.decision_verdict` is `green` or `conditional_go` | Verdict is go/conditional | Verdict is `red` |
| DC5 | Forge brief: problem | `forge_brief.problem` is non-empty | Present | Missing |
| DC6 | Forge brief: solution | `forge_brief.solution` is non-empty | Present | Missing |
| DC7 | Forge brief: success_criteria | `forge_brief.success_criteria` is non-empty list | Present | Missing |
| DC8 | Forge brief: non_goals | `forge_brief.non_goals` is non-empty list | Present | Missing |

**CONDITIONAL_GO handling:**
If `decision_verdict` is `conditional_go`, sprint must:
1. Surface what's conditional (from `needs_more_data[]`)
2. Ask user: "This is a conditional go. The following are unresolved: [list]. Proceed anyway?"
3. Record user's acknowledgment in venture-brief

---

## Handoff Gate

**Must pass ALL of the following:**

| # | Criterion | Evidence artifact | Pass | Fail |
|---|---|---|---|---|
| H1 | All previous stages completed | `stage_completed_at` has timestamps for diagnose, evidence, decision | All 3 timestamps present | Any missing |
| H2 | Forge brief complete | All DC5-DC8 criteria still pass | All fields present | Any field missing |
| H3 | User confirms "ship it" | Explicit user confirmation in conversation | User said yes | User hasn't confirmed |

---

## Gate Failure Responses

When a gate check fails, sprint:

1. Lists ALL failing criteria (not just the first one)
2. For each failure, suggests the specific action and subskill to invoke
3. Does NOT attempt to fix the failures itself — it routes to the right subskill
4. Does NOT auto-invoke subskills — presents the plan and waits for user confirmation

Example response for Evidence gate failure:
> "Evidence gate check: 2 of 3 criteria failing.
>
> - **E1 FAIL:** Assumption 'UK accountants spend >10h/mo on FX reconciliation' has no
>   experiment. Action: run `founder-validation design_experiment` for this assumption.
> - **E2 FAIL:** 0 interviews logged (need >= 1). Action: run `founder-validation
>   draft_interview` and conduct at least 1 Mom Test interview.
> - **E3 PASS:** No falsified high-risk assumptions.
>
> Want me to start with designing an experiment for the untested assumption?"
