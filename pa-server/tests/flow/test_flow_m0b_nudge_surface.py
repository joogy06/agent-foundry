"""FLOW-M0B-3 (STANDARD) — nudge create then surface on next compose, end-to-end.

Declared flow (signed contract map `flows[2]`):

    nudge-lifecycle  ->  routine-engine
    (entry: nudge_spec)       (terminal: brief_output)

    "A pa_nudge_create writes a nudge; the next briefing compose drains it and
     surfaces it in the rendered output."

This test traverses the DECLARED PATH ONLY (M5 declared-flows-only — NO
call-graph auto-traversal). It exercises the REAL bodies end-to-end across the
two-step lifecycle:

  * nudge-lifecycle node (the entry) — ``pa_core.nudge_create(nudge_spec)`` AND
    the registered ``pa_nudge_create`` tool dispatch (tools/call -> JSON-Schema
    validation -> body), which WRITES a 'pending' nudges row;
  * routine-engine node (the terminal) — the NEXT ``pa_core.pa_brief`` compose
    drains the now-due nudge (state 'pending' -> 'shown') and SURFACES it in the
    rendered ``brief_output``.

Because the same conn is shared, the write-then-read across the two tool calls
is the real cross-component seam: the nudge written by nudge-lifecycle is
drained + rendered by routine-engine on the subsequent compose.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json

import pytest

from tests.conftest import _load_pa_server  # noqa: F401

NOW = "2026-06-15T12:00:00"
PAST_DUE = "2026-06-15T08:00:00"     # due before NOW -> drained on next compose
FUTURE_DUE = "2026-06-20T08:00:00"   # not yet due -> NOT drained


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415

    return pa_core


@pytest.fixture(autouse=True)
def _bootstrap_workspace(tools):
    return tools


class TestNudgeCreateThenSurface:
    def test_create_then_next_compose_drains_and_surfaces(
        self, pa_core_module, conn, ws_id
    ):
        """The full flow: nudge_create writes a due nudge; the very next pa_brief
        compose drains it (state -> 'shown') and surfaces it in the brief_output."""
        # (1) nudge-lifecycle entry: create a due (manual/local) nudge.
        created = pa_core_module.nudge_create(
            conn, ws_id,
            {"message": "Call the client back", "due_at": PAST_DUE, "kind": "followup"},
        )
        nudge_id = created["id"]
        assert created["state"] == "pending", "a fresh nudge starts 'pending'"

        # Before the compose, the nudge is still pending (not yet surfaced).
        pre = conn.execute(
            "SELECT state FROM nudges WHERE id=? AND workspace_id=?", (nudge_id, ws_id)
        ).fetchone()
        assert pre["state"] == "pending"

        # (2) routine-engine terminal: the next compose drains + surfaces it.
        out = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        surfaced = [it for it in out["items"]
                    if it["source_kind"] == "nudge" and it["id"] == f"nudge:{nudge_id}"]
        assert surfaced, "the created nudge must surface in the next briefing"

        # the drain promoted it to 'shown' (the in-composer write path).
        post = conn.execute(
            "SELECT state FROM nudges WHERE id=? AND workspace_id=?", (nudge_id, ws_id)
        ).fetchone()
        assert post["state"] == "shown", "compose must drain the due nudge to 'shown'"

        # it is rendered in the terminal text (a DUE nudge -> 'Due nudge' line).
        assert "Due nudge" in out["rendered_text"]

    def test_future_due_nudge_is_not_drained_on_compose(
        self, pa_core_module, conn, ws_id
    ):
        """A nudge whose due_at is in the FUTURE is NOT drained — it stays
        'pending' and does NOT surface (the drain predicate is due-or-unsnoozed)."""
        created = pa_core_module.nudge_create(
            conn, ws_id, {"message": "Quarterly check-in", "due_at": FUTURE_DUE},
        )
        out = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        surfaced = [it for it in out["items"]
                    if it["source_kind"] == "nudge" and it["id"] == f"nudge:{created['id']}"]
        assert not surfaced, "a not-yet-due nudge must not surface"
        post = conn.execute(
            "SELECT state FROM nudges WHERE id=? AND workspace_id=?",
            (created["id"], ws_id),
        ).fetchone()
        assert post["state"] == "pending", "future nudge stays pending"

    def test_idempotent_second_compose_does_not_resurface_shown_nudge(
        self, pa_core_module, conn, ws_id
    ):
        """Once drained to 'shown', a nudge is NOT re-drained on a later compose
        (the drain predicate is state IN ('pending','snoozed') — 'shown' is
        terminal for the drain). The created concern is surfaced exactly once."""
        created = pa_core_module.nudge_create(
            conn, ws_id, {"message": "One-shot reminder", "due_at": PAST_DUE},
        )
        first = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        assert any(it["id"] == f"nudge:{created['id']}" for it in first["items"])
        second = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        resurfaced = [it for it in second["items"]
                      if it["id"] == f"nudge:{created['id']}"]
        assert not resurfaced, "a 'shown' nudge is not re-drained on the next compose"


class TestNudgeCreateViaToolThenSurface:
    """The REAL nudge entry: tools/call -> JSON-Schema validation ->
    pa_core.nudge_create — then the next pa_brief tool call surfaces it. Proves
    BOTH ends of the flow through the registered MCP dispatch."""

    def test_create_via_tool_then_brief_via_tool_surfaces(
        self, pa_server_module, conn, ws_id, tools
    ):
        srv = pa_server_module.JsonRpcServer(tools)
        listed = [t["name"] for t in srv._handle_tools_list({})["tools"]]
        assert "pa_nudge_create" in listed and "pa_brief" in listed

        # (1) create through the tool path.
        cres = srv._handle_tools_call({
            "name": "pa_nudge_create",
            "arguments": {"message": "Approve the budget", "due_at": PAST_DUE},
        })
        assert cres["isError"] is False
        created = json.loads(cres["content"][0]["text"])

        # (2) compose through the tool path: the nudge surfaces.
        bres = srv._handle_tools_call({"name": "pa_brief", "arguments": {"now": NOW}})
        assert bres["isError"] is False
        brief = json.loads(bres["content"][0]["text"])
        assert any(it["id"] == f"nudge:{created['id']}" for it in brief["items"]), \
            "a tool-created due nudge must surface via the tool-composed briefing"

    def test_create_tool_rejects_missing_message(
        self, pa_server_module, conn, ws_id, tools
    ):
        """nudge_spec validation: a missing required 'message' is rejected by the
        inputSchema BEFORE the body runs (isError=true)."""
        srv = pa_server_module.JsonRpcServer(tools)
        res = srv._handle_tools_call(
            {"name": "pa_nudge_create", "arguments": {"due_at": PAST_DUE}}
        )
        assert res["isError"] is True


class TestIngestedNudgeStaysWrappedOnSurface:
    """An INGESTED (remote) nudge created with a remote message surfaces on the
    next compose still delimiter-wrapped — the create+drain+render path never
    unwraps (security floor L1)."""

    def test_ingested_nudge_surface_is_wrapped(self, pa_core_module, conn, ws_id):
        created = pa_core_module.nudge_create(
            conn, ws_id,
            {"message": "remote-authored escalation", "due_at": PAST_DUE,
             "source": "ingested"},
        )
        out = pa_core_module.pa_brief(conn, ws_id, {"now": NOW})
        item = next(it for it in out["items"]
                    if it["id"] == f"nudge:{created['id']}")
        OPEN, CLOSE = pa_core_module.UNTRUSTED_OPEN, pa_core_module.UNTRUSTED_CLOSE
        assert item["detail"].startswith(OPEN) and item["detail"].endswith(CLOSE), \
            "an ingested nudge must stay wrapped through create -> drain -> render"
