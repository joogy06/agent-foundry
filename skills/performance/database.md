# Database Performance

Reference file for `performance` skill. Query optimization, N+1 detection, index design, and connection pool monitoring.

---

## Query Analysis Per Database

| Database | Explain Command | Slow Query Detection |
|----------|----------------|---------------------|
| PostgreSQL | `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` | pg_stat_statements, log_min_duration_statement |
| MySQL/MariaDB | `EXPLAIN FORMAT=JSON` | slow_query_log, performance_schema |
| SQL Server | `SET STATISTICS IO ON; SET STATISTICS TIME ON` | Extended Events, Query Store |
| SQLite | `EXPLAIN QUERY PLAN` | .timer on |

### Quick-Start: Reading EXPLAIN Output

**PostgreSQL:**
```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) SELECT * FROM orders WHERE user_id = 42;
```

Key things to look for:
- **Seq Scan** on large tables = missing index
- **Nested Loop** with high actual rows = N+1 or cartesian join
- **Sort** with external merge = not enough work_mem
- **Buffers: shared read** = cache miss, data read from disk
- **Actual time** vs **estimated** divergence = stale statistics (run ANALYZE)

**MySQL:**
```sql
EXPLAIN FORMAT=JSON SELECT * FROM orders WHERE user_id = 42;
```

Key things to look for:
- `type: ALL` = full table scan
- `type: ref` or `type: eq_ref` = index used (good)
- `rows` much higher than expected = stale statistics or bad join
- `Extra: Using filesort` = sort not served by index
- `Extra: Using temporary` = temp table created

---

## N+1 Detection Per ORM

| ORM | Detection Method | Fix |
|-----|-----------------|-----|
| SQLAlchemy | Enable echo=True, count queries per request | joinedload() / selectinload() |
| Django ORM | django-debug-toolbar, assertNumQueries() | select_related() / prefetch_related() |
| Eloquent | DB::enableQueryLog(), clockwork | with() / load() |
| TypeORM | logging: true, query count | relations: { eager: true } / QueryBuilder join |
| Prisma | prisma.$on('query'), count events | include: {} in findMany |
| ActiveRecord | Bullet gem, ActiveSupport::Notifications | includes() / eager_load() |

### N+1 Detection Pattern

```
1. Count queries executed for a single request
2. If query count scales linearly with result set size -> N+1 detected
   Example: 1 query for 10 users + 10 queries for their orders = N+1
3. Fix: use eager loading (one query with JOIN or IN clause)
4. Verify: query count should be constant regardless of result set size
```

### Quick Detection Commands

**Python/SQLAlchemy:**
```python
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
# Count INFO lines per request
```

**Django:**
```python
from django.test.utils import override_settings
from django.db import connection
# In test: self.assertNumQueries(2, lambda: list(MyModel.objects.all()))
```

**Node.js/TypeORM:**
```typescript
// In data source config
logging: true
// Count query log entries per request
```

---

## Index Design Methodology

### Step 1: Check Existing Indexes

```sql
-- PostgreSQL
\di+ tablename

-- MySQL
SHOW INDEX FROM tablename;

-- SQL Server
SELECT * FROM sys.indexes WHERE object_id = OBJECT_ID('tablename');
```

### Step 2: Identify Missing Indexes from EXPLAIN

```
IF EXPLAIN shows Seq Scan on filtered column -> candidate for index
IF EXPLAIN shows Sort without index -> candidate for index on sort column
IF EXPLAIN shows Hash Join on large tables -> candidate for index on join column
```

### Step 3: Create and Verify

```sql
-- Create index
CREATE INDEX idx_orders_user_id ON orders(user_id);

-- Re-run EXPLAIN, verify scan type changed
EXPLAIN (ANALYZE) SELECT * FROM orders WHERE user_id = 42;
-- Should now show Index Scan or Bitmap Index Scan

-- Measure query time before/after
\timing on
```

### Index Design Rules

| Rule | Why |
|------|-----|
| Index columns used in WHERE clauses | Enables index scan instead of sequential scan |
| Index columns used in JOIN conditions | Speeds up join operations |
| Index columns used in ORDER BY | Avoids expensive sort operations |
| Use composite indexes for multi-column filters | (user_id, created_at) serves WHERE user_id=X ORDER BY created_at |
| Put high-selectivity columns first in composite indexes | Narrows results faster |
| Avoid indexing low-cardinality columns alone | Boolean columns have only 2 values -- index adds overhead without benefit |
| Partial indexes for subset queries | `WHERE status = 'active'` on a table that is 90% inactive |

### Index Overhead

Indexes are not free:
- Each index adds write overhead (INSERT, UPDATE, DELETE are slower)
- Each index consumes disk space
- Too many indexes slow down writes more than they speed up reads
- Rule of thumb: 5-10 indexes per table is typical. >20 suggests over-indexing.

---

## Connection Pool Monitoring

### Symptoms of Pool Problems

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Requests queuing, slow response | Pool exhaustion -- all connections in use | Increase pool size or reduce query time |
| Connection count growing over time | Connection leak -- connections not returned | Fix code to close/return connections |
| Intermittent "too many connections" | Pool too small for concurrency | Increase pool or add pgbouncer/ProxySQL |
| High latency on first request after idle | Pool connections expired, reconnecting | Set pool min idle connections |

### Optimal Pool Size

**PostgreSQL guideline:**
```
pool_size = 2 * CPU_cores + number_of_disks
```
For an 8-core server with SSDs: `2 * 8 + 1 = 17` connections.

**General rules:**
- Start conservative (10-20 connections)
- Monitor: if pool is always full, increase. If mostly idle, decrease.
- Total connections across all app instances must not exceed database max_connections
- Use a connection pooler (pgbouncer, ProxySQL) between app and database for high concurrency

### Monitoring Commands

```sql
-- PostgreSQL: active connections
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';

-- PostgreSQL: waiting queries (blocked by locks)
SELECT * FROM pg_stat_activity WHERE wait_event_type IS NOT NULL;

-- MySQL: connection status
SHOW STATUS LIKE 'Threads_connected';
SHOW STATUS LIKE 'Threads_running';

-- MySQL: max connections vs current
SHOW VARIABLES LIKE 'max_connections';
SHOW STATUS LIKE 'Max_used_connections';
```

---

## Common Query Optimization Patterns

| Pattern | Problem | Fix |
|---------|---------|-----|
| SELECT * | Fetches unnecessary columns, wastes I/O | Select only needed columns |
| No LIMIT on list queries | Returns unbounded results | Add LIMIT + pagination |
| LIKE '%term%' | Cannot use index (leading wildcard) | Full-text search or trigram index |
| OR conditions on different columns | Cannot use single index | UNION of indexed queries |
| Subquery in WHERE | Re-executed per row | Rewrite as JOIN |
| COUNT(*) on large tables | Full table scan | Use approximate counts or cached counts |
| Implicit type conversion | Index not used due to type mismatch | Match types in WHERE clause |

---

## Slow Query Investigation Checklist

1. [ ] Get the exact query (from slow query log, ORM logging, or application logs)
2. [ ] Run EXPLAIN ANALYZE on the query
3. [ ] Check for sequential scans on large tables
4. [ ] Check for N+1 patterns (multiple similar queries per request)
5. [ ] Check index coverage (are filtered/joined columns indexed?)
6. [ ] Check table statistics freshness (ANALYZE / OPTIMIZE TABLE)
7. [ ] Check for lock contention (pg_stat_activity, SHOW PROCESSLIST)
8. [ ] Measure before and after any change
9. [ ] Log finding to `_meta/perf-findings.jsonl`

---

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Add indexes without checking EXPLAIN first | You might index the wrong column |
| Remove indexes without checking impact | Other queries may depend on them |
| Optimize queries without measuring | The bottleneck might be elsewhere |
| Use ORM default fetching without thought | Default lazy loading causes N+1. Choose eager vs lazy intentionally. |
| Set pool size to max_connections | Leaves no room for admin connections or other services |
| Cache query results without invalidation strategy | Stale cache is worse than slow queries |
| Run EXPLAIN without ANALYZE | EXPLAIN alone shows estimates, not actual execution |
