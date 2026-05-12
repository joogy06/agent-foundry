# Output schema — JSON canonical + rendering layer

Per Codex challenger Rev 2 — JSON is the **single canonical data contract**. All other outputs (markdown, table, yaml) are **renderings** over the JSON with zero authority of their own.

## Canonical JSON shape (`dep-currency.v1`)

```json
{
  "schema_version": "dep-currency.v1",
  "generated_at": "2026-05-12T14:00:00Z",
  "project_root": "/path/to/project",
  "grounding_mode": "full",
  "manifests_scanned": ["pyproject.toml", "poetry.lock"],
  "summary": {"critical": 1, "high": 0, "moderate": 0, "deprecated": 1, "current": 47},
  "findings": [
    {
      "package": "requests",
      "ecosystem": "python",
      "declared_version": ">=2.20,<2.28",
      "declared_resolves_to": "2.27.1",
      "latest_stable": "2.32.3",
      "is_direct": true,
      "is_dev": false,
      "is_transitive": false,
      "transitive_depth": 0,
      "parent_chain": [],
      "gap_kind": "major_behind",
      "semver_distance": [0, 5, 2],
      "last_release_age_days": null,
      "cves": [
        {
          "id": "CVE-2024-35195",
          "severity": "critical",
          "cvss_score": 7.5,
          "summary": "...",
          "affected_range": "<2.32.0",
          "fixed_versions": ["2.32.0"],
          "published": "2024-05-20",
          "source": "osv",
          "osv_id": "GHSA-9wx4-h78v-vm56"
        }
      ],
      "blocks_build": true,
      "recommended_action": "upgrade_to_latest_stable"
    }
  ],
  "advisories": ["osv-scanner unavailable for python; fell back to OSV.dev HTTP"],
  "osv_records": [
    {"/* embedded OSV-format record per CVE */"}
  ]
}
```

## Field semantics

| Field | Type | Notes |
|---|---|---|
| `schema_version` | `"dep-currency.v1"` | Pin via `--schema-version`; bump on breaking change |
| `grounding_mode` | `"full"` \| `"internal-only"` \| `"offline-cold-cache"` | From sources.json + cache state |
| `manifests_scanned` | list of relative paths | Relative to `project_root` |
| `summary` | map[str, int] | Counts by severity + special categories (deprecated, current) |
| `findings[]` | array of Finding objects | One per `(manifest, package)` tuple |
| `findings[].gap_kind` | enum | `current` \| `minor_behind` \| `major_behind` \| `deprecated` \| `yanked` \| `unmaintained` \| `unknown` \| `deferred_offline` |
| `findings[].blocks_build` | bool | `true` only when critical CVE + direct + production (not dev) + fix available |
| `advisories[]` | list[str] | Soft-failure notes ("rate-limited", "fell back to HTTP", etc.) |
| `osv_records[]` | array | Raw OSV records embedded for any CVE referenced in `findings[].cves` |

## Offline-cold-cache shape (example)

```json
{
  "schema_version": "dep-currency.v1",
  "generated_at": "2026-05-12T14:00:00Z",
  "project_root": "/path/to/project",
  "grounding_mode": "offline-cold-cache",
  "manifests_scanned": ["pyproject.toml"],
  "summary": {"deferred_offline": 47},
  "findings": [
    {
      "package": "requests",
      "ecosystem": "python",
      "declared_version": ">=2.20,<2.28",
      "declared_resolves_to": null,
      "latest_stable": null,
      "is_direct": true,
      "is_dev": false,
      "gap_kind": "deferred_offline",
      "cves": [],
      "blocks_build": false,
      "recommended_action": "retry_when_online"
    }
  ],
  "advisories": [
    "grounding_mode: offline-cold-cache — all version queries deferred",
    "47 packages have no cached version data; cannot assess currency"
  ],
  "osv_records": []
}
```

## Rendering views

Pure functions of the canonical JSON. They cannot add/modify fields; only re-shape for display.

- `--render markdown` — markdown table; default for chat / forge / alf consumption
- `--render table` — ASCII table; TTY-friendly
- `--render yaml` — YAML representation; compat-friendly
- `--render osv` — emits ONLY the OSV records (no Report wrapper) for raw vuln consumers

There is NO `--format yaml`. YAML is a `--render` value.

## Schema validation

A `dep-currency.v1.json` JSON schema lives next to this doc. Validated in unit tests via stdlib `unittest`.
