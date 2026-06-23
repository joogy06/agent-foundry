"""FLOW-M0B-2 (STANDARD) — review scope, end-to-end.

Declared flow (signed contract map `flows[1]`):

    review-scopes  ->  routine-engine
    (entry: scope)          (terminal: brief_output)

    "A pa_review(scope) call windows tasks to the scope and renders them grouped
     by the scope's grouping key using the shared ranker."

This test traverses the DECLARED PATH ONLY (M5 declared-flows-only — NO
call-graph auto-traversal). It exercises the REAL bodies end-to-end:

  * review-scopes node — ``pa_core.pa_review(scope)`` (the entry, scope input),
    AND through the registered MCP tool dispatch (tools/call -> JSON-Schema
    validation -> pa_core.pa_review), which is the real review entry point;
  * routine-engine node — pa_review REUSES ``build_brief_items`` (the SHARED
    ranker — never forks the urgency taxonomy) and renders the grouped terminal
    ``brief_output``.

The seeded pa.db carries tasks in/out of each window and across grouping
dimensions so the window EXCLUSION (criterion a), the GROUPING by the scope's
key (criterion b), and the SHARED-RANKER order WITHIN each group are all
observable.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json
from datetime import date, timedelta

import pytest

from tests.conftest import _load_pa_server  # noqa: F401

# Anchor the clock to a Wednesday so today / tomorrow / week / month windows are
# all well-defined and non-degenerate (week = Mon..Sun containing this date).
NOW = "2026-06-17T09:00:00"          # Wednesday
TODAY = "2026-06-17"
TOMORROW = "2026-06-18"
# ISO week containing 2026-06-17 (Wed) is Mon 2026-06-15 .. Sun 2026-06-21.
IN_WEEK_NOT_TODAY = "2026-06-19"     # Friday, same week
OUT_OF_WEEK = "2026-06-30"           # later in the month, outside the week
NEXT_MONTH = "2026-07-05"            # outside the month window


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415

    return pa_core


@pytest.fixture(autouse=True)
def _bootstrap_workspace(tools):
    return tools


def _add_task(conn, ws_id, title, *, due_at=None, status="new",
              priority="medium", tags=None, planning_period=None):
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority, due_at, tags, planning_period) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ws_id, title, status, priority, due_at,
         json.dumps(tags) if tags is not None else None, planning_period),
    )


def _seed_review_workspace(conn, ws_id):
    """Tasks spanning the scope windows + grouping dimensions. All valid M0a
    enums (status in the CHECK set; priority 'high'/'medium'/'low')."""
    # today-due (-> in today, tomorrow-excluded, in week, in month)
    _add_task(conn, ws_id, "File today's status", due_at=TODAY + "T15:00:00",
              status="executing", priority="high", tags=["delivery"],
              planning_period="Q2-FY26")
    # tomorrow-due
    _add_task(conn, ws_id, "Prep tomorrow's demo", due_at=TOMORROW + "T10:00:00",
              status="new", priority="medium", tags=["delivery"],
              planning_period="Q2-FY26")
    # in-week-not-today (Friday) — different workstream + same milestone
    _add_task(conn, ws_id, "Mid-week review", due_at=IN_WEEK_NOT_TODAY + "T11:00:00",
              status="new", priority="medium", tags=["governance"],
              planning_period="Q2-FY26")
    # later this month but outside the week — different milestone
    _add_task(conn, ws_id, "End-of-month report", due_at=OUT_OF_WEEK + "T11:00:00",
              status="new", priority="low", tags=["governance"],
              planning_period="Q3-FY26")
    # next month — outside the month window entirely
    _add_task(conn, ws_id, "Next month planning", due_at=NEXT_MONTH + "T11:00:00",
              status="new", priority="low", tags=["planning"],
              planning_period="Q3-FY26")
    # UNDATED active task — must be EXCLUDED from every windowed review.
    _add_task(conn, ws_id, "Someday cleanup", due_at=None, status="new", priority="low")
    conn.commit()


def _all_titles(review):
    return {it.get("title") for g in review["groups"] for it in g["items"]}


class TestReviewScopeWindowing:
    """Criterion (a): each scope EXCLUDES items outside its window AND every
    undated item — a windowed review surfaces only what is DUE in the window."""

    def test_today_scope_windows_to_today_only(self, pa_core_module, conn, ws_id):
        _seed_review_workspace(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "today", "now": NOW})
        assert out["scope"] == "today"
        titles = _all_titles(out)
        assert titles == {"File today's status"}, titles
        assert "Someday cleanup" not in titles, "undated item must be excluded"

    def test_tomorrow_scope_windows_to_tomorrow_only(self, pa_core_module, conn, ws_id):
        _seed_review_workspace(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "tomorrow", "now": NOW})
        assert _all_titles(out) == {"Prep tomorrow's demo"}

    def test_week_scope_includes_only_this_iso_week(self, pa_core_module, conn, ws_id):
        _seed_review_workspace(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        titles = _all_titles(out)
        assert "File today's status" in titles
        assert "Prep tomorrow's demo" in titles
        assert "Mid-week review" in titles
        assert "End-of-month report" not in titles, "out-of-week item excluded"
        assert "Next month planning" not in titles
        assert "Someday cleanup" not in titles

    def test_month_scope_includes_only_this_month(self, pa_core_module, conn, ws_id):
        _seed_review_workspace(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "month", "now": NOW})
        titles = _all_titles(out)
        assert "Next month planning" not in titles, "next-month item excluded"
        assert "End-of-month report" in titles, "same-month item included"
        assert "Someday cleanup" not in titles


class TestReviewScopeGrouping:
    """Criterion (b): items are GROUPED by the scope's grouping key
    (today/tomorrow=urgency, week=workstream, month=milestone)."""

    def test_week_groups_by_workstream(self, pa_core_module, conn, ws_id):
        _seed_review_workspace(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        assert out["grouping_key"] == "workstream"
        keys = {g["key"] for g in out["groups"]}
        assert keys == {"delivery", "governance"}, keys

    def test_month_groups_by_milestone(self, pa_core_module, conn, ws_id):
        _seed_review_workspace(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "month", "now": NOW})
        assert out["grouping_key"] == "milestone"
        keys = {g["key"] for g in out["groups"]}
        assert keys == {"Q2-FY26", "Q3-FY26"}, keys

    def test_today_groups_by_urgency(self, pa_core_module, conn, ws_id):
        _seed_review_workspace(conn, ws_id)
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "today", "now": NOW})
        assert out["grouping_key"] == "urgency"
        # the today-due task is DUE_TODAY-urgent.
        assert out["groups"][0]["key"] == "DUE_TODAY"


class TestReviewSharedRankerOrderPreserved:
    """The shared routine-engine ranker order is preserved as a STABLE partition
    within each group — pa_review REUSES build_brief_items, never re-ranks."""

    def test_within_group_order_matches_shared_ranker(self, pa_core_module, conn, ws_id):
        # Two same-workstream, same-week tasks with different urgency so the
        # shared ranker imposes a clear order we can assert is preserved.
        _add_task(conn, ws_id, "Loud delivery item", due_at=TODAY + "T08:00:00",
                  status="executing", priority="high", tags=["delivery"])
        _add_task(conn, ws_id, "Quiet delivery item", due_at=IN_WEEK_NOT_TODAY + "T08:00:00",
                  status="new", priority="low", tags=["delivery"])
        conn.commit()
        # The shared ranker (no window) — the authority for relative order.
        ranked = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        rank_pos = {it["id"]: i for i, it in enumerate(ranked)}

        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        delivery = next(g for g in out["groups"] if g["key"] == "delivery")
        positions = [rank_pos[it["id"]] for it in delivery["items"]]
        assert positions == sorted(positions), \
            "within-group order must preserve the shared ranker order (no re-rank)"


class TestReviewViaRegisteredToolDispatch:
    """The REAL review entry: tools/call -> JSON-Schema validation ->
    pa_core.pa_review. Proves review-scopes is wired as a tool and the scope enum
    is enforced pre-dispatch."""

    def test_pa_review_via_tool_dispatch_renders_grouped_text(
        self, pa_server_module, conn, ws_id, tools
    ):
        _seed_review_workspace(conn, ws_id)
        srv = pa_server_module.JsonRpcServer(tools)
        listed = [t["name"] for t in srv._handle_tools_list({})["tools"]]
        assert "pa_review" in listed
        res = srv._handle_tools_call(
            {"name": "pa_review", "arguments": {"scope": "week", "now": NOW}}
        )
        assert res["isError"] is False
        payload = json.loads(res["content"][0]["text"])
        assert payload["grouping_key"] == "workstream"
        assert "AMY review" in payload["rendered_text"]
        # the grouped render carries the group headers.
        assert "## delivery" in payload["rendered_text"]

    def test_tool_dispatch_rejects_out_of_enum_scope(
        self, pa_server_module, conn, ws_id, tools
    ):
        """A scope outside the closed enum is rejected by the inputSchema BEFORE
        the body runs (isError=true)."""
        srv = pa_server_module.JsonRpcServer(tools)
        res = srv._handle_tools_call(
            {"name": "pa_review", "arguments": {"scope": "decade", "now": NOW}}
        )
        assert res["isError"] is True


class TestReviewRemoteFieldsStayWrapped:
    """Remote-authored fields (ingested nudge messages, conflict_detail) that the
    shared ranker surfaces into a windowed review stay delimiter-wrapped — the
    review never unwraps (security floor L1)."""

    def test_due_today_ingested_nudge_in_review_stays_wrapped(
        self, pa_core_module, conn, ws_id
    ):
        # An ingested nudge due today surfaces in the 'today' urgency review.
        conn.execute(
            "INSERT INTO nudges (workspace_id, kind, message, source, due_at, state) "
            "VALUES (?, 'followup', ?, 'ingested', ?, 'pending')",
            (ws_id, "remote: escalate to exec", TODAY + "T07:00:00"),
        )
        conn.commit()
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "today", "now": NOW})
        nudges = [it for g in out["groups"] for it in g["items"]
                  if it.get("source_kind") == "nudge"]
        assert nudges, "the due ingested nudge should surface in today's review"
        OPEN = pa_core_module.UNTRUSTED_OPEN
        assert nudges[0]["detail"].startswith(OPEN), "remote nudge must stay wrapped"
