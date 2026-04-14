# Frontend Performance

Reference file for `performance` skill. Browser-side perceived performance: Core Web Vitals, interaction latency, animation smoothness, and progressive-loading patterns.

**Scope boundaries**:
- Server-side load and latency → `load-testing.md`
- JS heap / CPU profiling on the server → `profiling.md`
- Query-time regressions that surface as slow page loads → `database.md`

Cross-link back when the frontend signal traces to the backend — a slow LCP caused by a 2 s API call is a backend problem seen through a browser metric.

---

## Core Web Vitals

Google's user-experience metrics, all captured at p75 of the target population.

| Metric | Budget | What it measures | Common causes |
|---|---|---|---|
| LCP (Largest Contentful Paint) | 2.5 s | Time to paint the largest above-the-fold element | Slow server response, render-blocking CSS/JS, large hero image, late font |
| CLS (Cumulative Layout Shift) | 0.1 | Visual stability across the lifetime of the page | Images without `width`/`height`, ads injected late, font swap, banner insertion |
| INP (Interaction to Next Paint) | 200 ms | Latency from user input to the next visual update | Long-running JS handlers, main-thread congestion, heavy hydration, frequent re-renders |
| TTFB (Time to First Byte) | 800 ms | Server response time as seen by the browser | Backend latency, geographic distance, cold cache, uncompressed response |
| FCP (First Contentful Paint) | 1.8 s | Time to first pixel of content | Same as LCP + render-blocking resources |

INP replaced FID in March 2024 — use INP.

Budgets above are the "good" threshold from Google's guidance. Contract may tighten them per scope.

---

## Measurement

### Lighthouse CI (lab)

- Repeatable synthetic runs with simulated throttling
- Good for regression gates in CI
- Does not observe real-user interactions (INP is synthesised from TBT and max-potential-FID)
- Template: `scripts/lighthouse-ci-template.js`

```bash
LHCI_TARGET_URL=https://staging.example.com \
LHCI_PERF_ENV=staging \
LHCI_LCP_MS=2500 LHCI_CLS=0.1 LHCI_INP_MS=200 \
npx @lhci/cli autorun --config=scripts/lighthouse-ci-template.js
```

### Playwright programmatic CWV (lab, more faithful INP)

- Controlled browser automation with synthesised interactions
- Reads live web-vitals callbacks (LCP / CLS / INP)
- Template: `scripts/playwright-perf-template.ts`

```bash
PERF_ENV=staging \
TARGET_URL=https://staging.example.com/products \
LCP_MS=2500 CLS=0.1 INP_MS=200 \
npx playwright test scripts/playwright-perf-template.ts
```

### Real User Monitoring (field)

Lab numbers predict; field numbers decide. When available, correlate lab regressions with RUM data (Chrome UX Report, SpeedCurve, Datadog RUM, Vercel Analytics, or the `web-vitals` lib reporting to your own ingest).

| Signal mismatch | Likely cause |
|---|---|
| Lab passes, field fails | Real devices / network / geo are worse than the lab profile; ship a slower lab profile |
| Lab fails, field passes | Lab throttling is over-aggressive; keep the lab strict as a safety margin |
| Both fail | Real regression — fix |

---

## Interaction Latency (INP)

INP captures the slowest "user did a thing" → "screen updated" window during the session, at p75.

Common causes (ranked by frequency):

1. **Long synchronous JS** in event handlers (loops, JSON parse / stringify on large payloads, expensive re-renders)
2. **Frequent re-renders** in React/Vue/Angular (missing memoisation, state changes that flood the tree)
3. **Hydration blocking** on SSR frameworks (Next.js / Remix / Nuxt) — first interaction is slow because hydration hasn't finished
4. **Main-thread contention** from third-party scripts (ads, analytics, live chat)
5. **Forced synchronous layout** (read-then-write pattern against the DOM)

Diagnosis:

- Chrome DevTools → Performance tab → record → interact → look for "Long tasks" (>50 ms) around the interaction
- `performance.getEntriesByType('longtask')` in a monitor
- React: Profiler tab, look for wasted renders
- Move the handler body into `requestIdleCallback` or a worker if the work isn't user-visible

---

## Animation Smoothness

Target: 60 fps — a 16.6 ms budget per frame.

| Signal | Meaning | Fix |
|---|---|---|
| Frame drops visible in DevTools Rendering → Frame Rendering Stats | Too much work per frame | Reduce work, move off main thread, simplify styles |
| Jank during scroll | Scroll event handlers doing layout work | Use `passive: true`; do heavy work in `requestAnimationFrame` / worker |
| Paint flashing (DevTools Rendering → Paint flashing) | Large repaint regions | Isolate changes with `will-change` or `transform` |
| Long task during animation | JS is stealing frame budget | Decouple animation from state; use CSS animations or Web Animations API |

Good animation properties: `transform`, `opacity`, `filter`. They are composited and do not force layout. Anything that changes layout (`top`, `left`, `width`, `margin`) forces the browser through layout + paint every frame — expensive.

---

## Perceived Performance Patterns

Real performance (what the clock measures) and perceived performance (what the user feels) differ. Perceived patterns close the gap.

| Pattern | When to use |
|---|---|
| Skeleton screens | Loading state visible for >500 ms |
| Optimistic UI updates | High-latency writes (likes, favourites, cart updates) |
| Progressive loading (content first, decorations second) | Hero sections with heavy imagery |
| Priority hints (`fetchpriority="high"` on LCP image) | Competing resources during initial load |
| `<link rel="preload">` critical CSS / fonts / LCP image | Late-discovered critical resources |
| `<link rel="preconnect">` to CDN / API origin | Cross-origin handshakes dominate sub-resource latency |
| Route-based code splitting | Bundle > 200 KB compressed |
| Image CDN with auto-format (WebP / AVIF) + `srcset` | Image-heavy pages |
| Font `font-display: swap` + subsetting | Text invisibility during font load |

Delegate implementation to `frontend-design` (React / Next / Angular / generic SPA) and `woocommerce-developer` / `wordpress-developer` for CMS stacks.

---

## CI Integration

Recommended minimum gate:

```
PR smoke  → Lighthouse CI on one critical URL, assertions on LCP/CLS/TBT
Nightly   → Lighthouse CI on the full URL set + Playwright programmatic CWV
Release   → Playwright CWV against preprod + RUM review
```

Fail the PR lane only on regressions (delta > threshold vs. baseline), not on absolute score — absolute scores fluctuate with network weather. Use assertion `warn` for absolute, `error` for delta.

---

## Output — Frontend Perf Finding Format

When invoked, `frontend-performance.md` produces:

```markdown
## Frontend Perf Finding: <url or component>

### Measurements (p75 across <N> iterations)
| metric | measured | budget | status |
|---|---|---|---|
| LCP | 3200ms | 2500ms | FAIL |
| CLS | 0.08 | 0.10 | PASS |
| INP | 240ms | 200ms | FAIL |
| TTFB | 900ms | 800ms | FAIL |

### Likely root causes (ranked)
- LCP: large hero image served uncompressed from origin (no CDN)
- INP: long task in product-list hydration (1.2 s), caused by ...
- TTFB: backend p95 regression — cross-link to load-testing.md

### Conditions
- Tool: Playwright + Lighthouse CI
- PERF_ENV: staging
- Generator: same LAN as server
- Date: 2026-04-13
- Source bundle hash: ...

### Synthesis & Improvements
For findings of type `lcp_budget_breach`, consult `references/improvement-catalog.md` § 6 Compression, § 7 CDN, § 9 Resource preloading, filtered by detected frontend stack.
For `inp_budget_breach`, see § 8 Lazy loading and § 11 Frontend rendering.
For `ttfb_regression`, cross-link to `load-testing.md` and `database.md`.
```

---

## Self-Learning

Log notable findings to `~/.claude/skills/_meta/perf-findings.jsonl` per the parent-skill schema, with:

- `finding_type`: `lcp_budget_breach`, `cls_budget_breach`, `inp_budget_breach`, `ttfb_regression`, `frontend_regression`
- `metric`: one of `lcp_ms`, `cls`, `inp_ms`, `ttfb_ms`, `fcp_ms`
- `target`: the budget value from the contract

---

## Anti-patterns

| Don't | Why |
|---|---|
| Optimise LCP by removing the largest element | You fixed the metric, not the experience — users still saw nothing faster |
| Use Lighthouse absolute scores as a gate | Scores fluctuate; assert on metric thresholds and deltas instead |
| Ignore RUM when lab passes | The lab is one device + one network; real users are many |
| Assume INP needs more CPU | It usually needs less main-thread contention — look for long tasks first |
| Chase 100/100 Lighthouse | Past the thresholds, more effort yields no user-visible win |
| Fix CLS by disabling the shifting feature | Ads / banners belong in stable-size containers, not removed |
| Apply perceived-perf patterns without measuring | Optimistic UI that reverts frequently is worse than honest latency |
