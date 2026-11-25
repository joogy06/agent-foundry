# Forge reference — intake

Checklist steps 1, 3 and 5 — previous: none, a cycle starts here; next: step 6, design exploration.
When this file is read, return to the SKILL.md checklist.

The cycle-start block that opens Step 1 (`.forge/cycle-id`, `.forge/cycle-base`) is in SKILL.md, under "Step 1: Understanding (Lead Only)". Run it before anything in this file.

## Contents

- Skill Gap Detection — checklist step 5
- Understanding: what the lead does in Step 1 — checklist steps 1 and 3 (questions, performance, runtime and security branches)
- Large Project Decomposition and the Recursion Limit — checklist step 3

## Skill Gap Detection

After assessing complexity, identify what domain skills agents will need:

Follow gap-detection protocol at `~/.claude/skills/research-for-skills/gap-detection.md`

---

## Understanding: what the lead does in the first step

The lead handles all user interaction:
- Check current project state (files, docs, recent commits)
- Ask ONE bounded round of questions, bundled in one message (prefer multiple choice); material questions only — anything else, decide and note the assumption
- Focus on: purpose, non-goals, constraints, success criteria (the checkable done-when that becomes the DWs)
- **Performance expectations** (ask if task creates/modifies endpoints, queries, UI, or batch processes):
  - "Expected concurrency / data volume?"
  - "Latency requirements? (e.g., p95 < 200ms)"
  - "Is this on a hot path?"
  - "Existing performance budgets to respect?"
- **Runtime / observability branch** (ask once, not a full questionnaire):
  "Does this change runtime behavior, service boundaries, or SLOs?"
  - If YES: delegate full capacity questionnaire to `performance` skill
    (`references/capacity-questionnaire.md`), full signals-map drafting to
    `observability` skill, BEFORE design-team exploration. Capture the
    signals-map path + capacity answers into `shared_context` so design
    agents consume them as constraints.
  - If NO: skip. Existing performance-expectation questions still apply.
- **Security / threat-model branch** (ask once, not a full questionnaire):
  "Does this component process untrusted input, hold secrets/tokens, cross a
  trust boundary, OR consume content the LLM agent will read (prompts, tool
  results, wiki pages, mail, web)?"
  - If YES: capture into `shared_context.security_model`:
    (a) `trust_boundary` — what's inside vs outside the trust perimeter
    (b) `attacker_model` — who's the adversary, what can they touch
    (c) `sensitive_inputs` — PII / secrets / tokens / untrusted-from-network
    (d) `egress_destinations` — external systems reached
    Then delegate to `threat-modeling` skill for STRIDE / LINDDUN if high-stakes,
    AND to `llm-security` skill if the component is part of an agentic chain
    (prompt injection / OWASP LLM Top 10 defense — Dual LLM pattern where
    consequential tool use meets untrusted text). Design agents consume the
    security_model as constraints, the same way they consume capacity_answers.
  - If NO: skip. (Pure refactors, internal-only changes, no new input surface.)
- Determine complexity level

---

## Large Project Decomposition

Before asking detailed design questions, assess scope. If the request describes multiple independent subsystems (e.g., "build a platform with chat, file storage, billing, and analytics"):

1. **Flag immediately** — don't spend questions refining details of a project that needs decomposition
2. **Help decompose** — identify independent pieces, relationships, and build order
3. **Brainstorm first sub-project** — each sub-project gets its own forge cycle (design -> approval -> implementation)

### Recursion Limit

Forge tracks decomposition depth:
- depth=0: top-level task (default)
- depth=1: first sub-project from decomposition
- depth=2: sub-project of a sub-project — WARN user: "Deeply nested. Consider flattening."
- depth>=3: REFUSE to recurse. Present remaining work as a flat list for the user to prioritize.

When spawning a sub-project forge cycle, pass depth+1 in the prompt.
