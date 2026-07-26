"""
WP2 — efficacy rollup (S039 efficacy-telemetry v1).

Covers all 4 metrics over synthetic fixtures + the N1 normalization + the
verdict-arm parse guards (the mandated mis-bucketing fixture) + FP coverage/
upper-bound flags + empty-ledger graceful + --format json|text.

Run with:
    pytest ~/.claude/skills/process-observation/tests/test_efficacy_rollup.py -v
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import yaml  # noqa: E402

import rollup  # noqa: E402
import gate_runs  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
NOW_S = NOW.timestamp()
RECENT = _iso(NOW - timedelta(days=1))     # inside a 7d window
OLD = _iso(NOW - timedelta(days=30))       # outside a 7d window


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    (root / "PROJECT.md").write_text("# test\n")
    return root


def _write_jsonl(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")


def _gate_run_pair(gate, code, ts, run_id):
    """A bump (code:null) + outcome (real code) sharing one run_id."""
    return [
        {"ts": ts, "gate": gate, "run_id": run_id, "code": None},
        {"ts": ts, "gate": gate, "run_id": run_id, "code": code},
    ]


# ---------------------------------------------------------------------------
# Metric 1 — gate-fail rate (§6.1 policy table)
# ---------------------------------------------------------------------------

def test_gate_fail_rate_policy_table():
    """fail = exit 2 ONLY; 3 = advisory/env (not fail); 4 = skip (not fail);
    0 = pass."""
    records = []
    # G1: 2 pass, 1 fail(2), 1 advisory/env(3)
    records += _gate_run_pair("G1", 0, RECENT, "r1")
    records += _gate_run_pair("G1", 0, RECENT, "r2")
    records += _gate_run_pair("G1", 2, RECENT, "r3")
    records += _gate_run_pair("G1", 3, RECENT, "r4")
    # G4: 1 skip(4)
    records += _gate_run_pair("G4", 4, RECENT, "r5")
    res = rollup.compute_gate_fail_rate(records, NOW_S - 7 * 86400)
    assert res["numerator"] == 1, "only exit 2 counts as fail"
    assert res["denominator"] == 5
    assert res["rate"] == round(1 / 5, 4)
    assert res["advisory_or_env_count"] == 1, "exit 3 broken out, not a fail"
    assert res["skip_count"] == 1, "exit 4 broken out, not a fail"
    # Per-gate
    assert res["per_gate"]["G1"]["numerator"] == 1
    assert res["per_gate"]["G1"]["denominator"] == 4
    assert res["per_gate"]["G1"]["advisory_or_env_count"] == 1
    assert res["per_gate"]["G4"]["skip_count"] == 1
    assert res["per_gate"]["G4"]["numerator"] == 0


def test_gate_fail_rate_advisory_and_env_not_counted_as_fail():
    """An advisory exit (3) and an env-error exit (3) must NOT inflate the fail
    rate (the §6.1 honesty split)."""
    records = []
    records += _gate_run_pair("G_DEP_CURRENCY", 3, RECENT, "a1")  # advisory
    records += _gate_run_pair("G_XR", 3, RECENT, "a2")            # env-error
    res = rollup.compute_gate_fail_rate(records, NOW_S - 7 * 86400)
    assert res["numerator"] == 0
    assert res["advisory_or_env_count"] == 2
    assert res["rate"] == 0.0


def test_gate_fail_rate_window_filters_old():
    records = []
    records += _gate_run_pair("G1", 2, RECENT, "new")
    records += _gate_run_pair("G1", 2, OLD, "old")
    res = rollup.compute_gate_fail_rate(records, NOW_S - 7 * 86400)
    assert res["denominator"] == 1, "old record outside window excluded"
    assert res["numerator"] == 1


def test_gate_fail_rate_null_code_in_denominator_only():
    """A run killed before terminal exit (code:null, no outcome) counts in the
    denominator but not in any outcome tally."""
    records = [{"ts": RECENT, "gate": "G1", "run_id": "killed", "code": None}]
    res = rollup.compute_gate_fail_rate(records, NOW_S - 7 * 86400)
    assert res["denominator"] == 1
    assert res["numerator"] == 0
    assert res["advisory_or_env_count"] == 0
    assert res["skip_count"] == 0


def test_gate_fail_rate_empty_no_div_by_zero():
    res = rollup.compute_gate_fail_rate([], NOW_S - 7 * 86400)
    assert res["denominator"] == 0
    assert res["rate"] is None  # not a ZeroDivisionError


# ---------------------------------------------------------------------------
# Metric 2 — false-positive rate (§6.2 upper-bound + 6-of-12 coverage)
# ---------------------------------------------------------------------------

def _false_block_event(gate, ts):
    return {
        "ts": ts, "category": "gate_false_block",
        "subject": {"type": "gate", "id": gate},
    }


def test_false_positive_rate_upper_bound_and_coverage():
    events = [
        _false_block_event("G1", RECENT),
        _false_block_event("G1", RECENT),
        _false_block_event("G_V", RECENT),
    ]
    gate_runs_records = []
    for i in range(10):
        gate_runs_records += _gate_run_pair("G1", 0, RECENT, f"g1-{i}")
    for i in range(4):
        gate_runs_records += _gate_run_pair("G_V", 0, RECENT, f"gv-{i}")
    res = rollup.compute_false_positive_rate(
        events, gate_runs_records, NOW_S - 7 * 86400
    )
    assert res["numerator"] == 3  # 2x G1 + 1x G_V
    assert res["denominator"] == 14  # 10 G1 + 4 G_V
    assert res["coverage"] == "6_of_12_gates; upper_bound"
    assert res["per_gate"]["G1"]["coverage"] == "upper_bound"


def test_false_positive_rate_non_false_block_gate_reports_null():
    """A gate NOT in the 6-gate set reports fp null with the coverage flag."""
    events = []
    gate_runs_records = _gate_run_pair("G_SECURE", 0, RECENT, "s1")
    res = rollup.compute_false_positive_rate(
        events, gate_runs_records, NOW_S - 7 * 86400
    )
    assert res["per_gate"]["G_SECURE"]["rate"] is None
    assert res["per_gate"]["G_SECURE"]["coverage"] == "no_false_block_numerator"
    # G_SECURE is excluded from the aggregate numerator/denominator.
    assert res["denominator"] == 0


def test_false_positive_rate_ignores_non_false_block_categories():
    """Other friction categories (e.g. agent_drift) are NOT FP numerator."""
    events = [
        {"ts": RECENT, "category": "agent_drift",
         "subject": {"type": "agent", "id": "G1"}},
    ]
    gate_runs_records = _gate_run_pair("G1", 0, RECENT, "g1")
    res = rollup.compute_false_positive_rate(
        events, gate_runs_records, NOW_S - 7 * 86400
    )
    assert res["numerator"] == 0


# ---------------------------------------------------------------------------
# Metric 3 — dual-verdict disagreement (§6.3, N1) + the parse guards
# ---------------------------------------------------------------------------

def test_n1_normalization_mapping():
    assert rollup._axis_for("VERIFIED") == "pass"
    assert rollup._axis_for("VERIFIED_WITH_CONCERNS") == "pass"
    assert rollup._axis_for("REJECTED") == "fail"
    assert rollup._axis_for("AUDIT_UNAVAILABLE") == "indeterminate"
    # Missing / non-canonical -> indeterminate (fail-safe).
    assert rollup._axis_for(None) == "indeterminate"
    assert rollup._axis_for("garbage") == "indeterminate"
    assert rollup._axis_for(42) == "indeterminate"


def test_verdict_reads_only_canonical_keys_ignores_decoy():
    """audit axis = audit_arm.result; arbiter axis = arbiter_arm.verdict.
    The decoy claude_verdict/codex_verdict sub-vocabulary MUST be ignored."""
    doc = {
        "audit_arm": {
            "result": "VERIFIED",          # canonical -> pass
            "claude_verdict": "fail",      # DECOY — must be ignored
            "codex_verdict": "fail",       # DECOY — must be ignored
        },
        "arbiter_arm": {"verdict": "VERIFIED"},
    }
    audit_axis, arbiter_axis = rollup.classify_verdict_file(doc)
    assert audit_axis == "pass", "must read audit_arm.result, not the decoys"
    assert arbiter_axis == "pass"


def test_mandated_misbucketing_fixture():
    """THE mandated fixture (design §6.3, §11): first_run_result AUDIT_UNAVAILABLE
    in the free-text rerun-history field, but canonical audit_arm.result is
    REJECTED -> MUST bucket as determinate-REJECTED (fail), NOT indeterminate.

    Replicates the real archived file
    1b2917...verdict.yaml shape exactly."""
    doc = {
        "audit_arm": {
            "result": "REJECTED",              # canonical -> fail (determinate!)
            "claude_verdict": "pass_with_concerns",
            "codex_verdict": "fail",
        },
        "arbiter_arm": {"verdict": "VERIFIED_WITH_CONCERNS"},  # -> pass
        "rerun_notes": {
            # The TRAP: a free-text field containing the substring
            # AUDIT_UNAVAILABLE. A naive substring-grep would mis-bucket this
            # determinate verdict as indeterminate.
            "first_run_result": "AUDIT_UNAVAILABLE (component_id mismatch)",
        },
    }
    audit_axis, arbiter_axis = rollup.classify_verdict_file(doc)
    assert audit_axis == "fail", (
        "audit_arm.result=REJECTED must bucket as determinate fail, "
        "NOT indeterminate from the free-text AUDIT_UNAVAILABLE"
    )
    assert arbiter_axis == "pass"
    # Aggregate: it must land in the determinate denominator as a disagreement.
    res = rollup.compute_dual_verdict_disagreement_rate([doc])
    assert res["indeterminate_count"] == 0, "must NOT be indeterminate"
    assert res["denominator"] == 1, "must be in the determinate denominator"
    assert res["numerator"] == 1, "fail vs pass = a disagreement"


def test_audit_unavailable_on_canonical_key_is_indeterminate():
    """When AUDIT_UNAVAILABLE is the CANONICAL audit_arm.result, that arm IS
    indeterminate and the bundle is excluded from the denominator."""
    doc = {
        "audit_arm": {"result": "AUDIT_UNAVAILABLE"},
        "arbiter_arm": {"verdict": "VERIFIED"},
    }
    res = rollup.compute_dual_verdict_disagreement_rate([doc])
    assert res["indeterminate_count"] == 1
    assert res["denominator"] == 0
    assert res["numerator"] == 0


def test_missing_axis_key_is_indeterminate():
    """A missing or malformed canonical key -> that arm indeterminate."""
    doc_missing_audit = {"arbiter_arm": {"verdict": "VERIFIED"}}
    doc_missing_arbiter = {"audit_arm": {"result": "REJECTED"}}
    res1 = rollup.compute_dual_verdict_disagreement_rate([doc_missing_audit])
    res2 = rollup.compute_dual_verdict_disagreement_rate([doc_missing_arbiter])
    assert res1["indeterminate_count"] == 1 and res1["denominator"] == 0
    assert res2["indeterminate_count"] == 1 and res2["denominator"] == 0


def test_dual_verdict_agreement_not_counted():
    docs = [
        {"audit_arm": {"result": "VERIFIED"},
         "arbiter_arm": {"verdict": "VERIFIED"}},                  # agree pass
        {"audit_arm": {"result": "REJECTED"},
         "arbiter_arm": {"verdict": "REJECTED"}},                  # agree fail
        {"audit_arm": {"result": "VERIFIED"},
         "arbiter_arm": {"verdict": "REJECTED"}},                  # DISAGREE
    ]
    res = rollup.compute_dual_verdict_disagreement_rate(docs)
    assert res["denominator"] == 3
    assert res["numerator"] == 1
    assert res["rate"] == round(1 / 3, 4)


def test_dual_verdict_empty_no_div_by_zero():
    res = rollup.compute_dual_verdict_disagreement_rate([])
    assert res["denominator"] == 0
    assert res["rate"] is None


# ---------------------------------------------------------------------------
# Metric — triple-arm disagreement (S048 / #116)
# ---------------------------------------------------------------------------

def test_triple_arm_red_while_llms_pass_is_caught():
    """The HEADLINE caught-correlated-error: deterministic RED while both LLM
    arms pass -> counted in the numerator."""
    doc = {
        "audit_arm": {"result": "VERIFIED"},
        "arbiter_arm": {"verdict": "VERIFIED"},
        "deterministic_arm": {"state": "RED"},
    }
    res = rollup.compute_triple_arm_disagreement([doc])
    assert res["denominator"] == 1
    assert res["numerator"] == 1
    assert res["red_while_llms_pass"] == 1
    assert res["rate"] == 1.0


def test_triple_arm_indeterminate_while_llms_pass_is_caught():
    doc = {
        "audit_arm": {"result": "VERIFIED_WITH_CONCERNS"},
        "arbiter_arm": {"verdict": "VERIFIED"},
        "deterministic_arm": {"state": "INDETERMINATE"},
    }
    res = rollup.compute_triple_arm_disagreement([doc])
    assert res["numerator"] == 1
    assert res["indeterminate_while_llms_pass"] == 1


def test_triple_arm_green_agreement_not_counted():
    doc = {
        "audit_arm": {"result": "VERIFIED"},
        "arbiter_arm": {"verdict": "VERIFIED"},
        "deterministic_arm": {"state": "GREEN"},
    }
    res = rollup.compute_triple_arm_disagreement([doc])
    assert res["denominator"] == 1
    assert res["numerator"] == 0


def test_triple_arm_unrecorded_excluded():
    """A pre-S048 archive with no deterministic state -> unrecorded, excluded
    from numerator AND denominator (never guessed)."""
    doc = {"audit_arm": {"result": "VERIFIED"}, "arbiter_arm": {"verdict": "VERIFIED"}}
    res = rollup.compute_triple_arm_disagreement([doc])
    assert res["unrecorded_count"] == 1
    assert res["denominator"] == 0
    assert res["numerator"] == 0


def test_triple_arm_red_but_llm_already_rejected_not_counted():
    """If an LLM arm already REJECTED, deterministic RED is NOT a 'correlated
    error' (the LLMs did NOT both pass) -> not in the numerator."""
    doc = {
        "audit_arm": {"result": "REJECTED"},
        "arbiter_arm": {"verdict": "VERIFIED"},
        "deterministic_arm": {"state": "RED"},
    }
    res = rollup.compute_triple_arm_disagreement([doc])
    assert res["denominator"] == 1  # both LLM axes determinate
    assert res["numerator"] == 0    # but not both-pass -> not a triple disagreement


def test_triple_arm_llm_indeterminate_excluded_from_denominator():
    doc = {
        "audit_arm": {"result": "AUDIT_UNAVAILABLE"},
        "arbiter_arm": {"verdict": "VERIFIED"},
        "deterministic_arm": {"state": "RED"},
    }
    res = rollup.compute_triple_arm_disagreement([doc])
    assert res["denominator"] == 0  # an LLM axis is indeterminate
    assert res["numerator"] == 0


def test_triple_arm_quality_and_citation_counters():
    docs = [
        {"audit_arm": {"result": "VERIFIED"}, "arbiter_arm": {"verdict": "VERIFIED"},
         "deterministic_arm": {"state": "GREEN", "evidence_quality": "degraded"}},
        {"audit_arm": {"result": "VERIFIED"}, "arbiter_arm": {"verdict": "VERIFIED"},
         "deterministic_arm": {"state": "GREEN", "citation": {"status": "veto"}}},
    ]
    res = rollup.compute_triple_arm_disagreement(docs)
    assert res["evidence_quality_degraded_count"] == 1
    assert res["citation_veto_count"] == 1


def test_triple_arm_empty_no_div_by_zero():
    res = rollup.compute_triple_arm_disagreement([])
    assert res["denominator"] == 0
    assert res["rate"] is None


def test_triple_arm_in_rollup_and_render(proj):
    roll = rollup.compute_rollup(proj, 7 * 86400, now_s=NOW_S)
    assert "triple_arm_disagreement" in roll
    txt = rollup.render(roll, fmt="text")
    assert "triple_arm_disagreement:" in txt


# ---------------------------------------------------------------------------
# Metric 4 — user-override rate (§6.4)
# ---------------------------------------------------------------------------

def _scope_delta(status, created_at):
    return {"status": status, "created_at": created_at}


def test_user_override_rate():
    recs = [
        _scope_delta("amended", RECENT),
        _scope_delta("excluded", RECENT),
        _scope_delta("undecided", RECENT),
        _scope_delta("undecided", RECENT),
    ]
    res = rollup.compute_user_override_rate(recs, NOW_S - 7 * 86400)
    assert res["numerator"] == 2  # amended + excluded
    assert res["denominator"] == 4
    assert res["rate"] == 0.5
    assert res["not_yet_instrumented"] == ["git_no_verify", "escalation_override"]


def test_user_override_rate_window_filters_old():
    recs = [
        _scope_delta("amended", RECENT),
        _scope_delta("excluded", OLD),
    ]
    res = rollup.compute_user_override_rate(recs, NOW_S - 7 * 86400)
    assert res["denominator"] == 1
    assert res["numerator"] == 1


def test_user_override_rate_empty():
    res = rollup.compute_user_override_rate([], NOW_S - 7 * 86400)
    assert res["denominator"] == 0
    assert res["rate"] is None


# ---------------------------------------------------------------------------
# Top-level rollup + forward-looking window honesty + render
# ---------------------------------------------------------------------------

def test_compute_rollup_schema_and_window_start(proj):
    obs = proj / ".process-observations"
    # Establish a denominator window start via the real writer.
    gate_runs.bump_gate_run("G1", project_root_override=proj)
    gate_runs.record_gate_outcome("G1", 2, project_root_override=proj)
    roll = rollup.compute_rollup(proj, 7 * 86400, window_label="7d", now_s=NOW_S)
    assert roll["schema"] == "efficacy-rollup.v1"
    assert roll["window"] == "7d"
    # denominator_window_start surfaced (forward-looking honesty, §9).
    assert roll["denominator_window_start"] is not None
    for metric in ("gate_fail_rate", "false_positive_rate",
                   "dual_verdict_disagreement_rate", "user_override_rate"):
        assert metric in roll


def test_forward_looking_window_start_none_when_no_bump(proj):
    """No gate run yet -> denominator_window_start is null, so a too-young
    baseline is self-evident (§9)."""
    roll = rollup.compute_rollup(proj, 7 * 86400, now_s=NOW_S)
    assert roll["denominator_window_start"] is None


def test_empty_project_graceful(proj):
    """Totally empty .process-observations + no .ledger -> all rates null, no
    crash (§11 empty-ledger graceful)."""
    roll = rollup.compute_rollup(proj, 7 * 86400, now_s=NOW_S)
    assert roll["gate_fail_rate"]["rate"] is None
    assert roll["false_positive_rate"]["rate"] is None
    assert roll["dual_verdict_disagreement_rate"]["rate"] is None
    assert roll["user_override_rate"]["rate"] is None


def test_render_json_is_canonical():
    roll = {"schema": "efficacy-rollup.v1", "b": 1, "a": 2}
    out = rollup.render(roll, fmt="json")
    # sorted keys, compact
    assert out.strip() == '{"a":2,"b":1,"schema":"efficacy-rollup.v1"}'


def test_render_text_includes_all_four_metrics(proj):
    roll = rollup.compute_rollup(proj, 7 * 86400, now_s=NOW_S)
    txt = rollup.render(roll, fmt="text")
    assert "gate_fail_rate:" in txt
    assert "false_positive_rate:" in txt
    assert "dual_verdict_disagreement_rate:" in txt
    assert "user_override_rate:" in txt
    assert "denominator_window_start:" in txt


# ---------------------------------------------------------------------------
# CLI integration (query.py rollup op) — both formats render
# ---------------------------------------------------------------------------

_QUERY_PY = _SCRIPTS / "query.py"


def _run_query(args, cwd):
    proc = subprocess.run(
        [sys.executable, str(_QUERY_PY)] + args,
        cwd=str(cwd), capture_output=True, text=True,
    )
    return proc


def test_cli_rollup_json(proj):
    proc = _run_query(
        ["rollup", "--project-root", str(proj), "--window", "7d",
         "--format", "json"],
        cwd=proj,
    )
    assert proc.returncode == 0, proc.stderr
    obj = json.loads(proc.stdout)
    assert obj["schema"] == "efficacy-rollup.v1"


def test_cli_rollup_text(proj):
    proc = _run_query(
        ["rollup", "--project-root", str(proj), "--format", "text"],
        cwd=proj,
    )
    assert proc.returncode == 0, proc.stderr
    assert "efficacy-rollup" in proc.stdout
    assert "gate_fail_rate:" in proc.stdout


def test_cli_rollup_default_format_is_json(proj):
    proc = _run_query(["rollup", "--project-root", str(proj)], cwd=proj)
    assert proc.returncode == 0, proc.stderr
    json.loads(proc.stdout)  # parses as JSON


def test_cli_rollup_against_real_archive():
    """End-to-end against the 24 real s028 verdict files incl. the trap case.
    The disagreement metric must have 0 indeterminate (trap not mis-bucketed)."""
    archive = Path(
        "/path/to/foundry-lab/progress/archive/s028-ecosystem-keystone"
    )
    if not (archive / ".ledger" / "verdicts").is_dir():
        pytest.skip("real archive not present")
    proc = _run_query(
        ["rollup", "--project-root", str(archive), "--window", "3650d",
         "--format", "json"],
        cwd="/tmp",
    )
    assert proc.returncode == 0, proc.stderr
    obj = json.loads(proc.stdout)
    dv = obj["dual_verdict_disagreement_rate"]
    assert dv["indeterminate_count"] == 0, (
        "trap file must NOT be mis-bucketed as indeterminate"
    )
    assert dv["denominator"] == 24
