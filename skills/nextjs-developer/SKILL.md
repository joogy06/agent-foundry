---
name: nextjs-developer
description: Use when building or reviewing a Next.js application on the App Router — routing, layouts and route groups, the rendering modes and where each is appropriate, Cache Components and the opt-in `use cache` model, data fetching and revalidation, Route Handlers and Server Actions, middleware, Turbopack, streaming and Partial Pre-Rendering, environment and secret handling, and the deployment-target decision. Covers the caching inversion that makes most older Next.js advice wrong.
disambiguation: The NEXT.JS framework — routing, rendering modes, caching, server surface, build and deploy. React itself (components, hooks, the compiler, render behaviour) is react-developer; choosing between Next.js, a Vite SPA or Angular in the first place is modern-frontend; where a Next server surface should become a separate Node service is modern-frontend's boundary section.
---

# Next.js — App Router

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29 against Next.js 16.2.7.** This framework changes fast and has reversed a major
default once already — re-check before relying on a version claim.

## 1. The caching inversion — read this before anything else

**Next.js 16 made caching opt-in. The older App Router cached aggressively by default.**

This is the single most important thing on this page, because it makes a large body of tutorials,
blog posts and remembered advice **wrong rather than merely dated**:

| | Old App Router | **Next.js 16** |
|---|---|---|
| Default | Cached aggressively | **Many fetches and route handlers default to `no-store`** |
| Opting in | Fighting the cache off | **`'use cache'` directive to opt IN** |
| Model | Implicit and surprising | **Cache Components** — explicit |

**The practical consequence in both directions:**

- Advice that says "remember to opt *out* of caching" is describing a version you are not on, and
  following it produces uncached-and-slow.
- If you upgraded from an older major, **things that were silently cached now are not** — a route
  that felt fast may now hit the origin every request.

**When you see a caching claim about Next.js, check which major it applies to before acting on it.**

## 2. Rendering modes — pick per route, not per app

| Mode | Renders | Use for |
|---|---|---|
| **Static** | Build time | Marketing, docs, anything not per-user |
| **Dynamic (SSR)** | Per request | Personalised or auth-dependent pages |
| **ISR / revalidate** | Build, then refreshed | Content that changes on a known cadence |
| **Client** | Browser | Highly interactive islands |
| **PPR** | Static shell + streamed dynamic holes | Mostly-static pages with a personal corner |

**Partial Pre-Rendering is the one that resolves the usual dilemma** — a static shell delivered
instantly with dynamic parts streamed in, instead of choosing between a fast generic page and a slow
personal one.

**Choose per route.** Making a whole app dynamic because one page needs personalisation is the
commonest and most expensive Next.js mistake.

## 3. App Router structure

```
app/
  layout.tsx          root layout — persists across navigation, does NOT re-render
  page.tsx            route UI
  loading.tsx         Suspense fallback for this segment
  error.tsx           error boundary ('use client' required)
  not-found.tsx
  (group)/            route group — organisation without a URL segment
  [id]/               dynamic segment
  api/route.ts        Route Handler
```

- **Layouts persist and do not re-render on navigation.** Per-page state belongs in the page.
- **Route groups** organise without affecting the URL — useful for separate layouts for marketing vs
  app sections.
- **`loading.tsx` is a Suspense boundary**, and it is how you stream rather than block.

## 4. Data fetching

- **Fetch in Server Components.** `async` components can await directly — no `useEffect`, no loading
  state, no client bundle cost.
- **Fetch in parallel.** Sequential awaits in one component create a waterfall; `Promise.all` where
  the calls are independent.
- **`'use cache'` to opt in**, with revalidation where the data has a known freshness.
- **Route Handlers** (`app/api/route.ts`) for webhooks, third-party callbacks and non-React consumers
   — not for your own components, which should reach data directly.
- **Server Actions** for mutations from the client, then revalidate the affected paths or tags.

**Do not build an internal API route just for your own Server Component to call.** It is a network
hop to your own process.

## 5. Server Actions are public endpoints

A Server Action compiles to a callable endpoint. **Whoever can reach your app can invoke it**, with
arguments of their choosing.

- **Authenticate and authorise inside the action itself.** Not in the component that renders the form
   — that check does not run on invocation.
- **Validate arguments** with a schema. Types are erased at runtime.
- Return typed errors rather than throwing raw ones across the boundary.

This is the most consequential security detail in the framework and the easiest to miss, because
locally it looks like calling a function.

## 6. Environment and secrets

- **`NEXT_PUBLIC_` is inlined into the client bundle.** Anything with that prefix is public,
  permanently, to anyone who views source. **Never prefix a secret.**
- Server-only variables are available in Server Components, Route Handlers and Actions.
- Keep real secrets out of the repo — `~/.secrets/<project>.env`, per
  `secret-scanning/references/storage-standard.md`.

## 7. Build and dev

- **Turbopack is the default dev bundler**, with filesystem caching stable and on. Expect
  substantially faster Fast Refresh; large projects benefit most.
- **Middleware runs on every matching request** — keep it small and use a narrow `matcher`. Heavy
  middleware taxes every route including static ones.
- **`next build` output tells you the mode per route.** Read it: a route you expected to be static
  showing as dynamic is a bug you can see before deploying.
- **Bundle analysis before optimising.** Guessing which import is heavy is usually wrong.

## 8. Deployment target — decide deliberately

Next.js runs beyond Vercel, but not every feature is equally available everywhere. **Confirm that ISR,
PPR, image optimisation and middleware behave as expected on your target before committing** — this
is `modern-frontend`'s static-first default: if a project does not genuinely need a server surface,
static export removes a whole class of operational cost.

If the server surface is growing past rendering — queues, schedulers, heavy background work — that is
the signal it should become a separate service rather than more Route Handlers.

## 9. Anti-patterns

- **Applying caching advice from an older major.** The default inverted; check the version.
- **Making the whole app dynamic** because one route needs personalisation.
- **Server Actions without authorisation and validation.**
- **`NEXT_PUBLIC_` on a secret.**
- **An internal API route your own Server Component calls.**
- **Sequential awaits** where the requests are independent.
- **`'use client'` in the root layout**, forfeiting Server Components app-wide.
- **Fat middleware** on a broad matcher.
- **Assuming feature parity** on a non-Vercel target without checking.
- **Ignoring the build output** that already told you a route is dynamic.
