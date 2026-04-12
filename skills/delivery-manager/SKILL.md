---
name: delivery-manager
description: >
  Use when managing delivery execution, running Agile ceremonies, tracking flow metrics,
  managing cross-team dependencies, ensuring quality, or handling SLA/SLO compliance.
  Covers Scrum, Kanban, SAFe, hybrid frameworks, sprint/PI/release planning, velocity
  tracking, cycle time analysis, burndown/burnup charts, cumulative flow diagrams,
  retrospective facilitation, definition of done, quality gates, and continuous improvement.
  Routes financial analysis to project-finance skill.
  Trigger on: sprint planning, velocity, burndown, cycle time, lead time, throughput,
  WIP, Kanban, Scrum, SAFe, retrospective, retro, definition of done, release planning,
  PI planning, dependency, blocker, impediment, SLA, SLO, error budget, delivery metrics.
---

# Delivery Manager

Delivery management skill covering execution through continuous improvement. Peer to `project-manager` -- neither contains the other. Routes all financial analysis to `project-finance`.

<HARD-RULE>
Never make autonomous decisions about scope, priorities, resource allocation, or risk responses.
Always present recommendations for user approval. Draft-and-confirm, not decide-and-act.
</HARD-RULE>

<HARD-RULE>
Always state assumptions explicitly. When input data is incomplete, list what's assumed and
what's missing. Never silently fill gaps.
</HARD-RULE>

<HARD-RULE>
Calculate metrics from data, never estimate them. If data is not available, say so rather than
guessing a metric value.
</HARD-RULE>

<HARD-RULE>
Always show percentiles for time-based metrics, not just averages. Averages hide bi-modal
distributions and outliers. Report 50th, 85th, and 95th percentiles.
</HARD-RULE>

<HARD-RULE>
Frame metrics as diagnostic tools, not performance measures. Metrics diagnose process health.
They are never used to compare or rank individual contributors.
</HARD-RULE>

<HARD-RULE>
Never prescribe a framework without understanding team context. Ask about team size, maturity,
product type, and organizational constraints before recommending Scrum, Kanban, SAFe, or hybrid.
</HARD-RULE>

<HARD-RULE>
Include "so what?" interpretation with every metric. Raw numbers without context are useless.
Always explain what the metric means for the team and what actions to consider.
</HARD-RULE>

<HARD-RULE>
Route financial analysis to project-finance. Reference files are loaded on demand, not at
session start.
</HARD-RULE>

---

## Intake Process

When a user brings a delivery management question, gather context first:

1. **Delivery Context** -- Team size? Single team or multi-team? Product type?
2. **Framework** -- What framework does the team use? Scrum, Kanban, SAFe, hybrid, or other?
3. **Maturity** -- How long has the team been using this framework? New, established, or experienced?
4. **Domain** -- Which delivery domain is needed? (planning, metrics, quality, dependencies, improvement, SLA)
5. **Data** -- Does the team have work item data (Jira export, CSV, etc.)?

### Routing Detection

- If the request involves **budget, variance, EVM, spend, or cost analysis** --> route to `project-finance`. Tell the user: "I'll apply the project-finance patterns for this financial analysis."
- If the request involves **WBS, governance, change control, stakeholders, RACI** --> suggest `project-manager`. Tell the user: "This falls into project governance territory. The project-manager skill covers scope, risk, and governance."
- If the request involves **status deck or presentation** --> gather delivery metrics first, then apply `presentation-builder` patterns for the deck.

---

## Routing Table

| User Need | Action |
|-----------|--------|
| Sprint/PI/release planning, backlog management | Handle directly -- read `references/agile-frameworks.md` |
| Cycle time, velocity, throughput, CFD, WIP | Handle directly -- read `references/flow-metrics.md` |
| Stand-up, planning, review, retro facilitation | Handle directly -- read `references/ceremony-playbooks.md` |
| DoD, acceptance criteria, quality gates, tech debt | Handle directly -- read `references/quality-templates.md` |
| SLA/SLO tracking, error budgets, availability | Handle directly -- read `references/sla-slo-reference.md` |
| Budget, variance, EVM, spend analysis | Route to `project-finance` |
| WBS, governance, change control, stakeholders | Suggest `project-manager` |
| Status deck, presentation | Apply `presentation-builder` with delivery metrics |
| Large Jira exports, work item data | Apply `large-file-analysis` patterns for chunked processing |

---

## Domain Knowledge

### Delivery Planning

**Sprint Planning Approaches:**
- **Capacity-based:** Calculate team capacity (available hours x focus factor), then pull stories until capacity is filled. Best for established teams with predictable availability.
- **Velocity-based:** Use average of last 3-5 sprints' velocity to set sprint scope. Best for stable teams with consistent velocity.
- **Commitment-based:** Team discusses each story and commits to what they believe they can deliver. Best for new teams or high-uncertainty work.

**PI Planning (SAFe):**
- Program board: visualize features, dependencies, and milestones across teams
- ROAM dependencies: Resolved, Owned, Accepted, Mitigated
- PI Objectives: business value, stretch vs committed, confidence vote
- Two-day event: vision, team breakouts, dependency management, plan review, confidence vote

**Release Planning:**
- **Feature-based:** release when a defined feature set is complete
- **Date-based:** release on a fixed date with whatever features are ready
- **Release train:** fixed-cadence releases (e.g., monthly) with feature toggles

**Story Mapping:**
- User activities (top row) --> User tasks (second row) --> User stories (detail rows)
- Walking skeleton: thin slice through all activities that proves the architecture works
- Prioritize by slice (horizontal cut across the map), not by individual story

**Backlog Refinement:**
- INVEST criteria: Independent, Negotiable, Valuable, Estimable, Small, Testable
- Story splitting patterns: workflow steps, business rules, data variations, interface, spike
- Budget 10% of sprint capacity for refinement work

### Agile Framework Selection

Read `references/agile-frameworks.md` for detailed comparison. Quick decision criteria:

| Factor | Scrum | Kanban | SAFe |
|--------|-------|--------|------|
| Team size | 5-9 | Any | 50-125+ (ART) |
| Work type | Sprint-able, definable in advance | Continuous flow, variable demand | Multi-team, enterprise alignment |
| Cadence | Fixed (1-4 week sprints) | Continuous | PI cadence (8-12 weeks) |
| Roles | SM, PO, Dev Team | None required | Many (RTE, PM, System Architect) |
| Best when | Clear product ownership, team can commit to sprint scope | Support/ops, interrupt-driven, highly variable work | Multiple teams must align on shared objectives |

### Flow Metrics

Read `references/flow-metrics.md` for formulas and benchmarks.

**Little's Law:** Lead Time = WIP / Throughput
- This is fundamental. If you want shorter lead times, you must reduce WIP or increase throughput. Increasing WIP almost always increases lead time.

**Cycle Time Analysis:**
- Report percentiles: 50th (typical), 85th (most items finish by), 95th (nearly all items)
- Bi-modal detection: two distinct peaks in the cycle time distribution suggest two different types of work being mixed (e.g., bugs vs features)
- Trend over time: is cycle time improving, stable, or degrading?

**CFD (Cumulative Flow Diagram) Reading:**
- Band width = WIP in that state (wider = more WIP = likely bottleneck)
- Horizontal distance between bands = approximate lead time for that transition
- Vertical distance at any time point = throughput at that point
- Parallel bands = stable flow. Diverging bands = growing WIP (problem).

**WIP Limit Setting:**
- Start with current average WIP per state
- Reduce incrementally until queues form (expose bottlenecks)
- Common starting point: number of team members / 2

**Flow Efficiency:**
- Value-adding time / Total time x 100
- Typical for knowledge work: 15-40% (most time is spent waiting)
- Improving flow efficiency has more impact than improving speed

**Monte Carlo Forecasting:**
- When-will-it-be-done? Probabilistic answer using historical throughput
- Run N simulations using random samples from historical throughput
- Result: "There is an 85% chance we'll complete 30 items by March 15"
- Requires at least 10-15 data points for meaningful simulation

### Quality

**DoD Evolution:**
- Start simple (code review + tests pass + deployed to staging)
- Add criteria as team matures (security scan, performance test, documentation)
- DoD at three levels: story (individual work), sprint (collection), release (production-ready)

**Quality Gate Design:**
- Dev: unit tests, code review, static analysis
- Test/QA: integration tests, regression suite, exploratory testing
- Staging: performance testing, security scan, UAT
- Production: smoke tests, monitoring confirmed, rollback plan ready

**Tech Debt Management:**
- Reserve 15-20% of sprint capacity for tech debt reduction
- Quadrant model: Reckless/Prudent x Deliberate/Inadvertent
- Track in a register: item, quadrant, impact, effort, priority
- Pay down high-impact debt first (affects delivery speed or reliability)

**Defect Triage:**
- Severity: Critical (system down) > Major (key feature broken) > Minor (workaround exists) > Cosmetic
- Escaped defect analysis: where in the pipeline should this have been caught?
- Defect trend: increasing escaped defects = quality process gap

### Continuous Improvement

**Retro Format Selection:**
- **Start/Stop/Continue:** simple, good for new teams
- **4Ls (Liked, Learned, Lacked, Longed For):** good for mature teams wanting depth
- **Sailboat:** good for stuck teams (anchors = what holds us back, wind = what helps)
- **Timeline:** good after incidents or challenging sprints
- **Lean Coffee:** good for teams with many diverse topics
- **Mad/Sad/Glad:** good for emotional processing after difficult periods

**Improvement Backlog:**
- Treat improvements as first-class work items (not "nice to haves")
- Each retro produces at most 3 specific, owned improvement actions
- Track completion of improvement actions in the next retro
- If improvements never get done, something is structurally wrong

**Team Health Checks:**
- Spotify model: dimensions like Delivering Value, Speed, Mission, Fun, Learning, Process, Support
- Score each dimension 1-5 with trend arrows (improving, stable, declining)
- Focus on the declining dimensions, not just the low-scoring ones

**Value Stream Mapping:**
- Map the flow from idea to production
- Measure time spent in each step vs time spent waiting between steps
- Identify bottlenecks (longest wait times, not longest processing times)
- Typical waste: handoffs, approvals, context switching, rework

### SLA/SLO

Read `references/sla-slo-reference.md` for templates and calculations.

**SLI/SLO/SLA Hierarchy:**
- **SLI** (Service Level Indicator): the metric you measure (e.g., p99 latency, error rate)
- **SLO** (Service Level Objective): the target for the SLI (e.g., p99 < 200ms, error rate < 0.1%)
- **SLA** (Service Level Agreement): the contractual commitment with consequences (e.g., SLO + refund policy)

**Error Budget:**
- Error budget = 1 - SLO target (e.g., if SLO is 99.9%, error budget is 0.1%)
- When error budget is exhausted: freeze feature releases, focus on reliability
- Error budget policy: define what happens at 100%, 75%, 50% budget remaining

**Incident Impact on Delivery:**
- Calculate capacity lost to incident response
- Adjust sprint scope to account for incident time
- Track incident rate trend as a delivery health metric

---

## Integration Points

- **project-finance** -- for delivery cost analysis
- **presentation-builder** -- for delivery status decks
- **large-file-analysis** -- for analyzing Jira exports, work item data
- **project-manager** -- cross-reference for planning and governance artifacts

---

## Anti-Patterns

| Anti-Pattern | Why It's Wrong | Do This Instead |
|-------------|----------------|-----------------|
| Using velocity as a performance metric | Velocity is a planning tool, not a productivity measure | Use velocity for capacity planning only |
| Averaging cycle time | Averages hide bi-modal distributions and outliers | Always use percentiles (50th, 85th, 95th) |
| Retros without action items | Talk shop without change = waste | Every retro produces at most 3 specific, owned improvements |
| Infinite WIP | WIP without limits = everything started, nothing finished | Set WIP limits, enforce them |
| Skipping refinement | Unrefined work = planning chaos | Budget 10% of sprint capacity for refinement |
| SAFe for one team | Framework overhead without multi-team benefit | Use Scrum or Kanban for single teams |
| Estimating metrics instead of measuring | Invented numbers lead to bad decisions | Calculate from data or say "insufficient data" |
| Metrics without interpretation | Raw numbers without context are useless | Always include "so what?" with every metric |

---

## When NOT to Use This Skill

| Request | Use Instead |
|---------|-------------|
| Budget analysis, EVM, variance | `project-finance` |
| WBS, governance, change control | `project-manager` |
| Slide deck creation | `presentation-builder` |
| Technical implementation patterns | Domain-specific skill |
| General career advice | `career-coach` |

---

## Reference Files

Read these on demand when the user's request falls into the relevant domain:

- `~/.claude/skills/delivery-manager/references/agile-frameworks.md` -- Scrum/Kanban/SAFe/hybrid comparison, selection criteria, event cheat sheets
- `~/.claude/skills/delivery-manager/references/flow-metrics.md` -- cycle time, lead time, throughput, WIP, CFD, Little's Law, Monte Carlo
- `~/.claude/skills/delivery-manager/references/ceremony-playbooks.md` -- stand-up, planning, review, retro, refinement agendas and facilitation tips
- `~/.claude/skills/delivery-manager/references/quality-templates.md` -- DoD, acceptance criteria, quality gates, tech debt register
- `~/.claude/skills/delivery-manager/references/sla-slo-reference.md` -- SLI/SLO/SLA hierarchy, error budgets, availability nines, operational readiness
