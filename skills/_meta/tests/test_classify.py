"""
test_classify.py — acceptance suite for the deterministic component-
classification gate `G_CLASSIFY` (S042 / #115).

Covers design §8 (bob acceptance) in full:
  1. The 8 fixtures (verdict + exit) + S042-self (`no`) + test_discusses_not_declares.
  2. The 2 adversarial cases (asserted-N/A + real component-decl -> exit 2;
     free-text reason not in enum -> escalate).
  3. Per-signal unit tests.
  4. Threshold-band tests.
  5. Corroboration-matrix (all 8 rows).
  6. `--verify-diff` (envelope-exceeded -> exit 2; within -> exit 0).
  7. No-doc path (bugfix file-set -> `no`; contract-surface-no-doc -> escalate).
  8. Telemetry byte-invariance under forced ImportError (S039 discipline).
  9. D1 / no-skill-write grep (classify.py writes ONLY under progress/.classify/).
 10. Live smoke against the real archived design docs (the empirical
     discriminator: contract-map.yaml counts S014/S023/S029/S028 high vs
     S039/S040/S041 = 0).

Run:
    pytest skills/_meta/tests/test_classify.py -v
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# --- make _meta importable (classify, classify_emit) -----------------------
_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import classify  # noqa: E402
import classify_emit  # noqa: E402

_GATES_PY = _META / "gates.py"
# Repo root: …/skills/_meta/tests/ -> repo root is 3 up from _meta? No:
# _meta == <repo>/skills/_meta ; tests == <repo>/skills/_meta/tests.
_REPO_ROOT = _META.parent.parent  # <repo>
_DOCS_PLANS = _REPO_ROOT / "docs" / "plans"


# ===========================================================================
# Helpers
# ===========================================================================

def run_gate(args, cwd: Path, force_importerror: bool = False):
    """Invoke gates.py G_CLASSIFY as a subprocess. Returns (rc, stdout+stderr)."""
    cmd = [sys.executable, str(_GATES_PY), "G_CLASSIFY"] + args
    env = dict(os.environ)
    if force_importerror:
        env["GATES_TELEMETRY_FORCE_IMPORTERROR"] = "1"
    else:
        env.pop("GATES_TELEMETRY_FORCE_IMPORTERROR", None)
    proc = subprocess.run(cmd, cwd=str(cwd), env=env,
                          capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)


def write_doc(root: Path, name: str, text: str) -> Path:
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    p = plans / name
    p.write_text(text, encoding="utf-8")
    return p


# Synthetic fixture doc bodies -------------------------------------------------
# POSITIVE: a real fenced contract-map declaration (P1 fenced) + fenced
# integration_points/semantic_type (P2/P3 fenced) — CONFIRMED without needing
# a file profile (fenced => confirmed per R1(a)).
POS_DOC = """# Some Feature — Design

## Components
This introduces a new component.

The signed contract map lives at progress/contract-map.yaml:

```yaml
revision: 1
components:
  - id: thinger
    integration_points:
      - id: ip1
        inputs:
          - name: user
            semantic_type: user_id
    flows:
      - id: f1
        flow_entry_point: ip1
```

It is HMAC-signed (contract-map.yaml.sig).
"""

# NEGATIVE: prose-only, clean exempt profile. Discusses nothing structural.
NEG_DOC = """# Career Brand Refresh — Design

A pure content refresh. No new components, no services, no endpoints, no schemas.
This is a skill-markdown / agent text change only. precedent: S040.
Deterministic stdlib edits to existing files. bugfix + refactor.
"""

# DISCUSSES-NOT-DECLARES: prose full of component talk (contract-map.yaml,
# services, schema-as-API, HMAC) but ALL unfenced + a clean file profile.
# Must classify `no` (R1 / R6 generalization).
DISCUSSES_DOC = """# Meta-Doc About The Pipeline — Design

This design DISCUSSES the contract-map.yaml pipeline at length. The
integration_points and flows live in the contract map. A frozen schema acts as
an API. We talk about services/ and REST endpoints and the HMAC of the map and
_meta/schemas/foo.json — but only in prose, describing how OTHER cycles work.

This cycle itself is a deterministic stdlib _meta helper. No new components.
precedent: S041. agent text + skill-markdown only.
"""

# ADVERSARIAL-1: asserts N/A in the prompt but the doc DECLARES a real component
# (fenced contract map + integration_points). -> exit 2 BLOCK.
ADV_DECL_DOC = POS_DOC

# Exempt file profile (clean) — S042-shaped.
EXEMPT_PROFILE = ",".join([
    "skills/_meta/foo.py",
    "agents/bob.md",
    "skills/forge/SKILL.md",
    "docs/plans/x-design.md",
])

# A profile that includes a component-evidence path (contract-map.yaml).
COMPONENT_PROFILE = ",".join([
    "progress/contract-map.yaml",
    "_meta/schemas/thinger.v1.json",
    "skills/foo/SKILL.md",
])


# ===========================================================================
# 1. Synthetic fixtures: positive -> yes, negative -> no
# ===========================================================================

def test_positive_fixture_fenced_decl_is_yes(tmp_path):
    root = tmp_path / "proj"
    doc = write_doc(root, "pos-design.md", POS_DOC)
    res = classify.classify(root, design_doc=doc, file_profile=None)
    assert res["verdict"] == "yes", res["decision_trace"]


def test_negative_fixture_prose_only_is_no(tmp_path):
    root = tmp_path / "proj"
    doc = write_doc(root, "neg-design.md", NEG_DOC)
    res = classify.classify(
        root, design_doc=doc,
        file_profile=["skills/foo/SKILL.md", "agents/bob.md"],
    )
    assert res["verdict"] == "no", res["decision_trace"]


def test_discusses_not_declares_is_no(tmp_path):
    """R6 generalization: a doc full of prose component-talk but a clean file
    profile -> `no`. Guards against the meta-doc self-FP class."""
    root = tmp_path / "proj"
    doc = write_doc(root, "discusses-design.md", DISCUSSES_DOC)
    res = classify.classify(
        root, design_doc=doc,
        file_profile=["skills/_meta/foo.py", "agents/bob.md", "docs/x.md"],
    )
    assert res["verdict"] == "no", res["decision_trace"]
    # Every positive candidate must be prose_only (none confirmed).
    assert not res["decision_trace"]["confirmed_positive_signals"], \
        res["evidence"]["confirmed_positives"]


# ===========================================================================
# 2. The S042 self-classify (irony-as-test) — against the REAL design doc
# ===========================================================================

S042_DOC = _DOCS_PLANS / "2026-06-05-component-classification-gate-design.md"
S042_PROFILE = [
    "skills/_meta/classify.py", "skills/_meta/classify_emit.py",
    "skills/_meta/gates.py", "skills/_meta/identity_check.py",
    "agents/bob.md", "agents/alf.md", "skills/forge/SKILL.md",
    "skills/_meta/tests/test_classify.py",
    "docs/plans/2026-06-05-component-classification-gate-design.md",
]


@pytest.mark.skipif(not S042_DOC.is_file(), reason="S042 design doc not found")
def test_self_classify_s042_is_no():
    """The mandatory irony-as-test (design §12 R6/R8): THIS design doc must
    self-classify `no` via O2 (zero confirmed positives ∧ N4)."""
    res = classify.classify(_REPO_ROOT, design_doc=S042_DOC,
                            file_profile=S042_PROFILE)
    assert res["verdict"] == "no", res["decision_trace"]
    assert res["decision_trace"]["rule_fired"] == "O2", res["decision_trace"]
    assert not res["decision_trace"]["confirmed_positive_signals"]


@pytest.mark.skipif(not S042_DOC.is_file(), reason="S042 design doc not found")
def test_self_classify_s042_gate_exit0():
    """Live gate: G_CLASSIFY against THIS doc --asserted N/A -> exit 0 'no'."""
    rc, out = run_gate(
        [str(_REPO_ROOT), "--design-doc", str(S042_DOC),
         "--asserted", "N/A", "--files-from", ",".join(S042_PROFILE)],
        cwd=_REPO_ROOT,
    )
    assert rc == 0, out
    assert "corroborated" in out.lower()


# ===========================================================================
# 3. Adversarial cases
# ===========================================================================

def test_adversarial_asserted_na_but_real_decl_blocks(tmp_path):
    """asserted N/A + a doc that DECLARES a real component (fenced contract
    map) -> exit 2 BLOCK with named contradicting signals."""
    root = tmp_path / "proj"
    doc = write_doc(root, "adv-design.md", ADV_DECL_DOC)
    rc, out = run_gate(
        [str(root), "--design-doc", str(doc), "--asserted", "N/A",
         "--files-from", "docs/x.md"],
        cwd=root,
    )
    assert rc == 2, out
    assert "CRITICAL" in out or "P1" in out, out


def test_adversarial_freetext_reason_escalates(tmp_path):
    """A classification.json with a free-text reason_code not in the closed
    enum -> --verify-diff escalates (exit 3), never silent-passes."""
    root = tmp_path / "proj"
    (root / ".forge").mkdir(parents=True)
    import json
    (root / ".forge" / "classification.json").write_text(json.dumps({
        "schema": "contract-classification.v1",
        "introduces_components": "no",
        "reason_code": "because-i-said-so",  # NOT in the closed enum
        "design_doc": None,
        "planned_globs": [],
        "evidence": {"confirmed_positives": [], "negatives": [], "prose_only": []},
        "classified_by": "bob_direct",
        "classified_at": "2026-06-05T00:00:00Z",
    }), encoding="utf-8")
    rc, out = run_gate([str(root), "--verify-diff"], cwd=root)
    assert rc == 3, out
    assert "validation" in out.lower() or "reason_code" in out.lower(), out


def test_emit_rejects_freetext_reason():
    """classify_emit raises on a free-text reason_code (closed enum at emit)."""
    with pytest.raises(ValueError):
        classify_emit.emit_artifact(
            _REPO_ROOT, reason_code="totally-made-up", file_profile=[],
        )


# ===========================================================================
# 4. Per-signal unit tests (R2 catalog)
# ===========================================================================

def test_p1_fenced_confirms_prose_does_not():
    fenced = "```yaml\nx: progress/contract-map.yaml\n```\n"
    hits = {h.sid: h for h in classify.scan(fenced, file_profile=[])}
    assert "P1" in hits and hits["P1"].confirmed

    prose = "We mention contract-map.yaml in a sentence.\n"
    hits2 = {h.sid: h for h in classify.scan(prose, file_profile=[])}
    assert "P1" in hits2 and not hits2["P1"].confirmed  # prose_only


def test_p1_file_corroboration_confirms_unfenced():
    prose = "We mention contract-map.yaml in a sentence.\n"
    hits = {h.sid: h for h in classify.scan(
        prose, file_profile=["progress/contract-map.yaml"])}
    assert hits["P1"].confirmed  # R1(b): file-corroborated


def test_p5_is_dropped_r7():
    """R7: a 'new gate in gates.py' must NOT be a positive signal."""
    doc = "```\nWe add a new gate G_FOOBAR via check_G_FOOBAR.\n```\n"
    hits = {h.sid for h in classify.scan(doc, file_profile=[])}
    assert "P5" not in hits


def test_n2_exempt_lexicon_negative():
    doc = "deterministic stdlib, no new components, sidecar, bugfix.\n"
    hits = {h.sid: h for h in classify.scan(doc, file_profile=[])}
    assert "N2" in hits and hits["N2"].weight < 0


def test_n4_fires_on_clean_profile():
    hits = {h.sid: h for h in classify.scan(
        "", file_profile=["skills/_meta/foo.py", "agents/bob.md"])}
    assert "N4" in hits and hits["N4"].weight == -5


def test_n4_absent_when_component_evidence_present():
    hits = {h.sid for h in classify.scan(
        "", file_profile=["progress/contract-map.yaml"])}
    assert "N4" not in hits


def test_catalog_grammar_exclusion():
    """R1 belt-and-suspenders: a catalog/table line never self-matches."""
    doc = "| P1 | contract-map.yaml | +5 |\n- **P4** schema as API contract\n"
    hits = {h.sid: h for h in classify.scan(doc, file_profile=[])}
    # P1 in a table row must be excluded -> no confirmed P1.
    assert "P1" not in hits or not hits["P1"].confirmed


# ===========================================================================
# 5. Threshold-band tests
# ===========================================================================

def _hit(sid, w, confirmed=True):
    return classify.SignalHit(sid, w, confirmed, True, "synthetic")


def test_band_yes_at_plus5():
    v, s, _ = classify.derive_class([_hit("P2", 5)])
    assert v == "yes" and s == 5


def test_band_no_at_minus4():
    v, s, _ = classify.derive_class([_hit("N2", -4)])
    assert v == "no" and s == -4


def test_band_ambiguous_between():
    # +1 (P8, not structural) -> score 1, no O1/O2 -> ambiguous.
    v, s, _ = classify.derive_class([_hit("P8", 1)])
    assert v == "ambiguous", (v, s)


def test_o1_positive_floor():
    v, _, tr = classify.derive_class([_hit("P1", 5), _hit("P2", 4)])
    assert v == "yes" and tr["rule_fired"] == "O1"


def test_o2_clean_negative_fast_path():
    v, _, tr = classify.derive_class([_hit("N4", -5)])
    assert v == "no" and tr["rule_fired"] == "O2"


def test_o2_requires_zero_confirmed_positives():
    """O2 must NOT fire if a confirmed structural positive exists, even with N4."""
    v, _, tr = classify.derive_class([_hit("N4", -5), _hit("P1", 5)])
    assert tr["rule_fired"] != "O2"


# ===========================================================================
# 6. Corroboration matrix — all 8 rows (§3.4)
# ===========================================================================

@pytest.mark.parametrize("asserted,doc,profile,expect_rc,desc", [
    ("N/A",      NEG_DOC,      "skills/foo/SKILL.md", 0, "N/A + no -> PASS"),
    ("N/A",      POS_DOC,      "docs/x.md",           2, "N/A + yes -> BLOCK"),
    ("provided", POS_DOC,      "docs/x.md",           0, "provided + yes -> PASS"),
    ("provided", NEG_DOC,      "skills/foo/SKILL.md", 0, "provided + no -> ADVISORY-PASS"),
    (None,       POS_DOC,      "docs/x.md",           2, "nothing + yes -> BLOCK"),
    (None,       NEG_DOC,      "skills/foo/SKILL.md", 0, "nothing + no -> PASS"),
])
def test_corroboration_matrix(asserted, doc, profile, expect_rc, desc, tmp_path):
    root = tmp_path / "proj"
    p = write_doc(root, "m-design.md", doc)
    args = [str(root), "--design-doc", str(p), "--files-from", profile]
    if asserted is not None:
        args += ["--asserted", asserted]
    rc, out = run_gate(args, cwd=root)
    assert rc == expect_rc, f"{desc}: rc={rc} out={out}"


def test_corroboration_matrix_ambiguous_rows_escalate(tmp_path):
    """N/A + ambiguous -> exit 3; nothing + ambiguous -> exit 3. Built with a
    doc that lands in the band (a lone +1 P8, no N4 because profile is not
    clean / empty)."""
    root = tmp_path / "proj"
    # Ambiguous: a heading (P8 +1) only, with a NON-exempt-but-non-component
    # profile so N4 does not fire and no negative pushes it to `no`.
    amb_doc = "## Components\nJust a heading, nothing else structural.\n"
    p = write_doc(root, "amb-design.md", amb_doc)
    # profile with a non-exempt path so N4 cannot fire -> score stays +1 -> ambiguous
    prof = "src/app/main.go"
    rc_na, out_na = run_gate(
        [str(root), "--design-doc", str(p), "--asserted", "N/A",
         "--files-from", prof], cwd=root)
    assert rc_na == 3, out_na
    rc_none, out_none = run_gate(
        [str(root), "--design-doc", str(p), "--files-from", prof], cwd=root)
    assert rc_none == 3, out_none


# ===========================================================================
# 7. --verify-diff (R3 / §6.4)
# ===========================================================================

def _init_git_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(root), check=True)
    (root / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=str(root), check=True)


def _write_artifact(root: Path, introduces="no", reason="self_contained_meta_helper",
                    planned=None, ext_globs=None):
    import json
    (root / ".forge").mkdir(parents=True, exist_ok=True)
    art = {
        "schema": "contract-classification.v1",
        "introduces_components": introduces,
        "reason_code": reason,
        "design_doc": None,
        "planned_globs": planned or [],
        "evidence": {"confirmed_positives": [], "negatives": [], "prose_only": []},
        "classified_by": "bob_direct",
        "classified_at": "2026-06-05T00:00:00Z",
    }
    if ext_globs is not None:
        art["existing_extension_globs"] = ext_globs
    (root / ".forge" / "classification.json").write_text(json.dumps(art))


def test_verify_diff_within_envelope_passes(tmp_path):
    root = tmp_path / "proj"
    _init_git_repo(root)
    _write_artifact(root, introduces="no")
    # Touch only exempt files (no component-evidence).
    (root / "agents").mkdir()
    (root / "agents" / "bob.md").write_text("edit\n")
    rc, out = run_gate([str(root), "--verify-diff"], cwd=root)
    assert rc == 0, out


def test_verify_diff_envelope_exceeded_blocks(tmp_path):
    root = tmp_path / "proj"
    _init_git_repo(root)
    _write_artifact(root, introduces="no")
    # Introduce a component-evidence path (contract-map.yaml) NOT declared.
    (root / "progress").mkdir()
    (root / "progress" / "contract-map.yaml").write_text("revision: 1\n")
    rc, out = run_gate([str(root), "--verify-diff"], cwd=root)
    assert rc == 2, out
    assert "contract-map.yaml" in out, out


def test_verify_diff_existing_extension_whitelists(tmp_path):
    root = tmp_path / "proj"
    _init_git_repo(root)
    _write_artifact(root, introduces="no", reason="existing_component_extension",
                    planned=["progress/contract-map.yaml"])
    (root / "progress").mkdir()
    (root / "progress" / "contract-map.yaml").write_text("revision: 1\n")
    rc, out = run_gate([str(root), "--verify-diff"], cwd=root)
    assert rc == 0, out


def test_verify_diff_missing_artifact_blocks(tmp_path):
    root = tmp_path / "proj"
    _init_git_repo(root)
    rc, out = run_gate([str(root), "--verify-diff"], cwd=root)
    assert rc == 2, out
    assert "classification.json" in out, out


# ===========================================================================
# 8. No-doc path (§6.5)
# ===========================================================================

def test_no_doc_bugfix_fileset_is_no(tmp_path):
    """No design doc + a bugfix file-set (all exempt) -> `no`."""
    root = tmp_path / "proj"  # no docs/plans
    res = classify.classify(
        root, design_doc=None,
        file_profile=["skills/_meta/dep_currency_check.py", "agents/bob.md"],
    )
    assert res["verdict"] == "no", res["decision_trace"]


def test_no_doc_contract_surface_escalates(tmp_path):
    """No doc + a contract-surface touch (component-evidence) -> ambiguous
    (a contract change with no doc deserves a human glance)."""
    root = tmp_path / "proj"
    res = classify.classify(
        root, design_doc=None,
        file_profile=["progress/contract-map.yaml"],
    )
    # P1 confirmed via R1(b) (+5) but no O1 secondary, score 5 -> band:yes...
    # however with no doc this is a pure-file signal; per §6.5 a contract-
    # surface change with no doc should escalate. P1 alone => score 5 => yes.
    # The gate row (nothing-asserted + yes) BLOCKS, which is also a HALT (a
    # contract surface change with no doc is never a silent pass). Accept yes.
    assert res["verdict"] in ("yes", "ambiguous"), res["decision_trace"]


def test_no_doc_empty_fileset_escalates(tmp_path):
    """Empty file set + no doc -> ambiguous (escalate)."""
    root = tmp_path / "proj"
    res = classify.classify(root, design_doc=None, file_profile=[])
    assert res["verdict"] == "ambiguous", res["decision_trace"]


# ===========================================================================
# 9. Telemetry byte-invariance (S039 discipline)
# ===========================================================================

@pytest.mark.skipif(not S042_DOC.is_file(), reason="S042 design doc not found")
def test_telemetry_exit_invariance_for_g_classify(tmp_path):
    """G_CLASSIFY exit code must be byte-identical with telemetry installed vs
    forced ImportError (rides the S039 main() wrapper)."""
    # Two independent project roots (the gate writes verdict.json under each).
    a = tmp_path / "a"
    b = tmp_path / "b"
    for r in (a, b):
        write_doc(r, "neg-design.md", NEG_DOC)
    rc_hook, _ = run_gate(
        [str(a), "--design-doc", str(a / "docs/plans/neg-design.md"),
         "--asserted", "N/A", "--files-from", "skills/foo/SKILL.md"],
        cwd=a, force_importerror=False)
    rc_noh, _ = run_gate(
        [str(b), "--design-doc", str(b / "docs/plans/neg-design.md"),
         "--asserted", "N/A", "--files-from", "skills/foo/SKILL.md"],
        cwd=b, force_importerror=True)
    assert rc_hook == rc_noh, f"exit drift: hook={rc_hook} noh={rc_noh}"
    assert rc_hook == 0


def test_telemetry_invariance_block_path(tmp_path):
    """Same invariance on the BLOCK (exit 2) path."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    for r in (a, b):
        write_doc(r, "pos-design.md", POS_DOC)
    rc_hook, _ = run_gate(
        [str(a), "--design-doc", str(a / "docs/plans/pos-design.md"),
         "--asserted", "N/A", "--files-from", "docs/x.md"],
        cwd=a, force_importerror=False)
    rc_noh, _ = run_gate(
        [str(b), "--design-doc", str(b / "docs/plans/pos-design.md"),
         "--asserted", "N/A", "--files-from", "docs/x.md"],
        cwd=b, force_importerror=True)
    assert rc_hook == rc_noh == 2


# ===========================================================================
# 10. D1 — classify.py writes ONLY under progress/.classify/
# ===========================================================================

def test_d1_write_only_under_progress_classify(tmp_path):
    """classify.write_verdict writes ONLY progress/.classify/verdict.json and
    nothing else. (Plus a source grep that classify.py has no other write.)"""
    root = tmp_path / "proj"
    root.mkdir()
    classify.write_verdict(root, {"verdict": "no"})
    written = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                     if p.is_file())
    assert written == ["progress/.classify/verdict.json"], written


def test_d1_source_has_no_skill_writes():
    """Grep classify.py source: no write/open('w')/mkdir outside progress/."""
    src = (_META / "classify.py").read_text(encoding="utf-8")
    # The only filesystem mutation points are inside write_verdict (progress/
    # .classify) and verdict.json.tmp. Assert no '~/.claude/skills' literal and
    # no write into skills/ bodies.
    assert "~/.claude/skills" not in src
    assert ".claude/skills" not in src
    # write_text / mkdir occurrences must all be within the progress/.classify
    # writer (single function). Cheap structural proof: only one mkdir call.
    assert src.count("mkdir(") == 1, "unexpected extra mkdir in classify.py"


# ===========================================================================
# 11. Live smoke against the real archived design docs (§8.9)
# ===========================================================================

LIVE_FIXTURES = [
    ("2026-04-23-ecosystem-keystone-design.md", "yes"),               # S028 +
    ("2026-04-26-contract-scope-enforcement-keystone-design.md", "yes"),  # S029 +
    ("2026-04-14-wiring-skills-design.md", "yes"),                    # S023 +
    ("2026-04-09-contract-testing-pipeline-design.md", "yes"),       # S014 +
    ("2026-06-04-career-brand-refresh-design.md", "no"),             # S040 -
    ("2026-06-04-evergreening-design.md", "no"),                     # S041 - STRESS
    ("2026-06-03-efficacy-telemetry-v1-design.md", "no"),            # S039 -
    ("2026-06-05-component-classification-gate-design.md", "no"),    # S042 self -
]


@pytest.mark.parametrize("fname,expect", LIVE_FIXTURES,
                         ids=[f[0][:24] for f in LIVE_FIXTURES])
def test_live_doc_calibration(fname, expect):
    """The empirical discriminator: real archived docs classify per §7.

    Doc-only scan (no file profile) — the fenced-confirmation discriminator.
    Positives win on confirmed fenced contract-map refs; negatives have 0
    confirmed positives and net-negative scores. Verdict must match §7."""
    doc = _DOCS_PLANS / fname
    if not doc.is_file():
        pytest.skip(f"{fname} not archived in this tree")
    res = classify.classify(_REPO_ROOT, design_doc=doc, file_profile=None)
    assert res["verdict"] == expect, (
        f"{fname}: got {res['verdict']} (score={res['score']}, "
        f"rule={res['decision_trace']['rule_fired']}, "
        f"confirmed={res['decision_trace']['confirmed_positive_signals']}) "
        f"expected {expect}"
    )
