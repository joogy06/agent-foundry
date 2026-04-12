# Governance Templates Reference

Change control, decision log, RACI matrix, stakeholder register, and communication plan templates.

---

## Change Request Template

```markdown
# Change Request CR-[NNN]

**Date Submitted:** [date]
**Submitted By:** [name, role]
**Change Authority:** [PM / Sponsor / Steerco]

## 1. Change Description
[Clear, specific description of what is being changed]

## 2. Rationale
[Why is this change needed? What problem does it solve or opportunity does it capture?]

## 3. Impact Assessment

### Scope Impact
- **Current scope:** [what the plan says now]
- **Proposed scope:** [what changes]
- **Work packages affected:** [WBS IDs]

### Schedule Impact
- **Current baseline end date:** [date]
- **Revised end date if approved:** [date]
- **Schedule change:** [+/- N days/weeks]
- **Critical path affected?** [Yes/No -- if yes, explain]

### Budget Impact
- **Current budget:** $[amount]
- **Additional cost:** $[amount]
- **Revised budget if approved:** $[amount]
- **Funding source:** [contingency / additional funding / reallocation]

### Quality Impact
- [Does this change affect quality requirements, test scope, or acceptance criteria?]

### Risk Impact
- **New risks introduced:** [list any]
- **Existing risks affected:** [list any]

## 4. Alternatives Considered
| Option | Pros | Cons | Cost | Schedule |
|--------|------|------|------|----------|
| Do nothing | [pros] | [cons] | $0 | 0 days |
| Proposed change | [pros] | [cons] | $X | +N days |
| Alternative approach | [pros] | [cons] | $Y | +M days |

## 5. Recommendation
[Recommended option with rationale]

## 6. Decision
- [ ] Approved
- [ ] Approved with modifications: [details]
- [ ] Rejected: [reason]
- [ ] Deferred to: [date]

**Decided by:** [name, role]
**Decision date:** [date]

## 7. Implementation (if approved)
- **Implementation owner:** [name]
- **Implementation date:** [date]
- **Verification method:** [how we confirm the change was implemented correctly]
- **Baseline documents to update:** [list]
```

---

## Decision Log Template

| ID | Date | Decision | Context | Options Considered | Rationale | Owner | Impact | Status |
|----|------|---------|---------|-------------------|-----------|-------|--------|--------|
| D01 | [date] | Use PostgreSQL for the data layer | Need to select a database; team has mixed experience | PostgreSQL, MySQL, MongoDB | PostgreSQL: better JSON support, team has 2 experts, bank has enterprise license | Architect | Affects all data layer design | Final |
| D02 | [date] | 2-week sprint cadence | Need to establish delivery rhythm | 1-week, 2-week, 3-week sprints | 2-week: balances ceremony overhead with feedback frequency; aligns with existing release windows | DM | Sprint planning, resource allocation | Final |
| D03 | [date] | Defer mobile app to Phase 2 | Scope exceeds budget and timeline | Include mobile, defer mobile, cut features for mobile | Defer: web MVP delivers 80% of user value; mobile adds 6 weeks + $200K | PM / Sponsor | Reduces Phase 1 scope by 30% | Final |
| D04 | [date] | Use vendor X for authentication | SSO integration required | Build custom, Vendor X, Vendor Y | Vendor X: bank-approved, SOC2 certified, competitive pricing | Security Lead | Security architecture, vendor management | Pending review |

### Decision Log Best Practices

- Record decisions **when they are made**, not retroactively
- Include options that were **rejected** and why -- this prevents revisiting settled decisions
- Mark decisions as **Final**, **Pending Review**, or **Superseded**
- When a decision is superseded, reference the new decision ID
- Keep the log visible to all stakeholders -- transparency builds trust

---

## RACI Matrix Template

| Activity / Deliverable | PM | Sponsor | Architect | Dev Lead | Test Lead | BA | DM |
|------------------------|----|---------|-----------|---------|-----------|----|-----|
| Project Charter | A | R | C | I | I | C | I |
| Requirements Document | C | I | C | C | C | A/R | I |
| Architecture Design | C | I | A/R | C | I | C | I |
| Development Plan | C | I | C | A/R | C | I | C |
| Test Strategy | C | I | C | C | A/R | C | I |
| Sprint Planning | I | I | C | R | R | R | A |
| Status Reporting | A/R | I | I | C | C | I | C |
| Change Requests | A | R | C | C | C | C | I |
| Risk Management | A/R | C | C | C | C | I | C |
| Go/No-Go Decision | R | A | C | C | C | I | C |
| Deployment | C | I | C | A/R | R | I | C |
| Lessons Learned | A/R | C | C | C | C | C | C |

### RACI Validation Rules

- [ ] Every row has exactly one **A** (Accountable)
- [ ] Every row has at least one **R** (Responsible)
- [ ] No row is entirely empty
- [ ] No person has >5 **A** assignments (overloaded accountability)
- [ ] **C** count is minimized (too many consulted = slow decisions)
- [ ] **I** count is appropriate (information overload vs need-to-know)
- [ ] The person who is **A** has the authority to make decisions for that activity

### RACI Definitions

| Letter | Role | Description | Count Per Row |
|--------|------|-------------|---------------|
| **R** | Responsible | Does the work. Multiple R's OK (shared work). | 1 or more |
| **A** | Accountable | Ultimately answerable. Signs off. Buck stops here. | Exactly 1 |
| **C** | Consulted | Provides input before work/decision. Two-way communication. | 0 or more |
| **I** | Informed | Told after work/decision. One-way communication. | 0 or more |

---

## Stakeholder Register Template

| ID | Name | Role / Title | Organization | Interest Level (1-5) | Influence Level (1-5) | Engagement Level | Engagement Strategy | Key Concerns | Communication Preference |
|----|------|-------------|-------------|---------------------|----------------------|-----------------|--------------------|--------------|-----------------------|
| S01 | [name] | CTO | [org] | 4 | 5 | Champion | Manage closely | Budget, timeline, tech debt | Monthly 1:1, steerco deck |
| S02 | [name] | Head of Compliance | [org] | 3 | 5 | Neutral | Keep satisfied | Regulatory compliance, data privacy | Email updates, compliance gate reviews |
| S03 | [name] | Product Owner | [org] | 5 | 3 | Champion | Keep informed | Feature scope, user experience | Sprint reviews, Slack |
| S04 | [name] | Infrastructure Lead | [org] | 2 | 3 | Resistant | Monitor | Environment availability, workload impact | Capacity planning meetings |
| S05 | [name] | End User Rep | [org] | 5 | 2 | Supportive | Keep informed | Usability, training, change impact | UAT sessions, training schedule |

### Stakeholder Engagement Levels

| Level | Description | Goal |
|-------|------------|------|
| **Unaware** | Does not know about the project | Move to Informed |
| **Resistant** | Aware but opposed or concerned | Move to Neutral through engagement |
| **Neutral** | Aware, neither supportive nor resistant | Move to Supportive through value demonstration |
| **Supportive** | Aware and supportive but not actively helping | Move to Champion if appropriate |
| **Champion** | Actively advocates for the project | Maintain and leverage |

### Power/Interest Grid

```
HIGH     | Keep Satisfied  | Manage Closely |
POWER    |  (S02)         |  (S01)         |
         |                 |                |
LOW      | Monitor         | Keep Informed  |
POWER    |  (S04)         |  (S03, S05)    |
         |                 |                |
         | LOW INTEREST    | HIGH INTEREST  |
```

---

## Stakeholder Communication Plan Template

| Stakeholder Group | Information Needed | Format | Frequency | Owner | Channel |
|-------------------|-------------------|--------|-----------|-------|---------|
| Steering Committee | Overall status, RAG, decisions needed, risks, financials | 1-page summary | Monthly | PM | Steerco meeting |
| Project Sponsor | Detailed status, escalations, change requests | Status report + 1:1 | Bi-weekly | PM | Meeting + email |
| PMO | Full metrics, schedule tracking, resource utilization | PMO template | Weekly | PM | PMO portal |
| Development Team | Sprint goals, blockers, dependencies, technical decisions | Stand-up + sprint planning | Daily / per sprint | DM | Stand-up meeting |
| Business Stakeholders | Progress against milestones, upcoming changes | Progress update | Monthly | BA | Email newsletter |
| End Users | Training schedule, go-live timeline, change impact | Change comms | Per milestone | Change Lead | Email + intranet |
| Compliance / Legal | Compliance gate status, regulatory impacts | Gate review report | Per gate | PM | Compliance meeting |

### Communication Best Practices

- **Frequency matches power/interest**: high-power stakeholders get more frequent, detailed communication
- **Format matches audience**: executives get summaries, teams get detail
- **Every communication answers**: What happened? So what? What next?
- **No surprises**: bad news should never arrive for the first time at a steerco meeting
- **Two-way for C (Consulted)**: schedule input sessions, not just broadcasts
