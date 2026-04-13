# Grounding Tiers: Confidence Classification

## Tier Definitions

| Tier | Label | Confidence | Source Required | Citation Format |
|------|-------|-----------|----------------|----------------|
| 1 | **verified** | HIGH | Direct match from authoritative source | `[Grounding: verified \| source: <id>/<page>]` |
| 2 | **grounded** | MEDIUM-HIGH | Partial match or synthesis from multiple sources | `[Grounding: grounded \| source: <id>, N sources]` |
| 3 | **inferred** | MEDIUM | Cross-referenced weak signals | `[Grounding: inferred \| signals: <id1>, <id2>]` |
| 4 | **training-only** | LOW | None -- model training data only | `[Grounding: training-only \| no internal sources matched]` |

## Decision Matrix

| Match quality | Single source | Multiple sources |
|--------------|--------------|-----------------|
| Exact content match | Tier 1 (verified) | Tier 1 (verified, multi-source) |
| Partial / related content | Tier 3 (inferred) | Tier 2 (grounded) |
| Semantic similarity only | Tier 3 (inferred) | Tier 3 (inferred) |
| No match | Tier 4 | Tier 4 |

## Edge Cases

| Scenario | Tier | Rationale |
|----------|------|-----------|
| Wiki page exists but is >6 months old | Tier 2, not 1 | Freshness matters -- stale source degrades confidence |
| Confluence page matches but auth failed | Tier 4 | Cannot verify content without access |
| Vector store returns 0.95 similarity | Tier 2 | Semantic match, not exact content |
| Vector store returns 0.7 similarity | Tier 3 | Weak signal, needs corroboration |
| Multiple wiki pages partially match | Tier 2 | Synthesis from multiple internal sources |
| Internet source contradicts wiki | Tier 2 + flag | Note the contradiction, prefer internal authoritative source |
| Training data matches wiki exactly | Tier 1 | The wiki citation is what elevates it |

## strict_airgap Behavior

When `strict_airgap: true` in `~/.knowledge-grounding.yaml`:

| Tier | Behavior |
|------|----------|
| 1 (verified) | Proceed normally |
| 2 (grounded) | Proceed normally |
| 3 (inferred) | Proceed with warning: "Inferred from weak signals, not directly verified" |
| 4 (training-only) | BLOCK: "No internal source found. This would use model training data (cutoff May 2025). Proceed? [y/n]" |

Default (`strict_airgap: false`): all tiers proceed, tier 4 is flagged but not blocked.

## Freshness Weighting

Source freshness modifies the tier assignment:

| Source Age | Modifier |
|-----------|----------|
| < 30 days | No change |
| 30-90 days | No change (still current) |
| 90-180 days | Consider downgrading by 1 tier if topic is fast-moving |
| > 180 days | Downgrade by 1 tier for tech topics; no change for stable reference |

Freshness is tracked in the sources manifest (`freshness` field per source).
