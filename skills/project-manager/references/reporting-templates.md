# Reporting Templates Reference

Status report, steering committee summary, RAG threshold definitions, and dashboard layout recommendations.

---

## Weekly Status Report Template

```markdown
# Project Status Report -- [Project Name]

**Reporting Period:** [start date] to [end date]
**Report Date:** [date]
**Project Manager:** [name]

## Overall Status: [GREEN / AMBER / RED]

| Dimension | Status | Trend | Notes |
|-----------|--------|-------|-------|
| Schedule | [RAG] | [improving/stable/declining] | [brief note] |
| Budget | [RAG] | [improving/stable/declining] | [brief note] |
| Scope | [RAG] | [improving/stable/declining] | [brief note] |
| Quality | [RAG] | [improving/stable/declining] | [brief note] |

## Key Metrics

| Metric | Target | Actual | Variance |
|--------|--------|--------|----------|
| % Complete (planned) | [X]% | [X]% | [+/-X]% |
| % Budget spent | [X]% | [X]% | [+/-X]% |
| Open risks (high/critical) | [N] | [N] | |
| Open issues | [N] | [N] | |
| Milestones on track | [N/M] | [N/M] | |

## Accomplishments This Period
1. [Completed item with measurable outcome]
2. [Completed item with measurable outcome]
3. [Completed item with measurable outcome]

## Planned for Next Period
1. [Planned activity with expected completion date]
2. [Planned activity with expected completion date]
3. [Planned activity with expected completion date]

## Blockers and Issues

| ID | Description | Impact | Owner | Expected Resolution | Escalation Needed? |
|----|-------------|--------|-------|--------------------|--------------------|
| I01 | [description] | [impact on schedule/budget/scope] | [name] | [date] | [Yes/No] |
| I02 | [description] | [impact] | [name] | [date] | [Yes/No] |

## Risks (Top 5)

| ID | Risk | Score | Trend | Response Status |
|----|------|-------|-------|----------------|
| R01 | [description] | [N] | [up/stable/down] | [status of mitigation] |
| R02 | [description] | [N] | [up/stable/down] | [status] |

## Decisions Needed

| Decision | Context | Options | Deadline | Decision Maker |
|----------|---------|---------|----------|----------------|
| [decision needed] | [why it's needed] | [A, B, or C] | [date] | [name/role] |

## Dependencies Update

| Dependency | Provider | Due Date | Status | Risk |
|-----------|----------|----------|--------|------|
| [dependency] | [team/vendor] | [date] | [on track/at risk/late] | [impact if late] |
```

---

## Monthly Steering Committee Summary Template

```markdown
# Steering Committee Report -- [Project Name]
**Date:** [date] | **PM:** [name] | **Sponsor:** [name]

---

## Executive Summary

**Overall Status: [GREEN / AMBER / RED]** [one sentence explaining why]

[2-3 sentences: Where we are. What's going well. What needs attention.]

---

## Key Performance Indicators

| KPI | Target | Actual | Status |
|-----|--------|--------|--------|
| Schedule (% complete vs plan) | [X]% | [X]% | [RAG] |
| Budget (spend vs baseline) | $[X] | $[X] | [RAG] |
| Scope (features delivered vs planned) | [N] | [N] | [RAG] |
| Quality (defect rate / test pass rate) | [X]% | [X]% | [RAG] |
| Team utilization | [X]% | [X]% | [RAG] |

---

## Financial Summary

*Detailed analysis available from `project-finance`.*

| Item | Budget | Actual | Forecast | Variance |
|------|--------|--------|----------|----------|
| Total project | $[X] | $[X] | $[X] | [+/-$X] ([X]%) |
| Phase [current] | $[X] | $[X] | $[X] | [+/-$X] |

---

## Milestone Tracker

| Milestone | Baseline Date | Forecast Date | Status |
|-----------|--------------|---------------|--------|
| [M1] | [date] | [date] | [Complete/On Track/At Risk/Late] |
| [M2] | [date] | [date] | [status] |
| [M3] | [date] | [date] | [status] |

---

## Top Risks and Issues

| # | Type | Description | Impact | Action | Owner |
|---|------|-------------|--------|--------|-------|
| 1 | [Risk/Issue] | [description] | [schedule/budget/scope impact] | [action being taken] | [name] |
| 2 | [Risk/Issue] | [description] | [impact] | [action] | [name] |
| 3 | [Risk/Issue] | [description] | [impact] | [action] | [name] |

---

## Decisions Required from Steering Committee

| # | Decision | Context | Recommendation | Deadline |
|---|----------|---------|----------------|----------|
| 1 | [decision] | [why needed] | [PM recommendation] | [date] |
| 2 | [decision] | [context] | [recommendation] | [date] |

---

## Next Period Outlook

- [Key activities planned]
- [Key milestones approaching]
- [Known challenges or dependencies]
```

---

## RAG Threshold Definitions

### Schedule RAG

| Status | Criteria | Action Required |
|--------|---------|-----------------|
| **Green** | Within 5% of baseline schedule. All critical path activities on track. | Normal monitoring. |
| **Amber** | 5-15% behind baseline. One or more critical path activities at risk. | Recovery plan required. PM to present options. |
| **Red** | >15% behind baseline. Critical path activities delayed with no recovery plan. | Escalation to sponsor/steerco. Re-baseline discussion. |

### Budget RAG

| Status | Criteria | Action Required |
|--------|---------|-----------------|
| **Green** | Within 5% of baseline budget. CPI > 0.95. | Normal monitoring. |
| **Amber** | 5-10% over baseline budget. CPI between 0.85-0.95. | Cost recovery actions. PM to present savings options. |
| **Red** | >10% over baseline budget. CPI < 0.85. | Escalation. Scope reduction or additional funding request. |

### Scope RAG

| Status | Criteria | Action Required |
|--------|---------|-----------------|
| **Green** | All deliverables on track. Change requests within threshold. | Normal monitoring. |
| **Amber** | Minor scope changes pending approval. 1-2 deliverables at risk. | Change control review. Prioritization discussion. |
| **Red** | Major scope changes required. Multiple deliverables cut or deferred. | Steerco decision on scope vs timeline vs budget trade-off. |

### Quality RAG

| Status | Criteria | Action Required |
|--------|---------|-----------------|
| **Green** | All quality gates passing. Defect rate within tolerance. Test coverage on target. | Normal monitoring. |
| **Amber** | Minor quality issues. 1-2 quality gates with conditions. Defect trend increasing. | Root cause analysis. Quality improvement actions. |
| **Red** | Critical quality failures. Quality gates not passing. Unacceptable defect rate. | Stop and fix. Quality remediation plan required. |

---

## Dashboard Layout Recommendations

### Executive Dashboard (1 page)

```
+----------------------------------+----------------------------------+
|  OVERALL STATUS: [RAG]          |  KEY METRICS                      |
|  [1-sentence summary]          |  Schedule: [X]% vs [Y]% planned  |
|                                 |  Budget:   $[X] vs $[Y] baseline |
|  Trend: [improving/declining]  |  Scope:    [N/M] features done    |
+----------------------------------+----------------------------------+
|  MILESTONE TRACKER              |  TOP 3 RISKS                      |
|  [Visual timeline with RAG      |  1. [risk] - [RAG]               |
|   per milestone]                |  2. [risk] - [RAG]               |
|                                 |  3. [risk] - [RAG]               |
+----------------------------------+----------------------------------+
|  DECISIONS NEEDED                                                   |
|  1. [Decision] - deadline: [date]                                  |
|  2. [Decision] - deadline: [date]                                  |
+--------------------------------------------------------------------+
```

### PMO Dashboard (detailed)

| Section | Metrics to Include |
|---------|-------------------|
| Schedule | Gantt chart or milestone view, % complete, critical path status |
| Budget | Budget vs actual chart, burn rate, EVM metrics (CPI, SPI, EAC) |
| Scope | Feature completion tracker, change request log, backlog burn-down |
| Quality | Defect trend, test coverage, quality gate status |
| Risk | Risk heat map (P/I matrix), risk trend, new risks this period |
| Resources | Team utilization, capacity vs demand, skills gaps |

### Team Dashboard

| Section | Metrics to Include |
|---------|-------------------|
| Sprint/iteration | Current sprint goals, velocity, burn-down |
| Blockers | Active blockers with owner and age |
| Upcoming | Next 2 weeks' key activities |
| Dependencies | Cross-team dependencies with status |
| Action items | Open action items from last retrospective |
