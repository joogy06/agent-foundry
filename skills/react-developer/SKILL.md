---
name: react-developer
description: Use when building or reviewing React components — Server versus Client Components and where the boundary belongs, Actions and form submission, the use() API, useOptimistic and the other React 19 hooks, the React Compiler and why manual memoisation is now mostly obsolete, state management choices, effects and when NOT to use one, refs, error boundaries, Suspense and data fetching, and the render-behaviour traps that produce stale or duplicated UI.
disambiguation: REACT itself — components, hooks, the compiler, render behaviour. The Next.js framework around it (routing, caching, rendering modes, server surface) is nextjs-developer; choosing a framework or rendering mode in the first place is modern-frontend; Angular and enterprise SPA patterns stay in modern-frontend.
---

# React

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29 against React 19.2.7.** React moves fast — re-check before relying on a version
claim.

## 1. What changed, and what it invalidates

Two shifts matter more than everything else, because they make widely-taught advice **wrong** rather
than merely dated.

### The React Compiler makes manual memoisation obsolete

**Stable at 1.0 since October 2025**, and it works back to React 17. It automatically memoises
components and values, which means:

- **Stop reaching for `useMemo` / `useCallback` / `React.memo` by default.** With the compiler on,
  most manual memoisation is noise the compiler already handles — and hand-memoising can *defeat* it
  by introducing dependencies it must respect.
- Keep them for genuinely expensive computations, or where profiling shows a real cost.
- **"Wrap everything in useCallback" is now actively bad advice.** It was always cargo-culted; it is
  now measurably counterproductive.

**Check whether the compiler is enabled before optimising anything.** The right answer differs
completely between a project with it and one without.

### Server Components are stable

Stable since 19.0, and they do not break between minors. They change where code *runs*, which is the
architectural decision underneath everything else — see §2.

## 2. Server vs Client Components — the boundary decision

**Server Components are the default in frameworks that support them.** They render on the server,
ship no JavaScript, and can reach data directly. Client Components opt in with `'use client'`.

```
Server Component            Client Component  ('use client')
─────────────────────       ────────────────────────────────
data fetching               state (useState, useReducer)
secrets, DB, filesystem     effects (useEffect)
zero JS to the client       event handlers (onClick, onChange)
async/await directly        browser APIs, refs to DOM
                            hooks generally
```

**Push `'use client'` down the tree, not up.** Marking a top-level layout as a Client Component drags
everything beneath it into the client bundle and forfeits the entire benefit. The pattern that works:
keep the page a Server Component and make only the interactive leaves clients.

**Server Components can render Client Components; the reverse needs `children`.** A Client Component
cannot import a Server Component, but it can *receive* one as a prop or child — that composition
gap is the most common early confusion.

**Props crossing the boundary must be serialisable.** Functions, class instances and Dates-with-methods
do not cross. Passing a callback down to a Client Component is a boundary error, not a style issue.

## 3. Actions — the form and mutation model

Actions handle async transitions, pending state and errors without hand-rolled `isLoading` state.

- **`useActionState`** — an action plus its result and pending state.
- **`useFormStatus`** — pending state for a parent form, read by a child (a submit button, typically)
  without prop drilling.
- **`useOptimistic`** — show the result immediately, and **React reverts automatically if the request
  fails**. This is the one worth adopting first; hand-rolled optimistic UI is where subtle bugs live.
- **Server Actions** (`'use server'`) — a Client Component calls an async function that executes on
  the server. React passes a reference, not the code.

**A Server Action is a public endpoint.** It is invoked over the network by whoever can reach it.
**Authenticate and authorise inside every action, and validate its arguments** — the fact that only
your UI calls it today is not a security control.

## 4. `use()` and Suspense

`use()` reads a promise or context inline, and unlike hooks it may be called conditionally.

- Suspense boundaries decide *where* a fallback appears — place them at meaningful UI seams, not
  around the whole page.
- **Do not create the promise during render** in a Client Component, or every render starts a new
  request. Create it in a Server Component or a cache, and pass it down.

## 5. Hooks and render behaviour — where bugs actually come from

- **You probably do not need an effect.** Deriving state during render, or computing in an event
  handler, is right far more often. Effects are for *synchronising with something outside React* —
  a subscription, a DOM measurement, a non-React library. Data fetching in an effect is a legacy
  pattern where Server Components or a data library exist.
- **Effects run twice in development StrictMode, deliberately.** It surfaces missing cleanup. Do not
  "fix" it by disabling StrictMode — fix the cleanup.
- **Stale closures** — an effect or callback capturing an old value. Usually a missing dependency or
  a value that should have been a ref.
- **Keys** — index keys break on reorder or insertion, producing wrong state on the wrong row.
  Use a stable id.
- **State updates are asynchronous and batched.** Reading state straight after setting it gives the
  old value; use the updater form when the next value depends on the previous.
- **Lifting state too high** re-renders large trees; **colocating it too low** causes prop drilling.
  The middle is where it belongs.

## 6. State — choose by shape

| Shape | Use |
|---|---|
| Local UI | `useState` |
| Complex transitions | `useReducer` |
| Deep, rarely-changing | Context — **it re-renders every consumer on change**, so keep it stable |
| Server data | A query library (TanStack Query, SWR) — caching, revalidation, dedupe |
| URL-worthy state | The URL. Filters, tabs and pagination belong there, not in memory |
| Cross-tree client state | Zustand/Jotai over Context when updates are frequent |

**Server state and client state are different problems.** Putting fetched data in a global store
means reimplementing caching, invalidation and dedupe badly. Most "state management" pain is server
state in the wrong container.

## 7. Anti-patterns

- **Manual memoisation everywhere** when the compiler is enabled.
- **`'use client'` at the top of the tree**, forfeiting Server Components entirely.
- **Passing functions across the server/client boundary.**
- **Server Actions without authorisation and argument validation.**
- **Fetching in `useEffect`** where Server Components or a query library apply.
- **Disabling StrictMode** to silence double-invoked effects.
- **Index keys** on reorderable lists.
- **Server data in a global store**, hand-rolling cache invalidation.
- **Reading state immediately after setting it.**
