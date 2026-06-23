"""M0b unit tests for review-scopes GROUPING key + ranker-order preservation (WP-2).

Covers the contract-map ``review-scopes`` grouping behavior (success criterion
(b), T-RV-1):

  * The grouping KEY matches the scope:
        today    -> urgency
        tomorrow -> urgency   (groups like today; kept simple + consistent)
        week     -> workstream
        month    -> milestone
  * The SHARED routine-engine ranker (``build_brief_items``, WP-1) order is
    PRESERVED within each group — pa_review never re-ranks; it windows + buckets a
    list that is already in ranker order, as a STABLE partition.
  * pa_review reuses the WP-1 ranker (no forked ranker / no duplicated urgency
    taxonomy).

``workstream`` is derived from a task's first tag (``unassigned`` when absent);
``milestone`` is derived from a task's ``planning_period`` (``unassigned`` when
absent). Both are read via the same conn (the pa_core_task_window_read in_process
integration point). stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json
from pathlib import Path

import pytest

from tests.conftest import _load_pa_server  # noqa: F401


NOW = "2026-06-15T12:00:00"   # Monday
TODAY = "2026-06-15"
TOMORROW = "2026-06-16"


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415

    return pa_core


def _ws_row(conn, ws_id):
    conn.execute(
        "INSERT OR IGNORE INTO workspaces (id, name, project_path) VALUES (?, ?, ?)",
        (ws_id, "review-grouping-test", "/tmp/rvg"),
    )
    conn.commit()


def _task(conn, ws_id, title, due_at, *, status="new", priority="high",
          tags=None, planning_period=None):
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority, due_at, tags, planning_period) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ws_id, title, status, priority, due_at,
         json.dumps(tags) if tags is not None else None, planning_period),
    )
    conn.commit()


def _group_keys(review):
    return [g["key"] for g in review["groups"]]


def _group_titles(review, key):
    for g in review["groups"]:
        if g["key"] == key:
            return [it.get("title") for it in g["items"]]
    return None


# ---------------------------------------------------------------------------
# Grouping key per scope
# ---------------------------------------------------------------------------

class TestGroupingKeyPerScope:
    def test_today_groups_by_urgency(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        # due-today task -> DUE_TODAY; executing task due today -> DUE_TODAY too,
        # so add a conflict (CONFLICT) due today as well to get >1 urgency band.
        _task(conn, ws_id, "due task", TODAY + "T16:00:00")
        # A due, ingested nudge (DUE_TODAY) due today.
        conn.execute(
            "INSERT INTO nudges (workspace_id, kind, message, source, due_at, state) "
            "VALUES (?, 'followup', 'ping', 'ingested', ?, 'pending')",
            (ws_id, TODAY + "T08:00:00"),
        )
        conn.commit()
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "today", "now": NOW})
        assert out["grouping_key"] == "urgency"
        # Every group key is an urgency band from the taxonomy.
        for k in _group_keys(out):
            assert k in pa_core_module.URGENCY_RANK or k == "FYI"

    def test_tomorrow_groups_by_urgency(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "due tomorrow", TOMORROW + "T16:00:00")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "tomorrow", "now": NOW})
        assert out["grouping_key"] == "urgency"

    def test_week_groups_by_workstream(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "alpha task", TODAY + "T09:00:00", tags=["alpha"])
        _task(conn, ws_id, "beta task", "2026-06-17T09:00:00", tags=["beta"])
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        assert out["grouping_key"] == "workstream"
        assert "alpha" in _group_keys(out)
        assert "beta" in _group_keys(out)

    def test_month_groups_by_milestone(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "m1 task", "2026-06-05T09:00:00", planning_period="2026-Q2-M1")
        _task(conn, ws_id, "m2 task", "2026-06-20T09:00:00", planning_period="2026-Q2-M2")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "month", "now": NOW})
        assert out["grouping_key"] == "milestone"
        assert "2026-Q2-M1" in _group_keys(out)
        assert "2026-Q2-M2" in _group_keys(out)


# ---------------------------------------------------------------------------
# Default group key for missing workstream / milestone
# ---------------------------------------------------------------------------

class TestUnassignedBucket:
    def test_week_untagged_task_lands_in_unassigned(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "no tag", TODAY + "T09:00:00")  # tags=None
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        assert "unassigned" in _group_keys(out)
        assert "no tag" in _group_titles(out, "unassigned")

    def test_month_no_planning_period_lands_in_unassigned(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "no period", TODAY + "T09:00:00")  # planning_period=None
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "month", "now": NOW})
        assert "unassigned" in _group_keys(out)
        assert "no period" in _group_titles(out, "unassigned")


# ---------------------------------------------------------------------------
# Ranker order preserved within a group
# ---------------------------------------------------------------------------

class TestRankerOrderPreservedWithinGroup:
    def test_within_group_order_matches_shared_ranker(self, pa_core_module, conn, ws_id):
        """Two in-week tasks of the SAME workstream, different urgency: the
        shared ranker orders the higher-urgency one first; pa_review preserves
        that order inside the group (it never re-ranks)."""
        _ws_row(conn, ws_id)
        # Same workstream 'alpha'. One is due-today (DUE_TODAY), one is a
        # later-in-week 'new' task that is NOT due today -> FYI (lower urgency).
        _task(conn, ws_id, "alpha due today", TODAY + "T09:00:00", tags=["alpha"])
        _task(conn, ws_id, "alpha later week", "2026-06-19T09:00:00", tags=["alpha"], status="new")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        alpha = _group_titles(out, "alpha")
        assert alpha is not None
        # DUE_TODAY (rank 3) sorts before FYI (rank 6): due-today first.
        assert alpha.index("alpha due today") < alpha.index("alpha later week")

    def test_within_group_order_is_shared_ranker_subsequence(self, pa_core_module, conn, ws_id):
        """The order of items WITHIN every group is a subsequence of the shared
        ranker's global order over the windowed items — proving no re-rank."""
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "a1 due today", TODAY + "T09:00:00", tags=["alpha"])
        _task(conn, ws_id, "b1 due today", TODAY + "T10:00:00", tags=["beta"])
        _task(conn, ws_id, "a2 fyi", "2026-06-18T09:00:00", tags=["alpha"], status="new")
        _task(conn, ws_id, "b2 fyi", "2026-06-19T09:00:00", tags=["beta"], status="new")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})

        # Recompute the shared ranker's global order over the SAME windowed set
        # (build_brief_items is WP-1's ranker — reused, never forked).
        ranked = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        global_titles = [it.get("title") for it in ranked]
        global_pos = {t: i for i, t in enumerate(global_titles)}

        for g in out["groups"]:
            titles = [it.get("title") for it in g["items"]]
            positions = [global_pos[t] for t in titles if t in global_pos]
            assert positions == sorted(positions), (
                f"group {g['key']} not in shared-ranker order: {titles}"
            )


# ---------------------------------------------------------------------------
# Output shape contract
# ---------------------------------------------------------------------------

class TestOutputShape:
    def test_review_output_has_required_keys(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        _task(conn, ws_id, "t", TODAY + "T09:00:00", tags=["alpha"])
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        for key in ("scope", "grouping_key", "workspace", "groups",
                    "item_count", "rendered_text", "window"):
            assert key in out, f"review_output missing '{key}'"
        assert isinstance(out["groups"], list)
        for g in out["groups"]:
            assert "key" in g and "items" in g
            assert isinstance(g["items"], list)

    def test_groups_ordered_by_first_item_ranker_position(self, pa_core_module, conn, ws_id):
        """Groups are ordered by the shared-ranker position of their first
        (highest-ranked) member, so the loudest group leads the review."""
        _ws_row(conn, ws_id)
        # beta has a due-today (loud); alpha only a later-week FYI (quiet).
        _task(conn, ws_id, "beta due today", TODAY + "T09:00:00", tags=["beta"])
        _task(conn, ws_id, "alpha later", "2026-06-19T09:00:00", tags=["alpha"], status="new")
        out = pa_core_module.pa_review(conn, ws_id, {"scope": "week", "now": NOW})
        keys = _group_keys(out)
        assert keys.index("beta") < keys.index("alpha")
