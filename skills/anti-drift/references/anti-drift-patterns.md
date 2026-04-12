# Anti-drift patterns — techniques that work (April 2026)

## Pattern 1: Recency anchoring

**What**: Place critical rules at the END of prompts, not the beginning.

**Why it works**: Models exhibit U-shaped recall (LITM). Last-token bias is structurally
stronger than first-token recall. Critical rules at the end have higher attention
priority during generation.

**Source**: Stanford LITM paper, validated empirically in Claude Code, GPT-4 docs.

**How to apply**:
- When writing system prompts, put the highest-priority rules in the LAST section
- When spawning sub-agents, end the spawn prompt with the most-critical constraint
- Example: Claude Code's built-in prompt repeats the safety constraint at the bottom

## Pattern 2: Negative framing > positive

**What**: Use "NEVER X" / "MUST NOT Y" / "FORBIDDEN to Z" instead of "Always X" / "Should Y".

**Why it works**: Negative boundary conditions process more reliably over long sessions.
Positive instructions decay; negative ones survive.

**Source**: Applied AI Hub research, prompt engineering communities.

**How to apply**:
- Rewrite hard-rules-checklist.md in the negative
- Convert "Apply TDD" → "NEVER mark a feature complete without a passing test"
- Convert "Use forge for design" → "NEVER skip forge for design tasks"

## Pattern 3: Hierarchical / progressive disclosure

**What**: Don't load a monolithic CLAUDE.md. Use directory-scoped rules that load
only when relevant.

**Why it works**: Reduces instruction density (avoids the 150-200 instruction budget),
keeps attention focused on the current task scope.

**Source**: 2026 best practices guides (Morph LLM, Builder.io, Anthropic docs).

**How to apply**:
- Global `~/.claude/CLAUDE.md`: universal rules only
- Per-project `<project>/CLAUDE.md`: project-specific rules
- `<project>/.claude/rules/<topic>.md`: topic-scoped rules with frontmatter triggers
- Skills via `~/.claude/skills/<skill>/SKILL.md`: invoked on demand only

## Pattern 4: Periodic re-injection

**What**: Inject brief reminders every N turns/tool calls.

**Why it works**: Counteracts persona collapse. Re-anchors the system prompt's
influence on the in-context conversation.

**Source**: Anthropic engineering blog, production support agent patterns.

**How to apply**:
- Hook-based (best): use settings.json `PreToolUse` to inject every N calls
- Skill-based: invoke `anti-drift checkpoint` every 50 tool calls
- Manual: when user notices drift, immediately re-anchor

Cost: ~10 tokens per injection. Negligible vs the cost of drift.

## Pattern 5: State externalization

**What**: Maintain a `.session-state.md` (or `state.md`, `memory.md`) file with
completed steps, active constraints, failed approaches, next planned action.

**Why it works**: Removes dependency on context recall. The file is the source of
truth; the in-context conversation is just the working buffer.

**Source**: Anthropic agentic patterns, multi-agent reliability papers.

**How to apply**:
- Create `.session-state.md` at the start of any 5+ sub-task session
- Update after each sub-task completion
- Re-read it (don't recall from context) when making decisions
- Reference: `templates/state.md.template`

## Pattern 6: Metacognitive audit (SPOC / MARCH)

**What**: Force the model to switch to a "Checker" persona and audit its own
intermediate claims against external evidence.

**Why it works**: Provides a structurally separate evaluation step that's not
tainted by the implementer's confirmation bias.

**Source**: SPOC (Spontaneous Self-Correction) and MARCH (Multi-Agent Reinforced
Self-Check) papers, NeurIPS 2025.

**How to apply**:
1. State the persona switch explicitly: "I am now a Checker. I have no investment
   in the previous output."
2. Re-read the task brief verbatim
3. For each requirement, demand tangible evidence (file path, command output, test result)
4. If evidence is missing, the requirement is NOT done
5. Only after zero gaps: claim completion

## Pattern 7: Verification as finality

**What**: No task is complete without tangible, executable proof. Tests run, lint
passed, build succeeded, grep clean.

**Why it works**: Forces the agent to produce evidence rather than self-report.
Self-reports drift; evidence does not.

**Source**: development-lifecycle skill, verification-before-completion patterns.

**How to apply**:
- Define what "complete" means up front (test pass, build success, etc.)
- Run the verification commands as the final step
- Capture and present the output, don't summarize
- If verification fails, the task is not complete — fix and re-verify

## Pattern 8: Hooks > prompts for hard enforcement

**What**: For rules that must happen every time with zero exceptions, use hooks
(deterministic shell commands triggered by events), not prompt instructions.

**Why it works**: Hooks are deterministic. Prompt instructions are advisory and
subject to drift.

**Source**: Claude Code documentation, Anthropic engineering blog.

**How to apply**:
- Linting / formatting → `PostToolUse` hook
- Blocking dangerous commands → `PreToolUse` hook
- Injecting recency anchors → `PreToolUse` hook every N calls
- See `update-config` skill for hook configuration syntax

## Pattern 9: Context pruning at thresholds

**What**: After N tool calls without resolution, summarize findings to state.md,
clear approach, and formulate a new plan.

**Why it works**: Prevents the agent from compounding errors by trying variations
of the same failed approach. Forces a fresh perspective.

**Source**: Agentic workflow research, "lessons learned" file pattern.

**How to apply**:
- Hard limit: 10 tool calls per sub-task. If unresolved, summarize and replan.
- Soft limit: 5 tool calls. Note the approach so far and consider alternatives.
