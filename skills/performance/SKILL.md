---
name: performance
description: Use when profiling code, load testing, optimizing database queries, measuring Core Web Vitals, building a capacity model, defining a performance test contract, or any performance-related analysis. Parent skill for the performance-* family — routes to profiling, load-testing, database, frontend-performance, or capacity-planning based on context and the detected tech stack.
---

# Performance

Parent skill for performance analysis and optimisation. Routes to sub-skills based on the user's need and the detected tech stack, delegates runnable artifacts to `scripts/` templates, and references the improvement catalogue for synthesis — never inlines it.

## Companion Files

### Sub-skills (measurement)

- **profiling.md** — CPU/memory profiling, flame graphs, hotspot identification
- **load-testing.md** — Load/stress/spike/soak tools, SLA determination, capacity validation patterns
- **database.md** — Query optimisation, N+1 detection, index design, connection pool monitoring
- **frontend-performance.md** — Core Web Vitals, INP, animation smoothness, Lighthouse CI, Playwright CWV
- **capacity-planning.md** — Theoretical headroom math, contention scenarios, consumer of load-test output

### References (lookups, not routes)

- `references/perf-test-contract-template.md` — SLO + acceptance-criteria contract; source of truth for generating scripts
- `references/test-reality-model.md` — Environment isolation, warmup, mocks, CI tiers; mandatory pre-flight
- `references/workload-taxonomy.md` — Workload-shape table (HTTP, browser, queues, streaming, batch, cache)
- `references/improvement-catalog.md` — Improvement patterns with applicability, impact, owner skills

### Scripts (runnable templates)

- `scripts/k6-template.js` — Parameterised k6 load test
- `scripts/locust-template.py` — Parameterised Locust load test
- `scripts/playwright-perf-template.ts` — Programmatic CWV via Playwright
- `scripts/lighthouse-ci-template.js` — Lighthouse CI config
- `scripts/capacity-model.py` — Consumes load-test JSON, emits capacity-model.md
- `scripts/detect-stack.sh` — Thin wrapper for non-context-aware callers; delegates to `project-documentation/context-detection`

---

## Stack Detection (Step 1)

Before routing, determine the stack and context. Reuse the existing detector — do not build a second one.

```
Read ~/.claude/skills/project-documentation/context-detection.md

Apply its Detection Flow (Steps 1-6) against the current project:
  - Step 1: PROJECT.md present?
  - Step 2: package manifest present?
  - Step 3: component membership
  - Step 4: consumer detection
  - Step 5: dependency depth
  - Step 6: classify → context_type (standalone | component | library | service | monorepo-package)

Extract the detected tech stack from the package manifest and PROJECT.md:
  - python-flask | python-django | python-fastapi
  - nodejs | nextjs | nestjs
  - java-spring
  - php-woocommerce | php-wordpress
  - go | rust | other
```

Report the detection to the user and offer override:

```
Detected stack: python-flask (pyproject.toml + Flask in dependencies).
Detected context_type: service (has public API, has consumers).
Override? [y/N]
```

After confirmation, surface the relevant domain skill for the synthesis phase:

| Detected stack | Primary domain skill |
|---|---|
| python-flask / python-fastapi | python-flask-developer |
| python-django | python-flask-developer + python-data-engineer |
| nodejs (Express / Fastify) | (no dedicated skill — use profiling.md + database.md) |
| nextjs / SSR React | modern-frontend |
| java-spring | java-backend |
| php-woocommerce | woocommerce-developer |
| php-wordpress | wordpress-developer |
| go | (no dedicated skill — use profiling.md + database.md) |

For non-context-aware callers (CI scripts, external tools), invoke `scripts/detect-stack.sh` which simply collects signals and points the caller back to `context-detection.md`. The script parses nothing — it is a wrapper, not a detector.

---

## Routing Table

| User Need | Route To | Notes |
|---|---|---|
| Profile / bottleneck / slow code | `profiling.md` | unchanged |
| Load test / stress / SLA validation | `load-testing.md` | also handles capacity execution |
| Slow queries / DB / N+1 / indexes | `database.md` | unchanged |
| Capacity / scaling / max users / headroom | `capacity-planning.md` | theory + math; consumes load-test output |
| Page speed / CWV / Lighthouse / jank / perceived perf | `frontend-performance.md` | new sub-skill |
| Performance contract / SLOs / acceptance criteria | `references/perf-test-contract-template.md` | template, not a sub-skill |
| Workload doesn't look like plain HTTP (queue / stream / batch / cache) | `references/workload-taxonomy.md` then linked sub-skill | lookup, not a route |
| "Make it faster" / improvement ideas | sub-skill's "Synthesis & Improvements" section → `references/improvement-catalog.md` | synthesis layer, not a route |

When a user asks for "performance" broadly, gather context first:

1. Run stack detection (above)
2. Classify the workload via `references/workload-taxonomy.md`
3. Choose the measurement sub-skill for the primary workload
4. Write a perf-test contract from `references/perf-test-contract-template.md` if the project has none
5. Run the measurement
6. Synthesise improvements from the matching `references/improvement-catalog.md` categories

---

## Synthesis-Section Pattern

Each measurement sub-skill (profiling, load-testing, database, frontend-performance, capacity-planning) ends with a short "Synthesis & Improvements" stub that:

1. Names the finding type (slow_query, lcp_budget_breach, headroom_exhausted, etc.)
2. Points at specific `references/improvement-catalog.md` categories
3. Delegates stack-specific implementation to the detected domain skill

These stubs are ~10 lines. They do NOT repeat the catalogue inline. This keeps the catalogue as the single source of truth and avoids drift across five sub-skills.

---

## Gap Detection

Before routing to a child skill:

1. Verify target exists (check `~/.claude/skills/performance/<name>.md`)
2. If missing: follow gap-detection protocol at `~/.claude/skills/research-for-skills/gap-detection.md`
3. If exists: invoke with context (detected stack, context_type, workload category, contract path if any)

---

## Performance Findings Output Format

All performance findings — from sub-skills or fallback guidance — use this structured format. Consumable by team-manager, bob, qa-reviewer, and development-lifecycle.

```markdown
## Performance Finding: [component]

### Measurement
| metric | measured | budget | status |
|---|---|---|---|
| [metric] | [value] | [target or N/A] | PASS/FAIL/BASELINE |

### Root Cause (if identified)
- [specific bottleneck]

### Recommended Fix
- [actionable fix — owned by detected-stack domain skill]

### Action Required
- [ ] Fix root cause
- [ ] Re-measure after fix
- [ ] Update performance budget if baseline changed
```

---

## Self-Learning

Log all significant findings to `~/.claude/skills/_meta/perf-findings.jsonl`:

```jsonl
{"date":"YYYY-MM-DD","project_type":"<stack>","component":"<name>","finding_type":"slow_query|hotspot|high_latency|memory_leak|regression|lcp_budget_breach|cls_budget_breach|inp_budget_breach|ttfb_regression|headroom_exhausted|workload-gap","metric":"<name>","measured":"<value>","target":"<value or N/A>","root_cause":"<description>","fix_applied":true|false,"improvement":"<before->after>"}
```

Log when:
- A performance issue is identified and measured
- A fix is applied and re-measured
- A baseline is established for the first time
- A workload type has no matching taxonomy row (type `workload-gap`)

Do NOT log:
- Speculative findings without measurements
- Duplicate entries for the same issue in the same session

---

## Standalone-First Design

This skill works without forge, bob, or PA:
- Directly usable by any agent or in standalone conversation
- No dependency on MCP tools or orchestration infrastructure
- Sub-skills and references are self-contained

### Optional PA Integration

If PA MCP tools are available (`pa_log_action`, `pa_update_task`):
- Log performance findings via `pa_log_action()`
- Update task status when performance checks complete

If PA is not available: skip silently. PA integration is optional.

---

## Anti-patterns

| Don't | Why |
|---|---|
| Optimise without measuring first | You might optimise the wrong thing. Measure, then fix. |
| Report "it's fast" without numbers | Numbers are evidence. Feelings are not. |
| Skip baseline measurement | Without a baseline, you cannot prove improvement. |
| Test with unrealistic data volumes | Production data is 10-100× larger than test data. Scale matters. |
| Focus on averages instead of percentiles | p95/p99 reveal the real user experience. Averages hide outliers. |
| Block tasks to run performance tests | Performance is a dimension of TEST phase, not a separate gate. |
| Assume all changes need perf testing | Config, docs, CSS-only, test-only changes do not need it. |
| Run perf tests against production | The scripts refuse; the harness must too. See `test-reality-model.md`. |
| Compare results across different env tiers | Baselines are per-tier; cross-tier comparisons are invalid. |
| Accept "p95 = X" without warmup | First requests hit cold caches; warmup is mandatory per stack. |
| Generate runnable scripts before the contract exists | The contract drives the scripts; generating the other way round guarantees drift. |
| Embed runnable code in these .md files | Runnable artifacts live in `scripts/` — this file points at them. |
| Build a second stack detector | Reuse `project-documentation/context-detection`. `detect-stack.sh` is a wrapper only. |
| Duplicate the improvement catalogue in sub-skill synthesis sections | Synthesis is a 10-line lookup stub; the catalogue is the single source of truth. |
