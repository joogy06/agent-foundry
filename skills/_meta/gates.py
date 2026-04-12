#!/usr/bin/env python3
"""
gates.py — Subprocess-based gate enforcement for the contract-driven testing pipeline.

Implements G1 (contract map exists, signed, bound to ledger),
G2 (schema validation V1-V15 + semantic type registry + technical closed list),
G3 (bob-owned leased claim verification — delegates to claims.py).

Exit codes:
    0 = pass
    2 = fail (gate violation)
    3 = environmental error (file missing, parse error not attributable to a violation)

Usage:
    python -m gates G1 <design_dir> [--no-ledger-binding]
    python -m gates G2 <contract-map-path> [--project-root <dir>]
    python -m gates G3 <wp_id> <invoking_skill> [--project-root <dir>]

This module is invoked from bash via:
    python3 ~/.claude/skills/_meta/gates.py G1 .

Provenance: spec section 8 (gate enforcement subsystem).
Critical invariants enforced: CB1 (per-component generations), CB2 (G1 binds map to ledger).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed. gates.py requires pyyaml.\n")
    sys.exit(3)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION_SUPPORTED = "1.0.0"

# v1 semantic type registry — frozen at exactly 18 types per spec section 7.3.1
V1_SEMANTIC_TYPES = frozenset({
    # Identity (3)
    "user_id", "session_token", "api_key",
    # Contact (4)
    "email", "phone_e164", "address_line", "country_iso2",
    # Personal (4)
    "full_name", "first_name", "last_name", "date_of_birth",
    # Temporal (3)
    "iso_8601_datetime", "iso_8601_date", "unix_timestamp",
    # Financial (3)
    "currency_amount", "currency_iso4217", "iban",
    # Web (1)
    "url_http",
})
assert len(V1_SEMANTIC_TYPES) == 18, "v1 registry frozen at 18 types"

# Closed list for `semantic_type: technical` per spec section 7.3 V13 definition
TECHNICAL_CLOSED_LIST = frozenset({
    "id", "revision", "event_id", "_meta", "hash", "checksum",
    "version", "created_at", "updated_at", "deleted_at",
    "generation", "schema_version", "internal_ref",
})

KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def fail(gate: str, message: str) -> None:
    """Exit 2 with a structured failure message."""
    sys.stderr.write(f"{gate}_FAIL: {message}\n")
    sys.exit(2)


def env_error(message: str) -> None:
    """Exit 3 for environmental issues that aren't gate violations."""
    sys.stderr.write(f"ENV_ERROR: {message}\n")
    sys.exit(3)


def ok(gate: str, message: str = "") -> None:
    """Exit 0 with a structured pass message."""
    sys.stdout.write(f"{gate}_PASS: {message}\n")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Canonical JSON serialization (must match the signing side bit-for-bit)
# ---------------------------------------------------------------------------


def canonical_json(obj: Any) -> str:
    """Sort keys, no whitespace — same on both signing and verification sides."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Project-local semantic-type override loader
# ---------------------------------------------------------------------------


def load_semantic_type_registry(project_root: Path) -> set[str]:
    """Load v1 base + project-local override at .contract/semantic-types.yaml."""
    registry = set(V1_SEMANTIC_TYPES)
    override_path = project_root / ".contract" / "semantic-types.yaml"
    if override_path.is_file():
        try:
            data = yaml.safe_load(override_path.read_text()) or {}
            local_types = data.get("semantic_types", {})
            if isinstance(local_types, dict):
                for type_name in local_types.keys():
                    registry.add(type_name)
        except (yaml.YAMLError, OSError) as e:
            env_error(f"failed to load project-local semantic types: {e}")
    return registry


# ---------------------------------------------------------------------------
# Ledger reader (minimal — only the header and projection table fields gates need)
# ---------------------------------------------------------------------------


class LedgerHeader:
    """Minimal ledger header projection used by G1's binding check."""
    def __init__(self, raw: Dict[str, Any]) -> None:
        self.contract_map_hash: Optional[str] = raw.get("contract_map_hash")
        self.contract_map_revision: Optional[int] = raw.get("contract_map_revision")
        self.forge_session_id: Optional[str] = raw.get("forge_session_id")
        self.pause_epoch: int = raw.get("pause_epoch", 0)
        self.consumed_request_ids: List[str] = raw.get("consumed_request_ids", []) or []


def read_ledger_header(ledger_path: Path) -> LedgerHeader:
    """Parse just the YAML frontmatter from progress/integration-ledger.md."""
    if not ledger_path.is_file():
        env_error(f"ledger not found at {ledger_path}")
    text = ledger_path.read_text()
    if not text.startswith("---"):
        env_error(f"ledger {ledger_path} missing YAML frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        env_error(f"ledger {ledger_path} frontmatter not closed")
    fm = text[4:end].strip()
    try:
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError as e:
        env_error(f"ledger frontmatter unparseable: {e}")
    return LedgerHeader(data)


# ---------------------------------------------------------------------------
# G1 — contract map exists, signed, AND bound to the ledger
# ---------------------------------------------------------------------------


def check_G1(design_dir: Path, expect_ledger_binding: bool = True) -> Dict[str, Any]:
    """G1 implementation per spec section 8.2.

    Verifies four things, not just signature validity:
      1. contract-map.yaml + .sig + session.key + session-id all exist
      2. signed payload self-consistency (hash, revision, session_id all match yaml)
      3. HMAC verification using forge session key
      4. If expect_ledger_binding: payload's hash + revision match ledger header
         (CB2 fix — closes stale-map replay hole)

    Returns the parsed contract map yaml on success; calls fail() on violation.
    """
    map_path = design_dir / "progress" / "contract-map.yaml"
    sig_path = design_dir / "progress" / "contract-map.yaml.sig"
    key_path = design_dir / ".forge" / "session.key"
    session_id_path = design_dir / ".forge" / "session-id"

    for p, name in [
        (map_path, "contract-map.yaml"),
        (sig_path, "contract-map.yaml.sig"),
        (key_path, "session.key"),
        (session_id_path, "session-id"),
    ]:
        if not p.is_file():
            fail("G1", f"{name} missing at {p}")

    # Permissions check on session.key — 0600 required
    key_stat = key_path.stat()
    if key_stat.st_mode & 0o077:
        fail("G1", f"session.key permissions unsafe ({oct(key_stat.st_mode & 0o777)}), must be 0600")

    key = key_path.read_bytes()
    current_session_id = session_id_path.read_text().strip()

    map_content = map_path.read_bytes()
    map_hash = hashlib.sha256(map_content).hexdigest()

    try:
        map_yaml = yaml.safe_load(map_content)
    except yaml.YAMLError as e:
        fail("G1", f"contract-map.yaml unparseable: {e}")

    if not isinstance(map_yaml, dict):
        fail("G1", "contract-map.yaml is not a mapping")

    map_revision = map_yaml.get("revision")
    if not isinstance(map_revision, int) or map_revision < 1:
        fail("G1", f"map revision missing or invalid: {map_revision!r}")

    try:
        sig_data = json.loads(sig_path.read_text())
    except json.JSONDecodeError as e:
        fail("G1", f"signature file is not valid JSON: {e}")

    if not isinstance(sig_data, dict) or "payload" not in sig_data or "signature" not in sig_data:
        fail("G1", "signature file missing 'payload' or 'signature'")

    payload = sig_data["payload"]
    provided_sig = sig_data["signature"]

    # 1. Payload self-consistency
    if not isinstance(payload, dict):
        fail("G1", "signature payload is not a mapping")
    if payload.get("map_hash") != map_hash:
        fail("G1", "payload map_hash does not match current YAML — tamper evident")
    if payload.get("map_revision") != map_revision:
        fail("G1", "payload map_revision does not match current YAML")
    if payload.get("forge_session_id") != current_session_id:
        fail("G1", "session id mismatch — signed map is from a different forge session (replay)")

    # 2. Signature validity (HMAC-SHA256)
    expected_sig = hmac.new(
        key, canonical_json(payload).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_sig, provided_sig):
        fail("G1", "signature mismatch — tamper evident")

    # 3. Ledger binding (CB2 — the critical new check)
    if expect_ledger_binding:
        ledger_path = design_dir / "progress" / "integration-ledger.md"
        if not ledger_path.is_file():
            fail("G1", f"ledger not found at {ledger_path} (binding required)")
        header = read_ledger_header(ledger_path)
        if header.contract_map_hash != map_hash:
            fail(
                "G1",
                f"ledger-pinned hash ({(header.contract_map_hash or 'None')[:12]}) "
                f"does not match current map ({map_hash[:12]}) — stale map replay"
            )
        if header.contract_map_revision != map_revision:
            fail(
                "G1",
                f"ledger-pinned revision ({header.contract_map_revision}) "
                f"does not match current map ({map_revision}) — rollback detected"
            )

    return map_yaml


# ---------------------------------------------------------------------------
# G2 — schema validation V1-V15 + registry + closed list
# ---------------------------------------------------------------------------


def _v1_schema_version(map_yaml: Dict[str, Any]) -> None:
    sv = map_yaml.get("schema_version")
    if not isinstance(sv, str) or not sv:
        fail("G2", "V1: schema_version missing")
    if sv != SCHEMA_VERSION_SUPPORTED:
        fail("G2", f"V1: unsupported schema_version {sv!r} (supported: {SCHEMA_VERSION_SUPPORTED})")


def _v2_revision(map_yaml: Dict[str, Any]) -> None:
    rev = map_yaml.get("revision")
    if not isinstance(rev, int) or rev < 1:
        fail("G2", f"V2: revision must be a positive integer, got {rev!r}")


def _v3_unique_kebab_ids(components: List[Dict[str, Any]]) -> None:
    seen = set()
    for c in components:
        cid = c.get("id")
        if not isinstance(cid, str):
            fail("G2", f"V3: component missing id: {c}")
        if not KEBAB_CASE_RE.match(cid):
            fail("G2", f"V3: component id {cid!r} not kebab-case")
        if cid in seen:
            fail("G2", f"V3: duplicate component id {cid!r}")
        seen.add(cid)


REQUIRED_COMPONENT_FIELDS = {
    "id", "purpose", "owner_wp", "source_paths",
    "test_paths", "fixtures_path", "inputs", "outputs",
    "callers", "callees", "success_criteria", "test_scenarios",
}


def _v4_required_fields(components: List[Dict[str, Any]]) -> None:
    for c in components:
        missing = REQUIRED_COMPONENT_FIELDS - set(c.keys())
        if missing:
            fail("G2", f"V4: component {c.get('id', '?')!r} missing required fields: {sorted(missing)}")


def _v5_v6_callers_callees(components: List[Dict[str, Any]]) -> None:
    by_id = {c["id"]: c for c in components}
    for c in components:
        cid = c["id"]
        for callee in c.get("callees") or []:
            if callee not in by_id:
                fail("G2", f"V5: component {cid!r} declares callee {callee!r} which is not a component")
            # V6: bidirectional consistency
            if cid not in (by_id[callee].get("callers") or []):
                fail("G2", f"V6: component {cid!r} -> {callee!r} not bidirectional (callee missing caller)")
        for caller in c.get("callers") or []:
            if caller not in by_id:
                fail("G2", f"V5: component {cid!r} declares caller {caller!r} which is not a component")
            if cid not in (by_id[caller].get("callees") or []):
                fail("G2", f"V6: component {cid!r} <- {caller!r} not bidirectional (caller missing callee)")


def _walk_refs(node: Any, type_names: set, path: str = "") -> None:
    """Recursively check all $ref usages resolve to a declared type."""
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"]
            if ref not in type_names:
                fail("G2", f"V7: $ref {ref!r} at {path} does not resolve to a declared type")
        for k, v in node.items():
            _walk_refs(v, type_names, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_refs(v, type_names, f"{path}[{i}]")


def _v7_refs(map_yaml: Dict[str, Any]) -> None:
    types = map_yaml.get("types") or {}
    if not isinstance(types, dict):
        fail("G2", "V7: types section is not a mapping")
    type_names = set(types.keys())
    components = map_yaml.get("components") or []
    _walk_refs(components, type_names, "components")


def _v8_fixture_refs(components: List[Dict[str, Any]]) -> None:
    for c in components:
        input_names = {i.get("name") for i in (c.get("inputs") or []) if isinstance(i, dict)}
        for ts in c.get("test_scenarios") or []:
            for fr in ts.get("fixture_refs") or []:
                # fixture_refs may be like "session_token[0]" — strip index
                base = fr.split("[")[0]
                if base not in input_names:
                    fail(
                        "G2",
                        f"V8: component {c['id']!r} test_scenario {ts.get('id')!r} "
                        f"fixture_ref {fr!r} does not point to a declared input"
                    )


def _v9_v10_flow_markers(components: List[Dict[str, Any]]) -> None:
    has_entry = any(c.get("flow_entry_point") for c in components)
    has_terminal = any(c.get("flow_terminal") for c in components)
    if not has_entry:
        fail("G2", "V9: no component has flow_entry_point: true")
    if not has_terminal:
        fail("G2", "V10: no component has flow_terminal: true")


def _tarjan_scc(graph: Dict[str, List[str]]) -> List[List[str]]:
    """Tarjan's strongly-connected components algorithm."""
    index_counter = [0]
    stack: List[str] = []
    on_stack: Dict[str, bool] = {}
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    sccs: List[List[str]] = []

    def strongconnect(v: str) -> None:
        indices[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True
        for w in graph.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif on_stack.get(w, False):
                lowlinks[v] = min(lowlinks[v], indices[w])
        if lowlinks[v] == indices[v]:
            component: List[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                component.append(w)
                if w == v:
                    break
            sccs.append(component)

    for v in list(graph.keys()):
        if v not in indices:
            strongconnect(v)
    return sccs


def _v11_acyclic_or_declared(components: List[Dict[str, Any]]) -> None:
    graph = {c["id"]: list(c.get("callees") or []) for c in components}
    cycle_groups = {c["id"]: c.get("cycle_group") for c in components}
    sccs = _tarjan_scc(graph)
    for scc in sccs:
        if len(scc) <= 1:
            # singleton — check it isn't a self-loop
            v = scc[0]
            if v in graph.get(v, []):
                # self-loop counts as a cycle
                if not cycle_groups.get(v):
                    fail("G2", f"V11: self-loop on {v!r} not declared via cycle_group")
            continue
        # Multi-node SCC — every member must declare the same cycle_group
        groups = {cycle_groups.get(v) for v in scc}
        if None in groups or len(groups) > 1:
            fail(
                "G2",
                f"V11: cycle detected among {sorted(scc)} — must all declare the same cycle_group"
            )


def _v12_test_scenarios(components: List[Dict[str, Any]]) -> None:
    for c in components:
        ts = c.get("test_scenarios")
        if not isinstance(ts, list) or len(ts) == 0:
            fail("G2", f"V12: component {c['id']!r} has no test_scenarios")


def _v13_semantic_types(components: List[Dict[str, Any]], registry: set[str]) -> None:
    """V13 (M4 fix + SC2 fix): every input field needs a semantic_type from the registry,
    or `semantic_type: technical: <value from closed list>`, or `kind: opaque` with reason.
    """
    for c in components:
        for inp in c.get("inputs") or []:
            if not isinstance(inp, dict):
                fail("G2", f"V13: component {c['id']!r} has malformed input: {inp}")
            kind = inp.get("kind")
            if kind == "opaque":
                # Opaque escape hatch — needs reason + fixture_source
                if not inp.get("opaque_reason"):
                    fail("G2", f"V13: opaque input {inp.get('name')!r} in {c['id']!r} missing opaque_reason")
                if not inp.get("opaque_fixture_source"):
                    fail("G2", f"V13: opaque input {inp.get('name')!r} in {c['id']!r} missing opaque_fixture_source")
                continue
            st = inp.get("semantic_type")
            if st is None:
                fail(
                    "G2",
                    f"V13: input {inp.get('name')!r} in {c['id']!r} missing semantic_type "
                    f"(use registry value, technical, or kind: opaque)"
                )
            # `semantic_type: technical` is a sentinel; the actual technical kind goes in `technical`
            if st == "technical":
                tech = inp.get("technical")
                if tech not in TECHNICAL_CLOSED_LIST:
                    fail(
                        "G2",
                        f"V13: input {inp.get('name')!r} in {c['id']!r} declares technical "
                        f"but technical={tech!r} is not in the closed list "
                        f"({sorted(TECHNICAL_CLOSED_LIST)})"
                    )
                continue
            if st not in registry:
                fail(
                    "G2",
                    f"V13: input {inp.get('name')!r} in {c['id']!r} has unknown semantic_type "
                    f"{st!r} (not in v1 registry or project-local override)"
                )


def _v14_v15_flows(map_yaml: Dict[str, Any], components: List[Dict[str, Any]]) -> None:
    flows = map_yaml.get("flows") or []
    component_ids = {c["id"] for c in components}
    for flow in flows:
        path = flow.get("path") or []
        for elem in path:
            if elem not in component_ids:
                fail("G2", f"V14: flow {flow.get('id')!r} path element {elem!r} not a component")
    budget = (map_yaml.get("flow_budget") or {}).get("max_flows")
    if isinstance(budget, int) and len(flows) > budget:
        fail("G2", f"V15: total flows ({len(flows)}) exceed budget ({budget})")


def check_G2(map_path: Path, project_root: Path) -> Dict[str, Any]:
    """Run all V1-V15 schema rules. On first failure, exit 2."""
    if not map_path.is_file():
        fail("G2", f"contract map not found at {map_path}")
    try:
        map_yaml = yaml.safe_load(map_path.read_text())
    except yaml.YAMLError as e:
        fail("G2", f"contract-map.yaml unparseable: {e}")
    if not isinstance(map_yaml, dict):
        fail("G2", "contract-map.yaml is not a mapping")

    components = map_yaml.get("components") or []
    if not isinstance(components, list) or not components:
        fail("G2", "components must be a non-empty list")

    registry = load_semantic_type_registry(project_root)

    _v1_schema_version(map_yaml)
    _v2_revision(map_yaml)
    _v3_unique_kebab_ids(components)
    _v4_required_fields(components)
    _v5_v6_callers_callees(components)
    _v7_refs(map_yaml)
    _v8_fixture_refs(components)
    _v9_v10_flow_markers(components)
    _v11_acyclic_or_declared(components)
    _v12_test_scenarios(components)
    _v13_semantic_types(components, registry)
    _v14_v15_flows(map_yaml, components)

    return map_yaml


# ---------------------------------------------------------------------------
# G3 — bob-owned leased claim verification
# ---------------------------------------------------------------------------


def check_G3(wp_id: str, invoking_skill: str, project_root: Path) -> None:
    """G3 verification per spec section 8.4 — delegates to claims.py.

    G3 is satisfied when bob has issued a non-stale, non-expired claim for this
    WP+skill combination. Skills NEVER write claim files; bob is the sole writer.
    This check verifies that a claim file exists in .ledger/claims/ matching the
    WP+skill, that its lease is still valid, and that its pinned per-component
    generations still match the current ledger state.
    """
    # Lazy import to avoid circular dependency
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        import claims as claims_mod  # type: ignore
    except ImportError as e:
        env_error(f"claims.py not importable: {e}")

    claims_dir = project_root / ".ledger" / "claims"
    if not claims_dir.is_dir():
        fail("G3", f"no claims directory at {claims_dir} (bob has not issued claims)")

    ledger_path = project_root / "progress" / "integration-ledger.md"
    if not ledger_path.is_file():
        fail("G3", f"ledger not found at {ledger_path}")

    matching = claims_mod.find_active_claims_for_wp(claims_dir, wp_id, invoking_skill)
    if not matching:
        fail("G3", f"no active claim for WP={wp_id!r} skill={invoking_skill!r}")
    if len(matching) > 1:
        fail("G3", f"multiple active claims for WP={wp_id!r} (concurrency violation)")
    claim = matching[0]
    state = claims_mod.classify_claim(claim, ledger_path)
    if state != "ok":
        fail("G3", f"claim {claim.get('claim_uuid', '?')} is {state}, must be 'ok'")


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------


def _parse_args(argv: List[str]) -> Tuple[str, List[str], Dict[str, str]]:
    if len(argv) < 2:
        env_error("usage: gates.py G1|G2|G3 ...")
    gate = argv[1]
    positional: List[str] = []
    flags: Dict[str, str] = {}
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--no-ledger-binding":
            flags["no_ledger_binding"] = "1"
            i += 1
            continue
        if a == "--project-root":
            if i + 1 >= len(argv):
                env_error("--project-root requires a value")
            flags["project_root"] = argv[i + 1]
            i += 2
            continue
        positional.append(a)
        i += 1
    return gate, positional, flags


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    gate, positional, flags = _parse_args(argv)

    if gate == "G1":
        if len(positional) < 1:
            env_error("G1 requires <design_dir>")
        design_dir = Path(positional[0]).resolve()
        expect_binding = "no_ledger_binding" not in flags
        check_G1(design_dir, expect_ledger_binding=expect_binding)
        ok("G1", f"contract map verified at {design_dir} (binding={expect_binding})")
    elif gate == "G2":
        if len(positional) < 1:
            env_error("G2 requires <contract-map-path>")
        map_path = Path(positional[0]).resolve()
        project_root = Path(flags.get("project_root", str(map_path.parent.parent))).resolve()
        check_G2(map_path, project_root)
        ok("G2", f"schema validation passed for {map_path}")
    elif gate == "G3":
        if len(positional) < 2:
            env_error("G3 requires <wp_id> <invoking_skill>")
        wp_id = positional[0]
        invoking_skill = positional[1]
        project_root = Path(flags.get("project_root", os.getcwd())).resolve()
        check_G3(wp_id, invoking_skill, project_root)
        ok("G3", f"claim verified for WP={wp_id} skill={invoking_skill}")
    else:
        env_error(f"unknown gate: {gate}")


if __name__ == "__main__":
    main()
