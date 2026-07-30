---
name: trading-automation-runtime
description: "Use when building or reviewing an unattended trading bot or automation daemon (any asset class) — the process lifecycle around a trading loop: boot state machine (BOOT → QUARANTINED → RECONCILING → ACTIVE/HALTED), halt and kill-switch state that persists across restarts, single-active-instance enforcement with lease fencing at order submission, a startup admission gate (broker reconciliation, feed health, risk and compliance reload) before the first strategy callback, market-calendar scheduling with misfire policy, graceful shutdown that drains exposure without cancelling protective exits, readiness vs liveness, and restart/failover/split-brain test matrices. Trigger on - trading bot, trading daemon, unattended trading, bot restart, kill switch persistence, duplicate orders after restart, split brain, reconcile on startup. Order placement lives in equity-broker-execution / crypto-exchange-integration; risk thresholds in trading-risk-management; feed health in market-data-engineering."
family: trading
---

# Trading Automation Runtime

## 1. Overview + routing + ownership carve

This skill owns the **process lifecycle and admission** around an unattended trading
loop — asset-class-agnostic. It is the part of a trading bot that decides *whether the
strategy is even allowed to run right now*, survives `kill -9` at any instant, and shuts
down without stranding exposure. It is **not** the strategy, **not** the order router, and
**not** the risk-threshold owner.

**What this skill owns:** the boot/lifecycle state machine, halt state that persists
across restarts, single-active-instance fencing, the startup admission gate, the
asset-neutral reconciliation *protocol*, the durable order-intent journal, calendar-driven
scheduling, and the crash-consistent drain.

**What it orchestrates but does NOT own (seam discipline — trip-wired):**

- **Risk thresholds and automatic-liquidation policy** are `trading-risk-management`
  verdicts. This runtime **persists and reloads** halt state and **reads** the risk mode,
  but it **never defines a threshold** and **never writes the risk halt cause**
  (see `trading-risk-management` → *KillSwitch state serialization*).
- **Broker/exchange queries** belong to the adapters. This runtime defines the
  reconciliation *protocol* (§5) and **calls** each adapter's implementation —
  `equity-broker-execution` for equities, `crypto-exchange-integration` for crypto — and
  **never implements a broker endpoint itself**.
- **Feed-health facts** are the one measurement schema defined in `market-data-engineering`
  (the `FeedHealthMeasurement` schema, SEAM 1). This runtime **aggregates** the streams a
  strategy requires and applies admission policy; it **does not re-derive the facts**.
- **Order placement / pricing / cancel-replace** live in the execution adapters.
- **Operator UI** lives in `trading-dashboard-ux`; **signal mapping / cardinality budgets**
  live in `observability` (domain events and their meanings are owned here — high-cardinality
  order/symbol/account IDs go to logs and traces, never metric labels).

## 2. State model: orthogonal axes, not one FSM

A single boot FSM that mixes lifecycle with risk causes eventually renders a status that is
a lie ("ACTIVE" while the account is liquidation-only). Model **three independent axes** and
combine them through a **most-restrictive permission lattice**:

- **`lifecycle_phase`** (runtime-owned): `BOOT → QUARANTINED → RECONCILING → ACTIVE`,
  plus `DRAINING` and `STOPPED`.
- **`risk_mode`** (`trading-risk-management`-owned): `NORMAL | HALTED | LIQUIDATION_ONLY`.
  The runtime **never writes this axis**; each owner clears only its own halt cause.
- **`lease_authority`** (lease-system-owned): `CURRENT | STALE | NONE`.

Effective permissions are **derived**, never stored as a fourth truth:

```python
def effective_permissions(lifecycle_phase: str, risk_mode: str, lease_authority: str):
    """Most-restrictive lattice over three orthogonal axes.

    NEW-EXPOSURE requires ACTIVE + NORMAL + CURRENT.
    cancel/reduce survives every restrictive lifecycle/risk state, but requires a
    CURRENT lease: a fenced-out (STALE/NONE) instance has NO mutation authority at all —
    the current leaseholder does the reducing. A state label must never trap a position,
    and a stale twin must never duplicate its exits.
    """
    can_new_exposure = (lifecycle_phase == "ACTIVE"
                        and risk_mode == "NORMAL"
                        and lease_authority == "CURRENT")
    can_cancel_reduce = lease_authority == "CURRENT"   # survives HALTED/DRAINING/LIQUIDATION_ONLY
    return {"increase": can_new_exposure,
            "cancel":   can_cancel_reduce,
            "reduce":   can_cancel_reduce}
```

The carve-out is binding in **both** directions: a halt/drain/liquidation state must not
gate exits shut for the current leaseholder, and a fenced-out instance must not place
"safety" exits (they are mutations — the current epoch owns them).

## 3. Persistent halt state with a safety contract

Halt state **outlives the process**. A restart can never clear a halt.

- **Versioned, append-only records:** `(source, epoch, reason, asserted_at, cleared_at,
  cleared_by)`. History is never rewritten; an unhalt is a new record, not an edit.
- **Compare-and-swap on epoch:** a stale writer (an epoch at or below the highest already
  recorded for that source) **cannot erase or supersede a newer halt**.
- **Single-writer-per-source; explicit, audited unhalt** — who may clear which cause is
  defined, not implicit.
- **Storage is a deployment choice, the pattern is the contract:** atomic-replace + fsync
  for a local file; a consistent shared store (etcd/consul/a serializable DB row) for HA.
- **Fail closed on absence.** Missing, corrupt, conflicting, or UNAVAILABLE halt state
  means **no new exposure** while the fenced cancel/reduce path stays open.

```python
def assert_halt(store, record, expected_epoch):
    """Append-only + CAS. A stale writer cannot erase or supersede a newer halt."""
    highest = store.highest_epoch(record["source"])
    if highest is not None and record["epoch"] <= highest:
        raise StaleWriterError(f"epoch {record['epoch']} <= current {highest}")
    store.append_cas(record, expected_epoch)          # atomic; loser of the race retries

def load_halt_state(store):
    """Missing/corrupt/conflicting/UNAVAILABLE halt state FAILS CLOSED for new exposure
    while preserving the fenced cancel/reduce path."""
    try:
        records = store.read_all()
    except StoreUnavailable:
        return {"risk_mode": "HALTED", "reason": "halt store unavailable — fail closed"}
    active = [r for r in records if r["cleared_at"] is None]
    if conflicting(active):
        return {"risk_mode": "HALTED", "reason": "conflicting halt records — fail closed"}
    return derive_mode(active)
```

`trading-risk-management` serializes its `KillSwitch` state into exactly this record shape
(thin delta A) — no threshold logic moves; only a serializable projection crosses the seam.

## 4. Single-active-instance with real fencing

Two live instances sharing one broker account is the worst failure in this skill. Prevent it
with **fencing enforced at the resource boundary**, not just a lease check.

A lease answers *"who should be leader now"*; a **fencing token** lets the protected resource
*reject work from a former leader*. Checking the lease immediately before `send()` only moves
the time-of-check/time-of-use window — the holder can pause (GC, VM stall), lose its lease,
and resume after a new leader exists. The **execution gateway** (the component holding broker
credentials) is where fencing must live, because brokers do not understand fencing tokens.

**The precise idiom — activate before trading, then equality on every mutation.** Merely
retaining `max_seen` and rejecting lower tokens has a subtle gap: an old in-flight request
can still be accepted before the boundary has *seen* the newer token. The new leader must
**persist the activation first**:

```python
def activate(gateway, scope: str, epoch: int):
    """New leader takes over: monotonic epoch, persisted BEFORE any trading."""
    if epoch <= gateway.active_epoch(scope):
        raise StaleLeaderError(epoch)
    gateway.persist_active_epoch(scope, epoch)        # durable; survives gateway restart
    gateway.purge_obsolete_command_queue(scope)       # drop lower-epoch queued commands

def mutate(gateway, scope: str, epoch: int, side: str, request):
    """EVERY order/cancel/replace/flatten carries the epoch and fails closed on mismatch."""
    if side.lower() not in ("buy", "sell", "buy_to_cover", "sell_short"):
        raise ValueError(f"invalid side: {side!r}")   # side is a validated input, never fixed
    if epoch != gateway.active_epoch(scope):          # equality, not >= — reject stale AND future
        raise FencedOutError(epoch, gateway.active_epoch(scope))
    return gateway.send(request)
```

**Required properties:** every order, cancel, replace, mass-cancel, flatten, and account
mutation carries `{scope, epoch, request_id}` and fails closed on mismatch; epoch activation
and sends are serialized; no strategy instance holds credentials or an alternate execution
path; the active epoch is durable across gateway restart; idempotency / client-order keys
handle commands already accepted before a takeover.

**Transition rules:**

- Current leader **loses its lease** → `DRAINING` for new exposure, keep the fenced
  cancel/reduce path.
- New leader → **full `RECONCILING`** (§5) before `ACTIVE`.
- **Split-brain** → highest epoch holds authority; the lower-epoch instance drops to
  `lease_authority = STALE` (**no mutations, not even "safety" exits**) and alerts.

**Critical pitfall:** if two gateway replicas can *both* use the broker credentials, the
broker cannot atomically compare the epoch and the real resource is still unfenced. You need
**one serialized credential endpoint** (or venue session-takeover / cancel-on-disconnect
semantics strong enough to be that endpoint). FIX sequence numbers and cancel-on-disconnect
are useful controls but are **not** general fencing tokens.

**Primitives (2025-2026) — pick one that yields a monotonic token:** etcd lock
`create_revision` / election `LeaderKey.rev` (not the lease ID); ZooKeeper `czxid` /
ephemeral-sequential suffix; Consul `(Key, LockIndex, Session)` sequencer. **Redis Redlock
and Postgres advisory locks do NOT return a monotonic fencing token** — add an explicit
generation counter. All such counters are scoped to a coordination-cluster incarnation; a
snapshot rollback or cluster replacement can move them backward, so bind a
`(cluster_generation, counter)` compound. *(Fencing argument: Martin Kleppmann, "How to do
distributed locking", 2016 — martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html.)*

## 5. Startup admission gate + reconciliation protocol (SEAM 2)

Nothing trades until the gate passes. This runtime defines **one versioned, asset-neutral
protocol**; each adapter implements it.

```
ReconciliationRequest  -> account/venue scope, snapshot watermark, what to fetch
ReconciliationResult   -> open orders, executions/fills (composite keys where needed),
                          positions, balances (where applicable), discrepancy list,
                          pagination completeness, and status: complete | incomplete | unknown
```

An **`incomplete` or `unknown` result blocks new exposure** — admission fails to
`QUARANTINED`, it is never silently treated as "no open state". Each adapter owns
retrieval/normalization: `equity-broker-execution` names its §4 invariants as the equity
implementation (thin delta B); `crypto-exchange-integration` adds the crypto surface with
per-exchange capability checks (thin delta C — CCXT capabilities vary, so `incomplete` is
venue-specific).

The gate runs, in order, before the first strategy callback:

1. **Reload halt/risk state** (§3) — a persisted halt keeps the bot out of `ACTIVE`.
2. **Reconcile** open orders / fills / positions / balances via the protocol above.
3. **Resolve the order-intent journal** (§6) — no unresolved `PREPARED`/`UNKNOWN` intents.
4. **Revalidate the compliance snapshot** — boot is a session start under
   `equity-trading-compliance` §2 revalidation triggers.
5. **Evaluate feed health** — aggregate the `FeedHealthMeasurement` facts
   (`market-data-engineering`) over the strategy's required streams against fail-closed
   admission thresholds.

**All pass → `ACTIVE`. Any fail → `QUARANTINED` + alert.** Admission is fail-closed by
construction: an unknown answer is a failing answer.

## 6. Durable order-intent journal (adapter-owned; the runtime consumes it at boot)

This is what makes "compare scheduled intent vs broker reality" possible after `kill -9`
mid-submit. The submission path writes intent **before** sending and records the response
**after**:

```python
def record_intent(journal, intent_id, client_order_key, digest, side: str, qty: float):
    """Write PREPARED intent BEFORE the send. `side` is a validated input, never hardcoded."""
    if side.lower() not in ("buy", "sell", "buy_to_cover", "sell_short"):
        raise ValueError(f"invalid side: {side!r}")
    journal.append({"intent_id": intent_id, "client_order_key": client_order_key,
                    "digest": digest, "side": side, "qty": qty, "state": "PREPARED"})

def resolve_intents_at_boot(journal, adapter):
    """Unresolved PREPARED intents become UNKNOWN and are resolved by adapter query —
    NEVER blindly retried (a blind retry doubles exposure)."""
    for intent in journal.where(state="PREPARED"):
        intent["state"] = "UNKNOWN"
        found = (adapter.query_by_client_key(intent["client_order_key"])
                 or adapter.query_by_execution_key(intent["digest"]))
        if found is None:
            journal.mark_ambiguous(intent["intent_id"])   # stay QUARANTINED, manual resolution
        else:
            journal.reconcile(intent["intent_id"], found)
```

Unresolvable ambiguity keeps the account in `QUARANTINED` pending manual resolution — the
runtime never guesses whether an order landed.

## 7. Scheduling + session model

Consume **versioned venue calendars / capability snapshots** — never a hardcoded
`pre / regular / post` triple. Overnight and venue-specific sessions exist and are expanding
in 2026, and named sessions differ per venue.

- **The snapshot carries:** per-venue timezone and trade-date/clearing rules, **named
  sessions** (stable IDs, open/close, auction and order-entry windows), maintenance windows,
  **protection-regime coverage per session** (LULD, venue collars, halts, clearly-erroneous),
  holiday/early-close/DST/cross-midnight overrides, and effective dates.
- **Misfire policy:** skip vs run-late vs quarantine, with idempotent run keys.
- **Unknown session / protection facts → fail closed for new exposure.**

**2026 landscape (verify against the live calendar before shipping):** LULD remains
**regular-hours only (09:30–16:00 ET)**. Overnight ATS liquidity is live (e.g. Blue Ocean
ATS, ~20:00–04:00 ET); national-exchange overnight sessions (Nasdaq Day/Night, NYSE Arca's
four-session model, Cboe EDGX) are SEC-approved with launches targeted around **2026-12-06**,
so "24×5" is in practice **23×5** with a daily maintenance break. An overnight price-band
proposal — **SEC Release No. 34-105596 (File No. 4-631)** — is a *Notice of Filing* (not an
approval) as of 2026-07-14; if adopted, Phase 1 would publish **static** overnight bands for
21:00–04:00 ET only, not the full daytime sliding-band/limit-state mechanism. Treat overnight
band protection as **absent** until a venue's snapshot says otherwise. The order-time detail
lives in `equity-broker-execution` §7 (including the unattended extended-hours prohibition
when band/halt state is unavailable) — reference it, do not restate the rule model here.

## 8. Graceful shutdown / crash-consistent drain

The drain is a **persisted lifecycle phase**, not a best-effort sequence. Persist first,
then act — so a crash mid-drain is just the boot path.

```python
def drain(runtime, adapter, deadline):
    """Persist DRAINING BEFORE acting. Boot detects an unfinished drain and resumes it
    before normal admission. kill -9 at ANY step is recovered by the boot path."""
    runtime.persist_lifecycle("DRAINING")             # 1. new exposure disabled, persisted first
    adapter.reconcile()                               # 2. broker-authoritative state
    adapter.cancel_exposure_increasing_orders()       # 3. adapter-classified; exits untouched
    adapter.wait_for_terminal_acks(deadline)          # 4. BOUNDED wait for acknowledgements
    adapter.reconcile_fills_during_cancel_race()      # 5. fills that landed during the cancel
    apply_protective_exit_policy(adapter)             # 6. see rule below
    runtime.checkpoint_protective_exits()             # 7. re-adopt at next boot
    runtime.persist_lifecycle("STOPPED")              # 8. final checkpoint
```

**Protective-exit policy (binding):** broker-side protective stops **stay active** and are
checkpointed for re-adoption at next boot — **never cancel exits and leave a naked
position**. Client-side-synthesized exits are converted to broker-side orders (or the
position is reduced) before the process exits. **Define behavior when the supervisor's
termination deadline expires mid-drain** — a hard `SIGKILL` at the deadline must still leave
the persisted `DRAINING` state and live protective exits, so boot resumes safely.

## 9. Test matrix

Each scenario asserts a **terminal state and effective permissions**, driven by fault
injection (the design test is: kill -9 recovery at any point is just the boot path).

| Scenario | Expected terminal state / permission |
|---|---|
| SIGKILL at every lifecycle transition (incl. mid-submit, mid-drain) | Boot reconstructs; no lost/duplicated exposure |
| Restart during a halt | Stays out of `ACTIVE`; halt reloaded from persistent store |
| Lease loss during `ACTIVE` | `DRAINING` new exposure; fenced cancel/reduce preserved |
| Split-brain with in-flight orders | Highest epoch trades; lower-epoch instance = STALE, no mutations |
| Feed-degraded boot | Admission fails to `QUARANTINED` |
| Store outage during halt assertion | Fail closed (no new exposure); alert |
| Ambiguous submission (kill -9 mid-submit) | Journal `UNKNOWN` resolved by query; ambiguity → QUARANTINED |
| Paginated / incomplete reconciliation | `incomplete` → blocks new exposure |

**Readiness vs liveness:** liveness = the process is up; **readiness = the admission gate
passed**. A live-but-not-ready bot must never receive strategy callbacks.

## 10. Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| In-memory-only halt state | A restart silently clears the kill switch | Persist halt state (append-only + CAS); reload at boot; a restart can never clear a halt |
| Supervisor restarts straight to ACTIVE | Skips reconciliation; duplicates orders after a crash | Boot → QUARANTINED → RECONCILING; ACTIVE only after the admission gate passes |
| Lease validated only at startup, or only against a local cache | TOCTOU + stale-twin double-trades | Fence at the credential-holding gateway; activate-before-trade; epoch equality on every mutation |
| One FSM mixing lifecycle and risk causes | Renders "ACTIVE" while liquidation-only | Orthogonal axes + most-restrictive lattice; risk_mode stays risk-owned |
| Stale instance performing "safety" exits | Two instances duplicate exits; the fenced twin has no authority | A STALE lease = no mutations at all; the current leaseholder reduces |
| Blind retry after a send timeout | Doubles exposure when the first order landed | PREPARED/UNKNOWN intent journal; query by client/execution key, never blind-retry |
| Drain without a persisted DRAINING state | A crash mid-drain loses the drain; new exposure resumes | Persist DRAINING first; boot detects and resumes an unfinished drain |
| Cancelling protective exits at shutdown | Leaves naked positions overnight | Broker-side exits stay active and are checkpointed for re-adoption |
| Hardcoded three-session calendars | Breaks on overnight/venue sessions; misprices protection coverage | Consume versioned venue calendars with named sessions and per-session protection facts |

---

**Thin deltas that complete this skill's seams:**
`trading-risk-management` (KillSwitch → halt-record serialization; `risk_mode` axis
ownership) · `equity-broker-execution` (§4 invariants as the equity reconciliation
implementation; boot call site) · `crypto-exchange-integration` (per-exchange capability
checks, composite execution keys, pagination completeness).

**See also:** `market-data-engineering` (the `FeedHealthMeasurement` schema, SEAM 1) ·
`trading-dashboard-ux` (the operator console that displays these axes) · `observability`
(signal mapping / cardinality) · `equity-trading-compliance` (boot compliance revalidation).
