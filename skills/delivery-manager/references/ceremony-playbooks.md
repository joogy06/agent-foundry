# Ceremony Playbooks Reference

Agenda templates, timebox guidelines, facilitation tips, and anti-pattern warnings for Agile ceremonies.

---

## Daily Stand-up

**Purpose:** Inspect progress toward the sprint goal and adapt the plan for the day.

### Agenda (15 minutes max)

**Walk-the-board format (recommended over round-robin):**
1. Start from the rightmost column (closest to Done)
2. For each item on the board:
   - Is it blocked? What's needed to unblock?
   - Can it move forward today? Who's working on it?
3. After the board walk: anything not on the board that the team should know?
4. Parking lot: topics that need discussion go to after-standup or dedicated sessions

### Timebox by Team Size

| Team Size | Target Duration |
|-----------|----------------|
| 3-5 | 8-10 minutes |
| 6-8 | 12-15 minutes |
| 9+ | 15 minutes (strict) |

### Facilitation Tips
- Stand up (literally) to keep it short
- Use a physical or digital board -- walk it, don't use it as decoration
- If a topic needs >2 minutes of discussion, park it for after
- Rotate the facilitator role to build team ownership
- The stand-up is for the team, not for management reporting

### Anti-Patterns
- **Round-robin status reports**: "Yesterday I... Today I..." is low-value. Walk the board instead.
- **Problem-solving in stand-up**: Deep discussions delay the whole team. Park and follow up.
- **Manager-directed updates**: Team members reporting to the manager, not each other.
- **Missing team members**: If people regularly skip, the stand-up isn't providing value to them.

---

## Sprint Planning

**Purpose:** Define the sprint goal, select backlog items, and create a plan for delivering them.

### Agenda

| Phase | Activity | Time Allocation |
|-------|----------|----------------|
| 1 | **Sprint Goal** -- PO proposes the sprint goal. Team discusses and aligns. | 10% |
| 2 | **What** -- PO presents top backlog items. Team asks questions, clarifies acceptance criteria. | 25% |
| 3 | **How Much** -- Team selects items based on capacity/velocity. Explicit commitment. | 20% |
| 4 | **How** -- Team breaks items into tasks, identifies dependencies, creates a plan. | 35% |
| 5 | **Confidence Check** -- Team confirms commitment. Raise concerns now. | 10% |

### Timebox by Sprint Length

| Sprint Length | Planning Timebox |
|--------------|-----------------|
| 1 week | 2 hours |
| 2 weeks | 4 hours |
| 3 weeks | 6 hours |
| 4 weeks | 8 hours |

### Facilitation Tips
- Sprint goal first -- it provides focus for item selection
- Only plan items the team has refined (INVEST-ready with acceptance criteria)
- Use historical velocity as a guide, not a target
- If the team cannot fill the sprint, pull from the refined backlog in priority order
- End with an explicit confidence vote (fist of five: 1 = no way, 5 = very confident)

### Anti-Patterns
- **No sprint goal**: items without a unifying goal = a to-do list, not a sprint
- **PO dictates scope**: team must own the commitment
- **Planning unrefined items**: leads to mid-sprint discovery and churn
- **Over-committing**: taking more than velocity suggests to please stakeholders

---

## Sprint Review (Demo)

**Purpose:** Inspect the increment, gather stakeholder feedback, and adapt the product backlog.

### Agenda

| Phase | Activity | Time Allocation |
|-------|----------|----------------|
| 1 | **Context** -- Sprint goal, what was planned vs delivered | 10% |
| 2 | **Demo** -- Show working software. Live demo, not slides. | 50% |
| 3 | **Feedback** -- Stakeholders ask questions, provide input | 25% |
| 4 | **Backlog Update** -- PO adapts backlog based on feedback | 15% |

### Timebox by Sprint Length

| Sprint Length | Review Timebox |
|--------------|---------------|
| 1 week | 1 hour |
| 2 weeks | 2 hours |
| 3 weeks | 3 hours |
| 4 weeks | 4 hours |

### Facilitation Tips
- Demo working software, not slides or mockups
- Invite real stakeholders -- their feedback is the whole point
- Let the people who built it demonstrate it (builds pride and direct feedback)
- Capture feedback visibly (whiteboard, shared doc) so nothing is lost
- End with clear next steps: what feedback will be actioned?

### Anti-Patterns
- **No stakeholders present**: review without feedback = wasted ceremony
- **Slide deck instead of demo**: shows process, not product
- **Only showing happy path**: include edge cases and known limitations
- **Feedback ignored**: if feedback never appears in the backlog, stakeholders stop coming

---

## Retrospective

**Purpose:** Inspect the team's process and create a plan for improvement.

### Six Retrospective Formats

#### 1. Start/Stop/Continue
**Best for:** New teams, simple format, low facilitation skill needed.

```
Three columns:
  START: What should we start doing?
  STOP: What should we stop doing?
  CONTINUE: What's working well and should continue?

Process:
  1. Silent brainstorm (5 min) -- sticky notes
  2. Share and cluster (10 min)
  3. Dot vote on most important items (3 min)
  4. Discuss top 3 (15 min)
  5. Commit to actions (5 min)
```

#### 2. 4Ls (Liked, Learned, Lacked, Longed For)
**Best for:** Mature teams wanting deeper reflection.

```
Four quadrants:
  LIKED: What did we enjoy?
  LEARNED: What did we learn?
  LACKED: What was missing?
  LONGED FOR: What do we wish we had?
```

#### 3. Sailboat
**Best for:** Stuck teams, visual metaphor helps surface issues.

```
Visual elements:
  ISLAND: Our goal / where we want to be
  WIND: What's pushing us forward
  ANCHORS: What's holding us back
  ROCKS: Risks ahead

Process: Draw the sailboat, add sticky notes to each element.
```

#### 4. Timeline
**Best for:** After incidents or challenging sprints.

```
Draw a horizontal timeline of the sprint.
Team adds events/moments on the timeline.
Categorize each as positive (above line) or negative (below line).
Discuss patterns and turning points.
```

#### 5. Lean Coffee
**Best for:** Teams with many diverse topics to discuss.

```
1. Everyone writes topics on cards (3 min)
2. Group briefly explains each topic (1 min each)
3. Dot vote to prioritize (2 min)
4. Discuss in priority order, 5 min per topic
5. At 5 min: thumbs up/down to continue or move on
```

#### 6. Mad/Sad/Glad
**Best for:** Emotional processing after difficult periods.

```
Three columns:
  MAD: What frustrated us?
  SAD: What disappointed us?
  GLAD: What made us happy?

Focus on feelings first, then identify actionable patterns.
```

### Retro Timebox by Sprint Length

| Sprint Length | Retro Timebox |
|--------------|--------------|
| 1 week | 45 minutes |
| 2 weeks | 1.5 hours |
| 3 weeks | 2 hours |
| 4 weeks | 3 hours |

### Facilitation Tips
- **Safety first**: if people don't feel safe, they won't share honestly. Check the room.
- **Rotate formats**: using the same format every sprint leads to stale retros.
- **Review previous actions first**: did we complete last retro's improvements? If not, why?
- **Maximum 3 actions**: more than 3 never get done. Pick the most impactful.
- **Owner and deadline for each action**: "we should improve X" is not an action. "Pat will do X by Friday" is.
- **No blame**: retros are about process improvement, not finding fault.

### Anti-Patterns
- **Skipping retros**: the team loses its primary improvement mechanism
- **No actions**: talking without committing to change = waste
- **Same format every time**: leads to disengagement
- **Manager present and dominating**: team members self-censor
- **Actions never reviewed**: team stops believing retros produce change

---

## Backlog Refinement

**Purpose:** Prepare backlog items so they are ready for sprint planning.

### Agenda (ongoing, not a single event)

| Activity | Purpose | Time |
|----------|---------|------|
| PO presents upcoming items | Context and priority | 5 min per item |
| Team asks clarifying questions | Understanding | 5 min per item |
| Team reviews acceptance criteria | Quality and completeness | 3 min per item |
| Story splitting (if needed) | Right-sizing | 5 min per item |
| Estimation (if used) | Planning data | 3 min per item |

### Guidelines
- Budget 10% of sprint capacity for refinement
- Refine 1-2 sprints ahead (not more -- waste if priorities change)
- Use INVEST criteria to assess readiness: Independent, Negotiable, Valuable, Estimable, Small, Testable
- An item is "ready" when the team can explain what it does, how to test it, and estimate it

### Story Splitting Patterns

| Pattern | Example | When to Use |
|---------|---------|-------------|
| Workflow steps | "As a user, I can submit" vs "As a user, I can edit before submit" | Multi-step processes |
| Business rules | "Basic validation" vs "Complex validation" | Multiple rules in one story |
| Data variations | "Process CSV" vs "Process Excel" | Multiple input formats |
| Interface | "API endpoint" vs "UI form" | Multiple interfaces to the same feature |
| Spike | "Research X (timebox: 2 days)" then "Implement X" | High uncertainty |
