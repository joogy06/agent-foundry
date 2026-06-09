#!/usr/bin/env python3
"""goldcheck.py — call-edge accuracy gate against a hand-labeled gold file.

The challenger's critical mitigation (design §8): the LLM call-graph can be wrong,
there is no native oracle for COBOL/DSX, and the confidence tag flags uncertainty
but NOT incorrectness — so without an accuracy measurement the store becomes a
write-once never-trusted graveyard. goldcheck.py measures it:

  precision = |extracted_call_edges ∩ gold_call_edges| / |extracted_call_edges|
  recall    = |extracted_call_edges ∩ gold_call_edges| / |gold_call_edges|

Edges are compared by NAME pair (from_name, to_name), resolved from the index's
content-addressed symbol IDs via its symbol table (the gold is authored
independently of any artifact hash). 'calls' relationships in the index correspond
to PERFORM (intra-program) and CALL (inter-program) transfers in the gold.

Then it records the number in the promoted catalog via store.set_accuracy, which
sets advisory=True for the format until precision clears the threshold (default
0.85). impact() reads that flag and stays speculative below threshold (design §8).
The navigator header + the printed manifest also report the number.

Pure stdlib (+ store.py for the catalog write). No LLM calls.

CLI usage:
    goldcheck.py <index_json> <gold_json> [--threshold 0.85]
                 [--store PATH] [--record]   (--record writes the catalog accuracy)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

DEFAULT_THRESHOLD = 0.85


def _id_to_name(index: dict) -> Dict[str, str]:
    return {s.get("symbol_id"): s.get("name") for s in index.get("symbols", []) if s.get("symbol_id")}


def extracted_call_edges(index: dict) -> Set[Tuple[str, str]]:
    """Set of (from_name, to_name) for every 'calls' relationship in the index."""
    id2name = _id_to_name(index)
    edges: Set[Tuple[str, str]] = set()
    for rel in index.get("relationships", []):
        if rel.get("rel") != "calls":
            continue
        fn = id2name.get(rel.get("from_id"))
        tn = id2name.get(rel.get("to_id"))
        if fn and tn:
            edges.add((fn, tn))
    return edges


def gold_call_edges(gold: dict) -> Set[Tuple[str, str]]:
    return {(e["from_name"], e["to_name"]) for e in gold.get("call_edges", [])}


def score(index: dict, gold: dict) -> dict:
    extracted = extracted_call_edges(index)
    truth = gold_call_edges(gold)
    correct = extracted & truth
    precision = (len(correct) / len(extracted)) if extracted else None
    recall = (len(correct) / len(truth)) if truth else None
    return {
        "format": gold.get("format", "cobol"),
        "program": gold.get("program", ""),
        "extracted_edges": len(extracted),
        "gold_edges": len(truth),
        "correct_edges": len(correct),
        "precision": precision,
        "recall": recall,
        "missing_edges": sorted(list(truth - extracted)),
        "spurious_edges": sorted(list(extracted - truth)),
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("index_json", type=Path)
    parser.add_argument("gold_json", type=Path)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--store")
    parser.add_argument("--record", action="store_true",
                        help="Record the result in the promoted catalog accuracy block.")
    args = parser.parse_args(argv)

    for p in (args.index_json, args.gold_json):
        if not p.exists():
            print(f"ERROR: not found: {p}", file=sys.stderr)
            return 2

    index = json.loads(args.index_json.read_text(encoding="utf-8"))
    gold = json.loads(args.gold_json.read_text(encoding="utf-8"))

    result = score(index, gold)
    result["threshold"] = args.threshold
    prec = result["precision"]
    result["advisory"] = prec is None or prec < args.threshold

    if args.record:
        import store as st
        root = st.resolve_store_root(args.store)
        st.set_accuracy(
            root, result["format"], precision=prec, recall=result["recall"],
            gold_program=result["program"], precision_threshold=args.threshold,
        )
        result["recorded"] = True

    print(json.dumps(result, sort_keys=True, indent=2))
    # Exit 0 always (gold check is informational/advisory; it never blocks ingest).
    # A separate consumer (tests / CI) can assert precision >= threshold.
    return 0


if __name__ == "__main__":
    sys.exit(main())
