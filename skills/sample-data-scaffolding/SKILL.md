---
name: sample-data-scaffolding
description: Use during bob's Step 2.5 (once per component, before implementation WPs run) to generate realistic, seeded fixtures for each component in the frozen contract map. Reads inputs declared in progress/contract-map.yaml and produces tests/fixtures/<component>/<input>/<index>.json plus a manifest.yaml with hashes and semantic types used. Requires a bob-issued claim token; heartbeats it; emits transition requests for PLANNED → SCAFFOLDED. Never writes claim files or executes tests — bob owns both.
---

# Sample Data Scaffolding

## Overview

Turn the frozen contract map into realistic test fixtures. For each component's declared inputs, generate deterministic, semantically-typed sample data (Faker/Mimesis) and hash it into a manifest. Three fixture variants per field: happy, boundary, adversarial.

Bob invokes this skill once per component after G1/G2/G3 pass and after bob has issued a claim token. The skill does NOT gate itself — bob runs the gates and hands a pre-approved opaque claim UUID to the skill. The skill heartbeats the claim, generates fixtures, emits a transition request, and exits. Bob applies the transition atomically.

The skill GENERATES fixture files. Bob EXECUTES the runner (spec section 11.2 CB3 fix). The skill NEVER writes to the ledger directly.

## When Bob Invokes This Skill (with a claim_uuid bob already issued)

Bob's Step 2.5 (spec section 14.2) calls this skill with:
- `component_id` — the component to scaffold
- `claim_uuid` — opaque claim token bob issued via `claims.issue_claim(wp_id, "sample-data-scaffolding")`
- `contract_map_path` — `progress/contract-map.yaml` (read-only)
- `project_root` — project root

Bob has already:
1. Run `gates.py G1` with ledger binding — passed
2. Run `gates.py G2` — passed
3. Called `claims.issue_claim(...)` — returned the claim UUID
4. Bumped the component's generation counter if needed

The skill's job is narrow: generate fixtures, heartbeat, emit a request.

## Pre-Flight: Verify Bob Issued a Claim Token

The first thing the skill does is verify the claim actually exists on disk and is owned by bob:

```python
import yaml
from pathlib import Path

claim_path = Path(f".ledger/claims/{claim_uuid}.claim.yaml")
if not claim_path.is_file():
    raise SystemExit("CLAIM_MISSING: bob has not issued a claim for this skill invocation")
claim = yaml.safe_load(claim_path.read_text())
if claim.get("issued_by") != "bob" or claim.get("skill") != "sample-data-scaffolding":
    raise SystemExit("CLAIM_OWNERSHIP_VIOLATION: claim is not a bob-issued sample-data-scaffolding claim")
```

If either check fails, the skill HALTs. It never writes claim files — that would violate CB4.

## Step 1: Receive `component_id` and `claim_uuid` from bob

Expected CLI invocation (reference pattern):

```
python3 -m sample_data_scaffolding scaffold \
    --component auth-service \
    --claim <UUID> \
    --contract-map progress/contract-map.yaml \
    --project-root .
```

The skill is typically invoked by bob as a Python module; the CLI form above is a reference.

## Step 2: Start Heartbeat Loop (every 60s)

```python
from _meta import claims
state = claims.heartbeat_claim(claim_uuid)  # 'ok' | 'stale' | 'expired'
if state != "ok":
    # STOP IMMEDIATELY. Report to bob. Do not emit a transition request.
    raise SystemExit(f"CLAIM_{state.upper()}: re-run G3 and reissue claim")
```

Heartbeat runs every 60 seconds in a background thread while the generator works. If any heartbeat returns `stale` or `expired`, STOP all work immediately and exit cleanly — bob will reissue a fresh claim and re-invoke the skill.

## Step 3: Load Contract Map (Read-Only), Locate Component Entry

```python
import yaml
map_yaml = yaml.safe_load(Path("progress/contract-map.yaml").read_text())
component = next((c for c in map_yaml["components"] if c["id"] == component_id), None)
if component is None:
    raise SystemExit(f"COMPONENT_NOT_IN_MAP: {component_id}")
```

Do NOT mutate the map. It is frozen.

## Step 4: For Each Input — Derive Fixture Strategy

Load the v1 semantic type registry from
`~/.claude/skills/sample-data-scaffolding/semantic-types.yaml`
and the project-local override at `.contract/semantic-types.yaml` if present.

For each input field:

| Input shape | Strategy |
|---|---|
| `kind: primitive` + `semantic_type: X` | Look up X in the merged registry. Use the declared Faker/Mimesis strategy key. |
| `kind: primitive` + `semantic_type: technical` + `technical: Y` | Generate per the technical closed-list rules (ids from uuid4, timestamps from now, hashes from sha256 of random bytes). |
| `kind: record` | Recurse into each field. |
| `kind: collection` | Generate N items (N = `example_count` or default 4). |
| `kind: opaque` | DO NOT generate. Copy `opaque_fixture_source` into the fixtures path as-is. |
| `$ref: TypeName` | Look up the type in `map_yaml["types"]` and recurse on its shape. |

NEVER invent a field the input does not declare. NEVER generate for a field without a semantic type unless it is `kind: opaque` with a fixture source.

## Step 5: Generate Fixtures (Faker/Mimesis + Seeded Determinism)

Determinism is mandatory. Re-running with the same seed MUST produce the same fixtures — this makes tests reproducible and lets the audit bundle be hashed reliably.

Seed derivation:
```python
import hashlib
seed_input = f"{component_id}::{input_name}::{contract_map_hash}".encode()
seed = int.from_bytes(hashlib.sha256(seed_input).digest()[:8], "big")
faker = Faker()
faker.seed_instance(seed)
```

Variants per field (spec section 17 R2):
- `happy`    — typical value
- `boundary` — empty-string, zero, max-length, unicode edges
- `adversarial` — SQL injection marker, XSS marker, null byte, overflow

Produce `example_count` samples per variant (default 3; max from contract map).

## Step 6: Write Fixtures and Manifest Atomically

Write to `tests/fixtures/<component_id>/<input_name>/<variant>/<index>.json` via tmp+rename:

```python
fixtures_dir = Path(f"tests/fixtures/{component_id}/{input_name}/{variant}")
fixtures_dir.mkdir(parents=True, exist_ok=True)
for i, sample in enumerate(samples):
    tmp = fixtures_dir / f".{i}.json.tmp"
    tmp.write_text(json.dumps(sample, sort_keys=True))
    tmp.rename(fixtures_dir / f"{i}.json")
```

Write the manifest:

```yaml
# tests/fixtures/<component_id>/manifest.yaml
schema_version: "1.0.0"
component_id: auth-service
contract_map_hash: sha256:<hash>
generated_at: <iso8601>
generated_by: sample-data-scaffolding@1.0.0
seed_salt: <component_id + contract_map_hash>
inputs:
  session_token:
    semantic_type: session_token
    strategy: hex_random_32
    fixtures:
      happy:
        - path: tests/fixtures/auth-service/session_token/happy/0.json
          hash: sha256:<hash>
      boundary: [...]
      adversarial: [...]
```

## Step 7: Emit Transition Request to Bob

Write `.ledger/requests/<request_id>.request.yaml` (do NOT touch the ledger or claim files directly):

```yaml
request_id: <UUID>          # for idempotent apply
claim_uuid: <UUID>          # bob verifies this
wp: WP-NNN
component_id: auth-service
requester: sample-data-scaffolding
target_stage: SCAFFOLDED
evidence:
  - type: fixture_manifest
    path: tests/fixtures/auth-service/manifest.yaml
    hash: sha256:<hash>
    produced_by: skill:sample-data-scaffolding
  - type: semantic_validation
    command: "python3 -m sample_data_scaffolding validate tests/fixtures/auth-service/"
    exit_code: 0
at: <iso8601>
```

## Step 8: Await Bob's Apply Confirmation or Stale/Expired Signal

Bob picks up the request file, runs `verify_claim_on_transition`, and either:
- Applies the transition atomically (ledger bumps to SCAFFOLDED) → skill exits 0
- Rejects the request (stale claim, invalid transition) → skill exits 1 and bob escalates

The skill does NOT poll forever. If bob has not applied within the claim's lease TTL (default 10 min), the claim expires and the skill exits with `CLAIM_EXPIRED`. Bob's recovery logic handles the retry.

## Fixture Derivation Rules (primitive / record / collection / $ref)

See Step 4. The rule is: follow the shape declared in the contract map. Never guess structure. Never inline fields that the shape does not declare.

## Semantic Type Registry (v1 — 18 types, see spec section 7.3.1)

The registry lives at `~/.claude/skills/sample-data-scaffolding/semantic-types.yaml` and is derived from `~/.claude/skills/_meta/gates.py` `V1_SEMANTIC_TYPES` by construction. A parity test (spec section 20 criterion 9 and this skill's test suite) runs on any change — drift fails the build.

The 18 types are:
- Identity: `user_id`, `session_token`, `api_key`
- Contact: `email`, `phone_e164`, `address_line`, `country_iso2`
- Personal: `full_name`, `first_name`, `last_name`, `date_of_birth`
- Temporal: `iso_8601_datetime`, `iso_8601_date`, `unix_timestamp`
- Financial: `currency_amount`, `currency_iso4217`, `iban`
- Web: `url_http`

To add a project-specific type, create `.contract/semantic-types.yaml` in the project root:

```yaml
semantic_types:
  internal_product_sku:
    strategy: faker.bothify
    args: { text: "PRD-####-???" }
    validator: "^PRD-\\d{4}-[A-Z]{3}$"
```

G2 loads both and namespaces them. Project-local wins on collision with a warning in the design-doc callout.

## Determinism & Seeding

Same inputs → same bytes. The `contract_map_hash` is part of the seed so that a re-signing of the map (freeze-the-world revision bump) produces fresh fixtures for affected components only. Unaffected components keep their fixtures because the re-run produces bit-identical output.

## Heartbeat Discipline (on stale/expired → stop work, wait for new claim)

- Heartbeat every 60 seconds in a background thread.
- On `stale` or `expired`: stop work immediately, do NOT emit a transition request, exit with `CLAIM_STALE` or `CLAIM_EXPIRED`.
- On `ok`: continue.
- On heartbeat network error: retry once after 5 seconds, then HALT.

## Timeout Handling

Per-WP budgets: S=10min, M=25min, L=60min. If the generator exceeds its budget (determined by bob), bob revokes the claim, the skill's next heartbeat sees `expired`, and the skill exits cleanly.

## CRITICAL REMINDERS — RE-READ BEFORE EVERY ACTION

- NEVER start work without verifying the claim token on disk is bob-issued.
- NEVER write to `progress/integration-ledger.md` directly — emit a transition request file.
- NEVER write to `.ledger/claims/` — claims are bob-only (CB4).
- NEVER execute tests — bob's trusted runner owns execution (CB3).
- NEVER generate fixtures for a field without a `semantic_type` (unless `kind: opaque` with fixture source).
- NEVER use a semantic type not in the v1 registry or the project-local override.
- NEVER invent fixture fields the contract map input does not declare.
- NEVER overwrite existing fixtures without an explicit `--regenerate` flag from bob.
- NEVER skip the heartbeat loop — silent work after the lease expires is a discipline violation.
- FORBIDDEN: fixtures without deterministic seeds — re-runs must be reproducible.
- FORBIDDEN: opaque fixtures with no declared source file — the map must point to a real sample.
- FORBIDDEN: running G1/G2/G3 yourself — bob does that before calling the skill.

v1 scope: sync request/response, the 18 registry types, pytest + jest fixtures only. Report scope violations to bob, do not solve them.
