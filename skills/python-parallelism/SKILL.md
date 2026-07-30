---
name: python-parallelism
description: Use when implementing concurrent or parallel Python code — asyncio, multiprocessing, threading, concurrent.futures, task queues (Celery), or data processing parallelism (Polars, Dask). Covers the GIL-free Python transition, decision frameworks for choosing the right approach, and production patterns.
family: python
---

# Python Parallelism

## Overview

Python's concurrency landscape changed fundamentally in 2025-2026. The GIL is becoming optional (Python 3.13+ experimental, 3.14 officially supported with 5-10% single-thread penalty). But for most code, the right tool depends on whether your workload is I/O-bound or CPU-bound — not whether the GIL exists.

## Decision Framework

```
Is your workload I/O-bound or CPU-bound?

I/O-bound (network, disk, database):
  ├── Many concurrent connections? → asyncio (TaskGroup)
  ├── Simple parallel I/O? → ThreadPoolExecutor
  └── Background jobs? → Celery / Dramatiq / arq

CPU-bound (computation, data processing):
  ├── NumPy/pandas-style? → Polars (auto multi-core)
  ├── Custom Python code? → ProcessPoolExecutor
  ├── Large-scale distributed? → Dask or Ray
  └── Simple loop parallelism? → joblib

Mixed:
  └── asyncio + ProcessPoolExecutor (run_in_executor)
```

## asyncio (I/O-Bound — Primary Choice)

### TaskGroup (Python 3.11+) — Preferred Over gather()

```python
async with asyncio.TaskGroup() as tg:
    task1 = tg.create_task(fetch_url(url1))
    task2 = tg.create_task(fetch_url(url2))
    task3 = tg.create_task(fetch_url(url3))
# All tasks complete here. If any raises, all are cancelled.
results = [task1.result(), task2.result(), task3.result()]
```

**TaskGroup vs gather():**
- TaskGroup: structured concurrency, automatic cancellation on failure, cleaner error handling
- gather(): returns results in order, `return_exceptions=True` for mixed success/failure
- **Use TaskGroup** for new code. Use `gather()` only when you need `return_exceptions=True`

### Rate Limiting with Semaphore

```python
sem = asyncio.Semaphore(10)  # Max 10 concurrent

async def limited_fetch(url):
    async with sem:
        return await fetch_url(url)
```

### Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Forgotten `await` | Coroutine object returned, not result | Always await coroutines |
| Blocking the event loop | Everything freezes | Use `run_in_executor()` for blocking calls |
| Fire-and-forget tasks | Tasks silently dropped, exceptions lost | Always hold task references |
| Not using `async with` for resources | Connection leaks | Use async context managers |

### Async Libraries

| Library | Purpose | Status (2026) |
|---------|---------|---------------|
| **httpx** | HTTP client (sync + async) | Recommended |
| **asyncpg** | PostgreSQL (5x faster than psycopg sync) | Active |
| **aiosqlite** | SQLite async | Active |
| **SQLAlchemy 2.0** | Async ORM sessions | Active |
| **aiofiles** | File I/O | Active |
| **aioredis** | **Merged into redis-py** | Use `redis.asyncio` |
| **Motor** | **Deprecated** (May 2025) | Use PyMongo native async |

## multiprocessing (CPU-Bound)

### ProcessPoolExecutor (Recommended)

```python
from concurrent.futures import ProcessPoolExecutor
import os

with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
    results = list(executor.map(cpu_intensive_task, data_chunks))
```

### Pool Sizing

| Workload | Formula |
|----------|---------|
| Pure CPU | `os.cpu_count()` |
| CPU + some I/O | `os.cpu_count() + 2` |
| I/O-heavy (threads) | `min(32, os.cpu_count() + 4)` or higher |

### Start Method (Python 3.14 Change)

Python 3.14 changed the default start method for `ProcessPoolExecutor` to **forkserver** on Linux (was fork). This is safer but slightly slower to start.

**Rules:**
- Never mix `fork` with threads (deadlock risk)
- `spawn` is safest (default on Windows/macOS)
- `forkserver` is the new Linux default — good balance of safety and performance
- All data passed to workers must be **picklable**

### Shared Memory (Large Data)

```python
from multiprocessing import shared_memory
import numpy as np

shm = shared_memory.SharedMemory(create=True, size=array.nbytes)
shared_array = np.ndarray(array.shape, dtype=array.dtype, buffer=shm.buf)
shared_array[:] = array[:]  # Copy data once
# Workers access via shm.name — no serialization overhead
```

## concurrent.futures

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=20) as executor:
    futures = {executor.submit(fetch, url): url for url in urls}
    for future in as_completed(futures):
        url = futures[future]
        try:
            result = future.result(timeout=30)
        except Exception as e:
            logger.error(f"Failed {url}: {e}")
```

**submit() vs map():**
- `submit()`: returns Future objects, use with `as_completed()` for results as they arrive
- `map()`: simpler, returns results in input order, less control

## Data Processing Parallelism

| Tool | Best For | Speed vs pandas |
|------|----------|----------------|
| **Polars** | DataFrames (auto multi-core, Rust) | **3-10x faster** |
| **Modin** | Drop-in pandas replacement | 2-4x faster |
| **Dask** | Larger-than-memory datasets | Depends on cluster |
| **Ray** | Distributed computing, ML | Cluster-scale |
| **joblib** | Simple loop parallelism | Easy to add |

**2026 recommendation:** For new data processing, default to **Polars** unless you need pandas compatibility. Polars automatically uses all CPU cores and has lazy evaluation.

## Task Queues (Production Background Jobs)

| Queue | Throughput | Best For |
|-------|-----------|----------|
| **Celery** | Highest | Complex workflows, scheduling, monitoring |
| **Dramatiq** | High | Simpler API, fewer footguns than Celery |
| **Huey** | Medium | Small projects, SQLite/Redis backend |
| **RQ** | Medium | Redis-only, simple jobs |
| **arq** | Medium | Async-native (asyncio), Redis backend |

**Flask integration:** Use Celery or Dramatiq with Redis broker. For simple cases, `concurrent.futures` in a background thread may suffice.

### Retry Pattern

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    reraise=True
)
def call_external_api(url):
    response = httpx.get(url, timeout=10)
    response.raise_for_status()
    return response.json()
```

## GIL-Free Python (3.13-3.14)

- Python 3.13: experimental `--disable-gil` build flag
- Python 3.14: officially supported free-threading with **5-10% single-thread penalty**
- `concurrent.interpreters` (PEP 734): sub-interpreters with separate GILs — true parallelism without process overhead
- **Don't rush to free-threading**: Most C extensions aren't thread-safe yet. asyncio + multiprocessing covers 95% of use cases today

## Connection Pooling

| Resource | Library | Pattern |
|----------|---------|---------|
| PostgreSQL | SQLAlchemy / asyncpg pool | `pool_size=10, max_overflow=20` |
| HTTP | httpx | `httpx.AsyncClient(limits=httpx.Limits(max_connections=100))` |
| Redis | redis-py | `ConnectionPool(max_connections=50)` |

**Rule:** Always use connection pools for external resources. Creating new connections per request is a performance killer.

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Use threading for CPU-bound work | GIL prevents true parallelism (until free-threading matures) |
| Create unlimited threads/processes | Resource exhaustion — always use pools with max_workers |
| Fork + threads | Deadlock risk — use `spawn` or `forkserver` |
| Fire-and-forget async tasks | Lost exceptions, resource leaks |
| Block the asyncio event loop | Freezes all concurrent tasks — use `run_in_executor()` |
| Use `aioredis` or `Motor` for new code | Deprecated — use `redis.asyncio` and PyMongo async |
| Over-parallelize (more workers than cores for CPU work) | Context switching overhead exceeds benefit |
| Skip error handling in worker tasks | Silent failures — always catch and log in workers |
| Use `os.fork()` directly | Unsafe — use multiprocessing or concurrent.futures |
