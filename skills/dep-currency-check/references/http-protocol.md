# HTTP protocol — exact GET URLs, response shapes, rate limits

## PyPI

- **URL**: `https://pypi.org/pypi/<pkg>/json`
- **Method**: GET
- **Auth**: none
- **Rate limit**: 100 req/min (generous)
- **Response shape**:
  ```json
  {
    "info": {"name": "...", "version": "...", "yanked": false, ...},
    "releases": {
      "1.0.0": [{"yanked": false, "upload_time_iso_8601": "..."}, ...],
      ...
    }
  }
  ```
- **VersionInfo extraction**: `info.version` = latest stable; `releases` keys filtered for non-yanked = full version list.
- **Yanked detection**: any release entry with `yanked: true`.

## npm

- **URL**: `https://registry.npmjs.org/<pkg>/latest`
- **Method**: GET
- **Auth**: none (unauthenticated for public packages)
- **Rate limit**: liberal; ~500 req/min observed
- **Response shape**:
  ```json
  {
    "name": "...",
    "version": "1.0.0",
    "deprecated": "use foo-ng instead",   // optional
    "dist": {"tarball": "...", "shasum": "..."},
    "time": "..."
  }
  ```
- For dist-tags: `https://registry.npmjs.org/<pkg>` returns full metadata including `dist-tags`.

## crates.io

- **Sparse index URL (PREFERRED for v1)**: `https://index.crates.io/<prefix>/<pkg>` where `<prefix>` is computed from package name length:
  - 1 char: `1/<name>`
  - 2 chars: `2/<name>`
  - 3 chars: `3/<first-char>/<name>`
  - ≥4 chars: `<first-2-chars>/<chars-3-4>/<name>`
- **API URL (rate-limited fallback)**: `https://crates.io/api/v1/crates/<pkg>`
- **Mandatory User-Agent**: crates.io REJECTS missing or default User-Agents (`User-Agent: dep-currency-check/0.1.0`)
- **Rate limit (API)**: 1 req/s hard limit; sparse index has no limit
- **Sparse index response**: JSONL — one JSON record per line, one per version. Latest is the last non-yanked entry.

## Go module proxy

- **URL**: `https://proxy.golang.org/<module>/@latest`
- **Method**: GET
- **CRITICAL**: capital letters MUST be escaped with `!`. `github.com/Azure/azure-sdk-for-go` → `github.com/!azure/azure-sdk-for-go`.
- **Auth**: none
- **Response shape**:
  ```json
  {"Version": "v1.2.3", "Time": "2024-01-15T10:00:00Z"}
  ```

## RubyGems

- **URL**: `https://rubygems.org/api/v1/gems/<pkg>.json`
- **Method**: GET
- **Auth**: none
- **Response shape**:
  ```json
  {"name": "...", "version": "1.0.0", "deprecation": null, ...}
  ```

## Maven Central

- **URL**: `https://search.maven.org/solrsearch/select?q=g:<group>+AND+a:<artifact>&core=gav&rows=1&wt=json`
- **Method**: GET
- **Composite key**: requires BOTH `g:` (group) AND `a:` (artifact) — connected by `+AND+`
- **Response shape**: Solr-formatted; `response.docs[0]` has `v` (version), `timestamp` (epoch ms).

## OSV.dev /v1/querybatch

- **URL**: `https://api.osv.dev/v1/querybatch`
- **Method**: POST
- **Body**:
  ```json
  {"queries": [{"package": {"name": "...", "ecosystem": "..."}, "version": "..."}, ...]}
  ```
- **Ecosystem strings (verified)**:
  - Python: `PyPI`
  - JavaScript: `npm`
  - Rust: `crates.io`
  - Go: `Go`
  - Ruby: `RubyGems`
  - Java: `Maven`
- **Rate limit**: ~600 req/min (very generous)
- **No auth required** (rate limit can be raised with `$GH_TOKEN`)
- **Response shape**: array of `{vulns: [{id, summary, severity, affected, ...}]}` per query.

## Error semantics

- 404 → mark `gap_kind=unknown`, advisory
- 429 → backoff 1s/2s/4s, max 3 retries; then defer
- 5xx → defer immediately (server fault, not our problem)
- Timeout (default 10s/request, 60s total): defer
- TLS failures → check `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` env vars for enterprise CA bundle support

## Per-host failure tally

After 3 consecutive timeouts/5xx to one host in a single run, that host switches to deferred for the rest of the run. Prevents wasting time on a degraded registry.
