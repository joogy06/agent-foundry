"""WP-3 unit tests for the schema-migrations component (design §4.1).

Covers the contract-map ``schema-migrations`` success criteria + T-MIG-1:

  * All 14 new AMY tables + the tasks due_at/start_at/planning_period columns
    exist after bootstrap on an empty DB (zero existing-row migration cost).
  * schema_migrations.version reflects the highest applied migration.
  * T-MIG-1 — Idempotent re-run is a no-op: a second run_migrations applies no
    DDL, leaves schema_migrations.version unchanged, and returns
    applied_version == target_version with newly_applied == [].
  * CHECK constraints, FK->workspaces(id), and the people_fts/external_items_fts
    ai/au/ad triggers match the existing SCHEMA_SQL idiom.
  * connectors stores env-var NAMES only (base_url_env/user_env/token_env) —
    the schema has no raw-token column.

These exercise pa_core's run_migrations DIRECTLY against the production init_db
DDL (the `conn` fixture is bootstrapped by pa_server.init_db, which already calls
run_migrations). The in-process loader is the same conftest idiom as the
characterization + WP-2 suites.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import sqlite3

import pytest

from tests.conftest import _load_pa_server


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    """The pa_core module pa_server is a thin adapter over (importable after the
    pa_server load inserts pa-server/ on sys.path)."""
    import pa_core  # noqa: PLC0415

    return pa_core


# The 14 new AMY tables per design §4.1 (schema_migrations bookkeeping table is
# verified separately as the version gate).
EXPECTED_NEW_TABLES = [
    "people",
    "teams",
    "team_members",
    "delegations",
    "blockers",
    "routines",
    "nudges",
    "role_profile",
    "style_profiles",
    "connectors",
    "external_items",
    "task_external_links",
    "approvals",
    "quarantine_extractions",
]

EXPECTED_NEW_TASK_COLUMNS = ["due_at", "start_at", "planning_period"]

EXPECTED_NEW_FTS = ["people_fts", "external_items_fts"]


def _tables(conn):
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _task_columns(conn):
    return {r["name"] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}


def _triggers(conn):
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }


# ---------------------------------------------------------------------------
# Bootstrap on an empty DB creates every new table + column
# ---------------------------------------------------------------------------

class TestBootstrapCreatesSchema:
    def test_all_14_new_tables_exist_after_bootstrap(self, conn):
        """All 14 AMY tables exist after init_db (which runs the migrations)."""
        tables = _tables(conn)
        missing = [t for t in EXPECTED_NEW_TABLES if t not in tables]
        assert not missing, f"missing AMY tables after bootstrap: {missing}"

    def test_schema_migrations_table_exists(self, conn):
        assert "schema_migrations" in _tables(conn)

    def test_tasks_gains_due_start_planning_columns(self, conn):
        cols = _task_columns(conn)
        missing = [c for c in EXPECTED_NEW_TASK_COLUMNS if c not in cols]
        assert not missing, f"missing tasks columns after migration: {missing}"

    def test_fts_companions_exist(self, conn):
        tables = _tables(conn)
        missing = [t for t in EXPECTED_NEW_FTS if t not in tables]
        assert not missing, f"missing FTS companions: {missing}"

    def test_schema_version_is_target_after_bootstrap(self, conn, pa_core_module):
        assert pa_core_module.schema_version(conn) == pa_core_module.SCHEMA_TARGET_VERSION
        # And the highest schema_migrations.version row matches.
        top = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
        assert top["v"] == pa_core_module.SCHEMA_TARGET_VERSION


# ---------------------------------------------------------------------------
# T-MIG-1 — Idempotent re-run is a no-op
# ---------------------------------------------------------------------------

class TestMig1IdempotentRerun:
    def test_t_mig_1_second_run_is_noop_version_unchanged(self, conn, pa_core_module):
        """T-MIG-1 (contract-map schema-migrations scenario).

        Given a pa.db already migrated to the latest version, when the migration
        runner executes again, then no DDL is re-applied, schema_migrations.version
        is unchanged, and applied_version equals target_version.
        """
        version_before = pa_core_module.schema_version(conn)
        rows_before = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        target = pa_core_module.SCHEMA_TARGET_VERSION
        assert version_before == target  # init_db already migrated to target

        result = pa_core_module.run_migrations(conn)

        assert result["newly_applied"] == []  # nothing re-applied
        assert result["applied_version"] == target
        assert result["target_version"] == target
        # No new schema_migrations row, version unchanged.
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == rows_before
        assert pa_core_module.schema_version(conn) == version_before

    def test_repeated_runs_stay_stable(self, conn, pa_core_module):
        """Running the migrations several more times never changes the version or
        the migration-row count (belt-and-suspenders idempotency)."""
        baseline = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        for _ in range(3):
            r = pa_core_module.run_migrations(conn)
            assert r["newly_applied"] == []
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == baseline

    def test_migration_from_scratch_on_a_bare_db(self, conn, pa_core_module):
        """A fresh connection whose only schema is the WP-2 base (no AMY tables)
        migrates forward to target and records exactly the registered versions."""
        # Build a bare DB with ONLY the base schema (no migrations applied yet).
        pa_server = _load_pa_server()
        import tempfile, os  # noqa: PLC0415
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            bare = pa_core_module.connect(path)
            bare.executescript(pa_server.SCHEMA_SQL)
            bare.executescript(pa_server.FTS_SQL)
            bare.executescript(pa_server.INDEXES_SQL)
            bare.executescript(pa_server.TRIGGERS_SQL)
            bare.commit()
            assert pa_core_module.schema_version(bare) == 0  # nothing applied yet
            assert "people" not in _tables(bare)

            result = pa_core_module.run_migrations(bare)

            assert result["newly_applied"] == [
                v for v, _n, _f in pa_core_module._MIGRATIONS
            ]
            assert result["applied_version"] == pa_core_module.SCHEMA_TARGET_VERSION
            assert "people" in _tables(bare)
            # A second run on this same DB is now a no-op (T-MIG-1).
            again = pa_core_module.run_migrations(bare)
            assert again["newly_applied"] == []
            bare.close()
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# CHECK constraints / FK / FTS-trigger idiom match the existing SCHEMA_SQL
# ---------------------------------------------------------------------------

class TestConstraintsAndIdiom:
    def test_people_relationship_check_constraint_enforced(self, conn, ws_id):
        """people.relationship has the closed CHECK enum; an illegal value raises."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO people (workspace_id, name, relationship) VALUES (?, ?, ?)",
                (ws_id, "Bad Rel", "NOT-A-RELATIONSHIP"),
            )

    def test_people_fk_to_workspaces_enforced(self, conn):
        """people.workspace_id FK -> workspaces(id) rejects an unknown workspace
        (foreign_keys=ON is set by connect())."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO people (workspace_id, name) VALUES (?, ?)",
                ("no-such-workspace", "Orphan"),
            )

    def test_delegations_status_default_and_check(self, tools, conn, ws_id):
        """delegations.status defaults to 'open' and rejects an out-of-enum value.

        ``tools`` bootstraps the workspaces row so the delegations FK ->
        workspaces(id) is satisfiable.
        """
        conn.execute(
            "INSERT INTO delegations (workspace_id, direction) VALUES (?, ?)",
            (ws_id, "delegated_out"),
        )
        row = conn.execute("SELECT status FROM delegations").fetchone()
        assert row["status"] == "open"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO delegations (workspace_id, status) VALUES (?, ?)",
                (ws_id, "NOT-A-STATUS"),
            )

    def test_people_fts_triggers_present_and_indexable(self, tools, conn, ws_id):
        """The people_fts ai/au/ad triggers exist (matching the tasks_fts idiom)
        and an insert into people is searchable via the FTS companion.

        ``tools`` bootstraps the workspaces row (FK target for people)."""
        trigs = _triggers(conn)
        for t in ("people_ai", "people_au", "people_ad"):
            assert t in trigs, f"missing FTS trigger {t}"
        conn.execute(
            "INSERT INTO people (workspace_id, name, notes) VALUES (?, ?, ?)",
            (ws_id, "Ada Lovelace", "first programmer analytical engine"),
        )
        conn.commit()
        hit = conn.execute(
            "SELECT name FROM people_fts WHERE people_fts MATCH ?", ("analytical",)
        ).fetchone()
        assert hit is not None
        assert hit["name"] == "Ada Lovelace"

    def test_external_items_fts_triggers_present_and_indexable(self, tools, conn, ws_id):
        trigs = _triggers(conn)
        for t in ("external_items_ai", "external_items_au", "external_items_ad"):
            assert t in trigs, f"missing FTS trigger {t}"
        # external_items needs a connector row first (FK); ``tools`` bootstraps
        # the workspaces row (FK target for both connectors and external_items).
        conn.execute(
            "INSERT INTO connectors (workspace_id, kind, deployment) VALUES (?, 'jira', 'cloud')",
            (ws_id,),
        )
        connector_id = conn.execute("SELECT id FROM connectors").fetchone()["id"]
        conn.execute(
            "INSERT INTO external_items (workspace_id, connector_id, remote_id, title, body) "
            "VALUES (?, ?, ?, ?, ?)",
            (ws_id, connector_id, "JIRA-1", "Ticket title", "remote untrusted body text here"),
        )
        conn.commit()
        hit = conn.execute(
            "SELECT title FROM external_items_fts WHERE external_items_fts MATCH ?", ("untrusted",)
        ).fetchone()
        assert hit is not None


# ---------------------------------------------------------------------------
# connectors stores env-var NAMES only — never raw tokens
# ---------------------------------------------------------------------------

class TestConnectorsTokenHygiene:
    def test_connectors_schema_has_env_name_columns_not_token(self, conn):
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(connectors)").fetchall()}
        # The env-var-NAME columns are present...
        for env_col in ("base_url_env", "user_env", "token_env"):
            assert env_col in cols, f"connectors missing env-name column {env_col}"
        # ...and there is NO column that would hold a raw secret value.
        forbidden = {"token", "password", "secret", "api_key", "bearer", "credential"}
        leaked = forbidden & cols
        assert not leaked, f"connectors must store env NAMES only; found raw-secret column(s): {leaked}"

    def test_connectors_unique_workspace_kind(self, tools, conn, ws_id):
        """connectors UNIQUE(workspace_id, kind) prevents duplicate connectors.

        ``tools`` bootstraps the workspaces row (FK target for connectors)."""
        conn.execute(
            "INSERT INTO connectors (workspace_id, kind, deployment) VALUES (?, 'jira', 'cloud')",
            (ws_id,),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO connectors (workspace_id, kind, deployment) VALUES (?, 'jira', 'datacenter')",
                (ws_id,),
            )

    def test_connectors_deployment_check_enum(self, tools, conn, ws_id):
        """deployment CHECK enum rejects an out-of-set value (``tools`` provides
        the workspaces row so it is the CHECK, not the FK, that fires)."""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO connectors (workspace_id, kind, deployment) VALUES (?, 'jira', 'NOPE')",
                (ws_id,),
            )
