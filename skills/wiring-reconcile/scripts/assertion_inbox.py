#!/usr/bin/env python3
"""assertion_inbox.py — normalize per-agent asserted edge files.

Per design 2026-04-14 §2.3 (Agent-assertion ownership) and §5.2 (Reconcile
lifecycle step 3). This is a **library module**, never a standalone skill.
It is consumed by `reconciler.py` (WP-5) — WP-4's boundary is that the
inbox is importable, validates every line against `wiring-source-edge.v1`,
enforces canonical component naming against the contract map, and logs +
skips malformed input rather than aborting the reconcile run.

Writer ownership: this module is **read-only** with respect to the
filesystem. It NEVER writes files. The reconciler collects normalized
edges in memory and later writes them into `snapshot.json`.

Public API:
    read_assertions(run_dir, contract_map_components, logger=None) -> Iterator[Edge]
        Iterate all `asserted/<agent_id>.jsonl` files under the run dir,
        yielding validated edge dicts. Unmapped or malformed lines are
        logged (if a logger is supplied) and skipped.

    AssertionStats
        Dataclass counting per-run processed/skipped/unmapped lines.
        Returned by read_assertions_with_stats() for reconcile statistics.

Dependencies: jsonschema (Draft 2020-12 per existing pattern), standard
library only otherwise.

Drift canary: ALDEBARAN-7 (see ledger convention; this module itself does
not emit events, but the reconciler includes it verbatim).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

try:
    from jsonschema import Draft202012Validator
except ImportError as _e:  # pragma: no cover - environment invariant
    raise ImportError(
        "assertion_inbox requires jsonschema>=4.18 for Draft202012Validator"
    ) from _e


# ---------------------------------------------------------------------------
# Schema loading (lazy — one load per process)
# ---------------------------------------------------------------------------

_SOURCE_EDGE_SCHEMA_PATH = (
    Path.home()
    / ".claude"
    / "skills"
    / "wiring-extract-static"
    / "schemas"
    / "wiring-source-edge.v1.json"
)

_VALIDATOR: Optional[Draft202012Validator] = None


def _load_validator() -> Draft202012Validator:
    global _VALIDATOR
    if _VALIDATOR is None:
        schema = json.loads(_SOURCE_EDGE_SCHEMA_PATH.read_text(encoding="utf-8"))
        _VALIDATOR = Draft202012Validator(schema)
    return _VALIDATOR


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

Edge = Dict[str, object]


@dataclass
class AssertionStats:
    files_scanned: int = 0
    lines_read: int = 0
    edges_valid: int = 0
    malformed_json: int = 0
    schema_invalid: int = 0
    unmapped_component: int = 0
    unmapped_paths: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "files_scanned": self.files_scanned,
            "lines_read": self.lines_read,
            "edges_valid": self.edges_valid,
            "malformed_json": self.malformed_json,
            "schema_invalid": self.schema_invalid,
            "unmapped_component": self.unmapped_component,
            "unmapped_paths": sorted(set(self.unmapped_paths)),
        }


# ---------------------------------------------------------------------------
# Core reader
# ---------------------------------------------------------------------------


def _iter_asserted_files(run_dir: Path) -> List[Path]:
    """Return sorted list of `<run_dir>/asserted/*.jsonl` files.

    Deterministic order ensures reconcile output is stable across platforms.
    Missing `asserted/` directory -> empty list (legal empty case).
    """
    asserted_dir = Path(run_dir) / "asserted"
    if not asserted_dir.is_dir():
        return []
    return sorted(asserted_dir.glob("*.jsonl"))


def _agent_id_from_path(path: Path) -> str:
    return path.stem


def read_assertions_with_stats(
    run_dir: Path,
    contract_map_components: Iterable[str],
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[Edge], AssertionStats]:
    """Read all `asserted/*.jsonl` files under run_dir, return (edges, stats).

    Parameters
    ----------
    run_dir
        Path to `.wiring/runs/<run_id>/`. Must exist; `asserted/` subdirectory
        may or may not exist (empty run is legal).
    contract_map_components
        Iterable of known component ids from `progress/contract-map.yaml`.
        Edges whose `src_component` or `dst_component` is not in this set are
        marked unmapped and skipped. Callers pass `ledger_rows` or map.components
        equivalent.
    logger
        Optional `logging.Logger`. If None, a null logger is used. Malformed
        lines and unmapped components are logged at WARNING level; everything
        else at DEBUG.

    Returns
    -------
    (edges, stats)
        `edges` is a list of edge dicts that passed every check. Stable order:
        files sorted alphabetically, lines in file order.
        `stats` tracks counts for reconcile statistics.
    """
    logger = logger or logging.getLogger("wiring-reconcile.assertion_inbox")

    run_dir = Path(run_dir)
    components: Set[str] = set(contract_map_components or [])
    validator = _load_validator()

    edges: List[Edge] = []
    stats = AssertionStats()

    for asserted_file in _iter_asserted_files(run_dir):
        stats.files_scanned += 1
        agent_id = _agent_id_from_path(asserted_file)
        try:
            raw_lines = asserted_file.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            logger.warning(
                "assertion_inbox: cannot read %s: %s", asserted_file, e
            )
            continue
        for line_no, line in enumerate(raw_lines, start=1):
            s = line.strip()
            if not s:
                continue
            stats.lines_read += 1
            try:
                edge = json.loads(s)
            except json.JSONDecodeError as e:
                stats.malformed_json += 1
                logger.warning(
                    "assertion_inbox: %s:%d malformed JSON: %s",
                    asserted_file.name, line_no, e,
                )
                continue
            if not isinstance(edge, dict):
                stats.malformed_json += 1
                logger.warning(
                    "assertion_inbox: %s:%d line is not a JSON object",
                    asserted_file.name, line_no,
                )
                continue
            # Schema validation (wiring-source-edge.v1)
            errors = sorted(validator.iter_errors(edge), key=lambda e: e.path)
            if errors:
                stats.schema_invalid += 1
                msg = "; ".join(
                    f"{list(err.path)}: {err.message}" for err in errors[:3]
                )
                logger.warning(
                    "assertion_inbox: %s:%d schema invalid: %s",
                    asserted_file.name, line_no, msg,
                )
                continue
            # Canonical component naming enforcement: src + dst must resolve
            # to a component id present in the contract map. If the contract
            # map is empty (no components), we skip this check — callers must
            # supply components; an empty set means "accept everything" only
            # when the caller deliberately passes set() and accepts the risk.
            if components:
                bad_components = []
                if edge.get("src_component") not in components:
                    bad_components.append(("src", edge.get("src_component")))
                if edge.get("dst_component") not in components:
                    bad_components.append(("dst", edge.get("dst_component")))
                if bad_components:
                    stats.unmapped_component += 1
                    for role, name in bad_components:
                        stats.unmapped_paths.append(
                            f"{asserted_file.name}:{line_no} {role}={name!r}"
                        )
                    logger.warning(
                        "assertion_inbox: %s:%d unmapped components %s",
                        asserted_file.name, line_no, bad_components,
                    )
                    continue
            # Annotate agent provenance for reconcile (non-authoritative, does
            # not change edge_id).
            if "_agent_id" not in edge:
                edge["_agent_id"] = agent_id
            # Force evidence_source to "agent_asserted" for assertions — a
            # well-formed assertion file may have declared static_extract in
            # error; reconcile semantics require these edges to be classified
            # as agent_asserted regardless of what the file claims.
            edge["evidence_source"] = "agent_asserted"
            stats.edges_valid += 1
            edges.append(edge)

    return edges, stats


def read_assertions(
    run_dir: Path,
    contract_map_components: Iterable[str],
    logger: Optional[logging.Logger] = None,
) -> Iterator[Edge]:
    """Iterator wrapper around read_assertions_with_stats for ergonomic use."""
    edges, _ = read_assertions_with_stats(run_dir, contract_map_components, logger=logger)
    for e in edges:
        yield e


# ---------------------------------------------------------------------------
# Convenience: components from contract map
# ---------------------------------------------------------------------------


def load_component_ids(contract_map_path: Path) -> List[str]:
    """Extract `components[].id` list from a contract-map YAML.

    Used by reconciler when caller doesn't already have the component list.
    Returns [] if the file is missing or malformed.
    """
    try:
        import yaml  # local import — reconciler handles pyyaml dependency globally
    except ImportError:
        return []
    if not Path(contract_map_path).is_file():
        return []
    try:
        doc = yaml.safe_load(Path(contract_map_path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return [c["id"] for c in (doc.get("components") or []) if isinstance(c, dict) and c.get("id")]


# ---------------------------------------------------------------------------
# CLI (self-test; not a real entry point — reconcile owns orchestration)
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="assertion_inbox self-test")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--contract-map", default=None)
    args = parser.parse_args(argv)
    comps: List[str] = []
    if args.contract_map:
        comps = load_component_ids(Path(args.contract_map))
    logging.basicConfig(level=logging.INFO)
    edges, stats = read_assertions_with_stats(Path(args.run_dir), comps)
    print(json.dumps({"edge_count": len(edges), "stats": stats.as_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
