"""Characterization tests for the EXISTING pa-server tool surface (AMY M0a / WP-1).

PURPOSE
-------
pa-server has ZERO tests today. Before the M0a rework (WP-2 pa-core extraction +
_with_tx; WP-4 sync rework) lands, this suite pins the CURRENT, pre-rework,
observable behavior of every existing tool against a temp SQLite DB loaded
in-process. It is the TDD safety net: WP-2/WP-4 will update exactly the handful
of assertions whose pinned behavior IS the bug being fixed, and everything else
must keep passing.

THE THREE KNOWN BUGS (pinned here as the to-be-fixed BASELINE)
-------------------------------------------------------------
Each is marked with a ``KNOWN BUG (baseline)`` comment and lives in a clearly
named test so the flip in WP-2/WP-4 is deliberate and visible in the diff:

  BUG-1  isError:False on returned-error dicts
         Handlers that *return* {"error": ...} (instead of raising) are wrapped
         by JsonRpcServer._handle_tools_call with isError=False — an error
         reported as success. Fixed in WP-2 (handlers RAISE typed errors).
         -> test_bug1_*  classes/functions below.

  BUG-2  no base-version conflict detection
         On re-sync, a remotely-changed item unconditionally overwrites the
         local task and sets status='synced'; conflict_count stays 0 and
         sync_state.status='conflict' never fires (dead conflict code).
         Fixed in WP-4 (3-way base + real conflict detection).
         -> test_bug2_*

  BUG-3  commit-on-partial-failure
         Sync does per-item INSERT/UPDATE then a single commit() at the end.
         A mid-batch exception leaves earlier items' writes pending on the
         connection (no rollback), so they get committed by the next successful
         write. Fixed in WP-2 (_with_tx rollback wrapping every write path).
         -> test_bug3_*

CONVENTIONS
-----------
stdlib + pytest only (no new pip deps — AMY D-plus lock). The current handlers
are exercised both directly (PATools.*) and through the dispatcher
(JsonRpcServer._handle_tools_call) where the isError contract lives.
"""
import json

import pytest

from tests.fixtures import (
    CONFLUENCE_PAGE_V1,
    CONFLUENCE_PAGE_V2,
    JIRA_ISSUE_BAD,
    JIRA_ISSUE_GOOD,
    JIRA_ISSUE_V1,
    JIRA_ISSUE_V2,
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _call(server, name, arguments):
    """Drive a tool through the real dispatcher; return the MCP result dict
    ({"content": [...], "isError": bool})."""
    return server._handle_tools_call({"name": name, "arguments": arguments})


def _payload(result):
    """Decode the JSON text payload out of an MCP tools/call result."""
    return json.loads(result["content"][0]["text"])


# ===========================================================================
# pa_health
# ===========================================================================

class TestPaHealth:
    def test_health_shape_on_empty_db(self, tools):
        out = tools.pa_health({})
        assert out["task_count"] == 0
        assert out["fts_enabled"] is True
        assert out["semantic_enabled"] is False
        assert out["transport"] == "json-rpc"
        # last_sync keys exist and are None on a never-synced workspace
        assert out["last_sync"] == {"confluence": None, "jira": None}

    def test_health_task_count_tracks_created_tasks(self, tools):
        tools.pa_create_task({"title": "one"})
        tools.pa_create_task({"title": "two"})
        assert tools.pa_health({})["task_count"] == 2


# ===========================================================================
# pa_create_task / pa_get_task / pa_update_task / pa_query_tasks
# ===========================================================================

class TestTaskCrud:
    def test_create_task_returns_new_status_and_id(self, tools):
        out = tools.pa_create_task({"title": "Write tests", "priority": "high"})
        assert isinstance(out["id"], int)
        assert out["title"] == "Write tests"
        assert out["status"] == "new"  # current default

    def test_create_task_serializes_list_tags_to_json(self, tools):
        out = tools.pa_create_task({"title": "tagged", "tags": ["a", "b"]})
        got = tools.pa_get_task({"id": out["id"]})
        assert json.loads(got["tags"]) == ["a", "b"]

    def test_get_task_includes_recent_actions_list(self, tools):
        tid = tools.pa_create_task({"title": "with action"})["id"]
        tools.pa_log_action({"task_id": tid, "action": "did a thing"})
        got = tools.pa_get_task({"id": tid})
        assert got["id"] == tid
        assert isinstance(got["recent_actions"], list)
        assert got["recent_actions"][0]["action"] == "did a thing"

    def test_update_task_status_designed_sets_designed_at(self, tools):
        tid = tools.pa_create_task({"title": "to design"})["id"]
        out = tools.pa_update_task({"id": tid, "status": "designed"})
        assert out["status"] == "designed"
        row = tools.pa_get_task({"id": tid})
        assert row["designed_at"] is not None

    def test_update_task_terminal_status_sets_completed_at(self, tools):
        tid = tools.pa_create_task({"title": "to finish"})["id"]
        tools.pa_update_task({"id": tid, "status": "done"})
        row = tools.pa_get_task({"id": tid})
        assert row["completed_at"] is not None

    def test_query_tasks_filters_by_status(self, tools):
        a = tools.pa_create_task({"title": "open one"})["id"]
        b = tools.pa_create_task({"title": "done one"})["id"]
        tools.pa_update_task({"id": b, "status": "done"})
        new_rows = tools.pa_query_tasks({"status": "new"})
        ids = {r["id"] for r in new_rows}
        assert a in ids and b not in ids

    def test_query_tasks_respects_limit(self, tools):
        for i in range(5):
            tools.pa_create_task({"title": f"t{i}"})
        assert len(tools.pa_query_tasks({"limit": 3})) == 3


# ===========================================================================
# pa_log_action / pa_search
# ===========================================================================

class TestActionsAndSearch:
    def test_log_action_returns_id(self, tools):
        out = tools.pa_log_action({"action": "standalone action"})
        assert isinstance(out["id"], int)
        assert "created_at" in out

    def test_search_finds_task_by_title_via_fts(self, tools):
        tools.pa_create_task({"title": "unicorn rainbow sparkle"})
        results = tools.pa_search({"query": "unicorn"})
        assert any(r["type"] == "task" and "unicorn" in r["title"] for r in results)

    def test_search_finds_action_via_fts(self, tools):
        tid = tools.pa_create_task({"title": "host task"})["id"]
        tools.pa_log_action({"task_id": tid, "action": "provisioned the widgetron"})
        results = tools.pa_search({"query": "widgetron"})
        assert any(r["type"] == "action" for r in results)

    def test_search_empty_when_no_match(self, tools):
        tools.pa_create_task({"title": "nothing relevant"})
        assert tools.pa_search({"query": "zzzznomatchzzzz"}) == []


# ===========================================================================
# pa_start_session / pa_end_session
# ===========================================================================

class TestSessions:
    def test_start_session_returns_briefing_shape(self, tools):
        tools.pa_create_task({"title": "active work"})
        out = tools.pa_start_session({})
        assert isinstance(out["session_id"], int)
        assert isinstance(out["active_tasks"], list)
        assert any(t["title"] == "active work" for t in out["active_tasks"])
        assert isinstance(out["recent_actions"], list)
        assert isinstance(out["unresolved_conflicts"], list)
        # No prior session -> last_session_summary is None
        assert out["last_session_summary"] is None

    def test_start_session_excludes_completed_tasks_from_active(self, tools):
        tid = tools.pa_create_task({"title": "finished"})["id"]
        tools.pa_update_task({"id": tid, "status": "done"})
        out = tools.pa_start_session({})
        assert all(t["title"] != "finished" for t in out["active_tasks"])

    def test_end_session_then_start_surfaces_last_summary(self, tools):
        s1 = tools.pa_start_session({})["session_id"]
        tools.pa_end_session({"session_id": s1, "summary": "did the thing"})
        out2 = tools.pa_start_session({})
        assert out2["last_session_summary"]["summary"] == "did the thing"

    def test_start_session_CURRENTLY_writes_a_session_row(self, tools, conn, ws_id):
        # CHARACTERIZATION (back-compat anchor for WP-5): pa_start_session today
        # WRITES a sessions row as a side effect. WP-5 keeps pa_start_session as a
        # write-then-snapshot shim, so this must remain true after the rework even
        # though get_briefing_snapshot itself will be a pure read.
        before = conn.execute(
            "SELECT COUNT(*) c FROM sessions WHERE workspace_id=?", (ws_id,)
        ).fetchone()["c"]
        tools.pa_start_session({})
        after = conn.execute(
            "SELECT COUNT(*) c FROM sessions WHERE workspace_id=?", (ws_id,)
        ).fetchone()["c"]
        assert after == before + 1


# ===========================================================================
# preferences CRUD: pa_get_preferences / pa_update_preference / pa_clear_preference
# ===========================================================================

class TestPreferences:
    def test_update_preference_inserts_with_base_confidence(self, tools, ws_id):
        out = tools.pa_update_preference(
            {"key": "tone", "value": "concise", "category": "writing", "workspace": ws_id}
        )
        assert out["confidence"] == 0.3
        assert out["signal_count"] == 1

    def test_update_preference_reinforces_confidence(self, tools, ws_id):
        args = {"key": "tone", "value": "concise", "category": "writing", "workspace": ws_id}
        tools.pa_update_preference(args)
        second = tools.pa_update_preference(args)
        # 2 signals -> 0.5 in the current confidence ladder
        assert second["signal_count"] == 2
        assert second["confidence"] == 0.5

    def test_get_preferences_returns_stored(self, tools, ws_id):
        tools.pa_update_preference(
            {"key": "fmt", "value": "md", "category": "presentation", "workspace": ws_id}
        )
        rows = tools.pa_get_preferences({"workspace": ws_id})
        assert any(r["key"] == "fmt" and r["value"] == "md" for r in rows)

    def test_clear_preference_removes_it(self, tools, ws_id):
        tools.pa_update_preference(
            {"key": "gone", "value": "x", "category": "tool", "workspace": ws_id}
        )
        out = tools.pa_clear_preference({"key": "gone", "workspace": ws_id})
        assert out == {"deleted": True}
        rows = tools.pa_get_preferences({"workspace": ws_id})
        assert all(r["key"] != "gone" for r in rows)


# ===========================================================================
# sync_config CRUD: pa_set_sync_config / pa_get_sync_configs
# ===========================================================================

class TestSyncConfig:
    def test_set_sync_config_stores_env_var_NAMES_only(self, tools, conn, ws_id):
        tools.pa_set_sync_config(
            {
                "source": "jira",
                "config": {
                    "base_url_env": "JIRA_BASE",
                    "token_env": "JIRA_TOKEN",
                    "strategy": "assigned",
                    "query": "",
                },
            }
        )
        row = conn.execute(
            "SELECT base_url_env, token_env FROM sync_configs WHERE workspace_id=? AND source='jira'",
            (ws_id,),
        ).fetchone()
        # Security invariant: we persist env-var NAMES, never raw tokens.
        assert row["base_url_env"] == "JIRA_BASE"
        assert row["token_env"] == "JIRA_TOKEN"

    def test_set_sync_config_upserts(self, tools, ws_id):
        base = {"source": "jira", "config": {"base_url_env": "A", "token_env": "B", "strategy": "assigned", "query": ""}}
        tools.pa_set_sync_config(base)
        base["config"]["strategy"] = "jql"
        tools.pa_set_sync_config(base)
        cfgs = tools.pa_get_sync_configs({"workspace": ws_id})
        jira = [c for c in cfgs if c["source"] == "jira"]
        assert len(jira) == 1
        assert jira[0]["strategy"] == "jql"

    def test_get_sync_configs_returns_enabled(self, tools, ws_id):
        tools.pa_set_sync_config(
            {"source": "confluence", "config": {"base_url_env": "C", "token_env": "D", "strategy": "label", "query": "x"}}
        )
        cfgs = tools.pa_get_sync_configs({"workspace": ws_id})
        assert any(c["source"] == "confluence" for c in cfgs)


# ===========================================================================
# pa_get_conflicts / pa_resolve_conflict
# ===========================================================================

class TestConflicts:
    def test_get_conflicts_empty_on_fresh_db(self, tools):
        assert tools.pa_get_conflicts({}) == []

    def test_resolve_conflict_clears_a_seeded_conflict(self, tools, conn, ws_id):
        # Seed a conflict row directly (the sync path never creates one today —
        # see BUG-2). This exercises pa_resolve_conflict's clear-to-synced path.
        conn.execute(
            "INSERT INTO sync_state (workspace_id, source, remote_id, status, conflict_detail) "
            "VALUES (?, 'jira', 'PROJ-9', 'conflict', ?)",
            (ws_id, json.dumps({"remote": {"title": "remote title"}})),
        )
        conn.commit()
        ss_id = conn.execute(
            "SELECT id FROM sync_state WHERE workspace_id=? AND remote_id='PROJ-9'", (ws_id,)
        ).fetchone()["id"]
        out = tools.pa_resolve_conflict({"sync_state_id": ss_id, "resolution": "keep_local"})
        assert out["resolved"] is True
        # status flipped to synced, conflict_detail cleared
        row = conn.execute("SELECT status, conflict_detail FROM sync_state WHERE id=?", (ss_id,)).fetchone()
        assert row["status"] == "synced"
        assert row["conflict_detail"] is None

    def test_get_conflicts_lists_seeded_conflict(self, tools, conn, ws_id):
        conn.execute(
            "INSERT INTO sync_state (workspace_id, source, remote_id, status, conflict_detail) "
            "VALUES (?, 'confluence', '777', 'conflict', '{}')",
            (ws_id,),
        )
        conn.commit()
        rows = tools.pa_get_conflicts({})
        assert any(r["remote_source"] == "confluence" and r["status"] == "conflict" for r in rows)


# ===========================================================================
# pa_sync_jira / pa_sync_confluence — happy paths (network monkeypatched)
# ===========================================================================

class TestSyncHappyPath:
    def test_sync_jira_missing_env_now_raises_sync_error(self, tools, monkeypatch, pa_server_module):
        # WP-2 FLIP: missing credentials previously RETURNED an {"error": ...,
        # "pulled": 0} dict (silent failure); pa_core now RAISES SyncError so the
        # adapter reports isError=true honestly. Direct callers see the raise.
        monkeypatch.delenv("JIRA_BASE", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)
        with pytest.raises(pa_server_module.SyncError):
            tools.pa_sync_jira({"source_config": {"base_url_env": "JIRA_BASE", "token_env": "JIRA_TOKEN"}})

    def test_sync_jira_inserts_new_item_as_task(self, tools, conn, ws_id, monkeypatch, pa_server_module):
        monkeypatch.setenv("JIRA_BASE", "https://example.test")
        monkeypatch.setenv("JIRA_TOKEN", "tok")
        monkeypatch.setattr(pa_server_module, "_jira_fetch", lambda *a, **k: [JIRA_ISSUE_V1])
        out = tools.pa_sync_jira({"source_config": {"base_url_env": "JIRA_BASE", "token_env": "JIRA_TOKEN"}})
        assert out["new_items"] == 1
        task = conn.execute(
            "SELECT title, source, remote_id FROM tasks WHERE source='jira' AND remote_id='PROJ-1'"
        ).fetchone()
        assert task["title"] == "Original Jira summary"
        assert task["source"] == "jira"

    def test_sync_confluence_inserts_new_item_as_task(self, tools, conn, monkeypatch, pa_server_module):
        monkeypatch.setenv("CONFLUENCE_BASE", "https://wiki.test")
        monkeypatch.setenv("CONFLUENCE_TOKEN", "tok")
        monkeypatch.setattr(pa_server_module, "_confluence_fetch", lambda *a, **k: [CONFLUENCE_PAGE_V1])
        out = tools.pa_sync_confluence({})
        assert out["new_items"] == 1
        task = conn.execute(
            "SELECT title, source FROM tasks WHERE source='confluence' AND remote_id='12345'"
        ).fetchone()
        assert task["title"] == "Original Confluence title"


# ===========================================================================
# (FIXED in WP-2) #1 — honest isError on raised typed errors
# ===========================================================================
# BASELINE (WP-1): the dispatcher wrapped a handler's RETURN value with
# isError=False, so handlers signalling failure by RETURNING an {"error": ...}
# dict were reported to the MCP client as SUCCESS.
# WP-2 FIX: handlers now RAISE pa_core typed errors (NotFoundError / SyncError);
# the dispatcher's `except PaError` maps them to isError=true. The assertions
# below were FLIPPED from `is False` to `is True` as the deliberate, visible
# WP-2 change (the error payload still carries an `error` message, now with a
# stable `code`).

class TestBug1IsErrorTrueOnRaisedTypedErrors:
    def test_get_task_not_found_is_now_iserror_true(self, server):
        result = _call(server, "pa_get_task", {"id": 999999})
        body = _payload(result)
        assert "error" in body  # handler signalled an error...
        assert body.get("code") == "not_found"  # ...as a typed error now
        # WP-2 FLIP: raise typed NotFound -> dispatcher except -> isError=true.
        assert result["isError"] is True

    def test_update_task_not_found_is_now_iserror_true(self, server):
        result = _call(server, "pa_update_task", {"id": 888888, "status": "done"})
        body = _payload(result)
        assert "error" in body
        assert body.get("code") == "not_found"
        # WP-2 FLIP: was isError=False, now honestly isError=true.
        assert result["isError"] is True

    def test_resolve_conflict_not_found_is_now_iserror_true(self, server):
        result = _call(server, "pa_resolve_conflict", {"sync_state_id": 4242, "resolution": "keep_local"})
        body = _payload(result)
        assert "error" in body
        assert body.get("code") == "not_found"
        # WP-2 FLIP: was isError=False, now honestly isError=true.
        assert result["isError"] is True

    def test_sync_jira_missing_env_is_now_iserror_true(self, server, monkeypatch):
        monkeypatch.delenv("JIRA_BASE", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)
        result = _call(server, "pa_sync_jira", {"source_config": {"base_url_env": "JIRA_BASE", "token_env": "JIRA_TOKEN"}})
        body = _payload(result)
        assert "error" in body
        assert body.get("code") == "sync_error"
        # WP-2 FLIP: a missing-credentials sync error is now honestly isError=true
        # (was a silent isError=False success).
        assert result["isError"] is True

    def test_bug1_contrast_unknown_tool_IS_marked_iserror(self, server):
        # Contrast: the ONLY path that honestly reports isError=True today is the
        # "unknown tool" branch (handled before dispatch). This pins that the
        # mechanism exists — the bug is purely that returned-error dicts skip it.
        result = _call(server, "pa_does_not_exist", {})
        assert result["isError"] is True


# ===========================================================================
# (FIXED in WP-4) #2 — 3-way base + REAL conflict detection
# ===========================================================================
# BASELINE (WP-1) pinned the bug: on re-sync, a remotely-changed item was applied
# UNCONDITIONALLY into `tasks`, clobbering the local edit and marking
# sync_state.status='synced'; conflict_count stayed 0 and 'conflict' never fired
# (dead pa_get_conflicts / pa_resolve_conflict surface).
#
# WP-4 FLIP (design §4.2): remote records now land in `external_items` (not
# `tasks`), linked to a mirror task via `task_external_links` storing the 3-way
# base (base_remote_version + base_local_updated_at). On re-sync the engine
# compares remote-version vs base AND task.updated_at vs base:
#   - BOTH advanced -> sync_state.status='conflict', the local task is NOT
#     overwritten (T-SYNC-1);
#   - only one side advanced -> fast-forward that side.
# The assertions below were FLIPPED from the silent-overwrite baseline to the
# correct 3-way behavior as the deliberate, visible WP-4 change.

class TestBug2ConflictDetectionNowReal:
    def test_bug2_concurrent_local_and_remote_edit_now_conflicts(
        self, tools, conn, monkeypatch, pa_server_module
    ):
        """T-SYNC-1: both sides moved past the base -> conflict, not overwrite."""
        monkeypatch.setenv("JIRA_BASE", "https://example.test")
        monkeypatch.setenv("JIRA_TOKEN", "tok")

        # First sync: insert PROJ-1 at V1 -> external_item + mirror task + link
        # with the 3-way base pinned.
        monkeypatch.setattr(pa_server_module, "_jira_fetch", lambda *a, **k: [JIRA_ISSUE_V1])
        tools.pa_sync_jira({"source_config": {"base_url_env": "JIRA_BASE", "token_env": "JIRA_TOKEN"}})

        # Simulate a LOCAL edit to the mirror task (advances task.updated_at past
        # the stored base_local_updated_at — the local arm of the conflict).
        local_task = conn.execute(
            "SELECT id FROM tasks WHERE source='jira' AND remote_id='PROJ-1'"
        ).fetchone()
        conn.execute(
            "UPDATE tasks SET title=?, updated_at=? WHERE id=?",
            ("LOCALLY edited title", "2099-01-01T00:00:00+00:00", local_task["id"]),
        )
        conn.commit()

        # Second sync: remote ALSO changed (V2) -> remote arm advanced too.
        monkeypatch.setattr(pa_server_module, "_jira_fetch", lambda *a, **k: [JIRA_ISSUE_V2])
        out = tools.pa_sync_jira({"source_config": {"base_url_env": "JIRA_BASE", "token_env": "JIRA_TOKEN"}})

        # WP-4: a conflict is reported (the dead surface finally fires)...
        assert out["conflicts"] == 1
        assert out["updated_items"] == 0
        # ...the local edit is PRESERVED (not clobbered by the remote title)...
        preserved = conn.execute(
            "SELECT title FROM tasks WHERE id=?", (local_task["id"],)
        ).fetchone()["title"]
        assert preserved == "LOCALLY edited title"
        # ...and sync_state is marked 'conflict' with conflict_detail populated.
        ss = conn.execute(
            "SELECT status, conflict_detail FROM sync_state WHERE source='jira' AND remote_id='PROJ-1'"
        ).fetchone()
        assert ss["status"] == "conflict"
        assert ss["conflict_detail"]
        assert tools.pa_get_conflicts({})  # non-empty conflict surface

    def test_bug2_confluence_remote_only_change_fast_forwards(
        self, tools, conn, monkeypatch, pa_server_module
    ):
        """Only the remote moved (no local edit) -> fast-forward, no conflict."""
        monkeypatch.setenv("CONFLUENCE_BASE", "https://wiki.test")
        monkeypatch.setenv("CONFLUENCE_TOKEN", "tok")
        monkeypatch.setattr(pa_server_module, "_confluence_fetch", lambda *a, **k: [CONFLUENCE_PAGE_V1])
        tools.pa_sync_confluence({})
        monkeypatch.setattr(pa_server_module, "_confluence_fetch", lambda *a, **k: [CONFLUENCE_PAGE_V2])
        out = tools.pa_sync_confluence({})
        # WP-4: a remote-only change fast-forwards (no conflict).
        assert out["conflicts"] == 0
        assert out["updated_items"] == 1
        # The external_item carries the (wrapped) updated remote title; the
        # mirror task title fast-forwards to the new remote summary.
        task_title = conn.execute(
            "SELECT title FROM tasks WHERE source='confluence' AND remote_id='12345'"
        ).fetchone()["title"]
        assert task_title == "Updated Confluence title (remote changed)"
        ss = conn.execute(
            "SELECT status FROM sync_state WHERE source='confluence' AND remote_id='12345'"
        ).fetchone()
        assert ss["status"] == "synced"


# ===========================================================================
# KNOWN BUG (baseline) #3 — commit-on-partial-failure
# ===========================================================================
# Sync runs per-item INSERTs/UPDATEs eagerly and commits ONCE at the end of the
# loop. If item N raises mid-batch, the handler's `except` returns an error dict
# WITHOUT rolling back, so writes from items 0..N-1 remain pending on the
# connection. They are NOT discarded — the next successful commit (e.g. the very
# next tool call, via _ensure_workspace or any write) flushes them to disk. This
# pins that the partial work SURVIVES a mid-batch failure. WP-2 wraps every write
# path in _with_tx so a mid-batch failure rolls the whole batch back.

class TestBug3CommitOnPartialFailure:
    def test_bug3_partial_batch_write_is_now_rolled_back_atomically(
        self, tools, conn, monkeypatch, pa_server_module
    ):
        """WP-2 FLIP (was: test_bug3_partial_batch_write_survives_midbatch_exception).

        BUG-3 baseline (WP-1) pinned commit-on-partial-failure: a GOOD item
        followed by a BAD item left the GOOD item's INSERT pending on the
        connection (no rollback), so a later successful commit flushed the
        partial write. WP-2 wraps the entire sync batch in ``pa_core._with_tx``,
        so a mid-batch raise now ROLLS BACK the whole batch AND re-raises the
        failure as a typed ``SyncError`` (instead of swallowing it into an
        ``{"error": ...}`` dict). This test asserts the post-WP-2 behavior:
        (1) the call raises SyncError, and (2) the GOOD item did NOT persist.
        """
        monkeypatch.setenv("JIRA_BASE", "https://example.test")
        monkeypatch.setenv("JIRA_TOKEN", "tok")
        # Batch: a GOOD item (inserts) followed by a BAD item (raises in-loop).
        monkeypatch.setattr(
            pa_server_module, "_jira_fetch", lambda *a, **k: [JIRA_ISSUE_GOOD, JIRA_ISSUE_BAD]
        )

        # WP-2: the mid-batch failure is RAISED as a typed SyncError (BUG-1 +
        # BUG-3 fix), no longer returned as a silent error dict.
        with pytest.raises(pa_server_module.SyncError):
            tools.pa_sync_jira(
                {"source_config": {"base_url_env": "JIRA_BASE", "token_env": "JIRA_TOKEN"}}
            )

        # WP-2: _with_tx rolled the whole batch back. Force a flush the same way
        # a real subsequent tool call would (any successful commit), then assert
        # the GOOD item's row is GONE — the failed batch was ATOMIC.
        conn.commit()  # mimics the next successful write committing pending work
        good = conn.execute(
            "SELECT title FROM tasks WHERE source='jira' AND remote_id='PROJ-GOOD'"
        ).fetchone()
        assert good is None  # partial write was rolled back (batch is atomic)
