# Air-gap mode

## Three grounding modes

Read from `~/.claude/state/sources.json` on EVERY CLI invocation (sessions can flip air-gap state):

| Mode | Behavior |
|---|---|
| `full` | Network reachable; query registries + OSV normally; cache as usual |
| `internal-only` | No internet but local data sources may be reachable; ANY cached entry acceptable regardless of TTL |
| `offline-cold-cache` | No network AND no useful cache; mark all findings `gap_kind: deferred_offline`; emit advisory |

## CLI flags

- `--offline` — explicit offline mode; treats network as unreachable. Equivalent to `grounding_mode: internal-only`
- `--strict-airgap` — fails (exit 4) if anything would have required network. For CI on internal hosts.
- `--allow-deferred` — exit 0 even with `gap_kind: deferred_offline` findings

## Source of truth

`~/.claude/state/sources.json` is the **single source of truth** for grounding mode. Only the CLI reads it (not the lower modules). This centralizes air-gap policy.

Shape (from `knowledge-grounding` skill):

```json
{
  "grounding_mode": "full" | "internal-only",
  "internet_reachable": true | false,
  "sources_available": [...],
  "last_probe": "2026-05-12T13:00:00Z"
}
```

## Behavior in each mode

### `full`
- Try wrapper subprocess (if installed)
- Fall back to HTTP if wrapper unavailable
- Cache fresh data per TTL rules
- ETag conditional GETs when cache stale

### `internal-only`
- Use cache regardless of TTL
- If cache miss: mark `gap_kind: deferred_offline`
- Emit advisory: `"grounding_mode: internal-only — using stale cache; <N> packages have no cached data"`
- Never attempt network

### `offline-cold-cache`
- Computed dynamically when `internal-only` AND cache cold for ALL packages
- All findings marked `gap_kind: deferred_offline`
- Single advisory: `"grounding_mode: offline-cold-cache — all version queries deferred; retry when online"`
- Recommended action: `"retry_when_online"`

## --strict-airgap

For CI on internal hosts where ANY accidental network call is a security concern:

- Wraps the HTTP client to refuse all requests
- If wrapper subprocess attempts network → wrapper may fail; that's treated as `None` per normal failure semantics
- If cache miss → exit 4 (deferred) immediately; no fallback to network attempted

## Per-host failure tally

Even in `full` mode, after 3 consecutive timeouts/5xx to one host, that host switches to deferred for the rest of the run. Prevents wasting time on a degraded registry.

State: in-memory per-CLI-invocation only; doesn't persist between runs.
