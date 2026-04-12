# Flow Metrics Reference

Metric definitions, formulas, measurement points, Little's Law, Monte Carlo forecasting, and percentile interpretation.

---

## Metric Definitions

| Metric | Definition | Measurement Points | Unit |
|--------|-----------|-------------------|------|
| **Cycle Time** | Time from when work starts to when it finishes | Start: item moves to "In Progress". End: item moves to "Done" | Days |
| **Lead Time** | Time from when work is requested to when it is delivered | Start: item enters backlog or is created. End: item moves to "Done" | Days |
| **Throughput** | Number of items completed per time period | Count items moving to "Done" per sprint/week/month | Items/period |
| **WIP** | Number of items currently in progress (started but not finished) | Count items between "In Progress" and "Done" at a point in time | Items |
| **Flow Efficiency** | Ratio of value-adding time to total elapsed time | (Active work time) / (Total lead time) x 100 | Percentage |

### Measurement Point Definitions

Be precise about what "started" and "finished" mean in your team's context:

| Team's Process | "Started" = | "Finished" = |
|----------------|------------|-------------|
| Software dev | Moves to In Progress / In Dev | Deployed to production |
| Software dev (sprint) | Moves to In Progress | Accepted in sprint review |
| Support team | Assigned to agent | Resolution confirmed |
| Design team | Design started | Design approved by stakeholder |

---

## Formulas

### Little's Law

```
Average Lead Time = Average WIP / Average Throughput
```

**Implications:**
- To reduce lead time: reduce WIP OR increase throughput
- Increasing WIP almost never increases throughput -- it increases lead time
- This is mathematically proven for stable systems (arrivals ≈ departures)

**Worked example:**
- Team averages 8 items in progress (WIP)
- Team completes 4 items per week (Throughput)
- Average Lead Time = 8 / 4 = 2 weeks
- If WIP drops to 4: Lead Time = 4 / 4 = 1 week (50% faster delivery)

### Cycle Time Percentiles

```
Given a set of cycle times [2, 3, 3, 4, 5, 5, 7, 8, 12, 15]:
  Sort ascending: [2, 3, 3, 4, 5, 5, 7, 8, 12, 15]
  50th percentile (median): 5 days    -- "typical" item
  85th percentile: 12 days            -- "most items finish within"
  95th percentile: 15 days            -- "nearly all items finish within"
```

**Why percentiles over averages:**
- Average of above: 6.4 days
- Average hides the fact that 20% of items take >8 days
- 85th percentile is the recommended SLA target for Kanban teams

### Throughput Calculation

```
Throughput = Items completed in period / Period length

Weekly throughput example:
  Week 1: 5 items, Week 2: 3 items, Week 3: 6 items, Week 4: 4 items
  Average: 4.5 items/week
  Std Dev: 1.3 items/week
```

### Flow Efficiency

```
Flow Efficiency = Active Work Time / Total Lead Time x 100

Example:
  Item lead time: 10 days
  Time actively worked on: 2 days
  Time waiting (in queue, blocked, etc.): 8 days
  Flow Efficiency = 2 / 10 x 100 = 20%
```

Typical benchmarks (knowledge work):
- 15%: common but poor
- 25%: average
- 40%: good
- 60%+: excellent (rare)

---

## Monte Carlo Forecasting (Simplified)

When-will-it-be-done? Use historical throughput to simulate possible outcomes.

### Method

```
1. Collect daily/weekly throughput history (at least 10-15 data points)
2. For each simulation run (N = 1000+):
   a. Randomly sample from historical throughput values (with replacement)
   b. Sum sampled values until total >= remaining items
   c. Record how many periods it took
3. Sort the results
4. Read off percentiles:
   - 50th percentile: "There's a 50% chance we'll finish by this date"
   - 85th percentile: "There's an 85% chance we'll finish by this date"
   - 95th percentile: "There's a 95% chance we'll finish by this date"
```

### Example

```
Historical weekly throughput: [3, 5, 4, 6, 3, 5, 4, 7, 3, 4, 5, 6]
Remaining items: 20

After 1000 simulations:
  50th percentile: 4 weeks (finish by April 15)
  85th percentile: 5 weeks (finish by April 22)
  95th percentile: 6 weeks (finish by April 29)

Recommendation: "Plan for April 22 (85% confidence).
If a hard deadline is needed, use April 29 (95% confidence)."
```

### Confidence Levels

| Percentile | Use For | Risk Level |
|------------|---------|------------|
| 50th | Internal planning targets | High risk (coin flip) |
| 70th | Team commitments | Moderate risk |
| 85th | External commitments, SLAs | Low risk (recommended) |
| 95th | Contractual deadlines | Very low risk |

---

## CFD (Cumulative Flow Diagram) Reading Guide

```
Items
  ^
  |           ___________  Done
  |         _/
  |       _/  ___________  In Review
  |     _/  _/
  |   _/  _/  ___________  In Progress
  |  /  _/  _/
  | / _/  _/  ___________  Backlog
  |/_/  _/  _/
  +---/--/--/-----------> Time
```

### What to Look For

| Pattern | What It Means | Action |
|---------|--------------|--------|
| Bands are roughly parallel | Stable flow | Good -- maintain current WIP |
| A band is widening | WIP increasing in that state (items accumulating) | Bottleneck. Reduce input or add capacity to that state |
| A band is narrowing | WIP decreasing (draining) | Possibly starving downstream. Check if upstream is blocked |
| Horizontal gap between bands | Lead time for that transition | Large gaps = long wait times. Investigate why |
| All bands flat | No items moving through the system | System is stalled. Major blocker or no demand |
| Steep "Done" line | High throughput period | Identify what went well, try to replicate |

---

## Velocity Guidelines

Velocity = story points completed per sprint. **Planning tool only, not a performance metric.**

### Healthy Velocity Patterns

| Pattern | Interpretation |
|---------|---------------|
| Stable (within 20% variance sprint to sprint) | Good for planning. Team is predictable. |
| Gradually increasing | Team is improving (or inflating estimates -- verify) |
| Gradually decreasing | Potential concern: increasing tech debt, scope creep, team issues |
| Highly variable (>30% variance) | Unreliable for planning. Investigate root cause. |
| Sudden drop | One-time event (holiday, incident, missing team member) or process problem |

### Velocity Anti-Patterns

- Comparing velocity between teams (meaningless -- different estimation calibration)
- Using velocity as a KPI or target (Goodhart's Law: when a measure becomes a target, it ceases to be a good measure)
- Increasing velocity by inflating estimates (gamed metric = no value)

---

## Metric Reporting Template

```markdown
## Delivery Metrics Report -- [Team Name] -- [Period]

### Flow Health
| Metric | Value | Trend | Interpretation |
|--------|-------|-------|---------------|
| Throughput | X items/sprint | [up/stable/down] | [so what?] |
| Cycle Time (50th) | X days | [up/stable/down] | [so what?] |
| Cycle Time (85th) | X days | [up/stable/down] | [so what?] |
| WIP | X items | [up/stable/down] | [so what?] |
| Flow Efficiency | X% | [up/stable/down] | [so what?] |

### Sprint/Iteration Summary (if applicable)
| Metric | Value |
|--------|-------|
| Velocity | X points |
| Sprint Goal met? | Yes/No |
| Items committed | X |
| Items completed | X |
| Completion rate | X% |

### Forecast
Using Monte Carlo on last [N] sprints of throughput:
- Remaining items: X
- 50% confidence: [date]
- 85% confidence: [date]
- 95% confidence: [date]

### Observations and Actions
1. [Observation with data] --> [recommended action]
2. [Observation with data] --> [recommended action]
```
