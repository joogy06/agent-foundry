# Pre-Trade Guard Conformance Checklist — `day_trade_permitted`

**Status:** canonical shared contract (TW-2). This file is the ONE source of
truth for the day-trade pre-trade guard. It is pointed at by BOTH:

- `equity-trading-compliance` (the KNOWLEDGE OWNER — defines the signature,
  the verdict semantics, and the regulatory rule model), and
- `trading-risk-management` (the ENFORCEMENT POINT — registers the guard in
  the `KillSwitch` per-order check chain and calls it, but contains NO
  regime/tax knowledge).

One gate, one knowledge owner. If the signature or the verdict semantics drift
between the two skills, that is a defect: STOP and reconcile against this file.
Do not fork a second signature, and do not restate regime/tax rules inside
`trading-risk-management`.

---

## 1. Canonical signature (exact)

```python
def day_trade_permitted(
    order_intent,           # what the account is about to do (see §2)
    account_snapshot,       # broker-authoritative account state (see §3)
    broker_policy_snapshot, # detected per-account regime + policy (see §4)
    as_of,                  # timestamp the decision is anchored to (tz-aware)
) -> Verdict:               # STRUCTURED result — never a bare bool (see §5)
    ...
```

The guard is a PURE decision function over four inputs. It does not place
orders, does not mutate account state, and does not fetch data itself — the
caller supplies already-fetched, already-timestamped snapshots so the decision
is reproducible and auditable.

> Deviation note (surfaced at design time): the deliberation's illustrative
> form was `day_trade_permitted(account_state, broker_regime)`. It was enriched
> to the signature above because a guard blind to the order cannot classify
> exposure or determine whether the order CREATES a day trade, and the new
> risk-based regime monitors intraday-margin exposure, not just counts.
> TW-2's requirement — exactly ONE canonical signature — is preserved.

## 2. `order_intent` (required fields)

| Field | Meaning |
|---|---|
| `symbol` | instrument identifier |
| `side` | `buy` / `sell` / `sell_short` / `buy_to_cover` |
| `quantity` | order quantity |
| `order_type` | market / marketable_limit / limit / bracket / etc. |
| `session` | regular / pre / after_hours / overnight |
| `exposure` | classification — one of `increase` / `neutral` / `reduce` |

`exposure` is the load-bearing field. It is computed by the caller from the
current broker-authoritative position and the order, NOT guessed by the guard:

- `increase` — opens new risk or adds to an existing position.
- `neutral` — replaces an existing order at the same size/exposure.
- `reduce` — closes or reduces a position, a reduce-only exit, or a cancel.

## 3. `account_snapshot` (required fields)

Broker-authoritative account state as fetched by the caller: `account_id`,
`account_type` (cash / reg_t_margin / portfolio_margin), equity, buying power,
open positions, and — WHERE THE BROKER EXPOSES THEM — the broker's own
`pattern_day_trader` flag, `day_trade_count`, and any order-preview / margin
result. **Broker-provided counts and previews are AUTHORITATIVE where
available; local counting is an explainability / reconciliation layer, never
the decision source of record.**

## 4. `broker_policy_snapshot` (required fields)

The regime is a RUNTIME fact detected at
**(broker, account_id, account_type, policy_version)** granularity — a defensive
engineering assumption that broker policies may in practice differ across
accounts (NOT an express FINRA account-level authorization). Fields: `regime`
(`legacy_pdt` / `risk_based_intraday_margin` / `unknown`), `policy_version`,
`evidence_source` (broker API field / broker disclosure / user attestation),
`evidence_as_of`. Detection preference order: broker API field → broker
disclosure/docs → user attestation (an EXPIRING fallback, never ground truth).

## 5. `Verdict` (structured — never a bare boolean)

| Field | Meaning |
|---|---|
| `verdict` | one of `permit` / `reject_fail_closed` / `liquidation_only` |
| `reason_code` | machine-stable code (e.g. `regime_unknown`, `pdt_would_exceed`, `permitted`) |
| `evidence_source` | which source backed the decision |
| `evidence_freshness` | age of the evidence relative to `as_of` |
| `policy_version` | the `broker_policy_snapshot.policy_version` used |

`verdict` values:

- `permit` — the exposure-increasing order may proceed.
- `reject_fail_closed` — new exposure is refused (unknown/stale regime,
  count exceeded, or any unknown/stale required input). NOT a system error;
  a deliberate refusal to add risk.
- `liquidation_only` — no NEW exposure, but cancel-and-reduce operations are
  authorized. This is what fail-closed and halted states resolve to for a
  reducing order.

## 6. Behavioral invariants (both skills MUST honor)

1. **Fail closed for new exposure, never for exits.** On any unknown or stale
   required input, an `exposure == increase` order returns
   `reject_fail_closed`. An `exposure == reduce` order (or a cancel) is NEVER
   blocked by an unknown regime, a stale snapshot, or a tripped kill switch —
   it returns `permit` (or `liquidation_only`), never `reject_fail_closed`.
   "Closed" means "no new risk", never "trapped in a position".
2. **Broker-authoritative precedence.** Where the broker exposes a PDT status /
   day-trade count / preview, that is the decision source of record; local
   computation only explains and reconciles.
3. **Per-account regime.** The regime is cached (if at all) at the
   per-account granularity of §4 — NEVER at broker/firm level.
4. **Revalidation triggers.** Regime evidence is revalidated at session start,
   before an exposure-increasing order after any staleness interval, and on
   broker notices / changed account fields — not merely at a window close.

## 7. Registration contract (trading-risk-management side)

`trading-risk-management`'s `KillSwitch` (checked before EVERY order) calls
`day_trade_permitted(...)` as a registered pre-trade guard **for
exposure-increasing orders only**. Enforcement mapping:

- `permit` → the kill switch's other checks decide.
- `reject_fail_closed` → block the order (no new exposure).
- `liquidation_only` → allow only cancel-and-reduce; block new exposure.

Kill-switch `HALTED` / `EMERGENCY_EXIT` states and guard fail-closed verdicts
block NEW exposure while authorizing cancel-and-reduce — exits are never gated
shut. The registration section in `trading-risk-management` contains the call
site and the enforcement mapping ONLY; all regime/tax knowledge lives in
`equity-trading-compliance`.

## 8. Conformance checklist

Verify BOTH skills against every line. A mismatch = reopen (TW-2).

- [ ] Exactly one signature exists, matching §1 verbatim (4 inputs, structured `Verdict`).
- [ ] `order_intent` carries `exposure` and the guard branches on it (§2).
- [ ] Verdict is the structured object of §5 — no bare boolean anywhere.
- [ ] `reject_fail_closed` is reachable ONLY for `exposure == increase`.
- [ ] `exposure == reduce` / cancels can NEVER return `reject_fail_closed`.
- [ ] Broker-authoritative counts/previews take precedence over local counting.
- [ ] Regime is treated as per-(broker, account_id, account_type, policy_version).
- [ ] `trading-risk-management` registers the call for exposure-increasing orders and states the liquidation carve-out, with NO regime/tax knowledge restated.
- [ ] Both skills point at THIS file as the shared contract.
