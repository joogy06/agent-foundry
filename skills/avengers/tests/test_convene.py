#!/usr/bin/env python3
"""avengers — test_convene.py (WP-2 base; WP-1 effort-layer rewrite).

Covers the resolver acceptance areas: fail-closed structural validate (sub-quorum,
provider-family floor, arbiter/adversarial-provider invariant, >=1 adversarial),
effort tiers ('high' resolves with a model-scoped measured note; 'minimal' is gone),
two-layer merge (no repo-local override layer), guard-stack injection, session-plan
schema validation, and --dry-run pre-spend review. Runs under pytest; stdlib + PyYAML only.

WP-1 (design §2a) rewrote the effort tests to the SEAT-CLASS contract: effort pins
resolve per (provider, seat-class) through resolve_effort(); a challenger provider-
swap off codex resolves via the challenger_floor seat-class instead of crashing
(success criterion #2); 'high' stayed retired (until S081 WP-105, below); guard_stack_for
+ the ratification-arbiter max/1200 case re-key on (provider, seat-class).

WP-2 (design §4/§9.8) rewrote the ARBITER-SELECTION tests to the EXTERNAL SEATLESS
arbiter contract: the arbiter is a fresh cold-context CALL (is_external/cold_context,
no `seat`), its provider != every deliberation seat (widened from adversarial-only),
clean vs fallback paths, fallback_arbiter_residual on the fallback path, and the ONLY
unsatisfiable case (all-adversarial) fails CLOSED. The plan schema is now
session-plan.v2. Cross-cutting arbiter-behavior tests live in test_arbiter_external.py.

S081 WP-R07 (design §4.2 "one timeout owner per provider", §4.8 convene row, §11 Timeouts /
Adoption; I5, I6, I7, I20) wired the codex and agy guard stacks through
skills/_meta/seat_model.py, fail-closed. Codex stacks now carry `-m <slug>` and take their
ceiling from codex_model.timeout_for (the local codex timeout table is gone); agy stacks carry
`--model <slug>` before `-p`. ISOLATION: the autouse `seat_home` fixture points HOME at a tmp
tree holding a fixture codex roster, the freeze pins and an agy cache, so no test here reads
the live ~/.codex or ~/.claude/state; `test_seat_home_fixture_is_live_not_assumed` proves it
with fixture-only sentinel slugs. Adoption is proven by running the materialised stacks against
stub binaries (`test_stub_launch_*`), not by reading the strings.

S081 WP-105 (S080 §9, §11.1, §11.2; S081 design §4.8, §4.9, §11) follows stream 5 into the
tests. Tests that encoded removed behaviour are INVERTED, not deleted (renamed where the old
name now says the opposite): `high` resolves (codex native, with the gpt-5.6-sol measured
note; claude/agy resolve down), the schema enums accept `high` and still reject an invalid
tier, no tier is retired, Claude seats route through seat_model, `wall_clock_s` is a derived
floor, the shipped skeptic pins the challenger_floor seat-class. New coverage: `minimal` gone
from every convene constant; seat_weight routing (claude fable/opus, agy -high/-medium, codex
consultant_main at any weight, unknown weight fails closed); `model` on seats and the arbiter
in both schemas; the business-ideation creativity flip's agy arbiter (with coding-ratification
and a pre-flip copy as controls); the wall-clock floor; and the stub launch re-run WITHOUT the
codex freeze, which serves the fixture roster TOP (`-m gpt-6-astra`) with no code change.

S081 WP-F04 (amendment 1 D6 + item 4; plan J12, J16): astra unavailable -> PLAN-TIME Fable
substitution of codex member seats, the arbiter recomputed without codex, the optional schema
fields, the one review line and the persisted-path `deliberation` rows. HERMETICITY: plan build
now asks `shutil.which("codex")`, so the autouse `codex_on_path` fixture answers that lookup
(present by default) instead of the host PATH — on a codex-less host every existing test would
otherwise see a substitution. Rollout readings and budget stores live under the fixture HOME.
Every assertion above this section is carried forward unchanged.

#282 r14 (plan K16): every materialised member seat and the arbiter persist `provenance` in the plan
and the run record. Three WP-F04 / R8 key-set assertions are RE-POINTED (names kept, nothing deleted)
from the legacy sets to the legacy sets plus `provenance` (_R14_KEYS):
test_an_unavailable_codex_skeptic_is_re_seated_on_fable_in_coding_ratification (run-record seats),
test_without_a_signal_the_plan_is_the_pre_change_plan (plan seats, arbiter, run-record seats) and
test_r8_a_no_eligible_codex_arbiter_is_excluded_and_the_claude_fallback_serves (arbiter).

S081 revision 4, WP-D2 (design §3.4, §2.2, D17; plan L9): convene ADMITS its codex seat at plan time against
the hoisted session id, a refusal substitutes through the existing path, the admission_id rides on the seat,
`--size` defaults to complex, and --dry-run decides check-only. That closes I11, so FOUR existing tests change,
each listed by name with its reason and NOTHING deleted: test_threshold_and_a_spent_budget_never_substitute is
RENAMED test_a_threshold_now_substitutes_but_a_spent_consult_budget_never_does (threshold half INVERTED,
spent-consult half kept as the control); test_without_a_signal_the_plan_is_the_pre_change_plan (codex seats gain
`admission_id`; the threshold reading moves to the inverted test);
test_dry_run_writes_no_budget_store_and_the_persisted_path_writes_one_row_per_seat (substitution rows key on the
session id, and the no-signal control records the session's one admission); and
test_a_codex_and_claude_profile_relaxes_through_the_substitutes_declared_fallback (its mutant forwards the new
keywords — a signature adaptation, the mutation is unchanged).
"""
import copy
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

_CONVENE = Path(__file__).resolve().parent.parent / "scripts" / "convene.py"
_spec = importlib.util.spec_from_file_location("avengers_convene", _CONVENE)
convene = importlib.util.module_from_spec(_spec)
sys.modules["avengers_convene"] = convene
_spec.loader.exec_module(convene)

_REAL_PROFILES = Path(__file__).resolve().parent.parent / "profiles"
_REAL_ROSTER = Path(__file__).resolve().parent.parent / "roster"
_AVENGERS_ROOT = Path(__file__).resolve().parent.parent
_META = _AVENGERS_ROOT.parent / "_meta"
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import codex_model  # type: ignore  # noqa: E402
import codex_quota  # type: ignore  # noqa: E402
import seat_model  # type: ignore  # noqa: E402
import model_roster  # type: ignore  # noqa: E402

_META_TESTS = _META / "tests"
if str(_META_TESTS) not in sys.path:
    sys.path.insert(0, str(_META_TESTS))
import codex_roster_fixture as crf  # type: ignore  # noqa: E402

#: #291: which model a Claude seat serves is ROSTER DATA. Where a test below means "the role's
#: model" it asserts against these tier constants, read from model_roster (the data), never from
#: the resolver under test: MAIN is what consultant_main / arbiter / a main-weight Claude seat /
#: an astra substitute serve, SUPPORT what consultant_support (a support-weight seat, a DECLARED
#: arbiter) serves. The literal values are pinned once, by hand, in
#: skills/_meta/tests/test_model_roster_golden.py; test_roster_reversibility_* at the end of this
#: file re-runs the profile assertions against two explicit literal pairs.
MAIN = model_roster.CLAUDE_MAIN
SUPPORT = model_roster.CLAUDE_SUPPORT
#: #302 WP-1: the codex tiers, read the same way (model_roster data via the shared synthetic-roster
#: helper). STD = the light/medium sized main seats and the `std` spend class; CODEX_SUP = the
#: consultant_support codex row a supporting codex seat serves (CODEX_STD before roster rev 3).
#: The fixture FREEZE below (codex frozen to gpt-5.6-sol, the stream-3 live state) stays literal:
#: it is a freeze value, not a tier. A test that needs the freeze to BE the std model says so.
STD = crf.codex_std()
CODEX_SUP = crf.codex_support()
#: The astra reserve (roster rev 4, design 2026-09-27 s3): a `main` codex member seat and the codex
#: arbiter are consultant_main / arbiter, now the Sol LITERAL (CODEX_STD) at every size. A literal row
#: never reads the freeze (F8), so under the fixture freeze below they serve STD, not the frozen slug.
#: Where a test below meant "the model the codex member serves" it now says MEMBER.
MEMBER = STD
#: The seat-class benchmark finding and the measured_on model stay keyed on gpt-5.6-sol (DATED DATA).
#: The member model differs, so a seat-class codex member now carries the PROVISIONAL note.
MEASURED = "gpt-5.6-sol"
ROSTER_REV = model_roster.REVISION

_REAL_HOME = Path.home()
_SENTINEL_PROMPT = "SENTINEL PROMPT"


# --------------------------------------------------------------------------- #
# D24: a codex seat call is WATCHED, not wall-clocked (S081 revision 4, WP-A03)
# --------------------------------------------------------------------------- #
#
# The codex guard stack changed shape: `timeout <T> codex exec … < /dev/null` became
# `python3 codex_watch.py --hard-cap <T> … -- codex exec …`. Every assertion that
# pinned the old prefix is RE-POINTED through this builder rather than deleted, so
# each one still pins the SAME facts it always did — the ceiling, the model, the
# effort, `-s read-only`, `--ephemeral` or its absence, and the prompt last.
#
# It is NOT built from convene's own formatting: the flag names, their order and the
# `-- codex exec` separator are written out here literally, so a change in convene's
# emitted shape fails these tests instead of being mirrored by them. The one value
# interpolated from convene is the absolute path to codex_watch.py, which is
# genuinely environment-dependent (repo checkout vs the live ~/.claude copy), and
# test_the_watched_stack_has_the_exact_shape below pins the whole string once so the
# shape is anchored somewhere non-derived.
def _watched_codex_prefix(model, effort, *, ceiling=None, ephemeral=False):
    """The watched codex guard stack's prefix, up to and including the effort pin."""
    cap = codex_model.timeout_for(model, effort) if ceiling is None else ceiling
    return (f"python3 {convene._CODEX_WATCH} --mode codex --model {model} "
            f"--hard-cap {cap} --stdout-file {convene._STDOUT_SLOT} "
            f"--stderr-file {convene._STDERR_SLOT} "
            f"-- codex exec {'--ephemeral ' if ephemeral else ''}-s read-only "
            f"-m {model} -c model_reasoning_effort={effort} ")

_POSIX_SHELL = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or shutil.which("timeout") is None,
    reason="stub-launch tests need bash, coreutils timeout and POSIX shebangs",
)


# --------------------------------------------------------------------------- #
# Seat-model fixture HOME (S081 WP-R07): the resolver reads only home-tier files
# --------------------------------------------------------------------------- #
def _iso_nanos(epoch):
    """The live codex `fetched_at` shape (nine fractional digits)."""
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".887906859Z"


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry(slug, priority, *, visibility="list",
           efforts=("low", "medium", "high", "xhigh", "max", "ultra")):
    return crf.entry(slug, priority, visibility=visibility, efforts=efforts)


def _live_like_codex_entries():
    """The 2026-09-14 live codex roster, reduced to the selection-relevant fields, listing the
    roster's codex tiers (#302 WP-1: the shared synthetic roster, skills/_meta/tests/
    codex_roster_fixture.py; this suite never listed the hidden codex-auto-review entry)."""
    return crf.codex_entries(drop=("codex-auto-review",))


def _live_like_agy_models():
    return [
        "gemini-4-argon-high", "gemini-4-argon-medium", "gemini-4-argon-low",
        "gemini-3.7-argon-high", "gemini-3.7-argon-medium", "gemini-3.7-argon-low",
        "gemini-3.6-argon-high", "gemini-3.6-argon-medium", "gemini-3.6-argon-low",
        # #367: the live cache still lists a retired Google family line beside argon; the agy family rule never
        # selects it. #368 renamed the synthetic line ("nova") so no retired slug is quoted in avengers text.
        "gemini-3.8-nova-high", "gemini-3.8-nova-medium", "gemini-3.8-nova-low",
        "gemini-3.1-pro-high", "gemini-3.1-pro-low",
        "claude-sonnet-4-6", "claude-opus-4-6-thinking", "gpt-oss-120b-medium",
    ]


def _write_codex_roster(home, entries=None):
    crf.write_codex_roster(home, _live_like_codex_entries() if entries is None else entries,
                           fetched_at=_iso_nanos(time.time() - 3600))


def _write_agy_cache(home, models=None):
    doc = {
        "schema": "agy-models.v1",
        "fetched_at": _iso(time.time() - 3600),
        "agy_version": "1.2.2",
        "models": _live_like_agy_models() if models is None else models,
    }
    (home / ".claude" / "state" / "agy-models.json").write_text(json.dumps(doc), encoding="utf-8")


def _pins_path(home):
    return home / ".claude" / "state" / "seat-model-pins.json"


def _write_pins(home, pins=None, *, raw=None):
    if raw is not None:
        _pins_path(home).write_text(raw, encoding="utf-8")
        return
    pins = {"codex": "gpt-5.6-sol", "agy": "gemini-4-argon-high"} if pins is None else pins
    doc = {"schema": "seat-model-pins.v1", "pins": {
        provider: {"top": top, "set_at": _iso(time.time()), "reason": "test_convene fixture"}
        for provider, top in pins.items()
    }}
    _pins_path(home).write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture(autouse=True)
def seat_home(tmp_path, monkeypatch):
    """A fixture HOME shaped like the stream-3 live state: codex frozen to sol, agy to 4-argon (#367; the previous agy family before that)."""
    home = tmp_path / "seat-home"
    (home / ".claude" / "state").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    _write_codex_roster(home)
    _write_agy_cache(home)
    _write_pins(home)
    return home


@pytest.fixture(autouse=True)
def codex_on_path(monkeypatch):
    """S081 WP-F04: answer `shutil.which("codex")` from the fixture (present unless a test flips
    it), never from the host PATH; every other lookup goes to the real shutil.which."""
    state = {"present": True, "calls": 0}
    real_which = shutil.which

    def fake_which(name, *args, **kwargs):
        if name == "codex":
            state["calls"] += 1
            return "/fixture/bin/codex" if state["present"] else None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", fake_which)
    return state


# --------------------------------------------------------------------------- #
# Synthetic fixture builders
# --------------------------------------------------------------------------- #
def _write_card(rdir, seat_id, provider, effort, adversarial, can_arbitrate, fallback_ok=True,
                seat_weight=None):
    rdir.mkdir(parents=True, exist_ok=True)
    # S081 WP-105: `seat_weight` is written as a TOP-LEVEL card field (the only placement convene
    # reads); None writes no line, so every older caller gets the default weight (support).
    weight_line = "" if seat_weight is None else "seat_weight: %s\n" % seat_weight
    (rdir / f"{seat_id}.yaml").write_text(
        "seat_id: %s\n"
        "profession: test\n"
        "adversarial_role: %s\n"
        "can_arbitrate: %s\n"
        "incentive: {optimizes_for: x, discounts: y, standing_challenge: z, failure_mode: w}\n"
        "%s"
        "provider: {affinity: %s, fallback_ok: %s, effort: %s}\n"
        "forbidden: []\n"
        % (seat_id, str(adversarial).lower(), str(can_arbitrate).lower(), weight_line,
           provider, str(fallback_ok).lower(), effort),
        encoding="utf-8",
    )


def _write_profile(pdir, family, seats, arbiter_prefer=None, semantics="ratification",
                   budgets=None, outcome=("decision",), declared_arbiter=None):
    pdir.mkdir(parents=True, exist_ok=True)
    seat_lines = ""
    for s in seats:
        seat_lines += f"  - ref: {s['ref']}\n"
        # WP-2: provider/effort pins are OPTIONAL (a seat dict may omit them to
        # rely on the roster card's affinity — success criterion #1).
        if s.get("provider") is not None:
            seat_lines += f"    provider: {s['provider']}\n"
        if s.get("effort") is not None:
            seat_lines += f"    effort: {s['effort']}\n"
        if s.get("adversarial_role") is not None:
            seat_lines += f"    adversarial_role: {str(s['adversarial_role']).lower()}\n"
        if s.get("seat_weight") is not None:       # S081 WP-105: a profile entry overrides the card
            seat_lines += f"    seat_weight: {s['seat_weight']}\n"
    budget_lines = ""
    if budgets:
        budget_lines = "budgets:\n" + "".join(f"  {k}: {v}\n" for k, v in budgets.items())
    prefer_line = f"  prefer: {arbiter_prefer}\n" if arbiter_prefer else ""
    # AMENDMENT 3: a fixture may DECLARE its arbiter (provider + role + the top-level
    # arbiter_independence). Declaration is an authored act and stays available to every provider;
    # the D25 bar is on SELECTION only, which is why the agy-arbiter fixtures below declare.
    declared_lines, independence_line = "", ""
    if declared_arbiter:
        declared_lines = "".join(f"  {k}: {v}\n" for k, v in declared_arbiter.items())
        independence_line = "arbiter_independence: separate-session\n"
    outcome_list = ", ".join(outcome)
    (pdir / f"{family}.yaml").write_text(
        f"schema: avengers-profile.v1\n"
        f"family: {family}\n"
        f"seats:\n{seat_lines}"
        f"{independence_line}"
        f"arbiter:\n{prefer_line}{declared_lines}  effort_on_codex: max\n"
        f"phases:\n  converge:\n    semantics: {semantics}\n"
        f"outcome:\n  type: [{outcome_list}]\n  default: {outcome[0]}\n"
        f"{budget_lines}",
        encoding="utf-8",
    )


def _std_roster(rdir):
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False)
    _write_card(rdir, "architect", "claude", "default", False, True)
    _write_card(rdir, "operator", "agy", "default", False, True)


# --------------------------------------------------------------------------- #
# Happy path against the REAL shipped profile
# --------------------------------------------------------------------------- #
def test_real_profile_resolves_and_validates():
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t", "outcome": "decision"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER, session_id="fixed-id",
    )
    assert plan["schema"] == "session-plan.v2"
    assert plan["session_id"] == "fixed-id"
    assert len(plan["profile_sha256"]) == 64
    # WP-3 (design §5/§7): coding-ratification gains the steward as the 4th deliberation
    # seat (skeptic + architect + operator + steward), so member_seats is 4. RE-POINTED at
    # AMENDMENT 3 (D25): both agy seats left — operator to codex sol, steward to claude opus —
    # so provider_families is now the TWO families {codex, claude}. The arbiter is still the
    # external claude fallback (asserted below), which the amendment's table also says.
    # RE-POINTED at #368: agy returns as an ADDED fifth seat (user-advocate), so member_seats is 5 and the
    # families are all three again. The arbiter does NOT move (claude, fallback; agy is barred, D23).
    assert plan["quorum"]["member_seats"] == 5
    assert set(plan["quorum"]["provider_families"]) == {"codex", "claude", "agy"}
    # WP-2: the arbiter is a fresh EXTERNAL cold-context call — no `seat` field.
    arb = plan["arbiter"]
    assert "seat" not in arb
    assert arb["is_external"] is True and arb["cold_context"] is True
    assert arb["provider"] == "claude"        # strongest adjudication prior, != adversarial codex
    # in a healthy session coding-ratification lands on the fallback path — this fixture has codex serving, and
    # agy (seated again since #368) is barred from a healthy session's selection; under any
    # codex refusal its arbiter is agy on the fallback path (convene-contract.md, External arbiter)
    assert arb["path"] == "fallback"
    assert arb["fallback_arbiter_residual"] is True
    # no member seat is the arbiter (the participant-judge violation is gone)
    assert all("arbiter" not in s.get("seat_class", "") for s in plan["seats"])
    # schema validation clean (now v2)
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_no_per_seat_pins_resolves_via_affinity(tmp_path):
    # SUCCESS CRITERION #1: a profile with NO per-seat provider pins resolves to a
    # valid, constraint-satisfying staffing (>=2 families, external arbiter,
    # effort-compatible) via the roster cards' affinity — proving provider locks are
    # now opt-in DATA, not schema. A per-seat provider: override still wins.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False)          # affinity codex, adversarial
    _write_card(rdir, "architect", "claude", "default", False, False)
    _write_card(rdir, "operator", "agy", "default", False, False)
    # seat entries omit provider/effort -> the resolver falls back to card affinity.
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": None, "effort": None, "adversarial_role": None},
        {"ref": "architect", "provider": None, "effort": None},
        {"ref": "operator", "provider": None, "effort": None},
    ])
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    seats = {s["seat_id"]: s for s in plan["seats"]}
    assert seats["skeptic"]["provider"] == "codex"       # from card affinity, no pin
    assert seats["architect"]["provider"] == "claude"
    assert seats["operator"]["provider"] == "agy"
    assert set(plan["quorum"]["provider_families"]) == {"codex", "claude", "agy"}  # >=2 families
    assert plan["arbiter"]["is_external"] is True
    assert convene.schema_validate(plan, convene.load_schema()) == []

    # A per-seat provider: override still WINS over the card affinity (opt-in lock).
    _write_profile(pdir, "fam2", [
        {"ref": "skeptic", "provider": None, "effort": None, "adversarial_role": None},
        {"ref": "architect", "provider": None, "effort": None},
        {"ref": "operator", "provider": "claude", "effort": "default"},   # override agy -> claude
    ])
    plan2 = convene.build_session_plan({"profile": "fam2"}, profiles_dir=pdir, roster_dir=rdir)
    seats2 = {s["seat_id"]: s for s in plan2["seats"]}
    assert seats2["operator"]["provider"] == "claude"    # override won over affinity


def test_run_record_written_alongside_session_plan(tmp_path):
    # SUCCESS CRITERION #7: every materialized run writes run-record.json validating
    # against run-record.v1.schema.json with the §6a instrumentation (provider +
    # effort per seat with the seat-class name, fallback_arbiter_residual, the
    # post-run dissent-margin + 1-5 outcome-grade slots).
    rc = convene.main([
        "--profile", "coding-ratification", "--task", "t",
        "--profiles-dir", str(_REAL_PROFILES), "--roster-dir", str(_REAL_ROSTER),
        "--project-root", str(tmp_path), "--session-id", "rr-1",
    ])
    assert rc == 0
    rr_path = tmp_path / ".avengers" / "sessions" / "rr-1" / "run-record.json"
    assert rr_path.exists()
    rr = json.loads(rr_path.read_text(encoding="utf-8"))
    assert convene.schema_validate(rr, convene.load_run_record_schema()) == []
    assert rr["schema"] == "run-record.v1"
    # provider + effort + seat-class name recorded per seat. INVERTED (S081 WP-105): WP-103
    # migrated the shipped skeptic to the challenger_floor SEAT-CLASS (codex -> xhigh), so the
    # class is the semantic name, not the raw tier (the raw-tier-keeps-its-class case moved to
    # a fixture card in test_guard_stacks_injected).
    sk = next(s for s in rr["staffing"]["seats"] if s["seat_id"] == "skeptic")
    assert (sk["provider"], sk["effort"], sk["seat_class"]) == ("codex", "xhigh", "challenger_floor")
    # S081 WP-102/WP-104: the plan-time resolved model is recorded per seat and on the arbiter
    assert sk["model"] == MEMBER
    assert rr["arbiter"]["model"] == MAIN
    # coding-ratification -> fallback arbiter path -> residual flagged
    assert rr["arbiter"]["path"] == "fallback"
    assert rr["fallback_arbiter_residual"] is True
    # post-run outcome slots present but ungraded at materialization time
    assert rr["outcome"] == {"dissent_margin": None, "outcome_grade": None, "graded": False}


def test_guard_stacks_injected(tmp_path):
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    seats = {s["seat_id"]: s for s in plan["seats"]}
    # codex challenger: -s read-only, a pinned MODEL (-m, via seat_model consultant_main)
    # and a pinned effort. S081 I6: consultant_main is a TOP selector, so the call is
    # metered — no --ephemeral (a TOP frozen to sol still meters).
    sk = seats["skeptic"]["guard_stack"]
    assert "-s read-only" in sk
    assert "--ephemeral" not in sk
    assert f"-m {MEMBER}" in sk
    assert sk.index(f"-m {MEMBER}") < sk.index('"')
    assert "model_reasoning_effort=xhigh" in sk
    # RE-POINTED (S081 revision 4, WP-A03, D24): the seat call is watched, and its ceiling
    # rose with the codex table (xhigh 600 -> 2400). Same facts pinned, new shape.
    assert sk.startswith("python3 ")
    assert sk.startswith(_watched_codex_prefix(MEMBER, "xhigh"))
    # WP-1 seat-class contract: every resolved seat carries its seat_class + an
    # (optional) advisory note. INVERTED (S081 WP-105): the shipped skeptic pins the
    # challenger_floor SEAT-CLASS since WP-103, which resolves to xhigh on codex; under the
    # fixture freeze the model (sol) is the class's measured_on model, so there is no note.
    assert seats["skeptic"]["seat_class"] == "challenger_floor"
    # RE-POINTED by the astra reserve: the member serves Sol-6, not the measured_on model, so the
    # challenger_floor tier is recorded as PROVISIONAL for it (never inherited silently).
    assert f"PROVISIONAL for {MEMBER}" in seats["skeptic"]["effort_note"]
    assert seats["skeptic"]["effort"] == "xhigh"
    # A native raw-tier pin keeps the tier as its class — on a FIXTURE card now, since no shipped
    # seat uses one. The class name does not change the stack: same role, effort and model.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "rawtier", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ])
    raw = {s["seat_id"]: s for s in convene.build_session_plan(
        {"profile": "rawtier"}, profiles_dir=pdir, roster_dir=rdir)["seats"]}
    assert (raw["skeptic"]["effort"], raw["skeptic"]["seat_class"]) == ("xhigh", "xhigh")
    assert raw["skeptic"]["effort_note"] is None
    assert raw["skeptic"]["guard_stack"] == sk
    # agy: --sandbox and --model with flags BEFORE -p (the operator card has no seat_weight ->
    # default support -> consultant_support -> the -medium level).
    # RE-POINTED at AMENDMENT 3 (D25): read from the FIXTURE plan `raw`, whose operator is still agy —
    # coding-ratification's operator is a codex sol seat now, asserted just below. The agy guard-stack
    # shape is the subject here, so it moved to a plan that still has one rather than being deleted.
    agy = raw["operator"]["guard_stack"]
    assert agy.startswith('(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan --model gemini-4-argon-medium -p ')
    assert agy.index("--sandbox") < agy.index("-p")
    assert agy.index("--model") < agy.index(" -p ")
    assert agy.endswith(" < /dev/null)")
    # and the shipped coding-ratification operator is now the SUPPORTING codex seat: the support-tier
    # literal. RE-POINTED (#302 WP-4, JC-3): it is not a TOP selector, but no codex seat runs
    # --ephemeral any more — the support tier is metered too (design §3.4b).
    op = seats["operator"]
    assert op["seat_model_role"] == "consultant_support"
    assert op["guard_stack"].startswith(_watched_codex_prefix(CODEX_SUP, "medium", ephemeral=False))
    assert "--ephemeral" not in op["guard_stack"]


# --------------------------------------------------------------------------- #
# Effort tiers: `high` resolves, `minimal` is gone (S081 WP-105 inverts the old
# retired-tier rejection; S080 §4.4, §11.1 reading (a), §11.2, D1)
# --------------------------------------------------------------------------- #
_SOL_HIGH_FINDING = "never beat medium — benchmark 2026-07-11, 14 scored runs"


def test_high_effort_resolves_with_the_model_scoped_note(tmp_path, seat_home):
    # INVERTED from test_reject_high_effort (S081 WP-105). `high` was RETIRED and the plan build
    # raised. The five-edit set (convene WP-102 + the schema enums WP-104) makes it a FULLY
    # RESOLVING codex tier; its 2026-07-11 benchmark finding is now a NOTE scoped to the model it
    # was measured on (MEASURED_EFFORT_FINDINGS), never a provider-wide rejection.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_card(rdir, "skeptic", "codex", "high", True, False)  # 'high' resolves now
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "high"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect")
    # the five-edit set, as constants (the timeout half is ASSERTED, nothing was added for it)
    assert convene.RETIRED_EFFORT_TIERS == frozenset()
    assert "high" in convene.CODEX_EFFORT_TIERS and "high" in convene.KNOWN_CONCRETE_TIERS
    assert codex_model._TIMEOUT_FLOOR_S["high"] == 2400   # RE-POINTED (WP-A03, D24): 600 -> 2400
    assert convene.MEASURED_EFFORT_FINDINGS[("gpt-5.6-sol", "high")] == _SOL_HIGH_FINDING

    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    sk = {s["seat_id"]: s for s in plan["seats"]}["skeptic"]
    assert (sk["provider"], sk["effort"], sk["seat_class"], sk["model"]) == ("codex", "high", "high", MEMBER)
    # RE-POINTED (WP-A03, D24): watched stack; `high` 600 -> 2400.
    assert sk["guard_stack"].startswith(_watched_codex_prefix(MEMBER, "high"))
    # RE-POINTED by the astra reserve: the member serves Sol-6 at every size and a freeze no longer
    # reaches it, so the gpt-5.6-sol finding is NOT inherited (the model-scope rule, at plan level).
    assert _SOL_HIGH_FINDING not in (sk["effort_note"] or "")
    assert "RETIRED" not in (sk["effort_note"] or "")
    assert convene.schema_validate(plan, convene.load_schema()) == []
    # CONTROL (model scope): a freeze change does not move the Sol member at all.
    _write_pins(seat_home, {"agy": "gemini-4-argon-high"})
    plan2 = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    sk2 = {s["seat_id"]: s for s in plan2["seats"]}["skeptic"]
    assert (sk2["effort"], sk2["model"], sk2["effort_note"]) == ("high", MEMBER, sk["effort_note"])

    # Unit level. codex: native pass-through; the note needs the model.
    assert convene.resolve_effort("skeptic", "codex", "high") == ("high", "high", None)
    eff, cls, note = convene.resolve_effort("skeptic", "codex", "high", model="gpt-5.6-sol")
    assert (eff, cls) == ("high", "high") and _SOL_HIGH_FINDING in note
    assert convene.resolve_effort("skeptic", "codex", "high", model="gpt-6-astra") == ("high", "high", None)
    # A non-codex 'high' pin is no longer rejected: it resolves DOWN like any foreign raw tier.
    c_eff, c_cls, c_note = convene.resolve_effort("skeptic", "claude", "high")
    assert (c_eff, c_cls) == ("default", "high")
    assert "no claude-native equivalent" in c_note and "RETIRED" not in c_note


def test_seat_class_tiers_are_provisional_off_their_measured_model():
    # M6 (S080 §11.2): `model` is KEYWORD-only with a None default, so the six pre-M6 call sites
    # above keep their results, and a positional model is a TypeError rather than a silent pin.
    with pytest.raises(TypeError):
        convene.resolve_effort("skeptic", "codex", "high", "gpt-5.6-sol")
    for seat_class in (convene.CHALLENGER_FLOOR, convene.RATIFICATION_ARBITER):
        assert convene.SEAT_CLASS_TABLE[seat_class]["measured_on"] == "gpt-5.6-sol"
    floor = convene.CHALLENGER_FLOOR
    assert convene.resolve_effort("skeptic", "codex", floor, model="gpt-5.6-sol") == ("xhigh", floor, None)
    assert convene.resolve_effort("skeptic", "codex", floor, model="gpt-6-astra") == (
        "xhigh", floor,
        "seat-class 'challenger_floor' tier 'xhigh' was measured on gpt-5.6-sol; PROVISIONAL for gpt-6-astra")
    _e, _c, arb_note = convene.resolve_effort("<arbiter>", "codex", convene.RATIFICATION_ARBITER,
                                              model="gpt-6-astra")
    assert (_e, arb_note) == ("max", "seat-class 'ratification_arbiter' tier 'max' was measured on "
                                     "gpt-5.6-sol; PROVISIONAL for gpt-6-astra")
    # CONTROL: no model -> no lookup; a non-codex seat never gets the codex benchmark caveat.
    assert convene.resolve_effort("skeptic", "codex", floor) == ("xhigh", floor, None)
    _e, _c, claude_note = convene.resolve_effort("skeptic", "claude", floor, model=MAIN)
    assert "anti-sycophancy" in claude_note and "PROVISIONAL" not in claude_note


def _constant_tokens(value):
    """Every str leaf reachable in a constant: dict keys and values, tuples, sets, lists."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _constant_tokens(key)
            yield from _constant_tokens(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _constant_tokens(item)


def _constants_carrying(module, token):
    """Names of module-level UPPER_CASE collection constants that hold `token` as an exact leaf."""
    return sorted(
        name for name, value in vars(module).items()
        if name.lstrip("_").isupper() and isinstance(value, (dict, list, tuple, set, frozenset))
        and token in set(_constant_tokens(value))
    )


def test_minimal_is_gone_from_every_convene_constant(monkeypatch):
    # D1 (S080): no listed codex model supports `minimal`, so convene carries it nowhere.
    assert "minimal" not in convene.CODEX_EFFORT_TIERS
    assert "minimal" not in convene.KNOWN_CONCRETE_TIERS
    assert all("minimal" not in key for key in convene.SEED_LATENCY_S)
    assert _constants_carrying(convene, "minimal") == []
    # ...and a `minimal` pin fails CLOSED as an unknown tier, on every provider.
    for provider in sorted(convene.KNOWN_PROVIDERS):
        with pytest.raises(convene.ConveneError) as e:
            convene.resolve_effort("skeptic", provider, "minimal")
        assert "unknown effort/seat-class 'minimal'" in str(e.value)
    # CONTROL: the scan reaches a tuple key nested in a dict, and a legal tier still resolves.
    monkeypatch.setattr(convene, "PROBE_SEEDS", {("codex", "minimal"): 1}, raising=False)
    assert _constants_carrying(convene, "minimal") == ["PROBE_SEEDS"]
    assert "low" in set(_constant_tokens(convene.SEED_LATENCY_S))
    assert convene.resolve_effort("skeptic", "codex", "low") == ("low", "low", None)


def test_reject_unpinned_codex(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "default"},  # un-pinned codex
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect")
    with pytest.raises(convene.ConveneError):
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)


# --------------------------------------------------------------------------- #
# Seat-class effort semantics (WP-1, design §2a)
# --------------------------------------------------------------------------- #
def test_seat_class_challenger_floor_resolves_per_provider():
    # The challenger_floor seat-class resolves per (provider, seat-class):
    # codex -> xhigh (native, no note); claude/agy -> default + advisory note.
    assert convene.resolve_effort("skeptic", "codex", "challenger_floor") == ("xhigh", "challenger_floor", None)
    c_eff, c_cls, c_note = convene.resolve_effort("skeptic", "claude", "challenger_floor")
    assert (c_eff, c_cls) == ("default", "challenger_floor")
    assert "no codex-equivalent anti-sycophancy floor for this provider" in c_note
    a_eff, a_cls, a_note = convene.resolve_effort("skeptic", "agy", "challenger_floor")
    assert (a_eff, a_cls) == ("default", "challenger_floor")
    assert a_note and "anti-sycophancy floor" in a_note


def test_raw_tier_cross_provider_resolves_not_crash():
    # SUCCESS CRITERION #2 (unit level): the old non-codex + non-'default'
    # fail-closed (former validate_effort:184-189) no longer crashes — a raw
    # codex-band tier pinned on a claude/agy seat resolves DOWN with a note.
    eff, cls, note = convene.resolve_effort("skeptic", "claude", "xhigh")
    assert (eff, cls) == ("default", "xhigh")
    assert note and "no claude-native equivalent" in note
    # codex still MUST be explicitly pinned (un-pinned/illegal codex fails closed).
    with pytest.raises(convene.ConveneError):
        convene.resolve_effort("skeptic", "codex", "default")
    # a truly unknown token (typo'd seat-class) fails closed, not silently resolved.
    with pytest.raises(convene.ConveneError):
        convene.resolve_effort("skeptic", "claude", "challenger_flooor")


def test_challenger_provider_swap_off_codex(tmp_path):
    # SUCCESS CRITERION #2: rotating the challenger (skeptic) OFF codex resolves
    # via the challenger_floor seat-class instead of raising ConveneError, and
    # surfaces the 'no anti-sycophancy floor' note (destined for the run record).
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "claude", "challenger_floor", True, False)
    _write_card(rdir, "architect", "codex", "medium", False, True)
    _write_card(rdir, "operator", "agy", "default", False, True)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "claude", "effort": "challenger_floor"},
        {"ref": "architect", "provider": "codex", "effort": "medium"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="operator")
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    seats = {s["seat_id"]: s for s in plan["seats"]}
    sk = seats["skeptic"]
    assert sk["provider"] == "claude"
    assert sk["effort"] == "default"                 # resolved down — NO crash
    assert sk["seat_class"] == "challenger_floor"    # semantic name preserved
    assert "no codex-equivalent anti-sycophancy floor for this provider" in (sk["effort_note"] or "")
    # the codex seat still pins its native tier into its guard stack
    assert "model_reasoning_effort=medium" in seats["architect"]["guard_stack"]
    # S081 I5: a raw-tier codex seat keeps its own tier under the consultant_main MODEL;
    # I20: its ceiling is codex_model's medium floor (600), not the deleted 180.
    assert f"-m {MEMBER}" in seats["architect"]["guard_stack"]
    # RE-POINTED (WP-A03, D24): watched stack; medium 600 -> 1200.
    assert seats["architect"]["guard_stack"].startswith(
        _watched_codex_prefix(MEMBER, "medium"))
    # the plan still validates against the (unchanged) v1 schema
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_ratification_arbiter_codex_max_1200_rekey(tmp_path):
    # AC3 (WP-2 external-arbiter rewrite): the ratification-arbiter max/1200 special
    # case is keyed on (provider, seat-class). To force a CODEX external arbiter,
    # codex must be the sole NON-adversarial provider (skeptic=claude + arch=agy are
    # adversarial; operator=codex is not) -> the fallback path selects codex, which
    # resolves to 'max' via the RATIFICATION_ARBITER seat-class and gets 1200s —
    # NOT by matching the literal effort string 'max'.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "claude", "challenger_floor", True, False)  # adversarial claude
    _write_card(rdir, "arch", "agy", "default", True, False)                 # adversarial agy
    _write_card(rdir, "operator", "codex", "medium", False, False)           # non-adversarial codex
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "claude", "effort": "challenger_floor"},
        {"ref": "arch", "provider": "agy", "effort": "default"},
        {"ref": "operator", "provider": "codex", "effort": "medium"},
    ])
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    arb = plan["arbiter"]
    assert arb["is_external"] is True and "seat" not in arb
    assert arb["provider"] == "codex"          # sole non-adversarial provider
    assert arb["path"] == "fallback"           # codex deliberated (as operator)
    assert arb["effort"] == "max"
    assert arb["seat_class"] == convene.RATIFICATION_ARBITER
    # RE-POINTED (WP-A03, D24): the ceiling is now carried as the watchdog's --hard-cap,
    # and max rose 1200 -> 3600.
    assert "--hard-cap 3600" in arb["guard_stack"]
    assert "model_reasoning_effort=max" in arb["guard_stack"]
    # S081 I7: the codex arbiter resolves the `arbiter` role (TOP @ max) -> pinned model,
    # metered (no --ephemeral); 1200 is codex_model.timeout_for(model, "max").
    # the astra reserve U4: the arbiter row is the Sol literal; the ratification SEAT CLASS keeps max.
    assert f"-m {MEMBER}" in arb["guard_stack"]
    assert "--ephemeral" not in arb["guard_stack"]
    assert codex_model.timeout_for(MEMBER, "max") == 3600   # RE-POINTED (WP-A03, D24): 1200 -> 3600


def test_guard_stack_for_rekeys_on_seat_class():
    # S081 I20 rewrite. The old contract gave a plain codex 'max' MEMBER seat a 300s
    # ceiling and only the RATIFICATION_ARBITER class 1200. With one timeout owner
    # (codex_model.timeout_for) both get 1200 — a timeout is a ceiling, and the member
    # max call was under-provisioned. What is still keyed per seat is the ROLE: the
    # seat-class resolves the EFFORT upstream (resolve_effort / _resolve_arbiter_effort),
    # and the arbiter flag — never the literal effort string — selects the `arbiter` role.
    member = convene.guard_stack_for("codex", "max", seat_class="max",
                                     is_arbiter=False, is_ratification=True)
    assert "--hard-cap 3600" in member   # RE-POINTED (WP-A03, D24): max 1200 -> 3600, as --hard-cap
    arbiter = convene.guard_stack_for("codex", "max", seat_class=convene.RATIFICATION_ARBITER,
                                      is_arbiter=True, is_ratification=True)
    assert "--hard-cap 3600" in arbiter  # RE-POINTED (WP-A03, D24)

    member_role, member_pin = convene.resolve_seat_pin("codex", "max", is_arbiter=False)
    arbiter_role, arbiter_pin = convene.resolve_seat_pin("codex", "max", is_arbiter=True)
    assert member_role == "consultant_main"
    assert arbiter_role == "arbiter"
    # I5: the raw-tier seat class 'max' keeps its own tier; the consultant_main ROW says xhigh.
    assert seat_model.ROLE_TABLE["consultant_main"]["codex"].effort == "xhigh"
    assert member_pin.effort == "max" and "model_reasoning_effort=max" in member
    assert member_pin.provenance["requested_selector"] == f"{MEMBER}@max"   # the astra reserve: Sol literal
    assert arbiter_pin.effort == "max" and "model_reasoning_effort=max" in arbiter
    # the seat-class name alone never promotes a member seat to the arbiter role
    assert convene.resolve_seat_pin("codex", "max", is_arbiter=False)[0] == "consultant_main"
    assert convene.guard_stack_for("codex", "max", seat_class=convene.RATIFICATION_ARBITER,
                                   is_arbiter=False, is_ratification=True) == member
    # one owner: both ceilings are exactly codex_model's value for (model, effort)
    assert member_pin.model == arbiter_pin.model == MEMBER
    assert member.startswith(_watched_codex_prefix(member_pin.model, "max"))
    # CONTROL: a different raw tier on the same role gets that tier's own ceiling.
    medium = convene.guard_stack_for("codex", "medium", seat_class="medium",
                                     is_arbiter=False, is_ratification=True)
    assert medium.startswith(_watched_codex_prefix(MEMBER, "medium"))
    assert "model_reasoning_effort=medium" in medium


# --------------------------------------------------------------------------- #
# Fail-closed structural sub-quorum
# --------------------------------------------------------------------------- #
def test_fail_closed_too_few_seats(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
    ], arbiter_prefer="architect")
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "sub-quorum" in str(e.value)


def test_fail_closed_single_family_no_fallback(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False, fallback_ok=False)
    _write_card(rdir, "s2", "codex", "medium", False, True, fallback_ok=False)
    _write_card(rdir, "s3", "codex", "medium", False, True, fallback_ok=False)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "s2", "provider": "codex", "effort": "medium"},
        {"ref": "s3", "provider": "codex", "effort": "medium"},
    ], arbiter_prefer="s2")
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "provider family" in str(e.value)


def test_single_family_with_fallback_relaxes(tmp_path):
    # <2 families but a declared fallback -> the family floor relaxes (design §4).
    # WP-2: the EXTERNAL arbiter then resolves on the CLEAN path — a provider used
    # by NO deliberation seat (all seats are codex, so claude/agy are both unused;
    # the strongest-prior one, claude, is picked). No fail-closed here: the only
    # unsatisfiable arbiter case is all-adversarial-across-all-three-providers.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False, fallback_ok=True)
    _write_card(rdir, "s2", "codex", "medium", False, True, fallback_ok=True)
    _write_card(rdir, "s3", "codex", "medium", False, True, fallback_ok=True)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "s2", "provider": "codex", "effort": "medium"},
        {"ref": "s3", "provider": "codex", "effort": "medium"},
    ])
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert plan["quorum"]["fallback_relaxed"] is True
    arb = plan["arbiter"]
    assert arb["is_external"] is True
    assert arb["path"] == "clean"                    # arbiter provider used by no seat
    assert arb["provider"] == "claude"               # strongest adjudication prior among {claude, agy}
    assert arb["fallback_arbiter_residual"] is False  # clean path -> no residual
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_fail_closed_arbiter_unsatisfiable(tmp_path):
    # WP-2: the ONLY unsatisfiable arbiter case — every provider deliberated AND
    # every one is adversarial, so no non-adversarial external arbiter exists.
    # Fails CLOSED (never hangs). All 3 families + all adversarial passes the
    # structural gate (>=1 adversarial), so the failure is specifically the arbiter.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False)     # codex adversarial
    _write_card(rdir, "advclaude", "claude", "default", True, False)  # claude adversarial
    _write_card(rdir, "advagy", "agy", "default", True, False)      # agy adversarial
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "advclaude", "provider": "claude", "effort": "default"},
        {"ref": "advagy", "provider": "agy", "effort": "default"},
    ])
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    msg = str(e.value)
    assert "arbiter constraint unsatisfiable" in msg and "adversarial" in msg


def test_fail_closed_no_adversarial(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "a", "codex", "medium", False, True)
    _write_card(rdir, "b", "claude", "default", False, True)
    _write_card(rdir, "c", "agy", "default", False, True)
    _write_profile(pdir, "fam", [
        {"ref": "a", "provider": "codex", "effort": "medium"},
        {"ref": "b", "provider": "claude", "effort": "default"},
        {"ref": "c", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="b")
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "adversarial" in str(e.value)


# --------------------------------------------------------------------------- #
# Two-layer merge + no repo-local override
# --------------------------------------------------------------------------- #
def test_two_layer_merge_defaults_and_profile(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect", budgets={"max_cycles": 2})
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    # profile wins where set; shipped default fills the rest
    assert plan["budgets"]["max_cycles"] == 2         # from profile
    assert plan["budgets"]["max_seat_calls"] == 10    # from shipped default
    # INVERTED (S081 WP-105 / I12): wall_clock_s has NO shipped default any more. With no profile
    # or caller value it is the floor derived from the resolved timeouts.
    # RE-POINTED (S081 revision 4, WP-A03, D24; expected_red_set): the FORMULA is untouched and
    # is still what this asserts — claude fallback arbiter + 2 x the slowest external member
    # seat. Its inputs moved: the codex xhigh member seat went 600 -> 2400, so
    # 1200 + 2 x 2400 = 6000 (was 1200 + 2 x 600 = 2400). Still no raise note: this fixture
    # profile sets no wall_clock_s, so the floor IS the budget.
    assert "wall_clock_s" not in convene.SHIPPED_DEFAULTS["budgets"]
    wc = plan["wall_clock_floor"]
    assert plan["budgets"]["wall_clock_s"] == wc["floor_s"] == wc["effective_s"] == 6000
    assert wc["floor_s"] == 1200 + 2 * codex_model.timeout_for("gpt-5.6-sol", "xhigh")
    assert (wc["requested_from"], wc["requested_s"], wc["raised"], wc["note"]) == ("none", None, False, None)
    assert plan["merge_provenance"]["layers"] == ["shipped_defaults", "profile"]


def test_caller_budget_request_applied_and_recorded(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect")
    plan = convene.build_session_plan(
        {"profile": "fam", "budget": {"max_seat_calls": 4}},
        profiles_dir=pdir, roster_dir=rdir,
    )
    assert plan["budgets"]["max_seat_calls"] == 4
    assert plan["merge_provenance"]["budget_from_caller_request"] is True


def test_no_repo_local_override_layer(tmp_path):
    # A stray repo-local config must NOT influence the plan (design §3/§14).
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect")
    # Plant repo-local override files convene must ignore.
    (tmp_path / ".avengers").mkdir()
    (tmp_path / ".avengers" / "config.yaml").write_text("budgets: {max_seat_calls: 999}\n")
    (pdir / "override.yaml").write_text("budgets: {max_seat_calls: 888}\n")
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert plan["budgets"]["max_seat_calls"] == 10  # shipped default, NOT 999/888
    assert plan["merge_provenance"]["repo_local_overrides"].startswith("none")


# --------------------------------------------------------------------------- #
# Schema validation catches a corrupt plan
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad_tier", ["ultra-bogus", "minimal"])
def test_schema_rejects_an_invalid_effort_tier_in_plan(bad_tier):
    # INVERTED half (a) of test_schema_rejects_high_effort_in_plan (S081 WP-105): the effort
    # enum still rejects a genuinely invalid tier. `minimal` left the enums with S080 D1 (WP-104).
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    record = convene.build_run_record(plan)
    plan["seats"][0]["effort"] = bad_tier
    errs = convene.schema_validate(plan, convene.load_schema())
    assert errs and any("enum" in e for e in errs)
    plan["seats"][0]["effort"] = "xhigh"
    plan["arbiter"]["effort"] = bad_tier
    assert any("$.arbiter.effort" in e and "enum" in e for e in convene.schema_validate(plan, convene.load_schema()))
    record["staffing"]["seats"][0]["effort"] = bad_tier
    assert any("enum" in e for e in convene.schema_validate(record, convene.load_run_record_schema()))


def test_schema_accepts_high_effort_in_plan():
    # INVERTED half (b): `high` is a legal tier in BOTH schemas' effort enums (edit 5 of the
    # S080 §11.1 five-edit set), on seats and on the arbiter.
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    record = convene.build_run_record(plan)
    plan["seats"][0]["effort"] = "high"
    plan["arbiter"]["effort"] = "high"
    assert convene.schema_validate(plan, convene.load_schema()) == []
    record["staffing"]["seats"][0]["effort"] = "high"
    record["arbiter"]["effort"] = "high"
    assert convene.schema_validate(record, convene.load_run_record_schema()) == []
    # CONTROL: the same slot with a bogus tier is rejected, so the enum is live, not absent.
    plan["seats"][0]["effort"] = "ultra-bogus"
    assert any("enum" in e for e in convene.schema_validate(plan, convene.load_schema()))


def test_schema_rejects_missing_required():
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    del plan["arbiter"]
    errs = convene.schema_validate(plan, convene.load_schema())
    assert any("arbiter" in e for e in errs)


# --------------------------------------------------------------------------- #
# --dry-run review + write flow
# --------------------------------------------------------------------------- #
def test_dry_run_review_text():
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "lower the default?"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    review = convene.render_pre_spend_review(plan)
    assert "PRE-SPEND REVIEW" in review
    assert "NO run performed" in review
    # INVERTED (S081 WP-105): no tier is retired, and the review line reports the empty set honestly.
    assert plan["guard_policy"]["retired_tiers_rejected"] == []
    assert "retired effort tiers rejected: none" in review
    assert "retired effort tiers rejected: high" not in review


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    rc = convene.main([
        "--profile", "coding-ratification", "--task", "t", "--dry-run",
        "--profiles-dir", str(_REAL_PROFILES), "--roster-dir", str(_REAL_ROSTER),
        "--project-root", str(tmp_path),
    ])
    assert rc == 0
    assert not (tmp_path / ".avengers").exists()  # no session dir on dry-run


def test_cli_writes_session_plan(tmp_path):
    rc = convene.main([
        "--profile", "coding-ratification", "--task", "write it",
        "--profiles-dir", str(_REAL_PROFILES), "--roster-dir", str(_REAL_ROSTER),
        "--project-root", str(tmp_path), "--session-id", "sid-1",
    ])
    assert rc == 0
    plan_path = tmp_path / ".avengers" / "sessions" / "sid-1" / "session-plan.json"
    assert plan_path.exists()
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert data["session_id"] == "sid-1"
    assert convene.schema_validate(data, convene.load_schema()) == []


def test_cli_fail_closed_returns_nonzero(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
    ], arbiter_prefer="architect")
    rc = convene.main([
        "--profile", "fam", "--profiles-dir", str(pdir), "--roster-dir", str(rdir),
        "--project-root", str(tmp_path),
    ])
    assert rc == 2  # fail-closed, no spend


# =========================================================================== #
# S081 WP-R07 — guard stacks through seat_model (design §4.2, §4.8, §11; I5-I7, I20)
# =========================================================================== #
def _clean_agy_arbiter_profile(tmp_path):
    """codex members (xhigh + medium) + a claude member, with agy unused -> a CLEAN agy arbiter.

    RE-POINTED at AMENDMENT 3 (D25): agy is no longer SELECTED as an arbiter in a healthy session,
    so this fixture now DECLARES it. That keeps the agy-arbiter machinery these tests exercise —
    guard-stack shape, the agy family rule pin enforcement, roster-TOP resolution — reachable, and it is
    honest about what changed: the bar removed agy from the algorithm's CHOICES, not from the
    harness. The seats are unchanged, so the path is still `clean` (agy deliberates nowhere here).
    """
    rdir, pdir = tmp_path / "roster-agyarb", tmp_path / "profiles-agyarb"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False)
    _write_card(rdir, "architect", "claude", "default", False, False)
    _write_card(rdir, "builder", "codex", "medium", False, False)
    _write_profile(pdir, "agyarb", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "builder", "provider": "codex", "effort": "medium", "seat_weight": "main"},
    ], declared_arbiter={"provider": "agy", "role": "arbiter"})
    return {"profile": "agyarb"}, pdir, rdir


def _codex_arbiter_profile(tmp_path):
    """adversarial claude + adversarial agy + non-adversarial codex -> FALLBACK codex arbiter @ max."""
    rdir, pdir = tmp_path / "roster-codexarb", tmp_path / "profiles-codexarb"
    _write_card(rdir, "skeptic", "claude", "challenger_floor", True, False)
    _write_card(rdir, "arch", "agy", "default", True, False)
    _write_card(rdir, "operator", "codex", "medium", False, False)
    _write_profile(pdir, "codexarb", [
        {"ref": "skeptic", "provider": "claude", "effort": "challenger_floor"},
        {"ref": "arch", "provider": "agy", "effort": "default"},
        {"ref": "operator", "provider": "codex", "effort": "medium"},
    ])
    return {"profile": "codexarb"}, pdir, rdir


def _build(fixture):
    contract, pdir, rdir = fixture
    return convene.build_session_plan(contract, profiles_dir=pdir, roster_dir=rdir)


def _external_calls(plan):
    """(label, provider, effort, is_arbiter, guard_stack) for every codex/agy call in a plan."""
    calls = [(s["seat_id"], s["provider"], s["effort"], False, s["guard_stack"])
             for s in plan["seats"] if s["provider"] in ("codex", "agy")]
    arb = plan["arbiter"]
    if arb["provider"] in ("codex", "agy"):
        calls.append(("<arbiter>", arb["provider"], arb["effort"], True, arb["guard_stack"]))
    return calls


def test_codex_timeout_table_is_deleted():
    # L5 / I20: ONE codex timeout owner. The name is assembled so this file itself stays
    # out of the `grep -rn` the plan runs over skills/avengers.
    table = "CODEX_" + "TIMEOUTS"
    assert not hasattr(convene, table)
    assert not hasattr(convene, "CODEX_RATIFICATION_" + "ARBITER_TIMEOUT")
    hits = []
    for path in _AVENGERS_ROOT.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in (".py", ".md", ".yaml", ".json"):
            if table in path.read_text(encoding="utf-8"):
                hits.append(str(path.relative_to(_AVENGERS_ROOT)))
    assert hits == []
    # CONTROL: the scan really reads files — this file names the adjacent live constant.
    assert "SEED_LATENCY_S" in (_AVENGERS_ROOT / "tests" / "test_convene.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("effort,ceiling", [("low", 1200), ("medium", 1200), ("xhigh", 2400), ("max", 3600)])
def test_codex_ceilings_come_from_codex_model_timeout_for(effort, ceiling):
    # I20 expected ceilings: medium 180->600, xhigh 300->600, member max 300->1200, low 120.
    # RE-POINTED (S081 revision 4, WP-A03; expected_red_set): D24 raised the whole floor table
    # (low 120->1200, medium 600->1200, xhigh 600->2400, max 1200->3600). The GUARD is what it
    # always was — the ceiling in the stack is exactly codex_model's value for (model, effort),
    # one owner — asserted against codex_model below, not against a literal.
    stack = convene.guard_stack_for("codex", effort, seat_class=effort, is_arbiter=False, is_ratification=True)
    assert codex_model.timeout_for(MEMBER, effort) == ceiling
    assert stack.startswith(_watched_codex_prefix(MEMBER, effort, ceiling=ceiling))


def test_agy_ceiling_comes_from_the_seat_model_role_row():
    for is_arbiter, role in ((False, "consultant_support"), (True, "arbiter")):
        row_timeout = seat_model.ROLE_TABLE[role]["agy"].timeout
        stack = convene.guard_stack_for("agy", "default", is_arbiter=is_arbiter)
        assert row_timeout == 600
        assert stack.startswith(f'(d="$(mktemp -d)" && cd "$d" && timeout {row_timeout} agy --sandbox --mode plan --model ')


def test_unknown_effort_raises_convene_error():
    # strict lookup: an effort no roster model supports is a fail-closed resolution failure
    with pytest.raises(convene.ConveneError) as e:
        convene.guard_stack_for("codex", "turbo", seat_class="turbo", is_arbiter=False)
    assert "turbo" in str(e.value)
    # CONTROL: a supported effort resolves on the same fixture
    assert "model_reasoning_effort=xhigh" in convene.guard_stack_for("codex", "xhigh")


def test_untabulated_timeout_raises_convene_error(seat_home):
    # A model that DOES list an effort the codex floor table has no row for: the strict
    # codex_model.timeout_for miss surfaces as ConveneError instead of a default ceiling.
    entries = _live_like_codex_entries()
    for e in entries:
        if e["slug"] == MEMBER:
            e["supported_reasoning_levels"].append({"effort": "turbo", "description": "turbo"})
    _write_codex_roster(seat_home, entries)
    with pytest.raises(codex_model.CodexModelError):
        codex_model.timeout_for(MEMBER, "turbo")
    with pytest.raises(convene.ConveneError) as e:
        convene.guard_stack_for("codex", "turbo", seat_class="turbo")
    assert "no timeout recorded" in str(e.value)
    # CONTROL: the same roster still resolves a tabulated effort
    assert convene.guard_stack_for("codex", "xhigh").startswith(
        _watched_codex_prefix(MEMBER, "xhigh"))


def test_role_mapping_routes_members_by_provider_and_seat_weight(tmp_path):
    # Renamed from test_role_mapping_is_stream_3_interim (S081 WP-105). I7 as amended by §4.8/§4.9
    # (WP-102) as amended by AMENDMENT 3 (D25/D26): EVERY member seat -> consultant_main when
    # seat_weight is main, else consultant_support (the default); a codex call that names NO seat
    # keeps consultant_main; the arbiter -> arbiter for every provider.
    assert convene.seat_role_for("codex", is_arbiter=False) == "consultant_main"
    assert convene.seat_role_for("codex", is_arbiter=True) == "arbiter"
    assert convene.seat_role_for("agy", is_arbiter=False) == "consultant_support"
    assert convene.seat_role_for("agy", is_arbiter=True) == "arbiter"
    # INVERTED: Claude seats ARE routed now (stream 3 raised ConveneError here).
    assert convene.seat_role_for("claude", is_arbiter=False) == "consultant_support"
    assert convene.seat_role_for("claude", is_arbiter=True) == "arbiter"
    for weight, member_role in (("main", "consultant_main"), ("support", "consultant_support")):
        assert convene.seat_role_for("claude", is_arbiter=False, seat_weight=weight) == member_role
        assert convene.seat_role_for("agy", is_arbiter=False, seat_weight=weight) == member_role
        # RE-POINTED at AMENDMENT 3 (D25/D26): a codex SEAT is weight-keyed like every other
        # member seat, which is what lets one profile hold an astra seat and a sol seat.
        assert convene.seat_role_for("codex", is_arbiter=False, seat_weight=weight) == member_role
        for provider in ("codex", "agy", "claude"):
            assert convene.seat_role_for(provider, is_arbiter=True, seat_weight=weight) == "arbiter"
    # still strict on the provider
    with pytest.raises(convene.ConveneError):
        convene.seat_role_for("gemini", is_arbiter=False)
    plan = _build(_clean_agy_arbiter_profile(tmp_path))
    arb = plan["arbiter"]
    assert (arb["provider"], arb["path"]) == ("agy", "clean")
    assert arb["guard_stack"].startswith('(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan --model gemini-4-argon-high -p ')
    seats = {s["seat_id"]: s for s in plan["seats"]}
    assert f"-m {MEMBER} -c model_reasoning_effort=xhigh" in seats["skeptic"]["guard_stack"]
    assert f"-m {MEMBER} -c model_reasoning_effort=medium" in seats["builder"]["guard_stack"]
    # INVERTED (S081 WP-105): the Claude label names the seat_model MODEL. This architect card has
    # no seat_weight -> support -> consultant_support -> opus.
    claude_role, claude_pin = convene.resolve_seat_pin("claude", "default")
    assert (claude_role, claude_pin.model, claude_pin.timeout) == ("consultant_support", SUPPORT, 600)
    assert seats["architect"]["guard_stack"] == convene.claude_guard_stack(claude_pin, role=claude_role)
    assert seats["architect"]["guard_stack"] == (
        f"(claude host seat · model={SUPPORT} via seat_model consultant_support · effort=default · "
        "non-CLI spawn, timeout 600s)")
    plan2 = _build(_codex_arbiter_profile(tmp_path))
    seats2 = {s["seat_id"]: s for s in plan2["seats"]}
    assert seats2["arch"]["guard_stack"].startswith('(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan --model gemini-4-argon-medium -p ')
    assert plan2["arbiter"]["guard_stack"].startswith(
        _watched_codex_prefix(MEMBER, "max"))   # RE-POINTED (WP-A03, D24)


def test_ephemeral_is_decided_by_the_role_selector(monkeypatch):
    # INVERTED (#302 WP-4, JC-3; design §3.4b): I6 made TOP-selector roles omit --ephemeral; the support
    # tier now meters too, so NO codex role carries it, TOP selector or not.
    stack = convene.guard_stack_for("codex", "xhigh")
    assert "--ephemeral" not in stack
    assert seat_model.is_top("consultant_main", "codex") is False     # the astra reserve: a Sol literal
    # A non-TOP selector still routes to its own model (the support tier) — and stays metered.
    assert seat_model.is_top("consultant_support", "codex") is False
    monkeypatch.setattr(convene, "CODEX_MEMBER_ROLE", "consultant_support")
    switched = convene.guard_stack_for("codex", "xhigh")
    assert switched.startswith(
        _watched_codex_prefix(CODEX_SUP, "xhigh", ephemeral=False))   # RE-POINTED (WP-A03, D24; #302)
    assert "--ephemeral" not in switched
    # The arbiter flag reaches the stack's role too: a non-TOP arbiter role routes to the support
    # model (observable in -m), and neither stack is ephemeral.
    monkeypatch.setattr(convene, "CODEX_MEMBER_ROLE", "consultant_main")
    monkeypatch.setattr(convene, "ARBITER_ROLE", "consultant_support")
    arb = convene.guard_stack_for("codex", "max", is_arbiter=True)
    member = convene.guard_stack_for("codex", "max", is_arbiter=False)
    assert f"-m {CODEX_SUP} " in arb and f"-m {CODEX_SUP} " not in member
    assert "--ephemeral" not in arb and "--ephemeral" not in member


@pytest.mark.parametrize("pins_raw,needle", [
    ("{not json", "seat-model-pins"),                                           # unreadable freeze
    # REMOVED by the astra reserve (F8): a codex freeze (`gpt-reserve`) no longer reaches the codex member
    # seat, which is the Sol literal; the codex broken-resolver path is the roster case below.
    (json.dumps({"schema": "seat-model-pins.v1",
                 "pins": {"agy": {"top": "gemini-3.1-pro-high"}}}), "agy family rule"),
    ("ROSTER_INVALID", "roster_invalid"),                                    # the roster the Sol literal reads
])
def test_seat_model_error_surfaces_as_convene_error(seat_home, capsys, pins_raw, needle):
    # RE-POINTED at AMENDMENT 3 (D25): an agy PIN violation can only surface on a profile that resolves an
    # agy seat, and coding-ratification no longer has one. research-synthesis is the profile that does, and
    # it still has a codex seat for the codex rows, so one profile serves every parametrization.
    contract = {"profile": "research-synthesis", "task": "t"}
    if pins_raw == "ROSTER_INVALID":
        (seat_home / ".codex" / "models_cache.json").write_text("{not json", encoding="utf-8")
    else:
        _write_pins(seat_home, raw=pins_raw)
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan(contract, profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER)
    assert needle in str(e.value)
    # fail-CLOSED is convene's choice: the same fixture fail-OPEN would have served a literal
    provider = "agy" if "agy" in pins_raw else "codex"
    # the astra reserve: a codex freeze reaches only the TOP rows, so the codex control reads escalation;
    # the Sol member's own fail-open is the literal, from the (member-less) roster.
    role = "consultant_support" if provider == "agy" else (
        "consultant_main" if pins_raw == "ROSTER_INVALID" else "escalation")
    opened = seat_model.resolve(role, provider, fail_open=True)
    assert opened.provenance["source"] == "harness_literal" and "fallback_reason" in opened.provenance
    # the CLI reports it as a fail-closed convene error, exit 2, nothing materialised
    rc = convene.main(["--profile", "research-synthesis", "--task", "t", "--dry-run",
                       "--profiles-dir", str(_REAL_PROFILES), "--roster-dir", str(_REAL_ROSTER)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "CONVENE FAIL-CLOSED" in err and needle in err
    # CONTROL: a valid freeze (and the full roster) in the same HOME materialises and validates
    _write_codex_roster(seat_home)
    _write_pins(seat_home)
    plan = convene.build_session_plan(contract, profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER)
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_seat_model_unavailable_fails_closed(monkeypatch):
    # `monkeypatch.context()` scopes the simulated import failure so the fixture HOME (set by the
    # autouse seat_home fixture on the same monkeypatch) stays in force for the controls below.
    with monkeypatch.context() as m:
        m.setattr(convene, "_seat_model", None)
        m.setattr(convene, "_SEAT_MODEL_IMPORT_ERROR", "ImportError: simulated")
        with pytest.raises(convene.ConveneError) as e:
            convene.guard_stack_for("codex", "xhigh")
        assert "simulated" in str(e.value)
        with pytest.raises(convene.ConveneError):
            convene.guard_stack_for("agy", "default")
        # INVERTED (S081 WP-105): Claude seats resolve their MODEL through seat_model now, so an
        # unavailable seat_model fails them CLOSED too (stream 3's control said they were unaffected).
        with pytest.raises(convene.ConveneError) as ec:
            convene.guard_stack_for("claude", "default")
        assert "simulated" in str(ec.value)
        # CONTROL: convene's pure helpers do not need seat_model.
        assert convene.resolve_effort("skeptic", "codex", "xhigh") == ("xhigh", "xhigh", None)
        assert convene.seat_role_for("claude", is_arbiter=False) == "consultant_support"
    # CONTROL: with seat_model back (and the fixture HOME still in force) all three providers resolve.
    assert Path.home() != _REAL_HOME
    assert f"model={SUPPORT} via seat_model consultant_support" in convene.guard_stack_for("claude", "default")
    assert convene.guard_stack_for("codex", "xhigh").startswith(
        _watched_codex_prefix(MEMBER, "xhigh"))
    # agy is UNCHANGED by this WP: L13 left the agy seat timeout at 600 and its 900s
    # watchdog cap un-reconciled until revision 5 wires the agy call sites.
    assert convene.guard_stack_for("agy", "default").startswith('(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan --model ')


def test_guard_policy_documents_the_pinned_shapes():
    plan = convene.build_session_plan({"profile": "coding-ratification", "task": "t"},
                                      profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER)
    policy = plan["guard_policy"]
    # RE-POINTED (#302 WP-4, JC-3): the policy states that no codex seat runs ephemeral.
    assert "-m <slug>" in policy["codex"] and "--ephemeral" not in policy["codex"]
    assert "no codex seat runs ephemeral" in policy["codex"]
    assert "--model <slug>" in policy["agy"]
    assert policy["agy"].index("--model") < policy["agy"].index(" -p ")
    # #366: the policy is the real stack with placeholders, so it cannot go stale.
    assert policy["agy"].startswith(convene.agy_guard_stack(convene._PolicyPin))
    assert "--mode plan" in policy["agy"] and "mktemp -d" in policy["agy"]
    # S081 WP-102: the Claude label shape and the seat_weight routing are documented too.
    assert "model=<alias> via seat_model <role>" in policy["claude"]
    assert "seat_weight" in policy["model_resolution"]
    # INVERTED (S081 WP-105): no tier is retired; the field stays and reports the empty set.
    assert policy["retired_tiers_rejected"] == []


def test_seat_home_fixture_is_live_not_assumed(seat_home, tmp_path):
    """Proves the isolation: the resolver reads THIS HOME, not the live one."""
    assert Path.home() == seat_home and Path.home() != _REAL_HOME
    fixture = _clean_agy_arbiter_profile(tmp_path)
    # Roster path: slugs that exist ONLY in this fixture, freeze removed.
    _write_codex_roster(seat_home, [_entry("gpt-fixture-sentinel", 0)] + _live_like_codex_entries())
    _write_agy_cache(seat_home, ["gemini-97.1-argon-high", "gemini-97.1-argon-medium"] + _live_like_agy_models())
    _pins_path(seat_home).unlink()
    plan = _build(fixture)
    seats = {s["seat_id"]: s for s in plan["seats"]}
    # RE-POINTED by the astra reserve: the codex member is the Sol LITERAL, so the roster proof is that
    # it resolves from THIS roster (a roster without the Sol slug fails closed, naming this HOME's file).
    assert f"-m {MEMBER} " in seats["skeptic"]["guard_stack"]
    assert "--model gemini-97.1-argon-high " in plan["arbiter"]["guard_stack"]
    _write_codex_roster(seat_home, [e for e in _live_like_codex_entries() if e["slug"] != MEMBER])
    missing = _by_id(_build(fixture))["skeptic"]                          # this roster lacks Sol -> substituted
    assert (missing["provider"], missing["substitution_reason"]) == ("claude", "no_eligible_model")
    _write_codex_roster(seat_home, [_entry("gpt-fixture-sentinel", 0)] + _live_like_codex_entries())
    assert seat_model.resolve("escalation", "codex").model == "gpt-fixture-sentinel"   # the TOP rows follow it
    # Freeze path: a fixture pins file that the live freeze does not carry.
    _write_pins(seat_home, {"codex": "gpt-5.6-terra", "agy": "gemini-3.7-argon-high"})
    plan = _build(fixture)
    seats = {s["seat_id"]: s for s in plan["seats"]}
    assert f"-m {MEMBER} " in seats["skeptic"]["guard_stack"]          # F8: a freeze never reaches Sol
    assert "--model gemini-3.7-argon-high " in plan["arbiter"]["guard_stack"]
    assert seat_model.resolve("escalation", "codex").model == "gpt-5.6-terra"   # it reaches the TOP rows
    # The one file the resolver writes landed in the fixture HOME.
    tops = json.loads((seat_home / ".claude" / "state" / "seat-model-tops.json").read_text(encoding="utf-8"))
    assert tops["tops"]["codex"]["top"] == "gpt-5.6-terra"


# =========================================================================== #
# S081 WP-105 — stream 5: seat_weight routing, Claude seat models, the business-
# ideation flip, the wall-clock floor (design §4.8, §4.9; I7, I12; S080 §9)
# =========================================================================== #
_WEIGHTED_SEATS = ("codex_main", "codex_support", "claude_main", "claude_default", "agy_main", "agy_support")


def _weighted_profile(tmp_path, family="weighted", overrides=None):
    """One plan exercising every member route. codex is the only adversarial provider and all three
    deliberate, so the arbiter is the FALLBACK claude call (strongest adjudication prior)."""
    rdir, pdir = tmp_path / f"roster-{family}", tmp_path / f"profiles-{family}"
    _write_card(rdir, "codex_main", "codex", "xhigh", True, False, seat_weight="main")
    _write_card(rdir, "codex_support", "codex", "xhigh", False, False, seat_weight="support")
    _write_card(rdir, "claude_main", "claude", "default", False, False, seat_weight="main")
    _write_card(rdir, "claude_default", "claude", "default", False, False)          # no weight -> support
    _write_card(rdir, "agy_main", "agy", "default", False, False, seat_weight="main")
    _write_card(rdir, "agy_support", "agy", "default", False, False, seat_weight="support")
    overrides = overrides or {}
    _write_profile(pdir, family, [
        {"ref": ref, "seat_weight": overrides.get(ref)} for ref in _WEIGHTED_SEATS
    ])
    return {"profile": family}, pdir, rdir


def _claude_label(model, role, timeout):
    return (f"(claude host seat · model={model} via seat_model {role} · effort=default · "
            f"non-CLI spawn, timeout {timeout}s)")


def test_seat_weight_routes_member_seats_to_real_models(tmp_path):
    plan = _build(_weighted_profile(tmp_path))
    seats = {s["seat_id"]: s for s in plan["seats"]}
    expected = {
        # seat_id: (seat_weight, seat_model_role, model, timeout_s)
        # RE-POINTED (S081 revision 4, WP-A03, D24; expected_red_set): the two CODEX rows carry
        # the raised xhigh ceiling (600 -> 2400). Every claude and agy row stays 600 — the raise
        # was to codex_model's table only, which is exactly what this row-by-row form shows.
        "codex_main": ("main", "consultant_main", MEMBER, 2400),       # the astra reserve: Sol
        # RE-POINTED at AMENDMENT 3 (D25/D26): codex no longer ignores weight — a support-weight
        # codex SEAT takes consultant_support (the gpt-5.6-sol literal). The ceiling stays 2400
        # because this fixture pins the seat's effort to xhigh; the ROLE is what moved.
        "codex_support": ("support", "consultant_support", CODEX_SUP, 2400),
        "claude_main": ("main", "consultant_main", MAIN, 600),
        "claude_default": ("support", "consultant_support", SUPPORT, 600),
        "agy_main": ("main", "consultant_main", "gemini-4-argon-high", 600),
        "agy_support": ("support", "consultant_support", "gemini-4-argon-medium", 600),
    }
    got = {sid: (s["seat_weight"], s["seat_model_role"], s["model"], s["timeout_s"]) for sid, s in seats.items()}
    assert got == expected
    codex_stack = _watched_codex_prefix(MEMBER, "xhigh")   # RE-POINTED (WP-A03, D24)
    assert seats["codex_main"]["guard_stack"].startswith(codex_stack)
    # RE-POINTED at AMENDMENT 3: the two codex seats no longer share a stack. RE-POINTED again at
    # #302 WP-4 (JC-3): both are metered now (no --ephemeral); what differs is the MODEL — the
    # supporting seat serves the support tier. That difference IS the second model class.
    assert seats["codex_support"]["guard_stack"] != seats["codex_main"]["guard_stack"]
    assert "--ephemeral" not in seats["codex_support"]["guard_stack"]
    assert "--ephemeral" not in seats["codex_main"]["guard_stack"]
    assert f"-m {CODEX_SUP} " in seats["codex_support"]["guard_stack"]
    assert seats["claude_main"]["guard_stack"] == _claude_label(MAIN, "consultant_main", 600)
    assert seats["claude_default"]["guard_stack"] == _claude_label(SUPPORT, "consultant_support", 600)
    assert seats["agy_main"]["guard_stack"].startswith('(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan --model gemini-4-argon-high -p ')
    assert seats["agy_support"]["guard_stack"].startswith('(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan --model gemini-4-argon-medium -p ')
    # The Claude arbiter is a real model too: the `arbiter` role -> fable, 1200.
    arb = plan["arbiter"]
    assert (arb["provider"], arb["path"], arb["seat_model_role"], arb["model"], arb["timeout_s"]) == (
        "claude", "fallback", "arbiter", MAIN, 1200)
    assert arb["guard_stack"] == _claude_label(MAIN, "arbiter", 1200)
    assert "claude_main" in convene.render_pre_spend_review(plan) and "weight=main" in convene.render_pre_spend_review(plan)

    # A profile seat entry OVERRIDES the card's weight, in both directions.
    over = _build(_weighted_profile(tmp_path, "override",
                                    {"claude_default": "main", "agy_main": "support", "codex_main": "support"}))
    oseats = {s["seat_id"]: s for s in over["seats"]}
    assert (oseats["claude_default"]["seat_weight"], oseats["claude_default"]["model"]) == ("main", MAIN)
    assert (oseats["agy_main"]["seat_weight"], oseats["agy_main"]["model"]) == ("support", "gemini-4-argon-medium")
    # RE-POINTED at AMENDMENT 3 (D25/D26): a profile entry overriding a codex seat to `support` now ROUTES
    # it — this row used to prove codex IGNORED the override, and it proves the opposite now. That override
    # is the mechanism by which one profile holds two codex model classes.
    assert (oseats["codex_main"]["seat_model_role"], oseats["codex_main"]["model"]) == ("consultant_support", CODEX_SUP)
    # CONTROL: the seats the override did not name resolve exactly as in the first plan.
    for sid in ("claude_main", "agy_support", "codex_support"):
        assert oseats[sid]["guard_stack"] == seats[sid]["guard_stack"]


@pytest.mark.parametrize("where,value,needle", [
    ("card", "heavy", "unknown seat_weight 'heavy'"),
    ("card", "1", "unknown seat_weight 1"),                 # YAML int, not a weight name
    ("profile", "primary", "unknown seat_weight 'primary'"),
    ("nested", "main", "seat_weight must be a top-level roster-card field"),
])
def test_unknown_seat_weight_fails_closed(tmp_path, where, value, needle):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    entries = [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ]
    if where == "card":
        _write_card(rdir, "architect", "claude", "default", False, True, seat_weight=value)
    elif where == "profile":
        entries[1]["seat_weight"] = value
    else:   # a copy under provider: would be silently ignored, so convene refuses it
        (rdir / "architect.yaml").write_text(
            "seat_id: architect\nprofession: test\nadversarial_role: false\ncan_arbitrate: true\n"
            "incentive: {optimizes_for: x, discounts: y, standing_challenge: z, failure_mode: w}\n"
            f"provider: {{affinity: claude, fallback_ok: true, effort: default, seat_weight: {value}}}\n"
            "forbidden: []\n", encoding="utf-8")
    _write_profile(pdir, "fam", entries)
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert needle in str(e.value)
    # direct calls refuse an unknown weight too, member and arbiter alike
    with pytest.raises(convene.ConveneError):
        convene.seat_role_for("claude", is_arbiter=False, seat_weight="heavy")
    with pytest.raises(convene.ConveneError):
        convene.seat_role_for("agy", is_arbiter=True, seat_weight="heavy")
    # CONTROL: the same fixture with a legal top-level weight builds.
    _write_card(rdir, "architect", "claude", "default", False, True, seat_weight="main")
    entries[1].pop("seat_weight", None)
    _write_profile(pdir, "fam", entries)
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert {s["seat_id"]: s["model"] for s in plan["seats"]}["architect"] == MAIN


def test_seats_and_arbiter_carry_model_valid_in_both_schemas(tmp_path):
    plan = _build(_weighted_profile(tmp_path))
    schema, rr_schema = convene.load_schema(), convene.load_run_record_schema()
    assert all(isinstance(s["model"], str) and s["model"] for s in plan["seats"])
    assert isinstance(plan["arbiter"]["model"], str) and plan["arbiter"]["model"]
    assert convene.schema_validate(plan, schema) == []
    record = convene.build_run_record(plan)
    assert convene.schema_validate(record, rr_schema) == []
    assert {s["seat_id"]: s["model"] for s in record["staffing"]["seats"]} == {
        s["seat_id"]: s["model"] for s in plan["seats"]}
    assert record["arbiter"]["model"] == plan["arbiter"]["model"] == MAIN
    # OPTIONAL (no v3 bump): an in-flight plan / record without the fields, or with null, validates;
    # `served_model` is a string-or-null slot beside it.
    for doc, sch, seat_list, arb in ((plan, schema, "seats", "arbiter"), (record, rr_schema, None, "arbiter")):
        seat_path = (lambda d: d["seats"]) if seat_list else (lambda d: d["staffing"]["seats"])
        legacy = copy.deepcopy(doc)
        for item in seat_path(legacy) + [legacy[arb]]:
            item.pop("model", None)
        assert convene.schema_validate(legacy, sch) == []
        nulled = copy.deepcopy(doc)
        for item in seat_path(nulled) + [nulled[arb]]:
            item["model"], item["served_model"] = None, None
        assert convene.schema_validate(nulled, sch) == []
        served = copy.deepcopy(doc)
        seat_path(served)[0]["served_model"] = "gpt-5.6-sol"
        assert convene.schema_validate(served, sch) == []
        # CONTROL: the fields are TYPED, so a non-string model is rejected on a seat and the arbiter.
        for bad in (7, ["fable"], {"m": 1}):
            typed = copy.deepcopy(doc)
            seat_path(typed)[0]["model"] = bad
            typed[arb]["served_model"] = bad
            errs = convene.schema_validate(typed, sch)
            assert any(".model" in e and "expected type" in e for e in errs)
            assert any(".served_model" in e and "expected type" in e for e in errs)


def test_a3_business_ideation_declares_its_opus_arbiter_at_its_derived_floor():
    """REPLACES test_business_ideation_flip_puts_an_agy_arbiter_on_the_fallback_path (AMENDMENT 3 item 8).

    RETIREMENT, recorded here rather than in a commit message. The retired node was the cycle's LAST
    expected_red_set member. It was left red on purpose at WP-A03 to FORCE this stage to re-derive
    business-ideation's wall_clock_s instead of merely permitting it, and it did its job. It is retired
    rather than re-pointed because amendment 3 DELETES BOTH of its premises: the profile no longer seats
    agy (D25) and no longer takes an agy fallback arbiter (D23/D26, now a DECLARED Opus arbiter). Its name
    says "puts an agy arbiter on the fallback path", so re-pointing it to Opus would leave the name lying
    about what it checks, and renaming it would make the node VANISH rather than go green — the WP-D3
    PARTIAL flagged exactly that trap. The replacement below asserts what the node was protecting (the
    floor is DERIVED and met) on the composition that now ships.
    """
    plan = _real_plan("business-ideation")
    assert convene.schema_validate(plan, convene.load_schema()) == []
    seats = _by_id(plan)
    # D26 composition: skeptic Fable (adversary) · economist Fable · operator codex sol · architect codex TOP
    sk = seats["skeptic"]
    assert (sk["provider"], sk["model"], sk["seat_model_role"], sk["seat_weight"]) == (
        "claude", MAIN, "consultant_main", "main")
    assert (sk["adversarial_role"], sk["effort"], sk["seat_class"]) == (True, "default", "challenger_floor")
    econ = seats["economist"]
    assert (econ["provider"], econ["model"], econ["seat_model_role"], econ["seat_weight"]) == (
        "claude", MAIN, "consultant_main", "main")          # D26: Fable, NOT opus — this is what frees the arbiter
    arch, op = seats["architect"], seats["operator"]
    assert (arch["provider"], arch["seat_model_role"], arch["effort"]) == ("codex", "consultant_main", "xhigh")
    assert (op["provider"], op["seat_model_role"], op["effort"], op["seat_weight"]) == (
        "codex", "consultant_support", "medium", "support")
    assert op["model"] == CODEX_SUP
    # RE-POINTED at #368: D25 removed agy; #368 adds it back as a fifth, ADDED seat — the user-advocate on
    # consultant_main (unsized here: -high). Every D26 seat above is unchanged.
    ua = seats["user-advocate"]
    assert (ua["provider"], ua["seat_model_role"], ua["seat_weight"], ua["model"]) == (
        "agy", "consultant_main", "main", "gemini-4-argon-high")
    assert [s["seat_id"] for s in plan["seats"] if s["provider"] == "agy"] == ["user-advocate"]
    assert set(plan["quorum"]["provider_families"]) == {"codex", "claude", "agy"}
    # D23 declared arbiter: Opus, separate session, and its model is no seat's model
    arb = plan["arbiter"]
    assert (arb["provider"], arb["model"], arb["seat_model_role"], arb["timeout_s"]) == (
        "claude", SUPPORT, "consultant_support", 600)
    assert (arb["selection"], arb["independence"]) == ("declared", "separate-session")
    assert arb["model"] not in {s["model"] for s in plan["seats"]}
    assert arb["obligations"] == list(convene.DECLARED_ARBITER_OBLIGATIONS)
    # THE FLOOR, derived from THIS plan rather than copied: 600 + 2 x 2400 = 5400, met, no raise note.
    # #368 adds the agy user-advocate (600), which is not the slowest, so the floor does not move.
    wc = plan["wall_clock_floor"]
    external = [s["timeout_s"] for s in plan["seats"] if s["provider"] in ("codex", "agy")]
    assert sorted(external) == [600, 1200, 2400]               # agy, the support tier @ medium, sol @ xhigh
    assert wc["floor_s"] == arb["timeout_s"] + 2 * max(external) == 5400
    assert (plan["budgets"]["wall_clock_s"], wc["requested_from"], wc["raised"], wc["note"]) == (
        5400, "profile", False, None)


def test_business_ideation_agy_arbiter_comes_from_the_flip(tmp_path):
    # CONTROL for the flip: the real profile with its two seat providers put back (pre-flip), under
    # the same real roster, priors and fixture pins, resolves the pre-flip claude arbiter.
    doc = yaml.safe_load((_REAL_PROFILES / "business-ideation.yaml").read_text(encoding="utf-8"))
    by_ref = {s["ref"]: s for s in doc["seats"]}
    assert (by_ref["skeptic"]["provider"], by_ref["architect"]["provider"]) == ("claude", "codex")
    by_ref["skeptic"]["provider"] = "codex"
    by_ref["architect"].update(provider="claude", effort="default")
    pdir = tmp_path / "profiles-preflip"
    pdir.mkdir()
    (pdir / "business-ideation.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    plan = convene.build_session_plan({"profile": "business-ideation", "task": "t"},
                                      profiles_dir=pdir, roster_dir=_REAL_ROSTER)
    arb = plan["arbiter"]
    # RE-POINTED at AMENDMENT 3: the pre-flip copy still carries the profile's DECLARED arbiter (the
    # declaration is not part of the flip), so it resolves consultant_support -> opus 600, not the selected
    # `arbiter` row -> fable 1200. What this control proves is unchanged: the SEATS come from the flip.
    assert (arb["provider"], arb["path"], arb["model"], arb["timeout_s"]) == ("claude", "fallback", SUPPORT, 600)
    seats = {s["seat_id"]: s for s in plan["seats"]}
    assert (seats["skeptic"]["provider"], seats["skeptic"]["model"]) == ("codex", MEMBER)
    assert (seats["architect"]["provider"], seats["architect"]["model"]) == ("claude", MAIN)
    # the profile's 1800 is below THIS arrangement's floor, so it is raised.
    # RE-POINTED (S081 revision 4, WP-A03, D24; expected_red_set): the FLOOR moved, not the
    # profile — this pre-flip arrangement is a CLAUDE arbiter (1200) over a codex xhigh member
    # seat (600 -> 2400), so 1200 + 2 x 2400 = 6000 (was 1200 + 2 x 600 = 2400). `raised` was
    # already True and stays True: the assertion still says "1800 is below the floor", which is
    # the fact this line exists for.
    # RE-POINTED at AMENDMENT 3: the pre-flip copy keeps the DECLARED opus arbiter (600), and its slowest
    # external seat is still a codex xhigh (2400), so its floor is 5400 — the shipped value — and nothing is
    # raised. It read (6000, True) when the pre-flip arbiter was the selected fable row (1200).
    assert (plan["budgets"]["wall_clock_s"], plan["wall_clock_floor"]["raised"]) == (5400, False)
    # AMENDMENT 3: the arbiter term is the DECLARED consultant_support row (opus, 600), not the selected
    # `arbiter` row (fable, 1200) — the declaration survives the seats being put back.
    assert plan["wall_clock_floor"]["floor_s"] == 600 + 2 * codex_model.timeout_for(MEMBER, "xhigh")


def test_real_roster_cards_carry_the_seat_class_and_weight_without_profile_pins(tmp_path):
    # WP-103's card edits are DATA a profile reaches through affinity. Every shipped profile pins the
    # skeptic's effort per seat, so this reads the REAL cards with NO per-seat provider/effort/weight.
    pdir = tmp_path / "profiles-affinity"
    _write_profile(pdir, "affinity", [{"ref": "skeptic"}, {"ref": "architect"}, {"ref": "operator"}])
    plan = convene.build_session_plan({"profile": "affinity"}, profiles_dir=pdir, roster_dir=_REAL_ROSTER)
    seats = {s["seat_id"]: s for s in plan["seats"]}
    got = {sid: (s["provider"], s["effort"], s["seat_class"], s["seat_weight"], s["model"]) for sid, s in seats.items()}
    assert got == {
        "skeptic": ("codex", "xhigh", "challenger_floor", "main", MEMBER),
        "architect": ("claude", "default", "default", "main", MAIN),
        "operator": ("agy", "default", "default", "support", "gemini-4-argon-medium"),
    }
    assert seats["skeptic"]["adversarial_role"] is True
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_activation_records_provisional_notes_off_the_measured_model(tmp_path, seat_home):
    # S080 §4.4 measured_on, made operational by WP-102 on seats AND the arbiter. RE-POINTED by the
    # astra reserve (roster rev 4): the codex member and the codex arbiter serve the Sol LITERAL (Sol-6),
    # which is not the measured model, so the PROVISIONAL caveat is recorded with or without a freeze.
    provisional = "seat-class {!r} tier {!r} was measured on gpt-5.6-sol; PROVISIONAL for " + MEMBER
    contract = {"profile": "coding-ratification", "task": "t"}
    frozen = convene.build_session_plan(contract, profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER)
    frozen_arb = _build(_codex_arbiter_profile(tmp_path))
    # a freeze no longer reaches them (F8): the notes are present under the freeze too
    assert {s["seat_id"]: s for s in frozen["seats"]}["skeptic"]["effort_note"] == provisional.format(
        "challenger_floor", "xhigh")
    assert (frozen_arb["arbiter"]["provider"], frozen_arb["arbiter"]["effort_note"]) == (
        "codex", provisional.format("ratification_arbiter", "max"))

    _write_pins(seat_home, {"agy": "gemini-4-argon-high"})
    active = convene.build_session_plan(contract, profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER)
    skeptic = {s["seat_id"]: s for s in active["seats"]}["skeptic"]
    assert (skeptic["model"], skeptic["effort"]) == (MEMBER, "xhigh")
    assert skeptic["effort_note"] == provisional.format("challenger_floor", "xhigh")
    assert active["arbiter"]["provider"] == "claude"          # the arbiter stays fable; no codex caveat
    active_arb = _build(_codex_arbiter_profile(tmp_path))
    arb = active_arb["arbiter"]
    assert (arb["model"], arb["effort"], arb["seat_class"]) == (MEMBER, "max", convene.RATIFICATION_ARBITER)
    assert arb["effort_note"] == provisional.format("ratification_arbiter", "max")
    record = convene.build_run_record(active_arb)
    assert f"<arbiter>: {arb['effort_note']}" in record["advisory_notes"]
    assert f"note : {arb['effort_note']}" in convene.render_pre_spend_review(active_arb)


def _floor_plan(tmp_path, family, seats, *, budgets=None, caller_budget=None, cards=None):
    rdir, pdir = tmp_path / f"roster-{family}", tmp_path / f"profiles-{family}"
    _std_roster(rdir)
    for card in cards or ():
        _write_card(rdir, *card)
    _write_profile(pdir, family, seats, budgets=budgets)
    contract = {"profile": family}
    if caller_budget is not None:
        contract["budget"] = caller_budget
    return convene.build_session_plan(contract, profiles_dir=pdir, roster_dir=rdir)


_STD_SEATS = [
    {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
    {"ref": "architect", "provider": "claude", "effort": "default"},
    {"ref": "operator", "provider": "agy", "effort": "default"},
]


def test_wall_clock_floor_raises_a_below_floor_budget_with_a_note(tmp_path):
    # I12: floor = arbiter timeout + 2 x the slowest EXTERNAL member seat, from resolved timeouts.
    # RE-POINTED (S081 revision 4, WP-A03, D24; expected_red_set): the FORMULA and every
    # behaviour asserted here are unchanged — only the member-seat input moved, codex xhigh
    # 600 -> 2400, so the floor is 1200 + 2 x 2400 = 6000 (was 2400). The claude arbiter term
    # (1200) did NOT move: Claude pin timeouts are ROLE_TABLE harness literals, untouched by
    # the codex table raise. The CONTROL values below move with the floor for the same reason.
    low = _floor_plan(tmp_path, "low", _STD_SEATS, budgets={"wall_clock_s": 900})
    wc = low["wall_clock_floor"]
    assert (wc["arbiter_timeout_s"], wc["member_seat_timeout_s"], wc["member_turns"], wc["floor_s"]) == (
        1200, 2400, 2, 6000)
    assert low["budgets"]["wall_clock_s"] == wc["effective_s"] == 6000
    assert (wc["requested_s"], wc["requested_from"], wc["raised"]) == (900, "profile", True)
    assert wc["note"] == (f"wall_clock_s 900 (from profile) is below the derived floor 6000 "
                          f"({wc['formula']}); raised to 6000")
    review = convene.render_pre_spend_review(low)
    assert f"wall-clock floor: {wc['formula']}" in review and f"note : {wc['note']}" in review
    # CONTROL: a profile value at or above the floor is untouched, with no note.
    for value in (6000, 9000):
        kept = _floor_plan(tmp_path, f"kept{value}", _STD_SEATS, budgets={"wall_clock_s": value})
        assert kept["budgets"]["wall_clock_s"] == value
        assert (kept["wall_clock_floor"]["raised"], kept["wall_clock_floor"]["note"]) == (False, None)
        assert "is below the derived floor" not in convene.render_pre_spend_review(kept)
    # A caller request is floored as well (a legal call is never truncated), with its own provenance.
    caller = _floor_plan(tmp_path, "caller", _STD_SEATS, budgets={"wall_clock_s": 9000},
                         caller_budget={"wall_clock_s": 60})
    assert caller["budgets"]["wall_clock_s"] == 6000
    assert (caller["wall_clock_floor"]["requested_from"], caller["wall_clock_floor"]["raised"]) == (
        "caller_request", True)
    # A non-integer budget fails CLOSED.
    with pytest.raises(convene.ConveneError) as e:
        _floor_plan(tmp_path, "bad", _STD_SEATS, budgets={"wall_clock_s": '"soon"'})
    assert "wall_clock_s must be an integer" in str(e.value)


def test_wall_clock_floor_follows_the_slowest_external_member_seat(tmp_path):
    # The slowest EXTERNAL seat sets the member term: a codex max member doubles into it.
    # RE-POINTED (S081 revision 4, WP-A03, D24; expected_red_set): max 1200 -> 3600, so
    # 1200 + 2 x 3600 = 8400 (was 3600).
    slow = _floor_plan(tmp_path, "slow", _STD_SEATS + [{"ref": "builder", "provider": "codex", "effort": "max"}],
                       cards=[("builder", "codex", "max", False, False)])
    assert (slow["wall_clock_floor"]["member_seat_timeout_s"], slow["wall_clock_floor"]["floor_s"]) == (3600, 8400)
    # Claude members are NOT external: a codex `low` seat sets the term even beside 600s Claude
    # seats; the only uncovered provider (agy) is the clean arbiter, 600 -> 600 + 2 x 1200.
    # RE-POINTED with it: codex `low` 120 -> 1200, so this floor is 3000 (was 840). The POINT
    # of the case is unchanged and still load-bearing — the Claude seats' 600 is ignored
    # because they are not external, which is now MORE visible, not less: 1200 > 600 either way,
    # so the CONTROL below (no external member at all -> the Claude seat stands in) is what
    # proves the branch, and it is untouched at 1800.
    fast = _floor_plan(tmp_path, "fast", [
        {"ref": "skeptic", "provider": "codex", "effort": "low"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "claude", "effort": "default"},
    ])
    fwc = fast["wall_clock_floor"]
    # RE-POINTED at AMENDMENT 3 (D25): agy is barred from a healthy session's arbiter, so this fixture's
    # arbiter is the claude `arbiter` row (fable, 1200) and the floor rises 3000 -> 3600. The PROPERTY under
    # test is unchanged and still visible: the member term is the SLOWEST external seat (1200), not the sum.
    assert (fast["arbiter"]["provider"], fwc["arbiter_timeout_s"], fwc["member_seat_timeout_s"], fwc["floor_s"]) == (
        "claude", 1200, 1200, 3600)
    assert fwc["member_basis"] == "slowest external (codex/agy) member seat"
    # CONTROL: with NO external member seat, the slowest member seat (Claude, 600) stands in.
    claude_only = _floor_plan(tmp_path, "claudeonly", [
        {"ref": "skeptic", "provider": "claude", "effort": "challenger_floor"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "claude", "effort": "default"},
    ], cards=[("skeptic", "claude", "challenger_floor", True, False)])
    cwc = claude_only["wall_clock_floor"]
    assert cwc["member_basis"] == "slowest member seat (no external member seat in this plan)"
    # RE-POINTED at AMENDMENT 3 (D25): with agy barred from a healthy session's arbiter, this all-claude
    # fixture's arbiter is no longer the agy `arbiter` row (600) but a codex one at `max` (3600), so the
    # floor is 3600 + 2 x 600. The PROPERTY under test is untouched: with no external MEMBER seat, the
    # member term falls back to the slowest member seat (600), which is what member_basis records.
    assert (cwc["arbiter_timeout_s"], cwc["member_seat_timeout_s"], cwc["floor_s"]) == (3600, 600, 4800)


# --------------------------------------------------------------------------- #
# Stub-launch materialisation (design §11 Adoption)
# --------------------------------------------------------------------------- #
_STUB = """#!/bin/sh
printf '%s\\n' "$@" > "$STUB_RECORD"
cat > /dev/null
printf 'eof\\n' > "$STUB_RECORD.eof"
"""


def _stub_bindir(tmp_path):
    bindir = tmp_path / "stub-bin"
    bindir.mkdir(exist_ok=True)
    for name in ("codex", "agy"):
        stub = bindir / name
        stub.write_text(_STUB, encoding="utf-8")
        stub.chmod(0o755)
    return bindir


def _run_stack(stack, bindir, record, *, timeout=30):
    """Run a guard stack VERBATIM through bash (only the prompt slot replaced), with bash's
    own stdin a pipe held OPEN, so the stub can reach EOF only through the stack's redirect.

    S081 revision 4, WP-D3: the stack runs with its cwd set to the record's directory (every caller's
    tmp_path). The codex stack's `{stdout-file}` / `{stderr-file}` are DELIBERATE unfilled slots (convene
    _STDOUT_SLOT / _STDERR_SLOT — the chair substitutes run-scoped paths), so codex_watch.py writes two files
    literally named after them into its cwd; with no cwd they landed in the PYTEST cwd, which from the repo
    root would be two untracked strays. Pinned by
    test_d3_a_stub_launch_writes_its_stream_slots_beside_its_record_never_into_the_pytest_cwd."""
    script = stack.replace(f'"{convene._PROMPT_SLOT}"', f'"{_SENTINEL_PROMPT}"')
    assert script != stack, "the stack carries no prompt slot"
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["STUB_RECORD"] = str(record)
    proc = subprocess.Popen(["bash", "-c", script], env=env, stdin=subprocess.PIPE, cwd=str(Path(record).parent),
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        code = None
    finally:
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", "replace")
        proc.stderr.close()
    return code, stderr


def _pinned_argv_problems(provider, argv):
    """Every way a recorded argv fails the pinned shape; [] means it passes."""
    problems = []
    if not argv or argv[-1] != _SENTINEL_PROMPT:
        problems.append("prompt is not the last argument")
    flag = "-m" if provider == "codex" else "--model"
    if flag not in argv:
        problems.append(f"no {flag}")
    else:
        i = argv.index(flag)
        if i + 1 >= len(argv) or argv[i + 1] == _SENTINEL_PROMPT or argv[i + 1].startswith("-"):
            problems.append(f"{flag} carries no model")
        if _SENTINEL_PROMPT in argv and i > argv.index(_SENTINEL_PROMPT):
            problems.append(f"{flag} after the prompt")
    if provider == "codex":
        if argv[:1] != ["exec"]:
            problems.append("not `codex exec`")
        if "-s" not in argv or argv[argv.index("-s") + 1:argv.index("-s") + 2] != ["read-only"]:
            problems.append("no -s read-only")
    else:
        if "--sandbox" not in argv or "-p" not in argv:
            problems.append("no --sandbox / -p")
        else:
            if argv.index("--sandbox") > argv.index("-p"):
                problems.append("--sandbox after -p")
            if flag in argv and argv.index(flag) > argv.index("-p"):
                problems.append("--model after -p")
            if argv.index("-p") != len(argv) - 2:
                problems.append("-p is not immediately before the prompt")
    return problems


@_POSIX_SHELL
@pytest.mark.parametrize("builder", [_clean_agy_arbiter_profile, _codex_arbiter_profile])
def test_stub_launch_materialised_stacks_are_pinned(tmp_path, builder):
    plan = _build(builder(tmp_path))
    calls = _external_calls(plan)
    assert {c[1] for c in calls} == {"codex", "agy"}                      # both providers exercised
    assert any(c[3] for c in calls)                                       # and an arbiter call
    bindir = _stub_bindir(tmp_path)
    for n, (label, provider, effort, is_arbiter, stack) in enumerate(calls):
        record = tmp_path / f"call-{n}.argv"
        started = time.monotonic()
        code, stderr = _run_stack(stack, bindir, record)
        assert code == 0, (label, stack, stderr)
        assert time.monotonic() - started < 20
        argv = record.read_text(encoding="utf-8").splitlines()
        assert _pinned_argv_problems(provider, argv) == [], (label, argv)
        assert (tmp_path / f"call-{n}.argv.eof").exists(), (label, "stdin never reached EOF")
        role, pin = convene.resolve_seat_pin(provider, effort, is_arbiter=is_arbiter)
        if provider == "codex":
            assert argv[argv.index("-m") + 1] == pin.model == MEMBER
            assert f"model_reasoning_effort={effort}" in argv
            assert "--ephemeral" not in argv
            assert stack.startswith(_watched_codex_prefix(pin.model, effort))
        else:
            level = "high" if is_arbiter else "medium"
            assert argv == ["--sandbox", "--mode", "plan", "--model", f"gemini-4-argon-{level}", "-p", _SENTINEL_PROMPT]
            assert stack.startswith(f'(d="$(mktemp -d)" && cd "$d" && timeout {seat_model.ROLE_TABLE[role]["agy"].timeout} ')


@_POSIX_SHELL
def test_stub_launch_unpinned_stack_fails_the_same_assertion(tmp_path):
    """NEGATIVE CONTROL: the materialised stack with its pin removed fails `_pinned_argv_problems`."""
    plan = _build(_codex_arbiter_profile(tmp_path))
    bindir = _stub_bindir(tmp_path)
    checked = set()
    for n, (label, provider, effort, is_arbiter, stack) in enumerate(_external_calls(plan)):
        _role, pin = convene.resolve_seat_pin(provider, effort, is_arbiter=is_arbiter)
        unpinned = stack.replace(" " + " ".join(pin.argv_fragment[:2]), "")
        assert unpinned != stack
        record = tmp_path / f"unpinned-{n}.argv"
        code, stderr = _run_stack(unpinned, bindir, record)
        assert code == 0, stderr
        problems = _pinned_argv_problems(provider, record.read_text(encoding="utf-8").splitlines())
        assert ("no -m" if provider == "codex" else "no --model") in problems
        checked.add(provider)
    assert checked == {"codex", "agy"}


@_POSIX_SHELL
def test_a_failed_mktemp_refuses_the_agy_call(tmp_path):
    """#366 design C1: `cd` on an empty mktemp result succeeds, so the allocation must be checked."""
    bindir = _stub_bindir(tmp_path)
    fail = Path(bindir) / "mktemp"
    fail.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fail.chmod(0o755)
    plan = _build(_clean_agy_arbiter_profile(tmp_path))
    record = tmp_path / "refused.argv"
    code, _stderr = _run_stack(plan["arbiter"]["guard_stack"], bindir=bindir, record=record)
    assert code != 0
    assert not record.exists()                                            # agy never started


@_POSIX_SHELL
def test_stub_launch_eof_marker_needs_the_redirect(tmp_path):
    """CONTROL for the stdin assertion: without `< /dev/null` the stub never sees EOF."""
    plan = _build(_clean_agy_arbiter_profile(tmp_path))
    stack = plan["arbiter"]["guard_stack"]
    assert stack.endswith(" < /dev/null)")
    no_redirect = stack[: -len(" < /dev/null)")] + ")"
    no_redirect = no_redirect.replace("timeout 600 ", "timeout 2 ")
    assert "timeout 2 agy" in no_redirect
    record = tmp_path / "noredirect.argv"
    code, _stderr = _run_stack(no_redirect, bindir=_stub_bindir(tmp_path), record=record)
    assert code == 124                                                    # timeout(1) fired
    assert record.exists()                                                # the stub did start
    assert not (tmp_path / "noredirect.argv.eof").exists()


@_POSIX_SHELL
@pytest.mark.parametrize("builder", [_clean_agy_arbiter_profile, _codex_arbiter_profile])
def test_stub_launch_without_the_codex_freeze_serves_the_roster_top(tmp_path, seat_home, builder):
    """S081 WP-105 (design §7 row 5 / WP-A03): the WP-R07 stub launch re-run with the codex pin
    REMOVED from the fixture freeze (the agy pin kept, as WP-A03 leaves it). RE-POINTED by the astra
    reserve (roster rev 4): every avengers codex seat - member and arbiter - is the Sol literal, so the
    launch serves Sol with or without the codex freeze (F8), and never the roster TOP."""
    _write_pins(seat_home, {"agy": "gemini-4-argon-high"})
    plan = _build(builder(tmp_path))
    calls = _external_calls(plan)
    assert {c[1] for c in calls} == {"codex", "agy"}
    assert any(c[3] for c in calls)
    bindir = _stub_bindir(tmp_path)
    for n, (label, provider, effort, is_arbiter, stack) in enumerate(calls):
        record = tmp_path / f"nofreeze-{n}.argv"
        code, stderr = _run_stack(stack, bindir, record)
        assert code == 0, (label, stack, stderr)
        argv = record.read_text(encoding="utf-8").splitlines()
        assert _pinned_argv_problems(provider, argv) == [], (label, argv)
        assert (tmp_path / f"nofreeze-{n}.argv.eof").exists(), (label, "stdin never reached EOF")
        if provider == "codex":
            assert argv[argv.index("-m") + 1] == MEMBER
            assert f"model_reasoning_effort={effort}" in argv
            assert "--ephemeral" not in argv
            assert stack.startswith(_watched_codex_prefix(MEMBER, effort))
        else:
            level = "high" if is_arbiter else "medium"
            assert argv == ["--sandbox", "--mode", "plan", "--model", f"gemini-4-argon-{level}", "-p", _SENTINEL_PROMPT]
    # CONTROL: putting the codex pin back in the same HOME changes nothing on these seats (F8) ...
    _write_pins(seat_home)
    frozen = [c for c in _external_calls(_build(builder(tmp_path))) if c[1] == "codex"]
    assert frozen and all(f" -m {MEMBER} " in c[4] for c in frozen)
    # ... while it does move the TOP rows, through the same resolver.
    assert seat_model.resolve("escalation", "codex").model == "gpt-5.6-sol"


# =========================================================================== #
# S081 WP-F04 — astra unavailable -> PLAN-TIME Fable substitution of codex member seats
# (amendment 1 D6 + item 4 + item 7; plan J12, J16). Rollouts, rosters, pins and budget stores
# all live under the fixture HOME; `shutil.which("codex")` is answered by `codex_on_path`.
# =========================================================================== #
_FIXED_NOW = datetime(2026, 9, 15, 1, 0, tzinfo=timezone.utc)
_SUBSTITUTION_KEYS = ("substitute_for", "substitution_reason", "requested_model")
_GAP_LINE = "— provider gap: openai; arbiter recomputed"
# The key sets every plan / record carried before WP-F04 (read from the HEAD build, 2026-09-15).
_LEGACY_PLAN_KEYS = frozenset({
    "arbiter", "budgets", "caller", "capability_priors_sha256", "chair", "created_at", "depth",
    "evidence_policy", "family", "guard_policy", "interactive", "memory", "merge_provenance",
    "outcome_type", "overlay_policy", "phases_planned", "profile", "profile_path", "profile_sha256",
    "quorum", "schema", "seats", "served_by_policy", "session_id", "task", "task_family", "wall_clock_floor"})
_LEGACY_SEAT_KEYS = frozenset({
    "adversarial_role", "can_arbitrate", "effort", "effort_note", "fallback_ok", "guard_stack", "model",
    "overlay_type", "provider", "seat_class", "seat_id", "seat_model_role", "seat_weight", "timeout_s"})
_LEGACY_ARBITER_KEYS = frozenset({
    "cold_context", "constraint", "effort", "effort_note", "excluded_authorship", "fallback_arbiter_residual",
    "guard_stack", "is_external", "model", "path", "provider", "seat_class", "seat_model_role", "timeout_s"})
_LEGACY_RECORD_SEAT_KEYS = frozenset({"adversarial_role", "effort", "effort_note", "model", "provider", "seat_class", "seat_id"})
# #282 r14 (plan K16): every materialised member seat and the arbiter — in the plan and in the run record — carry
# ONE new key, `provenance`. The legacy sets above stay the pre-change record; assertions add this key explicitly.
_R14_KEYS = frozenset({"provenance"})


def _iso_ms(epoch):
    dt = datetime.fromtimestamp(epoch, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _write_rollout(home, primary, weekly, *, age=60.0, reached_type=None, name="fixture"):
    """One codex rollout reading in the live shape under the fixture HOME (codex_quota's real clock)."""
    observed = time.time() - age
    day_dir = home / ".codex" / "sessions" / datetime.fromtimestamp(observed, timezone.utc).strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    rate_limits = {
        "limit_id": "codex", "limit_name": None,
        "primary": {"used_percent": primary, "window_minutes": 300, "resets_at": int(observed + 7200)},
        "secondary": {"used_percent": weekly, "window_minutes": 10080, "resets_at": int(observed + 259200)},
        "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
        "individual_limit": None, "plan_type": "plus", "rate_limit_reached_type": reached_type,
    }
    event = {"timestamp": _iso_ms(observed), "type": "event_msg",
             "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 1, "output_tokens": 1}},
                         "rate_limits": rate_limits}}
    path = day_dir / f"rollout-2026-09-15T01-00-00-{name}.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    return path


def _clear_rollouts(home):
    shutil.rmtree(home / ".codex" / "sessions", ignore_errors=True)


# signal name -> (expected substitution_reason, setup(home, codex_on_path))
_SIGNALS = {
    "rate_limit_reached": ("rate_limit_reached", lambda h, c: _write_rollout(h, 10, 10, reached_type="primary")),
    "quota_exhausted_primary": ("quota_exhausted", lambda h, c: _write_rollout(h, 99, 10)),
    "quota_exhausted_weekly": ("quota_exhausted", lambda h, c: _write_rollout(h, 10, 99)),
    "cli_missing": ("cli_missing", lambda h, c: c.update(present=False)),
}


def _signal(name, home, codex_state):
    reason, setup = _SIGNALS[name]
    setup(home, codex_state)
    return reason


def _no_signal(home, codex_state):
    _clear_rollouts(home)
    codex_state["present"] = True


def _real_plan(profile, *, profiles_dir=_REAL_PROFILES):
    return convene.build_session_plan({"profile": profile, "task": "t"}, profiles_dir=profiles_dir,
                                      roster_dir=_REAL_ROSTER, session_id="wp-f04", now=_FIXED_NOW)


def _by_id(plan):
    return {s["seat_id"]: s for s in plan["seats"]}


def _store_rows(project):
    path = codex_quota.budget_path_for(project)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _codex_claude_profile(tmp_path):
    """codex skeptic (xhigh, adversarial) + codex builder (medium) + claude architect, NO card declares a fallback."""
    rdir, pdir = tmp_path / "roster-cc", tmp_path / "profiles-cc"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False, fallback_ok=False)
    _write_card(rdir, "builder", "codex", "medium", False, False, fallback_ok=False)
    _write_card(rdir, "architect", "claude", "default", False, False, fallback_ok=False)
    _write_profile(pdir, "cc", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "builder", "provider": "codex", "effort": "medium"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
    ])
    return {"profile": "cc"}, pdir, rdir


def test_substitution_vocabulary_matches_the_harness_owners():
    """Drift guard: every name convene writes is one codex_quota / seat_model accept."""
    assert convene.CODEX_CLI == seat_model.CODEX_CLI == "codex"
    assert convene.UNAVAILABLE_CLI_MISSING == seat_model.UNAVAILABLE_CLI_MISSING
    assert convene.UNAVAILABLE_NO_ELIGIBLE == seat_model.UNAVAILABLE_NO_ELIGIBLE
    assert convene.NoEligibleCodexModelError.unavailable_reason == seat_model.NoEligibleModelError.unavailable_reason
    for reason in (convene.UNAVAILABLE_CLI_MISSING, convene.UNAVAILABLE_NO_ELIGIBLE,
                   codex_quota.UNAVAILABLE_RATE_LIMIT_REACHED, codex_quota.UNAVAILABLE_QUOTA_EXHAUSTED):
        assert reason in codex_quota.SUBSTITUTION_REASONS
    assert convene.CODEX_SUBSTITUTION_USE in codex_quota.SUBSTITUTION_USES
    assert convene.CODEX_SUBSTITUTE_ROLE in codex_quota.SUBSTITUTION_ROLES
    # the astra reserve F1: substitution is gated on the budgeted ROLE, not on a TOP row
    assert convene.CODEX_SUBSTITUTE_ROLE in seat_model.ADMITTED_ROLES
    assert issubclass(convene.NoEligibleCodexModelError, convene.ConveneError)


def test_the_codex_cli_check_is_an_in_process_which_lookup(codex_on_path, monkeypatch):
    assert convene._codex_cli_missing() is False and codex_on_path["calls"] == 1
    codex_on_path["present"] = False
    assert convene._codex_cli_missing() is True and codex_on_path["calls"] == 2

    def refuse(*_a, **_k):
        raise AssertionError("the plan-time availability check spawned a process")
    for name in ("run", "Popen", "call", "check_output"):
        monkeypatch.setattr(subprocess, name, refuse)
    monkeypatch.setattr(os, "system", refuse)
    assert convene.codex_unavailable_reason() == "cli_missing"
    codex_on_path["present"] = True
    assert convene.codex_unavailable_reason() is None


def test_cli_missing_outranks_a_quota_token(seat_home, codex_on_path):
    _write_rollout(seat_home, 10, 10, reached_type="primary")
    assert convene.codex_unavailable_reason() == "rate_limit_reached"
    codex_on_path["present"] = False
    assert convene.codex_unavailable_reason() == "cli_missing"
    assert _by_id(_real_plan("coding-ratification"))["skeptic"]["substitution_reason"] == "cli_missing"


def test_one_availability_evaluation_per_plan_build(seat_home, codex_on_path, monkeypatch, tmp_path):
    calls = {"unavailable": 0}
    real_unavailable = convene._codex_quota.unavailable

    def spy(*args, **kwargs):
        calls["unavailable"] += 1
        return real_unavailable(*args, **kwargs)
    monkeypatch.setattr(convene._codex_quota, "unavailable", spy)
    fixture = _clean_agy_arbiter_profile(tmp_path)          # TWO codex seats
    for signal in (None, "rate_limit_reached"):
        if signal:
            _signal(signal, seat_home, codex_on_path)
        before_which, before_unavailable = codex_on_path["calls"], calls["unavailable"]
        _build(fixture)
        assert (codex_on_path["calls"] - before_which, calls["unavailable"] - before_unavailable) == (1, 1)
    # a plan with NO codex seat still evaluates once: its arbiter could have been codex
    before_which, before_unavailable = codex_on_path["calls"], calls["unavailable"]
    _floor_plan(tmp_path, "noCodex", [
        {"ref": "skeptic", "provider": "claude", "effort": "challenger_floor"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], cards=[("skeptic", "claude", "challenger_floor", True, False)])
    assert (codex_on_path["calls"] - before_which, calls["unavailable"] - before_unavailable) == (1, 1)


@pytest.mark.parametrize("signal", sorted(_SIGNALS))
def test_an_unavailable_codex_skeptic_is_re_seated_on_fable_in_coding_ratification(seat_home, codex_on_path, signal):
    control = _real_plan("coding-ratification")
    reason = _signal(signal, seat_home, codex_on_path)
    plan = _real_plan("coding-ratification")
    assert convene.schema_validate(plan, convene.load_schema()) == []
    seats, cseats = _by_id(plan), _by_id(control)
    sk = seats["skeptic"]
    assert (sk["provider"], sk["model"], sk["seat_model_role"], sk["timeout_s"], sk["seat_weight"]) == (
        "claude", MAIN, "consultant_main", 600, "main")
    assert (sk["adversarial_role"], sk["fallback_ok"]) == (True, True)
    assert (sk["substitute_for"], sk["substitution_reason"], sk["requested_model"]) == ("codex", reason, MEMBER)
    # effort re-resolved for claude through resolve_effort: the challenger floor keeps its anti-sycophancy note
    assert (sk["effort"], sk["seat_class"]) == ("default", "challenger_floor")
    assert "no codex-equivalent anti-sycophancy floor for this provider (claude)" in sk["effort_note"]
    assert sk["guard_stack"] == _claude_label(MAIN, "consultant_main", 600)
    # RE-POINTED at AMENDMENT 3 (D25): the operator is a CODEX seat now (sol), so it substitutes too
    # — a codex outage takes BOTH codex seats, which is the real cost of a two-codex-seat profile and
    # is asserted rather than hidden. The claude seats are still exactly the control's.
    op = seats["operator"]
    assert (op["provider"], op["model"], op["seat_model_role"], op["seat_weight"]) == (
        "claude", MAIN, "consultant_main", "support")
    assert (op["substitute_for"], op["substitution_reason"], op["requested_model"]) == (
        "codex", reason, CODEX_SUP)
    for sid in ("architect", "steward"):
        assert seats[sid] == cseats[sid]
    # arbiter recomputed without codex: claude holds the adversary now -> agy fallback
    assert (control["arbiter"]["provider"], cseats["skeptic"]["provider"]) == ("claude", "codex")
    assert cseats["operator"]["provider"] == "codex"
    arb = plan["arbiter"]
    # RE-POINTED at AMENDMENT 3: the path moved fallback -> CLEAN, because D25 took agy's seats away.
    # RE-POINTED AGAIN at #368: agy holds a seat again (the user-advocate), so it has deliberated and the
    # path is back to FALLBACK, residual flagged. The provider does not move: claude holds the adversary
    # and codex is excluded, so agy is the only non-adversarial provider left. It is still reachable only
    # because the session is DEGRADED — a healthy session bars it (ARBITER_INELIGIBLE_PROVIDERS).
    assert (arb["provider"], arb["path"], arb["model"], arb["seat_model_role"], arb["timeout_s"]) == (
        "agy", "fallback", "gemini-4-argon-high", "arbiter", 600)
    assert arb["fallback_arbiter_residual"] is True
    assert "unavailable at plan build, excluded from both paths: ['codex']" in arb["constraint"]
    # jc10 MADE VISIBLE, and RE-POINTED at #368. Under amendment 3 (no agy seat) both codex seats substituted
    # left ONE provider family and the quorum relaxed through the declared fallback ("a refused OpenAI arm
    # makes the session Claude-only"). With #368's agy seat the degraded session keeps TWO families
    # {agy, claude}, so the floor is met without relaxing; the OpenAI gap is still recorded (the review
    # line below) rather than hidden.
    assert (plan["quorum"]["provider_families"], plan["quorum"]["fallback_relaxed"]) == (["agy", "claude"], False)
    assert "(relaxed via declared fallback)" not in convene.render_pre_spend_review(plan)
    assert not any(str(s["model"]).startswith("gpt-") for s in plan["seats"]) and not arb["model"].startswith("gpt-")
    # run record: the substituted seat carries its provenance, the others keep the legacy key set (+ r14 provenance)
    record = convene.build_run_record(plan)
    assert convene.schema_validate(record, convene.load_run_record_schema()) == []
    rseats = {s["seat_id"]: s for s in record["staffing"]["seats"]}
    # #302 WP-1 / the astra reserve: the skeptic wanted the Sol literal (consultant_main); the operator
    # wanted the consultant_support row (the support tier).
    for sid, wanted in (("skeptic", MEMBER), ("operator", CODEX_SUP)):
        assert {k: rseats[sid][k] for k in _SUBSTITUTION_KEYS} == {
            "substitute_for": "codex", "substitution_reason": reason, "requested_model": wanted}
        assert (rseats[sid]["provider"], rseats[sid]["model"]) == ("claude", MAIN)
    assert all(set(rseats[sid]) == _LEGACY_RECORD_SEAT_KEYS | _R14_KEYS for sid in ("architect", "steward"))
    # the one review line, verbatim; absent from the control. Both substituted seats are listed on it,
    # in seat order — one line for the session, not one per seat.
    line = f"codex unavailable ({reason}): skeptic, operator served by claude/{MAIN} {_GAP_LINE}"
    review = convene.render_pre_spend_review(plan)
    assert line in review.splitlines()
    assert sum(1 for l in review.splitlines() if l.startswith("codex unavailable")) == 1
    assert "codex unavailable" not in convene.render_pre_spend_review(control)


def test_without_a_signal_the_plan_is_the_pre_change_plan(seat_home, codex_on_path):
    """CONTROL for every substitution test: no signal -> the legacy key sets, no substitution field, no review
    line, and a plan byte-equal whether or not a fresh-but-healthy or a STALE reached reading exists.
    (The stage also byte-compared these builds against the pre-change convene.py.)

    RE-POINTED (S081 revision 4, WP-D2), two changes and nothing deleted: (1) a codex member seat now carries
    ONE more key, `admission_id` (_D2_KEYS) — null here, because a bare build decides CHECK-ONLY; (2) the
    THRESHOLD reading (80, 20) left this "byte-equal" list because a threshold now substitutes (design §3.4):
    its assertion is INVERTED in test_a_threshold_now_substitutes_but_a_spent_consult_budget_never_does."""
    baseline = {p: _real_plan(p) for p in ("coding-ratification", "business-ideation")}
    for name, plan in baseline.items():
        assert set(plan) == _LEGACY_PLAN_KEYS                              # r14 adds no plan-level key; nor does D2
        assert all(set(s) == _LEGACY_SEAT_KEYS | _R14_KEYS | (_D2_KEYS if s["provider"] == "codex" else set())
                   for s in plan["seats"])
        # AMENDMENT 3: these profiles hold TWO codex seats now, so a bare build carries two null ids
        # (CHECK-ONLY decides nothing). The property is that NONE is recorded, not that there is one seat.
        assert set(s["admission_id"] for s in plan["seats"] if s["provider"] == "codex") == {None}
        assert [s["provider"] for s in plan["seats"]].count("codex") == 2
        # AMENDMENT 3: business-ideation declares its arbiter now, and a declared arbiter carries three
        # more keys (selection / independence / obligations). coding-ratification, still selected, does not.
        declared = {"selection", "independence", "obligations"} if convene.declared_arbiter(
            yaml.safe_load((_REAL_PROFILES / f"{name}.yaml").read_text(encoding="utf-8"))) else set()
        assert set(plan["arbiter"]) == _LEGACY_ARBITER_KEYS | _R14_KEYS | declared
        assert "unavailable at plan build" not in plan["arbiter"]["constraint"]
        assert "codex unavailable" not in convene.render_pre_spend_review(plan)
        record = convene.build_run_record(plan)
        assert all(set(s) == _LEGACY_RECORD_SEAT_KEYS | _R14_KEYS | (_D2_KEYS if s["provider"] == "codex" else set())
                   for s in record["staffing"]["seats"])
    assert baseline["coding-ratification"]["arbiter"]["provider"] == "claude"
    assert _by_id(baseline["business-ideation"])["architect"]["provider"] == "codex"
    for reading in ((10, 10, 60.0, None), (10, 10, 3 * 3600.0, "primary")):
        _clear_rollouts(seat_home)
        primary, weekly, age, reached = reading
        _write_rollout(seat_home, primary, weekly, age=age, reached_type=reached)
        assert codex_quota.unavailable() is None
        for name, plan in baseline.items():
            assert _real_plan(name) == plan, (name, reading)


def test_business_ideation_architect_is_re_seated_on_consultant_main_whatever_its_weight(seat_home, codex_on_path, tmp_path):
    control = _real_plan("business-ideation")
    _signal("rate_limit_reached", seat_home, codex_on_path)
    plan = _real_plan("business-ideation")
    assert convene.schema_validate(plan, convene.load_schema()) == []
    seats, cseats = _by_id(plan), _by_id(control)
    arch = seats["architect"]
    assert (arch["provider"], arch["model"], arch["seat_model_role"], arch["fallback_ok"], arch["adversarial_role"]) == (
        "claude", MAIN, "consultant_main", True, False)
    assert (arch["effort"], arch["seat_class"]) == ("default", "xhigh")
    assert arch["effort_note"] == "raw effort tier 'xhigh' has no claude-native equivalent; resolved to the unpinned tier 'default'"
    assert (arch["substitute_for"], arch["substitution_reason"], arch["requested_model"]) == (
        "codex", "rate_limit_reached", MEMBER)
    # AMENDMENT 3: the operator is a codex seat now, so it substitutes alongside the architect; only the
    # two claude seats are untouched.
    op = seats["operator"]
    assert (op["provider"], op["model"], op["seat_model_role"]) == ("claude", MAIN, "consultant_main")
    assert (op["substitute_for"], op["requested_model"]) == ("codex", CODEX_SUP)
    for sid in ("skeptic", "economist"):
        assert seats[sid] == cseats[sid]
    arb, carb = plan["arbiter"], control["arbiter"]
    # the DECLARED Opus arbiter is not recomputed by a substitution — a declaration is honoured or fails
    assert (arb["provider"], arb["path"], arb["model"]) == (carb["provider"], carb["path"], carb["model"]) == (
        "claude", "fallback", SUPPORT)
    assert (plan["budgets"]["wall_clock_s"], plan["wall_clock_floor"]["raised"]) == (5400, False)

    # seat_weight support is IGNORED for the substitute: still consultant_main (fable), never opus.
    doc = yaml.safe_load((_REAL_PROFILES / "business-ideation.yaml").read_text(encoding="utf-8"))
    {s["ref"]: s for s in doc["seats"]}["architect"]["seat_weight"] = "support"
    pdir = tmp_path / "profiles-support-architect"
    pdir.mkdir()
    (pdir / "business-ideation.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    weighted = _by_id(_real_plan("business-ideation", profiles_dir=pdir))
    assert (weighted["architect"]["seat_weight"], weighted["architect"]["seat_model_role"], weighted["architect"]["model"]) == (
        "support", "consultant_main", MAIN)
    # CONTROL: the override is observable against an ordinary support-weight claude seat -> opus. AMENDMENT
    # 3 moved business-ideation's economist to `main` (D26), so the control reads the STEWARD-shaped seat in
    # coding-ratification instead, which still carries the default support weight.
    assert (weighted["economist"]["seat_model_role"], weighted["economist"]["model"]) == ("consultant_main", MAIN)
    steward = _by_id(_real_plan("coding-ratification"))["steward"]
    assert (steward["seat_weight"], steward["seat_model_role"], steward["model"]) == (
        "support", "consultant_support", SUPPORT)
    _no_signal(seat_home, codex_on_path)
    unsub = _by_id(_real_plan("business-ideation", profiles_dir=pdir))["architect"]
    assert (unsub["provider"], unsub["seat_weight"], unsub["model"]) == ("codex", "support", CODEX_SUP)


def test_a_codex_and_claude_profile_relaxes_through_the_substitutes_declared_fallback(seat_home, codex_on_path, tmp_path, monkeypatch):
    fixture = _codex_claude_profile(tmp_path)
    control = _build(fixture)
    assert (control["quorum"]["provider_families"], control["quorum"]["fallback_relaxed"]) == (["claude", "codex"], False)
    _signal("rate_limit_reached", seat_home, codex_on_path)
    plan = _build(fixture)
    assert (plan["quorum"]["provider_families"], plan["quorum"]["families_count"], plan["quorum"]["fallback_relaxed"]) == (
        ["claude"], 1, True)
    seats = _by_id(plan)
    assert [(seats[s]["provider"], seats[s]["model"], seats[s]["fallback_ok"]) for s in ("skeptic", "builder")] == [
        ("claude", MAIN, True)] * 2
    assert seats["architect"]["fallback_ok"] is False                     # the only declared fallback is the substitutes'
    assert (seats["builder"]["effort"], seats["builder"]["seat_class"]) == ("default", "medium")
    assert (plan["arbiter"]["provider"], plan["arbiter"]["path"]) == ("agy", "clean")
    assert convene.schema_validate(plan, convene.load_schema()) == []
    assert convene.schema_validate(convene.build_run_record(plan), convene.load_run_record_schema()) == []
    assert (f"codex unavailable (rate_limit_reached): skeptic, builder served by claude/{MAIN} {_GAP_LINE}"
            in convene.render_pre_spend_review(plan).splitlines())
    # MUTANT CONTROL: the same substitution WITHOUT the declared fallback is a sub-quorum.
    real = convene.apply_codex_substitution

    # SIGNATURE ADAPTED (S081 revision 4, WP-D2): the builder now passes the plan-time admission as keywords,
    # which the mutant forwards unchanged. The mutation itself — the declared fallback stripped — is untouched.
    def without_fallback(seats_, reason, **kwargs):
        result = real(seats_, reason, **kwargs)
        for s in seats_:
            if s.get("substitute_for"):
                s["fallback_ok"] = False
        return result
    monkeypatch.setattr(convene, "apply_codex_substitution", without_fallback)
    with pytest.raises(convene.ConveneError) as e:
        _build(fixture)
    assert "provider family" in str(e.value)


def test_no_eligible_model_substitutes_only_the_seat_whose_effort_has_none(seat_home, codex_on_path, tmp_path, capsys):
    # RE-POINTED by the astra reserve (roster rev 4): the `main` codex member is the Sol LITERAL, so "no
    # eligible model" is a roster that does not serve Sol at the seat's effort (seat_model F1: a budgeted
    # literal that codex cannot serve is substitutable, like a TOP seat with no eligible TOP).
    _write_pins(seat_home, {"agy": "gemini-4-argon-high"})              # codex freeze removed: roster path
    # (a) Sol lacks xhigh: the xhigh skeptic has no eligible model, the medium builder does
    _write_codex_roster(seat_home, [_entry(MEMBER, 2, efforts=("low", "medium")), _entry(CODEX_SUP, 7)])
    assert convene.codex_unavailable_reason() is None                      # NOT a plan-wide signal
    plan = _build(_clean_agy_arbiter_profile(tmp_path))
    seats = _by_id(plan)
    assert (seats["skeptic"]["provider"], seats["skeptic"]["model"]) == ("claude", MAIN)
    assert (seats["skeptic"]["substitution_reason"], seats["skeptic"]["requested_model"]) == ("no_eligible_model", None)
    assert (seats["builder"]["provider"], seats["builder"]["model"]) == ("codex", MEMBER)
    assert all(k not in seats["builder"] for k in _SUBSTITUTION_KEYS)
    # AMENDMENT 3: this fixture DECLARES its arbiter, and a declared arbiter never runs the exclusion
    # algorithm, so its constraint states the relaxed rule instead of the exclusion note. The note itself is
    # still pinned, on a SELECTED arbiter, in test_the_arbiter_excludes_unavailable_providers_on_both_paths.
    assert "arbiter_independence: separate-session" in plan["arbiter"]["constraint"]
    assert plan["arbiter"]["selection"] == "declared"
    assert (f"codex unavailable (no_eligible_model): skeptic served by claude/{MAIN} {_GAP_LINE}"
            in convene.render_pre_spend_review(plan).splitlines())
    # (b) a roster that does not list Sol at all: the real coding-ratification skeptic substitutes; the
    # persisted row has no requested model
    _write_codex_roster(seat_home, [_entry(slug, prio, visibility="hide")
                                    for slug, prio in (("gpt-6-astra", 1), (CODEX_SUP, 4), ("gpt-5.5", 12))])
    cr = _real_plan("coding-ratification")
    sk = _by_id(cr)["skeptic"]
    assert (sk["provider"], sk["substitution_reason"], sk["requested_model"]) == ("claude", "no_eligible_model", None)
    assert cr["arbiter"]["provider"] == "agy"
    project = tmp_path / "proj-no-eligible"
    project.mkdir()
    assert convene.main(["--profile", "coding-ratification", "--task", "t", "--profiles-dir", str(_REAL_PROFILES),
                         "--roster-dir", str(_REAL_ROSTER), "--project-root", str(project), "--session-id", "ne"]) == 0
    # AMENDMENT 3: coding-ratification holds TWO codex seats, so the store carries an ADMISSION row for the
    # surviving support seat beside the skeptic's substitution row. Filter to the substitution rows.
    rows = [r for r in _store_rows(project) if r.get("kind") == "substitution"]
    assert [(r["kind"], r["reason"], r["requested_model"], r["served_model"]) for r in rows] == [
        ("substitution", "no_eligible_model", None, MAIN)]
    capsys.readouterr()
    # CONTROL: NO roster at all is the sanctioned harness literal (the Sol slug itself), never a substitution
    (seat_home / ".codex" / "models_cache.json").unlink()
    literal = _by_id(_real_plan("coding-ratification"))["skeptic"]
    assert (literal["provider"], literal["model"]) == ("codex", MEMBER)
    assert all(k not in literal for k in _SUBSTITUTION_KEYS)


# RE-POINTED by the astra reserve (F8): a codex freeze no longer reaches any avengers codex seat (all are
# literals), so the broken resolver is planted in the ROSTER the literals are validated against instead.
@pytest.mark.parametrize("pins_raw,needle", [
    ("ROSTER_INVALID", "roster_invalid"),
    ("ROSTER_JUNK_SHAPE", "roster_invalid"),
])
@pytest.mark.parametrize("signal", ["rate_limit_reached", "cli_missing"])
def test_a_broken_resolver_is_a_convene_error_never_a_substitution(seat_home, codex_on_path, capsys, tmp_path,
                                                                    pins_raw, needle, signal):
    _signal(signal, seat_home, codex_on_path)
    if pins_raw == "ROSTER_JUNK_SHAPE":
        _invalid_codex_roster(seat_home)
    else:
        (seat_home / ".codex" / "models_cache.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(convene.ConveneError) as e:
        _real_plan("coding-ratification")
    assert needle in str(e.value) and not isinstance(e.value, convene.NoEligibleCodexModelError)
    project = tmp_path / "proj-broken"
    project.mkdir()
    rc = convene.main(["--profile", "coding-ratification", "--task", "t", "--profiles-dir", str(_REAL_PROFILES),
                       "--roster-dir", str(_REAL_ROSTER), "--project-root", str(project)])
    out = capsys.readouterr()
    assert rc == 2 and "CONVENE FAIL-CLOSED" in out.err and "codex unavailable" not in out.out
    assert not codex_quota.budget_path_for(project).exists() and not (project / ".avengers").exists()
    # CONTROL: a valid roster under the same signal substitutes
    _write_codex_roster(seat_home)
    assert _by_id(_real_plan("coding-ratification"))["skeptic"]["provider"] == "claude"


# RE-POINTED at AMENDMENT 3 (D25): research-synthesis is the ONLY profile that still seats agy, so it
# is the only one whose agy seats can be compared. The other four are covered by the no-agy control
# test_a3_research_synthesis_is_the_only_profile_that_seats_agy, which fails if agy reappears anywhere.
@pytest.mark.parametrize("profile", ["research-synthesis"])
def test_agy_seats_are_identical_with_and_without_the_codex_signal(seat_home, codex_on_path, profile):
    control = _real_plan(profile)
    _signal("rate_limit_reached", seat_home, codex_on_path)
    plan = _real_plan(profile)
    agy, cagy = [s for s in plan["seats"] if s["provider"] == "agy"], [s for s in control["seats"] if s["provider"] == "agy"]
    assert agy and agy == cagy
    assert any(s.get("substitute_for") for s in plan["seats"])              # the signal did act on this profile


@pytest.mark.parametrize("freeze", ["sol", "none"])
@pytest.mark.parametrize("signal", ["rate_limit_reached", "cli_missing"])
def test_sol_never_serves_a_substituted_seat_or_the_arbiter(seat_home, codex_on_path, tmp_path, freeze, signal):
    _write_pins(seat_home, None if freeze == "sol" else {"agy": "gemini-4-argon-high"})
    builders = {
        "coding-ratification": lambda: _real_plan("coding-ratification"),
        "business-ideation": lambda: _real_plan("business-ideation"),
        "agyarb": lambda: _build(_clean_agy_arbiter_profile(tmp_path)),
        "weighted": lambda: _build(_weighted_profile(tmp_path)),
        "codex-claude": lambda: _build(_codex_claude_profile(tmp_path)),
    }
    expected_codex = MEMBER          # the astra reserve: the Sol literal, freeze or not (F8)
    for name, build in builders.items():
        _no_signal(seat_home, codex_on_path)
        control = build()
        # CONTROL: this fixture really would have served a gpt model to a codex seat
        assert any(s["provider"] == "codex" and s["model"] == expected_codex for s in control["seats"]), name
        _signal(signal, seat_home, codex_on_path)
        plan = build()
        models = [s["model"] for s in plan["seats"]] + [plan["arbiter"]["model"]]
        assert not any(str(m).lower().startswith("gpt-") for m in models), (name, models)
        assert all(s["provider"] != "codex" for s in plan["seats"]) and plan["arbiter"]["provider"] != "codex"
        assert not any("codex exec" in s["guard_stack"] for s in plan["seats"] + [plan["arbiter"]])
        # RE-POINTED at AMENDMENT 3: `requested_model` is what a substituted seat WANTED, and a profile
        # with two codex classes wants BOTH. What this test guards is unchanged and asserted below —
        # sol never SERVES a substituted seat (they are all claude/fable) nor the arbiter.
        wanted = {s["requested_model"] for s in plan["seats"] if s.get("substitute_for")}
        assert wanted <= {expected_codex, CODEX_SUP} and expected_codex in wanted


def test_a_gpt_substitute_model_fails_closed(seat_home, codex_on_path, monkeypatch):
    _signal("rate_limit_reached", seat_home, codex_on_path)
    real_resolve = seat_model.resolve

    def poisoned(role, provider, **kwargs):
        pin = real_resolve(role, provider, **kwargs)
        if provider == "claude" and role == convene.CODEX_SUBSTITUTE_ROLE:
            return seat_model.SeatPin(model="gpt-5.6-sol", effort=None, timeout=pin.timeout,
                                      argv_fragment=("--model", "gpt-5.6-sol"), provenance=dict(pin.provenance))
        return pin
    monkeypatch.setattr(convene._seat_model, "resolve", poisoned)
    with pytest.raises(convene.ConveneError) as e:
        _real_plan("coding-ratification")
    assert "refusing to substitute codex with 'gpt-5.6-sol'" in str(e.value)


def test_322_a_high_reading_no_longer_substitutes_and_a_spent_consult_budget_never_does(seat_home, codex_on_path,
                                                                                         tmp_path, capsys):
    """INVERTED AGAIN AND RENAMED by #322 (was test_a_threshold_now_substitutes_but_a_spent_consult_budget_never_does):
    the 70 % threshold no longer refuses, so an 80 % reading keeps the codex skeptic. History below.

    RE-POINTED AND RENAMED (S081 revision 4, WP-D2; was test_threshold_and_a_spent_budget_never_substitute).

    It pinned J16 / I11 — "avengers seats are not admit-gated; only UNAVAILABILITY substitutes" — which is
    the gap WP-D2 exists to close (design §3.4). The THRESHOLD half is INVERTED: a fresh >= 70 % reading now
    substitutes through the plan-time admission. The spent-CONSULT half is KEPT UNCHANGED, and is now the
    control: the seat's budget is its SESSION's `deliberation` slot (plan L9), so a forge cycle's spent
    `consult` budget is a different key AND a different use and still substitutes nothing."""
    _freeze_codex_on_std(seat_home)          # #302 WP-1: the subject needs ONE std class (see helper)
    baseline = _real_plan("coding-ratification")
    project = tmp_path / "proj-threshold"
    project.mkdir()
    cycle = codex_quota.cycle_id_for(project)
    _write_rollout(seat_home, 80, 20)
    assert codex_quota.unavailable() is None
    assert codex_quota.admit("consult", cycle, project_root=project, record=False)["reason"] == "within_budget"
    # #322: the same reading no longer substitutes: the skeptic stays on codex, exactly as the baseline
    sk = _by_id(_real_plan("coding-ratification"))["skeptic"]
    assert sk["provider"] == "codex" and "substitute_for" not in sk
    assert _by_id(baseline)["skeptic"]["provider"] == "codex"                                     # CONTROL
    # KEPT: a spent consult budget in the same cycle
    _clear_rollouts(seat_home)
    _write_rollout(seat_home, 10, 10)
    assert codex_quota.admit("consult", cycle, project_root=project)["admitted"] is True
    assert codex_quota.admit("consult", cycle, project_root=project)["reason"] == "budget_spent"
    rows_before = _store_rows(project)
    assert convene.main(["--profile", "coding-ratification", "--task", "t", "--profiles-dir", str(_REAL_PROFILES),
                         "--roster-dir", str(_REAL_ROSTER), "--project-root", str(project), "--session-id", "spent"]) == 0
    assert "astra substitutions" not in capsys.readouterr().out
    # RE-POINTED (was "nothing appended"): exactly the session's OWN admission is appended, on its own key
    rows_after = _store_rows(project)
    assert rows_after[:len(rows_before)] == rows_before
    assert [(r["key"], r["use"], r["admitted"], r["reason"]) for r in rows_after[len(rows_before):]] == [
        ("spent", "deliberation", True, "within_budget")]
    written = json.loads((project / ".avengers" / "sessions" / "spent" / "session-plan.json").read_text(encoding="utf-8"))
    assert _by_id(written)["skeptic"]["provider"] == "codex"


def _arb_seat(provider, adversarial):
    return {"seat_id": f"{provider}-{int(adversarial)}", "provider": provider, "adversarial_role": adversarial}


def test_the_arbiter_excludes_unavailable_providers_on_both_paths():
    ratify = {"is_ratification": True}
    # CLEAN path: codex is the only provider no seat used
    clean_seats = [_arb_seat("claude", True), _arb_seat("agy", False)]
    assert convene.resolve_arbiter({}, clean_seats, **ratify)["provider"] == "codex"
    arb = convene.resolve_arbiter({}, clean_seats, unavailable_providers={"codex"}, **ratify)
    assert (arb["provider"], arb["path"]) == ("agy", "fallback")
    assert arb["constraint"].endswith("excluded from both paths: ['codex']") and "all available providers deliberated" in arb["constraint"]
    # FALLBACK path: codex is the only non-adversarial provider -> nothing remains -> fail closed
    fallback_seats = [_arb_seat("codex", False), _arb_seat("claude", True), _arb_seat("agy", True)]
    assert convene.resolve_arbiter({}, fallback_seats, **ratify)["provider"] == "codex"
    with pytest.raises(convene.ConveneError) as e:
        convene.resolve_arbiter({}, fallback_seats, unavailable_providers=frozenset({"codex"}), **ratify)
    assert "arbiter constraint unsatisfiable" in str(e.value) and "unavailable ['codex']" in str(e.value)
    # CONTROL: the keyword is generic and its default is HEAD's selection, byte for byte
    two = [_arb_seat("codex", True), _arb_seat("claude", False)]
    # RE-POINTED at AMENDMENT 3 (D25): agy is barred from a HEALTHY session's arbiter, so a two-provider
    # team no longer lands on it; the non-adversarial claude takes it on the fallback path instead.
    assert convene.resolve_arbiter({}, two, **ratify)["provider"] == "claude"
    assert convene.resolve_arbiter({}, two, unavailable_providers=["agy"], **ratify)["provider"] == "claude"
    for empty in (None, (), frozenset()):
        assert convene.resolve_arbiter({}, two, unavailable_providers=empty, **ratify) == convene.resolve_arbiter({}, two, **ratify)
    with pytest.raises(convene.ConveneError) as e:
        convene.resolve_arbiter({}, two, unavailable_providers={"gemini"}, **ratify)
    assert "unknown provider" in str(e.value)


def test_an_all_adversarial_remainder_fails_closed_after_substitution(seat_home, codex_on_path, tmp_path):
    fixture = _codex_arbiter_profile(tmp_path)
    assert _build(fixture)["arbiter"]["provider"] == "codex"               # CONTROL
    _signal("rate_limit_reached", seat_home, codex_on_path)
    with pytest.raises(convene.ConveneError) as e:
        _build(fixture)
    assert "arbiter constraint unsatisfiable" in str(e.value)


def test_substitution_happens_before_the_structural_validate_and_the_arbiter(seat_home, codex_on_path, monkeypatch):
    seen = {}
    real_validate, real_arbiter = convene.validate_structural, convene.resolve_arbiter

    def validate_spy(seats):
        seen["validate"] = {s["seat_id"]: s["provider"] for s in seats}
        return real_validate(seats)

    def arbiter_spy(profile, seats, **kwargs):
        seen["arbiter"] = ({s["seat_id"]: s["provider"] for s in seats}, frozenset(kwargs.get("unavailable_providers") or ()))
        return real_arbiter(profile, seats, **kwargs)
    monkeypatch.setattr(convene, "validate_structural", validate_spy)
    monkeypatch.setattr(convene, "resolve_arbiter", arbiter_spy)
    _real_plan("coding-ratification")
    assert seen["validate"]["skeptic"] == "codex" and seen["arbiter"][1] == frozenset()      # CONTROL
    _signal("rate_limit_reached", seat_home, codex_on_path)
    _real_plan("coding-ratification")
    assert seen["validate"]["skeptic"] == "claude"
    assert seen["arbiter"] == (seen["validate"], frozenset({"codex"}))


def test_seat_role_for_accepts_only_a_claude_member_substituting_codex():
    for weight in ("main", "support", None):
        assert convene.seat_role_for("claude", is_arbiter=False, seat_weight=weight, substitute_for="codex") == "consultant_main"
    for provider, is_arbiter, substitute_for in (("codex", False, "codex"), ("agy", False, "codex"),
                                                 ("claude", True, "codex"), ("claude", False, "agy")):
        with pytest.raises(convene.ConveneError) as e:
            convene.seat_role_for(provider, is_arbiter=is_arbiter, substitute_for=substitute_for)
        assert "illegal substitution" in str(e.value)
    # CONTROL: without the substitution a support-weight claude member is consultant_support
    assert convene.seat_role_for("claude", is_arbiter=False, seat_weight="support") == "consultant_support"


def test_both_schemas_accept_the_optional_substitution_fields(seat_home, codex_on_path):
    _signal("rate_limit_reached", seat_home, codex_on_path)
    plan = _real_plan("coding-ratification")
    record = convene.build_run_record(plan)
    schema, rr_schema = convene.load_schema(), convene.load_run_record_schema()
    for doc, sch, seats_of in ((plan, schema, lambda d: d["seats"]), (record, rr_schema, lambda d: d["staffing"]["seats"])):
        assert convene.schema_validate(doc, sch) == []
        props = sch["properties"]["seats"]["items"]["properties"] if sch is schema else \
            sch["properties"]["staffing"]["properties"]["seats"]["items"]["properties"]
        assert all(k in props for k in _SUBSTITUTION_KEYS)
        # OPTIONAL: an in-flight document without them validates, and a null requested model is legal
        legacy = copy.deepcopy(doc)
        for s in seats_of(legacy):
            for k in _SUBSTITUTION_KEYS:
                s.pop(k, None)
        assert convene.schema_validate(legacy, sch) == []
        nulled = copy.deepcopy(doc)
        next(s for s in seats_of(nulled) if s.get("substitute_for"))["requested_model"] = None
        assert convene.schema_validate(nulled, sch) == []
        # CONTROL: the fields are typed
        for key, bad, needle in (("substitute_for", "agy", "enum"), ("substitution_reason", 7, "expected type"),
                                 ("requested_model", 7, "expected type")):
            typed = copy.deepcopy(doc)
            next(s for s in seats_of(typed) if s.get("substitute_for"))[key] = bad
            assert any(f".{key}" in err and needle in err for err in convene.schema_validate(typed, sch)), key


def test_dry_run_writes_no_budget_store_and_the_persisted_path_writes_one_row_per_seat(seat_home, codex_on_path, tmp_path, capsys):
    _signal("rate_limit_reached", seat_home, codex_on_path)
    project = tmp_path / "proj"
    project.mkdir()
    store = codex_quota.budget_path_for(project)
    assert seat_home in store.parents and not store.exists()
    fixture = _clean_agy_arbiter_profile(tmp_path)
    contract, pdir, rdir = fixture
    plan = _build(fixture)                                                   # build_session_plan is pure
    assert len([s for s in plan["seats"] if s.get("substitute_for")]) == 2
    assert list(seat_home.rglob("astra-budget.jsonl")) == []                 # no store for ANY project key
    common = ["--profile", "agyarb", "--profiles-dir", str(pdir), "--roster-dir", str(rdir), "--project-root", str(project)]
    assert convene.main(common + ["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"codex unavailable (rate_limit_reached): skeptic, builder served by claude/{MAIN} {_GAP_LINE}" in out.splitlines()
    assert list(seat_home.rglob("astra-budget.jsonl")) == [] and not (project / ".avengers").exists()
    # persisted: exactly one `deliberation` substitution row per substituted seat, in --project-root's store.
    # RE-POINTED (S081 revision 4, WP-D2; plan L9, design §2.2): the rows now key on the SESSION id — the key
    # the seat's admission uses — not on .forge/cycle-id. The forge cycle id below is KEPT as the control that
    # proves it no longer captures the key (was: cycle_id "wp-f04-cycle", source "cycle-id"). A plan-wide
    # signal substitutes BEFORE any admission, so these rows are still the only ones and name no admission.
    (project / ".forge").mkdir()
    (project / ".forge" / "cycle-id").write_text("wp-f04-cycle\n", encoding="utf-8")
    assert convene.main(common + ["--session-id", "persisted"]) == 0
    out = capsys.readouterr().out
    assert "astra substitutions recorded: 2 of 2 (use deliberation; provider gap: openai)" in out
    assert list(seat_home.rglob("astra-budget.jsonl")) == [store]            # only --project-root's store
    rows = _store_rows(project)
    assert len(rows) == 2 and all("admitted" not in r for r in rows)
    assert [(r["kind"], r["use"], r["role"], r["substitute_for"], r["served_model"], r["requested_model"], r["reason"],
             r["cycle_id"], r["cycle_id_source"], r["admission_id"]) for r in rows] == [
        ("substitution", "deliberation", "consultant_main", "codex", MAIN, MEMBER, "rate_limit_reached",
         "persisted", "explicit", None)] * 2
    session = project / ".avengers" / "sessions" / "persisted"
    written = json.loads((session / "session-plan.json").read_text(encoding="utf-8"))
    record = json.loads((session / "run-record.json").read_text(encoding="utf-8"))
    assert {s["seat_id"] for s in written["seats"] if s.get("substitute_for")} == {"skeptic", "builder"}
    assert {s["seat_id"] for s in record["staffing"]["seats"] if s.get("substitute_for")} == {"skeptic", "builder"}
    # CONTROL: no signal -> the persisted path prints no substitution line and writes NO substitution row.
    # RE-POINTED (S081 revision 4, WP-D2; was "writes no store"): it now records the session's ONE admission —
    # both codex seats share it — and nothing else.
    _no_signal(seat_home, codex_on_path)
    other = tmp_path / "proj-control"
    other.mkdir()
    assert convene.main(["--profile", "agyarb", "--profiles-dir", str(pdir), "--roster-dir", str(rdir),
                         "--project-root", str(other), "--session-id", "control"]) == 0
    assert "astra substitutions" not in capsys.readouterr().out
    assert [(r.get("kind"), r["use"], r["key"], r["admitted"]) for r in _store_rows(other)] == [
        (None, "deliberation", "control", True)]


def test_a_substitution_row_that_cannot_be_written_never_blocks_the_session(seat_home, codex_on_path, tmp_path, capsys, monkeypatch):
    _signal("rate_limit_reached", seat_home, codex_on_path)
    args = ["--profile", "coding-ratification", "--task", "t", "--profiles-dir", str(_REAL_PROFILES),
            "--roster-dir", str(_REAL_ROSTER)]
    with monkeypatch.context() as m:
        def boom(*_a, **_k):
            raise seat_model.SeatModelError("boom")
        m.setattr(convene._seat_model, "substitute", boom)
        project = tmp_path / "p-raise"
        project.mkdir()
        assert convene.main(args + ["--project-root", str(project), "--session-id", "r"]) == 0
        out = capsys.readouterr()
        assert (project / ".avengers" / "sessions" / "r" / "session-plan.json").exists()
        # AMENDMENT 3: coding-ratification holds TWO codex seats, so a session that substitutes both
        # reports 0 of 2 recorded when the recorder raises.
        assert "astra substitutions recorded: 0 of 2" in out.out
        assert "substitution row NOT recorded for seat skeptic: SeatModelError: boom" in out.err
    with monkeypatch.context() as m:
        m.setattr(codex_quota, "record_substitution", lambda *a, **k: {"row_written": False, "error": "disk full"})
        project = tmp_path / "p-store"
        project.mkdir()
        assert convene.main(args + ["--project-root", str(project), "--session-id", "s"]) == 0
        out = capsys.readouterr()
        # AMENDMENT 3: coding-ratification holds TWO codex seats, so both substitute and both rows fail.
        assert "astra substitutions recorded: 0 of 2" in out.out and "disk full" in out.err
    # CONTROL: the real owner records the row
    project = tmp_path / "p-ok"
    project.mkdir()
    assert convene.main(args + ["--project-root", str(project), "--session-id", "o"]) == 0
    # AMENDMENT 3: both codex seats substitute, so both rows are recorded.
    assert "astra substitutions recorded: 2 of 2" in capsys.readouterr().out
    assert len(_store_rows(project)) == 2


def test_plan_build_under_a_signal_spawns_no_process_and_opens_no_socket(seat_home, codex_on_path, monkeypatch):
    _signal("rate_limit_reached", seat_home, codex_on_path)
    import socket

    def refuse(*_a, **_k):
        raise AssertionError("plan build spawned a process or opened a socket")
    for name in ("run", "Popen", "call", "check_output"):
        monkeypatch.setattr(subprocess, name, refuse)
    monkeypatch.setattr(os, "system", refuse)
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    plan = _real_plan("coding-ratification")
    assert _by_id(plan)["skeptic"]["substitute_for"] == "codex"
    convene.render_pre_spend_review(plan)
    convene.build_run_record(plan)


# WP-D2 resume (plan revision 35): this test asks only for the SUBSTRING "admit-gated", which a stale
# "not admit-gated" also supplies. The stale-claim guard for convene-contract.md is
# test_d2_the_contract_doc_states_the_plan_time_admission_and_none_of_the_retired_i11_claims.
def test_the_docs_quote_the_review_line_verbatim(seat_home, codex_on_path):
    _signal("rate_limit_reached", seat_home, codex_on_path)
    line = convene.codex_substitution_review_line(_real_plan("coding-ratification"))
    # AMENDMENT 3: coding-ratification holds TWO codex seats, so the ONE review line names both, in seat
    # order. Still one line per session, which is the property the docs quote.
    assert line == f"codex unavailable (rate_limit_reached): skeptic, operator served by claude/{MAIN} {_GAP_LINE}"
    # #291 WP-6: the docs name TIERS, not models (design s3.8), so a doc may quote the line with the
    # served model written as its tier, `claude/<Claude main tier>`; the literal line with today's main
    # model is accepted too. A doc still quoting a model the roster no longer serves matches neither.
    tiered = line.replace(f"claude/{MAIN}", f"claude/<{_TIER_NAME[MAIN]}>")
    assert tiered != line                                                  # CONTROL: the templating bit
    for doc in (_AVENGERS_ROOT / "SKILL.md", _AVENGERS_ROOT / "references" / "convene-contract.md"):
        text = doc.read_text(encoding="utf-8")
        assert line in text or tiered in text, doc.name
        assert "mid-session" in text and "admit-gated" in text, doc.name


# =========================================================================== #
# #282 R4 + R8 (plan K14, K15) — the codex roster's three states in convene
#
#   absent       harness-literal codex seats / arbiter (sanctioned; the pin's provenance says so)
#   invalid      ConveneError naming roster_invalid, for member seats and the arbiter alike
#   no_eligible  a member seat -> the existing substitution; the ARBITER -> codex joins the
#                excluded providers and the selection is recomputed ONCE (clean, then fallback)
#
# R8 fixtures have NO codex member seat, so nothing at plan build evaluates the codex roster before
# the arbiter does: the clean path picks codex (the only provider no seat used), and before R8 an
# all-hidden roster turned that into NoEligibleCodexModelError out of build_session_plan.
# =========================================================================== #
_ALL_HIDDEN_CODEX = [_entry(slug, prio, visibility="hide")
                     for slug, prio in (("gpt-6-astra", 1), ("gpt-5.6-sol", 4), ("gpt-5.5", 12))]


def _r8_profile(tmp_path, family, *, claude_adversarial, agy_adversarial):
    """Three member seats, NO codex seat: two claude, one agy. Ratification semantics (arbiter @ max)."""
    rdir, pdir = tmp_path / f"roster-{family}", tmp_path / f"profiles-{family}"
    _write_card(rdir, "architect", "claude", "default", claude_adversarial, False)
    _write_card(rdir, "reviewer", "claude", "default", False, False)
    _write_card(rdir, "operator", "agy", "default", agy_adversarial, False)
    _write_profile(pdir, family, [{"ref": "architect"}, {"ref": "reviewer"}, {"ref": "operator"}])
    return {"profile": family, "task": "r8"}, pdir, rdir


def _r8_fixture_a(tmp_path):
    """Claude non-adversarial, agy adversarial -> after the codex exclusion only claude remains."""
    return _r8_profile(tmp_path, "r8a", claude_adversarial=False, agy_adversarial=True)


def _r8_fixture_b(tmp_path):
    """Claude adversarial, agy non-adversarial -> after the codex exclusion only agy remains."""
    return _r8_profile(tmp_path, "r8b", claude_adversarial=True, agy_adversarial=False)


def _no_codex_freeze(home):
    _write_pins(home, {"agy": "gemini-4-argon-high"})


def _freeze_codex_on_std(home):
    """#302 WP-1: the fixture freeze held on THE STD MODEL rather than on the literal stream-3 slug.
    For the tests whose subject is that a frozen TOP seat is billed in the `std` class (and so shares
    one admission with a supporting seat): that holds exactly when the freeze names the std model,
    so the freeze reads the tier instead of assuming gpt-5.6-sol is it."""
    _write_pins(home, {"codex": STD, "agy": "gemini-4-argon-high"})


def _invalid_codex_roster(home):
    entries = _live_like_codex_entries()
    entries[0]["supported_reasoning_levels"] = True
    _write_codex_roster(home, entries)


def _arbiter_call_spy(monkeypatch):
    calls = []
    real = convene.materialise_call

    def spy(provider, effort, **kwargs):
        if kwargs.get("is_arbiter"):
            calls.append((provider, effort))
        return real(provider, effort, **kwargs)
    monkeypatch.setattr(convene, "materialise_call", spy)
    return calls


def test_r8_a_no_eligible_codex_arbiter_is_excluded_and_the_claude_fallback_serves(seat_home, codex_on_path, tmp_path,
                                                                                  monkeypatch, capsys):
    _no_codex_freeze(seat_home)
    fixture = _r8_fixture_a(tmp_path)
    # CONTROL: a valid roster -> the clean path really picks a codex arbiter (Sol @ max: the astra reserve) on this fixture
    control = _build(fixture)
    assert (control["arbiter"]["provider"], control["arbiter"]["path"], control["arbiter"]["model"],
            control["arbiter"]["effort"]) == ("codex", "clean", MEMBER, "max")
    assert "recomputed" not in control["arbiter"]["constraint"]
    _write_codex_roster(seat_home, _ALL_HIDDEN_CODEX)
    assert convene.codex_unavailable_reason() is None                      # no plan-wide signal
    calls = _arbiter_call_spy(monkeypatch)
    plan = _build(fixture)
    assert calls == [("codex", "max"), ("claude", "default")]              # ONE recompute
    arb = plan["arbiter"]
    assert (arb["provider"], arb["path"], arb["model"], arb["seat_model_role"], arb["timeout_s"]) == (
        "claude", "fallback", MAIN, "arbiter", 1200)
    assert arb["fallback_arbiter_residual"] is True
    assert "codex" in arb["constraint"] and "no_eligible_model" in arb["constraint"]
    assert "recomputed" in arb["constraint"]
    assert "unavailable at plan build" not in arb["constraint"]           # it was not a plan-wide signal
    assert set(arb) == _LEGACY_ARBITER_KEYS | _R14_KEYS                    # no new arbiter key beyond r14's provenance
    assert all(s["provider"] != "codex" and not s.get("substitute_for") for s in plan["seats"])
    assert convene.codex_substitution_review_line(plan) is None           # no seat was substituted
    assert convene.schema_validate(plan, convene.load_schema()) == []
    assert convene.schema_validate(convene.build_run_record(plan), convene.load_run_record_schema()) == []
    # no budget row: the persisted path records substitutions of member seats only, and there are none
    contract, pdir, rdir = fixture
    project = tmp_path / "proj-r8"
    project.mkdir()
    assert convene.main(["--profile", "r8a", "--task", "r8", "--profiles-dir", str(pdir), "--roster-dir", str(rdir),
                         "--project-root", str(project), "--session-id", "r8"]) == 0
    assert "astra substitutions" not in capsys.readouterr().out
    assert list(seat_home.rglob("astra-budget.jsonl")) == []


def test_r8_fixture_b_a_claude_adversary_puts_the_recomputed_arbiter_on_agy(seat_home, codex_on_path, tmp_path):
    _no_codex_freeze(seat_home)
    fixture = _r8_fixture_b(tmp_path)
    assert _build(fixture)["arbiter"]["provider"] == "codex"               # CONTROL: valid roster -> codex
    _write_codex_roster(seat_home, _ALL_HIDDEN_CODEX)
    arb = _build(fixture)["arbiter"]
    assert (arb["provider"], arb["path"], arb["model"], arb["timeout_s"]) == (
        "agy", "fallback", "gemini-4-argon-high", 600)
    assert "no_eligible_model" in arb["constraint"] and "recomputed" in arb["constraint"]


def test_r8_negative_control_without_the_recompute_the_build_raises_no_eligible(seat_home, codex_on_path, tmp_path,
                                                                                 monkeypatch):
    _no_codex_freeze(seat_home)
    _write_codex_roster(seat_home, _ALL_HIDDEN_CODEX)

    def recompute_off(provider, effort, exc):
        raise exc
    monkeypatch.setattr(convene, "_no_eligible_arbiter_exclusion", recompute_off)
    with pytest.raises(convene.NoEligibleCodexModelError):
        _build(_r8_fixture_a(tmp_path))


def test_r8_nothing_left_after_the_exclusion_fails_closed(seat_home, codex_on_path, tmp_path):
    """Claude AND agy adversarial: the recompute has no candidate -> ConveneError, as today."""
    _no_codex_freeze(seat_home)
    fixture = _r8_profile(tmp_path, "r8none", claude_adversarial=True, agy_adversarial=True)
    _write_codex_roster(seat_home, _ALL_HIDDEN_CODEX)
    with pytest.raises(convene.ConveneError) as e:
        _build(fixture)
    assert not isinstance(e.value, convene.NoEligibleCodexModelError)
    assert "arbiter constraint unsatisfiable" in str(e.value) and "['codex']" in str(e.value)


# RE-POINTED by the astra reserve (F8): the codex arbiter is the Sol literal, which never reads the freeze,
# so the broken resolver is planted in the roster it is validated against.
@pytest.mark.parametrize("pins_raw,needle", [
    ("{not json", "roster_invalid"),
    ("JUNK_SHAPE", "roster_invalid"),
])
def test_r8_control_a_broken_resolver_is_a_convene_error_and_never_recomputed(seat_home, codex_on_path, tmp_path,
                                                                             monkeypatch, pins_raw, needle):
    if pins_raw == "JUNK_SHAPE":
        _invalid_codex_roster(seat_home)
    else:
        (seat_home / ".codex" / "models_cache.json").write_text(pins_raw, encoding="utf-8")
    calls = _arbiter_call_spy(monkeypatch)
    with pytest.raises(convene.ConveneError) as e:
        _build(_r8_fixture_a(tmp_path))
    assert needle in str(e.value) and not isinstance(e.value, convene.NoEligibleCodexModelError)
    assert calls == [("codex", "max")]                                     # no second arbiter selection


def test_r4_an_invalid_codex_roster_fails_closed_naming_roster_invalid_for_members_and_the_arbiter(
        seat_home, codex_on_path, tmp_path, monkeypatch, capsys):
    _no_codex_freeze(seat_home)
    _invalid_codex_roster(seat_home)
    # member seats: the coding-ratification skeptic is codex
    with pytest.raises(convene.ConveneError) as e:
        _real_plan("coding-ratification")
    assert "roster_invalid" in str(e.value) and not isinstance(e.value, convene.NoEligibleCodexModelError)
    project = tmp_path / "proj-invalid"
    project.mkdir()
    rc = convene.main(["--profile", "coding-ratification", "--task", "t", "--profiles-dir", str(_REAL_PROFILES),
                       "--roster-dir", str(_REAL_ROSTER), "--project-root", str(project)])
    err = capsys.readouterr().err
    assert rc == 2 and "CONVENE FAIL-CLOSED" in err and "roster_invalid" in err and "Traceback" not in err
    assert not (project / ".avengers").exists() and list(seat_home.rglob("astra-budget.jsonl")) == []
    # the arbiter: R8 fixture A has no codex member seat, so the arbiter is the first codex resolution
    calls = _arbiter_call_spy(monkeypatch)
    with pytest.raises(convene.ConveneError) as e:
        _build(_r8_fixture_a(tmp_path))
    assert "roster_invalid" in str(e.value) and not isinstance(e.value, convene.NoEligibleCodexModelError)
    assert calls == [("codex", "max")]                                     # invalid is never recomputed
    # a plain JSON break is invalid too
    (seat_home / ".codex" / "models_cache.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(convene.ConveneError) as e:
        _real_plan("coding-ratification")
    assert "roster_invalid" in str(e.value)
    # CONTROL: a valid roster in the same HOME builds both plans
    _write_codex_roster(seat_home)
    assert _by_id(_real_plan("coding-ratification"))["skeptic"]["model"] == MEMBER
    assert _build(_r8_fixture_a(tmp_path))["arbiter"]["provider"] == "codex"


def test_r4_an_absent_codex_roster_builds_with_harness_literal_codex_seats_and_arbiter(seat_home, codex_on_path,
                                                                                      tmp_path):
    _no_codex_freeze(seat_home)
    (seat_home / ".codex" / "models_cache.json").unlink()
    plan = _real_plan("coding-ratification")
    sk = _by_id(plan)["skeptic"]
    assert (sk["provider"], sk["model"]) == ("codex", MEMBER) and f"-m {MEMBER} " in sk["guard_stack"]
    assert all(k not in sk for k in _SUBSTITUTION_KEYS)
    role, pin = convene.resolve_seat_pin("codex", "xhigh")
    assert (role, pin.provenance["source"]) == ("consultant_main", "harness_literal")
    assert "no codex roster" in pin.provenance["fallback_reason"] and "roster_invalid" not in pin.provenance
    arb = _build(_r8_fixture_a(tmp_path))["arbiter"]                       # absent is never a recompute
    # RE-POINTED (WP-A03, D24): the codex arbiter's max ceiling 1200 -> 3600. Model, path and
    # provider — what this test is about — unchanged.
    assert (arb["provider"], arb["path"], arb["model"], arb["timeout_s"]) == ("codex", "clean", MEMBER, 3600)
    assert "recomputed" not in arb["constraint"]


def test_r8_a_plan_without_a_recompute_keeps_the_pre_r8_arbiter_text(seat_home, codex_on_path, tmp_path):
    """REGRESSION GUARD (found by the WP-H3A live dry-run): the recompute's excluded-provider set must not
    leak into the no-signal wording. HEAD's fallback text says "all providers deliberated"; it says "all
    available providers" only when a provider really was excluded."""
    arb = _real_plan("coding-ratification")["arbiter"]
    assert arb["constraint"] == (
        "external seatless arbiter; claude is the strongest-adjudication-prior NON-adversarial provider "
        "(adversarial=['codex']); all providers deliberated -> fallback path (accepted residual)")
    assert arb["excluded_authorship"].startswith("fallback path — 'claude' deliberated")
    _no_codex_freeze(seat_home)
    _write_codex_roster(seat_home, _ALL_HIDDEN_CODEX)
    recomputed = _build(_r8_fixture_a(tmp_path))["arbiter"]
    assert "all available providers deliberated" in recomputed["constraint"]
    assert recomputed["excluded_authorship"].startswith("fallback path — 'claude' deliberated")
    clean = _build(_clean_agy_arbiter_profile(tmp_path))["arbiter"]       # CONTROL: the clean path text
    # AMENDMENT 3: the agy-arbiter fixture DECLARES its arbiter now (agy is not selected in a healthy
    # session), so the authorship note is the declared-arbiter form rather than the selection form.
    assert clean["excluded_authorship"].startswith("declared arbiter — 'agy' is used")


def test_r4_r8_the_contract_documents_the_arbiter_recompute_and_the_invalid_roster_error():
    text = (_AVENGERS_ROOT / "references" / "convene-contract.md").read_text(encoding="utf-8")
    assert "roster_invalid" in text
    assert "recomputed once" in text


# =========================================================================== #
# #282 r14 (plan K16) — convene persists each materialised seat's pin provenance
#
# Persisted `provenance` = EXACTLY {requested_selector, resolved_model, source, roster_fetched_at}, plus
# `frozen_slug` (the pins-file top as written) when source is "freeze" — on every member seat, on the
# arbiter, and wherever the run record copies them. The pin's live / event keys (quota_state,
# fallback_reason, roster_stale, roster_invalid, ...) are NOT persisted: a frozen plan records what was
# resolved, not a meter reading (so test_without_a_signal_the_plan_is_the_pre_change_plan still finds
# the plan byte-equal across readings). Both schemas carry it as an OPTIONAL object, closed inside.
# =========================================================================== #
_R14_BASE_KEYS = frozenset({"requested_selector", "resolved_model", "source", "roster_fetched_at"})
_AGY_LEVEL_BY_ROLE = {"consultant_main": "high", "consultant_support": "medium", "arbiter": "high"}


def _roster_fetched_at(home, provider):
    path = (home / ".codex" / "models_cache.json") if provider == "codex" else \
        (home / ".claude" / "state" / "agy-models.json")
    return json.loads(path.read_text(encoding="utf-8"))["fetched_at"]


def _claude_provenance(model):
    # #291: a Claude pin is roster-decided, so its provenance carries roster_rev (the roster REVISION).
    return {"requested_selector": model, "resolved_model": model, "source": "harness_literal", "roster_fetched_at": None,
            "roster_rev": ROSTER_REV}


def _persisted_session(project, session_id):
    session = project / ".avengers" / "sessions" / session_id
    return (json.loads((session / "session-plan.json").read_text(encoding="utf-8")),
            json.loads((session / "run-record.json").read_text(encoding="utf-8")))


def _provenance_by_seat(seats):
    return {s["seat_id"]: s.get("provenance") for s in seats}


def test_r14_frozen_seats_persist_freeze_provenance_in_the_plan_and_the_run_record(seat_home, codex_on_path, tmp_path):
    # RE-POINTED at AMENDMENT 3 (D25): this test needs a profile with BOTH a codex seat and an agy
    # seat. coding-ratification lost both agy seats, and research-synthesis is the only profile that
    # still has both. Its roles are MIRRORED: the codex seat is the architect and the claude seat is
    # the skeptic, the opposite of coding-ratification — so the two seat ids are SWAPPED, not renamed.
    # The agy slug is written at level -low, which NO seat serves, so frozen_slug is provably the file's value.
    _write_pins(seat_home, {"codex": "gpt-5.6-sol", "agy": "gemini-4-argon-low"})
    codex_at, agy_at = _roster_fetched_at(seat_home, "codex"), _roster_fetched_at(seat_home, "agy")
    project = tmp_path / "proj-r14-freeze"
    project.mkdir()
    assert convene.main(["--profile", "research-synthesis", "--task", "t", "--profiles-dir", str(_REAL_PROFILES),
                         "--roster-dir", str(_REAL_ROSTER), "--project-root", str(project), "--session-id", "r14"]) == 0
    plan, record = _persisted_session(project, "r14")                      # the documents as written to disk
    assert convene.schema_validate(plan, convene.load_schema()) == []
    assert convene.schema_validate(record, convene.load_run_record_schema()) == []
    seats = _by_id(plan)
    # RE-POINTED by the astra reserve (F8): the codex seat is the Sol literal, which a codex freeze never
    # reaches, so it persists a ROSTER provenance (with the roster revision) while the agy seats below
    # still persist the freeze.
    assert seats["architect"]["provenance"] == {
        "requested_selector": f"{MEMBER}@xhigh", "resolved_model": MEMBER, "source": "roster",
        "roster_fetched_at": codex_at, "roster_rev": ROSTER_REV}
    agy = [s for s in plan["seats"] if s["provider"] == "agy"]
    assert agy
    for s in agy:
        level = _AGY_LEVEL_BY_ROLE[s["seat_model_role"]]
        assert s["model"] == f"gemini-4-argon-{level}" != "gemini-4-argon-low"
        assert s["provenance"] == {
            "requested_selector": f"TOP-argon-{level}", "resolved_model": s["model"], "source": "freeze",
            "roster_fetched_at": agy_at, "frozen_slug": "gemini-4-argon-low"}, s["seat_id"]
    assert seats["skeptic"]["provenance"] == _claude_provenance(MAIN)
    # research-synthesis DECLARES its arbiter (D23), so it is the consultant_support row -> OPUS, not the
    # selected `arbiter` row's fable that coding-ratification resolved. Provenance shape is the same.
    assert (plan["arbiter"]["provider"], plan["arbiter"]["provenance"]) == ("claude", _claude_provenance(SUPPORT))
    assert all(s["provenance"]["resolved_model"] == s["model"] for s in plan["seats"])     # convene reads no env layer
    # the run record carries the same provenance wherever it copies seats and the arbiter
    assert _provenance_by_seat(record["staffing"]["seats"]) == _provenance_by_seat(plan["seats"])
    assert record["arbiter"]["provenance"] == plan["arbiter"]["provenance"]
    # the codex arbiter (R8 fixture A, clean path) is the Sol literal too: roster provenance at its effort
    arb_plan = _build(_r8_fixture_a(tmp_path))
    arb = arb_plan["arbiter"]
    assert (arb["provider"], arb["path"], arb["model"], arb["effort"]) == ("codex", "clean", MEMBER, "max")
    assert arb["provenance"] == {
        "requested_selector": f"{MEMBER}@max", "resolved_model": MEMBER, "source": "roster",
        "roster_fetched_at": codex_at, "roster_rev": ROSTER_REV}
    arb_record = convene.build_run_record(arb_plan)
    assert arb_record["arbiter"]["provenance"] == arb["provenance"]
    assert convene.schema_validate(arb_plan, convene.load_schema()) == []
    assert convene.schema_validate(arb_record, convene.load_run_record_schema()) == []


def test_r14_roster_seats_persist_source_roster_with_the_fetch_time_and_no_frozen_slug(seat_home, codex_on_path, tmp_path):
    _write_pins(seat_home, {})                                              # no freeze for either provider
    codex_at, agy_at = _roster_fetched_at(seat_home, "codex"), _roster_fetched_at(seat_home, "agy")
    plan = _real_plan("coding-ratification")
    seats = _by_id(plan)
    assert seats["skeptic"]["provenance"] == {
        "requested_selector": f"{MEMBER}@xhigh", "resolved_model": MEMBER, "source": "roster",
        "roster_fetched_at": codex_at, "roster_rev": ROSTER_REV}
    for s in plan["seats"]:
        if s["provider"] == "agy":
            assert s["provenance"] == {
                "requested_selector": f"TOP-argon-{_AGY_LEVEL_BY_ROLE[s['seat_model_role']]}",
                "resolved_model": s["model"], "source": "roster", "roster_fetched_at": agy_at}, s["seat_id"]
        elif s["provider"] == "claude":
            assert s["provenance"] == _claude_provenance(s["model"]), s["seat_id"]
    assert plan["arbiter"]["provenance"] == _claude_provenance(MAIN)
    assert not any("frozen_slug" in item["provenance"] for item in plan["seats"] + [plan["arbiter"]])
    arb = _build(_r8_fixture_a(tmp_path))["arbiter"]
    assert arb["provenance"] == {"requested_selector": f"{MEMBER}@max", "resolved_model": MEMBER, "source": "roster",
                                 "roster_fetched_at": codex_at, "roster_rev": ROSTER_REV}
    record = convene.build_run_record(plan)
    assert _provenance_by_seat(record["staffing"]["seats"]) == _provenance_by_seat(plan["seats"])
    assert convene.schema_validate(record, convene.load_run_record_schema()) == []
    # CONTROL: restoring the codex freeze in the same HOME leaves the Sol seat on the roster (F8) while the
    # TOP rows record it, so the absence above is the reserve's rule and not an accident.
    _write_pins(seat_home, {"codex": "gpt-5.6-sol"})
    assert _by_id(_real_plan("coding-ratification"))["skeptic"]["provenance"] == seats["skeptic"]["provenance"]
    frozen = seat_model.resolve("escalation", "codex").provenance
    assert (frozen["source"], frozen["frozen_slug"]) == ("freeze", "gpt-5.6-sol")


def test_r14_persisted_provenance_is_the_four_keys_never_the_pins_event_or_meter_keys(seat_home, codex_on_path,
    # RE-POINTED at AMENDMENT 3 (D25): this test needs a profile with BOTH a codex seat and an agy
    # seat. coding-ratification lost both agy seats, and research-synthesis is the only profile that
    # still has both. Its roles are MIRRORED: the codex seat is the architect and the claude seat is
    # the skeptic, the opposite of coding-ratification — so the two seat ids are SWAPPED, not renamed.
                                                                                     monkeypatch):
    _no_codex_freeze(seat_home)                                            # agy stays frozen
    (seat_home / ".codex" / "models_cache.json").unlink()                  # absent roster: a recorded literal
    _role, pin = convene.resolve_seat_pin("codex", "xhigh")
    assert {"fallback_reason", "quota_state"} <= set(pin.provenance)       # CONTROL: the pin DOES carry event keys
    plan = _real_plan("research-synthesis")
    assert _by_id(plan)["architect"]["provenance"] == {           # the astra reserve: the Sol literal
        "requested_selector": f"{MEMBER}@xhigh", "resolved_model": MEMBER, "source": "harness_literal",
        "roster_fetched_at": None, "roster_rev": ROSTER_REV}
    for item in plan["seats"] + [plan["arbiter"]]:
        prov = item["provenance"]
        # #291: a roster-DECIDED pin (every Claude pin, and the codex std literal) also carries roster_rev
        roster_decided = item["provider"] == "claude" or prov["requested_selector"].startswith(
            model_roster.CODEX_STD + "@")
        expected = (_R14_BASE_KEYS | ({"frozen_slug"} if prov["source"] == "freeze" else set())
                    | ({"roster_rev"} if roster_decided else set()))
        assert set(prov) == expected, (item.get("seat_id", "<arbiter>"), prov)
        if roster_decided:
            assert prov["roster_rev"] == ROSTER_REV, (item.get("seat_id", "<arbiter>"), prov)
    assert {item["provenance"]["source"] for item in plan["seats"]} == {"harness_literal", "freeze"}
    # FAIL-CLOSED: a freeze pin that does not say what was frozen cannot be persisted as a freeze
    real_resolve = seat_model.resolve

    def forgetful(role, provider, **kwargs):
        got = real_resolve(role, provider, **kwargs)
        prov = {k: v for k, v in got.provenance.items() if k != "frozen_slug"}
        return seat_model.SeatPin(model=got.model, effort=got.effort, timeout=got.timeout,
                                  argv_fragment=got.argv_fragment, provenance=prov)
    monkeypatch.setattr(convene._seat_model, "resolve", forgetful)
    with pytest.raises(convene.ConveneError) as e:
        _real_plan("research-synthesis")
    assert "frozen_slug" in str(e.value) and "schema validation" in str(e.value)


def test_r14_a_substituted_seat_persists_its_claude_pins_provenance(seat_home, codex_on_path):
    control = _by_id(_real_plan("coding-ratification"))["skeptic"]
    assert (control["provider"], control["provenance"]["source"]) == ("codex", "roster")   # CONTROL: the Sol pin
    _signal("rate_limit_reached", seat_home, codex_on_path)
    plan = _real_plan("coding-ratification")
    sk = _by_id(plan)["skeptic"]
    assert (sk["provider"], sk["substitute_for"], sk["requested_model"]) == ("claude", "codex", MEMBER)
    claude_pin = seat_model.resolve(convene.CODEX_SUBSTITUTE_ROLE, "claude")
    assert sk["provenance"] == {k: claude_pin.provenance[k] for k in _R14_BASE_KEYS | {"roster_rev"}} \
        == _claude_provenance(MAIN)
    record = convene.build_run_record(plan)
    rsk = {s["seat_id"]: s for s in record["staffing"]["seats"]}["skeptic"]
    assert rsk["provenance"] == sk["provenance"] and rsk["substitute_for"] == "codex"
    # the arbiter recomputed without codex lands on agy (fallback) and carries agy's freeze provenance
    arb = plan["arbiter"]
    assert (arb["provider"], arb["provenance"]["source"], arb["provenance"]["frozen_slug"],
            arb["provenance"]["requested_selector"]) == ("agy", "freeze", "gemini-4-argon-high", "TOP-argon-high")
    assert convene.schema_validate(plan, convene.load_schema()) == []
    assert convene.schema_validate(record, convene.load_run_record_schema()) == []


def _schema_provenance_copies(schema, rr_schema):
    return [
        schema["properties"]["seats"]["items"]["properties"]["provenance"],
        schema["properties"]["arbiter"]["properties"]["provenance"],
        rr_schema["properties"]["staffing"]["properties"]["seats"]["items"]["properties"]["provenance"],
        rr_schema["properties"]["arbiter"]["properties"]["provenance"],
    ]


def test_r14_both_schemas_carry_an_optional_provenance_object_closed_inside(seat_home, codex_on_path):
    schema, rr_schema = convene.load_schema(), convene.load_run_record_schema()
    assert (schema["$id"], rr_schema["$id"]) == ("avengers/session-plan.v2", "avengers/run-record.v1")   # ids unchanged
    copies = _schema_provenance_copies(schema, rr_schema)
    assert all(c == copies[0] for c in copies)                             # one definition, four copies (no $ref)
    prov_schema = copies[0]
    assert prov_schema["type"] == "object" and prov_schema["additionalProperties"] is False
    assert set(prov_schema["required"]) == _R14_BASE_KEYS
    # RE-POINTED by #282 fix round 1 F15 (plan K47): the closed object gained the OPTIONAL boolean
    # `roster_invalid`. `required` is untouched, so the additive claim this test makes still holds;
    # only the property SET grew. Its own coverage lives in
    # test_fr1_f15_both_schemas_carry_roster_invalid_as_an_optional_boolean_inside_the_closed_object.
    # #291 (WP-1 JC1): the closed object gained the OPTIONAL integer `roster_rev` the same additive way.
    assert set(prov_schema["properties"]) == _R14_BASE_KEYS | {"frozen_slug", "roster_invalid", "roster_rev"}
    assert (prov_schema["properties"]["roster_rev"]["type"], prov_schema["properties"]["roster_rev"]["minimum"]) == (
        "integer", 1)
    assert set(prov_schema["properties"]["source"]["enum"]) == seat_model.SOURCES
    assert prov_schema["properties"]["roster_fetched_at"]["type"] == ["string", "null"]
    for required in (schema["properties"]["seats"]["items"]["required"], schema["properties"]["arbiter"]["required"],
                     rr_schema["properties"]["staffing"]["properties"]["seats"]["items"]["required"],
                     rr_schema["properties"]["arbiter"]["required"]):
        assert "provenance" not in required                                  # OPTIONAL on seats and the arbiter

    plan = _real_plan("coding-ratification")                               # fixture pins: codex + agy frozen
    record = convene.build_run_record(plan)
    for doc, sch, seats_of in ((plan, schema, lambda d: d["seats"]), (record, rr_schema, lambda d: d["staffing"]["seats"])):
        assert convene.schema_validate(doc, sch) == []
        # a pre-r14 artifact (no provenance anywhere) still validates
        legacy = copy.deepcopy(doc)
        for item in seats_of(legacy) + [legacy["arbiter"]]:
            item.pop("provenance")
        assert convene.schema_validate(legacy, sch) == []
        # NEGATIVE CONTROLS, on a seat and on the arbiter
        for where, pick in (("seats[0]", lambda d: seats_of(d)[0]), ("arbiter", lambda d: d["arbiter"])):
            for mutate, needle in (
                    (lambda p: p.__setitem__("quota_state", "fresh"), "additional property 'quota_state' not allowed"),
                    (lambda p: p.__setitem__("source", "bogus"), "'bogus' not in enum"),
                    (lambda p: p.pop("resolved_model"), "missing required property 'resolved_model'"),
                    (lambda p: p.__setitem__("roster_fetched_at", 7), "expected type"),
                    (lambda p: p.__setitem__("frozen_slug", None), "expected type"),
            ):
                bad = copy.deepcopy(doc)
                mutate(pick(bad)["provenance"])
                errs = convene.schema_validate(bad, sch)
                assert any(".provenance" in e and needle in e for e in errs), (where, needle, errs)
            not_object = copy.deepcopy(doc)
            pick(not_object)["provenance"] = "freeze"
            assert any(".provenance" in e and "expected type" in e for e in convene.schema_validate(not_object, sch))
    # the run record built from a pre-r14 plan carries no provenance and validates
    legacy_plan = copy.deepcopy(plan)
    for item in legacy_plan["seats"] + [legacy_plan["arbiter"]]:
        item.pop("provenance")
    legacy_record = convene.build_run_record(legacy_plan)
    assert not any("provenance" in s for s in legacy_record["staffing"]["seats"]) and "provenance" not in legacy_record["arbiter"]


def test_r14_the_persisted_vocabulary_matches_seat_model_and_the_contract_documents_it():
    assert convene.PROVENANCE_FROZEN_SLUG == seat_model.FROZEN_SLUG
    assert set(convene.PERSISTED_PROVENANCE_KEYS) == _R14_BASE_KEYS
    text = (_AVENGERS_ROOT / "references" / "convene-contract.md").read_text(encoding="utf-8")
    assert "`provenance`" in text and "`frozen_slug`" in text


# =========================================================================== #
# #282 fix round 1 F15 (plan K47) — the freeze-with-invalid-roster rule is
# DOCUMENTED and RECORDED, not changed
#
# A codex freeze is honoured UNVALIDATED when the roster is invalid (the accepted K14
# behaviour): the freeze is the operator's emergency override, and it is what restored
# gpt-6-astra during the 2026-09-15 priority tie. The behaviour is deliberately unchanged;
# what F15 adds is that the frozen plan SAYS SO — `roster_invalid: true` joins the persisted
# provenance whenever the pin carries it, so a plan frozen under an invalid roster is
# distinguishable after the fact from one frozen under a good roster.
# =========================================================================== #
def test_fr1_f15_a_frozen_codex_seat_with_an_invalid_roster_persists_roster_invalid(
    # RE-POINTED at AMENDMENT 3 (D25): this test needs a profile with BOTH a codex seat and an agy
    # seat. coding-ratification lost both agy seats, and research-synthesis is the only profile that
    # still has both. Its roles are MIRRORED: the codex seat is the architect and the claude seat is
    # the skeptic, the opposite of coding-ratification — so the two seat ids are SWAPPED, not renamed.
        seat_home, codex_on_path, tmp_path):
    """RE-POINTED by the astra reserve (roster rev 4, F8). F15 was: codex FROZEN + roster INVALID -> the plan
    BUILDS (the freeze honoured unvalidated) and the seat persists `roster_invalid: true`. No avengers codex
    seat reads the freeze any more - the member and the arbiter are the Sol LITERAL - so an invalid roster now
    fails the codex seat CLOSED whether or not a codex freeze is in force. The freeze exception itself still
    holds on the TOP rows (asserted below through seat_model), where F15's persisted key would come from.

    CONTROLS in the same body: (1) a VALID roster in the same HOME builds, with no key; (2) the same invalid
    roster with NO freeze fails the same way; (3) the freeze exception is intact for a TOP row."""
    _write_pins(seat_home, {"codex": "gpt-5.6-sol", "agy": "gemini-4-argon-high"})
    _invalid_codex_roster(seat_home)
    with pytest.raises(convene.ConveneError) as e:
        _real_plan("research-synthesis")
    assert "roster_invalid" in str(e.value)
    # (3) the freeze exception is unchanged where a freeze still applies: a TOP row
    top = seat_model.resolve("escalation", "codex", fail_open=False).provenance
    assert (top["source"], top["frozen_slug"], top["roster_invalid"]) == ("freeze", "gpt-5.6-sol", True)

    # (1) CONTROL: the same HOME, the same freeze, a VALID roster -> builds, roster provenance, no key
    _write_codex_roster(seat_home)
    codex_at = _roster_fetched_at(seat_home, "codex")
    clean = _by_id(_real_plan("research-synthesis"))["architect"]["provenance"]
    assert clean["source"] == "roster" and "roster_invalid" not in clean
    assert clean["roster_fetched_at"] == codex_at
    assert set(clean) == _R14_BASE_KEYS | {"roster_rev"}

    # (2) CONTROL: NO codex freeze + the invalid roster -> still fail-closed, still no plan
    _no_codex_freeze(seat_home)
    _invalid_codex_roster(seat_home)
    with pytest.raises(convene.ConveneError) as e:
        _real_plan("research-synthesis")
    assert "roster_invalid" in str(e.value)


def test_fr1_f15_both_schemas_carry_roster_invalid_as_an_optional_boolean_inside_the_closed_object(
    # RE-POINTED at AMENDMENT 3 (D25): this test needs a profile with BOTH a codex seat and an agy
    # seat. coding-ratification lost both agy seats, and research-synthesis is the only profile that
    # still has both. Its roles are MIRRORED: the codex seat is the architect and the claude seat is
    # the skeptic, the opposite of coding-ratification — so the two seat ids are SWAPPED, not renamed.
        seat_home, codex_on_path):
    """K47's schema half: an ADDITIVE optional boolean inside the still-closed `provenance`
    object, in all four copies, with no `$id` change. NEGATIVE CONTROLS: a non-boolean is
    rejected, the object is still closed against anything else, and a plan carrying no
    `roster_invalid` still validates."""
    schema, rr_schema = convene.load_schema(), convene.load_run_record_schema()
    assert (schema["$id"], rr_schema["$id"]) == ("avengers/session-plan.v2", "avengers/run-record.v1")
    copies = _schema_provenance_copies(schema, rr_schema)
    assert all(c == copies[0] for c in copies)                             # still one definition, four copies
    prov_schema = copies[0]
    assert prov_schema["properties"]["roster_invalid"] == {"type": "boolean"}
    assert "roster_invalid" not in prov_schema["required"]                 # OPTIONAL
    assert prov_schema["additionalProperties"] is False                    # still closed

    # RE-POINTED by the astra reserve: no avengers codex seat can be frozen any more, so the key is planted on
    # a valid plan's codex seat (the shape a frozen TOP seat would persist) and the schema judges it.
    plan = _real_plan("research-synthesis")
    for s in plan["seats"]:
        if s["provider"] == "codex":
            s["provenance"]["roster_invalid"] = True
    record = convene.build_run_record(plan)
    for doc, sch, seats_of in ((plan, schema, lambda d: d["seats"]),
                               (record, rr_schema, lambda d: d["staffing"]["seats"])):
        assert convene.schema_validate(doc, sch) == []
        bad = copy.deepcopy(doc)
        codex_seat = [s for s in seats_of(bad) if s.get("provider") == "codex"][0]
        codex_seat["provenance"]["roster_invalid"] = "true"                # NEGATIVE CONTROL: not a boolean
        assert any(".provenance" in err and "expected type" in err for err in convene.schema_validate(bad, sch))
        without = copy.deepcopy(doc)                                       # CONTROL: absent still validates
        for s in seats_of(without):
            s["provenance"].pop("roster_invalid", None)
        assert convene.schema_validate(without, sch) == []


# --------------------------------------------------------------------------- #
# D24 — a convene seat call is subject to the same policy (WP-A03)
# --------------------------------------------------------------------------- #
def test_d24_the_watched_stack_has_the_exact_shape():
    """THE ANCHOR for _watched_codex_prefix: the whole string, written out once.

    Every other guard-stack assertion goes through the builder, which would happily mirror a
    change in convene's output. This one does not — it pins the flags, their order, the
    `-- codex exec` separator and the placeholders literally, so a shape change has to be
    made deliberately here.
    """
    stack = convene.guard_stack_for("codex", "xhigh")
    assert stack == (
        f"python3 {convene._CODEX_WATCH} --mode codex --model gpt-6.1-sol --hard-cap 2400 "
        f"--stdout-file {{stdout-file}} --stderr-file {{stderr-file}} "
        f'-- codex exec -s read-only -m gpt-6.1-sol -c model_reasoning_effort=xhigh "…"'
    )
    # The watchdog really is the one being invoked, from the tree convene imported.
    assert convene._CODEX_WATCH.name == "codex_watch.py"
    assert convene._CODEX_WATCH.parent == convene._META_DIR


def test_d24_a_seat_call_is_watched_not_wall_clocked():
    """ONE SEAT, the whole policy (WP-A03 criterion: "convene: a seat call is subject to the
    same policy, proven on one seat").

    The fixed wall clock is GONE and the ceiling survives as the watchdog's runaway cap —
    the two halves of D24. Asserted together because either alone is satisfiable by a
    mistake: keeping `timeout` AND adding the watchdog would pass a cap check, and dropping
    both would pass a "no timeout" check while removing the cap entirely.
    """
    stack = convene.guard_stack_for("codex", "xhigh")
    assert not stack.startswith("timeout ")
    assert " timeout " not in stack
    assert "codex_watch.py" in stack
    # The cap is the SEAT REGISTRY's number, one owner -- not the watchdog's own table.
    assert f"--hard-cap {codex_model.timeout_for(MEMBER, 'xhigh')} " in stack
    # And it is passed as a cap, never as an --effort that would hand ownership over.
    assert "--effort" not in stack

    # NEGATIVE CONTROL: agy is deliberately NOT migrated this revision (L13), so the agy seat
    # still carries the fixed wall clock. Without this, "no `timeout ` prefix" could be read
    # as a whole-module property rather than the codex-only change it is.
    assert convene.guard_stack_for("agy", "default").startswith('(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan ')


def test_d24_the_stream_slots_survive_a_shell():
    """The stack is run VERBATIM by the chair, so its placeholders must not be shell syntax.

    NEGATIVE CONTROL included: the angle-bracket form this was almost written with really is
    eaten by the shell (it becomes a redirection), which is why the slots are braced.
    """
    stack = convene.guard_stack_for("codex", "xhigh")
    for slot in (convene._STDOUT_SLOT, convene._STDERR_SLOT):
        assert slot in stack
        for meta in "<>|&;$`":
            assert meta not in slot, (slot, meta)

    if os.name == "nt" or shutil.which("bash") is None:
        pytest.skip("needs bash to prove what the shell does with each form")
    out = subprocess.run(["bash", "-c", f"printf '%s\\n' --stdout-file {convene._STDOUT_SLOT}"],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert out.returncode == 0
    assert out.stdout.split() == ["--stdout-file", convene._STDOUT_SLOT]
    # CONTROL: the angle-bracket form is a redirect, so bash consumes it and fails on the
    # missing file rather than passing it through as an argument.
    bad = subprocess.run(["bash", "-c", "printf '%s\\n' --stdout-file <stdout-file>"],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert bad.returncode != 0 or "stdout-file" not in bad.stdout.split()[1:]


# =========================================================================== #
# S081 revision 4, WP-D2 (design §3.4, §2.2, D17; plan L9) — convene ADMITS its codex seat at PLAN TIME
#
# The session id is minted BEFORE apply_codex_substitution (the hoist), so the codex member seat can be
# admitted against it: ONE in-process codex_quota.admit("deliberation", <session id>, size=…,
# model_class=…) per session. A refusal (threshold / budget_spent / budget_store_unavailable / an
# unavailable token) re-seats the seat through the EXISTING substitution; the decision's admission_id is
# stored on the seat beside substitute_for / substitution_reason / requested_model. A persisted convene
# RECORDS; --dry-run and a bare build_session_plan decide CHECK-ONLY and write nothing. Every store here
# lives under the fixture HOME.
# =========================================================================== #
_D2_KEYS = frozenset({"admission_id"})
_D2_ROW_FIELDS = ("key", "use", "admitted", "reason", "role", "model_class", "requested_model", "size",
                  "size_source", "admission_id")


def _project(tmp_path, name):
    project = tmp_path / name
    project.mkdir()
    return project


def _persisted_plan(profile, project, *, session_id="d2", size=None):
    """A RECORDING plan build (what main() does without --dry-run), on a real profile."""
    return convene.build_session_plan({"profile": profile, "task": "t"}, profiles_dir=_REAL_PROFILES,
                                      roster_dir=_REAL_ROSTER, session_id=session_id, now=_FIXED_NOW,
                                      size=size, project_root=project, record_admission=True)


def _main_args(project, *extra, profile="coding-ratification"):
    return ["--profile", profile, "--task", "t", "--profiles-dir", str(_REAL_PROFILES),
            "--roster-dir", str(_REAL_ROSTER), "--project-root", str(project), *extra]


#: AMENDMENT 3 (D25): the profile that still holds exactly ONE codex seat. Tests whose subject is "the
#: codex seat" (singular) run on it; coding-ratification now holds two, of different model classes.
_ONE_CODEX_SEAT = {"profile": "research-synthesis"}


def _written_plan(project, session_id):
    path = project / ".avengers" / "sessions" / session_id / "session-plan.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_d2_CONTROL_the_hoist_keeps_the_session_id_value_and_its_derivation():
    """THE CONTROL THAT PROVES THE HOIST IS PURE: the same (task, now) yields the same id before and after
    it. Nothing in this test depends on the admission, so it passes against the PRE-hoist convene too —
    the stage ran it there, and a hoist that changed the value would have failed it on one side."""
    common = {"profiles_dir": _REAL_PROFILES, "roster_dir": _REAL_ROSTER, "now": _FIXED_NOW}
    plan = convene.build_session_plan({"profile": "coding-ratification", "task": "Ship The Thing!"}, **common)
    assert plan["session_id"] == convene.make_session_id("Ship The Thing!", now=_FIXED_NOW)
    assert plan["session_id"] == "20260915-0100-ship-the-thing"            # the literal, not only the function
    assert plan["created_at"] == "2026-09-15T01:00:00Z"
    # no task -> the contract's family names it; an explicit id wins over both
    nameless = convene.build_session_plan({"profile": "coding-ratification"}, **common)
    assert nameless["session_id"] == "20260915-0100-coding-ratification"
    given = convene.build_session_plan({"profile": "coding-ratification", "task": "x"}, session_id="given", **common)
    assert given["session_id"] == "given"


def test_d2_the_admission_is_keyed_on_the_hoisted_session_id(seat_home, tmp_path):
    _freeze_codex_on_std(seat_home)          # #302 WP-1: the subject needs ONE std class (see helper)
    project = _project(tmp_path, "proj-key")
    plan = convene.build_session_plan({"profile": "coding-ratification", "task": "Ship The Thing!"},
                                      profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER, now=_FIXED_NOW,
                                      project_root=project, record_admission=True)
    rows = _store_rows(project)
    assert [(r["key"], r["cycle_id"], r["use"], r["admitted"]) for r in rows] == [
        ("20260915-0100-ship-the-thing", "20260915-0100-ship-the-thing", "deliberation", True)]
    assert rows[0]["key"] == plan["session_id"]
    assert rows[0]["admission_id"] == _by_id(plan)["skeptic"]["admission_id"]
    # CONTROL (L9): a forge cycle id in the project does NOT capture the key — `deliberation` keys on the
    # SESSION, and the row says the key came from its caller, not from .forge/cycle-id.
    (project / ".forge").mkdir()
    (project / ".forge" / "cycle-id").write_text("forge-cycle-x\n", encoding="utf-8")
    assert codex_quota.cycle_id_for(project) == "forge-cycle-x"
    convene.build_session_plan({"profile": "coding-ratification", "task": "x"}, profiles_dir=_REAL_PROFILES,
                               roster_dir=_REAL_ROSTER, session_id="given", project_root=project,
                               record_admission=True)
    assert [r["key"] for r in _store_rows(project)] == ["20260915-0100-ship-the-thing", "given"]
    assert {r["cycle_id_source"] for r in _store_rows(project)} == {"explicit"}


def test_d2_an_admitted_session_seats_codex_and_carries_its_admission_id(seat_home, tmp_path):
    _freeze_codex_on_std(seat_home)          # #302 WP-1: the subject needs ONE std class (see helper)
    # RE-POINTED at AMENDMENT 3 (D25): this test's subject is ONE codex seat taking ONE admission.
    # coding-ratification now holds TWO codex seats of different classes (and so takes two admissions,
    # covered by test_a3_each_codex_model_class_takes_its_own_admission_once_per_session);
    # research-synthesis is the profile that still has exactly one, so the subject is preserved.
    project = _project(tmp_path, "proj-admitted")
    plan = _persisted_plan("research-synthesis", project)
    sk = _by_id(plan)["architect"]
    assert (sk["provider"], sk["model"]) == ("codex", STD)
    assert all(k not in sk for k in _SUBSTITUTION_KEYS)
    assert codex_quota.is_admission_id(sk["admission_id"])
    rows = _store_rows(project)
    assert [{k: r[k] for k in _D2_ROW_FIELDS} for r in rows] == [{
        "key": "d2", "use": "deliberation", "admitted": True, "reason": "within_budget", "role": "consultant_main",
        "model_class": "std", "requested_model": STD, "size": "complex", "size_source": "default",
        "admission_id": sk["admission_id"]}]
    # ONLY the codex member seat went through the admission; the arbiter never does
    assert [s["seat_id"] for s in plan["seats"] if "admission_id" in s] == ["architect"]
    assert "admission_id" not in plan["arbiter"]
    # it is SEAT provenance, not a pin-provenance key: #282 r14's object stays closed and pin-only
    assert set(sk["provenance"]) == _R14_BASE_KEYS | {"roster_rev"}      # the astra reserve: a Sol literal
    record = convene.build_run_record(plan)
    assert {s["seat_id"]: s for s in record["staffing"]["seats"]}["architect"]["admission_id"] == sk["admission_id"]
    assert convene.schema_validate(plan, convene.load_schema()) == []
    assert convene.schema_validate(record, convene.load_run_record_schema()) == []
    assert "codex unavailable" not in convene.render_pre_spend_review(plan)


def test_d2_CONTROL_a_refused_session_seats_the_declared_fable_fallback_with_the_refusal_reason(seat_home, tmp_path):
    # RE-POINTED at AMENDMENT 3 (D25): this test's subject is ONE codex seat taking ONE admission.
    # coding-ratification now holds TWO codex seats of different classes (and so takes two admissions,
    # covered by test_a3_each_codex_model_class_takes_its_own_admission_once_per_session);
    # research-synthesis is the profile that still has exactly one, so the subject is preserved.
    project = _project(tmp_path, "proj-refused")
    # RE-POINTED by #322: the refusal was the 70 % trip-wire (an 80 % reading), which no longer refuses. The
    # admission refusal that is NOT unavailability is now a spent session slot (budget_spent).
    for key in ("d2", "d2-cc"):
        assert codex_quota.admit("deliberation", key, project_root=project, model_class="std")["admitted"] is True
    assert codex_quota.unavailable() is None                                # NOT unavailability: only admit refuses it
    plan = _persisted_plan("research-synthesis", project)
    sk = _by_id(plan)["architect"]
    assert (sk["provider"], sk["model"], sk["seat_model_role"], sk["timeout_s"]) == ("claude", MAIN, "consultant_main", 600)
    assert (sk["substitute_for"], sk["substitution_reason"], sk["requested_model"]) == ("codex", "budget_spent", MEMBER)
    assert (sk["adversarial_role"], sk["fallback_ok"]) == (False, True)   # research-synthesis's codex seat is the architect, not its adversary
    rows = [r for r in _store_rows(project) if r.get("admitted") is False]
    assert [(r["key"], r["use"], r["admitted"], r["reason"]) for r in rows] == [("d2", "deliberation", False, "budget_spent")]
    assert sk["admission_id"] == rows[0]["admission_id"]                    # the refusal the substitution follows
    assert convene.schema_validate(plan, convene.load_schema()) == []
    assert (f"codex unavailable (budget_spent): architect served by claude/{MAIN} {_GAP_LINE}"
            in convene.render_pre_spend_review(plan).splitlines())
    # the structural validate still passes, THROUGH the declared fallback: codex + claude collapses to one family
    contract, pdir, rdir = _codex_claude_profile(tmp_path)
    relaxed = convene.build_session_plan(contract, profiles_dir=pdir, roster_dir=rdir, session_id="d2-cc",
                                         project_root=project, record_admission=True)
    assert (relaxed["quorum"]["provider_families"], relaxed["quorum"]["fallback_relaxed"]) == (["claude"], True)
    # `_codex_claude_profile` is a SYNTHETIC fixture whose seats are skeptic + builder — the retarget of
    # this test to research-synthesis applies to the REAL-profile half above, not to this fixture.
    assert {s["seat_id"]: s["substitution_reason"] for s in relaxed["seats"] if s.get("substitute_for")} == {
        "skeptic": "budget_spent", "builder": "budget_spent"}


# RE-POINTED by #322: "threshold" left the parameter list; nothing produces that refusal any more.
@pytest.mark.parametrize("refusal", ["budget_spent", "budget_store_unavailable"])
def test_d2_every_admission_refusal_routes_through_the_existing_substitution(seat_home, tmp_path, monkeypatch, refusal):
    project = _project(tmp_path, f"proj-{refusal}")
    _freeze_codex_on_std(seat_home)          # #302 WP-1: the subject needs ONE std class (see helper)
    if refusal == "budget_spent":
        assert codex_quota.admit("deliberation", "d2", project_root=project, model_class="std")["admitted"] is True
    else:
        def unwritable(*_a, **_k):
            raise OSError("the budget store is read-only")
        monkeypatch.setattr(codex_quota, "file_lock", unwritable)
    plan = _persisted_plan("coding-ratification", project)
    sk = _by_id(plan)["skeptic"]
    assert (sk["provider"], sk["model"], sk["substitution_reason"], sk["requested_model"]) == (
        "claude", MAIN, refusal, STD)
    assert codex_quota.is_admission_id(sk["admission_id"])                  # a recorded decision has an id, row or not
    assert plan["arbiter"]["provider"] != "codex"
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_d2_a_refusal_outside_the_substitution_vocabulary_fails_closed(tmp_path, monkeypatch):
    project = _project(tmp_path, "proj-vocab")
    real_admit = convene._codex_quota.admit

    def drifted(use, key, **kwargs):
        decision = real_admit(use, key, **kwargs)
        decision.update(admitted=False, reason="trial_threshold")           # a real admit reason, never a substitution one
        return decision
    monkeypatch.setattr(convene._codex_quota, "admit", drifted)
    with pytest.raises(convene.ConveneError) as e:
        _persisted_plan("coding-ratification", project)
    assert "trial_threshold" in str(e.value) and not isinstance(e.value, convene.NoEligibleCodexModelError)

    def caller_bug(use, key, **kwargs):
        raise ValueError("unknown use")
    monkeypatch.setattr(convene._codex_quota, "admit", caller_bug)
    with pytest.raises(convene.ConveneError) as e:
        _persisted_plan("coding-ratification", project)
    assert "unknown use" in str(e.value)
    # CONTROL: the real admit in the same HOME and project builds. It needs its OWN session: the drifted
    # wrapper above ran the real admit first, so session "d2" has already spent its one slot.
    monkeypatch.setattr(convene._codex_quota, "admit", real_admit)
    assert _by_id(_persisted_plan("coding-ratification", project, session_id="d2-control"))["skeptic"]["provider"] == "codex"


def test_d2_one_session_takes_one_deliberation_slot_however_many_turns(tmp_path, capsys):
    # RE-POINTED at AMENDMENT 3 (D25): ONE codex seat = ONE slot, and research-synthesis is the
    # profile that still has exactly one. Two classes taking two slots is pinned separately in
    # test_a3_each_codex_model_class_takes_its_own_admission_once_per_session.
    project = _project(tmp_path, "proj-once")
    assert convene.main(_main_args(project, "--session-id", "once", **_ONE_CODEX_SEAT)) == 0
    capsys.readouterr()
    written = _written_plan(project, "once")
    sk = _by_id(written)["architect"]
    admitted = [r for r in _store_rows(project) if r.get("admitted") is True]
    assert [(r["key"], r["use"]) for r in admitted] == [("once", "deliberation")]
    assert sk["admission_id"] == admitted[0]["admission_id"]
    # A TURN CANNOT ADMIT: the stack the chair runs verbatim on every turn carries no admission step, and
    # reading the frozen plan again (the review, the run record) spends nothing.
    assert "--use" not in sk["guard_stack"] and "codex_quota" not in sk["guard_stack"] and "admit" not in sk["guard_stack"]
    for _turn in range(3):
        convene.render_pre_spend_review(written)
        convene.build_run_record(written)
    assert len(_store_rows(project)) == 1
    # the SAME session convened again cannot buy a second astra seat: budget_spent -> the declared Fable fallback
    again_out = tmp_path / "again" / "session-plan.json"
    assert convene.main(_main_args(project, "--session-id", "once", "--out", str(again_out), **_ONE_CODEX_SEAT)) == 0
    assert "astra substitutions recorded: 1 of 1 (use deliberation; provider gap: openai)" in capsys.readouterr().out
    ask = _by_id(json.loads(again_out.read_text(encoding="utf-8")))["architect"]
    assert (ask["provider"], ask["substitution_reason"]) == ("claude", "budget_spent")
    decisions = [(r["key"], r["admitted"], r["reason"]) for r in _store_rows(project) if r.get("kind") != "substitution"]
    assert decisions == [("once", True, "within_budget"), ("once", False, "budget_spent")]
    # the substitution row keys on the SESSION too (L9), and names no admission: a refusal replaces none
    subs = [r for r in _store_rows(project) if r.get("kind") == "substitution"]
    assert [(r["key"], r["cycle_id"], r["cycle_id_source"], r["use"], r["reason"], r["admission_id"]) for r in subs] == [
        ("once", "once", "explicit", "deliberation", "budget_spent", None)]
    assert ask["admission_id"] == [r for r in _store_rows(project) if r.get("admitted") is False][0]["admission_id"]
    # CONTROL: another session is its own budget — the slot is per session, not per project or per day
    assert convene.main(_main_args(project, "--session-id", "other", **_ONE_CODEX_SEAT)) == 0
    assert _by_id(_written_plan(project, "other"))["architect"]["provider"] == "codex"
    assert [r["key"] for r in _store_rows(project) if r.get("admitted") is True] == ["once", "other"]


def test_d2_two_codex_seats_of_one_class_share_the_sessions_one_admission(seat_home, tmp_path):
    _freeze_codex_on_std(seat_home)          # #302 WP-1: the subject needs ONE std class (see helper)
    contract, pdir, rdir = _clean_agy_arbiter_profile(tmp_path)            # TWO codex seats, both sol under the freeze
    project = _project(tmp_path, "proj-two")
    plan = convene.build_session_plan(contract, profiles_dir=pdir, roster_dir=rdir, session_id="two",
                                      project_root=project, record_admission=True)
    seats = _by_id(plan)
    assert (seats["skeptic"]["provider"], seats["builder"]["provider"]) == ("codex", "codex")
    rows = _store_rows(project)
    assert [(r["key"], r["model_class"], r["admitted"]) for r in rows] == [("two", "std", True)]
    assert seats["skeptic"]["admission_id"] == seats["builder"]["admission_id"] == rows[0]["admission_id"]
    assert "admission_id" not in seats["architect"]


def test_d2_seats_serving_different_model_classes_are_admitted_separately(seat_home, tmp_path):
    """D16: the class is part of the budget, so a TOP seat and a std seat would take one admission EACH.
    RE-POINTED by the astra reserve (roster rev 4): no avengers codex seat serves the TOP class any more (the
    `main` member is the Sol literal at every size), so a roster whose TOP lacks `medium` changes nothing and
    both member seats share ONE std admission. The two-class admission itself is codex_quota's (tested there)."""
    _no_codex_freeze(seat_home)
    entries = _live_like_codex_entries()
    entries[0]["supported_reasoning_levels"] = [{"effort": e, "description": e} for e in ("xhigh", "max")]
    _write_codex_roster(seat_home, entries)                                 # astra offers no `medium`
    contract, pdir, rdir = _clean_agy_arbiter_profile(tmp_path)
    project = _project(tmp_path, "proj-classes")
    plan = convene.build_session_plan(contract, profiles_dir=pdir, roster_dir=rdir, session_id="classes",
                                      project_root=project, record_admission=True)
    seats = _by_id(plan)
    assert (seats["skeptic"]["model"], seats["builder"]["model"]) == (MEMBER, MEMBER)
    rows = _store_rows(project)
    assert [(r["key"], r["model_class"], r["requested_model"], r["admitted"]) for r in rows] == [
        ("classes", "std", MEMBER, True)]
    assert seats["skeptic"]["admission_id"] == seats["builder"]["admission_id"] == rows[0]["admission_id"]


def test_d2_an_admission_refusal_recomputes_the_arbiter_without_codex(seat_home, tmp_path):
    """Amendment 1's recompute still fires when the substitution came from an ADMISSION refusal. Proven on
    coding-ratification, which declares no arbiter (WP-D3 keeps such profiles on today's algorithm), so this
    test pins no assumption about the declared-arbiter profiles WP-D3 changes."""
    project = _project(tmp_path, "proj-arb")
    control = _persisted_plan("coding-ratification", project, session_id="arb-control")
    assert (control["arbiter"]["provider"], control["arbiter"]["path"]) == ("claude", "fallback")       # CONTROL
    assert "unavailable at plan build" not in control["arbiter"]["constraint"]
    # RE-POINTED by #322: the refusal was an 80 % threshold; the session's spent `deliberation` slot is the
    # admission refusal that remains (unavailability is refused BEFORE admission, at plan time).
    assert codex_quota.admit("deliberation", "arb-refused", project_root=project, model_class="std")["admitted"]
    plan = _persisted_plan("coding-ratification", project, session_id="arb-refused")
    arb = plan["arbiter"]
    # AMENDMENT 3 put the recomputed arbiter on the CLEAN path (agy deliberated nowhere). #368 seats agy
    # again (the user-advocate), so with BOTH codex seats substituted by the refusal the recomputed arbiter
    # is agy on the FALLBACK path: claude holds the adversary, agy is the one non-adversarial provider. It
    # is still reachable only because the session is DEGRADED (ARBITER_INELIGIBLE_PROVIDERS bars it otherwise).
    assert (arb["provider"], arb["path"], arb["model"]) == ("agy", "fallback", "gemini-4-argon-high")
    assert "unavailable at plan build, excluded from both paths: ['codex']" in arb["constraint"]


# RE-POINTED by the astra reserve (roster rev 4): the `main` codex member is the Sol literal at EVERY size, so
# the size is still RECORDED (and still defaults to complex) but no longer moves the model or its class.
@pytest.mark.parametrize("flag,model,size,size_source,model_class", [
    ((), STD, "complex", "default", "std"),
    (("--size", "complex"), STD, "complex", "routing", "std"),
    (("--size", "medium"), STD, "medium", "routing", "std"),
    (("--size", "light"), STD, "light", "routing", "std"),
])
def test_d2_the_size_flag_defaults_to_complex(seat_home, tmp_path, capsys, flag, model, size, size_source, model_class):
    """D17: a caller passing nothing gets astra, recorded as the DEFAULT (not as an explicit complex, which
    is `routing`); light / medium get sol. CONTROL: --size medium serves sol, so the default is observable."""
    _no_codex_freeze(seat_home)                                              # the roster TOP serves, not a freeze
    project = _project(tmp_path, "proj-size")
    assert convene.main(_main_args(project, "--session-id", "sz", "--dry-run", *flag, **_ONE_CODEX_SEAT)) == 0
    assert f" -m {model} -c model_reasoning_effort=xhigh " in capsys.readouterr().out
    assert not codex_quota.budget_path_for(project).exists()
    assert convene.main(_main_args(project, "--session-id", "sz", *flag, **_ONE_CODEX_SEAT)) == 0
    assert _by_id(_written_plan(project, "sz"))["architect"]["model"] == model
    [row] = _store_rows(project)
    assert (row["size"], row["size_source"], row["model_class"], row["requested_model"]) == (size, size_source, model_class, model)


def test_d2_an_unsized_convene_ignores_forge_size_and_a_sized_one_follows_l7(seat_home, tmp_path):
    """Sizing stays OPT-IN (the seat_model convention): with no --size, `.forge/size` is not read and D17's
    complex holds. With one, L7 applies under --project-root: forge's size wins and a conflict takes the larger."""
    _no_codex_freeze(seat_home)
    project = _project(tmp_path, "proj-forge-size")
    (project / ".forge").mkdir()
    (project / ".forge" / "size").write_text("light\n", encoding="utf-8")
    unsized = _by_id(_persisted_plan("coding-ratification", project, session_id="unsized"))["skeptic"]
    sized = _by_id(_persisted_plan("coding-ratification", project, session_id="sized", size="medium"))["skeptic"]
    assert (unsized["model"], sized["model"]) == (MEMBER, MEMBER)      # the astra reserve: Sol at every size
    by_key = {r["key"]: r for r in _store_rows(project)}
    assert (by_key["unsized"]["size"], by_key["unsized"]["size_source"]) == ("complex", "default")
    assert (by_key["sized"]["size"], by_key["sized"]["size_source"]) == ("medium", "forge")     # larger of light, medium


def test_d2_an_unknown_size_is_a_usage_error_never_a_silent_default(capsys):
    with pytest.raises(SystemExit) as e:
        convene.main(["--profile", "coding-ratification", "--task", "t", "--size", "huge", "--dry-run"])
    assert e.value.code == 2 and "invalid choice" in capsys.readouterr().err
    for bad in ("huge", "", "COMPLEX", 3):
        with pytest.raises(convene.ConveneError) as ce:
            convene.build_session_plan({"profile": "coding-ratification", "task": "t"}, profiles_dir=_REAL_PROFILES,
                                       roster_dir=_REAL_ROSTER, size=bad)
        assert "size" in str(ce.value), bad
    # the vocabulary is the owner's, not a second literal
    assert tuple(convene.SIZES) == tuple(codex_quota.SIZES) == tuple(seat_model.SIZES)


def test_d2_the_dry_run_decides_check_only_and_leaves_a_store_byte_unchanged(seat_home, tmp_path, capsys):
    # RE-POINTED at AMENDMENT 3 (D25): this test's subject is ONE codex seat taking ONE admission.
    # coding-ratification now holds TWO codex seats of different classes (and so takes two admissions,
    # covered by test_a3_each_codex_model_class_takes_its_own_admission_once_per_session);
    # research-synthesis is the profile that still has exactly one, so the subject is preserved.
    project = _project(tmp_path, "proj-dry")
    store = codex_quota.budget_path_for(project)
    lock = codex_quota.lock_path_for(store)
    # a LIVE-shaped store: an earlier admission for another session, with its .lock sidecar
    assert codex_quota.admit("deliberation", "earlier", project_root=project, model_class="std")["row_written"] is True
    before = (store.read_bytes(), sorted(p.name for p in store.parent.iterdir()),
              (lock.stat().st_ino, lock.stat().st_size, lock.stat().st_mtime_ns))
    # RE-POINTED by #322: the refusal was an 80 % THRESHOLD reading; a spent `dry` session slot is the
    # admission refusal that remains. It is recorded BEFORE `before` is taken, so the dry run's zero stands.
    assert codex_quota.admit("deliberation", "dry", project_root=project, model_class="std")["row_written"] is True
    before = (store.read_bytes(), sorted(p.name for p in store.parent.iterdir()),
              (lock.stat().st_ino, lock.stat().st_size, lock.stat().st_mtime_ns))
    assert convene.main(_main_args(project, "--session-id", "dry", "--dry-run", **_ONE_CODEX_SEAT)) == 0
    out = capsys.readouterr().out
    assert f"codex unavailable (budget_spent): architect served by claude/{MAIN} {_GAP_LINE}" in out.splitlines()   # it DECIDED
    after = (store.read_bytes(), sorted(p.name for p in store.parent.iterdir()),
             (lock.stat().st_ino, lock.stat().st_size, lock.stat().st_mtime_ns))
    assert after == before
    assert list(seat_home.rglob("astra-budget.jsonl")) == [store] and not (project / ".avengers").exists()
    # a bare build_session_plan is check-only too: its decision has no id to name
    plan = convene.build_session_plan({"profile": "research-synthesis", "task": "t"}, profiles_dir=_REAL_PROFILES,
                                      roster_dir=_REAL_ROSTER, project_root=project)
    assert _by_id(plan)["architect"]["admission_id"] is None and store.read_bytes() == before[0]
    # NEGATIVE CONTROL: the same command under the same reading WITHOUT --dry-run appends the refusal and its
    # substitution, so the zero above is a measurement that could have seen a write, not one blind to it
    assert convene.main(_main_args(project, "--session-id", "dry", **_ONE_CODEX_SEAT)) == 0
    assert store.read_bytes().startswith(before[0])
    assert [(r["key"], r.get("kind"), r.get("admitted"), r["reason"]) for r in _store_rows(project)] == [
        ("earlier", None, True, "within_budget"), ("dry", None, True, "within_budget"),
        ("dry", None, False, "budget_spent"), ("dry", "substitution", None, "budget_spent")]


def test_d2_the_admission_runs_in_process_once_per_build(seat_home, tmp_path, monkeypatch):
    _freeze_codex_on_std(seat_home)          # #302 WP-1: the subject needs ONE std class (see helper)
    import socket
    calls = []
    real_admit = convene._codex_quota.admit

    def spy(use, key, **kwargs):
        calls.append((use, key, kwargs.get("record"), kwargs.get("model_class"), kwargs.get("size"),
                      kwargs.get("size_source"), kwargs.get("role")))
        return real_admit(use, key, **kwargs)
    monkeypatch.setattr(convene._codex_quota, "admit", spy)

    def refuse(*_a, **_k):
        raise AssertionError("plan-time admission spawned a process or opened a socket")
    for name in ("run", "Popen", "call", "check_output"):
        monkeypatch.setattr(subprocess, name, refuse)
    monkeypatch.setattr(os, "system", refuse)
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    project = _project(tmp_path, "proj-inproc")
    _persisted_plan("coding-ratification", project, session_id="inproc")
    assert calls == [("deliberation", "inproc", True, "std", None, None, "consultant_main")]
    convene.build_session_plan({"profile": "coding-ratification", "task": "t"}, profiles_dir=_REAL_PROFILES,
                               roster_dir=_REAL_ROSTER, session_id="inproc-dry", project_root=project)
    assert calls[1:] == [("deliberation", "inproc-dry", False, "std", None, None, "consultant_main")]


def test_d2_the_admission_vocabulary_matches_the_harness_owners():
    assert convene.CODEX_ADMISSION_USE == convene.CODEX_SUBSTITUTION_USE == "deliberation"   # L9: one use, the session's
    assert convene.CODEX_ADMISSION_USE in codex_quota.USES
    assert dict(codex_quota.BUDGET_LIMITS["deliberation"]) == {"top": 1, "std": 1}           # design §2.2: 1 seat / session
    assert convene.CODEX_MEMBER_ROLE in codex_quota.ADMIT_ROLES
    for reason in ("threshold", "budget_spent", "budget_store_unavailable",
                   codex_quota.UNAVAILABLE_RATE_LIMIT_REACHED, codex_quota.UNAVAILABLE_QUOTA_EXHAUSTED):
        assert reason in codex_quota.SUBSTITUTION_REASONS


# --------------------------------------------------------------------------- #
# WP-D2 RESUME (plan revision 35, criterion RESUME_AFTER_PARTIAL (iii)) — the contract doc must not
# argue with the code
#
# WP-D2 made three statements in references/convene-contract.md false: "Not admit-gated (I11)",
# "Convene never calls `codex_quota.admit`" (with "only unavailability does") and substitution rows
# "keyed on `--project-root`'s `.forge/cycle-id`". test_the_docs_quote_the_review_line_verbatim could
# not see it: it asks for the SUBSTRING "admit-gated", which the stale claim itself supplies.
#
# SCOPE WAS DELIBERATE at the resume: convene-contract.md ONLY, because skills/avengers/SKILL.md (~line 163)
# still said "avengers seats are NOT admit-gated (I11)" and was WP-D3's to fix (plan ruling R5). WP-D3 fixed
# that line and appended SKILL.md to _D2_GUARDED_DOCS — one entry, recorded RED on SKILL.md before the fix —
# so this guard now reads both docs, asserting both halves on each.
#
# `.forge/cycle-id` is matched as a bare TOKEN, not as a phrase: convene has no relationship with that
# key since WP-D2 (its rows and its admission key on the session id), so the contract has no true
# sentence to say with it, and a token cannot be dodged by re-wording the stale claim. The cost is
# stated rather than hidden: a future true mention would have to change this test.
# --------------------------------------------------------------------------- #
#: The docs this guard reads. WP-D3 appended _AVENGERS_ROOT / "SKILL.md" (ruling R5) when it fixed SKILL.md's I11 line.
_D2_GUARDED_DOCS = (_AVENGERS_ROOT / "references" / "convene-contract.md", _AVENGERS_ROOT / "SKILL.md")

#: The retired I11 claims, each by the words a doc spells it with. Matched on whitespace-collapsed,
#: lower-cased text, so a claim re-wrapped across lines or re-cased is still found.
_D2_RETIRED_DOC_CLAIMS = {
    "not_admit_gated": "not admit-gated",
    "never_calls_admit": "never calls `codex_quota.admit`",
    "only_unavailability_substitutes": "only unavailability does",
    "forge_cycle_id_key": ".forge/cycle-id",
}

#: What the doc must say instead (criterion (ii)), so deleting the section cannot pass for fixing it.
_D2_REQUIRED_DOC_FACTS = {
    "the_in_process_admit_on_the_session_id": 'codex_quota.admit("deliberation", <session id>',
    "admitted_in_process_at_plan_build": "in-process at plan build",
    "dry_run_and_the_default_build_are_check_only": "check-only",
    "a_refusal_reason_substitutes": "`threshold`",
    "admission_id_on_the_seat": "`admission_id`",
}

#: The two passages as they stood BEFORE the resume (convene-contract.md 1fc0660d), VERBATIM. NEGATIVE
#: CONTROL only. Embedded rather than read through `git show`: this file runs in BOTH trees and
#: ~/.claude is not a git repository.
_PRE_D2_CONTRACT_PASSAGES = '''
**Budget rows.** `build_session_plan` and `--dry-run` write nothing. Only a persisted convene
(`main()` without `--dry-run`) records, after the plan and run record are written, one
`deliberation` substitution row per substituted seat through `seat_model.substitute(...)` into
`~/.claude/projects/<slug>/astra-budget.jsonl`, keyed on `--project-root`'s
`.forge/cycle-id` (else the adhoc key). A row never spends a budget. A row that cannot be
written is reported on stderr and never blocks the session (under-count, never invent).

**Honest limits.**
- **Not admit-gated (I11).** Convene never calls `codex_quota.admit`, so a ≥70% threshold or
  a spent consult budget never substitutes an avengers seat; only unavailability does.
'''


def _d2_normalized(text):
    return " ".join(text.split()).lower()


def _d2_retired_claims_in(text):
    norm = _d2_normalized(text)
    return sorted(name for name, needle in _D2_RETIRED_DOC_CLAIMS.items() if _d2_normalized(needle) in norm)


def _d2_missing_facts_in(text):
    norm = _d2_normalized(text)
    return sorted(name for name, needle in _D2_REQUIRED_DOC_FACTS.items() if _d2_normalized(needle) not in norm)


def test_d2_the_contract_doc_states_the_plan_time_admission_and_none_of_the_retired_i11_claims():
    for doc in _D2_GUARDED_DOCS:
        text = doc.read_text(encoding="utf-8")
        assert _d2_retired_claims_in(text) == [], f"{doc.name} still states a retired I11 claim"
        assert _d2_missing_facts_in(text) == [], f"{doc.name} does not state WP-D2's plan-time admission"


def test_d2_CONTROL_the_retired_claim_guard_fires_on_the_pre_resume_contract_text():
    """The guard has teeth, needle by needle: EVERY retired claim is found in the pre-resume text, and that
    text states none of the required facts. Then the two ways a guard like this goes wrong: a claim
    re-wrapped and re-cased (SKILL.md's own spelling) is still found, and a TRUE sentence that uses the
    words is not a claim — the guard keys on the negation, not on the term."""
    assert _d2_retired_claims_in(_PRE_D2_CONTRACT_PASSAGES) == sorted(_D2_RETIRED_DOC_CLAIMS)
    assert _d2_missing_facts_in(_PRE_D2_CONTRACT_PASSAGES) == sorted(_D2_REQUIRED_DOC_FACTS)
    assert _d2_retired_claims_in("HONEST LIMITS: avengers seats are NOT\n  admit-gated (I11), so") == ["not_admit_gated"]
    assert _d2_retired_claims_in("- **Admit-gated at plan time, once per session (closes I11).**") == []


# =========================================================================== #
# S081 revision 4, WP-D3 (design §3.4, D15 + D23; plan L2, L6, L11) — the composition and the DECLARED arbiter
#
# research-synthesis and website-ux take business-ideation's flip (codex = the visionary lead, a Fable main seat
# holds the adversary) and DECLARE their arbiter: `arbiter: {provider: claude, role: consultant_support}` with the
# top-level `arbiter_independence: separate-session` — Opus in a separate session. resolve_arbiter honours a
# declaration and enforces the RELAXED rule (the arbiter's MODEL differs from every seat's model; it runs in its
# own session) in place of the provider-exclusion rule. Profiles that declare nothing resolve exactly as before:
# the CONTROL below compares their whole arbiter object with the one captured from the base code.
#
# NOT YET HERE, recorded rather than hidden (the stage returned PARTIAL): business-ideation does not declare its
# arbiter — its economist seat resolves `opus`, the model a declared consultant_support arbiter resolves, so the
# relaxed rule refuses it — and coding-ratification.yaml, whose wall_clock_s the plan orders re-derived, is in no
# WP's files list. Both await a ruling; _D3_FLOORED_PROFILES grows when they land.
# =========================================================================== #
_D3_FLIPPED = ("research-synthesis", "website-ux")
# RE-POINTED at AMENDMENT 3: business-ideation can declare now that D26 moved its economist off opus, and
# writing-cv gained a declared arbiter (jc8), so FOUR profiles declare and coding-ratification is the ONE
# undeclared control left. That single remaining subject is what keeps the byte-for-byte proof below alive —
# if it ever declares too, the control must move to a synthetic profile rather than be dropped.
_D3_DECLARING = ("business-ideation", "research-synthesis", "website-ux", "writing-cv")
_D3_UNDECLARED_CONTROLS = ("coding-ratification",)
_D3_ALL_PROFILES = ("business-ideation", "research-synthesis", "website-ux", "coding-ratification", "writing-cv")
# AMENDMENT 3: all FIVE are floored now (the first run shipped three; business-ideation was blocked on B1
# and coding-ratification was in no WP's files at all — B2).
_D3_FLOORED_PROFILES = _D3_ALL_PROFILES
_D3_DECLARED = {"provider": "claude", "role": "consultant_support"}

#: The arbiter each undeclared profile resolved at the WP-D3 BASE (convene f8f23901, profiles and cards at HEAD),
#: under this file's seat_home fixture. CAPTURED by running that code, not written from the formula — the
#: byte-for-byte half of the control (key order included, because the plan is persisted with json.dumps).
_D3_BASE_FALLBACK_TEXT = ("fallback path — 'claude' deliberated (non-adversarially); its authorship is ANONYMIZED "
                          "but style-recognition self-preference is an ACCEPTED residual (flagged "
                          "fallback_arbiter_residual in run-record.json §6a)")
_D3_BASE_CONSTRAINT = ("external seatless arbiter; claude is the strongest-adjudication-prior NON-adversarial provider "
                       "(adversarial=['codex']); all providers deliberated -> fallback path (accepted residual)")


def _d3_base_arbiter(seat_class):
    return {
        "is_external": True, "cold_context": True, "path": "fallback", "provider": "claude", "effort": "default",
        "seat_class": seat_class, "effort_note": None, "model": MAIN, "seat_model_role": "arbiter",
        "timeout_s": 1200,
        "guard_stack": f"(claude host seat · model={MAIN} via seat_model arbiter · effort=default · non-CLI spawn, timeout 1200s)",
        "fallback_arbiter_residual": True, "excluded_authorship": _D3_BASE_FALLBACK_TEXT,
        "constraint": _D3_BASE_CONSTRAINT,
        "provenance": {"requested_selector": MAIN, "resolved_model": MAIN, "source": "harness_literal",
                       "roster_fetched_at": None, "roster_rev": ROSTER_REV},
    }


_D3_BASE_ARBITERS = {"coding-ratification": _d3_base_arbiter("ratification_arbiter")}


def _d3_profile(tmp_path, family, seats, *, arbiter=None, independence="separate-session", cards=(),
                semantics="generative", budgets=None):
    """A synthetic profile written through yaml.safe_dump over the standard roster (+ `cards`)."""
    rdir, pdir = tmp_path / f"roster-{family}", tmp_path / f"profiles-{family}"
    _std_roster(rdir)
    for card in cards:
        _write_card(rdir, *card)
    doc = {"schema": "avengers-profile.v1", "family": family, "seats": seats,
           "arbiter": dict({"effort_on_codex": "max"}, **(arbiter or {})),
           "phases": {"converge": {"semantics": semantics}},
           "outcome": {"type": ["decision"], "default": "decision"}}
    if independence is not None:
        doc["arbiter_independence"] = independence
    if budgets:
        doc["budgets"] = budgets
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{family}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return {"profile": family}, pdir, rdir


def _d3_real_doc(profile):
    return yaml.safe_load((_REAL_PROFILES / f"{profile}.yaml").read_text(encoding="utf-8"))


def _d3_write_doc(tmp_path, name, profile, doc):
    pdir = tmp_path / name
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{profile}.yaml").write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return pdir


@pytest.mark.parametrize("profile", _D3_FLIPPED)
def test_d3_a_flipped_profile_resolves_an_opus_arbiter_in_a_separate_session(profile):
    plan = _real_plan(profile)
    assert convene.schema_validate(plan, convene.load_schema()) == []
    seats = _by_id(plan)
    arch, sk = seats["architect"], seats["skeptic"]
    # D15: codex is the VISIONARY LEAD — consultant_main @ xhigh, not a challenger, not the adversary …
    assert (arch["provider"], arch["model"], arch["seat_model_role"], arch["effort"], arch["adversarial_role"]) == (
        "codex", MEMBER, "consultant_main", "xhigh", False)          # the astra reserve: Sol
    assert arch["seat_class"] != convene.CHALLENGER_FLOOR
    # … ALWAYS paired with a Fable main seat, which holds the adversary at the challenger floor
    assert (sk["provider"], sk["model"], sk["seat_model_role"], sk["seat_weight"], sk["adversarial_role"]) == (
        "claude", MAIN, "consultant_main", "main", True)
    assert (sk["effort"], sk["seat_class"]) == ("default", convene.CHALLENGER_FLOOR)
    assert "no codex-equivalent anti-sycophancy floor for this provider" in sk["effort_note"]
    assert plan["quorum"]["adversarial_seats"] == ["skeptic"]
    # D23: the DECLARED arbiter — Opus through the protected consultant_support/claude row, in its own session
    arb = plan["arbiter"]
    assert (arb["provider"], arb["model"], arb["seat_model_role"], arb["timeout_s"]) == (
        "claude", SUPPORT, "consultant_support", 600)
    assert (arb["selection"], arb["independence"]) == ("declared", "separate-session")
    assert arb["obligations"] == list(convene.DECLARED_ARBITER_OBLIGATIONS)
    # claude deliberated (it holds the adversary), so the residual stays flagged on the fallback path
    assert (arb["is_external"], arb["cold_context"], arb["path"], arb["fallback_arbiter_residual"]) == (
        True, True, "fallback", True)
    assert arb["guard_stack"] == (f"(claude host seat · model={SUPPORT} via seat_model consultant_support · effort=default "
                                  f"· non-CLI spawn, timeout 600s · {convene.SEPARATE_SESSION_LABEL})")
    assert arb["model"] not in {s["model"] for s in plan["seats"]}          # the relaxed rule, on the real profile
    assert "arbiter_independence: separate-session" in arb["constraint"]
    record = convene.build_run_record(plan)
    assert convene.schema_validate(record, convene.load_run_record_schema()) == []
    assert (record["arbiter"]["model"], record["arbiter"]["selection"], record["arbiter"]["independence"]) == (
        SUPPORT, "declared", "separate-session")
    review = convene.render_pre_spend_review(plan)
    assert "independence: separate-session" in review
    assert all(obligation in review for obligation in convene.DECLARED_ARBITER_OBLIGATIONS)


@pytest.mark.parametrize("profile", _D3_UNDECLARED_CONTROLS)
def test_d3_CONTROL_an_undeclared_profile_resolves_its_arbiter_exactly_as_at_the_base(profile):
    doc = _d3_real_doc(profile)
    assert convene.declared_arbiter(doc) is None
    plan = _real_plan(profile)
    base = _D3_BASE_ARBITERS[profile]
    assert plan["arbiter"] == base
    assert json.dumps(plan["arbiter"], ensure_ascii=False) == json.dumps(base, ensure_ascii=False)
    assert "independence:" not in convene.render_pre_spend_review(plan)
    record = convene.build_run_record(plan)
    assert not {"selection", "independence", "obligations"} & set(record["arbiter"])


def test_d3_a_declared_arbiter_that_shares_a_model_with_a_seat_is_refused(tmp_path):
    # the relaxed rule still has teeth: an Opus arbiter over an Opus (support-weight claude) member seat
    cards = [("economist", "claude", "default", False, True)]
    seats = [
        {"ref": "skeptic", "provider": "claude", "effort": "challenger_floor", "adversarial_role": True,
         "seat_weight": "main"},
        {"ref": "economist", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
        {"ref": "architect", "provider": "codex", "effort": "xhigh"},
    ]
    with pytest.raises(convene.ConveneError) as e:
        _build(_d3_profile(tmp_path, "shared", seats, arbiter=_D3_DECLARED, cards=cards))
    msg = str(e.value)
    assert f"'{SUPPORT}'" in msg and "['economist']" in msg and "arbiter_independence: separate-session" in msg
    # CONTROL: the same profile with that seat on a Fable main weight resolves the declared Opus arbiter
    seats[1] = dict(seats[1], seat_weight="main")
    plan = _build(_d3_profile(tmp_path, "distinct", seats, arbiter=_D3_DECLARED, cards=cards))
    assert (plan["arbiter"]["model"], plan["arbiter"]["independence"]) == (SUPPORT, "separate-session")


def test_d3_one_agy_family_version_at_two_levels_is_one_model(tmp_path):
    assert convene.model_identity("agy", "gemini-4-argon-high") == convene.model_identity("agy", "gemini-4-argon-medium")
    assert convene.model_identity("agy", "gemini-4-argon-high") != convene.model_identity("agy", "gemini-3.7-argon-high")
    assert convene.model_identity("claude", "opus") != convene.model_identity("claude", "fable")
    seats = [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh", "adversarial_role": True},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ]
    declared = {"provider": "agy", "role": "arbiter"}
    with pytest.raises(convene.ConveneError) as e:
        _build(_d3_profile(tmp_path, "argon", seats, arbiter=declared))
    assert "'gemini-4-argon-high'" in str(e.value) and "['operator']" in str(e.value)
    # CONTROL: with no agy member seat the same declared argon-high arbiter resolves
    seats[2] = {"ref": "operator", "provider": "claude", "effort": "default"}
    plan = _build(_d3_profile(tmp_path, "noargon", seats, arbiter=declared))
    assert (plan["arbiter"]["provider"], plan["arbiter"]["model"]) == ("agy", "gemini-4-argon-high")


def test_d3_a_declared_arbiter_does_not_rescue_a_profile_with_no_adversarial_seat(tmp_path):
    seats = [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh", "adversarial_role": False},
        {"ref": "architect", "provider": "claude", "effort": "default", "seat_weight": "main"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ]
    with pytest.raises(convene.ConveneError) as e:
        _build(_d3_profile(tmp_path, "noadv", seats, arbiter=_D3_DECLARED))
    assert "no adversarial_role seat" in str(e.value)
    # CONTROL: the same profile with its skeptic adversarial builds, on the declared arbiter
    seats[0] = dict(seats[0], adversarial_role=True)
    assert _build(_d3_profile(tmp_path, "adv", seats, arbiter=_D3_DECLARED))["arbiter"]["selection"] == "declared"


_D3_VOCABULARY_BREAKS = {
    "unknown_arbiter_key": (lambda d: d["arbiter"].update(provder="claude"), "unknown key(s) ['provder']"),
    "declaration_without_independence": (lambda d: d.pop("arbiter_independence"), "without arbiter_independence"),
    "independence_without_a_role": (lambda d: d["arbiter"].pop("role"), "needs BOTH arbiter.provider and arbiter.role"),
    "independence_without_a_declaration": (lambda d: [d["arbiter"].pop(k) for k in ("provider", "role")],
                                           "needs BOTH arbiter.provider and arbiter.role"),
    "unknown_independence": (lambda d: d.update(arbiter_independence="same-session"),
                             "unknown arbiter_independence 'same-session'"),
    "independence_inside_the_arbiter_block": (
        lambda d: d["arbiter"].update(arbiter_independence=d.pop("arbiter_independence")), "TOP-LEVEL"),
    "unknown_role": (lambda d: d["arbiter"].update(role="code_reviewer"), "declared arbiter role 'code_reviewer'"),
    "unknown_provider": (lambda d: d["arbiter"].update(provider="gemini"), "declared arbiter provider 'gemini'"),
}


@pytest.mark.parametrize("name", sorted(_D3_VOCABULARY_BREAKS))
def test_d3_the_arbiter_vocabulary_is_closed_and_half_a_declaration_fails_closed_before_any_admission(tmp_path, name):
    mutate, needle = _D3_VOCABULARY_BREAKS[name]
    doc = _d3_real_doc("research-synthesis")
    mutate(doc)
    pdir = _d3_write_doc(tmp_path, f"broken-{name}", "research-synthesis", doc)
    project = _project(tmp_path, "vocab")
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "research-synthesis", "task": "t"}, profiles_dir=pdir,
                                   roster_dir=_REAL_ROSTER, project_root=project, record_admission=True)
    assert needle in str(e.value)
    assert not codex_quota.budget_path_for(project).exists()              # refused before the admission recorded
    # CONTROL: the unbroken profile records its admission on the same persisted path
    convene.build_session_plan({"profile": "research-synthesis", "task": "t"}, profiles_dir=_REAL_PROFILES,
                               roster_dir=_REAL_ROSTER, project_root=project, record_admission=True)
    assert codex_quota.budget_path_for(project).exists()


def test_d3_the_inert_and_consumed_arbiter_keys_still_load_on_every_undeclared_profile():
    for profile in _D3_ALL_PROFILES:
        doc = _d3_real_doc(profile)
        assert set(doc.get("arbiter") or {}) <= convene.ARBITER_BLOCK_KEYS, profile
        if convene.declared_arbiter(doc) is None:
            assert _real_plan(profile)["arbiter"].get("selection") is None, profile


def test_d3_a_declared_arbiter_whose_provider_is_unavailable_fails_closed_never_reselected(seat_home, codex_on_path,
                                                                                        tmp_path):
    seats = [
        {"ref": "skeptic", "provider": "claude", "effort": "challenger_floor", "adversarial_role": True,
         "seat_weight": "main"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ]
    fixture = _d3_profile(tmp_path, "codexarb", seats, arbiter={"provider": "codex", "role": "arbiter"})
    # CONTROL: available, the declared codex arbiter serves with its declared role
    arb = _build(fixture)["arbiter"]
    assert (arb["provider"], arb["seat_model_role"], arb["model"], arb["selection"]) == (
        "codex", "arbiter", MEMBER, "declared")
    _signal("rate_limit_reached", seat_home, codex_on_path)
    with pytest.raises(convene.ConveneError) as e:
        _build(fixture)
    assert "unavailable" in str(e.value) and "never silently replaced" in str(e.value)


@pytest.mark.parametrize("profile", _D3_FLOORED_PROFILES)
def test_d3_a_shipped_profile_is_at_or_above_its_derived_floor(tmp_path, profile):
    text = (_REAL_PROFILES / f"{profile}.yaml").read_text(encoding="utf-8")
    shipped = yaml.safe_load(text)["budgets"]["wall_clock_s"]
    plan = _real_plan(profile)
    wc = plan["wall_clock_floor"]
    assert (wc["requested_from"], wc["requested_s"], wc["raised"], wc["note"]) == ("profile", shipped, False, None)
    assert plan["budgets"]["wall_clock_s"] == shipped >= wc["floor_s"]
    # the floor is the formula over THIS plan's resolved timeouts: the arbiter's plus two turns of the slowest
    # external member seat — named here, not assumed from the profile's comment
    external = [s["timeout_s"] for s in plan["seats"] if s["provider"] in ("codex", "agy")]
    assert wc["floor_s"] == plan["arbiter"]["timeout_s"] + 2 * max(external)
    assert f"= {wc['floor_s']}" in text                                    # the comment shows its own arithmetic
    # a light / medium convene serves sol, whose xhigh ceiling is astra's: the shipped value covers every size
    for size in ("light", "medium"):
        sized = convene.build_session_plan({"profile": profile, "task": "t"}, profiles_dir=_REAL_PROFILES,
                                           roster_dir=_REAL_ROSTER, size=size, project_root=tmp_path)
        assert sized["wall_clock_floor"]["raised"] is False, size
    # CONTROL: one second below its floor, the same profile is raised with the note
    doc = yaml.safe_load(text)
    doc["budgets"]["wall_clock_s"] = wc["floor_s"] - 1
    low = _real_plan(profile, profiles_dir=_d3_write_doc(tmp_path, "lowered", profile, doc))
    lwc = low["wall_clock_floor"]
    assert (lwc["raised"], low["budgets"]["wall_clock_s"]) == (True, wc["floor_s"])
    assert lwc["note"].startswith(
        f"wall_clock_s {wc['floor_s'] - 1} (from profile) is below the derived floor {wc['floor_s']}")
    assert f"note : {lwc['note']}" in convene.render_pre_spend_review(low)


_D3_TABLE_START = "<!-- composition-table:start (test_convene.py pins these rows to the profiles on disk) -->"
_D3_TABLE_END = "<!-- composition-table:end -->"
#: #291 WP-6: the table names the Claude TIER, not a model (design s3.8 — docs name tiers), so the
#: next roster swap edits model_roster.py and never this table.
#: #368 added the "agy seat" column: every profile seats exactly one agy seat, named with its seat_weight.
_D3_TABLE_HEADER = ("Profile", "codex seats", "paired Claude main-tier seat", "agy seat", "arbiter")
#: How the SKILL.md table and the quoted review line spell each Claude tier.
_TIER_NAME = {MAIN: "Claude main tier", SUPPORT: "Claude support tier"}


def _d3_table_rows(text):
    block = text.split(_D3_TABLE_START, 1)[1].split(_D3_TABLE_END, 1)[0]
    rows = {}
    for line in block.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = tuple(c.strip() for c in line.strip().strip("|").split("|"))
        if cells == _D3_TABLE_HEADER or all(set(c) <= set("-: ") for c in cells):
            continue
        rows[cells[0].strip("`")] = cells[1:]
    return rows


#: How a codex seat is labelled in the SKILL.md table. AMENDMENT 3 added the second class, so
#: "visionary lead" no longer describes every non-adversarial codex seat — the supporting one is `support`.
_D3_CODEX_LABELS = {"consultant_main": "visionary lead", "consultant_support": "support"}


def _d3_expected_row(plan):
    codex = ", ".join(
        f"{s['seat_id']} ({'adversary' if s['adversarial_role'] else _D3_CODEX_LABELS[s['seat_model_role']]})"
        for s in plan["seats"] if s["provider"] == "codex")
    main_seats = ", ".join(s["seat_id"] for s in plan["seats"]
                           if s["provider"] == "claude" and s["model"] == MAIN and s["seat_weight"] == "main")
    agy = ", ".join(f"{s['seat_id']} ({s['seat_weight']})" for s in plan["seats"] if s["provider"] == "agy")
    a = plan["arbiter"]
    name = (_TIER_NAME.get(a["model"], a["model"]) if a["provider"] == "claude"
            else "agy argon" if a["provider"] == "agy" else a["model"])
    how = "separate session" if a.get("independence") == "separate-session" else f"selected, {a['path']} path"
    return (codex, main_seats, agy, f"{name} ({a['provider']} {a['seat_model_role']}), {how}")


def _d3_table_mismatches(text, plans):
    rows = _d3_table_rows(text)
    out = {name: (rows.get(name), _d3_expected_row(plan)) for name, plan in plans.items()
           if rows.get(name) != _d3_expected_row(plan)}
    out.update({name: (rows[name], None) for name in rows if name not in plans})
    return out


def test_d3_the_skill_composition_table_matches_the_profiles_on_disk():
    assert sorted(p.stem for p in _REAL_PROFILES.glob("*.yaml")) == sorted(_D3_ALL_PROFILES)
    plans = {name: _real_plan(name) for name in _D3_ALL_PROFILES}
    text = (_AVENGERS_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert sorted(_d3_table_rows(text)) == sorted(_D3_ALL_PROFILES)
    assert _d3_table_mismatches(text, plans) == {}
    # astra is ALWAYS paired with a Claude main-tier seat (#291: "a Fable main seat" before the roster
    # swap). RE-POINTED at AMENDMENT 3: the old form asserted
    # "exactly one codex seat" by counting brackets, which the second codex class now breaks. The property
    # D15 actually buys is that there is exactly ONE consultant_main (astra) codex seat and a Claude main-tier
    # seat beside it — a supporting sol seat does not dilute that pairing, and an accidental SECOND astra
    # seat would. It would NOT draw the astra allowance twice (D21 f5): two seats of one model class SHARE
    # the session's one admission for that class (jc6, a known limit, pinned by
    # test_d2_two_codex_seats_of_one_class_share_the_sessions_one_admission), so what keeps a second astra
    # seat out of the shipped profiles is the roles.count("consultant_main") == 1 assertion below, not the budget.
    for name, plan in plans.items():
        codex_cell, main_cell, agy_cell, _arbiter = _d3_expected_row(plan)
        assert agy_cell.count("(") == 1, (name, agy_cell)          # #368: exactly one agy seat per profile
        roles = [s["seat_model_role"] for s in plan["seats"] if s["provider"] == "codex"]
        assert roles.count("consultant_main") == 1, (name, roles)
        assert roles.count("consultant_support") <= 1, (name, roles)
        assert main_cell, name
        assert codex_cell.count("(") == len(roles), (name, codex_cell)
    # CONTROL: the same comparator catches a table that swapped two profiles' codex seats
    rows = _d3_table_rows(text)
    doctored = text.replace(" | ".join(("research-synthesis",) + rows["research-synthesis"]),
                            " | ".join(("research-synthesis", rows["coding-ratification"][0]) + rows["research-synthesis"][1:]))
    assert doctored != text
    assert set(_d3_table_mismatches(doctored, plans)) == {"research-synthesis"}


def _d3_profile_prose(profile):
    """A profile's text with each line's leading YAML comment marker removed, whitespace-collapsed and lower-cased,
    so a sentence wrapped across comment lines is matched whole."""
    lines = (_REAL_PROFILES / f"{profile}.yaml").read_text(encoding="utf-8").splitlines()
    return _d2_normalized("\n".join(line.strip().lstrip("#") for line in lines))


@pytest.mark.parametrize("profile", ("business-ideation",) + _D3_FLIPPED)
def test_d3_the_trip_wire_and_its_no_counter_caveat_travel_with_every_visionary_profile(profile):
    text = _d3_profile_prose(profile)
    for needle in ("overturns the arbiter's decision in 2 of the first 3", "no automated counter exists",
                   "count these sessions by hand"):
        assert needle in text, (profile, needle)


@pytest.mark.parametrize("profile", _D3_UNDECLARED_CONTROLS)
def test_d3_CONTROL_the_trip_wire_needles_do_not_match_an_unflipped_profile(profile):
    text = _d3_profile_prose(profile)
    assert "overturns the arbiter's decision in 2 of the first 3" not in text


def test_d3_the_writing_cv_wordsmith_is_its_fable_main_seat_and_no_other_profile_seats_it():
    seating = sorted(p.stem for p in _REAL_PROFILES.glob("*.yaml")
                     if any((s or {}).get("ref") == "wordsmith" for s in yaml.safe_load(p.read_text(encoding="utf-8"))["seats"]))
    assert seating == ["writing-cv"]
    card = yaml.safe_load((_REAL_ROSTER / "wordsmith.yaml").read_text(encoding="utf-8"))
    assert card["seat_weight"] == "main" and "seat_weight" not in card["provider"]
    ws = _by_id(_real_plan("writing-cv"))["wordsmith"]
    assert (ws["provider"], ws["model"], ws["seat_model_role"], ws["seat_weight"]) == (
        "claude", MAIN, "consultant_main", "main")


def _d3_missing_obligations(text):
    norm = _d2_normalized(text)
    return [o for o in convene.DECLARED_ARBITER_OBLIGATIONS if _d2_normalized(o) not in norm]


def test_d3_the_declared_arbiter_obligations_are_in_the_plan_the_profiles_and_the_skill_contract():
    assert [o.split()[0] for o in convene.DECLARED_ARBITER_OBLIGATIONS] == ["cite", "may", "send"]
    assert _d3_missing_obligations((_AVENGERS_ROOT / "SKILL.md").read_text(encoding="utf-8")) == []
    declaring = []
    for p in sorted(_REAL_PROFILES.glob("*.yaml")):
        if convene.declared_arbiter(yaml.safe_load(p.read_text(encoding="utf-8"))) is not None:
            declaring.append(p.stem)
            assert _d3_missing_obligations(_d3_profile_prose(p.stem)) == [], p.stem
    assert set(_D3_FLIPPED) <= set(declaring)
    # CONTROL: an arbiter that cannot abstain is caught by the same check
    assert _d3_missing_obligations("cite evidence for each ruling; send unresolved material disputes to the user") == [
        "may abstain"]


def test_d3_codex_unavailable_reason_no_longer_says_the_seat_is_not_admit_gated():
    doc = _d2_normalized(convene.codex_unavailable_reason.__doc__)
    assert _d2_retired_claims_in(doc) == []
    assert "admit-gated once, at plan build, against the session id" in doc
    # its other half is still true of THIS function and stays
    assert "a threshold or a spent budget is not unavailability" in doc


@_POSIX_SHELL
def test_d3_a_stub_launch_writes_its_stream_slots_beside_its_record_never_into_the_pytest_cwd(tmp_path, monkeypatch):
    cwd = tmp_path / "pytest-cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    stack = convene.guard_stack_for("codex", "xhigh")
    assert convene._STDOUT_SLOT in stack and convene._STDERR_SLOT in stack   # the slots are deliberately unfilled
    work = tmp_path / "work"
    work.mkdir()
    code, stderr = _run_stack(stack, _stub_bindir(tmp_path), work / "slots.argv")
    assert code == 0, stderr
    assert sorted(p.name for p in cwd.iterdir()) == []
    # POSITIVE CONTROL: the watchdog really wrote both slot files — beside the record, so "nothing leaked"
    # cannot be a stack that never ran
    assert {convene._STDOUT_SLOT, convene._STDERR_SLOT} <= {p.name for p in work.iterdir()}


# =========================================================================== #
# AMENDMENT 3 (D25-D28, user-approved 2026-09-19; docs/plans/2026-09-17-S081-revision-4-amendment-3.md).
# agy leaves every profile but research-synthesis and codex supplies the second provider, so ONE profile
# can now hold TWO codex seats of DIFFERENT model classes. These pin the composition itself, the budget
# consequence, the D18 fallback and D28's inline brief.
# =========================================================================== #
_A3_TWO_CODEX_PROFILES = ("business-ideation", "website-ux", "writing-cv", "coding-ratification")


def test_368_every_profile_seats_exactly_one_agy_seat_and_none_declares_an_agy_arbiter():
    """#368 (supersedes AMENDMENT 3 item (5), the D25 carve-out, and the test that pinned it,
    test_a3_research_synthesis_is_the_only_profile_that_seats_agy — renamed because its name became false).
    agy (Gemini 4 Argon) returns as ONE ADDED seat in each of the four profiles D25 emptied; research-synthesis
    keeps its operator. A CONTROL that fails if an agy seat appears, moves or multiplies anywhere.

    Written as a scan of every profile on disk rather than a list, so a SIXTH profile added later cannot slip
    an agy seat in unnoticed — the enumeration-vs-shape lesson this plan records twice.
    """
    seating_agy = {}
    for path in sorted(_REAL_PROFILES.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        refs = [s["ref"] for s in doc["seats"] if s.get("provider") == "agy"]
        if refs:
            seating_agy[path.stem] = refs
    assert seating_agy == {"research-synthesis": ["operator"], "business-ideation": ["user-advocate"],
                           "website-ux": ["operator"], "writing-cv": ["architect"],
                           "coding-ratification": ["user-advocate"]}
    # and it is a SEAT, never the arbiter: no profile declares an agy arbiter either
    for path in sorted(_REAL_PROFILES.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc.get("arbiter", {}).get("provider") != "agy", path.stem
    # resolved, not just declared: every profile really does seat its one agy seat, and the four #368 seats
    # deliberate on the main weight (consultant_main -> -high unsized); research-synthesis's stays support.
    for name, refs in seating_agy.items():
        plan = _real_plan(name)
        agy = [s for s in plan["seats"] if s["provider"] == "agy"]
        assert [s["seat_id"] for s in agy] == refs, name
        assert plan["arbiter"]["provider"] != "agy", name
        want = ("support", "consultant_support") if name == "research-synthesis" else ("main", "consultant_main")
        assert (agy[0]["seat_weight"], agy[0]["seat_model_role"]) == want, name


@pytest.mark.parametrize("size,level", [(None, "high"), ("light", "low"), ("medium", "medium"), ("complex", "high")])
def test_368_a_sized_convene_serves_the_agy_seat_the_size_level_and_pattern_1(tmp_path, size, level):
    """#368: the added agy seats are `seat_weight: main` (consultant_main -> -high unsized) and a SIZED convene serves
    model_roster.AGY_LEVEL_BY_SIZE (light -low, medium -medium, complex -high). Pattern 1 only: --sandbox, the
    prompt inline, stdin closed. The arbiter is never sized and never agy; research-synthesis's support-weight operator
    follows the same size map (unsized it stays -medium)."""
    project = _project(tmp_path, f"proj-368-{size}")
    for name, sid in (("business-ideation", "user-advocate"), ("website-ux", "operator"),
                      ("writing-cv", "architect"), ("coding-ratification", "user-advocate"),
                      ("research-synthesis", "operator")):
        plan = convene.build_session_plan({"profile": name, "task": "t"}, profiles_dir=_REAL_PROFILES,
                                          roster_dir=_REAL_ROSTER, session_id=f"s368-{name}", project_root=project,
                                          size=size)
        seat = _by_id(plan)[sid]
        want = "medium" if (name == "research-synthesis" and size is None) else level
        assert (seat["provider"], seat["model"]) == ("agy", f"gemini-4-argon-{want}"), (name, size)
        assert seat["guard_stack"] == (f'(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan '
                                       f'--model gemini-4-argon-{want} -p "…" < /dev/null)')
        assert "--dangerously-skip-permissions" not in seat["guard_stack"]
        assert plan["arbiter"]["provider"] == "claude", name


@pytest.mark.parametrize("profile", _A3_TWO_CODEX_PROFILES)
def test_a3_a_profile_holds_two_codex_seats_of_different_model_classes(seat_home, profile):
    """AMENDMENT 3 item (6): a profile holds a `main` seat on consultant_main and a `support` seat on
    consultant_support. RE-POINTED by the astra reserve (roster rev 4): consultant_main is the Sol literal now,
    so the two seats are two different MODELS (Sol and the support tier) in ONE model class (std), never astra.
    The name is kept for history; the property it pins now is "two models, one class, no TOP".
    """
    _no_codex_freeze(seat_home)
    plan = _real_plan(profile)
    codex = [s for s in plan["seats"] if s["provider"] == "codex"]
    assert len(codex) == 2, [s["seat_id"] for s in codex]
    by_role = {s["seat_model_role"]: s for s in codex}
    assert set(by_role) == {"consultant_main", "consultant_support"}
    assert by_role["consultant_main"]["model"] == MEMBER
    assert by_role["consultant_support"]["model"] == CODEX_SUP
    assert by_role["consultant_main"]["seat_weight"] == "main"
    assert by_role["consultant_support"]["seat_weight"] == "support"
    # ONE model class (std) and two distinct models: the reserve never reaches an avengers seat
    assert {seat_model.model_class_of(s["model"]) for s in codex} == {"std"}
    assert len({s["model"] for s in codex}) == 2
    # I6 + #302 JC-3: BOTH meter (no --ephemeral) — the support tier is metered like TOP
    assert "--ephemeral" not in by_role["consultant_main"]["guard_stack"]
    assert "--ephemeral" not in by_role["consultant_support"]["guard_stack"]


def test_a3_each_codex_model_class_takes_its_own_admission_once_per_session(seat_home, tmp_path):
    """AMENDMENT 3 item (6): `deliberation` admits ONCE PER MODEL CLASS per session (jc6) — astra and sol
    counted separately — and the astra allowance stays 1 per session behind the trip-wire."""
    assert dict(codex_quota.BUDGET_LIMITS["deliberation"]) == {"top": 1, "std": 1}   # 1 astra AND 1 sol
    _no_codex_freeze(seat_home)
    project = _project(tmp_path, "proj-a3-classes")
    plan = convene.build_session_plan({"profile": "business-ideation", "task": "t"},
                                      profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
                                      session_id="a3-classes", project_root=project, record_admission=True)
    rows = _store_rows(project)
    # RE-POINTED by the astra reserve (roster rev 4): both codex seats are the std class now (Sol and the
    # support tier), so the session takes exactly ONE std admission covering both models and both roles
    # (#302 s3.5) - once per class per session is unchanged, there is simply one class.
    assert [(r["key"], r["model_class"], r["admitted"]) for r in rows] == [("a3-classes", "std", True)]
    assert set(rows[0]["models"]) == {MEMBER, CODEX_SUP}
    assert set(rows[0]["roles"]) == {"consultant_main", "consultant_support"}
    seats = _by_id(plan)
    assert seats["architect"]["admission_id"] == seats["operator"]["admission_id"] == rows[0]["admission_id"]


def test_a3_a_refused_sol_seat_falls_back_to_a_fresh_fable_seat_not_to_opus(seat_home, codex_on_path):
    """AMENDMENT 3 item (6), D18: a refused SUPPORT codex seat falls back to FABLE.

    The trap this pins: the seat is support-weight, and a support-weight claude member seat resolves OPUS.
    The substitute is pinned to CODEX_SUBSTITUTE_ROLE instead, because it stands in for a codex seat rather
    than for a support-weight claude one — so the fallback is a fresh Fable seat, exactly as D18 says.
    """
    reason = _signal("cli_missing", seat_home, codex_on_path)
    op = _by_id(_real_plan("business-ideation"))["operator"]
    assert op["seat_weight"] == "support"                       # would resolve opus on its own weight
    assert (op["provider"], op["model"], op["seat_model_role"]) == ("claude", MAIN, "consultant_main")
    assert (op["substitute_for"], op["substitution_reason"], op["requested_model"]) == (
        "codex", reason, CODEX_SUP)
    assert op["guard_stack"] == _claude_label(MAIN, "consultant_main", 600)


def test_a3_a_declaring_profile_whose_seats_are_all_adversarial_does_not_fail_closed(tmp_path):
    """AMENDMENT 3 item (6) closes the ONE judgement call WP-D3's first run left untested (jc11).

    The relaxed rule REPLACES provider-exclusion with MODEL-exclusion, so the all-adversarial fail-closed —
    which exists because no NON-ADVERSARIAL PROVIDER remains to judge — no longer applies to a declaring
    profile: independence is established by the arbiter's model and its separate session, not by finding a
    provider that stayed out of the fight. That is a real relaxation and it is pinned here rather than left
    as a footnote. The CONTROL is the same profile with the declaration stripped, which still fails closed.
    """
    # THREE seats: the structural sub-quorum (LOW_QUORUM case (a)) needs >= 3 and fires before the
    # arbiter, so a two-seat fixture would prove nothing about the arbiter rule.
    seats = [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh", "adversarial_role": True,
         "seat_weight": "main"},
        {"ref": "architect", "provider": "claude", "effort": "default", "adversarial_role": True,
         "seat_weight": "main"},
        {"ref": "operator", "provider": "agy", "effort": "default", "adversarial_role": True},
    ]
    contract, pdir, rdir = _d3_profile(tmp_path, "alladv", seats, arbiter=dict(_D3_DECLARED))
    plan = convene.build_session_plan(contract, profiles_dir=pdir, roster_dir=rdir, session_id="alladv")
    arb = plan["arbiter"]
    assert (arb["provider"], arb["model"], arb["selection"], arb["independence"]) == (
        "claude", SUPPORT, "declared", "separate-session")
    assert arb["model"] not in {s["model"] for s in plan["seats"]}      # the teeth that remain
    assert plan["quorum"]["adversarial_seats"] == ["skeptic", "architect", "operator"]
    # CONTROL: strip the declaration and the SAME seats fail closed on the all-adversarial rule
    bare, bpdir, brdir = _d3_profile(tmp_path, "alladvbare", seats, independence=None)
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan(bare, profiles_dir=bpdir, roster_dir=brdir, session_id="alladvbare")
    assert "unsatisfiable" in str(e.value) and "adversarial" in str(e.value)


@pytest.mark.parametrize("profile", _A3_TWO_CODEX_PROFILES)
def test_a3_d28_a_codex_seat_launch_names_no_repository_path(seat_home, tmp_path, profile):
    """AMENDMENT 3 item (7) / D28: the codex seat launcher passes NO repository working directory — the
    envelope carries the evidence instead. Measured basis for D28: a repo-exploring codex seat cost
    95-115K tokens per call against ~21K for an inline-brief call.

    Pinned as a NEGATIVE on the launch string plus a POSITIVE on the prompt slot, so a future change that
    starts handing codex a repo path fails here rather than quietly tripling the session's token cost.
    """
    _no_codex_freeze(seat_home)
    project = _project(tmp_path, "proj-d28")
    plan = convene.build_session_plan({"profile": profile, "task": "t"}, profiles_dir=_REAL_PROFILES,
                                      roster_dir=_REAL_ROSTER, session_id="d28", project_root=project)
    codex = [s for s in plan["seats"] if s["provider"] == "codex"]
    assert codex
    for seat in codex:
        stack = seat["guard_stack"]
        # no repo path, by value or by flag
        assert str(project) not in stack
        assert str(_REAL_PROFILES.parent) not in stack.replace(str(convene._CODEX_WATCH), "")
        for flag in ("--add-dir", "--cd", " -C ", "--project-root", "--workdir"):
            assert flag not in stack, (flag, stack)
        # sandboxed read-only, and the ONLY payload is the chair-substituted prompt slot
        assert "-s read-only" in stack
        assert stack.endswith(f'"{convene._PROMPT_SLOT}"')
        assert stack.count(convene._PROMPT_SLOT) == 1


# =========================================================================== #
# S081 revision 4, D21 FIX ROUND 1 — WP-X6 (docs/reviews/2026-09-22-S081-rev4-review.md f2, f3, f4, f5 and the
# carried revision-5 item C174; plan L43, L44, L45). The avengers docs and convene's prose must say what the code
# does, as MEASURED in a fixture HOME with no codex freeze (the live host's state), not as a plan described it:
#   f2    four of the five shipped profiles seat TWO codex seats of two model classes (a TOP consultant_main seat
#         and a std consultant_support seat) and take TWO `deliberation` admissions per session, one per class;
#         research-synthesis seats one and takes one. Retired: "every shipped profile seats exactly one".
#   f3    D29's SCOPED bar: agy never arbitrates a HEALTHY session, stays the LAST-RESORT arbiter of a session
#         that has lost a provider (coding-ratification on any codex refusal: agy, clean path then; the fallback
#         path since #368 seated agy there), and a declared arbiter is not selection. Retired: the UNSCOPED "agy is never an arbiter",
#         "every arbiter is Claude" and "a session whose codex arm is refused becomes Claude-only".
#   C174  SKILL.md's "The round is a Claude + Google round": only research-synthesis keeps one.
#   f4    a persisted build that fails after its recorded admission keeps the row, so a retry with the SAME
#         session id is refused budget_spent (pinned by the CHARACTERIZATION test below — green at base by
#         design; the code change is filed for revision 5). Retired: "so it blocks nothing else".
#   f5    a COMMENT-only correction in test_d3_the_skill_composition_table_matches_the_profiles_on_disk: N/A for a
#         red. The behaviour it describes is pinned by test_d2_two_codex_seats_of_one_class_share_the_sessions_one_admission.
# The retired claims are REGEXES over whitespace-collapsed, lower-cased text (_d2_normalized), keyed on the UNSCOPED
# form so a TRUE scoped sentence that reuses the words does not trip them. convene.py is read as its PROSE only
# (docstrings and comments), never its code. The base passages are embedded VERBATIM from 13a3e04 — this file runs
# in BOTH trees and ~/.claude is not a git repository.
# =========================================================================== #
_X6_DOCS = {
    "SKILL.md": _AVENGERS_ROOT / "SKILL.md",
    "convene-contract.md": _AVENGERS_ROOT / "references" / "convene-contract.md",
    "dialogue-protocol.md": _AVENGERS_ROOT / "references" / "dialogue-protocol.md",
}

#: The retired claims. Each is the UNSCOPED form; the lookaheads let the same words through when a scope follows.
_X6_RETIRED_CLAIMS = {
    "f2_every_shipped_profile_seats_one": r"every shipped profile,? (?:which )?seats (?:exactly )?one\b(?! `?consultant_main)",
    "f2_each_seats_exactly_one_codex_seat": r"\beach seats exactly one codex seat",
    "f2_one_admission_for_every_shipped_profile": r"\bon(?:e|ce) (?:per session )?for every shipped profile",
    "f2_the_sessions_one_deliberation_slot": r"the session's (?:one|single) `?deliberation`? slot",
    "f3_agy_is_never_an_arbiter": r"agy is never an arbiter(?! (?:of|in|for) a healthy)",
    "f3_every_arbiter_is_claude": r"every arbiter is claude(?! (?:of|in|for) a healthy)",
    "f3_a_refused_codex_arm_makes_the_session_claude_only": r"codex arm is refused[^.]*?becomes \**claude-only",
    "c174_the_round_is_a_claude_google_round": r"the round is a claude \+ google round",
    "f4_blocks_nothing_else": r"blocks nothing else",
}

_X6_TWO_SEATS = "four of the five shipped profiles seat two codex seats"
#: RE-POINTED by the astra reserve (roster rev 4): both codex seats of the four two-seat profiles are std-class
#: now (Sol and the support tier), so the docs state ONE std-class admission per session, not two.
_X6_TWO_ADMISSIONS = "one std-class `deliberation` admission per session"
_X6_HEALTHY_BAR = "agy never arbitrates a healthy session"
_X6_LAST_RESORT = "last-resort arbiter"
_X6_DECLARED_IS_NOT_SELECTION = "a declared arbiter is not selection"
_X6_CLAUDE_ONLY_DELIBERATION = "claude-only deliberation"
#: #368: every profile seats agy again, so a codex outage leaves Claude + Google EVERYWHERE. This replaces C174's
#: "only research-synthesis keeps a Google round" fact; the docs state the Claude-only case as history.
_X6_GOOGLE_ROUND_EVERYWHERE = "every profile's codex outage still leaves a claude + google round"

#: What each doc must say instead, so deleting a passage cannot pass for correcting it.
_X6_REQUIRED_FACTS = {
    "SKILL.md": {
        "f2_four_of_five_seat_two_codex_seats": _X6_TWO_SEATS,
        "f2_two_admissions_per_session": _X6_TWO_ADMISSIONS,
        "f3_the_healthy_session_bar": _X6_HEALTHY_BAR,
        "f3_the_last_resort_arbiter": _X6_LAST_RESORT,
        "f3_a_declared_arbiter_is_not_selection": _X6_DECLARED_IS_NOT_SELECTION,
        "f3_a_claude_only_deliberation": _X6_CLAUDE_ONLY_DELIBERATION,
        "c368_every_profile_keeps_a_google_round": _X6_GOOGLE_ROUND_EVERYWHERE,
    },
    "convene-contract.md": {
        "f2_four_of_five_seat_two_codex_seats": _X6_TWO_SEATS,
        "f2_two_admissions_per_session": _X6_TWO_ADMISSIONS,
        "f4_a_retry_with_the_same_session_id": "a retry with the same session id",
        "f4_is_refused_budget_spent": "is refused `budget_spent`",
        "f4_the_remedy_a_fresh_session_id": "re-run with a fresh `--session-id`",
    },
    "dialogue-protocol.md": {
        "f3_the_healthy_session_bar": _X6_HEALTHY_BAR,
        "f3_the_last_resort_arbiter": _X6_LAST_RESORT,
        "f3_a_declared_arbiter_is_not_selection": _X6_DECLARED_IS_NOT_SELECTION,
        "f3_a_claude_only_deliberation": _X6_CLAUDE_ONLY_DELIBERATION,
        "c368_every_profile_keeps_a_google_round": _X6_GOOGLE_ROUND_EVERYWHERE,
    },
    "convene.py": {
        "f2_the_four_profiles_with_two_classes": "every shipped codex seat is std-class",   # the astra reserve
    },
}

_X6_BASE_PASSAGES = {
    "SKILL.md": (
        # skills/avengers/SKILL.md:172-176 at 13a3e04
        '''  `substitution_reason` and `requested_model` — BEFORE the structural validate. The arbiter
  is then chosen with codex EXCLUDED from both paths (nothing left → fail CLOSED). Never
  `gpt-5.6-sol`: it draws the same quota. The round is a Claude + Google round with the
  OpenAI provider gap named on the ONE pre-spend review line, e.g.
  `codex unavailable (rate_limit_reached): skeptic, operator served by claude/fable — provider gap: openai; arbiter recomputed`.
''',
        # skills/avengers/SKILL.md:179-183 at 13a3e04
        '''- ADMIT-GATED AT PLAN BUILD (S081 revision 4, WP-D2 — closes I11). The session id is minted before
  the substitution, and the codex seat is admit-gated once: admitted in-process at plan build with ONE
  `codex_quota.admit("deliberation", <session id>, size=…, model_class=…)` per session (one per
  model class; every shipped profile seats one codex seat). A refusal — a ≥70% `threshold`,
  `budget_spent`, `budget_store_unavailable` or an unavailable token — re-seats the seat through the
''',
        # skills/avengers/SKILL.md:190-191 at 13a3e04
        '''  HONEST LIMITS: the session's ONE `deliberation` slot covers every turn, so a trip-wire that trips
  mid-session is not seen by the frozen plan; a spent forge `consult` budget substitutes nothing (a
''',
        # skills/avengers/SKILL.md:216-217 at 13a3e04
        '''Every shipped profile seats exactly ONE codex seat, and codex is always paired with a Fable main seat
in the same profile. In the three idea profiles codex is the VISIONARY LEAD and a Fable skeptic holds
''',
        # skills/avengers/SKILL.md:239-244 at 13a3e04
        '''- **agy is never an arbiter** (`convene.ARBITER_INELIGIBLE_PROVIDERS`). Removing agy's seats is
  exactly what would have qualified it for the CLEAN arbiter path, so the bar is explicit rather than
  incidental. **Outside `research-synthesis`, avengers is a two-provider deliberation (Claude + codex)
  and every arbiter is Claude** — declared Opus in a separate session, or a recorded fallback residual
  for `coding-ratification`. A session whose codex arm is refused becomes Claude-only and its dissent
  record must say so. This is the accepted price of D25, recorded as a cost rather than an equivalence.
''',
    ),
    "convene-contract.md": (
        # skills/avengers/references/convene-contract.md:248-257 at 13a3e04
        '''**The plan-time admission (S081 revision 4, WP-D2; closes I11).** Convene is admit-gated once
per session. `build_session_plan` mints the session id first (the same `make_session_id`
expression, moved ahead of the substitution, so the id's value and derivation are unchanged).
Then, after each codex seat's pin and the plan-wide checks above, it calls
`codex_quota.admit("deliberation", <session id>, size=…, model_class=…)` in-process at plan
build. It never uses the `codex_quota.py admit` CLI, which is check-only by design and cannot
record. There is one decision per model class across the codex seats still standing, which is
one per session for every shipped profile (each seats exactly one codex seat). The budget is
the session's single `deliberation` slot for all of its turns, and no turn's guard stack
carries an admission step.
''',
        # skills/avengers/references/convene-contract.md:303-307 at 13a3e04
        '''- **One admission per model class per session.** A custom profile that seats N codex seats of
  one model class takes ONE slot for all N, not N slots. Every shipped profile seats exactly one.
- **A build that fails after its admission keeps the row.** A persisted build that fails once
  its admission is recorded leaves that row behind. It is keyed to a session that never ran,
  so it blocks nothing else.
''',
    ),
    "dialogue-protocol.md": (
        # skills/avengers/references/dialogue-protocol.md:130-147 at 13a3e04 — verbatim except ONE elision (#368):
        # the retired agy slug the base quoted is replaced by "<the agy family of the day>"; no needle reads it.
        '''**agy is NEVER AN ARBITER (S081 revision 4, amendment 3 D25 + D23), and it is barred from
SELECTION in code** (`convene.ARBITER_INELIGIBLE_PROVIDERS`), not merely absent by accident.
This is the half of D25 that is easy to miss: D25 removed agy's *seats* from every profile but
`research-synthesis`, and a provider with no seat is precisely what qualifies for the CLEAN
path — so the seat removal, left alone, would have **promoted agy from member to arbiter**.
Measured before the bar was added: `coding-ratification` resolved `agy <the agy family of the day>,
path clean`, in the one profile whose arbiter the amendment says is Fable.

The consequence is stated plainly rather than presented as equivalence: **outside
`research-synthesis`, avengers is a two-provider deliberation (Claude + codex) and EVERY
arbiter is Claude** — so the clean path is now unreachable for those four profiles and each
arbiter is either **DECLARED** (`business-ideation`, `website-ux`, `writing-cv`: Opus through
the protected `consultant_support` row, `arbiter_independence: separate-session`, context
independence standing in for provider independence) or a **recorded FALLBACK residual**
(`coding-ratification`: the selected Claude `arbiter` row, Fable, `fallback_arbiter_residual`).
`research-synthesis` keeps the one agy *seat* — as the research voice, never as the arbiter —
and declares Opus like the others. A session whose codex arm is refused by the trip-wire
becomes **Claude-only**, and its dissent record must say so (jc10).
''',
    ),
    "convene.py": (
        # skills/avengers/scripts/convene.py:60-64 at 13a3e04
        '''  - ADMITS the codex member seat AT PLAN TIME (S081 revision 4, WP-D2; design §3.4, §2.2 —
    closing I11). The session id is minted BEFORE the substitution, so each build makes ONE
    in-process codex_quota.admit("deliberation", <session id>, size=…, model_class=…) — once
    per session (per model class, which is one for every shipped profile), after the pin and
    the plan-wide checks (seat_model's `argv --use` order, J10). A REFUSAL (threshold,
''',
        # skills/avengers/scripts/convene.py:812-814 at 13a3e04
        '''# no call-time hook, so the codex seat is admit-gated ONCE, AT PLAN BUILD (S081 revision 4,
# WP-D2 — I11 closed): the session's one `deliberation` slot covers every turn, and a trip-wire
# that trips mid-session is not seen by a frozen plan (the same no-re-seating limit as below).
''',
        # skills/avengers/scripts/convene.py:1223-1226 at 13a3e04
        '''      3. otherwise — S081 revision 4, WP-D2 — the PLAN-TIME ADMISSION, when `admission` is given:
         ONE decision per model class across the seats still standing (so once per session for
         every shipped profile, which seats exactly one codex seat; codex_quota budgets the two
         classes separately, D16). Every seat the decision covers carries its `admission_id`
''',
    ),
}

#: Which retired claims each doc's base passages state — the per-site map the CONTROL asserts exactly.
_X6_BASE_CLAIMS = {
    "SKILL.md": {"f2_every_shipped_profile_seats_one", "f2_the_sessions_one_deliberation_slot",
                 "f3_agy_is_never_an_arbiter", "f3_every_arbiter_is_claude",
                 "f3_a_refused_codex_arm_makes_the_session_claude_only", "c174_the_round_is_a_claude_google_round"},
    "convene-contract.md": {"f2_every_shipped_profile_seats_one", "f2_each_seats_exactly_one_codex_seat",
                            "f2_one_admission_for_every_shipped_profile", "f2_the_sessions_one_deliberation_slot",
                            "f4_blocks_nothing_else"},
    "dialogue-protocol.md": {"f3_agy_is_never_an_arbiter", "f3_every_arbiter_is_claude",
                             "f3_a_refused_codex_arm_makes_the_session_claude_only"},
    "convene.py": {"f2_every_shipped_profile_seats_one", "f2_one_admission_for_every_shipped_profile",
                   "f2_the_sessions_one_deliberation_slot"},
}

#: TRUE sentences that reuse the retired claims' words with their scope. None may trip a needle.
_X6_TRUE_SCOPED_SENTENCES = (
    "agy never arbitrates a HEALTHY session: agy is never an arbiter in a healthy session.",
    "Outside research-synthesis every healthy-session arbiter is Claude, and every arbiter is Claude in a healthy session.",
    "A session whose codex arm is refused has a Claude-only deliberation in the four profiles with no agy seat.",
    "research-synthesis, which keeps its agy seat, is the profile whose codex outage still leaves a Claude + Google round.",
    "Every shipped profile seats exactly ONE `consultant_main` (astra) codex seat; research-synthesis seats exactly one codex seat.",
    "A failed build blocks a same-session-id retry, and nothing else.",
)


def _x6_convene_prose(path=_CONVENE):
    """convene.py's PROSE — every docstring and every comment, in that order — never its code."""
    import ast
    import io
    import tokenize
    source = Path(path).read_text(encoding="utf-8")
    docs = [ast.get_docstring(node, clean=False) for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
    comments = [tok.string.lstrip("#").lstrip(":") for tok in tokenize.generate_tokens(io.StringIO(source).readline)
                if tok.type == tokenize.COMMENT]
    return "\n".join([d for d in docs if d] + comments)


def _x6_retired_claims_in(text):
    import re
    norm = _d2_normalized(text)
    return {name for name, needle in _X6_RETIRED_CLAIMS.items() if re.search(needle, norm)}


def _x6_missing_facts(text, doc):
    norm = _d2_normalized(text)
    return {name for name, needle in _X6_REQUIRED_FACTS[doc].items() if needle not in norm}


def _x6_texts():
    texts = {name: path.read_text(encoding="utf-8") for name, path in _X6_DOCS.items()}
    texts["convene.py"] = _x6_convene_prose()
    return texts


def test_x6_the_docs_and_convenes_prose_state_none_of_the_retired_claims():
    """GUARD (D21 f2, f3, f4, C174): RED at 13a3e04, where every doc and convene's prose state at least one."""
    found = {doc: sorted(_x6_retired_claims_in(text)) for doc, text in _x6_texts().items()}
    assert found == {doc: [] for doc in found}


def test_x6_the_docs_and_convenes_prose_state_the_measured_facts():
    """GUARD (D21 f2, f3, f4, C174): the corrections are PRESENT, so deleting a passage is not a fix."""
    missing = {doc: sorted(_x6_missing_facts(text, doc)) for doc, text in _x6_texts().items()}
    assert missing == {doc: [] for doc in missing}


def test_x6_CONTROL_every_needle_fires_on_its_base_passages_and_no_true_scoped_sentence_trips_one():
    """Green at base BY DESIGN — the guard's teeth, needle by needle. Every base passage (embedded verbatim)
    states EXACTLY its recorded claims and none of its doc's required facts; together they state every
    claim. A claim re-wrapped and re-cased is still found, the prose extractor sees a comment and a
    docstring but not code, and a TRUE scoped sentence reusing the words trips nothing."""
    for doc, passages in _X6_BASE_PASSAGES.items():
        text = "".join(passages)
        assert _x6_retired_claims_in(text) == _X6_BASE_CLAIMS[doc], doc
        assert _x6_missing_facts(text, doc) == set(_X6_REQUIRED_FACTS[doc]), doc
    assert set().union(*_X6_BASE_CLAIMS.values()) == set(_X6_RETIRED_CLAIMS)
    assert _x6_retired_claims_in("AGY IS NEVER\n    AN ARBITER, and EVERY\n arbiter is Claude") == {
        "f3_agy_is_never_an_arbiter", "f3_every_arbiter_is_claude"}
    for sentence in _X6_TRUE_SCOPED_SENTENCES:
        assert _x6_retired_claims_in(sentence) == set(), sentence


def test_x6_CONTROL_the_prose_extractor_reads_docstrings_and_comments_and_never_code(tmp_path):
    module = tmp_path / "m.py"
    module.write_text('"""Every shipped profile seats exactly one codex seat."""\n'
                      "# so it blocks nothing else\n"
                      "X = 'the round is a Claude + Google round'\n", encoding="utf-8")
    assert _x6_retired_claims_in(_x6_convene_prose(module)) == {"f2_every_shipped_profile_seats_one",
                                                                "f4_blocks_nothing_else"}


def test_x6_the_facts_the_docs_quote_hold_for_every_shipped_profile(seat_home, codex_on_path, tmp_path, monkeypatch):
    """REGRESSION GUARD (green at base by design): the numbers the corrected docs quote, measured on the
    profiles on disk, so a profile edit that makes them false fails HERE rather than going stale in prose.
    No codex freeze: the roster TOP serves consultant_main, as on the live host (under a freeze to a std slug
    both roles serve one class and share ONE admission — test_d2_the_admission_runs_in_process_once_per_build)."""
    _no_codex_freeze(seat_home)
    calls = []
    real_admit = convene._codex_quota.admit

    def spy(use, key, **kwargs):
        calls.append((key, kwargs.get("model_class")))
        return real_admit(use, key, **kwargs)
    monkeypatch.setattr(convene._codex_quota, "admit", spy)
    project = _project(tmp_path, "proj-x6-facts")

    def build(name):
        del calls[:]
        return convene.build_session_plan({"profile": name, "task": "t"}, profiles_dir=_REAL_PROFILES,
                                          roster_dir=_REAL_ROSTER, session_id=f"x6-{name}", project_root=project)
    healthy = {}
    for name in _D3_ALL_PROFILES:
        plan = build(name)
        codex = [s for s in plan["seats"] if s["provider"] == "codex"]
        healthy[name] = (sorted(seat_model.model_class_of(s["model"]) for s in codex), sorted(calls),
                         (plan["arbiter"]["provider"], plan["arbiter"]["model"], plan["arbiter"].get("selection")))
    # FOUR of the five seat two codex seats of two classes and take two admissions, one per class, keyed on
    # the session; research-synthesis seats one and takes one
    assert sorted(_A3_TWO_CODEX_PROFILES + ("research-synthesis",)) == sorted(_D3_ALL_PROFILES)
    for name in _A3_TWO_CODEX_PROFILES:
        # the astra reserve (roster rev 4): both codex seats are std now -> ONE std admission per session
        assert healthy[name][:2] == (["std", "std"], [(f"x6-{name}", "std")]), name
    assert healthy["research-synthesis"][:2] == (["std"], [("x6-research-synthesis", "std")])
    # the HEALTHY-session bar: no shipped profile's arbiter is agy while codex serves
    assert {n: h[2] for n, h in healthy.items()} == {
        **{n: ("claude", SUPPORT, "declared") for n in _D3_DECLARING}, "coding-ratification": ("claude", MAIN, None)}
    assert not codex_quota.budget_path_for(project).exists()                  # check-only builds wrote nothing
    # a codex refusal of either kind: every codex seat re-seated; the agy-free profiles deliberate Claude-only,
    # research-synthesis keeps Claude + Google, and coding-ratification's arbiter is agy, the LAST RESORT
    # RE-POINTED by #322: the second setup was an 80 % THRESHOLD reading, which no longer refuses; a fresh
    # >= 99 % reading (quota_exhausted) is the codex refusal a high meter now produces.
    for setup in (lambda: _signal("rate_limit_reached", seat_home, codex_on_path),
                  lambda: _write_rollout(seat_home, 99.5, 20)):
        _no_signal(seat_home, codex_on_path)
        setup()
        refused = {name: build(name) for name in _D3_ALL_PROFILES}
        assert all(s["provider"] != "codex" for plan in refused.values() for s in plan["seats"])
        # RE-POINTED at #368: every profile seats agy again, so a refused session keeps Claude + Google
        # everywhere (it was Claude-only in the four profiles D25 emptied), and coding-ratification's last-resort
        # agy arbiter is on the FALLBACK path (agy deliberates) where it was clean.
        assert {n: sorted({s["provider"] for s in p["seats"]}) for n, p in refused.items()} == {
            n: ["agy", "claude"] for n in _D3_ALL_PROFILES}
        assert {n: (p["arbiter"]["provider"], p["arbiter"]["model"], p["arbiter"]["path"]) for n, p in refused.items()} == {
            **{n: ("claude", SUPPORT, "fallback") for n in _D3_DECLARING},
            "coding-ratification": ("agy", "gemini-4-argon-high", "fallback")}
    assert not codex_quota.budget_path_for(project).exists()


def test_x6_f4_CHARACTERIZATION_a_failed_persisted_build_keeps_its_admission_and_a_same_id_retry_loses_astra(
        seat_home, tmp_path, capsys):
    """CHARACTERIZATION — green at 13a3e04 BY DESIGN, never a red -> green (D21 f4, plan L44). The persisted path
    records the admission at plan build, BEFORE the build's later fail-closed checks: a build that then fails
    keeps an ADMITTED row keyed to its session id, and a retry with the SAME id is refused budget_spent and its
    astra seat re-seated on Fable. convene-contract.md states exactly this; recording the admission only after
    the last fail-closed check is filed for revision 5. Everything runs under the fixture HOME."""
    project = _project(tmp_path, "proj-x6-f4")
    bad_pin = json.dumps({"schema": "seat-model-pins.v1", "pins": {"agy": {"top": "gemini-3.1-pro-high"}}})
    # no codex freeze, so the architect is astra; the agy seat's pro pin fails the agy family rule AFTER the admission
    _write_pins(seat_home, raw=bad_pin)
    assert convene.main(_main_args(project, "--session-id", "x6-f4", profile="research-synthesis")) == 2
    err = capsys.readouterr().err
    assert "CONVENE FAIL-CLOSED" in err and "agy family rule" in err
    assert not (project / ".avengers").exists()                                # no session was written ...
    assert [(r["key"], r["use"], r["model_class"], r["requested_model"], r["admitted"]) for r in _store_rows(project)] == [
        ("x6-f4", "deliberation", "std", MEMBER, True)]      # the astra reserve: Sol                  # ... yet its admission stands
    # the operator fixes the pin and retries with the SAME --session-id: the class slot is already spent
    _no_codex_freeze(seat_home)
    assert convene.main(_main_args(project, "--session-id", "x6-f4", profile="research-synthesis")) == 0
    assert "astra substitutions recorded: 1 of 1" in capsys.readouterr().out
    arch = _by_id(_written_plan(project, "x6-f4"))["architect"]
    assert (arch["provider"], arch["model"], arch["substitution_reason"], arch["requested_model"]) == (
        "claude", MAIN, "budget_spent", MEMBER)
    # a GENERATED id is minute-resolution, so the same task re-run within the same minute is the same retry
    first, later = (datetime(2026, 9, 23, 2, 0, s, tzinfo=timezone.utc) for s in (5, 55))
    contract = {"profile": "research-synthesis", "task": "Same Task"}
    common = {"profiles_dir": _REAL_PROFILES, "roster_dir": _REAL_ROSTER, "project_root": project, "record_admission": True}
    _write_pins(seat_home, raw=bad_pin)
    with pytest.raises(convene.ConveneError):
        convene.build_session_plan(contract, now=first, **common)
    _no_codex_freeze(seat_home)
    retry = convene.build_session_plan(contract, now=later, **common)
    assert retry["session_id"] == "20260923-0200-same-task"
    assert _by_id(retry)["architect"]["substitution_reason"] == "budget_spent"
    # CONTROL, the contract's remedy: a fresh --session-id is admitted and seats astra
    assert convene.main(_main_args(project, "--session-id", "x6-f4-fresh", profile="research-synthesis")) == 0
    fresh = _by_id(_written_plan(project, "x6-f4-fresh"))["architect"]
    assert (fresh["provider"], fresh["model"]) == ("codex", MEMBER) and "substitute_for" not in fresh


# =========================================================================== #
# S081 revision 4, D21 FIX ROUND 2 — WP-Y3 (docs/reviews/2026-09-22-S081-rev4-review.md R2-15 and R2-16; plan
# L57, L58). The same guard pattern as the X6 family above, for two items the round-1 stage found:
#   R2-15  seven sites said where coding-ratification's arbiter lands as if it held for every session. MEASURED
#          (progress/.golden-rev4/fix-round-2/y3-measure.json, a fixture HOME seeded with the live roster): the
#          profile seats two provider families (codex, claude); a healthy session takes the FALLBACK path
#          (claude `arbiter`, Fable, residual flagged) because agy is barred from a healthy session's selection;
#          every codex refusal measured (rate_limit_reached, quota_exhausted, cli_missing, a threshold or
#          budget_spent admission refusal, a roster with no eligible TOP model) takes the CLEAN path on agy.
#   R2-16  the contract's "## External arbiter" section never stated the agy bar, D29's scope or the D23
#          declared arbiter, and its opening MUST was unscoped (four of five shipped profiles declare).
# The needles are REGEXES over whitespace-collapsed, lower-cased text (_d2_normalized), keyed on the UNSCOPED
# form. Where each is searched: the whole contract; convene.py's PROSE (_x6_convene_prose); the COMMENTS of
# coding-ratification.yaml (never a value); test_arbiter_external.py's prose; and THIS file's COMMENTS only,
# so the base passages below, which are string constants, are never read by the scan. The base passages are
# embedded VERBATIM from 615231b — this file runs in BOTH trees and ~/.claude is not a git repository.
# =========================================================================== #
_Y3_CONTRACT = _AVENGERS_ROOT / "references" / "convene-contract.md"
_Y3_PROFILE = _AVENGERS_ROOT / "profiles" / "coding-ratification.yaml"
_Y3_ARBITER_TESTS = _AVENGERS_ROOT / "tests" / "test_arbiter_external.py"
_Y3_THIS_FILE = Path(__file__).resolve()

#: The retired claims, each in its UNSCOPED form (a lookahead lets a trailing healthy-session scope through).
_Y3_RETIRED_CLAIMS = {
    "r2_15_pins_all_three_families": r"\bpin(?:s|ning) all (?:three|3) families",
    "r2_15_always_lands_on_the_fallback": (r"\**always\**\s+(?:lands|takes)\s+(?:here|on\s+the\s+fallback|the\s+fallback)"
                                           r"(?!(?:\s+path)?,?\s+(?:only\s+)?(?:in|for|while|during)\s+a\s+healthy)"),
    "r2_15_the_coding_ratification_reality": r"the coding-ratification reality",
    "r2_15_losing_agy_did_not_change_the_path": r"losing agy did not change the path",
    "r2_15_fallback_means_all_providers_deliberated": r"fallback path\**\s*(?:=|—|-|:)?\s*all providers deliberated",
    "r2_16_the_unscoped_must_differ": r"never inherited from a seat\**,? and must differ from",
}

#: What every one of the seven R2-15 sites must state instead, so deleting a sentence is not a correction.
_Y3_SITE_FACTS = {
    "r2_15_the_fallback_is_a_healthy_session_property": "in a healthy session coding-ratification lands",
    # RE-POINTED at #368: agy holds a coding-ratification seat again, so the degraded arbiter is agy on the
    # FALLBACK path (it was the clean path while D25 left agy seatless). The key is kept for history.
    "r2_15_agy_on_the_clean_path_under_any_codex_refusal": "under any codex refusal its arbiter is agy on the fallback path",
}

#: What the contract's External-arbiter SECTION must state (R2-16). The first four are the X6 phrases, so the
#: contract and dialogue-protocol.md cannot drift apart in wording.
_Y3_SECTION_FACTS = {
    "r2_16_the_bar_named_in_code": "arbiter_ineligible_providers",
    "r2_16_agy_never_arbitrates_a_healthy_session": _X6_HEALTHY_BAR,
    "r2_16_the_last_resort_arbiter": _X6_LAST_RESORT,
    "r2_16_a_declared_arbiter_is_not_selection": _X6_DECLARED_IS_NOT_SELECTION,
    "r2_16_d29_named_with_its_approval": "d29 (user-approved 2026-09-19)",
    "r2_16_the_declared_arbiter_is_held_to_the_relaxed_rule": "the relaxed rule",
    "r2_16_the_must_is_scoped_to_a_selected_arbiter": "a selected arbiter's provider must differ",
    "r2_16_fallback_over_eligible_providers": "no eligible provider is free of deliberation",
    "r2_16_all_adversarial_over_eligible_providers": "every eligible provider deliberated",
}

#: The files the retired-claim scan reads, each through its extractor.
_Y3_SCANNED = ("convene-contract.md", "convene.py prose", "coding-ratification.yaml comments",
               "test_arbiter_external.py prose", "test_convene.py comments")

#: The seven R2-15 sites, each the unit that must state the measured arbiter.
_Y3_SITES = ("convene-contract.md External arbiter", "convene.py module docstring",
             "convene.py resolve_arbiter docstring", "coding-ratification.yaml comments",
             "test_arbiter_external.py module docstring", "test_arbiter_external.py comments",
             "test_convene.py comments")

#: skills/avengers/references/convene-contract.md:68-119 at 615231b — the whole base External-arbiter section.
_Y3_BASE_CONTRACT_SECTION = '''## External arbiter (design §4, WP-2 — the highest-value fix)

The arbiter is a **fresh, persona-free, deliberation-EXTERNAL cold-context CALL** —
it did NOT file a position, argue, or ballot; it is NOT a promoted seat. Its
provider is **selected, never inherited from a seat**, and MUST differ from **every
deliberation seat's provider** (widened from adversarial-only):

- **CLEAN path** — a provider used by **no** deliberation seat is chosen: genuinely
  external, authorship linkage total-excluded, **no residual**.
- **FALLBACK path** — all providers deliberated (coding-ratification pins all three
  families, so it **always** lands here): the strongest-adjudication-prior
  **non-adversarial** provider is invoked cold-context. Authorship is anonymized,
  but style-recognition self-preference is an **ACCEPTED, DOCUMENTED residual**
  (arXiv 2410.21819), flagged `fallback_arbiter_residual: true` in
  `run-record.json` (§6a). We do not pretend the fallback is residual-free.
- **ALL-ADVERSARIAL** — every provider deliberated **and** every one is adversarial:
  no non-adversarial arbiter exists → **fail CLOSED** (`ConveneError`). This is the
  **only** unsatisfiable arbiter case; it never hangs.
- **UNAVAILABLE PROVIDERS** (S081 amendment 1 D6) — `resolve_arbiter(...,
  unavailable_providers=...)` excludes a provider that cannot serve a call at plan build
  (today only codex, when astra is unavailable) from **both** paths, and the `constraint`
  text names it. If nothing remains — e.g. the only non-adversarial provider was codex —
  the arbiter fails **CLOSED**, the same way.
- **NO ELIGIBLE ARBITER MODEL** (#282 R8) — when the chosen provider is codex and its
  roster lists no eligible TOP model for the arbiter's effort (`NoEligibleCodexModelError`:
  e.g. a profile with no codex member seat, so nothing at plan build evaluated the roster,
  or an arbiter `max` the members' effort did not need), codex is excluded and the selection
  is **recomputed once** — clean path, then fallback — and the `constraint` text names the
  exclusion (`codex excluded after the arbiter pin found no eligible codex model for effort
  'max' (no_eligible_model); arbiter selection recomputed once`). Nothing left → **fail
  CLOSED** as above. No budget row is written (no seat was substituted). A broken resolver
  (an invalid freeze pin, unreadable pins) or an invalid codex roster is a plain
  `ConveneError` and is **never** recomputed.

`can_arbitrate` is **inert** under v2 — no seat is ever the adjudicator, so no seat
both ballots and adjudicates (the participant-judge violation is gone). The
adjudication prior comes from the editable `capability-priors.yaml` DATA (designer
belief, not measured capability); the resolver fails **open** to built-in defaults
if that file is missing.

The arbiter object in the session-plan **drops `seat`**, **adds**
`{is_external: true, cold_context: true, path: clean|fallback}`, and **keeps** the
runtime-load-bearing `{provider, effort, guard_stack}` (`constraint` is optional).

### Arbiter output contract (versioned system contract)

The external arbiter emits a fixed-shape synthesis over **all** positions (a
position is never dropped from the synthesis set): a **decision**, the **rejected
alternatives**, **≥2 actionable trip-wires**, a **mandatory attributed dissent
record**, and the **convergence margin** (unanimous / converged N-M / arbiter broke
tie).

'''

#: The other six sites at 615231b, VERBATIM, keyed by the unit that now carries each one.
_Y3_BASE_PASSAGES = {
    # skills/avengers/scripts/convene.py:11-20 at 615231b
    "convene.py module docstring": '''  - resolves the EXTERNAL, SEATLESS, cold-context arbiter (design §4, WP-2): a
    fresh persona-free CALL that did NOT file a position, argue, or ballot. Unless the
    profile DECLARES its arbiter (D23, below), its
    provider MUST differ from EVERY deliberation seat's provider (widened from
    adversarial-only). CLEAN path = a provider used by no deliberation seat (total
    exclusion). FALLBACK path = all providers deliberated (coding-ratification
    always lands here) -> the strongest-adjudication-prior NON-adversarial
    provider, cold-context, with the ACCEPTED style-recognition residual RECORDED
    as `fallback_arbiter_residual` in run-record.json. An ALL-ADVERSARIAL profile
    is arbiter-unsatisfiable -> fails CLOSED (ConveneError), never hangs.
''',
    # skills/avengers/scripts/convene.py:1613-1625 at 615231b
    "convene.py resolve_arbiter docstring": '''    The arbiter is a FRESH persona-free CALL — it did NOT file a position, argue,
    or ballot; it is NOT a promoted seat. Its provider is selected (never inherited
    from a seat) by precedence:
      * CLEAN path  — a provider used by NO deliberation seat: genuinely external,
        authorship-linkage total-excluded, no residual.
      * FALLBACK path — all providers deliberated (coding-ratification ALWAYS lands
        here, pinning all 3 families): the strongest-adjudication-prior
        NON-adversarial provider, cold-context. Authorship is anonymized but
        style-recognition self-preference is an ACCEPTED, DOCUMENTED residual
        (arXiv 2410.21819), RECORDED as `fallback_arbiter_residual` (§6a).
      * ALL-ADVERSARIAL — every provider deliberated AND every one is adversarial:
        no non-adversarial arbiter exists -> fail CLOSED (the only unsatisfiable
        arbiter case; never hangs).
''',
    # skills/avengers/profiles/coding-ratification.yaml:18-27 at 615231b
    "coding-ratification.yaml comments": '''# --- Roster resolution (refs into roster/<seat_id>.yaml) ---
# Per-seat provider/effort overrides are permitted only WITHIN policy
# (convene.py fails closed on an unknown tier/seat-class or an un-pinned codex seat). >=1 seat MUST resolve
# adversarial_role: true. The EXTERNAL seatless arbiter's provider MUST differ
# from every DELIBERATION seat's provider on the clean path (widened from
# adversarial-only, design §4); coding-ratification pins BOTH remaining families
# (codex, claude — agy left at AMENDMENT 3 D25) so it always lands on the fallback
# path -> the strongest non-adversarial provider (claude), authorship anonymized
# with an accepted, flagged residual (§6a). Losing agy did not change the path: it
# was already fallback, because claude deliberates here too.
''',
    # skills/avengers/tests/test_arbiter_external.py:8-13 at 615231b
    "test_arbiter_external.py module docstring": '''  * CLEAN path — arbiter provider used by NO deliberation seat (total exclusion,
    no residual).
  * FALLBACK path — all providers deliberated (coding-ratification always lands
    here): the strongest-adjudication-prior NON-adversarial provider, cold-context,
    with the ACCEPTED style-recognition residual FLAGGED (fallback_arbiter_residual)
    in run-record.json (§6a).
''',
    # skills/avengers/tests/test_arbiter_external.py:104-106 at 615231b
    "test_arbiter_external.py comments": '''# --------------------------------------------------------------------------- #
# FALLBACK path — all providers deliberated (the coding-ratification reality)
# --------------------------------------------------------------------------- #
''',
    # skills/avengers/tests/test_convene.py:346 at 615231b
    "test_convene.py comments": '''    # coding-ratification pins all 3 families -> the arbiter ALWAYS takes the fallback path
''',
}

#: Which retired claims each base passage states — the per-site map the CONTROL asserts EXACTLY.
_Y3_BASE_CLAIMS = {
    "convene-contract.md External arbiter": {"r2_16_the_unscoped_must_differ", "r2_15_fallback_means_all_providers_deliberated",
                                             "r2_15_pins_all_three_families", "r2_15_always_lands_on_the_fallback"},
    "convene.py module docstring": {"r2_15_fallback_means_all_providers_deliberated", "r2_15_always_lands_on_the_fallback"},
    "convene.py resolve_arbiter docstring": {"r2_15_fallback_means_all_providers_deliberated",
                                             "r2_15_always_lands_on_the_fallback", "r2_15_pins_all_three_families"},
    "coding-ratification.yaml comments": {"r2_15_always_lands_on_the_fallback", "r2_15_losing_agy_did_not_change_the_path"},
    "test_arbiter_external.py module docstring": {"r2_15_fallback_means_all_providers_deliberated",
                                                  "r2_15_always_lands_on_the_fallback"},
    "test_arbiter_external.py comments": {"r2_15_fallback_means_all_providers_deliberated",
                                          "r2_15_the_coding_ratification_reality"},
    "test_convene.py comments": {"r2_15_pins_all_three_families", "r2_15_always_lands_on_the_fallback"},
}

#: TRUE sentences that reuse the retired claims' words with their scope. None may trip a Y3 or an X6 needle.
_Y3_TRUE_SCOPED_SENTENCES = (
    "In a healthy session coding-ratification lands on the fallback path.",
    "Under a codex refusal its arbiter is agy on the clean path.",
    "coding-ratification pins BOTH remaining families (codex, claude).",
    "It always lands on the fallback path in a healthy session, and nowhere else.",
    "FALLBACK path — no eligible provider is free of deliberation; here all three providers deliberate.",
    "A SELECTED arbiter's provider MUST differ from every deliberation seat's provider whenever an eligible one does.",
    "Losing agy's seats alone would have put agy on the clean path.",
    "The two-provider team is the coding-ratification shape; the three-provider team is not.",
)


def _y3_normalized_claims(text):
    import re
    norm = _d2_normalized(text)
    return {name for name, needle in _Y3_RETIRED_CLAIMS.items() if re.search(needle, norm)}


def _y3_missing(text, facts):
    norm = _d2_normalized(text)
    return {name for name, needle in facts.items() if needle not in norm}


def _y3_external_arbiter_section(text):
    """The contract's "## External arbiter" section: from that heading to the next "## " heading (a "### "
    subsection stays inside it). FAILS LOUDLY when the heading is missing or the section is empty, so a renamed
    heading can never turn the R2-16 guard into a check of nothing."""
    import re
    head = re.search(r"^## External arbiter\b[^\n]*\n", text, re.M)
    assert head is not None, "no '## External arbiter' heading: the R2-16 guard has no section to read"
    rest = text[head.end():]
    end = re.search(r"^## ", rest, re.M)
    body = rest if end is None else rest[:end.start()]
    assert body.strip(), "the '## External arbiter' section is empty"
    return text[head.start():head.end()] + body


def _y3_yaml_comment_spans(text):
    """(line index, column of the '#') for every COMMENT of a YAML text — never a value. A '#' opens a comment
    only outside a quoted scalar and at the start of a line or after whitespace (YAML's rule, so a URL fragment
    stays a value); a quote opens a quoted scalar only where a scalar starts (so an apostrophe in a plain
    scalar is literal); and the lines of a block scalar (`key: >`, `- |`) are value, whatever they contain."""
    import re
    spans = []
    block_indent = None
    for index, line in enumerate(text.splitlines()):
        body = line.lstrip(" ")
        indent = len(line) - len(body)
        if block_indent is not None:
            if not body or indent > block_indent:
                continue
            block_indent = None
        quote, prev, column, i = None, None, None, 0
        while i < len(line):
            ch = line[i]
            if quote is not None:
                if quote == '"' and ch == "\\":
                    i += 2
                    continue
                if ch == quote:
                    if quote == "'" and line[i + 1:i + 2] == "'":
                        i += 2
                        continue
                    quote = None
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                column = i
                break
            elif ch in "'\"" and (prev is None or prev in ":-[{,?"):
                quote = ch
            if ch not in " \t":
                prev = ch
            i += 1
        content = line if column is None else line[:column]
        if column is not None:
            spans.append((index, column))
        if re.match(r"^\s*(?:-\s+)?(?:[^\s#][^#]*?:\s+)?[|>][1-9+-]{0,2}\s*$", content):
            block_indent = indent
    return spans


def _y3_yaml_comments(text):
    lines = text.splitlines()
    return "\n".join(lines[index][column + 1:] for index, column in _y3_yaml_comment_spans(text))


def _y3_py_comments(source):
    """The COMMENTS of Python source — never a docstring, never a string constant, never code."""
    import io
    import tokenize
    return "\n".join(tok.string[1:] for tok in tokenize.generate_tokens(io.StringIO(source).readline)
                     if tok.type == tokenize.COMMENT)


def _y3_docstring(path, function=None):
    """A module docstring, or the ONE function named `function`'s docstring. Fails loudly on none."""
    import ast
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    if function is None:
        doc = ast.get_docstring(tree, clean=False)
    else:
        found = [node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function]
        assert len(found) == 1, f"{Path(path).name}: expected ONE def {function}, found {len(found)}"
        doc = ast.get_docstring(found[0], clean=False)
    assert doc, f"{Path(path).name}: {function or 'the module'} has no docstring"
    return doc


def _y3_scanned_text(name):
    return {
        "convene-contract.md": lambda: _Y3_CONTRACT.read_text(encoding="utf-8"),
        "convene.py prose": lambda: _x6_convene_prose(),
        "coding-ratification.yaml comments": lambda: _y3_yaml_comments(_Y3_PROFILE.read_text(encoding="utf-8")),
        "test_arbiter_external.py prose": lambda: _x6_convene_prose(_Y3_ARBITER_TESTS),
        "test_convene.py comments": lambda: _y3_py_comments(_Y3_THIS_FILE.read_text(encoding="utf-8")),
    }[name]()


def _y3_site_text(name):
    return {
        "convene-contract.md External arbiter": lambda: _y3_external_arbiter_section(_Y3_CONTRACT.read_text(encoding="utf-8")),
        "convene.py module docstring": lambda: _y3_docstring(_CONVENE),
        "convene.py resolve_arbiter docstring": lambda: _y3_docstring(_CONVENE, "resolve_arbiter"),
        "coding-ratification.yaml comments": lambda: _y3_yaml_comments(_Y3_PROFILE.read_text(encoding="utf-8")),
        "test_arbiter_external.py module docstring": lambda: _y3_docstring(_Y3_ARBITER_TESTS),
        "test_arbiter_external.py comments": lambda: _y3_py_comments(_Y3_ARBITER_TESTS.read_text(encoding="utf-8")),
        "test_convene.py comments": lambda: _y3_py_comments(_Y3_THIS_FILE.read_text(encoding="utf-8")),
    }[name]()


@pytest.mark.parametrize("scanned", _Y3_SCANNED, ids=lambda name: name.replace(" ", "-"))
def test_y3_R2_15_no_unscoped_arbiter_claim_survives(scanned):
    """GUARD (D21 R2-15, R2-16's opening MUST): RED at 615231b, where every scanned file states at least one."""
    assert sorted(_y3_normalized_claims(_y3_scanned_text(scanned))) == []


@pytest.mark.parametrize("site", _Y3_SITES, ids=lambda name: name.replace(" ", "-"))
def test_y3_R2_15_every_site_states_where_coding_ratification_lands(site):
    """GUARD (D21 R2-15): each of the seven sites states the measured arbiter — the FALLBACK path is a property of
    a healthy session, and every codex refusal puts agy on the fallback path (#368) — so deleting a site is not a fix."""
    assert sorted(_y3_missing(_y3_site_text(site), _Y3_SITE_FACTS)) == []


def test_y3_R2_16_the_external_arbiter_section_states_the_bar_d29_and_the_declared_arbiter():
    """GUARD (D21 R2-16): the section itself — not the rest of the contract — states the agy bar and its name in
    code, D29's scope, that a declared arbiter is not selection and is held to the relaxed rule, the MUST scoped
    to a SELECTED arbiter, and the path bullets over ELIGIBLE providers."""
    section = _y3_external_arbiter_section(_Y3_CONTRACT.read_text(encoding="utf-8"))
    assert sorted(_y3_missing(section, _Y3_SECTION_FACTS)) == []


def test_y3_CONTROL_every_needle_fires_on_its_base_passage_and_no_true_scoped_sentence_trips_one():
    """Green at base BY DESIGN — the guard's teeth. Every base passage (embedded verbatim) states EXACTLY its
    recorded claims and none of the site facts; the comment passages state the same claims through their own
    extractors; together they state every claim; the base SECTION states none of the section facts; a claim
    re-wrapped and re-cased is still found; and a TRUE scoped sentence trips neither a Y3 nor an X6 needle."""
    passages = dict(_Y3_BASE_PASSAGES, **{"convene-contract.md External arbiter": _Y3_BASE_CONTRACT_SECTION})
    assert set(passages) == set(_Y3_SITES) == set(_Y3_BASE_CLAIMS)
    for site, text in passages.items():
        assert _y3_normalized_claims(text) == _Y3_BASE_CLAIMS[site], site
        assert _y3_missing(text, _Y3_SITE_FACTS) == set(_Y3_SITE_FACTS), site
    assert _y3_normalized_claims(_y3_yaml_comments(_Y3_BASE_PASSAGES["coding-ratification.yaml comments"])) == \
        _Y3_BASE_CLAIMS["coding-ratification.yaml comments"]
    for site in ("test_arbiter_external.py comments", "test_convene.py comments"):
        assert _y3_normalized_claims(_y3_py_comments(_Y3_BASE_PASSAGES[site])) == _Y3_BASE_CLAIMS[site], site
    assert set().union(*_Y3_BASE_CLAIMS.values()) == set(_Y3_RETIRED_CLAIMS)
    base_section = _y3_external_arbiter_section(_Y3_BASE_CONTRACT_SECTION + "## Effort-tier policy\n")
    assert base_section == _Y3_BASE_CONTRACT_SECTION
    assert _y3_missing(base_section, _Y3_SECTION_FACTS) == set(_Y3_SECTION_FACTS)
    assert _y3_normalized_claims("coding-ratification ALWAYS\n    lands HERE, PINNING all 3\n families") == {
        "r2_15_always_lands_on_the_fallback", "r2_15_pins_all_three_families"}
    for sentence in _Y3_TRUE_SCOPED_SENTENCES:
        assert _y3_normalized_claims(sentence) == set(), sentence
        assert _x6_retired_claims_in(sentence) == set(), sentence


def test_y3_CONTROL_the_section_extractor_is_scoped_and_fails_loudly():
    """A required fact OUTSIDE the section (before its heading, or in the next section) does not satisfy it; a
    '### ' subsection stays inside it; a missing heading or an empty section is an AssertionError, not a pass."""
    facts = " ".join(_Y3_SECTION_FACTS.values())
    doc = (f"# Contract\n\n{facts}\n\n" + _Y3_BASE_CONTRACT_SECTION + f"## Effort-tier policy\n\n{facts}\n")
    section = _y3_external_arbiter_section(doc)
    assert section == _Y3_BASE_CONTRACT_SECTION
    assert "### Arbiter output contract" in section
    assert _y3_missing(section, _Y3_SECTION_FACTS) == set(_Y3_SECTION_FACTS)
    assert _y3_missing(doc, _Y3_SECTION_FACTS) == set()          # the whole doc WOULD satisfy them
    with pytest.raises(AssertionError, match="no '## External arbiter' heading"):
        _y3_external_arbiter_section(doc.replace("## External arbiter", "## External judge"))
    with pytest.raises(AssertionError, match="section is empty"):
        _y3_external_arbiter_section("## External arbiter (x)\n\n## Next\n")


def test_y3_CONTROL_the_yaml_comment_extractor_never_reads_a_value():
    """The extractor returns comments and NOTHING a YAML parser would read as a value: a plain value, a quoted
    value holding ' # ', a doubled-quote escape, a URL fragment, a folded and a literal block scalar holding
    ' # '. On the LIVE profile, blanking every span it returns leaves the parsed document unchanged — had it
    taken a value, the parse would move — and the base passage's claims are seen through it."""
    sample = (
        "key: coding-ratification always lands here  # a TRUE comment\n"
        "quoted: \"a # value that names the coding-ratification reality\"\n"
        "single: 'it''s # also a value'\n"
        "plain: it's a value # and a comment\n"
        "url: http://example.invalid/#losing agy did not change the path\n"
        "block: >\n"
        "  a folded value # with a hash that is content\n"
        "  pinning all 3 families\n"
        "# a full-line comment\n"
        "seq:\n"
        "  - |\n"
        "    literal # content\n"
        "  - plain # trailing comment\n"
    )
    assert _y3_yaml_comments(sample).splitlines() == [" a TRUE comment", " and a comment", " a full-line comment",
                                                      " trailing comment"]
    assert _y3_normalized_claims(_y3_yaml_comments(sample)) == set()
    assert _y3_normalized_claims(sample) == {"r2_15_always_lands_on_the_fallback", "r2_15_the_coding_ratification_reality",
                                             "r2_15_losing_agy_did_not_change_the_path", "r2_15_pins_all_three_families"}

    def blanked(text):
        lines = text.splitlines()
        for index, column in _y3_yaml_comment_spans(text):
            lines[index] = lines[index][:column]
        return "\n".join(lines) + "\n"

    assert yaml.safe_load(blanked(sample)) == yaml.safe_load(sample)
    live = _Y3_PROFILE.read_text(encoding="utf-8")
    assert _y3_yaml_comment_spans(live)
    assert yaml.safe_load(blanked(live)) == yaml.safe_load(live)


def test_y3_CONTROL_the_comment_extractors_never_read_code_or_string_constants(tmp_path):
    """THIS file holds every base passage as a string constant, so its raw text states every retired claim —
    yet the scan reads only its comments. The Python comment extractor returns comments, never a docstring or a
    string constant; the prose extractor (docstrings AND comments) is the one used for the other .py files."""
    raw = _Y3_THIS_FILE.read_text(encoding="utf-8")
    assert _y3_normalized_claims(raw) == set(_Y3_RETIRED_CLAIMS)
    module = tmp_path / "m.py"
    module.write_text('"""coding-ratification always lands here."""\n'
                      "X = 'the coding-ratification reality'\n"
                      "# losing agy did not change the path\n", encoding="utf-8")
    source = module.read_text(encoding="utf-8")
    assert _y3_normalized_claims(_y3_py_comments(source)) == {"r2_15_losing_agy_did_not_change_the_path"}
    assert _y3_normalized_claims(_x6_convene_prose(module)) == {"r2_15_always_lands_on_the_fallback",
                                                                "r2_15_losing_agy_did_not_change_the_path"}


# =========================================================================== #
# #291 WP-6 (design s3.9) — REVERSIBILITY of every shipped profile over two explicit roster pairs
#
# The committed rev-2 roster (opus main / sonnet support, fable benched) and the rev-1 roster it
# replaced (fable / opus, nothing benched) must BOTH convene all five profiles: the naive swap
# (main = support = opus) made four of them fail closed on D23 (a declared consultant_support arbiter
# sharing the members' model). Each pair is injected by monkeypatching model_roster in-process and
# giving convene a FRESH seat_model over it (conftest.seat_model_under_roster). Every expected value
# is an explicit LITERAL of its pair — the rev-1 column is exactly what the pre-#291 tests pinned —
# and the derived wall-clock floors (6000 s / 5400 s) are the SAME in both, as the design requires.
# =========================================================================== #
_REVERSIBILITY_PROFILES = {
    # profile: (claude member seats {seat_id: (weight, model)}, arbiter (provider, model, selection, timeout),
    #           wall-clock floor)
    "rev2": {
        "business-ideation": ({"economist": ("main", "opus"), "skeptic": ("main", "opus")},
                              ("claude", "sonnet", "declared", 600), 5400),
        "coding-ratification": ({"architect": ("main", "opus"), "steward": ("support", "sonnet")},
                                ("claude", "opus", None, 1200), 6000),
        "research-synthesis": ({"skeptic": ("main", "opus")}, ("claude", "sonnet", "declared", 600), 5400),
        "website-ux": ({"skeptic": ("main", "opus")}, ("claude", "sonnet", "declared", 600), 5400),
        "writing-cv": ({"wordsmith": ("main", "opus")}, ("claude", "sonnet", "declared", 600), 5400),
    },
    "rev1": {
        "business-ideation": ({"economist": ("main", "fable"), "skeptic": ("main", "fable")},
                              ("claude", "opus", "declared", 600), 5400),
        "coding-ratification": ({"architect": ("main", "fable"), "steward": ("support", "opus")},
                                ("claude", "fable", None, 1200), 6000),
        "research-synthesis": ({"skeptic": ("main", "fable")}, ("claude", "opus", "declared", 600), 5400),
        "website-ux": ({"skeptic": ("main", "fable")}, ("claude", "opus", "declared", 600), 5400),
        "writing-cv": ({"wordsmith": ("main", "fable")}, ("claude", "opus", "declared", 600), 5400),
    },
}


@pytest.mark.parametrize("main,support,benched,expected", [
    pytest.param("opus", "sonnet", frozenset({"fable"}), _REVERSIBILITY_PROFILES["rev2"],
                 id="rev2-main-opus-support-sonnet-benched-fable"),
    pytest.param("fable", "opus", frozenset(), _REVERSIBILITY_PROFILES["rev1"],
                 id="rev1-main-fable-support-opus-benched-none"),
])
def test_roster_reversibility_every_profile_convenes_under_both_pairs(load_seat_model_under_roster, monkeypatch,
                                                                     tmp_path, capsys, main, support, benched,
                                                                     expected):
    fresh, rev = load_seat_model_under_roster(main, support, benched)
    monkeypatch.setattr(convene, "_seat_model", fresh)
    assert sorted(expected) == sorted(_D3_ALL_PROFILES)                   # all five shipped profiles
    for name, (claude_seats, arbiter, floor) in expected.items():
        plan = _real_plan(name)
        assert {s["seat_id"]: (s["seat_weight"], s["model"]) for s in plan["seats"]
                if s["provider"] == "claude"} == claude_seats, name
        a = plan["arbiter"]
        assert (a["provider"], a["model"], a.get("selection"), a["timeout_s"]) == arbiter, name
        assert (plan["budgets"]["wall_clock_s"], plan["wall_clock_floor"]["floor_s"],
                plan["wall_clock_floor"]["raised"]) == (floor, floor, False), name
        # D23 holds under the pair: a DECLARED arbiter's model is no member seat's model (the undeclared
        # coding-ratification arbiter is the selected `arbiter` row on the flagged fallback residual)
        if a.get("selection") == "declared":
            assert a["model"] not in {s["model"] for s in plan["seats"]}, name
        else:
            assert (a["path"], a["fallback_arbiter_residual"]) == ("fallback", True), name
        # every Claude pin in the plan carries the pair's roster revision
        for item in plan["seats"] + [a]:
            if item["provider"] == "claude":
                assert item["provenance"]["roster_rev"] == rev, (name, item.get("seat_id", "<arbiter>"))
        # and the operator-facing --dry-run convenes it (exit 0, pre-spend review printed, no session)
        project = _project(tmp_path, f"rev-{main}-{name}")
        assert convene.main(_main_args(project, "--dry-run", profile=name)) == 0, name
        review = capsys.readouterr().out
        assert "PRE-SPEND REVIEW" in review and f"wall_clock_s={floor}" in review, name
        assert not (project / ".avengers").exists(), name


def test_roster_reversibility_a_pair_with_main_equal_to_support_is_refused_at_import(load_seat_model_under_roster):
    """CONTROL (the naive swap, main == support == opus): the roster invariant refuses it, so the fresh
    seat_model import fails CLOSED before any profile could convene with a D23 arbiter/member collision."""
    with pytest.raises(Exception) as e:
        load_seat_model_under_roster("opus", "opus", frozenset({"fable"}))
    assert type(e.value).__name__ == "SeatModelError"
    assert "CLAUDE_MAIN == CLAUDE_SUPPORT" in str(e.value)
    assert seat_model.ROLE_TABLE["arbiter"]["claude"].value == MAIN     # the shared module is untouched


# --------------------------------------------------------------------------- #
# #302 WP-4 (design §3.4b, §3.5, §3.8) — per-model attribution on the shared admission,
# supporting seats metered on the support tier, residual literals
# --------------------------------------------------------------------------- #
_302_PROFILES = ("business-ideation", "coding-ratification", "research-synthesis", "website-ux", "writing-cv")


def test_302_a_std_main_seat_and_a_support_seat_share_one_std_admission_listing_both_models(seat_home, tmp_path):
    """design §3.5 (challenger #2): a MEDIUM convene sizes the main codex seat down to the std tier
    (gpt-6-sol at rev 3) while the supporting seat serves the support tier (terra). Both spend the std
    class, so they ride ONE `deliberation` admission — and that row must name BOTH models and roles,
    or #284 cannot tell the two apart."""
    _no_codex_freeze(seat_home)
    project = _project(tmp_path, "proj-302-shared")
    plan = _persisted_plan("business-ideation", project, session_id="s302", size="medium")
    codex = [s for s in plan["seats"] if s["provider"] == "codex"]
    by_role = {s["seat_model_role"]: s for s in codex}
    assert by_role["consultant_main"]["model"] == STD
    assert by_role["consultant_support"]["model"] == CODEX_SUP
    assert STD != CODEX_SUP                                                    # rev 3: two std-class models
    rows = [r for r in _store_rows(project) if "admitted" in r]
    assert [(r["key"], r["use"], r["model_class"], r["admitted"]) for r in rows] == [
        ("s302", "deliberation", "std", True)]
    # seat order: operator (support) precedes architect (main) in business-ideation
    seat_order = [s for s in plan["seats"] if s["provider"] == "codex"]
    assert rows[0]["models"] == [s["model"] for s in seat_order]
    assert set(rows[0]["models"]) == {STD, CODEX_SUP}
    assert rows[0]["roles"] == [s["seat_model_role"] for s in seat_order]
    assert rows[0]["requested_model"] in rows[0]["models"]
    # every seat the admission covers names it
    assert {s["admission_id"] for s in codex} == {rows[0]["admission_id"]}


def test_302_the_check_only_dry_run_decision_also_lists_every_model(seat_home, tmp_path, monkeypatch):
    """The CHECK-ONLY build (--dry-run's path) hands admit() the same model list it would record."""
    _no_codex_freeze(seat_home)
    seen = []
    real_admit = codex_quota.admit

    def spy(*args, **kwargs):
        decision = real_admit(*args, **kwargs)
        seen.append(decision)
        return decision

    project = _project(tmp_path, "proj-302-co")
    monkeypatch.setattr(codex_quota, "admit", spy)
    convene.build_session_plan({"profile": "coding-ratification", "task": "t"},
                               profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
                               session_id="s302co", size="light", project_root=project)
    assert [d["model_class"] for d in seen] == ["std"]
    assert set(seen[0]["models"]) == {STD, CODEX_SUP} and seen[0]["recorded"] is False
    assert _store_rows(project) == []


def test_302_a_seat_is_billed_by_its_resolving_row_not_its_slug(seat_home, tmp_path, monkeypatch):
    """ruling R1 (WP-2): convene bills a pin by seat_model.pin_model_class, not model_class_of(pin.model).
    Proven by hiding the tier set from the slug fallback: the supporting seat still resolves from the
    consultant_support LITERAL row, so it must still bill std and take its own admission."""
    _no_codex_freeze(seat_home)
    monkeypatch.setattr(seat_model, "CODEX_NON_TOP_TIERS", frozenset())
    assert seat_model.model_class_of(CODEX_SUP) == "top"                      # the slug fallback is blind now
    project = _project(tmp_path, "proj-302-row")
    _persisted_plan("business-ideation", project, session_id="s302row")
    rows = [r for r in _store_rows(project) if "admitted" in r]
    # the astra reserve: the Sol member resolves from a LITERAL row too, so both bill std, in one admission
    assert [(r["model_class"], tuple(sorted(r["models"]))) for r in rows] == [("std", tuple(sorted((CODEX_SUP, MEMBER))))]


@pytest.mark.parametrize("profile", _302_PROFILES)
def test_302_no_codex_guard_stack_is_ephemeral(seat_home, profile):
    """design §3.4b (JC-3): support-tier calls run WITHOUT --ephemeral, like TOP calls, so every codex
    call leaves a rollout and meters real quota."""
    _no_codex_freeze(seat_home)
    plan = _real_plan(profile)
    stacks = [s["guard_stack"] for s in plan["seats"] if s["provider"] == "codex"]
    if plan["arbiter"]["provider"] == "codex":
        stacks.append(plan["arbiter"]["guard_stack"])
    assert stacks
    assert all("--ephemeral" not in stack for stack in stacks), stacks
    assert "--ephemeral" not in plan["guard_policy"]["codex"]


@pytest.mark.parametrize("seat_weight", [None, "main", "support"])
@pytest.mark.parametrize("is_arbiter", [False, True])
def test_302_no_codex_role_gains_ephemeral(seat_home, seat_weight, is_arbiter):
    _no_codex_freeze(seat_home)
    _role, _pin, stack = convene.materialise_call("codex", "medium", is_arbiter=is_arbiter,
                                                  seat_weight=seat_weight)
    assert "--ephemeral" not in stack


def test_302_supporting_codex_seats_serve_the_support_tier(seat_home):
    _no_codex_freeze(seat_home)
    for profile in _302_PROFILES:
        for seat in _real_plan(profile)["seats"]:
            if seat["provider"] == "codex" and seat["seat_model_role"] == "consultant_support":
                assert seat["model"] == CODEX_SUP == model_roster.CODEX_SUPPORT, (profile, seat["seat_id"])


def test_302_seat_class_tiers_are_provisional_for_the_std_and_support_tiers():
    """design §3.5: SEAT_CLASS_MEASURED_ON stays the model the 2026-07-11 benchmark ran on, so BOTH
    rev-3 non-TOP tiers inherit the seat-class tiers only PROVISIONALLY."""
    assert convene.SEAT_CLASS_MEASURED_ON == "gpt-5.6-sol"
    for model in (STD, CODEX_SUP):
        assert model != convene.SEAT_CLASS_MEASURED_ON
        for seat_class, tier in ((convene.CHALLENGER_FLOOR, "xhigh"), (convene.RATIFICATION_ARBITER, "max")):
            _e, _c, note = convene.resolve_effort("s", "codex", seat_class, model=model)
            assert note == (f"seat-class {seat_class!r} tier {tier!r} was measured on gpt-5.6-sol; "
                            f"PROVISIONAL for {model}")


def test_302_convene_names_gpt_5_6_sol_only_as_measurement_history():
    """design §3.8: the surviving literals are the benchmark's measured_on model and its dated finding."""
    source = Path(convene.__file__).read_text(encoding="utf-8")
    hits = [line.strip() for line in source.splitlines() if "gpt-5.6-sol" in line]
    assert hits == ['("gpt-5.6-sol", "high"): "never beat medium — benchmark 2026-07-11, 14 scored runs",',
                    'SEAT_CLASS_MEASURED_ON = "gpt-5.6-sol"'], hits
    for path in _REAL_PROFILES.glob("*.yaml"):
        assert "gpt-5.6-sol" not in path.read_text(encoding="utf-8"), path.name


def _n3_flipping_pin_model_class(monkeypatch):
    """Every other read of a pin's class flips it, so two reads of one pin never agree."""
    real = seat_model.pin_model_class
    calls = {}

    def flipping(pin):
        calls[pin.model] = calls.get(pin.model, 0) + 1
        if calls[pin.model] % 2 == 0:
            return "top" if real(pin) == "std" else "std"
        return real(pin)

    monkeypatch.setattr(seat_model, "pin_model_class", flipping)


def test_n3_a_class_that_flips_between_reads_does_not_crash_a_one_class_plan(seat_home, tmp_path, monkeypatch):
    """D21 fix round 2 (N3): pin_model_class reads the roster / tops / pins files, so a concurrent
    rewrite can flip a pin's class between two reads. With ONE class admitted, a second read that
    flipped indexed decisions[class] with a class never decided -> KeyError. convene reads it ONCE."""
    _no_codex_freeze(seat_home)
    _n3_flipping_pin_model_class(monkeypatch)
    project = _project(tmp_path, "proj-n3a")
    _persisted_plan(_ONE_CODEX_SEAT["profile"], project, session_id="sn3a")
    rows = [r for r in _store_rows(project) if "admitted" in r]
    assert len(rows) == 1


def test_n3_each_seat_is_gated_by_the_admission_of_the_class_it_was_billed_in(seat_home, tmp_path, monkeypatch):
    """Two classes: a flip between reads swapped the decisions, so a seat carried the OTHER class's
    admission_id. Computed once, every seat carries the id of the row that lists its model."""
    _no_codex_freeze(seat_home)
    _n3_flipping_pin_model_class(monkeypatch)
    project = _project(tmp_path, "proj-n3b")
    plan = _persisted_plan("business-ideation", project, session_id="sn3b")
    rows = [r for r in _store_rows(project) if "admitted" in r]
    by_model = {m: r["admission_id"] for r in rows for m in r["models"]}
    codex = [s for s in plan["seats"] if s["provider"] == "codex"]
    assert codex and all(s["admission_id"] == by_model[s["model"]] for s in codex), (codex, rows)


# =========================================================================== #
# The astra reserve fix round 1, item 12 (astra F8): "every avengers codex seat is std-class" holds only
# while the vendor does not rank the std model TOP. When it does - a reordered roster, or a stale roster whose
# recorded TOP is the std model - the Sol literal serves the ROSTER TOP and is billed `top`
# (seat_model.pin_model_class F1b), so the session's admission is a TOP one. Pinned so the doc stays honest.
# =========================================================================== #
def test_fr1_a_roster_that_ranks_sol_top_bills_the_avengers_sol_seat_top(seat_home, tmp_path):
    _no_codex_freeze(seat_home)
    crf.write_codex_roster(seat_home, crf.codex_entries(drop=("codex-auto-review",), priorities={MEMBER: 0}),
                           fetched_at=_iso_nanos(time.time() - 3600))
    project = _project(tmp_path, "proj-fr1-reordered")
    plan = _persisted_plan("research-synthesis", project, session_id="fr1-top")
    assert _by_id(plan)["architect"]["model"] == MEMBER                    # still the Sol literal ...
    [row] = [r for r in _store_rows(project) if "admitted" in r]
    assert (row["model_class"], row["requested_model"]) == ("top", MEMBER)   # ... billed TOP
    # CONTROL: the ordinary roster bills the same seat std
    _write_codex_roster(seat_home)
    other = _project(tmp_path, "proj-fr1-ordinary")
    _persisted_plan("research-synthesis", other, session_id="fr1-std")
    assert [r["model_class"] for r in _store_rows(other) if "admitted" in r] == ["std"]


def test_fr1_a_stale_roster_whose_recorded_top_is_sol_bills_it_top(seat_home, tmp_path):
    _no_codex_freeze(seat_home)
    crf.write_codex_roster(seat_home, crf.codex_entries(drop=("codex-auto-review",)),
                           fetched_at=_iso_nanos(time.time() - 30 * 86400))
    (seat_home / ".claude" / "state" / "seat-model-tops.json").write_text(json.dumps(
        {"schema": "seat-model-tops.v1", "tops": {"codex": {
            "top": MEMBER, "previous": None, "changed_at": None, "resolved_at": _iso(time.time() - 86400),
            "roster_fetched_at": None}}}), encoding="utf-8")
    project = _project(tmp_path, "proj-fr1-stale")
    _persisted_plan("research-synthesis", project, session_id="fr1-stale")
    assert [r["model_class"] for r in _store_rows(project) if "admitted" in r] == ["top"]


# --------------------------------------------------------------------------- #
# #322 fix round 1 (item 11): a QUOTA stand-in is announced as a wait, not taken at once
# --------------------------------------------------------------------------- #
def _quota_plan(reason):
    return {"session_id": "sess-1", "seats": [
        {"seat_id": "skeptic", "substitute_for": "codex", "substitution_reason": reason},
        {"seat_id": "operator", "substitute_for": "codex", "substitution_reason": reason},
        {"seat_id": "architect", "provider": "claude"}]}


def test_322_fr1_a_quota_substitution_prints_the_quota_wait_line():
    line = convene.codex_quota_wait_line(_quota_plan("quota_exhausted"),
                                         {"wait_advice": "notify", "resets_in_s": 2400})
    assert line.startswith("CODEX_QUOTA_WAIT: avengers sess-1 (reason quota_exhausted; wait_advice notify; "
                           "resets_in_s 2400; seats skeptic, operator)")
    assert "notify-claim" in line and "await-reset --cycle-id sess-1" in line and "stand-in" in line


def test_322_fr1_a_meter_with_no_reset_still_prints_the_line_as_notify():
    line = convene.codex_quota_wait_line(_quota_plan("rate_limit_reached"), {})
    assert "wait_advice notify; resets_in_s unknown" in line


@pytest.mark.parametrize("reason", ["budget_spent", "cli_missing", "no_eligible_model", "class_not_budgeted"])
def test_322_fr1_control_a_non_quota_substitution_prints_no_wait_line(reason):
    assert convene.codex_quota_wait_line(_quota_plan(reason), {"wait_advice": "wait", "resets_in_s": 60}) is None
