#!/usr/bin/env python3
"""
pa_core — transport-neutral data-access core for the PA / AMY kernel (M0a / WP-2).

This module hosts the SINGLE SQLite writer for a PA workspace. Every operation is
a plain ``def fn(conn, ws_id, params) -> dict|list`` function: no transport
concern, no stdio, no JSON-RPC. The stdio JSON-RPC adapter (``pa_server.py``) and
the future M4 localhost dashboard both import these functions; the dashboard uses
only the read functions (single-writer invariant — pa_core owns every write).

Design anchors (docs/plans/2026-06-11-amy-m0-kernel-routines-design.md §WP-2):

  * ``_with_tx(conn)`` — BEGIN / COMMIT, ROLLBACK on exception. Every write path
    runs inside it so a mid-operation failure rolls the WHOLE op back. Fixes the
    commit-on-partial-failure bug (old pa_server.py :620/:628 committed per-batch
    with no rollback on a mid-batch raise).
  * ``connect()`` sets ``PRAGMA busy_timeout=5000`` (block-and-retry instead of an
    immediate SQLITE_BUSY) in addition to WAL + foreign_keys, which the old
    ``init_db`` already set.
  * Handlers RAISE typed errors (``PaError`` subclasses: ``NotFoundError``,
    ``ValidationError``) instead of returning ``{"error": ...}`` dicts, so the
    adapter's dispatcher reports ``isError=true`` honestly. Fixes the
    isError:False-wrapped-error-dict bug (old :628 -> :1244).

stdlib-only — json / os / sqlite3 / hashlib / datetime. NO new pip deps
(AMY D-plus lock).
"""

import json
import os
import sqlite3
import hashlib
import base64
import contextlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta, date
from pathlib import Path


# ---------------------------------------------------------------------------
# Typed errors (handlers RAISE these; the adapter maps them to isError=true)
# ---------------------------------------------------------------------------

class PaError(Exception):
    """Base class for all pa_core operational errors. Carries a stable
    ``code`` so the adapter (and future dashboard) can branch on the kind of
    failure without string-matching the message."""

    code = "pa_error"

    def to_payload(self) -> dict:
        return {"error": str(self), "code": self.code}


class NotFoundError(PaError):
    """A referenced row (task / sync_state / session) does not exist."""

    code = "not_found"


class ValidationError(PaError):
    """Caller-supplied params are invalid (missing required, bad type/enum).
    Raised by the adapter's pre-dispatch JSON-Schema guard AND by core
    functions that re-check invariants the schema cannot express."""

    code = "validation_error"


class SyncError(PaError):
    """A sync/remote operation failed (missing credentials, HTTP error, or a
    malformed remote item mid-batch). Raised (not returned) so the failed batch
    rolls back via ``_with_tx`` and the adapter reports isError=true."""

    code = "sync_error"


# ---------------------------------------------------------------------------
# Time + workspace helpers (kept here so the dashboard need not import pa_server)
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Current UTC timestamp in the ISO format the schema's datetime() default
    is compatible with."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def workspace_id_from_path(ws_path: Path) -> str:
    """Derive a stable workspace ID from its path (sha256 prefix)."""
    return hashlib.sha256(str(ws_path).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Connection + transaction discipline
# ---------------------------------------------------------------------------

def connect(db_path) -> sqlite3.Connection:
    """Open a SQLite connection with the pa_core PRAGMA set:

      * journal_mode=WAL        — concurrent readers (future dashboard) under a
                                  single writer.
      * foreign_keys=ON         — enforce the workspaces FK references.
      * busy_timeout=5000       — block-and-retry up to 5s instead of raising
                                  SQLITE_BUSY immediately (NEW in M0a).

    isolation_level is left at the sqlite3 default; ``_with_tx`` issues an
    explicit BEGIN so transaction boundaries are owned by pa_core, not by the
    driver's implicit-transaction heuristics.
    """
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextlib.contextmanager
def _with_tx(conn: sqlite3.Connection):
    """Transaction context-manager: explicit BEGIN, COMMIT on clean exit,
    ROLLBACK on ANY exception.

    Wrapping every write path in this is the fix for commit-on-partial-failure:
    a mid-operation CHECK-constraint violation (or any raise) discards every
    pending statement of the operation instead of leaving them on the connection
    to be flushed by the next successful commit.

    Nesting note: SQLite has a single transaction per connection, so this is NOT
    re-entrant — a write function wrapped in _with_tx must not call another
    _with_tx-wrapped function. pa_core composes at the SQL level (multiple
    statements inside ONE _with_tx), never by nesting transaction managers.
    """
    # Roll back any stray pending state from a prior aborted op before we begin,
    # so a leaked partial write can never ride along into this transaction.
    if conn.in_transaction:
        conn.rollback()
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


# ---------------------------------------------------------------------------
# Schema migrations (WP-3 / component schema-migrations, design §4.1)
# ---------------------------------------------------------------------------
#
# AMY adds 14 new tables + the tasks due_at/start_at/planning_period columns on
# top of the WP-2 base schema (SCHEMA_SQL/FTS_SQL/INDEXES_SQL/TRIGGERS_SQL in
# pa_server.init_db). The plan adopted a schema_migrations bookkeeping table from
# day one (the cheap insurance — design §4.1 / "No-migration assumption
# rejected"): re-running migrations on an already-migrated DB is a no-op, and
# schema_migrations.version reflects the highest applied migration.
#
# Idempotency is belt-and-suspenders:
#   * the DDL itself is IF-NOT-EXISTS / column-exists-checked (safe to re-run);
#   * the schema_migrations version gate SKIPS any migration whose version is
#     already recorded, so a second run touches no DDL and leaves version
#     unchanged (T-MIG-1).
#
# Each migration runs inside its OWN _with_tx so a mid-migration failure rolls
# that migration back atomically (no half-applied version row). All new tables
# carry the FK->workspaces(id), CHECK constraints, and the ai/au/ad FTS-trigger
# idiom matching the existing SCHEMA_SQL. Empty DBs => zero row migration cost.
#
# NOTE on placement: the new-table DDL lives HERE in pa_core (the schema-migrations
# component source path) rather than in pa_server.SCHEMA_SQL. pa_server.init_db
# calls run_migrations(conn) after the base schema so the adapter (and the future
# M4 dashboard, which also imports pa_core) bootstrap identically.

# v1 — AMY M0a kernel schema additions. One executescript per logical group so a
# group's failure rolls back as a unit. The version gate (schema_migrations)
# guards the whole v1 set; the IF NOT EXISTS guards each statement.

_MIGRATION_1_TABLES = """
-- People / org-graph (delegations + blockers reference these).
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  name TEXT NOT NULL, email TEXT, role TEXT,
  relationship TEXT CHECK(relationship IN ('manager','report','peer','stakeholder','vendor','self')),
  manager_person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
  external_id TEXT,
  notes TEXT, created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')),
  UNIQUE(workspace_id, email));

CREATE TABLE IF NOT EXISTS teams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  name TEXT NOT NULL, kind TEXT CHECK(kind IN ('squad','programme','vendor','virtual','reporting')),
  lead_person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
  external_ref TEXT,
  notes TEXT, created_at TEXT DEFAULT (datetime('now')), UNIQUE(workspace_id, name));

CREATE TABLE IF NOT EXISTS team_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  role_on_team TEXT, allocation REAL,
  active INTEGER DEFAULT 1, UNIQUE(team_id, person_id));

CREATE TABLE IF NOT EXISTS delegations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
  team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL,
  direction TEXT CHECK(direction IN ('delegated_out','owed_to_me')),
  status TEXT DEFAULT 'open' CHECK(status IN ('open','chased','done','dropped')),
  expected_by TEXT, last_nudged_at TEXT, created_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS blockers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  blocked_on_person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
  blocked_on_task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  kind TEXT CHECK(kind IN ('person','task','decision','external')),
  description TEXT NOT NULL, severity TEXT DEFAULT 'medium' CHECK(severity IN ('critical','high','medium','low')),
  status TEXT DEFAULT 'active' CHECK(status IN ('active','cleared')),
  raised_at TEXT DEFAULT (datetime('now')), cleared_at TEXT);

CREATE TABLE IF NOT EXISTS routines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT REFERENCES workspaces(id),
  kind TEXT NOT NULL CHECK(kind IN ('briefing','today','tomorrow','week','month')),
  cadence TEXT, last_run_at TEXT, enabled INTEGER DEFAULT 1, config TEXT);

CREATE TABLE IF NOT EXISTS nudges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  delegation_id INTEGER REFERENCES delegations(id) ON DELETE SET NULL,
  kind TEXT CHECK(kind IN ('stale_task','due','overdue_delegation','blocker_aging','followup')),
  message TEXT NOT NULL, source TEXT DEFAULT 'manual' CHECK(source IN ('manual','routine','ingested')),
  due_at TEXT, snooze_until TEXT, snooze_count INTEGER DEFAULT 0,
  state TEXT DEFAULT 'pending' CHECK(state IN ('pending','shown','snoozed','acked','dismissed')),
  created_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS role_profile (
  workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id),
  role_title TEXT, aims TEXT, responsibilities TEXT, methodology TEXT,
  reporting_lines TEXT, escalation_threshold TEXT, tone TEXT, updated_at TEXT DEFAULT (datetime('now')));

CREATE TABLE IF NOT EXISTS style_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT REFERENCES workspaces(id),
  channel TEXT CHECK(channel IN ('email','jira','confluence','chat','briefing')),
  tone TEXT, sample TEXT, derived_from TEXT,
  confidence REAL DEFAULT 0.3, signal_count INTEGER DEFAULT 1, updated_at TEXT DEFAULT (datetime('now')));

-- Sync rework (fixes the :599 root cause — design §4.2). Remote records are NOT
-- locally-editable tasks; connectors stores env-var NAMES only (never raw tokens).
CREATE TABLE IF NOT EXISTS connectors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  kind TEXT NOT NULL,
  deployment TEXT CHECK(deployment IN ('cloud','datacenter','graph')),
  auth_mode TEXT,
  base_url_env TEXT, user_env TEXT, token_env TEXT,
  allowed_host TEXT, query TEXT, enabled INTEGER DEFAULT 1, UNIQUE(workspace_id, kind));

CREATE TABLE IF NOT EXISTS external_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  connector_id INTEGER NOT NULL REFERENCES connectors(id),
  remote_id TEXT NOT NULL, remote_url TEXT,
  title TEXT, body TEXT,
  remote_version TEXT, remote_hash TEXT, last_synced TEXT,
  UNIQUE(workspace_id, connector_id, remote_id));

CREATE TABLE IF NOT EXISTS task_external_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  external_item_id INTEGER NOT NULL REFERENCES external_items(id) ON DELETE CASCADE,
  link_kind TEXT DEFAULT 'mirror' CHECK(link_kind IN ('mirror','derived','reference')),
  base_remote_version TEXT, base_local_updated_at TEXT,
  UNIQUE(task_id, external_item_id));

-- Security-floor table-shapes (WP-7 surfaces them; engines deferred to M3, §6
-- L2/L4). Columns ship now (empty-DB freedom); NO engine logic here.
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  action_kind TEXT NOT NULL,
  payload TEXT,
  approval_token TEXT,
  state TEXT DEFAULT 'pending' CHECK(state IN ('pending','approved','rejected','executed','expired')),
  proposed_by TEXT, created_at TEXT DEFAULT (datetime('now')), decided_at TEXT);

CREATE TABLE IF NOT EXISTS quarantine_extractions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  external_item_id INTEGER REFERENCES external_items(id) ON DELETE CASCADE,
  input_hash TEXT,
  facts TEXT,
  schema_version TEXT, extracted_at TEXT DEFAULT (datetime('now')));
"""

# FTS companions where bodies exist (design §4.1): people_fts(name,notes) +
# external_items_fts(title,body), with the existing ai/au/ad trigger idiom.
_MIGRATION_1_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS people_fts USING fts5(
    name, notes,
    content=people, content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS external_items_fts USING fts5(
    title, body,
    content=external_items, content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS people_ai AFTER INSERT ON people BEGIN
    INSERT INTO people_fts(rowid, name, notes) VALUES (new.id, new.name, new.notes);
END;
CREATE TRIGGER IF NOT EXISTS people_au AFTER UPDATE ON people BEGIN
    INSERT INTO people_fts(people_fts, rowid, name, notes) VALUES('delete', old.id, old.name, old.notes);
    INSERT INTO people_fts(rowid, name, notes) VALUES (new.id, new.name, new.notes);
END;
CREATE TRIGGER IF NOT EXISTS people_ad AFTER DELETE ON people BEGIN
    INSERT INTO people_fts(people_fts, rowid, name, notes) VALUES('delete', old.id, old.name, old.notes);
END;

CREATE TRIGGER IF NOT EXISTS external_items_ai AFTER INSERT ON external_items BEGIN
    INSERT INTO external_items_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS external_items_au AFTER UPDATE ON external_items BEGIN
    INSERT INTO external_items_fts(external_items_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body);
    INSERT INTO external_items_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS external_items_ad AFTER DELETE ON external_items BEGIN
    INSERT INTO external_items_fts(external_items_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body);
END;
"""

# Indexes for the new org-graph + sync hot paths.
_MIGRATION_1_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_people_workspace ON people(workspace_id);
CREATE INDEX IF NOT EXISTS idx_delegations_workspace_status ON delegations(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_blockers_workspace_status ON blockers(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_nudges_workspace_state ON nudges(workspace_id, state);
CREATE INDEX IF NOT EXISTS idx_external_items_workspace_connector ON external_items(workspace_id, connector_id);
CREATE INDEX IF NOT EXISTS idx_task_external_links_task ON task_external_links(task_id);
CREATE INDEX IF NOT EXISTS idx_approvals_workspace_state ON approvals(workspace_id, state);
"""

# tasks gains due_at/start_at/planning_period (design §4.1: M2 reviews are
# underivable from created_at/updated_at alone). SQLite has no
# "ADD COLUMN IF NOT EXISTS", so the runner column-checks before ALTER.
_MIGRATION_1_TASK_COLUMNS = (
    ("due_at", "ALTER TABLE tasks ADD COLUMN due_at TEXT"),
    ("start_at", "ALTER TABLE tasks ADD COLUMN start_at TEXT"),
    ("planning_period", "ALTER TABLE tasks ADD COLUMN planning_period TEXT"),
)


def _table_columns(conn: sqlite3.Connection, table: str) -> set:
    """Column-name set for ``table`` (empty if the table does not exist)."""
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migration_1(conn: sqlite3.Connection) -> None:
    """v1 — AMY M0a kernel schema additions.

    Runs as the migration body inside run_migrations' per-version _with_tx, so a
    failure here rolls the WHOLE v1 set (including the version row) back. Each
    statement is IF NOT EXISTS / column-checked, so even outside the version gate
    re-running is a no-op.
    """
    conn.executescript(_MIGRATION_1_TABLES)
    conn.executescript(_MIGRATION_1_FTS)
    conn.executescript(_MIGRATION_1_INDEXES)
    existing_cols = _table_columns(conn, "tasks")
    for col, ddl in _MIGRATION_1_TASK_COLUMNS:
        if col not in existing_cols:
            conn.execute(ddl)


# The migration registry: (version, note, apply_fn). Append-only — NEVER mutate
# or reorder an already-shipped migration (that would re-version a DB inconsistently).
# Each apply_fn takes the connection and runs its DDL; run_migrations wraps each
# in its own transaction and records the version in schema_migrations.
_MIGRATIONS = [
    (1, "AMY M0a kernel schema: people/teams/team_members/delegations/blockers/"
        "routines/nudges/role_profile/style_profiles/connectors/external_items/"
        "task_external_links/approvals/quarantine_extractions + tasks "
        "due_at/start_at/planning_period + people_fts/external_items_fts",
     _migration_1),
]

# The highest version this code knows how to apply — the migration target.
SCHEMA_TARGET_VERSION = max(v for v, _note, _fn in _MIGRATIONS) if _MIGRATIONS else 0


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    """Create the schema_migrations bookkeeping table (idempotent, design §4.1).

    Its OWN creation is outside the version gate (it IS the gate), inside its own
    transaction so a partial create can't leave the gate half-formed."""
    with _with_tx(conn) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now')), note TEXT)"
        )


def schema_version(conn: sqlite3.Connection) -> int:
    """Highest applied migration version (0 if none / table absent)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not row:
        return 0
    out = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return int(out["v"]) if out and out["v"] is not None else 0


def run_migrations(conn: sqlite3.Connection, target_version: int = None) -> dict:
    """Apply every registered migration whose version is not yet recorded, up to
    ``target_version`` (defaults to SCHEMA_TARGET_VERSION — the highest known).

    Idempotent (T-MIG-1): on an already-migrated DB no DDL is re-applied,
    schema_migrations.version is unchanged, and applied_version == target_version.

    Each migration runs in its OWN _with_tx — the DDL and the version row commit
    (or roll back) together, so a crash mid-migration never records a version
    whose DDL did not land. Empty DBs => zero existing-row migration cost.

    Returns {"applied_version": int, "target_version": int, "newly_applied": [v...]}.
    """
    if target_version is None:
        target_version = SCHEMA_TARGET_VERSION

    _ensure_schema_migrations_table(conn)
    current = schema_version(conn)

    newly_applied = []
    for version, note, apply_fn in _MIGRATIONS:
        if version <= current:
            continue  # already recorded — the version gate (no DDL re-applied)
        if version > target_version:
            break  # caller pinned an older target
        # DDL + version row in ONE transaction: atomic per migration.
        with _with_tx(conn) as c:
            apply_fn(c)
            c.execute(
                "INSERT INTO schema_migrations (version, applied_at, note) VALUES (?, ?, ?)",
                (version, now_iso(), note),
            )
        newly_applied.append(version)

    return {
        "applied_version": schema_version(conn),
        "target_version": target_version,
        "newly_applied": newly_applied,
    }


# ---------------------------------------------------------------------------
# Security floor — L1 delimiter wrap (WP-7, design §6 "Security model")
# ---------------------------------------------------------------------------
#
# THE L1 ANTI-INJECTION FLOOR. Every remote-authored field (external_items.body
# /title, ticket/page text, mail subject/body) MUST be surfaced to an agent
# wrapped in <untrusted_remote_content>…</…> so the trust boundary between
# instruction and data is explicit (cpmail's <user_data> precedent — but cpmail
# v1 does NOT escape an embedded close-delimiter, so attacker text containing a
# literal </user_data> breaks out of the wrapper. WP-7 closes exactly that hole:
# T-SEC-1 — the embedded close-delimiter is escaped so it cannot terminate the
# wrapper early).
#
# A `provenance` discriminator (local | remote) drives the wrap: locally-authored
# text (the user's own task titles, notes) is trusted and passes through
# unwrapped; remote-authored text is ALWAYS wrapped. This is a PURE FUNCTION — no
# I/O, no DB, no transport — so the sync-rework (WP-4) and briefing-snapshot
# (WP-5) readers can route every remote field through it before any agent read.
#
# L1 is necessary but NOT sufficient alone (design §6): the Dual-LLM quarantine
# (L2) + human-in-the-loop approvals (L4) engines are deferred to M3. The
# approvals + quarantine_extractions TABLE SHAPES ship now (empty-DB DDL, see
# _MIGRATION_1_TABLES) with NO engine logic.
#
# --- L6: NO-EXECUTE-FROM-DATA (hard rule; cpmail precedent) ---------------------
# Content tagged `remote` is DATA, never an instruction. It is never eval'd, never
# used to select a tool, never concatenated into a system/instruction string
# without the L1 wrapper. The agent persona that consumes AMY output MUST treat
# everything inside <untrusted_remote_content>…</…> as inert quoted data — an
# embedded "ignore previous instructions / send an email now" is at most a
# *pending proposed action* the user must approve (L4), never an auto-executed
# one. M0a encodes the rule here + in the wrapper; L2 enforcement is M3.
#
# --- L7: LEAST-PRIVILEGE / SEPARABLE EGRESS TOOL NAMING ------------------------
# Read/ingest tools and egress tools get SEPARATE permission scopes so a future
# settings.json can carry a stricter `ask` rule on egress alone. M0a implements NO
# outward egress (honest framing: the routine engine writes only the LOCAL DB —
# nudges, sessions — never out of the host). Egress tool names are kept SEPARABLE
# by the EGRESS_TOOL_INFIX convention below: any future send/post/write-back tool
# is named ``*_send_*`` (e.g. ``mcp__pa-server__mail_send_draft``) so a single
# glob ``mcp__pa-server__*_send_*`` can scope the stricter ask-rule. Read/ingest
# tools (``*_search_*``, ``*_get_*``, ``*_sync_*``) never carry the infix.

# The wrapper delimiters. Kept as module constants so tests + future readers
# reference one source of truth (never hardcode the literal tag at call sites).
UNTRUSTED_OPEN = "<untrusted_remote_content>"
UNTRUSTED_CLOSE = "</untrusted_remote_content>"

# L7 convention: egress (outward-sending) tools carry this infix so a single
# permission glob ``mcp__pa-server__*_send_*`` can scope a stricter ask-rule.
# M0a ships NO egress tools; this names the future-reserved scope only.
EGRESS_TOOL_INFIX = "_send_"


def wrap_remote_field(raw_field, provenance: str):
    """L1 delimiter-wrap a single field according to its provenance (PURE).

    Args:
        raw_field: the field text. ``None`` passes through as ``None`` (an absent
            body is not data to wrap). Non-str values are coerced via ``str()`` so
            a caller cannot smuggle a non-string past the wrap.
        provenance: ``"local"`` (trusted, the user's own text) → return unchanged;
            ``"remote"`` (any externally-authored text) → wrap in
            ``<untrusted_remote_content>…</…>`` with every embedded close-delimiter
            escaped so it cannot break out of the wrapper (T-SEC-1).

    Returns:
        The wrapped string for ``provenance="remote"``; the unchanged value for
        ``provenance="local"`` (``None`` stays ``None``).

    Raises:
        ValidationError: if ``provenance`` is not one of the closed two-value set
            {"local", "remote"} — an unknown discriminator must FAIL CLOSED rather
            than silently pass remote text through unwrapped.

    Security invariant (T-SEC-1): a remote ``raw_field`` containing a literal
    ``</untrusted_remote_content>`` sequence is neutralised — the embedded ``<`` of
    the close-delimiter is escaped to ``&lt;`` so the sequence can no longer
    terminate the wrapper. The wrapper's own boundary delimiters are the ONLY
    unescaped occurrences in the output, so a downstream parser/agent reading to
    the first true ``</untrusted_remote_content>`` always sees the full payload as
    inert data.
    """
    if provenance not in ("local", "remote"):
        raise ValidationError(
            f"wrap_remote_field: provenance must be 'local' or 'remote', "
            f"got {provenance!r} (fail-closed: unknown provenance is not trusted)"
        )

    if provenance == "local":
        # Trusted, user-authored: pass through untouched (None stays None).
        return raw_field

    # provenance == "remote": always wrap. Coerce to str first so a non-str body
    # cannot bypass the escape.
    text = "" if raw_field is None else str(raw_field)

    # Escape any embedded close-delimiter so it cannot break out of the wrapper.
    # We escape the leading '<' of the close-delimiter specifically; escaping the
    # bare close-delimiter string (not all '<') keeps the payload otherwise
    # byte-faithful (an agent still reads the attacker's text — it just can no
    # longer terminate the wrapper). Defence-in-depth: also escape the OPEN
    # delimiter so injected nested wrappers can't confuse a boundary scanner.
    escaped = text.replace(UNTRUSTED_CLOSE, "&lt;/untrusted_remote_content>")
    escaped = escaped.replace(UNTRUSTED_OPEN, "&lt;untrusted_remote_content>")

    return f"{UNTRUSTED_OPEN}{escaped}{UNTRUSTED_CLOSE}"


# ---------------------------------------------------------------------------
# Workspace bootstrap
# ---------------------------------------------------------------------------

def ensure_workspace(conn: sqlite3.Connection, ws_id: str, ws_name: str, ws_path: str) -> None:
    """Ensure the workspaces row for ``ws_id`` exists; refresh last_accessed if
    it already does. Runs inside its own transaction."""
    with _with_tx(conn) as c:
        row = c.execute("SELECT id FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
        if not row:
            c.execute(
                "INSERT INTO workspaces (id, name, project_path, last_accessed) VALUES (?, ?, ?, ?)",
                (ws_id, ws_name, ws_path, now_iso()),
            )
        else:
            c.execute(
                "UPDATE workspaces SET last_accessed = ? WHERE id = ?",
                (now_iso(), ws_id),
            )


# ---------------------------------------------------------------------------
# Task management
# ---------------------------------------------------------------------------

def create_task(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    workspace = params.get("workspace", ws_id)
    title = params["title"]
    description = params.get("description")
    priority = params.get("priority", "medium")
    source = params.get("source", "local")
    remote_id = params.get("remote_id")
    remote_url = params.get("remote_url")
    tags = params.get("tags")
    if isinstance(tags, list):
        tags = json.dumps(tags)

    with _with_tx(conn) as c:
        cur = c.execute(
            """INSERT INTO tasks (workspace_id, title, description, priority, source, remote_id, remote_url, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (workspace, title, description, priority, source, remote_id, remote_url, tags),
        )
        task_id = cur.lastrowid
    return {"id": task_id, "title": title, "status": "new", "created_at": now_iso()}


def update_task(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    task_id = params["id"]
    updates = []
    values = []
    for field in ("status", "priority", "description", "assigned_agent", "tags"):
        if field in params:
            val = params[field]
            if field == "tags" and isinstance(val, list):
                val = json.dumps(val)
            updates.append(f"{field} = ?")
            values.append(val)

    if "status" in params:
        status = params["status"]
        if status == "designed":
            updates.append("designed_at = ?")
            values.append(now_iso())
        elif status in ("done", "failed", "cancelled"):
            updates.append("completed_at = ?")
            values.append(now_iso())

    updates.append("updated_at = ?")
    values.append(now_iso())
    values.append(task_id)

    with _with_tx(conn) as c:
        # Existence check inside the tx so a missing task does not silently
        # no-op-then-report-success. RAISE NotFoundError -> adapter isError=true.
        row = c.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise NotFoundError(f"Task {task_id} not found")
        c.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values)

    out = conn.execute(
        "SELECT id, title, status, updated_at FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return dict(out)


def query_tasks(conn: sqlite3.Connection, ws_id: str, params: dict) -> list:
    workspace = params.get("workspace", ws_id)
    conditions = ["workspace_id = ?"]
    values = [workspace]

    for field in ("status", "priority", "source"):
        if field in params and params[field]:
            conditions.append(f"{field} = ?")
            values.append(params[field])

    if "since" in params and params["since"]:
        conditions.append("updated_at >= ?")
        values.append(params["since"])

    limit = params.get("limit", 50)
    sql = (
        "SELECT id, title, status, priority, source, remote_id, tags, updated_at "
        f"FROM tasks WHERE {' AND '.join(conditions)} ORDER BY updated_at DESC LIMIT ?"
    )
    values.append(limit)

    rows = conn.execute(sql, values).fetchall()
    return [dict(r) for r in rows]


def get_task(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    task_id = params["id"]
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise NotFoundError(f"Task {task_id} not found")

    actions = conn.execute(
        "SELECT id, action, agent, skill, result, artifacts, created_at "
        "FROM actions WHERE task_id = ? ORDER BY created_at DESC LIMIT 20",
        (task_id,),
    ).fetchall()

    result = dict(task)
    result["recent_actions"] = [dict(a) for a in actions]
    return result


# ---------------------------------------------------------------------------
# Action logging
# ---------------------------------------------------------------------------

def log_action(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    workspace = params.get("workspace", ws_id)
    task_id = params.get("task_id")
    action = params["action"]
    agent = params.get("agent")
    skill = params.get("skill")
    result = params.get("result")
    artifacts = params.get("artifacts")
    if isinstance(artifacts, list):
        artifacts = json.dumps(artifacts)

    with _with_tx(conn) as c:
        cur = c.execute(
            """INSERT INTO actions (task_id, workspace_id, action, agent, skill, result, artifacts)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_id, workspace, action, agent, skill, result, artifacts),
        )
        action_id = cur.lastrowid
    return {"id": action_id, "created_at": now_iso()}


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def get_briefing_snapshot(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """Compose the catch-up briefing snapshot as a PURE, idempotent read (WP-5).

    Returns the composed read — active tasks + last-24h actions + last-session
    summary + due nudges (+ unresolved conflicts) — with NO write side effect:
    no ``sessions`` row is inserted, no other table is mutated. Calling this
    twice with no intervening write returns byte-identical payloads and leaves
    the ``sessions`` table untouched (T-BRIEF-1).

    The pure read is the M4-dashboard-importable surface; ``start_session`` is a
    thin write-then-call shim over it (back-compat for the documented pa-agent
    protocol + STATELESS-MODE). The returned payload carries NO per-call
    ``session_id`` (that is the shim's write artifact, not part of the read) so
    repeated reads are deterministic.

    Remote-authored fields surfaced in the payload (nudge messages whose
    ``source = 'ingested'`` are externally authored; ``conflict_detail`` mirrors
    a remote sync record) are delimiter-wrapped via ``wrap_remote_field(...,
    'remote')`` (security-floor / WP-7, L1) so a downstream agent reading the
    briefing treats them as inert data — never as instructions (L6).

    Args:
        conn: an open pa_core connection (single-writer; this path never writes).
        ws_id: the default workspace id.
        params: optional ``workspace`` override.

    Returns:
        dict with keys ``workspace``, ``active_tasks``, ``recent_actions``,
        ``due_nudges``, ``unresolved_conflicts``, ``last_session_summary``.
    """
    workspace = params.get("workspace", ws_id)

    active_tasks = conn.execute(
        "SELECT id, title, status, priority, assigned_agent, updated_at FROM tasks "
        "WHERE workspace_id = ? AND status NOT IN ('done','failed','cancelled') "
        "ORDER BY priority, updated_at DESC",
        (workspace,),
    ).fetchall()

    recent_actions = conn.execute(
        "SELECT a.id, a.task_id, a.action, a.agent, a.result, a.created_at FROM actions a "
        "WHERE a.workspace_id = ? AND a.created_at >= datetime('now', '-1 day') "
        "ORDER BY a.created_at DESC LIMIT 10",
        (workspace,),
    ).fetchall()

    # Due nudges (design §4.1: the briefing surfaces what is due). A nudge whose
    # source is 'ingested' is externally authored → its message is delimiter-
    # wrapped before it reaches the agent's eyes.
    due_nudge_rows = conn.execute(
        "SELECT id, task_id, kind, message, source, due_at, state FROM nudges "
        "WHERE workspace_id = ? AND state = 'pending' AND due_at IS NOT NULL "
        "AND due_at <= datetime('now') "
        "ORDER BY due_at ASC, id ASC LIMIT 20",
        (workspace,),
    ).fetchall()
    due_nudges = []
    for r in due_nudge_rows:
        nudge = dict(r)
        provenance = "remote" if nudge.get("source") == "ingested" else "local"
        nudge["message"] = wrap_remote_field(nudge.get("message"), provenance)
        due_nudges.append(nudge)

    conflict_rows = conn.execute(
        "SELECT ss.id, ss.source, ss.remote_id, ss.status, ss.conflict_detail FROM sync_state ss "
        "WHERE ss.workspace_id = ? AND ss.status = 'conflict' "
        "ORDER BY ss.id ASC",
        (workspace,),
    ).fetchall()
    unresolved_conflicts = []
    for r in conflict_rows:
        conflict = dict(r)
        # conflict_detail mirrors externally-authored remote sync state → wrap.
        conflict["conflict_detail"] = wrap_remote_field(
            conflict.get("conflict_detail"), "remote"
        )
        unresolved_conflicts.append(conflict)

    last_session = conn.execute(
        "SELECT summary, ended_at FROM sessions WHERE workspace_id = ? "
        "AND ended_at IS NOT NULL ORDER BY id DESC LIMIT 1",
        (workspace,),
    ).fetchone()

    return {
        "workspace": workspace,
        "active_tasks": [dict(t) for t in active_tasks],
        "recent_actions": [dict(a) for a in recent_actions],
        "due_nudges": due_nudges,
        "unresolved_conflicts": unresolved_conflicts,
        "last_session_summary": dict(last_session) if last_session else None,
    }


def start_session(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """Write a session row, then return the briefing snapshot (thin WP-5 shim).

    Back-compat shim: it WRITES a ``sessions`` row (the side effect the existing
    pa agent protocol + agents/pa.md STATELESS-MODE fallback rely on), then
    delegates the read composition to the pure ``get_briefing_snapshot`` and
    returns its payload augmented with the new ``session_id``. The observable
    snapshot shape the characterization suite pins is preserved; the read logic
    lives in exactly one place.
    """
    workspace = params.get("workspace", ws_id)
    tool = params.get("tool", "claude-cli")

    with _with_tx(conn) as c:
        cur = c.execute(
            "INSERT INTO sessions (workspace_id, tool) VALUES (?, ?)",
            (workspace, tool),
        )
        session_id = cur.lastrowid

    snapshot = get_briefing_snapshot(conn, ws_id, params)
    return {"session_id": session_id, **snapshot}


def end_session(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    session_id = params["session_id"]
    summary = params.get("summary", "")

    with _with_tx(conn) as c:
        c.execute(
            "UPDATE sessions SET ended_at = ?, summary = ? WHERE id = ?",
            (now_iso(), summary, session_id),
        )
    return {"session_id": session_id, "ended_at": now_iso()}


# ---------------------------------------------------------------------------
# Nudge lifecycle (M0b / component nudge-lifecycle, owner WP-3)
# ---------------------------------------------------------------------------
#
# The nudge engine the routine-engine (WP-1) composer calls. It owns:
#   * nudge_create        — write a 'pending' nudges row (inside _with_tx).
#   * nudge_mark_shown /  — lifecycle transitions
#     nudge_ack /
#     nudge_snooze /
#     nudge_dismiss
#   * nudge_drain         — the in-composer DRAIN (NO daemon): promote nudges
#                           that are due (due_at<=now) or whose snooze has elapsed
#                           (snooze_until<=now) AND are still actionable
#                           (state IN (pending,snoozed)) to 'shown'. Not-yet-due
#                           nudges are left untouched (T-NU-1).
#
# 3x-snooze escalation (design §4.1): a nudge that has been snoozed >=3 times
# carries an escalated urgency class so a repeatedly-deferred item surfaces
# LOUDER. We never mutate the nudges-table shape to add an "urgency" column
# (M0a table is frozen); escalation is a DERIVED classification computed at
# drain time from snooze_count and surfaced in the drained result.
#
# Reads/writes ONLY the M0a `nudges` table (shape unchanged). stdlib only.

# The legal nudge states (mirror the nudges.state CHECK constraint).
NUDGE_STATES = ("pending", "shown", "snoozed", "acked", "dismissed")
# The legal nudge kinds (mirror the nudges.kind CHECK constraint).
NUDGE_KINDS = ("stale_task", "due", "overdue_delegation", "blocker_aging", "followup")
# The legal nudge sources (mirror the nudges.source CHECK constraint).
NUDGE_SOURCES = ("manual", "routine", "ingested")

# Snooze count at/above which a nudge escalates its urgency class (design §4.1:
# "a nudge reaching its 3rd snooze escalates").
SNOOZE_ESCALATION_THRESHOLD = 3


def nudge_urgency_class(snooze_count: int) -> str:
    """DERIVE the urgency class of a nudge from its snooze_count (PURE).

    A nudge that has been deferred SNOOZE_ESCALATION_THRESHOLD (3) or more times
    is ``escalated`` — it has been repeatedly pushed away and must surface
    louder. Below the threshold it is ``normal``. This is a derived
    classification, NOT a stored column (the M0a nudges-table shape is frozen).
    """
    try:
        n = int(snooze_count or 0)
    except (TypeError, ValueError):
        n = 0
    return "escalated" if n >= SNOOZE_ESCALATION_THRESHOLD else "normal"


def nudge_create(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """Create a 'pending' nudges row inside _with_tx (M0b / nudge-lifecycle).

    Params (the nudge_spec the stdio adapter validates upstream):
      * message       (required) — the nudge text. A `subject` param, if present,
                       is PREPENDED to the message ("subject — message"); the M0a
                       nudges table has NO subject column and its shape is frozen.
      * due_at        (optional) — ISO timestamp when the nudge becomes due.
      * kind          (optional) — one of NUDGE_KINDS; re-checked here (the table
                       CHECK constraint would otherwise raise a raw sqlite error).
      * task_id       (optional) — associated task row.
      * delegation_id (optional) — associated delegation row.
      * source        (optional, default 'manual') — one of NUDGE_SOURCES.

    The state always defaults to 'pending' and snooze_count to 0 — a fresh nudge
    is never pre-shown or pre-snoozed.
    """
    workspace = params.get("workspace", ws_id)
    message = params.get("message")
    if message is None or not isinstance(message, str):
        raise ValidationError("nudge_create: 'message' is required and must be a string")
    subject = params.get("subject")
    if subject:
        # No subject column on the frozen M0a table — fold it into the message.
        message = f"{subject} — {message}"

    kind = params.get("kind")
    if kind is not None and kind not in NUDGE_KINDS:
        raise ValidationError(
            f"nudge_create: kind {kind!r} not in allowed {NUDGE_KINDS} (fail-closed)"
        )

    source = params.get("source", "manual")
    if source not in NUDGE_SOURCES:
        raise ValidationError(
            f"nudge_create: source {source!r} not in allowed {NUDGE_SOURCES} (fail-closed)"
        )

    due_at = params.get("due_at")
    task_id = params.get("task_id")
    delegation_id = params.get("delegation_id")

    with _with_tx(conn) as c:
        cur = c.execute(
            """INSERT INTO nudges
                 (workspace_id, task_id, delegation_id, kind, message, source,
                  due_at, snooze_until, snooze_count, state)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, 'pending')""",
            (workspace, task_id, delegation_id, kind, message, source, due_at),
        )
        nudge_id = cur.lastrowid

    return {
        "id": nudge_id,
        "state": "pending",
        "kind": kind,
        "due_at": due_at,
        "snooze_count": 0,
        "urgency_class": nudge_urgency_class(0),
        "created_at": now_iso(),
    }


def _nudge_row(conn: sqlite3.Connection, workspace: str, nudge_id) -> sqlite3.Row:
    """Fetch a nudge row scoped to the workspace, or raise NotFoundError."""
    row = conn.execute(
        "SELECT * FROM nudges WHERE id = ? AND workspace_id = ?",
        (nudge_id, workspace),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"nudge {nudge_id!r} not found in workspace")
    return row


def _nudge_set_state(conn: sqlite3.Connection, ws_id: str, params: dict,
                     new_state: str, *, bump_snooze: bool = False) -> dict:
    """Shared lifecycle transition: move a nudge to ``new_state`` atomically.

    When ``bump_snooze`` is True (the snooze transition) it ALSO sets
    snooze_until and increments snooze_count in the SAME _with_tx, so a
    repeatedly-snoozed nudge accumulates its count and a future drain can
    escalate it (T-NU-1).
    """
    workspace = params.get("workspace", ws_id)
    nudge_id = params.get("id")
    if nudge_id is None:
        raise ValidationError(f"nudge transition to {new_state!r}: 'id' is required")

    with _with_tx(conn) as c:
        # Verify existence inside the tx so a missing id rolls back as a no-op.
        row = c.execute(
            "SELECT id, snooze_count FROM nudges WHERE id = ? AND workspace_id = ?",
            (nudge_id, workspace),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"nudge {nudge_id!r} not found in workspace")

        if bump_snooze:
            snooze_until = params.get("snooze_until")
            if snooze_until is None:
                raise ValidationError("nudge_snooze: 'snooze_until' is required")
            c.execute(
                "UPDATE nudges SET state = ?, snooze_until = ?, "
                "snooze_count = snooze_count + 1 WHERE id = ? AND workspace_id = ?",
                (new_state, snooze_until, nudge_id, workspace),
            )
        else:
            c.execute(
                "UPDATE nudges SET state = ? WHERE id = ? AND workspace_id = ?",
                (new_state, nudge_id, workspace),
            )

    updated = _nudge_row(conn, workspace, nudge_id)
    return {
        "id": updated["id"],
        "state": updated["state"],
        "snooze_until": updated["snooze_until"],
        "snooze_count": updated["snooze_count"],
        "urgency_class": nudge_urgency_class(updated["snooze_count"]),
    }


def nudge_mark_shown(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """Transition a nudge to 'shown' (the composer surfaced it)."""
    return _nudge_set_state(conn, ws_id, params, "shown")


def nudge_ack(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """Transition a nudge to 'acked' (the user acknowledged it)."""
    return _nudge_set_state(conn, ws_id, params, "acked")


def nudge_dismiss(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """Transition a nudge to 'dismissed' (the user dismissed it)."""
    return _nudge_set_state(conn, ws_id, params, "dismissed")


def nudge_snooze(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """Transition a nudge to 'snoozed', set snooze_until, increment snooze_count.

    The 3rd snooze (snooze_count reaching SNOOZE_ESCALATION_THRESHOLD) flips the
    DERIVED urgency_class to 'escalated' (surfaced in the return + at drain time).
    """
    return _nudge_set_state(conn, ws_id, params, "snoozed", bump_snooze=True)


def nudge_drain(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """The in-composer DRAIN — no daemon (M0b / nudge-lifecycle, T-NU-1).

    Promote to 'shown' every nudge that is BOTH:
      * actionable          — state IN ('pending', 'snoozed'); and
      * due or un-snoozed   — due_at <= now OR snooze_until <= now.

    Not-yet-due nudges (due_at in the future AND snooze_until in the future or
    NULL) are left UNTOUCHED. The single time reference is captured once
    (`now`) so the read-which-to-promote and the write are consistent within
    one drain. A nudge whose snooze_count >= SNOOZE_ESCALATION_THRESHOLD is
    reported with an 'escalated' urgency_class so a repeatedly-deferred item
    surfaces louder.

    Returns a summary: the list of promoted nudges (each with its derived
    urgency_class) and a count of how many escalated.
    """
    workspace = params.get("workspace", ws_id)
    # Allow an explicit `now` override for deterministic testing; default to UTC now.
    now = params.get("now") or now_iso()

    # Select the nudges to promote OUTSIDE the write so we can report exactly
    # which ones moved (and their derived urgency) — the SQL predicate mirrors
    # the success criterion verbatim.
    select_sql = (
        "SELECT id, kind, message, source, due_at, snooze_until, snooze_count "
        "FROM nudges "
        "WHERE workspace_id = ? "
        "  AND state IN ('pending', 'snoozed') "
        "  AND ( (due_at IS NOT NULL AND due_at <= ?) "
        "        OR (snooze_until IS NOT NULL AND snooze_until <= ?) ) "
        "ORDER BY id ASC"
    )
    to_promote = conn.execute(select_sql, (workspace, now, now)).fetchall()

    promoted = []
    escalated_count = 0
    with _with_tx(conn) as c:
        for r in to_promote:
            c.execute(
                "UPDATE nudges SET state = 'shown' WHERE id = ? AND workspace_id = ?",
                (r["id"], workspace),
            )
            urgency = nudge_urgency_class(r["snooze_count"])
            if urgency == "escalated":
                escalated_count += 1
            # Externally-authored nudge messages (source 'ingested') are
            # delimiter-wrapped before they reach the agent's eyes (security
            # floor L1), exactly as get_briefing_snapshot does.
            provenance = "remote" if r["source"] == "ingested" else "local"
            promoted.append({
                "id": r["id"],
                "kind": r["kind"],
                "message": wrap_remote_field(r["message"], provenance),
                "due_at": r["due_at"],
                "snooze_count": r["snooze_count"],
                "urgency_class": urgency,
            })

    return {
        "promoted": promoted,
        "promoted_count": len(promoted),
        "escalated_count": escalated_count,
        "drained_at": now,
    }


# ---------------------------------------------------------------------------
# role-lens (M0b / WP-4) — role_profile reweighting as an ordering-only LENS
# ---------------------------------------------------------------------------
#
# routine-engine (WP-1) produces a pre-weight ranked BriefItem list. role-lens
# REORDERS it per the workspace role_profile; it NEVER filters. Two invariants
# (signed contract map success_criteria):
#
#   * Membership is invariant: set(reweighted) == set(input) (T-RL-1). The lens
#     changes ORDER only — it is never a filtered subset.
#   * A critical blocker is never demoted to invisibility: it stays above the
#     fold or reachable via the mandatory [+N more]. Because the lens never
#     drops anything, "reachable" is guaranteed structurally; the urgency
#     taxonomy keeps a critical item near the top regardless of the role
#     category weight (urgency DOMINATES category weight — see the sort key).
#
# The function is PURE: ``reweight_brief_items(brief_items, role_profile)`` takes
# no conn, performs no DB writes, and does not mutate its inputs. It returns the
# SAME item objects, reordered (so delimiter-wrapped remote fields surfaced by
# the M0a snapshot path pass through verbatim — the lens never unwraps).
#
# stdlib only.

# The urgency taxonomy (design §4.1): CONFLICT is loudest, FYI is quietest.
# Lower rank == higher priority == sorts earlier.
URGENCY_RANK = {
    "CONFLICT": 0,
    "OVERDUE_NUDGE": 1,
    "BLOCKER": 2,
    "DUE_TODAY": 3,
    "DELEGATION_FOLLOWUP": 4,
    "IN_FLIGHT": 5,
    "FYI": 6,
}
# An urgency class not in the taxonomy sorts AFTER every known class (defensive:
# an opaque/garbage urgency never crashes the sort and never jumps the queue).
URGENCY_RANK_DEFAULT = 99

# methodology -> week-review framing bucket. An ORDERING signal only: the lens
# uses the framing to pick how a week review is framed (Scrum=velocity vs
# Kanban=cycle-time); it is NEVER executed or interpreted as a command.
_FRAMING_BY_METHODOLOGY = {
    "scrum": "velocity",
    "kanban": "cycle-time",
}


def week_review_framing(methodology) -> str:
    """Map a role_profile.methodology to a week-review framing bucket (PURE).

    Returns 'velocity' for Scrum, 'cycle-time' for Kanban, else 'unknown'.
    Matching is case-insensitive and TOKEN-based on the leading word, so a
    remote-authored / injection-looking methodology string ("Scrum; DROP TABLE
    ...; --") still maps to its leading framing token and is NEVER executed.
    Non-string input -> 'unknown'.
    """
    if not isinstance(methodology, str):
        return "unknown"
    # Take the leading alphabetic token only (defensive against trailing junk).
    token = ""
    for ch in methodology.strip():
        if ch.isalpha():
            token += ch
        else:
            break
    return _FRAMING_BY_METHODOLOGY.get(token.lower(), "unknown")


def _category_weight(role_profile, category) -> float:
    """The reweight multiplier for a BriefItem category under the role_profile.

    Defensive: a missing/None profile, missing category_weights, an unlisted
    category, or a non-numeric / negative weight all fall back to the neutral
    weight 1.0 (identity on the category axis). Never raises — the lens is total.
    """
    if not isinstance(role_profile, dict):
        return 1.0
    weights = role_profile.get("category_weights")
    if not isinstance(weights, dict):
        return 1.0
    raw = weights.get(category)
    if isinstance(raw, bool):  # bool is an int subclass — reject it explicitly
        return 1.0
    if not isinstance(raw, (int, float)):
        return 1.0
    if raw != raw:  # NaN
        return 1.0
    return float(raw) if raw >= 0.0 else 1.0


def _due_sort_key(due_at):
    """ISO due_at -> (has_due_flag, due_at) so a dated item sorts BEFORE an
    undated one at equal urgency/weight. Missing/None due_at -> sorts last."""
    if isinstance(due_at, str) and due_at:
        return (0, due_at)
    return (1, "")


def reweight_brief_items(brief_items, role_profile):
    """Reorder a pre-weight ranked BriefItem list per the role_profile (PURE).

    An ordering-only LENS — the returned list contains the SAME item objects,
    reordered; nothing is filtered, dropped, or duplicated (T-RL-1: membership
    is invariant). The sort key, in priority order:

      1. urgency taxonomy rank (URGENCY_RANK) — DOMINANT; a role category weight
         can NEVER pull a low-urgency item above a high-urgency one. This is what
         guarantees a critical blocker is never demoted to invisibility.
      2. role category weight, DESCENDING (higher-weighted category earlier) —
         the actual reweighting signal, applied only WITHIN an equal urgency.
      3. due_at ASCENDING (dated before undated; sooner before later).
      4. age_seconds DESCENDING (older surfaces first).
      5. order_index ASCENDING — the routine-engine pre-weight rank, the final
         STABLE tiebreak so the output is deterministic.

    methodology is consumed via ``week_review_framing`` as an ordering signal
    only (callers may read it; it never gates membership and is never executed).

    Args:
      brief_items: the pre-weight ranked list of opaque BriefItem dicts.
      role_profile: the role_profile row (dict) or None.

    Returns:
      a NEW list of the same item objects, reordered. Inputs are not mutated.
    """
    if not brief_items:
        return []

    def key(item):
        urgency = item.get("urgency")
        urank = URGENCY_RANK.get(urgency, URGENCY_RANK_DEFAULT)
        weight = _category_weight(role_profile, item.get("category"))
        has_due, due = _due_sort_key(item.get("due_at"))
        try:
            age = int(item.get("age_seconds") or 0)
        except (TypeError, ValueError):
            age = 0
        try:
            oidx = int(item.get("order_index") or 0)
        except (TypeError, ValueError):
            oidx = 0
        # Negate weight (higher weight earlier) and age (older earlier). Python
        # sort is stable, so equal keys keep input order, but we add order_index
        # last for an explicit, position-independent deterministic tiebreak.
        return (urank, -weight, has_due, due, -age, oidx)

    # New list, same objects — never mutate the input, never copy the items
    # (so wrapped remote fields pass through verbatim).
    return sorted(brief_items, key=key)


# ---------------------------------------------------------------------------
# routine-engine (M0b / WP-1) — pa_brief composer + ranker + fold
# ---------------------------------------------------------------------------
#
# The HUB component (design §4.1). pa_brief composes the catch-up briefing:
#
#   1. CONSUME the M0a pure read surface get_briefing_snapshot (active_tasks,
#      recent_actions, due_nudges, unresolved_conflicts, last_session_summary)
#      — the `pa_core_briefing_snapshot_read` in_process integration point.
#      Remote-authored fields in that payload are ALREADY delimiter-wrapped by
#      the snapshot path (security floor L1); pa_brief NEVER unwraps them.
#   2. READ the delegations + blockers tables DIRECTLY via the same conn — the
#      `pa_core_delegation_blocker_read` integration point. NOTE (carried from
#      the signed map + verified at pa_core.py get_briefing_snapshot): the M0a
#      snapshot does NOT read delegations/blockers, so routine-engine reads them
#      itself. blockers.description is locally-authored (user's own notes) so it
#      is NOT remote-wrapped; only externally-authored fields are wrapped.
#   3. DRAIN nudges via nudge_drain (WP-3, nudge-lifecycle) — the in-composer
#      drain (no daemon). Drained nudges are already wrap-preserved by WP-3.
#   4. BUILD a typed BriefItem list, one per surfaced concern, each tagged with
#      an urgency class from the taxonomy (URGENCY_RANK, WP-4).
#   5. RANK strictly by the urgency taxonomy (CONFLICT first … FYI last) with a
#      due/age tiebreak, then REWEIGHT ordering via reweight_brief_items (WP-4,
#      role-lens) — an ordering-only LENS that never filters.
#   6. FOLD to exactly 5 BriefItems above the fold + a MANDATORY [+N more]
#      affordance for the remainder. NO item is EVER dropped to zero visibility
#      (T-RE-1): the overflow is always reachable.
#   7. RENDER the ~12-line terminal briefing text.
#
# pa_brief reads via get_briefing_snapshot and writes ONLY through nudge_drain
# (the drain promotes due nudges to 'shown' — that is the WP-3 write path,
# already inside its own _with_tx). pa_brief itself opens no transaction.
#
# stdlib only.

# How many BriefItems show above the fold before the [+N more] affordance kicks
# in (design §4.1: "5 lines above the fold").
BRIEF_FOLD_SIZE = 5

# The urgency class each BriefItem source maps to (mirrors URGENCY_RANK keys).
# A snapshot conflict -> CONFLICT; a drained escalated nudge -> OVERDUE_NUDGE;
# a critical/high blocker -> BLOCKER; a today-due task -> DUE_TODAY; an open
# owed/chased delegation -> DELEGATION_FOLLOWUP; an in-progress task ->
# IN_FLIGHT; everything else -> FYI.


def _today_iso_date(now=None):
    """The current UTC calendar date as 'YYYY-MM-DD' (for DUE_TODAY matching).

    A `now` ISO override (testing) is honored; only the leading date component
    is used so a 'YYYY-MM-DDTHH:MM:SS' override and a bare date both work.
    """
    ref = now or now_iso()
    return ref[:10] if isinstance(ref, str) and len(ref) >= 10 else now_iso()[:10]


def _is_due_today(due_at, today_date):
    """True iff an ISO due_at falls on today's calendar date (date-prefix match)."""
    return isinstance(due_at, str) and len(due_at) >= 10 and due_at[:10] == today_date


def _brief_item(item_id, urgency, title, *, detail=None, due_at=None,
                age_seconds=0, order_index=0, severity=None, urgency_class=None,
                source_kind=None):
    """Build a typed BriefItem dict (uniform shape for the ranker + renderer).

    `category` is set equal to `urgency` so role-lens category_weights can target
    an urgency band directly; callers may override category later if needed. The
    `detail` value is passed through VERBATIM — when it is a delimiter-wrapped
    remote field the wrap is preserved end-to-end (pa_brief never unwraps).
    """
    return {
        "id": item_id,
        "urgency": urgency,
        "category": urgency,
        "title": title,
        "detail": detail,
        "due_at": due_at,
        "age_seconds": age_seconds,
        "order_index": order_index,
        "severity": severity,
        "urgency_class": urgency_class,
        "source_kind": source_kind,
    }


def build_brief_items(conn: sqlite3.Connection, ws_id: str, params: dict) -> list:
    """Build the pre-weight ranked BriefItem list for a workspace (the ranker).

    Reads the M0a snapshot (in_process), the delegations/blockers tables
    (filesystem_io, directly via the same conn), and the drained nudges, then
    emits one BriefItem per surfaced concern, ranked strictly by the urgency
    taxonomy (URGENCY_RANK: CONFLICT < OVERDUE_NUDGE < BLOCKER < DUE_TODAY <
    DELEGATION_FOLLOWUP < IN_FLIGHT < FYI) with a due/age tiebreak.

    Remote-authored fields surfaced from the snapshot/drain (conflict_detail,
    ingested nudge messages) arrive ALREADY delimiter-wrapped and pass through
    verbatim — this builder never unwraps them.
    """
    workspace = params.get("workspace", ws_id)
    now = params.get("now")  # optional ISO override for deterministic tests
    today_date = _today_iso_date(now)

    items = []

    # (1) Snapshot — the M0a in_process read surface. Remote fields pre-wrapped.
    snap_params = {"workspace": workspace}
    snapshot = get_briefing_snapshot(conn, ws_id, snap_params)

    # (1a) Unresolved sync conflicts -> CONFLICT (loudest). conflict_detail is
    # already remote-wrapped by the snapshot path; pass through verbatim.
    for cf in snapshot.get("unresolved_conflicts", []) or []:
        items.append(_brief_item(
            f"conflict:{cf.get('id')}",
            "CONFLICT",
            f"Sync conflict: {cf.get('source')} {cf.get('remote_id')}",
            detail=cf.get("conflict_detail"),
            source_kind="conflict",
        ))

    # (3) Drain nudges via nudge-lifecycle (WP-3). The drain promotes due/un-
    # snoozed nudges to 'shown' and returns each with its derived urgency_class
    # (escalated when snooze_count >= 3) and a wrap-preserved message.
    drain = nudge_drain(conn, ws_id, {"workspace": workspace, "now": now} if now else {"workspace": workspace})
    for nd in drain.get("promoted", []) or []:
        # A repeatedly-deferred (escalated) nudge surfaces LOUDER as an
        # OVERDUE_NUDGE; an ordinary drained nudge is a DUE_TODAY-class reminder.
        escalated = nd.get("urgency_class") == "escalated"
        urgency = "OVERDUE_NUDGE" if escalated else "DUE_TODAY"
        items.append(_brief_item(
            f"nudge:{nd.get('id')}",
            urgency,
            "Overdue nudge (escalated)" if escalated else "Due nudge",
            detail=nd.get("message"),  # already wrap-preserved by the drain
            due_at=nd.get("due_at"),
            urgency_class=nd.get("urgency_class"),
            source_kind="nudge",
        ))

    # (2) blockers — read DIRECTLY via the same conn (pa_core_delegation_blocker_read).
    # blockers.description is the user's own note (local) -> NOT remote-wrapped.
    blocker_rows = conn.execute(
        "SELECT id, description, severity, status, raised_at FROM blockers "
        "WHERE workspace_id = ? AND status = 'active' "
        "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "  WHEN 'medium' THEN 2 ELSE 3 END, id ASC",
        (workspace,),
    ).fetchall()
    for b in blocker_rows:
        items.append(_brief_item(
            f"blocker:{b['id']}",
            "BLOCKER",
            b["description"],
            severity=b["severity"],
            source_kind="blocker",
        ))

    # (4) tasks. The M0a snapshot supplies the active-task LIST (the
    # pa_core_briefing_snapshot_read in_process integration point), but its
    # active_tasks projection omits the due_at column. due-today classification
    # needs due_at, so we resolve due_at per active task directly via the same
    # conn (a thin filesystem_io read keyed by the snapshot's task ids — the
    # snapshot remains the authority for WHICH tasks are active).
    #
    #   due-today          -> DUE_TODAY
    #   in-progress        -> IN_FLIGHT  ('executing' is the M0a-kernel
    #                                      "in progress" status)
    #   everything else    -> FYI
    #
    # Task titles are locally authored (never remote-wrapped).
    active_tasks = snapshot.get("active_tasks", []) or []
    task_ids = [t.get("id") for t in active_tasks if t.get("id") is not None]
    due_by_id = {}
    if task_ids:
        placeholders = ",".join("?" for _ in task_ids)
        for row in conn.execute(
            "SELECT id, due_at FROM tasks WHERE workspace_id = ? "
            f"AND id IN ({placeholders})",
            (workspace, *task_ids),
        ).fetchall():
            due_by_id[row["id"]] = row["due_at"]
    for t in active_tasks:
        due = due_by_id.get(t.get("id"))
        if _is_due_today(due, today_date):
            urgency = "DUE_TODAY"
        elif t.get("status") in ("executing", "in_progress"):
            urgency = "IN_FLIGHT"
        else:
            urgency = "FYI"
        items.append(_brief_item(
            f"task:{t.get('id')}",
            urgency,
            t.get("title"),
            due_at=due,
            source_kind="task",
        ))

    # (2b) delegations — read DIRECTLY via the same conn. An open/chased
    # delegation is a DELEGATION_FOLLOWUP. expected_by drives the due tiebreak.
    delegation_rows = conn.execute(
        "SELECT id, direction, status, expected_by FROM delegations "
        "WHERE workspace_id = ? AND status IN ('open', 'chased') "
        "ORDER BY (expected_by IS NULL), expected_by ASC, id ASC",
        (workspace,),
    ).fetchall()
    for d in delegation_rows:
        label = "owed to me" if d["direction"] == "owed_to_me" else "delegated out"
        items.append(_brief_item(
            f"delegation:{d['id']}",
            "DELEGATION_FOLLOWUP",
            f"Follow up ({label})",
            due_at=d["expected_by"],
            source_kind="delegation",
        ))

    # Assign a stable pre-weight order_index per the urgency taxonomy + due/age
    # tiebreak, so the role-lens reweight has a deterministic base order and the
    # final STABLE tiebreak (order_index) is meaningful.
    def _base_key(it):
        urank = URGENCY_RANK.get(it.get("urgency"), URGENCY_RANK_DEFAULT)
        has_due, due = _due_sort_key(it.get("due_at"))
        try:
            age = int(it.get("age_seconds") or 0)
        except (TypeError, ValueError):
            age = 0
        return (urank, has_due, due, -age, str(it.get("id")))

    ranked = sorted(items, key=_base_key)
    for idx, it in enumerate(ranked):
        it["order_index"] = idx
    return ranked


def fold_brief_items(brief_items, fold_size: int = BRIEF_FOLD_SIZE) -> dict:
    """Split a ranked BriefItem list into above-the-fold + a MANDATORY overflow.

    Returns a dict with:
      * above_fold        — at most ``fold_size`` items (the top of the list);
      * overflow          — the remainder (possibly empty);
      * overflow_count    — len(overflow);
      * overflow_affordance — "[+N more]" when overflow_count > 0 else "" .

    INVARIANT (T-RE-1): NO item is ever dropped — above_fold + overflow is a
    partition of the input (same membership, same order). The [+N more]
    affordance guarantees the overflow stays reachable; it is never hidden to
    zero visibility.
    """
    items = list(brief_items or [])
    n = max(0, int(fold_size))
    above = items[:n]
    overflow = items[n:]
    count = len(overflow)
    return {
        "above_fold": above,
        "overflow": overflow,
        "overflow_count": count,
        "overflow_affordance": f"[+{count} more]" if count > 0 else "",
    }


def _render_brief_text(workspace, fold: dict) -> str:
    """Render the ~12-line terminal briefing text from a folded BriefItem set.

    A header line, up to 5 numbered above-the-fold lines, and a trailing
    [+N more] affordance line when there is overflow. Each line is a short,
    urgency-tagged summary. Remote-authored detail (already delimiter-wrapped)
    is surfaced verbatim — NEVER unwrapped.
    """
    lines = [f"AMY briefing — {workspace}"]
    above = fold.get("above_fold", [])
    if not above:
        lines.append("(nothing pressing right now)")
    for i, it in enumerate(above, start=1):
        urgency = it.get("urgency", "FYI")
        if urgency == "BLOCKER" and it.get("severity"):
            tag = f"BLOCKER {it['severity']}"
        elif urgency == "OVERDUE_NUDGE":
            tag = "OVERDUE!"
        elif urgency == "DUE_TODAY":
            tag = "DUE TODAY"
        else:
            tag = urgency
        title = it.get("title") or ""
        lines.append(f"{i}. [{tag}] {title}")
    if fold.get("overflow_count", 0) > 0:
        lines.append(fold["overflow_affordance"])
    return "\n".join(lines)


def pa_brief(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """Compose the catch-up briefing — the routine-engine HUB (M0b / WP-1).

    Pipeline: build_brief_items (consume the M0a snapshot + read
    delegations/blockers directly + drain nudges, rank by the urgency taxonomy)
    -> reweight_brief_items (role-lens ordering-only reweight via the workspace
    role_profile) -> fold to 5-above-the-fold + a MANDATORY [+N more] ->
    render the ~12-line terminal text.

    The composed output is OPAQUE (brief_output): the ranked item list, the fold
    split, and the rendered text. Remote-authored fields stay delimiter-wrapped
    end-to-end (security floor L1) — pa_brief never unwraps.

    Returns:
      dict with keys ``workspace``, ``items`` (the full reweighted ranked list),
      ``above_fold``, ``overflow``, ``overflow_count``, ``overflow_affordance``,
      ``rendered_text``, and ``week_review_framing`` (an ordering signal from the
      role_profile methodology; never executed).
    """
    workspace = params.get("workspace", ws_id)

    # Pre-weight ranked list (ranker, consuming the snapshot + delegations/
    # blockers + drained nudges).
    ranked = build_brief_items(conn, ws_id, params)

    # role-lens reweight (ordering-only; never filters — membership invariant).
    role_profile = _read_role_profile(conn, workspace)
    reweighted = reweight_brief_items(ranked, role_profile)

    # Fold to 5 above the fold + a MANDATORY [+N more] (T-RE-1: nothing dropped).
    fold = fold_brief_items(reweighted, BRIEF_FOLD_SIZE)

    rendered = _render_brief_text(workspace, fold)
    framing = week_review_framing(role_profile.get("methodology")) if isinstance(role_profile, dict) else "unknown"

    return {
        "workspace": workspace,
        "items": reweighted,
        "above_fold": fold["above_fold"],
        "overflow": fold["overflow"],
        "overflow_count": fold["overflow_count"],
        "overflow_affordance": fold["overflow_affordance"],
        "rendered_text": rendered,
        "week_review_framing": framing,
    }


# ---------------------------------------------------------------------------
# review-scopes (M0b / review-scopes, owner WP-2) — pa_review(scope)
# ---------------------------------------------------------------------------
#
# pa_review windows + groups the SHARED routine-engine ranker output per a closed
# review scope. It is a CALLER of routine-engine (callees: [routine-engine]): it
# REUSES build_brief_items (WP-1's ranker) verbatim and NEVER forks the urgency
# taxonomy. The only review-specific logic is:
#
#   1. a per-scope TIME WINDOW (today / tomorrow / this-week / this-month) that
#      EXCLUDES every item whose due_at falls outside it (and every undated item —
#      a windowed review is about what is DUE in the window);
#   2. a per-scope GROUPING KEY (today=urgency, tomorrow=urgency, week=workstream,
#      month=milestone) that partitions the already-ranked, already-windowed list
#      into groups WITHOUT re-ranking — the shared ranker order is preserved as a
#      STABLE partition within each group, and groups themselves lead with the
#      loudest (highest-ranked) member.
#
# workstream is derived from a task's first tag; milestone from its
# planning_period. Both are resolved over the SAME conn (the
# pa_core_task_window_read in_process integration point) keyed by the task ids the
# ranker already surfaced — the ranker remains the authority for WHICH items are
# active; this read only attaches the grouping dimensions + due_at.
#
# Remote-authored fields (ingested nudge messages, conflict_detail) arrive ALREADY
# delimiter-wrapped from the ranker and pass through verbatim — pa_review never
# unwraps. stdlib only (json / sqlite3 / datetime).

# The closed review-scope enum + each scope's grouping key.
REVIEW_SCOPES = ("today", "tomorrow", "week", "month")
_GROUPING_KEY_BY_SCOPE = {
    "today": "urgency",
    "tomorrow": "urgency",
    "week": "workstream",
    "month": "milestone",
}
# How a missing workstream / milestone is bucketed.
REVIEW_UNASSIGNED = "unassigned"


def _scope_window(scope: str, now=None):
    """The [start_date, end_date] inclusive calendar window for a review scope.

    Returns (start_date, end_date) as date objects. The window is matched against
    a due_at by DATE prefix (the ranker's due_at values are ISO strings), so the
    bounds are whole calendar days:

      today    -> [today, today]
      tomorrow -> [tomorrow, tomorrow]
      week     -> the ISO week (Monday..Sunday) containing today
      month    -> [first day of month, last day of month]

    `now` is an optional ISO override for deterministic tests (only the leading
    date component is used). An unknown scope raises ValidationError (defense in
    depth — the pa-server inputSchema also rejects it pre-dispatch)."""
    if scope not in REVIEW_SCOPES:
        raise ValidationError(
            f"pa_review: 'scope' must be one of {list(REVIEW_SCOPES)}, got {scope!r}"
        )
    today_iso = _today_iso_date(now)
    today = date(int(today_iso[0:4]), int(today_iso[5:7]), int(today_iso[8:10]))
    if scope == "today":
        return today, today
    if scope == "tomorrow":
        nxt = today + timedelta(days=1)
        return nxt, nxt
    if scope == "week":
        # Monday-anchored ISO week. weekday(): Monday=0 .. Sunday=6.
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    # month
    start = today.replace(day=1)
    if start.month == 12:
        nxt_month_first = start.replace(year=start.year + 1, month=1)
    else:
        nxt_month_first = start.replace(month=start.month + 1)
    end = nxt_month_first - timedelta(days=1)
    return start, end


def _due_in_window(due_at, start_date, end_date) -> bool:
    """True iff an ISO due_at falls on a calendar date within [start, end].

    Undated (None / non-string / too-short) -> False: a windowed review only
    surfaces DATED items inside the window."""
    if not isinstance(due_at, str) or len(due_at) < 10:
        return False
    try:
        d = date(int(due_at[0:4]), int(due_at[5:7]), int(due_at[8:10]))
    except (ValueError, TypeError):
        return False
    return start_date <= d <= end_date


def _task_grouping_dims(conn: sqlite3.Connection, workspace: str, task_ids):
    """Read workstream + milestone (+ due_at) for a set of task ids over the same
    conn (the pa_core_task_window_read in_process integration point).

    workstream  := the task's first tag (tags is a JSON list column), else None.
    milestone   := the task's planning_period column, else None.

    Returns {task_id: {"workstream": str|None, "milestone": str|None,
    "due_at": str|None}}. Defensive: a malformed tags JSON / missing column never
    raises — the dimension simply falls back to None (-> the 'unassigned' bucket).
    The ranker stays the authority for WHICH tasks are active; this only attaches
    the grouping dimensions."""
    dims = {}
    ids = [t for t in (task_ids or []) if t is not None]
    if not ids:
        return dims
    placeholders = ",".join("?" for _ in ids)
    try:
        rows = conn.execute(
            f"SELECT id, tags, planning_period, due_at FROM tasks "
            f"WHERE workspace_id = ? AND id IN ({placeholders})",
            (workspace, *ids),
        ).fetchall()
    except sqlite3.Error:
        return dims
    for r in rows:
        workstream = None
        raw_tags = r["tags"] if "tags" in r.keys() else None
        if isinstance(raw_tags, str) and raw_tags:
            try:
                parsed = json.loads(raw_tags)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], str):
                    workstream = parsed[0]
            except (ValueError, TypeError):
                workstream = None
        dims[r["id"]] = {
            "workstream": workstream,
            "milestone": r["planning_period"] if "planning_period" in r.keys() else None,
            "due_at": r["due_at"] if "due_at" in r.keys() else None,
        }
    return dims


def _item_task_id(item):
    """Recover the underlying task id from a BriefItem whose id is 'task:<id>'.

    Returns the integer/string task id, or None for non-task items (nudges,
    blockers, delegations, conflicts have no tasks-table row)."""
    iid = item.get("id")
    if isinstance(iid, str) and iid.startswith("task:"):
        raw = iid[len("task:"):]
        try:
            return int(raw)
        except (ValueError, TypeError):
            return raw
    return None


def _group_key_for_item(item, grouping_key, dims_by_task):
    """The group bucket key for a windowed BriefItem under the active grouping.

      urgency    -> the item's urgency band (every item has one).
      workstream -> the task's first tag, else 'unassigned' (non-task items, e.g.
                    a due nudge, have no workstream -> 'unassigned').
      milestone  -> the task's planning_period, else 'unassigned'.
    """
    if grouping_key == "urgency":
        return item.get("urgency") or "FYI"
    tid = _item_task_id(item)
    dim = dims_by_task.get(tid) if tid is not None else None
    if grouping_key == "workstream":
        ws = dim.get("workstream") if isinstance(dim, dict) else None
        return ws if isinstance(ws, str) and ws else REVIEW_UNASSIGNED
    # milestone
    ms = dim.get("milestone") if isinstance(dim, dict) else None
    return ms if isinstance(ms, str) and ms else REVIEW_UNASSIGNED


def _render_review_text(workspace, scope, groups) -> str:
    """Render a compact grouped review text (header + per-group numbered items).

    Remote-authored detail (already delimiter-wrapped) is surfaced via the item
    title verbatim — NEVER unwrapped. Mirrors _render_brief_text's urgency tags."""
    lines = [f"AMY review — {workspace} ({scope})"]
    if not groups:
        lines.append("(nothing in this window)")
        return "\n".join(lines)
    for g in groups:
        lines.append(f"## {g['key']}")
        for i, it in enumerate(g["items"], start=1):
            urgency = it.get("urgency", "FYI")
            if urgency == "BLOCKER" and it.get("severity"):
                tag = f"BLOCKER {it['severity']}"
            elif urgency == "OVERDUE_NUDGE":
                tag = "OVERDUE!"
            elif urgency == "DUE_TODAY":
                tag = "DUE TODAY"
            else:
                tag = urgency
            lines.append(f"{i}. [{tag}] {it.get('title') or ''}")
    return "\n".join(lines)


def pa_review(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    """Scope-windowed, grouped review over the SHARED routine-engine ranker (WP-2).

    pa_review(scope) for scope in {today, tomorrow, week, month}:

      * builds the ranked BriefItem list via build_brief_items (WP-1's ranker —
        REUSED, never forked; the urgency taxonomy is not duplicated);
      * EXCLUDES every item whose due_at falls outside the scope's time window
        (and every undated item — success criterion (a));
      * GROUPS the surviving items by the scope's grouping key (today=urgency,
        tomorrow=urgency, week=workstream, month=milestone) as a STABLE partition
        that preserves the shared ranker order WITHIN each group (success
        criterion (b)); groups lead with their loudest (highest-ranked) member.

    workstream/milestone are resolved over the same conn (pa_core_task_window_read,
    in_process). Remote-authored fields stay delimiter-wrapped end-to-end — the
    review never unwraps. Returns the OPAQUE review_output payload.

    Raises ValidationError when 'scope' is missing or not in the closed enum
    (defense in depth — the pa-server inputSchema also rejects it pre-dispatch).
    """
    workspace = params.get("workspace", ws_id)
    now = params.get("now")  # optional ISO override for deterministic tests
    scope = params.get("scope")
    if scope is None:
        raise ValidationError("pa_review: 'scope' is required")
    if scope not in REVIEW_SCOPES:
        raise ValidationError(
            f"pa_review: 'scope' must be one of {list(REVIEW_SCOPES)}, got {scope!r}"
        )

    grouping_key = _GROUPING_KEY_BY_SCOPE[scope]
    start_date, end_date = _scope_window(scope, now)

    # (1) Shared ranker — REUSE WP-1's build_brief_items verbatim (no fork).
    ranked = build_brief_items(conn, ws_id, {"workspace": workspace, "now": now} if now else {"workspace": workspace})

    # (2) Window filter — keep only items DUE inside the scope window. The ranker
    # global order is preserved (filter is order-stable).
    windowed = [it for it in ranked if _due_in_window(it.get("due_at"), start_date, end_date)]

    # (3) Resolve grouping dims for the surviving task items (pa_core_task_window_read).
    task_ids = [tid for tid in (_item_task_id(it) for it in windowed) if tid is not None]
    dims_by_task = _task_grouping_dims(conn, workspace, task_ids) if grouping_key != "urgency" else {}

    # (4) Stable partition into groups, preserving shared-ranker order within each
    # group, and ordering the groups by the rank position of their first member.
    group_items = {}
    group_order = []
    for it in windowed:  # windowed is already in shared-ranker order
        key = _group_key_for_item(it, grouping_key, dims_by_task)
        if key not in group_items:
            group_items[key] = []
            group_order.append(key)  # first appearance = loudest member's rank
        group_items[key].append(it)

    groups = [{"key": k, "items": group_items[k]} for k in group_order]

    rendered = _render_review_text(workspace, scope, groups)

    return {
        "scope": scope,
        "grouping_key": grouping_key,
        "workspace": workspace,
        "window": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "now": now,
        },
        "groups": groups,
        "item_count": len(windowed),
        "rendered_text": rendered,
    }


def _read_role_profile(conn: sqlite3.Connection, workspace: str):
    """Read the workspace role_profile row as a dict (or {} when absent).

    The M0a role_profile table has no category_weights column; the reweight
    signal lives in the (optional) role_profile config. We surface every row
    column plus, when present, a parsed category_weights from a JSON `config`
    convention is NOT assumed here — _category_weight defends against a missing
    category_weights key by falling back to the neutral 1.0 weight, so an absent
    profile yields the pure urgency-taxonomy order (identity on the lens).
    """
    try:
        row = conn.execute(
            "SELECT role_title, aims, responsibilities, methodology, "
            "reporting_lines, escalation_threshold, tone FROM role_profile "
            "WHERE workspace_id = ?",
            (workspace,),
        ).fetchone()
    except sqlite3.Error:
        return {}
    if row is None:
        return {}
    return dict(row)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(conn: sqlite3.Connection, ws_id: str, params: dict) -> list:
    workspace = params.get("workspace", ws_id)
    query = params["query"]
    params.get("mode", "keyword")  # semantic is a v2 feature; falls back to keyword
    limit = params.get("limit", 20)

    results = []

    task_rows = conn.execute(
        """SELECT t.id, t.title, snippet(tasks_fts, 1, '<b>', '</b>', '...', 32) as snippet, rank
           FROM tasks_fts
           JOIN tasks t ON t.id = tasks_fts.rowid
           WHERE tasks_fts MATCH ? AND t.workspace_id = ?
           ORDER BY rank
           LIMIT ?""",
        (query, workspace, limit),
    ).fetchall()

    for row in task_rows:
        results.append({
            "type": "task",
            "id": row["id"],
            "title": row["title"],
            "snippet": row["snippet"],
            "relevance_score": abs(row["rank"]) if row["rank"] else 0,
        })

    remaining = limit - len(results)
    if remaining > 0:
        action_rows = conn.execute(
            """SELECT a.id, a.task_id, snippet(actions_fts, 0, '<b>', '</b>', '...', 32) as snippet, rank
               FROM actions_fts
               JOIN actions a ON a.id = actions_fts.rowid
               WHERE actions_fts MATCH ? AND a.workspace_id = ?
               ORDER BY rank
               LIMIT ?""",
            (query, workspace, remaining),
        ).fetchall()

        for row in action_rows:
            results.append({
                "type": "action",
                "id": row["id"],
                "task_id": row["task_id"],
                "snippet": row["snippet"],
                "relevance_score": abs(row["rank"]) if row["rank"] else 0,
            })

    return results


# ---------------------------------------------------------------------------
# Sync rework (WP-4 — the highest-value fix; design §4.2)
# ---------------------------------------------------------------------------
#
# WP-4 replaces the old "remote record == locally-editable task" model (which
# silently clobbered local edits — BUG-2 / pa_server.py:599) with a 3-way-merge
# pipeline:
#
#   * Remote records land in ``external_items`` (NOT ``tasks``) — remote-owned,
#     never directly edited by the user. A mirror ``task`` is created so the user
#     has a local surface, and ``task_external_links`` stores the 3-way-merge
#     BASE (``base_remote_version`` + ``base_local_updated_at``).
#   * On re-sync, compare remote_version vs base AND task.updated_at vs base:
#       - BOTH advanced past the base  -> sync_state.status='conflict' +
#         conflict_detail; the local task is NOT overwritten (T-SYNC-1).
#       - only the remote advanced     -> fast-forward: refresh external_item +
#         mirror task, advance the base.
#       - only the local advanced      -> fast-forward the local arm: advance the
#         base_local_updated_at; leave the (unchanged) remote as-is.
#       - neither advanced             -> touch last_synced only.
#   * Remote-authored text (title/body) is delimiter-wrapped via
#     ``wrap_remote_field(..., 'remote')`` (security-floor / WP-7) before it is
#     stored in external_items.body and before it surfaces — remote content is
#     untrusted data, never an instruction (L1 + L6).
#
# Auth (driven by ``connectors.deployment``):
#   * 'cloud'      -> Basic auth (email from user_env + token from token_env);
#                     Jira: GET /rest/api/3/search/jql + nextPageToken cursor;
#                     Confluence: GET /rest/api/search (CQL) + Basic.
#   * 'datacenter' -> PAT Bearer (token_env only); Jira: GET /rest/api/2/search +
#                     startAt/maxResults; Confluence: GET /rest/api/search + Bearer.
# The auth/endpoint payloads are PORTED from the jira-rest-api + confluence-rest-api
# skills (post-2025 Cloud reality: classic /rest/api/3/search was removed; Cloud
# uses /search/jql with a nextPageToken cursor and returns NO `total`).
#
# Fetching stays an injected callable so the characterization + integration
# suites can monkeypatch it without network. ``connectors`` stores env-var NAMES
# only — never the raw token (the never-store-raw-tokens invariant). stdlib
# urllib only; NO new pip deps (AMY D-plus lock).

_JIRA_PRIORITY_MAP = {
    "Highest": "critical", "High": "high", "Medium": "medium",
    "Low": "low", "Lowest": "low",
}

_JIRA_STATUS_MAP = {
    "new": "new",
    "undefined": "new",
    "indeterminate": "executing",
    "done": "done",
}


def _jira_status_map(status_category_key: str) -> str:
    """Map a Jira statusCategory.key to the PA status vocabulary.

    pa_core-local so the sync engine is self-contained (pa_server keeps its own
    back-compat copy for any direct caller / monkeypatch)."""
    return _JIRA_STATUS_MAP.get(status_category_key, "new")


def _ensure_connector(c, workspace, kind, source_config) -> int:
    """Upsert the ``connectors`` row for (workspace, kind) and return its id.

    Stores env-var NAMES only (base_url_env / user_env / token_env) — never the
    raw token. The connector is the FK target for external_items.connector_id.
    """
    deployment = source_config.get("deployment", "datacenter")
    if deployment not in ("cloud", "datacenter", "graph"):
        raise ValidationError(
            f"connector deployment must be one of cloud/datacenter/graph, got "
            f"{deployment!r}"
        )
    auth_mode = source_config.get("auth_mode") or (
        "basic" if deployment == "cloud" else "bearer"
    )
    base_url_env = source_config.get("base_url_env", "")
    user_env = source_config.get("user_env", "")
    token_env = source_config.get("token_env", "")
    allowed_host = source_config.get("allowed_host", "")
    query = source_config.get("query", "")

    c.execute(
        "INSERT INTO connectors (workspace_id, kind, deployment, auth_mode, "
        "base_url_env, user_env, token_env, allowed_host, query) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(workspace_id, kind) DO UPDATE SET "
        "deployment=excluded.deployment, auth_mode=excluded.auth_mode, "
        "base_url_env=excluded.base_url_env, user_env=excluded.user_env, "
        "token_env=excluded.token_env, allowed_host=excluded.allowed_host, "
        "query=excluded.query",
        (workspace, kind, deployment, auth_mode, base_url_env, user_env,
         token_env, allowed_host, query),
    )
    row = c.execute(
        "SELECT id FROM connectors WHERE workspace_id = ? AND kind = ?",
        (workspace, kind),
    ).fetchone()
    return row["id"]


def _sync_source(conn, ws_id, params, fetch, source, extract) -> dict:
    """Shared sync engine for both Jira and Confluence (design §4.2).

    Args:
        source: the sync_state.source enum value ('jira' or 'confluence').
        extract: ``fn(item, base_url) -> dict`` returning the normalised fields
            ``{remote_id, title, body, remote_version, remote_hash, url,
            mirror_status, mirror_priority}``. body/title are RAW remote text;
            this engine wraps them via security-floor before storage.

    The entire batch runs inside one ``_with_tx`` so a mid-batch raise rolls
    every prior write back (BUG-3) and re-raises as a typed SyncError so the
    adapter reports isError=true (BUG-1).
    """
    workspace = params.get("workspace", ws_id)
    source_config = params.get("source_config", {})

    default_base = "JIRA_BASE" if source == "jira" else "CONFLUENCE_BASE"
    default_token = "JIRA_TOKEN" if source == "jira" else "CONFLUENCE_TOKEN"
    base_url_env = source_config.get("base_url_env", default_base)
    token_env = source_config.get("token_env", default_token)
    strategy = source_config.get("strategy", "assigned" if source == "jira" else "label")
    query = source_config.get("query", "")

    base_url = os.environ.get(base_url_env)
    token = os.environ.get(token_env)
    if not base_url or not token:
        raise SyncError(
            f"Missing env vars: {base_url_env}={'set' if base_url else 'missing'}, "
            f"{token_env}={'set' if token else 'missing'}"
        )

    items = fetch(base_url, token, strategy, query)
    new_count = updated_count = conflict_count = 0

    try:
        with _with_tx(conn) as c:
            connector_id = _ensure_connector(c, workspace, source, source_config)
            for item in items:
                norm = extract(item, base_url)
                remote_id = norm["remote_id"]
                # Security-floor: remote title/body are UNTRUSTED data — wrap
                # before storing so a downstream agent read always sees inert,
                # delimiter-fenced content (L1 / WP-7).
                wrapped_title = wrap_remote_field(norm["title"], "remote")
                wrapped_body = wrap_remote_field(norm["body"], "remote")
                remote_version = str(norm["remote_version"])
                remote_hash = norm["remote_hash"]
                url = norm["url"]

                ext = c.execute(
                    "SELECT id, remote_version, remote_hash FROM external_items "
                    "WHERE workspace_id = ? AND connector_id = ? AND remote_id = ?",
                    (workspace, connector_id, remote_id),
                ).fetchone()

                if ext is None:
                    # First time we see this remote record: store the external
                    # item, create a mirror task (the local surface), link them,
                    # and pin the 3-way base at the link.
                    cur = c.execute(
                        "INSERT INTO external_items (workspace_id, connector_id, "
                        "remote_id, remote_url, title, body, remote_version, "
                        "remote_hash, last_synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (workspace, connector_id, remote_id, url, wrapped_title,
                         wrapped_body, remote_version, remote_hash, now_iso()),
                    )
                    external_item_id = cur.lastrowid

                    c.execute(
                        "INSERT INTO tasks (workspace_id, title, status, priority, "
                        "source, remote_id, remote_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (workspace, norm.get("mirror_title", norm["title"]),
                         norm.get("mirror_status", "new"),
                         norm.get("mirror_priority", "medium"),
                         source, remote_id, url),
                    )
                    task_row = c.execute(
                        "SELECT id, updated_at FROM tasks WHERE workspace_id = ? "
                        "AND source = ? AND remote_id = ?",
                        (workspace, source, remote_id),
                    ).fetchone()
                    task_id = task_row["id"]

                    c.execute(
                        "INSERT INTO task_external_links (task_id, external_item_id, "
                        "link_kind, base_remote_version, base_local_updated_at) "
                        "VALUES (?, ?, 'mirror', ?, ?)",
                        (task_id, external_item_id, remote_version, task_row["updated_at"]),
                    )
                    # sync_state row tracks the per-item sync status (the conflict
                    # surface pa_get_conflicts / pa_resolve_conflict read).
                    c.execute(
                        "INSERT INTO sync_state (workspace_id, source, remote_id, "
                        "remote_url, remote_version, local_hash, last_synced, status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'synced') "
                        "ON CONFLICT(workspace_id, source, remote_id) DO UPDATE SET "
                        "remote_version=excluded.remote_version, "
                        "local_hash=excluded.local_hash, last_synced=excluded.last_synced, "
                        "status='synced', conflict_detail=NULL",
                        (workspace, source, remote_id, url, remote_version,
                         remote_hash, now_iso()),
                    )
                    new_count += 1
                    continue

                external_item_id = ext["id"]
                link = c.execute(
                    "SELECT tel.id AS link_id, tel.task_id, tel.base_remote_version, "
                    "tel.base_local_updated_at FROM task_external_links tel "
                    "WHERE tel.external_item_id = ?",
                    (external_item_id,),
                ).fetchone()

                # The 3-way arms: did the remote advance past the base? did the
                # local task advance past the base?
                base_remote_version = link["base_remote_version"] if link else None
                base_local_updated_at = link["base_local_updated_at"] if link else None
                task_id = link["task_id"] if link else None

                task_row = (
                    c.execute(
                        "SELECT id, title, status, updated_at FROM tasks WHERE id = ?",
                        (task_id,),
                    ).fetchone()
                    if task_id is not None
                    else None
                )
                local_updated_at = task_row["updated_at"] if task_row else None

                remote_advanced = remote_hash != ext["remote_hash"]
                local_advanced = (
                    base_local_updated_at is not None
                    and local_updated_at is not None
                    and local_updated_at != base_local_updated_at
                )

                if remote_advanced and local_advanced:
                    # T-SYNC-1: BOTH sides moved past the base -> real conflict.
                    # Do NOT overwrite the local task; surface it for the user.
                    conflict_detail = json.dumps({
                        "remote": {
                            "version": remote_version,
                            "title": wrapped_title,
                        },
                        "local": {
                            "title": task_row["title"] if task_row else None,
                            "updated_at": local_updated_at,
                        },
                        "base": {
                            "remote_version": base_remote_version,
                            "local_updated_at": base_local_updated_at,
                        },
                    }, default=str)
                    # Refresh the external_item's remote view (remote-side facts
                    # are not in dispute — they ARE the remote), but leave the
                    # local task untouched and flag the conflict.
                    c.execute(
                        "UPDATE external_items SET title = ?, body = ?, "
                        "remote_version = ?, remote_hash = ?, last_synced = ? WHERE id = ?",
                        (wrapped_title, wrapped_body, remote_version, remote_hash,
                         now_iso(), external_item_id),
                    )
                    c.execute(
                        "INSERT INTO sync_state (workspace_id, source, remote_id, "
                        "remote_url, remote_version, last_synced, status, conflict_detail) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'conflict', ?) "
                        "ON CONFLICT(workspace_id, source, remote_id) DO UPDATE SET "
                        "remote_version=excluded.remote_version, "
                        "last_synced=excluded.last_synced, status='conflict', "
                        "conflict_detail=excluded.conflict_detail",
                        (workspace, source, remote_id, url, remote_version,
                         now_iso(), conflict_detail),
                    )
                    conflict_count += 1
                elif remote_advanced:
                    # Only the remote moved -> fast-forward the local mirror and
                    # advance the base. Safe: no local edit to lose.
                    c.execute(
                        "UPDATE external_items SET title = ?, body = ?, "
                        "remote_version = ?, remote_hash = ?, last_synced = ? WHERE id = ?",
                        (wrapped_title, wrapped_body, remote_version, remote_hash,
                         now_iso(), external_item_id),
                    )
                    if task_row is not None:
                        c.execute(
                            "UPDATE tasks SET title = ?, status = ?, updated_at = ? WHERE id = ?",
                            (norm.get("mirror_title", norm["title"]),
                             norm.get("mirror_status", task_row["status"]),
                             now_iso(), task_id),
                        )
                        new_base_local = c.execute(
                            "SELECT updated_at FROM tasks WHERE id = ?", (task_id,)
                        ).fetchone()["updated_at"]
                    else:
                        new_base_local = base_local_updated_at
                    if link is not None:
                        c.execute(
                            "UPDATE task_external_links SET base_remote_version = ?, "
                            "base_local_updated_at = ? WHERE id = ?",
                            (remote_version, new_base_local, link["link_id"]),
                        )
                    c.execute(
                        "INSERT INTO sync_state (workspace_id, source, remote_id, "
                        "remote_url, remote_version, local_hash, last_synced, status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'synced') "
                        "ON CONFLICT(workspace_id, source, remote_id) DO UPDATE SET "
                        "remote_version=excluded.remote_version, "
                        "local_hash=excluded.local_hash, last_synced=excluded.last_synced, "
                        "status='synced', conflict_detail=NULL",
                        (workspace, source, remote_id, url, remote_version,
                         remote_hash, now_iso()),
                    )
                    updated_count += 1
                elif local_advanced:
                    # Only the local moved -> fast-forward the LOCAL arm of the
                    # base so the next remote change is measured from here. The
                    # remote is unchanged; nothing to write to external_items.
                    if link is not None:
                        c.execute(
                            "UPDATE task_external_links SET base_local_updated_at = ? "
                            "WHERE id = ?",
                            (local_updated_at, link["link_id"]),
                        )
                    c.execute(
                        "UPDATE external_items SET last_synced = ? WHERE id = ?",
                        (now_iso(), external_item_id),
                    )
                    c.execute(
                        "UPDATE sync_state SET last_synced = ?, status = 'synced' "
                        "WHERE workspace_id = ? AND source = ? AND remote_id = ?",
                        (now_iso(), workspace, source, remote_id),
                    )
                else:
                    # Neither side moved -> just record we looked.
                    c.execute(
                        "UPDATE external_items SET last_synced = ? WHERE id = ?",
                        (now_iso(), external_item_id),
                    )
                    c.execute(
                        "UPDATE sync_state SET last_synced = ? "
                        "WHERE workspace_id = ? AND source = ? AND remote_id = ?",
                        (now_iso(), workspace, source, remote_id),
                    )
    except SyncError:
        raise
    except Exception as e:  # malformed remote item etc. — rolled back, re-raised honestly
        raise SyncError(str(e))

    return {
        "pulled": len(items),
        "new_items": new_count,
        "updated_items": updated_count,
        "conflicts": conflict_count,
    }


def _extract_jira(item, base_url) -> dict:
    """Normalise a Jira issue (Cloud v3 search/jql OR DC v2 search shape)."""
    remote_id = item.get("key", "")
    fields = item.get("fields", {})
    summary = fields.get("summary", "Untitled")
    status_name = (
        fields.get("status", {}).get("statusCategory", {}).get("key", "new")
    )
    mirror_status = _jira_status_map(status_name)
    jira_priority = fields.get("priority", {}).get("name", "Medium")
    mirror_priority = _JIRA_PRIORITY_MAP.get(jira_priority, "medium")
    body = fields.get("description") or ""
    if isinstance(body, dict):  # Cloud ADF description -> store the JSON text
        body = json.dumps(body, sort_keys=True, default=str)
    remote_version = fields.get("updated", "") or remote_id
    remote_hash = hashlib.sha256(
        json.dumps(item, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return {
        "remote_id": remote_id,
        "title": summary,
        "mirror_title": summary,
        "body": body,
        "remote_version": remote_version,
        "remote_hash": remote_hash,
        "url": f"{base_url}/browse/{remote_id}",
        "mirror_status": mirror_status,
        "mirror_priority": mirror_priority,
    }


def _extract_confluence(item, base_url) -> dict:
    """Normalise a Confluence page (Cloud /rest/api/search OR DC shape)."""
    remote_id = str(item.get("id", ""))
    title = item.get("title", "Untitled")
    version = (
        item.get("version", {}).get("number", 1)
        if isinstance(item.get("version"), dict)
        else item.get("version", 1)
    )
    body = ""
    body_obj = item.get("body", {})
    if isinstance(body_obj, dict):
        body = (
            body_obj.get("storage", {}).get("value", "")
            or body_obj.get("view", {}).get("value", "")
            or ""
        )
    remote_hash = hashlib.sha256(
        json.dumps(item, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return {
        "remote_id": remote_id,
        "title": title,
        "mirror_title": title,
        "body": body,
        "remote_version": version,
        "remote_hash": remote_hash,
        "url": f"{base_url}/pages/viewpage.action?pageId={remote_id}",
        "mirror_status": "new",
        "mirror_priority": "medium",
    }


def sync_confluence(conn, ws_id, params, fetch) -> dict:
    """Sync Confluence pages into external_items with 3-way conflict detection."""
    return _sync_source(conn, ws_id, params, fetch, "confluence", _extract_confluence)


def sync_jira(conn, ws_id, params, fetch, status_map=None) -> dict:
    """Sync Jira issues into external_items with 3-way conflict detection.

    ``status_map`` is accepted for back-compat with the pa_server wiring but is
    unused — the engine resolves status via the module-level ``_jira_status_map``
    through ``_extract_jira`` so pa_core stays self-contained.
    """
    return _sync_source(conn, ws_id, params, fetch, "jira", _extract_jira)


# ---------------------------------------------------------------------------
# Cloud / Data Center fetchers (deployment-driven auth; stdlib urllib only)
# ---------------------------------------------------------------------------
#
# Ported from the jira-rest-api + confluence-rest-api skills. The deployment
# discriminator (from connectors / source_config) selects the auth scheme +
# endpoint. Tokens are read from the environment at call time — NEVER stored.


def _auth_header(deployment: str, user_env: str, token: str) -> dict:
    """Build the Authorization header for the deployment.

    Cloud  -> HTTP Basic with ``<email>:<api_token>`` (email from user_env).
    Data Center / other -> PAT ``Bearer <token>`` (no username).
    """
    if deployment == "cloud":
        email = os.environ.get(user_env, "") if user_env else ""
        raw = f"{email}:{token}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
    return {"Authorization": f"Bearer {token}"}


def _http_get_json(url: str, headers: dict, query_params: dict = None) -> dict:
    """GET JSON using only stdlib urllib (NO new pip deps)."""
    if query_params:
        url = url + "?" + urllib.parse.urlencode(query_params)
    req = urllib.request.Request(url)
    for k, v in headers.items():
        req.add_header(k, v)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SyncError(f"Authentication failed (401). Refresh credentials. URL: {url}")
        raise SyncError(f"HTTP {e.code}: {e.reason}. URL: {url}")
    except urllib.error.URLError as e:
        raise SyncError(f"Network error reaching {url}: {e.reason}")


def jira_fetch(base_url: str, token: str, strategy: str, query: str,
               deployment: str = "datacenter", user_env: str = "") -> list:
    """Fetch Jira issues, deployment-aware (design §4.2 step 3).

    Cloud      -> Basic auth + GET /rest/api/3/search/jql + nextPageToken cursor
                  (the classic /rest/api/3/search was removed from Cloud in 2025;
                  the response carries NO `total`).
    Data Center-> PAT Bearer + GET /rest/api/2/search + startAt/maxResults offset.
    """
    if strategy == "jql":
        jql = query
    elif strategy == "filter":
        jql = f"filter = {query}"
    else:
        jql = query or "assignee = currentUser() ORDER BY updated DESC"

    headers = _auth_header(deployment, user_env, token)
    fields = "summary,status,priority,updated,description"
    issues = []

    if deployment == "cloud":
        url = f"{base_url}/rest/api/3/search/jql"
        next_token = None
        # Bounded paging loop — never tight-loop; the cursor terminates when the
        # API stops returning nextPageToken (no `total` on Cloud).
        for _ in range(100):
            params = {"jql": jql, "maxResults": "50", "fields": fields}
            if next_token:
                params["nextPageToken"] = next_token
            data = _http_get_json(url, headers, params)
            issues.extend(data.get("issues", []))
            next_token = data.get("nextPageToken")
            if not next_token or data.get("isLast"):
                break
    else:
        url = f"{base_url}/rest/api/2/search"
        start_at = 0
        for _ in range(100):
            data = _http_get_json(url, headers, {
                "jql": jql, "maxResults": "50", "fields": fields, "startAt": str(start_at),
            })
            page = data.get("issues", [])
            issues.extend(page)
            total = data.get("total", 0)
            start_at += len(page)
            if not page or start_at >= total:
                break
    return issues


def confluence_fetch(base_url: str, token: str, strategy: str, query: str,
                     deployment: str = "datacenter", user_env: str = "") -> list:
    """Fetch Confluence pages, deployment-aware.

    CQL search (`/rest/api/search`) has NO v2 equivalent, so both Cloud and DC
    use it; the deployment only selects the auth scheme (Cloud Basic vs DC
    Bearer). ``expand=body.storage,version`` so the remote body is available to
    wrap.
    """
    if strategy == "label":
        cql = f'label = "{query}" AND type = "page"'
    elif strategy == "parent":
        cql = f'ancestor = {query} AND type = "page"'
    elif strategy == "cql":
        cql = query
    else:
        cql = 'type = "page" ORDER BY lastModified DESC'

    headers = _auth_header(deployment, user_env, token)
    url = f"{base_url}/rest/api/search"
    results = []
    start = 0
    for _ in range(100):
        data = _http_get_json(url, headers, {
            "cql": cql, "limit": "50", "start": str(start),
            "expand": "version,body.storage",
        })
        page = data.get("results", [])
        results.extend(page)
        # Cloud/DC CQL search uses start+limit offset paging; stop when a short
        # page comes back (no more results).
        if len(page) < 50:
            break
        start += len(page)
    return results


def get_conflicts(conn: sqlite3.Connection, ws_id: str, params: dict) -> list:
    workspace = params.get("workspace", ws_id)
    rows = conn.execute(
        """SELECT ss.id as sync_state_id, t.id as task_id, ss.source as remote_source,
                  ss.status, ss.conflict_detail, ss.last_synced as detected_at
           FROM sync_state ss
           LEFT JOIN tasks t ON t.workspace_id = ss.workspace_id AND t.source = ss.source AND t.remote_id = ss.remote_id
           WHERE ss.workspace_id = ? AND ss.status = 'conflict'""",
        (workspace,),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_conflict(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    sync_state_id = params["sync_state_id"]
    resolution = params["resolution"]  # 'keep_local' or 'accept_remote'

    with _with_tx(conn) as c:
        ss = c.execute("SELECT * FROM sync_state WHERE id = ?", (sync_state_id,)).fetchone()
        if not ss:
            raise NotFoundError(f"Sync state {sync_state_id} not found")

        if resolution == "accept_remote" and ss["conflict_detail"]:
            try:
                detail = json.loads(ss["conflict_detail"])
                task = c.execute(
                    "SELECT id FROM tasks WHERE workspace_id = ? AND source = ? AND remote_id = ?",
                    (ss["workspace_id"], ss["source"], ss["remote_id"]),
                ).fetchone()
                if task and "remote" in detail:
                    remote_data = detail["remote"]
                    if "title" in remote_data:
                        c.execute(
                            "UPDATE tasks SET title = ?, updated_at = ? WHERE id = ?",
                            (remote_data["title"], now_iso(), task["id"]),
                        )
            except (json.JSONDecodeError, KeyError):
                pass

        c.execute(
            "UPDATE sync_state SET status = 'synced', conflict_detail = NULL, last_synced = ? WHERE id = ?",
            (now_iso(), sync_state_id),
        )
        ws_source_id = (ss["workspace_id"], ss["source"], ss["remote_id"])

    task = conn.execute(
        "SELECT id FROM tasks WHERE workspace_id = ? AND source = ? AND remote_id = ?",
        ws_source_id,
    ).fetchone()
    return {"resolved": True, "task_id": task["id"] if task else None, "updated_at": now_iso()}


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

def get_preferences(conn: sqlite3.Connection, ws_id: str, params: dict) -> list:
    workspace = params.get("workspace")
    category = params.get("category")

    conditions = []
    values = []
    if workspace:
        conditions.append("(workspace_id = ? OR workspace_id IS NULL)")
        values.append(workspace)
    else:
        conditions.append("workspace_id IS NULL")

    if category:
        conditions.append("category = ?")
        values.append(category)

    where = " AND ".join(conditions) if conditions else "1=1"
    rows = conn.execute(
        f"SELECT key, value, confidence, signal_count, category FROM preferences "
        f"WHERE {where} ORDER BY signal_count DESC",
        values,
    ).fetchall()
    return [dict(r) for r in rows]


def update_preference(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    key = params["key"]
    value = params["value"]
    category = params["category"]
    workspace = params.get("workspace")

    with _with_tx(conn) as c:
        existing = c.execute(
            "SELECT id, signal_count, confidence FROM preferences "
            "WHERE key = ? AND (workspace_id = ? OR (workspace_id IS NULL AND ? IS NULL))",
            (key, workspace, workspace),
        ).fetchone()

        if existing:
            new_count = existing["signal_count"] + 1
            if new_count >= 5:
                confidence = 0.95
            elif new_count >= 3:
                confidence = 0.8
            elif new_count >= 2:
                confidence = 0.5
            else:
                confidence = 0.3
            c.execute(
                "UPDATE preferences SET value = ?, signal_count = ?, confidence = ?, updated_at = ? WHERE id = ?",
                (value, new_count, confidence, now_iso(), existing["id"]),
            )
            out = {"key": key, "value": value, "confidence": confidence, "signal_count": new_count}
        else:
            c.execute(
                "INSERT INTO preferences (workspace_id, key, value, category, confidence, signal_count) "
                "VALUES (?, ?, ?, ?, 0.3, 1)",
                (workspace, key, value, category),
            )
            out = {"key": key, "value": value, "confidence": 0.3, "signal_count": 1}
    return out


def clear_preference(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    key = params["key"]
    workspace = params.get("workspace")

    with _with_tx(conn) as c:
        c.execute(
            "DELETE FROM preferences WHERE key = ? AND (workspace_id = ? OR (workspace_id IS NULL AND ? IS NULL))",
            (key, workspace, workspace),
        )
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def health(conn: sqlite3.Connection, ws_id: str, params: dict, db_path=None) -> dict:
    db_size = 0
    if db_path is not None:
        p = Path(db_path)
        db_size = p.stat().st_size if p.exists() else 0

    task_count = conn.execute(
        "SELECT COUNT(*) as c FROM tasks WHERE workspace_id = ?", (ws_id,)
    ).fetchone()["c"]

    confluence_sync = conn.execute(
        "SELECT MAX(last_synced) as ls FROM sync_state WHERE workspace_id = ? AND source = 'confluence'",
        (ws_id,),
    ).fetchone()
    jira_sync = conn.execute(
        "SELECT MAX(last_synced) as ls FROM sync_state WHERE workspace_id = ? AND source = 'jira'",
        (ws_id,),
    ).fetchone()

    return {
        "db_size": db_size,
        "task_count": task_count,
        "last_sync": {
            "confluence": confluence_sync["ls"] if confluence_sync else None,
            "jira": jira_sync["ls"] if jira_sync else None,
        },
        "fts_enabled": True,
        "semantic_enabled": False,
        "transport": "json-rpc",
    }


# ---------------------------------------------------------------------------
# Sync configuration
# ---------------------------------------------------------------------------

def set_sync_config(conn: sqlite3.Connection, ws_id: str, params: dict) -> dict:
    workspace = params.get("workspace", ws_id)
    source = params["source"]
    config = params.get("config", {})

    with _with_tx(conn) as c:
        c.execute(
            """INSERT INTO sync_configs (workspace_id, source, base_url_env, token_env, strategy, query)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(workspace_id, source) DO UPDATE SET
               base_url_env = excluded.base_url_env,
               token_env = excluded.token_env,
               strategy = excluded.strategy,
               query = excluded.query""",
            (workspace, source, config.get("base_url_env", ""), config.get("token_env", ""),
             config.get("strategy", ""), config.get("query", "")),
        )
    return {"workspace": workspace, "source": source, "configured": True}


def get_sync_configs(conn: sqlite3.Connection, ws_id: str, params: dict) -> list:
    workspace = params.get("workspace", ws_id)
    rows = conn.execute(
        """SELECT sc.source, sc.strategy, sc.query,
                  (SELECT MAX(last_synced) FROM sync_state ss
                   WHERE ss.workspace_id = sc.workspace_id AND ss.source = sc.source) as last_synced
           FROM sync_configs sc
           WHERE sc.workspace_id = ? AND sc.enabled = 1""",
        (workspace,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Stdlib JSON-Schema validation (the ~20-line pre-dispatch guard)
# ---------------------------------------------------------------------------
#
# NOT a full JSON-Schema implementation — the subset the TOOL_SCHEMAS use:
# object `required`, scalar `type` (string/integer/number/boolean/array/object),
# and `enum`. Nested object `properties` are validated one level deep (enough for
# source_config / config). Raises ValidationError on the FIRST violation so the
# adapter rejects the call before pa_core is ever invoked (T-ADP-1).

_JSON_TYPE_CHECK = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def validate_arguments(schema: dict, arguments: dict, _path: str = "arguments") -> None:
    """Validate ``arguments`` against the subset of JSON-Schema used by
    TOOL_SCHEMAS. Raises ValidationError on the first problem. Returns None on
    success. Pure (no I/O)."""
    if schema is None:
        return
    if not isinstance(arguments, dict):
        raise ValidationError(f"{_path}: expected an object")

    for req in schema.get("required", []):
        if req not in arguments:
            raise ValidationError(f"{_path}: missing required field '{req}'")

    props = schema.get("properties", {})
    for key, value in arguments.items():
        spec = props.get(key)
        if spec is None:
            # Unknown keys are tolerated (forward-compat); only declared keys are typed.
            continue
        expected = spec.get("type")
        if expected and expected in _JSON_TYPE_CHECK:
            if not _JSON_TYPE_CHECK[expected](value):
                raise ValidationError(
                    f"{_path}.{key}: expected {expected}, got {type(value).__name__}"
                )
        enum = spec.get("enum")
        if enum is not None and value not in enum:
            raise ValidationError(f"{_path}.{key}: '{value}' not in allowed {enum}")
        # One level of nested-object validation (source_config / config).
        if expected == "object" and "properties" in spec:
            validate_arguments(spec, value, _path=f"{_path}.{key}")
