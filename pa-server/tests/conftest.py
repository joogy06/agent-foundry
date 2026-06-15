"""Shared pytest fixtures for the pa-server characterization suite (AMY M0a / WP-1).

These fixtures load the CURRENT, pre-rework `pa_server.py` IN-PROCESS via
``SourceFileLoader`` (mirroring ``skills/cross-project-mail/tests/conftest.py``)
against a TEMP SQLite DB. They pin the *current observable behavior* of the
existing ~18-20 tools so the WP-2/WP-4 rework is verified against an explicit
baseline. Nothing here writes to the developer's real workspace DB.

Stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import sys
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec
from pathlib import Path

import pytest

# pa-server/  (parent of tests/)
PA_SERVER_ROOT = Path(__file__).resolve().parent.parent
PA_SERVER_PATH = PA_SERVER_ROOT / "pa_server.py"


def _load_pa_server():
    """Import pa_server.py fresh as a module named 'pa_server'.

    The file HAS a .py extension, but we use SourceFileLoader explicitly so the
    import is independent of sys.path / CWD and matches the cross-project-mail
    in-process test idiom. Re-loading is cheap and side-effect-free: importing
    the module does NOT run main() (guarded by __name__ == "__main__").
    """
    loader = SourceFileLoader("pa_server", str(PA_SERVER_PATH))
    spec = spec_from_loader("pa_server", loader)
    mod = module_from_spec(spec)
    sys.modules["pa_server"] = mod
    loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def pa_server_module():
    """The loaded pa_server module (session-scoped; module load is stateless)."""
    return _load_pa_server()


@pytest.fixture
def workspace(tmp_path):
    """A fresh temp workspace directory for one test (holds pa.db)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def conn(pa_server_module, workspace):
    """A temp-DB SQLite connection bootstrapped by the REAL init_db().

    Uses pa_server.init_db so the schema/FTS/index/trigger DDL under test is the
    production DDL, not a hand-rolled copy. Closed at teardown.
    """
    db_path = workspace / "pa.db"
    c = pa_server_module.init_db(db_path)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def ws_id(pa_server_module, workspace):
    """The deterministic workspace id the server derives from the path."""
    return pa_server_module.workspace_id_from_path(workspace)


@pytest.fixture
def tools(pa_server_module, conn, workspace, ws_id):
    """A PATools instance bound to the temp DB + temp workspace.

    Construction calls _ensure_workspace(), so the workspaces row exists and FK
    constraints on tasks/actions/sessions are satisfiable.
    """
    return pa_server_module.PATools(conn, workspace, ws_id)


@pytest.fixture
def server(pa_server_module, tools):
    """A JsonRpcServer wrapping the temp-DB PATools — exercises the dispatcher
    (tools/call), which is where the isError-wrapping behavior lives."""
    return pa_server_module.JsonRpcServer(tools)
