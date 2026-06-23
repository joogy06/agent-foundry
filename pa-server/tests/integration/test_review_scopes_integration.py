"""M0b integration test for the review-scopes integration point (WP-2).

The contract map declares review-scopes' integration point:

  * ``pa_core_task_window_read`` (kind: in_process) — pa_review resolves each
    windowed task's grouping dimensions (workstream from tags[0], milestone from
    planning_period) AND the due_at it windows on, over the SAME conn. The shared
    routine-engine ranker (WP-1's ``build_brief_items``) remains the authority for
    WHICH items are active; this read only attaches the grouping dimensions.

The unit tests drive windowing/grouping from a hand-seeded conn. This integration
layer exercises the REAL seam end-to-end: rows WRITTEN to the M0a kernel +
M0b-migration tables (tasks.due_at / tags / planning_period), READ back through
``pa_review`` (the registered tool body) — including through the registered MCP
tool dispatch (``tools/call`` -> JSON-Schema scope-enum validation ->
pa_core.pa_review). T-RV-1 is exercised here against the real DB seam.

It does NOT auto-traverse the call graph (M5 declared-flows-only); the end-to-end
FLOW-M0B-* tests belong to WP-6. stdlib + pytest only — no new pip deps (AMY
D-plus lock).
"""
import json

import pytest

from tests.conftest import _load_pa_server  # noqa: F401


NOW = "2026-06-15T12:00:00"   # Monday -> ISO week 2026-06-15..2026-06-21
TODAY = "2026-06-15"


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415

    return pa_core


@pytest.fixture(autouse=True)
def _bootstrap_workspace(tools):
    """`tools` construction calls ensure_workspace() so FK targets exist."""
    return tools


def _seed_week(conn, ws_id):
    """Tasks spread across days, some in-week some out, two workstreams + an
    untagged one + an undated blocker (the T-RV-1 shape)."""
    rows = [
        # title, due_at, tags(json), planning_period, status, priority
        ("alpha due today", TODAY + "T09:00:00", '["alpha"]', "2026-Q2-M1", "new", "high"),
        ("beta wed", "2026-06-17T09:00:00", '["beta"]', "2026-Q2-M1", "new", "high"),
        ("alpha later week", "2026-06-19T09:00:00", '["alpha"]', "2026-Q2-M2", "new", "low"),
        ("untagged in week", "2026-06-18T09:00:00", None, None, "new", "low"),
        ("next mon (out)", "2026-06-22T09:00:00", '["beta"]', "2026-Q2-M2", "new", "high"),
        ("last sun (out)", "2026-06-14T09:00:00", '["alpha"]', "2026-Q2-M1", "new", "high"),
    ]
    for title, due, tags, pp, status, prio in rows:
        conn.execute(
            "INSERT INTO tasks (workspace_id, title, status, priority, due_at, tags, planning_period) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ws_id, title, status, prio, due, tags, pp),
        )
    # An undated critical blocker — high urgency in the brief, but EXCLUDED from a
    # windowed review (no due_at).
    conn.execute(
        "INSERT INTO blockers (workspace_id, description, severity, status) "
        "VALUES (?, 'legal sign-off pending', 'critical', 'active')",
        (ws_id,),
    )
    conn.commit()


def _all_titles(review):
    return [it.get("title") for g in review["groups"] for it in g["items"]]


class TestTaskWindowReadSeam:
    """pa_core_task_window_read (in_process): pa_review windows + groups tasks
    read DIRECTLY via the same conn, off the shared ranker's surfaced ids."""

    def test_week_windows_and_groups_by_workstream(self, pa_core_module, conn, ws_id):
        """T-RV-1: only in-window items appear, grouped by workstream, ranked by
        the shared ranker within each group."""
        _seed_week(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        assert out["grouping_key"] == "workstream"
        titles = _all_titles(out)
        # in-window
        assert "alpha due today" in titles
        assert "beta wed" in titles
        assert "alpha later week" in titles
        assert "untagged in week" in titles
        # out-of-window excluded
        assert "next mon (out)" not in titles
        assert "last sun (out)" not in titles
        # undated blocker excluded
        assert "legal sign-off pending" not in titles
        # grouped by workstream
        keys = [g["key"] for g in out["groups"]]
        assert "alpha" in keys and "beta" in keys and "unassigned" in keys

    def test_shared_ranker_order_preserved_within_group(self, pa_core_module, conn, ws_id):
        """Within the alpha group, the shared ranker's order holds: the due-today
        (DUE_TODAY) item precedes the later-week FYI item."""
        _seed_week(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        alpha = next(g["items"] for g in out["groups"] if g["key"] == "alpha")
        alpha_titles = [it.get("title") for it in alpha]
        assert alpha_titles.index("alpha due today") < alpha_titles.index("alpha later week")

    def test_month_groups_by_milestone(self, pa_core_module, conn, ws_id):
        _seed_week(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "month", "now": NOW})
        assert out["grouping_key"] == "milestone"
        keys = [g["key"] for g in out["groups"]]
        # All seeded in-month tasks carry M1/M2 except the untagged one (no period).
        assert "2026-Q2-M1" in keys and "2026-Q2-M2" in keys
        assert "unassigned" in keys  # the untagged-in-week task has no planning_period

    def test_today_groups_by_urgency(self, pa_core_module, conn, ws_id):
        _seed_week(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "today", "now": NOW})
        assert out["grouping_key"] == "urgency"
        titles = _all_titles(out)
        assert "alpha due today" in titles
        assert "beta wed" not in titles  # wed is not today


class TestReviewViaRegisteredToolDispatch:
    """The registered MCP tool path: tools/call -> JSON-Schema scope-enum
    validation -> pa_core.pa_review."""

    def test_pa_review_listed_and_dispatches(self, pa_server_module, conn, ws_id, tools):
        _seed_week(conn, ws_id)
        srv = pa_server_module.JsonRpcServer(tools)
        listed = [t["name"] for t in srv._handle_tools_list({})["tools"]]
        assert "pa_review" in listed
        res = srv._handle_tools_call(
            {"name": "pa_review", "arguments": {"scope": "week", "now": NOW}}
        )
        assert res["isError"] is False
        payload = json.loads(res["content"][0]["text"])
        assert payload["scope"] == "week"
        assert payload["grouping_key"] == "workstream"
        assert "AMY review" in payload["rendered_text"]

    def test_dispatch_rejects_bad_scope_enum(self, pa_server_module, conn, ws_id, tools):
        """Schema validation runs BEFORE the body (T-ADP-1): an out-of-enum scope
        is rejected with isError=true; pa_core.pa_review never runs."""
        srv = pa_server_module.JsonRpcServer(tools)
        res = srv._handle_tools_call(
            {"name": "pa_review", "arguments": {"scope": "decade"}}
        )
        assert res["isError"] is True

    def test_dispatch_rejects_missing_scope(self, pa_server_module, conn, ws_id, tools):
        srv = pa_server_module.JsonRpcServer(tools)
        res = srv._handle_tools_call({"name": "pa_review", "arguments": {"now": NOW}})
        assert res["isError"] is True


class TestRemoteWrapThroughReview:
    """A due, ingested (remote-wrapped) nudge surfaced into a windowed review
    keeps its wrap end-to-end (security floor L1) — pa_review never unwraps."""

    def test_remote_nudge_stays_wrapped(self, pa_core_module, conn, ws_id):
        conn.execute(
            "INSERT INTO nudges (workspace_id, kind, message, source, due_at, state) "
            "VALUES (?, 'followup', ?, 'ingested', ?, 'pending')",
            (ws_id, "chase the vendor", TODAY + "T08:00:00"),
        )
        conn.commit()
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "today", "now": NOW})
        nudge_items = [
            it for g in out["groups"] for it in g["items"]
            if it.get("source_kind") == "nudge"
        ]
        assert nudge_items
        detail = nudge_items[0].get("detail") or ""
        assert "chase the vendor" in detail  # raw text preserved inside the wrap
