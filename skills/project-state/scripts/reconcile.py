#!/usr/bin/env python3
"""reconcile.py — project-state reconcile generator (WP-11 of S028 ecosystem-keystone).

Per design docs/plans/2026-04-23-ecosystem-keystone-design.md section 3.3 (13-step
lifecycle) + 3.4 (hash-first freshness) + 3.8 (self-reports 5 observation classes).

This mirrors wiring-reconcile/scripts/run.py EXACTLY (as spec says) with the
five key differences:

  1. Sources = 6 ledgers (contract-map.yaml, .wiring/latest.json,
     .design-ledger/skeletons/**/*.yaml, progress/flows.yaml,
     progress/integration-ledger.md, .process-observations/active.yaml)
  2. Output = a projection keyed by URI, not an edge snapshot.
  3. Signed fields = (projection_id, projection_generation, generated_at,
     generated_from) per section 3.2.
  4. Idempotent-no-op path when EVERY (path, hash) pair matches existing
     .project-state/latest.json.generated_from[].
  5. Self-emits process-observations for impossible states (circular dep,
     missing file, unresolved URI, reconcile >5s, HMAC fail).

CLI:
    python3 reconcile.py --project-root DIR
        [--claim-uuid UUID]
        [--force]
        [--skip-heartbeat] [--skip-claim-check]  # for tests
        [--log-level INFO]

This script is pure deterministic Python. NO LLM calls.

CB4 boundary: writes ONLY to `.project-state/runs/<run_id>/projection.json`
and `.ledger/requests/<claim_uuid>.request.yaml`. Bob-the-promoter copies the
run output to `.project-state/latest.json` under `.promote.lock` — skill does
NOT write latest.json.

Drift canary: ALDEBARAN-7.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Import discipline: _meta lives at ~/.claude/skills/_meta/
# We run this script either from the installed location or the staging
# location (/path/to/project/skills/project-state/...). In both
# cases, the shared primitives live at ~/.claude/skills/_meta/.
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent

_META_CANDIDATES = [
    Path.home() / ".claude" / "skills" / "_meta",
    SKILL_ROOT.parent / "_meta",  # staging layout
]
for _p in _META_CANDIDATES:
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    import yaml
except ImportError as _e:  # pragma: no cover
    raise ImportError("project-state reconcile requires pyyaml") from _e

try:
    from trusted_runner import atomic_write_bytes  # type: ignore
except Exception:  # pragma: no cover
    # Fallback so tests that install only pyyaml still work. Matches
    # process-observation's fallback contract.
    import tempfile

    def atomic_write_bytes(path: Path, data: bytes) -> None:  # type: ignore
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, str(path))
        except BaseException:
            try:
                Path(tmp_name).unlink()
            except FileNotFoundError:
                pass
            raise


# URI resolver + observation writer are imported lazily so reconcile can run
# in minimal test envs. See _load_uri() / _claude_observe() below.

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_NAME = "project-state.v1"
GENERATED_BY = "project-state@1.0.0"

# Exact paths that constitute the freshness contract (section 3.2
# generated_from[]). Order matters only for human readability; hash-compare
# is by path string.
SOURCE_PATHS: Tuple[str, ...] = (
    "progress/contract-map.yaml",
    ".wiring/latest.json",
    "progress/flows.yaml",
    "progress/integration-ledger.md",
    ".process-observations/active.yaml",
)
# Skeleton ledgers are glob-matched dynamically (index.yaml + per-screen files).
SKELETON_GLOB = ".design-ledger/skeletons/*.yaml"

# Entry-point tags (section 5.4) — entities reachable from these are NOT
# orphans, irrespective of call-graph reachability.
ENTRY_POINT_TAGS: frozenset = frozenset({
    "cron", "webhook", "cli", "api_public", "test_harness", "migration",
})

# S014 stage taxonomy per D9
STAGES: Tuple[str, ...] = (
    "PLANNED", "DRAFT", "APPROVED", "WIP", "IN_REVIEW", "VERIFIED",
)
MODIFIERS: Tuple[str, ...] = ("TBC", "BLOCKED", "CHALLENGED", "SKIPPED", "RETIRED")

# Wallclock defense-in-depth (D10 MODIFIED) — read from _meta/config.yaml
# if present, else fall back to 60s. Hash-match is primary; wallclock only
# catches `cp -p` edge where bytes are stable but metadata was changed.
DEFAULT_FRESHNESS_WINDOW_S = 60

# Soft SLA for reconcile latency — over this emits external_tool_slow
# observation per section 3.8.
RECONCILE_SOFT_SLA_S = 5.0

# Drift canary.
DRIFT_CANARY = "ALDEBARAN-7"


# ---------------------------------------------------------------------------
# Helpers: time + hashing + canonical JSON
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_json_bytes(obj: Any) -> bytes:
    return _canonical_json(obj).encode("utf-8")


def _file_hash(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Lazy imports for optional primitives
# ---------------------------------------------------------------------------

def _load_uri():
    """Return uri module or None on failure (keeps reconcile resilient)."""
    try:
        import uri as _uri  # type: ignore
        return _uri
    except Exception:
        return None


def _claude_observe(
    category: str,
    subject_id: str,
    what_happened: str,
    *,
    severity: str = "degraded",
    project_root: Optional[Path] = None,
    **kwargs: Any,
) -> None:
    """Fail-open observation writer. Never raises."""
    try:
        # Try to locate process-observation.write.claude_observe.
        po_candidates = [
            Path.home() / ".claude" / "skills" / "process-observation" / "scripts",
            SKILL_ROOT.parent / "process-observation" / "scripts",
        ]
        for cand in po_candidates:
            if cand.is_dir() and str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
        import write as _po_write  # type: ignore
        _po_write.claude_observe(
            category,
            subject_id,
            what_happened,
            severity=severity,
            project_root_override=project_root,
            **kwargs,
        )
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(
            f"project-state:claude_observe_fail: {type(e).__name__}: {e}\n"
        )


# ---------------------------------------------------------------------------
# Heartbeat thread — mirrors wiring-reconcile/scripts/run.py::HeartbeatThread
# ---------------------------------------------------------------------------

class HeartbeatThread(threading.Thread):
    """60s poll; stop skill on non-ok claim status."""

    def __init__(
        self,
        claim_uuid: str,
        project_root: Path,
        on_stop,
        interval_s: float = 60.0,
    ) -> None:
        super().__init__(daemon=True)
        self.claim_uuid = claim_uuid
        self.project_root = project_root
        self.on_stop = on_stop
        self.interval_s = interval_s
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # pragma: no cover - exercised via integration
        try:
            import claims as _claims  # type: ignore
        except ImportError:
            return
        while not self._stop.wait(self.interval_s):
            try:
                state = _claims.heartbeat_claim(self.claim_uuid, self.project_root)
            except Exception:
                state = "expired"
            if state != "ok":
                self.on_stop(state)
                return


# ---------------------------------------------------------------------------
# Step c — compute generated_from[] (hash of every source ledger)
# ---------------------------------------------------------------------------

def compute_generated_from(project_root: Path) -> List[Dict[str, Any]]:
    """Return the generated_from[] list for the current on-disk state.

    Each entry: {path, hash, revision?, snapshot_id?, snapshot_generation?}

    Missing files are included with `hash: null` so the diff against a prior
    projection surfaces "file disappeared" without special-casing.
    """
    entries: List[Dict[str, Any]] = []

    for rel in SOURCE_PATHS:
        p = project_root / rel
        entry: Dict[str, Any] = {"path": rel, "hash": _file_hash(p)}
        # Pull optional metadata from certain sources.
        if rel == "progress/contract-map.yaml" and p.is_file():
            try:
                doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                if isinstance(doc, dict):
                    rev = doc.get("revision")
                    if isinstance(rev, int):
                        entry["revision"] = rev
            except yaml.YAMLError:
                pass
        if rel == ".wiring/latest.json" and p.is_file():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(doc, dict):
                    sid = doc.get("snapshot_id")
                    sgen = doc.get("snapshot_generation")
                    if isinstance(sid, str):
                        entry["snapshot_id"] = sid
                    if isinstance(sgen, int):
                        entry["snapshot_generation"] = sgen
            except (json.JSONDecodeError, OSError):
                pass
        entries.append(entry)

    # Skeleton files — one entry per .yaml file under .design-ledger/skeletons/.
    skel_dir = project_root / ".design-ledger" / "skeletons"
    if skel_dir.is_dir():
        for p in sorted(skel_dir.glob("*.yaml")):
            rel_path = str(p.relative_to(project_root))
            entries.append({"path": rel_path, "hash": _file_hash(p)})

    # Canonical ordering so the output is deterministic.
    entries.sort(key=lambda e: e["path"])
    return entries


# ---------------------------------------------------------------------------
# Step d+e — load prior projection, compare, early-exit on idempotent no-op
# ---------------------------------------------------------------------------

def load_prior_projection(project_root: Path) -> Optional[Dict[str, Any]]:
    latest = project_root / ".project-state" / "latest.json"
    if not latest.is_file():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def hashes_match(
    current: List[Dict[str, Any]],
    prior: List[Dict[str, Any]],
) -> bool:
    """Return True iff every (path, hash) tuple in current matches prior.

    Both lists are compared as sets of (path, hash) tuples. Mismatch or
    missing entries in either side → False.
    """
    cur_map = {e["path"]: e.get("hash") for e in current}
    pri_map = {e["path"]: e.get("hash") for e in prior}
    if set(cur_map.keys()) != set(pri_map.keys()):
        return False
    for path, h in cur_map.items():
        if h != pri_map.get(path):
            return False
    return True


# ---------------------------------------------------------------------------
# Step g — walk each source ledger and emit entities[]
# ---------------------------------------------------------------------------

# Regex to parse blocking/blocked_by URI lists safely (tolerate YAML list or
# comma-separated strings).

def _list_of_strings(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [s.strip() for s in raw.split(",") if s.strip()]
    if isinstance(raw, list):
        return [str(s) for s in raw if s]
    return []


def _capability_status(cap_node: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Infer (status, modifier) from a capability node in contract-map.

    The contract-map doesn't always carry explicit status — we infer from
    stage if present, else PLANNED. Modifier from explicit `modifier` field.
    """
    stage = cap_node.get("stage") or cap_node.get("status")
    if isinstance(stage, str) and stage.upper() in STAGES:
        status = stage.upper()
    else:
        status = "PLANNED"
    modifier = cap_node.get("modifier")
    if isinstance(modifier, str) and modifier.upper() in MODIFIERS:
        modifier = modifier.upper()
    else:
        modifier = None
    return status, modifier


def walk_contract_map(
    project_root: Path,
    doc: Any,
    observations_bus: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Emit one entity per capability in progress/contract-map.yaml.

    Also emits component-level entries as kind=component.
    """
    entities: List[Dict[str, Any]] = []
    if not isinstance(doc, dict):
        return entities

    for comp in doc.get("components", []) or []:
        if not isinstance(comp, dict):
            continue
        comp_id = comp.get("id")
        if not isinstance(comp_id, str):
            continue

        # component entity
        entities.append({
            "uri": f"component://{comp_id}",
            "kind": "component",
            "source_ledger": "progress/contract-map.yaml",
            "source_jsonpointer": f"/components/{comp_id}",
            "entity_uuid": comp.get("entity_uuid"),
            "status": _capability_status(comp)[0],
            "modifier": _capability_status(comp)[1],
            "blocking": _list_of_strings(comp.get("blocking")),
            "blocked_by": _list_of_strings(comp.get("blocked_by")) or _list_of_strings(comp.get("dependencies_uris")),
            "visual_refs": _list_of_strings(comp.get("visual_refs")),
            "flow_refs": _list_of_strings(comp.get("flow_refs")),
            "test_count": {},
            "last_touched": comp.get("last_touched"),
            "last_observation_severity": None,
            "entry_point": comp.get("entry_point") if isinstance(comp.get("entry_point"), str) else None,
        })

        caps = comp.get("capabilities") or {}
        if not isinstance(caps, dict):
            continue
        for cap_id, cap_node in caps.items():
            if not isinstance(cap_node, dict):
                continue
            status, modifier = _capability_status(cap_node)
            uri = f"capability://{comp_id}.{cap_id}"
            entities.append({
                "uri": uri,
                "kind": "capability",
                "source_ledger": "progress/contract-map.yaml",
                "source_jsonpointer": f"/components/{comp_id}/capabilities/{cap_id}",
                "entity_uuid": cap_node.get("entity_uuid"),
                "status": status,
                "modifier": modifier,
                "blocking": _list_of_strings(cap_node.get("blocking")),
                "blocked_by": _list_of_strings(cap_node.get("blocked_by"))
                              or _list_of_strings(cap_node.get("dependencies")),
                "visual_refs": _list_of_strings(cap_node.get("visual_refs")),
                "flow_refs": _list_of_strings(cap_node.get("flow_refs")),
                "test_count": cap_node.get("test_count") or {},
                "last_touched": cap_node.get("last_touched"),
                "last_observation_severity": None,
                "entry_point": cap_node.get("entry_point") if isinstance(cap_node.get("entry_point"), str) else None,
            })
    return entities


def walk_skeletons(
    project_root: Path,
    observations_bus: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    skel_dir = project_root / ".design-ledger" / "skeletons"
    if not skel_dir.is_dir():
        return entities
    for path in sorted(skel_dir.glob("*.yaml")):
        if path.name == "index.yaml":
            continue
        screen = path.stem
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            observations_bus.append({
                "category": "schema_mismatch",
                "severity": "blocking",
                "subject_id": f"skeleton://{screen}",
                "what_happened": f"YAML parse error in {path}",
            })
            continue
        if not isinstance(doc, dict):
            continue
        elements = doc.get("elements") or {}
        if not isinstance(elements, dict):
            continue
        for elem_id, elem in elements.items():
            if not isinstance(elem, dict):
                continue
            interactions = elem.get("interactions") or []
            for inter in interactions:
                if not isinstance(inter, dict):
                    continue
                event = inter.get("event")
                if not isinstance(event, str):
                    continue
                uri = f"skeleton://{screen}#{elem_id}.{event}"
                binds_to = inter.get("binds_to")
                visual_only = bool(inter.get("visual_only"))
                blocking_list: List[str] = []
                if isinstance(binds_to, str):
                    blocking_list.append(binds_to)
                entities.append({
                    "uri": uri,
                    "kind": "visual_element",
                    "source_ledger": str(path.relative_to(project_root)),
                    "source_jsonpointer": f"/elements/{elem_id}/interactions/{event}",
                    "entity_uuid": inter.get("entity_uuid"),
                    "status": "TBC" if visual_only else "PLANNED",
                    "modifier": None,
                    "blocking": blocking_list,
                    "blocked_by": [],
                    "visual_refs": [],
                    "flow_refs": [],
                    "test_count": {},
                    "last_touched": None,
                    "last_observation_severity": None,
                    "visual_only": visual_only,
                })
    return entities


def walk_flows(
    project_root: Path,
    observations_bus: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    path = project_root / "progress" / "flows.yaml"
    if not path.is_file():
        return entities
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        observations_bus.append({
            "category": "schema_mismatch",
            "severity": "blocking",
            "subject_id": "flows.yaml",
            "what_happened": f"YAML parse error in {path}",
        })
        return entities
    if not isinstance(doc, dict):
        return entities
    flows = doc.get("flows")
    # flows can be a dict (id → body) or a list of dicts with 'id'.
    flow_iter: Iterable[Tuple[str, Dict[str, Any]]] = ()
    if isinstance(flows, dict):
        flow_iter = list(flows.items())
    elif isinstance(flows, list):
        flow_iter = [
            (str(f.get("id")), f) for f in flows if isinstance(f, dict) and f.get("id")
        ]
    for flow_id, flow in flow_iter:
        if not isinstance(flow, dict):
            continue
        uri = f"flow://{flow_id}"
        entities.append({
            "uri": uri,
            "kind": "flow",
            "source_ledger": "progress/flows.yaml",
            "source_jsonpointer": f"/flows/{flow_id}",
            "entity_uuid": flow.get("entity_uuid"),
            "status": _capability_status(flow)[0],
            "modifier": _capability_status(flow)[1],
            "blocking": _list_of_strings(flow.get("blocking")),
            "blocked_by": _list_of_strings(flow.get("blocked_by")) or _list_of_strings(flow.get("calls")),
            "visual_refs": _list_of_strings(flow.get("visual_refs")),
            "flow_refs": [],
            "test_count": flow.get("test_count") or {},
            "last_touched": flow.get("last_touched"),
            "last_observation_severity": None,
        })
    return entities


# ---------------------------------------------------------------------------
# Step h — compute blocking / blocked_by by joining cross-ledger refs
# ---------------------------------------------------------------------------

def fill_reverse_edges(entities: List[Dict[str, Any]]) -> None:
    """Given forward blocked_by, fill in reverse blocking[] where unset."""
    rev: Dict[str, List[str]] = defaultdict(list)
    for ent in entities:
        for dep in ent.get("blocked_by") or []:
            rev[dep].append(ent["uri"])
    for ent in entities:
        # Merge existing blocking[] with reverse edges, dedupe.
        merged = set(ent.get("blocking") or [])
        merged.update(rev.get(ent["uri"], []))
        ent["blocking"] = sorted(merged)


# ---------------------------------------------------------------------------
# Step i — Tarjan SCC for build_order
# ---------------------------------------------------------------------------

def tarjan_scc(nodes: List[str], adj: Dict[str, List[str]]) -> List[List[str]]:
    """Tarjan's strongly-connected-components algorithm.

    Iterative version (avoids Python recursion limits on deep graphs).
    Returns list of SCCs in reverse-topological order.
    """
    idx_of: Dict[str, int] = {}
    low: Dict[str, int] = {}
    on_stack: Set[str] = set()
    stack: List[str] = []
    index = 0
    sccs: List[List[str]] = []

    # Explicit iterative DFS with per-frame iterator state.
    for root in nodes:
        if root in idx_of:
            continue
        work: List[Tuple[str, Iterable[str]]] = [(root, iter(adj.get(root, [])))]
        idx_of[root] = index
        low[root] = index
        index += 1
        stack.append(root)
        on_stack.add(root)

        while work:
            v, it = work[-1]
            try:
                w = next(it)
            except StopIteration:
                # Node finished — pop frame, finalize SCC if root.
                work.pop()
                if work:
                    parent_v, _ = work[-1]
                    low[parent_v] = min(low[parent_v], low[v])
                if low[v] == idx_of[v]:
                    comp: List[str] = []
                    while True:
                        w2 = stack.pop()
                        on_stack.discard(w2)
                        comp.append(w2)
                        if w2 == v:
                            break
                    sccs.append(sorted(comp))
                continue
            if w not in idx_of:
                idx_of[w] = index
                low[w] = index
                index += 1
                stack.append(w)
                on_stack.add(w)
                work.append((w, iter(adj.get(w, []))))
            elif w in on_stack:
                low[v] = min(low[v], idx_of[w])
    return sccs


def build_topological_levels(
    entities: List[Dict[str, Any]],
    observations_bus: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compute build_order levels + SCC handling (§3.9).

    Returns list of {level, entities, note?, scc_id?}. Cycles → level=99 +
    schema_mismatch observation.
    """
    nodes = [e["uri"] for e in entities]
    # Directed graph: edge from blocked_by → entity (i.e. dep → dependent).
    adj: Dict[str, List[str]] = {u: [] for u in nodes}
    for ent in entities:
        for dep in ent.get("blocked_by") or []:
            if dep in adj:
                adj[dep].append(ent["uri"])

    sccs = tarjan_scc(nodes, adj)
    # Condense each SCC to a single node for topological sort.
    comp_of: Dict[str, int] = {}
    for i, comp in enumerate(sccs):
        for u in comp:
            comp_of[u] = i

    comp_adj: Dict[int, Set[int]] = {i: set() for i in range(len(sccs))}
    for ent in entities:
        u = ent["uri"]
        if u not in comp_of:
            continue
        for dep in ent.get("blocked_by") or []:
            if dep in comp_of and comp_of[dep] != comp_of[u]:
                comp_adj[comp_of[dep]].add(comp_of[u])

    # Kahn topological sort over components.
    indeg: Dict[int, int] = {i: 0 for i in range(len(sccs))}
    for src, dsts in comp_adj.items():
        for d in dsts:
            indeg[d] += 1
    queue: deque = deque([i for i, d in indeg.items() if d == 0])
    level_of: Dict[int, int] = {}
    while queue:
        c = queue.popleft()
        for d in sorted(comp_adj.get(c, ())):
            indeg[d] -= 1
            if indeg[d] == 0:
                level_of[d] = max(level_of.get(d, 0), level_of.get(c, 0) + 1)
                queue.append(d)
        level_of.setdefault(c, 0)

    # Assign levels; cycles (SCCs with >1 node) → level 99.
    levels: Dict[int, List[str]] = defaultdict(list)
    for i, comp in enumerate(sccs):
        if len(comp) > 1:
            # Cyclic SCC — emit schema_mismatch.
            scc_id = f"scc-{i:04d}"
            levels[99].extend(comp)
            observations_bus.append({
                "category": "schema_mismatch",
                "severity": "noisy",  # cycles are legal input — emit as 'noisy'
                "subject_id": "project-state",
                "what_happened": f"circular dep SCC: {comp} ({scc_id})",
                "scc_id": scc_id,
            })
        else:
            levels[level_of.get(i, 0)].extend(comp)

    out: List[Dict[str, Any]] = []
    for level in sorted(levels.keys()):
        bucket = {"level": level, "entities": sorted(levels[level])}
        if level == 99:
            bucket["note"] = "strongly-connected component — project-state emits schema_mismatch observation"
        out.append(bucket)
    return out


# ---------------------------------------------------------------------------
# Step j — orphan detection (reachability walk per §5.4)
# ---------------------------------------------------------------------------

def reachable_set(
    entities: List[Dict[str, Any]],
) -> Tuple[Set[str], str]:
    """Compute reachability from visual entry points + tagged roots.

    Per D8 + §5.4. Returns (reachable_uris, root_set_hash).

    Cycle handling (§5.4 end): mutual-calls without entry_point → both
    unreachable → both orphans. No special case needed; BFS from empty
    root_set never reaches them.
    """
    # Visual roots = every skeleton interaction's binds_to (non-visual_only)
    visual_roots: Set[str] = set()
    for ent in entities:
        if ent.get("kind") == "visual_element" and not ent.get("visual_only"):
            # binds_to is in blocking[] (we placed it there in walk_skeletons)
            for b in ent.get("blocking") or []:
                visual_roots.add(b)

    # Tagged roots — entities with entry_point in ENTRY_POINT_TAGS
    tagged_roots: Set[str] = {
        ent["uri"]
        for ent in entities
        if isinstance(ent.get("entry_point"), str)
        and ent["entry_point"] in ENTRY_POINT_TAGS
    }

    # Forward call graph: node → nodes it calls (blocked_by).
    adj: Dict[str, List[str]] = defaultdict(list)
    for ent in entities:
        uri = ent["uri"]
        # A calls B  <->  A.blocked_by includes B  -->  B is reached from A
        for dep in ent.get("blocked_by") or []:
            adj[uri].append(dep)

    roots = visual_roots | tagged_roots
    reachable: Set[str] = set(roots)
    frontier: deque = deque(roots)
    while frontier:
        cur = frontier.popleft()
        for nxt in adj.get(cur, ()):
            if nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)

    # Also consider visual_elements themselves reachable (they are UI leaves).
    for ent in entities:
        if ent.get("kind") == "visual_element":
            reachable.add(ent["uri"])

    # root_set_hash is a deterministic fingerprint of the inputs used.
    rs_hash = hashlib.sha256(
        _canonical_json_bytes(sorted(roots)) + _canonical_json_bytes(sorted(adj.keys()))
    ).hexdigest()[:16]
    return reachable, rs_hash


def compute_orphans(
    entities: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    reachable, rs_hash = reachable_set(entities)
    orphans: List[Dict[str, Any]] = []
    for ent in entities:
        uri = ent["uri"]
        kind = ent.get("kind")
        # Orphan scope: only capabilities. Flows/visual_elements are intrinsic.
        if kind != "capability":
            continue
        if uri in reachable:
            continue
        # Entry-point-tagged capabilities are never orphans.
        if isinstance(ent.get("entry_point"), str) and ent["entry_point"] in ENTRY_POINT_TAGS:
            continue
        orphans.append({
            "uri": uri,
            "entity_uuid": ent.get("entity_uuid"),
            "reason": "not reachable from any skeleton:// and not tagged entry_point",
            "root_set_hash": rs_hash,
        })
    return orphans


# ---------------------------------------------------------------------------
# Step k — observations_summary (read-only from active.yaml)
# ---------------------------------------------------------------------------

def load_observations_summary(project_root: Path) -> Dict[str, Any]:
    path = project_root / ".process-observations" / "active.yaml"
    summary: Dict[str, Any] = {
        "last_7_days": {
            "by_category": {},
            "hot_subjects": [],
        },
        "unresolved_blocking": 0,
    }
    if not path.is_file():
        return summary
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return summary
    if not isinstance(doc, dict):
        return summary
    obs = doc.get("observations") or {}
    if not isinstance(obs, dict):
        return summary
    by_cat: Dict[str, int] = defaultdict(int)
    subj_count: Dict[str, int] = defaultdict(int)
    subj_last_seen: Dict[str, str] = {}
    unresolved = 0
    for entry in obs.values():
        if not isinstance(entry, dict):
            continue
        cat = entry.get("category") or "unknown"
        by_cat[cat] += int(entry.get("count_last_7d") or entry.get("count") or 1)
        sev = entry.get("severity")
        if sev == "blocking" and not entry.get("resolved") and not entry.get("promoted_to_task"):
            unresolved += 1
        subj = entry.get("subject", {}).get("id") if isinstance(entry.get("subject"), dict) else None
        if isinstance(subj, str):
            subj_count[subj] += int(entry.get("count_last_7d") or entry.get("count") or 1)
            ls = entry.get("last_seen")
            if isinstance(ls, str) and ls > subj_last_seen.get(subj, ""):
                subj_last_seen[subj] = ls
    hot = sorted(
        ({"subject": s, "count": c, "last_seen": subj_last_seen.get(s, "")}
         for s, c in subj_count.items()),
        key=lambda r: (-r["count"], r["subject"]),
    )[:10]
    summary["last_7_days"]["by_category"] = dict(by_cat)
    summary["last_7_days"]["hot_subjects"] = hot
    summary["unresolved_blocking"] = unresolved
    return summary


# ---------------------------------------------------------------------------
# Step l — emit observations for impossible states
# ---------------------------------------------------------------------------

def emit_reconcile_observations(
    project_root: Path,
    observations_bus: List[Dict[str, Any]],
    elapsed_s: float,
    hmac_verify_ok: bool,
) -> None:
    """Drain the bus → claude_observe. Fail-open at every call."""
    for ev in observations_bus:
        _claude_observe(
            category=ev["category"],
            subject_id=ev.get("subject_id", "project-state"),
            what_happened=ev["what_happened"],
            severity=ev.get("severity", "degraded"),
            project_root=project_root,
            subject_type="skill",
            observed_by="project-state@1.0.0",
        )
    # Soft SLA
    if elapsed_s > RECONCILE_SOFT_SLA_S:
        _claude_observe(
            category="external_tool_slow",
            subject_id="project-state",
            what_happened=f"reconcile took {elapsed_s:.2f}s (>5s soft SLA)",
            severity="degraded",
            project_root=project_root,
            subject_type="skill",
            observed_by="project-state@1.0.0",
        )
    # HMAC verify fail on PRIOR projection
    if not hmac_verify_ok:
        _claude_observe(
            category="schema_mismatch",
            subject_id="project-state",
            what_happened="HMAC verify failed on prior .project-state/latest.json; possible tamper or key rotation",
            severity="blocking",
            project_root=project_root,
            subject_type="skill",
            observed_by="project-state@1.0.0",
        )


# ---------------------------------------------------------------------------
# Step m — canonical-JSON + HMAC + atomic write + transition request
# ---------------------------------------------------------------------------

SIGNED_FIELDS: List[str] = [
    "projection_id",
    "projection_generation",
    "generated_at",
    "generated_from",
]


def _read_session_key(project_root: Path) -> Optional[bytes]:
    key_path = project_root / ".forge" / "session.key"
    if not key_path.is_file():
        return None
    try:
        return key_path.read_bytes()
    except OSError:
        return None


def _read_session_id(project_root: Path) -> Optional[str]:
    sid_path = project_root / ".forge" / "session-id"
    if not sid_path.is_file():
        return None
    try:
        return sid_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def build_signature(
    projection: Dict[str, Any],
    session_key_bytes: bytes,
) -> Dict[str, Any]:
    payload = {k: projection[k] for k in SIGNED_FIELDS if k in projection}
    digest = hmac.new(session_key_bytes, _canonical_json_bytes(payload), hashlib.sha256).hexdigest()
    return {
        "algorithm": "HMAC-SHA256",
        "key_id": ".forge/session.key",
        "signed_fields": list(SIGNED_FIELDS),
        "signed_at": now_iso(),
        "digest": digest,
    }


def verify_signature(
    projection: Dict[str, Any],
    session_key_bytes: bytes,
) -> bool:
    sig = projection.get("signature") or {}
    if sig.get("algorithm") != "HMAC-SHA256":
        return False
    expected = sig.get("digest")
    if not expected:
        return False
    payload = {k: projection[k] for k in SIGNED_FIELDS if k in projection}
    digest = hmac.new(session_key_bytes, _canonical_json_bytes(payload), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected)


def compute_projection_id(projection_without_id_or_sig: Dict[str, Any]) -> str:
    """Content-hash of the payload below projection_id / signature fields."""
    # Per §3.2: projection_id is content-hash of "the payload below" — take
    # every field except projection_id + signature + projection_generation
    # (generation is monotonic, not content-addressed). generated_at is
    # included because two reconciles a minute apart over identical content
    # should still be distinguishable; but we exclude it from the hash so
    # idempotent-no-op matches on hash alone.
    filtered = {
        k: v
        for k, v in projection_without_id_or_sig.items()
        if k not in {"projection_id", "signature", "projection_generation", "generated_at"}
    }
    return hashlib.sha256(_canonical_json_bytes(filtered)).hexdigest()


# ---------------------------------------------------------------------------
# Step n — emit transition request for bob-the-promoter
# ---------------------------------------------------------------------------

def emit_transition_request(
    project_root: Path,
    claim_uuid: str,
    run_id: str,
    projection: Dict[str, Any],
) -> Path:
    req_dir = project_root / ".ledger" / "requests"
    req_dir.mkdir(parents=True, exist_ok=True)
    req_path = req_dir / f"{claim_uuid}.request.yaml"
    body = {
        "schema_version": 1,
        "request_id": f"{claim_uuid}-{projection['projection_id']}",
        "claim_uuid": claim_uuid,
        "component": "project-state",
        "target_stage": "VERIFIED",
        "emitted_at": now_iso(),
        "emitted_by": "project-state@1.0.0",
        "run_id": run_id,
        "projection_id": projection["projection_id"],
        "projection_generation": projection["projection_generation"],
        "generated_from": projection["generated_from"],
        "drift_canary": DRIFT_CANARY,
    }
    req_bytes = yaml.safe_dump(body, sort_keys=True).encode("utf-8")
    atomic_write_bytes(req_path, req_bytes)
    return req_path


# ---------------------------------------------------------------------------
# Top-level reconcile entry
# ---------------------------------------------------------------------------

def reconcile(
    project_root: Path,
    *,
    claim_uuid: Optional[str] = None,
    force: bool = False,
    skip_claim_check: bool = False,
    skip_heartbeat: bool = False,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Run the full 13-step lifecycle. Returns a dict describing the outcome.

    Result shape:
        {
          "projection_id": "<hex>",
          "projection_generation": int,
          "run_id": "<uuid>",
          "run_projection_path": "<path>",
          "request_path": "<path>" or None,
          "idempotent_noop": bool,
          "elapsed_s": float,
          "observations_emitted": int,
        }
    """
    project_root = project_root.resolve()
    logger = logger or logging.getLogger("project-state.reconcile")
    start_wall = time.monotonic()

    observations_bus: List[Dict[str, Any]] = []
    hmac_verify_ok = True

    # --- Step a: verify claim ---
    if claim_uuid and not skip_claim_check:
        try:
            import claims as _claims  # type: ignore
            claim_path = project_root / ".ledger" / "claims" / f"{claim_uuid}.claim.yaml"
            if claim_path.is_file():
                try:
                    claim_doc = yaml.safe_load(claim_path.read_text(encoding="utf-8")) or {}
                    state = _claims.classify_claim(
                        claim_doc,
                        project_root / "progress" / "integration-ledger.md",
                    )
                    if state != "ok":
                        raise RuntimeError(f"claim {claim_uuid} state={state}")
                except yaml.YAMLError:
                    raise RuntimeError(f"claim {claim_uuid} corrupt YAML")
        except ImportError:
            logger.info("claims.py not importable; skipping claim check")

    # --- Step b: heartbeat thread ---
    stop_flag = {"triggered": False, "reason": None}
    heartbeat: Optional[HeartbeatThread] = None
    if claim_uuid and not skip_heartbeat:
        def _stop(reason: str) -> None:
            stop_flag["triggered"] = True
            stop_flag["reason"] = reason
        heartbeat = HeartbeatThread(claim_uuid, project_root, _stop)
        heartbeat.start()

    try:
        # --- Step c: compute generated_from ---
        generated_from = compute_generated_from(project_root)

        # Detect missing files the design claims must exist (blocking schema_mismatch).
        # Missing is only blocking if the file is required; we treat ALL six
        # sources as optional (per §3.9 "bootstrap edge" — new projects may
        # lack skeleton/flows/observations). We emit schema_mismatch warning
        # for missing contract-map since that's the hard root.
        cm_entry = next((e for e in generated_from if e["path"] == "progress/contract-map.yaml"), None)
        if cm_entry and cm_entry.get("hash") is None:
            observations_bus.append({
                "category": "schema_mismatch",
                "severity": "blocking",
                "subject_id": "project-state",
                "what_happened": "progress/contract-map.yaml missing — projection cannot be built",
            })

        # --- Step d: load prior projection ---
        prior = load_prior_projection(project_root)

        # --- Step e: idempotent no-op check ---
        if prior and not force and hashes_match(generated_from, prior.get("generated_from") or []):
            # Verify HMAC on prior projection before trusting its id.
            key_bytes = _read_session_key(project_root)
            if key_bytes is not None:
                hmac_verify_ok = verify_signature(prior, key_bytes)
            if hmac_verify_ok:
                elapsed = time.monotonic() - start_wall
                emit_reconcile_observations(project_root, observations_bus, elapsed, hmac_verify_ok)
                return {
                    "projection_id": prior["projection_id"],
                    "projection_generation": prior.get("projection_generation", 0),
                    "run_id": prior.get("run_id", ""),
                    "run_projection_path": None,
                    "request_path": None,
                    "idempotent_noop": True,
                    "elapsed_s": elapsed,
                    "observations_emitted": len(observations_bus)
                    + (1 if elapsed > RECONCILE_SOFT_SLA_S else 0),
                }
            # HMAC fail — fall through to rebuild; emit observation
            observations_bus.append({
                "category": "schema_mismatch",
                "severity": "blocking",
                "subject_id": "project-state",
                "what_happened": "prior projection HMAC verify failed — rebuilding",
            })

        # --- Step f/g: rebuild ---
        cm_path = project_root / "progress" / "contract-map.yaml"
        cm_doc: Any = None
        if cm_path.is_file():
            try:
                cm_doc = yaml.safe_load(cm_path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                observations_bus.append({
                    "category": "schema_mismatch",
                    "severity": "blocking",
                    "subject_id": "project-state",
                    "what_happened": f"YAML parse error in {cm_path}",
                })
        entities = walk_contract_map(project_root, cm_doc, observations_bus)
        entities.extend(walk_skeletons(project_root, observations_bus))
        entities.extend(walk_flows(project_root, observations_bus))

        # --- Step g2: URI resolver check (unresolved refs → flow_gap blocking) ---
        uri_mod = _load_uri()
        if uri_mod is not None:
            resolve_fn = getattr(uri_mod, "resolve", None)
            UriError = getattr(uri_mod, "UriError", Exception)
            entity_uris = {e["uri"] for e in entities}
            if resolve_fn is not None:
                for ent in entities:
                    for ref_uri in list(ent.get("blocked_by") or []) + list(ent.get("flow_refs") or []):
                        if not isinstance(ref_uri, str):
                            continue
                        if not ref_uri.startswith(("capability://", "skeleton://", "flow://", "wire://", "token://", "component://")):
                            continue
                        if ref_uri in entity_uris:
                            continue
                        # Not in local entities — ask resolver.
                        try:
                            resolve_fn(ref_uri, project_root, allow_expired=False)
                        except UriError:
                            observations_bus.append({
                                "category": "flow_gap",
                                "severity": "blocking",
                                "subject_id": ref_uri,
                                "what_happened": f"unresolved URI referenced by {ent['uri']}",
                            })

        # --- Step h: fill reverse edges ---
        fill_reverse_edges(entities)

        # --- Step i: build_order (Tarjan SCC) ---
        build_order = build_topological_levels(entities, observations_bus)

        # --- Step j: orphans (reachability walk) ---
        orphans = compute_orphans(entities)

        # --- Step k: observations_summary (read-only from active.yaml) ---
        obs_summary = load_observations_summary(project_root)

        # --- by_status histogram + next_buildable ---
        by_status: Dict[str, int] = defaultdict(int)
        verified_set: Set[str] = set()
        for ent in entities:
            status = ent.get("status") or "PLANNED"
            modifier = ent.get("modifier")
            by_status[status] += 1
            if modifier:
                by_status[modifier] += 1
            if status == "VERIFIED":
                verified_set.add(ent["uri"])

        next_buildable: List[Dict[str, str]] = []
        for ent in entities:
            if ent.get("status") == "VERIFIED":
                continue
            if ent.get("modifier") in ("BLOCKED", "RETIRED", "SKIPPED"):
                continue
            deps = ent.get("blocked_by") or []
            if not deps:
                continue
            if all(d in verified_set for d in deps):
                next_buildable.append({"uri": ent["uri"]})
        next_buildable.sort(key=lambda r: r["uri"])

        # --- Step m: assemble projection, compute id, sign ---
        # projection_generation is provisional (1); bob increments on promote.
        new_gen = int(prior.get("projection_generation", 0)) + 1 if prior else 1

        projection_draft: Dict[str, Any] = {
            "schema": SCHEMA_NAME,
            "projection_generation": new_gen,
            "generated_at": now_iso(),
            "generated_by": GENERATED_BY,
            "generated_from": generated_from,
            "entities": sorted(entities, key=lambda e: e["uri"]),
            "orphans": sorted(orphans, key=lambda o: o["uri"]),
            "build_order": build_order,
            "by_status": dict(sorted(by_status.items())),
            "next_buildable": next_buildable,
            "observations_summary": obs_summary,
            "focus_packs_cache": {},
        }
        projection_id = compute_projection_id(projection_draft)
        projection_draft["projection_id"] = projection_id

        # Sign iff key available. Unsigned projection is still written (bob
        # may sign on promote) — but we prefer signed-from-skill where
        # possible because it closes the window where runs/<run_id>/
        # projection.json is unsigned.
        key_bytes = _read_session_key(project_root)
        if key_bytes is not None:
            projection_draft["signature"] = build_signature(projection_draft, key_bytes)
        else:
            projection_draft["signature"] = {
                "algorithm": "HMAC-SHA256",
                "key_id": "unsigned",
                "signed_fields": list(SIGNED_FIELDS),
                "signed_at": now_iso(),
                "digest": "0" * 64,
            }

        # --- Step m2: atomic write run-scoped projection.json ---
        run_id = str(uuid.uuid4())
        run_dir = project_root / ".project-state" / "runs" / run_id
        run_projection_path = run_dir / "projection.json"
        atomic_write_bytes(run_projection_path, _canonical_json_bytes(projection_draft))

        # --- Step n: transition request (bob-the-promoter will copy → latest.json) ---
        request_path: Optional[Path] = None
        if claim_uuid:
            request_path = emit_transition_request(
                project_root, claim_uuid, run_id, projection_draft
            )

        elapsed = time.monotonic() - start_wall

        # --- Step l: drain observations bus ---
        emit_reconcile_observations(project_root, observations_bus, elapsed, hmac_verify_ok)

        if stop_flag["triggered"]:
            logger.error("heartbeat stop: %s", stop_flag["reason"])
            # Still return the projection metadata — the caller decides.

        return {
            "projection_id": projection_id,
            "projection_generation": new_gen,
            "run_id": run_id,
            "run_projection_path": str(run_projection_path),
            "request_path": str(request_path) if request_path else None,
            "idempotent_noop": False,
            "elapsed_s": elapsed,
            "observations_emitted": len(observations_bus)
            + (1 if elapsed > RECONCILE_SOFT_SLA_S else 0),
        }

    finally:
        if heartbeat:
            heartbeat.stop()


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="project-state reconcile")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--claim-uuid", default=None)
    parser.add_argument("--force", action="store_true",
                        help="rebuild even if hashes match prior projection")
    parser.add_argument("--skip-heartbeat", action="store_true")
    parser.add_argument("--skip-claim-check", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("project-state")

    try:
        result = reconcile(
            project_root=args.project_root,
            claim_uuid=args.claim_uuid,
            force=args.force,
            skip_claim_check=args.skip_claim_check or args.claim_uuid is None,
            skip_heartbeat=args.skip_heartbeat or args.claim_uuid is None,
            logger=logger,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("reconcile failed: %s", e)
        return 1

    sys.stdout.write(_canonical_json(result))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
