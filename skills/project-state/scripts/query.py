#!/usr/bin/env python3
"""query.py — project-state query CLI (WP-11 of S028 ecosystem-keystone).

Per design docs/plans/2026-04-23-ecosystem-keystone-design.md section 3.5
+ 3.6 (focus_pack) + 3.4 (hash-first freshness).

Six operations, all emit canonical JSON on stdout (sort_keys=True,
separators=(',',':')) so callers can hash stdout for caching:

    focus_pack     --uri --depth --ceiling --relevance --include-tests --include-observations
    orphans        (no args)
    next_buildable [--limit N]
    by_status      --status S [--modifier M]
    impact         --uri U
    resolve        --uri U

Freshness contract (D10 MODIFIED): every op EXCEPT `resolve` reads caller's
expected source-ledger hashes from `.forge/session-inputs.json` if present,
else computes on-the-fly. Compared against projection's `generated_from[]`:
    - all match → projection fresh, serve query
    - any differ → synchronously reconcile OR fail with
      STALE_PROJECTION_HASH_MISMATCH if --no-self-heal.

Wallclock defense-in-depth: freshness_window_s from _meta/config.yaml
triggers reconcile even if hashes match but generated_at > window.

Drift canary: ALDEBARAN-7.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent

# Reuse reconcile.py helpers in-process so we don't duplicate any logic.
sys.path.insert(0, str(SCRIPT_DIR))
import reconcile as _reconcile  # noqa: E402

_META_CANDIDATES = [
    Path.home() / ".claude" / "skills" / "_meta",
    SKILL_ROOT.parent / "_meta",
]
for _p in _META_CANDIDATES:
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    import yaml  # noqa: F401  (used by reconcile module load)
except ImportError as _e:  # pragma: no cover
    raise ImportError("project-state query requires pyyaml") from _e


# ---------------------------------------------------------------------------
# Constants (mirror reconcile)
# ---------------------------------------------------------------------------

# Relevance-strict BFS edge kinds (§3.6 pseudocode).
PATH_EDGES: frozenset = frozenset({
    "blocks", "blocked_by", "binds_to", "calls", "back_ref", "flow_ref",
})

# Default token ceiling. Per §3.6. Overridable via --ceiling.
DEFAULT_TOKEN_CEILING = 60_000
DEFAULT_FOCUS_DEPTH = 2

# LRU bound per §3.6.
FOCUS_PACK_LRU_SIZE = 50

# Heuristic: bytes of canonical JSON / 4 ≈ tokens (same heuristic as
# wiring-query).
_TOKENS_PER_BYTE_DIV = 4


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _estimate_tokens(obj: Any) -> int:
    return max(1, len(_canonical_json(obj).encode("utf-8")) // _TOKENS_PER_BYTE_DIV)


# ---------------------------------------------------------------------------
# Freshness check (§3.4)
# ---------------------------------------------------------------------------

def _read_expected_hashes(project_root: Path) -> Optional[Dict[str, str]]:
    """Read caller's expected source-ledger hashes from session-inputs.json."""
    path = project_root / ".forge" / "session-inputs.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(doc, dict):
        return None
    hashes = doc.get("source_hashes")
    if not isinstance(hashes, dict):
        return None
    return {str(k): str(v) for k, v in hashes.items()}


def _wallclock_window_s(project_root: Path) -> int:
    cfg_candidates = [
        Path.home() / ".claude" / "skills" / "_meta" / "config.yaml",
        SKILL_ROOT.parent / "_meta" / "config.yaml",
    ]
    for cfg_path in cfg_candidates:
        if cfg_path.is_file():
            try:
                import yaml as _yaml  # type: ignore
                doc = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                ps = (doc.get("project_state") or {}) if isinstance(doc, dict) else {}
                window = ps.get("freshness_window_s")
                if isinstance(window, int):
                    return window
            except Exception:
                pass
    return _reconcile.DEFAULT_FRESHNESS_WINDOW_S


def _projection_is_fresh(
    projection: Dict[str, Any],
    project_root: Path,
) -> Tuple[bool, str]:
    """Return (fresh, reason) for the loaded projection.

    Hash-first (§3.4) — caller's session-inputs.json hashes (or computed
    on-the-fly) must match projection.generated_from[] exactly. Wallclock
    window is defense-in-depth for `cp -p` edge.
    """
    proj_gf = projection.get("generated_from") or []
    proj_map = {e["path"]: e.get("hash") for e in proj_gf}

    expected = _read_expected_hashes(project_root)
    if expected is None:
        # Compute on-the-fly.
        current = _reconcile.compute_generated_from(project_root)
        expected = {e["path"]: e.get("hash") for e in current}

    # Hash comparison.
    for path, exp_hash in expected.items():
        if proj_map.get(path) != exp_hash:
            return False, f"hash mismatch on {path}: projection={proj_map.get(path)} expected={exp_hash}"

    # Wallclock defense-in-depth.
    try:
        gen_at = projection.get("generated_at")
        if isinstance(gen_at, str):
            gen_ts = datetime.strptime(gen_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            delta = (datetime.now(timezone.utc) - gen_ts).total_seconds()
            if delta > _wallclock_window_s(project_root):
                return False, f"generated_at older than window ({delta:.0f}s)"
    except Exception:
        pass

    return True, "fresh"


def _load_fresh_projection(
    project_root: Path,
    *,
    op: str,
    allow_self_heal: bool,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load latest.json, self-heal if stale. Returns (projection, error_code)."""
    latest = project_root / ".project-state" / "latest.json"
    if not latest.is_file():
        if not allow_self_heal:
            return None, "STALE_PROJECTION_HASH_MISMATCH"
        _reconcile.reconcile(
            project_root,
            skip_claim_check=True,
            skip_heartbeat=True,
        )
        # After reconcile, there's a run-scoped projection but no latest.json
        # (bob promotes). For query purposes we fall back to run-scoped if
        # no latest.json exists — this keeps query ops useful in tests and
        # bootstrap.
        runs_dir = project_root / ".project-state" / "runs"
        if runs_dir.is_dir():
            run_dirs = sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            for rd in run_dirs:
                candidate = rd / "projection.json"
                if candidate.is_file():
                    try:
                        return json.loads(candidate.read_text(encoding="utf-8")), None
                    except (json.JSONDecodeError, OSError):
                        continue
        return None, "STALE_PROJECTION_HASH_MISMATCH"

    try:
        projection = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "STALE_PROJECTION_HASH_MISMATCH"

    # resolve op is pure read — skip freshness check.
    if op == "resolve":
        return projection, None

    fresh, reason = _projection_is_fresh(projection, project_root)
    if fresh:
        return projection, None

    if not allow_self_heal:
        return None, "STALE_PROJECTION_HASH_MISMATCH"

    # Self-heal: reconcile + reload.
    _reconcile.reconcile(
        project_root,
        skip_claim_check=True,
        skip_heartbeat=True,
    )
    # Prefer latest.json if bob promoted; else run-scoped (tests often run
    # without bob).
    if latest.is_file():
        try:
            return json.loads(latest.read_text(encoding="utf-8")), None
        except (json.JSONDecodeError, OSError):
            pass
    runs_dir = project_root / ".project-state" / "runs"
    if runs_dir.is_dir():
        run_dirs = sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for rd in run_dirs:
            candidate = rd / "projection.json"
            if candidate.is_file():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8")), None
                except (json.JSONDecodeError, OSError):
                    continue
    return None, "STALE_PROJECTION_HASH_MISMATCH"


# ---------------------------------------------------------------------------
# Operation: resolve (pure read, skips freshness)
# ---------------------------------------------------------------------------

def op_resolve(projection: Dict[str, Any], uri: str) -> Dict[str, Any]:
    for ent in projection.get("entities", []):
        if ent.get("uri") == uri:
            return {
                "query": "resolve",
                "uri": uri,
                "found": True,
                "path": ent.get("source_ledger"),
                "jsonpointer": ent.get("source_jsonpointer"),
                "node": {
                    k: ent.get(k)
                    for k in (
                        "kind", "entity_uuid", "status", "modifier",
                        "blocking", "blocked_by", "visual_refs",
                        "flow_refs", "test_count",
                    )
                },
            }
    # Fuzzy top-3 suggestions.
    import difflib
    all_uris = [e["uri"] for e in projection.get("entities", [])]
    suggestions = difflib.get_close_matches(uri, all_uris, n=3, cutoff=0.5)
    return {
        "query": "resolve",
        "uri": uri,
        "found": False,
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# Operation: orphans
# ---------------------------------------------------------------------------

def op_orphans(projection: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "query": "orphans",
        "projection_id": projection.get("projection_id"),
        "orphans": projection.get("orphans", []),
    }


# ---------------------------------------------------------------------------
# Operation: next_buildable
# ---------------------------------------------------------------------------

def op_next_buildable(projection: Dict[str, Any], limit: Optional[int]) -> Dict[str, Any]:
    nb = list(projection.get("next_buildable", []))
    if limit is not None:
        nb = nb[: int(limit)]
    return {
        "query": "next_buildable",
        "projection_id": projection.get("projection_id"),
        "next_buildable": nb,
    }


# ---------------------------------------------------------------------------
# Operation: by_status
# ---------------------------------------------------------------------------

def op_by_status(
    projection: Dict[str, Any],
    status: str,
    modifier: Optional[str],
) -> Dict[str, Any]:
    matches: List[str] = []
    for ent in projection.get("entities", []):
        if ent.get("status") != status:
            continue
        if modifier is not None and ent.get("modifier") != modifier:
            continue
        matches.append(ent["uri"])
    matches.sort()
    return {
        "query": "by_status",
        "projection_id": projection.get("projection_id"),
        "status": status,
        "modifier": modifier,
        "entities": matches,
    }


# ---------------------------------------------------------------------------
# Operation: impact (reverse BFS over blocked_by + flow/test refs)
# ---------------------------------------------------------------------------

def op_impact(projection: Dict[str, Any], uri: str) -> Dict[str, Any]:
    # Build reverse-index: for each URI X, which entities have X in their
    # blocked_by[] or flow_refs[] or blocking[]?
    reverse: Dict[str, Set[str]] = defaultdict(set)
    for ent in projection.get("entities", []):
        u = ent["uri"]
        for dep in ent.get("blocked_by") or []:
            reverse[dep].add(u)
        for fr in ent.get("flow_refs") or []:
            reverse[fr].add(u)
        for bl in ent.get("blocking") or []:
            # blocking means "this entity blocks X" — so X depends on u
            # reverse lookup is handled by blocked_by above; don't double-count
            pass

    visited: Set[str] = set()
    frontier: deque = deque([uri])
    visited.add(uri)
    while frontier:
        cur = frontier.popleft()
        for nxt in sorted(reverse.get(cur, ())):
            if nxt not in visited:
                visited.add(nxt)
                frontier.append(nxt)

    retest_set = sorted(visited - {uri})
    return {
        "query": "impact",
        "projection_id": projection.get("projection_id"),
        "uri": uri,
        "retest_set": retest_set,
        "retest_count": len(retest_set),
    }


# ---------------------------------------------------------------------------
# Operation: focus_pack (§3.6)
# ---------------------------------------------------------------------------

def _build_edge_maps(
    entities: List[Dict[str, Any]],
) -> Tuple[Dict[str, List[Tuple[str, str]]], Dict[str, Dict[str, Any]]]:
    """Return (edges_out[uri] = [(edge_kind, dst), ...], node_index[uri] = ent)."""
    edges_out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    node_index: Dict[str, Dict[str, Any]] = {}
    for ent in entities:
        u = ent["uri"]
        node_index[u] = ent
        for dep in ent.get("blocked_by") or []:
            edges_out[u].append(("blocked_by", dep))
        for dep in ent.get("blocking") or []:
            edges_out[u].append(("blocks", dep))
        for fr in ent.get("flow_refs") or []:
            edges_out[u].append(("flow_ref", fr))
        for vr in ent.get("visual_refs") or []:
            edges_out[u].append(("back_ref", vr))
    return edges_out, node_index


def _suggest_splits(
    pack: Dict[str, Any],
    node_index: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Generate split suggestions (§3.6 end) when ceiling is tripped.

    Strategy: bisect the pack over top-level components. Each suggestion
    carries a cut_at URI and the two halves of entities.
    """
    # Group entities by first URI segment (component/scheme).
    groups: Dict[str, List[str]] = defaultdict(list)
    for uri in pack.keys():
        if "://" not in uri:
            continue
        scheme, rest = uri.split("://", 1)
        if scheme == "capability":
            # capability://component.cap
            prefix = rest.split(".", 1)[0] if "." in rest else rest
            key = f"component:{prefix}"
        elif scheme == "skeleton":
            prefix = rest.split("#", 1)[0] if "#" in rest else rest
            key = f"screen:{prefix}"
        elif scheme == "flow":
            key = f"flow:{rest.split('.', 1)[0] if '.' in rest else rest}"
        else:
            key = f"{scheme}:misc"
        groups[key].append(uri)

    suggestions: List[Dict[str, Any]] = []
    group_items = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    if len(group_items) >= 2:
        # Bisect: largest group vs rest.
        a_key, a_list = group_items[0]
        b_list: List[str] = []
        for _, ls in group_items[1:]:
            b_list.extend(ls)
        suggestions.append({
            "cut_at": a_list[0] if a_list else None,
            "agent_a_entities": sorted(a_list),
            "agent_b_entities": sorted(b_list),
            "rationale": f"split over largest subgraph group ({a_key})",
        })
    # Second suggestion: bisect alphabetically (fallback).
    sorted_uris = sorted(pack.keys())
    half = len(sorted_uris) // 2
    suggestions.append({
        "cut_at": sorted_uris[half] if half < len(sorted_uris) else None,
        "agent_a_entities": sorted_uris[:half],
        "agent_b_entities": sorted_uris[half:],
        "rationale": "alphabetic bisect (fallback)",
    })
    return suggestions


def op_focus_pack(
    projection: Dict[str, Any],
    uri: str,
    depth: int,
    ceiling: int,
    include_tests: bool,
    include_observations: bool,
) -> Dict[str, Any]:
    entities = projection.get("entities", []) or []
    edges_out, node_index = _build_edge_maps(entities)

    if uri not in node_index:
        return {
            "query": "focus_pack",
            "projection_id": projection.get("projection_id"),
            "uri": uri,
            "found": False,
            "error": "URI not in projection",
        }

    # Relevance-strict BFS (§3.6).
    pack: Dict[str, Any] = {}
    # Root node — fullbody.
    pack[uri] = dict(node_index[uri])

    seen: Set[str] = {uri}
    frontier: deque = deque([(uri, 0)])

    while frontier:
        cur_uri, d = frontier.popleft()
        if d >= depth:
            continue
        for edge_kind, nxt in edges_out.get(cur_uri, ()):
            if edge_kind not in PATH_EDGES:
                continue
            if nxt in seen:
                continue
            seen.add(nxt)
            nxt_node = node_index.get(nxt)
            if nxt_node is None:
                # Cross-boundary ref we don't have body for — summary only.
                pack[nxt] = {"uri": nxt, "status": "EXTERNAL", "summary_only": True}
                continue
            if d + 1 == depth:
                # Boundary: names + types only (§3.6 pseudocode).
                pack[nxt] = {
                    "uri": nxt_node["uri"],
                    "kind": nxt_node.get("kind"),
                    "status": nxt_node.get("status"),
                    "modifier": nxt_node.get("modifier"),
                    "summary_only": True,
                }
            else:
                pack[nxt] = dict(nxt_node)
            frontier.append((nxt, d + 1))

    # Universal context (light, always relevant): tokens + components.
    for ent in entities:
        if ent.get("kind") in ("token", "component") and ent["uri"] not in pack:
            pack[ent["uri"]] = {
                "uri": ent["uri"],
                "kind": ent["kind"],
                "status": ent.get("status"),
                "universal_context": True,
            }

    # Observations slice (opt-in, default True).
    obs_slice: Optional[Dict[str, Any]] = None
    if include_observations:
        obs_summary = projection.get("observations_summary") or {}
        obs_slice = {
            "by_category": obs_summary.get("last_7_days", {}).get("by_category", {}),
            "hot_subjects": obs_summary.get("last_7_days", {}).get("hot_subjects", [])[:5],
        }

    # Estimate tokens + maybe abort (DIRECTIVE per D11 MODIFIED).
    estimation_obj = {"pack": pack, "observations": obs_slice}
    tokens = _estimate_tokens(estimation_obj)

    if tokens > ceiling:
        # Directive abort — include suggested_splits[].
        splits = _suggest_splits(pack, node_index)
        return {
            "query": "focus_pack",
            "projection_id": projection.get("projection_id"),
            "uri": uri,
            "found": True,
            "error": "FOCUS_PACK_TOO_BIG",
            "token_count": tokens,
            "ceiling": ceiling,
            "entity_count": len(pack),
            "entities": sorted(pack.keys()),
            "suggested_splits": splits,
            "remediation": "Split this work across multiple agent-teams per the suggested cuts.",
        }

    result: Dict[str, Any] = {
        "query": "focus_pack",
        "projection_id": projection.get("projection_id"),
        "uri": uri,
        "found": True,
        "depth": depth,
        "ceiling": ceiling,
        "token_count": tokens,
        "entity_count": len(pack),
        "pack": pack,
    }
    if include_tests:
        result["tests"] = {"note": "test_count from each entity body"}
    if include_observations and obs_slice is not None:
        result["observations"] = obs_slice
    return result


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------

def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="project-state query")
    parser.add_argument("--project-root", required=False, type=Path,
                        help="project root (contains .project-state/)")
    parser.add_argument("--no-self-heal", action="store_true",
                        help="fail with STALE_PROJECTION_HASH_MISMATCH instead of reconciling")

    sub = parser.add_subparsers(dest="op", required=True)

    p_fp = sub.add_parser("focus_pack")
    p_fp.add_argument("--uri", required=True)
    p_fp.add_argument("--depth", type=int, default=DEFAULT_FOCUS_DEPTH)
    p_fp.add_argument("--ceiling", type=int, default=DEFAULT_TOKEN_CEILING)
    p_fp.add_argument("--relevance", default="strict", choices=["strict"])
    p_fp.add_argument("--include-tests", action="store_true")
    p_fp.add_argument("--include-observations", action="store_true", default=True)
    p_fp.add_argument("--no-include-observations", dest="include_observations",
                      action="store_false")

    sub.add_parser("orphans")

    p_nb = sub.add_parser("next_buildable")
    p_nb.add_argument("--limit", type=int, default=None)

    p_bs = sub.add_parser("by_status")
    p_bs.add_argument("--status", required=True)
    p_bs.add_argument("--modifier", default=None)

    p_im = sub.add_parser("impact")
    p_im.add_argument("--uri", required=True)

    p_rv = sub.add_parser("resolve")
    p_rv.add_argument("--uri", required=True)

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.project_root is None:
        sys.stderr.write("--project-root is required\n")
        return 2

    project_root = Path(args.project_root).resolve()
    allow_self_heal = not args.no_self_heal

    projection, err = _load_fresh_projection(
        project_root,
        op=args.op,
        allow_self_heal=allow_self_heal,
    )
    if err is not None:
        sys.stderr.write(f"{err}\n")
        return 1
    if projection is None:
        sys.stderr.write("projection unavailable\n")
        return 1

    if args.op == "resolve":
        result = op_resolve(projection, args.uri)
    elif args.op == "orphans":
        result = op_orphans(projection)
    elif args.op == "next_buildable":
        result = op_next_buildable(projection, args.limit)
    elif args.op == "by_status":
        result = op_by_status(projection, args.status, args.modifier)
    elif args.op == "impact":
        result = op_impact(projection, args.uri)
    elif args.op == "focus_pack":
        result = op_focus_pack(
            projection,
            args.uri,
            args.depth,
            args.ceiling,
            args.include_tests,
            args.include_observations,
        )
    else:
        sys.stderr.write(f"unknown op: {args.op}\n")
        return 2

    sys.stdout.write(_canonical_json(result))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
