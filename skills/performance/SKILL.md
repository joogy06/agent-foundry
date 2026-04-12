---
name: performance
description: Use when profiling code, load testing, optimizing database queries, identifying bottlenecks, measuring response times, or any performance-related analysis. Routes to profiling, load-testing, or database sub-skills based on context. Parent skill for the performance-* family.
---

# Performance

Parent skill for performance analysis and optimization. Routes to sub-skills based on the user's need, provides fallback guidance when sub-skills are missing, and logs findings for cross-project learning.

## Companion Skills

- **profiling.md** -- CPU/memory profiling, flame graphs, hotspot identification
- **load-testing.md** -- Load/stress testing tools and methodology
- **database.md** -- Query optimization, N+1 detection, index design

---

## Gap Detection

Before routing to a child skill:
1. Verify target exists (check `~/.claude/skills/performance/<name>.md`)
2. If missing: follow gap-detection protocol at `~/.claude/skills/research-for-skills/gap-detection.md`
3. If exists: invoke with context

---

## Context Detection Integration

Read the context-detection performance profile (if available) to determine what is applicable:

```
IF context_type available from project-documentation/context-detection:
  Read performance profile (hot_path, has_perf_budget, perf_sensitive_deps)
  Use recommended_perf_scope to guide routing
ELSE:
  Ask user about performance context
```

---

## Routing Table

| User Need | Route To | Fallback |
|-----------|----------|----------|
| Profile / bottleneck / slow code | profiling.md | General profiling guidance below |
| Load test / stress test / benchmark / SLA | load-testing.md | General load test guidance below |
| Slow queries / database / N+1 / indexes | database.md | General DB guidance below |
| Page speed / CWV / Lighthouse | Gap detected: log, offer creation | General frontend guidance below |
| API latency / throughput | Gap detected: log, offer creation | General API guidance below |
| Server resources / scaling | Gap detected: log, offer creation | General infra guidance below |

### Fallback Guidance (when sub-skill is missing or gap detected)

**Profiling fallback:** Measure before changing. Use language-native profilers (cProfile for Python, --prof for Node.js, pprof for Go). Look for the top 3 hotspots consuming the most time.

**Load testing fallback:** Start with a smoke test (1-2 users). Establish a baseline. Then test at expected concurrency. Focus on p95 latency, throughput (RPS), error rate. Tools: hey (quick), k6 (scripted), locust (Python).

**Database fallback:** Run EXPLAIN on slow queries. Look for sequential scans on large tables. Check for N+1 patterns (count queries per request). Verify indexes exist on filtered/joined columns.

**Frontend fallback:** Run Lighthouse in Chrome DevTools. Focus on LCP, CLS, INP. Check for blocking resources, unoptimized images, excessive JavaScript.

**API fallback:** Measure end-to-end latency with curl timing. Check for synchronous external calls without timeouts. Look for missing pagination on list endpoints.

**Infrastructure fallback:** Check CPU, memory, disk I/O, and network utilization. Identify whether bottleneck is CPU-bound, I/O-bound, or memory-bound.

---

## Performance Findings Output Format

All performance findings -- from sub-skills or fallback guidance -- use this structured format. This format is consumable by team-manager, bob, qa-reviewer, and development-lifecycle.

```markdown
## Performance Finding: [component]

### Measurement
| metric | measured | budget | status |
|--------|----------|--------|--------|
| [metric] | [value] | [target or N/A] | PASS/FAIL/BASELINE |

### Root Cause (if identified)
- [specific bottleneck]

### Recommended Fix
- [actionable fix]

### Action Required
- [ ] Fix root cause
- [ ] Re-measure after fix
- [ ] Update performance budget if baseline changed
```

---

## Self-Learning

Log all significant findings to `~/.claude/skills/_meta/perf-findings.jsonl`:

```jsonl
{"date":"YYYY-MM-DD","project_type":"<stack>","component":"<name>","finding_type":"slow_query|hotspot|high_latency|memory_leak|regression","metric":"<name>","measured":"<value>","target":"<value or N/A>","root_cause":"<description>","fix_applied":true|false,"improvement":"<before->after>"}
```

Log when:
- A performance issue is identified and measured
- A fix is applied and re-measured
- A baseline is established for the first time

Do NOT log:
- Speculative findings without measurements
- Duplicate entries for the same issue in the same session

---

## Standalone-First Design

This skill works without forge, bob, or PA:
- Directly usable by any agent or in standalone conversation
- No dependency on MCP tools or orchestration infrastructure
- Sub-skills are self-contained reference files

### Optional PA Integration

If PA MCP tools are available (`pa_log_action`, `pa_update_task`):
- Log performance findings via `pa_log_action()`
- Update task status when performance checks complete

If PA is not available: skip silently. PA integration is optional.

---

## Anti-Patterns

| Don't | Why |
|-------|-----|
| Optimize without measuring first | You might optimize the wrong thing. Measure, then fix. |
| Report "it's fast" without numbers | Numbers are evidence. Feelings are not. |
| Skip baseline measurement | Without a baseline, you cannot prove improvement. |
| Test with unrealistic data volumes | Production data is 10-100x larger than test data. Scale matters. |
| Focus on averages instead of percentiles | p95/p99 reveal the real user experience. Averages hide outliers. |
| Block tasks to run performance tests | Performance is a dimension of TEST phase, not a separate gate. |
| Assume all changes need perf testing | Config, docs, CSS-only, test-only changes do not need it. |
