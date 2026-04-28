#!/usr/bin/env python3
"""scope_reaction.py — Bob's reaction to undecided critical scope_delta records.

This module is the FIRST and ONLY production caller of `pause_state.request_pause`
(closes alf gap 1 / S029 design §11). Per the design's CB4 invariant, only bob
orchestrates the pause/amend/resume cycle — skills NEVER call pause_state directly.

The contract: when bob's `G_CONTRACT_SCOPE` gate exits 2 with critical undecided
records, bob invokes `scope_reaction.handle(project_root)` which:

    1. Reads all `.ledger/scope-deltas/<id>.yaml` records with status=undecided.
    2. For each record with severity=critical:
         pause_state.request_pause(project_root, gap=record, requesting_wp=...)
       Subsequent calls dedupe onto the same epoch via pause_state.py:122-127.
    3. Advisory records are NOT acted upon — they persist as audit log only.

Public API:
    handle(project_root) -> dict
        Returns a structured summary of what was triggered:
            { "epoch": "<epoch_str_or_None>",
              "critical_count": int,
              "advisory_count": int,
              "delta_ids": [<critical delta_ids>] }

Invariant (verified by tests/test_scope_reaction.py):
    * If there are zero critical+undecided records, no pause is requested
      and the returned epoch is None.
    * Advisory-only records do NOT trigger pause_state.

This module deliberately has a tiny surface area; the heavy work lives in
pause_state.py (state machine, recovery, atomic writes).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pause_state  # noqa: E402
import scope_delta  # noqa: E402


def handle(project_root: Path) -> Dict[str, Any]:
    """Bob-only entry point. Reads undecided scope_delta records and routes
    critical ones through pause_state.request_pause.

    Args:
        project_root: filesystem path; scope_delta records live at
            <project_root>/.ledger/scope-deltas/.

    Returns:
        dict with keys: epoch (str|None), critical_count (int),
        advisory_count (int), delta_ids (list[str]).
    """
    project_root = Path(project_root).resolve()
    undecided = scope_delta.read_records(project_root, status_filter="undecided")

    critical = [r for r in undecided if r.get("severity") == "critical"]
    advisory = [r for r in undecided if r.get("severity") == "advisory"]

    epoch: Optional[str] = None
    triggered: List[str] = []

    for rec in critical:
        wp = rec.get("requesting_wp", "")
        # Each request_pause call is idempotent at the state-machine level:
        # subsequent gaps queue onto the existing epoch (pause_state.py:122-127).
        epoch = pause_state.request_pause(
            project_root, gap=rec, requesting_wp=wp,
        )
        triggered.append(rec.get("delta_id", ""))

    return {
        "epoch": epoch,
        "critical_count": len(critical),
        "advisory_count": len(advisory),
        "delta_ids": triggered,
    }


# ---------------------------------------------------------------------------
# CLI (status helper for diagnosis only — never used in production hot path)
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    project_root = Path(os.getcwd())
    if len(argv) >= 2:
        project_root = Path(argv[1])
    summary = handle(project_root)
    print(
        f"scope_reaction: epoch={summary['epoch']} "
        f"critical={summary['critical_count']} "
        f"advisory={summary['advisory_count']}"
    )
    for did in summary["delta_ids"]:
        print(f"  triggered: {did}")


if __name__ == "__main__":
    main()
