#!/usr/bin/env python3
"""Tests for `seat_model.py check` and its module seat_model_check.py (#291 design s3.3, plan WP-2).

`check` validates a TREE (the repo, or an installed ~/.claude) without a model call: the roster
invariants, `emit --json` at every size, every shipped avengers profile's --dry-run, the
smart-config tiers, a benched-literal lint, and with --home the installed copy plus drift.

HOW THESE TESTS WORK. Every test builds its own FIXTURE TREE (a copy of the repo's skills/_meta,
skills/avengers and skills/smart-config, tests excluded) and a FIXTURE HOME (a fixture codex
roster, agy roster and model-policy.yaml). `check` is then run as a subprocess of the REPO's
seat_model.py with `--root <fixture tree>` and HOME = the fixture home. So:
  * a broken roster is planted in the fixture tree only; the checker itself stays importable;
  * the live home is never the HOME of any process here (the autouse fixture and the subprocess
    env both point at tmp_path), and the live_home_guard plugin watches the real one;
  * the fixture home is the home `check` READS from, and one test asserts it is left
    byte-for-byte and mtime-for-mtime unchanged, with no file added.

The fixture tree's roster starts as a copy of the committed one, so these tests follow whatever
the roster holds (the mechanism is what is under test). Planted rosters are written explicitly.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
_SKILLS = _META.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import model_roster  # type: ignore  # noqa: E402
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import codex_roster_fixture as crf  # type: ignore  # noqa: E402
import seat_model as sm  # type: ignore  # noqa: E402
import seat_model_check as smc  # type: ignore  # noqa: E402

SEAT_MODEL = _META / "seat_model.py"
_COPIED_SKILLS = ("_meta", "avengers", "smart-config")
_IGNORE = shutil.ignore_patterns("tests", "__pycache__", "*.pyc")
#: The FIXTURE benched family (#291 fix round 1 E). Never read from the live roster: a module
#: constant like `sorted(model_roster.CLAUDE_BENCHED)[0]` raised IndexError at COLLECTION after
#: a runbook s7 revert (an empty benched set). Tests that need the family benched plant a
#: fixture roster that benches it (bench_fixture_family); the reversibility tests plant one
#: that benches nothing.
FAMILY = "fable"
#: Whole-check wall clock bound asserted by one test ("a few minutes at most").
CHECK_BUDGET_S = 180


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def fixture_home(tmp_path, monkeypatch):
    """The HOME of this test process AND of every `check` it runs (never the live home)."""
    home = tmp_path / "home"
    (home / ".claude" / "state").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    _seed_home(home)
    return home


def _now_iso(nanos: bool = False) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return stamp + (".123456789Z" if nanos else "Z")


def _seed_home(home: Path, *, policy: str | None = None) -> None:
    """A fixture codex roster, agy roster and smart-config policy (fresh `fetched_at`)."""
    # #302 WP-1: astra, gpt-5.5 and the roster's codex tiers (the shared synthetic roster).
    crf.write_codex_roster(home, crf.codex_entries(slugs=("gpt-6-astra", "gpt-5.5")), fetched_at=_now_iso(nanos=True))
    agy = {"schema": "agy-models.v1", "fetched_at": _now_iso(), "agy_version": "1.2.2",
           "models": ["gemini-4-argon-high", "gemini-4-argon-medium", "gemini-4-argon-low",
                      "gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low",
                      # #367: a second family, so a planted family-swap roster resolves too
                      "gemini-5-neon-high", "gemini-5-neon-medium", "gemini-5-neon-low"]}
    (home / ".claude" / "state" / "agy-models.json").write_text(json.dumps(agy), encoding="utf-8")
    if policy is None:
        policy = (f"version: 1\ndefaults:\n  tier: medium\ntiers:\n"
                  f"  complex: {{ claude-code: {model_roster.CLAUDE_MAIN} }}\n"
                  f"  medium: {{ claude-code: {model_roster.CLAUDE_MAIN} }}\n"
                  f"  light: {{ claude-code: {model_roster.CLAUDE_SUPPORT} }}\n")
    (home / ".claude" / "model-policy.yaml").write_text(policy, encoding="utf-8")


@pytest.fixture
def tree(tmp_path) -> Path:
    """A fixture tree holding copies of the three skills `check` exercises (tests excluded)."""
    root = tmp_path / "tree"
    for name in _COPIED_SKILLS:
        shutil.copytree(_SKILLS / name, root / "skills" / name, ignore=_IGNORE)
    return root


def run_check(root: Path, home: Path, *extra: str, path: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)
    if path is not None:
        env["PATH"] = path
    cwd = home.parent / "cwd"
    cwd.mkdir(exist_ok=True)
    return subprocess.run([sys.executable, "-B", str(SEAT_MODEL), "check", "--root", str(root), *extra],
                          cwd=str(cwd), env=env, capture_output=True, text=True, timeout=CHECK_BUDGET_S * 2,
                          stdin=subprocess.DEVNULL)


def fails(done: subprocess.CompletedProcess) -> list:
    return [line[len("FAIL "):] for line in done.stdout.splitlines() if line.startswith("FAIL ")]


def passes(done: subprocess.CompletedProcess) -> list:
    return [line[len("PASS "):] for line in done.stdout.splitlines() if line.startswith("PASS ")]


def warns(done: subprocess.CompletedProcess) -> list:
    return [line[len("WARN "):] for line in done.stdout.splitlines() if line.startswith("WARN ")]


#: roster_text(codex_support=OMIT) writes a rev-2-shaped roster: no CODEX_SUPPORT line and no
#: codex_support key in the appended HISTORY row (both read as the row's codex std, #302 JC-1).
OMIT = object()


def roster_text(*, revision, main, support, benched, eligible, codex_std=None, codex_support=None,
                history=None, agy_family=None, agy_harness_version=None, agy_level_by_size=None) -> str:
    """A data-only model_roster.py. `history` defaults to the committed rows with a last row
    equal to the given live values (so only the targeted invariant fails). `codex_support`
    defaults to the committed support tier (#302); OMIT leaves the support tier out."""
    codex_std = model_roster.CODEX_STD if codex_std is None else codex_std
    codex_support = crf.codex_support() if codex_support is None else codex_support
    # #367 (roster rev 6): the agy family is roster data; default to the committed values.
    agy_family = model_roster.AGY_FAMILY if agy_family is None else agy_family
    agy_harness_version = model_roster.AGY_HARNESS_VERSION if agy_harness_version is None else agy_harness_version
    # #367 WP-C (roster rev 7): the agy size -> level map too.
    agy_level_by_size = dict(model_roster.AGY_LEVEL_BY_SIZE) if agy_level_by_size is None else agy_level_by_size
    if history is None:
        # Same revision: re-sync the last row. A new revision: append a row (a real swap).
        keep = model_roster.HISTORY[:-1] if revision == model_roster.REVISION else model_roster.HISTORY
        rows = [dict(h) for h in keep]
        row = {"rev": revision, "at": "2026-09-24", "claude_main": main, "claude_support": support,
               "codex_std": codex_std, "benched": tuple(sorted(benched)), "reason": "fixture"}
        if codex_support is not OMIT:
            row["codex_support"] = codex_support
        row["codex_top_roles"] = model_roster.CODEX_TOP_ROLES      # the astra reserve (roster rev 4)
        row["agy_family"] = agy_family                             # #367 (roster rev 6)
        row["agy_level_by_size"] = agy_level_by_size               # #367 WP-C (roster rev 7)
        rows.append(row)
        history = tuple(rows)
    return (
        '"""fixture roster (data only)."""\n'
        'SCHEMA = "model-roster.v1"\n'
        f"REVISION = {revision!r}\n"
        f"CLAUDE_MAIN = {main!r}\n"
        f"CLAUDE_SUPPORT = {support!r}\n"
        f"CLAUDE_BENCHED = frozenset({sorted(benched)!r})\n"
        f"CLAUDE_MAIN_ELIGIBLE = frozenset({sorted(eligible)!r})\n"
        f"CODEX_STD = {codex_std!r}\n"
        + ("" if codex_support is OMIT else f"CODEX_SUPPORT = {codex_support!r}\n")
        + f"CODEX_TOP_ROLES = {model_roster.CODEX_TOP_ROLES!r}\n"
        + f"AGY_FAMILY = {agy_family!r}\n"
        + f"AGY_HARNESS_VERSION = {agy_harness_version!r}\n"
        + f"AGY_LEVEL_BY_SIZE = {agy_level_by_size!r}\n"
        + f"HISTORY = {tuple(history)!r}\n"
    )


def committed(**over) -> dict:
    values = {"revision": model_roster.REVISION, "main": model_roster.CLAUDE_MAIN,
              "support": model_roster.CLAUDE_SUPPORT, "benched": set(model_roster.CLAUDE_BENCHED),
              "eligible": set(model_roster.CLAUDE_MAIN_ELIGIBLE)}
    values.update(over)
    return values


def plant_roster(meta: Path, **values) -> None:
    (meta / "model_roster.py").write_text(roster_text(**values), encoding="utf-8")


def bench_fixture_family(tree: Path) -> None:
    """Plant a valid fixture roster (the next revision) that benches FAMILY, whatever the
    committed roster holds today, so the benched-path tests survive a swap or a revert."""
    plant_roster(tree / "skills" / "_meta", revision=model_roster.REVISION + 1, main="opus",
                 support="sonnet", benched={FAMILY}, eligible={FAMILY, "opus"})


def _other_alias(*avoid):
    return sorted(a for a in sm.CLAUDE_ALIASES if a not in avoid and not sm.is_benched(a))[0]


def _snapshot(home: Path) -> dict:
    out = {}
    for path in sorted(home.rglob("*")):
        st = path.lstat()
        out[path.relative_to(home).as_posix()] = (
            stat.S_IFMT(st.st_mode), st.st_size, st.st_mtime_ns,
            path.read_bytes() if path.is_file() else None)
    return out


# --------------------------------------------------------------------------- #
# The clean fixture
# --------------------------------------------------------------------------- #
def test_a_clean_fixture_passes_every_item_and_exits_0(tree, fixture_home):
    started = time.monotonic()
    done = run_check(tree, fixture_home)
    elapsed = time.monotonic() - started
    assert done.returncode == 0, done.stdout + done.stderr
    assert fails(done) == []
    ok = passes(done)
    assert any(p.startswith("roster[tree]:") for p in ok)
    for label in ("emit[tree]", "emit[tree --size light]", "emit[tree --size medium]", "emit[tree --size complex]"):
        assert any(p.startswith(label + ":") for p in ok), label
    profiles = sorted(p.stem for p in (tree / "skills" / "avengers" / "profiles").glob("*.yaml"))
    assert profiles, "the fixture tree holds the shipped profiles"
    for profile in profiles:
        assert any(p.startswith(f"avengers[{profile}]:") for p in ok), profile
    for tier in smc.CHECK_POLICY_TIERS:
        assert any(p.startswith(f"smart-config[{tier}]:") for p in ok), tier
    assert any(p.startswith("lint:") for p in ok)
    # #302: the codex tiers are judged against the roster and the current TOP, and the rev-3
    # fixture (std and support distinct) prints no warning.
    assert any(p.startswith("codex[tree]:") for p in ok), ok
    assert warns(done) == []
    assert done.stdout.rstrip().splitlines()[-1].startswith("seat_model.py check: 0 failure(s)")
    assert elapsed < CHECK_BUDGET_S


def test_check_leaves_the_home_it_reads_byte_and_mtime_identical(tree, fixture_home):
    """The home `check` copies its inputs FROM is only read: nothing modified, nothing added."""
    before = _snapshot(fixture_home)
    done = run_check(tree, fixture_home, "--home")   # --home reads the most from the home
    assert done.returncode in (0, 1), done.stderr
    assert _snapshot(fixture_home) == before


# --------------------------------------------------------------------------- #
# Item 1 - roster invariants, from the files on disk
# --------------------------------------------------------------------------- #
def _main_equals_support():
    c = committed()
    return dict(c, support=c["main"])


def _benched_main():
    c = committed()
    return dict(c, benched=c["benched"] | {c["main"]})


def _main_not_eligible():
    c = committed()
    return dict(c, eligible=c["eligible"] - {c["main"]} | {_other_alias(c["main"], c["support"])})


@pytest.mark.parametrize("case_id, values, needle", [
    ("main-equals-support", _main_equals_support, "CLAUDE_MAIN == CLAUDE_SUPPORT"),
    ("benched-main", _benched_main, "is benched"),
    ("main-not-eligible", _main_not_eligible, "is not in CLAUDE_MAIN_ELIGIBLE"),
])
def test_a_violated_invariant_fails_check_and_is_named(tree, fixture_home, case_id, values, needle):
    plant_roster(tree / "skills" / "_meta", **values())
    done = run_check(tree, fixture_home)
    assert done.returncode == 1, done.stdout + done.stderr
    roster_fails = [f for f in fails(done) if f.startswith("roster[tree]:")]
    assert any(needle in f for f in roster_fails), (case_id, fails(done))


def test_a_stale_history_row_fails_check(tree, fixture_home):
    """REVISION bumped but no HISTORY row appended (the swap forgot the history)."""
    c = committed()
    plant_roster(tree / "skills" / "_meta", **dict(c, revision=c["revision"] + 1,
                                                   history=tuple(model_roster.HISTORY)))
    done = run_check(tree, fixture_home)
    assert done.returncode == 1
    assert any("!= HISTORY[-1]['rev']" in f for f in fails(done) if f.startswith("roster[tree]:")), fails(done)


def test_a_history_row_that_disagrees_with_the_live_values_fails_check(tree, fixture_home):
    c = committed()
    history = list(model_roster.HISTORY[:-1]) + [dict(model_roster.HISTORY[-1], claude_support="haiku")]
    plant_roster(tree / "skills" / "_meta", **dict(c, history=tuple(history)))
    done = run_check(tree, fixture_home)
    assert done.returncode == 1
    assert any("HISTORY[-1]['claude_support']" in f for f in fails(done)), fails(done)


def test_a_missing_roster_module_fails_check_without_crashing_it(tree, fixture_home):
    (tree / "skills" / "_meta" / "model_roster.py").unlink()
    done = run_check(tree, fixture_home)
    assert done.returncode == 1
    assert any(f.startswith("roster[tree]: model_roster.py does not import") for f in fails(done)), fails(done)
    assert any(f.startswith("lint: not run") for f in fails(done)), fails(done)


# --------------------------------------------------------------------------- #
# Items 3 and 4 - avengers dry runs and smart-config tiers
# --------------------------------------------------------------------------- #
def test_a_profile_whose_dry_run_fails_closed_is_named(tree, fixture_home):
    (tree / "skills" / "avengers" / "profiles" / "zz-broken.yaml").write_text(
        "this: [is not a profile\n", encoding="utf-8")
    done = run_check(tree, fixture_home)
    assert done.returncode == 1
    assert any(f.startswith("avengers[zz-broken]: --dry-run exit") for f in fails(done)), fails(done)
    # the shipped profiles are still each checked and pass
    assert any(p.startswith("avengers[") for p in passes(done))


@pytest.mark.parametrize("served", [f"claude-{FAMILY}-5-1", FAMILY, f"{FAMILY}[1m]", f"{FAMILY}[1m][1m]",
                                    f"Claude {FAMILY.capitalize()} 5.1"])
def test_a_smart_config_tier_resolving_to_a_benched_model_is_named(tree, fixture_home, served):
    """A stand-in resolver (the real one is WP-3's) proves the check reads the resolved model."""
    bench_fixture_family(tree)
    script = tree / "skills" / "smart-config" / "scripts" / "model_policy.py"
    script.write_text(
        "import json, sys\n"
        "tier = sys.argv[sys.argv.index('--tier') + 1]\n"
        f"model = {served!r} if tier == 'complex' else 'opus'\n"
        "print(json.dumps({'ok': True, 'tier': tier, 'model': model, 'source': 'global'}))\n",
        encoding="utf-8")
    done = run_check(tree, fixture_home)
    assert done.returncode == 1
    tier_fails = [f for f in fails(done) if f.startswith("smart-config[")]
    assert len(tier_fails) == 1 and tier_fails[0].startswith("smart-config[complex]: resolves to benched"), tier_fails


# --------------------------------------------------------------------------- #
# Item 5 - the benched-literal lint
# --------------------------------------------------------------------------- #
def _plant_literals(root: Path, family: str) -> dict:
    """Plant one literal per shape; return {relative path: expected line number}."""
    skill = root / "skills" / "zz-demo"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"# demo\n\n```\nAgent(model=\"{family}\", prompt=\"x\")\n```\n", encoding="utf-8")
    (skill / "scripts" / "run.sh").write_text(f"#!/bin/sh\nclaude -p --model {family} \"hi\"\n", encoding="utf-8")
    (root / "workflows").mkdir(exist_ok=True)
    (root / "workflows" / "zz-demo.js").write_text(f"const a = 1;\nargs.models.escalation = '{family}';\n",
                                                  encoding="utf-8")
    (skill / "scripts" / "table.py").write_text(f"ROW = dict(value=\"claude-{family}-5-1\")\n", encoding="utf-8")
    return {"skills/zz-demo/SKILL.md": 4, "skills/zz-demo/scripts/run.sh": 2,
            "workflows/zz-demo.js": 2, "skills/zz-demo/scripts/table.py": 1}


def _plant_controls(root: Path, family: str) -> None:
    """Lines the lint must NOT flag."""
    skill = root / "skills" / "zz-demo"
    (skill / "tests").mkdir(parents=True, exist_ok=True)
    (skill / "tests" / "test_demo.py").write_text(f"MODEL = dict(model=\"{family}\")\n", encoding="utf-8")
    (skill / "scripts" / "served.py").write_text(
        f"served_id = \"claude-{family}-5-1\"   # served-id matching\n"
        f"PIN = dict(model=\"{family}\")  # {smc.LINT_ALLOW_MARKER} (legacy alias compat)\n"
        f"FLAG = \"--{family}-touches-tests\"\n"
        f"# The {family.capitalize()} tier moved: models now follow the roster.\n",
        encoding="utf-8")


def test_a_planted_benched_literal_fails_check_naming_file_and_line(tree, fixture_home):
    bench_fixture_family(tree)
    expected = _plant_literals(tree, FAMILY)
    _plant_controls(tree, FAMILY)
    done = run_check(tree, fixture_home)
    assert done.returncode == 1
    lint = [f for f in fails(done) if f.startswith("lint: ")]
    flagged = {":".join(f[len("lint: "):].split(":")[:2]) for f in lint}
    assert flagged == {f"{path}:{line}" for path, line in expected.items()}, lint


def test_the_lint_flags_nothing_when_the_family_is_not_benched(tree, fixture_home):
    """Reversibility: under a roster that benches nothing, the same literal is legal."""
    family = FAMILY
    plant_roster(tree / "skills" / "_meta", revision=model_roster.REVISION + 1, main=family,
                 support=_other_alias(family), benched=set(), eligible={family})
    _plant_literals(tree, family)
    done = run_check(tree, fixture_home)
    assert done.returncode == 0, fails(done)
    assert any(p.startswith("lint: no spawn literal") for p in passes(done))


#: Spawn-literal spellings the lint MUST flag for the fixture family (#291 fix round 1 D adds
#: the argv-list, JSON/dict-key, *_MODEL-constant and push() shapes that used to lint clean).
LINT_MUST_HIT = [
    'model="fable"', "model: fable", "model = 'FABLE'", "--model fable[1m]", "--model=claude-fable-5-1",
    'value="fable"', "models: {bob: opus, escalation: fable}",
    'cmd = ["claude", "-p", "--model", "fable", prompt]',            # D: argv list
    "args.push('--model','fable')",                                  # D: JS push
    '{"model": "fable"}', '"model": "fable",', "{'model': 'fable'}",  # D: dict / JSON key
    "DEFAULT_MODEL = 'fable'", 'CLAUDE_MODEL = "claude-fable-5-1"',  # D: *_MODEL constants
    "const ESCALATION_MODEL = `fable`;", "model: 'claude_fable'",    # D + G spellings
    'model="fable5"', "--model 'Claude Fable 5.1'",
    # #291 fix round 2 N3: a vendor prefix before the family, and the *_id / *_name keys
    'model="anthropic/claude-fable-5"', "model='us.anthropic.claude-fable-5-1'", 'model = "vendor/fable"',
    "--model anthropic/claude-fable-5", 'model_id="fable"', "model_name: 'claude-fable-5-1'",
    'modelId: "fable"', 'modelName = "fable"', '{"model_id": "us.anthropic.claude-fable-5-1"}',
    # #291 final re-review F2: several path segments, and a path segment before a dotted one
    'model: "openrouter/anthropic/claude-fable"', '"model": "bedrock/us.anthropic.claude-fable-5-1-v1:0"',
]
#: Lines the lint must NOT flag: allowed-marker lines, served-id matching tables, the benched
#: sets themselves, other families, and words that merely contain the family.
LINT_MUST_NOT_HIT = [
    'served = "claude-fable-5-1"', "--fable-touches-tests", "model=opus", "models are now Fable-free",
    "RUNG_FABLE = 1", 'model="fablex"', "model = 'fables'", 'model="fable5x"',
    f'PIN = dict(model="fable")  # {smc.LINT_ALLOW_MARKER} (legacy alias compat)',
    'SERVED_IDS = {"claude-fable-5-1": "fable", "claude-opus-5-5": "opus"}',
    'const RUNG_MODEL_KEY = { opus: "bob", takeover: "escalation", fable: "escalation" };',
    'const DEFAULT_BENCHED = ["fable"];', '_FLOOR_BENCHED = frozenset({"fable"})',
    '{"model": "opus", "benched": ["fable"]}', "model_family = 'opus'  # was fable",
    # N3 controls: a prefixed OTHER family, a dotted attribute that is not a vendor id, and
    # names that merely start with a key
    'model="anthropic/claude-opus-5-5"', "model = 'us.anthropic.claude-opus-5-5'",
    'model_id = "opus"', "model = self.fable_rung", "if model_ids.is_benched(value, benched):",
    'model="vendor/fablex"',
]


def _lint_one(tmp_path, line, name="f.py", tree="skills/x"):
    root = tmp_path / "r"
    (root / tree).mkdir(parents=True, exist_ok=True)
    (root / tree / name).write_text(line + "\n", encoding="utf-8")
    return smc.lint_benched_literals(root, frozenset({"fable"}))


@pytest.mark.parametrize("line", LINT_MUST_HIT)
@pytest.mark.parametrize("name", ["f.py", "f.js", "f.json", "f.md"])
def test_the_lint_flags_every_spawn_literal_shape(tmp_path, line, name):
    assert len(_lint_one(tmp_path, line, name)) == 1, line


@pytest.mark.parametrize("line", LINT_MUST_NOT_HIT)
def test_the_lint_leaves_the_controls_alone(tmp_path, line):
    assert _lint_one(tmp_path, line) == [], line


@pytest.mark.parametrize("tree", ["templates", "skills/x/templates", "agents", "commands", "workflows"])
def test_the_lint_scans_every_shipped_tree(tmp_path, tree):
    # install.py ships templates/ (settings.global.json, agy.md) as well as the four
    # manifest categories; a benched default planted in any of them is flagged.
    hits = _lint_one(tmp_path, '{"model": "fable"}', "settings.global.json", tree)
    assert len(hits) == 1 and hits[0].startswith(f"{tree}/settings.global.json:1:"), hits


def test_the_lint_flags_nothing_with_an_empty_bench(tmp_path):
    root = tmp_path / "r"
    (root / "skills" / "x").mkdir(parents=True)
    (root / "skills" / "x" / "f.py").write_text("\n".join(LINT_MUST_HIT) + "\n", encoding="utf-8")
    assert smc.lint_benched_literals(root, frozenset()) == []
    assert len(smc.lint_benched_literals(root, frozenset({"fable"}))) == len(LINT_MUST_HIT)


def test_the_roster_file_itself_is_allow_listed(tree, fixture_home):
    """model_roster.py names the benched family by design (the benched set and the history)."""
    bench_fixture_family(tree)
    meta = tree / "skills" / "_meta"
    (meta / "model_roster.py").write_text(
        (meta / "model_roster.py").read_text(encoding="utf-8")
        + f"# example: model=\"{FAMILY}\" is what a swap forbids\n", encoding="utf-8")
    done = run_check(tree, fixture_home)
    assert done.returncode == 0, fails(done)


# --------------------------------------------------------------------------- #
# Item 2b - the codex tiers (#302 design s3.4; plan WP-3)
# --------------------------------------------------------------------------- #
def _seed_codex(home: Path, **kw) -> list:
    """Re-write the fixture home's codex roster (the shared synthetic one) with overrides.
    `mutate` = {slug: {field: value}} edits entries after they are built."""
    mutate = kw.pop("mutate", {})
    entries = crf.codex_entries(slugs=("gpt-6-astra", "gpt-5.5"), **kw)
    for item in entries:
        item.update(mutate.get(item["slug"], {}))
    crf.write_codex_roster(home, entries, fetched_at=_now_iso(nanos=True))
    return entries


def _codex_fails(done) -> list:
    return [f for f in fails(done) if f.startswith("codex[tree]:")]


@pytest.mark.parametrize("case_id, tier, seed, needle", [
    ("support-not-listed", "support", lambda: dict(mutate={crf.codex_support(): {"visibility": "hide"}}),
     "is not listed"),
    ("support-not-in-api", "support", lambda: dict(mutate={crf.codex_support(): {"supported_in_api": False}}),
     "is not supported_in_api"),
    ("support-lacks-medium", "support",
     lambda: dict(efforts={crf.codex_support(): ("low", "high", "xhigh", "max")}), "does not offer effort 'medium'"),
    ("support-absent", "support", lambda: dict(mutate={crf.codex_support(): {"slug": "gpt-renamed-away"}}),
     "is not in the codex roster"),
    ("std-not-listed", "std", lambda: dict(mutate={crf.codex_std(): {"visibility": "hide"}}), "is not listed"),
    ("std-not-in-api", "std", lambda: dict(mutate={crf.codex_std(): {"supported_in_api": False}}),
     "is not supported_in_api"),
    # D21 fix round 1 (F2): std serves `medium` too (codex_model's std fallbacks; runbook s6), which
    # the sized-row efforts alone (xhigh/max) never asked for.
    ("std-lacks-medium", "std", lambda: dict(efforts={crf.codex_std(): ("low", "high", "xhigh", "max")}),
     "does not offer effort 'medium'"),
    # The astra reserve fix round 1 (item 4): the avengers ratification arbiter runs the std literal @ max.
    ("std-lacks-max", "std", lambda: dict(efforts={crf.codex_std(): ("low", "medium", "high", "xhigh")}),
     "does not offer effort 'max'"),
])
def test_an_illegal_codex_tier_fails_check_and_is_named(tree, fixture_home, case_id, tier, seed, needle):
    _seed_codex(fixture_home, **seed())
    slug = crf.codex_support() if tier == "support" else crf.codex_std()
    done = run_check(tree, fixture_home)
    assert done.returncode == 1, done.stdout + done.stderr
    named = [f for f in _codex_fails(done) if f"codex {tier} {slug!r}" in f and needle in f]
    assert named, (case_id, fails(done))


@pytest.mark.parametrize("tier", ["std", "support"])
def test_a_codex_tier_that_is_the_current_top_fails_check(tree, fixture_home, tier):
    """A strict priority inversion puts the tier model above astra: TOP resolves onto it."""
    slug = crf.codex_support() if tier == "support" else crf.codex_std()
    _seed_codex(fixture_home, priorities={slug: 0})
    done = run_check(tree, fixture_home)
    assert done.returncode == 1, done.stdout + done.stderr
    named = [f for f in _codex_fails(done) if f"codex {tier} {slug!r} is the current codex TOP" in f]
    assert named, fails(done)


@pytest.mark.parametrize("tier", ["std", "support"])
def test_a_deliberate_freeze_onto_a_codex_tier_is_a_warning_not_a_failure(tree, fixture_home, tier):
    """D21 fix round 1 (m5b): a home-tier FREEZE of the codex TOP onto a tier model is legitimate per
    design (R1 bills it std). It is named as a WARN and check exits 0. The unfrozen inversion above
    stays a FAIL."""
    slug = crf.codex_support() if tier == "support" else crf.codex_std()
    doc = {"schema": "seat-model-pins.v1",
           "pins": {"codex": {"top": slug, "set_at": _now_iso(), "reason": "fixture freeze"}}}
    (fixture_home / ".claude" / "state" / "seat-model-pins.json").write_text(json.dumps(doc), encoding="utf-8")
    done = run_check(tree, fixture_home)
    assert _codex_fails(done) == [], done.stdout
    assert done.returncode == 0, fails(done) or done.stderr
    named = [w for w in warns(done) if w.startswith("codex[tree]:") and f"codex {tier} {slug!r}" in w
             and "frozen" in w]
    assert named, done.stdout


def _freeze_codex(fixture_home, slug):
    doc = {"schema": "seat-model-pins.v1",
           "pins": {"codex": {"top": slug, "set_at": _now_iso(), "reason": "fixture freeze"}}}
    (fixture_home / ".claude" / "state" / "seat-model-pins.json").write_text(json.dumps(doc), encoding="utf-8")


def test_the_freeze_warning_says_exactly_what_is_billed_std(tree, fixture_home):
    """D21 fix round 2 (N1): the m5b WARN names what is billed std - the frozen TOP seats (R1) - and
    makes no claim about other seats when the roster alone does not rank the tier TOP."""
    std = crf.codex_std()
    _seed_codex(fixture_home)
    _freeze_codex(fixture_home, std)
    done = run_check(tree, fixture_home)
    assert done.returncode == 0, fails(done) or done.stderr
    named = [w for w in warns(done) if f"codex std {std!r}" in w and "frozen" in w]
    assert named and "the frozen TOP seats are billed std" in named[0], done.stdout
    assert "the roster itself" not in named[0]


def test_the_freeze_warning_names_a_roster_inversion_it_hides(tree, fixture_home):
    """D21 fix round 2 (N1): frozen onto std while the ROSTER ALONE also ranks std first. The frozen
    TOP seats are still billed std, but a non-TOP seat serving std is billed top - the WARN says so
    rather than claiming 'billed std' for everything."""
    std = crf.codex_std()
    _seed_codex(fixture_home, priorities={std: 0})
    _freeze_codex(fixture_home, std)
    done = run_check(tree, fixture_home)
    named = [w for w in warns(done) if f"codex std {std!r}" in w and "frozen" in w]
    assert named, done.stdout
    assert "the frozen TOP seats are billed std" in named[0]
    assert "the roster itself also ranks it TOP" in named[0], named[0]


def test_std_equal_to_support_is_a_warning_and_check_still_exits_0(tree, fixture_home):
    """#302 JC-1: CODEX_STD == CODEX_SUPPORT (a runbook s7 revert to a rev-1/2 row) stays legal."""
    c = committed()
    plant_roster(tree / "skills" / "_meta", **dict(c, codex_std=crf.codex_std(), codex_support=crf.codex_std()))
    done = run_check(tree, fixture_home)
    assert done.returncode == 0, fails(done) or done.stderr
    assert any(w.startswith("codex[tree]: CODEX_STD == CODEX_SUPPORT") for w in warns(done)), done.stdout
    assert "1 warning(s)" in done.stdout.rstrip().splitlines()[-1]


def test_a_rev_2_shaped_roster_without_a_support_tier_warns_and_passes(tree, fixture_home):
    """No CODEX_SUPPORT at all reads as CODEX_STD (JC-1): the same WARN, exit 0."""
    c = committed()
    plant_roster(tree / "skills" / "_meta", **dict(c, codex_support=OMIT))
    done = run_check(tree, fixture_home)
    assert done.returncode == 0, fails(done) or done.stderr
    assert any(w.startswith("codex[tree]: CODEX_STD == CODEX_SUPPORT") for w in warns(done)), done.stdout


def test_no_codex_roster_warns_rather_than_fails(tree, fixture_home):
    """A host without codex has no roster: the tiers cannot be judged, which is said, not failed."""
    (fixture_home / ".codex" / "models_cache.json").unlink()
    done = run_check(tree, fixture_home)
    assert done.returncode == 0, fails(done) or done.stderr
    assert any(w.startswith("codex[tree]: no codex roster") for w in warns(done)), done.stdout


# --------------------------------------------------------------------------- #
# Item 6 - --home and drift
# --------------------------------------------------------------------------- #
def _install_home(tree: Path, home: Path) -> Path:
    meta = home / ".claude" / "skills" / "_meta"
    shutil.copytree(tree / "skills" / "_meta", meta)
    return meta


def test_home_identical_to_the_tree_passes_with_no_drift(tree, fixture_home):
    _install_home(tree, fixture_home)
    done = run_check(tree, fixture_home, "--home")
    assert done.returncode == 0, fails(done)
    assert any(p.startswith("roster[home]:") for p in passes(done))
    assert any(p.startswith("emit[home --size complex]:") for p in passes(done))
    assert any(p.startswith("drift: home and checked tree both at roster rev") for p in passes(done))


def test_a_home_copy_at_a_different_revision_is_reported_as_drift(tree, fixture_home):
    meta = _install_home(tree, fixture_home)
    family = FAMILY
    plant_roster(meta, revision=model_roster.REVISION + 1, main=family, support=_other_alias(family),
                 benched=set(), eligible={family})
    done = run_check(tree, fixture_home, "--home")
    assert done.returncode == 1
    drift = [f for f in fails(done) if f.startswith("drift:")]
    assert len(drift) == 1, fails(done)
    assert f"repo rev {model_roster.REVISION}" in drift[0]
    assert f"home rev {model_roster.REVISION + 1}" in drift[0]
    assert "run install.py" in drift[0]
    # the home copy is itself valid: only drift fails
    assert [f for f in fails(done) if not f.startswith("drift:")] == []


def test_a_home_copy_whose_codex_support_differs_is_reported_as_drift(tree, fixture_home):
    """#302: the drift keys carry codex_support (same revision, a different support tier)."""
    meta = _install_home(tree, fixture_home)
    other = "gpt-5.5"   # listed in the fixture roster with medium, so the home emit resolves
    assert other != crf.codex_support()
    plant_roster(meta, **dict(committed(), codex_support=other))
    done = run_check(tree, fixture_home, "--home")
    assert done.returncode == 1
    drift = [f for f in fails(done) if f.startswith("drift:")]
    assert len(drift) == 1, fails(done)
    assert f"codex_support {crf.codex_support()!r}" in drift[0] and f"codex_support {other!r}" in drift[0], drift
    assert [f for f in fails(done) if not f.startswith("drift:")] == []


@pytest.mark.parametrize("key,over", [("agy_family", {"agy_family": "neon", "agy_harness_version": "5"}),
                                      ("agy_harness_version", {"agy_harness_version": "4.5"}),
                                      ("agy_level_by_size", {"agy_level_by_size": {
                                          "light": "medium", "medium": "medium", "complex": "high"}})])
def test_367_a_home_copy_whose_agy_roster_fields_differ_is_reported_as_drift(tree, fixture_home, key, over):
    """#367 (Sol C10): the drift keys carry the agy family and the harness version (same revision)."""
    meta = _install_home(tree, fixture_home)
    plant_roster(meta, **dict(committed(), **over))
    done = run_check(tree, fixture_home, "--home")
    assert done.returncode == 1
    drift = [f for f in fails(done) if f.startswith("drift:")]
    assert len(drift) == 1, fails(done)
    assert f"{key} {getattr(model_roster, key.upper())!r}" in drift[0] and f"{key} {over[key]!r}" in drift[0], drift
    assert [f for f in fails(done) if not f.startswith("drift:")] == []


def test_367_the_roster_item_reports_the_agy_family_and_harness_literal(tree, fixture_home):
    done = run_check(tree, fixture_home)
    line = next(p for p in passes(done) if p.startswith("roster[tree]:"))
    assert f"agy family {model_roster.AGY_FAMILY} (harness literal gemini-{model_roster.AGY_HARNESS_VERSION}-" \
           f"{model_roster.AGY_FAMILY}-<level>)" in line, line


def test_367c_the_roster_item_reports_the_agy_level_map(tree, fixture_home):
    done = run_check(tree, fixture_home)
    line = next(p for p in passes(done) if p.startswith("roster[tree]:"))
    assert f"agy level by size {dict(model_roster.AGY_LEVEL_BY_SIZE)}" in line, line


def test_367c_a_home_roster_with_a_bad_agy_level_map_fails_the_roster_item(tree, fixture_home):
    meta = _install_home(tree, fixture_home)
    plant_roster(meta, **dict(committed(), agy_level_by_size={"light": "low", "medium": "medium"}))
    done = run_check(tree, fixture_home, "--home")
    assert done.returncode == 1
    assert any(f.startswith("roster[home]:") and "AGY_LEVEL_BY_SIZE must be" in f for f in fails(done)), fails(done)


def test_367_a_home_roster_violating_the_agy_family_rule_fails_the_roster_item(tree, fixture_home):
    meta = _install_home(tree, fixture_home)
    plant_roster(meta, **dict(committed(), agy_family="Argon"))
    done = run_check(tree, fixture_home, "--home")
    assert done.returncode == 1
    assert any(f.startswith("roster[home]:") and "AGY_FAMILY must match" in f for f in fails(done)), fails(done)


def test_a_pre_roster_home_copy_fails_roster_emit_and_drift(tree, fixture_home):
    meta = _install_home(tree, fixture_home)
    (meta / "model_roster.py").unlink()
    done = run_check(tree, fixture_home, "--home")
    assert done.returncode == 1
    names = fails(done)
    assert any(f.startswith("roster[home]: model_roster.py does not import") for f in names), names
    assert any(f.startswith("emit[home]") for f in names), names
    assert any(f.startswith("drift: not compared") for f in names), names


def test_a_stale_home_emit_serving_a_benched_model_is_named(fixture_home, tree):
    """A pre-roster installed copy (today's live home before WP-8's install): a stand-in
    seat_model.py whose emit still serves the benched family and carries no roster_rev. Its
    Claude pins are judged against the CHECKED tree's benched set."""
    bench_fixture_family(tree)
    meta = fixture_home / ".claude" / "skills" / "_meta"
    meta.mkdir(parents=True)
    family = FAMILY
    pins = {role: {"claude": {"model": family if role in sm.PROTECTED else "opus"},
                   "codex": {"model": "gpt-6-astra"}} for role in sm.ROLES}
    (meta / "seat_model.py").write_text(
        "import json\n"
        f"print(json.dumps({{'schema': 'seat-model-emit.v1', 'pins': {pins!r}}}))\n", encoding="utf-8")
    done = run_check(tree, fixture_home, "--home")
    assert done.returncode == 1
    names = fails(done)
    for role in sorted(sm.PROTECTED):
        assert f"emit[home]: {role} x claude serves benched '{family}'" in names, names
    assert "emit[home]: consultant_support x claude serves benched" not in " ".join(names)
    assert "emit[home]: no roster_rev in the emit document (a pre-#291 copy)" in names, names


def test_without_home_the_installed_copy_is_not_read(tree, fixture_home):
    meta = _install_home(tree, fixture_home)
    (meta / "model_roster.py").write_text("raise SystemExit('must not be imported')\n", encoding="utf-8")
    done = run_check(tree, fixture_home)
    assert done.returncode == 0, fails(done)
    assert not any("[home]" in line for line in done.stdout.splitlines())


# --------------------------------------------------------------------------- #
# No model calls
# --------------------------------------------------------------------------- #
def test_check_runs_with_codex_agy_and_claude_absent_from_path(tree, fixture_home, tmp_path):
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    done = run_check(tree, fixture_home, path=str(empty_bin))
    for name in ("codex", "agy", "claude"):
        assert shutil.which(name, path=str(empty_bin)) is None
    assert done.returncode == 0, fails(done) or done.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell stubs")
def test_check_never_invokes_codex_agy_or_claude(tree, fixture_home, tmp_path):
    """Trap stubs on PATH record any invocation; a clean check leaves the trap empty."""
    trap_bin, trap = tmp_path / "trap-bin", tmp_path / "trap.log"
    trap_bin.mkdir()
    for name in ("codex", "agy", "claude"):
        stub = trap_bin / name
        stub.write_text(f"#!/bin/sh\necho {name} \"$@\" >> '{trap}'\nexit 2\n", encoding="utf-8")
        stub.chmod(0o755)
    done = run_check(tree, fixture_home, "--home", path=f"{trap_bin}{os.pathsep}{os.environ.get('PATH', '')}")
    assert done.returncode in (0, 1), done.stderr
    assert not trap.exists(), trap.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Usage
# --------------------------------------------------------------------------- #
def test_a_root_that_is_not_a_directory_is_a_usage_error(fixture_home, tmp_path):
    done = run_check(tmp_path / "nope", fixture_home)
    assert done.returncode == 2
    assert done.stdout == ""
    assert "--root" in done.stderr


# --------------------------------------------------------------------------- #
# #311: every Claude seat is dispatched at an explicit effort
# --------------------------------------------------------------------------- #
def test_311_a_claude_seat_without_an_explicit_effort_fails_check(tree, fixture_home):
    script = tree / "skills" / "_meta" / "seat_model.py"
    text = script.read_text(encoding="utf-8")
    # code_reviewer and consultant_main share this row text (their pinned effort, medium since 2026-10-29).
    old = 'CLAUDE: RoleRow(KIND_ALIAS, value=model_roster.CLAUDE_MAIN, effort="medium", timeout=600),'
    assert text.count(old) == 2
    script.write_text(text.replace(old, 'CLAUDE: RoleRow(KIND_ALIAS, value=model_roster.CLAUDE_MAIN, timeout=600),', 1),
                      encoding="utf-8")
    done = run_check(tree, fixture_home)
    assert done.returncode == 1
    # Fix round 2 item 6: resolution itself now raises for a protected seat without an effort,
    # so `emit` fails and names the seat (check still fails; the message is the resolver's).
    assert any("code_reviewer x claude" in f and "effort" in f for f in fails(done)), fails(done)
