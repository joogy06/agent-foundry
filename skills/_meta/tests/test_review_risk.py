#!/usr/bin/env python3
"""Tests for review_risk.py -- the D22 risk tagger (S081 rev 4, WP-A1).

Table-driven over the six families, and every positive claim has its CONTROL.
A tagger that promotes everything would pass a suite of positives alone while
being worthless, so the controls are the point: each family's representative is
paired with a NEIGHBOURING path that must NOT promote.

  gates.py / claims.py / audit_spawn.py promote  <-> a plain skill SKILL.md does not
  a schema under schemas/ promotes              <-> a fixture named like a contract does not
  CLAUDE.md and agents/*.md promote             <-> a docs/plans design doc does not
  a secrets path promotes                       <-> `workflow-authoring` is not `auth`
  a test OF a protected module promotes         <-> a test of an unprotected one does not

Purity has its own control (`test_assess_touches_no_file`): the module is the
thing that decides how carefully a change is reviewed, so it must not be
readable-from or steerable-by the tree under review.
"""
import builtins
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import review_risk as rr  # noqa: E402


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #

#: (family, path) -- one or more representatives per family. Every family in
#: rr.FAMILIES must appear here; test_the_table_covers_every_family enforces it.
PROMOTING = [
    ("gates_and_verification", "skills/_meta/gates.py"),
    ("gates_and_verification", "skills/_meta/claims.py"),
    ("gates_and_verification", "skills/_meta/audit_spawn.py"),
    ("gates_and_verification", "skills/_meta/verification_arbiter_spawn.py"),
    ("gates_and_verification", "skills/_meta/trusted_runner.py"),
    ("trust_boundary", "skills/_meta/seat_model.py"),
    ("trust_boundary", "skills/_meta/codex_model.py"),
    ("trust_boundary", ".claude/settings.json"),
    ("trust_boundary", "skills/_meta/review_risk.py"),   # judgement call 3
    ("trust_boundary", "skills/_meta/escalation.py"),    # WP-C1: the ladder
    ("trust_boundary", "skills/_meta/review_dossier.py"),  # WP-C1: the dossier
    ("quota_budget_registry", "skills/_meta/codex_quota.py"),
    ("quota_budget_registry", "skills/_meta/seat_model.py"),
    ("quota_budget_registry", "state/seat-model-pins.json"),
    ("schemas_and_contracts", "skills/_meta/schemas/execution-report.v1.json"),
    ("schemas_and_contracts", "progress/contract-map.yaml"),
    ("schemas_and_contracts", "progress/contract-map.yaml.sig"),
    ("secrets_and_auth", "skills/secret-scanning/SKILL.md"),
    ("secrets_and_auth", ".env"),
    ("secrets_and_auth", "deploy/server.pem"),
    ("governance_and_agents", "CLAUDE.md"),
    ("governance_and_agents", "global/CLAUDE.md"),         # the global rules' source (#318)
    ("governance_and_agents", "agents/bob.md"),
    ("governance_and_agents", "skills/_meta/hard-rules-checklist.md"),
]

#: Neighbours of the above that must NOT promote. If any of these starts
#: promoting, the tagger has stopped discriminating.
CONTROLS = [
    "skills/react-developer/SKILL.md",                      # a plain skill
    "skills/python-flask-developer/SKILL.md",
    "docs/plans/2026-09-15-S081-revision-4-design.md",      # a design doc
    "docs/reviews/2026-09-16-review.md",
    "skills/_meta/tests/fixtures/contract-map.yaml",        # fixture, not a contract
    "skills/_meta/tests/fixtures/execution-report.v1.json",
    "README.md",
    "history.md",
    "progress/work-packages.yaml",
    "skills/_meta/portable_cli.py",
    "skills/workflow-authoring/SKILL.md",                   # 'authoring' != 'auth'
    "skills/_meta/author.py",                               # 'author'   != 'auth'
    "skills/keybindings-help/SKILL.md",                     # 'keybindings' != 'key'
    "skills/_meta/tests/test_portable_cli.py",              # test of an unprotected module
]


# --------------------------------------------------------------------------- #
# The six families
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("family,path", PROMOTING)
@pytest.mark.parametrize("declared", ["light", "medium"])
def test_a_representative_path_promotes_its_family(family, path, declared):
    result = rr.assess([path], size=declared, size_source="forge")
    assert family in result.families, (
        "{0} did not fire {1}; fired {2}".format(path, family, result.families))
    assert result.size == "complex"
    assert result.promoted is True
    assert result.size_source == "risk"
    assert result.declared_size == declared


@pytest.mark.parametrize("path", CONTROLS)
@pytest.mark.parametrize("declared", ["light", "medium"])
def test_a_control_path_does_not_promote(path, declared):
    result = rr.assess([path], size=declared, size_source="forge")
    assert result.tags == (), "{0} fired {1}".format(path, result.families)
    assert result.size == declared
    assert result.promoted is False
    assert result.size_source == "forge", "provenance must survive untouched"


def test_the_table_covers_every_family():
    covered = {family for family, _ in PROMOTING}
    assert covered == set(rr.FAMILIES), (
        "families with no representative: {0}".format(
            sorted(set(rr.FAMILIES) - covered)))


def test_a_path_may_fire_more_than_one_family():
    # seat_model.py is both the protected-role resolver and the seat registry.
    result = rr.assess(["skills/_meta/seat_model.py"], size="light")
    assert "trust_boundary" in result.families
    assert "quota_budget_registry" in result.families


# --------------------------------------------------------------------------- #
# The promotion contract
# --------------------------------------------------------------------------- #

def test_an_empty_change_set_does_not_promote():
    result = rr.assess([], size="light", size_source="forge")
    assert result.tags == ()
    assert result.size == "light"
    assert result.promoted is False
    assert result.size_source == "forge"


def test_a_declared_complex_is_unchanged_and_keeps_its_provenance():
    result = rr.assess(["skills/_meta/gates.py"], size="complex",
                       size_source="forge")
    assert result.tags, "the tags are still reported"
    assert result.size == "complex"
    assert result.promoted is False
    assert result.size_source == "forge", "no spurious size_source rewrite"


def test_size_source_is_only_set_when_the_size_actually_moved():
    moved = rr.assess(["skills/_meta/gates.py"], size="light",
                      size_source="forge")
    still = rr.assess(["skills/_meta/gates.py"], size="complex",
                      size_source="forge")
    assert moved.size_source == "risk"
    assert still.size_source == "forge"


def test_promotion_is_idempotent():
    first = rr.assess(["skills/_meta/gates.py"], size="light")
    second = rr.assess(["skills/_meta/gates.py"], size=first.size,
                       size_source=first.size_source)
    assert (second.size, second.promoted) == ("complex", False)
    assert second.size_source == "risk", "the earlier provenance survives"
    third = rr.assess(["skills/_meta/gates.py"], size=second.size,
                      size_source=second.size_source)
    assert (third.size, third.size_source) == (second.size, second.size_source)


def test_promotion_is_upward_only_and_never_lowers_a_size():
    for declared in rr.SIZES:
        result = rr.assess(["skills/_meta/gates.py"], size=declared)
        assert rr.SIZES.index(result.size) >= rr.SIZES.index(declared)


def test_user_request_suppresses_promotion_and_keeps_provenance():
    result = rr.assess(["skills/_meta/gates.py"], size="light",
                       size_source="user", user_request=True)
    assert result.tags, "the tags are still reported for the record"
    assert result.size == "light", "--user-request already forces TOP"
    assert result.promoted is False
    assert result.size_source == "user"


def test_an_absent_size_resolves_to_complex_by_default():
    result = rr.assess(["skills/react-developer/SKILL.md"])
    assert result.size == "complex"
    assert result.size_source == "default"
    assert result.promoted is False


def test_an_unknown_size_is_refused_rather_than_guessed():
    with pytest.raises(rr.ReviewRiskError):
        rr.assess(["CLAUDE.md"], size="enormous")


# --------------------------------------------------------------------------- #
# Tags carry their evidence
# --------------------------------------------------------------------------- #

def test_every_tag_records_what_matched_and_why():
    result = rr.assess(["skills/_meta/gates.py", "CLAUDE.md"], size="light")
    for tag in result.tags:
        assert tag.family in rr.FAMILIES
        assert tag.kind in ("path", "symbol")
        assert tag.matched, "a tag must name what fired it"
        assert tag.rule and " " in tag.rule, "the reason must be readable"
    matched = {t.matched for t in result.tags}
    assert matched == {"skills/_meta/gates.py", "CLAUDE.md"}


def test_tags_are_deduplicated_and_the_result_is_deterministic():
    twice = ["skills/_meta/gates.py", "skills/_meta/gates.py"]
    once = rr.assess(["skills/_meta/gates.py"], size="light")
    dupe = rr.assess(twice, size="light")
    assert [t.to_dict() for t in dupe.tags] == [t.to_dict() for t in once.tags]
    again = rr.assess(twice, size="light")
    assert dupe.to_dict() == again.to_dict()


# --------------------------------------------------------------------------- #
# Path handling
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("spelling", [
    "skills/_meta/gates.py",
    "skills\\_meta\\gates.py",
    "./skills/_meta/gates.py",
    "skills/_meta/../_meta/gates.py",
])
def test_the_same_file_spelled_differently_tags_the_same(spelling):
    result = rr.assess([spelling], size="light")
    assert "gates_and_verification" in result.families
    assert result.tags[0].matched == "skills/_meta/gates.py"


@pytest.mark.parametrize("path", [
    "skills/_meta/tests/fixtures/contract-map.yaml",
    "skills/_meta/tests/fixtures/schemas/execution-report.v1.json",
    "tests/fixtures/.env",
])
def test_a_fixture_never_promotes(path):
    result = rr.assess([path], size="light")
    assert result.tags == ()
    assert result.size == "light"


@pytest.mark.parametrize("path,family", [
    ("skills/_meta/tests/test_gates.py", "gates_and_verification"),
    ("skills/_meta/tests/test_claims.py", "gates_and_verification"),
    ("skills/_meta/tests/test_seat_model.py", "trust_boundary"),
    ("skills/_meta/tests/test_codex_quota.py", "quota_budget_registry"),
])
def test_a_test_of_a_protected_module_inherits_its_family(path, family):
    result = rr.assess([path], size="light")
    assert family in result.families
    assert result.promoted is True
    assert any("test of a protected module" in t.rule for t in result.tags)


@pytest.mark.parametrize("path", [
    "skills/_meta/tests/test_portable_cli.py",
    "skills/_meta/tests/test_geometry_rules.py",
    "skills/avengers/tests/test_convene.py",
])
def test_a_test_of_an_unprotected_module_does_not_promote(path):
    assert rr.assess([path], size="light").tags == ()


def test_the_tagger_protects_itself_and_its_own_test():
    """Judgement call 3: the thing deciding review depth is trust boundary.

    A tagger that protects every surface except itself can be weakened first
    and then used to wave through everything else.
    """
    module = rr.assess(["skills/_meta/review_risk.py"], size="light")
    assert "trust_boundary" in module.families
    assert module.size == "complex"
    own_test = rr.assess(["skills/_meta/tests/test_review_risk.py"], size="light")
    assert "trust_boundary" in own_test.families, (
        "the test that pins the tagger inherits it (judgement call 2)")


@pytest.mark.parametrize("path", [
    "skills/_meta/escalation.py",
    "skills/_meta/review_dossier.py",
])
@pytest.mark.parametrize("declared", ["light", "medium"])
def test_the_two_modules_the_table_exists_to_protect_are_in_it(path, declared):
    """WP-C1 closes the gap judgement call 3 left open.

    THE GAP, as measured at HEAD before this change: `escalation.py` returned
    `promoted=False, size=light` with NO FAMILY FIRING AT ALL, while
    `review_risk.py` -- already in the table, by its own author's hand --
    returned `promoted=True, size=complex, trust_boundary`. The table protected
    its own author and not the two modules it was deferring.

    Why it could only be closed here: the table lives in `review_risk.py`,
    whose sole owner (WP-A1) was already complete, so "the WPs that create
    them can add themselves" named no one who could reach the file. An
    obligation with no owner is abandoned, not deferred. By WP-C1 both modules
    exist -- `escalation.py` at commit 18, `review_dossier.py` in this very
    package -- so the deferral's own stated reason, that naming files which do
    not exist is a guess, expires exactly here.
    """
    result = rr.assess([path], size=declared, size_source="forge")
    assert "trust_boundary" in result.families, (
        "{0} fired {1}".format(path, result.families))
    assert result.size == "complex"
    assert result.promoted is True
    assert result.size_source == "risk"


@pytest.mark.parametrize("path", [
    "skills/_meta/portable_cli.py",
    "skills/_meta/review_helper.py",
    "skills/_meta/escalation_notes.md",
])
def test_a_neighbour_of_the_two_new_entries_still_does_not_promote(path):
    """The control. Two names were added, not a directory.

    `escalation_notes.md` is the sharp one: it shares a word with a table
    entry and must NOT inherit it, because the table matches BASENAMES and not
    prefixes. Without this control, a table that had accidentally started
    promoting on a substring would pass every positive test above.
    """
    result = rr.assess([path], size="light", size_source="forge")
    assert result.tags == (), "{0} fired {1}".format(path, result.families)
    assert result.promoted is False
    assert result.size == "light"
    assert result.size_source == "forge"


@pytest.mark.parametrize("path", [
    "skills/_meta/tests/test_escalation.py",
    "skills/_meta/tests/test_review_dossier.py",
])
def test_the_tests_of_the_two_new_entries_inherit_the_family(path):
    """Judgement call 2 reaches the new entries too: gutting the assertions
    that pin them is as dangerous as editing them."""
    result = rr.assess([path], size="light")
    assert "trust_boundary" in result.families
    assert result.promoted is True
    assert any("test of a protected module" in t.rule for t in result.tags)


def test_the_table_names_both_modules_exactly_once():
    """The entries are real table members, not an artefact of another rule.

    A path can promote for a reason that has nothing to do with the table --
    `seat_model.py` fires two families -- so a promotion test alone would pass
    even if the entry had never been added.
    """
    assert "escalation.py" in rr.TRUST_BOUNDARY_BASENAMES
    assert "review_dossier.py" in rr.TRUST_BOUNDARY_BASENAMES
    assert "review_risk.py" in rr.TRUST_BOUNDARY_BASENAMES


def test_a_production_module_starting_with_test_is_not_re_pointed():
    # Outside a tests/ directory, `test_harness.py` is just a module name.
    assert rr.assess(["skills/_meta/test_gates.py"], size="light").tags == ()


def test_blank_and_empty_paths_are_ignored():
    assert rr.assess(["", "   ", "."], size="light").tags == ()


# --------------------------------------------------------------------------- #
# Symbols
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("symbol,family", [
    ("G_SECURITY", "gates_and_verification"),
    ("G_CONTRACT_SCOPE", "gates_and_verification"),
    ("assert_verified_preconditions", "gates_and_verification"),
    ("ROLE_TABLE", "trust_boundary"),
    ("SUBSTITUTION_USES", "quota_budget_registry"),
    ("weekly_quota", "quota_budget_registry"),
    ("rotate_secret", "secrets_and_auth"),
    ("schema_version", "schemas_and_contracts"),
])
def test_a_risky_symbol_promotes(symbol, family):
    result = rr.assess([], [symbol], size="light")
    assert family in result.families
    assert result.size == "complex"
    assert result.tags[0].kind == "symbol"


@pytest.mark.parametrize("symbol", [
    "main", "resolve", "render_table", "author", "to_dict", "Greeting", "",
])
def test_a_generic_symbol_is_not_a_risk_signal(symbol):
    assert rr.assess([], [symbol], size="light").tags == ()


# --------------------------------------------------------------------------- #
# Purity
# --------------------------------------------------------------------------- #

def test_assess_touches_no_file(monkeypatch):
    """The module that decides review depth must not read the tree."""
    def explode(*args, **kwargs):
        raise AssertionError("review_risk opened a file")

    monkeypatch.setattr(builtins, "open", explode)
    monkeypatch.setattr(Path, "read_text", explode)
    monkeypatch.setattr(Path, "exists", explode)
    result = rr.assess(["skills/_meta/gates.py", "CLAUDE.md"],
                       ["G_SECURITY"], size="light")
    assert result.size == "complex"


def test_paths_need_not_exist():
    real = rr.assess(["skills/_meta/gates.py"], size="light")
    fake = rr.assess(["skills/_meta/gates.py"], size="light")
    assert real.to_dict() == fake.to_dict()
    assert rr.assess(["no/such/dir/gates.py"], size="light").promoted is True


# --------------------------------------------------------------------------- #
# Serialisation and CLI
# --------------------------------------------------------------------------- #

def test_to_dict_carries_the_fields_a_row_must_record():
    result = rr.assess(["skills/_meta/gates.py"], size="light")
    data = result.to_dict()
    assert data["size"] == "complex"
    assert data["size_source"] == "risk"
    assert data["promoted"] is True
    assert data["declared_size"] == "light"
    assert data["families"] == ["gates_and_verification"]
    assert data["tags"][0]["matched"] == "skills/_meta/gates.py"


def test_cli_reports_the_promotion(capsys):
    rc = rr.main(["--size", "light", "--json", "skills/_meta/gates.py"])
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["size"] == "complex"
    assert payload["size_source"] == "risk"


def test_cli_rejects_an_unknown_size_without_traceback(capsys):
    with pytest.raises(SystemExit):
        rr.main(["--size", "enormous", "CLAUDE.md"])


def test_cli_human_output_names_the_reason(capsys):
    rc = rr.main(["--size", "light", "skills/_meta/gates.py"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "size=complex" in out
    assert "gates_and_verification" in out
    assert "skills/_meta/gates.py" in out
