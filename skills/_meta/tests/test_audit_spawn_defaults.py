"""S030-quickwins #53 + #54 — audit_spawn defaults & race-safe helper.

#53: DEFAULT_TIMEOUT_S MUST equal 300 (was 180; bumped to give audit
    subprocesses headroom on slow models / GCP egress).
#54: ensure_verdicts_dir() MUST exist and synchronously create the directory
    before any caller spawns parallel subprocesses that write into it.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_META = _HERE.parent.parent
sys.path.insert(0, str(_META))

import audit_spawn  # noqa: E402


def test_default_timeout_s_is_300() -> None:
    """Regression guard: DEFAULT_TIMEOUT_S = 300 (S030-quickwins #53)."""
    assert audit_spawn.DEFAULT_TIMEOUT_S == 300


def test_ensure_verdicts_dir_creates_directory(tmp_path: Path) -> None:
    """ensure_verdicts_dir() creates the dir and returns the resolved path."""
    target = tmp_path / "ledger" / "verdicts"
    assert not target.exists()
    out = audit_spawn.ensure_verdicts_dir(target)
    assert out.exists() and out.is_dir()
    assert out == target.resolve()


def test_ensure_verdicts_dir_idempotent(tmp_path: Path) -> None:
    """Calling ensure_verdicts_dir() twice on the same path is safe."""
    target = tmp_path / "ledger" / "verdicts"
    audit_spawn.ensure_verdicts_dir(target)
    # No exception on the second call.
    audit_spawn.ensure_verdicts_dir(target)
    assert target.is_dir()


def test_audit_spawn_race_note_documents_motivation() -> None:
    """The race-note string mentions the helper name + the .ledger path."""
    note = audit_spawn.audit_spawn_race_note
    assert "ensure_verdicts_dir" in note
    assert ".ledger/verdicts" in note
