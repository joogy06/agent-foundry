# Agile Frameworks Reference

Framework comparison, selection criteria, event cheat sheets, and board design patterns.

---

## Framework Comparison Matrix

| Dimension | Scrum | Kanban | SAFe | LeSS | Scrumban |
|-----------|-------|--------|------|------|----------|
| **Team size** | 5-9 | Any | 50-125+ (ART) | 2-8 teams | 5-9 |
| **Cadence** | Fixed sprints (1-4 weeks) | Continuous flow | PI (8-12 weeks) + sprints | Fixed sprints | Hybrid (optional sprints) |
| **Roles** | SM, PO, Dev Team | None required | RTE, PM, SA, SM, PO | SM, PO, Dev Team | Optional SM/PO |
| **Planning** | Sprint Planning | On-demand | PI Planning + Sprint Planning | Sprint Planning | On-demand or time-boxed |
| **WIP limits** | Sprint backlog = implicit WIP | Explicit WIP limits per column | Team capacity per sprint | Sprint backlog | Explicit WIP limits |
| **Estimation** | Story points or hours | None required | Story points | Story points | Optional |
| **Reviews** | Sprint Review | On-demand / periodic | System Demo | Sprint Review | Periodic |
| **Retrospectives** | Every sprint | Periodic | PI Retrospective + sprint retros | Every sprint | Periodic |
| **Best for** | Product development, clear PO | Support, ops, variable demand | Enterprise multi-team | Multi-team, minimal framework | Transitioning from Scrum to flow |

---

## Framework Selection Decision Tree

```
How many teams need to coordinate?

ONE TEAM:
  Is work predictable and can be planned in sprints?
    YES --> Is the team new to Agile?
      YES --> SCRUM (structure helps new teams)
      NO  --> Does the team want more flow-based delivery?
        YES --> SCRUMBAN or KANBAN
        NO  --> SCRUM
    NO --> Is work interrupt-driven or highly variable?
      YES --> KANBAN
      NO  --> SCRUMBAN

MULTIPLE TEAMS (2-8):
  Do teams need minimal framework overhead?
    YES --> LeSS
    NO  --> Do teams need enterprise-level alignment and governance?
      YES --> SAFe
      NO  --> Scrum of Scrums (informal coordination)

MANY TEAMS (8+):
  --> SAFe (or portfolio-level Kanban)
```

---

## Scrum Event Cheat Sheet

### Sprint Planning

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Define what can be delivered in the sprint and how |
| **Timebox** | 2 hours per sprint week (e.g., 4h for 2-week sprint) |
| **Participants** | Full Scrum Team (PO, SM, Dev Team) |
| **Inputs** | Product Backlog, velocity data, team capacity, DoD |
| **Outputs** | Sprint Goal, Sprint Backlog (selected items + plan) |

**Agenda:**
1. PO presents top backlog items and sprint goal proposal (20%)
2. Team discusses and clarifies items (20%)
3. Team selects items based on capacity (20%)
4. Team creates a plan (tasks, dependencies) for selected items (30%)
5. Team confirms sprint goal and commitment (10%)

### Daily Stand-up

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Inspect progress toward sprint goal, adapt plan |
| **Timebox** | 15 minutes |
| **Participants** | Dev Team (SM facilitates, PO optional) |
| **Format** | Walk the board (not round-robin status updates) |

**Walk-the-board approach:**
- Start from the rightmost column (closest to done)
- For each item: What's needed to move it forward? Any blockers?
- Focus on flow, not individual status reports

### Sprint Review

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Inspect the increment, gather feedback, adapt backlog |
| **Timebox** | 1 hour per sprint week |
| **Participants** | Scrum Team + stakeholders |
| **Outputs** | Revised Product Backlog based on feedback |

**Agenda:**
1. Sprint goal recap and accomplishment summary (10%)
2. Demo of completed work (50%)
3. Stakeholder feedback and discussion (25%)
4. Backlog adaptation and next sprint preview (15%)

### Sprint Retrospective

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Inspect team process and create improvement plan |
| **Timebox** | 45 min per sprint week |
| **Participants** | Scrum Team only (no stakeholders) |
| **Outputs** | Maximum 3 specific, owned improvement actions |

### Backlog Refinement

| Attribute | Detail |
|-----------|--------|
| **Purpose** | Prepare backlog items for future sprints |
| **Timebox** | 10% of sprint capacity (ongoing, not a single event) |
| **Participants** | PO + Dev Team members (subset OK) |
| **Outputs** | Refined stories (estimated, acceptance criteria, small enough) |

---

## Kanban Board Design Patterns

### Basic Board

```
| Backlog | Ready | In Progress | Review | Done |
|---------|-------|-------------|--------|------|
|         |       | WIP: 3      | WIP: 2 |      |
```

### Swimlane Board (by work type)

```
              | Backlog | In Progress | Review | Done |
| Features    |         | WIP: 2      |        |      |
| Bugs        |         | WIP: 2      |        |      |
| Tech Debt   |         | WIP: 1      |        |      |
| Expedite    |         | WIP: 1      |        |      |
```

### Class of Service Board

| Class | Description | WIP Allocation | Lead Time Target |
|-------|-------------|----------------|-----------------|
| Expedite | Production incidents, critical bugs | 1 (shared lane, can preempt) | ASAP |
| Fixed Date | Regulatory, contractual deadlines | Planned in advance | Meet the date |
| Standard | Normal features and stories | Majority of WIP | 85th percentile |
| Intangible | Tech debt, refactoring, experiments | 15-20% of capacity | No specific target |

---

## SAFe Ceremony Calendar Template

**PI Cadence: 10 weeks (5 x 2-week sprints)**

| Week | Event | Duration | Participants |
|------|-------|----------|-------------|
| 0 | PI Planning Day 1 | Full day | All ART members |
| 0 | PI Planning Day 2 | Full day | All ART members |
| 2 | Sprint 1 Review/Retro | 2h | Individual teams |
| 4 | Sprint 2 Review/Retro | 2h | Individual teams |
| 5 | Mid-PI Sync | 1h | Scrum Masters, RTE |
| 6 | Sprint 3 Review/Retro | 2h | Individual teams |
| 8 | Sprint 4 Review/Retro | 2h | Individual teams |
| 9 | Innovation & Planning (IP) Sprint | Full sprint | All ART members |
| 10 | System Demo | 2h | All ART + stakeholders |
| 10 | Inspect & Adapt | 3h | All ART members |

**Weekly ART Sync (Scrum of Scrums):** 30 min, Scrum Masters + RTE
**PO Sync:** 30 min weekly, Product Owners + Product Manager
