"""
WP1 ship-gate — gate-run denominator telemetry (S039 efficacy-telemetry v1).

The HARD gate (design §7, §11): every gate's exit code (0/2/3/4) across the
12-gate matrix is BYTE-IDENTICAL (a) with the telemetry hook installed and
(b) with the telemetry import forced to ImportError (fail-open -> no-op).
WP1 is NOT done until test_exit_code_invariance_matrix is green.

Plus: bump-fires-once, never-raise under injected writer exception, and
SystemExit.code None/str/int/bool normalization.

Run with:
    pytest ~/.claude/skills/process-observation/tests/test_gate_run_telemetry.py -v
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Make the scripts dir importable so we can unit-test the helpers directly.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import gate_runs  # noqa: E402

# Locate the real gates.py. Prefer the production path; the shadow under
# foundry-lab imports the same way. We resolve relative to this skill's
# install location: ~/.claude/skills/process-observation/tests/ ->
# ~/.claude/skills/_meta/gates.py.
_GATES_PY = (
    Path(__file__).resolve().parent.parent.parent / "_meta" / "gates.py"
)


def _gates_available() -> bool:
    return _GATES_PY.is_file()


pytestmark = pytest.mark.skipif(
    not _gates_available(),
    reason=f"gates.py not found at {_GATES_PY}",
)


# ---------------------------------------------------------------------------
# 12-gate representative input matrix (design §11).
#
# Each entry: (label, argv_template). `{root}` is substituted with the temp
# project root. Inputs are chosen to span exit codes 0/2/3/4 without requiring
# a signed contract map or live security scanners — i.e. the gates fail-fast on
# missing inputs, which is the exact terminal-exit path the hook must preserve.
# ---------------------------------------------------------------------------

GATE_MATRIX = [
    ("G1_block",            ["G1", "{root}"]),
    ("G2_block",            ["G2", "{root}/progress/contract-map.yaml",
                             "--project-root", "{root}"]),
    ("G3_block",            ["G3", "WP-001", "sample-data-scaffolding",
                             "--project-root", "{root}"]),
    ("G4_skip",             ["G4", "{root}"]),
    ("G_V_block",           ["G_V", "deadbeef", "--project-root", "{root}"]),
    ("G_XR_env",            ["G_XR", "--project-root", "{root}"]),
    ("G_SCOPE_env",         ["G_SCOPE", "tokens_only", "--project-root", "{root}"]),
    ("G_CONTRACT_SCOPE_env", ["G_CONTRACT_SCOPE", "{root}",
                              "{root}/progress/contract-map.yaml",
                              "--wp", "WP-001",
                              "--detection-point", "wp_boundary"]),
    ("G_DEP_CURRENCY_pass", ["G_DEP_CURRENCY", "{root}"]),
    ("G_SECURE_env",        ["G_SECURE", "{root}"]),
    ("G_SECRETS_SCAN_env",  ["G_SECRETS_SCAN", "{root}"]),
    ("G_INTENT_MAP_FRESH_block", ["G_INTENT_MAP_FRESH", "{root}", "run-xyz"]),
    # Edge variants exercising the env_error paths.
    ("G1_missing_arg",      ["G1"]),
    ("unknown_gate",        ["G_NOPE"]),
]


def _run_gate(argv, root: Path, force_importerror: bool):
    """Run gates.py as a subprocess from inside `root`. Returns returncode."""
    cmd = [sys.executable, str(_GATES_PY)] + [
        a.format(root=str(root)) for a in argv
    ]
    env = dict(os.environ)
    if force_importerror:
        env["GATES_TELEMETRY_FORCE_IMPORTERROR"] = "1"
    else:
        env.pop("GATES_TELEMETRY_FORCE_IMPORTERROR", None)
    proc = subprocess.run(
        cmd, cwd=str(root), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc.returncode


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    (root / "PROJECT.md").write_text("# test project\n")
    return root


# ---------------------------------------------------------------------------
# THE hard ship-gate.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,argv", GATE_MATRIX, ids=[m[0] for m in GATE_MATRIX])
def test_exit_code_invariance_matrix(label, argv, tmp_path):
    """Exit code must be byte-identical: hook installed vs forced ImportError.

    Two independent project roots so the two runs cannot interfere via the
    sibling gate-runs.jsonl.
    """
    root_a = tmp_path / "with_hook"
    root_b = tmp_path / "no_hook"
    for r in (root_a, root_b):
        (r / ".process-observations").mkdir(parents=True)
        (r / "PROJECT.md").write_text("# test\n")

    code_with_hook = _run_gate(argv, root_a, force_importerror=False)
    code_no_hook = _run_gate(argv, root_b, force_importerror=True)

    assert code_with_hook == code_no_hook, (
        f"{label}: exit code drift — with_hook={code_with_hook} "
        f"no_hook={code_no_hook} (argv={argv})"
    )
    # And the code must be one of the documented gate exit codes.
    assert code_with_hook in (0, 2, 3, 4), (
        f"{label}: unexpected exit code {code_with_hook}"
    )


def test_matrix_covers_all_four_exit_codes(proj):
    """Sanity: the representative matrix actually spans 0/2/3/4 so the
    invariance test is meaningful (not vacuously all-same-code)."""
    seen = set()
    for _label, argv in GATE_MATRIX:
        code = _run_gate(argv, proj, force_importerror=False)
        seen.add(code)
    assert {0, 2, 3, 4} <= seen, (
        f"matrix does not span all four exit codes; saw {sorted(seen)}"
    )


# ---------------------------------------------------------------------------
# Denominator correctness.
# ---------------------------------------------------------------------------

def _read_gate_runs(root: Path):
    path = root / ".process-observations" / "gate-runs.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def test_bump_fires_exactly_once_per_invocation(proj):
    """Each gate invocation = exactly one bump (code:null) + one outcome
    (real code), sharing one run_id."""
    code = _run_gate(["G1", "{root}"], proj, force_importerror=False)
    assert code == 2
    records = _read_gate_runs(proj)
    assert len(records) == 2, f"expected bump+outcome, got {records}"
    bump = [r for r in records if r["code"] is None]
    outcome = [r for r in records if r["code"] is not None]
    assert len(bump) == 1, "exactly one pre-dispatch bump"
    assert len(outcome) == 1, "exactly one terminal outcome"
    assert bump[0]["run_id"] == outcome[0]["run_id"], "shared run_id"
    assert bump[0]["gate"] == "G1"
    assert outcome[0]["code"] == 2
    # Each record carries the four canonical fields, nothing else.
    for r in records:
        assert set(r.keys()) == {"ts", "gate", "run_id", "code"}


def test_window_sentinel_established_and_stable(proj):
    """First bump writes .telemetry_window; subsequent bumps never overwrite."""
    sentinel = proj / ".process-observations" / ".telemetry_window"
    _run_gate(["G1", "{root}"], proj, force_importerror=False)
    assert sentinel.is_file()
    first = sentinel.read_text()
    # A second, later invocation must not move the window start.
    _run_gate(["G_NOPE"], proj, force_importerror=False)
    assert sentinel.read_text() == first, "window start must be immutable"


def test_no_friction_ledger_pollution(proj):
    """The DENOMINATOR hook writes gate-runs.jsonl ONLY — never active.yaml /
    events.jsonl (design §4 constraint #5).

    NOTE: some gates (G_V/G_XR/G_SCOPE/G_CONTRACT_SCOPE) independently emit a
    `gate_false_block`/`gate_false_pass` FRICTION observation via the
    pre-existing S028 `exit_with_observation` -> `claude_observe` path; that is
    their own designed behavior and writes active.yaml/events.jsonl. To isolate
    THIS feature's invariant we run only the S014 gates (G1/G2/G3/G4/
    G_DEP_CURRENCY) which use `fail()`/`env_error()` and never touch the
    friction emitter — so any active.yaml/events.jsonl here could only come
    from the denominator hook, which must produce neither."""
    s014_only = [
        ["G1", "{root}"],
        ["G2", "{root}/progress/contract-map.yaml", "--project-root", "{root}"],
        ["G3", "WP-001", "sample-data-scaffolding", "--project-root", "{root}"],
        ["G4", "{root}"],
        ["G_DEP_CURRENCY", "{root}"],
    ]
    for argv in s014_only:
        _run_gate(argv, proj, force_importerror=False)
    obs = proj / ".process-observations"
    assert not (obs / "active.yaml").exists(), (
        "denominator hook must not write active.yaml"
    )
    assert not (obs / "events.jsonl").exists(), (
        "denominator hook must not write events.jsonl"
    )
    assert (obs / "gate-runs.jsonl").exists(), "gate-runs.jsonl must exist"


def test_denominator_writer_targets_only_gate_runs(tmp_path):
    """Helper-level proof: calling the writers directly produces ONLY
    gate-runs.jsonl + the sentinel — never active.yaml / events.jsonl."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    gate_runs.bump_gate_run("G1", project_root_override=root)
    gate_runs.record_gate_outcome("G1", 2, project_root_override=root)
    obs = root / ".process-observations"
    written = sorted(p.name for p in obs.iterdir())
    assert written == sorted(["gate-runs.jsonl", ".telemetry_window"]), (
        f"writer touched unexpected files: {written}"
    )


def test_forced_importerror_writes_nothing(proj):
    """Fail-open path is a true no-op: no gate-runs, no sentinel."""
    code = _run_gate(["G1", "{root}"], proj, force_importerror=True)
    assert code == 2  # exit code still correct
    obs = proj / ".process-observations"
    assert not (obs / "gate-runs.jsonl").exists()
    assert not (obs / ".telemetry_window").exists()


# ---------------------------------------------------------------------------
# Helper-level unit tests (direct import, no subprocess).
# ---------------------------------------------------------------------------

def test_exit_code_normalization():
    """SystemExit.code None/int/str/bool -> int-or-None per CPython semantics."""
    assert gate_runs._normalize_exit_code(None) == 0
    assert gate_runs._normalize_exit_code(0) == 0
    assert gate_runs._normalize_exit_code(2) == 2
    assert gate_runs._normalize_exit_code(3) == 3
    assert gate_runs._normalize_exit_code(4) == 4
    # str -> Python exits 1
    assert gate_runs._normalize_exit_code("some error message") == 1
    # bool (int subclass) handled explicitly
    assert gate_runs._normalize_exit_code(True) == 1
    assert gate_runs._normalize_exit_code(False) == 0


def test_bump_never_raises_on_broken_writer(tmp_path, monkeypatch):
    """If the underlying append raises, bump_gate_run swallows it (never-raise),
    addressing the cross-cutting risk that claude_observe's guarantee protects
    only its own body, not the caller's arg-construction."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    def _boom(*a, **k):
        raise RuntimeError("simulated writer explosion")

    monkeypatch.setattr(gate_runs, "_append_event_line", _boom)
    # Must NOT raise.
    gate_runs.bump_gate_run("G1", project_root_override=root)
    gate_runs.record_gate_outcome("G1", 2, project_root_override=root)


def test_record_outcome_never_raises_on_bad_code(tmp_path, monkeypatch):
    """An exotic code object cannot crash the outcome path."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    class Weird:
        def __int__(self):
            raise ValueError("no int for you")

    # Should swallow everything and write a normalized code (1 for non-int).
    gate_runs.record_gate_outcome("G1", Weird(), project_root_override=root)
    records = _read_gate_runs(root)
    assert records, "outcome record written despite weird code"
    assert records[-1]["code"] == 1


def test_read_window_start_none_when_absent(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    assert gate_runs.read_window_start(root) is None
    gate_runs.bump_gate_run("G1", project_root_override=root)
    assert gate_runs.read_window_start(root) is not None
