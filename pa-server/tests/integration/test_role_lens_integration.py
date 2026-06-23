"""M0b integration test for the role-lens in_process integration point (WP-4).

The contract map declares role-lens's only integration_point as
``reweight_pure_function`` (kind: in_process): routine-engine (WP-1) will read
the workspace ``role_profile`` row via the shared conn and feed it to
``reweight_brief_items``. The unit tests drive the lens from opaque FIXTURE
profiles; this integration test exercises the REAL in_process path — a
role_profile row WRITTEN to the M0a table, READ back via the same conn, and
applied to a BriefItem list — so the DB-sourced-profile -> pure-lens seam that
routine-engine depends on is verified before WP-1 builds on it.

This is the integration-flow-testing layer for the in_process point. It does NOT
auto-traverse the call graph (M5 declared-flows-only); the end-to-end flow tests
(FLOW-M0B-*) belong to WP-6. stdlib + pytest only — no new pip deps.
"""
import json
from pathlib import Path

import pytest

from tests.conftest import _load_pa_server  # noqa: F401


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "role-lens"


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415

    return pa_core


@pytest.fixture(autouse=True)
def _bootstrap_workspace(tools):
    """`tools` construction calls ensure_workspace() so the role_profile FK to
    workspaces is satisfiable."""
    return tools


def _load(rel):
    return json.loads((FIXTURES / rel).read_text())


def _ids(items):
    return [it["id"] for it in items]


def _write_role_profile(conn, ws_id, profile):
    """Insert a role_profile row using the REAL M0a table shape (the lens reads
    the same columns). category_weights is not a stored column — routine-engine
    derives weights from responsibilities/aims in WP-1; here we pass the derived
    weights directly to the pure lens to verify the seam."""
    conn.execute(
        """INSERT INTO role_profile
             (workspace_id, role_title, aims, responsibilities, methodology,
              reporting_lines, escalation_threshold, tone)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (ws_id, profile.get("role_title"), profile.get("aims"),
         profile.get("responsibilities"), profile.get("methodology"),
         profile.get("reporting_lines"), profile.get("escalation_threshold"),
         profile.get("tone")),
    )
    conn.commit()


class TestDbSourcedProfileSeam:
    def test_role_profile_round_trips_through_db_then_lens(self, pa_core_module, conn, ws_id):
        """The role_profile row written to the M0a table reads back with the same
        methodology, and the lens consumes it without error (the in_process seam
        routine-engine will use)."""
        profile = _load("role_profile/happy/0.json")["role_profile"]
        _write_role_profile(conn, ws_id, profile)
        row = conn.execute(
            "SELECT methodology FROM role_profile WHERE workspace_id=?",
            (ws_id,),
        ).fetchone()
        assert row["methodology"] == profile["methodology"]
        framing = pa_core_module.week_review_framing(row["methodology"])
        assert framing == "velocity"  # Scrum

    def test_lens_over_db_profile_preserves_membership(self, pa_core_module, conn, ws_id):
        """End-to-end in_process: DB-sourced methodology + caller-derived weights
        -> lens -> membership invariant holds on a real BriefItem list."""
        profile = _load("role_profile/happy/0.json")["role_profile"]
        _write_role_profile(conn, ws_id, profile)
        bi = _load("brief_items/happy/0.json")["brief_items"]
        # routine-engine will derive category_weights; we pass the profile's
        # declared weights to mirror that derivation at the seam.
        rp = {"methodology": conn.execute(
                  "SELECT methodology FROM role_profile WHERE workspace_id=?", (ws_id,)
              ).fetchone()["methodology"],
              "category_weights": profile["category_weights"]}
        out = pa_core_module.reweight_brief_items(bi, rp)
        assert sorted(_ids(out)) == sorted(_ids(bi))
        # urgency still dominant
        ranks = [pa_core_module.URGENCY_RANK.get(x["urgency"], pa_core_module.URGENCY_RANK_DEFAULT)
                 for x in out]
        assert ranks == sorted(ranks)

    def test_critical_blocker_survives_db_profile_downweight(self, pa_core_module, conn, ws_id):
        """The T-RL-1 safety invariant through the DB seam: a people-first profile
        that down-weights engineering (holding a critical blocker) still keeps the
        blocker reachable."""
        profile = _load("role_profile/adversarial/0.json")["role_profile"]
        _write_role_profile(conn, ws_id, profile)
        bi = _load("brief_items/adversarial/0.json")["brief_items"]
        rp = {"category_weights": profile["category_weights"]}
        out = pa_core_module.reweight_brief_items(bi, rp)
        assert "a-1" in _ids(out), "critical blocker dropped through DB seam"

    def test_lens_is_read_only_no_writes(self, pa_core_module, conn, ws_id):
        """The lens performs NO DB writes — the role_profile row count is
        unchanged after a reweight (single-writer invariant: the lens is a pure
        reader, pa_core owns writes elsewhere)."""
        profile = _load("role_profile/happy/0.json")["role_profile"]
        _write_role_profile(conn, ws_id, profile)
        before = conn.execute("SELECT COUNT(*) c FROM role_profile").fetchone()["c"]
        bi = _load("brief_items/happy/0.json")["brief_items"]
        pa_core_module.reweight_brief_items(bi, {"category_weights": profile["category_weights"]})
        after = conn.execute("SELECT COUNT(*) c FROM role_profile").fetchone()["c"]
        assert before == after == 1
