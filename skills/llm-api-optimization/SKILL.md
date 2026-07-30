---
name: llm-api-optimization
description: Use when an LLM-backed application's API calls need to get cheaper, faster or more reliable — prompt caching and the prefix rules that decide whether it hits, batch processing, context engineering and what earns a place in the window, payload format economics, structured outputs and constrained decoding, model routing by task, streaming and latency, and measuring cost per resolved task rather than per call.
disambiguation: The API CALL — what you send, how it is cached and billed, and how the response is shaped. Designing what to RETRIEVE and from where is rag-architecture; deciding whether the system should be an agent or a workflow at all is agentic-architecture; routing spawned harness work to model tiers is smart-config; defending against injection in what you send is llm-security.
---

# LLM API optimisation

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29.** Prices, multipliers and TTLs move constantly and differ per provider —
**every number below is a shape to reason with, and must be re-checked against current provider
documentation before it goes in a budget.**

## 1. The cost stack, in order of leverage

| Lever | Typical saving | Effort |
|---|---|---|
| **Prompt caching** | Up to ~90% on the repeated portion | Low — often a few lines |
| **Batch processing** | ~50% on both input and output | Low, if latency permits |
| **Context engineering** | 40–60% | Medium — ongoing discipline |
| **Payload format** | 20–50% on structured payloads | Low |
| **Model routing** | Large, task-dependent | Medium |

**Caching and batching stack multiplicatively** — combined they can take the repeated portion of a
workload to a small fraction of list price. Realistic end-to-end reduction on a well-engineered
application is around 70–80%.

**Do the cheap structural work before switching to a smaller model.** Model downgrades trade quality
for cost; caching does not.

## 2. Prompt caching — it is a prefix cache, and that governs everything

The cache keys on an **exact prefix** of the request. Everything before the change is reusable;
everything from the first differing byte onward is not.

**Therefore: static content first, dynamic content last.** System prompt, tool definitions and
documents at the top; the user's turn at the bottom. This one ordering rule decides whether caching
works at all.

Typical economics (verify against current docs):

| | Multiplier |
|---|---|
| Cache **write**, short TTL | ~1.25× base input |
| Cache **write**, extended TTL | ~2× base input |
| Cache **read** | ~0.1× base input |

**Break-even is one hit on a short TTL, roughly two on an extended one.** So the calculation is not
"is caching good" but "will this prefix be read again inside its TTL". A prefix read once costs you
money.

**Extended TTL wins where the natural gap between requests exceeds the short window** — a support
agent handling a case over half an hour, an interactive session with thinking time. Paying the write
premium once beats re-writing every few minutes.

**Do not cache what will not be re-read.** A one-shot call with a large unique document is the
canonical waste.

### The cache-miss traps

Every one of these silently drops the hit rate to zero while the code looks correct:

- **A timestamp, request id or "today's date" near the top of the system prompt.** The single most
  common cause. Move it to the end of the message, or omit it.
- **Tool definitions reordered** between calls — a dictionary iteration order change is enough.
- **Non-deterministic JSON serialisation** of tools or schemas: unsorted keys, varying whitespace.
- **Per-user or per-session content placed before shared content.** Shared prefix first, always.
- **Any prompt-version A/B test that edits the head** of the system prompt rather than appending.
- **Editing the system prompt on deploy**, which cold-starts every cache at once — expected, but plan
  for the cost spike.

**Instrument the hit rate.** Providers report cache-read and cache-write tokens per response. A
caching implementation nobody measured is usually a caching implementation that is not working.

## 3. Batch processing

Asynchronous batch submission typically returns within a day at around half price on input and
output, and **stacks with caching**.

Fits: evaluation runs, back-fills, bulk classification, summarising a document corpus, nightly
enrichment. Does not fit: anything a user is waiting for.

**Look for the interactive work that is not actually interactive.** Enrichment triggered by a user
action but consumed hours later is batch work wearing a synchronous costume.

## 4. Context engineering — decide what earns a place in the window

Prompt engineering is what you say; **context engineering is what you provide**. On production
systems the second dominates the bill and most of the quality.

- **Selective retrieval over stuffing.** More context is not more accuracy — see `rag-architecture` §5.
- **Summarise or compact conversation history** rather than replaying it turn by turn. Providers now
  offer first-class compaction and server-side memory for exactly this; a hand-rolled rolling summary
  works too.
- **Externalise durable facts.** Anything stable belongs in a cached prefix or a memory store, not
  re-sent every turn.
- **Trim tool definitions to what this call can plausibly use.** Tool schemas are input tokens on
  *every* request, and a large unused toolset also degrades selection.
- **Budget the window explicitly.** Overrun does not degrade gracefully — it truncates context, drops
  tool calls and malforms output.

## 5. Payload format economics

**JSON costs roughly twice the tokens of YAML or TSV for the same data** — quotes, braces and
repeated keys on every record.

- **Internal, machine-to-machine payloads**: use the compact format. Tabular data as TSV/CSV with one
  header row is dramatically cheaper than an array of objects repeating keys per row.
- **Model *output* that must be parsed**: keep JSON, and constrain it (§6). Output tokens are the
  expensive ones, but reliable parsing is worth more than the saving.
- **Strip what nobody reads** — nulls, empty arrays, internal audit fields, deep nesting that exists
  for a database's benefit rather than the model's.

**Measure before rewriting a serialiser.** This lever is large on high-volume structured payloads and
negligible on prose-shaped workloads.

## 6. Structured outputs

Two approaches, and the difference matters under load:

| Approach | How | Trade-off |
|---|---|---|
| **Constrained decoding** | The decoder can only emit tokens valid for the schema | Structurally guaranteed; needs provider or local support |
| **Schema-in-prompt + validate + retry** | Ask for a shape, validate, retry on failure | Portable; retries cost tokens and latency |

**Validate the output regardless of which you use.** Schema-valid is not the same as semantically
correct — a required field can be present and wrong. Types are not a business-rule check.

**Never parse structure out of prose.** Regexing an amount out of a sentence works in testing and
fails on the first unusual phrasing.

## 7. Model routing

**Route by task, not by habit.** Classification, extraction, routing and formatting rarely need the
largest model; multi-step reasoning, ambiguous judgement and code architecture do.

Build the routing decision as a policy in one place, not as a hard-coded model id at each call site —
that is what makes re-tiering a config change instead of a refactor. Inside this harness, that policy
is `smart-config`; in an application, a small resolver reading configuration does the same job.

**Escalate on evidence.** A cheap model plus a validity check, escalating on failure, is often
cheaper *and* better than the large model everywhere — provided the check is real.

## 8. Latency

- **Stream when a human is reading.** Time-to-first-token dominates perceived speed even when total
  time is unchanged.
- **Parallelise independent calls.** Sequential awaits on unrelated requests are the same waterfall
  mistake as in a front end.
- **Cache reads are faster as well as cheaper** — the prefix is already processed. Caching is a
  latency optimisation people forget to claim.
- **Speculative or eager calls burn real money.** Firing a request the user may not need is only
  worth it where the hit rate is measured and high.

## 9. Measure cost per resolved task, not per call

**Per-call cost is the wrong denominator.** A cheaper model that needs three attempts, a retry loop
that hides two extra calls, or an agent that retrieves the same document five times all look fine
per call and terrible per outcome.

Log per request: input tokens, **cache-read and cache-write tokens**, output tokens, model, latency,
and a task id that ties retries and sub-calls to one unit of work. Then track:

- **Cache hit rate** — the first number to check when a bill moves.
- **Tokens per resolved task** — the number that actually tracks the bill.
- **Retry and escalation rate** — where quality problems show up as cost.

**Set a per-task budget and alert on breach.** Agentic systems fail expensively in loops, and an
unbounded retry is a bill, not an error.

## 10. Anti-patterns

- **Dynamic content at the top of the prompt**, silently defeating the cache.
- **A timestamp in the system prompt.** The classic zero-hit-rate bug.
- **Caching a prefix that is read once.**
- **Never measuring the hit rate**, then assuming caching is working.
- **Synchronous calls for work nobody is waiting for.**
- **Replaying full conversation history** every turn instead of compacting.
- **Shipping every tool definition** on every call.
- **Verbose JSON for high-volume internal payloads.**
- **Parsing structure out of prose** instead of constraining the output.
- **Hard-coding a model id at every call site.**
- **Downgrading the model before doing the free structural work.**
- **Reporting cost per call** while the retries hide in another metric.
