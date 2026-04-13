# Routing Logic: Per-Query Source Selection

## Algorithm

For each factual question or claim that needs grounding:

```
1. Read sources.json to get available sources
2. Read session state to get reachability status
3. Walk priority list top-to-bottom:
   a. Skip sources not in active_sources
   b. For remote sources: lazy-probe on first use (update session state)
   c. Query the source using its query_via skill/tool
   d. If match found: assign grounding tier, stop
   e. If partial match: note it, continue to next source
4. If no match from any source:
   a. Assign tier 4 (training-only)
   b. If strict_airgap: prompt user for override
   c. If not strict_airgap: proceed with training data, flag explicitly
5. Combine results if multiple tiers contributed
```

## Priority Order

| # | Source | Speed | When to Skip |
|---|--------|-------|-------------|
| 1 | Wiki (auto_consult) | instant | No wikis discovered |
| 2 | Project docs | instant | No PROJECT.md or docs/ in CWD |
| 3 | Git repo docs | instant | No doc_paths configured |
| 4 | Vector store | fast | Not configured or not reachable |
| 5 | Confluence | slow | Not configured or auth failed |
| 6 | Jira | slow | Not configured or auth failed |
| 7 | Internet | slow | internet_reachable = false |
| 8 | Training data | instant | Never skipped (always available) |

## Tier Assignment

| Condition | Tier |
|-----------|------|
| Exact content match from single authoritative source | 1 (verified) |
| Multiple partial matches synthesized | 2 (grounded) |
| Weak signals from multiple sources, cross-referenced | 3 (inferred) |
| No internal source match | 4 (training-only) |

## Lazy Remote Probing

Remote sources (Confluence, Jira, vector store) are NOT probed at session start. On first query that needs them:

1. Check session state: if `probed: false` or `reachable: "not-yet-probed"`
2. Probe the endpoint (3s timeout for HTTP, 2s for vector store)
3. Record result in session state: `reachable`, `authenticated`, `latency_ms`, `error`
4. Classify: reachable + authenticated = active; reachable + not authenticated = degraded; not reachable = unavailable

## Examples

### Query: "What is the retry policy for the payment service?"

```
1. Wiki grep: "retry policy payment" -> wiki_trading/payment-retry.md -> MATCH
   Tier: 1 (verified)
   Citation: [Grounding: verified | source: wiki_trading/payment-retry]
```

### Query: "What is the current Flask recommended deployment pattern?"

```
1. Wiki grep: "Flask deployment" -> no match
2. Project docs grep: "Flask deployment" -> no match
3. Internet reachable: true -> web-research skill
   Result: 3 independent sources agree on Gunicorn + reverse proxy
   Tier: 2 (grounded)
   Citation: [Grounding: grounded | source: web-research, 3 sources]
```

### Query: "What is the internal SLA for the batch processing pipeline?"

```
1-7. No matches (internal knowledge, not public)
8. Training data: no specific knowledge
   Tier: 4 (training-only)
   strict_airgap: true -> "No internal source found. Proceed with training data? [y/n]"
```
