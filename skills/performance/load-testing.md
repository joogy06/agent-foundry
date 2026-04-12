# Load Testing

Reference file for `performance` skill. Load/stress testing tools, methodology, SLA determination, and regression detection.

---

## Tool Selection

| Tool | Language | Best For | Install |
|------|----------|----------|---------|
| k6 | Go binary | Script-based HTTP load testing, CI integration | Binary download or brew |
| Locust | Python | Python-native, distributed testing | pip install locust |
| Artillery | Node.js | YAML-configured, CI-friendly | npm install -g artillery |
| wrk/wrk2 | C | Raw HTTP benchmarking, simple | Build from source or package |
| hey | Go binary | Quick ad-hoc benchmarking | Binary download or brew |
| vegeta | Go binary | Constant-rate load testing | Binary download |

### Tool Decision Tree

```
Need quick ad-hoc benchmark?
  -> hey (simplest CLI, one command)

Need scripted scenarios (login, browse, checkout)?
  -> k6 (JavaScript scenarios, best CI integration)
  -> Locust (Python scenarios, distributed)

Need constant-rate testing (not "as fast as possible")?
  -> vegeta (constant request rate)
  -> wrk2 (constant throughput mode)

Need YAML config for non-developers?
  -> Artillery (YAML + JS extensible)
```

### Quick-Start Commands

```bash
# hey -- quick benchmark
hey -n 1000 -c 50 http://localhost:8080/api/products

# k6 -- scripted load test
cat > test.js << 'EOF'
import http from 'k6/http';
import { check, sleep } from 'k6';
export const options = { vus: 50, duration: '30s' };
export default function () {
  const res = http.get('http://localhost:8080/api/products');
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(1);
}
EOF
k6 run test.js

# vegeta -- constant rate
echo "GET http://localhost:8080/api/products" | vegeta attack -rate=100 -duration=30s | vegeta report

# wrk -- raw throughput
wrk -t4 -c100 -d30s http://localhost:8080/api/products
```

---

## 5 Load Test Types

### 1. Smoke Test
- **Purpose:** Verify the system works under minimal load
- **Config:** 1-2 virtual users, 1-2 minutes
- **Pass criteria:** No errors, responses return
- **When:** Before every other test type. If smoke fails, nothing else matters.

### 2. Load Test
- **Purpose:** Verify SLAs at expected concurrency
- **Config:** Expected concurrent users, 5-15 minutes
- **Pass criteria:** p95 latency within SLA, error rate <1%, throughput stable
- **When:** After code changes to endpoints, before release

### 3. Stress Test
- **Purpose:** Find the breaking point
- **Config:** 2-3x expected concurrency, ramp up gradually
- **Pass criteria:** System degrades gracefully (no crashes, no data corruption)
- **When:** Capacity planning, architecture validation

### 4. Spike Test
- **Purpose:** Test sudden burst handling and recovery
- **Config:** Jump from baseline to 5-10x concurrency instantly, hold 1-2 minutes, drop back
- **Pass criteria:** System recovers to baseline within 30 seconds after spike ends
- **When:** Systems expecting flash sales, marketing campaigns, viral events

### 5. Soak Test
- **Purpose:** Detect memory leaks, connection exhaustion, log growth
- **Config:** Normal concurrency, 1-4 hours
- **Pass criteria:** No degradation over time. Memory/CPU stable. No OOM kills.
- **When:** Before production release of long-running services

---

## SLA Determination Process

### Step 1: Check Existing Budgets

```
IF COMPONENT.md has performance budget -> use those targets
IF PROJECT.md has performance section -> use those targets
IF design doc specifies latency requirements -> use those
```

### Step 2: Establish Baseline (No Budget Exists)

1. Run smoke test to verify system works
2. Run load test at conservative concurrency (10 users, 30 seconds)
3. Record p50, p95, p99 latency and throughput (RPS)
4. Set initial SLA at 2x baseline p95

```
Baseline: p95 = 120ms at 10 concurrent users
Initial SLA: p95 < 240ms
```

### Step 3: Focus on Percentiles

| Metric | What It Tells You |
|--------|------------------|
| p50 (median) | Typical user experience |
| p95 | Worst case for most users (1 in 20 is slower) |
| p99 | Tail latency -- reveals queuing, GC pauses, outliers |
| Throughput (RPS) | System capacity -- requests per second at given concurrency |
| Error rate | Percentage of non-2xx responses |

**Always report p95 and p99, not just averages.** Averages hide the worst experiences.

### Step 4: Always Measure

These four metrics are mandatory for every load test:
1. Response time (p50, p95, p99)
2. Throughput (requests per second)
3. Error rate (% non-2xx)
4. Resource utilization (CPU, memory of the service under test)

---

## Regression Detection

### Process

1. Run baseline test, save results (before changes)
2. Apply code changes
3. Run same test with identical parameters
4. Compare p95 latency and throughput

### Regression Thresholds

| Metric | Regression If | Action |
|--------|--------------|--------|
| p95 latency | Increased >20% | Investigate root cause |
| Throughput (RPS) | Decreased >10% | Investigate root cause |
| Error rate | Increased from 0% to >0% | Critical -- fix immediately |
| p99 latency | Increased >50% | Investigate tail latency |

### Regression Report Format

```
## Load Test Regression: [component]

### Before (baseline)
| metric | value |
|--------|-------|
| p95 latency | 120ms |
| p99 latency | 250ms |
| RPS | 450 |
| Error rate | 0% |

### After (current)
| metric | value | delta |
|--------|-------|-------|
| p95 latency | 180ms | +50% REGRESSION |
| p99 latency | 300ms | +20% |
| RPS | 380 | -16% REGRESSION |
| Error rate | 0% | OK |

### Conditions
- Tool: k6
- Concurrency: 50 VUs
- Duration: 30s
- Date: YYYY-MM-DD
```

---

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Testing from same machine as the server | Network latency = 0, results are unrealistic. Use a separate machine or container. |
| Not warming up the application | First requests hit cold caches, JIT, connection pools. Warm up for 10-30 seconds first. |
| Using too-short test duration | <30 seconds misses GC pauses, connection pool exhaustion. Run 1-5 minutes minimum. |
| Testing a single endpoint in isolation | Real traffic hits multiple endpoints. Mix the scenario. |
| Ignoring resource utilization | The app might "pass" but be at 99% CPU -- no headroom for growth. |
| Comparing results across different hardware | Hardware changes invalidate comparisons. Pin to same infra. |

---

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Report only averages | Averages hide p99 nightmares. Always report percentiles. |
| Load test in production without warning | You will cause an incident. Use staging or get approval. |
| Use "as fast as possible" mode for SLA tests | Real users don't make 10,000 RPS. Use realistic concurrency. |
| Skip the smoke test | If the app is broken, load testing tells you nothing useful. |
| Test with empty databases | Production databases have real data. Seed realistic volumes. |
| Ignore think time between requests | Real users pause between clicks. Add sleep(1) between requests. |
