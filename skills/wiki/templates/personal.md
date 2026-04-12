# Personal Domain Template

Master template for personal knowledge wikis: goals, habits, journal, health, self-model, reviews, people, systems. Zettelkasten-adjacent second-brain setup.

**Template version**: personal-v1
**Best for**: personal knowledge management, life logs, habit tracking, personal retrospectives, self-directed learning.

---

## Directory Structure

```
<wiki-root>/
  WIKI.md
  index.md
  log.md
  raw/
    images/
    <YYYY-MM-DD>-<slug>.md                 # journal, notes
    <YYYY-MM-DD>-<slug>.pdf                 # books, articles saved
    <YYYY-MM-DD>-<slug>-health.csv          # health exports
  wiki/
    goals/
    habits/
    journal/          # Daily/weekly notes
    health/
    self-model/       # Values, strengths, learning styles
    reviews/          # Weekly, monthly, quarterly, annual
    people/           # Relationships and connections
    resources/        # Books, courses, tools
    systems/          # Routines, workflows
    values/
  _templates/
    goal.md
    habit.md
    journal.md
    health-log.md
    self-model.md
    review.md
    person.md
    resource.md
    system.md
    value.md
  _maintenance/
    link-index.md
    tag-registry.md
    lint-history.jsonl
    source-manifest.yaml
```

---

## Page Types

| Type | Purpose | Required Frontmatter | Template |
|------|---------|---------------------|----------|
| `goal` | One goal with target + milestones | target_date, status, milestones | `goal.md` |
| `habit` | One habit to track | frequency, start_date, streak | `habit.md` |
| `journal` | Daily/weekly free-form entry | entry_date, mood (optional) | `journal.md` |
| `health-log` | Structured health data | metric, date, value, unit | `health-log.md` |
| `self-model` | Values, strengths, learning style | dimension (values/strengths/style) | `self-model.md` |
| `review` | Retrospective | period (weekly/monthly/quarterly/annual), date_start, date_end | `review.md` |
| `person` | Someone in your network | relationship, last_contact | `person.md` |
| `resource` | Book, course, tool | resource_kind, status (unread/reading/read) | `resource.md` |
| `system` | A routine or workflow | trigger, steps, frequency | `system.md` |
| `value` | A personal value | description, examples | `value.md` |

---

## Frontmatter Schema (Personal Extensions)

```yaml
---
# Base fields (always required)
type: goal
title: "Run a half marathon in 2026"
slug: half-marathon-2026
created: 2026-04-07
updated: 2026-04-07
sources: []
tags: [running, fitness-2026]
status: active
confidence: high

# Personal extensions (vary by type)
target_date: 2026-10-15
progress: 0.25           # 0.0 to 1.0
milestones:
  - date: 2026-05-01
    description: "Run 10k without stopping"
    done: false
priority: medium         # low|medium|high
related: [running-habit, fitness-2026-plan]

# For habits
# frequency: daily       # daily|weekly|monthly
# streak: 12
# longest_streak: 45
# started_on: 2026-01-15
# cue: "after morning coffee"

# For journal
# entry_date: 2026-04-07
# mood: reflective       # open enum
# highlights: ["long walk", "good conversation"]

# For reviews
# period: weekly         # weekly|monthly|quarterly|annual
# date_start: 2026-04-01
# date_end: 2026-04-07
---
```

---

## Cross-Referencing Conventions

- `[[goal-slug]]` when a journal entry or review mentions progress
- `[[habit-slug]]` in journal entries when a habit is performed
- `[[person-slug]]` when mentioning someone
- `[[value-slug]]` when a decision references a personal value
- Reviews list all goals/habits they touch in `related`

---

## Naming Conventions

- **Goals**: descriptive kebab-case with year if time-bound (`half-marathon-2026`)
- **Habits**: `<verb-noun>-habit` (`read-daily-habit`, `meditate-habit`)
- **Journal**: `<YYYY-MM-DD>-journal` or `<YYYY-WW>-weekly-journal`
- **Reviews**: `review-<YYYY-WW>` (weekly), `review-<YYYY-MM>` (monthly), `review-<YYYY>` (annual)
- **People**: first-name-last-initial (`alice-s`) to avoid collisions while respecting privacy
- **Resources**: `<title-slug>` for books/courses, `<tool-name>` for tools

---

## Output Formats

**Citations**: `[Source: raw/2026-04-07-book-atomic-habits.pdf, p.42]` — still required for claims, even in personal wikis (self-hallucination still corrupts a second brain)
**Mermaid defaults**:
- `mindmap` — self-model, values hierarchy
- `gantt` — goal timelines
- `pie` — habit streak charts, time allocation
- `timeline` — life events, quarterly reviews

---

## Maintenance Workflows

- **Lint frequency**: weekly (or after each journal batch)
- **Staleness thresholds**: journal entries never stale (historical); goals stale when past `target_date` without status update; habits stale if no entries in 7 days
- **Archive**: completed goals -> `status: archived`, stays in index under "Completed Goals" section

---

## Obsidian Compatibility Notes

Personal template maps very cleanly to Obsidian:
- Dataview: "all active goals", "habit streaks", "journal entries this week"
- Daily notes plugin: use for journal template
- Templater plugin: auto-fill journal frontmatter

---

## Example Pages

### Example: goal

```markdown
---
type: goal
title: "Run a half marathon in 2026"
slug: half-marathon-2026
target_date: 2026-10-15
status: active
progress: 0.25
sources: []
tags: [running, fitness-2026]
confidence: high
related: [running-habit, fitness-2026-plan]
milestones:
  - date: 2026-05-01
    description: "Run 10k without stopping"
    done: false
  - date: 2026-07-01
    description: "Run 15k at race pace"
    done: false
---

# Half Marathon 2026

Run a half marathon by October 15, 2026, targeting sub-2:00 finish time.

## Why

Fitness maintenance + accountability milestone for the year.

## Plan

See [[running-habit]] for daily practice and [[fitness-2026-plan]] for the overall program.

## Progress Log

- 2026-04-07: Completed 8k long run at easy pace — [[journal/2026-04-07-journal]]
```

### Example: habit

```markdown
---
type: habit
title: "Read 30 minutes daily"
slug: read-daily-habit
frequency: daily
start_date: 2026-01-15
streak: 12
longest_streak: 45
status: active
sources: []
tags: [reading, discipline]
confidence: high
cue: "after dinner, before phone"
related: [resources/atomic-habits, resources/deep-work]
---

# Read 30 Minutes Daily

A daily habit to read physical books for at least 30 minutes, cued after dinner.

## Current streak: 12 days

## Why

Protects deep work capacity, reduces phone-first evenings.

## See Also

- [[resources/atomic-habits]] — "Make it obvious, attractive, easy, satisfying" framework inspired this habit
```

---

## Anti-Patterns (Personal Domain)

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Stream-of-consciousness journal without frontmatter | Breaks lint, can't be queried by date/mood/tag | Always include `entry_date` and `type: journal` frontmatter |
| Setting goals without `target_date` | Goals drift indefinitely, accountability breaks | Require `target_date` field — even approximate |
| Tracking habits without a `cue` | Habits without triggers fail to form (Atomic Habits research) | Document the cue in frontmatter, adjust if habit stalls |
| Not linking journal to goals/habits | Reflective loop broken, progress invisible | Journal entries list affected goals/habits in `related` |
| Mixing private info with shareable wiki content | Privacy leak risk if wiki is ever shared | Use `visibility: private` + keep personal wikis in `~/wikis/` (not `.wiki/` in shared projects) |
