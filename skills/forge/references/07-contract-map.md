# Forge reference — contract map

Checklist step 8a — previous: step 8, write design doc; next: step 8b, spec review.
When this file is read, return to the SKILL.md checklist.

## Contents

- Step 8a.0: Emit + corroborate the classification artifact
- Step 8a.1+: Build the signed contract map (component cycles only)
- Step 8a.1: Invoke component-contract-mapping
- Step 8a.2: Emit session material and sign
- Step 8a.3: Verify signature
- Step 8a.3b: Re-pin the retro-scan baseline (mandatory after any map write)
- Step 8a.4: Stage for bob

## Contract Map Generation (Step 8a)

### Step 8a.0: Emit + corroborate the classification artifact (S042 / #115)

The per-cycle astra budget key is `.forge/cycle-id`, written fresh at Step 1 (Step 6B); `.forge/session-id` is the contract-signing id, minted only by Step 8a.2's idempotent line and never re-minted, so this step mints no id.

BEFORE deciding whether to build a map, forge MUST write `.forge/classification.json` (schema `contract-classification.v1`) — the recorded classification that travels with the cycle, analogous to the signed contract map. This closes the bare-`Contract map: N/A` hole at the producer side (not just bob's front door).

The artifact states:
- `introduces_components`: `"yes" | "no"`
- `reason_code`: a value from the **closed enum** {`skill_text`, `doc_only`, `direct_bugfix`, `refactor`, `self_contained_meta_helper`, `sidecar_telemetry`, `agent_text`, `existing_component_extension`} — NOT free-text (free-text reasons are a loophole).
- `design_doc`, `planned_globs`, `evidence` (confirmed_positives / negatives / prose_only).

Forge may hand-write it, or derive a default via the helper:
```bash
python3 ~/.claude/skills/_meta/classify_emit.py "<project_root>" \
  --design-doc "<design-doc-path>" --classified-by forge_design \
  --files-from "<planned-file-touch-list>"
```

Then forge **locally runs `G_CLASSIFY` to fail-fast at design time** (catch a misclassification before bob is ever spawned):
```bash
python3 ~/.claude/skills/_meta/gates.py G_CLASSIFY "<project_root>" \
  --design-doc "<design-doc-path>" \
  --asserted "<N/A if introduces_components==no, else provided>" \
  --files-from "<planned-file-touch-list>"
```
- Exit 0 → classification corroborated; proceed.
- Exit 2 → the scan contradicts the artifact (named signals). Fix the design/classification before continuing; do NOT hand bob a false N/A.
- Exit 3 → ambiguous; resolve with the user before spawning bob.

The artifact is a CLAIM the gate re-derives and corroborates — never trusted (the threat model includes a buggy/drifting producer). `existing_component_extension` makes the Ship-of-Theseus case (appending component logic into existing allowed files) a *declarable, checkable* category rather than a silent dodge.

### Step 8a.1+: Build the signed contract map (component cycles only)

When a design introduces components (new services, modules, APIs, integration points), forge MUST produce a signed contract map BEFORE invoking the spec review (Step 8b) and before spawning bob.

Pure refactors, bugfixes, and single-file changes with no new components are exempt.

### Step 8a.1: Invoke component-contract-mapping

Invoke the `component-contract-mapping` skill with:

1. The draft design doc path
2. Relevant PROJECT.md and COMPONENT.md paths
3. The user's spoken intent from design dialogue

The skill will:
1. Extract components from the design discussion
2. Define types dictionary with semantic_type per field (from the v1 18-type registry)
3. Write `progress/contract-map.yaml` (single writer — only ever written here)
4. Run G2 validation locally by invoking `python -m gates G2 progress/contract-map.yaml`
5. Auto-render a markdown table into the design doc
6. Request forge to sign the map

If G2 validation fails, fix the design doc (not the YAML — the skill rewrites it from the design doc). Re-invoke the skill. Bob will refuse to execute without a valid signed contract map.

### Step 8a.2: Emit session material and sign

Forge is responsible for the session material and the signing payload.

```bash
# Create session material once per forge session (idempotent)
mkdir -p .forge
[[ -f .forge/session-id ]] || uuidgen > .forge/session-id
[[ -f .forge/session.key ]] || ( umask 077; openssl rand -hex 32 > .forge/session.key )  # umask 077: created 0600, no readable window

# Read current state
MAP_HASH=$(sha256sum progress/contract-map.yaml | awk '{print $1}')
MAP_REVISION=$(yq eval '.revision' progress/contract-map.yaml)
SESSION_ID=$(cat .forge/session-id)
SIGNED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Build the signed payload per spec section 7.4 — full payload including session_id
PAYLOAD=$(jq -cn --arg h "$MAP_HASH" --arg r "$MAP_REVISION" --arg s "$SESSION_ID" --arg t "$SIGNED_AT" \
  '{map_hash: $h, map_revision: ($r | tonumber), forge_session_id: $s, signed_at: $t}')

# Canonical JSON (sort keys, no whitespace) — must match gates.py canonical_json() bit-for-bit
CANONICAL=$(printf '%s' "$PAYLOAD" | jq -cS .)

# Compute HMAC-SHA256 using the session key file content (ALL BYTES, including the
# trailing newline from `openssl rand -hex 32 > file`) as the key.
#
# gates.py reads the key via pathlib.Path.read_bytes() which returns 65 bytes
# (64 hex chars + newline). Shell command substitution `$(cat file)` strips trailing
# newlines and produces a 64-byte key — mismatches gates.py. This produced a G1
# signature-mismatch on every forge-signed contract map before 2026-04-19; see
# foundry-lab/docs/reviews/2026-04-19-product-merger-codex-spec-review.md (tasks.md #85).
#
# Mirrors _meta/gates.sh §HMAC verification (Python oracle preferred; bash fallback uses
# xxd round-trip + openssl -macopt hexkey: to preserve the trailing newline byte).
if command -v python3 >/dev/null 2>&1; then
  SIG=$(printf '%s' "$CANONICAL" | python3 -c "
import hmac, hashlib, sys, pathlib
key = pathlib.Path('.forge/session.key').read_bytes()
msg = sys.stdin.buffer.read()
print(hmac.new(key, msg, hashlib.sha256).hexdigest())
")
else
  KEY_HEX=$(xxd -p -c 0 .forge/session.key)
  SIG=$(printf '%s' "$CANONICAL" | \
    openssl dgst -sha256 -mac HMAC -macopt "hexkey:$KEY_HEX" -binary | \
    xxd -p -c 256 | tr -d '\n')
fi

# Write the signature file — contains both payload and signature
jq -cn --argjson p "$PAYLOAD" --arg s "$SIG" '{payload: $p, signature: $s}' > progress/contract-map.yaml.sig
```

### Step 8a.3: Verify signature

Run G1 locally (with `--no-ledger-binding`, since bob has not yet initialized the ledger):

```bash
python3 ~/.claude/skills/_meta/gates.py G1 "$(pwd)" --no-ledger-binding
# exit 0 = signature valid, safe to hand off to bob
# exit 2 = G1_FAIL — fix and re-sign
```

If G1 fails, re-run Step 8a.2 after fixing the underlying issue (most common: the skill re-wrote the YAML without updating the signature; re-sign).

### Step 8a.3b: Re-pin the retro-scan baseline (MANDATORY after any map write)

**Run this immediately after signing a NEW map, and again after every AMENDMENT.**

```bash
python3 ~/.claude/skills/retro-scan-s028/scripts/scan.py "$(pwd)"
# rewrites progress/retro-scan-S028.yaml, re-pinned to the new contract_map_hash
```

**Why this is not optional.** `progress/retro-scan-S028.yaml` records
`contract_map_hash`. `G_CONTRACT_SCOPE` compares that stored hash against the
live map and, on a mismatch, **silently declines to consult the baseline at all**
(warning to stderr only — see `gates.py` §7.5 safety notes). No baseline means no
grandfathering, so every pre-existing path the baseline was holding down re-emits
as a **fresh critical undeclared**, `critical_undecided` jumps from 0 to dozens,
and the cycle freezes in `AWAITING_AMENDMENT` — pointing at paths that were
already known and already accepted.

The failure is doubly nasty because it is **delayed and misattributed**: signing
succeeds, G1 passes, and the breakage only surfaces later at a WP boundary, where
it reads as "the implementation introduced scope creep" rather than "the baseline
went stale." **S033 and S069 each lost a full pause cycle to exactly this.**

Verify the re-pin before handing off:

```bash
grep contract_map_hash progress/retro-scan-S028.yaml    # must equal the live map's hash
```

Keep the superseded baseline alongside the new one (`progress/retro-scan-S028.yaml.pre-<cycle>-amend`)
so a bad re-pin can be diffed rather than guessed at.

### Step 8a.4: Stage for bob

At this point the workspace contains:
- `progress/contract-map.yaml` (frozen — never edited after this)
- `progress/contract-map.yaml.sig` (full signed payload)
- `progress/retro-scan-S028.yaml` (re-pinned to the map hash — Step 8a.3b)
- `.forge/session-id` (UUID, inherited by bob)
- `.forge/session.key` (0600, inherited by bob)

Proceed to Step 8b (spec review).
