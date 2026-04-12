# Codex Orchestration — Brief Templates

Ready-to-use templates for common Codex delegation scenarios. Copy and customize.

---

## Challenger Review Brief

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

cat > "$CODEX_WORK/brief-challenger.md" << 'BRIEF'
# Challenger Review Brief

## Context
[TASK DESCRIPTION + KEY CONSTRAINTS]
Project files at: [PROJECT_DIR]
Design document at: [DESIGN_DOC_PATH]

## Your Role
You are a devil's advocate / challenger. Find flaws in EVERY approach.
Focus on: scalability, security, maintainability, edge cases, operational complexity.

## Output Format
For each issue:
- **Severity**: critical / moderate / minor
- **What's wrong**: specific description
- **Why it matters**: impact if ignored
- **How to fix**: concrete recommendation

Rank overall design: strong / acceptable / needs-rework / reject.
BRIEF

timeout 120 codex exec --ephemeral -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/challenger.md" \
  "Read $CODEX_WORK/brief-challenger.md and execute the challenger review." \
  || echo "CODEX_TIMEOUT" > "$CODEX_WORK/challenger.md"
```

**Note:** Claude's "challenger" skill = Codex's "challenger-review" skill. Both provide the same framework from different model perspectives.

---

## Approach Explorer Brief

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

timeout 120 codex exec --ephemeral -C "$PROJECT_DIR" -s read-only \
  -o "$CODEX_WORK/approach.md" \
  "You are exploring approaches for [TASK].
Context: [KEY FILES, ARCHITECTURE, CONSTRAINTS]
Produce your top 2-3 recommended approaches with:
1. How it works  2. Pros/cons  3. Effort estimate  4. Risks
Be opinionated — recommend the best approach and explain why." \
  || echo "CODEX_TIMEOUT" > "$CODEX_WORK/approach.md"
```

---

## Research Brief

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

timeout 120 codex exec --ephemeral --skip-git-repo-check --search \
  -o "$CODEX_WORK/research.md" \
  "Research current best practices for [TECHNOLOGY/PATTERN] as of 2026.
Focus on:
1. Latest stable version and key features
2. Known limitations and gotchas
3. Community adoption and support
4. Comparison with alternatives
5. Production readiness assessment

Cite sources where possible." \
  || echo "CODEX_TIMEOUT" > "$CODEX_WORK/research.md"
```

---

## Escalation Brief (When Claude Is Stuck)

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

cat > "$CODEX_WORK/escalation-brief.md" << 'BRIEF'
# Escalation: Claude agents are stuck on [PROBLEM]

## What was tried
[LIST APPROACHES THAT FAILED AND WHY]

## The specific blocker
[DESCRIBE THE EXACT ISSUE]

## Project context
[KEY FILES, ARCHITECTURE]

## What we need
A fresh approach to solve this. Don't repeat what was already tried.
Think differently — challenge the assumptions that led to the dead end.
BRIEF

timeout 120 codex exec --ephemeral -C "$PROJECT_DIR" -s read-only --search \
  -o "$CODEX_WORK/escalation-result.md" \
  "Read $CODEX_WORK/escalation-brief.md and provide a fresh solution." \
  || echo "CODEX_TIMEOUT" > "$CODEX_WORK/escalation-result.md"
```

---

## Prototyping Brief

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)
mkdir -p "$CODEX_WORK/prototype"

codex exec --ephemeral \
  -C "$CODEX_WORK/prototype" \
  -s workspace-write \
  --full-auto \
  -o "$CODEX_WORK/prototype-summary.md" \
  "Create a minimal working prototype of [DESCRIPTION].
Write all files to the current directory.
After creating the prototype, summarize what you built and how to run it."

# Claude can then review the prototype
# Read: $CODEX_WORK/prototype-summary.md
# Glob: $CODEX_WORK/prototype/**/*
```

---

## Code Review Brief

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# Built-in review command
codex review --uncommitted \
  -o "$CODEX_WORK/review-result.md"

# Or review against a branch
codex review --base main \
  -o "$CODEX_WORK/review-result.md"

# Custom review with specific focus
codex review --uncommitted \
  "Focus on: security vulnerabilities, error handling gaps, and performance anti-patterns. Ignore style issues." \
  -o "$CODEX_WORK/review-result.md"
```

---

## Structured Output Brief

```bash
CODEX_WORK=$(mktemp -d /tmp/codex-XXXXXXXXXX)

# Create a JSON schema for structured responses
cat > "$CODEX_WORK/schema.json" << 'EOF'
{
  "type": "object",
  "properties": {
    "summary": { "type": "string" },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "topic": { "type": "string" },
          "assessment": { "type": "string" },
          "confidence": { "type": "string", "enum": ["high", "medium", "low"] }
        }
      }
    },
    "recommendation": { "type": "string" }
  }
}
EOF

codex exec --ephemeral --skip-git-repo-check \
  --output-schema "$CODEX_WORK/schema.json" \
  -o "$CODEX_WORK/structured.json" \
  "[YOUR PROMPT HERE]"
```
