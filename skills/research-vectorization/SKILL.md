---
name: research-vectorization
description: Use when writing the code that turns a document corpus into a queryable vector store — runnable Python for markdown chunking, sentence-transformer embedding, ChromaDB and FAISS indexing, metadata schemas and a basic RAG query pipeline.
disambiguation: The PIPELINE CODE — chunk, embed, index, query, in working Python. The design decisions around it (RAG vs CAG, hybrid retrieval, reranking, which embedding model and vector store, evaluation) are rag-architecture; read that first if the question is "what should this system be" rather than "how do I write it".
---

# Research Vectorization

> **This skill is the implementation companion to `rag-architecture`.** It gives you working code for
> a local corpus. The architectural decisions it assumes — dense-only retrieval, fixed chunk sizes,
> a local embedding model, no reranking — are defaults suited to a single-user research corpus, not
> to a production application. **For an application, decide the architecture in `rag-architecture`
> first**, then come back here for the pipeline mechanics.
>
> *(Code verified working; named models and library defaults were current when written and drift
> quickly — check `rag-architecture` §6 before adopting a model from the table below.)*

## Overview

Research vectorization converts unstructured documents (markdown, PDFs, reports) into a searchable vector store. Combined with RAG (Retrieval-Augmented Generation), it lets an LLM answer queries grounded in your specific research corpus.

**Core principle:** Chunk quality determines retrieval quality. Bad chunking = bad retrieval = hallucinated answers.

## When to Use

- Converting trading research docs to a queryable knowledge base
- Building RAG pipelines for financial analysis assistants
- Implementing semantic search over market research
- Integrating vector retrieval with Qwen or Claude for grounded responses

## Chunking Strategies

```python
from typing import Generator
import re

def chunk_markdown(
    text: str,
    chunk_size: int = 512,       # tokens (approximate: 4 chars/token)
    chunk_overlap: int = 64,     # token overlap between chunks
    min_chunk_size: int = 100,
) -> list[dict]:
    """
    Semantically-aware chunking for markdown documents.
    Splits on headers first, then on sentence boundaries within sections.
    Preserves header context in each chunk.
    """
    # Split into sections by markdown headers
    sections = re.split(r'\n(#{1,3} .+)\n', text)

    chunks = []
    current_header = ''

    for i, section in enumerate(sections):
        # Track current header
        if re.match(r'^#{1,3} ', section):
            current_header = section.strip()
            continue

        # Split section into sentences
        sentences = re.split(r'(?<=[.!?])\s+', section.strip())

        current_chunk = []
        current_size = 0
        char_chunk_size = chunk_size * 4

        for sentence in sentences:
            sentence_size = len(sentence)

            if current_size + sentence_size > char_chunk_size and current_chunk:
                # Emit chunk
                chunk_text = ' '.join(current_chunk)
                if len(chunk_text) >= min_chunk_size * 4:
                    chunks.append({
                        'text': f"{current_header}\n\n{chunk_text}" if current_header else chunk_text,
                        'header': current_header,
                        'char_count': len(chunk_text),
                    })

                # Overlap: keep last N chars worth of sentences
                overlap_text = chunk_text[-chunk_overlap * 4:]
                current_chunk = [overlap_text]
                current_size = len(overlap_text)

            current_chunk.append(sentence)
            current_size += sentence_size

        # Emit final chunk
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            if len(chunk_text) >= min_chunk_size * 4:
                chunks.append({
                    'text': f"{current_header}\n\n{chunk_text}" if current_header else chunk_text,
                    'header': current_header,
                    'char_count': len(chunk_text),
                })

    return chunks


def chunk_by_tokens(text: str, tokenizer, max_tokens: int = 512,
                     overlap_tokens: int = 64) -> list[str]:
    """Token-precise chunking using a HuggingFace tokenizer."""
    tokens = tokenizer.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(tokenizer.decode(chunk_tokens))
        start += max_tokens - overlap_tokens
    return chunks
```

## Embedding Models

```python
from sentence_transformers import SentenceTransformer
import numpy as np

# Model selection guide
EMBEDDING_MODELS = {
    'general':          'sentence-transformers/all-MiniLM-L6-v2',   # fast, 384-dim
    'high_quality':     'sentence-transformers/all-mpnet-base-v2',  # better, 768-dim
    'financial':        'yiyanghkust/finbert-tone',                  # finance-tuned
    'multilingual':     'sentence-transformers/paraphrase-multilingual-mpnet-base-v2',
    'large_context':    'Alibaba-NLP/gte-large-en-v1.5',            # 8192 context
}

class EmbeddingEngine:
    def __init__(self, model_name: str = 'sentence-transformers/all-mpnet-base-v2'):
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str], batch_size: int = 32,
              normalize: bool = True) -> np.ndarray:
        """Returns (N, dim) float32 array of embeddings."""
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=normalize,  # for cosine similarity
            show_progress_bar=len(texts) > 100,
        )
        return embeddings
```

## ChromaDB Integration

```python
import chromadb
from chromadb.config import Settings

def build_chroma_collection(
    documents: list[dict],   # [{text, metadata}]
    embeddings: np.ndarray,
    collection_name: str,
    persist_dir: str = './chroma_db',
) -> chromadb.Collection:
    """Build and persist a ChromaDB collection."""
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )

    # Delete existing collection if rebuilding
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    collection = client.create_collection(
        name=collection_name,
        metadata={'hnsw:space': 'cosine'},  # cosine similarity
    )

    # Batch upsert (ChromaDB limit: ~41k docs per batch)
    batch_size = 1000
    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i:i + batch_size]
        batch_embs = embeddings[i:i + batch_size]
        collection.upsert(
            ids=[f"doc_{i + j}" for j in range(len(batch_docs))],
            embeddings=batch_embs.tolist(),
            documents=[d['text'] for d in batch_docs],
            metadatas=[d.get('metadata', {}) for d in batch_docs],
        )

    return collection


def query_collection(collection: chromadb.Collection,
                      query_embedding: np.ndarray,
                      n_results: int = 5,
                      where: dict = None) -> list[dict]:
    """Query ChromaDB and return ranked results."""
    results = collection.query(
        query_embeddings=query_embedding.tolist(),
        n_results=n_results,
        where=where,  # metadata filter e.g. {'source': 'earnings_report'}
    )
    return [
        {'text': doc, 'distance': dist, 'metadata': meta}
        for doc, dist, meta in zip(
            results['documents'][0],
            results['distances'][0],
            results['metadatas'][0],
        )
    ]
```

## FAISS for High-Performance Retrieval

```python
import faiss
import numpy as np

def build_faiss_index(embeddings: np.ndarray,
                       use_gpu: bool = False) -> faiss.Index:
    """Build FAISS flat L2 index. Use IVF for >100k vectors."""
    dim = embeddings.shape[1]

    if len(embeddings) < 10_000:
        # Exact search for small collections
        index = faiss.IndexFlatIP(dim)  # inner product = cosine if normalised
    else:
        # Approximate search for large collections
        nlist = min(int(np.sqrt(len(embeddings))), 256)
        quantiser = faiss.IndexFlatIP(dim)
        index = faiss.IndexIVFFlat(quantiser, dim, nlist, faiss.METRIC_INNER_PRODUCT)
        index.train(embeddings.astype('float32'))

    if use_gpu:
        res = faiss.StandardGpuResources()
        index = faiss.index_cpu_to_gpu(res, 0, index)

    index.add(embeddings.astype('float32'))
    return index
```

## RAG Pipeline

```python
async def rag_query(
    question: str,
    collection: chromadb.Collection,
    embedder: EmbeddingEngine,
    llm_client,
    n_context: int = 5,
    system_prompt: str = "You are a financial research assistant. Answer based only on the provided context.",
) -> dict:
    """Complete RAG pipeline: embed query → retrieve → generate."""
    # Embed question
    query_emb = embedder.embed([question])[0]

    # Retrieve relevant chunks
    results = query_collection(collection, query_emb, n_results=n_context)

    # Build context string
    context = "\n\n---\n\n".join([
        f"[Source: {r['metadata'].get('source', 'unknown')}]\n{r['text']}"
        for r in results
    ])

    # Generate answer
    prompt = f"""Context:
{context}

Question: {question}

Answer based only on the context above. If the context doesn't contain the answer, say so."""

    response = await llm_client.complete(
        prompt=prompt,
        system=system_prompt,
        temperature=0.1,
    )

    return {
        'answer': response,
        'sources': [r['metadata'] for r in results],
        'n_chunks_retrieved': len(results),
    }
```

## Metadata Strategy for Financial Research

```python
# Recommended metadata schema for financial research docs
METADATA_SCHEMA = {
    'source':         str,    # 'earnings_report', 'news_article', 'research_note'
    'ticker':         str,    # 'AAPL', 'BTC-USD'
    'date':           str,    # ISO8601 '2025-11-15'
    'asset_class':    str,    # 'equity', 'crypto', 'commodity'
    'author':         str,    # source author/analyst
    'doc_type':       str,    # 'fundamental', 'technical', 'macro', 'sentiment'
    'confidence':     float,  # 0-1 reliability score of source
}

# Filter examples
def filter_by_ticker(collection, ticker: str, query_emb):
    return query_collection(collection, query_emb, where={'ticker': ticker})

def filter_by_date_range(collection, start_date: str, end_date: str, query_emb):
    return query_collection(collection, query_emb,
                            where={'$and': [{'date': {'$gte': start_date}},
                                            {'date': {'$lte': end_date}}]})
```

## Quick Reference — Tool Selection

| Scenario | Tool | Reason |
|----------|------|--------|
| < 10k docs, simple setup | ChromaDB | Easy to use, persistent, good filtering |
| > 100k docs, low latency | FAISS | Fastest ANN search |
| Multi-user / production | pgvector + PostgreSQL | SQL integration, ACID |
| Local, privacy-sensitive | ChromaDB or FAISS | No cloud calls |

## Common Mistakes

1. **Chunks too large** — >1000 tokens per chunk reduces precision; aim for 256-512 tokens
2. **No overlap** — without overlap, context at chunk boundaries is lost; use 10-15% overlap
3. **Ignoring metadata** — filtering by ticker/date dramatically improves retrieval; always add metadata
4. **Not normalising embeddings** — for cosine similarity, L2-normalise all embeddings before indexing
5. **Rebuilding index on every query** — persist the index; rebuild only when adding new documents
6. **Generic embeddings for financial text** — general models miss financial terminology; use financial-tuned models

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Chunking documents by fixed character count without respecting section boundaries | Splits mid-sentence or mid-paragraph; retrieved chunks lack context; LLM generates confused answers | Chunk by markdown headers, paragraph boundaries, or semantic sections; overlap chunks by 10-20% for continuity |
| Using cosine similarity without a relevance threshold | Low-quality matches returned alongside good ones; LLM answers based on irrelevant context | Set a minimum similarity threshold (0.7-0.8 for most embeddings); filter before passing to LLM |
| Not including metadata in vector store | Cannot filter by source, date, or category; retrieval returns outdated or wrong-domain content | Store metadata (source file, section, date, tags) with each vector; use metadata filters in queries |
| Embedding entire large documents as single vectors | One embedding per 50-page document loses all granularity; retrieval is essentially random | Chunk to 500-1500 tokens per vector; test chunk size against your specific retrieval accuracy needs |
| Rebuilding the entire vector store on every document update | Expensive recomputation; downtime during rebuild; unnecessary for incremental changes | Implement incremental indexing: hash document chunks, only re-embed changed chunks, delete removed ones |
