"""M0b integration test for the routine-engine integration points (WP-1).

The contract map declares routine-engine's two integration points:

  * ``pa_core_briefing_snapshot_read`` (kind: in_process) — pa_brief CONSUMES
    the M0a ``get_briefing_snapshot`` pure-read surface (active tasks, due
    nudges, unresolved conflicts) over the SAME conn. Remote-authored fields in
    that payload are already delimiter-wrapped by the snapshot path; the hub
    never unwraps them.
  * ``pa_core_delegation_blocker_read`` (kind: filesystem_io) — pa_brief READS
    the ``delegations`` + ``blockers`` tables DIRECTLY via the same conn, because
    the M0a snapshot does NOT surface those tables.

The unit tests drive the ranker/fold from a hand-seeded conn. This integration
layer exercises the REAL seams end-to-end: rows WRITTEN to the M0a kernel +
M0b-migration tables, READ back through ``pa_brief`` (the registered tool body),
so the snapshot-consume seam AND the direct delegation/blocker-read seam are
verified through the actual composer — including through the registered MCP tool
dispatch (``tools/call`` -> JSON-Schema validation -> pa_core.pa_brief).

It does NOT auto-traverse the call graph (M5 declared-flows-only); the
end-to-end FLOW-M0B-* tests belong to WP-6. stdlib + pytest only — no new pip
deps (AMY D-plus lock).
"""
import json

import pytest

from tests.conftest import _load_pa_server  # noqa: F401


NOW = "2026-06-15T12:00:00"
TODAY = "2026-06-15"


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415

    return pa_core


@pytest.fixture(autouse=True)
def _bootstrap_workspace(tools):
    """`tools` construction calls ensure_workspace() so the FK targets exist."""
    return tools


def _seed(conn, ws_id):
    """Seed a workspace touching BOTH integration seams (snapshot + direct read)."""
    # Snapshot seam inputs: a sync conflict (remote-wrapped) + a due-today task.
    conn.execute(
        "INSERT INTO sync_state (workspace_id, source, remote_id, status, conflict_detail) "
        "VALUES (?, 'jira', 'PROJ-9', 'conflict', ?)",
        (ws_id, "remote moved the due date"),
    )
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority, due_at) "
        "VALUES (?, 'Sign the SOW', 'executing', 'high', ?)",
        (ws_id, TODAY + "T16:00:00"),
    )
    # Snapshot seam input: a due, ingested (remote-wrapped) nudge.
    conn.execute(
        "INSERT INTO nudges (workspace_id, kind, message, source, due_at, state) "
        "VALUES (?, 'followup', ?, 'ingested', '2026-06-15T08:00:00', 'pending')",
        (ws_id, "chase the vendor"),
    )
    # Direct-read seam inputs: a critical blocker + an open delegation owed to me.
    conn.execute(
        "INSERT INTO blockers (workspace_id, description, severity, status) "
        "VALUES (?, 'legal sign-off pending', 'critical', 'active')",
        (ws_id,),
    )
    conn.execute(
        "INSERT INTO delegations (workspace_id, direction, status, expected_by) "
        "VALUES (?, 'owed_to_me', 'open', '2026-06-13T00:00:00')",
        (ws_id,),
    )
    conn.commit()


class TestSnapshotReadSeam:
    """pa_core_briefing_snapshot_read (in_process): pa_brief consumes the M0a
    snapshot over the same conn; remote fields stay wrapped."""

    def test_pa_brief_surfaces_snapshot_conflict_and_task(self, pa_core_module, conn, ws_id):
        _seed(conn, ws_id)
        out = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        kinds = {it["source_kind"] for it in out["items"]}
        assert "conflict" in kinds, "snapshot conflict must reach the hub"
        assert "task" in kinds, "snapshot active task must reach the hub"

    def test_conflict_detail_stays_wrapped_through_hub(self, pa_core_module, conn, ws_id):
        _seed(conn, ws_id)
        out = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        conflict = next(it for it in out["items"] if it["source_kind"] == "conflict")
        assert conflict["detail"].startswith(pa_core_module.UNTRUSTED_OPEN)
        assert conflict["detail"].endswith(pa_core_module.UNTRUSTED_CLOSE)


class TestDelegationBlockerReadSeam:
    """pa_core_delegation_blocker_read (filesystem_io): the hub reads
    delegations/blockers DIRECTLY — the snapshot does not carry them."""

    def test_snapshot_omits_delegations_and_blockers(self, pa_core_module, conn, ws_id):
        _seed(conn, ws_id)
        snap = pa_core_module.get_briefing_snapshot(conn, ws_id, {})
        assert "delegations" not in snap
        assert "blockers" not in snap

    def test_hub_reads_them_directly(self, pa_core_module, conn, ws_id):
        _seed(conn, ws_id)
        out = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        kinds = {it["source_kind"] for it in out["items"]}
        assert "blocker" in kinds, "blocker must be read directly via conn"
        assert "delegation" in kinds, "delegation must be read directly via conn"

    def test_local_blocker_not_wrapped_remote_nudge_wrapped(self, pa_core_module, conn, ws_id):
        _seed(conn, ws_id)
        out = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        blocker = next(it for it in out["items"] if it["source_kind"] == "blocker")
        assert pa_core_module.UNTRUSTED_OPEN not in (blocker["title"] or "")
        nudge = next(it for it in out["items"] if it["source_kind"] == "nudge")
        assert nudge["detail"].startswith(pa_core_module.UNTRUSTED_OPEN)


class TestComposedHubEndToEnd:
    def test_conflict_first_and_fold_caps_at_5(self, pa_core_module, conn, ws_id):
        _seed(conn, ws_id)
        out = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        assert out["above_fold"][0]["urgency"] == "CONFLICT"
        assert len(out["above_fold"]) <= 5
        # nothing dropped (T-RE-1)
        rejoined = out["above_fold"] + out["overflow"]
        assert {i["id"] for i in rejoined} == {i["id"] for i in out["items"]}

    def test_pa_brief_via_registered_tool_dispatch(self, pa_server_module, conn, ws_id, tools):
        """The registered MCP tool path: tools/call -> JSON-Schema validation ->
        pa_core.pa_brief. Verifies pa_brief is wired as a tool (the M0a pattern)."""
        _seed(conn, ws_id)
        srv = pa_server_module.JsonRpcServer(tools)
        listed = [t["name"] for t in srv._handle_tools_list({})["tools"]]
        assert "pa_brief" in listed
        res = srv._handle_tools_call({"name": "pa_brief", "arguments": {"now": NOW}})
        assert res["isError"] is False
        payload = json.loads(res["content"][0]["text"])
        assert "AMY briefing" in payload["rendered_text"]
        assert payload["above_fold"][0]["urgency"] == "CONFLICT"

    def test_tool_dispatch_rejects_bad_arguments(self, pa_server_module, conn, ws_id, tools):
        """Schema validation runs BEFORE the body (T-ADP-1): a wrong-typed `now`
        is rejected with isError=true, the pa_core body never runs."""
        srv = pa_server_module.JsonRpcServer(tools)
        res = srv._handle_tools_call({"name": "pa_brief", "arguments": {"now": 123}})
        assert res["isError"] is True
