"""M0b unit tests for the routine-engine RANKER + BriefItem builder (WP-1).

Covers the contract-map ``routine-engine`` ranking behavior:

  * BriefItems are ranked strictly by the urgency taxonomy
    (CONFLICT > OVERDUE_NUDGE > BLOCKER > DUE_TODAY > DELEGATION_FOLLOWUP >
    IN_FLIGHT > FYI) with a due/age tiebreak.
  * pa_brief consumes get_briefing_snapshot (in_process) AND reads
    delegations/blockers directly via the same conn (the
    pa_core_delegation_blocker_read integration point — get_briefing_snapshot
    does NOT read those tables).
  * It drains nudges via nudge-lifecycle (WP-3): an escalated (3x-snoozed) nudge
    surfaces as OVERDUE_NUDGE.
  * Remote-authored fields (ingested nudge messages, conflict_detail) stay
    delimiter-wrapped end-to-end (security-floor L1) — pa_brief never unwraps.

Tests build a seeded temp DB via the shared conftest ``conn``/``ws_id`` fixtures
and direct INSERTs (the seed-state shape documented in the routine-engine
db_conn fixture). stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json
from pathlib import Path

import pytest

from tests.conftest import _load_pa_server  # noqa: F401 — triggers pa_core import path


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "routine-engine"
NOW = "2026-06-15T12:00:00"
TODAY = "2026-06-15"


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415

    return pa_core


def _ws_row(conn, ws_id):
    """Ensure the workspaces row exists (FK target for tasks/blockers/etc)."""
    conn.execute(
        "INSERT OR IGNORE INTO workspaces (id, name, project_path) VALUES (?, ?, ?)",
        (ws_id, "rt-engine-test", "/tmp/rt"),
    )
    conn.commit()


def _seed_full(conn, ws_id):
    """Seed a workspace exercising every urgency band (the db_conn fixture shape)."""
    _ws_row(conn, ws_id)
    # A sync conflict -> CONFLICT (loudest). conflict_detail is remote-wrapped.
    conn.execute(
        "INSERT INTO sync_state (workspace_id, source, remote_id, status, conflict_detail) "
        "VALUES (?, 'jira', 'PROJ-412', 'conflict', ?)",
        (ws_id, "Local edit and remote edit diverged on the due date"),
    )
    # A 3x-snoozed ingested nudge, past due -> drained -> escalated OVERDUE_NUDGE.
    conn.execute(
        "INSERT INTO nudges (workspace_id, kind, message, source, due_at, "
        "snooze_until, snooze_count, state) "
        "VALUES (?, 'followup', ?, 'ingested', '2026-06-15T09:00:00', "
        "'2026-06-15T11:00:00', 3, 'snoozed')",
        (ws_id, "Chase the procurement ticket"),
    )
    # A critical active blocker -> BLOCKER (local description, NOT wrapped).
    conn.execute(
        "INSERT INTO blockers (workspace_id, description, severity, status) "
        "VALUES (?, ?, 'critical', 'active')",
        (ws_id, "Waiting on legal sign-off for the data-sharing clause"),
    )
    # A due-today task -> DUE_TODAY; an in-progress future task -> IN_FLIGHT.
    # 'executing' is the M0a-kernel "in progress" status (the legacy tasks.status
    # enum is new|designed|executing|blocked|done|failed|cancelled).
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority, due_at) "
        "VALUES (?, 'Q3 board deck', 'executing', 'high', ?)",
        (ws_id, TODAY + "T17:00:00"),
    )
    conn.execute(
        "INSERT INTO tasks (workspace_id, title, status, priority, due_at) "
        "VALUES (?, 'Refactor auth module', 'executing', 'low', '2026-06-20T00:00:00')",
        (ws_id,),
    )
    # An open delegation owed to me -> DELEGATION_FOLLOWUP.
    conn.execute(
        "INSERT INTO delegations (workspace_id, direction, status, expected_by) "
        "VALUES (?, 'owed_to_me', 'open', '2026-06-13T00:00:00')",
        (ws_id,),
    )
    conn.commit()


class TestUrgencyTaxonomyRanking:
    def test_ranker_orders_strictly_by_taxonomy(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        ranks = [pa_core_module.URGENCY_RANK.get(it["urgency"],
                 pa_core_module.URGENCY_RANK_DEFAULT) for it in items]
        assert ranks == sorted(ranks), f"not taxonomy-monotonic: {[i['urgency'] for i in items]}"

    def test_conflict_is_first(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        assert items[0]["urgency"] == "CONFLICT"

    def test_escalated_nudge_surfaces_as_overdue(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        nudge_items = [it for it in items if it["source_kind"] == "nudge"]
        assert nudge_items, "the drained 3x-snoozed nudge must surface"
        assert nudge_items[0]["urgency"] == "OVERDUE_NUDGE"
        assert nudge_items[0]["urgency_class"] == "escalated"

    def test_blocker_present_and_classified(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        blockers = [it for it in items if it["source_kind"] == "blocker"]
        assert len(blockers) == 1
        assert blockers[0]["urgency"] == "BLOCKER"
        assert blockers[0]["severity"] == "critical"

    def test_delegation_followup_present(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        delegs = [it for it in items if it["source_kind"] == "delegation"]
        assert len(delegs) == 1
        assert delegs[0]["urgency"] == "DELEGATION_FOLLOWUP"

    def test_due_today_vs_in_flight(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        tasks = {it["title"]: it for it in items if it["source_kind"] == "task"}
        assert tasks["Q3 board deck"]["urgency"] == "DUE_TODAY"
        assert tasks["Refactor auth module"]["urgency"] == "IN_FLIGHT"


class TestDelegationBlockerReadDirect:
    """pa_brief must read delegations/blockers DIRECTLY — get_briefing_snapshot
    does NOT surface them (the pa_core_delegation_blocker_read integration point)."""

    def test_snapshot_does_not_carry_delegations_or_blockers(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        snap = pa_core_module.get_briefing_snapshot(conn, ws_id, {})
        assert "delegations" not in snap
        assert "blockers" not in snap

    def test_routine_engine_surfaces_them_anyway(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        kinds = {it["source_kind"] for it in items}
        assert "blocker" in kinds, "blocker must be read directly via conn"
        assert "delegation" in kinds, "delegation must be read directly via conn"


class TestRemoteWrapPreservedEndToEnd:
    """Security floor L1: remote-authored fields stay delimiter-wrapped. The
    routine-engine never unwraps what the snapshot/drain already wrapped."""

    def test_conflict_detail_stays_wrapped(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        conflict = next(it for it in items if it["source_kind"] == "conflict")
        assert conflict["detail"].startswith(pa_core_module.UNTRUSTED_OPEN)
        assert conflict["detail"].endswith(pa_core_module.UNTRUSTED_CLOSE)

    def test_ingested_nudge_message_stays_wrapped(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        nudge = next(it for it in items if it["source_kind"] == "nudge")
        assert nudge["detail"].startswith(pa_core_module.UNTRUSTED_OPEN)
        assert nudge["detail"].endswith(pa_core_module.UNTRUSTED_CLOSE)

    def test_local_blocker_description_not_wrapped(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        blocker = next(it for it in items if it["source_kind"] == "blocker")
        # blocker description is the user's own note -> never remote-wrapped.
        assert pa_core_module.UNTRUSTED_OPEN not in (blocker["title"] or "")


class TestDueAgeTiebreak:
    def test_dated_sorts_before_undated_at_equal_urgency(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        # Two DELEGATION_FOLLOWUP items: one dated, one undated.
        conn.execute(
            "INSERT INTO delegations (workspace_id, direction, status, expected_by) "
            "VALUES (?, 'owed_to_me', 'open', '2026-06-10T00:00:00')",
            (ws_id,),
        )
        conn.execute(
            "INSERT INTO delegations (workspace_id, direction, status, expected_by) "
            "VALUES (?, 'owed_to_me', 'open', NULL)",
            (ws_id,),
        )
        conn.commit()
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        delegs = [it for it in items if it["source_kind"] == "delegation"]
        assert len(delegs) == 2
        assert delegs[0]["due_at"] == "2026-06-10T00:00:00"
        assert delegs[1]["due_at"] is None

    def test_sooner_due_sorts_first(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        conn.execute(
            "INSERT INTO delegations (workspace_id, direction, status, expected_by) "
            "VALUES (?, 'owed_to_me', 'open', '2026-06-14T00:00:00')",
            (ws_id,),
        )
        conn.execute(
            "INSERT INTO delegations (workspace_id, direction, status, expected_by) "
            "VALUES (?, 'owed_to_me', 'open', '2026-06-12T00:00:00')",
            (ws_id,),
        )
        conn.commit()
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        delegs = [it for it in items if it["source_kind"] == "delegation"]
        assert delegs[0]["due_at"] == "2026-06-12T00:00:00"
        assert delegs[1]["due_at"] == "2026-06-14T00:00:00"


class TestRankerTotality:
    def test_empty_workspace_yields_empty_list(self, pa_core_module, conn, ws_id):
        _ws_row(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        assert items == []

    def test_order_index_is_assigned_and_dense(self, pa_core_module, conn, ws_id):
        _seed_full(conn, ws_id)
        items = pa_core_module.build_brief_items(conn, ws_id, {"now": NOW})
        idxs = [it["order_index"] for it in items]
        assert idxs == list(range(len(items)))


def test_fixture_db_conn_descriptor_documents_seed_shape():
    """The opaque db_conn fixture descriptor must enumerate the seed state the
    ranker tests build (keeps the fixture honest about the runtime handle)."""
    desc = json.loads((FIXTURES / "db_conn" / "sample.json").read_text())
    assert desc["_opaque"] is True
    seed = desc["seed_state"]
    for key in ("tasks", "blockers", "delegations", "nudges",
                "sync_state_conflicts", "role_profile"):
        assert key in seed
