---
name: equity-trading-compliance
description: Use when checking whether a US equity day trade is permitted, counting day trades, or handling trader tax mechanics — per-account broker-regime detection (legacy PDT vs FINRA risk-based intraday margin, transition window through 2027-10-20), day-trade counting and round-trip identification with broker reconciliation, the day_trade_permitted pre-trade guard contract with a liquidation-only carve-out, wash-sale (section 1091) accounting, section 475(f) mark-to-market election, short-locate and Reg SHO Rule 201 rule models, and 1099-B/cost-basis reconciliation. Trigger on - PDT, pattern day trader, day trade count, intraday margin, wash sale, 475(f), mark to market, trader tax status, short locate, SSR, 1099-B, cost basis. Kill-switch machinery lives in trading-risk-management (this skill registers its guard there); order-time enforcement lives in equity-broker-execution. Educational reference, not tax or legal advice - elections and filings belong to the user and their tax professional.
family: equity
---

# Equity Trading Compliance

## 1. Overview + routing + disclaimer

This skill is the KNOWLEDGE OWNER for the US-equity day-trading regulatory and
tax domain: broker day-trade regimes, day-trade counting, the pre-trade guard,
wash sales, the §475(f) election, short-sale rules, and cost-basis
reconciliation. It **defines** the canonical `day_trade_permitted(...)` guard;
the **enforcement point** for that guard lives in `trading-risk-management`
(the `KillSwitch` calls it), and **order-time** regulatory marking lives in
`equity-broker-execution`. One gate, one knowledge owner.

> **Educational reference — NOT tax or legal advice.** Elections, filings, and
> account setup belong to the user and their tax professional. This skill
> explains what the rules ARE and how to compute against them; it does not file
> anything on the user's behalf.

**Routing:**
- Kill-switch / position sizing / circuit breakers → `trading-risk-management`
  (this skill registers its guard there — see the shared contract at
  `references/guard-contract.md`).
- Order marking / locate-at-order-time / SSR-and-LULD order handling →
  `equity-broker-execution` (§7 here owns what the rules ARE; that skill owns
  order-time enforcement).
- The canonical trade/execution ledger schema is OWNED by
  `trade-journaling-and-review`; this skill CONSUMES it for §8 tax views.

## 2. Broker-regime detection (core)

The day-trade regime is a **runtime fact**, detected per
**(broker, account_id, account_type, policy_version)** — never a global
constant and never a hardcoded rule. Two regimes coexist during the transition:

- **Legacy PDT** — the static test (§3): 4+ day trades in 5 business days in a
  margin account, $25,000 minimum equity.
- **Risk-based intraday margin** — the newer FINRA framework that monitors
  **intraday margin exposure** rather than a bare count. Because it watches
  exposure, a guard blind to the order's size/side cannot evaluate it — which
  is why the guard signature carries `order_intent` (§4).

FINRA's rules grant implementation flexibility to member FIRMS — they do NOT
contain an express account-by-account migration authorization. Treat per-account
regime variation as a **defensive engineering assumption** (broker policies may
in practice differ across accounts, and cash / Reg-T margin / portfolio-margin
accounts differ), not a regulatory citation. **Detect at the account
granularity, never cache at broker/firm level.**

**Detection sources, in preference order:**
1. Broker API field (authoritative where present).
2. Broker disclosure / documentation.
3. User attestation — an **EXPIRING** fallback, never ground truth.

**Revalidate** at session start, before an exposure-increasing order after any
staleness interval, and on broker notices / changed account fields — not merely
at a window close.

**TW-3 — fail closed for NEW exposure, never for exits.** When the regime
cannot be reliably detected, the guard **fails closed for exposure-INCREASING
orders** (rejects; never guesses) and **NEVER blocks exposure-reducing or
liquidation-only orders**. "Closed" means *no new risk*, not *trapped in a
position*.

Regulatory anchors: new FINRA rules effective **2026-06-04** (SEC approval
order **34-105226**); brokers may retain legacy PDT through **2027-10-20**.

## 3. Day-trade counting + broker reconciliation

- Rolling **five-business-day** window; a day trade is opening and closing the
  same security the same session.
- **Round-trip identification:** aggregate partial fills, count long-to-short
  reversals, and treat options/multileg per their own rules.
- Margin vs cash accounts differ; the **6% test** flags accounts whose day
  trades exceed 6% of total trades; **overnight-position exceptions** apply;
  broker **house rules** are frequently stricter than the regulatory floor.

**Broker-authoritative reconciliation (binding).** Broker-provided PDT status,
day-trade counts, and order-preview / margin endpoints are **AUTHORITATIVE
where available**. Local counting is an **explainability / reconciliation
layer**, never the decision source of record. Example broker fields: Alpaca
`pattern_day_trader` / `daytrade_count` / `daytrading_buying_power`; Schwab and
IBKR expose day-trade counts and preview/margin endpoints.

## 4. Guard contract (canonical — TW-2)

This skill DEFINES exactly ONE canonical signature. The full input/output
contract and the shared conformance checklist live at
[`references/guard-contract.md`](references/guard-contract.md), which is pointed
at by BOTH this skill and `trading-risk-management`'s registration section.
Drift between the two = reopen.

```python
from dataclasses import dataclass


@dataclass
class Verdict:
    verdict: str          # "permit" | "reject_fail_closed" | "liquidation_only"
    reason_code: str
    evidence_source: str
    evidence_freshness: str
    policy_version: str


def day_trade_permitted(order_intent, account_snapshot,
                        broker_policy_snapshot, as_of) -> Verdict:
    """Canonical pre-trade day-trade guard. Pure decision function.

    order_intent carries symbol/side/quantity/order_type/session AND
    order_intent.exposure in {"increase", "neutral", "reduce"}.
    Returns a STRUCTURED Verdict — never a bare boolean.
    """
    reducing = order_intent.exposure in ("reduce", "neutral")

    # Exits and cancels are NEVER blocked by an unknown/stale regime.
    if broker_policy_snapshot.regime == "unknown":
        if reducing:
            return Verdict("liquidation_only", "regime_unknown_exit_ok",
                           broker_policy_snapshot.evidence_source,
                           broker_policy_snapshot.evidence_as_of,
                           broker_policy_snapshot.policy_version)
        # Exposure-INCREASING order with an unknown regime -> fail closed.
        return Verdict("reject_fail_closed", "regime_unknown",
                       broker_policy_snapshot.evidence_source,
                       broker_policy_snapshot.evidence_as_of,
                       broker_policy_snapshot.policy_version)

    # Broker-authoritative count is the source of record where present.
    broker_count = getattr(account_snapshot, "day_trade_count", None)
    if (order_intent.exposure == "increase"
            and broker_count is not None
            and account_snapshot.would_exceed_day_trade_limit(order_intent)):
        return Verdict("reject_fail_closed", "pdt_would_exceed",
                       "broker_api", broker_policy_snapshot.evidence_as_of,
                       broker_policy_snapshot.policy_version)

    return Verdict("permit", "permitted", broker_policy_snapshot.evidence_source,
                   broker_policy_snapshot.evidence_as_of,
                   broker_policy_snapshot.policy_version)
```

The verdict is **structured** — `permit | reject_fail_closed |
liquidation_only` with reason code, evidence source, evidence freshness, and
policy version. **Never a bare boolean.** `reject_fail_closed` is reachable
ONLY for `exposure == "increase"`; a reducing order can only return `permit`
or `liquidation_only`.

## 5. Wash-sale mechanics (§1091)

- Loss disallowed if a **substantially identical** security is acquired within
  **30 days before or after** the sale (a 61-day window). The disallowed loss
  is **added to the replacement lot's basis** and the holding period tacks on.
- **Partial-quantity** wash sales disallow only the replaced portion.
- **Day-trader accumulation:** rapid re-entry across the window serially defers
  losses into replacement basis — a large latent effect for active traders.
- **Short-sale and option interactions** fall under §1091 as well.
- **Cross-account scope:** applies across the taxpayer's accounts including a
  **spouse's**; if the replacement is bought in an **IRA**, the disallowed loss
  is **permanently lost** (no basis add-back). Wherever the ledger is
  single-account, state an explicit **"external accounts unknown"** caveat.

Primary source: IRS **Publication 550**.

## 6. §475(f) mark-to-market election

- Changes treatment to **mark-to-market**: open qualifying **trading**
  positions are marked at year end, gains/losses become **ordinary**, and
  **wash-sale rules do not apply** to the marked trading positions.
- Requires **segregating investment positions** (which keep capital treatment)
  from trading positions.
- **Eligibility** turns on **trader tax status** (substantial, frequent,
  continuous, regular short-term trading — facts and circumstances).
- **Deadline mechanics:** the election is generally made by the due date
  (without extensions) of the prior year's return; the method change uses
  **Form 3115**. Missing it generally **cannot be repaired until the next tax
  year**.

Primary source: IRS **Topic 429** (traders in securities).

## 7. Short-sale rule model (locate + Reg SHO / Rule 201)

This section owns what the rules ARE; `equity-broker-execution` owns order-time
enforcement.

- **Locate (Rule 203):** before a short sale is accepted, the broker must have
  reasonable grounds to believe the security can be borrowed and delivered — a
  **pre-execution broker obligation**, distinct from the price test.
- **SSR / Rule 201 (alternative uptick):** triggered when a security **declines
  10%** from the prior day's close (the listing market determines the trigger
  from eligible consolidated last-sale prices during 09:30–16:00 ET). For the
  **rest of that day and the next day**, non-exempt short sales may
  execute/display only **strictly ABOVE the current national best bid, unless a
  Rule 201 exception applies** — a **price-test restriction, NOT a blanket
  ban**. Once triggered, the price test applies whenever an NBB is calculated
  and disseminated, potentially outside regular hours.
- **Order marking:** long / short / short-exempt.

## 8. 1099-B / cost-basis reconciliation

Reconcile the broker-reported 1099-B against the canonical ledger (schema owned
by `trade-journaling-and-review` §2, consumed here). Reconcile wash-sale
adjustments, corrections/busts, and common mismatch causes (broker vs local
lot selection, corporate actions, wash-sale basis add-backs). The ledger is
the explainability layer; the 1099-B is the filing artifact.

## 9. Freshness anchor (TW-5)

```
FRESHNESS:v1
date_gated_review: 2027-10-20   # FINRA transition window close — re-verify regime rules
event_triggers:
  - session_start
  - staleness_interval_before_exposure_increase
  - broker_notice_or_changed_account_field
```

Re-verify the regime rules on the date gate AND on every event trigger — the
regime is not a set-and-forget constant. Primary sources to re-check: FINRA
transition guidance, SEC approval order **34-105226**, IRS **Pub 550**, IRS
**Topic 429**.

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Hardcoding the "sub-$25k / 4-in-5" PDT constant | The regime is a per-account runtime fact now spanning legacy PDT AND risk-based intraday margin | Detect the regime per (broker, account_id, account_type, policy_version); branch on it |
| Caching the regime at broker/firm level | FINRA permits per-account migration; one firm runs both regimes | Cache (if at all) at account granularity; revalidate on the §2 triggers |
| Duplicating the guard in two skills | The signature silently rots and the two gates disagree | One canonical signature here; `trading-risk-management` registers, never restates (references/guard-contract.md) |
| Returning a bare boolean verdict | Callers cannot distinguish "no new risk" from "close everything" or see the evidence | Return the structured Verdict (permit / reject_fail_closed / liquidation_only) with reason + evidence |
| Fail-OPEN on an unknown regime | Guessing "probably fine" places unpermitted risk | Fail closed for exposure-increasing orders on any unknown/stale input |
| Fail-CLOSED applied to liquidation | Blocking exits traps the account in a losing position | Reducing orders and cancels are never rejected; unknown/halt states resolve to liquidation_only |
| Local count overriding the broker verdict | The broker is the source of record; local drift causes false permits/rejects | Broker counts/previews are authoritative; local counting only explains/reconciles |
| Treating wash-sale as a year-end-only concern | Intraday re-entries create wash sales continuously; basis is wrong all year | Track the 61-day window per lot as trades happen; flag partial and cross-account cases |
| Writing in a tax-advice voice | This is educational reference; elections/filings are the user's and their pro's | Explain the rules; defer elections, filings, and account setup to the user's tax professional |
