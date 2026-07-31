"""run.py — intent-map-render CLI entry point (S032 WP-5)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import d1_sequence  # noqa: E402
import d2_cytoscape  # noqa: E402
import d3_sankey  # noqa: E402
import d4_heatmap  # noqa: E402
from loader import (  # noqa: E402
    LoaderError, load_intent_map, load_wiring_snapshot, load_api_delta,
)


HARD_RULE_5_MAX_DIAGRAMS = 3
VALID_DIAGRAMS = ("D1", "D2", "D3", "D4")
FUNCTION_LEVEL_REJECTED = ("function_level", "function-level", "per_function")


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="intent-map-render")
    p.add_argument("--intent-map", required=True, type=Path)
    p.add_argument("--wiring-snapshot", required=True, type=Path)
    p.add_argument("--api-delta", type=Path, default=None)
    p.add_argument("--emit", required=True,
                   help="Comma-separated diagram codes (D1,D2,D3,D4)")
    p.add_argument("--output-dir", type=Path, default=None,
                   help="Directory to write outputs to. If absent, print to stdout.")
    p.add_argument("--max-edges", type=int, default=200,
                   help="D2 edge cap")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    # Parse + validate --emit
    requested = [d.strip() for d in args.emit.split(",") if d.strip()]
    if any(d.lower() in FUNCTION_LEVEL_REJECTED for d in requested):
        sys.stderr.write(
            "EVO_HARD_RULE_5_VIOLATION: function-level diagrams forbidden "
            "(default C4 container+component level only)\n"
        )
        return 2

    invalid = [d for d in requested if d.upper() not in VALID_DIAGRAMS]
    if invalid:
        sys.stderr.write(f"unknown diagram codes: {invalid}; valid: {VALID_DIAGRAMS}\n")
        return 2

    distinct = set(d.upper() for d in requested)
    if len(distinct) > HARD_RULE_5_MAX_DIAGRAMS:
        sys.stderr.write(
            f"EVO_HARD_RULE_5_VIOLATION: requested {len(distinct)} distinct "
            f"diagrams; cap is {HARD_RULE_5_MAX_DIAGRAMS} per consultation turn\n"
        )
        return 2

    # Load inputs
    try:
        intent_map = load_intent_map(args.intent_map)
        wiring_snapshot = load_wiring_snapshot(args.wiring_snapshot)
        api_delta = load_api_delta(args.api_delta)
    except LoaderError as e:
        sys.stderr.write(f"ENV_ERROR: {e}\n")
        return 3

    # Dispatch
    output_dir = args.output_dir
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    outputs = {}
    for code in sorted(distinct):
        if code == "D1":
            text = d1_sequence.render(intent_map)
            outputs["D1.md"] = text
        elif code == "D2":
            text = d2_cytoscape.render_string(
                intent_map, wiring_snapshot, max_edges=args.max_edges,
            )
            outputs["D2.json"] = text
        elif code == "D3":
            if api_delta is None:
                # Soft fallback: print a note instead of failing
                outputs["D3.md"] = "<!-- D3: --api-delta not provided -->\n"
            else:
                outputs["D3.md"] = d3_sankey.render(api_delta)
        elif code == "D4":
            outputs["D4.md"] = d4_heatmap.render(intent_map)

    if output_dir is not None:
        for fname, content in outputs.items():
            (output_dir / fname).write_text(content, encoding="utf-8")
        for fname in sorted(outputs.keys()):
            sys.stdout.write(f"wrote {output_dir / fname}\n")
    else:
        for fname in sorted(outputs.keys()):
            sys.stdout.write(f"=== {fname} ===\n")
            sys.stdout.write(outputs[fname])
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
