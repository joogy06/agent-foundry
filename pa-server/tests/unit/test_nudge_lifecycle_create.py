"""M0b unit tests for nudge-lifecycle CREATE + lifecycle transitions (WP-3).

Covers the contract-map ``nudge-lifecycle`` component success criteria:

  * pa_nudge_create writes a 'pending' nudges row inside _with_tx; lifecycle
    transitions (acked/snoozed/dismissed/shown) update state correctly and
    atomically.
  * pa_nudge_create is registered as a pa-server tool with inputSchema
    validation; malformed args are rejected pre-dispatch (M0a adapter pattern).
  * The 3rd snooze flips the DERIVED urgency class to 'escalated'; snooze_count
    is tracked.
  * The M0a nudges-table shape is unchanged (no new columns).

Exercises pa_core DIRECTLY (transport-neutral) plus the stdio adapter for the
validation + dispatch path, using the shared conftest in-process idiom.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json

import pytest

from tests.conftest import _load_pa_server


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415 — available after pa_server load

    return pa_core


@pytest.fixture(autouse=True)
def _bootstrap_workspace(tools):
    """The `tools` fixture's construction calls ensure_workspace(), creating the
    workspaces row so the nudges FK -> workspaces(id) is satisfiable. Autouse so
    every test in this module exercising pa_core directly has the row."""
    return tools


# ---------------------------------------------------------------------------
# nudge_create — writes a 'pending' row
# ---------------------------------------------------------------------------

class TestNudgeCreate:
    def test_creates_pending_row(self, pa_core_module, conn, ws_id):
        res = pa_core_module.nudge_create(
            conn, ws_id,
            {"message": "Chase the migration sign-off", "due_at": "2026-06-16T09:00:00Z", "kind": "followup"},
        )
        assert res["state"] == "pending"
        assert res["snooze_count"] == 0
        assert res["urgency_class"] == "normal"
        row = conn.execute("SELECT * FROM nudges WHERE id = ?", (res["id"],)).fetchone()
        assert row["state"] == "pending"
        assert row["message"] == "Chase the migration sign-off"
        assert row["kind"] == "followup"
        assert row["snooze_count"] == 0
        assert row["snooze_until"] is None

    def test_subject_is_folded_into_message(self, pa_core_module, conn, ws_id):
        # The frozen M0a table has NO subject column — subject is prepended.
        res = pa_core_module.nudge_create(
            conn, ws_id, {"subject": "URGENT", "message": "review the PR"}
        )
        row = conn.execute("SELECT message FROM nudges WHERE id = ?", (res["id"],)).fetchone()
        assert row["message"] == "URGENT — review the PR"

    def test_default_source_is_manual(self, pa_core_module, conn, ws_id):
        res = pa_core_module.nudge_create(conn, ws_id, {"message": "ping"})
        row = conn.execute("SELECT source FROM nudges WHERE id = ?", (res["id"],)).fetchone()
        assert row["source"] == "manual"

    def test_missing_message_raises_validation(self, pa_core_module, conn, ws_id):
        with pytest.raises(pa_core_module.ValidationError):
            pa_core_module.nudge_create(conn, ws_id, {"due_at": "2026-06-16T09:00:00Z"})

    def test_bad_kind_raises_validation_and_writes_nothing(self, pa_core_module, conn, ws_id):
        before = conn.execute("SELECT COUNT(*) c FROM nudges").fetchone()["c"]
        with pytest.raises(pa_core_module.ValidationError):
            pa_core_module.nudge_create(conn, ws_id, {"message": "x", "kind": "not_a_kind"})
        after = conn.execute("SELECT COUNT(*) c FROM nudges").fetchone()["c"]
        assert after == before  # fail-closed: no partial row

    def test_bad_source_raises_validation(self, pa_core_module, conn, ws_id):
        with pytest.raises(pa_core_module.ValidationError):
            pa_core_module.nudge_create(conn, ws_id, {"message": "x", "source": "evil"})


# ---------------------------------------------------------------------------
# Lifecycle transitions — state moves are atomic + scoped to the workspace
# ---------------------------------------------------------------------------

class TestNudgeLifecycleTransitions:
    def _make(self, pa_core_module, conn, ws_id, **extra):
        params = {"message": "lifecycle target"}
        params.update(extra)
        return pa_core_module.nudge_create(conn, ws_id, params)["id"]

    def test_mark_shown(self, pa_core_module, conn, ws_id):
        nid = self._make(pa_core_module, conn, ws_id)
        res = pa_core_module.nudge_mark_shown(conn, ws_id, {"id": nid})
        assert res["state"] == "shown"
        assert conn.execute("SELECT state FROM nudges WHERE id=?", (nid,)).fetchone()["state"] == "shown"

    def test_ack(self, pa_core_module, conn, ws_id):
        nid = self._make(pa_core_module, conn, ws_id)
        res = pa_core_module.nudge_ack(conn, ws_id, {"id": nid})
        assert res["state"] == "acked"

    def test_dismiss(self, pa_core_module, conn, ws_id):
        nid = self._make(pa_core_module, conn, ws_id)
        res = pa_core_module.nudge_dismiss(conn, ws_id, {"id": nid})
        assert res["state"] == "dismissed"

    def test_snooze_sets_until_and_increments_count(self, pa_core_module, conn, ws_id):
        nid = self._make(pa_core_module, conn, ws_id)
        res = pa_core_module.nudge_snooze(conn, ws_id, {"id": nid, "snooze_until": "2026-06-20T09:00:00Z"})
        assert res["state"] == "snoozed"
        assert res["snooze_until"] == "2026-06-20T09:00:00Z"
        assert res["snooze_count"] == 1
        assert res["urgency_class"] == "normal"

    def test_third_snooze_escalates(self, pa_core_module, conn, ws_id):
        nid = self._make(pa_core_module, conn, ws_id)
        for i in range(2):
            r = pa_core_module.nudge_snooze(conn, ws_id, {"id": nid, "snooze_until": "2026-06-20T09:00:00Z"})
            assert r["urgency_class"] == "normal"
        r3 = pa_core_module.nudge_snooze(conn, ws_id, {"id": nid, "snooze_until": "2026-06-20T09:00:00Z"})
        assert r3["snooze_count"] == 3
        assert r3["urgency_class"] == "escalated"

    def test_snooze_requires_snooze_until(self, pa_core_module, conn, ws_id):
        nid = self._make(pa_core_module, conn, ws_id)
        with pytest.raises(pa_core_module.ValidationError):
            pa_core_module.nudge_snooze(conn, ws_id, {"id": nid})

    def test_transition_missing_id_raises(self, pa_core_module, conn, ws_id):
        with pytest.raises(pa_core_module.ValidationError):
            pa_core_module.nudge_ack(conn, ws_id, {})

    def test_transition_unknown_id_raises_notfound(self, pa_core_module, conn, ws_id):
        with pytest.raises(pa_core_module.NotFoundError):
            pa_core_module.nudge_ack(conn, ws_id, {"id": 999999})


# ---------------------------------------------------------------------------
# urgency_class derivation (pure)
# ---------------------------------------------------------------------------

class TestUrgencyClassDerivation:
    @pytest.mark.parametrize("n,expected", [
        (0, "normal"), (1, "normal"), (2, "normal"),
        (3, "escalated"), (4, "escalated"), (10, "escalated"),
    ])
    def test_threshold(self, pa_core_module, n, expected):
        assert pa_core_module.nudge_urgency_class(n) == expected

    def test_none_is_normal(self, pa_core_module):
        assert pa_core_module.nudge_urgency_class(None) == "normal"


# ---------------------------------------------------------------------------
# Tool registration + pre-dispatch validation (M0a adapter pattern)
# ---------------------------------------------------------------------------

class TestNudgeToolRegistration:
    def test_pa_nudge_create_is_registered(self, pa_server_module):
        assert "pa_nudge_create" in pa_server_module.TOOL_SCHEMAS
        assert callable(getattr(pa_server_module.PATools, "pa_nudge_create"))

    def test_all_nudge_tools_registered(self, pa_server_module):
        for name in ("pa_nudge_create", "pa_nudge_mark_shown", "pa_nudge_ack",
                     "pa_nudge_snooze", "pa_nudge_dismiss", "pa_nudge_drain"):
            assert name in pa_server_module.TOOL_SCHEMAS, name
            assert callable(getattr(pa_server_module.PATools, name)), name

    def test_create_via_server_dispatch_success(self, server):
        out = server._handle_tools_call(
            {"name": "pa_nudge_create", "arguments": {"message": "via adapter", "kind": "due"}}
        )
        assert out["isError"] is False
        payload = json.loads(out["content"][0]["text"])
        assert payload["state"] == "pending"

    def test_missing_required_message_rejected_pre_dispatch(self, server):
        out = server._handle_tools_call(
            {"name": "pa_nudge_create", "arguments": {"kind": "due"}}
        )
        assert out["isError"] is True
        payload = json.loads(out["content"][0]["text"])
        assert payload["code"] == "validation_error"

    def test_bad_kind_enum_rejected_pre_dispatch(self, server):
        out = server._handle_tools_call(
            {"name": "pa_nudge_create", "arguments": {"message": "x", "kind": "bogus"}}
        )
        assert out["isError"] is True

    def test_snooze_requires_until_via_schema(self, server):
        out = server._handle_tools_call(
            {"name": "pa_nudge_snooze", "arguments": {"id": 1}}
        )
        assert out["isError"] is True
        payload = json.loads(out["content"][0]["text"])
        assert payload["code"] == "validation_error"


# ---------------------------------------------------------------------------
# The nudges-table shape is unchanged (M0a freeze invariant)
# ---------------------------------------------------------------------------

class TestNudgesTableShapeUnchanged:
    def test_columns_match_m0a(self, conn):
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(nudges)").fetchall()}
        expected = {
            "id", "workspace_id", "task_id", "delegation_id", "kind", "message",
            "source", "due_at", "snooze_until", "snooze_count", "state", "created_at",
        }
        assert cols == expected
