#!/usr/bin/env python3
"""test_gates_intent_map_fresh.py — coverage for G_INTENT_MAP_FRESH (S032 WP-0).

Verifies the 3-way exit contract from design §4.2:

    0 = PASS    — intent-map present, wiring_hash + dep_lock_hash both match
    2 = FAIL    — file missing OR hash drift
    3 = ENV_ERROR — referenced wiring snapshot / lockfile absent (auto-rewind)

Run:
    pytest /path/to/project/skills/_meta/tests/test_gates_intent_map_fresh.py -v
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_META_DIR = Path(__file__).resolve().parent.parent


def _gates_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Invoke gates.py as a subprocess. Mirror live caller flow (CB3)."""
    return subprocess.run(
        [sys.executable, str(_META_DIR / "gates.py"), "G_INTENT_MAP_FRESH", *args],
        capture_output=True,
        text=True,
    )


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _seed_happy_path(root: Path, run_id: str = "test-run-1") -> tuple[str, str]:
    """Lay down a wiring snapshot, lockfile, and intent-map whose declared
    hashes match. Returns (wiring_hash, dep_lock_hash).
    """
    (root / ".ledger" / "evo" / "runs" / run_id).mkdir(parents=True, exist_ok=True)
    (root / ".wiring").mkdir(parents=True, exist_ok=True)

    wiring_hash = "a" * 40
    wiring_path = root / ".wiring" / "latest.json"
    wiring_path.write_text(json.dumps({
        "schema_version": "1.0.0",
        "workspace_tree_hash": wiring_hash,
    }))

    lock_path = root / "poetry.lock"
    lock_path.write_text("# poetry lockfile\ncontent-hash = \"deadbeef\"\n")
    dep_lock_hash = _sha256(lock_path)

    intent_map = root / ".ledger" / "evo" / "runs" / run_id / "intent-map.yaml"
    intent_map.write_text(
        f"schema_version: \"1.0.0\"\n"
        f"run_id: {run_id}\n"
        f"wiring_hash: \"{wiring_hash}\"\n"
        f"dep_lock_hash: \"{dep_lock_hash}\"\n"
    )
    return wiring_hash, dep_lock_hash


# ---------------------------------------------------------------------------
# Exit-code coverage
# ---------------------------------------------------------------------------


def test_pass_happy_path(tmp_path: Path) -> None:
    """0 PASS — fresh intent-map with matching hashes."""
    _seed_happy_path(tmp_path, "test-run-1")
    cp = _gates_cli([str(tmp_path), "test-run-1"])
    assert cp.returncode == 0, f"stdout={cp.stdout} stderr={cp.stderr}"
    assert "G_INTENT_MAP_FRESH_PASS" in cp.stdout


def test_fail_missing_intent_map(tmp_path: Path) -> None:
    """2 FAIL — intent-map.yaml absent at expected path."""
    # No seeding — directory is empty.
    cp = _gates_cli([str(tmp_path), "nonexistent-run"])
    assert cp.returncode == 2, f"stdout={cp.stdout} stderr={cp.stderr}"
    assert "intent-map.yaml not found" in cp.stderr


def test_fail_wiring_hash_drift(tmp_path: Path) -> None:
    """2 FAIL — declared wiring_hash != current workspace_tree_hash."""
    _seed_happy_path(tmp_path, "test-run-1")
    # Mutate the snapshot's workspace_tree_hash to force drift
    wiring_path = tmp_path / ".wiring" / "latest.json"
    wiring_path.write_text(json.dumps({
        "schema_version": "1.0.0",
        "workspace_tree_hash": "b" * 40,
    }))
    cp = _gates_cli([str(tmp_path), "test-run-1"])
    assert cp.returncode == 2, f"stdout={cp.stdout} stderr={cp.stderr}"
    assert "wiring_hash drift" in cp.stderr


def test_fail_dep_lock_hash_drift(tmp_path: Path) -> None:
    """2 FAIL — declared dep_lock_hash != current lockfile sha256."""
    _seed_happy_path(tmp_path, "test-run-1")
    # Append to lockfile to change its hash
    (tmp_path / "poetry.lock").write_text(
        "# poetry lockfile (modified)\ncontent-hash = \"freshhash\"\n"
    )
    cp = _gates_cli([str(tmp_path), "test-run-1"])
    assert cp.returncode == 2, f"stdout={cp.stdout} stderr={cp.stderr}"
    assert "dep_lock_hash drift" in cp.stderr


def test_env_error_no_wiring_snapshot(tmp_path: Path) -> None:
    """3 ENV_ERROR — wiring snapshot absent triggers auto-rewind."""
    _seed_happy_path(tmp_path, "test-run-1")
    (tmp_path / ".wiring" / "latest.json").unlink()
    cp = _gates_cli([str(tmp_path), "test-run-1"])
    assert cp.returncode == 3, f"stdout={cp.stdout} stderr={cp.stderr}"
    assert "ENV_ERROR" in cp.stderr
    assert ".wiring/latest.json not found" in cp.stderr


def test_env_error_no_lockfile(tmp_path: Path) -> None:
    """3 ENV_ERROR — lockfile absent triggers auto-rewind."""
    _seed_happy_path(tmp_path, "test-run-1")
    (tmp_path / "poetry.lock").unlink()
    cp = _gates_cli([str(tmp_path), "test-run-1"])
    assert cp.returncode == 3, f"stdout={cp.stdout} stderr={cp.stderr}"
    assert "ENV_ERROR" in cp.stderr
    assert "no lockfile found" in cp.stderr


def test_fail_missing_wiring_hash_field(tmp_path: Path) -> None:
    """2 FAIL — intent-map missing required wiring_hash field."""
    _seed_happy_path(tmp_path, "test-run-1")
    intent_map = tmp_path / ".ledger" / "evo" / "runs" / "test-run-1" / "intent-map.yaml"
    intent_map.write_text(
        "schema_version: \"1.0.0\"\n"
        "run_id: test-run-1\n"
        "dep_lock_hash: \"deadbeef\"\n"  # wiring_hash deliberately absent
    )
    cp = _gates_cli([str(tmp_path), "test-run-1"])
    assert cp.returncode == 2, f"stdout={cp.stdout} stderr={cp.stderr}"
    assert "missing required field: wiring_hash" in cp.stderr


def test_fail_malformed_yaml(tmp_path: Path) -> None:
    """2 FAIL — intent-map.yaml is invalid YAML."""
    run_dir = tmp_path / ".ledger" / "evo" / "runs" / "test-run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "intent-map.yaml").write_text(":\n: invalid: yaml: [\n")
    cp = _gates_cli([str(tmp_path), "test-run-1"])
    assert cp.returncode == 2, f"stdout={cp.stdout} stderr={cp.stderr}"
    assert "parse error" in cp.stderr


def test_explicit_lockfile_flag(tmp_path: Path) -> None:
    """0 PASS — --lockfile overrides auto-detect."""
    _seed_happy_path(tmp_path, "test-run-1")
    # Move the lockfile to a non-standard location
    custom_lock = tmp_path / "custom-deps.lock"
    (tmp_path / "poetry.lock").rename(custom_lock)
    # Now the auto-detect would ENV_ERROR; --lockfile should rescue
    cp = _gates_cli([str(tmp_path), "test-run-1", "--lockfile", str(custom_lock)])
    assert cp.returncode == 0, f"stdout={cp.stdout} stderr={cp.stderr}"


def test_yaml_top_level_not_mapping(tmp_path: Path) -> None:
    """2 FAIL — intent-map.yaml top-level is a list instead of a mapping."""
    run_dir = tmp_path / ".ledger" / "evo" / "runs" / "test-run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "intent-map.yaml").write_text("- a\n- b\n- c\n")
    cp = _gates_cli([str(tmp_path), "test-run-1"])
    assert cp.returncode == 2, f"stdout={cp.stdout} stderr={cp.stderr}"
    assert "top-level must be a mapping" in cp.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
