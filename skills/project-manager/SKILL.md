---
name: project-manager
description: >
  Use when planning projects, managing scope, tracking risks, creating status reports,
  managing stakeholders, or handling project governance. Covers WBS decomposition,
  critical path analysis, milestone planning, risk registers, RAID logs, RACI matrices,
  change control, and executive reporting. Works with any methodology (Agile, Waterfall,
  hybrid, PRINCE2, PMBOK). Routes financial analysis to project-finance skill.
  Trigger on: project plan, WBS, milestone, critical path, risk register, RAID,
  RACI, status report, steering committee, change request, project governance,
  resource allocation, capacity planning, stakeholder management.
---

# Project Manager

Project management skill covering planning through closure. Peer to `delivery-manager` -- neither contains the other. Routes all financial analysis to `project-finance`.

<HARD-RULE>
Never make autonomous decisions about scope, priorities, resource allocation, or risk responses.
Always present recommendations for user approval. Draft-and-confirm, not decide-and-act.
</HARD-RULE>

<HARD-RULE>
Always state assumptions explicitly. When input data is incomplete, list what's assumed and
what's missing. Never silently fill gaps.
</HARD-RULE>

<HARD-RULE>
Never present financial numbers without showing the calculation method and input data used.
Confidently wrong financial analysis is worse than no analysis.
</HARD-RULE>

<HARD-RULE>
Never assume methodology. Ask what framework the project uses (Agile, Waterfall, hybrid,
PRINCE2, PMBOK, or other) before producing methodology-specific artifacts.
</HARD-RULE>

<HARD-RULE>
Reference files are loaded on demand, not at session start. Only read a reference file when
the user's request falls into that domain.
</HARD-RULE>

---

## Intake Process

When a user brings a project management question, gather context before producing artifacts:

1. **Project Context** -- What type of project? Size? Phase (initiation, planning, execution, closing)?
2. **Methodology** -- What framework? Agile, Waterfall, hybrid, PRINCE2, PMBOK, or other?
3. **Domain** -- Which PM domain does the user need? (planning, risk, reporting, governance, resources)
4. **Constraints** -- Timeline, budget, regulatory requirements, team size?
5. **Existing Artifacts** -- Does the project already have a WBS, risk register, or status report format?

### Routing Detection

- If the request involves **budget, variance, EVM, spend, or cost analysis** --> route to `project-finance`. Tell the user: "I'll apply the project-finance patterns for this financial analysis."
- If the request involves **sprint planning, velocity, ceremonies, flow metrics** --> suggest `delivery-manager`. Tell the user: "This falls into delivery execution territory. The delivery-manager skill covers Agile ceremonies and flow metrics."
- If the request involves **status deck or presentation** --> gather status data first, then apply `presentation-builder` patterns for the deck.

---

## Routing Table

| User Need | Action |
|-----------|--------|
| WBS, schedule, milestones, dependencies | Handle directly -- read `references/planning-templates.md` |
| Risk register, RAID log, risk assessment | Handle directly -- read `references/risk-templates.md` |
| Change control, decision log, RACI | Handle directly -- read `references/governance-templates.md` |
| Status report, steerco summary, RAG | Handle directly -- read `references/reporting-templates.md` |
| Budget, variance, EVM, spend analysis | Route to `project-finance` |
| Sprint planning, velocity, ceremonies | Suggest `delivery-manager` |
| Status deck, presentation | Apply `presentation-builder` with gathered status data |
| Large project data exports | Apply `large-file-analysis` patterns for chunked processing |

---

## Domain Knowledge

### Planning

**WBS Decomposition Rules:**
- **100% Rule** -- the WBS must capture 100% of the project scope. Every deliverable must be represented.
- **Mutual Exclusivity** -- work packages should not overlap. Each piece of work appears exactly once.
- **Progressive Elaboration** -- decompose to the level needed for estimation and assignment. Near-term work is detailed; future phases can be higher-level.
- **Deliverable-Oriented** -- WBS elements represent deliverables (nouns), not activities (verbs).
- **8/80 Rule** -- work packages should take between 8 and 80 hours of effort. Smaller = micro-management; larger = not decomposed enough.

**Critical Path Method:**
- Forward pass: calculate Early Start (ES) and Early Finish (EF) for each activity
- Backward pass: calculate Late Start (LS) and Late Finish (LF) from the end
- Float = LS - ES = LF - EF. Zero float = critical path activity.
- Critical path = longest path through the network. Determines minimum project duration.
- Any delay on a critical path activity delays the entire project.

**Estimation Techniques Decision Tree:**
1. **Analogous** -- if you have a similar past project, use its actuals as a baseline. Fast, rough (range: -25% to +75%).
2. **Parametric** -- if you have a cost/duration driver (e.g., $X per function point), apply the rate. More accurate if the parameter is calibrated.
3. **Three-Point (PERT)** -- if you have expert judgment but uncertainty. E = (O + 4M + P) / 6. Standard deviation = (P - O) / 6.
4. **Bottom-Up** -- if you need accuracy and have detailed WBS. Sum estimates for each work package. Most accurate, most effort.

**Dependency Types:**
- **FS (Finish-to-Start)** -- most common. B cannot start until A finishes.
- **FF (Finish-to-Finish)** -- B cannot finish until A finishes.
- **SS (Start-to-Start)** -- B cannot start until A starts.
- **SF (Start-to-Finish)** -- B cannot finish until A starts. (Rare)
- **Leads** -- acceleration (negative lag). "Start B 2 days before A finishes."
- **Lags** -- delay. "Start B 3 days after A finishes."

**Schedule Compression:**
- **Crashing** -- add resources to critical path activities. Increases cost. Diminishing returns. Only works if activity is resource-limited, not externally constrained.
- **Fast-Tracking** -- overlap sequential activities. Increases risk. Only works if activities have natural overlap opportunity.

### Risk Management

**Risk Identification Techniques:**
- **SWOT Analysis** -- internal strengths/weaknesses, external opportunities/threats
- **Pre-Mortem** -- imagine the project has failed, then identify what caused the failure
- **Assumption Analysis** -- list all assumptions, assess what happens if each is wrong
- **Checklist Review** -- use historical risk categories from similar projects

**Response Strategy Selection:**
- **Threats:** Avoid (eliminate the cause) > Transfer (insurance, contract) > Mitigate (reduce probability or impact) > Accept (acknowledge and budget contingency)
- **Opportunities:** Exploit (ensure it happens) > Share (partner with someone who can realize it) > Enhance (increase probability or impact) > Accept (take it if it comes)

**Risk Escalation Criteria:**
- Risk score exceeds project-level authority (e.g., impact > $500K)
- Risk crosses project boundaries (affects other projects/programs)
- Risk becomes an issue (probability = 100%, it has happened)
- Risk response requires resources outside the project team

**Risk Review Cadence:**
- Active risks (score > threshold): weekly review
- Watch-list risks (score below threshold): monthly review
- Closed risks: quarterly review for lessons learned

### Governance

**Change Control Process:**
1. Request submitted (scope, schedule, or budget change)
2. Impact assessment (what changes, what's affected, cost/time impact)
3. Approve, reject, or defer (by change authority -- PM for small, steerco for large)
4. Implement the change
5. Verify the change was implemented correctly
6. Update baseline documents

**Decision Log Format:**
- Decision ID, date, decision statement
- Context: what problem prompted this decision
- Options considered: what alternatives were evaluated
- Rationale: why this option was selected
- Owner: who made/approved the decision
- Impact: what the decision changes in the project plan

**RACI Rules:**
- Exactly one **A** (Accountable) per activity -- multiple A = nobody accountable
- One or more **R** (Responsible) -- the people doing the work
- **C** (Consulted) -- people whose input is sought before a decision
- **I** (Informed) -- people who are told after a decision or action
- Minimize C and I to reduce communication overhead
- No empty rows (every activity has at least R and A)
- If A and R are the same person, that's fine but note it explicitly

**Escalation Framework:**
1. Team level -- PM resolves within team authority
2. PM level -- PM escalates to project sponsor
3. Sponsor level -- sponsor escalates to steering committee
4. Steerco level -- steering committee escalates to executive management

### Status Reporting

**RAG Criteria (Objective, Not Subjective):**

| Dimension | Green | Amber | Red |
|-----------|-------|-------|-----|
| Schedule | Within 5% of baseline | 5-15% behind baseline | >15% behind baseline |
| Budget | Within 5% of baseline | 5-10% over baseline | >10% over baseline |
| Scope | All deliverables on track | Minor scope changes pending | Major scope changes or cuts needed |
| Quality | All quality gates passing | Minor quality issues | Critical quality failures |

**Executive Summary Structure:**
1. **Situation** -- one-sentence project status (where we are)
2. **Progress** -- key accomplishments this period
3. **Blockers** -- items impeding progress (with owner and expected resolution)
4. **Decisions Needed** -- specific asks for the audience (with deadline)
5. **Next Steps** -- planned actions for the coming period

**Audience Adaptation:**
- **Steerco** -- 1-page summary. RAG, key metrics, decisions needed, risks. No detail.
- **PMO** -- full detail. Financials, schedule tracking, resource utilization, risk log.
- **Team** -- action-oriented. What's done, what's next, who's doing what, blockers.

### Resources

**Capacity Planning:**
- Effective capacity = FTE count x availability % x allocation %
- Example: 5 FTEs x 80% available (holidays, meetings) x 60% allocated = 2.4 FTE effective
- Over-allocation detection: if sum of allocations > 100% for any person, they're over-allocated
- Resolution: re-prioritize, defer work, add resources, or negotiate timeline

**Skills Matrix:**
- Rows: team members. Columns: required competencies.
- Proficiency levels: 0 (none), 1 (basic), 2 (intermediate), 3 (advanced), 4 (expert)
- Identify gaps: required level vs current level for each person-competency pair
- Plan: training, hiring, or partnering to fill critical gaps

---

## Integration Points

- **project-finance** -- for all financial analysis (budget, variance, EVM, spend, forecasting)
- **presentation-builder** -- for status decks and steering committee presentations
- **large-file-analysis** -- for analyzing large project data exports
- **delivery-manager** -- cross-reference for execution metrics, sprint data, team velocity

---

## Anti-Patterns

| Anti-Pattern | Why It's Wrong | Do This Instead |
|-------------|----------------|-----------------|
| Creating a plan without WBS | Schedule without decomposition = guessing | Always decompose scope before scheduling |
| RAG status based on feelings | Subjective RAG destroys credibility | Tie RAG to measurable thresholds |
| Risk register as write-once artifact | Unreviewed risks = false security | Schedule regular risk reviews |
| RACI with multiple A's per activity | Multiple accountable = nobody accountable | Exactly one A per row |
| Status report without decisions needed | Report without asks = wasted exec time | Always include decisions/actions needed |
| Skipping change control | Scope creep kills projects silently | Every scope change goes through change control |
| Estimating without decomposition | High-level guesses compound into massive overruns | Decompose first, estimate at work package level |
| Planning in isolation | Plans without stakeholder input get rejected | Involve key stakeholders in planning workshops |

---

## When NOT to Use This Skill

| Request | Use Instead |
|---------|-------------|
| Sprint/PI planning, velocity, ceremonies | `delivery-manager` |
| Budget analysis, EVM, variance | `project-finance` |
| Slide deck creation | `presentation-builder` |
| Technical implementation planning | Domain-specific skill (e.g., `python-flask-developer`) |
| General career advice | `career-coach` |

---

## Reference Files

Read these on demand when the user's request falls into the relevant domain:

- `~/.claude/skills/project-manager/references/planning-templates.md` -- WBS, milestone register, dependency register, estimation templates
- `~/.claude/skills/project-manager/references/risk-templates.md` -- risk register, P/I matrix, RAID log, response strategies
- `~/.claude/skills/project-manager/references/governance-templates.md` -- change control, decision log, RACI, stakeholder register
- `~/.claude/skills/project-manager/references/reporting-templates.md` -- status report, steerco summary, RAG framework, dashboard layout
