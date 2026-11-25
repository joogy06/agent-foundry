# Agent Teams — coordination file formats

Read this file at Step 4, before writing `.forge/contracts.md`, `.forge/deps.md` or `.forge/session_control.md`, and at Step 5, before the first inbox write or outbox read. When it is read, return to that step in SKILL.md.

The `.forge/` directory layout is in SKILL.md, Step 4. The BLOCKED reasons a team lead may write to its outbox, and how each one is routed, are in SKILL.md, Step 6.

### contracts.md

Pre-populate with ALL known interface contracts between teams:

```markdown
# Interface Contracts

## [Contract Name] (owner: Team-{id}, work_package: {id})
Status: DRAFT | PUBLISHED
```typescript
// The interface definition
```
Consumers: Team-{id}, Team-{id}
```

### deps.md

```markdown
# Cross-Team Dependencies

| ID | From (needs) | Provider | Artifact | Status |
|----|-------------|----------|----------|--------|
| DEP-001 | Team-A:WP-003 | Team-B:WP-007 | User model | WAITING |
```

### session_control.md

```markdown
# File Ownership

| File/Directory | Owner | Status |
|---------------|-------|--------|
| src/auth/** | Team-A | ACTIVE |
| src/models/** | Team-B | ACTIVE |
| src/routes/** | Team-C | ACTIVE |
```

### Write Ownership Rules

| File | Writer | Readers |
|------|--------|---------|
| contracts.md | You only | All teams |
| deps.md | You only | All teams |
| team-X/manifest.md | You (at spawn) | Team-X |
| team-X/inbox.md | You only | Team-X lead |
| team-X/outbox.md | Team-X lead only | You |
| session_control.md | You (setup), team leads (claim/release) | All |

### Outbox Format (team leads write this)

```markdown
## [HH:MM:SS] STATUS_UPDATE
task_id: {id}
status: COMPLETE | IN_PROGRESS | BLOCKED
artifact: {file path if applicable}
summary: {1-2 sentences}
cross_team_note: {any published interface or dependency need}

## [HH:MM:SS] TEAM_COMPLETE
tasks_completed: {N}/{total}
artifacts: {list of file paths}
decisions_made: {key decisions}
```

### Inbox Format (you write this)

```markdown
## [HH:MM:SS] DEPENDENCY_RESOLVED
from_team: {id}
artifact: {description}
location: see contracts.md section "{name}"
action: unblock task {id}

## [HH:MM:SS] PRIORITY_CHANGE
reason: {why}
action: {what the team should do differently}
```
