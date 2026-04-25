#!/usr/bin/env python3
"""test_gates_keystone.py — ecosystem-keystone WP-6 coverage.

Covers contract-map `gates-keystone` test scenarios TS-G-01..06:

    TS-G-01  G_V happy path — verdict present + both arms pass + 8-field
             tuple echoes verbatim via claims.consume_visual_verdict → exit 0.
    TS-G-02  G_V tuple mismatch — verdict tuple does not echo the open
             verification-request → exit 2 + observation emitted
             (gate_false_block, fingerprint 'tuple-mismatch').
    TS-G-03  G_XR orphan detection — capability with no entry_point tag
             and no visual binding → exit 2 + observation emitted
             (fingerprint 'orphan-capability').
    TS-G-04  G_XR unresolved binds_to — skeleton interaction references
             a nonexistent capability → exit 2 + observation emitted
             (fingerprint 'dead-interaction').
    TS-G-05  G_SCOPE tokens_only honest declaration — only
             .design-ledger/skeletons/index.yaml tokens block changed → exit 0.
    TS-G-06  G_SCOPE false claim — declared tokens_only but an HTML file
             also changed → exit 2 + gate_false_pass observation
             (fingerprint 'scope-mismatch').

Run:
    pytest ~/.claude/skills/_meta/tests/test_gates_keystone.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
import yaml

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import claims  # noqa: E402
import gates  # noqa: E402


# ---------------------------------------------------------------------------
# Observation spy
# ---------------------------------------------------------------------------


class _ObserveSpy:
    """Records every claude_observe call issued from gates.exit_with_observation."""

    def __init__(self) -> None:
        self.calls: List[Tuple[tuple, dict]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _ObserveSpy:
    """Intercept `claude_observe` inside the gates module namespace so we can
    assert on every exit_with_observation emission without writing to disk.

    `exit_with_observation` resolves `claude_observe` at call time from the
    `gates` module globals, which is what we patch here.
    """
    s = _ObserveSpy()
    monkeypatch.setattr(gates, "claude_observe", s)
    return s


# ---------------------------------------------------------------------------
# Helpers that stand up a minimal project_root sandbox
# ---------------------------------------------------------------------------


def _seed_skeleton_index(project_root: Path, skeleton_version: str = "1.0",
                         screens: List[Dict[str, Any]] | None = None,
                         extra: Dict[str, Any] | None = None) -> Path:
    """Write a minimal `.design-ledger/skeletons/index.yaml`."""
    skeletons_dir = project_root / ".design-ledger" / "skeletons"
    skeletons_dir.mkdir(parents=True, exist_ok=True)
    doc: Dict[str, Any] = {
        "schema": "design-skeleton-index.v1",
        "skeleton_version": skeleton_version,
        "screens": screens or [],
    }
    if extra:
        doc.update(extra)
    path = skeletons_dir / "index.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return path


def _seed_per_screen_skeleton(project_root: Path, screen_file: str,
                               elements: Dict[str, Any]) -> Path:
    skeletons_dir = project_root / ".design-ledger" / "skeletons"
    skeletons_dir.mkdir(parents=True, exist_ok=True)
    path = skeletons_dir / screen_file
    path.write_text(yaml.safe_dump({"elements": elements}, sort_keys=False))
    return path


def _seed_contract_map(project_root: Path, components: List[Dict[str, Any]],
                       visual_entry_points: List[str] | None = None) -> Path:
    map_dir = project_root / "progress"
    map_dir.mkdir(parents=True, exist_ok=True)
    doc: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "revision": 1,
        "components": components,
    }
    if visual_entry_points is not None:
        doc["visual_entry_points"] = visual_entry_points
    path = map_dir / "contract-map.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return path


def _open_visual_request(project_root: Path, *, skeleton_hash: str,
                          impl_hash: str, skeleton_version: str = "1.0",
                          attempt_id: str = "attempt-1") -> Dict[str, Any]:
    """Call the real `claims.open_visual_verification_request` so G_V's call
    to `claims.consume_visual_verdict` finds a legitimate open record."""
    return claims.open_visual_verification_request(
        project_root,
        skeleton_hash=skeleton_hash,
        impl_hash=impl_hash,
        breakpoints=["mobile", "tablet", "desktop"],
        attempt_id=attempt_id,
        prior_state_version="ledger-rev-1",
        plan_hash="p" * 64,
        inventory_hash="i" * 64,
        runner_version="trusted_runner/1.0",
        rubric_version="rubric/1.0",
        opened_by="bob",
    )


def _verdict_from_request(record: Dict[str, Any], *,
                          skeleton_version: str,
                          arbiter_status: str = "pass",
                          drift_status: str = "pass",
                          **tuple_overrides: Any) -> Dict[str, Any]:
    """Build a visual-verdict.v1 YAML document that echoes the 8-field tuple."""
    verdict: Dict[str, Any] = {
        "schema": "visual-verdict.v1",
        "skeleton_version": skeleton_version,
        "arbiter_verdict": {"status": arbiter_status},
        "drift_arbiter_verdict": {"status": drift_status},
    }
    for field in claims.VISUAL_VERDICT_TUPLE_FIELDS:
        verdict[field] = record[field]
    verdict.update(tuple_overrides)
    return verdict


def _write_verdict(project_root: Path, impl_hash: str,
                   verdict: Dict[str, Any]) -> Path:
    verdict_dir = project_root / ".design-ledger" / "visual-verdicts"
    verdict_dir.mkdir(parents=True, exist_ok=True)
    path = verdict_dir / f"{impl_hash}.verdict.yaml"
    path.write_text(yaml.safe_dump(verdict, sort_keys=False))
    return path


# ---------------------------------------------------------------------------
# TS-G-01 — G_V happy path
# ---------------------------------------------------------------------------


def test_ts_g_01_gv_happy_path_exit_zero(tmp_path: Path, spy: _ObserveSpy) -> None:
    """TS-G-01: verdict present + both arms pass + 8-field tuple echo → exit 0."""
    impl_hash = "a" * 64
    skeleton_version = "1.0"
    _seed_skeleton_index(tmp_path, skeleton_version=skeleton_version)
    record = _open_visual_request(
        tmp_path,
        skeleton_hash="s" * 64,
        impl_hash=impl_hash,
        skeleton_version=skeleton_version,
    )
    verdict = _verdict_from_request(record, skeleton_version=skeleton_version)
    _write_verdict(tmp_path, impl_hash, verdict)

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_V(impl_hash, tmp_path)
    assert excinfo.value.code == 0, (
        f"expected exit 0 on happy path, got {excinfo.value.code}"
    )
    # Pass path must NOT emit any observation.
    assert spy.calls == [], (
        f"expected zero observations on pass, got {spy.calls!r}"
    )


# ---------------------------------------------------------------------------
# TS-G-02 — G_V tuple mismatch
# ---------------------------------------------------------------------------


def test_ts_g_02_gv_tuple_mismatch_exit_two(tmp_path: Path, spy: _ObserveSpy) -> None:
    """TS-G-02: the verdict echoes the WRONG attempt_id → consume_visual_verdict
    returns 'rejected_tuple_mismatch' → exit 2 + observation emitted.
    """
    impl_hash = "b" * 64
    skeleton_version = "1.0"
    _seed_skeleton_index(tmp_path, skeleton_version=skeleton_version)
    record = _open_visual_request(
        tmp_path,
        skeleton_hash="s" * 64,
        impl_hash=impl_hash,
        skeleton_version=skeleton_version,
        attempt_id="attempt-1",
    )
    # Intentionally corrupt the attempt_id in the verdict so the tuple echo fails.
    verdict = _verdict_from_request(
        record, skeleton_version=skeleton_version,
        attempt_id="attempt-WRONG",
    )
    _write_verdict(tmp_path, impl_hash, verdict)

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_V(impl_hash, tmp_path)
    assert excinfo.value.code == 2, (
        f"expected exit 2 on tuple mismatch, got {excinfo.value.code}"
    )
    # Exactly one observation should have been emitted via exit_with_observation.
    assert len(spy.calls) == 1, (
        f"expected 1 observation on tuple mismatch, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args[0] == "gate_false_block", (
        f"expected category 'gate_false_block', got {args[0]!r}"
    )
    assert kwargs.get("fingerprint") == "tuple-mismatch", (
        f"expected fingerprint 'tuple-mismatch', got {kwargs.get('fingerprint')!r}"
    )
    assert kwargs.get("severity") == "blocking"
    assert kwargs.get("subject_type") == "gate"


# ---------------------------------------------------------------------------
# TS-G-03 — G_XR orphan detection
# ---------------------------------------------------------------------------


def test_ts_g_03_gxr_orphan_capability_exit_two(tmp_path: Path, spy: _ObserveSpy) -> None:
    """TS-G-03: a capability without an entry_point tag and without any
    skeleton binds_to pointing at it must be flagged as an orphan.
    """
    # Seed index + a skeleton whose single interaction has visual_only:true so
    # there are NO visual roots reaching into the orphan capability.
    _seed_skeleton_index(
        tmp_path,
        skeleton_version="1.0",
        screens=[
            {"screen_id": "journey_main", "file": "journey_main.yaml"},
        ],
    )
    _seed_per_screen_skeleton(
        tmp_path, "journey_main.yaml",
        elements={
            "banner.1": {
                "id": "banner.1",
                "interactions": [
                    {"event": "click", "visual_only": True},
                ],
            },
        },
    )
    # Contract-map: one orphan capability (no entry_point, no caller, no binds_to).
    _seed_contract_map(tmp_path, components=[
        {
            "id": "utility",
            "capabilities": {
                "dead": {"purpose": "unreferenced dead capability"},
            },
        },
    ])

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_XR(tmp_path)
    assert excinfo.value.code == 2, (
        f"expected exit 2 on orphan capability, got {excinfo.value.code}"
    )
    assert len(spy.calls) == 1, (
        f"expected 1 observation on orphan detection, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args[0] == "gate_false_block"
    assert kwargs.get("fingerprint") == "orphan-capability", (
        f"expected fingerprint 'orphan-capability', got {kwargs.get('fingerprint')!r}"
    )
    # The what_happened blurb should include the orphan URI as a readable hint.
    what = args[2] if len(args) >= 3 else kwargs.get("what_happened", "")
    assert "capability://utility.dead" in what, (
        f"expected orphan URI in message, got {what!r}"
    )


# ---------------------------------------------------------------------------
# TS-G-04 — G_XR unresolved binds_to
# ---------------------------------------------------------------------------


def test_ts_g_04_gxr_dead_interaction_exit_two(tmp_path: Path, spy: _ObserveSpy) -> None:
    """TS-G-04: a skeleton interaction binds to a capability URI that has no
    matching component+capability in the contract-map → exit 2.
    """
    _seed_skeleton_index(
        tmp_path,
        skeleton_version="1.0",
        screens=[
            {"screen_id": "journey_main", "file": "journey_main.yaml"},
        ],
    )
    _seed_per_screen_skeleton(
        tmp_path, "journey_main.yaml",
        elements={
            "start_btn": {
                "id": "start_btn",
                "interactions": [
                    {
                        "event": "click",
                        "binds_to": "capability://controller.nonexistent",
                    },
                ],
            },
        },
    )
    # Contract-map DOES contain a controller component, but NOT the
    # `nonexistent` capability — so `uri.exists` returns False for the
    # binds_to URI.
    _seed_contract_map(tmp_path, components=[
        {
            "id": "controller",
            "capabilities": {
                "advance": {"purpose": "go forward"},
            },
            "entry_point": "cli",  # make it reachable so check 1 passes
        },
    ])

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_XR(tmp_path)
    assert excinfo.value.code == 2, (
        f"expected exit 2 on unresolved binds_to, got {excinfo.value.code}"
    )
    assert len(spy.calls) == 1, (
        f"expected 1 observation, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args[0] == "gate_false_block"
    assert kwargs.get("fingerprint") == "dead-interaction", (
        f"expected fingerprint 'dead-interaction', got {kwargs.get('fingerprint')!r}"
    )


# ---------------------------------------------------------------------------
# TS-G-05 — G_SCOPE tokens_only honest declaration
# ---------------------------------------------------------------------------


def _install_git_stubs(monkeypatch: pytest.MonkeyPatch,
                        name_only_output: str,
                        per_file_diff: Dict[str, str] | None = None,
                        show_output: Dict[str, str] | None = None) -> None:
    """Replace subprocess.run calls issued by gates.check_G_SCOPE with canned
    outputs keyed on the git subcommand. We match on argv[1:] shape so the
    stub only intercepts `git -C <root> diff ...` / `git -C <root> show ...`.
    """
    per_file_diff = per_file_diff or {}
    show_output = show_output or {}

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if (
            isinstance(cmd, list) and len(cmd) >= 5
            and cmd[0] == "git" and cmd[1] == "-C"
            and cmd[3] == "diff" and cmd[4] == "--name-only"
        ):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=name_only_output, stderr="",
            )
        if (
            isinstance(cmd, list) and len(cmd) >= 5
            and cmd[0] == "git" and cmd[1] == "-C"
            and cmd[3] == "diff" and cmd[4] == "HEAD"
        ):
            # `git diff HEAD -- <path>`
            path = cmd[-1] if cmd[-1] != "--" else ""
            out = per_file_diff.get(path, "")
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=out, stderr="",
            )
        if (
            isinstance(cmd, list) and len(cmd) >= 4
            and cmd[0] == "git" and cmd[1] == "-C" and cmd[3] == "show"
        ):
            ref = cmd[4] if len(cmd) > 4 else ""
            out = show_output.get(ref, "")
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=out, stderr="",
            )
        # Let any other subprocess.run call through unaltered.
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_ts_g_05_gscope_tokens_only_honest_exit_zero(
    tmp_path: Path, spy: _ObserveSpy, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TS-G-05: only index.yaml tokens block changed → honest tokens_only
    declaration → exit 0, no observation."""
    index_path = "/path/to/project/.design-ledger/skeletons/index.yaml"
    rel_path = ".design-ledger/skeletons/index.yaml"

    # Current working-tree state: tokens bumped.
    skeletons_dir = tmp_path / ".design-ledger" / "skeletons"
    skeletons_dir.mkdir(parents=True, exist_ok=True)
    current_doc = {
        "schema": "design-skeleton-index.v1",
        "skeleton_version": "1.0",
        "tokens": {"color": {"ink": "#111111"}},  # tokens block changed
        "screens": [],
        "must_satisfy": {"tolerance_px": 2},
    }
    (skeletons_dir / "index.yaml").write_text(yaml.safe_dump(current_doc))

    # HEAD state: same schema + skeleton_version + screens + must_satisfy,
    # but an older tokens block.
    head_doc = dict(current_doc)
    head_doc["tokens"] = {"color": {"ink": "#000000"}}  # old ink
    head_yaml = yaml.safe_dump(head_doc)

    _install_git_stubs(
        monkeypatch,
        name_only_output=f"{rel_path}\n",
        show_output={f"HEAD:{rel_path}": head_yaml},
    )

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_SCOPE("tokens_only", tmp_path)
    assert excinfo.value.code == 0, (
        f"expected exit 0 on honest tokens_only, got {excinfo.value.code}"
    )
    assert spy.calls == [], (
        f"expected no observation on pass, got {spy.calls!r}"
    )


# ---------------------------------------------------------------------------
# TS-G-06 — G_SCOPE false claim (declared tokens_only but HTML changed)
# ---------------------------------------------------------------------------


def test_ts_g_06_gscope_false_claim_exit_two(
    tmp_path: Path, spy: _ObserveSpy, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TS-G-06: declared tokens_only but the diff also shows an HTML change
    (outside index.yaml) → false claim → exit 2 + gate_false_pass observation."""
    # Don't even need a real index.yaml — the non-index HTML change alone
    # is enough to reject. But we add a stub so the function can check it too.
    name_only = (
        ".design-ledger/skeletons/index.yaml\n"
        "src/public/index.html\n"
    )
    _install_git_stubs(monkeypatch, name_only_output=name_only)

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_SCOPE("tokens_only", tmp_path)
    assert excinfo.value.code == 2, (
        f"expected exit 2 on false tokens_only claim, got {excinfo.value.code}"
    )
    assert len(spy.calls) == 1, (
        f"expected 1 observation on scope mismatch, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args[0] == "gate_false_pass", (
        f"expected category 'gate_false_pass' for scope mismatch, got {args[0]!r}"
    )
    assert kwargs.get("fingerprint") == "scope-mismatch", (
        f"expected fingerprint 'scope-mismatch', got {kwargs.get('fingerprint')!r}"
    )
    # The what_happened blurb should list the offending non-index path.
    what = args[2] if len(args) >= 3 else kwargs.get("what_happened", "")
    assert "src/public/index.html" in what, (
        f"expected offending HTML path in message, got {what!r}"
    )
