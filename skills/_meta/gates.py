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
# CONTRACT_SCOPE_CRITICAL_GLOBS — locked constant (S029 design §7.2 R1).
#
# Anti-baseline-poisoning fix: this is hard-coded as a constant, not config-
# driven. Modifying it requires a code change reviewable in git history.
# Configs are mutable and rubber-stampable; constants are not.
#
# Used by check_G_CONTRACT_SCOPE (WP-3) for severity classification:
# any ArtifactDelta whose path matches a glob below is severity=critical
# regardless of artifact_kind, and the path also overrides
# contract_map.excluded_paths (M4 precedence rule: critical wins).
# ---------------------------------------------------------------------------

CONTRACT_SCOPE_CRITICAL_GLOBS: Tuple[str, ...] = (
    "migrations/**/*.sql",
    "**/migrations/**/*.sql",
    "**/.env",
    "**/.env.*",
    "**/secrets/*",
    "**/secrets.*",
    "**/credentials*",
    "**/*service-account*",
    "**/Dockerfile",
    "**/Dockerfile.*",
    "**/docker-compose*.yml",
    "**/docker-compose*.yaml",
    "infra/**",
    "**/*.pem",
    "**/*.key",
    "**/.ssh/**",
)


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
# G4 — deterministic gate over the signed wiring snapshot
# ---------------------------------------------------------------------------
#
# Per design 2026-04-14 §5.4. Five rules (R0, R1, R3, R6, R7). R2/R4/R5 are v2.
#
# Exit codes (mapped in main() from check_G4's structured return):
#   0 = pass
#   2 = hard fail (status='fail')
#   3 = advisory warning (status='advisory')
#   4 = ledger missing / skip (status='ledger_missing')
#
# Modes:
#   strict   (default CI)   — R1 hard fail.   R3/R6/R7 hard fail. R0 silent.
#   advisory (default local) — R1 exit 3.     R3/R6/R7 hard fail. R0 silent.


def _g4_load_config(project_dir: Path) -> Dict[str, Any]:
    cfg_path = project_dir / ".ledger" / "config.yaml"
    if not cfg_path.is_file():
        return {}
    try:
        data = yaml.safe_load(cfg_path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _g4_get_stale_file_budget(cfg: Dict[str, Any]) -> int:
    g4 = cfg.get("g4") or {}
    return int(g4.get("stale_file_budget", 50))


def _g4_load_latest(project_dir: Path) -> Optional[Dict[str, Any]]:
    latest = project_dir / ".wiring" / "latest.json"
    if not latest.is_file():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _git_write_tree(project_dir: Path) -> Optional[str]:
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", str(project_dir), "write-tree"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return None
        h = out.stdout.strip()
        if len(h) == 40 and all(c in "0123456789abcdef" for c in h):
            return h
        return None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git_changed_file_count(project_dir: Path, base_tree: str) -> Optional[int]:
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", str(project_dir), "diff", "--name-only", base_tree],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return None
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
        return len(lines)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _g4_load_pr_components(project_dir: Path) -> set[str]:
    """Detect components whose `source_paths` intersect the current git diff.

    Used by R1 to determine which components are "changed" in this PR. If the
    project-relative source_paths entries can't be matched, we return an empty
    set (meaning R1 has nothing to block).
    """
    import subprocess
    map_path = project_dir / "progress" / "contract-map.yaml"
    if not map_path.is_file():
        return set()
    try:
        map_yaml = yaml.safe_load(map_path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return set()

    components = map_yaml.get("components") or []

    try:
        out = subprocess.run(
            ["git", "-C", str(project_dir), "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return set()
        changed_paths = [ln for ln in out.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return set()

    changed_components: set[str] = set()
    for c in components:
        cid = c.get("id")
        if not cid:
            continue
        for sp in (c.get("source_paths") or []):
            # A trivial containment check — mirrors the design's looseness.
            sp_norm = sp.replace("~/.claude/skills/", ".claude/skills/").rstrip("/")
            for cp in changed_paths:
                if sp_norm and sp_norm in cp:
                    changed_components.add(cid)
                    break
    return changed_components


def _g4_previous_components(previous_snapshot: Optional[Dict[str, Any]]) -> set[str]:
    if previous_snapshot is None:
        return set()
    names: set[str] = set()
    for e in previous_snapshot.get("edges") or []:
        names.add(e.get("src_component"))
        names.add(e.get("dst_component"))
    names.discard(None)
    return names


def _g4_current_source_components(project_dir: Path) -> set[str]:
    """Read component ids from the current contract map."""
    map_path = project_dir / "progress" / "contract-map.yaml"
    if not map_path.is_file():
        return set()
    try:
        map_yaml = yaml.safe_load(map_path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return set()
    return {c.get("id") for c in (map_yaml.get("components") or []) if c.get("id")}


def check_G4(project_dir: Path, mode: str = "strict") -> Dict[str, Any]:
    """G4 implementation per design 2026-04-14 §5.4.

    Rules evaluated:
      R0 — new-component exception (R1 becomes advisory for components
           not present in previous latest.json)
      R1 — blocking edges must be corroborated (blocking_eligible=true) for
           components touched by the current diff
      R3 — removed code must not retain live edges (src/dst absent from
           current source tree -> status must be orphan/stale/suppressed)
      R6 — snapshot freshness (strict: exact tree hash match; advisory:
           generated_at within 1h AND changed file count ≤ budget)
      R7 — signature HMAC verifies against forge session key

    Returns a structured dict:
      {
        "status": "pass" | "advisory" | "fail" | "ledger_missing",
        "mode": "strict" | "advisory",
        "violations": [{"rule": "R1", "severity": "hard"|"advisory",
                        "message": "..."}, ...],
        "message": "summary",
        "snapshot_generation": int or None,
      }
    """
    if mode not in ("strict", "advisory"):
        env_error(f"G4 mode must be 'strict' or 'advisory', got {mode!r}")

    # Ledger-missing skip (exit 4)
    ledger = project_dir / "progress" / "integration-ledger.md"
    if not ledger.is_file():
        return {
            "status": "ledger_missing",
            "mode": mode,
            "violations": [],
            "message": f"no ledger at {ledger}, skipping G4",
            "snapshot_generation": None,
        }

    # Snapshot must exist
    snapshot = _g4_load_latest(project_dir)
    if snapshot is None:
        return {
            "status": "fail",
            "mode": mode,
            "violations": [{"rule": "R6", "severity": "hard",
                            "message": "no .wiring/latest.json; run wiring-reconcile"}],
            "message": "snapshot missing",
            "snapshot_generation": None,
        }

    violations: List[Dict[str, Any]] = []
    cfg = _g4_load_config(project_dir)
    previous_snapshot: Optional[Dict[str, Any]] = None  # v1: no rotation; treat as None

    # R7 — signature validity (HMAC-SHA256 using forge session key)
    session_key_path = project_dir / ".forge" / "session.key"
    if not session_key_path.is_file():
        violations.append({
            "rule": "R7", "severity": "hard",
            "message": f"session.key missing at {session_key_path}",
        })
    else:
        try:
            key = session_key_path.read_bytes()
        except OSError as e:
            violations.append({"rule": "R7", "severity": "hard",
                               "message": f"session.key unreadable: {e}"})
            key = b""
        sig = snapshot.get("signature") or {}
        if sig.get("algorithm") != "HMAC-SHA256":
            violations.append({"rule": "R7", "severity": "hard",
                               "message": "signature.algorithm is not HMAC-SHA256"})
        else:
            # Use exactly the same signed payload shape as promote._build_signature
            # AND the same canonical_json convention (bit-for-bit).
            payload = {
                "contract_map_hash": snapshot.get("contract_map_hash", ""),
                "contract_map_revision": int(snapshot.get("contract_map_revision", 0) or 0),
                "forge_session_id": sig.get("key_id", "").removeprefix("forge-session-"),
                "snapshot_id": snapshot.get("snapshot_id"),
                "snapshot_generation": int(snapshot.get("snapshot_generation", 0) or 0),
                "signed_at": sig.get("signed_at"),
            }
            expected = hmac.new(
                key, canonical_json(payload).encode("utf-8"), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, sig.get("digest", "")):
                violations.append({"rule": "R7", "severity": "hard",
                                   "message": "signature HMAC does not verify"})

    # R6 — snapshot freshness
    # Strict: snapshot.workspace_tree_hash == current git write-tree.
    # Advisory: generated_at within 1 hour AND changed file count ≤ budget.
    cur_tree = _git_write_tree(project_dir)
    snap_tree = snapshot.get("workspace_tree_hash")
    if mode == "strict":
        if not snap_tree or not cur_tree:
            violations.append({"rule": "R6", "severity": "hard",
                               "message": "workspace_tree_hash missing on snapshot or git"})
        elif snap_tree != cur_tree:
            violations.append({"rule": "R6", "severity": "hard",
                               "message": f"tree hash mismatch "
                                          f"(snap={snap_tree[:12]}, cur={cur_tree[:12]})"})
    else:  # advisory
        from datetime import datetime, timezone
        generated_at = snapshot.get("generated_at", "")
        try:
            # Support trailing Z and offset
            if generated_at.endswith("Z"):
                gen_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            else:
                gen_dt = datetime.fromisoformat(generated_at)
            age_seconds = (datetime.now(timezone.utc) - gen_dt).total_seconds()
        except (ValueError, TypeError):
            violations.append({"rule": "R6", "severity": "hard",
                               "message": f"generated_at unparseable: {generated_at!r}"})
            age_seconds = None
        if age_seconds is not None:
            if age_seconds > 3600:
                violations.append({"rule": "R6", "severity": "hard",
                                   "message": f"generated_at is {int(age_seconds)}s old (>1h)"})
            elif snap_tree and cur_tree:
                if snap_tree != cur_tree:
                    budget = _g4_get_stale_file_budget(cfg)
                    changed = _git_changed_file_count(project_dir, snap_tree)
                    if changed is None:
                        violations.append({"rule": "R6", "severity": "hard",
                                           "message": "cannot count changed files via git diff"})
                    elif changed > budget:
                        violations.append({
                            "rule": "R6", "severity": "hard",
                            "message": f"{changed} files changed since snapshot (budget {budget})",
                        })

    # R3 — removed code must not keep live edges
    source_components = _g4_current_source_components(project_dir)
    if source_components:
        for e in snapshot.get("edges") or []:
            src_c = e.get("src_component")
            dst_c = e.get("dst_component")
            missing = []
            if src_c and src_c not in source_components:
                missing.append(src_c)
            if dst_c and dst_c not in source_components:
                missing.append(dst_c)
            if missing and e.get("status") == "live":
                violations.append({
                    "rule": "R3", "severity": "hard",
                    "message": f"edge {e.get('edge_id', '?')} references removed "
                               f"component(s) {missing} but status=live "
                               f"(must be orphan/stale/suppressed)",
                })

    # R1 — blocking edges must be corroborated, for components touched by the PR
    # R0 exception: if src_component is new (absent from previous latest.json AND
    # present in current source tree), R1 becomes advisory regardless of mode.
    previous_components = _g4_previous_components(previous_snapshot)
    changed_components = _g4_load_pr_components(project_dir)
    for e in snapshot.get("edges") or []:
        src_c = e.get("src_component")
        if not src_c:
            continue
        if src_c not in changed_components:
            continue
        if e.get("blocking_eligible"):
            continue
        # R0: new-component exception
        is_new_component = (
            previous_components  # only applies if there IS a prior snapshot
            and src_c not in previous_components
            and src_c in source_components
        )
        rule_severity = (
            "advisory" if (mode == "advisory" or is_new_component) else "hard"
        )
        msg = (
            f"R1: blocking edge {e.get('edge_id', '?')} on changed component "
            f"{src_c!r} is not blocking_eligible (no static corroboration)"
        )
        if is_new_component:
            msg += " [R0 new-component exception applied]"
        violations.append({"rule": "R1", "severity": rule_severity, "message": msg})

    # Classify status
    any_hard = any(v["severity"] == "hard" for v in violations)
    any_advisory = any(v["severity"] == "advisory" for v in violations)
    if any_hard:
        status = "fail"
    elif any_advisory:
        status = "advisory"
    else:
        status = "pass"

    return {
        "status": status,
        "mode": mode,
        "violations": violations,
        "message": (
            f"G4 {status} in {mode} mode "
            f"({len(violations)} violation(s))"
        ),
        "snapshot_generation": snapshot.get("snapshot_generation"),
    }


# ---------------------------------------------------------------------------
# Shared observation helper (ecosystem-keystone §4.7 Hook 1)
# ---------------------------------------------------------------------------
#
# Every non-zero gate exit in the G_V / G_XR / G_SCOPE paths MUST call
# `exit_with_observation` instead of bare `sys.exit` (or the shared `fail()`
# helper used by the pre-existing S014 gates). The helper writes a
# `gate_false_block` (or `gate_false_pass` for scope-claim mismatches)
# observation via `claude_observe`, wrapped in a best-effort try/except so
# a broken observation backend CANNOT block the gate exit. Observation is
# diagnostic; the gate is authoritative (design §4.7 rationale).
#
# The existing S014 G1/G2/G3/G4 paths continue to use `fail()` / `env_error()`
# for backwards compatibility — conversion to `exit_with_observation` is
# tracked as a separate follow-up (#43). This is an ADDITIVE change: no S014
# gate behavior is modified.


def _load_claude_observe_for_gates():
    """Fail-open loader for `claude_observe`; returns a no-op stub if the
    process-observation backend is unavailable. Mirrors the three-tier fallback
    in claims.py so gates.py runs correctly in minimal environments.
    """
    try:
        from process_observation.scripts.write import claude_observe as _co  # type: ignore
        return _co
    except ImportError:
        pass
    try:
        _scripts_dir = (
            Path(__file__).resolve().parent.parent
            / "process-observation" / "scripts"
        )
        if _scripts_dir.is_dir():
            _scripts_str = str(_scripts_dir)
            if _scripts_str not in sys.path:
                sys.path.insert(0, _scripts_str)
            from write import claude_observe as _co  # type: ignore
            return _co
    except Exception:
        pass
    return lambda *args, **kwargs: None


claude_observe = _load_claude_observe_for_gates()


_GATE_FALSE_BLOCK_SET = frozenset({"G1", "G2", "G3", "G4", "G_V", "G_XR"})


def exit_with_observation(
    gate_name: str,
    exit_code: int,
    subject_id: str,
    what_happened: str,
    severity: str = "blocking",
    category: Optional[str] = None,
    fingerprint: Optional[str] = None,
) -> None:
    """Emit an observation then exit with the given non-zero code.

    Per design §4.7 Hook 1:
      - `category` defaults to `gate_false_block` for G1/G2/G3/G4/G_V/G_XR
        and `gate_false_pass` for scope-claim mismatches (G_SCOPE).
      - `fingerprint` defaults to `<gate_name>-<subject_id>` so all refusals
        of the same kind for the same subject collapse into one active
        observation (dedup_key algorithm, §4.3).
      - observation-write is best-effort: exceptions during `claude_observe`
        are trapped + logged to stderr, never block the gate exit.

    NEVER called with exit_code == 0. Pass path should bypass this helper.
    """
    if exit_code == 0:
        # Defense-in-depth: pass paths must not route through here.
        sys.stdout.write(f"{gate_name}_PASS: {what_happened}\n")
        sys.exit(0)

    resolved_category = (
        category
        if category is not None
        else ("gate_false_block" if gate_name in _GATE_FALSE_BLOCK_SET else "gate_false_pass")
    )
    resolved_fingerprint = fingerprint or f"{gate_name}-{subject_id}"

    # Write the observation best-effort. Never let a failure here block the exit.
    try:
        claude_observe(
            resolved_category,
            subject_id,
            what_happened,
            fingerprint=resolved_fingerprint,
            subject_type="gate",
            severity=severity,
            observed_by=f"gates.py:{gate_name}",
            related=[f"uri://{subject_id}"],
        )
    except Exception as e:  # pragma: no cover - defense-in-depth
        sys.stderr.write(f"OBSERVATION_WRITE_FAIL: {e}\n")

    # Print the fail line to stderr in the same shape the existing S014 gates use.
    sys.stderr.write(f"{gate_name}_FAIL: {what_happened}\n")
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# G_V — visual gate (design §5.3)
# ---------------------------------------------------------------------------
#
# Invoked by bob BEFORE any UI-INTEGRATED -> UI-VERIFIED transition.
# Verdict file produced by visual-arbiter + design-drift-arbiter; read here.
# bob is the sole writer of `.design-ledger/visual-verdicts/*` (CB4).


VISUAL_VERDICTS_SUBDIR = ".design-ledger/visual-verdicts"
SKELETONS_SUBDIR = ".design-ledger/skeletons"
VERIFICATION_REQUESTS_SUBDIR = ".design-ledger/verification-requests"


def _gv_fail(impl_hash: str, message: str, *, category: Optional[str] = None,
             fingerprint: Optional[str] = None) -> None:
    """G_V non-zero exit helper — always routes through exit_with_observation."""
    exit_with_observation(
        "G_V",
        2,
        impl_hash,
        message,
        severity="blocking",
        category=category,
        fingerprint=fingerprint,
    )


def _gv_env_error(impl_hash: str, message: str) -> None:
    """G_V environmental (non-gate-violation) exit. Still emits an observation
    so alf can catch chronic env issues, but tagged external_tool_fail."""
    exit_with_observation(
        "G_V",
        3,
        impl_hash,
        message,
        severity="degraded",
        category="external_tool_fail",
        fingerprint=f"G_V-env-{impl_hash[:8]}",
    )


def _load_current_skeleton_version(project_root: Path) -> Optional[str]:
    """Read `.design-ledger/skeletons/index.yaml` and return the pinned
    `skeleton_version` (design §2.2). Returns None on any read/parse failure;
    caller decides whether that is an env error or a gate violation.
    """
    index_path = project_root / SKELETONS_SUBDIR / "index.yaml"
    if not index_path.is_file():
        return None
    try:
        data = yaml.safe_load(index_path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    sv = data.get("skeleton_version")
    if not isinstance(sv, str) or not sv:
        return None
    return sv


def check_G_V(impl_hash: str, project_root: Path) -> None:
    """G_V per design §5.3.

    Checks, in order (first failure exits 2 with observation):
      1. `.design-ledger/visual-verdicts/<impl_hash>.verdict.yaml` exists +
         well-formed YAML mapping with `schema: visual-verdict.v1`.
      2. Both arms present: `arbiter_verdict` + `drift_arbiter_verdict`.
      3. Both arms `status: pass` (drift arm may instead be
         `status: auto_approved` for micro-drift).
      4. Skeleton version pinned in verdict matches current
         `.design-ledger/skeletons/index.yaml` skeleton_version.
         Mismatch is a `gate_false_pass` observation (arbiter missed the bump).
      5. 8-field tuple echoes verbatim via `claims.consume_visual_verdict`.
         Any rejection outcome -> exit 2. `accepted` -> exit 0.

    Exit codes: 0 pass, 2 fail, 3 env error.
    Non-zero exits route through `exit_with_observation`.
    """
    project_root = project_root.resolve()
    verdict_path = project_root / VISUAL_VERDICTS_SUBDIR / f"{impl_hash}.verdict.yaml"

    # 1. Verdict file exists and is well-formed
    if not verdict_path.is_file():
        _gv_fail(
            impl_hash,
            f"verdict file missing at {verdict_path} (expected after arbiter spawn)",
            fingerprint="verdict-missing",
        )
    try:
        verdict = yaml.safe_load(verdict_path.read_text())
    except yaml.YAMLError as e:
        _gv_env_error(impl_hash, f"verdict YAML unparseable: {e}")
    except OSError as e:
        _gv_env_error(impl_hash, f"verdict file unreadable: {e}")

    if not isinstance(verdict, dict):
        _gv_fail(
            impl_hash,
            f"verdict is not a YAML mapping (got {type(verdict).__name__})",
            fingerprint="verdict-malformed",
        )

    # 2. Both arms present
    arbiter = verdict.get("arbiter_verdict")
    drift = verdict.get("drift_arbiter_verdict")
    if not isinstance(arbiter, dict):
        _gv_fail(
            impl_hash,
            "verdict missing arbiter_verdict arm",
            fingerprint="arm-missing-arbiter",
        )
    if not isinstance(drift, dict):
        _gv_fail(
            impl_hash,
            "verdict missing drift_arbiter_verdict arm",
            fingerprint="arm-missing-drift",
        )

    # 3. Both arms pass (drift may be auto_approved for micro-drift)
    arbiter_status = arbiter.get("status")
    drift_status = drift.get("status")
    if arbiter_status != "pass":
        _gv_fail(
            impl_hash,
            f"arbiter_verdict.status={arbiter_status!r} (expected 'pass')",
            fingerprint="arbiter-not-pass",
        )
    if drift_status not in ("pass", "auto_approved"):
        _gv_fail(
            impl_hash,
            f"drift_arbiter_verdict.status={drift_status!r} "
            f"(expected 'pass' or 'auto_approved')",
            fingerprint="drift-not-pass",
        )

    # 4. Skeleton version match
    verdict_skeleton_version = verdict.get("skeleton_version")
    current_skeleton_version = _load_current_skeleton_version(project_root)
    if current_skeleton_version is None:
        _gv_env_error(
            impl_hash,
            f"cannot read skeleton_version from "
            f"{project_root / SKELETONS_SUBDIR / 'index.yaml'}",
        )
    if verdict_skeleton_version != current_skeleton_version:
        # Per §5.3: arbiter missed the skeleton bump -> gate_false_pass
        _gv_fail(
            impl_hash,
            f"verdict.skeleton_version={verdict_skeleton_version!r} "
            f"but current index.yaml pins {current_skeleton_version!r} "
            f"(arbiter missed a skeleton bump)",
            category="gate_false_pass",
            fingerprint="skeleton-version-mismatch",
        )

    # 5. 8-field tuple echo via claims.consume_visual_verdict
    request_id = verdict.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        _gv_fail(
            impl_hash,
            "verdict missing request_id field (required for tuple echo)",
            fingerprint="request-id-missing",
        )

    # Lazy import to avoid circular dependency at module load time
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import claims as claims_mod  # type: ignore
    except ImportError as e:
        _gv_env_error(impl_hash, f"claims.py not importable: {e}")

    try:
        outcome, _record = claims_mod.consume_visual_verdict(
            project_root, request_id, verdict,
        )
    except RuntimeError as e:
        # consume_visual_verdict raises only when the request file is missing.
        _gv_fail(
            impl_hash,
            f"visual-verification request {request_id!r} not found: {e}",
            fingerprint="request-not-found",
        )
    except Exception as e:  # pragma: no cover - defensive
        _gv_env_error(
            impl_hash,
            f"consume_visual_verdict raised unexpectedly: {e!r}",
        )

    if outcome == "accepted":
        sys.stdout.write(
            f"G_V_PASS: verdict {request_id} accepted for impl_hash={impl_hash}\n"
        )
        sys.exit(0)
    if outcome == "rejected_tuple_mismatch":
        _gv_fail(
            impl_hash,
            f"8-field tuple echo mismatch for request_id={request_id}",
            fingerprint="tuple-mismatch",
        )
    if outcome == "rejected_not_open":
        _gv_fail(
            impl_hash,
            f"verification-request {request_id} is not status=open "
            f"(already consumed/abandoned)",
            fingerprint="request-not-open",
        )
    # Any other outcome string (future-compat)
    _gv_fail(
        impl_hash,
        f"consume_visual_verdict returned unexpected outcome={outcome!r}",
        fingerprint="outcome-unknown",
    )


# ---------------------------------------------------------------------------
# G_XR — cross-reference / orphan gate (design §5.4)
# ---------------------------------------------------------------------------
#
# Three checks (D8):
#   1. Every `capability://` in contract-map reachable from visual entry
#      points OR has an `entry_point` tag in ENTRY_POINT_TAGS.
#   2. Every `visual_entry_points[]` URI in contract-map resolves.
#   3. Every skeleton `interactions[].binds_to` URI resolves OR the
#      interaction declares `visual_only: true`.
#
# Reachability walk prefers `.wiring/latest.json` edges; falls back to
# contract-map `callees[]` so we still run (looser but no false orphans)
# when wiring is unavailable (A4 degradation path).


ENTRY_POINT_TAGS = frozenset({
    "cron", "webhook", "cli", "api_public", "test_harness", "migration",
})


def _gxr_fail(message: str, *, fingerprint: str = "G_XR") -> None:
    """G_XR non-zero exit helper — routes through exit_with_observation."""
    exit_with_observation(
        "G_XR",
        2,
        "contract-map",
        message,
        severity="blocking",
        fingerprint=fingerprint,
    )


def _gxr_env_error(message: str) -> None:
    exit_with_observation(
        "G_XR",
        3,
        "contract-map",
        message,
        severity="degraded",
        category="external_tool_fail",
        fingerprint="G_XR-env",
    )


def _load_contract_map_for_gxr(project_root: Path) -> Dict[str, Any]:
    map_path = project_root / "progress" / "contract-map.yaml"
    if not map_path.is_file():
        _gxr_env_error(f"contract-map not found at {map_path}")
    try:
        data = yaml.safe_load(map_path.read_text()) or {}
    except yaml.YAMLError as e:
        _gxr_env_error(f"contract-map unparseable: {e}")
    except OSError as e:
        _gxr_env_error(f"contract-map unreadable: {e}")
    if not isinstance(data, dict):
        _gxr_env_error("contract-map is not a YAML mapping")
    return data


def _load_all_skeletons(project_root: Path) -> Dict[str, Dict[str, Any]]:
    """Load every per-screen skeleton YAML under `.design-ledger/skeletons/`.

    Returns a dict screen_id -> parsed YAML mapping. Screens are enumerated
    from index.yaml's `screens[]` list; the index.yaml itself is NOT included.
    Missing index or unreadable screens -> empty dict (G_XR check 3 will
    harmlessly skip absent skeletons; the env is either pre-UI or broken).
    """
    skeletons: Dict[str, Dict[str, Any]] = {}
    index_path = project_root / SKELETONS_SUBDIR / "index.yaml"
    if not index_path.is_file():
        return skeletons
    try:
        index = yaml.safe_load(index_path.read_text()) or {}
    except (yaml.YAMLError, OSError):
        return skeletons
    if not isinstance(index, dict):
        return skeletons
    for screen in (index.get("screens") or []):
        if not isinstance(screen, dict):
            continue
        screen_file = screen.get("file")
        screen_id = screen.get("screen_id") or screen.get("id")
        if not isinstance(screen_file, str) or not isinstance(screen_id, str):
            continue
        screen_path = project_root / SKELETONS_SUBDIR / screen_file
        if not screen_path.is_file():
            continue
        try:
            data = yaml.safe_load(screen_path.read_text()) or {}
        except (yaml.YAMLError, OSError):
            continue
        if isinstance(data, dict):
            skeletons[screen_id] = data
    return skeletons


def _enumerate_capability_uris(contract_map: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Yield (uri, cap_node) for every declared capability in the contract map.

    Capabilities are components[].capabilities (dict of name -> node). If a
    component has no `capabilities:` subsection (current legacy format), its
    `id` alone is the URI (`capability://<component_id>`). This matches the
    uri.py convention.
    """
    out: List[Tuple[str, Dict[str, Any]]] = []
    for comp in contract_map.get("components") or []:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str):
            continue
        caps = comp.get("capabilities")
        if isinstance(caps, dict) and caps:
            for cap_name, cap_node in caps.items():
                if not isinstance(cap_name, str):
                    continue
                uri_str = f"capability://{cid}.{cap_name}"
                node = cap_node if isinstance(cap_node, dict) else {}
                out.append((uri_str, node))
        # If no explicit capabilities subsection, the component itself is not
        # a `capability://` target — it's a `component://`, not enumerated here.
    return out


def _load_call_graph(project_root: Path, contract_map: Dict[str, Any]) -> Dict[str, List[str]]:
    """Return adjacency list of capability URIs (or component ids as a fallback).

    Primary source: `.wiring/latest.json` edges (S023) -- preferred when present.
    Fallback: declared `callees[]` from contract-map components. The fallback is
    "looser" (misses runtime edges) but guarantees no FALSE orphans (declared ⊆
    true). Any empty/missing wiring file -> fall back silently.
    """
    graph: Dict[str, List[str]] = {}

    wiring_path = project_root / ".wiring" / "latest.json"
    if wiring_path.is_file():
        try:
            wiring = json.loads(wiring_path.read_text())
        except (json.JSONDecodeError, OSError):
            wiring = None
        if isinstance(wiring, dict):
            for edge in (wiring.get("edges") or []):
                if not isinstance(edge, dict):
                    continue
                src = edge.get("src_uri") or edge.get("src_symbol") or edge.get("src_component")
                dst = edge.get("dst_uri") or edge.get("dst_symbol") or edge.get("dst_component")
                if isinstance(src, str) and isinstance(dst, str):
                    graph.setdefault(src, []).append(dst)
            if graph:
                return graph

    # Fallback: contract-map declared callees[]
    for comp in contract_map.get("components") or []:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id")
        if not isinstance(cid, str):
            continue
        src_uri = f"capability://{cid}"
        for callee in (comp.get("callees") or []):
            if isinstance(callee, str):
                dst_uri = f"capability://{callee}"
                graph.setdefault(src_uri, []).append(dst_uri)
        # Also map capability-suffixed URIs for the walk to follow from
        # capabilities within the component.
        caps = comp.get("capabilities")
        if isinstance(caps, dict):
            for cap_name in caps.keys():
                if not isinstance(cap_name, str):
                    continue
                cap_uri = f"capability://{cid}.{cap_name}"
                # Component-level callees flow through each capability
                for callee in (comp.get("callees") or []):
                    if isinstance(callee, str):
                        graph.setdefault(cap_uri, []).append(f"capability://{callee}")
    return graph


def _compute_reachable_capabilities(
    project_root: Path,
    contract_map: Dict[str, Any],
    skeletons: Dict[str, Dict[str, Any]],
) -> set:
    """BFS from visual_roots + entry_point-tagged capabilities."""
    # Visual roots — skeleton interactions with a real binds_to (not visual_only)
    visual_roots: set = set()
    for skel in skeletons.values():
        elements = skel.get("elements")
        # `elements` may be either a dict (keyed by element_id) or a list (ordered)
        if isinstance(elements, dict):
            element_iter = elements.values()
        elif isinstance(elements, list):
            element_iter = elements
        else:
            continue
        for elem in element_iter:
            if not isinstance(elem, dict):
                continue
            for inter in (elem.get("interactions") or []):
                if not isinstance(inter, dict):
                    continue
                if inter.get("visual_only"):
                    continue
                bt = inter.get("binds_to")
                if isinstance(bt, str) and bt:
                    visual_roots.add(bt)

    # Entry-point-tagged capabilities
    tagged_roots: set = set()
    for cap_uri, cap_node in _enumerate_capability_uris(contract_map):
        ep = cap_node.get("entry_point") if isinstance(cap_node, dict) else None
        if isinstance(ep, str) and ep in ENTRY_POINT_TAGS:
            tagged_roots.add(cap_uri)
    # Also allow component-level entry_point (tag applies to all its caps)
    for comp in contract_map.get("components") or []:
        if not isinstance(comp, dict):
            continue
        ep = comp.get("entry_point")
        cid = comp.get("id")
        if isinstance(ep, str) and ep in ENTRY_POINT_TAGS and isinstance(cid, str):
            tagged_roots.add(f"capability://{cid}")
            caps = comp.get("capabilities")
            if isinstance(caps, dict):
                for cap_name in caps.keys():
                    if isinstance(cap_name, str):
                        tagged_roots.add(f"capability://{cid}.{cap_name}")

    graph = _load_call_graph(project_root, contract_map)
    reachable: set = set(visual_roots | tagged_roots)
    frontier: List[str] = list(reachable)
    while frontier:
        cap = frontier.pop()
        for callee in graph.get(cap, ()):
            if callee not in reachable:
                reachable.add(callee)
                frontier.append(callee)
    return reachable


def check_G_XR(project_root: Path) -> None:
    """G_XR per design §5.4.

    Three checks — any failure exits 2 with a specific fingerprint so the
    observation aggregate stays informative:
      - `orphan-capability` when a capability is neither reachable nor tagged
      - `unresolved-uri` when a visual_entry_point does not resolve
      - `dead-interaction` when a skeleton binds_to does not resolve
    """
    project_root = project_root.resolve()
    contract_map = _load_contract_map_for_gxr(project_root)
    skeletons = _load_all_skeletons(project_root)

    # Lazy import uri with fail-soft: G_XR requires uri.resolve for checks 2+3
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import uri as uri_mod  # type: ignore
    except ImportError as e:
        _gxr_env_error(f"uri.py not importable: {e}")

    # Check 1 — every capability reachable OR tagged
    capability_uris = _enumerate_capability_uris(contract_map)
    if capability_uris:
        reachable = _compute_reachable_capabilities(project_root, contract_map, skeletons)
        # The tagged set (entry_point-declared) is ALSO implicitly "reachable"
        # (a cron / webhook IS an entry point). _compute_reachable already
        # seeds tagged into `reachable`. Keep the explicit tag set for clarity.
        tagged: set = set()
        for cap_uri, cap_node in capability_uris:
            ep = cap_node.get("entry_point") if isinstance(cap_node, dict) else None
            if isinstance(ep, str) and ep in ENTRY_POINT_TAGS:
                tagged.add(cap_uri)
        for comp in contract_map.get("components") or []:
            if not isinstance(comp, dict):
                continue
            ep = comp.get("entry_point")
            cid = comp.get("id")
            if isinstance(ep, str) and ep in ENTRY_POINT_TAGS and isinstance(cid, str):
                tagged.add(f"capability://{cid}")
                caps = comp.get("capabilities")
                if isinstance(caps, dict):
                    for cap_name in caps.keys():
                        if isinstance(cap_name, str):
                            tagged.add(f"capability://{cid}.{cap_name}")

        orphans = [
            uri_str for uri_str, _node in capability_uris
            if uri_str not in reachable and uri_str not in tagged
        ]
        if orphans:
            preview = ", ".join(orphans[:5])
            suffix = "..." if len(orphans) > 5 else ""
            _gxr_fail(
                f"{len(orphans)} orphan capability(ies): {preview}{suffix}",
                fingerprint="orphan-capability",
            )

    # Check 2 — every visual_entry_point resolves
    for vep in contract_map.get("visual_entry_points") or []:
        if not isinstance(vep, str) or not vep:
            _gxr_fail(
                f"visual_entry_points contains non-string entry: {vep!r}",
                fingerprint="unresolved-uri",
            )
        if not uri_mod.exists(vep, project_root):
            _gxr_fail(
                f"visual_entry_point {vep!r} does not resolve",
                fingerprint="unresolved-uri",
            )

    # Check 3 — every skeleton interaction binds_to resolves (or visual_only)
    for screen_id, skel in skeletons.items():
        elements = skel.get("elements")
        if isinstance(elements, dict):
            element_iter = list(elements.items())
        elif isinstance(elements, list):
            element_iter = [(e.get("id") if isinstance(e, dict) else None, e)
                            for e in elements]
        else:
            continue
        for element_id, elem in element_iter:
            if not isinstance(elem, dict):
                continue
            for inter in (elem.get("interactions") or []):
                if not isinstance(inter, dict):
                    continue
                event = inter.get("event", "<unknown-event>")
                if inter.get("visual_only"):
                    continue
                bt = inter.get("binds_to")
                if not isinstance(bt, str) or not bt:
                    _gxr_fail(
                        f"{screen_id}/{element_id}/{event}: missing binds_to "
                        "AND missing visual_only:true",
                        fingerprint="dead-interaction",
                    )
                if not uri_mod.exists(bt, project_root):
                    _gxr_fail(
                        f"{screen_id}/{element_id}/{event}: binds_to "
                        f"{bt!r} does not resolve",
                        fingerprint="dead-interaction",
                    )

    sys.stdout.write(
        f"G_XR_PASS: cross-reference checks passed at {project_root}\n"
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# G_SCOPE — D18 scope-check mini-gate (design §7.2)
# ---------------------------------------------------------------------------
#
# Invoked by bob BEFORE G_V + G_XR when bob declares a lightweight ui_scope.
# Validates the declaration against the actual git diff — mechanical, no
# semantic judgment. False declaration -> `gate_false_pass` observation
# with fingerprint `scope-mismatch` (bob self-claimed a relaxed scope
# that the diff contradicts).


DECLARED_SCOPE_CLOSED_SET = frozenset({"none", "text_only", "tokens_only"})


def _gscope_fail(message: str, *, fingerprint: str = "scope-mismatch") -> None:
    """G_SCOPE non-zero exit helper — emits gate_false_pass on scope-claim
    mismatches per design §7.2."""
    exit_with_observation(
        "G_SCOPE",
        2,
        "declared_scope",
        message,
        severity="blocking",
        category="gate_false_pass",
        fingerprint=fingerprint,
    )


def _gscope_env_error(message: str) -> None:
    exit_with_observation(
        "G_SCOPE",
        3,
        "declared_scope",
        message,
        severity="degraded",
        category="external_tool_fail",
        fingerprint="G_SCOPE-env",
    )


def _git_diff_name_only(project_root: Path) -> List[str]:
    """Return `git diff --name-only HEAD` output as a list of changed paths.

    On any git failure, raises RuntimeError — caller converts to env error.
    Empty output (no diff) returns an empty list, not an error.
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"git diff failed: {e!r}") from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"git diff exit {proc.returncode}: {proc.stderr.strip()[:200]}"
        )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _git_diff_for_path(project_root: Path, path: str) -> str:
    """Return `git diff HEAD -- <path>` unified diff text, or empty string on failure."""
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "diff", "HEAD", "--", path],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout


_UI_STRUCTURAL_SUFFIXES = (".html", ".css", ".js", ".tsx")
_DESIGN_LEDGER_PREFIX = ".design-ledger/"


def _is_ui_path(path: str) -> bool:
    """True if the path counts as a UI-touching file for ui_scope:none."""
    if path.startswith(_DESIGN_LEDGER_PREFIX):
        return True
    return any(path.endswith(suffix) for suffix in _UI_STRUCTURAL_SUFFIXES)


def _is_structural_diff(diff_text: str) -> bool:
    """Heuristic: a diff is 'structural' if any added/removed line, after
    stripping leading +/- and whitespace, begins with a tag opener (`<`)
    or an attribute (`...=`), or contains JSX element syntax. Pure text
    changes (labels, inner text nodes) are ALLOWED under text_only.

    False positives err on the side of blocking — if a diff looks structural,
    the gate fails, forcing the caller to either retag the scope or split
    the commit. This matches the spec's "mechanical, no semantic judgment"
    policy.
    """
    for line in diff_text.splitlines():
        if not line or line[0] not in "+-":
            continue
        if line.startswith(("+++", "---", "@@")):
            continue
        stripped = line[1:].strip()
        if not stripped:
            continue
        # Quick structural markers: opening tags, attribute-like tokens, JSX.
        if stripped.startswith("<") or stripped.startswith("</"):
            return True
        # attribute-ish (space + ident=...): `  class="foo"` after the +/-.
        # Check for standalone `="..."` or `={...}` segments.
        if "=" in stripped and ("<" in stripped or stripped.endswith(">")
                                or "{" in stripped or "}" in stripped):
            return True
    return False


def _tokens_only_change(project_root: Path, index_path: str) -> bool:
    """Best-effort check that a diff against `.design-ledger/skeletons/index.yaml`
    touches ONLY the `tokens:` block. We parse the full file at HEAD and at
    working tree and compare everything except `tokens:`; if those are equal,
    the diff is tokens-only.

    Conservative: on parse failure, returns False (forces G_SCOPE fail; the
    caller should re-check manually).
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "show", f"HEAD:{index_path}"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    head_text = proc.stdout

    current_path = project_root / index_path
    if not current_path.is_file():
        return False
    try:
        current_text = current_path.read_text()
    except OSError:
        return False

    try:
        head_doc = yaml.safe_load(head_text) or {}
        current_doc = yaml.safe_load(current_text) or {}
    except yaml.YAMLError:
        return False
    if not isinstance(head_doc, dict) or not isinstance(current_doc, dict):
        return False

    head_no_tokens = {k: v for k, v in head_doc.items() if k != "tokens"}
    current_no_tokens = {k: v for k, v in current_doc.items() if k != "tokens"}
    return head_no_tokens == current_no_tokens


def check_G_SCOPE(declared_scope: str, project_root: Path) -> None:
    """G_SCOPE per design §7.2 pseudocode.

    Declared scopes (closed set): none | text_only | tokens_only.
    Any other value -> env error (caller passed a malformed scope).

    none        -> no .design-ledger/** or **/*.{html,css,js,tsx} may change.
    text_only   -> HTML/JSX files may change only in text-node positions
                   (no tag/attribute diff markers).
    tokens_only -> only .design-ledger/skeletons/index.yaml may change, and
                   only its `tokens:` block.

    False claim (diff contradicts declaration) -> exit 2 + `gate_false_pass`
    observation with fingerprint `scope-mismatch`.
    """
    project_root = project_root.resolve()

    if declared_scope not in DECLARED_SCOPE_CLOSED_SET:
        _gscope_env_error(
            f"declared_scope={declared_scope!r} not in "
            f"{sorted(DECLARED_SCOPE_CLOSED_SET)}"
        )

    try:
        changed_paths = _git_diff_name_only(project_root)
    except RuntimeError as e:
        _gscope_env_error(str(e))

    if declared_scope == "none":
        ui_touched = [p for p in changed_paths if _is_ui_path(p)]
        if ui_touched:
            preview = ", ".join(ui_touched[:5])
            suffix = "..." if len(ui_touched) > 5 else ""
            _gscope_fail(
                f"declared ui_scope:none but touched UI files: {preview}{suffix}",
                fingerprint="scope-mismatch",
            )
    elif declared_scope == "text_only":
        structural: List[str] = []
        for p in changed_paths:
            if not (p.endswith(".html") or p.endswith(".tsx")):
                # non-HTML/JSX file change under text_only is always fine here;
                # the declaration is scoped to structural UI changes only.
                continue
            diff_text = _git_diff_for_path(project_root, p)
            if _is_structural_diff(diff_text):
                structural.append(p)
        if structural:
            preview = ", ".join(structural[:5])
            suffix = "..." if len(structural) > 5 else ""
            _gscope_fail(
                f"declared text_only but structural diff in: {preview}{suffix}",
                fingerprint="scope-mismatch",
            )
    else:  # tokens_only
        index_path_str = ".design-ledger/skeletons/index.yaml"
        # Accept only the index.yaml file; any other file change is a false claim.
        non_index = [p for p in changed_paths if p != index_path_str]
        if non_index:
            preview = ", ".join(non_index[:5])
            suffix = "..." if len(non_index) > 5 else ""
            _gscope_fail(
                f"declared tokens_only but other files changed: {preview}{suffix}",
                fingerprint="scope-mismatch",
            )
        # If index.yaml itself is NOT in the diff, there's nothing to check —
        # the declaration is vacuously satisfied (zero changes).
        if index_path_str in changed_paths:
            if not _tokens_only_change(project_root, index_path_str):
                _gscope_fail(
                    f"declared tokens_only but {index_path_str} "
                    "changes extend beyond the tokens: block",
                    fingerprint="scope-mismatch",
                )

    sys.stdout.write(
        f"G_SCOPE_PASS: declared_scope={declared_scope!r} matches diff\n"
    )
    sys.exit(0)


# ---------------------------------------------------------------------------
# G_CONTRACT_SCOPE — S029 contract-scope-enforcement keystone (design §7.2/§9)
# ---------------------------------------------------------------------------
#
# Invoked by bob (eager / Q4) at every WP boundary AND at INTEGRATED→VERIFIED
# (TOCTOU re-check). Walks the workspace, classifies each path NOT in the
# frozen contract-map's declared_universe via the LOCKED extractor priority
# chain, writes scope_delta.v1 records under .ledger/scope-deltas/, and
# exits 2 with fingerprint `contract-scope-critical-undeclared` if any
# record has severity=critical AND status=undecided.
#
# declared_universe per design §7.1 / §9:
#     union(components[].source_paths)
#   + union(flows[].source_paths)        (v1 flows have no source_paths,
#                                         so this is currently empty —
#                                         union is forward-compat)
#   + excluded_paths
#
# PRECEDENCE (M4): if a path matches BOTH excluded_paths AND
# CONTRACT_SCOPE_CRITICAL_GLOBS, critical wins. Excluded_paths cannot mask
# critical artifacts.
#
# PRIORITY ORDER (M3): secret > db_migration > env_var > public_api >
# config_key > generated_artifact > file. Locked in extractors/__init__.py;
# this gate just calls extractors.first_match().


def _gcontract_scope_fail(message: str, *, count: int) -> None:
    """G_CONTRACT_SCOPE non-zero exit helper — `gate_false_pass` because the
    specialist's COMPLETE claim contradicts the frozen contract-map.
    Fingerprint dedups all critical-undeclared refusals together (alf can
    spot chronic recurrence)."""
    exit_with_observation(
        "G_CONTRACT_SCOPE",
        2,
        f"critical-undeclared:{count}",
        message,
        severity="blocking",
        category="gate_false_pass",
        fingerprint="contract-scope-critical-undeclared",
    )


def _gcontract_scope_env_error(message: str) -> None:
    exit_with_observation(
        "G_CONTRACT_SCOPE",
        3,
        "env",
        message,
        severity="degraded",
        category="external_tool_fail",
        fingerprint="G_CONTRACT_SCOPE-env",
    )


def _gcs_expand_path(p: str) -> str:
    """Normalise contract-map source_path string into a project-relative or
    absolute filesystem hint. Supports `~/...` (expanduser), absolute paths,
    or project-relative paths. Returned as-is for glob matching — the gate
    only cares about glob set membership, not filesystem existence."""
    if p.startswith("~"):
        return str(Path(p).expanduser())
    return p


def _gcs_glob_to_regex(pat: str) -> "re.Pattern":
    """Convert a glob with `**` (recursive) semantics into a compiled regex.

    Glob conventions honored:
        `**/` at the start  → zero-or-more dir segments
        `**` between slashes → zero-or-more dir segments (matches across /)
        `*`                 → any chars except `/`
        `?`                 → single char except `/`
    Anything else is escaped literally.
    """
    parts: List[str] = []
    i = 0
    while i < len(pat):
        ch = pat[i]
        # Handle `**` first.
        if ch == "*" and i + 1 < len(pat) and pat[i + 1] == "*":
            # Determine if it's `**/` or `/**` or standalone `**`.
            if i + 2 < len(pat) and pat[i + 2] == "/":
                # `**/`  → zero-or-more segments + slash, OR nothing
                parts.append(r"(?:.*/)?")
                i += 3
                continue
            else:
                # bare `**` or trailing `**` — match anything across /
                parts.append(r".*")
                i += 2
                continue
        if ch == "*":
            parts.append(r"[^/]*")
            i += 1
            continue
        if ch == "?":
            parts.append(r"[^/]")
            i += 1
            continue
        # Default — regex-escape the character.
        parts.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(parts) + "$")


def _gcs_glob_match(path: str, pat: str) -> bool:
    """Match `path` against a single glob `pat` with `**` semantics."""
    return bool(_gcs_glob_to_regex(pat).match(path))


def _gcs_in_universe(path: str, universe_globs: List[str]) -> bool:
    """True iff `path` matches at least one glob in the declared universe.

    Treats `**` as the recursive directory wildcard. Also accepts non-glob
    prefix matches (e.g., a tilde-expanded absolute path that names a
    specific file inside a subdir).
    """
    for g in universe_globs:
        if _gcs_glob_match(path, g):
            return True
        # Allow exact prefix match for non-glob declared paths.
        if "*" not in g and "?" not in g and "[" not in g:
            if path == g or path.startswith(g.rstrip("/") + "/"):
                return True
    return False


def _gcs_matches_critical(path: str) -> bool:
    """True iff `path` matches any glob in CONTRACT_SCOPE_CRITICAL_GLOBS."""
    for g in CONTRACT_SCOPE_CRITICAL_GLOBS:
        if _gcs_glob_match(path, g):
            return True
    return False


def _gcs_walk_workspace(project_root: Path) -> List[str]:
    """Walk the project filesystem and return project-relative paths.

    Skips dot-directories that are universally excluded (.git, .ledger,
    __pycache__, node_modules) at walk-time for performance. The full
    excluded_paths list is still consulted at classification time so the
    contract-map's declarations control what reaches scope_delta.

    The walk-time skip set is hard-coded (small, universally-excluded);
    excluded_paths from the map controls everything else.
    """
    SKIP_DIR_NAMES = {
        ".git", ".ledger", ".forge", ".design-ledger",
        "__pycache__", "node_modules", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache",
    }
    out: List[str] = []
    project_root = project_root.resolve()
    for root, dirs, files in os.walk(project_root, topdown=True):
        # Prune in-place for performance.
        dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES]
        for f in files:
            full = Path(root) / f
            try:
                rel = full.relative_to(project_root)
            except ValueError:
                continue
            out.append(str(rel))
    return out


def _gcs_load_contract_map(map_path: Path) -> Dict[str, Any]:
    if not map_path.is_file():
        _gcontract_scope_env_error(f"contract-map not found at {map_path}")
    try:
        return yaml.safe_load(map_path.read_text()) or {}
    except yaml.YAMLError as e:
        _gcontract_scope_env_error(f"contract-map unparseable: {e}")
    return {}


def _gcs_compute_declared_universe(map_yaml: Dict[str, Any]) -> List[str]:
    """declared_universe = union(components[].source_paths)
                         + union(flows[].source_paths)
                         + excluded_paths."""
    universe: List[str] = []
    for comp in map_yaml.get("components", []) or []:
        for sp in comp.get("source_paths", []) or []:
            universe.append(_gcs_expand_path(sp))
    for flow in map_yaml.get("flows", []) or []:
        # Forward-compat: v1 flows don't carry source_paths but the design
        # spec keeps the union edge open.
        for sp in flow.get("source_paths", []) or []:
            universe.append(_gcs_expand_path(sp))
    for ex in map_yaml.get("excluded_paths", []) or []:
        universe.append(ex)
    return universe


def _gcs_compute_critical_only_universe(map_yaml: Dict[str, Any]) -> List[str]:
    """Same as declared_universe but EXCLUDES excluded_paths.

    Used for the M4 precedence rule: a path that matches a critical glob
    is critical even if excluded_paths would otherwise mask it. The gate
    consults this universe before short-circuiting on excluded_paths so
    critical wins.
    """
    universe: List[str] = []
    for comp in map_yaml.get("components", []) or []:
        for sp in comp.get("source_paths", []) or []:
            universe.append(_gcs_expand_path(sp))
    for flow in map_yaml.get("flows", []) or []:
        for sp in flow.get("source_paths", []) or []:
            universe.append(_gcs_expand_path(sp))
    return universe


# ---------------------------------------------------------------------------
# Retro-scan baseline consultation (S029 spawn-4b defect-fix per design §7.5)
#
# Per design §7.5 paragraph 4: "Is this an advisory finding from baseline?
# Allow with logging." When `progress/retro-scan-S028.yaml` is present, the
# gate consults the baseline and adjusts emission as follows:
#
#   1. Path in baseline `pre_existing_critical` set AND op=="added"
#      (workspace-walk emits all paths as op="added" for v1)
#        → GRANDFATHER: do NOT emit a critical scope_delta record. The path
#          existed before S029 shipped; the baseline-allow rule applies.
#          v2-refinement (S030): if op∈{"changed","removed"} for a baseline-
#          critical path, emit critical (modification of pre-existing
#          critical resource is still a scope change).
#   2. Path in baseline `pre_existing_advisory` set
#        → emit advisory record but mark severity stays advisory and the
#          record carries the baseline marker (informational only). Same
#          severity classification as today; baseline membership is
#          recorded in extractor_meta for audit trail.
#   3. Path NOT in baseline AND matches CONTRACT_SCOPE_CRITICAL_GLOBS
#        → emit critical (current Q2 #3 behavior — block; new artifact
#          introduced post-baseline is still a scope change).
#   4. Path NOT in baseline AND no critical-glob match
#        → emit advisory (current behavior — non-blocking).
#
# v1 limitation (Q2 #4): the workspace-walk gate cannot distinguish "added"
# from "changed" without a git diff. For v1 we treat all walked paths as
# op="added" and grandfather every baseline-critical path. Synthetic-delta
# tests exercise the op="changed" branch via direct helper invocation.
# Refinement to git-aware diffing is S030 work.
#
# Safety:
#   * Missing baseline file → no-consultation; behavior identical to today.
#   * Malformed YAML → no-consultation; warning to stderr; do not crash.
#   * `contract_map_hash` mismatch with live map → no-consultation; warning
#     to stderr (baseline is stale; user should re-run retro-scan).
# ---------------------------------------------------------------------------

RETRO_SCAN_RELPATH = "progress/retro-scan-S028.yaml"


def _gcs_load_baseline(
    project_root: Path,
    contract_map_hash: str,
) -> Dict[str, Any]:
    """Load `progress/retro-scan-S028.yaml` and return a dict with keys:

        {
          "present": bool,                # True iff file exists and parses
          "stale":   bool,                # True iff hash mismatch with live map
          "critical_paths": set[str],     # paths classified pre_existing_critical
          "advisory_paths": set[str],     # paths classified pre_existing_advisory
        }

    On any error (missing file, malformed YAML, hash mismatch with live
    map, schema issues) the helper falls back safely: returns
    `present=False` (no-consultation) and emits one stderr warning. The
    gate never crashes on baseline issues.

    `contract_map_hash` is the LIVE contract-map hash (sha256:<hex>) the
    gate computed from `map_path.read_bytes()`. The baseline pins
    `contract_map_hash` at scan time; mismatch → baseline is stale
    relative to the current map and should not be consulted (operator
    should re-run retro-scan after any contract-map amendment).
    """
    empty = {
        "present": False,
        "stale": False,
        "critical_paths": set(),
        "advisory_paths": set(),
    }
    baseline_path = project_root / RETRO_SCAN_RELPATH
    if not baseline_path.is_file():
        return empty
    try:
        data = yaml.safe_load(baseline_path.read_text())
    except yaml.YAMLError as e:
        sys.stderr.write(
            f"G_CONTRACT_SCOPE: baseline {baseline_path} unparseable "
            f"({e}); falling back to no-consultation.\n"
        )
        return empty
    if not isinstance(data, dict):
        sys.stderr.write(
            f"G_CONTRACT_SCOPE: baseline {baseline_path} not a dict; "
            f"falling back to no-consultation.\n"
        )
        return empty
    if data.get("schema_version") != "retro_scan.v1":
        sys.stderr.write(
            f"G_CONTRACT_SCOPE: baseline {baseline_path} schema_version "
            f"!= retro_scan.v1; falling back to no-consultation.\n"
        )
        return empty
    # Hash binding: stale baseline → no-consultation.
    baseline_hash = data.get("contract_map_hash")
    if baseline_hash and baseline_hash != contract_map_hash:
        sys.stderr.write(
            f"G_CONTRACT_SCOPE: baseline contract_map_hash {baseline_hash} "
            f"!= live {contract_map_hash}; falling back to no-consultation.\n"
        )
        return {**empty, "stale": True}
    crit: set = set()
    adv: set = set()
    # Top-level baseline_critical_paths is the canonical critical list
    # per design §7.5 (Q2 #4 enforcement list).
    for p in data.get("baseline_critical_paths", []) or []:
        if isinstance(p, str):
            crit.add(p)
    # findings[] inside each component bucket is the canonical finding list;
    # for v1 attribution all findings are placed under the first bucket
    # (per scan.py docstring), but we walk every bucket to be robust.
    for comp in data.get("components", []) or []:
        for f in (comp or {}).get("findings", []) or []:
            if not isinstance(f, dict):
                continue
            path = f.get("path")
            sev = f.get("severity")
            if not isinstance(path, str):
                continue
            if sev == "pre_existing_critical":
                crit.add(path)
            elif sev == "pre_existing_advisory":
                adv.add(path)
    return {
        "present": True,
        "stale": False,
        "critical_paths": crit,
        "advisory_paths": adv,
    }


def _gcs_classify_against_baseline(
    path: str,
    operation: str,
    baseline_critical: set,
    baseline_advisory: set,
) -> str:
    """Classify a candidate scope_delta against baseline membership.

    Returns one of:
        "grandfather"       → do not emit a record; pre-existing critical,
                              op="added" (Q2 #4: modification still blocks)
        "block_modification"→ emit critical; baseline-critical path was
                              modified (op∈{"changed","removed"})
        "advisory_baseline" → emit advisory, baseline-marker; pre-existing
                              advisory (informational only)
        "block_new_critical"→ emit critical; not in baseline + critical-glob
        "advisory_new"      → emit advisory; not in baseline + no critical-glob

    The two "block_*" outcomes are the Q2 #3/#4 enforcement paths.
    The "grandfather"/"advisory_baseline" outcomes are the §7.5 baseline
    relief valves.

    `operation` is one of OPERATIONS = ("added", "removed", "changed").
    Caller decides whether to honor critical-glob match independently
    (this helper takes that decision as already-made via signature; it
    only handles the baseline-membership branch).
    """
    if path in baseline_critical:
        if operation == "added":
            return "grandfather"
        # op∈{"changed","removed"} → modification of pre-existing critical
        # resource is still a scope change. Q2 #4 enforces this.
        return "block_modification"
    if path in baseline_advisory:
        return "advisory_baseline"
    # Not in baseline → caller's existing critical-glob decision applies.
    # Helper does not duplicate that logic; sentinel value tells caller
    # to fall through to its existing classification path.
    return "no_baseline_match"


def check_G_CONTRACT_SCOPE(
    project_root: Path,
    map_path: Path,
    requesting_wp: str,
    detection_point: str,
) -> None:
    """G_CONTRACT_SCOPE per design §7.2 / §9.

    Steps:
      1. Load frozen contract-map.yaml (env-error on missing/parse-fail).
      2. Compute declared_universe (components + flows + excluded_paths).
      3. Walk workspace; for each path NOT in declared_universe (with M4
         precedence: critical globs override excluded_paths):
           a. Classify ArtifactKind via extractors.first_match (LOCKED M3
              priority chain).
           b. Severity = critical iff path matches CONTRACT_SCOPE_CRITICAL_GLOBS,
              else advisory.
           c. Write scope_delta.v1 record (status=undecided).
      4. Exit 0 if no critical undecided records were written.
         Exit 2 (fingerprint=contract-scope-critical-undeclared) if any
         critical undecided records were written.

    Side effects: writes scope_delta records to project_root/.ledger/scope-deltas/.
    Never modifies contract-map.yaml. Bob is the sole consumer of the records.
    """
    project_root = project_root.resolve()

    if detection_point not in ("wp_boundary", "integrated_to_verified"):
        _gcontract_scope_env_error(
            f"detection_point must be wp_boundary|integrated_to_verified, got {detection_point!r}"
        )
    if not requesting_wp:
        _gcontract_scope_env_error("requesting_wp must be non-empty")

    # Load the map and compute declared_universe.
    map_yaml = _gcs_load_contract_map(map_path)
    declared_universe = _gcs_compute_declared_universe(map_yaml)
    critical_only_universe = _gcs_compute_critical_only_universe(map_yaml)

    contract_map_revision = int(map_yaml.get("revision", 0))
    map_hash = hashlib.sha256(map_path.read_bytes()).hexdigest()
    contract_map_hash = f"sha256:{map_hash}"

    # Local imports to avoid any startup cost when the gate isn't invoked.
    import extractors as _extractors  # noqa: E402
    import scope_delta as _scope_delta  # noqa: E402

    # S030 #61: per-invocation dedup. Build the set of pre-existing undecided
    # records ONCE so we can skip re-emitting on every invocation.
    # Dedup key is (path, content_hash, severity). A change in any field
    # (e.g. file mutated, severity escalated, status moved off-undecided)
    # MUST produce a fresh record.
    existing_undecided_keys: set = set()
    for _rec in _scope_delta.read_records(project_root, status_filter="undecided"):
        existing_undecided_keys.add((
            _rec.get("path"),
            _rec.get("content_hash"),
            _rec.get("severity"),
        ))

    # Walk the workspace.
    actual_paths = _gcs_walk_workspace(project_root)

    # Spawn-4b: load retro-scan-S028 baseline (design §7.5 paragraph 4).
    # On missing/malformed/stale baseline, the helper returns present=False
    # and the gate behaves identically to today (no-consultation).
    baseline = _gcs_load_baseline(project_root, contract_map_hash)
    baseline_critical: set = baseline["critical_paths"]
    baseline_advisory: set = baseline["advisory_paths"]
    baseline_present: bool = baseline["present"]

    critical_records: List[str] = []
    advisory_records: List[str] = []

    for rel in actual_paths:
        is_critical_match = _gcs_matches_critical(rel)
        if is_critical_match:
            # M4 PRECEDENCE: a critical-glob path is "in declared" only if
            # it appears in components[].source_paths or flows[].source_paths.
            # excluded_paths cannot mask it.
            if _gcs_in_universe(rel, critical_only_universe):
                continue
        else:
            # Non-critical paths can be excluded normally.
            if _gcs_in_universe(rel, declared_universe):
                continue

        # Path is undeclared. Classify via extractor priority chain.
        # v1: workspace-walk emits all paths as op="added".
        delta = _extractors.first_match(project_root, rel, "added")
        if delta is None:
            # Should never happen — file extractor is catch-all.
            continue

        # Spawn-4b baseline consultation (design §7.5).
        # Only consulted when baseline is present + non-stale; otherwise
        # behavior is identical to pre-spawn-4b.
        baseline_outcome = "no_baseline_match"
        if baseline_present:
            baseline_outcome = _gcs_classify_against_baseline(
                rel, delta.operation, baseline_critical, baseline_advisory,
            )
            if baseline_outcome == "grandfather":
                # Pre-existing critical, op="added" → §7.5 baseline-allow.
                # Do not emit a record. The path was present at S029
                # baseline freeze; the user has implicitly accepted it.
                # An audit-trail observation is preferable but the
                # in-process scope-delta ledger is append-only and the
                # baseline file itself is the authoritative audit trail.
                continue

        severity = "critical" if is_critical_match else "advisory"
        record = {
            "delta_id": _scope_delta.new_delta_id(),
            "schema_version": "scope_delta.v1",
            "created_at": _scope_delta._now_iso(),
            "created_by": "G_CONTRACT_SCOPE",
            "project_root": str(project_root),
            "contract_map_hash": contract_map_hash,
            "contract_map_revision": contract_map_revision,
            "artifact_kind": delta.kind,
            "operation": delta.operation,
            "path": delta.path,
            "content_hash": delta.content_hash,
            "contract_ref": None,
            "consumer_refs": [],
            "severity": severity,
            "requesting_wp": requesting_wp,
            "detection_point": detection_point,
            "status": "undecided",
            "extractor_meta": dict(delta.extractor_meta or {}),
        }
        # Mark baseline-derived records via extractor_meta (informational).
        if baseline_outcome == "advisory_baseline":
            record["extractor_meta"]["baseline_marker"] = "pre_existing_advisory"
        elif baseline_outcome == "block_modification":
            # Q2 #4 (v1 unreachable via workspace-walk; reached only via
            # synthetic-delta tests). Severity stays critical.
            record["extractor_meta"]["baseline_marker"] = (
                "pre_existing_critical_modified"
            )
        if severity == "critical":
            record["critical_reason"] = (
                f"path matches CONTRACT_SCOPE_CRITICAL_GLOBS and is not in "
                f"components[].source_paths or flows[].source_paths"
            )

        # S030 #61: per-invocation dedup. If an undecided record with the
        # same (path, content_hash, severity) already exists, skip emission.
        # Only `undecided` records dedupe — excluded/amended records are
        # intentionally NOT dedup keys (re-emit so the user sees them
        # again if the situation re-arises post-resolution).
        dedup_key = (record["path"], record["content_hash"], record["severity"])
        if dedup_key in existing_undecided_keys:
            # Already-undecided record covers this finding. Track it so the
            # exit-code calculation still treats critical as blocking.
            if severity == "critical":
                critical_records.append("dedup:" + record["path"])
            else:
                advisory_records.append("dedup:" + record["path"])
            continue

        try:
            _scope_delta.write_record(project_root, record)
        except FileExistsError:
            # Duplicate delta-id (extremely unlikely with timestamp+hex);
            # mint a fresh one and retry once.
            record["delta_id"] = _scope_delta.new_delta_id()
            _scope_delta.write_record(project_root, record)

        # Add the new record's key so subsequent iterations within this
        # same invocation also dedupe (defense-in-depth; the workspace walk
        # is unique-on-path so this is informational).
        existing_undecided_keys.add(dedup_key)

        if severity == "critical":
            critical_records.append(record["delta_id"])
        else:
            advisory_records.append(record["delta_id"])

    # Always print a structured one-line summary so callers can parse.
    summary = (
        f"G_CONTRACT_SCOPE summary: critical_undecided={len(critical_records)} "
        f"advisory_undecided={len(advisory_records)} "
        f"requesting_wp={requesting_wp} detection_point={detection_point} "
        f"map_revision={contract_map_revision}"
    )

    if critical_records:
        # Echo the critical delta IDs to stdout for bob to consume.
        for did in critical_records:
            sys.stdout.write(
                f"G_CONTRACT_SCOPE_CRITICAL: {did}\n"
            )
        # Then fail through the observation pipeline.
        _gcontract_scope_fail(summary, count=len(critical_records))

    sys.stdout.write(f"G_CONTRACT_SCOPE_PASS: {summary}\n")
    sys.exit(0)


# ---------------------------------------------------------------------------
# G_DEP_CURRENCY — dependency currency + CVE check gate (2026-05-12)
#
# Wraps `python3 -m dep_currency_check` and maps CLI exit code to gate exit
# code. STRICT blocking criteria (gate fails ONLY if ALL met):
#   - severity == "critical"
#   - is_direct (not transitive)
#   - is_dev == false (production dep)
#   - cve.fixed_versions non-empty (a fix is available)
#   - AND --mode strict (advisory mode never blocks)
# ---------------------------------------------------------------------------


def check_G_DEP_CURRENCY(
    project_root: Path,
    *,
    mode: str = "advisory",
    changed_manifests: str = "",
    allow_deferred: bool = False,
) -> None:
    """Run dep-currency-check and exit 0/2/3/4 per gate contract."""
    import subprocess  # local import — keep gates.py import-light
    skill_root = Path.home() / ".claude" / "skills" / "dep-currency-check" / "dep_currency_check"
    if not skill_root.is_dir():
        env_error(
            f"dep-currency-check skill not installed at {skill_root}"
        )
    # Build the dep_currency_check CLI invocation
    cmd = [
        sys.executable, "-m", "dep_currency_check",
        str(project_root),
        "--format", "json",
        "--severity", "critical",  # gate only cares about critical
        "--mode", mode,
        "--quiet",
    ]
    if changed_manifests:
        cmd.extend(["--changed-manifests", changed_manifests])
    if allow_deferred:
        cmd.append("--allow-deferred")

    # Ensure dep_currency_check is importable. The skill ships a
    # `dep_currency_check` symlink → `scripts/` at the skill root for
    # `python3 -m dep_currency_check` to work.
    env = os.environ.copy()
    skill_root_dir = str(skill_root.parent)  # ~/.claude/skills/dep-currency-check/
    env["PYTHONPATH"] = (
        skill_root_dir + os.pathsep + env.get("PYTHONPATH", "")
    )
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=180, check=False, env=env,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        env_error(f"dep_currency_check subprocess failed: {e}")
        return  # unreachable; env_error exits

    rc = proc.returncode
    if rc == 0:
        ok("G_DEP_CURRENCY",
            "no critical findings in production direct deps")
    elif rc == 1:
        fail(
            "G_DEP_CURRENCY",
            "critical CVE in production direct dep with fix available "
            f"(stdout truncated: {proc.stdout[:200]})"
        )
    elif rc == 2:
        # Soft findings only; advisory mode — don't fail
        ok("G_DEP_CURRENCY",
            "soft findings only (advisory mode, never blocks)")
    elif rc == 4:
        if allow_deferred:
            ok("G_DEP_CURRENCY",
                "offline + cold cache, deferred allowed")
        else:
            sys.stderr.write(
                "G_DEP_CURRENCY_DEFERRED: offline + cold cache; "
                "retry online or pass --allow-deferred\n"
            )
            sys.exit(4)
    elif rc == 3:
        env_error(
            f"dep_currency_check environmental error: "
            f"{proc.stderr[:300] or 'unknown'}"
        )
    else:
        env_error(
            f"dep_currency_check unexpected rc={rc}: "
            f"stdout={proc.stdout[:200]!r} stderr={proc.stderr[:200]!r}"
        )


# ---------------------------------------------------------------------------
# G_INTENT_MAP_FRESH — evo's intent-map staleness gate (S032)
#
# Verifies that the per-run intent-map.yaml is still bound to the current
# wiring snapshot and dependency lockfile. Three-way exit (per design §4.2):
#
#   0 = PASS    — intent_map fresh; safe to consume in mode-b/c APPLYING
#   2 = FAIL    — file missing OR hash mismatch (intent-map.yaml exists but
#                 either wiring_hash or dep_lock_hash drifted from current
#                 .wiring/latest.json / resolved lockfile)
#   3 = ENV_ERROR — referenced inputs missing (no .wiring/latest.json, no
#                 lockfile to compute against); auto-rewind trigger for evo
#
# In mode-a (intent-map-only), evo treats FAIL/ENV_ERROR as advisory.
# In modes b/c, FAIL blocks APPLYING; ENV_ERROR triggers auto-rewind to
# ANALYZED phase (preserves consult-log decisions for still-applicable
# deltas — see design §6.1).
#
# CLI: gates.py G_INTENT_MAP_FRESH <project_root> <run_id>
#                                  [--lockfile <path>]   # explicit lockfile
# ---------------------------------------------------------------------------


_LOCKFILE_CANDIDATES = (
    # Python
    "poetry.lock", "uv.lock", "Pipfile.lock", "requirements.lock",
    "requirements.txt",
    # JavaScript / TypeScript
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    # Rust / Go / Ruby / Java
    "Cargo.lock", "go.sum", "Gemfile.lock", "pom.xml", "build.gradle.lock",
)


def _resolve_lockfile(project_root: Path, explicit: Optional[Path] = None) -> Optional[Path]:
    """Return the first lockfile under project_root, or None.

    If `explicit` is given, only that file is checked.
    """
    if explicit is not None:
        return explicit if explicit.is_file() else None
    for name in _LOCKFILE_CANDIDATES:
        candidate = project_root / name
        if candidate.is_file():
            return candidate
    return None


def _file_sha256(path: Path) -> str:
    """Return sha256 hex of a file's bytes (deterministic, no-mmap)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def check_G_INTENT_MAP_FRESH(
    project_root: Path,
    run_id: str,
    *,
    explicit_lockfile: Optional[Path] = None,
) -> None:
    """Implement G_INTENT_MAP_FRESH per design §4.2.

    Exit codes:
      0 PASS  — intent_map present, both hashes match current snapshot+lock
      2 FAIL  — hash drift OR intent-map.yaml missing
      3 ENV_ERROR — referenced inputs missing (auto-rewind trigger)
    """
    if not project_root.is_dir():
        env_error(f"G_INTENT_MAP_FRESH: project_root not a directory: {project_root}")

    intent_map_path = (
        project_root
        / ".ledger"
        / "evo"
        / "runs"
        / run_id
        / "intent-map.yaml"
    )
    if not intent_map_path.is_file():
        fail(
            "G_INTENT_MAP_FRESH",
            f"intent-map.yaml not found at {intent_map_path}",
        )

    try:
        intent_map = yaml.safe_load(intent_map_path.read_text()) or {}
    except yaml.YAMLError as e:
        fail("G_INTENT_MAP_FRESH", f"intent-map.yaml parse error: {e}")

    if not isinstance(intent_map, dict):
        fail(
            "G_INTENT_MAP_FRESH",
            f"intent-map.yaml top-level must be a mapping, got {type(intent_map).__name__}",
        )

    # Hashes we expect the map to carry. Per design §5.5 evo-manifest.v1
    # also has these, but the intent-map.yaml is the gate-checked artifact
    # at consumption time.
    declared_wiring_hash = intent_map.get("wiring_hash")
    declared_dep_lock_hash = intent_map.get("dep_lock_hash")

    if not declared_wiring_hash:
        fail(
            "G_INTENT_MAP_FRESH",
            "intent-map.yaml missing required field: wiring_hash",
        )
    if not declared_dep_lock_hash:
        fail(
            "G_INTENT_MAP_FRESH",
            "intent-map.yaml missing required field: dep_lock_hash",
        )

    # Resolve current wiring snapshot.
    wiring_latest = project_root / ".wiring" / "latest.json"
    if not wiring_latest.is_file():
        env_error(
            f"G_INTENT_MAP_FRESH: .wiring/latest.json not found at "
            f"{wiring_latest}; cannot verify wiring_hash. Auto-rewind to "
            f"ANALYZED recommended."
        )

    try:
        wiring_data = json.loads(wiring_latest.read_text())
    except (json.JSONDecodeError, OSError) as e:
        env_error(
            f"G_INTENT_MAP_FRESH: .wiring/latest.json unreadable: {e}; "
            f"auto-rewind recommended."
        )

    # Workspace_tree_hash is the canonical comparator per wiring-snapshot.v1
    # schema (see schemas/wiring-snapshot.v1.json — required pattern
    # ^[a-f0-9]{40}$). If the snapshot uses a different attribute name we
    # fall back to a content hash of the file itself.
    current_wiring_hash = wiring_data.get("workspace_tree_hash") or _file_sha256(wiring_latest)

    if declared_wiring_hash != current_wiring_hash:
        fail(
            "G_INTENT_MAP_FRESH",
            f"wiring_hash drift: intent-map declares "
            f"{declared_wiring_hash[:16]}... but current "
            f"{current_wiring_hash[:16]}... (run wiring-extract-static and "
            f"intent-extract again)",
        )

    # Resolve current lockfile.
    lockfile = _resolve_lockfile(project_root, explicit_lockfile)
    if lockfile is None:
        env_error(
            "G_INTENT_MAP_FRESH: no lockfile found under project_root; "
            "tried "
            + ", ".join(_LOCKFILE_CANDIDATES)
            + ". Auto-rewind recommended."
        )

    current_dep_lock_hash = _file_sha256(lockfile)
    if declared_dep_lock_hash != current_dep_lock_hash:
        fail(
            "G_INTENT_MAP_FRESH",
            f"dep_lock_hash drift: intent-map declares "
            f"{declared_dep_lock_hash[:16]}... but current "
            f"{current_dep_lock_hash[:16]}... at {lockfile.name} "
            f"(deps changed since intent-extract; re-run intent-extract)",
        )

    ok(
        "G_INTENT_MAP_FRESH",
        f"intent-map.yaml at run={run_id} bound to wiring "
        f"{current_wiring_hash[:16]}... and lockfile {lockfile.name} "
        f"{current_dep_lock_hash[:16]}...",
    )


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------


def _parse_args(argv: List[str]) -> Tuple[str, List[str], Dict[str, str]]:
    if len(argv) < 2:
        env_error(
            "usage: gates.py "
            "G1|G2|G3|G4|G_V|G_XR|G_SCOPE|G_CONTRACT_SCOPE|G_DEP_CURRENCY|"
            "G_INTENT_MAP_FRESH ..."
        )
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
        if a == "--strict":
            flags["g4_mode"] = "strict"
            i += 1
            continue
        if a == "--advisory":
            flags["g4_mode"] = "advisory"
            i += 1
            continue
        if a == "--wp":
            if i + 1 >= len(argv):
                env_error("--wp requires a value")
            flags["wp"] = argv[i + 1]
            i += 2
            continue
        if a == "--detection-point":
            if i + 1 >= len(argv):
                env_error("--detection-point requires a value")
            flags["detection_point"] = argv[i + 1]
            i += 2
            continue
        if a == "--map":
            # Optional flag form for G_CONTRACT_SCOPE if caller prefers it
            # over positional; positional path still takes precedence.
            if i + 1 >= len(argv):
                env_error("--map requires a value")
            flags["map"] = argv[i + 1]
            i += 2
            continue
        if a == "--mode":
            # G_DEP_CURRENCY mode (advisory|strict)
            if i + 1 >= len(argv):
                env_error("--mode requires a value")
            flags["dep_currency_mode"] = argv[i + 1]
            i += 2
            continue
        if a == "--changed-manifests":
            # G_DEP_CURRENCY: comma-separated paths
            if i + 1 >= len(argv):
                env_error("--changed-manifests requires a value")
            flags["dep_currency_changed"] = argv[i + 1]
            i += 2
            continue
        if a == "--allow-deferred":
            flags["dep_currency_allow_deferred"] = "1"
            i += 1
            continue
        if a == "--lockfile":
            # G_INTENT_MAP_FRESH: explicit lockfile path override
            if i + 1 >= len(argv):
                env_error("--lockfile requires a value")
            flags["intent_map_lockfile"] = argv[i + 1]
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
    elif gate == "G4":
        if len(positional) < 1:
            env_error("G4 requires <project_dir>")
        project_dir = Path(positional[0]).resolve()
        mode = flags.get("g4_mode", "strict")
        result = check_G4(project_dir, mode=mode)
        # Map structured result to exit codes
        status = result.get("status")
        if status == "pass":
            sys.stdout.write(f"G4_PASS: {result.get('message', '')}\n")
            sys.exit(0)
        elif status == "advisory":
            sys.stdout.write(f"G4_ADVISORY: {result.get('message', '')}\n")
            for v in result.get("violations", []):
                sys.stdout.write(f"  {v['rule']}: {v['message']}\n")
            sys.exit(3)
        elif status == "ledger_missing":
            sys.stderr.write(f"G4_SKIP: {result.get('message', '')}\n")
            sys.exit(4)
        else:  # fail
            sys.stderr.write(f"G4_FAIL: {result.get('message', '')}\n")
            for v in result.get("violations", []):
                sys.stderr.write(f"  {v['rule']}: {v['message']}\n")
            sys.exit(2)
    elif gate == "G_V":
        if len(positional) < 1:
            env_error("G_V requires <impl_hash>")
        impl_hash = positional[0]
        project_root = Path(flags.get("project_root", os.getcwd())).resolve()
        check_G_V(impl_hash, project_root)
    elif gate == "G_XR":
        project_root = Path(flags.get("project_root", os.getcwd())).resolve()
        check_G_XR(project_root)
    elif gate == "G_SCOPE":
        if len(positional) < 1:
            env_error("G_SCOPE requires <declared_scope>")
        declared_scope = positional[0]
        project_root = Path(flags.get("project_root", os.getcwd())).resolve()
        check_G_SCOPE(declared_scope, project_root)
    elif gate == "G_CONTRACT_SCOPE":
        # CLI: gates.py G_CONTRACT_SCOPE <project_root> <map_path>
        #                                  --wp <wp_id>
        #                                  --detection-point wp_boundary|integrated_to_verified
        if len(positional) < 2:
            env_error(
                "G_CONTRACT_SCOPE requires <project_root> <map_path>"
            )
        project_root = Path(positional[0]).resolve()
        map_path = Path(positional[1]).resolve()
        requesting_wp = flags.get("wp", "")
        detection_point = flags.get("detection_point", "wp_boundary")
        check_G_CONTRACT_SCOPE(
            project_root, map_path, requesting_wp, detection_point
        )
    elif gate == "G_INTENT_MAP_FRESH":
        # CLI: gates.py G_INTENT_MAP_FRESH <project_root> <run_id>
        #                                  [--lockfile <path>]
        # Exit codes:
        #   0 = pass
        #   2 = fail (hash drift / file missing)
        #   3 = environmental (auto-rewind trigger)
        if len(positional) < 2:
            env_error(
                "G_INTENT_MAP_FRESH requires <project_root> <run_id>"
            )
        project_root = Path(positional[0]).resolve()
        run_id = positional[1]
        explicit_lockfile: Optional[Path] = None
        if "intent_map_lockfile" in flags:
            explicit_lockfile = Path(flags["intent_map_lockfile"]).resolve()
        check_G_INTENT_MAP_FRESH(
            project_root, run_id, explicit_lockfile=explicit_lockfile
        )
    elif gate == "G_DEP_CURRENCY":
        # CLI: gates.py G_DEP_CURRENCY <project_root>
        #                                 [--mode advisory|strict]
        #                                 [--changed-manifests <list>]
        #                                 [--allow-deferred]
        # Exit codes:
        #   0 = pass (no findings meeting strict criteria, OR --mode advisory)
        #   2 = fail (strict criteria met: critical CVE in production direct
        #             dep with known fix AND --mode strict)
        #   3 = environmental error
        #   4 = deferred-only findings (offline + cold cache for required packages)
        if len(positional) < 1:
            env_error("G_DEP_CURRENCY requires <project_root>")
        project_root = Path(positional[0]).resolve()
        mode = flags.get("dep_currency_mode", "advisory")
        changed = flags.get("dep_currency_changed", "")
        allow_deferred = "dep_currency_allow_deferred" in flags
        check_G_DEP_CURRENCY(
            project_root, mode=mode, changed_manifests=changed,
            allow_deferred=allow_deferred,
        )
    else:
        env_error(f"unknown gate: {gate}")


if __name__ == "__main__":
    main()
