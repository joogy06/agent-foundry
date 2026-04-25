# Capability Deltas 2020→2026 — v1 Seed Catalog (D-01..D-08)

Catalog of the eight most load-bearing capability deltas between 2020 and 2026. Each entry is the
grep-anchor the Builder cites when claiming a 2020-era constraint has been removed. Entries are
prose with structured fields; v1.1 ships a machine-readable `scripts/catalogs.yaml` mirror.

**Citation format:** Builder references `D-NN` in `deltas_invoked[]` and pairs each with a
`prior_era_constraint.id` in `lifted_constraints[]`. See `references/verdict-rubric.md` for the
pairing schema.

**Scope boundary:** these 8 deltas cover the dimensions most frequent in skill / agent / product
ideation during this project's current work. Deltas D-09..D-25 (physical-robotics, video
generation, biological foundation models, on-device inference, etc.) are deferred to v1.1.

---

## D-01: Context window

- **2020_baseline**: 4k–32k tokens typical; GPT-3 at 4k, Codex at 8k, some research models at 32k.
  Holding even a single medium-sized source file + its tests + a style guide + a diff was not
  possible in one reasoning context.
- **2026_state**: 200k–1M tokens typical on frontier models. Claude Opus 4.7 at 1M, Gemini 3 Pro at
  1M, GPT-5.4 at 400k+. A 30–250× multiplier on context.
- **lifted_constraints**:
  - `context-window-2020` — could not hold multi-file codebase + diff + tests in one reasoning pass
  - `cross-file-reasoning-2020` — pre-2023 agents had to summarize or RAG-stuff, losing exact-string
    fidelity across files
  - `long-document-qa-2020` — full-contract, full-policy, full-manual Q&A was blocked by chunk
    boundaries
- **not_lifted**:
  - Recency-bias degradation at >200k tokens is a real 2026 failure mode (cited in 2025 research)
  - Cost scales near-linearly with tokens in; 1M prompts are expensive even at D-02 prices
  - Instruction-following quality degrades when the instructions are mid-context with distracting
    material on both sides
- **last_verified**: 2026-04-19
- **evidence_refs**: Anthropic Claude context-window release notes; Google Gemini 3 announcement;
  common-knowledge-with-rationale on GPT-3-era limits

---

## D-02: Inference cost (frontier models)

- **2020_baseline**: ~$30/1M input tokens on frontier models (GPT-3 davinci era); running a 10k-token
  prompt 100 times cost ~$30. Frontier use was budget-gated.
- **2026_state**: ~$3–$15/1M input tokens on 2026-frontier (Opus/GPT-5.4/Gemini 3 Pro). Open-weight
  frontier-adjacent models (Llama-4 class) available at fractions of this. A 10–20× cost reduction
  on frontier inference alone; 50–200× when including open-weight alternatives.
- **lifted_constraints**:
  - `inference-cost-2020` — long-horizon agent loops (hours of LLM calls) were economically
    infeasible
  - `mass-inference-2020` — running frontier inference across every row of a dataset was
    budget-gated
  - `multi-agent-cost-2020` — spawning 4+ parallel agents per task multiplied already-expensive
    inference beyond viability
- **not_lifted**:
  - Frontier inference is still expensive enough that careless loops can burn $100s/day
  - Cost-per-token rewards prompt caching; long uncached prompts blow the budget
  - Latency-cost tradeoff: the cheapest models are slower-per-token on long outputs
- **last_verified**: 2026-04-19
- **evidence_refs**: Anthropic/OpenAI/Google published pricing 2026-Q1; common-knowledge-with-
  rationale on 2020 davinci pricing

---

## D-03: Tool use

- **2020_baseline**: Ad-hoc ReAct prompting. Agents generated text that looked like tool calls and a
  harness parsed it with regex. Brittle; no parallel calls; no structured return; no schema
  enforcement.
- **2026_state**: Native structured tool-use in all frontier APIs. JSON-schema-constrained
  arguments; parallel tool calls; streaming tool-use; type-safe return values. MCP (Model Context
  Protocol) standardizes tool servers across providers.
- **lifted_constraints**:
  - `tool-reliability-2020` — ReAct parsing errors cascaded through agent loops, making multi-step
    tool use unreliable
  - `parallel-tool-calls-2020` — sequential-only tool calls bottlenecked agent throughput
  - `tool-ecosystem-2020` — no standard for sharing tool definitions across models
- **not_lifted**:
  - Tool call quality degrades on obscure / undertrained tools; the LLM confabulates arguments
  - Tool timeouts and error handling are still agent-design problems, not solved by the delta
  - MCP adoption is real but uneven; some providers lag
- **last_verified**: 2026-04-19
- **evidence_refs**: Anthropic tool-use docs; OpenAI function-calling docs; MCP specification
  (2024-Q4 launch)

---

## D-04: Multi-agent orchestration

- **2020_baseline**: Manual prompt chaining. LangChain-style Python glue. No native subagent
  primitives; no inter-agent coordination; no role-based specialization built into APIs. Every
  multi-agent system was bespoke code plus ReAct.
- **2026_state**: Agent primitives in Claude Code, Codex, Gemini CLI. Subagent spawning via the
  Agent / Task tools. Team-level orchestration (this project's `agent-teams` skill, forge's
  design teams, bob's WP-dispatch). MCP-based inter-agent communication. Topologies
  (concurrent / pipeline / specialist) are catalogued patterns, not per-project inventions.
- **lifted_constraints**:
  - `orchestration-code-2020` — building a multi-agent system required 500+ lines of Python glue
  - `role-specialization-2020` — no built-in notion of "challenger / QA / UX" agent roles
  - `parallel-agent-spawn-2020` — spawning N agents in parallel required your own process pool
- **not_lifted**:
  - Cross-agent coordination failures (stall, deadlock, conflicting writes) are still hard
  - Evaluation of multi-agent systems is immature; harder to measure than single-agent
  - Cost scales with agent count at D-02 prices — 4 agents × 1M context is still expensive
- **last_verified**: 2026-04-19
- **evidence_refs**: Claude Code Agent tool docs; this project's `agent-teams` skill; Codex
  subagent primitives (2025-Q4)

---

## D-05: Grounding / retrieval

- **2020_baseline**: Either no grounding (pure LLM recall, hallucination-prone) or ad-hoc RAG built
  from embeddings + vector DB + manual chunking. No native search integration in APIs. No provider-
  managed grounding.
- **2026_state**: Native search grounding in Gemini (Google Search) and Claude (web search tool);
  Vertex AI grounding API for enterprise; MCP-based RAG patterns standardize retrieval; source-
  citation in responses is default-on for grounded answers.
- **lifted_constraints**:
  - `hallucination-2020` — no production-ready way to cite sources in LLM output
  - `rag-build-cost-2020` — every project built its own embeddings + chunking + retrieval
  - `fresh-info-2020` — training-data cutoff meant LLMs could not answer questions about recent
    events without external integration
- **not_lifted**:
  - Grounding quality depends on the source; garbage-in still gives garbage-out
  - Citation accuracy is not perfect; LLMs occasionally cite sources that do not contain the claim
  - Retrieval-augmented LLMs still make up information when the retrieval returns nothing relevant
- **last_verified**: 2026-04-19
- **evidence_refs**: Gemini Google Search grounding docs; Claude web_search tool docs; Vertex AI
  grounding API

---

## D-06: Modality

- **2020_baseline**: Text-only. Image input / output required separate pipelines (CLIP + GAN). No
  audio in / out. No code execution inline. Multi-modal meant stitching model families together.
- **2026_state**: Native vision input on all frontier models (Claude, GPT-5.4, Gemini 3). Audio in
  on most. Code-interpreter / Python execution on most. Image generation via integrated or sibling
  models (Vertex Imagen, OpenAI image tools, Anthropic integrations). Vision-in + text-out +
  code-exec in one reasoning context is default.
- **lifted_constraints**:
  - `text-only-2020` — vision, audio, code-exec required separate specialist models with handoff
    glue
  - `diagram-understanding-2020` — architecture diagrams, whiteboard photos, charts were opaque to
    LLMs
  - `ocr-pipeline-2020` — extracting text from images required dedicated OCR + LLM stitching
- **not_lifted**:
  - Vision quality on small text / handwriting / non-English is uneven
  - Audio understanding lags text understanding in nuance
  - Code-interpreter is sandboxed; cannot replace a real dev environment for long-horizon work
- **last_verified**: 2026-04-19
- **evidence_refs**: Anthropic multimodal docs; GPT-5.4 multimodal capabilities; Gemini 3
  native-multimodal announcement

---

## D-07: Latency

- **2020_baseline**: 20–60s typical for long completions (1k+ tokens out) on frontier models. No
  native streaming — users waited for the full response. Interactive agent loops with 5+ steps
  took 2–5 minutes.
- **2026_state**: 2–10s for similar completions, with streaming as default. Perceived latency is
  time-to-first-token, not total. Agent loops with 5 steps typically take 15–45s end-to-end.
- **lifted_constraints**:
  - `interactive-latency-2020` — conversational agents with 5+ tool calls felt unusable
  - `streaming-ux-2020` — UIs could not show progress; users bounced during wait
  - `agent-loop-iteration-2020` — 10-iteration loops took 10+ minutes, killing developer feedback
    cycles
- **not_lifted**:
  - Very long outputs (10k+ tokens) are still seconds-to-tens-of-seconds
  - Parallel tool calls help but each branch still has its own latency floor
  - 1M-context prompts have pre-fill latency that scales with token count even at frontier speeds
- **last_verified**: 2026-04-19
- **evidence_refs**: Provider latency benchmarks 2026-Q1; common-knowledge-with-rationale on 2020
  GPT-3 latency

---

## D-08: Persistent memory

- **2020_baseline**: None. LLM calls were stateless; every call re-sent the full context. No
  standard way to persist facts / decisions / state across calls except roll-your-own DBs.
- **2026_state**: Multiple persistence primitives: filesystem access (Claude Code, Codex, Gemini
  CLI), MCP servers offering structured storage, claims-ledger patterns (this project's own
  infrastructure in bob), session state (`~/.claude/state/`, `.founder/venture-brief.yaml`,
  `.ledger/`), and agent-memory APIs in some providers.
- **lifted_constraints**:
  - `statelessness-2020` — every agent had amnesia between calls
  - `decision-audit-2020` — no built-in way to record "we decided X because Y" traceable across
    sessions
  - `multi-session-continuity-2020` — resuming yesterday's work required re-loading context manually
- **not_lifted**:
  - Storage format drift: the LLM may write to one schema on Monday and read a different schema on
    Tuesday if contracts are not enforced
  - Garbage accumulation: persisted state grows; without GC, signal-to-noise degrades
  - Concurrent writers (multi-agent) introduce classic database consistency problems — CB3/CB4 in
    this project's own architecture exist specifically because of this
- **last_verified**: 2026-04-19
- **evidence_refs**: Claude Code filesystem access; MCP specification; this project's `.founder/`,
  `.ledger/`, `~/.claude/state/` patterns
