#!/usr/bin/env python3
"""test_blocking_eligible_invariant.py — SC3 blocking_eligible invariant.

Per design 2026-04-14 §5.2 + contract-map.yaml wiring-reconcile success
criterion: "blocking_eligible is true only for edges with at least one
succeeded static_extract evidence entry".

Existing `test_reconciler.py::TestBlockingEligibility` covers per-edge
single-source paths (static_succeeded/partial/skipped). This test adds the
THREE-EDGE-IN-ONE-SNAPSHOT cross-edge invariant and an adversarial
regression case for mixed-source survivorship.

Why this test belongs in wiring-reconcile (not wiring-extract-static)
---------------------------------------------------------------------
`blocking_eligible` is computed by the reconciler (see
`wiring-reconcile/scripts/reconciler.py` line 256), not by the static
extractor. The retargeting note is in the bob completion report and the
ledger event.

Cases
-----
1. **Three coexisting edges in a single snapshot**:
   - static-only edge   -> blocking_eligible = TRUE
   - assertion-only edge -> blocking_eligible = FALSE
   - mixed (static+assertion) edge -> blocking_eligible = TRUE
   All three asserted in a single reconcile call so cross-edge
   consistency is validated, not just per-call behavior.

2. **Adversarial survivorship**: an edge starts static-only in run 1.
   In a hypothetical run 2 the asserted-only entry is added (different
   evidence_source for the SAME edge_id). After reconcile,
   blocking_eligible MUST stay TRUE — the static evidence has not been
   removed, so the invariant must not flip.

   Per the reconciler's actual contract: blocking_eligible is computed
   per-snapshot from the *current* evidence array. If both run 1's static
   and run 2's assertion are present in the same input, the merged edge
   keeps blocking_eligible=TRUE because >=1 static_extract evidence with
   manifest static_status in {succeeded, partial} still holds.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SKILL = Path.home() / ".claude" / "skills" / "wiring-reconcile"
sys.path.insert(0, str(_SKILL / "scripts"))

from reconciler import reconcile  # noqa: E402
from edge_identity import compute_edge_id  # noqa: E402


COMPONENTS = ["auth-service", "user-service", "db"]
TREE = "a" * 40


def _edge(
    src="auth-service",
    src_sym="auth-service.handler",
    dst="db",
    dst_sym="db.User.select",
    kind="calls",
    source="static_extract",
    extractor="fastapi",
    version="1.0.0",
    tree=TREE,
    emitted="2026-04-14T12:00:00Z",
    confidence=None,
):
    e = {
        "schema_version": "1.0.0",
        "edge_id": compute_edge_id(src, src_sym, dst, dst_sym, kind),
        "src_component": src,
        "src_symbol": src_sym,
        "dst_component": dst,
        "dst_symbol": dst_sym,
        "edge_kind": kind,
        "evidence_source": source,
        "extractor_id": extractor,
        "extractor_version": version,
        "workspace_tree_hash": tree,
        "emitted_at": emitted,
    }
    if confidence is not None:
        e["confidence"] = confidence
    return e


def _manifest(static_status="succeeded"):
    return {
        "schema_version": "1.0.0",
        "run_id": "00000000-0000-0000-0000-000000000000",
        "workspace_tree_hash": TREE,
        "project_dir": "/tmp/x",
        "started_at": "2026-04-14T12:00:00Z",
        "sources": [
            {
                "source_id": "wiring-extract-static.fastapi",
                "evidence_source": "static_extract",
                "status": static_status,
                "output_path": "static.jsonl",
                "edge_count": 1,
                "completed_at": "2026-04-14T12:01:00Z",
            },
            {
                "source_id": "agent.bob",
                "evidence_source": "agent_asserted",
                "status": "succeeded",
                "output_path": "asserted/bob.jsonl",
                "edge_count": 1,
                "completed_at": "2026-04-14T12:01:30Z",
            },
        ],
    }


def _do_reconcile(statics=(), asserteds=(), manuals=(), static_status="succeeded"):
    return reconcile(
        static_edges=list(statics),
        asserted_edges=list(asserteds),
        manual_edges=list(manuals),
        manifest=_manifest(static_status),
        contract_map_components=COMPONENTS,
        run_id="00000000-0000-0000-0000-000000000000",
        workspace_tree_hash=TREE,
        generated_at="2026-04-14T12:02:00Z",
        snapshot_generation=1,
        previous_snapshot=None,
        suppressed_edge_ids=[],
    )


class TestBlockingEligibleSC3Invariant(unittest.TestCase):

    def test_three_edge_invariant_in_single_snapshot(self):
        """Static-only=TRUE, assertion-only=FALSE, mixed=TRUE — all in one snapshot."""
        # Edge A: static-only path -- src=auth, dst=db
        a_static = _edge(
            src_sym="auth-service.A_handler",
            dst_sym="db.A_select",
            source="static_extract",
            extractor="fastapi",
        )
        # Edge B: assertion-only path -- src=user, dst=db
        b_asserted = _edge(
            src="user-service",
            src_sym="user-service.B_handler",
            dst_sym="db.B_select",
            source="agent_asserted",
            extractor="bob-assertion",
        )
        # Edge C: mixed path -- src=auth, dst=db (different symbols from A)
        c_static = _edge(
            src_sym="auth-service.C_handler",
            dst_sym="db.C_select",
            source="static_extract",
            extractor="fastapi",
        )
        c_asserted = _edge(
            src_sym="auth-service.C_handler",
            dst_sym="db.C_select",
            source="agent_asserted",
            extractor="bob-assertion",
        )

        snap = _do_reconcile(
            statics=[a_static, c_static],
            asserteds=[b_asserted, c_asserted],
        )

        # Index by edge_id for unambiguous lookup.
        by_eid = {e["edge_id"]: e for e in snap["edges"]}
        self.assertEqual(len(by_eid), 3, f"expected 3 distinct edges, got {len(by_eid)}: {list(by_eid)}")

        a = by_eid[a_static["edge_id"]]
        b = by_eid[b_asserted["edge_id"]]
        c = by_eid[c_static["edge_id"]]
        self.assertEqual(c_static["edge_id"], c_asserted["edge_id"],
                         "C edge identities should collapse on edge_id")

        # SC3: only edges with >=1 static_extract evidence are blocking_eligible.
        self.assertTrue(a["blocking_eligible"],
                        f"static-only edge A must be blocking_eligible: {a}")
        self.assertFalse(b["blocking_eligible"],
                         f"assertion-only edge B must NOT be blocking_eligible: {b}")
        self.assertTrue(c["blocking_eligible"],
                        f"mixed edge C must be blocking_eligible (>=1 static): {c}")

        # Additional cross-edge consistency: edge B has exactly 1 evidence
        # entry and it is agent_asserted; edge C has 2 evidence entries.
        self.assertEqual(len(b["evidence"]), 1)
        self.assertEqual(b["evidence"][0]["evidence_source"], "agent_asserted")
        c_sources = sorted(ev["evidence_source"] for ev in c["evidence"])
        self.assertEqual(c_sources, ["agent_asserted", "static_extract"],
                         f"edge C evidence sources must include both: {c_sources}")

    def test_adversarial_static_then_assertion_keeps_blocking_true(self):
        """If a later assertion is added alongside surviving static evidence,
        blocking_eligible stays TRUE — the invariant is "NOT removed", not
        "single-source"."""
        # Run 1: static-only edge.
        run1_static = _edge(
            src_sym="auth-service.adv_handler",
            dst_sym="db.adv_select",
            source="static_extract",
            extractor="fastapi",
            emitted="2026-04-14T12:00:00Z",
        )
        snap1 = _do_reconcile(statics=[run1_static])
        self.assertEqual(len(snap1["edges"]), 1)
        self.assertTrue(snap1["edges"][0]["blocking_eligible"],
                        "run-1 baseline must be blocking_eligible")

        # Run 2: same edge_id, but now with an additional agent assertion.
        # The static evidence is STILL present — assertion is additive,
        # not replacement.
        run2_static = _edge(
            src_sym="auth-service.adv_handler",
            dst_sym="db.adv_select",
            source="static_extract",
            extractor="fastapi",
            emitted="2026-04-15T12:00:00Z",  # later timestamp; same edge_id
        )
        run2_asserted = _edge(
            src_sym="auth-service.adv_handler",
            dst_sym="db.adv_select",
            source="agent_asserted",
            extractor="bob-assertion",
            emitted="2026-04-15T12:01:00Z",
        )
        snap2 = _do_reconcile(statics=[run2_static], asserteds=[run2_asserted])
        self.assertEqual(len(snap2["edges"]), 1)
        edge2 = snap2["edges"][0]
        self.assertEqual(edge2["edge_id"], run1_static["edge_id"],
                         "edge_id must be stable across runs")
        self.assertTrue(edge2["blocking_eligible"],
                        f"adversarial run-2 must REMAIN blocking_eligible "
                        f"(static survived, assertion is additive): {edge2}")
        # Evidence array carries both sources.
        sources = sorted(ev["evidence_source"] for ev in edge2["evidence"])
        self.assertEqual(sources, ["agent_asserted", "static_extract"],
                         f"both evidence sources must be present: {sources}")


if __name__ == "__main__":
    unittest.main()
