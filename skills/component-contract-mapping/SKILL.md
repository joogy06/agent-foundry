---
name: component-contract-mapping
description: Use at forge design phase (Step 8a) to produce a signed contract map for any design that introduces components. Extracts components from the design dialogue, defines typed I/O shapes with semantic types, writes progress/contract-map.yaml, runs G2 validation, auto-renders a markdown table into the design doc, and requests forge to HMAC-sign the result. The ONLY writer of contract-map.yaml.
---

# Component Contract Mapping

## Overview

Turn the design conversation into a **machine-parseable, frozen contract map** that bob can execute against. Every component the design introduces gets an explicit entry declaring its inputs, outputs, call graph position, integration points, success criteria, and test scenarios. The map is signed by forge with an HMAC payload (map_hash, map_revision, forge_session_id, signed_at) and verified mechanically by `gates.py G1` before any implementation begins.

This skill is the **single writer** of `progress/contract-map.yaml`. It runs during forge design phase 8a, after the design doc exists and before spec review.

## When Forge Invokes This Skill

Forge Step 8a invokes this skill when the approved design introduces new components (services, modules, APIs, integration points). Pure refactors and single-file bugfixes are exempt.

Inputs passed by forge:
- `design_doc_path` — path to the draft design document
- `project_root` — project root path (where `progress/` lives)
- `project_md_path` — path to PROJECT.md (optional)
- `component_md_paths` — list of relevant COMPONENT.md files (optional)

## Inputs Expected

You will need all of these before writing a single YAML field:

1. **The draft design doc** — read it end-to-end
2. **PROJECT.md** — so component ids and call graph fit the existing architecture
3. **Relevant COMPONENT.md files** — understand existing interfaces you must integrate with
4. **The user's spoken intent from the design dialogue** — forge has this in conversation; ask clarifying questions if a component's purpose or integration points are ambiguous
5. **The v1 semantic type registry** — `~/.claude/skills/sample-data-scaffolding/semantic-types.yaml` (18 types — see spec section 7.3.1)
6. **The project-local override** — `.contract/semantic-types.yaml` if present

## The Contract Map Schema (authoritative reference)

The full schema and all validation rules V1-V15 are defined in:
`/path/to/project/docs/plans/2026-04-09-contract-testing-pipeline-design.md`
sections 7.2 through 7.3.3.

Do NOT duplicate the schema in skill files — always cross-reference the spec. This prevents drift between the spec and the skill.

Key shape:

```yaml
schema_version: "1.0.0"      # REQUIRED
revision: 1                  # Monotonic. Bump on freeze-the-world updates.
design_doc: "docs/plans/..." # REQUIRED
generated_at: "<iso8601>"
generated_by: "component-contract-mapping@1.0.0"

types:                       # Shared type dictionary. Referenced by $ref.
  UserId: { kind: primitive, base: string, format: uuid, semantic_type: user_id }
  Email:  { kind: primitive, base: string, format: email, semantic_type: email }

components:
  - id: <kebab-case>         # Unique. V3 enforces kebab-case.
    purpose: "<one-line>"
    owner_wp: WP-NNN
    source_paths: ["src/..."]
    test_paths:
      unit:        "tests/unit/..."
      integration: "tests/integration/..."
      flow:        "tests/flow/"
    fixtures_path: "tests/fixtures/<component>/"
    inputs: [...]            # every input has semantic_type or kind: opaque
    outputs: [...]
    dependencies: [...]
    callers: [...]           # bidirectional with callees of the neighbours
    callees: [...]
    integration_points: [...]
    success_criteria: [...]
    test_scenarios: [...]    # V12 requires >=1
    flow_entry_point: bool   # at least one component must be true (V9)
    flow_terminal: bool      # at least one component must be true (V10)

flows:                        # consumer-driven only; NEVER auto-traverse
  - id: FLOW-001
    name: "..."
    path: [<component_id>, ...]
    entry_input: { component, input, fixture_ref }
    terminal_output: { component, output }
    expected_outcome: "..."
    priority: critical|standard|smoke

flow_budget:
  max_flows: 20
  max_components_per_flow: 10
```

## Step 1: Extract Components from the Design Discussion

Re-read the design doc and the user's dialogue. Identify every entity that:
- Has a distinct purpose that can be named in one sentence
- Has inputs and outputs (even if the output is a status code)
- Has a unique source_path pattern
- Is called by something or calls something

Do NOT invent components. If the design doc is silent on a component, flag it to the user and ask — never fabricate.

NEVER emit a contract map containing `TBD`, `?`, or empty required fields. Any gap = ask the user.

## Step 2: Define the Types Dictionary

Every shared type gets an entry in `types`. Components reference types via `$ref: TypeName` inside input/output shapes.

For each type:
- Declare the kind (primitive | record | collection)
- For primitives: declare base (string/integer/boolean/decimal) + format (if applicable) + `semantic_type`
- The `semantic_type` MUST be one of the 18 v1 registry values (section 7.3.1 of spec) OR a project-local override in `.contract/semantic-types.yaml` OR the literal `technical` sentinel with a valid `technical:` value from the closed list
- For records: declare fields recursively
- For collections: declare item type

If you need a semantic type not in the registry and not in the project-local override, STOP and tell the user. Two options:
1. Add the type to `.contract/semantic-types.yaml` with a Faker/Mimesis strategy (user decision)
2. Use `kind: opaque` with `opaque_reason` and `opaque_fixture_source` (technical debt path)

NEVER guess a semantic type. NEVER paraphrase `email` to `e-mail` — unknown values fail G2.

## Step 3: Write `progress/contract-map.yaml`

Write the map atomically:

```bash
mkdir -p progress
tmp=$(mktemp progress/.contract-map.XXXXXX.yaml)
# ... write YAML to $tmp ...
mv "$tmp" progress/contract-map.yaml
```

Required top-level fields: `schema_version`, `revision`, `design_doc`, `generated_at`, `generated_by`, `types`, `components`, `flows` (optional if no flows), `flow_budget` (optional).

**Revision counter:** start at `revision: 1` on first write. Bump to `2, 3, ...` only on freeze-the-world updates (spec section 12). The skill does NOT bump revision on its own — that happens during the pause protocol.

**Components order:** stable — sort by `id` alphabetically, or in topological order of the call graph. Either is acceptable; pick one and stick with it within a single run.

## Step 4: Run G2 Validation Locally

Before returning control to forge, run G2 yourself:

```bash
python3 ~/.claude/skills/_meta/gates.py G2 progress/contract-map.yaml --project-root "$PWD"
echo "exit=$?"
```

Expected: exit 0 with `G2_PASS:` message.

If exit 2 with `G2_FAIL: Vxx: ...`:
- Read the failing rule in spec section 7.3 (V1 through V15)
- Fix the design doc first (the YAML is a rendering of the doc; fixing the YAML without fixing the doc causes drift)
- Re-read the design doc to extract the corrected component
- Regenerate `progress/contract-map.yaml`
- Re-run G2

Iterate until G2 exits 0. Do NOT sign a map that has not passed G2.

## Step 5: Auto-Render Markdown Table into Design Doc

Append (or update) a "Component Contract Map" section in the design doc with a human-readable table rendered from the YAML:

```markdown
## Component Contract Map

| Component | Purpose | Inputs | Outputs | Callers | Callees | Flow Role |
|---|---|---|---|---|---|---|
| auth-service | Validates session tokens | session_token (session_token) | user_identity (record) | cart-service | — | entry |
| cart-service | Holds cart state | user_id (user_id), cart_items (record) | cart_state (record) | — | auth-service | — |
...

**Declared flows:** FLOW-001 (Guest checkout: auth → cart → order)

**New semantic types declared for this project:** (none | <list from .contract/semantic-types.yaml>)
```

The user reviews this table during Step 8c (spec review). If they spot a missing integration point or wrong semantic type, they edit the design doc; the skill is re-invoked to regenerate the YAML.

## Step 6: Request Forge Signature

Hand control back to forge with a signal that the map is ready to sign. Forge performs the HMAC step per its SKILL.md (Step 8a.2 — creates `.forge/session-id`, `.forge/session.key` if absent, computes the full signed payload, and writes `progress/contract-map.yaml.sig`).

Signing payload per spec section 7.4:

```json
{
  "map_hash": "<sha256 of contract-map.yaml bytes>",
  "map_revision": <revision int>,
  "forge_session_id": "<UUID from .forge/session-id>",
  "signed_at": "<ISO 8601 timestamp>"
}
```

Signature = HMAC-SHA256 over `canonical_json(payload)` using `.forge/session.key` content as the key. Canonical JSON = sorted keys, no whitespace, UTF-8.

## Step 7: Report Readiness to Forge

Return a structured report to forge:

```
Contract map generated:
- progress/contract-map.yaml (revision 1, N components, M flows)
- G2 validation: PASS
- Design doc updated with Component Contract Map section
- New semantic types declared: [list or "none"]
- Ready for forge-signing (Step 8a.2)
```

## Validation Rules (V1-V15 reference)

See spec section 7.3 for the authoritative list. Summary (with severity HALT for all):

| # | Rule |
|---|---|
| V1 | `schema_version` present and supported (currently 1.0.0) |
| V2 | `revision` is a positive integer |
| V3 | Every component has a unique kebab-case `id` |
| V4 | Every component has all required top-level fields |
| V5 | Every `callees[]` entry resolves to a declared component |
| V6 | `callers` and `callees` are bidirectionally consistent |
| V7 | Every `$ref` resolves to `types[<name>]` |
| V8 | Every `fixture_refs` in `test_scenarios` points to a declared input |
| V9 | At least one component has `flow_entry_point: true` |
| V10 | At least one component has `flow_terminal: true` |
| V11 | Call graph is acyclic OR cycles are declared via matching `cycle_group:` |
| V12 | Every component has ≥1 `test_scenarios` entry |
| V13 | Every input has a `semantic_type` from the v1 registry, OR `semantic_type: technical` with a `technical:` value from the closed list, OR `kind: opaque` with `opaque_reason` + `opaque_fixture_source` |
| V14 | Every `flows[].path` element resolves to a component id |
| V15 | Total flows ≤ `flow_budget.max_flows` (if set) |

## Schema Evolution (schema_version + migration notes)

v1 is `schema_version: "1.0.0"`. Future MAJOR bumps (2.0.0) indicate breaking changes; MINOR bumps (1.1.0) are additive.

If a project's map has `schema_version: "0.x"` or `"2.x"` when v1 tooling reads it, G2 V1 fails loudly. Migration is explicit (user + skill revision), never silent.

## Anti-Patterns

- **Fabricating components the design doc does not mention.** Ask the user. Never invent.
- **Skipping G2 and jumping straight to signing.** Forge will refuse and the smoke test will catch it, but the rework is expensive.
- **Using `semantic_type: technical` as an escape hatch for domain fields.** The closed list is for genuine technical metadata (ids, timestamps, checksums). Domain fields (email, money, phone) must use registry values.
- **Paraphrasing semantic types** (e.g., `e_mail` instead of `email`). Unknown values fail G2.
- **Editing the YAML directly to fix a G2 failure.** Fix the design doc; regenerate the YAML.
- **Silently filling in fields the user never discussed.** A "helpful" auto-complete here becomes a frozen lie the whole pipeline is built on.
- **Auto-traversing the call graph to suggest flows.** Flows are consumer-driven. Ask the user what end-to-end scenarios matter.

## CRITICAL REMINDERS — RE-READ BEFORE EVERY ACTION

- NEVER emit a map containing `TBD`, `?`, or empty required fields.
- NEVER sign the map without a PASS from `gates.py G2`.
- NEVER edit the contract map after forge signs it. Gaps require a freeze-the-world update via forge (spec section 12).
- NEVER accept free-text `inputs` — every input has a typed shape and `semantic_type` from the v1 registry (or project-local) or `kind: opaque` with a reason.
- NEVER use `semantic_type: technical` outside the closed list (spec section 7.3).
- NEVER model async patterns (webhooks, pub/sub, retries, circuit breakers) in v1 — use `kind: opaque` or defer to v2.
- NEVER auto-generate maps without user dialogue. Maps are authored in conversation with the user during design.
- FORBIDDEN: partial maps. Any component in the design must have a complete entry before signing.
- FORBIDDEN: v1 scope creep. Tell the user up front if their design needs async/retry/saga patterns.

v1 scope is **sync request/response only**, exactly the 18 semantic types in the registry, pytest + jest test codegen only. Report any scope violation as a blocker, do not solve it.
