---
name: modern-frontend
description: Use when building or debugging modern web front-ends — framework and rendering-mode selection (Vite SPA, Next.js SSR/SSG/ISR, hydration strategies), React/TypeScript component architecture, enterprise SPA patterns (Angular, NgRx, OIDC/PKCE, Nx monorepos), state and server-cache management, responsive layouts, Core Web Vitals as build-time budgets, source-map and browser-devtools debugging, bundle analysis and code splitting, testing (Playwright, MSW, axe/WCAG), and deployment-mode selection (static-first default, SSR only with platform validation). Trigger on - Vite, Next.js, SSR, SSG, hydration, React app, frontend build, web app performance budget, bundle size, frontend debugging, headless frontend. Headless WordPress/WooCommerce data boundaries live in wordpress-developer / woocommerce-developer; CWV measurement lives in performance; trading dashboards live in trading-dashboard-ux; UI/UX design decisions live in audience-experience-design.
disambiguation: The SELECTOR and cross-cutting layer — which framework, which rendering mode, Core Web Vitals budgets, debugging, bundle analysis, and the boundary where a front-end server surface should become a Node service. Depth on React itself is react-developer; depth on the Next.js framework is nextjs-developer; Angular and enterprise SPA patterns stay here.
---

# Modern Web Front-End Development

Owns modern web front-end work — framework and rendering-mode selection,
React/TypeScript component architecture, Core Web Vitals as build-time budgets,
and front-end debugging — **and** the **enterprise-SPA track** (Angular, NgRx,
RxJS, Nx monorepos, OAuth2/OIDC-with-PKCE) carried over intact from
`java-frontend`, which was promoted to this skill. Companion to `java-backend`
for the API tier.

**Seams (route, do not duplicate):**
- Headless data contracts live in `wordpress-developer` (§ Headless / Hybrid
  Boundary) and `woocommerce-developer` (§ Headless Storefront) — this skill
  builds the *consuming* app; those own the server-side contract.
- Core Web Vitals *measurement* lives in `performance` — this skill owns the
  *build-side budgets* that keep those metrics in range.
- Trading-application surfaces (order tickets, blotters) live in
  `trading-dashboard-ux`.
- What to build and for whom — audience, journey, information architecture, and
  token *semantics* — is decided upstream in `audience-experience-design`; this
  skill implements that brief, it does not originate it.

<HARD-RULE>
Never store JWT tokens in localStorage — use httpOnly cookies or in-memory storage to prevent XSS token theft. localStorage is readable by any script on the page, including injected XSS payloads. A single XSS vulnerability means every stored token is exfiltrated.
</HARD-RULE>

<HARD-RULE>
Always implement loading and error states for every async operation — unhandled states cause blank screens and confused users. Every fetch, mutation, and navigation that touches the network must have explicit pending, success, and error UI paths.
</HARD-RULE>

<HARD-RULE>
Never subscribe to observables without unsubscribing (Angular) — memory leaks accumulate and crash the browser tab in long-running SPAs. Use takeUntilDestroyed(), async pipe, or DestroyRef to guarantee cleanup. In React, always return cleanup functions from useEffect.
</HARD-RULE>

<HARD-RULE>
Always use semantic HTML elements before adding ARIA attributes — div with role="button" is never better than a real button element. Native elements provide keyboard handling, focus management, and screen reader announcements for free. ARIA is a repair tool, not a replacement.
</HARD-RULE>

---

> **Depth lives in the dedicated skills.** This file decides *which* framework and *which* rendering
> mode, and owns the cross-cutting concerns. For React itself — Server vs Client Components, Actions,
> the React Compiler, hooks and render behaviour — use **`react-developer`**. For the Next.js
> framework — App Router, Cache Components and the `use cache` model, Route Handlers, Turbopack,
> deployment targets — use **`nextjs-developer`**. Angular and enterprise SPA patterns stay here.
>
> **Two currency notes that invalidate older advice:** the React Compiler is stable and makes manual
> memoisation mostly unnecessary, and Next.js 16 **inverted caching to opt-in** (`'use cache'`).
> Check the version before applying any remembered guidance on either.

## Framework & Rendering-Mode Selection

The first decision is the **rendering mode**, not the framework. Choose by how
the content behaves, then pick the tool that serves it.

| Mode | Best for | SEO | Update cadence | Hosting need |
|---|---|---|---|---|
| **SPA** (Vite + React/Angular) | Authenticated app shells, dashboards, internal tools | Weak (client-rendered) | Live/interactive | Static host + API |
| **SSG** (Next static export, Astro) | Marketing, docs, blogs, mostly-static content | Strong | Rebuild on change | Static host / CDN |
| **ISR** (Next incremental) | Large catalogs, content that changes but not per-request | Strong | Background revalidate | Node runtime |
| **SSR** (Next request-time) | Per-request personalization, auth-gated pages, fresh data | Strong | Per request | Node runtime |

- **Static-first is the DEFAULT.** Ship SSG/SPA unless a concrete requirement
  (per-request personalization, auth-gated first paint, real-time freshness)
  demands a server. SSR trades a CDN edge hit for a server round-trip on every
  request — pay it only when the content genuinely varies per request.
- **Shared-hosting plan gate (verify before recommending SSR).** On Hostinger,
  the managed Node.js runtime (needed for SSR/ISR/API routes) exists on
  **Business Web Hosting and the Cloud tiers** (managed Node launched 2025-11;
  runtimes 18/20/22/24.x). The entry **Web Single / Web Premium** tiers have
  **no managed Node runtime** — Next.js must be **statically exported** there
  and SSR/server-ISR/API routes will not run. **Before recommending SSR on
  shared hosting, confirm the plan tier provides a Node runtime AND run an SSR
  load test** — a server-rendered app on a plan that cannot serve it fails in
  production, not at build time. (Older "Node is VPS-only on Hostinger"
  guidance predates the 2025-11 launch and is stale.)

## Next.js Working Knowledge (App Router)

Current stable is **Next.js 16.x** (major 16 stable 2025-10); the **App Router
is the default** for new projects and **React Server Components are the default
component model** inside it.

- **Server-first is the primary performance lever.** App-Router pages and
  layouts are Server Components by default — they render on the server and **do
  not ship or hydrate** client JS. `"use client"` marks a Client Component
  boundary; hydration cost applies only to that client subset. **Maximize the
  server portion; push `"use client"` down to the leaves that truly need
  interactivity** — the client/server split IS the main performance decision,
  not a detail.
- **Data fetching & revalidation.** Fetch directly in async Server Components
  (or via an ORM). In Next 16, `fetch` is **not cached by default** — opt in
  with explicit cache options or Cache Components / `"use cache"`.
  `revalidatePath()` invalidates a route's data; `revalidateTag(tag, "max")`
  marks tagged data stale with SWR semantics (the one-argument `revalidateTag`
  form is deprecated).
- **Images & fonts.** `next/image` (built-in optimization) and `next/font`
  (self-hosted, layout-shift-safe) remain the standard. In Next 16 the Image
  `priority` prop is deprecated in favor of `preload`.
- **Hydration failure modes** (the usual production culprits): invalid HTML
  nesting; branching on `window` / `typeof window`; touching browser APIs
  during render; nondeterministic output (`Date.now()`, `Math.random()`,
  locale/timezone formatting); server-vs-client data-snapshot drift; CSS-in-JS
  misconfiguration; browser extensions or iOS auto-linking mutating the DOM;
  and CDN/Edge HTML rewriting. A hydration mismatch means the server HTML and
  the first client render disagreed — the fix is to make the first client
  render deterministic and identical to the server's.

**Never assume a headless toolkit is App-Router-current** — verify per tool
(see Headless Consumption below).

## Core Web Vitals as Build-Time Budgets

Core Web Vitals are LCP, INP, and CLS. *Measurement* of the shipped site lives
in `performance` (route there for profiling / CrUX / Lighthouse). This section
owns what the **build can actually control** — enforce these as CI gates:

- **Bundle-size budget per route** — cap the first-load JS per route (e.g. fail
  CI when a route's compressed first-load JS exceeds its budget); route-based
  code splitting and lazy boundaries keep it there.
- **Script-execution / TBT budget** — Total Blocking Time is the **lab proxy**
  for interaction responsiveness. Budget main-thread script work; defer or
  offload heavy work (web workers, `requestIdleCallback`).
- **Long Animation Frames (LoAF) mitigation** — use LoAF attribution to find
  the blocking/rendering work behind slow interactions and break it up; LoAF
  works in both lab/CI and field.
- **Image budget** — enforce modern formats (AVIF/WebP), correct `srcset`,
  explicit dimensions (prevents CLS), and lazy-loading below the fold.
- **Third-party script policy** — every third-party tag is a TBT and privacy
  cost; load behind consent, defer, or facade-load (e.g. lite embeds).

**Lab gates (build-time):** LCP ≤ 2.5 s and CLS ≤ 0.1 are measurable in the lab
and belong in CI. **INP (≤ 200 ms good) is a FIELD metric** — it depends on
real user interactions over the page lifetime and **cannot be measured at build
time**; track it post-release via RUM / CrUX, and use **TBT as the lab proxy**
during the build. Do not claim a build "passes INP" — a build can only reduce
the *risk* of poor INP.

## Debugging Modern Front-Ends

Front-end defects are largely invisible without the right traces — treat
debugging as a first-class workflow, not an afterthought.

- **Source maps in production** — ship **hidden** source maps (`sourcemap:
  'hidden'` — emitted but not referenced by a `//# sourceMappingURL` comment)
  so stack traces symbolicate in your error reporter without exposing maps to
  the public. Upload them to the error-reporting service at deploy time.
- **Browser devtools traces** — use the Performance panel to see hydration
  cost, long tasks, and layout shifts on a real interaction; the Network panel
  (with throttling) to catch waterfalls, oversized payloads, and blocking
  requests. Record a trace against the actual slow interaction, not a cold load.
- **Framework devtools** — React DevTools (Profiler for re-render storms and
  wasted renders) and the Next.js overlay / build output (which routes are
  server vs client, bundle composition).
- **Error boundaries + reporting** — wrap client subtrees in error boundaries
  with a graceful fallback, and report caught errors (with symbolicated stacks)
  to a monitoring service. A blank screen with no report is the worst outcome.

## Headless Consumption

A Next/Vite front-end consuming WordPress/WooCommerce owns the **UI and
rendering**, never the server-side contract:

- **The data contract lives server-side.** How WordPress exposes content (REST
  vs WPGraphQL, auth for previews, cache-invalidation webhooks) is owned by
  `wordpress-developer` (§ Headless / Hybrid Boundary). What WooCommerce keeps
  authoritative (cart/session, checkout, price/stock, payment/tax/inventory) is
  owned by `woocommerce-developer` (§ Headless Storefront). Build against those
  boundaries; do not re-implement them here.
- **WooCommerce cart is same-origin by default.** Reverse-proxy/rewrite the
  storefront's Store-API calls to the WordPress origin so session cookies stay
  first-party — a cross-domain decoupled front-end breaks cart persistence
  under CORS credential rules and Safari ITP. (Full rationale in
  `woocommerce-developer`.)
- **Verify toolkit App-Router status per tool.** WPGraphQL can be queried
  directly from Server Components / route handlers (no special adapter).
  Faust.js's App Router package (`@faustwp/experimental-app-router`) was
  **deprecated in 2025** — its supported path is the Pages Router; do not adopt
  it for a new App-Router build. For a new App Router project, fetch REST or
  WPGraphQL directly rather than adding a data-client framework you must then
  keep current.

## Next.js Server-Side Surface — and where a Node service begins

Next ships server code, and this skill owns the part **co-deployed with one
Next app** — but only that part. The boundary matters because the headless-WP
glue above (a secret-holding preview/auth endpoint, a `save_post` →
`revalidateTag` webhook receiver) IS Next server code with no other owner, while
a standalone backend service is explicitly out of scope (no dedicated skill —
route it away).

**modern-frontend OWNS (co-deployed with the app):**
- **Route Handlers** (`app/api/*/route.ts`) — app-local BFF, webhook/revalidation
  receivers, preview-auth endpoints holding server-side secrets (never in client
  JS).
- **Server Actions** — UI-originated mutations; NOT public APIs or third-party
  webhook receivers.
- **Server-Component data fetching + revalidation** (`revalidateTag`/`revalidatePath`).
- **`middleware.ts`** — auth gating, redirects, rewrites, cookies/headers.

**A Node backend SERVICE begins (route away — no dedicated skill; use
profiling.md + database.md) at ANY of:**
- independent deployment, or a versioned API consumed by clients other than this
  app;
- separate data/domain ownership, or independent scaling/SLOs;
- durable queues, workers, schedulers, or cron independent of the HTTP request
  lifecycle;
- long-running processing or persistent connections (WebSocket/streaming beyond
  RSC).

If a task drifts across that line, it is no longer a modern-frontend task —
do not grow this section to cover it (Node/TypeScript MCP servers go to
`mcp-server-creator`).

---

## Reference Files

Detailed code examples, patterns, and configuration for each topic area are in
the reference files below. Read the relevant file when working on that area.
The Angular/NgRx/OIDC material is the **enterprise-SPA track**; the React /
Vite / testing material serves both modern and enterprise builds.

| Topic | File | Covers |
|---|---|---|
| Angular 17+ patterns (enterprise-SPA track) | [angular-patterns.md](angular-patterns.md) | Standalone components, services with inject(), routing (lazy loading, guards, resolvers), interceptors (auth token, error handling), change detection (OnPush, signals) |
| React 18+/19 patterns | [react-patterns.md](react-patterns.md) | Function components with hooks, custom hooks (useApi, useDebounce, useLocalStorage), error boundaries, React Router 6 with loaders |
| State management | [state-management.md](state-management.md) | NgRx (store, effects, selectors) for Angular, Redux Toolkit for React, guidance on global vs local vs server-cache state |
| API, auth, and forms | [api-auth-forms.md](api-auth-forms.md) | HttpClient typed responses, Axios with TanStack Query, GraphQL/Apollo Client, OpenAPI code generation, OAuth2 PKCE flows (Angular and React), role-based UI rendering, Angular reactive forms, React Hook Form with Zod validation |
| Components and styling | [component-styling.md](component-styling.md) | Smart/container vs presentational components, compound component pattern, Storybook documentation, Tailwind CSS configuration, responsive Grid/Flexbox layouts, CSS custom properties theming |
| Testing, build, and a11y | [testing-build-a11y.md](testing-build-a11y.md) | Jest + Testing Library (React), Jasmine + Angular testing, Playwright E2E, Mock Service Worker (MSW), Vite 8 (Rolldown) build config, Nx monorepo, GitHub Actions CI/CD, environment variables, WCAG 2.1 |

---

## Decision Guide

**Choosing a rendering mode:** see Framework & Rendering-Mode Selection above —
decide the mode from content behavior first, static-first by default.

**Choosing a framework:**
- **Next.js (App Router, RSC)** — content sites, marketing, commerce
  storefronts, and anything needing SSR/SSG/ISR and strong SEO. Server-first by
  default.
- **Vite + React** — authenticated SPA shells, dashboards, and internal tools
  where SEO is irrelevant and you want the fastest dev loop and a static deploy.
- **Angular** — large enterprise apps wanting opinionated structure (DI, RxJS,
  NgRx); the enterprise-SPA track. Best for admin portals and data-heavy SPAs.

**Choosing state management:**
- Local state first (useState / signals) — component-scoped data.
- Server-cache libraries (TanStack Query, RTK Query) — for *server* state
  (caching, pagination, optimistic updates). Most "global state" is really
  server state; reach for a cache before a store.
- NgRx / Redux Toolkit — only for genuinely shared client state with complex
  flows or time-travel debugging needs.

**Choosing API integration:**
- REST with HttpClient/Axios — default for most APIs.
- TanStack Query — caching, pagination, optimistic updates.
- GraphQL/Apollo — when the backend exposes a GraphQL schema (e.g. WPGraphQL)
  and field-precise queries pay off.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Reaching for SSR by default | Pays a server round-trip on every request and needs a Node runtime the host may not have | Static-first (SSG/SPA); adopt SSR only for per-request personalization, and verify the hosting plan first |
| Marking everything `"use client"` | Ships and hydrates JS that could have stayed on the server; defeats RSC | Keep components server by default; push `"use client"` to the interactive leaves |
| Treating INP as a build-time gate | INP is a field metric; a green Lighthouse run does not mean good INP in the wild | Gate LCP/CLS + TBT in the lab; track INP via RUM/CrUX post-release |
| Fetching data in every component instead of a server-cache | Duplicate requests, inconsistent data, excessive re-renders | Use TanStack Query (React) or NgRx/signals (Angular) for server state |
| Not typing API responses in TypeScript | Runtime errors when the API shape changes; bugs found in production | Define types for all responses; validate at the boundary with zod/io-ts |
| Importing entire UI libraries for a few components | Bundle balloons; unused code shipped to users | Tree-shakeable imports; analyze the bundle; enforce a per-route budget |
| No error boundaries or reporting | One failed call white-screens the app with no trace | Error boundaries with fallback UI + symbolicated error reporting |

---

## Related Skills

| Domain | Skill |
|---|---|
| Headless WordPress data boundary | `wordpress-developer` (§ Headless / Hybrid Boundary) |
| Headless WooCommerce storefront boundary | `woocommerce-developer` (§ Headless Storefront) |
| Core Web Vitals measurement / profiling | `performance` |
| Trading-application UI surfaces | `trading-dashboard-ux` |
| Experience / UX design (pre-build brief) | `audience-experience-design` |
| An LLM feature in the app (retrieval, agents, API cost) | `rag-architecture`, `agentic-architecture`, `llm-api-optimization` |
| Java backend (Spring Boot, REST APIs) | `java-backend`, `java-spring-boot` |
| SaaS architecture / implementation | `saas-architecture`, `saas-developer` |
| Docker containers and CI/CD | `docker-admin`, `docker-cicd` |
| Auth and security patterns | `python-auth-security` |
| SEO and content optimization | `seo-structure-architect`, `seo-meta-optimizer` |
