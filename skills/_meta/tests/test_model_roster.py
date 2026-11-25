#!/usr/bin/env python3
"""Tests for model_roster.py and its wiring into seat_model (#291 design s3.1, s3.2, s3.9).

What is covered here (WP-1):
  * model_roster.py is DATA ONLY: literal assignments, no import/def/class/open.
  * every roster invariant, each violated on its own: roster_violations() names it in-process,
    AND a FRESH `import seat_model` in a subprocess raises SeatModelError after the attribute is
    monkeypatched on model_roster (so the check really runs at import, from the module on disk).
  * the decided failure mode: a violated invariant makes `import audit_spawn` and
    `import verification_arbiter_spawn` raise too (fail CLOSED, never fall open).
  * HISTORY consistency.
  * is_benched() normalisation, with its controls.
  * a benched env override is refused on consultant_support (and on a protected seat) and the
    row value is served; a non-benched alias is still accepted (control).
  * roster_rev in the provenance of Claude and codex-std pins (not codex TOP / agy), at the top
    of `emit`, in audit_spawn's verdict provenance and in convene's persisted provenance - and
    OPTIONAL on read: an avengers plan / run record without it (a pre-#291 fixture) still
    validates.

The expected values here are read from model_roster itself on purpose: this file tests the
MECHANISM, whatever the roster holds. The committed rev-2 values are pinned by the golden test
(test_model_roster_golden.py, WP-6), which is edited by hand on each swap.

ISOLATION. Every test runs under a temp HOME (autouse). Subprocesses get their own temp HOME
and cwd, so no import writes the live ~/.claude/state.
"""
import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
_AVENGERS_SCRIPTS = _META.parent / "avengers" / "scripts"
for _p in (_META, _AVENGERS_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import model_roster  # type: ignore  # noqa: E402
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import codex_roster_fixture as crf  # type: ignore  # noqa: E402
import seat_model as sm  # type: ignore  # noqa: E402

ROSTER_FILE = _META / "model_roster.py"
ENV = "ROSTER_TEST_ENV"


@pytest.fixture(autouse=True)
def fixture_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "state").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv(ENV, raising=False)
    return home


def _run(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    """Run `code` in a fresh interpreter with _meta on sys.path, a temp HOME and a temp cwd."""
    home = tmp_path / "sub-home"
    (home / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    (home / ".codex").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("PYTHONPATH", None)
    prelude = f"import sys\nsys.path.insert(0, {str(_META)!r})\n"
    return subprocess.run([sys.executable, "-c", prelude + textwrap.dedent(code)],
                          cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=120)


def _live_attrs() -> dict:
    out = {name: getattr(model_roster, name) for name in
           ("SCHEMA", "REVISION", "CLAUDE_MAIN", "CLAUDE_SUPPORT", "CLAUDE_BENCHED",
            "CLAUDE_MAIN_ELIGIBLE", "CODEX_STD", "HISTORY")}
    # #302 WP-2: the codex support tier. Read with a fallback so a roster that predates it fails the
    # NAMED invariant tests below, not every test in the file at collection.
    out["CODEX_SUPPORT"] = getattr(model_roster, "CODEX_SUPPORT", model_roster.CODEX_STD)
    return out


def _synced(attrs: dict) -> dict:
    """`attrs` with HISTORY[-1] rewritten to its live values, so ONLY the targeted invariant fails."""
    out = dict(attrs)
    last = dict(out["HISTORY"][-1])
    last.update({"rev": out["REVISION"], "claude_main": out["CLAUDE_MAIN"],
                 "claude_support": out["CLAUDE_SUPPORT"], "codex_std": out["CODEX_STD"],
                 "codex_support": out["CODEX_SUPPORT"],
                 "benched": tuple(sorted(out["CLAUDE_BENCHED"]))})
    out["HISTORY"] = tuple(out["HISTORY"][:-1]) + (last,)
    return out


def _names(message: str, needle) -> bool:
    needles = (needle,) if isinstance(needle, str) else tuple(needle)
    return all(n in message for n in needles)


def _other_alias(*avoid):
    """A Claude vendor alias that is none of `avoid` and not benched."""
    return sorted(a for a in sm.CLAUDE_ALIASES if a not in avoid and not sm.is_benched(a))[0]


# Each case: (id, mutation(attrs) -> attrs, sync_history, the substring(s) ONE violation must contain).
def _case_main_equals_support(a):
    a["CLAUDE_SUPPORT"] = a["CLAUDE_MAIN"]
    return a


def _case_main_not_alias(a):
    a["CLAUDE_MAIN"] = "gpt-5.6-sol"
    a["CLAUDE_MAIN_ELIGIBLE"] = frozenset(a["CLAUDE_MAIN_ELIGIBLE"]) | {"gpt-5.6-sol"}
    return a


def _case_support_not_alias(a):
    a["CLAUDE_SUPPORT"] = "gemini-3.8-flash-high"
    return a


def _case_main_not_eligible(a):
    a["CLAUDE_MAIN_ELIGIBLE"] = frozenset()
    return a


def _case_main_benched(a):
    a["CLAUDE_BENCHED"] = frozenset(a["CLAUDE_BENCHED"]) | {a["CLAUDE_MAIN"]}
    return a


def _case_support_benched(a):
    a["CLAUDE_BENCHED"] = frozenset(a["CLAUDE_BENCHED"]) | {a["CLAUDE_SUPPORT"]}
    return a


def _case_codex_std_unsafe(a):
    a["CODEX_STD"] = "gpt 5; rm -rf"
    return a


def _case_history_stale(a):
    a["CODEX_STD"] = a["CODEX_STD"] + "-next"      # live value moved, HISTORY not appended
    return a


def _case_revision_mismatch(a):
    a["REVISION"] = a["REVISION"] + 1
    return a


def _case_history_benched_stale(a):
    a["CLAUDE_BENCHED"] = frozenset(a["CLAUDE_BENCHED"]) | {"haiku"}
    return a


def _case_history_rev_gap(a):
    last = dict(a["HISTORY"][-1])
    last["rev"] = last["rev"] + 1
    a["HISTORY"] = tuple(a["HISTORY"][:-1]) + (last,)
    a["REVISION"] = last["rev"]
    return a


def _case_schema(a):
    a["SCHEMA"] = "model-roster.v0"
    return a


# #302 WP-2 (JC-1): the codex support tier's invariants. There is deliberately NO std != support case:
# a revert to a rev-1/2-shaped row (std == support) must stay a legal roster (a `check` WARN only).
def _case_codex_support_unsafe(a):
    a["CODEX_SUPPORT"] = "gpt 5.6; rm -rf"
    return a


# #302 final re-review NEW-1: a codex tier set to the TOP harness literal would be billed std, and a
# freeze on that literal would bill all four protected TOP seats std. Literal, not read from seat_model.
def _case_codex_std_is_top(a):
    a["CODEX_STD"] = "gpt-6-astra"
    return a


def _case_codex_support_is_top(a):
    a["CODEX_SUPPORT"] = "gpt-6-astra"
    return a


def _case_history_support_stale(a):
    a["CODEX_SUPPORT"] = a["CODEX_SUPPORT"] + "-next"   # live value moved, HISTORY not appended
    return a


def _case_history_support_absent_differs(a):
    """A last row WITHOUT codex_support reads as its codex_std - wrong once the tiers differ."""
    last = {k: v for k, v in a["HISTORY"][-1].items() if k != "codex_support"}
    a["HISTORY"] = tuple(a["HISTORY"][:-1]) + (last,)
    a["CODEX_SUPPORT"] = last["codex_std"] + "-support"
    return a


def _case_history_support_blank(a):
    last = dict(a["HISTORY"][-1])
    first = dict(a["HISTORY"][0], codex_support="")
    a["HISTORY"] = (first,) + tuple(a["HISTORY"][1:-1]) + (last,)
    return a


INVARIANT_CASES = [
    ("main_equals_support", _case_main_equals_support, True, "CLAUDE_MAIN == CLAUDE_SUPPORT"),
    ("main_not_alias", _case_main_not_alias, True, "CLAUDE_MAIN 'gpt-5.6-sol' is not a Claude vendor alias"),
    ("support_not_alias", _case_support_not_alias, True, "CLAUDE_SUPPORT 'gemini-3.8-flash-high' is not a Claude vendor alias"),
    ("main_not_eligible", _case_main_not_eligible, True, "is not in CLAUDE_MAIN_ELIGIBLE"),
    ("main_benched", _case_main_benched, True, ("CLAUDE_MAIN '", "is benched")),
    ("support_benched", _case_support_benched, True, ("CLAUDE_SUPPORT '", "is benched")),
    ("codex_std_unsafe", _case_codex_std_unsafe, True, "CODEX_STD must be one safe shell word"),
    ("history_stale", _case_history_stale, False, "HISTORY[-1]['codex_std']"),
    ("revision_mismatch", _case_revision_mismatch, False, "!= HISTORY[-1]['rev']"),
    ("history_benched_stale", _case_history_benched_stale, False, "HISTORY[-1]['benched']"),
    ("history_rev_gap", _case_history_rev_gap, False, "HISTORY revs must run"),
    ("schema", _case_schema, True, "SCHEMA must be 'model-roster.v1'"),
    ("codex_support_unsafe", _case_codex_support_unsafe, True, "CODEX_SUPPORT must be one safe shell word"),
    ("history_support_stale", _case_history_support_stale, False, "HISTORY[-1]['codex_support']"),
    ("history_support_absent_differs", _case_history_support_absent_differs, False,
     "HISTORY[-1]['codex_support']"),
    ("history_support_blank", _case_history_support_blank, True, "'codex_support' must be a non-empty string"),
    ("codex_std_is_top", _case_codex_std_is_top, True, "CODEX_STD must not be the codex TOP harness literal"),
    ("codex_support_is_top", _case_codex_support_is_top, True, "CODEX_SUPPORT must not be the codex TOP harness literal"),
]


# --------------------------------------------------------------------------- #
# The module is data only
# --------------------------------------------------------------------------- #
def test_the_roster_module_imports_and_holds_only_literal_assignments():
    tree = ast.parse(ROSTER_FILE.read_text(encoding="utf-8"))
    for index, node in enumerate(tree.body):
        if index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            continue                                   # the module docstring
        assert isinstance(node, ast.Assign), f"line {node.lineno}: {type(node).__name__} is not an assignment"
        assert all(isinstance(t, ast.Name) for t in node.targets)
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef, ast.Lambda)), f"line {node.lineno}: {type(node).__name__}"
        if isinstance(node, ast.Name):
            assert node.id != "open"
        if isinstance(node, ast.Call):
            # frozenset({...}) is the only call a literal set needs.
            assert isinstance(node.func, ast.Name) and node.func.id == "frozenset", ast.dump(node)
    result = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import model_roster",
                             str(_META)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_the_committed_roster_satisfies_every_invariant():
    assert sm.roster_violations() == []


# --------------------------------------------------------------------------- #
# Invariants: in-process (named) and at a fresh import (raised)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case_id,mutate,sync,needle", INVARIANT_CASES, ids=[c[0] for c in INVARIANT_CASES])
def test_each_invariant_is_named_by_roster_violations(case_id, mutate, sync, needle):
    attrs = mutate(dict(_live_attrs()))
    if sync:
        attrs = _synced(attrs)
    violations = sm.roster_violations(SimpleNamespace(**attrs))
    assert violations, f"{case_id}: no violation reported"
    assert any(_names(v, needle) for v in violations), violations
    # CONTROL: the same helper, with the same sync, on the unmutated roster is clean.
    base = _synced(dict(_live_attrs())) if sync else dict(_live_attrs())
    assert sm.roster_violations(SimpleNamespace(**base)) == []


@pytest.mark.parametrize("case_id,mutate,sync,needle", INVARIANT_CASES, ids=[c[0] for c in INVARIANT_CASES])
def test_each_invariant_raises_seat_model_error_at_a_fresh_import(tmp_path, case_id, mutate, sync, needle):
    attrs = mutate(dict(_live_attrs()))
    if sync:
        attrs = _synced(attrs)
    code = f"""
        import model_roster
        attrs = {attrs!r}
        for name, value in attrs.items():
            setattr(model_roster, name, value)
        try:
            import seat_model
        except Exception as exc:
            print(type(exc).__name__)
            print(str(exc))
            raise SystemExit(0)
        print("IMPORTED")
    """
    result = _run(code, tmp_path)
    assert result.returncode == 0, result.stderr
    first, _, rest = result.stdout.partition("\n")
    assert first == "SeatModelError", result.stdout
    assert "model_roster.py violates its invariants" in rest, rest
    assert any(_names(part, needle) for part in rest.split("; ")), rest


def test_302_a_rev2_shaped_codex_roster_is_legal(tmp_path):
    """JC-1: std == support with a last HISTORY row WITHOUT codex_support (the rev-1/2 row shape, a
    runbook revert target) violates nothing, in-process and at a fresh import."""
    attrs = dict(_live_attrs())
    attrs["CODEX_STD"] = attrs["CODEX_SUPPORT"] = "gpt-5.6-sol"
    last = {k: v for k, v in attrs["HISTORY"][-1].items() if k != "codex_support"}
    last["codex_std"] = "gpt-5.6-sol"
    attrs["HISTORY"] = tuple(attrs["HISTORY"][:-1]) + (last,)
    assert sm.roster_violations(SimpleNamespace(**attrs)) == []
    result = _run(f"""
        import model_roster
        for name, value in {attrs!r}.items():
            setattr(model_roster, name, value)
        import seat_model
        print(seat_model.CODEX_STD_MODEL, seat_model.CODEX_SUPPORT_MODEL)
    """, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["gpt-5.6-sol", "gpt-5.6-sol"]


def test_302_a_roster_file_without_codex_support_reads_it_as_codex_std(tmp_path):
    """A rev-1/2 roster FILE has no CODEX_SUPPORT attribute at all (a git revert of the file, a pre-#302
    home copy). It reads as CODEX_STD - the same rule as a HISTORY row without `codex_support` - so it
    stays legal and consultant_support serves the std slug, exactly as before rev 3."""
    attrs = dict(_live_attrs())
    del attrs["CODEX_SUPPORT"]
    attrs["CODEX_STD"] = "gpt-5.6-sol"
    last = {k: v for k, v in attrs["HISTORY"][-1].items() if k != "codex_support"}
    last["codex_std"] = "gpt-5.6-sol"
    attrs["HISTORY"] = tuple(attrs["HISTORY"][:-1]) + (last,)
    assert sm.roster_violations(SimpleNamespace(**attrs)) == []
    result = _run(f"""
        import model_roster
        for name, value in {attrs!r}.items():
            setattr(model_roster, name, value)
        if hasattr(model_roster, "CODEX_SUPPORT"):
            del model_roster.CODEX_SUPPORT
        import seat_model
        print(seat_model.CODEX_SUPPORT_MODEL, seat_model.ROLE_TABLE["consultant_support"]["codex"].value)
    """, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["gpt-5.6-sol", "gpt-5.6-sol"]
    # CONTROL: the same file with a PRESENT but unsafe CODEX_SUPPORT is a violation.
    assert any("CODEX_SUPPORT must be one safe shell word" in v
               for v in sm.roster_violations(SimpleNamespace(**dict(attrs, CODEX_SUPPORT="a b"))))


def test_a_fresh_import_with_the_committed_roster_does_not_raise(tmp_path):
    """CONTROL for the case above: the same subprocess shape imports cleanly."""
    result = _run("import seat_model\nprint(seat_model.ROSTER_REVISION)\n", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(model_roster.REVISION)


# --------------------------------------------------------------------------- #
# The decided failure mode: every importer fails CLOSED
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("module", ["audit_spawn", "verification_arbiter_spawn"])
def test_a_violated_invariant_makes_the_verified_gate_spawners_fail_closed(tmp_path, module):
    code = f"""
        import model_roster
        model_roster.CLAUDE_SUPPORT = model_roster.CLAUDE_MAIN
        try:
            import {module}
        except Exception as exc:
            print(type(exc).__name__)
            raise SystemExit(0)
        print("IMPORTED", {module}.CLAUDE_MODEL)
    """
    result = _run(code, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SeatModelError", result.stdout


@pytest.mark.parametrize("module", ["audit_spawn", "verification_arbiter_spawn"])
def test_with_a_clean_roster_the_spawners_import_and_pin_the_main_tier(tmp_path, module):
    """CONTROL: the same import succeeds, and the Claude pin is the roster's main tier."""
    result = _run(f"import {module}\nprint({module}.CLAUDE_MODEL)\n", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == model_roster.CLAUDE_MAIN


# --------------------------------------------------------------------------- #
# HISTORY
# --------------------------------------------------------------------------- #
def test_history_is_consistent():
    history = model_roster.HISTORY
    assert [h["rev"] for h in history] == list(range(1, len(history) + 1))
    assert history[-1]["rev"] == model_roster.REVISION
    last = history[-1]
    assert (last["claude_main"], last["claude_support"], last["codex_std"]) == (
        model_roster.CLAUDE_MAIN, model_roster.CLAUDE_SUPPORT, model_roster.CODEX_STD)
    # #302: a row without codex_support reads as its codex_std (the support tier before rev 3).
    assert last.get("codex_support", last["codex_std"]) == model_roster.CODEX_SUPPORT
    assert frozenset(last["benched"]) == model_roster.CLAUDE_BENCHED
    dates = [h["at"] for h in history]
    assert dates == sorted(dates), "HISTORY must be in date order"
    for h in history:
        # Every revision that was ever live satisfied the pair invariants in its own day.
        assert h["claude_main"] != h["claude_support"], h
        assert h["claude_main"] in model_roster.CLAUDE_MAIN_ELIGIBLE, h
        assert not sm.is_benched(h["claude_main"], h["benched"]), h
        assert not sm.is_benched(h["claude_support"], h["benched"]), h
        assert isinstance(h["benched"], tuple) and h["reason"].strip()


# --------------------------------------------------------------------------- #
# is_benched
# --------------------------------------------------------------------------- #
#: #291 fix round 1 (F, G): every separator a model id is spelled with, stacked context
#: suffixes, and a version glued onto the family token ("fable5") are all the fable family.
BENCHED_SPELLINGS = [
    "fable", "fable[1m]", "claude-fable-5-1", "FABLE", " Fable[1M] ",
    "fable[1m][1m]", "fable[1m] [1m]", "claude-fable-5-1[1m][1m]",           # F: stacked suffixes
    "Fable 5.1", "claude_fable", "claude.fable.5", "claude/fable", "claude@fable",
    "claude:fable-5", "claude-fable5-1", "fable5", "Claude Fable 5.1 [1m]",  # G: separators, glue
]
#: The controls: a different family, a longer word that merely starts or ends with the family,
#: letters glued on (not a version), and non-strings.
NOT_BENCHED_SPELLINGS = [
    "opus", "sonnet", "claude-opus-5-5", "opus[1m]", "fablex", "claude-fables-1", "notfable",
    "claude_fables", "fable5x", "fablea5", "5fable", "Opus 5.5", "claude.opus.5", "", None, 5,
]


@pytest.mark.parametrize("model_id", BENCHED_SPELLINGS)
def test_is_benched_true_for_the_fable_family(model_id):
    assert sm.is_benched(model_id, frozenset({"fable"}))


@pytest.mark.parametrize("model_id", NOT_BENCHED_SPELLINGS)
def test_is_benched_false_for_everything_else(model_id):
    assert not sm.is_benched(model_id, frozenset({"fable"}))


def test_is_benched_defaults_to_the_roster_read_at_call_time(monkeypatch):
    monkeypatch.setattr(model_roster, "CLAUDE_BENCHED", frozenset({"fable"}))
    assert sm.is_benched("claude-fable-5-1")
    monkeypatch.setattr(model_roster, "CLAUDE_BENCHED", frozenset())
    assert not sm.is_benched("claude-fable-5-1")      # CONTROL: nothing benched, nothing refused


def test_the_committed_main_and_support_are_not_benched():
    assert not sm.is_benched(model_roster.CLAUDE_MAIN)
    assert not sm.is_benched(model_roster.CLAUDE_SUPPORT)


# --------------------------------------------------------------------------- #
# The env branch refuses a benched value; the row value is served
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", ["fable", "claude-fable-5-1", "fable[1m]"])
def test_a_benched_env_override_on_consultant_support_is_refused_and_the_row_served(monkeypatch, value):
    monkeypatch.setattr(model_roster, "CLAUDE_BENCHED", frozenset({"fable"}))
    monkeypatch.setenv(ENV, value)
    pin = sm.resolve(sm.CONSULTANT_SUPPORT, sm.CLAUDE, env_var=ENV)
    assert pin.model == model_roster.CLAUDE_SUPPORT
    assert pin.argv_fragment == ("--model", model_roster.CLAUDE_SUPPORT, "--effort", "medium")   # #311 F1
    assert pin.provenance["source"] == "harness_literal"
    refused = pin.provenance["env_override_refused"]
    assert refused["var"] == ENV and refused["value"] == value and "benched" in refused["reason"]


def test_a_benched_env_override_on_a_protected_seat_is_refused(monkeypatch):
    monkeypatch.setattr(model_roster, "CLAUDE_BENCHED", frozenset({"fable"}))
    monkeypatch.setenv(ENV, "fable")
    pin = sm.resolve(sm.CODE_REVIEWER, sm.CLAUDE, env_var=ENV)
    assert pin.model == model_roster.CLAUDE_MAIN
    assert "benched" in pin.provenance["env_override_refused"]["reason"]


def test_a_non_benched_alias_on_consultant_support_is_still_accepted(monkeypatch):
    """CONTROL: the refusal is about the benched family, not about env overrides in general."""
    alias = _other_alias(model_roster.CLAUDE_SUPPORT)
    monkeypatch.setenv(ENV, alias)
    pin = sm.resolve(sm.CONSULTANT_SUPPORT, sm.CLAUDE, env_var=ENV)
    assert pin.model == alias and pin.provenance["source"] == "env"
    assert "env_override_refused" not in pin.provenance


def test_with_nothing_benched_the_same_env_value_is_accepted(monkeypatch):
    """CONTROL: the same fixture serves the env value once the family leaves the benched set."""
    monkeypatch.setattr(model_roster, "CLAUDE_BENCHED", frozenset())
    monkeypatch.setenv(ENV, "fable")
    pin = sm.resolve(sm.CONSULTANT_SUPPORT, sm.CLAUDE, env_var=ENV)
    assert pin.model == "fable" and pin.provenance["source"] == "env"


# --------------------------------------------------------------------------- #
# roster_rev provenance
# --------------------------------------------------------------------------- #
def _write_small_codex_roster(home: Path) -> None:
    """astra plus the roster's codex tiers (#302 WP-1: the shared synthetic roster), efforts to max."""
    models = crf.codex_entries(slugs=("gpt-6-astra",))
    for m in models:
        m["supported_reasoning_levels"] = [{"effort": e, "description": e}
                                           for e in ("low", "medium", "high", "xhigh", "max")]
    crf.write_codex_roster(home, models, fetched_at="2099-01-01T00:00:00Z")


def test_every_claude_pin_carries_roster_rev():
    for role in sm.ROLES:
        pin = sm.resolve(role, sm.CLAUDE)
        assert pin.provenance[sm.ROSTER_REV] == model_roster.REVISION, role
    assert sm.ROSTER_REV == "roster_rev"


def test_codex_std_pins_carry_roster_rev_and_codex_top_and_agy_pins_do_not(fixture_home):
    _write_small_codex_roster(fixture_home)
    std = sm.resolve(sm.CONSULTANT_SUPPORT, sm.CODEX)
    assert std.model == crf.codex_support() and std.provenance["source"] == "roster"   # the support tier
    assert std.provenance["roster_rev"] == model_roster.REVISION
    sized = sm.resolve(sm.CODE_REVIEWER, sm.CODEX, size="light")
    assert sized.model == model_roster.CODEX_STD and sized.provenance["roster_rev"] == model_roster.REVISION
    top = sm.resolve(sm.CODE_REVIEWER, sm.CODEX)
    assert top.model == "gpt-6-astra" and "roster_rev" not in top.provenance
    agy = sm.resolve(sm.CONSULTANT_MAIN, sm.AGY)
    assert "roster_rev" not in agy.provenance


def test_emit_carries_roster_rev_at_the_top_level_and_serves_no_benched_claude_model(fixture_home):
    _write_small_codex_roster(fixture_home)
    doc = sm.emit()
    assert doc["roster_rev"] == model_roster.REVISION
    for role, cells in doc["pins"].items():
        claude = cells["claude"]
        assert not sm.is_benched(claude["model"]), role
        expected = model_roster.CLAUDE_SUPPORT if role == sm.CONSULTANT_SUPPORT else model_roster.CLAUDE_MAIN
        assert claude["model"] == expected, role


def test_audit_spawn_verdict_provenance_carries_roster_rev_only_when_the_pin_has_it(tmp_path):
    code = """
        import json, audit_spawn, seat_model
        def pin(prov):
            return seat_model.SeatPin(model="m", effort=None, timeout=1, argv_fragment=("--model", "m"),
                                      provenance=prov)
        base = {"source": "harness_literal", "requested_selector": "m", "roster_fetched_at": None}
        with_rev = audit_spawn._seat_provenance(pin(dict(base, roster_rev=7)))
        without = audit_spawn._seat_provenance(pin(dict(base)))
        live = audit_spawn._seat_provenance(audit_spawn.CLAUDE_PIN)
        print(json.dumps([with_rev, without, live]))
    """
    result = _run(code, tmp_path)
    assert result.returncode == 0, result.stderr
    with_rev, without, live = json.loads(result.stdout.strip().splitlines()[-1])
    assert with_rev["roster_rev"] == 7
    assert "roster_rev" not in without                 # a pre-#291 pin: optional, absent
    assert live["roster_rev"] == model_roster.REVISION


# --------------------------------------------------------------------------- #
# convene: persisted and OPTIONAL on read
# --------------------------------------------------------------------------- #
def _strip_roster_rev(obj):
    if isinstance(obj, dict):
        return {k: _strip_roster_rev(v) for k, v in obj.items() if k != "roster_rev"}
    if isinstance(obj, list):
        return [_strip_roster_rev(v) for v in obj]
    return obj


def _provenances(plan):
    out = [s["provenance"] for s in plan["seats"] if "provenance" in s]
    if "provenance" in plan["arbiter"]:
        out.append(plan["arbiter"]["provenance"])
    return out


def test_convene_persists_roster_rev_and_a_pre_change_plan_and_run_record_still_validate(fixture_home):
    import convene  # type: ignore
    _write_small_codex_roster(fixture_home)
    plan = convene.build_session_plan({"profile": "coding-ratification"})
    provs = _provenances(plan)
    assert provs, "the plan carries no provenance at all"
    claude_provs = [s["provenance"] for s in plan["seats"] if s["provider"] == "claude" and "provenance" in s]
    assert claude_provs and all(p["roster_rev"] == model_roster.REVISION for p in claude_provs)
    schema, rr_schema = convene.load_schema(), convene.load_run_record_schema()
    assert convene.schema_validate(plan, schema) == []
    record = convene.build_run_record(plan)
    assert convene.schema_validate(record, rr_schema) == []

    # A plan / run record frozen BEFORE #291 has no roster_rev anywhere: still valid.
    old_plan = _strip_roster_rev(plan)
    assert all("roster_rev" not in p for p in _provenances(old_plan))
    assert convene.schema_validate(old_plan, schema) == []
    assert convene.schema_validate(_strip_roster_rev(record), rr_schema) == []
    assert convene.schema_validate(convene.build_run_record(old_plan), rr_schema) == []

    # CONTROL: the property is validated, not ignored - a string roster_rev is rejected, and the
    # object stays closed to any other new key.
    bad = json.loads(json.dumps(plan))
    bad["arbiter"]["provenance"]["roster_rev"] = "2"
    assert convene.schema_validate(bad, schema)
    bad = json.loads(json.dumps(plan))
    bad["arbiter"]["provenance"]["roster_revision"] = 2
    assert convene.schema_validate(bad, schema)


def test_persisted_provenance_copies_roster_rev_only_when_the_pin_has_it():
    import convene  # type: ignore
    base = {"requested_selector": "x", "resolved_model": "x", "source": "harness_literal",
            "roster_fetched_at": None, "quota_state": None}
    old_pin = SimpleNamespace(provenance=dict(base))
    new_pin = SimpleNamespace(provenance=dict(base, roster_rev=3))
    assert "roster_rev" not in convene.persisted_provenance(old_pin)
    assert convene.persisted_provenance(new_pin)["roster_rev"] == 3


def test_codex_model_default_is_the_roster_codex_std():
    import codex_model  # type: ignore
    assert codex_model.DEFAULT_MODEL == model_roster.CODEX_STD == sm.CODEX_STD_MODEL


# --------------------------------------------------------------------------- #
# #302 WP-2: codex tier REVERSIBILITY over two explicit literal pairs
#
# A fresh seat_model is loaded over a model_roster whose codex tiers are the pair's literals (conftest
# seat_model_under_roster; the shipped seat_model.py file, unmodified). The rev-3 pair is the committed
# split; the rev-2-shaped pair is the runbook's revert target (std == support, HISTORY row without
# codex_support). Every expected value is the pair's own literal, never re-derived from the resolver.
# --------------------------------------------------------------------------- #
_CODEX_PAIRS = [
    pytest.param("gpt-6-sol", "gpt-5.6-terra", True, id="rev3-std-gpt-6-sol-support-gpt-5.6-terra"),
    pytest.param("gpt-5.6-sol", "gpt-5.6-sol", False, id="rev2-shape-std-and-support-gpt-5.6-sol"),
]


@pytest.mark.parametrize("std,support,in_history", _CODEX_PAIRS)
def test_302_codex_tier_reversibility(fixture_home, load_seat_model_under_roster, std, support, in_history):
    fresh, rev = load_seat_model_under_roster(model_roster.CLAUDE_MAIN, model_roster.CLAUDE_SUPPORT,
                                              model_roster.CLAUDE_BENCHED, codex_std=std, codex_support=support,
                                              support_in_history=in_history)
    assert fresh.roster_violations() == []
    assert (fresh.CODEX_STD_MODEL, fresh.CODEX_SUPPORT_MODEL) == (std, support)
    _write_small_codex_roster(fixture_home)          # astra + the pair's two tier models
    sup = fresh.resolve("consultant_support", "codex")
    assert (sup.model, sup.effort, sup.provenance["roster_rev"]) == (support, "medium", rev)
    sized = fresh.resolve("code_reviewer", "codex", size="light")
    assert (sized.model, sized.provenance["roster_rev"]) == (std, rev)
    top = fresh.resolve("code_reviewer", "codex")
    assert top.model == "gpt-6-astra" and "top_resolved_to_std" not in top.provenance
    # the spend class: both tiers std, astra and any other listed slug TOP
    assert (fresh.model_class_of(std), fresh.model_class_of(support)) == ("std", "std")
    assert (fresh.model_class_of("gpt-6-astra"), fresh.model_class_of("gpt-5.6-luna")) == ("top", "top")
    assert fresh.pin_model_class(sup) == fresh.pin_model_class(sized) == "std"
    assert fresh.pin_model_class(top) == "top"
    doc = fresh.emit()
    assert doc["roster_rev"] == rev
    assert doc["pins"]["consultant_support"]["codex"]["model"] == support


# --------------------------------------------------------------------------- #
# D21 fix round 1 (m1): the runbook's revert section (docs/model-roster-swap.md s7)
# --------------------------------------------------------------------------- #
_RUNBOOK = _HERE.parents[2] / "docs" / "model-roster-swap.md"


def _runbook_section_7() -> str:
    if not _RUNBOOK.is_file():
        pytest.skip("the runbook ships with the repo, not the installed tree")
    text = _RUNBOOK.read_text(encoding="utf-8")
    body = text[text.index("## 7. Reverting"):text.index("## 8.")]
    return " ".join(body.split())


def test_the_revert_example_numbers_the_new_row_revision_plus_one_never_a_fixed_rev():
    """A revert row is REVISION + 1 whatever the current revision is; 'a rev-3 row' was only true
    on the rev-2 roster the example was written against."""
    section = _runbook_section_7()
    assert "rev-3 row" not in section
    assert "a row numbered REVISION+1" in section


def test_the_revert_section_says_to_set_codex_support_explicitly():
    """Reverting the codex tiers to a rev-1/2 row (no codex_support) must still set CODEX_SUPPORT and
    write codex_support on the new HISTORY row, or the support tier silently follows std."""
    section = _runbook_section_7()
    assert "set `CODEX_SUPPORT` explicitly" in section
    assert "`codex_std`" in section and "no `codex_support`" in section
    assert "write `codex_support` on the new `HISTORY` row" in section
