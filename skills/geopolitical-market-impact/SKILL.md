---
name: geopolitical-market-impact
description: Use when mapping geopolitical events to market impact, classifying war/sanctions/policy events, estimating impact magnitude and duration, matching historical precedents, or building event-driven trading signals from macro/political news
---

# Geopolitical Market Impact

## Overview

Geopolitical events create **asymmetric, non-linear** market shocks. The challenge is: (1) classifying events by type and severity, (2) estimating impact direction and magnitude from historical analogues, and (3) acting before the crowd prices it in — or avoiding false alarms.

**Core principle:** Markets often front-run geopolitical risk. The best entry is frequently on rumour, not confirmation. Study **buy the rumour, sell the news** carefully.

## When to Use

- Classifying incoming geopolitical news for trading impact
- Searching for historical precedents to estimate price response
- Building event-driven trading signals from news feeds
- Estimating sanction/war/election impact on specific assets
- Assessing second-order effects (e.g., oil → airline stocks)

## Event Classification Framework

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class EventType(Enum):
    WAR_ESCALATION    = "war_escalation"
    WAR_DE_ESCALATION = "war_de_escalation"
    SANCTIONS_NEW     = "sanctions_new"
    SANCTIONS_LIFTED  = "sanctions_lifted"
    ELECTION_RESULT   = "election_result"
    POLICY_CHANGE     = "policy_change"      # rates, tariffs, regulation
    NATURAL_DISASTER  = "natural_disaster"
    SUPPLY_DISRUPTION = "supply_disruption"  # Suez, pipelines, ports
    COUP_INSTABILITY  = "coup_instability"
    DIPLOMATIC_CRISIS = "diplomatic_crisis"

class Severity(Enum):
    LOW    = 1   # localised, limited economic ties
    MEDIUM = 2   # regional spillover, moderate trade impact
    HIGH   = 3   # global supply chain, major economy involved
    EXTREME = 4  # nuclear risk, G7 direct involvement

@dataclass
class GeopoliticalEvent:
    event_type: EventType
    severity: Severity
    countries_involved: list[str]
    affected_commodities: list[str]   # e.g. ['crude_oil', 'wheat', 'natural_gas']
    affected_currencies: list[str]    # e.g. ['RUB', 'EUR', 'USD']
    description: str
    source_reliability: float         # 0-1, Reuters=0.9, Twitter=0.3
```

## Asset Impact Matrix

```python
# Historical directional impact by event type and asset class
# Values: typical directional bias (+ = up, - = down, ? = uncertain)
IMPACT_MATRIX = {
    EventType.WAR_ESCALATION: {
        'gold':          +1,    # safe haven
        'usd':           +1,    # safe haven flows
        'oil':           +1,    # supply disruption risk
        'natural_gas':   +1,
        'wheat':         +1,    # Russia/Ukraine = major exporters
        'equities':      -1,    # risk-off
        'btc':           -1,    # risk-off (initially)
        'bonds':         +1,    # safe haven
        'eur':           -1,    # if European theatre
    },
    EventType.SANCTIONS_NEW: {
        'affected_country_currency': -1,
        'oil':           +1,    # if sanctioned country is oil exporter
        'gold':          +1,
        'usd':           +1,
    },
    EventType.ELECTION_RESULT: {
        # Highly context-dependent — use historical_precedents() function
    },
    EventType.SUPPLY_DISRUPTION: {
        'affected_commodity': +1,
        'substitutes':   +1,
        'consumers':     -1,    # companies dependent on commodity
    },
}

def estimate_impact(event: GeopoliticalEvent, asset: str) -> dict:
    """Estimate directional impact and magnitude."""
    matrix = IMPACT_MATRIX.get(event.event_type, {})
    direction = matrix.get(asset, 0)

    # Severity multiplier
    magnitude_pct = {
        Severity.LOW: 0.5,
        Severity.MEDIUM: 2.0,
        Severity.HIGH: 5.0,
        Severity.EXTREME: 15.0,
    }[event.severity]

    return {
        'direction': direction,
        'estimated_move_pct': direction * magnitude_pct,
        'confidence': event.source_reliability,
        'note': 'Directional estimate only; timing and confirmation critical',
    }
```

## Historical Precedent Database

```python
HISTORICAL_PRECEDENTS = [
    {
        'event': 'Russia invades Ukraine (Feb 2022)',
        'type': EventType.WAR_ESCALATION,
        'impacts': {
            'crude_oil':    +28,   # % move in 3 months
            'wheat':        +60,
            'natural_gas':  +200,  # EU benchmark
            'gold':         +8,
            'eur_usd':      -6,
            'rub_usd':      -50,   # initial, then recovered on capital controls
            'spx':          -12,   # in 3 months
        },
        'time_to_peak': '3-6 weeks',
        'reversal': 'Partial within 3 months as supply routes adapted',
    },
    {
        'event': 'US-China tariff escalation (2018-2019)',
        'type': EventType.POLICY_CHANGE,
        'impacts': {
            'cny_usd':      -8,
            'spx':          -20,   # peak drawdown
            'soybeans':     -15,
            'gold':         +8,
        },
        'time_to_peak': '6-12 months',
    },
    {
        'event': 'Iran nuclear deal JCPOA exit (2018)',
        'type': EventType.SANCTIONS_NEW,
        'impacts': {
            'crude_oil':    +20,
            'irr_usd':      -70,   # Iranian rial
        },
        'time_to_peak': '6 months',
    },
    {
        'event': 'Brexit referendum (Jun 2016)',
        'type': EventType.ELECTION_RESULT,
        'impacts': {
            'gbp_usd':      -10,   # day after
            'ftse_100':     -8,    # day after (recovered quickly as GBP offset)
            'gold':         +5,
            'eurostoxx':    -8,
        },
        'time_to_peak': '1-2 days for initial shock',
    },
]

def find_precedents(event: GeopoliticalEvent, top_n: int = 3) -> list[dict]:
    """Match current event to historical precedents by type."""
    matches = [p for p in HISTORICAL_PRECEDENTS
               if p['type'] == event.event_type]
    return matches[:top_n]
```

## Second-Order Effects

```python
# Commodity → sector impact chains
SECOND_ORDER_CHAINS = {
    'crude_oil_up': {
        'airlines':       -1,   # fuel costs
        'shipping':       -1,
        'petrochemicals': +1,   # feedstock price up → margin down for consumers
        'oil_majors':     +1,
        'ev_sector':      +1,   # accelerated adoption
        'defense':        +1,   # increased military spending
    },
    'natural_gas_up': {
        'utilities':      -1,   # margin compression
        'lng_exporters':  +1,   # US LNG benefits
        'fertilisers':    -1,   # gas = feedstock for nitrogen fertilisers
        'food_producers': -1,
    },
    'wheat_up': {
        'food_companies': -1,
        'agri_tech':      +1,
        'emerging_markets': -1, # food import dependent nations: Egypt, Lebanon
    },
}
```

## Timing Model

```python
def geopolitical_signal_timing(event_severity: Severity) -> dict:
    """
    Markets typically price geopolitical events in phases.
    Returns suggested trade timing parameters.
    """
    timing_map = {
        Severity.LOW: {
            'initial_spike_duration': '1-4 hours',
            'peak_impact': '1-3 days',
            'mean_reversion': '1-2 weeks',
            'action': 'Wait for initial spike, fade if no escalation',
        },
        Severity.MEDIUM: {
            'initial_spike_duration': '4-24 hours',
            'peak_impact': '1-2 weeks',
            'mean_reversion': '4-8 weeks',
            'action': 'Trade with trend during peak, watch for plateau',
        },
        Severity.HIGH: {
            'initial_spike_duration': '1-3 days',
            'peak_impact': '4-12 weeks',
            'mean_reversion': '3-6 months',
            'action': 'Structural position; manage with trailing stops',
        },
        Severity.EXTREME: {
            'initial_spike_duration': '3-7 days',
            'peak_impact': 'Months to years',
            'mean_reversion': 'Uncertain',
            'action': 'Risk-off immediately; reassess when situation stabilises',
        },
    }
    return timing_map[event_severity]
```

## Quick Reference — Reliable Safe Havens

| Asset | Behaviour | Notes |
|-------|-----------|-------|
| Gold | Rises on uncertainty | Most reliable safe haven |
| USD | Rises on global crisis | Loses safe haven in US-specific events |
| CHF | Rises on European crisis | Swiss franc haven |
| JPY | Rises initially, may fall if Japan involved | Carry unwind amplifies |
| US Treasuries | Rises (yield falls) | Unless US fiscal crisis is the event |
| BTC | Inconsistent | Sometimes safe haven, often risk-off sells off |
| Oil | Rises on supply events | Falls on demand destruction events |

## Common Mistakes

1. **Chasing the initial spike** — first reaction is often wrong; wait for second-day confirmation
2. **Ignoring resolution probability** — a "warning shot" sanctions vs. full embargo = very different impact
3. **Forgetting sanctions evasion** — Russia/Iran showed sanctions rarely achieve stated economic goals
4. **Linear extrapolation** — market prices in a lot quickly; impact often peaks before situation resolves
5. **Missing second-order effects** — the wheat price impact on Egyptian pound is often more tradeable than wheat itself
6. **Source reliability** — Telegram/Twitter geopolitical news has 50%+ false alarm rate; weight accordingly

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Chasing the initial market reaction spike | First reaction to geopolitical events is wrong 40-60% of the time; driven by panic, not analysis | Wait for second-day confirmation; the initial spike often fully reverses within 24-48 hours |
| Linear extrapolation of event impact | Markets price in information quickly; impact often peaks before the situation reaches its worst point | Model impact as a decaying curve; most of the price move happens in the first 1-3 sessions |
| Treating all sanctions as economically devastating | Russia/Iran sanctions showed that evasion routes emerge quickly; actual economic impact often far less than projected | Assess enforcement capability and evasion probability; weight historical compliance rates for similar sanctions |
| Ignoring second-order effects for more tradeable opportunities | Direct impact on obvious assets is crowded; second-order effects are often more profitable | Map the supply chain: a Middle East conflict affects oil, but the Egyptian pound via wheat prices may be more tradeable |
| Using social media as primary geopolitical intelligence | Telegram/Twitter geopolitical news has 50%+ false alarm rate; reacting to every rumour destroys capital | Weight established sources (Reuters, AP, official government statements) heavily; treat social media as early warning only |
