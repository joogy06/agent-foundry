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


# ===========================================================================
# Phase5b — closing-test additions per Codex structured_disagreements
# ===========================================================================
#
# These tests close the four critical / moderate gaps Codex flagged on
# attempt_id=1 for gates-keystone:
#
#   Phase5b_StaticExitDiscipline (Codex critical [1])
#       SC[4]/SC[5] — "no bare non-zero sys.exit outside the allow-list".
#       Static AST check on gates.py source: every bare sys.exit with a
#       non-zero literal argument must live in an allow-listed function
#       (fail / env_error / ok / exit_with_observation / main /
#       _load_claude_observe_for_gates / module-level pyyaml import-fatal).
#
#   Phase5b_ExitWithObservationMatrix (Codex critical [2])
#       Drive every (gate_name, severity, fingerprint) combination through
#       exit_with_observation directly so the observation-then-exit ordering
#       is provably exercised for every gate name in
#       _GATE_FALSE_BLOCK_SET ∪ {G_SCOPE} on every severity level.
#
#   Phase5b_GxrHappyPath (Codex moderate [3] / Claude moderate [2])
#       The full G_XR pass condition (all capabilities reachable AND every
#       binds_to resolves AND every visual_entry_points entry resolves) →
#       exit 0 with no observation. Closes the iff-biconditional gap —
#       only the `if false → fail` half is currently exercised.
#
#   Phase5b_GvNegativeMatrix (Claude minor [5])
#       G_V conjunctive failure modes other than tuple-mismatch:
#         (a) verdict file missing,
#         (b) one arm = "fail" (the other = "pass"),
#         (c) skeleton_version mismatch between verdict + persisted index.
#       All three currently undocumented; closes the SC[1] coverage gap.


import ast
import inspect


# Allow-list of FUNCTION NAMES inside gates.py whose body is permitted to
# contain bare `sys.exit(NON_ZERO_LITERAL)` calls. Anything outside this set
# must route exits through `exit_with_observation` (per design §4.7 Hook 1).
_BARE_EXIT_ALLOWLIST = frozenset({
    "fail",                        # S014 legacy helper
    "env_error",                   # environmental-error helper
    "ok",                          # zero-exit helper (still allow-listed)
    "exit_with_observation",       # the helper itself does the final sys.exit
    "main",                        # CLI dispatcher
})


def _walk_function_exits(tree: ast.AST):
    """Yield (function_name | None, exit_arg_repr | 'no-arg', ast.Call) for
    every `sys.exit(...)` call in the module. function_name is None for
    module-level calls (e.g. the pyyaml import-fatal at line ~40).
    """
    # Build a parent map so we can identify which FunctionDef contains a Call.
    parents: Dict[ast.AST, Optional[ast.AST]] = {tree: None}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def enclosing_func(node: ast.AST) -> Optional[ast.FunctionDef]:
        cur: Optional[ast.AST] = parents.get(node)
        while cur is not None:
            if isinstance(cur, ast.FunctionDef):
                return cur
            cur = parents.get(cur)
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        # Match only `sys.exit(...)` (Attribute on Name 'sys').
        if not (
            isinstance(f, ast.Attribute) and f.attr == "exit"
            and isinstance(f.value, ast.Name) and f.value.id == "sys"
        ):
            continue
        # Resolve the literal argument (we only care about NON-ZERO literals;
        # variables/expressions are NOT considered "bare" — they're computed).
        if not node.args:
            arg_repr: Any = "no-arg"
        else:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                arg_repr = arg.value
            else:
                arg_repr = "non-literal"
        ef = enclosing_func(node)
        yield (ef.name if ef else None, arg_repr, node)


def test_phase5b_static_exit_discipline_allowlist() -> None:
    """Phase5b SC[4]/SC[5] (Codex critical [1]):
    every bare `sys.exit(<non-zero literal>)` in gates.py must live in an
    allow-listed function. Anything outside _BARE_EXIT_ALLOWLIST must route
    through `exit_with_observation` per design §4.7 Hook 1.
    """
    src_path = Path(gates.__file__)
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    violations: List[Tuple[Optional[str], int, Any]] = []
    for func_name, arg, call in _walk_function_exits(tree):
        # Module-level call (func_name is None) is the import-fatal at
        # line ~40; that's an allow-listed pre-condition check.
        if func_name is None:
            continue
        # Allow-listed function: anything inside is fine.
        if func_name in _BARE_EXIT_ALLOWLIST:
            continue
        # Non-literal arg (e.g. `sys.exit(exit_code)` in a helper) is fine —
        # those are computed exit codes, not bare hardcoded numbers.
        if arg == "non-literal":
            continue
        # Zero-arg or zero-literal sys.exit is allowed (success); we only
        # police non-zero hardcoded literals as "bare failure exits".
        if arg in (0, "no-arg"):
            continue
        violations.append((func_name, call.lineno, arg))

    assert not violations, (
        "Phase5b SC[4]/SC[5]: bare non-zero `sys.exit(<literal>)` found "
        f"outside the allow-list {sorted(_BARE_EXIT_ALLOWLIST)}: "
        f"{violations}. Route through `exit_with_observation` per "
        "design §4.7 Hook 1, or extend _BARE_EXIT_ALLOWLIST with rationale."
    )


def test_phase5b_allowlist_is_minimal_and_documented() -> None:
    """Defense-in-depth: the allow-list itself must stay small. Growth past
    ~6 entries usually means someone is papering over a real
    observation-discipline regression instead of fixing it.
    """
    assert len(_BARE_EXIT_ALLOWLIST) <= 6, (
        f"_BARE_EXIT_ALLOWLIST has grown to {len(_BARE_EXIT_ALLOWLIST)} entries; "
        "this is a smell — review whether new entries should route through "
        "exit_with_observation instead."
    )
    # Each allow-listed name MUST exist in gates.py as a real function.
    gates_funcs = {
        name for name, obj in inspect.getmembers(gates, inspect.isfunction)
    }
    missing = _BARE_EXIT_ALLOWLIST - gates_funcs
    assert not missing, (
        f"allow-list references non-existent gates.py functions: {missing}"
    )


# --- Phase5b: exit_with_observation matrix (Codex critical [2]) ------------


_GATE_CATEGORY_MATRIX = [
    ("G1",      "gate_false_block"),
    ("G2",      "gate_false_block"),
    ("G3",      "gate_false_block"),
    ("G4",      "gate_false_block"),
    ("G_V",     "gate_false_block"),
    ("G_XR",    "gate_false_block"),
    # G_SCOPE is the only gate that defaults to gate_false_pass — it's
    # the "you LIED about scope" case, not "you're BLOCKING from acting".
    ("G_SCOPE", "gate_false_pass"),
]


@pytest.mark.parametrize("gate_name,expected_category", _GATE_CATEGORY_MATRIX)
@pytest.mark.parametrize("severity", ["blocking", "advisory"])
@pytest.mark.parametrize("exit_code", [2, 3, 4])
def test_phase5b_exit_with_observation_emits_then_exits(
    gate_name: str, expected_category: str,
    severity: str, exit_code: int, spy: _ObserveSpy,
) -> None:
    """SC[2] / Codex critical [2]: every (gate × severity × non-zero exit)
    triple emits exactly ONE observation with the correct default category
    and a default fingerprint of `<gate>-<subject>`, BEFORE sys.exit fires.
    """
    with pytest.raises(SystemExit) as excinfo:
        gates.exit_with_observation(
            gate_name, exit_code,
            "subject-X",
            f"{gate_name} demo failure",
            severity=severity,
        )
    assert excinfo.value.code == exit_code, (
        f"expected exit {exit_code}, got {excinfo.value.code}"
    )
    # The observation MUST have been emitted before sys.exit reached us.
    assert len(spy.calls) == 1, (
        f"expected exactly 1 observation, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args[0] == expected_category, (
        f"gate {gate_name}: expected category {expected_category!r}, "
        f"got {args[0]!r}"
    )
    assert args[1] == "subject-X"
    assert kwargs.get("severity") == severity
    assert kwargs.get("subject_type") == "gate"
    assert kwargs.get("fingerprint") == f"{gate_name}-subject-X", (
        f"gate {gate_name}: default fingerprint should collapse repeats"
    )
    # `observed_by` must include the gate name so downstream filtering
    # can attribute observations to their originating gate.
    assert kwargs.get("observed_by") == f"gates.py:{gate_name}"


def test_phase5b_exit_with_observation_zero_code_bypass(
    spy: _ObserveSpy,
) -> None:
    """Defense-in-depth: exit_code=0 bypasses the observation write entirely
    (success paths must NOT emit gate_false_* events).
    """
    with pytest.raises(SystemExit) as excinfo:
        gates.exit_with_observation("G_V", 0, "subject-X", "all good")
    assert excinfo.value.code == 0
    assert spy.calls == [], (
        f"exit_code=0 must NOT emit any observation, got {spy.calls!r}"
    )


def test_phase5b_exit_with_observation_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken observation backend MUST NOT block the gate exit
    (best-effort try/except, design §4.7 rationale)."""
    def _explode(*args, **kwargs):
        raise RuntimeError("observation backend on fire")

    monkeypatch.setattr(gates, "claude_observe", _explode)
    with pytest.raises(SystemExit) as excinfo:
        gates.exit_with_observation(
            "G_V", 2, "subject-Y", "exits even though observe failed",
        )
    # Critical: the gate exit code MUST still be honored.
    assert excinfo.value.code == 2


# --- Phase5b: G_XR happy-path (Codex moderate [3] / Claude moderate [2]) ---


def test_phase5b_gxr_happy_path_all_reachable_exit_zero(
    tmp_path: Path, spy: _ObserveSpy,
) -> None:
    """SC[2] iff biconditional half: a fully-resolved contract-map + skeleton
    combination → exit 0 with NO observation emitted. Closes the gap that
    only the `not-resolved → exit 2` half of G_XR is currently exercised
    (TS-G-03 + TS-G-04). The pass case is part of the SC, and the absence of
    an observation on pass is just as much of an invariant as the presence
    of one on fail.
    """
    # Skeleton with one wired interaction that resolves into the contract
    # map's lone capability — no orphans, no dead binds_to.
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
                        "binds_to": "capability://controller.advance",
                    },
                ],
            },
        },
    )
    _seed_contract_map(tmp_path, components=[
        {
            "id": "controller",
            # entry_point makes it reachable so the orphan check passes.
            "entry_point": "cli",
            "capabilities": {
                "advance": {"purpose": "go forward"},
            },
        },
    ])

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_XR(tmp_path)
    assert excinfo.value.code == 0, (
        "G_XR happy path: all capabilities reachable AND every binds_to "
        f"resolves → exit 0; got {excinfo.value.code}"
    )
    # Pass path MUST NOT emit any observation.
    assert spy.calls == [], (
        f"G_XR pass must not emit observation, got {spy.calls!r}"
    )


# --- Phase5b: G_V negative matrix (Claude minor [5]) -----------------------


def test_phase5b_gv_verdict_missing_exit_two(
    tmp_path: Path, spy: _ObserveSpy,
) -> None:
    """SC[1] condition (1): no verdict file at all → exit 2 + observation.

    G_V is an iff biconditional with FOUR conjunctive conditions:
        (1) verdict file exists,
        (2) both arms (arbiter + drift_arbiter) report 'pass',
        (3) verdict.skeleton_version == persisted index.skeleton_version,
        (4) the 8-field tuple echoes the open verification request.

    TS-G-02 only exercises (4); these new tests add (1) / (2) / (3).
    """
    impl_hash = "c" * 64
    skeleton_version = "1.0"
    _seed_skeleton_index(tmp_path, skeleton_version=skeleton_version)
    # Open the request (so we know G_V's failure is purely about the
    # missing verdict, not a missing request).
    _open_visual_request(
        tmp_path, skeleton_hash="s" * 64, impl_hash=impl_hash,
        skeleton_version=skeleton_version,
    )
    # Deliberately DO NOT write any .verdict.yaml file.

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_V(impl_hash, tmp_path)
    assert excinfo.value.code == 2, (
        f"missing verdict must exit 2; got {excinfo.value.code}"
    )
    assert len(spy.calls) == 1, (
        f"expected 1 observation on missing-verdict, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args[0] == "gate_false_block"
    # The observation should attribute the failure to G_V.
    assert kwargs.get("observed_by") == "gates.py:G_V"


def test_phase5b_gv_one_arm_fails_exit_two(
    tmp_path: Path, spy: _ObserveSpy,
) -> None:
    """SC[1] condition (2): arbiter='pass' but drift_arbiter='fail' →
    exit 2 + observation. This is the "single-arm failure" case Codex
    flagged as unexercised."""
    impl_hash = "d" * 64
    skeleton_version = "1.0"
    _seed_skeleton_index(tmp_path, skeleton_version=skeleton_version)
    record = _open_visual_request(
        tmp_path, skeleton_hash="s" * 64, impl_hash=impl_hash,
        skeleton_version=skeleton_version,
    )
    # Build a verdict whose tuple is correct, but drift_arbiter says fail.
    verdict = _verdict_from_request(
        record, skeleton_version=skeleton_version,
        arbiter_status="pass", drift_status="fail",
    )
    _write_verdict(tmp_path, impl_hash, verdict)

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_V(impl_hash, tmp_path)
    assert excinfo.value.code == 2, (
        f"single-arm fail must exit 2; got {excinfo.value.code}"
    )
    assert len(spy.calls) == 1, (
        f"expected 1 observation on arm-failure, got {spy.calls!r}"
    )
    args, _ = spy.calls[0]
    assert args[0] == "gate_false_block"


def test_phase5b_gv_skeleton_version_mismatch_exit_two(
    tmp_path: Path, spy: _ObserveSpy,
) -> None:
    """SC[1] condition (3): verdict.skeleton_version != index.skeleton_version
    → exit 2 + observation. The verdict was issued against a stale
    skeleton version; the implementation has since rev'd."""
    impl_hash = "e" * 64
    # Index claims 2.0, but the verdict is going to claim 1.0 — mismatch.
    _seed_skeleton_index(tmp_path, skeleton_version="2.0")
    record = _open_visual_request(
        tmp_path, skeleton_hash="s" * 64, impl_hash=impl_hash,
        skeleton_version="2.0",
    )
    # Force the verdict's skeleton_version to a stale value.
    verdict = _verdict_from_request(
        record, skeleton_version="1.0",  # <-- stale
        arbiter_status="pass", drift_status="pass",
    )
    _write_verdict(tmp_path, impl_hash, verdict)

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_V(impl_hash, tmp_path)
    assert excinfo.value.code == 2, (
        f"skeleton-version mismatch must exit 2; got {excinfo.value.code}"
    )
    assert len(spy.calls) == 1, (
        f"expected 1 observation on version-mismatch, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    # Skeleton-version mismatch is categorized as `gate_false_pass`: the
    # verdict claimed pass under skeleton_version=1.0 but the index has
    # since rev'd to 2.0 — the arbiter implicitly LIED by not detecting
    # the bump. Any gate_false_* category is acceptable here; the invariant
    # is "an observation is emitted attributing to G_V before exit".
    assert args[0] in ("gate_false_pass", "gate_false_block"), (
        f"expected gate_false_* observation, got {args[0]!r}"
    )
    assert kwargs.get("observed_by") == "gates.py:G_V"


# ---------------------------------------------------------------------------
# Phase 5b SPAWN 7 — close the 4 attempt_id=2 verdict gaps
#
# Verdict source: .ledger/verdicts/22e7d0ec...verdict.yaml (attempt_id=2)
#
# Codex/Claude moderate disagreements addressed (4 of 9 — the moderates):
#   1. G_XR success criterion 2: visual_entry_points resolution path
#      (TS-G-03/04 cover orphan + dead binds_to but NOT VEP failure).
#      -> test_phase5b_spawn7_gxr_visual_entry_point_unresolved_exit_two
#      -> test_phase5b_spawn7_gxr_visual_entry_point_resolves_exit_zero
#   2. G_XR allowance: entry_point-tagged unreachable capability
#      (orphan check should let it through when tagged).
#      -> test_phase5b_spawn7_gxr_entry_point_tagged_unreachable_allowed
#   3. G_SCOPE 'none' and 'text_only' enum branches (only tokens_only
#      currently exercised at TS-G-05/06).
#      -> test_phase5b_spawn7_gscope_none_clean_diff_exit_zero
#      -> test_phase5b_spawn7_gscope_none_ui_touched_exit_two
#      -> test_phase5b_spawn7_gscope_text_only_text_change_exit_zero
#      -> test_phase5b_spawn7_gscope_text_only_structural_change_exit_two
#   4. integration / flow test paths declared in contract-map without
#      deferred_to_v2 — assert the bundle either has results or the path
#      is properly marked deferred.
#      -> test_phase5b_spawn7_gates_keystone_test_paths_documented
# ---------------------------------------------------------------------------


def test_phase5b_spawn7_gxr_visual_entry_point_unresolved_exit_two(
    tmp_path: Path, spy: _ObserveSpy,
) -> None:
    """Phase5b spawn7 [1a]: G_XR fails when a visual_entry_point URI does
    not resolve. Codex flagged that TS-G-03/04 cover orphan + dead binds_to
    but the third leg (visual_entry_point resolution) has no isolated test.
    """
    _seed_skeleton_index(
        tmp_path,
        skeleton_version="1.0",
        screens=[{"screen_id": "journey_main", "file": "journey_main.yaml"}],
    )
    _seed_per_screen_skeleton(
        tmp_path, "journey_main.yaml",
        elements={
            "btn": {
                "id": "btn",
                "interactions": [
                    {"event": "click", "binds_to": "capability://controller.advance"},
                ],
            },
        },
    )
    _seed_contract_map(
        tmp_path,
        components=[
            {
                "id": "controller",
                "entry_point": "cli",
                "capabilities": {"advance": {"purpose": "go forward"}},
            },
        ],
        # The third leg: visual_entry_points names a screen that does not
        # exist (no .design-ledger/skeletons/nonexistent_screen.yaml file).
        visual_entry_points=["screen://nonexistent_screen"],
    )

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_XR(tmp_path)
    assert excinfo.value.code == 2, (
        f"unresolved visual_entry_point must exit 2, got {excinfo.value.code}"
    )
    assert len(spy.calls) == 1, (
        f"expected exactly 1 observation, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args[0] == "gate_false_block", (
        f"expected category 'gate_false_block', got {args[0]!r}"
    )
    assert kwargs.get("fingerprint") == "unresolved-uri", (
        f"expected fingerprint 'unresolved-uri' (the visual_entry_point "
        f"resolution leg), got {kwargs.get('fingerprint')!r}"
    )
    what = args[2] if len(args) >= 3 else kwargs.get("what_happened", "")
    assert ("screen://nonexistent_screen" in what
            or "nonexistent_screen" in what), (
        f"expected failed VEP URI in observation message, got {what!r}"
    )


def test_phase5b_spawn7_gxr_visual_entry_point_resolves_exit_zero(
    tmp_path: Path, spy: _ObserveSpy,
) -> None:
    """Phase5b spawn7 [1b]: G_XR passes when every visual_entry_point
    resolves. Companion to the negative case above.

    Note: per uri.py registry, the resolvable schemes are
    {capability, skeleton, flow, wire, token, component}. We use
    `capability://controller.advance` which DOES resolve via the
    seeded contract-map (component=controller, capability=advance).
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
            "btn": {
                "id": "btn",
                "interactions": [
                    {"event": "click", "binds_to": "capability://controller.advance"},
                ],
            },
        },
    )
    _seed_contract_map(
        tmp_path,
        components=[
            {
                "id": "controller",
                "entry_point": "cli",
                "capabilities": {"advance": {"purpose": "go forward"}},
            },
        ],
        # capability://controller.advance resolves via the seeded contract-map.
        visual_entry_points=["capability://controller.advance"],
    )

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_XR(tmp_path)
    assert excinfo.value.code == 0, (
        f"happy-path VEP resolution must exit 0, got {excinfo.value.code}"
    )
    assert spy.calls == [], (
        f"expected no observation on pass, got {spy.calls!r}"
    )


def test_phase5b_spawn7_gxr_entry_point_tagged_unreachable_allowed(
    tmp_path: Path, spy: _ObserveSpy,
) -> None:
    """Phase5b spawn7 [2]: G_XR's orphan check has an explicit allowance
    for entry_point-tagged capabilities — even if no skeleton interaction
    binds to them, they are NOT orphans.
    """
    _seed_skeleton_index(
        tmp_path,
        skeleton_version="1.0",
        screens=[{"screen_id": "journey_main", "file": "journey_main.yaml"}],
    )
    _seed_per_screen_skeleton(
        tmp_path, "journey_main.yaml",
        elements={
            "btn": {
                "id": "btn",
                "interactions": [
                    {"event": "click", "binds_to": "capability://controller.advance"},
                ],
            },
        },
    )
    _seed_contract_map(tmp_path, components=[
        {
            "id": "controller",
            "entry_point": "cron",  # tag → all caps implicitly reachable
            "capabilities": {
                "advance": {"purpose": "go forward"},
                "idle_tick": {"purpose": "scheduled cron tick — never UI-bound"},
            },
        },
    ])

    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_XR(tmp_path)
    assert excinfo.value.code == 0, (
        f"entry_point='cron' must shield idle_tick from orphan flagging; "
        f"got exit {excinfo.value.code}"
    )
    assert spy.calls == [], (
        f"entry_point allowance is a pass path; no observation expected, "
        f"got {spy.calls!r}"
    )


# --- Phase5b spawn7 [3] — G_SCOPE 'none' branch ---------------------------


def test_phase5b_spawn7_gscope_none_clean_diff_exit_zero(
    tmp_path: Path, spy: _ObserveSpy, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G_SCOPE 'none' honest declaration — diff has zero UI files → exit 0.

    The contract enum is {none, text_only, tokens_only}; only tokens_only
    is exercised in TS-G-05/06. This adds the 'none' branch's pass path.
    """
    _install_git_stubs(monkeypatch, name_only_output="src/lib.py\nsrc/utils.py\n")
    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_SCOPE("none", tmp_path)
    assert excinfo.value.code == 0, (
        f"declared 'none' with no UI changes must exit 0, "
        f"got {excinfo.value.code}"
    )
    assert spy.calls == [], (
        f"pass path must not emit observation, got {spy.calls!r}"
    )


def test_phase5b_spawn7_gscope_none_ui_touched_exit_two(
    tmp_path: Path, spy: _ObserveSpy, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G_SCOPE 'none' false claim — diff DOES include UI files → exit 2 +
    gate_false_pass observation with fingerprint 'scope-mismatch'.
    """
    _install_git_stubs(
        monkeypatch,
        name_only_output="src/public/index.html\nsrc/lib.py\n",
    )
    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_SCOPE("none", tmp_path)
    assert excinfo.value.code == 2, (
        f"false 'none' claim with UI diff must exit 2, "
        f"got {excinfo.value.code}"
    )
    assert len(spy.calls) == 1, (
        f"expected one observation, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args[0] == "gate_false_pass", (
        f"G_SCOPE false claim is gate_false_pass (bob over-claimed a "
        f"relaxed scope), got {args[0]!r}"
    )
    assert kwargs.get("fingerprint") == "scope-mismatch", (
        f"expected fingerprint 'scope-mismatch', got {kwargs.get('fingerprint')!r}"
    )
    what = args[2] if len(args) >= 3 else kwargs.get("what_happened", "")
    assert "src/public/index.html" in what, (
        f"observation message must surface the offending UI file, got {what!r}"
    )


# --- Phase5b spawn7 [3] — G_SCOPE 'text_only' branch ----------------------


def test_phase5b_spawn7_gscope_text_only_text_change_exit_zero(
    tmp_path: Path, spy: _ObserveSpy, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G_SCOPE 'text_only' honest — HTML diff is text-node only → exit 0."""
    rel_path = "src/page.html"
    text_only_diff = (
        "diff --git a/src/page.html b/src/page.html\n"
        "index abc..def 100644\n"
        "--- a/src/page.html\n"
        "+++ b/src/page.html\n"
        "@@ -1,3 +1,3 @@\n"
        " <h1>Title</h1>\n"
        "-Old body copy here\n"
        "+New body copy here\n"
        " <p>Footer</p>\n"
    )
    _install_git_stubs(
        monkeypatch,
        name_only_output=f"{rel_path}\n",
        per_file_diff={rel_path: text_only_diff},
    )
    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_SCOPE("text_only", tmp_path)
    assert excinfo.value.code == 0, (
        f"declared text_only with text-node-only diff must exit 0, "
        f"got {excinfo.value.code}"
    )
    assert spy.calls == [], (
        f"pass path must not emit observation, got {spy.calls!r}"
    )


def test_phase5b_spawn7_gscope_text_only_structural_change_exit_two(
    tmp_path: Path, spy: _ObserveSpy, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G_SCOPE 'text_only' false claim — HTML diff includes a tag/attribute
    change → exit 2 + gate_false_pass observation.
    """
    rel_path = "src/page.html"
    structural_diff = (
        "diff --git a/src/page.html b/src/page.html\n"
        "index abc..def 100644\n"
        "--- a/src/page.html\n"
        "+++ b/src/page.html\n"
        "@@ -1,2 +1,2 @@\n"
        "-<h1>Title</h1>\n"
        "+<h2 class=\"big\">Title</h2>\n"
    )
    _install_git_stubs(
        monkeypatch,
        name_only_output=f"{rel_path}\n",
        per_file_diff={rel_path: structural_diff},
    )
    with pytest.raises(SystemExit) as excinfo:
        gates.check_G_SCOPE("text_only", tmp_path)
    assert excinfo.value.code == 2, (
        f"false text_only with structural diff must exit 2, "
        f"got {excinfo.value.code}"
    )
    assert len(spy.calls) == 1, (
        f"expected one observation, got {spy.calls!r}"
    )
    args, kwargs = spy.calls[0]
    assert args[0] == "gate_false_pass"
    assert kwargs.get("fingerprint") == "scope-mismatch"
    what = args[2] if len(args) >= 3 else kwargs.get("what_happened", "")
    assert rel_path in what, (
        f"observation must surface the offending HTML file, got {what!r}"
    )


# --- Phase5b spawn7 [4] — integration / flow test paths documentation ----


def test_phase5b_spawn7_gates_keystone_test_paths_documented() -> None:
    """Phase5b spawn7 [4]: integration/flow test paths in the live
    contract-map.yaml for gates-keystone are EITHER (a) backed by actual
    test files we can locate on disk, OR (b) marked `deferred_to_v2: true`
    with a reason, OR (c) listed in the documented v2-deferral set
    (a project-tracked tasks.md item — Codex flagged this gap and the
    forge-side decision was 'defer to v2', not 'wire integration tests').

    This pins the documentation contract: forge cannot silently slip
    integration coverage out of v1 without converting the entry to a
    structured deferral block. The test acts as a grep-able reminder
    on every commit that mutates contract-map.yaml.
    """
    project_root = Path("/path/to/project")
    contract_path = project_root / "progress" / "contract-map.yaml"
    if not contract_path.is_file():
        pytest.skip("contract-map.yaml not present in this checkout")
    cmap = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    components = cmap.get("components") or []
    gates_comp = None
    for c in components:
        if isinstance(c, dict) and c.get("id") == "gates-keystone":
            gates_comp = c
            break
    if gates_comp is None:
        pytest.skip("gates-keystone not present in contract-map")
    test_paths = gates_comp.get("test_paths") or {}

    # Documented v2-deferral set per S028 spawn-7 verdict triage.
    # If Codex re-flags the gap on a future attempt, the resolution is
    # one of: (a) wire the tests so the directory exists, (b) convert
    # the contract entry to {deferred_to_v2: true, reason: ...}, or (c)
    # extend this set after explicit forge approval.
    documented_v2_deferrals = {
        "tests/integration/gates-keystone/",
        "tests/flow/",
    }
    for kind in ("integration", "flow"):
        entry = test_paths.get(kind)
        if entry is None:
            continue  # not declared at all — no gap
        if isinstance(entry, str):
            on_disk = (project_root / entry).exists()
            in_documented_set = entry in documented_v2_deferrals
            assert on_disk or in_documented_set, (
                f"gates-keystone test_paths.{kind} = {entry!r} is declared "
                f"as a plain string but neither (a) exists on disk nor (b) "
                f"is in the documented v2-deferral set "
                f"{documented_v2_deferrals!r}. Either wire the tests, "
                f"convert the entry to a {{deferred_to_v2: true, reason: ...}} "
                f"block in contract-map.yaml, or add the path to the "
                f"documented_v2_deferrals set in this test."
            )
        elif isinstance(entry, dict):
            assert entry.get("deferred_to_v2") is True, (
                f"gates-keystone test_paths.{kind} dict missing "
                f"deferred_to_v2: true; got {entry!r}"
            )
            assert isinstance(entry.get("reason"), str) and entry["reason"], (
                f"gates-keystone test_paths.{kind} dict missing 'reason' "
                f"string; got {entry!r}"
            )
