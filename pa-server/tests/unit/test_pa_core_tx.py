"""WP-2 unit tests for pa_core transaction discipline + connection PRAGMA.

Covers the contract-map ``pa-core`` component success criteria and T-CORE-1:

  * T-CORE-1 — Write rolls back on mid-operation failure: an op that fails a
    CHECK constraint (or any raise) partway through a multi-statement write
    leaves NO committed row; a typed error is raised.
  * ``connect()`` sets PRAGMA busy_timeout=5000 + journal_mode=WAL +
    foreign_keys=ON (the block-and-retry single-writer discipline).
  * ``_with_tx`` commits on clean exit, rolls back on exception, and clears
    stray pending state from a prior aborted op before BEGIN.

These exercise pa_core DIRECTLY (transport-neutral), not via the stdio adapter.
The module is loaded in-process via the same conftest idiom as the
characterization suite (pa_server imports pa_core, so loading pa_server makes
pa_core importable as a sibling module).

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import sqlite3

import pytest

from tests.conftest import _load_pa_server


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    """The pa_core module pa_server is a thin adapter over.

    Depending on pa_server_module guarantees pa_server.py has been exec'd, which
    runs ``import pa_core`` after inserting pa-server/ on sys.path; pa_core is
    then importable here without duplicating the SourceFileLoader plumbing.
    """
    import pa_core  # noqa: PLC0415 — available after pa_server load

    return pa_core


# ---------------------------------------------------------------------------
# connect() PRAGMA contract
# ---------------------------------------------------------------------------

class TestConnectPragmas:
    def test_busy_timeout_is_5000(self, pa_core_module, tmp_path):
        conn = pa_core_module.connect(tmp_path / "pa.db")
        try:
            got = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert got == 5000
        finally:
            conn.close()

    def test_journal_mode_is_wal(self, pa_core_module, tmp_path):
        conn = pa_core_module.connect(tmp_path / "pa.db")
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
        finally:
            conn.close()

    def test_foreign_keys_enforced(self, pa_core_module, tmp_path):
        conn = pa_core_module.connect(tmp_path / "pa.db")
        try:
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# _with_tx commit / rollback semantics
# ---------------------------------------------------------------------------

class TestWithTx:
    def test_commits_on_clean_exit(self, pa_core_module, tools, conn, ws_id):
        # `tools` bootstraps the workspaces row (ensure_workspace) so the tasks
        # FK -> workspaces(id) is satisfiable.
        with pa_core_module._with_tx(conn) as c:
            c.execute(
                "INSERT INTO tasks (workspace_id, title) VALUES (?, ?)",
                (ws_id, "committed task"),
            )
        # After the context manager exits cleanly the row is committed and
        # visible on a fresh read with no pending transaction.
        assert not conn.in_transaction
        row = conn.execute(
            "SELECT title FROM tasks WHERE title = ?", ("committed task",)
        ).fetchone()
        assert row is not None

    def test_rolls_back_on_exception(self, pa_core_module, tools, conn, ws_id):
        class Boom(Exception):
            pass

        with pytest.raises(Boom):
            with pa_core_module._with_tx(conn) as c:
                c.execute(
                    "INSERT INTO tasks (workspace_id, title) VALUES (?, ?)",
                    (ws_id, "doomed task"),
                )
                raise Boom("mid-transaction failure")

        # The INSERT before the raise must NOT survive.
        assert not conn.in_transaction
        row = conn.execute(
            "SELECT title FROM tasks WHERE title = ?", ("doomed task",)
        ).fetchone()
        assert row is None

    def test_stray_pending_state_is_cleared_before_begin(self, pa_core_module, tools, conn, ws_id):
        # Simulate a leaked partial write left on the connection by a prior
        # aborted op (no commit/rollback). _with_tx must roll it back before its
        # own BEGIN so the leak cannot ride along into the new transaction.
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO tasks (workspace_id, title) VALUES (?, ?)",
            (ws_id, "leaked task"),
        )
        assert conn.in_transaction

        with pa_core_module._with_tx(conn) as c:
            c.execute(
                "INSERT INTO tasks (workspace_id, title) VALUES (?, ?)",
                (ws_id, "fresh task"),
            )

        leaked = conn.execute(
            "SELECT title FROM tasks WHERE title = ?", ("leaked task",)
        ).fetchone()
        fresh = conn.execute(
            "SELECT title FROM tasks WHERE title = ?", ("fresh task",)
        ).fetchone()
        assert leaked is None  # the stray pending write was discarded
        assert fresh is not None  # the new transaction committed cleanly


# ---------------------------------------------------------------------------
# T-CORE-1 — Write rolls back on a mid-operation CHECK-constraint failure
# ---------------------------------------------------------------------------

class TestCore1RollbackOnMidOpFailure:
    def test_t_core_1_check_constraint_failure_rolls_back_no_partial_commit(
        self, pa_core_module, tools, conn, ws_id
    ):
        """T-CORE-1 (contract-map pa-core test scenario).

        Given an op_params that fails a CHECK constraint partway through a
        multi-statement write, when pa-core executes it inside _with_tx, then the
        transaction rolls back, no row from the failed op is committed, and a
        typed error is raised.

        We exercise this at the SQL level so the assertion is unambiguous: the
        tasks.status CHECK only allows a closed enum, so the SECOND statement
        (an illegal status) raises sqlite3.IntegrityError mid-op, which _with_tx
        must roll back — discarding the FIRST (legal) INSERT too.
        """
        before = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError):
            with pa_core_module._with_tx(conn) as c:
                # Statement 1: a perfectly legal insert.
                c.execute(
                    "INSERT INTO tasks (workspace_id, title) VALUES (?, ?)",
                    (ws_id, "first legal row"),
                )
                # Statement 2: violates the tasks.status CHECK constraint
                # (status not in the allowed enum) -> raises mid-op.
                c.execute(
                    "INSERT INTO tasks (workspace_id, title, status) VALUES (?, ?, ?)",
                    (ws_id, "second illegal row", "NOT-A-VALID-STATUS"),
                )

        after = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        # Neither row committed — the whole multi-statement op rolled back.
        assert after == before
        assert (
            conn.execute(
                "SELECT id FROM tasks WHERE title = ?", ("first legal row",)
            ).fetchone()
            is None
        )

    def test_t_core_1_typed_error_via_update_task_on_missing_row(
        self, pa_core_module, tools, conn, ws_id
    ):
        """The pa_core write path RAISES a typed PaError on an invariant the
        schema cannot express (updating a non-existent task), and leaves no
        side effect. This is the path the adapter maps to isError=true.
        """
        before = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        with pytest.raises(pa_core_module.NotFoundError):
            pa_core_module.update_task(conn, ws_id, {"id": 999_999, "status": "done"})
        after = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        assert after == before
        assert not conn.in_transaction  # rolled back, connection clean
