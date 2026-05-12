# OSV.dev integration

## Why OSV-only for v1 (no GHSA direct queries)

OSV aggregates: GHSA + PyPA + RustSec + GoVulnDB + npm advisories. Direct GHSA = redundant queries + extra auth surface. Skip Snyk: enterprise-token-gated.

## /v1/querybatch endpoint

- **URL**: `https://api.osv.dev/v1/querybatch`
- **Method**: POST
- **Body**:
  ```json
  {
    "queries": [
      {"package": {"name": "requests", "ecosystem": "PyPI"}, "version": "2.27.1"},
      {"package": {"name": "react", "ecosystem": "npm"}, "version": "18.0.0"}
    ]
  }
  ```
- **No auth required** (rate limit uplift via `$GH_TOKEN` header — optional, ~600 req/min default)
- **Response**:
  ```json
  {
    "results": [
      {"vulns": [{"id": "GHSA-...", "summary": "...", "severity": [...], "affected": [...], ...}]},
      {"vulns": []}
    ]
  }
  ```

## Ecosystem mapping

Always use OSV-spec strings (NOT our internal lowercase Ecosystem literal):

| Internal | OSV string |
|---|---|
| `python` | `PyPI` |
| `js` | `npm` |
| `rust` | `crates.io` |
| `go` | `Go` |
| `ruby` | `RubyGems` |
| `java` | `Maven` |

## CVE → severity mapping

1. **OSV `database_specific.severity`** if present (`critical`/`high`/`moderate`/`low`)
2. Else **CVSS v3 score** → severity:
   - ≥9.0 = critical
   - 7.0-8.9 = high
   - 4.0-6.9 = moderate
   - <4.0 = low
3. No CVSS → `unknown` severity, advisory only (never blocks)

## Embedded OSV records

When CVEs found, the canonical JSON report includes raw OSV records in `osv_records[]`. This lets downstream consumers (vs-code-foundry, IDE integrations, SCA tools) consume the upstream schema directly without re-querying.

## Modified-record polling (optimization)

`https://api.osv.dev/v1/vulns?modified_since=<ISO-8601>` returns vuln IDs disclosed since the timestamp. Use to invalidate stale vuln cache entries without re-querying every package.

## False-positive mitigation

- Always show CVE summary + affected_range in report (user sanity-check)
- `--llm-cve-judge` opt-in for "does this CVE actually apply to my usage?" — off by default
- Distinguish DIRECT vs TRANSITIVE deps (direct blocks build; transitive advises)
- Distinguish "registry-deprecated" (hard) from "no release in 18 months" (soft)
