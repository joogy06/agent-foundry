# Codex Orchestration — Handover Patterns & Advanced Usage

Reference file for advanced Codex integration patterns. Load when needed — the core SKILL.md has the essentials.

---

## Handover Patterns via Session-Scoped Temp Directories

### Pattern 1: Claude → Codex → Claude (Simple)

```
1. CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
2. Claude writes context to $CODEX_WORK/task.md
3. Claude calls: codex exec --ephemeral -o "$CODEX_WORK/result.md" \
     "Read $CODEX_WORK/task.md and follow the instructions inside"
4. Claude reads $CODEX_WORK/result.md
5. Claude integrates findings into its response
```

### Pattern 2: Structured Handover (Complex Tasks)

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# Step 1: Claude writes a task brief
cat > "$CODEX_WORK/brief-challenger.md" << 'BRIEF'
# Challenger Review Brief

## Context
We are designing a Docker-based deployment for a Node.js API with PostgreSQL and Redis.
The design document is at: /path/to/project/docs/plans/2026-03-24-api-design.md

## Your Role
You are a devil's advocate / challenger. Your job is to find flaws, question assumptions,
and stress-test this design.

## Focus Areas
1. Single points of failure
2. Data persistence risks
3. Scaling bottlenecks
4. Security gaps
5. Operational complexity

## Output Format
For each issue found:
- **Severity**: critical / moderate / minor
- **Component**: which part of the design
- **Issue**: what's wrong
- **Impact**: what happens if ignored
- **Recommendation**: how to fix

Write your findings to this file, replacing its contents.
BRIEF

# Step 2: Codex processes the brief
codex exec --ephemeral -C /path/to/project \
  -s read-only \
  -o "$CODEX_WORK/challenger-result.md" \
  "Read $CODEX_WORK/brief-challenger.md and execute the challenger review described within. Read any files referenced in the brief."

# Step 3: Claude reads the result
# Read: $CODEX_WORK/challenger-result.md
```

### Pattern 3: Parallel Codex Tasks

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# Launch multiple Codex tasks simultaneously using background processes
# Each writes to its own output file

# Task 1: Research
codex exec --ephemeral --skip-git-repo-check \
  -o "$CODEX_WORK/research.md" \
  "Research best practices for PostgreSQL connection pooling with PgBouncer" &
PID1=$!

# Task 2: Code review
codex exec --ephemeral -C /path/to/project \
  -s read-only \
  -o "$CODEX_WORK/review.md" \
  "Review src/database.ts for connection leak risks and suggest fixes" &
PID2=$!

# Task 3: Idea generation
codex exec --ephemeral --skip-git-repo-check --search \
  -o "$CODEX_WORK/ideas.md" \
  "Generate 5 alternative approaches to rate limiting in a Node.js API. Include pros/cons." &
PID3=$!

# Wait for all to complete
wait $PID1 $PID2 $PID3

# Read all results
# Read: $CODEX_WORK/research.md
# Read: $CODEX_WORK/review.md
# Read: $CODEX_WORK/ideas.md
```

---

## Progress Tracking

### For Long-Running Tasks

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# Use --json to monitor progress in real time
codex exec --ephemeral --skip-git-repo-check --json \
  -C /path/to/project \
  "Comprehensive security audit of this project" \
  2>/dev/null > "$CODEX_WORK/audit-events.jsonl" &
CODEX_PID=$!

# Monitor progress (from Claude Code or another terminal)
# Check if still running:
kill -0 $CODEX_PID 2>/dev/null && echo "Running" || echo "Done"

# Check events so far:
wc -l "$CODEX_WORK/audit-events.jsonl"              # event count
tail -1 "$CODEX_WORK/audit-events.jsonl" | jq .     # latest event

# Extract messages received so far:
jq -r 'select(.type=="item.completed") | .item.text' \
  "$CODEX_WORK/audit-events.jsonl"

# Get token usage:
jq 'select(.type=="turn.completed") | .usage' \
  "$CODEX_WORK/audit-events.jsonl"
```

### Progress File Convention

```bash
# Reuse $CODEX_WORK from the long-running task block above, or create a new one:
# CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# For multi-step tasks, have Codex write progress to a tracking file
cat > "$CODEX_WORK/task-progress.md" << 'EOF'
# Task: Security Audit
Status: pending
Steps:
- [ ] Dependency scan
- [ ] Code analysis
- [ ] Config review
- [ ] Findings summary
EOF

# In the Codex prompt, instruct it to update the progress file:
codex exec --ephemeral -C /path/to/project \
  -s workspace-write \
  --add-dir "$CODEX_WORK" \
  -o "$CODEX_WORK/audit-result.md" \
  "Perform a security audit. Update $CODEX_WORK/task-progress.md after completing each step. Mark steps with [x] as you go."
```

---

## Skill Injection Pattern

For critical tasks where Codex MUST apply specific skill knowledge, inject the skill content directly into the brief. This guarantees Codex reads it (rather than hoping it discovers the symlinked file).

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# Inject skill into brief for guaranteed context
SKILL_CONTENT=$(cat ~/.claude/skills/woocommerce-developer/SKILL.md)

cat > "$CODEX_WORK/brief-woo-review.md" << BRIEF
# Task: WooCommerce Code Review

## Skill Reference (MUST follow these patterns)
$SKILL_CONTENT

## Your Task
Review the following WooCommerce customization for security and best practices.
Project: $PROJECT_DIR
Files to review: wp-content/themes/flavor-child/functions.php
BRIEF

cat "$CODEX_WORK/brief-woo-review.md" | codex exec --ephemeral \
  -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/woo-review.md" -
```

### When to Inject vs Let Codex Discover

| Inject skill into brief | Let Codex use symlinked skill |
|---|---|
| Security-critical reviews (WooCommerce, auth) | General research tasks |
| Challenger reviews needing domain rules | Broad exploration / brainstorming |
| Tasks where wrong patterns = vulnerabilities | Code review with `codex review` |
| Specific coding standards must be followed | Idea generation |

### Multi-Skill Injection (for complex tasks)

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# Combine multiple skills into one brief
cat > "$CODEX_WORK/brief-complex.md" << 'HEADER'
# Task: Full-Stack WooCommerce Review
## Required Skills (follow ALL rules below)
HEADER

echo "### WooCommerce Developer Patterns" >> "$CODEX_WORK/brief-complex.md"
cat ~/.claude/skills/woocommerce-developer/SKILL.md >> "$CODEX_WORK/brief-complex.md"
echo -e "\n### WordPress Security & Admin" >> "$CODEX_WORK/brief-complex.md"
cat ~/.claude/skills/wordpress-admin/SKILL.md >> "$CODEX_WORK/brief-complex.md"
echo -e "\n### Hostinger Hosting Context" >> "$CODEX_WORK/brief-complex.md"
cat ~/.claude/skills/hostinger-hosting/SKILL.md >> "$CODEX_WORK/brief-complex.md"

cat >> "$CODEX_WORK/brief-complex.md" << 'TASK'

## Your Task
Review the WordPress site at $PROJECT_DIR for security hardening,
WooCommerce best practices, and Hostinger-specific optimizations.
TASK

cat "$CODEX_WORK/brief-complex.md" | codex exec --ephemeral \
  -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/complex-review.md" -
```

---

## Codex as MCP Server

Codex can also run as an MCP server, allowing Claude Code to call it via MCP tools:

```bash
# Start Codex as MCP server (for use in Claude Code's .claude/settings.json)
codex mcp-server
```

Add to Claude Code settings:
```json
{
  "mcpServers": {
    "codex": {
      "command": "codex",
      "args": ["mcp-server"]
    }
  }
}
```

This gives Claude Code a `codex` MCP tool for delegation — but `codex exec` via Bash is more flexible for orchestration since it supports output files, JSON streaming, and parallel execution.

---

## Temp File Naming Convention

```bash
# Create a session-scoped directory for all Codex outputs
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
# e.g. /tmp/codex-a1b2c3d4e5

# All files go under $CODEX_WORK/ with descriptive names:
$CODEX_WORK/research.md              # Research task output
$CODEX_WORK/challenger-result.md     # Challenger review result
$CODEX_WORK/review-result.md         # Code review result
$CODEX_WORK/prototype-summary.md     # Prototype summary
$CODEX_WORK/ideas.md                 # Idea generation
$CODEX_WORK/schema.json              # Structured output schema
$CODEX_WORK/events.jsonl             # JSONL event stream
$CODEX_WORK/task-progress.md         # Progress tracking file
$CODEX_WORK/brief-challenger.md      # Task brief for Codex
$CODEX_WORK/forge-research.md        # Forge research output
$CODEX_WORK/prototype/               # Prototype working directory
```

### Cleanup

```bash
# Clean up the entire session directory after task completion
rm -rf "$CODEX_WORK"

# Or keep for user reference and note the location
echo "Codex outputs saved in $CODEX_WORK"
```
