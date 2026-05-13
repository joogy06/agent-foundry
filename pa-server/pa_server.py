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
"""

import json
import os
import sys
import sqlite3
import hashlib
import traceback
from datetime import datetime
from pathlib import Path

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
    """Create/open SQLite DB, run migrations, enable WAL."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    conn.executescript(FTS_SQL)
    conn.executescript(INDEXES_SQL)
    conn.executescript(TRIGGERS_SQL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

class PATools:
    """All 20 MCP tool implementations."""

    def __init__(self, conn: sqlite3.Connection, ws_path: Path, ws_id: str):
        self.conn = conn
        self.ws_path = ws_path
        self.ws_id = ws_id
        self._ensure_workspace()

    def _ensure_workspace(self):
        """Ensure workspace record exists."""
        row = self.conn.execute("SELECT id FROM workspaces WHERE id = ?", (self.ws_id,)).fetchone()
        if not row:
            self.conn.execute(
                "INSERT INTO workspaces (id, name, project_path, last_accessed) VALUES (?, ?, ?, ?)",
                (self.ws_id, self.ws_path.name, str(self.ws_path), _now())
            )
            self.conn.commit()
        else:
            self.conn.execute("UPDATE workspaces SET last_accessed = ? WHERE id = ?", (_now(), self.ws_id))
            self.conn.commit()

    # -- Task Management --

    def pa_create_task(self, params: dict) -> dict:
        workspace = params.get("workspace", self.ws_id)
        title = params["title"]
        description = params.get("description")
        priority = params.get("priority", "medium")
        source = params.get("source", "local")
        remote_id = params.get("remote_id")
        remote_url = params.get("remote_url")
        tags = params.get("tags")
        if isinstance(tags, list):
            tags = json.dumps(tags)

        cur = self.conn.execute(
            """INSERT INTO tasks (workspace_id, title, description, priority, source, remote_id, remote_url, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (workspace, title, description, priority, source, remote_id, remote_url, tags)
        )
        self.conn.commit()
        task_id = cur.lastrowid
        return {"id": task_id, "title": title, "status": "new", "created_at": _now()}

    def pa_update_task(self, params: dict) -> dict:
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
                values.append(_now())
            elif status in ("done", "failed", "cancelled"):
                updates.append("completed_at = ?")
                values.append(_now())

        updates.append("updated_at = ?")
        values.append(_now())
        values.append(task_id)

        self.conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values)
        self.conn.commit()

        row = self.conn.execute("SELECT id, title, status, updated_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row:
            return dict(row)
        return {"error": f"Task {task_id} not found"}

    def pa_query_tasks(self, params: dict) -> list:
        workspace = params.get("workspace", self.ws_id)
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
        sql = f"SELECT id, title, status, priority, source, remote_id, tags, updated_at FROM tasks WHERE {' AND '.join(conditions)} ORDER BY updated_at DESC LIMIT ?"
        values.append(limit)

        rows = self.conn.execute(sql, values).fetchall()
        return [dict(r) for r in rows]

    def pa_get_task(self, params: dict) -> dict:
        task_id = params["id"]
        task = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return {"error": f"Task {task_id} not found"}

        actions = self.conn.execute(
            "SELECT id, action, agent, skill, result, artifacts, created_at FROM actions WHERE task_id = ? ORDER BY created_at DESC LIMIT 20",
            (task_id,)
        ).fetchall()

        result = dict(task)
        result["recent_actions"] = [dict(a) for a in actions]
        return result

    # -- Action Logging --

    def pa_log_action(self, params: dict) -> dict:
        workspace = params.get("workspace", self.ws_id)
        task_id = params.get("task_id")
        action = params["action"]
        agent = params.get("agent")
        skill = params.get("skill")
        result = params.get("result")
        artifacts = params.get("artifacts")
        if isinstance(artifacts, list):
            artifacts = json.dumps(artifacts)

        cur = self.conn.execute(
            """INSERT INTO actions (task_id, workspace_id, action, agent, skill, result, artifacts)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_id, workspace, action, agent, skill, result, artifacts)
        )
        self.conn.commit()
        return {"id": cur.lastrowid, "created_at": _now()}

    # -- Session Management --

    def pa_start_session(self, params: dict) -> dict:
        workspace = params.get("workspace", self.ws_id)
        tool = params.get("tool", "claude-cli")

        # Create session
        cur = self.conn.execute(
            "INSERT INTO sessions (workspace_id, tool) VALUES (?, ?)",
            (workspace, tool)
        )
        self.conn.commit()
        session_id = cur.lastrowid

        # Get active tasks
        active_tasks = self.conn.execute(
            "SELECT id, title, status, priority, assigned_agent, updated_at FROM tasks WHERE workspace_id = ? AND status NOT IN ('done','failed','cancelled') ORDER BY priority, updated_at DESC",
            (workspace,)
        ).fetchall()

        # Get recent actions (last 24h)
        recent_actions = self.conn.execute(
            "SELECT a.id, a.task_id, a.action, a.agent, a.result, a.created_at FROM actions a WHERE a.workspace_id = ? AND a.created_at >= datetime('now', '-1 day') ORDER BY a.created_at DESC LIMIT 10",
            (workspace,)
        ).fetchall()

        # Get unresolved conflicts
        conflicts = self.conn.execute(
            "SELECT ss.id, ss.source, ss.remote_id, ss.status, ss.conflict_detail FROM sync_state ss WHERE ss.workspace_id = ? AND ss.status = 'conflict'",
            (workspace,)
        ).fetchall()

        # Get last session summary
        last_session = self.conn.execute(
            "SELECT summary, ended_at FROM sessions WHERE workspace_id = ? AND id != ? ORDER BY id DESC LIMIT 1",
            (workspace, session_id)
        ).fetchone()

        return {
            "session_id": session_id,
            "workspace": workspace,
            "active_tasks": [dict(t) for t in active_tasks],
            "recent_actions": [dict(a) for a in recent_actions],
            "unresolved_conflicts": [dict(c) for c in conflicts],
            "last_session_summary": dict(last_session) if last_session else None,
        }

    def pa_end_session(self, params: dict) -> dict:
        session_id = params["session_id"]
        summary = params.get("summary", "")

        self.conn.execute(
            "UPDATE sessions SET ended_at = ?, summary = ? WHERE id = ?",
            (_now(), summary, session_id)
        )
        self.conn.commit()
        return {"session_id": session_id, "ended_at": _now()}

    # -- Search --

    def pa_search(self, params: dict) -> list:
        workspace = params.get("workspace", self.ws_id)
        query = params["query"]
        mode = params.get("mode", "keyword")
        limit = params.get("limit", 20)

        if mode == "semantic":
            # v2 feature — fall back to keyword
            pass

        results = []

        # Search tasks via FTS5
        task_rows = self.conn.execute(
            """SELECT t.id, t.title, snippet(tasks_fts, 1, '<b>', '</b>', '...', 32) as snippet,
                      rank
               FROM tasks_fts
               JOIN tasks t ON t.id = tasks_fts.rowid
               WHERE tasks_fts MATCH ? AND t.workspace_id = ?
               ORDER BY rank
               LIMIT ?""",
            (query, workspace, limit)
        ).fetchall()

        for row in task_rows:
            results.append({
                "type": "task",
                "id": row["id"],
                "title": row["title"],
                "snippet": row["snippet"],
                "relevance_score": abs(row["rank"]) if row["rank"] else 0,
            })

        # Search actions via FTS5
        remaining = limit - len(results)
        if remaining > 0:
            action_rows = self.conn.execute(
                """SELECT a.id, a.task_id, snippet(actions_fts, 0, '<b>', '</b>', '...', 32) as snippet,
                          rank
                   FROM actions_fts
                   JOIN actions a ON a.id = actions_fts.rowid
                   WHERE actions_fts MATCH ? AND a.workspace_id = ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, workspace, remaining)
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

    # -- Sync --

    def pa_sync_confluence(self, params: dict) -> dict:
        workspace = params.get("workspace", self.ws_id)
        source_config = params.get("source_config", {})

        base_url_env = source_config.get("base_url_env", "CONFLUENCE_BASE")
        token_env = source_config.get("token_env", "CONFLUENCE_TOKEN")
        strategy = source_config.get("strategy", "label")
        query = source_config.get("query", "")

        base_url = os.environ.get(base_url_env)
        token = os.environ.get(token_env)

        if not base_url or not token:
            return {
                "error": f"Missing env vars: {base_url_env}={'set' if base_url else 'missing'}, {token_env}={'set' if token else 'missing'}",
                "pulled": 0, "new_items": 0, "updated_items": 0, "conflicts": 0
            }

        # Attempt HTTP sync
        try:
            import urllib.request
            import urllib.error

            items = _confluence_fetch(base_url, token, strategy, query)
            new_count, updated_count, conflict_count = 0, 0, 0

            for item in items:
                remote_id = str(item.get("id", ""))
                title = item.get("title", "Untitled")
                version = item.get("version", {}).get("number", 1) if isinstance(item.get("version"), dict) else item.get("version", 1)
                url = f"{base_url}/pages/viewpage.action?pageId={remote_id}"
                content_hash = hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()[:16]

                # Check sync state
                existing = self.conn.execute(
                    "SELECT id, remote_version, local_hash FROM sync_state WHERE workspace_id = ? AND source = 'confluence' AND remote_id = ?",
                    (workspace, remote_id)
                ).fetchone()

                if not existing:
                    # New item — create task
                    cur = self.conn.execute(
                        "INSERT INTO tasks (workspace_id, title, source, remote_id, remote_url) VALUES (?, ?, 'confluence', ?, ?)",
                        (workspace, title, remote_id, url)
                    )
                    self.conn.execute(
                        "INSERT INTO sync_state (workspace_id, source, remote_id, remote_url, remote_version, local_hash, last_synced) VALUES (?, 'confluence', ?, ?, ?, ?, ?)",
                        (workspace, remote_id, url, version, content_hash, _now())
                    )
                    new_count += 1
                elif existing["local_hash"] != content_hash:
                    # Changed remotely — check for local modifications
                    task = self.conn.execute(
                        "SELECT id, updated_at FROM tasks WHERE workspace_id = ? AND source = 'confluence' AND remote_id = ?",
                        (workspace, remote_id)
                    ).fetchone()

                    if task:
                        # Update task title, mark sync state
                        self.conn.execute(
                            "UPDATE tasks SET title = ?, updated_at = ? WHERE id = ?",
                            (title, _now(), task["id"])
                        )
                    self.conn.execute(
                        "UPDATE sync_state SET remote_version = ?, local_hash = ?, last_synced = ?, status = 'synced' WHERE id = ?",
                        (version, content_hash, _now(), existing["id"])
                    )
                    updated_count += 1
                else:
                    # No change — update last_synced
                    self.conn.execute(
                        "UPDATE sync_state SET last_synced = ? WHERE id = ?",
                        (_now(), existing["id"])
                    )

            self.conn.commit()
            return {
                "pulled": len(items),
                "new_items": new_count,
                "updated_items": updated_count,
                "conflicts": conflict_count,
            }

        except Exception as e:
            return {"error": str(e), "pulled": 0, "new_items": 0, "updated_items": 0, "conflicts": 0}

    def pa_sync_jira(self, params: dict) -> dict:
        workspace = params.get("workspace", self.ws_id)
        source_config = params.get("source_config", {})

        base_url_env = source_config.get("base_url_env", "JIRA_BASE")
        token_env = source_config.get("token_env", "JIRA_TOKEN")
        strategy = source_config.get("strategy", "assigned")
        query = source_config.get("query", "")

        base_url = os.environ.get(base_url_env)
        token = os.environ.get(token_env)

        if not base_url or not token:
            return {
                "error": f"Missing env vars: {base_url_env}={'set' if base_url else 'missing'}, {token_env}={'set' if token else 'missing'}",
                "pulled": 0, "new_items": 0, "updated_items": 0, "conflicts": 0
            }

        try:
            import urllib.request
            import urllib.error

            items = _jira_fetch(base_url, token, strategy, query)
            new_count, updated_count, conflict_count = 0, 0, 0

            for item in items:
                remote_id = item.get("key", "")
                title = item.get("fields", {}).get("summary", "Untitled")
                status_name = item.get("fields", {}).get("status", {}).get("statusCategory", {}).get("key", "new")
                pa_status = _jira_status_map(status_name)
                updated = item.get("fields", {}).get("updated", "")
                url = f"{base_url}/browse/{remote_id}"
                content_hash = hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()[:16]

                existing = self.conn.execute(
                    "SELECT id, local_hash FROM sync_state WHERE workspace_id = ? AND source = 'jira' AND remote_id = ?",
                    (workspace, remote_id)
                ).fetchone()

                if not existing:
                    priority_map = {"Highest": "critical", "High": "high", "Medium": "medium", "Low": "low", "Lowest": "low"}
                    jira_priority = item.get("fields", {}).get("priority", {}).get("name", "Medium")
                    pa_priority = priority_map.get(jira_priority, "medium")

                    cur = self.conn.execute(
                        "INSERT INTO tasks (workspace_id, title, status, priority, source, remote_id, remote_url) VALUES (?, ?, ?, ?, 'jira', ?, ?)",
                        (workspace, title, pa_status, pa_priority, remote_id, url)
                    )
                    self.conn.execute(
                        "INSERT INTO sync_state (workspace_id, source, remote_id, remote_url, local_hash, last_synced) VALUES (?, 'jira', ?, ?, ?, ?)",
                        (workspace, remote_id, url, content_hash, _now())
                    )
                    new_count += 1
                elif existing["local_hash"] != content_hash:
                    task = self.conn.execute(
                        "SELECT id FROM tasks WHERE workspace_id = ? AND source = 'jira' AND remote_id = ?",
                        (workspace, remote_id)
                    ).fetchone()
                    if task:
                        self.conn.execute(
                            "UPDATE tasks SET title = ?, status = ?, updated_at = ? WHERE id = ?",
                            (title, pa_status, _now(), task["id"])
                        )
                    self.conn.execute(
                        "UPDATE sync_state SET local_hash = ?, last_synced = ?, status = 'synced' WHERE id = ?",
                        (content_hash, _now(), existing["id"])
                    )
                    updated_count += 1
                else:
                    self.conn.execute(
                        "UPDATE sync_state SET last_synced = ? WHERE id = ?",
                        (_now(), existing["id"])
                    )

            self.conn.commit()
            return {
                "pulled": len(items),
                "new_items": new_count,
                "updated_items": updated_count,
                "conflicts": conflict_count,
            }

        except Exception as e:
            return {"error": str(e), "pulled": 0, "new_items": 0, "updated_items": 0, "conflicts": 0}

    def pa_get_conflicts(self, params: dict) -> list:
        workspace = params.get("workspace", self.ws_id)
        rows = self.conn.execute(
            """SELECT ss.id as sync_state_id, t.id as task_id, ss.source as remote_source,
                      ss.status, ss.conflict_detail, ss.last_synced as detected_at
               FROM sync_state ss
               LEFT JOIN tasks t ON t.workspace_id = ss.workspace_id AND t.source = ss.source AND t.remote_id = ss.remote_id
               WHERE ss.workspace_id = ? AND ss.status = 'conflict'""",
            (workspace,)
        ).fetchall()
        return [dict(r) for r in rows]

    def pa_resolve_conflict(self, params: dict) -> dict:
        sync_state_id = params["sync_state_id"]
        resolution = params["resolution"]  # 'keep_local' or 'accept_remote'

        ss = self.conn.execute(
            "SELECT * FROM sync_state WHERE id = ?", (sync_state_id,)
        ).fetchone()
        if not ss:
            return {"error": f"Sync state {sync_state_id} not found"}

        if resolution == "accept_remote" and ss["conflict_detail"]:
            try:
                detail = json.loads(ss["conflict_detail"])
                task = self.conn.execute(
                    "SELECT id FROM tasks WHERE workspace_id = ? AND source = ? AND remote_id = ?",
                    (ss["workspace_id"], ss["source"], ss["remote_id"])
                ).fetchone()
                if task and "remote" in detail:
                    remote_data = detail["remote"]
                    if "title" in remote_data:
                        self.conn.execute(
                            "UPDATE tasks SET title = ?, updated_at = ? WHERE id = ?",
                            (remote_data["title"], _now(), task["id"])
                        )
            except (json.JSONDecodeError, KeyError):
                pass

        self.conn.execute(
            "UPDATE sync_state SET status = 'synced', conflict_detail = NULL, last_synced = ? WHERE id = ?",
            (_now(), sync_state_id)
        )
        self.conn.commit()

        task = self.conn.execute(
            "SELECT id FROM tasks WHERE workspace_id = ? AND source = ? AND remote_id = ?",
            (ss["workspace_id"], ss["source"], ss["remote_id"])
        ).fetchone()
        return {"resolved": True, "task_id": task["id"] if task else None, "updated_at": _now()}

    # -- Preferences --

    def pa_get_preferences(self, params: dict) -> list:
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
        rows = self.conn.execute(
            f"SELECT key, value, confidence, signal_count, category FROM preferences WHERE {where} ORDER BY signal_count DESC",
            values
        ).fetchall()
        return [dict(r) for r in rows]

    def pa_update_preference(self, params: dict) -> dict:
        key = params["key"]
        value = params["value"]
        category = params["category"]
        workspace = params.get("workspace")

        existing = self.conn.execute(
            "SELECT id, signal_count, confidence FROM preferences WHERE key = ? AND (workspace_id = ? OR (workspace_id IS NULL AND ? IS NULL))",
            (key, workspace, workspace)
        ).fetchone()

        if existing:
            new_count = existing["signal_count"] + 1
            # Confidence increases: 1 signal=0.3, 2=0.5, 3+=0.8, 5+=0.95
            if new_count >= 5:
                confidence = 0.95
            elif new_count >= 3:
                confidence = 0.8
            elif new_count >= 2:
                confidence = 0.5
            else:
                confidence = 0.3

            self.conn.execute(
                "UPDATE preferences SET value = ?, signal_count = ?, confidence = ?, updated_at = ? WHERE id = ?",
                (value, new_count, confidence, _now(), existing["id"])
            )
            self.conn.commit()
            return {"key": key, "value": value, "confidence": confidence, "signal_count": new_count}
        else:
            self.conn.execute(
                "INSERT INTO preferences (workspace_id, key, value, category, confidence, signal_count) VALUES (?, ?, ?, ?, 0.3, 1)",
                (workspace, key, value, category)
            )
            self.conn.commit()
            return {"key": key, "value": value, "confidence": 0.3, "signal_count": 1}

    def pa_clear_preference(self, params: dict) -> dict:
        key = params["key"]
        workspace = params.get("workspace")

        self.conn.execute(
            "DELETE FROM preferences WHERE key = ? AND (workspace_id = ? OR (workspace_id IS NULL AND ? IS NULL))",
            (key, workspace, workspace)
        )
        self.conn.commit()
        return {"deleted": True}

    # -- Health --

    def pa_health(self, params: dict) -> dict:
        db_path = self.ws_path / "pa.db"
        db_size = db_path.stat().st_size if db_path.exists() else 0

        task_count = self.conn.execute("SELECT COUNT(*) as c FROM tasks WHERE workspace_id = ?", (self.ws_id,)).fetchone()["c"]

        confluence_sync = self.conn.execute(
            "SELECT MAX(last_synced) as ls FROM sync_state WHERE workspace_id = ? AND source = 'confluence'",
            (self.ws_id,)
        ).fetchone()
        jira_sync = self.conn.execute(
            "SELECT MAX(last_synced) as ls FROM sync_state WHERE workspace_id = ? AND source = 'jira'",
            (self.ws_id,)
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

    # -- Sync Configuration --

    def pa_set_sync_config(self, params: dict) -> dict:
        workspace = params.get("workspace", self.ws_id)
        source = params["source"]
        config = params.get("config", {})

        self.conn.execute(
            """INSERT INTO sync_configs (workspace_id, source, base_url_env, token_env, strategy, query)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(workspace_id, source) DO UPDATE SET
               base_url_env = excluded.base_url_env,
               token_env = excluded.token_env,
               strategy = excluded.strategy,
               query = excluded.query""",
            (workspace, source, config.get("base_url_env", ""), config.get("token_env", ""),
             config.get("strategy", ""), config.get("query", ""))
        )
        self.conn.commit()
        return {"workspace": workspace, "source": source, "configured": True}

    def pa_get_sync_configs(self, params: dict) -> list:
        workspace = params.get("workspace", self.ws_id)
        rows = self.conn.execute(
            """SELECT sc.source, sc.strategy, sc.query,
                      (SELECT MAX(last_synced) FROM sync_state ss WHERE ss.workspace_id = sc.workspace_id AND ss.source = sc.source) as last_synced
               FROM sync_configs sc
               WHERE sc.workspace_id = ? AND sc.enabled = 1""",
            (workspace,)
        ).fetchall()
        return [dict(r) for r in rows]


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


def _confluence_fetch(base_url: str, token: str, strategy: str, query: str) -> list:
    """Fetch Confluence items based on strategy."""
    if strategy == "label":
        cql = f'label = "{query}" AND type = "page"'
    elif strategy == "parent":
        cql = f'ancestor = {query} AND type = "page"'
    elif strategy == "cql":
        cql = query
    else:
        cql = f'type = "page" ORDER BY lastModified DESC'

    import urllib.parse
    url = f"{base_url}/rest/api/search"
    data = _http_get_json(url, token, {"cql": cql, "limit": "50", "expand": "version"})
    return data.get("results", [])


def _jira_fetch(base_url: str, token: str, strategy: str, query: str) -> list:
    """Fetch Jira issues based on strategy."""
    if strategy == "assigned":
        jql = query if query else "assignee = currentUser() ORDER BY updated DESC"
    elif strategy == "jql":
        jql = query
    elif strategy == "filter":
        jql = f"filter = {query}"
    else:
        jql = "assignee = currentUser() ORDER BY updated DESC"

    url = f"{base_url}/rest/api/2/search"
    data = _http_get_json(url, token, {"jql": jql, "maxResults": "50", "fields": "summary,status,priority,updated"})
    return data.get("issues", [])


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
    """Current UTC timestamp in ISO format."""
    from datetime import timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        return {
            "protocolVersion": "2024-11-05",
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

        tool_fn = getattr(self.tools, name, None)
        if not tool_fn:
            return {
                "content": [{"type": "text", "text": json.dumps({"error": f"Unknown tool: {name}"})}],
                "isError": True,
            }

        try:
            result = tool_fn(arguments)
            return {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "isError": False,
            }
        except Exception as e:
            _log(f"Tool error in {name}: {e}\n{traceback.format_exc()}")
            return {
                "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
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
