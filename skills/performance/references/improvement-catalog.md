# Improvement Catalog

Reference file for `performance` skill. Catalogue of common improvement patterns, with applicability, impact / effort estimates, and stack-specific owner skills. Consumed from the "Synthesis & Improvements" stubs in each measurement sub-skill — NOT a routing target.

The measurement sub-skills identify the problem; this catalogue names the pattern; the owning domain skill (python-flask-developer, frontend-design, etc.) owns the implementation detail.

---

## How to Use

1. Measurement sub-skill identifies a finding (e.g. "slow queries", "large LCP", "pool exhaustion").
2. Look up the matching category below.
3. Filter patterns by applicability (does the "when applicable" row match the finding?).
4. Rank by impact ÷ effort within the filtered set.
5. Delegate implementation to the listed **owner skill** for the detected stack.

Ranking is heuristic; actual impact is always measured after the change.

---

## Categories

### 1. Caching

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Application-level memoisation (hot, deterministic pure functions) | CPU hotspot in a function called repeatedly with same args | Medium | Low | python-flask-developer, nodejs-backend-patterns, java-backend |
| Query-result cache (Redis / Memcached) | Read-heavy endpoint, p95 dominated by DB time | High | Medium | python-flask-developer, nodejs-backend-patterns, database.md |
| HTTP response cache (`Cache-Control`, ETag) | Public idempotent GETs | High | Low | nodejs-backend-patterns, python-flask-developer, ubuntu-web-servers |
| CDN edge cache | Static + cacheable dynamic; global audience | Very High | Low–Medium | frontend-design, ubuntu-web-servers |
| Database query cache | Same query, same result, for short TTL | Medium | Low | database.md, mongodb, ubuntu-databases |

### 2. Query Optimisation

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Missing index on WHERE/JOIN column | `Seq Scan` on large table (EXPLAIN) | Very High | Low | `database.md` |
| Composite index for multi-column filter | WHERE `a = ? AND b = ?`, or WHERE + ORDER BY | High | Low | `database.md` |
| Partial index | Filter hits a narrow subset of a large table | High | Low | `database.md` |
| Rewrite correlated subquery → JOIN | Subquery in WHERE, evaluated per row | High | Medium | `database.md` |
| SELECT only needed columns | Fetching wide rows for narrow projection | Low–Medium | Low | `database.md` |
| Pagination via keyset (not OFFSET) | Deep-page queries on large tables | High | Medium | `database.md` |

### 3. N+1 Elimination

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Eager load via ORM helpers (`joinedload`, `select_related`, `with`, `include`) | Query count scales with result size | Very High | Low | python-flask-developer (SQLAlchemy), java-backend (Hibernate), nodejs-backend-patterns (Prisma/TypeORM), woocommerce-developer (Eloquent) |
| DataLoader / batching layer | Graph / resolver-driven N+1 | High | Medium | nodejs-backend-patterns |
| Explicit JOIN in a custom repository method | ORM-driven eager load is too broad | Medium | Medium | database.md, python-flask-developer |

### 4. Connection Pooling

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Right-size DB pool (2 × cores + 1) | Pool saturation under load | High | Low | `database.md`, ubuntu-databases |
| Add pgbouncer / ProxySQL | Multi-process/multi-host app exceeds DB `max_connections` | Very High | Medium | ubuntu-databases, rhel-databases |
| HTTP client keep-alive + pool | Outbound HTTP latency dominated by TLS handshake | High | Low | python-flask-developer, nodejs-backend-patterns |
| Connection leak fix | Connection count grows monotonically | Very High | Medium | `database.md`, domain skill |

### 5. Async Processing / Queueing

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Defer non-essential work to a queue | Endpoint does non-user-visible work inline | High | Medium | python-parallelism, nodejs-backend-patterns |
| Bulk / batch external API calls | Loop-of-requests to the same upstream | High | Medium | python-parallelism, nodejs-backend-patterns |
| Concurrent I/O via asyncio / Promise.all | Sequential independent I/O | High | Low–Medium | python-parallelism, modern-javascript-patterns |
| Move CPU-bound work out of the request | Handler blocks on CPU-heavy work | High | Medium | python-parallelism (multiprocessing) |

### 6. Compression

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| gzip / brotli on responses | Large JSON / HTML / JS payloads | Medium–High | Low | ubuntu-web-servers, rhel-web-servers, nodejs-backend-patterns |
| Image format optimisation (WebP / AVIF) | Image-heavy pages | High | Low | frontend-design |
| Font subsetting | Custom fonts dominate LCP | Medium | Low | frontend-design |
| Payload trimming (drop unused fields) | Over-fetching APIs (REST or GraphQL) | Medium | Low | frontend-design, domain API skill |

### 7. CDN / Edge Caching

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Push static assets to a CDN | Any non-CDN site with meaningful static bytes | High | Low | frontend-design, ubuntu-web-servers |
| Edge caching of cacheable APIs | Geo-distributed users, cacheable GETs | High | Medium | ubuntu-web-servers |
| Image CDN (auto-format, resize) | Image-heavy sites | High | Low | frontend-design |

### 8. Lazy Loading / Code Splitting

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Route-based code splitting | SPA bundle dominates first-load time | High | Medium | frontend-design, modern-javascript-patterns |
| Component-level lazy (`React.lazy`, dynamic import) | Rarely-visited UI sections | Medium | Low | frontend-design, modern-javascript-patterns |
| Lazy image loading (`loading="lazy"`) | Long pages with many images | Medium | Low | frontend-design |
| Defer non-critical `<script>` | Render-blocking third-party scripts | High | Low | frontend-design |

### 9. Resource Preloading

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| `<link rel="preload">` critical CSS/fonts | LCP dominated by late font / CSS discovery | High | Low | frontend-design |
| `<link rel="preconnect">` to CDN / API | TLS handshake dominates sub-request latency | Medium | Low | frontend-design |
| HTTP/2 server push | (Deprecated in most browsers — prefer preload) | n/a | n/a | frontend-design |

### 10. Read Replicas / Read-Write Split

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Point read-only endpoints at replica | Read traffic saturates primary | Very High | Medium | ubuntu-databases, rhel-databases |
| Stale-tolerant reads (eventual consistency) | UI can tolerate seconds of lag | High | Medium | database.md, domain API skill |

### 11. Frontend Rendering

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Skeleton screens / optimistic UI | Perceived-perf issue, not latency issue | Medium–High | Medium | frontend-design |
| Progressive hydration / island architecture | SPA ships too much JS for first paint | High | High | frontend-design |
| Virtualised lists / grids | Long lists cause jank on scroll | High | Medium | frontend-design |
| Avoid layout thrash (`requestAnimationFrame`, CSS `contain`) | High CLS, frame-budget overruns | Medium | Medium | frontend-design |
| GPU-backed animations (`transform`, `opacity`, `will-change`) | Frame-rate drops during animation | Medium | Low | frontend-design |

### 12. Infrastructure & Resource Right-sizing

| Pattern | When applicable | Impact | Effort | Owner skill |
|---|---|---|---|---|
| Vertical scale (more CPU/memory) | Single-instance ceiling, short-term fix | Medium | Low | ubuntu-server-admin, rhel-server-admin |
| Horizontal scale (more replicas) | Stateless service, load > single-node capacity | High | Medium | docker-admin, domain infra skill |
| Worker count tuning (uWSGI/Gunicorn/PM2) | Request queuing within an instance | High | Low | python-flask-developer, nodejs-backend-patterns |
| GC tuning | Long GC pauses visible in p99 | Medium | Medium | java-backend, profiling.md |

---

## Filter Helpers

When a measurement finding is captured, match it to this catalogue by:

| Finding signal | Category to consult |
|---|---|
| p95 latency high, CPU also high | 5. Async processing, 12. Right-sizing |
| p95 latency high, CPU low, DB time high | 2. Queries, 3. N+1, 10. Replicas |
| p95 latency spikes during GC | 12. GC tuning (profiling.md) |
| Throughput plateaus below expected | 4. Pooling, 12. Worker tuning |
| LCP budget breach | 6. Compression, 7. CDN, 9. Preloading |
| CLS budget breach | 11. Layout (CSS `contain`, size attrs on images) |
| INP budget breach | 11. Rendering, 5. Async |
| Queue depth grows unboundedly | 12. Horizontal scale of consumers; upstream review |
| Memory grows over soak | Leak fix (code review); GC tuning; 5. async defer |

---

## Stack-aware Delegation

Before applying a pattern, confirm the detected stack and route to the right skill:

| Detected stack | Primary owner skills to pair with this catalogue |
|---|---|
| Python / Flask | python-flask-developer, python-parallelism, database.md |
| Python / Django | python-flask-developer (patterns), python-data-engineer, database.md |
| Node.js / Express, Fastify | nodejs-backend-patterns, modern-javascript-patterns |
| Java / Spring | java-backend, profiling.md (async-profiler) |
| PHP / WooCommerce | woocommerce-developer, wordpress-developer |
| Go | profiling.md (pprof), database.md |
| Frontend (React / Next / Angular) | frontend-design, java-frontend |

When the stack is uncertain, delegate to `research-for-skills/gap-detection.md` before applying stack-specific patterns.

---

## Anti-patterns

| Don't | Why |
|---|---|
| Apply every pattern that "might help" | Each change muddies the signal; apply one, re-measure, keep or revert |
| Assume impact / effort ratings without re-measuring for your workload | These are heuristics; your workload's actual numbers are authoritative |
| Skip the owner skill and improvise | Stack-specific details (ORM syntax, framework quirks) live in the domain skill, not here |
| Treat this catalogue as an optimisation checklist | It is a lookup for a specific finding — not "implement everything" |
| Expand this catalogue inline from synthesis sections | Keep it a single source of truth; expansions happen here, not in sub-skills |
