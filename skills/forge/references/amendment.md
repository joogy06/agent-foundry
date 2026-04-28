# Forge Amendment Mode (S029 §7.3)

This reference describes how forge handles `mode=amendment` invocations from
bob during a contract-scope pause cycle. Forge does NOT enter amendment mode
on its own — bob spawns it after `G_CONTRACT_SCOPE` has flagged a critical
undeclared artifact and the pause-state machine has reached `MAP_UPDATING`.

> **Authority**: USER IS SOLE AUTHORITY for amendments. Forge cannot
> self-approve. Bob cannot self-approve. Forge proposes the amended map
> shape based on user decisions; bob signs/applies/restarts. (Q3b lock.)

---

## 1. Entry signature

Bob spawns forge with:

```
mode: amendment
project_root: <abs path>
contract_map_path: <abs path to current signed contract-map.yaml>
gaps_dir: <abs path to .ledger/scope-deltas/>
pause_epoch: <epoch returned by claims.request_scope_pause>
```

In code, forge loads the helper:

```python
import sys
sys.path.insert(0, str(Path.home() / ".claude/skills/_meta"))
import forge_amendment_helper as fah

undecided = fah.read_undecided_deltas(project_root)
# undecided is a list of scope_delta records, status="undecided".
```

There is NO standalone amendment invocation — running forge in amendment mode
without bob having already established the pause cycle is a protocol error.
Forge SHOULD validate the entry signature: `mode=amendment`, `pause_epoch`
present, `gaps_dir` non-empty, contract-map signature valid (G1).

---

## 2. Amendment dialogue protocol

For each record in `undecided`, forge presents a structured prompt to the user:

```
Scope delta detected
====================
delta_id:        <delta_id>
path:            <project-relative path>
artifact_kind:   <secret|db_migration|env_var|public_api|config_key|generated_artifact|file>
operation:       <added|removed|changed>
severity:        <critical|advisory>
critical_reason: <only if severity=critical>
requesting_wp:   <WP that triggered detection>
detection_point: <wp_boundary|integrated_to_verified>

Context (from contract-map):
  - Closest declared component(s): <component_id>(s) whose source_paths
    are nearest matches by path prefix.
  - Currently in declared universe?  No (would be allowed if Yes)
  - Match against critical globs?    <yes|no>

Your decision:
  [a] Amend — add this path to a component's source_paths
  [e] Exclude — add this path to top-level excluded_paths (legitimate non-tracked)
  [d] Defer — leave undecided (forge SHOULD escalate or HALT)
  [r] Reject — forge will NOT propose any amendment for this delta;
              bob's pause cycle will time out → ROLLBACK
```

If the user picks `[a]` (amend), forge asks:

```
Which component should own this path?
  [1] <component_id_1>  (purpose: ...)
  [2] <component_id_2>  (purpose: ...)
  ...
  [n] (declare a NEW component — escalate to a fresh forge cycle; not v1)

Target field: source_paths (only field supported in v1)
```

If the user picks `[e]` (exclude), forge asks for a brief reason (free text;
goes into the ledger event note). Forge SHOULD warn if the proposed
`excluded_paths` glob would mask anything matching `CONTRACT_SCOPE_CRITICAL_GLOBS`
— per design §7.2 M4 the gate's critical-wins precedence still applies, but the
warning helps the user catch over-broad excludes.

If the user picks `[d]` (defer): forge MUST NOT mark the delta resolved.
Forge SHOULD escalate to bob ("user deferred N deltas; pause cycle will
time out unless re-engaged before MAP_UPDATING expires").

Forge MAY batch multiple deltas in one `decisions` list; the user reviews
all outstanding undecided deltas in one pass and submits a single decision
list. The helper applies them in order.

---

## 3. Drafting the amended map (helper call)

Once forge has the user's decisions, it calls the helper:

```python
amended_yaml = fah.draft_amendment(contract_map_path, decisions)
```

`decisions` is a list of:

```python
{
    "delta_id": "scope-delta-...",
    "kind": "amend" | "exclude",
    "path": "<project-rel>",
    # When kind == "amend":
    "target_component": "<component-id>",  # kebab-case, matches component.id
    "target_field": "source_paths"          # default; v1 only supports source_paths
}
```

`draft_amendment` is a **pure function**:
  - Bumps `revision` (rev_N → rev_N+1).
  - Appends amended paths to the chosen component's `source_paths` (deduped).
  - Appends excluded paths to top-level `excluded_paths` (deduped).
  - Performs **no** filesystem writes, **no** ledger writes, **no** signing.
  - Same input → same output (deterministic, restart-safe).

Forge writes `amended_yaml` to a stable path (recommended:
`<project_root>/.forge/amendment-rev-<N>.yaml.proposal`) — this is the *proposal*
file. Bob will read this, run G2, sign, and only then commit the change to
`progress/contract-map.yaml`. **Forge never overwrites the production map.**

---

## 4. Output contract — what forge returns to bob

```python
result = fah.return_to_bob(amended_path, deltas_resolved)
# result == {
#   "amended_map_path": "<abs path to .forge/amendment-rev-N.yaml.proposal>",
#   "deltas_resolved": ["scope-delta-...", "scope-delta-...", ...]
# }
```

Forge prints/returns this dict. Bob's Step 8.7 reads it, runs G2 against the
amended path, signs (HMAC re-sign per existing forge Step 8a.2 pattern),
writes `.ledger/deltas/rev-<N>.yaml`, and only then calls
`scope_delta.update_status(delta_id, "amended", resolution=f"rev-{N}")` for
each resolved delta.

Forge MUST NOT:

- Write to `progress/contract-map.yaml` directly (bob signs and commits).
- Compute the HMAC signature, touch `.forge/session.key`, or modify
  `progress/contract-map.yaml.sig`.
- Call `scope_delta.update_status` (bob's hand-off step at 8.7).
- Call `pause_state.transition_to`, `pause_state.request_pause`, or any
  other pause-state mutator (CB4 — only `scope_reaction.handle` may call
  `pause_state.request_pause`; bob orchestrates other transitions).
- Write `.ledger/deltas/rev-<N>.yaml` directly (bob's responsibility).

---

## 5. Worked example — SQL-table-D delta

```
G_CONTRACT_SCOPE (in bob's WP-3 boundary check) writes:
    .ledger/scope-deltas/scope-delta-2026-04-26T07:14:02Z-3a1f8c.yaml
    {
      artifact_kind: db_migration,
      path: "migrations/004-table-d.sql",
      severity: critical,
      critical_reason: "matches CONTRACT_SCOPE_CRITICAL_GLOBS db_migration glob",
      requesting_wp: "WP-3",
      detection_point: "wp_boundary",
      status: "undecided",
    }

bob: claims.request_scope_pause(project_root) -> {epoch: 1, ...}
bob: pause_state ... -> MAP_UPDATING
bob: spawns forge in amendment mode

forge presents:
  delta scope-delta-...-3a1f8c
    path: migrations/004-table-d.sql  (kind=db_migration, CRITICAL)
    Closest declared components: schema-bootstrap, init-pipeline
    Decision? [a/e/d/r]: a
    Which component? [1] schema-bootstrap [2] init-pipeline: 1

user submits.

forge: decisions = [
  {delta_id: "scope-delta-...-3a1f8c",
   kind: "amend",
   path: "migrations/004-table-d.sql",
   target_component: "schema-bootstrap",
   target_field: "source_paths"}
]
forge: amended = fah.draft_amendment(map_path, decisions)
       # rev becomes 2; schema-bootstrap.source_paths now contains
       # "migrations/004-table-d.sql"
forge writes amended to .forge/amendment-rev-2.yaml.proposal
forge: result = fah.return_to_bob(<proposal>, ["scope-delta-...-3a1f8c"])
forge returns result to bob.

bob: runs check_G2(<proposal>, project_root) -> passes
bob: signs (HMAC) -> writes progress/contract-map.yaml + .sig (rev 2)
bob: writes .ledger/deltas/rev-2.yaml
bob: scope_delta.update_status("scope-delta-...-3a1f8c", "amended", "rev-2")
bob: pause_state.transition_to(RESUMING)
bob: affected_wps = [WP-3] -> force-restart at PLANNED, gen+1
bob: pause_state.transition_to(NORMAL)
WP-3 re-runs against the amended map; G_CONTRACT_SCOPE returns 0; INTEGRATED.
```

---

## 6. HARD-RULEs for forge in amendment mode (summary)

1. **No self-approval.** Every `kind: amend|exclude` decision MUST come from
   user input. If forge receives no user input or an empty `decisions` list,
   it returns to bob with `deltas_resolved=[]` (no progress, pause cycle
   times out → bob escalates).
2. **No signing.** Forge does not import `hmac`, does not read
   `.forge/session.key`, does not modify `progress/contract-map.yaml.sig`.
3. **No ledger writes.** Forge does not write to `progress/integration-ledger.md`,
   `.ledger/claims/`, `.ledger/deltas/`, or any subdirectory under `.ledger/`.
4. **No status mutation.** Forge does not call `scope_delta.update_status`.
   That is bob's Step 8.7 hand-off.
5. **No pause-state mutation.** Forge does not import `pause_state` or call
   any of its mutators (request_pause, transition_to, acknowledge_pause,
   clear_pause_state). CB4 invariant.
6. **No direct map overwrite.** Forge writes the proposal to a separate path
   (`.forge/amendment-rev-<N>.yaml.proposal`). Bob is the sole writer of
   `progress/contract-map.yaml`.
7. **G2 deferred to bob.** Forge MAY run G2 as a sanity check before
   returning, but bob runs G2 again on receipt — the helper's `draft_amendment`
   itself does not call G2.

These boundaries are enforced by `tests/test_amendment.py` static-scan
checks (AST-based: forbid `update_status` calls, forbid `hmac` imports,
forbid `pause_state.*` references, forbid `.ledger/` string literals).

---

## 7. Cross-references

- Helper: `~/.claude/skills/_meta/forge_amendment_helper.py` (CONTRACT-C1).
- Schema: `~/.claude/skills/_meta/schemas/scope_delta.v1.json`.
- Reader/writer: `~/.claude/skills/_meta/scope_delta.py` (CONTRACT-A2).
- Bob orchestration: `~/.claude/agents/bob.md` HARD-RULE 6, Step 4.6, Step 8.7.
- Pause-state machine: `~/.claude/skills/_meta/pause_state.py` (CONTRACT-A0).
- Reaction (only legal pause-state caller): `~/.claude/skills/_meta/scope_reaction.py` (CONTRACT-B2).
- Design doc: `docs/plans/2026-04-26-contract-scope-enforcement-keystone-design.md` §7.3.
