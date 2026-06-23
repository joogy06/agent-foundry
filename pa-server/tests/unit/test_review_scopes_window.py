"""M0b unit tests for review-scopes TIME-WINDOW selection (WP-2).

Covers the contract-map ``review-scopes`` windowing behavior:

  * ``pa_review(scope)`` for scope in {today, tomorrow, week, month} selects the
    correct time window keyed off ``now`` (an optional ISO override for
    deterministic tests).
  * Items whose ``due_at`` falls OUTSIDE the selected window are EXCLUDED; only
    in-window items appear in the review output (success criterion (a), T-RV-1).
  * Undated items (no ``due_at``: blockers, conflicts) are excluded from a
    windowed review — a review is about what is DUE in the window.
  * The closed-enum ``scope`` tag is validated; an unknown scope is rejected
    (raises a typed error) before any DB read.

``pa_review`` REUSES the WP-1 routine-engine ranker (``build_brief_items``); it
never forks the urgency taxonomy. Tests build a seeded temp DB via the shared
conftest ``conn``/``ws_id`` fixtures and direct INSERTs (the seed-state shape
documented in the review-scopes db_conn fixture). stdlib + pytest only — no new
pip deps (AMY D-plus lock).
"""
import json
from pathlib import Path

import pytest

from tests.conftest import _load_pa_server  # noqa: F401 — triggers pa_core import path


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "review-scopes"

# A fixed reference clock. 2026-06-15 is a MONDAY -> the ISO week is
# 2026-06-15 (Mon) .. 2026-06-21 (Sun). The month window is 2026-06-01..30.
NOW = "2026-06-15T12:00:00"
TODAY = "2026-06-15"
TOMORROW = "2026-06-16"


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415

    return pa_core


def _ws_row(conn, ws_id):
    conn.execute(
        "INSERT OR IGNORE INTO workspaces (id, name, project_path) VALUES (?, ?, ?)",
        (ws_id, "review-scopes-test", "/tmp/rv"),
    )
    conn.commit()


def _task(conn, ws_id, title, due_at, *, status="new", priority="high",
          tags=None, planning_period=None):
    """Insert one task with a due_at (and optional tags/planning_period).

    priority is a VALID M0a enum ('high'/'low' etc — NOT 'in_progress' /
    numerics); status is in the legacy CHECK set (incl. 'executing')."""
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority, due_at, tags, planning_period) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ws_id, title, status, priority, due_at,
         json.dumps(tags) if tags is not None else None, planning_period),
    )
    conn.commit()


def _all_titles(review):
    """Every item title across all groups in a review output."""
    out = []
    for g in review["groups"]:
        out.extend(it.get("title") for it in g["items"])
    return out


# ---------------------------------------------------------------------------
# Window selection per scope
# ---------------------------------------------------------------------------

class TestTodayWindow:
    def test_today_includes_only_today_due(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "due today", TODAY + "T16:00:00")
        _task(conn, ws_id, "due tomorrow", TOMORROW + "T09:00:00")
        _task(conn, ws_id, "due yesterday", "2026-06-14T09:00:00")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "today", "now": NOW})
        titles = _all_titles(out)
        assert "due today" in titles
        assert "due tomorrow" not in titles
        assert "due yesterday" not in titles


class TestTomorrowWindow:
    def test_tomorrow_includes_only_tomorrow_due(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "due today", TODAY + "T16:00:00")
        _task(conn, ws_id, "due tomorrow", TOMORROW + "T09:00:00")
        _task(conn, ws_id, "due in 2 days", "2026-06-17T09:00:00")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "tomorrow", "now": NOW})
        titles = _all_titles(out)
        assert "due tomorrow" in titles
        assert "due today" not in titles
        assert "due in 2 days" not in titles


class TestWeekWindow:
    def test_week_includes_in_week_excludes_out_of_week(self, pa_core_module, conn, ws_id):
        """T-RV-1 core: tasks spread across days, some in-week some out."""
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "mon (in week)", TODAY + "T09:00:00")
        _task(conn, ws_id, "wed (in week)", "2026-06-17T09:00:00")
        _task(conn, ws_id, "sun (in week, last day)", "2026-06-21T23:00:00")
        _task(conn, ws_id, "next mon (out of week)", "2026-06-22T09:00:00")
        _task(conn, ws_id, "last sun (out of week)", "2026-06-14T09:00:00")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        titles = _all_titles(out)
        assert "mon (in week)" in titles
        assert "wed (in week)" in titles
        assert "sun (in week, last day)" in titles
        assert "next mon (out of week)" not in titles
        assert "last sun (out of week)" not in titles


class TestMonthWindow:
    def test_month_includes_in_month_excludes_out_of_month(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "first of month", "2026-06-01T09:00:00")
        _task(conn, ws_id, "mid month", TODAY + "T09:00:00")
        _task(conn, ws_id, "last of month", "2026-06-30T23:00:00")
        _task(conn, ws_id, "next month", "2026-07-01T09:00:00")
        _task(conn, ws_id, "prev month", "2026-05-31T23:00:00")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "month", "now": NOW})
        titles = _all_titles(out)
        assert "first of month" in titles
        assert "mid month" in titles
        assert "last of month" in titles
        assert "next month" not in titles
        assert "prev month" not in titles


# ---------------------------------------------------------------------------
# Undated items excluded from a windowed review
# ---------------------------------------------------------------------------

class TestUndatedExcluded:
    def test_blocker_without_due_excluded(self, pa_core_module, conn, ws_id):
        """A blocker (no due_at) is a high-urgency BriefItem in the brief, but a
        windowed REVIEW only shows dated items in the window."""
        _ws_row(conn, ws_id)
        conn.execute(
            "INSERT INTO blockers (workspace_id, description, severity, status) "
            "VALUES (?, 'legal sign-off pending', 'critical', 'active')",
            (ws_id,),
        )
        _task(conn, ws_id, "due today", TODAY + "T16:00:00")
        conn.commit()
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "today", "now": NOW})
        titles = _all_titles(out)
        assert "due today" in titles
        assert "legal sign-off pending" not in titles, "undated blocker is out of the window"


class TestEmptyWindow:
    def test_empty_window_returns_no_groups(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "next month", "2026-07-01T09:00:00")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "today", "now": NOW})
        assert out["groups"] == []
        assert out["item_count"] == 0
        assert "rendered_text" in out


# ---------------------------------------------------------------------------
# Closed-enum scope validation
# ---------------------------------------------------------------------------

class TestScopeValidation:
    def test_unknown_scope_rejected(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        with pytest.raises(Exception) as ei:
            pa_core_module.pa_review(conn, ws_id, {"scope": "decade", "now": NOW})
        assert "scope" in str(ei.value).lower()

    def test_missing_scope_rejected(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        with pytest.raises(Exception):
            pa_core_module.pa_review(conn, ws_id, {"now": NOW})

    @pytest.mark.parametrize("scope", ["today", "tomorrow", "week", "month"])
    def test_all_valid_scopes_accepted(self, pa_core_module, conn, ws_id, scope):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "anchor", TODAY + "T12:00:00")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": scope, "now": NOW})
        assert out["scope"] == scope
        assert "groups" in out


# ---------------------------------------------------------------------------
# Remote-field wrap preservation (security floor L1)
# ---------------------------------------------------------------------------

class TestRemoteWrapPreserved:
    def test_remote_nudge_message_stays_wrapped(self, pa_core_module, conn, ws_id):
        """A due, ingested (remote-wrapped) nudge surfaced into a windowed review
        keeps its wrap end-to-end (pa_review never unwraps)."""
        _ws_row(conn, ws_id)
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
        assert nudge_items, "the due ingested nudge must reach the review"
        # The drain wraps ingested messages; pa_review passes detail through verbatim.
        detail = nudge_items[0].get("detail") or ""
        assert "chase the vendor" in detail
