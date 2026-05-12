# Cache design — split TTL + atomic writes

## Layout

`~/.claude/state/dep-currency-cache/<class>/<ecosystem>/<package>.{json,etag}`

- `<package>.json` — cached registry response (full original payload + extracted VersionInfo)
- `<package>.etag` — sidecar with ETag for conditional GETs

## Split TTL by data class

| Data class | TTL | Cache key prefix |
|---|---|---|
| Version metadata (registry queries) | 12-24h (default 18h) | `versions/<ecosystem>/<package>.json` |
| Vulnerability data (OSV records, advisory feeds) | **2h** (Codex challenger requirement) | `vulns/<ecosystem>/<package>.json` |
| Deprecation prose interpretations (LLM verdicts) | 7 days | `deprecation/<ecosystem>/<package>.json` |
| Community-wrapper outputs (pip-audit JSON, etc.) | 2h (mirrors vuln TTL) | `wrappers/<tool>/<project-hash>.json` |

Rationale: a newly disclosed critical CVE shouldn't hide for 24h. Versions move slower; deprecation prose almost never changes.

## Operations

- **put(key, value)**: write to `<key>.tmp` + `os.replace(tmp, key)` for atomicity
- **get(key)**: returns value if `mtime + ttl > now`, else None
- **invalidate(key)**: unlinks file (used by `--no-cache` for the matching entry)
- **etag_for(key)** / **set_etag(key, etag)**: ETag sidecar for conditional GETs

## ETag conditional GETs

When fetching a cached-but-stale entry:
1. Read `<key>.etag` if present
2. Send `If-None-Match: <etag>` header
3. On 304: refresh `mtime` of `<key>.json` in-place (no body re-download)
4. On 200: update both `<key>.json` and `<key>.etag`

## Atomic write

```python
def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(str(tmp), str(path))
```

Crash mid-write leaves no torn file. Mirrors `_meta/scope_delta.py` pattern.

## `--no-cache` bypass

- Bypasses ALL cache classes for the run
- Does not delete cached entries; just doesn't read them
- Still WRITES fresh entries (so subsequent runs benefit)

## Air-gap behavior

If `grounding_mode: internal-only` in `~/.claude/state/sources.json`, ANY cached entry is acceptable regardless of TTL (no network anyway). Report includes `stale_cache_used: true` advisory.

## Per-source modified-record polling (OSV optimization)

On EACH invocation, OPTIONALLY check OSV's modified-record index (`https://api.osv.dev/v1/vulns?modified_since=<last_poll>`) to invalidate vuln cache entries that have newer disclosures. Cheap (single API call); short-circuits per-package re-fetches.

State: `~/.claude/state/dep-currency-cache/osv-last-poll.txt` (single ISO-8601 timestamp).
