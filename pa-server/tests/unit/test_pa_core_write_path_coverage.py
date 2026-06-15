"""WP-2 pa-core coverage-widening tests (S059 / user Option-A: WIDEN COVERAGE).

These tests close the three CRITICAL coverage gaps the Codex audit arm raised on
the pa-core dual-verdict (attempt-2, bundle 7343a11f…), WITHOUT amending the
acceptance criteria. They are STRICTLY pa-core (WP-2) scoped — no stdio-adapter,
no other component.

  GAP-1 — "every write path runs inside _with_tx".
      The prior bundle proved _with_tx rollback for two failure modes but did not
      prove that EVERY public write function actually routes through _with_tx.
      Here we (a) enumerate every public write function in pa_core via AST and
      assert — by static analysis — that none commits/executes runtime DML
      outside _with_tx, and (b) install a runtime SPY on pa_core._with_tx and
      drive each public write function once, asserting it entered _with_tx.

  GAP-2 — "concurrent reader during an active write under WAL".
      The prior bundle proved WAL is *enabled* (the pragma) but not the
      *behavioral* guarantee. Here a real second reader connection observes the
      consistent pre-commit state while a writer transaction is open on a first
      connection, then observes the committed row after the writer commits.

  GAP-3 — "pa-core is the sole writer" (repo-scoped, honest).
      The system-level "sole writer of pa.db across all processes" claim is not
      provable from one repo. What IS provable, and what the design actually
      asserts, is that the stdio adapter (pa_server.py) performs NO runtime
      DML/commit of its own — every runtime write delegates to pa_core. We scan
      pa_server.py's AST and assert that the only non-delegated DML/commit lives
      in the init_db() bootstrap (schema DDL), and that every PATools handler
      body delegates to a pa_core.* call. The claim is documented as repo-scoped.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import ast
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from tests.conftest import _load_pa_server

PA_SERVER_ROOT = Path(__file__).resolve().parent.parent.parent
PA_CORE_PATH = PA_SERVER_ROOT / "pa_core.py"
PA_SERVER_PATH = PA_SERVER_ROOT / "pa_server.py"


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    """pa_core, importable after pa_server has been exec'd (sibling on sys.path)."""
    import pa_core  # noqa: PLC0415

    return pa_core


# ---------------------------------------------------------------------------
# Static model of pa_core: which public functions are WRITERS?
# ---------------------------------------------------------------------------
#
# A "public write function" is a top-level `def name(...)` where:
#   * name does not start with '_' (public surface), AND
#   * the first parameter is a connection (conn / c), AND
#   * the body contains runtime DML (INSERT/UPDATE/DELETE/executescript) OR a
#     _with_tx use OR delegates to a private writer (_sync_source / _ensure_*).
#
# Read-only functions (SELECT-only) are excluded — they MUST NOT open a tx.

_DML_KEYWORDS = ("insert ", "update ", "delete ", "executescript", "executemany")
# Public writers that delegate their writes to a private helper which owns the
# _with_tx (so the _with_tx token is not in the public fn body itself).
_DELEGATING_WRITERS = {"sync_jira", "sync_confluence"}


def _public_functions(src: str):
    tree = ast.parse(src)
    return [n for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]


def _is_conn_first(fn: ast.FunctionDef) -> bool:
    return bool(fn.args.args) and fn.args.args[0].arg in ("conn", "c")


def _body_has_dml(src_segment: str) -> bool:
    low = src_segment.lower()
    return any(k in low for k in _DML_KEYWORDS)


def _classify_pa_core_functions():
    """Return (writers, readers) — lists of public function names."""
    src = PA_CORE_PATH.read_text()
    writers, readers = [], []
    for fn in _public_functions(src):
        if not _is_conn_first(fn):
            continue  # now_iso / workspace_id_from_path / connect / wrap_remote_field / validate_arguments
        seg = ast.get_source_segment(src, fn) or ""
        is_writer = (
            "_with_tx" in seg
            or _body_has_dml(seg)
            or fn.name in _DELEGATING_WRITERS
        )
        (writers if is_writer else readers).append(fn.name)
    return writers, readers


# The frozen expectation: every one of these public write functions MUST be
# proven to route through _with_tx. Discovered by AST; pinned here so a NEW
# public writer added later that forgets _with_tx fails this test loudly.
EXPECTED_WRITERS = {
    "run_migrations",
    "ensure_workspace",
    "create_task",
    "update_task",
    "log_action",
    "start_session",
    "end_session",
    "resolve_conflict",
    "update_preference",
    "clear_preference",
    "set_sync_config",
    "sync_jira",
    "sync_confluence",
}


class TestGap1WritePathEnumerationStatic:
    """GAP-1 (static arm): EVERY public write function routes through _with_tx,
    and NO public write function performs a raw conn.commit() in its own body
    (commit ownership belongs to _with_tx)."""

    def test_writer_set_matches_expected(self):
        writers, _readers = _classify_pa_core_functions()
        # The discovered writer set must exactly equal the pinned expectation —
        # a new unlisted writer (or a writer that lost its _with_tx and dropped
        # out of the set) breaks this immediately.
        assert set(writers) == EXPECTED_WRITERS, (
            f"pa_core public-writer set drifted.\n"
            f"  discovered: {sorted(writers)}\n"
            f"  expected:   {sorted(EXPECTED_WRITERS)}"
        )

    def test_every_writer_body_uses_with_tx_or_delegates(self):
        src = PA_CORE_PATH.read_text()
        by_name = {fn.name: fn for fn in _public_functions(src)}
        for name in EXPECTED_WRITERS:
            fn = by_name[name]
            seg = ast.get_source_segment(src, fn) or ""
            if name in _DELEGATING_WRITERS:
                # Delegating writers hand off to _sync_source (which owns _with_tx);
                # assert the delegation rather than an inline _with_tx.
                assert "_sync_source" in seg, (
                    f"{name} should delegate its write to _sync_source"
                )
            else:
                assert "_with_tx" in seg, (
                    f"public write function {name} does not route through _with_tx"
                )

    def test_no_public_writer_calls_raw_commit(self):
        """No public write function may call conn.commit()/c.commit() directly —
        commit/rollback ownership is _with_tx's alone (the fix for
        commit-on-partial-failure). A stray .commit() would re-introduce the
        partial-commit hazard."""
        src = PA_CORE_PATH.read_text()
        by_name = {fn.name: fn for fn in _public_functions(src)}
        offenders = []
        for name in EXPECTED_WRITERS:
            fn = by_name[name]
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "commit"
                ):
                    offenders.append(name)
        assert offenders == [], (
            f"public write functions call .commit() directly (must use _with_tx): {offenders}"
        )

    def test_private_sync_source_owns_its_tx(self):
        """The delegating writers' shared engine _sync_source must itself wrap
        its batch in _with_tx (so the delegation chain terminates in a tx)."""
        src = PA_CORE_PATH.read_text()
        tree = ast.parse(src)
        sync_source = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_sync_source"),
            None,
        )
        assert sync_source is not None
        seg = ast.get_source_segment(src, sync_source) or ""
        assert "_with_tx" in seg, "_sync_source must wrap its batch write in _with_tx"


class TestGap1WritePathRuntimeSpy:
    """GAP-1 (runtime arm): drive each public write function once with a SPY
    installed on pa_core._with_tx, asserting the function actually ENTERED a
    transaction at runtime. This proves the static routing is exercised, not
    just lexically present."""

    def _install_spy(self, pa_core_module, monkeypatch):
        entered = []
        real_with_tx = pa_core_module._with_tx

        import contextlib

        @contextlib.contextmanager
        def spy(conn):
            entered.append(True)
            with real_with_tx(conn) as c:
                yield c

        monkeypatch.setattr(pa_core_module, "_with_tx", spy)
        return entered

    def test_each_simple_writer_enters_with_tx(self, pa_core_module, tools, conn, ws_id, monkeypatch):
        entered = self._install_spy(pa_core_module, monkeypatch)

        # A seed task so update/resolve/log paths have a target.
        seed = pa_core_module.create_task(conn, ws_id, {"title": "seed"})
        task_id = seed["id"]

        # Drive every simple (non-sync, non-migration) public writer once. Each
        # call must push at least one entry onto `entered`.
        cases = [
            lambda: pa_core_module.create_task(conn, ws_id, {"title": "t2"}),
            lambda: pa_core_module.update_task(conn, ws_id, {"id": task_id, "status": "executing"}),
            lambda: pa_core_module.log_action(conn, ws_id, {"action": "did-x", "task_id": task_id}),
            lambda: pa_core_module.update_preference(
                conn, ws_id, {"key": "k", "value": "v", "category": "routing", "workspace": ws_id}
            ),
            lambda: pa_core_module.clear_preference(conn, ws_id, {"key": "k", "workspace": ws_id}),
            lambda: pa_core_module.set_sync_config(
                conn, ws_id, {"source": "jira", "config": {"strategy": "assigned"}}
            ),
            lambda: pa_core_module.ensure_workspace(conn, ws_id, "ws", "/tmp/ws"),
        ]
        for call in cases:
            before = len(entered)
            call()
            assert len(entered) > before, "writer did not enter _with_tx"

    def test_session_writers_enter_with_tx(self, pa_core_module, tools, conn, ws_id, monkeypatch):
        entered = self._install_spy(pa_core_module, monkeypatch)
        before = len(entered)
        started = pa_core_module.start_session(conn, ws_id, {"tool": "claude-cli"})
        assert len(entered) > before, "start_session did not enter _with_tx"
        before = len(entered)
        pa_core_module.end_session(conn, ws_id, {"session_id": started["session_id"], "summary": "s"})
        assert len(entered) > before, "end_session did not enter _with_tx"

    def test_resolve_conflict_enters_with_tx_on_missing_state(self, pa_core_module, tools, conn, ws_id, monkeypatch):
        # resolve_conflict opens a tx then raises NotFoundError for a missing
        # sync_state — the tx is entered before the raise, which is what we assert.
        entered = self._install_spy(pa_core_module, monkeypatch)
        before = len(entered)
        with pytest.raises(pa_core_module.NotFoundError):
            pa_core_module.resolve_conflict(conn, ws_id, {"sync_state_id": 999999, "resolution": "keep_local"})
        assert len(entered) > before, "resolve_conflict did not enter _with_tx"

    def test_sync_delegating_writer_enters_with_tx(self, pa_core_module, tools, conn, ws_id, monkeypatch):
        """sync_jira delegates to _sync_source which opens _with_tx. Drive it with
        an injected fetch (no network) and a single well-formed item; assert the
        engine entered a transaction."""
        import os

        entered = self._install_spy(pa_core_module, monkeypatch)
        monkeypatch.setenv("JIRA_BASE", "https://example.invalid")
        monkeypatch.setenv("JIRA_TOKEN", "tok")

        def fake_fetch(base_url, token, strategy, query):
            return [{
                "key": "ABC-1",
                "fields": {
                    "summary": "remote summary",
                    "status": {"statusCategory": {"key": "new"}},
                    "priority": {"name": "Medium"},
                    "updated": "2026-06-12T00:00:00Z",
                    "description": "remote body",
                },
            }]

        before = len(entered)
        result = pa_core_module.sync_jira(conn, ws_id, {"source_config": {}}, fake_fetch)
        assert len(entered) > before, "sync_jira (via _sync_source) did not enter _with_tx"
        assert result["new_items"] == 1
        # The remote record landed in external_items, NOT as a directly-editable
        # bare task source (sanity tie-in with the sync-rework invariant).
        ext = conn.execute("SELECT COUNT(*) FROM external_items").fetchone()[0]
        assert ext == 1

    def test_run_migrations_enters_with_tx(self, pa_core_module, tmp_path, monkeypatch):
        """run_migrations applies each migration inside its own _with_tx. On a
        fresh base-schema DB at least one migration applies, entering _with_tx."""
        pa_server = _load_pa_server()
        db = tmp_path / "fresh.db"
        # Build a bare base-schema DB WITHOUT migrations, so run_migrations has
        # work to do (and must enter _with_tx to do it).
        conn = pa_server.pa_core.connect(db)
        conn.executescript(pa_server.SCHEMA_SQL)
        conn.commit()

        entered = []
        real = pa_server.pa_core._with_tx
        import contextlib

        @contextlib.contextmanager
        def spy(c):
            entered.append(True)
            with real(c) as cc:
                yield cc

        monkeypatch.setattr(pa_server.pa_core, "_with_tx", spy)
        try:
            out = pa_server.pa_core.run_migrations(conn)
            assert out["newly_applied"], "expected at least one migration to apply on a bare DB"
            assert entered, "run_migrations did not enter _with_tx"
        finally:
            conn.close()


class TestGap2WalConcurrentReaderDuringWrite:
    """GAP-2: behavioral WAL guarantee — a concurrent reader connection sees the
    consistent PRE-commit state while a writer transaction is open, then sees the
    committed row after the writer commits. This proves the *behavior* WAL buys
    (readers never block on, nor observe, an in-flight writer's uncommitted data),
    not merely that the pragma is set."""

    def test_reader_sees_pre_commit_state_then_post_commit(self, pa_core_module, tools, conn, ws_id, tmp_path):
        # `conn`/`tools` are bound to the workspace DB; find its path so a SECOND
        # independent connection can open the same file (real concurrency, two
        # connections, WAL).
        db_path = Path(
            conn.execute("PRAGMA database_list").fetchone()[2]
        )
        assert db_path.exists()

        # Baseline count via an independent reader connection.
        reader = pa_core_module.connect(db_path)
        try:
            baseline = reader.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

            # Open a WRITER transaction on the primary connection and INSERT a row,
            # but do NOT commit yet.
            writer_tx = conn  # primary connection
            writer_tx.execute("BEGIN")
            writer_tx.execute(
                "INSERT INTO tasks (workspace_id, title) VALUES (?, ?)",
                (ws_id, "in-flight uncommitted row"),
            )

            # While the writer's tx is OPEN and UNCOMMITTED, the independent reader
            # must still see the consistent pre-commit snapshot (WAL: readers are
            # not blocked and do not observe uncommitted writer state).
            reader.execute("COMMIT") if reader.in_transaction else None
            mid = reader.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            assert mid == baseline, (
                "reader observed the writer's UNCOMMITTED row (WAL isolation violated)"
            )
            assert (
                reader.execute(
                    "SELECT id FROM tasks WHERE title = ?", ("in-flight uncommitted row",)
                ).fetchone()
                is None
            )

            # Now the writer commits.
            writer_tx.execute("COMMIT")

            # A FRESH read on the reader connection (new implicit snapshot) now
            # sees the committed row.
            post = reader.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            assert post == baseline + 1, "reader did not observe the committed row after writer COMMIT"
            assert (
                reader.execute(
                    "SELECT id FROM tasks WHERE title = ?", ("in-flight uncommitted row",)
                ).fetchone()
                is not None
            )
        finally:
            reader.close()

    def test_concurrent_reader_thread_not_blocked_by_open_writer(self, pa_core_module, tools, conn, ws_id):
        """A reader on a separate THREAD + connection completes promptly while a
        writer transaction is held open — it is neither blocked to timeout nor
        does it see uncommitted data. Proves WAL readers do not serialize behind
        an active writer (the concurrent-reader-during-write behavior)."""
        db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2])

        # Hold a writer transaction open on the primary connection.
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO tasks (workspace_id, title) VALUES (?, ?)",
            (ws_id, "held-open writer row"),
        )

        result = {}

        def reader_thread():
            r = pa_core_module.connect(db_path)
            try:
                t0 = time.monotonic()
                cnt = r.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
                result["elapsed"] = time.monotonic() - t0
                result["count"] = cnt
                result["saw_uncommitted"] = (
                    r.execute(
                        "SELECT id FROM tasks WHERE title = ?", ("held-open writer row",)
                    ).fetchone()
                    is not None
                )
            finally:
                r.close()

        t = threading.Thread(target=reader_thread)
        t.start()
        t.join(timeout=10)

        # Release the writer.
        conn.execute("COMMIT")

        assert not t.is_alive(), "reader thread blocked behind the open writer (WAL concurrency failed)"
        assert "count" in result, "reader thread did not complete"
        # The reader must NOT have observed the writer's uncommitted row, and it
        # completed well within busy_timeout (5000ms) — promptly, not blocked.
        assert result["saw_uncommitted"] is False, "concurrent reader saw uncommitted writer data"
        assert result["elapsed"] < 5.0, f"reader was blocked ({result['elapsed']:.2f}s) — WAL concurrency failed"


class TestGap3SoleWriterRepoScoped:
    """GAP-3 (repo-scoped, honest): the stdio adapter pa_server.py performs NO
    runtime DML/commit of its own — every runtime write delegates to pa_core. The
    ONLY non-delegated DML/commit allowed is the init_db() bootstrap (schema DDL).

    HONEST SCOPE: this is a REPO-scoped static guarantee about pa_server.py, not a
    system-wide runtime proof that pa-core is the only process ever to write
    pa.db. The cross-process 'sole writer' property is enforced operationally
    (single MCP server process per workspace) and is out of scope for a unit test;
    we assert the in-repo invariant the design actually owns."""

    def _server_functions(self):
        src = PA_SERVER_PATH.read_text()
        return src, ast.parse(src)

    def test_only_init_db_holds_nondelegated_dml(self):
        """Walk every top-level function + method in pa_server.py. Any function
        whose body contains a raw conn.commit() or runtime DML execute() that is
        NOT a CREATE/SCHEMA bootstrap must be init_db. Everything else must route
        through a pa_core.* call."""
        src, tree = self._server_functions()

        def iter_funcs(node, prefix=""):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef):
                    yield prefix + child.name, child
                    yield from iter_funcs(child, prefix + child.name + ".")
                elif isinstance(child, ast.ClassDef):
                    yield from iter_funcs(child, prefix + child.name + ".")

        offenders = []
        for qualname, fn in iter_funcs(tree):
            seg = ast.get_source_segment(src, fn) or ""
            low = seg.lower()
            calls_commit = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("commit", "executemany")
                for n in ast.walk(fn)
            )
            # Runtime DML markers (exclude CREATE TABLE/TRIGGER/INDEX DDL which is
            # bootstrap, and exclude SQL embedded in module-level DDL constants —
            # those are not inside a function body unless init_db references them).
            has_runtime_dml_kw = any(
                k in low for k in ("insert into", "update ", "delete from")
            )
            short = qualname.split(".")[-1]
            if (calls_commit or has_runtime_dml_kw):
                # init_db is the sanctioned bootstrap exception (schema DDL +
                # one commit). Everything else is an offender.
                if short != "init_db":
                    # The DDL constants (SCHEMA_SQL etc.) contain INSERT inside
                    # trigger bodies; those live in module-level strings, not in a
                    # function body, so they won't reach here. But guard anyway:
                    # only flag if the DML is NOT inside a CREATE TRIGGER block.
                    if "create trigger" not in low:
                        offenders.append(qualname)
        assert offenders == [], (
            f"pa_server.py functions perform non-delegated DML/commit outside init_db "
            f"(sole-writer invariant breach): {offenders}"
        )

    def test_init_db_dml_is_bootstrap_only(self):
        """init_db's only write surface is schema DDL via executescript +
        pa_core.run_migrations — no runtime row INSERT/UPDATE/DELETE of its own."""
        src, tree = self._server_functions()
        init_db = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "init_db"),
            None,
        )
        assert init_db is not None
        seg = ast.get_source_segment(src, init_db) or ""
        low = seg.lower()
        # Bootstrap writes are executescript (DDL) + run_migrations delegation.
        assert "executescript" in low
        assert "run_migrations" in low
        # No raw runtime row DML in init_db's own body.
        assert "insert into" not in low
        assert "update " not in low.replace("update set", "")  # defensive
        assert "delete from" not in low

    def test_every_patools_handler_delegates_to_pa_core(self):
        """Each PATools.pa_* handler method body contains a pa_core.* call and no
        raw DML — the adapter is a pure façade over the single writer."""
        src, tree = self._server_functions()
        patools = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "PATools"),
            None,
        )
        assert patools is not None
        handler_methods = [
            n for n in patools.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("pa_")
        ]
        assert handler_methods, "no pa_* handler methods found on PATools"
        for m in handler_methods:
            seg = ast.get_source_segment(src, m) or ""
            assert "pa_core." in seg, (
                f"PATools.{m.name} does not delegate to pa_core (sole-writer façade breach)"
            )
            low = seg.lower()
            assert "insert into" not in low and "delete from" not in low, (
                f"PATools.{m.name} contains raw DML instead of delegating to pa_core"
            )

    def test_pa_server_imports_pa_core_as_single_writer(self):
        """pa_server.py imports pa_core (the documented single SQLite writer)."""
        src, tree = self._server_functions()
        imports_pa_core = any(
            (isinstance(n, ast.Import) and any(a.name == "pa_core" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "pa_core")
            for n in ast.walk(tree)
        )
        assert imports_pa_core, "pa_server.py must import pa_core (the single writer)"
