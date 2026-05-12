# Integration: scope_delta hook (S029)

## Trigger

forge Step 1 OR bob's WP boundary discovers a **critical CVE** in a **direct dep**. Transitive does NOT trigger — too noisy per FP-risk analysis.

## Record shape

Reuses `artifact_kind: file` per the verified `scope_delta.v1` schema constraint (NO v2 schema bump). All fields per `~/.claude/skills/_meta/schemas/scope_delta.v1.json`.

```yaml
delta_id: scope-delta-2026-05-12T14:00:00Z-a1b2c3
schema_version: scope_delta.v1
created_at: "2026-05-12T14:00:00Z"
created_by: dep-currency-check
project_root: /path/to/project
contract_map_hash: sha256:<64-hex>
contract_map_revision: 0
artifact_kind: file                   # reused — no v2 schema bump
operation: changed
path: pyproject.toml#requests         # composite: manifest + dep name
content_hash: <sha256 of manifest_path+package+cve_id>
severity: critical
detection_point: wp_boundary
requesting_wp: WP-3-http-client
status: undecided
critical_reason: |
  CVE-2024-35195 in requests <2.32.0 (declared range: >=2.20,<2.28).
  This WP imports requests directly. Pause and amend the contract map
  to require requests>=2.32.0, or excuse with explicit rationale.
extractor_meta:
  source: dep-currency-check
  schema: dep-currency.v1
  cve_ids: [CVE-2024-35195]
  cvss: 7.5
  latest_stable: 2.32.3
```

## Dedup key (NON-NEGOTIABLE S029 lesson)

`(manifest_path, package, cve_id)`

Computed BEFORE calling `scope_delta.write_record`. Mirrors `~/.claude/skills/_meta/gates.py` lines ~2393-2419 pattern:

```python
existing_undecided_keys = set()
for rec in _scope_delta.read_records(project_root, status_filter="undecided"):
    if rec.get("created_by") != "dep-currency-check":
        continue
    em = rec.get("extractor_meta", {})
    for cve in em.get("cve_ids", []):
        # Reconstruct (manifest_path, package, cve_id) from existing record
        path = rec["path"]  # "pyproject.toml#requests"
        manifest_path, _, package = path.partition("#")
        existing_undecided_keys.add((manifest_path, package, cve))

# For each new candidate finding:
dedup_key = (manifest_path, package, cve_id)
if dedup_key in existing_undecided_keys:
    continue  # already an undecided record covers this; skip emission
# Otherwise: write new record
_scope_delta.write_record(project_root, new_record)
existing_undecided_keys.add(dedup_key)
```

**Critical**: dedup BEFORE `write_record`, NEVER AFTER. Dedup after write produces the 2000+-record explosion documented in `_meta/gates.py`.

## Bob's reaction

Existing `scope_reaction.py` handles `undecided` + `critical`: pause cycle fires. User prompted:

- **B1** — amend contract-map to require `requests>=2.32.0`
- **B2** — excuse with rationale (writes resolution to scope_delta record + amended map)
- **B3** — abort WP

**No new pause-state code needed** — existing flow handles it.

## When this hook fires (CLI flag)

Only when `--emit-scope-delta` is passed AND `--mode strict`. The CLI default is advisory; `--emit-scope-delta` is opt-in for callers that want bob's pause-cycle integration.

```bash
python3 -m dep_currency_check "$PROJECT" \
  --emit-scope-delta \
  --mode strict \
  --format json
```

Forge Step 1 does NOT pass `--emit-scope-delta` (forge is advisory). Bob's WP boundary OPTIONALLY passes it (gated by `.contract/gates.yaml`).
