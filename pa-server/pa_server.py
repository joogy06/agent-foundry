#!/usr/bin/env python3
"""
PA Server — MCP-compatible tool server for the PA agent.

Transport: Raw stdio JSON-RPC 2.0 (Option B from spec).
Data:      SQLite + FTS5, WAL mode.
Location:  ~/.claude/pa-server/pa_server.py

Provides 20 MCP tools for task management, action logging, session management,
search, sync, preferences, health, and sync configuration.

Usage:
    python3 pa_server.py                     # workspace from CWD or $PA_WORKSPACE
    PA_WORKSPACE=/path python3 pa_server.py  # explicit workspace

<!-- FRESHNESS:v1
anchors:
  - kind: status_snapshot
    subject: mcp-protocol-version
    verified_against: "2025-11-25 (negotiated MCP spec; Claude Code negotiates at runtime)"
    verified_on: "2026-06-12"
    volatility: medium
    review_by: "2027-01"
-->
"""

import json
import os
import sys
import sqlite3
import hashlib
import traceback
from datetime import datetime
from pathlib import Path

# pa_core — transport-neutral data-access core (single SQLite writer, _with_tx
# rollback, busy_timeout, typed errors). pa_server is a THIN adapter over it
# (M0a / WP-2). Loaded relative to this file so it resolves regardless of CWD
# (bob's trusted_runner launches pytest from the project root, not pa-server/).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pa_core  # noqa: E402
from pa_core import PaError, NotFoundError, ValidationError, SyncError  # noqa: E402,F401

# MCP protocol version this server advertises in `initialize`. Bumped off the
# stale "2024-11-05" to the current negotiated MCP spec (M0a / WP-6). The S041
# evergreen freshness loop tracks drift via the FRESHNESS:v1 anchor in this
# module's docstring (subject: mcp-protocol-version).
MCP_PROTOCOL_VERSION = "2025-11-25"

# ---------------------------------------------------------------------------
# Workspace resolution
# ---------------------------------------------------------------------------

def resolve_workspace() -> Path:
    """Resolve workspace path from $PA_WORKSPACE or CWD."""
    if env := os.environ.get("PA_WORKSPACE"):
        ws_path = Path(env)
    else:
        cwd = Path.cwd()
        name = cwd.name or "default"
        ws_path = Path.home() / ".pa" / "workspaces" / name

    ws_path.mkdir(parents=True, exist_ok=True)
    return ws_path


def workspace_id_from_path(ws_path: Path) -> str:
    """Derive a stable workspace ID from its path."""
    return hashlib.sha256(str(ws_path).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Database initialisation
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
-- Core tables
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    project_path TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_accessed TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'new' CHECK(status IN ('new','designed','executing','blocked','done','failed','cancelled')),
    priority TEXT DEFAULT 'medium' CHECK(priority IN ('critical','high','medium','low')),
    source TEXT DEFAULT 'local' CHECK(source IN ('local','confluence','jira')),
    remote_id TEXT,
    remote_url TEXT,
    assigned_agent TEXT,
    tags TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    designed_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    action TEXT NOT NULL,
    agent TEXT,
    skill TEXT,
    result TEXT,
    artifacts TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    started_at TEXT DEFAULT (datetime('now')),
    ended_at TEXT,
    summary TEXT,
    tool TEXT
);

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.3,
    signal_count INTEGER DEFAULT 1,
    category TEXT CHECK(category IN ('routing','writing','presentation','communication','tool')),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    source TEXT NOT NULL CHECK(source IN ('confluence','jira')),
    remote_id TEXT NOT NULL,
    remote_url TEXT,
    remote_version INTEGER,
    local_hash TEXT,
    last_synced TEXT,
    status TEXT DEFAULT 'synced' CHECK(status IN ('synced','conflict','stale','deleted')),
    conflict_detail TEXT,
    UNIQUE(workspace_id, source, remote_id)
);

CREATE TABLE IF NOT EXISTS sync_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    source TEXT NOT NULL CHECK(source IN ('confluence','jira')),
    base_url_env TEXT NOT NULL,
    token_env TEXT NOT NULL,
    strategy TEXT NOT NULL,
    query TEXT,
    poll_interval INTEGER DEFAULT 300,
    enabled INTEGER DEFAULT 1,
    UNIQUE(workspace_id, source)
);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
    title, description, tags,
    content=tasks, content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS actions_fts USING fts5(
    action, result,
    content=actions, content_rowid=id
);
"""

INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_tasks_workspace_status ON tasks(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_source ON tasks(source, remote_id);
CREATE INDEX IF NOT EXISTS idx_actions_task ON actions(task_id);
CREATE INDEX IF NOT EXISTS idx_actions_workspace ON actions(workspace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sync_workspace_source ON sync_state(workspace_id, source);
CREATE INDEX IF NOT EXISTS idx_preferences_workspace ON preferences(workspace_id, category);
"""

TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS tasks_ai AFTER INSERT ON tasks BEGIN
    INSERT INTO tasks_fts(rowid, title, description, tags) VALUES (new.id, new.title, new.description, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS tasks_au AFTER UPDATE ON tasks BEGIN
    INSERT INTO tasks_fts(tasks_fts, rowid, title, description, tags) VALUES('delete', old.id, old.title, old.description, old.tags);
    INSERT INTO tasks_fts(rowid, title, description, tags) VALUES (new.id, new.title, new.description, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS tasks_ad AFTER DELETE ON tasks BEGIN
    INSERT INTO tasks_fts(tasks_fts, rowid, title, description, tags) VALUES('delete', old.id, old.title, old.description, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS actions_ai AFTER INSERT ON actions BEGIN
    INSERT INTO actions_fts(rowid, action, result) VALUES (new.id, new.action, new.result);
END;
CREATE TRIGGER IF NOT EXISTS actions_au AFTER UPDATE ON actions BEGIN
    INSERT INTO actions_fts(actions_fts, rowid, action, result) VALUES('delete', old.id, old.action, old.result);
    INSERT INTO actions_fts(rowid, action, result) VALUES (new.id, new.action, new.result);
END;
CREATE TRIGGER IF NOT EXISTS actions_ad AFTER DELETE ON actions BEGIN
    INSERT INTO actions_fts(actions_fts, rowid, action, result) VALUES('delete', old.id, old.action, old.result);
END;
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create/open SQLite DB, run schema DDL, enable WAL + busy_timeout.

    The connection PRAGMA (WAL / foreign_keys / busy_timeout=5000) is owned by
    ``pa_core.connect`` so the single-writer discipline + block-and-retry are set
    identically wherever pa_core is imported (adapter today, M4 dashboard later).
    """
    conn = pa_core.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(FTS_SQL)
    conn.executescript(INDEXES_SQL)
    conn.executescript(TRIGGERS_SQL)
    conn.commit()
    # WP-3: apply the AMY schema migrations (14 new tables + tasks
    # due_at/start_at/planning_period + FTS companions) idempotently. Empty DBs
    # => zero migration cost; re-running on a migrated DB is a no-op (T-MIG-1).
    # The runner owns its own per-version transactions.
    pa_core.run_migrations(conn)
    return conn


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

class PATools:
    """Thin façade over ``pa_core`` (M0a / WP-2).

    Historically this class held all tool logic. After the WP-2 extraction the
    logic lives in ``pa_core`` as transport-neutral ``fn(conn, ws_id, params)``
    functions; ``PATools`` is a back-compat binding (the existing pa agent code
    and the characterization suite call ``tools.pa_*(params)``). Each method
    forwards to its pa_core function with the connection + workspace id this
    instance is bound to. Errors RAISE (pa_core typed errors) — the dispatcher
    maps them to ``isError=true`` honestly.
    """

    def __init__(self, conn: sqlite3.Connection, ws_path: Path, ws_id: str):
        self.conn = conn
        self.ws_path = ws_path
        self.ws_id = ws_id
        # Workspace bootstrap is a pa_core write (inside _with_tx).
        pa_core.ensure_workspace(conn, ws_id, ws_path.name, str(ws_path))

    # -- Task Management --

    def pa_create_task(self, params: dict) -> dict:
        return pa_core.create_task(self.conn, self.ws_id, params)

    def pa_update_task(self, params: dict) -> dict:
        return pa_core.update_task(self.conn, self.ws_id, params)

    def pa_query_tasks(self, params: dict) -> list:
        return pa_core.query_tasks(self.conn, self.ws_id, params)

    def pa_get_task(self, params: dict) -> dict:
        return pa_core.get_task(self.conn, self.ws_id, params)

    # -- Action Logging --

    def pa_log_action(self, params: dict) -> dict:
        return pa_core.log_action(self.conn, self.ws_id, params)

    # -- Session Management --

    def pa_start_session(self, params: dict) -> dict:
        return pa_core.start_session(self.conn, self.ws_id, params)

    def pa_get_briefing_snapshot(self, params: dict) -> dict:
        # WP-5: pure idempotent read (no session row written). The
        # mcp__pa-server__* wildcard auto-permits this new tool.
        return pa_core.get_briefing_snapshot(self.conn, self.ws_id, params)

    def pa_end_session(self, params: dict) -> dict:
        return pa_core.end_session(self.conn, self.ws_id, params)

    # -- Search --

    def pa_search(self, params: dict) -> list:
        return pa_core.search(self.conn, self.ws_id, params)

    # -- Sync (fetchers injected so monkeypatching pa_server._jira_fetch /
    #    _confluence_fetch keeps working for the characterization + WP-4 suites).
    #    WP-4: the injected fetcher closes over the connector's deployment +
    #    user_env so pa_core's deployment-aware Cloud/DC auth is driven from
    #    source_config, while the 4-arg (base_url, token, strategy, query)
    #    fetcher signature the tests monkeypatch is preserved. --

    def pa_sync_confluence(self, params: dict) -> dict:
        cfg = params.get("source_config", {})
        deployment = cfg.get("deployment", "datacenter")
        user_env = cfg.get("user_env", "")

        def fetch(base_url, token, strategy, query):
            return _confluence_fetch(base_url, token, strategy, query,
                                     deployment=deployment, user_env=user_env)

        return pa_core.sync_confluence(self.conn, self.ws_id, params, fetch)

    def pa_sync_jira(self, params: dict) -> dict:
        cfg = params.get("source_config", {})
        deployment = cfg.get("deployment", "datacenter")
        user_env = cfg.get("user_env", "")

        def fetch(base_url, token, strategy, query):
            return _jira_fetch(base_url, token, strategy, query,
                               deployment=deployment, user_env=user_env)

        return pa_core.sync_jira(self.conn, self.ws_id, params, fetch, _jira_status_map)

    def pa_get_conflicts(self, params: dict) -> list:
        return pa_core.get_conflicts(self.conn, self.ws_id, params)

    def pa_resolve_conflict(self, params: dict) -> dict:
        return pa_core.resolve_conflict(self.conn, self.ws_id, params)

    # -- Preferences --

    def pa_get_preferences(self, params: dict) -> list:
        return pa_core.get_preferences(self.conn, self.ws_id, params)

    def pa_update_preference(self, params: dict) -> dict:
        return pa_core.update_preference(self.conn, self.ws_id, params)

    def pa_clear_preference(self, params: dict) -> dict:
        return pa_core.clear_preference(self.conn, self.ws_id, params)

    # -- Health --

    def pa_health(self, params: dict) -> dict:
        return pa_core.health(self.conn, self.ws_id, params, db_path=self.ws_path / "pa.db")

    # -- Sync Configuration --

    def pa_set_sync_config(self, params: dict) -> dict:
        return pa_core.set_sync_config(self.conn, self.ws_id, params)

    def pa_get_sync_configs(self, params: dict) -> list:
        return pa_core.get_sync_configs(self.conn, self.ws_id, params)


# NOTE (WP-2): the former in-class tool implementations were mechanically
# lifted into pa_core.py (transport-neutral fn(conn, ws_id, params)). PATools
# above is now a thin façade forwarding to them — pa_core is the single source
# of the data-access logic and the single SQLite writer.


# ---------------------------------------------------------------------------
# HTTP helpers for sync (stdlib only)
# ---------------------------------------------------------------------------

def _http_get_json(url: str, token: str, params: dict = None) -> dict:
    """GET JSON from URL using only stdlib."""
    import urllib.request
    import urllib.parse

    if params:
        url = url + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise Exception(f"Authentication failed (401). Refresh your token. URL: {url}")
        raise Exception(f"HTTP {e.code}: {e.reason}. URL: {url}")


def _confluence_fetch(base_url: str, token: str, strategy: str, query: str,
                      deployment: str = "datacenter", user_env: str = "") -> list:
    """Fetch Confluence items — delegates to pa_core's deployment-aware fetcher.

    WP-4: the real Cloud/DC auth + paging lives in ``pa_core.confluence_fetch``
    (Basic for Cloud, Bearer PAT for Data Center). This thin module-level wrapper
    is kept so the characterization + integration suites can monkeypatch
    ``pa_server._confluence_fetch`` without network.
    """
    return pa_core.confluence_fetch(base_url, token, strategy, query,
                                    deployment=deployment, user_env=user_env)


def _jira_fetch(base_url: str, token: str, strategy: str, query: str,
                deployment: str = "datacenter", user_env: str = "") -> list:
    """Fetch Jira issues — delegates to pa_core's deployment-aware fetcher.

    WP-4: Cloud uses Basic + /rest/api/3/search/jql + nextPageToken; Data Center
    uses PAT Bearer + /rest/api/2/search + startAt/maxResults. The endpoint/auth
    choice is driven by ``deployment`` (from connectors / source_config). This
    thin wrapper is kept for monkeypatch-ability in the test suites.
    """
    return pa_core.jira_fetch(base_url, token, strategy, query,
                              deployment=deployment, user_env=user_env)


def _jira_status_map(status_category_key: str) -> str:
    """Map Jira statusCategory.key to PA status vocabulary."""
    mapping = {
        "new": "new",
        "undefined": "new",
        "indeterminate": "executing",
        "done": "done",
    }
    return mapping.get(status_category_key, "new")


def _now() -> str:
    """Current UTC timestamp in ISO format. Delegates to pa_core.now_iso so the
    adapter and core share a single time source (kept for back-compat: existing
    callers / tests reference pa_server._now)."""
    return pa_core.now_iso()


# ---------------------------------------------------------------------------
# MCP Tool Registry (JSON Schema for each tool)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = {
    "pa_create_task": {
        "name": "pa_create_task",
        "description": "Create a new task in the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Workspace ID (defaults to current)"},
                "title": {"type": "string", "description": "Task title"},
                "description": {"type": "string", "description": "Task description"},
                "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                "source": {"type": "string", "enum": ["local", "confluence", "jira"]},
                "remote_id": {"type": "string", "description": "Remote system ID"},
                "remote_url": {"type": "string", "description": "Remote system URL"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags as JSON array"},
            },
            "required": ["title"],
        },
    },
    "pa_update_task": {
        "name": "pa_update_task",
        "description": "Update an existing task. Only provided fields are changed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Task ID"},
                "status": {"type": "string", "enum": ["new", "designed", "executing", "blocked", "done", "failed", "cancelled"]},
                "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                "description": {"type": "string"},
                "assigned_agent": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id"],
        },
    },
    "pa_query_tasks": {
        "name": "pa_query_tasks",
        "description": "Query tasks by workspace, status, priority, source, or time range.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "status": {"type": "string", "enum": ["new", "designed", "executing", "blocked", "done", "failed", "cancelled"]},
                "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                "source": {"type": "string", "enum": ["local", "confluence", "jira"]},
                "since": {"type": "string", "description": "ISO timestamp — return tasks updated since"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
            },
        },
    },
    "pa_get_task": {
        "name": "pa_get_task",
        "description": "Get full task record including recent actions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Task ID"},
            },
            "required": ["id"],
        },
    },
    "pa_log_action": {
        "name": "pa_log_action",
        "description": "Log an action (state transition, agent result, skill invocation).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "task_id": {"type": "integer", "description": "Associated task (optional)"},
                "action": {"type": "string", "description": "What happened"},
                "agent": {"type": "string", "description": "Agent that performed the action"},
                "skill": {"type": "string", "description": "Skill used"},
                "result": {"type": "string", "description": "Outcome"},
                "artifacts": {"type": "array", "items": {"type": "string"}, "description": "File paths produced"},
            },
            "required": ["action"],
        },
    },
    "pa_start_session": {
        "name": "pa_start_session",
        "description": "Start a new PA session. Returns workspace state for catch-up.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "tool": {"type": "string", "description": "Client tool: claude-cli, gemini-cli, vscode"},
            },
        },
    },
    "pa_get_briefing_snapshot": {
        "name": "pa_get_briefing_snapshot",
        "description": "Pure idempotent read of the catch-up briefing (active tasks, last-24h actions, due nudges, unresolved conflicts, last-session summary). Writes NOTHING — no session row is created.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
            },
        },
    },
    "pa_end_session": {
        "name": "pa_end_session",
        "description": "End the current PA session with a summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "integer"},
                "summary": {"type": "string"},
            },
            "required": ["session_id"],
        },
    },
    "pa_search": {
        "name": "pa_search",
        "description": "Full-text search across tasks and actions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "query": {"type": "string", "description": "Search query (FTS5 syntax supported)"},
                "mode": {"type": "string", "enum": ["keyword", "semantic"], "description": "Search mode (semantic falls back to keyword in v1)"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
            "required": ["query"],
        },
    },
    "pa_sync_confluence": {
        "name": "pa_sync_confluence",
        "description": "Sync tasks from Confluence. Read-only pull.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "source_config": {
                    "type": "object",
                    "properties": {
                        "base_url_env": {"type": "string", "description": "Env var name for base URL"},
                        "token_env": {"type": "string", "description": "Env var name for bearer token"},
                        "strategy": {"type": "string", "enum": ["label", "parent", "cql"]},
                        "query": {"type": "string", "description": "Label name, parent ID, or CQL query"},
                    },
                },
            },
        },
    },
    "pa_sync_jira": {
        "name": "pa_sync_jira",
        "description": "Sync tasks from Jira. Read-only pull.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "source_config": {
                    "type": "object",
                    "properties": {
                        "base_url_env": {"type": "string", "description": "Env var name for base URL"},
                        "token_env": {"type": "string", "description": "Env var name for bearer token"},
                        "strategy": {"type": "string", "enum": ["assigned", "jql", "filter"]},
                        "query": {"type": "string", "description": "JQL query, filter ID, or blank for assigned"},
                    },
                },
            },
        },
    },
    "pa_get_conflicts": {
        "name": "pa_get_conflicts",
        "description": "Get unresolved sync conflicts for the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
            },
        },
    },
    "pa_resolve_conflict": {
        "name": "pa_resolve_conflict",
        "description": "Resolve a sync conflict by keeping local or accepting remote.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sync_state_id": {"type": "integer"},
                "resolution": {"type": "string", "enum": ["keep_local", "accept_remote"]},
            },
            "required": ["sync_state_id", "resolution"],
        },
    },
    "pa_get_preferences": {
        "name": "pa_get_preferences",
        "description": "Get user preferences, optionally filtered by workspace and category.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "category": {"type": "string", "enum": ["routing", "writing", "presentation", "communication", "tool"]},
            },
        },
    },
    "pa_update_preference": {
        "name": "pa_update_preference",
        "description": "Update or create a preference. Increments signal_count if same key exists.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
                "category": {"type": "string", "enum": ["routing", "writing", "presentation", "communication", "tool"]},
                "workspace": {"type": "string", "description": "Workspace-specific (omit for global)"},
            },
            "required": ["key", "value", "category"],
        },
    },
    "pa_clear_preference": {
        "name": "pa_clear_preference",
        "description": "Delete a preference.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "workspace": {"type": "string"},
            },
            "required": ["key"],
        },
    },
    "pa_health": {
        "name": "pa_health",
        "description": "Health check — DB size, task count, sync timestamps, feature flags.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    "pa_set_sync_config": {
        "name": "pa_set_sync_config",
        "description": "Store sync configuration for a source (so user does not provide it each call).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
                "source": {"type": "string", "enum": ["confluence", "jira"]},
                "config": {
                    "type": "object",
                    "properties": {
                        "base_url_env": {"type": "string"},
                        "token_env": {"type": "string"},
                        "strategy": {"type": "string"},
                        "query": {"type": "string"},
                    },
                    "required": ["base_url_env", "token_env", "strategy"],
                },
            },
            "required": ["source", "config"],
        },
    },
    "pa_get_sync_configs": {
        "name": "pa_get_sync_configs",
        "description": "Get sync configurations for the workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string"},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 over stdio (MCP-compatible transport)
# ---------------------------------------------------------------------------

class JsonRpcServer:
    """Raw JSON-RPC 2.0 server implementing MCP protocol over stdio."""

    def __init__(self, tools: PATools):
        self.tools = tools
        self._method_map = {
            # MCP lifecycle
            "initialize": self._handle_initialize,
            "initialized": self._handle_initialized,
            "shutdown": self._handle_shutdown,
            # MCP tool methods
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            # MCP ping
            "ping": self._handle_ping,
        }

    def run(self):
        """Main loop — read JSON-RPC messages from stdin, write responses to stdout."""
        _log("PA Server started. Listening on stdio.")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                _write_error(None, -32700, f"Parse error: {e}")
                continue

            msg_id = msg.get("id")
            method = msg.get("method", "")

            # Notifications (no id) — just ack
            if msg_id is None and method == "notifications/initialized":
                continue
            if msg_id is None:
                continue

            handler = self._method_map.get(method)
            if handler:
                try:
                    result = handler(msg.get("params", {}))
                    _write_result(msg_id, result)
                except Exception as e:
                    _log(f"Error in {method}: {e}\n{traceback.format_exc()}")
                    _write_error(msg_id, -32603, str(e))
            else:
                _write_error(msg_id, -32601, f"Method not found: {method}")

    def _handle_initialize(self, params: dict) -> dict:
        # MCP protocol version advertised in `initialize`. Claude Code negotiates
        # the version at runtime, so this is the server's preferred-spec floor.
        # Currency anchor lives in the module docstring (FRESHNESS:v1, subject
        # `mcp-protocol-version`); the S041 evergreen loop nags on drift.
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "pa-server",
                "version": "1.0.0",
            },
        }

    def _handle_initialized(self, params: dict) -> dict:
        return {}

    def _handle_shutdown(self, params: dict) -> dict:
        return {}

    def _handle_ping(self, params: dict) -> dict:
        return {}

    def _handle_tools_list(self, params: dict) -> dict:
        return {"tools": list(TOOL_SCHEMAS.values())}

    def _handle_tools_call(self, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        # (1) The tool must be a REGISTERED tool (in TOOL_SCHEMAS) — not just any
        # attribute reachable via getattr. Unknown / unregistered -> isError=true.
        schema_entry = TOOL_SCHEMAS.get(name)
        tool_fn = getattr(self.tools, name, None)
        if schema_entry is None or not callable(tool_fn):
            return self._error_result(f"Unknown tool: {name}")

        # (2) Pre-dispatch JSON-Schema validation (the ~20-line stdlib guard in
        # pa_core.validate_arguments). A schema violation is rejected BEFORE the
        # handler runs, so pa-core is never invoked on malformed arguments
        # (T-ADP-1). validate_arguments RAISES ValidationError on the first
        # problem -> we map it to isError=true below.
        try:
            pa_core.validate_arguments(schema_entry.get("inputSchema"), arguments)
        except ValidationError as e:
            return self._error_result(str(e), code=e.code)

        # (3) Dispatch. Handlers RAISE pa_core typed errors; the dispatcher's
        # `except` maps them to isError=true (no more isError:False-wrapped error
        # dicts — BUG-1 fix).
        try:
            result = tool_fn(arguments)
            return {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "isError": False,
            }
        except PaError as e:
            _log(f"Tool error in {name}: {e} (code={e.code})")
            return self._error_result(str(e), code=e.code)
        except Exception as e:
            _log(f"Tool error in {name}: {e}\n{traceback.format_exc()}")
            return self._error_result(str(e))

    @staticmethod
    def _error_result(message: str, code: str = "error") -> dict:
        """Build an MCP tools/call error result with isError=true and a typed
        error payload."""
        return {
            "content": [{"type": "text", "text": json.dumps({"error": message, "code": code})}],
            "isError": True,
        }


def _write_result(msg_id, result):
    """Write a JSON-RPC success response."""
    response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _write_error(msg_id, code, message):
    """Write a JSON-RPC error response."""
    response = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _log(msg: str):
    """Log to stderr (not stdout, which is the JSON-RPC transport)."""
    sys.stderr.write(f"[pa-server] {msg}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ws_path = resolve_workspace()
    ws_id = workspace_id_from_path(ws_path)
    db_path = ws_path / "pa.db"

    _log(f"Workspace: {ws_path}")
    _log(f"Workspace ID: {ws_id}")
    _log(f"Database: {db_path}")

    conn = init_db(db_path)
    tools = PATools(conn, ws_path, ws_id)
    server = JsonRpcServer(tools)

    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
        _log("PA Server stopped.")


if __name__ == "__main__":
    main()
