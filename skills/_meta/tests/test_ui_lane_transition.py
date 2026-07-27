#!/usr/bin/env python3
"""test_ui_lane_transition.py — S070 #142 UI-lane enforcement (design §A5).

Closes the enforcement hole: before S070, `UI-INTEGRATED` and `UI-VERIFIED`
appeared nowhere in `LEGAL_TRANSITIONS`, and `check_transition_legal` fails
closed on an unknown `from_stage` — so the UI lane could not route through the
sole-writer transition engine AT ALL. It ran on its own path (`G_V` +
`consume_visual_verdict`), outside the chokepoint `apply_request_idempotent`
exists to be, which made the visual gate structurally skippable.

Coverage map (design §A5):

    legality           the UI edges are legal; illegal UI edges still are not,
                       including the INTEGRATED -> UI-INTEGRATED R6 bypass
    predicate          each failure class rejected independently
    purity             the predicate performs NO writes (fs snapshot)
    no nested lock     the predicate acquires no lock of its own — it runs
                       inside the engine's `_bob_claim_lock`, and `flock` on a
                       second fd in the same process blocks forever
    gate parity        `check_G_V` exit codes / categories / fingerprints
                       unchanged across every failure path (§A4)
    THE HOLE           a UI-VERIFIED transition with a missing/failing verdict
                       is rejected BY THE ENGINE, not merely by the CLI gate
    tuple binding      a stale-but-passing verdict does not authorize a
                       transition even though checks 1-4 pass
    two-case status    `consumed` + deep-equal stored verdict is ACCEPTED;
                       `consumed` + differing verdict is REJECTED; a missing
                       request record is REJECTED
    gate single-use    on the SAME fixture where the engine accepts a consumed
                       record, `check_G_V` STILL exits 2
    gate-then-engine   the HIGH-1 regression: consume first (as bob.md:76
                       prescribes), THEN transition — must SUCCEED
    env fails closed   degraded environment is never read as a pass
    idempotency        replaying a request_id is a no-op via engine dedup

Run:
    pytest ~/.claude/skills/_meta/tests/test_ui_lane_transition.py -v
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import yaml

_META_DIR = Path(__file__).resolve().parent.parent
if str(_META_DIR) not in sys.path:
    sys.path.insert(0, str(_META_DIR))

import claims  # noqa: E402
import gates  # noqa: E402


# ---------------------------------------------------------------------------
# Observation spy (same shape as test_gates_keystone.py)
# ---------------------------------------------------------------------------


class _ObserveSpy:
    def __init__(self) -> None:
        self.calls: List[Tuple[tuple, dict]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))

    @property
    def category(self) -> Optional[str]:
        return self.calls[0][0][0] if self.calls else None

    @property
    def fingerprint(self) -> Optional[str]:
        return self.calls[0][1].get("fingerprint") if self.calls else None

    @property
    def severity(self) -> Optional[str]:
        return self.calls[0][1].get("severity") if self.calls else None


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _ObserveSpy:
    s = _ObserveSpy()
    monkeypatch.setattr(gates, "claude_observe", s)
    return s


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

IMPL_HASH = "a" * 64
SKELETON_HASH = "s" * 64
SKELETON_VERSION = "1.0"


def _seed_skeleton_index(root: Path, skeleton_version: str = SKELETON_VERSION) -> Path:
    d = root / ".design-ledger" / "skeletons"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "index.yaml"
    path.write_text(yaml.safe_dump(
        {"schema": "design-skeleton-index.v1",
         "skeleton_version": skeleton_version,
         "screens": []},
        sort_keys=False,
    ))
    return path


def _open_request(root: Path, *, attempt_id: str = "attempt-1",
                  impl_hash: str = IMPL_HASH) -> Dict[str, Any]:
    return claims.open_visual_verification_request(
        root,
        skeleton_hash=SKELETON_HASH,
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


def _verdict(record: Dict[str, Any], *,
             skeleton_version: str = SKELETON_VERSION,
             arbiter_status: str = "pass",
             drift_status: str = "pass",
             **overrides: Any) -> Dict[str, Any]:
    v: Dict[str, Any] = {
        "schema": "visual-verdict.v1",
        "skeleton_version": skeleton_version,
        "arbiter_verdict": {"status": arbiter_status},
        "drift_arbiter_verdict": {"status": drift_status},
    }
    for field in claims.VISUAL_VERDICT_TUPLE_FIELDS:
        v[field] = record[field]
    v.update(overrides)
    return v


def _write_verdict(root: Path, verdict: Any,
                   impl_hash: str = IMPL_HASH, *, raw: Optional[str] = None) -> Path:
    d = root / ".design-ledger" / "visual-verdicts"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{impl_hash}.verdict.yaml"
    path.write_text(raw if raw is not None else yaml.safe_dump(verdict, sort_keys=False))
    return path


LEDGER_TEMPLATE = """---
schema_version: 1
contract_map_hash: "sha256:{maphash}"
contract_map_revision: 1
forge_session_id: "test-session"
frozen_at: "2026-07-25T00:00:00+00:00"
writer: bob
consumed_request_ids: []
drift_canary: "ALDEBARAN-7"
pause_epoch: 0
---

# UI-lane test ledger

## Projection (current state — one row per WP/component)

| WP | component | stage | generation | deps |
|----|-----------|-------|------------|------|
{rows}

## Transition log

| # | WP | component | from -> to | generation | evidence |
|---|----|-----------|-----------|------------|----------|
"""


def _seed_ledger(root: Path, rows: List[Tuple[str, str, str]]) -> Path:
    """rows: list of (wp, component, stage)."""
    d = root / "progress"
    d.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"| {wp} | {comp} | {stage} | 0 | — |" for wp, comp, stage in rows)
    path = d / "integration-ledger.md"
    path.write_text(LEDGER_TEMPLATE.format(maphash="0" * 64, rows=body))
    return path


def _ui_project(tmp_path: Path, *, stage: str = "UI-INTEGRATED") -> Dict[str, Any]:
    """Stand up a fully healthy UI-lane project: skeleton index, open request,
    passing verdict on disk, and a ledger with the component at `stage`."""
    _seed_skeleton_index(tmp_path)
    record = _open_request(tmp_path)
    verdict = _verdict(record)
    _write_verdict(tmp_path, verdict)
    _seed_ledger(tmp_path, [("WP-7", "screen-a", stage)])
    return {"record": record, "verdict": verdict}


def _ui_request(request_id: str = "req-ui-1", *,
                impl_hash: str = IMPL_HASH,
                to_stage: str = "UI-VERIFIED") -> Dict[str, Any]:
    return {
        "request_id": request_id,
        "wp": "WP-7",
        "component_id": "screen-a",
        "to_stage": to_stage,
        "impl_hash": impl_hash,
        "evidence": "G_V accepted",
    }


def _snapshot(root: Path) -> Dict[str, Tuple[int, str]]:
    """(size, sha256) per file under root — the no-write assertion's basis.

    Content-hashed rather than mtime-based: mtime granularity can hide a
    same-size rewrite, and a rewrite is exactly what this must catch.
    """
    out: Dict[str, Tuple[int, str]] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                data = p.read_bytes()
            except OSError:
                continue
            out[str(p.relative_to(root))] = (len(data), hashlib.sha256(data).hexdigest())
    return out


# ===========================================================================
# 1. Legality — the locked table (design §A1)
# ===========================================================================


def test_ui_lane_edges_are_legal() -> None:
    """The decided edge set: VERIFIED -> UI-INTEGRATED -> UI-VERIFIED -> DOCUMENTED."""
    assert claims.check_transition_legal("VERIFIED", "UI-INTEGRATED")
    assert claims.check_transition_legal("UI-INTEGRATED", "UI-VERIFIED")
    assert claims.check_transition_legal("UI-VERIFIED", "DOCUMENTED")


def test_verified_to_documented_retained() -> None:
    """The UI lane is an ADDITIONAL HOP, not a substitute — non-UI components
    must be completely unaffected."""
    assert claims.check_transition_legal("VERIFIED", "DOCUMENTED")


def test_integrated_to_ui_integrated_is_illegal_r6_bypass() -> None:
    """INTEGRATED -> UI-INTEGRATED would allow
    INTEGRATED -> UI-INTEGRATED -> UI-VERIFIED -> DOCUMENTED to reach terminal
    WITHOUT ever passing R6 — an unflagged bypass of the core lane's strongest
    gate. The decided shape forecloses it."""
    assert not claims.check_transition_legal("INTEGRATED", "UI-INTEGRATED")


@pytest.mark.parametrize("frm,to", [
    ("UI-VERIFIED", "UI-INTEGRATED"),   # no going backwards
    ("UI-INTEGRATED", "DOCUMENTED"),    # cannot skip the visual verdict
    ("UI-INTEGRATED", "VERIFIED"),      # not a demote path
    ("DOCUMENTED", "UI-INTEGRATED"),    # DOCUMENTED is terminal
    ("PLANNED", "UI-INTEGRATED"),
    ("SCAFFOLDED", "UI-VERIFIED"),
])
def test_illegal_ui_edges_stay_illegal(frm: str, to: str) -> None:
    assert not claims.check_transition_legal(frm, to)


@pytest.mark.parametrize("ui_stage", ["UI-INTEGRATED", "UI-VERIFIED"])
def test_ui_states_demote_and_block_like_the_core_lane(ui_stage: str) -> None:
    """§A1.2: no partial demote exists anywhere in the table, so a purely
    visual defect re-climbs the full ladder (and re-runs R6). BLOCKED from a UI
    state unblocks only via ->PLANNED, which bumps the generation (CB1)."""
    assert claims.check_transition_legal(ui_stage, "BLOCKED")
    assert claims.check_transition_legal(ui_stage, "PLANNED")
    assert claims.check_transition_legal("BLOCKED", "PLANNED")
    assert claims.is_demote_to_planned("PLANNED")


def test_core_lane_table_unchanged() -> None:
    """Regression: adding UI states must not perturb any core-lane edge."""
    assert claims.LEGAL_TRANSITIONS["PLANNED"] == frozenset({"SCAFFOLDED", "BLOCKED"})
    assert claims.LEGAL_TRANSITIONS["SCAFFOLDED"] == frozenset(
        {"UNIT_TESTED", "BLOCKED", "PLANNED"})
    assert claims.LEGAL_TRANSITIONS["UNIT_TESTED"] == frozenset(
        {"INTEGRATED", "BLOCKED", "PLANNED"})
    assert claims.LEGAL_TRANSITIONS["INTEGRATED"] == frozenset(
        {"VERIFIED", "BLOCKED", "PLANNED"})
    assert claims.LEGAL_TRANSITIONS["DOCUMENTED"] == frozenset()
    assert claims.LEGAL_TRANSITIONS["BLOCKED"] == frozenset({"PLANNED"})
    # VERIFIED gained exactly one member.
    assert claims.LEGAL_TRANSITIONS["VERIFIED"] == frozenset(
        {"DOCUMENTED", "BLOCKED", "PLANNED", "UI-INTEGRATED"})


# ===========================================================================
# 2. The predicate — each failure class, independently
# ===========================================================================


def test_predicate_accepts_healthy_fixture(tmp_path: Path) -> None:
    ctx = _ui_project(tmp_path)
    out = claims.assert_ui_verified_preconditions(IMPL_HASH, tmp_path)
    assert out["request_id"] == ctx["record"]["request_id"]


def _expect_reject(root: Path, *, fingerprint: Optional[str] = None,
                   kind: str = "violation",
                   category: Optional[str] = None,
                   impl_hash: str = IMPL_HASH) -> claims.UiVerifiedPreconditionError:
    with pytest.raises(claims.UiVerifiedPreconditionError) as ei:
        claims.assert_ui_verified_preconditions(impl_hash, root)
    err = ei.value
    assert err.kind == kind, f"expected kind={kind!r}, got {err.kind!r}"
    if fingerprint is not None:
        assert err.fingerprint == fingerprint, (
            f"expected fingerprint={fingerprint!r}, got {err.fingerprint!r}"
        )
    if category is not None:
        assert err.category == category
    return err


def test_predicate_rejects_missing_verdict(tmp_path: Path) -> None:
    _seed_skeleton_index(tmp_path)
    _open_request(tmp_path)
    _expect_reject(tmp_path, fingerprint="verdict-missing")


def test_predicate_rejects_malformed_verdict(tmp_path: Path) -> None:
    _seed_skeleton_index(tmp_path)
    _open_request(tmp_path)
    _write_verdict(tmp_path, None, raw="- not\n- a mapping\n")
    _expect_reject(tmp_path, fingerprint="verdict-malformed")


def test_predicate_rejects_missing_arbiter_arm(tmp_path: Path) -> None:
    _seed_skeleton_index(tmp_path)
    rec = _open_request(tmp_path)
    v = _verdict(rec)
    del v["arbiter_verdict"]
    _write_verdict(tmp_path, v)
    _expect_reject(tmp_path, fingerprint="arm-missing-arbiter")


def test_predicate_rejects_missing_drift_arm(tmp_path: Path) -> None:
    _seed_skeleton_index(tmp_path)
    rec = _open_request(tmp_path)
    v = _verdict(rec)
    del v["drift_arbiter_verdict"]
    _write_verdict(tmp_path, v)
    _expect_reject(tmp_path, fingerprint="arm-missing-drift")


def test_predicate_rejects_arbiter_not_pass(tmp_path: Path) -> None:
    _seed_skeleton_index(tmp_path)
    rec = _open_request(tmp_path)
    _write_verdict(tmp_path, _verdict(rec, arbiter_status="fail"))
    _expect_reject(tmp_path, fingerprint="arbiter-not-pass")


def test_predicate_rejects_drift_not_pass(tmp_path: Path) -> None:
    _seed_skeleton_index(tmp_path)
    rec = _open_request(tmp_path)
    _write_verdict(tmp_path, _verdict(rec, drift_status="fail"))
    _expect_reject(tmp_path, fingerprint="drift-not-pass")


def test_predicate_accepts_drift_auto_approved(tmp_path: Path) -> None:
    """Micro-drift auto-approval is a legitimate pass for the drift arm."""
    _seed_skeleton_index(tmp_path)
    rec = _open_request(tmp_path)
    _write_verdict(tmp_path, _verdict(rec, drift_status="auto_approved"))
    assert claims.assert_ui_verified_preconditions(IMPL_HASH, tmp_path)


def test_predicate_rejects_skeleton_version_mismatch(tmp_path: Path) -> None:
    """Category is `gate_false_pass`: the arbiter passed a verdict against a
    skeleton the index has since rev'd past — it missed the bump."""
    _seed_skeleton_index(tmp_path, skeleton_version="2.0")
    rec = _open_request(tmp_path)
    _write_verdict(tmp_path, _verdict(rec, skeleton_version="1.0"))
    _expect_reject(tmp_path, fingerprint="skeleton-version-mismatch",
                   category="gate_false_pass")


def test_predicate_rejects_missing_request_id(tmp_path: Path) -> None:
    _seed_skeleton_index(tmp_path)
    rec = _open_request(tmp_path)
    v = _verdict(rec)
    del v["request_id"]
    _write_verdict(tmp_path, v)
    _expect_reject(tmp_path, fingerprint="request-id-missing")


def test_predicate_does_not_implement_phantom_schema_check(tmp_path: Path) -> None:
    """The `check_G_V` docstring used to claim a `schema: visual-verdict.v1`
    check its body never performed. Implementing it would add a new failure
    class and break the fingerprint-set-unchanged guarantee, so the docstring
    was corrected instead. A verdict with NO schema key must still pass."""
    _seed_skeleton_index(tmp_path)
    rec = _open_request(tmp_path)
    v = _verdict(rec)
    del v["schema"]
    _write_verdict(tmp_path, v)
    assert claims.assert_ui_verified_preconditions(IMPL_HASH, tmp_path)

    v2 = _verdict(rec, schema="something-else.v9")
    _write_verdict(tmp_path, v2)
    assert claims.assert_ui_verified_preconditions(IMPL_HASH, tmp_path)


# --- env class (fails closed) ----------------------------------------------


def test_predicate_env_error_on_unparseable_verdict(tmp_path: Path) -> None:
    _seed_skeleton_index(tmp_path)
    _open_request(tmp_path)
    _write_verdict(tmp_path, None, raw="key: [unclosed\n  bad: : :\n")
    _expect_reject(tmp_path, kind="env")


def test_predicate_env_error_on_unreadable_skeleton_index(tmp_path: Path) -> None:
    rec_root = tmp_path
    rec = _open_request(rec_root)
    _write_verdict(rec_root, _verdict(rec))
    # No skeleton index at all -> indistinguishable from unreadable -> env.
    _expect_reject(rec_root, kind="env")


# ===========================================================================
# 3. Purity — no writes, no locks
# ===========================================================================


@pytest.mark.parametrize("scenario", [
    "healthy", "missing-verdict", "arm-fail", "tuple-mismatch", "consumed",
])
def test_predicate_performs_no_writes(tmp_path: Path, scenario: str) -> None:
    """§A5: filesystem snapshot before/after, on the pass path AND the reject
    paths. The predicate must be pure — `consume_visual_verdict` is the only
    mutation in this flow and it stays in `check_G_V`."""
    _seed_skeleton_index(tmp_path)
    rec = _open_request(tmp_path)
    if scenario == "healthy":
        _write_verdict(tmp_path, _verdict(rec))
    elif scenario == "missing-verdict":
        pass
    elif scenario == "arm-fail":
        _write_verdict(tmp_path, _verdict(rec, arbiter_status="fail"))
    elif scenario == "tuple-mismatch":
        _write_verdict(tmp_path, _verdict(rec, attempt_id="attempt-WRONG"))
    elif scenario == "consumed":
        v = _verdict(rec)
        _write_verdict(tmp_path, v)
        claims.consume_visual_verdict(tmp_path, rec["request_id"], v)

    before = _snapshot(tmp_path)
    try:
        claims.assert_ui_verified_preconditions(IMPL_HASH, tmp_path)
    except claims.UiVerifiedPreconditionError:
        pass
    after = _snapshot(tmp_path)

    assert before == after, (
        f"predicate mutated the filesystem in scenario {scenario!r}: "
        f"added={sorted(set(after) - set(before))} "
        f"removed={sorted(set(before) - set(after))} "
        f"changed={sorted(k for k in set(before) & set(after) if before[k] != after[k])}"
    )


def test_predicate_acquires_no_lock_of_its_own(tmp_path: Path) -> None:
    """§A5: `_bob_claim_lock` opens a NEW fd per call and takes a blocking
    LOCK_EX. `flock` treats separate open file descriptions as independent even
    within one process, so if the predicate acquired its own lock it would
    block FOREVER once the engine already holds it — shipping a hang rather
    than an error.

    Held here for real, and the predicate is run in a worker thread with a
    watchdog: a nested acquisition never returns.
    """
    _ui_project(tmp_path)
    done = threading.Event()
    result: Dict[str, Any] = {}

    def _run() -> None:
        try:
            result["verdict"] = claims.assert_ui_verified_preconditions(
                IMPL_HASH, tmp_path)
        except BaseException as e:  # noqa: BLE001 - recorded, re-raised by assert
            result["error"] = e
        finally:
            done.set()

    with claims._bob_claim_lock(tmp_path):
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        finished = done.wait(timeout=10)

    assert finished, (
        "predicate did not return within 10s while the claim lock was held — "
        "it acquired a nested lock and would deadlock inside the engine"
    )
    assert "error" not in result, f"predicate raised: {result.get('error')!r}"


# ===========================================================================
# 4. Gate parity — `check_G_V` behaviour is unchanged (§A4)
# ===========================================================================


def _run_gate(root: Path, impl_hash: str = IMPL_HASH) -> int:
    with pytest.raises(SystemExit) as ei:
        gates.check_G_V(impl_hash, root)
    return ei.value.code


def test_gate_happy_path_exit_zero_no_observation(tmp_path: Path, spy: _ObserveSpy) -> None:
    _ui_project(tmp_path)
    assert _run_gate(tmp_path) == 0
    assert spy.calls == [], f"pass path must emit no observation, got {spy.calls!r}"


def test_gate_fingerprints_unchanged_across_failure_paths(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§A4/§A5: exit code, category and fingerprint for EVERY failure path.

    A silently renamed fingerprint breaks downstream observation consumers
    without failing any other test, so the whole set is pinned here in one
    place.
    """
    env_fp = f"G_V-env-{IMPL_HASH[:8]}"
    cases: List[Tuple[str, int, str, Optional[str]]] = [
        # (scenario, exit, category, fingerprint or None for the dynamic env fp)
        ("missing-verdict",     2, "gate_false_block", "verdict-missing"),
        ("malformed-verdict",   2, "gate_false_block", "verdict-malformed"),
        ("unparseable-verdict", 3, "external_tool_fail", env_fp),
        ("arm-missing-arbiter", 2, "gate_false_block", "arm-missing-arbiter"),
        ("arm-missing-drift",   2, "gate_false_block", "arm-missing-drift"),
        ("arbiter-not-pass",    2, "gate_false_block", "arbiter-not-pass"),
        ("drift-not-pass",      2, "gate_false_block", "drift-not-pass"),
        ("no-skeleton-index",   3, "external_tool_fail", env_fp),
        ("skeleton-mismatch",   2, "gate_false_pass", "skeleton-version-mismatch"),
        ("request-id-missing",  2, "gate_false_block", "request-id-missing"),
        ("request-not-found",   2, "gate_false_block", "request-not-found"),
        ("tuple-mismatch",      2, "gate_false_block", "tuple-mismatch"),
        ("consumed-deep-equal", 2, "gate_false_block", "request-not-open"),
        ("consumed-differing",  2, "gate_false_block", "request-not-open"),
    ]

    for scenario, want_exit, want_cat, want_fp in cases:
        root = tmp_path_factory.mktemp(scenario.replace("-", "_"))
        s = _ObserveSpy()
        monkeypatch.setattr(gates, "claude_observe", s)
        _build_gate_scenario(root, scenario)

        with pytest.raises(SystemExit) as ei:
            gates.check_G_V(IMPL_HASH, root)

        assert ei.value.code == want_exit, (
            f"{scenario}: expected exit {want_exit}, got {ei.value.code}"
        )
        assert len(s.calls) == 1, f"{scenario}: expected 1 observation, got {s.calls!r}"
        assert s.category == want_cat, (
            f"{scenario}: expected category {want_cat!r}, got {s.category!r}"
        )
        assert s.fingerprint == want_fp, (
            f"{scenario}: expected fingerprint {want_fp!r}, got {s.fingerprint!r}"
        )
        assert s.severity == ("degraded" if want_exit == 3 else "blocking"), (
            f"{scenario}: unexpected severity {s.severity!r}"
        )


def _build_gate_scenario(root: Path, scenario: str) -> None:
    """Materialise one `check_G_V` failure fixture."""
    if scenario == "no-skeleton-index":
        rec = _open_request(root)
        _write_verdict(root, _verdict(rec))
        return

    _seed_skeleton_index(
        root, skeleton_version="2.0" if scenario == "skeleton-mismatch"
        else SKELETON_VERSION,
    )

    if scenario == "missing-verdict":
        _open_request(root)
        return
    if scenario == "unparseable-verdict":
        _open_request(root)
        _write_verdict(root, None, raw="key: [unclosed\n  bad: : :\n")
        return
    if scenario == "malformed-verdict":
        _open_request(root)
        _write_verdict(root, None, raw="- not\n- a mapping\n")
        return
    if scenario == "request-not-found":
        # A syntactically complete verdict pointing at a request that was
        # never opened.
        rec = _open_request(root)
        v = _verdict(rec, request_id="nonexistent-request-id")
        _write_verdict(root, v)
        return

    rec = _open_request(root)
    if scenario == "arm-missing-arbiter":
        v = _verdict(rec)
        del v["arbiter_verdict"]
    elif scenario == "arm-missing-drift":
        v = _verdict(rec)
        del v["drift_arbiter_verdict"]
    elif scenario == "arbiter-not-pass":
        v = _verdict(rec, arbiter_status="fail")
    elif scenario == "drift-not-pass":
        v = _verdict(rec, drift_status="fail")
    elif scenario == "skeleton-mismatch":
        v = _verdict(rec, skeleton_version="1.0")
    elif scenario == "request-id-missing":
        v = _verdict(rec)
        del v["request_id"]
    elif scenario == "tuple-mismatch":
        v = _verdict(rec, attempt_id="attempt-WRONG")
    elif scenario in ("consumed-deep-equal", "consumed-differing"):
        v = _verdict(rec)
        _write_verdict(root, v)
        claims.consume_visual_verdict(root, rec["request_id"], v)
        if scenario == "consumed-differing":
            # Present a DIFFERENT verdict than the one stored on the record.
            v = _verdict(rec, drift_status="auto_approved")
    else:  # pragma: no cover - guard against typos in the case table
        raise AssertionError(f"unknown scenario {scenario!r}")
    _write_verdict(root, v)


def test_gate_stays_single_use_even_though_predicate_tolerates_consumed(
    tmp_path: Path, spy: _ObserveSpy,
) -> None:
    """§A5, explicitly: on the SAME fixture where the ENGINE accepts a
    consumed-with-deep-equal record, `check_G_V` must STILL exit 2.

    Without this, an executor may "helpfully" make the gate succeed whenever
    the predicate tolerates the record — silently turning a single-use gate
    into a replayable one and breaking §A4's byte-identical guarantee.
    """
    ctx = _ui_project(tmp_path)
    rec, verdict = ctx["record"], ctx["verdict"]

    # Consume once (this is what bob does before transitioning).
    outcome, _ = claims.consume_visual_verdict(tmp_path, rec["request_id"], verdict)
    assert outcome == "accepted"

    # The ENGINE accepts this exact fixture...
    engine = claims.apply_request_idempotent(_ui_request("req-single-use"), tmp_path)
    assert engine["applied"] is True, f"engine should accept: {engine}"

    # ...and the GATE still refuses it.
    assert _run_gate(tmp_path) == 2, "G_V must remain single-use after a consume"
    assert spy.fingerprint == "request-not-open", (
        f"expected 'request-not-open', got {spy.fingerprint!r}"
    )


# ===========================================================================
# 5. THE HOLE — the engine, not just the CLI gate, enforces the verdict
# ===========================================================================


def test_engine_rejects_ui_verified_without_verdict(tmp_path: Path) -> None:
    """The regression test for the hole itself.

    Before S070 this transition could not even reach the engine
    (`check_transition_legal` returned False for the unknown UI stage), so the
    UI lane ran wholly outside the chokepoint. Now it routes through — and is
    refused when no verdict exists.
    """
    _seed_skeleton_index(tmp_path)
    _open_request(tmp_path)
    _seed_ledger(tmp_path, [("WP-7", "screen-a", "UI-INTEGRATED")])
    # No verdict file written.

    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is False
    assert out["outcome"] == "precondition_failed", out
    assert "verdict file missing" in out["reason"]

    # The ledger must be untouched — the engine never half-writes.
    ledger = claims.read_ledger(tmp_path / "progress" / "integration-ledger.md")
    assert ledger.row("WP-7").stage == "UI-INTEGRATED"


@pytest.mark.parametrize("scenario,fragment", [
    ("arbiter-not-pass", "arbiter_verdict.status"),
    ("drift-not-pass", "drift_arbiter_verdict.status"),
    ("skeleton-mismatch", "skeleton bump"),
    ("malformed-verdict", "not a YAML mapping"),
])
def test_engine_rejects_failing_verdicts(tmp_path: Path, scenario: str,
                                         fragment: str) -> None:
    _build_gate_scenario(tmp_path, scenario)
    _seed_ledger(tmp_path, [("WP-7", "screen-a", "UI-INTEGRATED")])
    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is False
    assert out["outcome"] == "precondition_failed", out
    assert fragment in out["reason"], out["reason"]


def test_engine_rejects_when_request_carries_no_impl_hash(tmp_path: Path) -> None:
    _ui_project(tmp_path)
    req = _ui_request()
    del req["impl_hash"]
    out = claims.apply_request_idempotent(req, tmp_path)
    assert out["applied"] is False
    assert out["outcome"] == "precondition_failed"
    assert "no impl_hash" in out["reason"]


def test_engine_env_failure_fails_closed(tmp_path: Path) -> None:
    """§A5: a degraded environment must never be read as a pass. `kind='env'`
    raises the same type, so the engine refuses without needing to branch."""
    _build_gate_scenario(tmp_path, "unparseable-verdict")
    _seed_ledger(tmp_path, [("WP-7", "screen-a", "UI-INTEGRATED")])
    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is False
    assert out["outcome"] == "precondition_failed", out
    assert "unparseable" in out["reason"]

    # And the CLI gate reports the same condition as exit 3.
    assert _run_gate(tmp_path) == 3


def test_engine_accepts_healthy_ui_transition(tmp_path: Path) -> None:
    """The positive control: with a passing, tuple-bound verdict the engine
    applies UI-INTEGRATED -> UI-VERIFIED and writes the ledger."""
    _ui_project(tmp_path)
    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is True, out
    assert (out["from"], out["to"]) == ("UI-INTEGRATED", "UI-VERIFIED")

    ledger_path = tmp_path / "progress" / "integration-ledger.md"
    ledger = claims.read_ledger(ledger_path)
    assert ledger.row("WP-7").stage == "UI-VERIFIED", (
        "the projection row must round-trip — this is where the hyphen bug bit"
    )
    events = claims._parse_event_rows(ledger_path.read_text())
    assert [(e["from"], e["to"]) for e in events] == [
        ("UI-INTEGRATED", "UI-VERIFIED")], events


# ===========================================================================
# 6. Tuple binding + the two-case status rule (§A3.2)
# ===========================================================================


@pytest.mark.parametrize("field,bad", [
    ("attempt_id", "attempt-STALE"),
    ("inventory_hash", "z" * 64),
    ("runner_version", "trusted_runner/0.9"),
    ("rubric_version", "rubric/0.9"),
    ("prior_state_version", "ledger-rev-0"),
    ("skeleton_hash", "z" * 64),
])
def test_engine_rejects_stale_tuple(tmp_path: Path, field: str, bad: str) -> None:
    """§A3.2 freshness: checks 1-4 all pass — same impl_hash, same skeleton
    version, both arms passing — but a tuple field disagrees with the request
    record (e.g. a verdict produced under an older measurement runner for a
    byte-identical artifact). Without this the engine would authorize a
    transition on a stale-but-passing verdict.
    """
    _seed_skeleton_index(tmp_path)
    rec = _open_request(tmp_path)
    _write_verdict(tmp_path, _verdict(rec, **{field: bad}))
    _seed_ledger(tmp_path, [("WP-7", "screen-a", "UI-INTEGRATED")])

    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is False, f"stale {field} must not authorize: {out}"
    assert out["outcome"] == "precondition_failed"
    assert "tuple echo mismatch" in out["reason"]
    assert field in out["reason"]


def test_engine_rejects_missing_request_record(tmp_path: Path) -> None:
    """§A3.2 case 3: the verdict names a request that does not exist."""
    _build_gate_scenario(tmp_path, "request-not-found")
    _seed_ledger(tmp_path, [("WP-7", "screen-a", "UI-INTEGRATED")])
    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is False
    assert out["outcome"] == "precondition_failed"
    assert "not found" in out["reason"]


def test_engine_accepts_consumed_request_with_deep_equal_verdict(tmp_path: Path) -> None:
    """§A3.2 THE case that a naive `status == "open"` breaks.

    bob consumes BEFORE transitioning (bob.md:76), so on the healthy path the
    request is ALREADY `consumed` by the time the engine runs. A naive
    open-only rule passes every other test in this file and breaks the real
    flow — HIGH-1 reborn in read-only form.
    """
    ctx = _ui_project(tmp_path)
    outcome, _ = claims.consume_visual_verdict(
        tmp_path, ctx["record"]["request_id"], ctx["verdict"])
    assert outcome == "accepted"

    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is True, (
        f"consumed-with-deep-equal must be ACCEPTED on the engine path: {out}"
    )


def test_deep_equal_compares_parsed_structures_not_bytes(tmp_path: Path) -> None:
    """§A3.2: `consume_visual_verdict` re-serialises the record canonically
    while the presented verdict file keeps its original formatting, so a byte
    or text comparison false-fails on whitespace and key order alone.

    Here the on-disk verdict is rewritten with a deliberately different key
    order, indentation and quoting style — same parsed structure, different
    bytes. It must still be accepted.
    """
    ctx = _ui_project(tmp_path)
    rec, verdict = ctx["record"], ctx["verdict"]
    claims.consume_visual_verdict(tmp_path, rec["request_id"], verdict)

    stored_raw = (tmp_path / ".design-ledger" / "visual-verdicts"
                  / f"{IMPL_HASH}.verdict.yaml").read_text()
    reordered = yaml.safe_dump(verdict, sort_keys=True, default_flow_style=False,
                               indent=4, width=40)
    assert reordered != stored_raw, (
        "fixture bug: the re-dump must differ BYTE-WISE for this test to mean "
        "anything"
    )
    _write_verdict(tmp_path, None, raw=reordered)

    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is True, (
        f"deep-equal must compare PARSED structures, not bytes: {out}"
    )


def test_engine_rejects_consumed_request_with_differing_verdict(tmp_path: Path) -> None:
    """§A3.2: a consumed record may only re-authorize the IDENTICAL verdict.

    This is the demote-and-reclimb case: a rebuild produced a byte-identical
    impl_hash, so an already-consumed verdict must not silently re-authorize a
    second transition with different content.
    """
    ctx = _ui_project(tmp_path)
    rec, verdict = ctx["record"], ctx["verdict"]
    claims.consume_visual_verdict(tmp_path, rec["request_id"], verdict)

    # Swap in a different (still internally consistent) verdict.
    _write_verdict(tmp_path, _verdict(rec, drift_status="auto_approved"))

    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is False, f"differing stored verdict must reject: {out}"
    assert out["outcome"] == "precondition_failed"
    assert "stored verdict differs" in out["reason"]


def test_engine_rejects_abandoned_request(tmp_path: Path) -> None:
    ctx = _ui_project(tmp_path)
    path = claims._visual_request_path(tmp_path, ctx["record"]["request_id"])
    rec = yaml.safe_load(path.read_text())
    rec["status"] = "abandoned"
    path.write_text(yaml.safe_dump(rec, sort_keys=False))

    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is False
    assert out["outcome"] == "precondition_failed"
    assert "not status=open" in out["reason"]


# ===========================================================================
# 7. Gate-then-engine ordering (the HIGH-1 regression test) + idempotency
# ===========================================================================


def test_gate_then_engine_sequence_succeeds(tmp_path: Path, spy: _ObserveSpy) -> None:
    """§A5 HIGH-1: run `check_G_V` to COMPLETION — which consumes the verdict
    and marks the request `consumed` — and THEN drive the transition through
    `apply_request_idempotent`. The transition MUST succeed.

    This is the exact ordering `bob.md:76` prescribes, and it is the test that
    would have caught the struck engine-side-consumption design: that version
    failed here PERMANENTLY, because requests cannot reopen.
    """
    _ui_project(tmp_path)

    # Step 1: bob runs the gate. Exit 0 and the verdict is now consumed.
    assert _run_gate(tmp_path) == 0
    assert spy.calls == []
    record = yaml.safe_load(
        claims._visual_request_path(
            tmp_path,
            yaml.safe_load((tmp_path / ".design-ledger" / "visual-verdicts"
                            / f"{IMPL_HASH}.verdict.yaml").read_text())["request_id"],
        ).read_text()
    )
    assert record["status"] == "consumed", "the gate must have consumed the verdict"

    # Step 2: bob drives the transition. It must be applied.
    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is True, (
        f"gate-then-engine is the prescribed order and MUST succeed: {out}"
    )
    assert (out["from"], out["to"]) == ("UI-INTEGRATED", "UI-VERIFIED")

    ledger = claims.read_ledger(tmp_path / "progress" / "integration-ledger.md")
    assert ledger.row("WP-7").stage == "UI-VERIFIED"


def test_engine_dedups_replayed_request_id(tmp_path: Path) -> None:
    """§A5 idempotency: replaying the same `request_id` is a no-op."""
    _ui_project(tmp_path)
    first = claims.apply_request_idempotent(_ui_request("req-dedup"), tmp_path)
    assert first["applied"] is True

    second = claims.apply_request_idempotent(_ui_request("req-dedup"), tmp_path)
    assert second["applied"] is False
    assert second["outcome"] == "duplicate_ignored", second

    ledger_path = tmp_path / "progress" / "integration-ledger.md"
    events = claims._parse_event_rows(ledger_path.read_text())
    assert len(events) == 1, f"replay must not append a second event: {events}"


def test_ui_verified_to_documented_completes_the_lane(tmp_path: Path) -> None:
    """End-to-end tail: once UI-VERIFIED, the component can be DOCUMENTED, and
    `DOCUMENTED` carries no visual precondition of its own."""
    _ui_project(tmp_path)
    assert claims.apply_request_idempotent(_ui_request("req-a"), tmp_path)["applied"]
    out = claims.apply_request_idempotent(
        {**_ui_request("req-b"), "to_stage": "DOCUMENTED"}, tmp_path)
    assert out["applied"] is True, out
    ledger = claims.read_ledger(tmp_path / "progress" / "integration-ledger.md")
    assert ledger.row("WP-7").stage == "DOCUMENTED"


def test_engine_rejects_ui_transition_from_wrong_stage(tmp_path: Path) -> None:
    """The ledger is truth for `from_stage`: a component sitting at VERIFIED
    cannot jump straight to UI-VERIFIED, verdict or no verdict."""
    _ui_project(tmp_path, stage="VERIFIED")
    out = claims.apply_request_idempotent(_ui_request(), tmp_path)
    assert out["applied"] is False
    assert out["outcome"] == "illegal_transition", out
