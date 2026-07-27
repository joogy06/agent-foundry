#!/usr/bin/env python3
"""test_alf_sweep_workflow.py — WP-16 (S055 §8) alf D-suite.

Covers (the deterministic, checkable parts):
  - Format-5 contract grep-pins in alf.md (ALF_FORMAT: 5, ZERO .alf/ writes,
    alf-finding-batch.v1, handoff_requests, skipped/limits);
  - `claude -p` ABSENT from the launcher (grep-pin);
  - launcher mode matrix (workflow forced => Workflow invocation; inline forced
    => direct prompt; the --workflow path writes an args file via atomic rename);
  - synthesis pure-function units (priority recompute, dedupe keep-max, tier
    resolution) in _meta/sweep_scope.py;
  - the alf-sweep.js workflow declares ZERO .alf/ writes (PROHIBITED header +
    no fs-write call).

The full runtime .alf/ no-write mtime sweep + golden-file render require a live
LLM sweep and are exercised by the in-session sweep path, not this unit suite.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_META_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = _META_DIR.parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import sweep_scope as ss  # noqa: E402

ALF_MD = REPO_ROOT / "agents" / "alf.md"
LAUNCHER = _META_DIR / "alf_sweep_launcher.sh"
SWEEP_JS = REPO_ROOT / "workflows" / "alf-sweep.js"


# ── Format-5 contract grep-pins ────────────────────────────────────────────
def test_format5_contract_pins():
    t = ALF_MD.read_text()
    for pin in [
        "ALF_FORMAT: 5",
        "alf-finding-batch.v1",
        "ZERO writes under `.alf/`",
        "handoff_requests[]",
        "budget honesty",
    ]:
        assert pin in t, f"alf.md missing Format-5 pin: {pin!r}"


def test_step5_inversion_pins():
    t = ALF_MD.read_text()
    assert "execution-context inversion" in t
    assert "agent-spawn-request.v1" in t
    assert "HANDOFF_PENDING" in t


def test_126_rescope_pin():
    t = ALF_MD.read_text()
    assert "#126 is RE-SCOPED to feed-write integrity only" in t or "RE-SCOPED to feed-write integrity" in t
    assert "atomic write-rename" in t


# ── launcher grep-pin: no `claude -p` ──────────────────────────────────────
def test_launcher_has_no_claude_p():
    t = LAUNCHER.read_text()
    assert "claude -p" not in t, "alf_sweep_launcher.sh still references `claude -p` (S055 stub must be deleted)"


# ── launcher mode matrix ───────────────────────────────────────────────────
def _run_launcher(*flags):
    return subprocess.run(
        ["bash", str(LAUNCHER), *flags],
        capture_output=True, text=True, timeout=60,
    )


def test_launcher_inline_prints_direct_prompt():
    r = _run_launcher("flow-pulse", "--inline")
    assert r.returncode == 0
    assert "Copy-paste this to alf" in r.stdout
    assert "Workflow({name:" not in r.stdout


def test_launcher_workflow_prints_invocation_and_writes_args():
    r = _run_launcher("flow-pulse", "--workflow")
    assert r.returncode == 0
    assert 'Workflow({name: "alf-sweep"' in r.stdout
    assert "args_path:" in r.stdout
    # An args file was written (durable audit record).
    assert "sweep-args-flow-pulse-" in r.stdout


# ── synthesis pure-function units ──────────────────────────────────────────
def test_priority_score_formula():
    assert ss.priority_score(5, 4, 1.0, 3, 2) == 30.0
    # effort floors at 1 (no div-by-zero)
    assert ss.priority_score(5, 4, 1.0, 3, 0) == 60.0


def test_dedupe_keep_max_and_stable_sort():
    fs = [
        {"target_path": "a", "lens": "sec", "title": "X Bug", "priority_score": 3},
        {"target_path": "a", "lens": "sec", "title": "x  bug", "priority_score": 7},
        {"target_path": "b", "lens": "perf", "title": "Slow", "priority_score": 5},
    ]
    d = ss.dedupe_keep_max(fs)
    assert len(d) == 2  # the two "x bug" variants merged
    assert d[0]["priority_score"] == 7  # max kept, sorted desc


def test_tier_resolution():
    assert set(ss.VALID_TIERS) == {"version", "freshness", "flow-pulse", "full", "flow-review"}
    assert ss.resolve_targets("flow-pulse") == ["orchestration-flow"]
    assert ss.resolve_targets("flow-review") == ss.FLOW_REVIEW_FIXED
    with pytest.raises(ValueError):
        ss.tier_spec("bogus-tier")


# ── alf-sweep.js declares ZERO .alf/ writes ────────────────────────────────
def test_sweep_js_prohibits_alf_writes():
    t = SWEEP_JS.read_text()
    assert "PROHIBITED:" in t
    assert ".alf/" in t  # mentioned in the prohibition
    # No fs.write* call in the workflow (it returns a summary; the main loop writes).
    assert "writeFileSync" not in t
    assert "fs.write" not in t


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
