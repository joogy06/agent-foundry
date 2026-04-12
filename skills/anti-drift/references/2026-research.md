# Anti-drift research citations (April 2026)

## Primary sources

### Context rot and instruction degradation

- **Chroma Research, "Context Rot: How Increasing Input Tokens Impacts LLM Performance"** (2025)
  https://research.trychroma.com/context-rot
  - Tested 18 frontier models (GPT-4.1, Claude 4, Gemini 2.5, Qwen3, etc.)
  - All 18 degrade as input length grows
  - Even simple retrieval fails in 2/3 of models at 2K tokens

- **"Drift No More? Context Equilibria in Multi-Turn LLM Interactions"** (arxiv 2510.07777, October 2025)
  https://arxiv.org/html/2510.07777v1
  - Formalizes drift as turn-wise KL divergence vs reference policy
  - Provides measurement framework

- **"Context Discipline and Performance Correlation"** (arxiv 2601.11564, January 2026)
  https://arxiv.org/html/2601.11564v1
  - Empirical study of context length impact on accuracy

### Lost-in-the-middle

- **"Lost in the Middle"** (Stanford, 2023, validated through 2025-2026)
  - U-shaped recall curve across multiple model families
  - 30%+ accuracy drop for mid-context information

### Self-correction patterns

- **SPOC** (Spontaneous Self-Correction) and **MARCH** (Multi-Agent Reinforced Self-Check)
  papers, NeurIPS 2025
  - Interleaved verification patterns
  - Force model to switch to Checker persona before proceeding

### Production observations

- **"How Claude Code Builds a System Prompt"** by David Breunig (April 2026)
  https://www.dbreunig.com/2026/04/04/how-claude-code-builds-a-system-prompt.html
  - Reverse engineering of Claude Code's prompt structure
  - Documents the recency anchor pattern in production

- **"The Complete Guide to Writing Agent System Prompts — Lessons from Reverse-Engineering Claude Code"** by Feng Liu (March 2026)
  https://medium.com/@fengliu_367/the-complete-guide-to-writing-agent-system-prompts-...
  - Empirical findings on instruction budget

- **"5 Claude System Prompt Patterns That Actually Work in 2026"** (DEV Community)
  https://dev.to/clawgenesis/the-5-claude-system-prompt-patterns-that-actually-work-in-2026-p6a
  - Recency anchoring
  - Negative framing
  - Periodic re-injection
  - State externalization
  - Hooks for hard enforcement

### Anthropic engineering

- **"Effective context engineering for AI agents"** (Anthropic, 2025)
  https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
  - Official guidance on long-context agentic workflows
  - "Smallest set of high-signal tokens" principle

### Industry impact

- **"Agent Drift: Why Your AI Gets Worse the Longer It Runs"** (Chanl Blog, 2025)
  https://www.chanl.ai/blog/agent-drift-silent-degradation
  - Documents 65% of enterprise AI failures attributed to drift/memory loss in 2025

## Update protocol

This file should be updated whenever:
- New frontier model is released (test for drift behavior)
- New paper publishes empirical drift findings
- New anti-drift technique gains adoption
- Existing techniques are empirically debunked

Use the `alf` agent's "freshness" lens to check this file every quarter.
