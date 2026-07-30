---
name: visual-architect
description: "Use at forge Step 2.5 for UI designs. Design-phase freeze skill that receives a draft skeleton (from skeleton-extractor), an approved HTML mockup, and user edits; validates every `binds_to: capability://...` URI resolves, enforces D2 strict on unresolved tokens (user must explicitly approve or add each one), HMAC-signs the payload with `.forge/session.key`, and atomically two-file writes `.design-ledger/skeletons/index.yaml` + `<screen>.yaml` via `trusted_runner.bundle_write`. Emits a `skeleton_frozen` transition request (bob applies — CB4). Mirrors S027 test-architect Phase-3 shape."
family: visual
disambiguation: forge Step 2.5 — reviews and FREEZES the design skeleton. Producing the draft skeleton by measurement is skeleton-extractor.
---

# visual-architect (v1)

**Status:** WP-8 of S028 ecosystem-keystone. Design-phase freeze skill for UI designs.

**Design document:** `/path/to/project/docs/plans/2026-04-23-ecosystem-keystone-design.md` §2.2, §2.3, §2.5, §5.7, D2.

## What this skill does

Turns a draft skeleton (from `skeleton-extractor`) + an approved HTML mockup + user edits into two **signed, frozen** artifacts:

- `.design-ledger/skeletons/index.yaml` — shared root (tokens, components, breakpoints, screen manifest, `design-skeleton-index.v1` schema)
- `.design-ledger/skeletons/<screen>.yaml` — per-screen skeleton (elements, bboxes, interactions, `design-skeleton.v1` schema)

Plus a ledger transition request (`skeleton_frozen` event) that bob consumes via `claims.apply_request_idempotent` (bob is sole ledger writer — CB4).

## When to invoke

Forge Step 2.5 (see design §5.7) when ALL the following are true:

- Design output includes an HTML mockup, CSS file, new user-facing screen, or new interactive element
- `ui_scope` is NOT `none` in the brief
- `skeleton-extractor` has already produced a draft skeleton on disk

Runs inline in forge's design-phase context; parallel with `component-contract-mapping` (Step 8a). NOT invoked by bob (`visual-arbiter` is bob's verification side).

## Invocation

```bash
python3 ~/.claude/skills/visual-architect/scripts/freeze.py freeze \
    --draft          <path to draft skeleton YAML> \
    --mockup         <path to approved HTML mockup> \
    --user-edits     <path to user-edits YAML or JSON> \
    --out-index      <path to write index.yaml> \
    --out-screen     <path to write <screen>.yaml> \
    --forge-session-key <path to .forge/session.key> \
    [--claim-uuid    <claim_uuid>] \
    [--project-root  <project root dir>]
```

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Freeze succeeded. Both files signed + written atomically. Transition request emitted to `.ledger/requests/`. |
| `1` | Freeze rejected — unresolved `binds_to` URI (challenge filed via `claims.file_challenge` with reason=`functional_requirement_conflict`). |
| `2` | Freeze rejected — unresolved token without explicit user approval (D2 strict; no challenge filed because it is a user-input gap, not a functional conflict). |
| `3` | Environmental / usage error (missing argv, unreadable input, malformed draft). |

## Library entry point

```python
from visual_architect.scripts.freeze import freeze_skeleton

result = freeze_skeleton(
    draft_path=Path(...),
    mockup_path=Path(...),
    user_edits={...},                 # parsed YAML/JSON dict
    out_index_path=Path(...),
    out_screen_path=Path(...),
    session_key_path=Path(...),
    project_root=Path(...),           # for URI resolution + challenge filing + request emission
    claim_uuid=str,                   # for transition request
)
# returns dict with: status ("frozen" | "rejected_binds_to" | "rejected_tokens"),
# index_path, screen_path, signature, request_path, challenges_filed.
```

## Inputs

### `--draft` — draft skeleton YAML

Output of `skeleton-extractor` (`.design-ledger/skeletons/<screen>.draft.yaml`). Unsigned; may contain:

- `interactions[].binds_to: null` — unwired; user MUST supply a `capability://...` URI (or mark `visual_only: true`)
- `unresolved_tokens: [{value: "#ac3b3b", seen_at: [selectors]}]` — hardcoded CSS values the extractor could not back-resolve. D2 strict: each MUST be approved or added to `tokens` before freeze.

### `--mockup` — approved HTML mockup

Pinned into `design_doc_hash` (sha256 of bytes). Used for provenance; not parsed here.

### `--user-edits` — user review output (YAML or JSON)

Schema (see §2.5 of design doc):

```yaml
binds_to_assignments:
  # map element_id#event -> capability URI (or visual_only sentinel)
  "step_card.1#click":           "capability://journey_controller.advance_step"
  "step_card.1#hover":           visual_only

bbox_confirmations:
  # map element_id -> {breakpoint: confirmed_bbox}
  # (if absent, extractor's bbox is kept)

tokens_approved:
  # list of {value, add_as: "path.to.token"} pairs to ADD to index.yaml tokens
  - {value: "#ac3b3b", add_as: "color.accent.brick"}

tokens_rejected:
  # list of values the user explicitly rejects — freeze FAILS if any unresolved
  # token is in this list (signals user wants to rewrite mockup, not accept)
  - "#ff0000"
```

## Freeze flow

1. Load draft skeleton from `--draft` (YAML).
2. Apply user edits:
   - For each `interactions[].binds_to: null`, look up the `element_id#event` key in `user_edits.binds_to_assignments`. Missing → error (user must handle every null).
   - For each `unresolved_tokens` entry, look up `value` in `tokens_approved`. If present, add to draft's `tokens` block. If in `tokens_rejected`, fail with exit code 2. If neither — **D2 strict** — fail with exit code 2.
3. Validate every `binds_to: capability://...` URI resolves via `uri.exists(uri, project_root)`. First failure:
   - Call `claims.file_challenge(project_root, skeleton_ref=..., reason="functional_requirement_conflict", details=...)` — auto-emits observation via fail-open `claude_observe`.
   - Exit code 1.
4. Compute:
   - `design_doc_hash` = sha256 of mockup bytes
   - `index_hash` = sha256 of canonical-JSON(index_body excluding `index_hash` + `signature`)
   - Per-screen `skeleton_hash` = sha256 of canonical-JSON(screen_body excluding `signature`)
5. **HMAC-sign** (see "Signature pattern" below).
6. Build YAML text for both files (index.yaml + `<screen>.yaml`).
7. Call `trusted_runner.bundle_write([(out_index, bytes1), (out_screen, bytes2)])` — atomic two-file commit with pre-image rollback.
8. Emit transition request at `.ledger/requests/<request_id>.request.yaml` with `event: skeleton_frozen`, referencing both frozen paths + their hashes.
9. Return structured result.

## Signature pattern (exactly matches S025)

```python
import hashlib, hmac, json

# session.key bytes INCLUDING trailing newline — S024/S025 invariant
key = session_key_path.read_bytes()   # NOT $(cat file)

payload = {
    "skeleton_hash": index_hash,      # for index.yaml, the index_hash
    "skeleton_version": "1.0",
    "design_doc_hash": design_doc_hash,
    "created_at": iso_now,
}
msg = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
digest = hmac.new(key, msg, hashlib.sha256).hexdigest()

signature = {
    "algorithm": "HMAC-SHA256",
    "key_id": ".forge/session.key",
    "signed_fields": ["skeleton_hash", "skeleton_version", "design_doc_hash", "created_at"],
    "signed_at": iso_now,
    "digest": digest,
}
```

The **canonical JSON** (sort_keys=True, compact separators, UTF-8) is identical to `trusted_runner.canonical_bundle_bytes`.

## Hard rules

- **Reads Foundation primitives, never modifies them** — `uri.exists`, `claims.file_challenge`, `trusted_runner.bundle_write`, `claude_observe`.
- **D2 strict token binding** — no silent skip. Every unresolved token requires explicit user approval (adds to tokens block) or explicit rejection (fails freeze).
- **`binds_to` validated via `uri.exists` BEFORE freeze** — rejection via `claims.file_challenge` (with reason `functional_requirement_conflict`); never a half-signed artifact.
- **Atomic two-file commit** — `trusted_runner.bundle_write`; hand-rolled tmp+rename would leak partial state on failure.
- **CB4 preserved** — this skill writes to `.design-ledger/skeletons/*.yaml` (its own output domain) + `.ledger/requests/<uuid>.request.yaml` (transition request bob consumes). It writes NOTHING to `progress/integration-ledger.md` or `.ledger/claims/`.
- **HMAC signature** uses `session.key` file bytes including trailing newline. `.read_bytes()` is required, not shell-captured string.

## Scope boundaries

| In scope | Out of scope |
|---|---|
| Applying user edits to draft | Invoking `skeleton-extractor` (runtime integration only; caller passes draft path) |
| Validating `binds_to` URIs | Validating built-product HTML against skeleton (that's `visual-arbiter`) |
| Emitting transition request | Applying transition request to ledger (bob owns; CB4) |
| Filing challenges for unresolved binds_to | Resolving challenges (`claims.resolve_challenge` — bob owns) |
| Writing frozen skeleton files | Writing `progress/integration-ledger.md` or `.ledger/claims/` (bob owns; CB4) |

## References

- Design doc: §2.2 index schema, §2.3 per-screen schema, §2.5 freeze flow, §5.7 forge Step 2.5 wiring, D2 strict token binding
- Contract map component: `visual-architect` (WP-8, TS-VA-01..03)
- Foundation primitives: `claims.file_challenge` (WP-5), `uri.exists` (WP-1), `trusted_runner.bundle_write` + `atomic_write_bytes` (WP-2), `claude_observe` (WP-3)
- Mirror pattern (conceptually): S027 test-architect Phase 3 (not yet built)
