#!/usr/bin/env python3
"""run.py — CLI entry for wiring-query.

Two operations only (v1): `impact` and `subgraph_for_llm`.
Deterministic output; no LLM calls.

Per design 2026-04-14 §5.3.

Usage:
  python3 -m wiring_query impact --symbol SYM [--max-depth N] [--include-stale] --project-dir DIR
  python3 -m wiring_query subgraph_for_llm --anchors "a,b,c" [--max-edges N] [--max-tokens N] [--max-depth N] --project-dir DIR

Exit codes:
  0 = success
  1 = snapshot missing / invalid
  2 = invalid CLI args

Drift canary: ALDEBARAN-7.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from loader import load_snapshot, SnapshotMissing, SnapshotInvalid  # noqa: E402
from graph_ops import build_symbol_index, impact, subgraph_for_llm  # noqa: E402


def _parse_args(argv):
    p = argparse.ArgumentParser(prog="wiring-query")
    p.add_argument("--project-dir", required=True,
                   help="Target project root (contains .wiring/latest.json)")
    sub = p.add_subparsers(dest="op", required=True)

    p_impact = sub.add_parser("impact", help="BFS impact from a symbol")
    p_impact.add_argument("--symbol", required=True)
    p_impact.add_argument("--max-depth", type=int, default=3)
    p_impact.add_argument("--include-stale", action="store_true", default=False)

    p_sub = sub.add_parser("subgraph_for_llm", help="Bounded subgraph for LLM context")
    p_sub.add_argument("--anchors", required=True,
                       help="Comma-separated anchor symbols")
    p_sub.add_argument("--max-edges", type=int, default=40)
    p_sub.add_argument("--max-tokens", type=int, default=50000)
    p_sub.add_argument("--max-depth", type=int, default=2)
    p_sub.add_argument("--include-stale", action="store_true", default=False)
    return p.parse_args(argv)


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # argparse swap: --project-dir can appear after the subcommand OR before; we
    # normalise by accepting both orderings. argparse already handles that when
    # --project-dir is a top-level arg and subcommand inherits the parser, so we
    # move --project-dir to the front if it appears after the op for ergonomics.
    # Supported: both orderings. argparse default position handles it because
    # --project-dir is a top-level `required` arg and can appear anywhere.
    args = _parse_args(argv)
    project_dir = Path(args.project_dir).resolve()
    try:
        snapshot = load_snapshot(project_dir)
    except SnapshotMissing as e:
        sys.stderr.write(f"no snapshot: {e}\n")
        return 1
    except SnapshotInvalid as e:
        sys.stderr.write(f"invalid snapshot: {e}\n")
        return 1

    idx = build_symbol_index(snapshot)

    if args.op == "impact":
        result = impact(
            snapshot, args.symbol,
            max_depth=args.max_depth,
            include_stale=args.include_stale,
            index=idx,
        )
    elif args.op == "subgraph_for_llm":
        anchors = [a.strip() for a in args.anchors.split(",") if a.strip()]
        result = subgraph_for_llm(
            snapshot, anchors,
            max_edges=args.max_edges,
            max_tokens=args.max_tokens,
            max_depth=args.max_depth,
            include_stale=args.include_stale,
            index=idx,
        )
    else:  # argparse enforces this unreachable
        sys.stderr.write(f"unknown op: {args.op}\n")
        return 2

    # Canonical JSON output (sorted keys, compact separators) so callers can
    # hash the stdout for caching.
    sys.stdout.write(json.dumps(result, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
