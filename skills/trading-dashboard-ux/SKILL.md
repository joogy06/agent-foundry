---
name: trading-dashboard-ux
description: Use when designing or building the user-facing surfaces of a trading application — order-entry tickets, live blotters, and operator/monitoring consoles — where UX defects convert directly to monetary loss. Covers order-ticket safety (side/size/symbol/notional review, exact-order-digest confirmation, fat-finger guards, keyboard and focus safety), order-lifecycle presentation without optimistic success, market-data freshness encoding (quote age, feed degradation, session/halt/connection state), blotter and partial-fill presentation, alert prioritization, and render contracts that keep emergency cancel/reduce/flatten controls responsive under tick storms (off-main-thread ingestion). Trigger on - trading dashboard, order ticket UI, order entry form, live blotter, trading terminal UX, stale quote display, emergency flatten button. Analytical charts and KPI tiles live in the dataviz skill; generic SPA mechanics live in modern-frontend; signal design lives in observability.
family: trading
---

# Trading Dashboard UX

## 1. Overview + routing

The trading surface is where a UX defect becomes a **monetary loss**: a mis-shown side, a
stale quote taken as live, an "accepted" flatten read as "flat". This skill owns the
**trading-specific interaction contracts**, framework-agnostic. It does **not** own chart
design or generic SPA mechanics.

- **Analytical charts / KPI tiles → `dataviz`** (cross-link, never duplicate — this skill
  contains **no chart-construction content**).
- **Component mechanics, routing, generic auth/CSRF, forms → `modern-frontend`**.
- **Signal mapping, alert classes, cardinality budgets → `observability`**.
- **The state meanings it displays** come from `trading-automation-runtime` (the axes) and
  `market-data-engineering` (the feed-health facts); this skill **renders** them, it does
  not define them.

**Platform honesty rule (binding).** A surface that cannot meet the §6 end-to-end
emergency-command contract — e.g. a purely server-rendered framework with no isolated
client control channel — is **MONITORING-ONLY**, and the product must say so explicitly
rather than presenting order-entry controls it cannot make safe. A browser is not a
real-time safety kernel; emergency protection must **also** exist server-side (§6).

## 2. Order-ticket safety (core)

**The canonical order digest is constructed by the ADAPTER/SERVER, never by the UI.** Only
the server knows the post-normalization truth: tick/lot rounding, session routing, order
flags, fees, worst-case notional. A UI-built digest can diverge from what is actually
submitted. This skill owns the **presentation** of the server's digest and the
**consent-state UX**:

- **Confirmation is bound to `{user, account, environment, nonce, expiry}`.** Any mutation
  of the ticket (side, size, symbol, price, TIF, session) **invalidates** the consent;
  confirmations **expire**; double-click / replay is **idempotent** (the nonce dedupes).
- **Fat-finger guards present the risk owner's verdict — they never define it.** Notional
  caps are shown **from** `trading-risk-management` with provenance and an as-of time; the
  UI **never defines or overrides a cap**. It surfaces the breach and blocks confirm.
- **Side conventions** are explicit and validated (buy/sell/buy-to-cover/sell-short) — never
  inferred from a sign or a button color alone.
- **Unusual-symbol / unusual-size confirmation**, keyboard and focus safety (no submit on a
  stray Enter; destructive actions are not the default focus).
- **Paper-vs-live environment badge**, always visible, with a **masked** account id.

```js
// The UI RECEIVES a server digest; it never builds one. `side` is a validated field.
function presentTicket(serverDigest, riskVerdict) {
  const validSides = ["buy", "sell", "buy_to_cover", "sell_short"];
  if (!validSides.includes(serverDigest.side)) throw new Error("invalid side");
  return {
    view: serverDigest,                        // masked account, side, qty, type, limit, TIF, session, worstCaseNotional
    nonce: serverDigest.nonce,                 // binds consent; replay-safe
    expiresAt: serverDigest.expiresAt,         // consent expires
    capBreach: riskVerdict.notionalCap != null &&
               serverDigest.worstCaseNotional > riskVerdict.notionalCap,
    capProvenance: riskVerdict.source,         // shown, never overridden by the UI
    capAsOf: riskVerdict.asOf,
  };
}
```

## 3. Order-lifecycle presentation: command vs resource views

**Commands and resources are separate view models.**

- **Commands** — submit / cancel / replace / flatten *requests* — have their own lifecycle:
  `requested → accepted → acknowledged → { done | failed | unknown }`. A command that was
  *accepted* is not a resource that *changed*.
- **Resources** — orders / positions / fills — reuse the **adapter lifecycle vocabulary in
  full**: `new, accepted, partial, pending_cancel, pending_replace, canceled, expired,
  rejected`, and **`unknown / ambiguous`**. Never collapse them to a reduced
  `pending → filled` strip.
- **No optimistic success anywhere.** A submitted order is not "working" and a filled order
  is not "filled" until the authoritative source says so.

**FLATTEN is a procedure view, not an order status:**

```text
flatten requested
  -> accepted (command acknowledged)
  -> per-symbol progress (cancel exposure-increasing, then reduce)
  -> authoritative position refresh
  -> residuals surfaced (e.g. halted symbols)
  -> status: complete | incomplete | unknown
```

"Accepted" is **never** rendered as "flat". Residuals (a halted symbol that could not be
reduced) are shown, not hidden — mirroring `equity-broker-execution`'s bounded flatten
state machine, which reports `incomplete` with residuals rather than a false success.

## 4. Freshness + market-state encoding

The dashboard **displays the per-stream `FeedHealthMeasurement` facts** from
`market-data-engineering` (SEAM 1) — it never re-derives them:

- **Event age vs receive age** are shown **separately** (a feed can be transport-alive but
  event-stale). **Visibly stale beats silently wrong** — degrade the display, never freeze a
  last-good value as if it were live.
- **Integrity state** (`ok | gapped | resyncing | corrupt`), **session/expected-activity
  state** (a quiet-but-healthy closed-session feed is not "stale"), **connection state**,
  and **halt banners** are first-class.
- **Per-symbol freshness** appears on tickets and blotter rows, not just a global header —
  the ticket's freshness gate is the symbol you are about to trade.

## 5. Blotter + positions

- A clear **positions / orders / fills** hierarchy; drill from a position to its orders to
  its fills.
- **Reconciliation states are shown**, including `unknown` inherited from the runtime's
  order-intent journal (§6 of `trading-automation-runtime`) — an unknown order is not an
  absent order.
- **Realized vs unrealized P&L** use stated conventions (sign, fees, FX) — the same
  discipline `trading-risk-management` requires for attribution; the blotter states which it
  shows.

## 6. Emergency controls: end-to-end contract

An **always-reachable** cancel-all / flatten control — fixed position, never occluded,
**never inside a virtualized list** that can scroll it out of existence — is necessary but
**not sufficient**. The emergency-command path must be **isolated end-to-end**:

- A **priority / isolated control channel** — a separate socket or lane from market data —
  so a tick storm cannot starve a cancel.
- A **bounded command queue** with **command idempotency keys**.
- **Explicit `acknowledged | unknown` states** — an emergency command whose fate is unknown
  is shown as unknown, never as done.
- A **measured input-to-dispatch latency budget** under replayed tick-storm load.

**Rendering isolation (platform-agnostic principle): market-data processing never shares a
thread / event loop / queue with safety-control input handling.** For browser surfaces:

- Run feed ingestion, parsing, sequencing, and book-delta computation in a **Dedicated
  Worker** (off the UI thread). Use a **SharedWorker** to share one feed/book across
  same-origin tabs — it reached Baseline in **May 2026**, so feature-detect and keep a
  dedicated-worker fallback for older managed devices. Chart/WebGL rendering can move to a
  worker via **OffscreenCanvas** (chart *design* still routes to `dataviz`).
- The worker **coalesces**: at most one pending latest snapshot, published at ~**10–30 Hz**
  or once per animation frame, using **transferable `ArrayBuffer`s** — **never one
  main-thread message per tick** (that recreates the queue storm you moved off-thread).
- The emergency handler is **constant-time**: latch visible feedback, timestamp the action,
  and enqueue a tiny command on the isolated control transport **without consulting the
  latest chart snapshot**.

**Latency SLO — HONESTY FLAG.** *No browser standard defines an emergency-trading latency
SLA.* A reasonable engineering **SLO** is **≤50 ms p99 and ≤100 ms p99.9** from the trusted
input timestamp to local control-channel enqueue, tested under replayed tick storms on
low-end hardware — treat it as a recommendation, not a guarantee. (The Core Web Vitals INP
"good" threshold of 200 ms is **far too loose** for this purpose.) Measure input-queue delay
and handler time via `PerformanceEventTiming` (Baseline Dec 2025). Note `scheduler.postTask`
is limited-availability and **cannot preempt already-running JS** (progressive enhancement
only); `requestAnimationFrame` pauses in hidden tabs; `BroadcastChannel` has **no
acknowledgement or authorization semantics** and is **not** a safety-command channel. Because
GC, OS scheduling, and tab suspension give a browser **no hard latency bound**, the real
emergency stop lives server-side (risk limits + the authenticated execution gateway +
venue dead-man / cancel-on-disconnect — see `trading-automation-runtime`).

**Alert prioritization:** a reject / halt / risk-breach alert **outranks** a price alert;
the emergency lane is never drowned by informational noise.

## 7. Monitoring / operator console for unattended bots

The console for a `trading-automation-runtime` bot **displays the state axes separately** —
never a single merged "status" light:

- **`lifecycle_phase`**, **`risk_mode`**, **`lease_authority`**, and the **derived effective
  permissions** each render on their own. A merged light can show green "ACTIVE" while the
  account is `LIQUIDATION_ONLY` — that is the failure this section exists to prevent.
- **Halt reasons show source + asserted-at** (from the append-only halt record), so an
  operator sees *who* halted and *when*.
- **Degraded-feed alerts** are driven by the `FeedHealthMeasurement` facts.
- A **dead-man indicator** shows the bot's own liveness/readiness split — live is not ready.

## 8. Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Optimistic fills (render success before authoritative confirmation) | Operator acts on a fill that never happened | No optimistic success; render the adapter state, `unknown` included |
| A single merged "status" light | Hides `LIQUIDATION_ONLY` behind a green "ACTIVE" | Display lifecycle / risk / lease / effective-permission axes separately |
| UI-constructed order digest | Diverges from what the server actually submits | The adapter/server builds the canonical digest; the UI only presents it |
| UI-local notional caps | The UI is not the risk authority; caps drift | Present the risk owner's verdict with provenance and as-of; never define/override |
| green = connected as the only feed signal | Transport-alive but event-stale reads as live | Show event age vs receive age, integrity state, and session state |
| Emergency button inside a virtualized list | It can scroll out of existence exactly when needed | Fixed, always-reachable position; never virtualized away |
| Unthrottled main-thread tick handling | The UI (and the emergency handler) starve under a tick storm | Off-main-thread ingestion; coalesced snapshots; isolated control lane |
| Flatten rendered "complete" from command acceptance | "Accepted" is not "flat"; residuals hidden | Flatten is a procedure with a complete/incomplete/unknown terminal + residuals |
| Paper / live ambiguity | An operator fires a live order believing it is paper | Always-visible environment badge with a masked account id |

---

**See also:** `trading-automation-runtime` (the state axes and emergency server-side stop) ·
`market-data-engineering` (the `FeedHealthMeasurement` facts this surface displays) ·
`equity-broker-execution` (the flatten state machine and order lifecycle vocabulary) ·
`dataviz` (analytical charts) · `modern-frontend` (component mechanics) · `observability`
(signal mapping and alert classes).
