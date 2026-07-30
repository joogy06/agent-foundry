---
name: rag-architecture
description: Use when designing or fixing a retrieval system for an LLM application — deciding between RAG, cache-augmented generation and plain long context, chunking strategy, hybrid dense+lexical retrieval, reranking, embedding-model and vector-store selection, metadata filtering and per-tenant access control, incremental ingestion and re-embedding, and the evaluation metrics that tell you whether retrieval or generation is the thing that is broken.
disambiguation: DESIGNING the retrieval system — what to retrieve, how, from where, and how to prove it works. Writing the pipeline code (chunking functions, ChromaDB/FAISS calls) is research-vectorization; prompt caching, batching and token economics are llm-api-optimization; poisoned documents and retrieval-borne prompt injection are llm-security; which knowledge SOURCE to consult at all is knowledge-grounding.
---

# RAG architecture

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29.** Model names, prices and benchmark positions in this space go stale in
months — treat every named model below as an example of a class, not a recommendation to copy.

## 1. When RAG fails, it is retrieval that failed

**Industry analysis through 2026 consistently puts the failure point at retrieval roughly three
quarters of the time, not generation.** The visible symptom is a bad answer, so the instinct is to
edit the prompt — and prompt edits cannot recover a chunk that never entered the context.

**Before touching the prompt, ask: was the right chunk retrieved at all?** Log the retrieved chunk ids
for every query. That single log line separates "the model ignored good context" from "the model
never saw it", and those have opposite fixes.

## 2. RAG vs CAG vs long context — a routing decision, not a religion

**Cache-augmented generation (CAG)** loads the whole corpus into a cached prompt once and answers
every query against it, with no retrieval step. Long-context models priced with prompt caching made
this viable, and it is a **peer architecture to RAG, not a successor**.

Decide on the axes, per workload:

| Axis | Favours **CAG** | Favours **RAG** |
|---|---|---|
| Corpus size | Fits in context with room to spare | Exceeds it, or grows unpredictably |
| Freshness | Stable — changes daily or slower | Changes during a session |
| Latency | Sub-second, no retrieval hop | Retrieval hop is acceptable |
| Cost shape | Many queries amortise one cache write | Few queries per corpus load |
| Citations | Best-effort attribution | **Auditable — you must name the source** |
| Query distribution | Broad, unpredictable across the corpus | Narrow, targeted |
| Tenancy | One shared corpus | **Per-tenant corpora** |

**The production answer is usually both**: a router sending the hot path to the cache and the cold
path to retrieval. **Score both with the same rubric** or the comparison is decided by whichever you
instrumented better.

**Teams that declare "RAG is dead" ship the wrong architecture for half their workloads and
back-port RAG within a quarter.** Per-tenant data and citation requirements are the two constraints
that most reliably force retrieval, and neither is negotiable by tuning.

## 3. Chunking — where pipelines fail silently

**The test for a chunk: can it answer a question on its own?** A chunk that begins "This means the
threshold is exceeded" is unretrievable, because the query that needs it does not look like it.

| Strategy | Use when |
|---|---|
| **Structural** (headings, sections) | Documents with real structure — docs, contracts, wikis |
| **Semantic** (split where meaning shifts) | Prose without reliable structure |
| **Fixed-size + overlap** | Baseline; fine for homogeneous text |
| **Parent–child / small-to-big** | **Retrieve the precise small chunk, send the enclosing parent** |
| **Row- or record-level** | Tabular and structured data — never split a record |

**Carry the heading path into the chunk text.** `Contract > Schedule 2 > Payment terms` costs a few
tokens and makes an otherwise ambiguous fragment both retrievable and readable.

**Parent–child is the pattern most worth adopting early.** Small chunks retrieve precisely; large
chunks answer completely. Storing the small one for the vector and returning its parent for the
context gets both, and removes most of the chunk-size argument.

**Semantic chunking is not free** — it embeds sentence-by-sentence at ingest. Justify it against
structural chunking on your own data before paying for it everywhere.

## 4. Hybrid retrieval is the default

**Dense vectors alone fail on exactly the queries users care most about**: product codes, error
numbers, invoice references, surnames, rare acronyms. Embeddings encode meaning, and an identifier
has no meaning to encode — `ERR-4471` and `ERR-4417` sit almost on top of each other.

**The 2026 default is BM25 (lexical) + dense vectors**, fused — commonly by reciprocal rank fusion —
with a graph or structured layer added only where entity relationships genuinely drive the questions.

**Add the graph layer on evidence, not fashion.** GraphRAG earns its substantial ingest cost on
multi-hop and relationship questions ("who signed the contracts that reference this clause"), and
adds cost with no benefit on lookup questions.

**Query rewriting before retrieval** — expanding a terse or pronoun-laden follow-up into a
standalone query — is one of the cheapest real wins, particularly in multi-turn chat where the user's
literal words retrieve nothing.

## 5. Reranking

A cross-encoder reranker scores query and chunk **together**, which a bi-encoder cannot do, and it is
consistently one of the largest single contributors to final ranking quality.

**Retrieve ~20, rerank, send 3–5.** Retrieving wide and cutting hard beats retrieving narrow: recall
is what you cannot recover later, and precision is what the reranker fixes.

**More context is not better.** A window padded with near-misses diffuses attention and inflates
cost. There is a real quality peak, and it is lower than most first implementations assume.

## 6. Embedding models

| Decision | Guidance |
|---|---|
| **Starting point** | A hosted general-purpose model. English-only general retrieval is largely a solved commodity |
| **Self-host** | High volume, data-sovereignty constraints, or existing MLOps capability. Open models now match or beat hosted ones on public benchmarks |
| **Domain models** | Legal, finance, code and multilingual specialists beat generalists in their domain by a wide margin |
| **Dimensions** | Matryoshka-trained models front-load meaning, so 1536 dims can often be truncated to 256–512 with modest loss and much cheaper storage and search |

**Public benchmark position is a shortlist, never a decision.** Benchmarks get overfitted, and your
corpus is not the benchmark. **Build a golden set of 50–100 real queries with known-correct chunks
and measure recall@k on your own data** — it takes an afternoon and outranks every leaderboard.

**Changing the embedding model means re-embedding the entire corpus.** Vectors from two models are
not comparable, and mixing them produces retrieval that is quietly, unfixably wrong rather than
broken. Plan the migration — dual-write, backfill, cut over — **before** the first model choice, and
store the model id and version alongside every vector so a mixed store is detectable.

## 7. Vector store

| Situation | Choice |
|---|---|
| Postgres is already the data platform, corpus modest | **`pgvector`** — one system, one transaction, one backup |
| Production RAG, filtering matters, mid-scale | A dedicated store — the operational simplicity of a single-purpose engine is the point |
| Very large scale, or a distributed platform requirement | A distributed engine, self-hosted or managed |

**Default to the database you already run.** A separate vector store is a second system to secure,
back up, monitor and keep consistent, and it earns that only at scale or under a workload the
extension genuinely cannot serve.

**Metadata filtering is the feature that decides this in practice, not raw query speed.** Almost
every real system filters — by tenant, date, document type, permission — and engines differ enormously
in whether filters are applied *during* the vector search or as a post-filter that silently returns
fewer than `k` results.

**Store text alongside vectors, or store a durable pointer.** Rebuilding the answer from ids against
a source that has since changed is a slow-motion correctness bug.

## 8. Access control — filter during retrieval, never after

**Permissions belong in the query, as chunk-level metadata.** Retrieving broadly and filtering the
results afterwards means the model has already seen material the user may not access, and any
summary, citation or follow-up can leak it. Post-filtering also breaks `k` silently.

**A document's permissions must be carried onto every chunk derived from it**, and re-derived when
the source's permissions change. This is the most commonly skipped step when a prototype meets its
first real tenant.

## 9. Evaluation — measure retrieval and generation separately

| Metric | Question |
|---|---|
| **Recall@k** | Did the needed chunk reach the candidate set? |
| **Precision@k** | What fraction of what we sent was relevant? |
| **Context relevance** | Were the retrieved chunks on-topic for the query? |
| **Faithfulness / groundedness** | Is every claim in the answer supported by the context? |
| **Answer relevance** | Does the answer address what was asked? |

**Recall is the higher-leverage retrieval metric**: if the right chunk never enters the candidate
set, no reranking, prompting or model upgrade recovers it. Precision is a cost and attention problem;
recall is a correctness ceiling.

**Faithfulness is the ship gate.** Widely-cited practice puts the production target around 90% and
treats sub-70% as unsafe to ship. Pick your own threshold, but pick it **before** you see the score.

**A golden set beats a framework.** Evaluation tooling helps, but a stored set of real queries with
known-correct chunks and expected answers is what makes a change reviewable. Without it, every tuning
round is a vibe.

**For agentic RAG, score the trajectory, not just the final answer** — how many retrievals, whether
they were redundant, whether the agent stopped when it had enough. Faithfulness is necessary and not
sufficient once the system acts on what it retrieved.

## 10. Ingestion and freshness

- **Incremental, content-hashed ingestion.** Re-embedding an unchanged document is pure cost.
- **Deletes must propagate.** An orphaned vector for a deleted document is a confident citation of
  something that no longer exists — and in a regulated setting, a retention breach.
- **Version the chunking scheme**, not just the data. A chunker change invalidates the corpus exactly
  as an embedding-model change does.
- **Retrieved content is untrusted input.** A document can carry instructions aimed at your model —
  see `llm-security` for the injection and poisoning defences that belong at this boundary.

## 11. Anti-patterns

- **Tuning the prompt when retrieval is what failed.** Log the retrieved chunk ids first.
- **Declaring RAG obsolete** because long context got cheap — then rediscovering per-tenant data and
  citations.
- **Dense-only retrieval** on a corpus full of identifiers, codes and names.
- **Chunks that cannot stand alone**, stripped of their heading context.
- **Stuffing the window** with 20 chunks because they fit.
- **Choosing an embedding model from a leaderboard** without a golden set.
- **Mixing vectors from two embedding models** in one index.
- **Post-filtering for permissions** after the model has seen the content.
- **Running a separate vector store** when the existing database would do.
- **No evaluation set**, so every change is judged on the last query someone happened to try.
- **Trusting retrieved text** as though the corpus were part of your prompt.
