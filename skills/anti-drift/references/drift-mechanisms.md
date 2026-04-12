# Drift mechanisms — what we know (April 2026)

## 1. Context rot

**What it is**: Performance degradation as input length grows, even when relevant
information is technically present in the context window.

**Evidence (April 2026)**:
- Chroma research tested 18 frontier models (GPT-4.1, Claude 4, Gemini 2.5, Qwen3, etc.).
  All 18 degrade as input length increases. https://research.trychroma.com/context-rot
- Retrieval accuracy drops 15-30% from 8K to 128K context windows.
- Even simple retrieval tasks (find sentence X in document Y) fail in 2/3 of models at 2K tokens.

**Mechanism**: Attention budget is finite. As context grows, attention spreads thinner
across more tokens. Signal-to-noise ratio degrades.

**Mitigation**:
- Keep contexts as small as possible (the smallest set of high-signal tokens)
- Externalize state to disk; re-read when needed instead of accumulating
- Use hierarchical CLAUDE.md (load only what's relevant)

## 2. Lost-in-the-middle (LITM)

**What it is**: U-shaped recall curve. Information at the start and end of context
is retained well; information in the middle gets forgotten.

**Evidence (April 2026)**:
- Stanford LITM paper (2023, validated in 2024-2025).
- ~30% accuracy drop for information buried in the middle of context vs the same
  information at the edges.

**Mechanism**: Positional attention bias. Models learn to attend strongly to first
and last tokens; middle gets less attention weight.

**Mitigation**:
- Place critical rules at the END of prompts (recency anchor)
- For long task briefs, repeat the most important constraint at the bottom
- For sub-agent spawning, end the prompt with the must-not-violate constraints

## 3. Persona collapse

**What it is**: After ~10-15 conversation turns, the system prompt's influence
weakens relative to the in-context conversation. The agent drifts away from its
defined role into a generic helpful-assistant mode.

**Evidence (April 2026)**:
- Industry observation in production support/sales agents.
- Documented in Anthropic's "Effective context engineering for AI agents" (2025).

**Mechanism**: System prompt is at position 0 in the context window. Each new turn
pushes it further from the model's "current attention" focus. After 10-15 turns,
the in-context conversation dominates.

**Mitigation**:
- Inject a brief role re-statement every N turns ("Reminder: you are reviewing
  contracts only. Stay within scope.")
- Keep system prompts compact — high density of rules survives longer than long lists
- Use hooks to forcibly re-inject role anchors at fixed intervals

## 4. Instruction budget

**What it is**: Frontier LLMs reliably follow only ~150-200 distinct instructions
in a prompt. Beyond that, instruction density degrades attention and instructions
start getting silently ignored.

**Evidence (April 2026)**:
- Empirical analysis of CLAUDE.md files at scale (Morph LLM, Builder.io).
- Claude Code's built-in system prompt has ~50 instructions, leaving ~100-150 budget.

**Mechanism**: Not token overflow — instruction-density overflow. The model treats
each rule as a soft constraint, and beyond a budget, soft constraints start losing
priority to in-context content.

**Mitigation**:
- Audit your CLAUDE.md for rule count
- Move topic-specific rules into skill-scoped or directory-scoped files
- Keep the global CLAUDE.md to universal rules only (~50-100 max)

## 5. Compounding error in multi-step workflows

**What it is**: Each component in a multi-step workflow has reliability < 100%.
Errors compound multiplicatively across the chain.

**Evidence (April 2026)**:
- 2026 multi-agent paper documenting reliability cascades.
- Example: LLM call 90→80%, tool exec 85→75%, memory retrieval 97→90% by turn 20.
  System reliability at turn 20 = 0.80 × 0.75 × 0.90 = 54%.

**Mechanism**: Each step has its own drift. They don't cancel out.

**Mitigation**:
- Verification gates at every step (no progression without proof)
- Externalized state so step N+1 doesn't depend on step N's recall accuracy
- Periodic restart points (after 10 steps, summarize and start fresh sub-task)

## 6. The "Drift No More" formalization

**What it is**: Drift formalized as turn-wise KL divergence between the test model's
predictive distribution and a goal-consistent reference model's predictive distribution.

**Source**: arxiv 2510.07777 (October 2025, "Drift No More? Context Equilibria in
Multi-Turn LLM Interactions")

**Why it matters**: Provides a measurable metric for drift, not just a description.
Enables A/B testing of anti-drift techniques empirically.

**Practical implication**: When evaluating new anti-drift techniques, measure them
against a reference distribution rather than relying on subjective assessment.
