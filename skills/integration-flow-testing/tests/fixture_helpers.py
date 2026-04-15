#!/usr/bin/env python3
"""fixture_helpers.py — shared builders for v1.1 tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WIRING_QUERY_FIXTURES = SCRIPT_DIR.parent.parent / "wiring-query" / "fixtures"
sys.path.insert(0, str(WIRING_QUERY_FIXTURES))


def write_snapshot(project_dir: Path):
    from make_fixture_snapshot import write_fixture  # type: ignore
    return write_fixture(project_dir, snapshot_generation=9)


def write_contract_map(project_dir: Path, contents: dict):
    (project_dir / "progress").mkdir(parents=True, exist_ok=True)
    import yaml
    (project_dir / "progress" / "contract-map.yaml").write_text(
        yaml.safe_dump(contents, sort_keys=True)
    )


DEFAULT_MAP = {
    "schema_version": "1.0.0",
    "revision": 3,
    "components": [
        {
            "id": "auth-service",
            "integration_points": [
                {"with": "user-service", "direction": "outbound",
                 "protocol": "http",
                 "endpoint": "GET /users/{id}",
                 "failure_mode": "404 when user unknown"},
            ],
        },
        {"id": "user-service"},
        {"id": "db"},
        {"id": "audit-log"},
    ],
    "flows": [
        {
            "id": "FLOW-LOGIN",
            "name": "login-success",
            "path": ["auth-service", "user-service", "db"],
            "entry_input": {"component": "auth-service",
                             "input": "session_token"},
            "terminal_output": {"component": "db"},
            "expected_outcome": "200",
            "priority": "critical",
        },
    ],
}
