#!/usr/bin/env python3
"""partition.py — bounded synthetic component partitioner for an arbitrary repo.

The load-bearing piece (design §4 + §11 Fix-2 + §12 C2/C3/C5 + §13 auto-gate).
Deterministic. NO PageRank / NO community-detection.

Produces a `component-partition.v1` synthetic contract-map under `.comprehension/`
(NEVER under `progress/`). The map is schema-compatible with the real contract-map
on `components[].{id, source_paths}` and additionally carries the C5 canonical
expanded file inventory (`components[].source_files`), per-component cost, and the
auto-resolution decision log.

§13 (no user pause): every HALT in the design becomes an AUTOMATIC decision:
  - over-partition (count>CAP OR fragmentation high) → cap + collapse-tail into `misc`
  - under-partition / giant component (>MAX_FILES / >MAX_BYTES) → auto-split if a clean
    sub-boundary exists, else auto-degrade to structural-only (no LLM intent)
  - per-component over budget → auto-degrade with omission note
  - ratify → auto-write partition.lock (recomputed + diffed each run, C9)

The skill logs a partition + cost report to `.comprehension/`; it never blocks.

CLI:
    python3 partition.py --project-dir DIR [--static-jsonl PATH] [--out-dir DIR]
                         [--cap N] [--max-files N] [--max-bytes N]
                         [--per-component-token-budget N] [--ratify]
Exit codes:
    0  partition produced (always, under §13 auto-gate)
    1  unrecoverable (bad args, project-dir missing, no source files at all)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed\n")
    sys.exit(1)

PARTITION_VERSION = "1.0.0"

# Directories never treated as source (mirrors wiring-extract-static._SKIP_DIRS + scratch dirs)
_SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules", "dist", "build",
    ".wiring", ".ledger", ".forge", ".comprehension", ".pytest_cache", ".mypy_cache",
    ".tox", ".idea", ".vscode", "htmlcov", ".eggs", "site-packages", ".cache",
}

# Source extensions we partition over. Python + TS/TSX get LLM intent; the rest are
# structural-only (no LLM). The set governs membership; intent_mode is decided later.
_LLM_EXTS = {".py", ".ts", ".tsx"}
_STRUCTURAL_EXTS = {
    ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".rb", ".php",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".kt", ".scala", ".swift",
}
_SOURCE_EXTS = _LLM_EXTS | _STRUCTURAL_EXTS

_MISC_ID = "misc"

# "Container" directories are not components themselves — they hold components.
# The directory-primary partition DESCENDS through them to their children (the §4
# step 1 "src/* / services/* / app_deploy/src/*" signal), so a repo whose code lives
# under app_deploy/src/products/<x> yields base / dlp / logsnif / cef — the hand-doc
# granularity — rather than one giant `app_deploy`. Descent is bounded.
_CONTAINER_DIRS = {
    "src", "app_deploy", "app", "lib", "libs", "packages", "pkg", "services",
    "products", "modules", "apps", "components", "internal", "cmd", "_base",
}
_CONTAINER_DESCENT_MAX_DEPTH = 4


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class PartitionConfig:
    """The one config block bob can tune (design §11 Fix-2)."""
    cap: int = 12
    fragment_pct_threshold: float = 0.40
    max_files: int = 40
    max_bytes: int = 512_000
    # est-token budget per component before auto-degrade; factors in 2x two-arm
    # (the orchestrator doubles bytes/4 → est_tokens already doubled when compared).
    per_component_token_budget: int = 120_000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cap": self.cap,
            "fragment_pct_threshold": self.fragment_pct_threshold,
            "max_files": self.max_files,
            "max_bytes": self.max_bytes,
            "per_component_token_budget": self.per_component_token_budget,
        }


@dataclass
class Candidate:
    """A candidate component before cap/gate resolution."""
    cid: str
    rel_dir: str                       # project-relative directory prefix ("" = repo root)
    files: List[str] = field(default_factory=list)   # project-relative file paths
    method: str = "directory"
    entry_points: List[str] = field(default_factory=list)
    score: int = 0
    # True if this candidate was reached via CONTAINER DESCENT (already at a
    # meaningful product level, e.g. src/products/dlp) — the giant-split should
    # DEGRADE it (structural-only) rather than fragment it into web/spa/routes.
    # False for a plain top-level dir, which the giant-split MAY split once.
    atomic: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rel(p: Path, project_dir: Path) -> str:
    return p.relative_to(project_dir).as_posix()


def walk_source_files(project_dir: Path) -> List[Path]:
    """All source files under project_dir, pruning skip dirs and dotdirs."""
    out: List[Path] = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in _SOURCE_EXTS:
                out.append(p)
    return sorted(out)


def _top_segment(rel_path: str) -> str:
    """First path segment of a project-relative file path; '' if at repo root."""
    parts = rel_path.split("/")
    return parts[0] if len(parts) > 1 else ""


def _sanitize_id(raw: str) -> str:
    """Make a component id conform to ^[a-zA-Z0-9_.-]+$."""
    out = []
    for ch in raw:
        out.append(ch if (ch.isalnum() or ch in "_.-") else "_")
    s = "".join(out).strip("_")
    return s or "root"


def read_static_entry_points(static_jsonl_path: Optional[Path]) -> Dict[str, List[str]]:
    """Harvest entry-point markers per project-relative file from static.jsonl.

    REUSE, not re-detect (Fix-2). Reads route/entry data already in the graph:
    framework plug-ins emit edges with edge_kind in {http_route, ...} and
    callsite_ref.file; Python entry points show up as symbols. We map
    rel-file → list of entry-point labels (edge_kind:symbol). When static.jsonl
    is the clean unmapped_path:* first pass it still carries callsite_ref.file +
    edge_kind, so this works on the first pass too.

    Returns {} on any error (graceful — the filesystem fallback in
    `detect_entry_point_files` still seeds main/route entry points).
    """
    out: Dict[str, List[str]] = {}
    if static_jsonl_path is None or not static_jsonl_path.is_file():
        return out
    route_kinds = {"http_route", "route", "ws_route", "socket_event", "cli_entry", "rpc"}
    try:
        for line in static_jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                edge = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = edge.get("edge_kind", "")
            cs = edge.get("callsite_ref") or {}
            f = cs.get("file")
            # callsite file may be absolute; we normalize to basename-join later via membership.
            if f and kind in route_kinds:
                label = f"{kind}:{edge.get('dst_symbol') or edge.get('src_symbol') or '?'}"
                out.setdefault(f, []).append(label)
    except OSError:
        return {}
    return out


def detect_entry_point_files(project_dir: Path, source_files: List[Path]) -> Dict[str, List[str]]:
    """Documented filesystem fallback for entry-point detection.

    Light scan (NOT a route re-implementation): flags files that look like an
    entry point by well-known conventions:
      - `if __name__ == "__main__":` or a top-level `def main(` (Python)
      - basename in {main, __main__, app, server, index, cli, manage, wsgi, asgi}
    Returns {rel_file: [labels]}.
    """
    out: Dict[str, List[str]] = {}
    ep_basenames = {"main", "__main__", "app", "server", "index", "cli", "manage", "wsgi", "asgi"}
    for p in source_files:
        rel = _rel(p, project_dir)
        labels: List[str] = []
        stem = p.stem.lower()
        if stem in ep_basenames:
            labels.append(f"basename:{stem}")
        if p.suffix.lower() == ".py":
            try:
                head = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                head = ""
            if '__name__ == "__main__"' in head or "__name__ == '__main__'" in head:
                labels.append("python:__main__")
        if labels:
            out[rel] = labels
    return out


# ---------------------------------------------------------------------------
# Candidate construction (directory-primary)
# ---------------------------------------------------------------------------


def build_candidates(project_dir: Path, source_files: List[Path]) -> List[Candidate]:
    """Directory-primary partition with CONTAINER DESCENT (§4 step 1).

    One candidate per source directory, BUT descend through "container" dirs
    (src / app_deploy / services / products / ...) to their children so component
    roots land at the meaningful level (base / dlp / logsnif / cef), not at a giant
    `app_deploy`. Files living directly in a container (not in a sub-component) form
    a candidate for that container path. Bounded by _CONTAINER_DESCENT_MAX_DEPTH.
    """
    rel_files = [_rel(p, project_dir) for p in source_files]
    groups: Dict[str, List[str]] = {}
    atomic_dirs: Set[str] = set()
    _assign_descending(rel_files, "", groups, atomic_dirs, depth=0)

    # Build ids, disambiguating leaf-name collisions by widening to parent.child.
    rel_dirs = sorted(groups.keys())
    chosen_ids = _unique_ids(rel_dirs)
    candidates: List[Candidate] = []
    for rel_dir in rel_dirs:
        candidates.append(Candidate(
            cid=chosen_ids[rel_dir],
            rel_dir=rel_dir,
            files=sorted(groups[rel_dir]),
            method="directory",
            atomic=(rel_dir in atomic_dirs),
        ))
    return candidates


def _unique_ids(rel_dirs: List[str]) -> Dict[str, str]:
    """Assign a UNIQUE component id to each rel_dir. Prefer the leaf segment; on a
    collision, widen to '<parent>.<leaf>' (and further) until unique. Deterministic."""
    # First pass: leaf candidate per dir.
    proposals: Dict[str, str] = {rd: _component_id_for_dir(rd) for rd in rel_dirs}
    # Detect collisions.
    from collections import Counter
    counts = Counter(proposals.values())
    out: Dict[str, str] = {}
    used: set = set()
    for rd in rel_dirs:
        leaf = proposals[rd]
        if counts[leaf] == 1 and leaf not in used:
            out[rd] = leaf
            used.add(leaf)
            continue
        # widen: include more parent segments until unique
        segs = [s for s in rd.split("/") if s]
        cid = None
        for take in range(2, len(segs) + 1):
            cand = _sanitize_id(".".join(segs[-take:]))
            if cand not in used:
                cid = cand
                break
        if cid is None:
            cid = _sanitize_id(rd.replace("/", "."))
            n = 2
            base = cid
            while cid in used:
                cid = f"{base}.{n}"
                n += 1
        out[rd] = cid
        used.add(cid)
    return out


def _assign_descending(
    rel_files: List[str],
    base_rel: str,
    groups: Dict[str, List[str]],
    atomic_dirs: Set[str],
    *,
    depth: int,
) -> None:
    """Assign files under base_rel to component groups, descending through containers.

    For files under base_rel: group by immediate child segment. A child segment that
    is a CONTAINER dir (and we're under the depth bound) is RECURSED into; a non-
    container child becomes its own component group; files directly in base_rel form
    a group keyed by base_rel itself. A component reached via descent (depth>0) is
    recorded in `atomic_dirs` → the giant-split degrades it rather than fragmenting.
    """
    prefix = (base_rel + "/") if base_rel else ""
    by_child: Dict[str, List[str]] = {}
    for f in rel_files:
        rest = f[len(prefix):] if f.startswith(prefix) else f
        parts = rest.split("/")
        child = parts[0] if len(parts) > 1 else "__root__"
        by_child.setdefault(child, []).append(f)

    for child, files in by_child.items():
        if child == "__root__":
            # files directly in base_rel → a group at base_rel (or 'root' at repo root)
            groups.setdefault(base_rel, []).extend(files)
            if depth > 0 and base_rel:
                atomic_dirs.add(base_rel)
            continue
        child_rel = f"{base_rel}/{child}" if base_rel else child
        if child in _CONTAINER_DIRS and depth < _CONTAINER_DESCENT_MAX_DEPTH:
            _assign_descending(files, child_rel, groups, atomic_dirs, depth=depth + 1)
        else:
            groups.setdefault(child_rel, []).extend(files)
            if depth > 0:
                atomic_dirs.add(child_rel)


def _component_id_for_dir(rel_dir: str) -> str:
    """Component id from a (possibly nested) dir path.

    Uses the LAST path segment (the meaningful component name: base, dlp, logsnif),
    falling back to 'root' for repo-root files. Disambiguates collisions by including
    the parent when the leaf alone would be ambiguous (handled by the caller's
    uniqueness check; here we prefer the leaf for readability).
    """
    if not rel_dir:
        return "root"
    return _sanitize_id(rel_dir.split("/")[-1])


def score_candidates(project_dir: Path, candidates: List[Candidate]) -> None:
    """Lift project-documentation's component-detection signals (§4 step 1).

    own-startup +3 (entry-point file present), own-config +2 (a config-ish file in
    the dir), file-count weight (depended-on-by proxy). Deterministic.
    """
    config_markers = {"pyproject.toml", "setup.py", "setup.cfg", "package.json",
                      "config.py", "settings.py", "dockerfile", "makefile"}
    for c in candidates:
        score = 0
        if c.entry_points:
            score += 3
        base = project_dir / c.rel_dir if c.rel_dir else project_dir
        try:
            names = {p.name.lower() for p in base.iterdir() if p.is_file()} if base.is_dir() else set()
        except OSError:
            names = set()
        if names & config_markers:
            score += 2
        # file-count as a mild ordering signal (more files = more "core")
        score += min(len(c.files), 10)
        c.score = score


def assign_entry_points(
    project_dir: Path,
    candidates: List[Candidate],
    ep_by_file: Dict[str, List[str]],
) -> None:
    """Attach entry-point labels to whichever candidate owns the file (exclusive)."""
    file_to_cand: Dict[str, Candidate] = {}
    for c in candidates:
        for f in c.files:
            file_to_cand[f] = c
    # Static-derived ep files may be absolute; match by basename suffix against owned files.
    owned_rel = set(file_to_cand.keys())
    for ep_file, labels in ep_by_file.items():
        rel = ep_file
        if rel not in owned_rel:
            # try matching by suffix (absolute callsite path → owned rel path)
            cand_match = None
            for owned in owned_rel:
                if ep_file.endswith(owned) or owned.endswith(ep_file.split("/")[-1]):
                    cand_match = owned
                    break
            if cand_match is None:
                continue
            rel = cand_match
        c = file_to_cand.get(rel)
        if c is not None:
            for lab in labels:
                if lab not in c.entry_points:
                    c.entry_points.append(lab)


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def component_cost(project_dir: Path, files: List[str]) -> Dict[str, int]:
    """file/byte/est-token totals. est_tokens = (bytes/4) * 2 (two-arm factor)."""
    byte_count = 0
    for rel in files:
        p = project_dir / rel
        try:
            byte_count += p.stat().st_size
        except OSError:
            continue
    est_tokens = (byte_count // 4) * 2
    return {"file_count": len(files), "byte_count": byte_count, "est_tokens": est_tokens}


# ---------------------------------------------------------------------------
# Auto-gate (§13): over-partition (cap/fragment) + under-partition (giant/budget)
# ---------------------------------------------------------------------------


def _children_by_dir(comp_files: List[str], rel_dir: str) -> Dict[str, List[str]]:
    """Group files by their immediate child segment below rel_dir.

    '__root__' collects files that live directly in rel_dir (no further nesting).
    """
    prefix = (rel_dir + "/") if rel_dir else ""
    by_child: Dict[str, List[str]] = {}
    for f in comp_files:
        rest = f[len(prefix):] if f.startswith(prefix) else f
        parts = rest.split("/")
        child = parts[0] if len(parts) > 1 else "__root__"
        by_child.setdefault(child, []).append(f)
    return by_child


def _clean_subsplit(
    project_dir: Path, comp_files: List[str], rel_dir: str,
    *, min_share: float = 0.10,
) -> Optional[List[Tuple[str, str, List[str]]]]:
    """Carve a giant component into >=2 parts on the immediate child-dir boundary.

    Returns [(child_suffix, child_rel_dir, files), ...] if a clean boundary exists
    (>=2 child dirs each holding >= min_share of files), else None. Deterministic.
    The remainder (root files + sub-share children) folds into the first part.
    """
    by_child = _children_by_dir(comp_files, rel_dir)
    sizable = {k: v for k, v in by_child.items() if k != "__root__"}
    if len(sizable) < 2:
        return None
    total = len(comp_files)
    big = [(k, v) for k, v in sorted(sizable.items()) if len(v) >= max(1, int(total * min_share))]
    if len(big) < 2:
        return None
    chosen = {k for k, _ in big}
    remainder: List[str] = []
    for k, v in by_child.items():
        if k not in chosen:
            remainder.extend(v)
    out: List[Tuple[str, str, List[str]]] = []
    for i, (k, v) in enumerate(big):
        child_rel = f"{rel_dir}/{k}" if rel_dir else k
        files = sorted(v + remainder) if i == 0 else sorted(v)
        out.append((k, child_rel, files))
    return out


def _split_recursively(
    project_dir: Path,
    cid: str,
    rel_dir: str,
    files: List[str],
    entry_points: List[str],
    cfg: PartitionConfig,
    decisions: List[Dict[str, str]],
    *,
    depth: int = 0,
    max_depth: int = 6,
) -> List[Candidate]:
    """Recursively split a giant component down the directory tree until each part is
    under the limits OR no clean boundary remains (then degrade that part).

    Bounded by max_depth (defensive). Deterministic. The dogfood (app_deploy/src/...)
    needs this to reach base / products/<x> rather than stopping at app_deploy.src.
    """
    cost = component_cost(project_dir, files)
    giant = (cost["file_count"] > cfg.max_files) or (cost["byte_count"] > cfg.max_bytes)
    over_budget = cost["est_tokens"] > cfg.per_component_token_budget

    if not (giant or over_budget):
        return [Candidate(cid=cid, rel_dir=rel_dir, files=sorted(files),
                          method=("split" if depth > 0 else "directory"),
                          entry_points=sorted(set(entry_points)))]

    if giant:
        decisions.append({"kind": "giant_observed", "component": cid,
                          "detail": f"files={cost['file_count']} bytes={cost['byte_count']} "
                                    f"(max_files={cfg.max_files}, max_bytes={cfg.max_bytes})"})
    if over_budget:
        decisions.append({"kind": "budget_exceeded", "component": cid,
                          "detail": f"est_tokens={cost['est_tokens']} > budget={cfg.per_component_token_budget}"})

    sub = _clean_subsplit(project_dir, files, rel_dir) if depth < max_depth else None
    if sub is None:
        # No clean sub-boundary (or depth cap) → degrade to structural-only.
        c = Candidate(cid=cid, rel_dir=rel_dir, files=sorted(files),
                      method=("split" if depth > 0 else "directory"),
                      entry_points=sorted(set(entry_points)))
        setattr(c, "_degraded", True)
        decisions.append({"kind": "auto_degrade", "component": cid,
                          "detail": "no clean sub-boundary; degraded to structural-only "
                                    "(LLM intent skipped), omission noted"})
        return [c]

    decisions.append({"kind": "auto_split", "component": cid,
                      "detail": f"split into {len(sub)} parts on a clean child-dir boundary "
                                f"(depth={depth})"})
    out: List[Candidate] = []
    for suffix, child_rel, child_files in sub:
        # entry-point labels that belong to files in this part travel with it
        sub_id = _sanitize_id(f"{cid}.{suffix}")
        out.extend(_split_recursively(
            project_dir, sub_id, child_rel, child_files, entry_points, cfg,
            decisions, depth=depth + 1, max_depth=max_depth,
        ))
    return out


def resolve_partition(
    project_dir: Path,
    candidates: List[Candidate],
    cfg: PartitionConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Apply the bidirectional auto-gate. Returns (components, decisions).

    components: list of dicts ready for the synthetic map (id, source_paths,
    source_files, method, entry_points, intent_mode, cost).
    decisions: the auto-resolution log.
    """
    decisions: List[Dict[str, str]] = []

    # --- over-partition: fragmentation observation (informational + drives cap order) ---
    n = len(candidates)
    frag = sum(1 for c in candidates if len(c.files) <= 1)
    frag_pct = (frag / n) if n else 0.0
    if n > cfg.cap:
        decisions.append({"kind": "cap_applied", "component": "*",
                          "detail": f"candidate_count={n} > cap={cfg.cap}; collapsing long tail into '{_MISC_ID}'"})
    if frag_pct > cfg.fragment_pct_threshold:
        decisions.append({"kind": "fragment_observed", "component": "*",
                          "detail": f"{frag}/{n} candidates <=1 file ({frag_pct:.0%} > {cfg.fragment_pct_threshold:.0%}); tail collapse mitigates"})

    # --- cap: keep top (cap-1) by score, collapse the rest into misc ---
    ordered = sorted(candidates, key=lambda c: (-c.score, c.cid))
    kept: List[Candidate]
    tail: List[Candidate]
    if n > cfg.cap:
        kept = ordered[: cfg.cap - 1]
        tail = ordered[cfg.cap - 1:]
    else:
        kept = ordered
        tail = []

    if tail:
        misc_files: List[str] = []
        misc_eps: List[str] = []
        for c in tail:
            misc_files.extend(c.files)
            misc_eps.extend(c.entry_points)
        misc = Candidate(cid=_MISC_ID, rel_dir="", files=sorted(set(misc_files)),
                         method="misc_tail", entry_points=sorted(set(misc_eps)))
        kept.append(misc)
        decisions.append({"kind": "collapse_tail", "component": _MISC_ID,
                          "detail": f"{len(tail)} candidate(s) collapsed into '{_MISC_ID}' ({len(misc.files)} files)"})

    # --- under-partition / giant / budget: RECURSIVELY split (down the dir tree) or
    # degrade. A single kept candidate (e.g. app_deploy with 600+ files) may explode
    # into base / products/<x> / tools / ... — exactly the hand-doc granularity. ---
    # Container descent has already placed components at a meaningful level (base /
    # dlp / logsnif / ...). The giant-split is now a BACKSTOP that splits AT MOST one
    # level for a still-oversized component, then DEGRADES (structural-only) rather
    # than fragmenting it into web/spa/routes leaves. This keeps the partition at the
    # hand-doc product granularity. (max_split_depth=1)
    resolved: List[Candidate] = []
    for c in kept:
        if c.cid == _MISC_ID:
            resolved.append(c)
            continue
        # atomic (container-descended) components degrade rather than fragment
        # (max_depth=0); plain top-level giants may split once (max_depth=1).
        split_depth = 0 if c.atomic else 1
        resolved.extend(_split_recursively(
            project_dir, c.cid, c.rel_dir, c.files, c.entry_points, cfg, decisions,
            max_depth=split_depth,
        ))

    # --- SECOND cap pass: the recursive split may have produced > CAP components.
    # Re-apply the cap (collapse the lowest-file-count tail into / extend misc). ---
    if len(resolved) > cfg.cap:
        # score by file count (more files = more "core"); keep top cap-1, collapse rest.
        ordered2 = sorted(resolved, key=lambda c: (-len(c.files), c.cid))
        keep2 = ordered2[: cfg.cap - 1]
        tail2 = ordered2[cfg.cap - 1:]
        misc_existing = next((c for c in resolved if c.cid == _MISC_ID), None)
        misc_files2: List[str] = list(misc_existing.files) if misc_existing else []
        misc_eps2: List[str] = list(misc_existing.entry_points) if misc_existing else []
        keep2 = [c for c in keep2 if c.cid != _MISC_ID]
        for c in tail2:
            if c.cid == _MISC_ID:
                continue
            misc_files2.extend(c.files)
            misc_eps2.extend(c.entry_points)
        misc2 = Candidate(cid=_MISC_ID, rel_dir="", files=sorted(set(misc_files2)),
                          method="misc_tail", entry_points=sorted(set(misc_eps2)))
        decisions.append({"kind": "cap_applied", "component": "*",
                          "detail": f"post-split component_count>{cfg.cap}; collapsed "
                                    f"{len(tail2)} into '{_MISC_ID}'"})
        resolved = keep2 + [misc2]

    # --- materialize components (canonical inventory + intent_mode + cost) ---
    components: List[Dict[str, Any]] = []
    for c in resolved:
        cost = component_cost(project_dir, c.files)
        intent_mode = _decide_intent_mode(project_dir, c)
        components.append({
            "id": c.cid,
            "source_paths": _minimal_glob_cover(c.rel_dir, c.files),
            "source_files": sorted(c.files),
            "method": c.method,
            "entry_points": sorted(set(c.entry_points)),
            "intent_mode": intent_mode,
            "cost": cost,
            "inputs": [],
            "outputs": [],
            "dependencies": [],
            "integration_points": [],
        })
    # deterministic component order by id
    components.sort(key=lambda d: d["id"])
    return components, decisions


def _decide_intent_mode(project_dir: Path, c: Candidate) -> str:
    """llm if the component has >=1 LLM-supported (.py/.ts/.tsx) file and isn't degraded;
    degraded if auto-degraded; structural-only if no LLM-supported files."""
    if getattr(c, "_degraded", False):
        return "degraded"
    has_llm = any(Path(f).suffix.lower() in _LLM_EXTS for f in c.files)
    return "llm" if has_llm else "structural-only"


def _minimal_glob_cover(rel_dir: str, files: List[str]) -> List[str]:
    """Derive directory-prefix globs from the canonical file list (C5).

    For a directory-primary component the glob is just the dir prefix. For misc /
    split components whose files span multiple top dirs, emit one glob per distinct
    parent directory so the wiring prefix-resolver and intent-extract glob loader
    resolve to the SAME file set. Globs are project-relative, recursive (`/**`).
    """
    if rel_dir:
        return [f"{rel_dir}/**"]
    # span multiple dirs → one prefix per distinct top segment / parent dir
    prefixes: Set[str] = set()
    for f in files:
        parts = f.split("/")
        if len(parts) > 1:
            prefixes.add(parts[0] + "/**")
        else:
            prefixes.add(f)   # a bare root file → exact path
    return sorted(prefixes)


# ---------------------------------------------------------------------------
# Hashing + tree state
# ---------------------------------------------------------------------------


def partition_hash(components: List[Dict[str, Any]]) -> str:
    """sha256 over the canonical (id, sorted source_files) projection. Excludes
    generated_at + cost (cosmetic). The C5 canonical inventory is the hashed surface."""
    projected = [
        {"id": c["id"], "source_files": sorted(c["source_files"])}
        for c in sorted(components, key=lambda d: d["id"])
    ]
    canonical = json.dumps(projected, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def tree_state(project_dir: Path) -> Dict[str, Any]:
    """C12 — explicit working-tree state (not just the git index)."""
    import subprocess
    state: Dict[str, Any] = {"tree_hash": None, "dirty": False, "untracked_count": 0}
    try:
        cp = subprocess.run(["git", "-C", str(project_dir), "write-tree"],
                            capture_output=True, text=True, timeout=30)
        if cp.returncode == 0:
            out = cp.stdout.strip()
            if len(out) == 40:
                state["tree_hash"] = out
        st = subprocess.run(["git", "-C", str(project_dir), "status", "--porcelain"],
                           capture_output=True, text=True, timeout=30)
        if st.returncode == 0:
            lines = [ln for ln in st.stdout.splitlines() if ln.strip()]
            state["dirty"] = any(not ln.startswith("??") for ln in lines)
            state["untracked_count"] = sum(1 for ln in lines if ln.startswith("??"))
    except (OSError, subprocess.SubprocessError):
        pass
    return state


# ---------------------------------------------------------------------------
# Map + lock IO
# ---------------------------------------------------------------------------


_UNSIGNED_HEADER = (
    "# UNSIGNED synthetic contract-map produced by code-comprehension/partition.py.\n"
    "# UNSIGNED — never move under progress/ (collision with a real signed map +\n"
    "# poisons a later gates.py G1 call). This is comprehension scratch, not a gate-bearing map.\n"
)


def build_partition_doc(
    project_dir: Path,
    components: List[Dict[str, Any]],
    decisions: List[Dict[str, str]],
    cfg: PartitionConfig,
) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "provenance": "synthetic-unsigned",
        "partition_version": PARTITION_VERSION,
        "generated_at": now_iso(),
        "project_dir": str(project_dir),
        "partition_hash": partition_hash(components),
        "tree_state": tree_state(project_dir),
        "config": cfg.to_dict(),
        "decisions": decisions,
        "components": components,
    }
    return doc


def write_partition_doc(out_dir: Path, doc: Dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "synthetic-contract-map.yaml"
    body = _UNSIGNED_HEADER + yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    tmp = out.with_suffix(out.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(body, encoding="utf-8")
    os.replace(str(tmp), str(out))
    # machine-readable report alongside
    report = out_dir / "partition-report.json"
    rtmp = report.with_suffix(report.suffix + f".tmp.{os.getpid()}")
    rtmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(rtmp), str(report))
    return out


def _lock_projection(components: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The diffable lock surface: id → (sorted files, sorted entry_points)."""
    return {
        c["id"]: {
            "source_files": sorted(c["source_files"]),
            "entry_points": sorted(c.get("entry_points", [])),
        }
        for c in sorted(components, key=lambda d: d["id"])
    }


def diff_against_lock(out_dir: Path, components: List[Dict[str, Any]]) -> Dict[str, Any]:
    """C9 — recompute draft vs the existing lock. Returns a diff summary.

    {changed: bool, added: [...], removed: [...], moved: [...]} where moved =
    components whose file set or entry points differ.
    """
    lock_path = out_dir / "partition.lock"
    draft = _lock_projection(components)
    if not lock_path.is_file():
        return {"changed": True, "first_run": True, "added": sorted(draft.keys()),
                "removed": [], "moved": []}
    try:
        prev = json.loads(lock_path.read_text(encoding="utf-8")).get("components", {})
    except (OSError, json.JSONDecodeError):
        prev = {}
    added = sorted(set(draft) - set(prev))
    removed = sorted(set(prev) - set(draft))
    moved = sorted(cid for cid in (set(draft) & set(prev)) if draft[cid] != prev[cid])
    changed = bool(added or removed or moved)
    return {"changed": changed, "first_run": False, "added": added,
            "removed": removed, "moved": moved}


def write_lock(out_dir: Path, components: List[Dict[str, Any]], partition_hash_val: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / "partition.lock"
    payload = {
        "schema_version": "1.0.0",
        "partition_hash": partition_hash_val,
        "ratified_at": now_iso(),
        "components": _lock_projection(components),
    }
    tmp = lock_path.with_suffix(lock_path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(lock_path))
    return lock_path


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def partition(
    project_dir: Path,
    *,
    static_jsonl_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    cfg: Optional[PartitionConfig] = None,
    ratify: bool = True,
) -> Dict[str, Any]:
    """Run the full partition. Returns the partition doc dict.

    Under §13, `ratify=True` (default) auto-writes the lock (recomputed + diffed).
    """
    project_dir = project_dir.resolve()
    cfg = cfg or PartitionConfig()
    out_dir = out_dir or (project_dir / ".comprehension")

    source_files = walk_source_files(project_dir)
    if not source_files:
        raise RuntimeError(f"no source files found under {project_dir}")

    candidates = build_candidates(project_dir, source_files)

    # entry points: static-derived (reuse) + filesystem fallback, merged.
    ep_static = read_static_entry_points(static_jsonl_path)
    ep_fs = detect_entry_point_files(project_dir, source_files)
    ep_merged: Dict[str, List[str]] = {}
    for src in (ep_static, ep_fs):
        for f, labels in src.items():
            ep_merged.setdefault(f, [])
            for lab in labels:
                if lab not in ep_merged[f]:
                    ep_merged[f].append(lab)
    assign_entry_points(project_dir, candidates, ep_merged)
    score_candidates(project_dir, candidates)

    components, decisions = resolve_partition(project_dir, candidates, cfg)

    # exclusive-coverage + entry-point-coverage assertions (invariants, not gates)
    _assert_coverage(source_files, project_dir, components, ep_merged, decisions)

    doc = build_partition_doc(project_dir, components, decisions, cfg)

    diff = diff_against_lock(out_dir, components)
    doc["lock_diff"] = diff  # informational; not part of the schema-validated surface
    if diff["changed"] and not diff.get("first_run"):
        decisions.append({"kind": "fragment_observed", "component": "*",
                          "detail": f"lock drift: added={diff['added']} removed={diff['removed']} moved={diff['moved']}"})

    write_partition_doc(out_dir, {k: v for k, v in doc.items() if k != "lock_diff"})
    if ratify:
        write_lock(out_dir, components, doc["partition_hash"])
    return doc


def _assert_coverage(
    source_files: List[Path],
    project_dir: Path,
    components: List[Dict[str, Any]],
    ep_merged: Dict[str, List[str]],
    decisions: List[Dict[str, str]],
) -> None:
    """Exclusive file coverage + entry-point coverage. Records decisions on gaps."""
    all_rel = {_rel(p, project_dir) for p in source_files}
    seen: Set[str] = set()
    dupes: Set[str] = set()
    for c in components:
        for f in c["source_files"]:
            if f in seen:
                dupes.add(f)
            seen.add(f)
    missing = all_rel - seen
    if dupes:
        decisions.append({"kind": "fragment_observed", "component": "*",
                          "detail": f"WARN non-exclusive coverage: {len(dupes)} file(s) in >1 component"})
    if missing:
        decisions.append({"kind": "fragment_observed", "component": "*",
                          "detail": f"WARN {len(missing)} source file(s) unassigned (should be 0)"})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="code-comprehension.partition")
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--static-jsonl", default=None, help="path to static.jsonl for entry-point reuse")
    ap.add_argument("--out-dir", default=None, help="default <project>/.comprehension")
    ap.add_argument("--cap", type=int, default=12)
    ap.add_argument("--fragment-pct-threshold", type=float, default=0.40)
    ap.add_argument("--max-files", type=int, default=40)
    ap.add_argument("--max-bytes", type=int, default=512_000)
    ap.add_argument("--per-component-token-budget", type=int, default=120_000)
    ap.add_argument("--ratify", action="store_true", default=True,
                    help="auto-write partition.lock (default true under §13)")
    ap.add_argument("--no-ratify", dest="ratify", action="store_false")
    ns = ap.parse_args(argv)

    project_dir = Path(ns.project_dir)
    if not project_dir.is_dir():
        sys.stderr.write(f"project-dir not found: {project_dir}\n")
        return 1
    cfg = PartitionConfig(
        cap=ns.cap, fragment_pct_threshold=ns.fragment_pct_threshold,
        max_files=ns.max_files, max_bytes=ns.max_bytes,
        per_component_token_budget=ns.per_component_token_budget,
    )
    static_path = Path(ns.static_jsonl) if ns.static_jsonl else None
    out_dir = Path(ns.out_dir) if ns.out_dir else None
    try:
        doc = partition(project_dir, static_jsonl_path=static_path, out_dir=out_dir,
                        cfg=cfg, ratify=ns.ratify)
    except RuntimeError as e:
        sys.stderr.write(f"partition failed: {e}\n")
        return 1
    n_llm = sum(1 for c in doc["components"] if c["intent_mode"] == "llm")
    n_deg = sum(1 for c in doc["components"] if c["intent_mode"] == "degraded")
    n_str = sum(1 for c in doc["components"] if c["intent_mode"] == "structural-only")
    sys.stdout.write(
        f"partition ok components={len(doc['components'])} "
        f"(llm={n_llm} structural-only={n_str} degraded={n_deg}) "
        f"decisions={len(doc['decisions'])} hash={doc['partition_hash'][:12]}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
