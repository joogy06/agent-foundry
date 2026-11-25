#!/usr/bin/env python3
"""Tests for codex_model.py — the shared codex pin emitter.

Covers the design §4.1 / §11.3 contract:
  - argv shape: `-m` is ALWAYS emitted; there is no "inherit" spelling
  - precedence env > data > harness literal, and `env_var=None` SKIPS env
  - effort legality against the REAL roster shape (objects keyed `effort`,
    NOT bare strings — an emitter assuming strings validates nothing)
  - fail_open=True (audit_spawn) vs fail_open=False (convene's pre-spend gate)
  - the fail-open floor is PER-ROLE, not one global constant
  - `default_model()` is an accessor: a raw-tier seat_class takes the default
  - a POSITIVE assertion on the reachable slug set

The slug-set test is written as an equality on the DERIVED set rather than as a
negative control naming a slug: it catches ANY unexpected model, not only the
one a test author thought to forbid.

S081 stream 3 (WP-R02) adds the CODEX ADAPTER tests at the bottom of this file:
the roster-metadata loader and `top_listed(effort)` auto-follow selection
(design §4.2 m2, §4.3). Those use FIXTURE rosters only, never the live
`~/.codex/models_cache.json`. Their positive control mirrors the 2026-09-14 live
roster and therefore names that roster's top slug. S080 stream 4 had to keep that
literal out of this file. S081 auto-follows the top on purpose, and the stream-3
freeze pin (not an absent literal) is what keeps it from serving. The 25 tests
above are the unchanged regression guard for the legacy `resolve()` shim.

#282 R4 (plan K14) adds the THREE ROSTER STATES at the bottom: a missing file is
CodexRosterAbsentError, every unreadable / malformed / wrongly typed document is
CodexRosterInvalidError (both CodexModelError), and no other exception type escapes the
loader. test_an_unranked_entry_is_not_eligible's "1" / True / nan cases are INVERTED to
invalid; its null-priority half and test_load_roster_entries_missing_metadata_is_none_not_invented
stand.
"""
import ast
import json
import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import codex_model as cm  # type: ignore

#: #302 WP-1: the std model (codex_model's default workhorse), read from the roster tier.
SOL = cm.DEFAULT_MODEL
#: The DATED 2026-09-15 tie fixtures below mirror a real roster refresh in which gpt-5.6-sol tied
#: gpt-6-astra. They stay LITERAL (design #302 section 4): they must not follow DEFAULT_MODEL.
TIE_SOL = "gpt-5.6-sol"
ALL_EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"]


# --------------------------------------------------------------------------- #
# Helpers — roster fixtures in the LIVE shape.
# --------------------------------------------------------------------------- #
def write_roster(tmp_path: Path, models, *, name="models_cache.json") -> Path:
    """models: {slug: [effort, ...]} -> a cache file in the real object shape."""
    doc = {
        "fetched_at": "2026-09-09T00:00:00Z",
        "client_version": "0.153.4",
        "models": [
            {
                "slug": slug,
                "supported_reasoning_levels": [
                    {"effort": e, "description": f"{e} reasoning"} for e in efforts
                ],
                "visibility": "list",
                "supported_in_api": True,
            }
            for slug, efforts in models.items()
        ],
    }
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture()
def full_roster(tmp_path: Path) -> Path:
    return write_roster(
        tmp_path, {SOL: ALL_EFFORTS, "some-other-model": ALL_EFFORTS, "shallow-model": ["low"]}
    )


# --------------------------------------------------------------------------- #
# argv shape
# --------------------------------------------------------------------------- #
def test_argv_fragment_shape(full_roster):
    pin = cm.resolve(cm.AUDIT_CODEX_ARM, cache_path=full_roster)
    assert pin.argv_fragment == [
        "-m", SOL, "-c", "model_reasoning_effort=xhigh",
    ]


def test_dash_m_is_always_emitted_on_every_path(full_roster, tmp_path):
    """Data, env and harness-literal paths all carry `-m`. No "omit -m" shape."""
    missing = tmp_path / "gone.json"
    seen = [
        cm.resolve(cm.AUDIT_CODEX_ARM, cache_path=full_roster),                     # data
        cm.resolve(cm.AUDIT_CODEX_ARM, cache_path=missing, fail_open=True),         # literal
        cm.resolve_seat_class("medium", cache_path=full_roster),                    # raw tier
    ]
    for pin in seen:
        assert pin.argv_fragment[0] == "-m"
        assert pin.argv_fragment[1] == pin.model
        assert pin.argv_fragment[2] == "-c"
        assert pin.argv_fragment[3] == f"model_reasoning_effort={pin.effort}"


# --------------------------------------------------------------------------- #
# Precedence: env > data > harness literal
# --------------------------------------------------------------------------- #
def test_env_overrides_data(full_roster, monkeypatch):
    monkeypatch.setenv("TEST_CODEX_MODEL", "some-other-model")
    pin = cm.resolve(
        cm.AUDIT_CODEX_ARM, env_var="TEST_CODEX_MODEL", cache_path=full_roster
    )
    assert pin.model == "some-other-model"
    assert pin.provenance_source == "env"
    # Effort stays the ROLE's pin — §4.1 resolves MODEL first, then validates
    # the effort against THAT model.
    assert pin.effort == "xhigh"


def test_env_model_must_support_the_role_effort(full_roster, monkeypatch):
    """The D1/D2 catch: MODEL resolves first, then the effort is re-validated
    against THAT model. An override to a model with a shallower ladder is
    refused rather than emitted as an argv the CLI will reject."""
    monkeypatch.setenv("TEST_CODEX_MODEL", "shallow-model")  # low only
    with pytest.raises(cm.CodexModelError) as exc:
        cm.resolve(
            cm.AUDIT_CODEX_ARM, env_var="TEST_CODEX_MODEL", cache_path=full_roster
        )
    assert "xhigh" in str(exc.value)


def test_env_var_none_skips_the_env_layer(full_roster, monkeypatch):
    """A set variable is irrelevant when the caller did not name one."""
    monkeypatch.setenv("TEST_CODEX_MODEL", "some-other-model")
    pin = cm.resolve(cm.AUDIT_CODEX_ARM, env_var=None, cache_path=full_roster)
    assert pin.model == SOL
    assert pin.provenance_source == "data"


def test_empty_env_var_falls_through_to_data(full_roster, monkeypatch):
    monkeypatch.setenv("TEST_CODEX_MODEL", "   ")
    pin = cm.resolve(
        cm.AUDIT_CODEX_ARM, env_var="TEST_CODEX_MODEL", cache_path=full_roster
    )
    assert pin.model == SOL
    assert pin.provenance_source == "data"


def test_env_slug_absent_from_roster_is_refused(full_roster, monkeypatch):
    monkeypatch.setenv("TEST_CODEX_MODEL", "not-a-real-slug")
    with pytest.raises(cm.CodexModelError):
        cm.resolve(
            cm.AUDIT_CODEX_ARM, env_var="TEST_CODEX_MODEL", cache_path=full_roster
        )
    # Fail-open callers keep the ROLE's identity rather than the bad override.
    pin = cm.resolve(
        cm.AUDIT_CODEX_ARM,
        env_var="TEST_CODEX_MODEL",
        cache_path=full_roster,
        fail_open=True,
    )
    assert pin.model == SOL
    assert pin.provenance_source == "harness_literal"


def test_provenance_values_are_the_declared_three(full_roster, tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_CODEX_MODEL", "some-other-model")
    sources = {
        cm.resolve(cm.AUDIT_CODEX_ARM, cache_path=full_roster).provenance_source,
        cm.resolve(
            cm.AUDIT_CODEX_ARM, env_var="TEST_CODEX_MODEL", cache_path=full_roster
        ).provenance_source,
        cm.resolve(
            cm.AUDIT_CODEX_ARM, cache_path=tmp_path / "gone.json", fail_open=True
        ).provenance_source,
    }
    assert sources == cm.PROVENANCE_SOURCES == {"env", "data", "harness_literal"}


# --------------------------------------------------------------------------- #
# Effort legality against the REAL cache shape
# --------------------------------------------------------------------------- #
def test_object_shape_levels_are_parsed_not_assumed_strings(tmp_path):
    """The load-bearing shape test.

    `supported_reasoning_levels` is a list of OBJECTS keyed `effort`. A parser
    that assumed bare strings would read an EMPTY legal set here and reject a
    perfectly legal pin — so a successful resolve is proof the shape is honoured.
    """
    roster = write_roster(tmp_path, {SOL: ["xhigh"]})
    parsed = cm.load_roster(roster)
    assert parsed[SOL] == frozenset({"xhigh"})
    pin = cm.resolve(cm.AUDIT_CODEX_ARM, cache_path=roster)
    assert pin.provenance_source == "data"


def test_unknown_effort_is_rejected_against_the_real_shape(tmp_path):
    """Same shape, effort genuinely absent -> refused, not silently accepted."""
    roster = write_roster(tmp_path, {SOL: ["low", "medium"]})
    with pytest.raises(cm.CodexModelError) as exc:
        cm.resolve(cm.CHALLENGER_FLOOR, cache_path=roster)  # pinned xhigh
    assert "xhigh" in str(exc.value)
    # ...while an effort the roster DOES list resolves normally, proving the
    # rejection is discrimination and not a blanket failure.
    assert cm.resolve_seat_class("medium", cache_path=roster).provenance_source == "data"


def test_real_roster_parses_if_present():
    if not cm.MODELS_CACHE_PATH.exists():
        pytest.skip("no local codex roster on this host")
    roster = cm.load_roster()
    assert SOL in roster, "the pinned workhorse is absent from the live roster"
    for role, pin in cm._ROLE_PINS.items():
        assert pin.effort in roster[pin.model], f"{role}: live roster rejects the pin"


def test_malformed_roster_is_an_error_not_an_empty_pass(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(cm.CodexModelError):
        cm.load_roster(bad)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"models": []}), encoding="utf-8")
    with pytest.raises(cm.CodexModelError):
        cm.load_roster(empty)


# --------------------------------------------------------------------------- #
# Fail-open vs fail-closed, and the PER-ROLE literal
# --------------------------------------------------------------------------- #
def test_fail_closed_raises_when_the_roster_is_unreadable(tmp_path):
    with pytest.raises(cm.CodexModelError):
        cm.resolve(cm.AUDIT_CODEX_ARM, cache_path=tmp_path / "gone.json")


def test_fail_open_returns_the_literal_when_the_roster_is_unreadable(tmp_path):
    pin = cm.resolve(cm.AUDIT_CODEX_ARM, cache_path=tmp_path / "gone.json", fail_open=True)
    assert pin.model == SOL
    assert pin.effort == "xhigh"
    assert pin.timeout == 2400
    assert pin.provenance_source == "harness_literal"


def test_harness_literal_is_per_role_not_one_global_constant(tmp_path):
    """Each role's fail-open floor is ITS OWN pin — model AND effort.

    A single global literal would silently downgrade an adversarial role to the
    workhorse's pin on every resolver hiccup while reporting success. In this
    revision every role shares one slug, so the EFFORT is what proves the floor
    is per-role; the model half starts to bite once the roles are re-pinned.
    """
    missing = tmp_path / "gone.json"
    for role, expected in cm._ROLE_PINS.items():
        pin = cm.resolve(role, cache_path=missing, fail_open=True)
        assert pin.provenance_source == "harness_literal"
        assert (pin.model, pin.effort) == (expected.model, expected.effort), role
    # ...and they are not all the same pin.
    assert len({p.effort for p in cm._ROLE_PINS.values()}) > 1


def test_unknown_role_raises_even_when_fail_open(full_roster):
    for kwargs in ({}, {"fail_open": True}):
        with pytest.raises(cm.CodexModelError):
            cm.resolve("stuck_escalation", cache_path=full_roster, **kwargs)


def test_role_key_space_is_exactly_three():
    assert cm.ROLES == {"challenger_floor", "ratification_arbiter", "audit_codex_arm"}


# --------------------------------------------------------------------------- #
# The default accessor (H1) — not a fourth role
# --------------------------------------------------------------------------- #
def test_default_accessor_serves_raw_tier_seat_classes(full_roster):
    """convene reaches its guard stack with RAW TIERS as the seat_class token."""
    assert cm.default_model() == SOL
    for raw_tier in ("xhigh", "max", "medium"):
        pin = cm.resolve_seat_class(raw_tier, cache_path=full_roster)
        assert pin.model == cm.default_model(), raw_tier
        assert pin.effort == raw_tier
        assert pin.provenance_source == "data"


def test_role_seat_classes_still_route_to_their_role_pin(full_roster):
    pin = cm.resolve_seat_class(cm.RATIFICATION_ARBITER, cache_path=full_roster)
    assert (pin.model, pin.effort, pin.timeout) == (SOL, "max", 3600)


# --------------------------------------------------------------------------- #
# The positive slug-set assertion
# --------------------------------------------------------------------------- #
def test_reachable_model_set_is_exactly_the_workhorse():
    """Positive control: the WHOLE reachable set, not an absence check.

    Catches any unexpected slug reaching the argv builders in this revision,
    including one nobody thought to name.
    """
    assert cm.reachable_models() == {SOL}


# --------------------------------------------------------------------------- #
# Coupled-pair and no-bare-default guards
# --------------------------------------------------------------------------- #
def test_every_reachable_pin_has_a_recorded_timeout():
    """Guards the fail-open path: `timeout_for` raises, and the fail-open branch
    deliberately does not catch it, so a literal missing from the timeout table
    would turn a fail-OPEN call into an exception."""
    for pin in cm._ROLE_PINS.values():
        assert cm.timeout_for(pin.model, pin.effort) > 0


def test_timeout_lookup_raises_instead_of_defaulting():
    """An unknown TIER has no answer. It must not inherit a scalar default —
    that shape is how a 300s ceiling ended up applied to 5-7 minute calls."""
    with pytest.raises(cm.CodexModelError):
        cm.timeout_for(SOL, "no-such-tier")


def test_a_model_with_no_override_row_takes_its_tier_floor():
    """An env-supplied model the harness has never tabulated still gets a
    coupled, documented timeout — the tier floor — instead of failing the call
    outright or inheriting a bare number."""
    assert cm.timeout_for("some-other-model", "xhigh") == cm.timeout_for(SOL, "xhigh")
    assert cm._MODEL_TIMEOUT_OVERRIDES_S == {}, (
        "no reachable model needs more than its tier floor in this revision; "
        "a row here must ship in the same change as the pin that needs it"
    )


def test_adversarial_tiers_clear_the_in_tree_timeout_floors():
    """Tier and timeout are a coupled pair; the 300s ceiling elsewhere in the
    tree is already known to be below the measured wall-clock for these tiers."""
    assert cm.timeout_for(SOL, "xhigh") >= 2400
    assert cm.timeout_for(SOL, "max") >= 3600


# --------------------------------------------------------------------------- #
# M5 — the emitter is offline by construction
# --------------------------------------------------------------------------- #
def test_emitter_has_no_network_or_subprocess_imports():
    """convene consumes this module FAIL-CLOSED to materialise plans. A socket
    or a subprocess in here would make an offline host unable to materialise any
    plan at all, and would put a network call inside a pre-spend gate."""
    tree = ast.parse(Path(cm.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"socket", "subprocess", "urllib", "http", "requests", "httpx"})


# =========================================================================== #
# S081 stream 3 (WP-R02) — the codex ADAPTER: roster metadata + top_listed()
#
# Design §4.2 (m2) and §4.3. Every roster below is a FIXTURE file under
# tmp_path. `no_live_roster` repoints the module's default path at a tmp file
# that does not exist, so an accidental default-path read fails loudly instead
# of silently consulting ~/.codex/models_cache.json. It asserts that the
# redirect took effect, so the isolation cannot pass vacuously.
# =========================================================================== #
LIVE_TOP = "gpt-6-astra"   # 2026-09-14 live roster, priority 1 (positive control only)


@pytest.fixture()
def no_live_roster(tmp_path, monkeypatch):
    sentinel = tmp_path / "no-live-roster" / "models_cache.json"
    monkeypatch.setattr(cm, "MODELS_CACHE_PATH", sentinel)
    assert cm.MODELS_CACHE_PATH == sentinel and not sentinel.exists()
    assert Path.home() / ".codex" / "models_cache.json" != cm.MODELS_CACHE_PATH
    return sentinel


def _entry(slug, priority, efforts=ALL_EFFORTS, *, visibility="list",
           supported_in_api=True, upgrade=None, omit=()):
    doc = {
        "slug": slug,
        "priority": priority,
        "visibility": visibility,
        "supported_in_api": supported_in_api,
        "supported_reasoning_levels": [
            {"effort": e, "description": f"{e} reasoning"} for e in efforts
        ],
        "upgrade": upgrade,
    }
    for key in omit:
        doc.pop(key, None)
    return doc


def write_meta_roster(tmp_path: Path, entries, *, fetched_at="2026-09-14T13:45:50Z",
                      client_version="0.154.0", name="models_cache.json") -> Path:
    """entries: a list of `_entry(...)` dicts -> a cache file in the live shape."""
    doc = {"fetched_at": fetched_at, "etag": 'W/"fixture"',
           "client_version": client_version, "models": list(entries)}
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def live_roster_2026_09_14(tmp_path: Path) -> Path:
    """Mirrors ~/.codex/models_cache.json as fetched 2026-09-14 (client 0.154.0)."""
    return write_meta_roster(tmp_path, [
        _entry(LIVE_TOP, 1, ["low", "medium", "high", "xhigh", "max", "ultra"]),
        _entry("gpt-reserve", 3, ["low", "medium", "high", "xhigh", "max"], visibility="hide"),
        _entry(SOL, 4, ["low", "medium", "high", "xhigh", "max", "ultra"]),
        _entry("gpt-5.6-terra", 7, ["low", "medium", "high", "xhigh", "max", "ultra"]),
        _entry("gpt-5.6-luna", 8, ["low", "medium", "high", "xhigh", "max"]),
        _entry("gpt-5.5", 12, ["low", "medium", "high", "xhigh"]),
        _entry("codex-auto-review", 43, ["low", "medium", "high", "xhigh", "max"], visibility="hide"),
    ])


# --------------------------------------------------------------------------- #
# Roster-metadata loader
# --------------------------------------------------------------------------- #
def test_load_roster_entries_exposes_per_slug_metadata(tmp_path, no_live_roster):
    path = write_meta_roster(tmp_path, [
        _entry("alpha", 2, ["low", "xhigh"], upgrade="beta"),
        _entry("beta", 5, ["medium"], visibility="hide", supported_in_api=False),
    ], fetched_at="2026-09-14T01:02:03Z", client_version="9.9.9")
    doc = cm.load_roster_entries(path)
    assert doc.fetched_at == "2026-09-14T01:02:03Z"
    assert doc.client_version == "9.9.9"
    assert set(doc.entries) == {"alpha", "beta"}
    alpha, beta = doc.entries["alpha"], doc.entries["beta"]
    assert (alpha.priority, alpha.visibility, alpha.supported_in_api) == (2, "list", True)
    assert alpha.efforts == frozenset({"low", "xhigh"})
    assert alpha.upgrade == "beta"
    assert (beta.priority, beta.visibility, beta.supported_in_api) == (5, "hide", False)
    assert beta.efforts == frozenset({"medium"})
    assert beta.upgrade is None


def test_load_roster_entries_agrees_with_legacy_load_roster(tmp_path, no_live_roster):
    """`load_roster()` keeps its signature and value; both read one parser."""
    path = live_roster_2026_09_14(tmp_path)
    legacy = cm.load_roster(path)
    doc = cm.load_roster_entries(path)
    assert legacy == {slug: e.efforts for slug, e in doc.entries.items()}
    assert all(isinstance(v, frozenset) for v in legacy.values())


def test_load_roster_entries_missing_metadata_is_none_not_invented(tmp_path, no_live_roster):
    path = write_meta_roster(
        tmp_path,
        [_entry("bare", 1, ["xhigh"], omit=("priority", "visibility", "supported_in_api", "upgrade"))],
        fetched_at=None, client_version=None,
    )
    doc = cm.load_roster_entries(path)
    bare = doc.entries["bare"]
    assert bare.priority is None and bare.visibility is None and bare.upgrade is None
    assert bare.supported_in_api is False
    assert doc.fetched_at is None and doc.client_version is None


@pytest.mark.parametrize("content", ["{ not json", json.dumps({"models": []}), json.dumps([1, 2])])
def test_load_roster_entries_malformed_is_an_error(tmp_path, no_live_roster, content):
    bad = tmp_path / "bad.json"
    bad.write_text(content, encoding="utf-8")
    with pytest.raises(cm.CodexModelError):
        cm.load_roster_entries(bad)
    with pytest.raises(cm.CodexModelError):
        cm.top_listed("xhigh", cache_path=bad)


def test_default_path_is_read_at_call_time(tmp_path, monkeypatch, no_live_roster):
    """cache_path=None reads the module path WHEN CALLED (seat_model redirects HOME)."""
    with pytest.raises(cm.CodexModelError):
        cm.top_listed("xhigh")                       # sentinel does not exist
    fixture = write_meta_roster(tmp_path, [_entry("only-one", 1, ["xhigh"])])
    monkeypatch.setattr(cm, "MODELS_CACHE_PATH", fixture)
    assert cm.top_listed("xhigh") == "only-one"


# --------------------------------------------------------------------------- #
# top_listed(effort) — selection rules (design §4.3)
# --------------------------------------------------------------------------- #
def test_a_new_priority_one_listed_slug_is_followed(tmp_path, no_live_roster):
    base = [_entry(SOL, 4), _entry("gpt-5.5", 12, ["low", "medium", "high", "xhigh"])]
    control = write_meta_roster(tmp_path, base, name="control.json")
    assert cm.top_listed("xhigh", cache_path=control) == SOL          # CONTROL
    newer = write_meta_roster(tmp_path, [_entry("brand-new-top", 1)] + base, name="new.json")
    assert cm.top_listed("xhigh", cache_path=newer) == "brand-new-top"


def test_a_hidden_entry_is_never_selected(tmp_path, no_live_roster):
    hidden = write_meta_roster(tmp_path, [
        _entry("gpt-reserve", 3, visibility="hide"),
        _entry("codex-auto-review", 0, visibility="hide"),
        _entry(SOL, 4),
    ], name="hidden.json")
    assert cm.top_listed("xhigh", cache_path=hidden) == SOL
    # CONTROL: the same entry with visibility "list" wins on priority, so the
    # exclusion above is the visibility rule and not an accident of ordering.
    listed = write_meta_roster(tmp_path, [_entry("gpt-reserve", 3), _entry(SOL, 4)], name="listed.json")
    assert cm.top_listed("xhigh", cache_path=listed) == "gpt-reserve"


@pytest.mark.parametrize("flag", [False, None, "true", 1, "missing"])
def test_an_entry_not_supported_in_api_is_never_selected(tmp_path, no_live_roster, flag):
    omit = ("supported_in_api",) if flag == "missing" else ()
    bad = write_meta_roster(tmp_path, [
        _entry("not-in-api", 1, supported_in_api=None if flag == "missing" else flag, omit=omit),
        _entry(SOL, 4),
    ])
    assert cm.top_listed("xhigh", cache_path=bad) == SOL


def test_supported_in_api_true_is_the_control(tmp_path, no_live_roster):
    good = write_meta_roster(tmp_path, [_entry("in-api", 1, supported_in_api=True), _entry(SOL, 4)])
    assert cm.top_listed("xhigh", cache_path=good) == "in-api"


def test_a_top_lacking_the_effort_falls_to_the_next_eligible(tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [
        _entry("no-max", 1, ["low", "medium", "high", "xhigh"]),
        _entry("has-max", 2, ["low", "medium", "high", "xhigh", "max"]),
    ])
    assert cm.top_listed("max", cache_path=roster) == "has-max"
    assert cm.top_listed("xhigh", cache_path=roster) == "no-max"      # CONTROL


@pytest.mark.parametrize("upgrade", ["successor", {"slug": "successor"}, {"model": "successor"}])
def test_a_populated_upgrade_is_followed(tmp_path, no_live_roster, upgrade):
    roster = write_meta_roster(tmp_path, [
        _entry("superseded", 1, upgrade=upgrade),
        _entry(SOL, 4),
        _entry("successor", 9),       # worse priority: supersession outranks it
    ])
    sel = cm.select_top("xhigh", cache_path=roster)
    assert sel.model == "successor"
    assert sel.priority_winner == "superseded"
    assert sel.upgrade_followed is True and sel.upgrade_ignored_reason is None
    assert cm.top_listed("xhigh", cache_path=roster) == "successor"


def test_a_null_upgrade_keeps_the_priority_winner(tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [_entry("winner", 1, upgrade=None), _entry("successor", 9)])
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.upgrade_followed, sel.upgrade_ignored_reason) == ("winner", False, None)


@pytest.mark.parametrize(
    "target, upgrade, fragment",
    [
        (_entry("successor", 9, visibility="hide"), "successor", "visibility"),
        (_entry("successor", 9, supported_in_api=False), "successor", "supported_in_api"),
        (_entry("successor", 9, ["low", "medium"]), "successor", "xhigh"),
        (None, "successor", "not in the roster"),
        (None, {"note": "no slug here"}, "names no slug"),
        (None, 42, "names no slug"),
        (None, "winner", "itself"),
    ],
    ids=["hidden", "not-in-api", "lacks-effort", "absent", "object-without-slug", "non-string", "self"],
)
def test_an_ineligible_upgrade_is_ignored_with_a_reason(tmp_path, no_live_roster, target, upgrade, fragment):
    entries = [_entry("winner", 1, upgrade=upgrade), _entry(SOL, 4)]
    if target is not None:
        entries.append(target)
    roster = write_meta_roster(tmp_path, entries)
    sel = cm.select_top("xhigh", cache_path=roster)
    assert sel.model == "winner" == sel.priority_winner     # never jumps to the target
    assert sel.upgrade_followed is False
    assert sel.upgrade_ignored_reason and fragment in sel.upgrade_ignored_reason
    assert cm.top_listed("xhigh", cache_path=roster) == "winner"


def test_the_upgrade_is_one_hop_only(tmp_path, no_live_roster):
    """The target's own `upgrade` is not chased: selection is bounded and loop-free."""
    roster = write_meta_roster(tmp_path, [
        _entry("a", 1, upgrade="b"),
        _entry("b", 5, upgrade="c"),
        _entry("c", 9, upgrade="a"),
    ])
    assert cm.top_listed("xhigh", cache_path=roster) == "b"


@pytest.mark.parametrize(
    "entries",
    [
        [_entry("h1", 1, visibility="hide"), _entry("h2", 2, visibility="hide")],
        [_entry("n1", 1, supported_in_api=False)],
        [_entry("shallow", 1, ["low", "medium"])],
    ],
    ids=["all-hidden", "none-in-api", "none-support-effort"],
)
def test_no_eligible_entry_raises(tmp_path, no_live_roster, entries):
    roster = write_meta_roster(tmp_path, entries)
    with pytest.raises(cm.CodexModelError):
        cm.top_listed("xhigh", cache_path=roster)
    with pytest.raises(cm.CodexModelError):
        cm.select_top("xhigh", cache_path=roster)


def test_an_unreadable_roster_raises_there_is_no_fail_open_here(tmp_path, no_live_roster):
    with pytest.raises(cm.CodexModelError):
        cm.top_listed("xhigh", cache_path=tmp_path / "gone.json")


def test_an_unranked_entry_is_not_eligible(tmp_path, no_live_roster):
    """TOP means lowest priority; an entry with no numeric priority cannot rank.

    INVERTED by #282 R4 (plan K14): a PRESENT, non-null priority that is not an int ("1", True,
    nan) no longer reads as "unranked" — the whole document is invalid. JSON null keeps the
    lenient unranked meaning."""
    for bad_priority in (None,):
        roster = write_meta_roster(
            tmp_path, [_entry("unranked", bad_priority), _entry(SOL, 4)], name="r.json"
        )
        assert cm.top_listed("xhigh", cache_path=roster) == SOL, bad_priority
    for invalid_priority in ("1", True, float("nan")):
        roster = write_meta_roster(
            tmp_path, [_entry("unranked", invalid_priority), _entry(SOL, 4)], name="r.json"
        )
        with pytest.raises(cm.CodexRosterInvalidError):
            cm.top_listed("xhigh", cache_path=roster)
    only_unranked = write_meta_roster(tmp_path, [_entry("unranked", None)], name="u.json")
    with pytest.raises(cm.CodexModelError):
        cm.top_listed("xhigh", cache_path=only_unranked)


def test_a_priority_tie_is_broken_by_slug_not_file_order(tmp_path, no_live_roster):
    one = write_meta_roster(tmp_path, [_entry("zeta", 1), _entry("alpha", 1)], name="one.json")
    two = write_meta_roster(tmp_path, [_entry("alpha", 1), _entry("zeta", 1)], name="two.json")
    assert cm.top_listed("xhigh", cache_path=one) == cm.top_listed("xhigh", cache_path=two) == "alpha"


def test_select_top_carries_roster_provenance(tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [_entry(SOL, 4)],
                               fetched_at="2026-09-01T00:00:00Z", client_version="0.150.0")
    sel = cm.select_top("medium", cache_path=roster)
    assert (sel.model, sel.effort) == (SOL, "medium")
    assert sel.roster_fetched_at == "2026-09-01T00:00:00Z"
    assert sel.roster_client_version == "0.150.0"
    assert isinstance(cm.top_listed("medium", cache_path=roster), str)


# --------------------------------------------------------------------------- #
# Positive control: the 2026-09-14 live roster, as a fixture
# --------------------------------------------------------------------------- #
def test_positive_control_live_roster_shape_selects_its_top(tmp_path, no_live_roster):
    roster = live_roster_2026_09_14(tmp_path)
    assert cm.top_listed("xhigh", cache_path=roster) == LIVE_TOP
    assert cm.top_listed("max", cache_path=roster) == LIVE_TOP
    assert cm.top_listed("medium", cache_path=roster) == LIVE_TOP
    # hidden gpt-reserve (p3) sits between astra (p1) and sol (p4) and is skipped
    without_top = write_meta_roster(
        tmp_path,
        [e for e in json.loads(roster.read_text(encoding="utf-8"))["models"] if e["slug"] != LIVE_TOP],
        name="without-top.json",
    )
    assert cm.top_listed("xhigh", cache_path=without_top) == SOL
    # `minimal` is supported by no live entry
    with pytest.raises(cm.CodexModelError):
        cm.top_listed("minimal", cache_path=roster)


# --------------------------------------------------------------------------- #
# Unchanged owners (design §4.2): one timeout table, one default accessor
# --------------------------------------------------------------------------- #
def test_the_adapter_leaves_the_timeout_owner_and_default_unchanged():
    assert cm._TIMEOUT_FLOOR_S == {
        "minimal": 120, "low": 1200, "medium": 1200, "high": 2400,
        "xhigh": 2400, "max": 3600, "ultra": 5400,
    }
    assert cm.default_model() == SOL


# --------------------------------------------------------------------------- #
# S081 revision 4, D24 (WP-A02) — the floors ARE the watchdog's runaway caps.
#
# Before D24 a codex call was killed by a wall clock (`timeout 600 codex exec`)
# that ran well under the measured wall time of the tiers it guarded. D24 moves
# the stop to INACTIVITY and keeps a runaway cap; this table is the cap the seat
# registry hands callers, so it must equal codex_watch's or a caller cuts its own
# call short with a number the registry itself gave it.
# --------------------------------------------------------------------------- #
def test_d24_tier_floors_equal_the_watchdog_hard_caps():
    codex_watch = pytest.importorskip("codex_watch")
    shared = set(cm._TIMEOUT_FLOOR_S) & set(codex_watch.HARD_CAP_S)
    assert shared == {"low", "medium", "high", "xhigh", "max", "ultra"}
    for effort in sorted(shared):
        assert cm._TIMEOUT_FLOOR_S[effort] == codex_watch.HARD_CAP_S[effort], effort
    # `minimal` is the ONE deliberate asymmetry: codex_model keeps a 120 s floor
    # (no seat can reach it — see the reachability tests below), codex_watch
    # tabulates no row at all and RAISES. It fails closed on both sides.
    assert set(cm._TIMEOUT_FLOOR_S) - set(codex_watch.HARD_CAP_S) == {"minimal"}


def test_d24_no_reachable_codex_seat_resolves_the_minimal_tier(tmp_path, no_live_roster):
    """RULING 3 (team lead, 2026-09-16) — the NEGATIVE, recorded as a test.

    `minimal` stays tabulated at 120 s and NO row is added to codex_watch,
    because nothing can reach it: no live roster model advertises the level, so
    every roster-gated path raises before a timeout is ever looked up.

    The roster here is the PRIORITY-BEARING live mirror on purpose. On a roster
    without priorities every selection raises for that reason instead, which
    would make this test pass while proving nothing about `minimal`."""
    roster = live_roster_2026_09_14(tmp_path)
    for effort, expected in (("minimal", 120), ("low", 1200), ("ultra", 5400)):
        assert cm._TIMEOUT_FLOOR_S[effort] == expected
    # The roster is the gate: no entry advertises `minimal`, so selection raises
    # — and the message says so, not "no numeric priority".
    for call in (cm.top_listed, cm.select_top):
        with pytest.raises(cm.CodexModelError, match="minimal") as exc:
            call("minimal", cache_path=roster)
        assert "does not support" in str(exc.value)
        assert "no numeric priority" not in str(exc.value)
    # CONTROL: on the SAME roster a tier it does advertise selects and prices.
    assert cm.timeout_for(cm.top_listed("xhigh", cache_path=roster), "xhigh") == 2400
    # No role pin names it either — the three legacy pins are xhigh/max only.
    assert {pin.effort for pin in cm._ROLE_PINS.values()} == {"xhigh", "max"}


def test_a_followed_top_still_gets_a_strict_coupled_timeout(tmp_path, no_live_roster):
    roster = live_roster_2026_09_14(tmp_path)
    top = cm.top_listed("max", cache_path=roster)
    assert cm.timeout_for(top, "max") == 3600
    with pytest.raises(cm.CodexModelError):
        cm.timeout_for(top, "no-such-tier")


# --------------------------------------------------------------------------- #
# Offline by construction, checked at RUN time as well as by import scan
# --------------------------------------------------------------------------- #
def test_top_listed_opens_no_socket_and_spawns_no_process(tmp_path, no_live_roster, monkeypatch):
    import socket
    import subprocess

    def _boom(*_a, **_k):
        raise AssertionError("codex adapter must not touch the network or spawn a process")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    roster = live_roster_2026_09_14(tmp_path)
    assert cm.top_listed("xhigh", cache_path=roster) == LIVE_TOP
    assert cm.select_top("max", cache_path=roster).model == LIVE_TOP
    assert LIVE_TOP in cm.load_roster_entries(roster).entries
    upgraded = write_meta_roster(tmp_path, [_entry("a", 1, upgrade="b"), _entry("b", 2)], name="u.json")
    assert cm.top_listed("xhigh", cache_path=upgraded) == "b"


# =========================================================================== #
# #282 R4 (plan K14) — the roster has THREE states, and the loader names two of them
#
#   absent   no models_cache.json                 -> CodexRosterAbsentError
#   invalid  unreadable, not JSON, wrong shapes,  -> CodexRosterInvalidError
#            bad field types
#   valid    the document parses (no_eligible is a question select_top answers later)
#
# Both errors are CodexModelError subclasses, so every existing `except CodexModelError`
# keeps working. No TypeError / AttributeError / ValueError may escape the loader for any
# field type: before R4 `supported_reasoning_levels: true` raised TypeError out of the
# loader, through seat_model, and out of `import audit_spawn`.
# =========================================================================== #
def _invalid_doc(case):
    """(content bytes-or-text, expected fragment) for one K14 invalid shape."""
    good = [_entry(SOL, 4), _entry("gpt-5.5", 12, ["low", "medium", "high", "xhigh"])]

    def roster(entries):
        return json.dumps({"fetched_at": "2026-09-14T13:45:50Z", "client_version": "0.154.0",
                           "models": entries})

    def with_first(**fields):
        first = dict(good[0])
        first.update(fields)
        return roster([first] + good[1:])

    kind, value = case
    if kind == "srl":
        return with_first(supported_reasoning_levels=value)
    if kind == "entry":
        return roster([value] + good)
    if kind == "priority":
        return with_first(priority=value)
    if kind == "level_element":
        return with_first(supported_reasoning_levels=[{"effort": "xhigh"}, value])
    if kind == "raw":
        return value
    raise AssertionError(case)


_INVALID_CASES = [
    ("srl", True), ("srl", 7), ("srl", None), ("srl", "x"), ("srl", {}),
    ("entry", 1), ("entry", "s"), ("entry", None),
    ("priority", True), ("priority", 1.5), ("priority", float("nan")), ("priority", "1"),
    ("level_element", 5),
    ("raw", json.dumps({"models": []})),
    ("raw", json.dumps([1, 2])),
    ("raw", json.dumps({"models": "nope"})),
    ("raw", json.dumps({"no_models": []})),
    ("raw", json.dumps({"models": [{"no_slug": 1}]})),
    ("raw", "{ not json"),
]


@pytest.mark.parametrize("case", _INVALID_CASES, ids=[f"{k}-{v!r}"[:40] for k, v in _INVALID_CASES])
def test_r4_every_invalid_shape_is_a_roster_invalid_error_never_another_type(tmp_path, no_live_roster, case):
    path = tmp_path / "models_cache.json"
    path.write_text(_invalid_doc(case), encoding="utf-8")
    for call in (lambda: cm.load_roster_entries(path), lambda: cm.load_roster(path),
                 lambda: cm.select_top("xhigh", cache_path=path), lambda: cm.top_listed("xhigh", cache_path=path)):
        with pytest.raises(cm.CodexRosterInvalidError) as info:     # any other type fails this test
            call()
        assert type(info.value) is cm.CodexRosterInvalidError
        assert isinstance(info.value, cm.CodexModelError)            # existing except clauses keep working
        assert not isinstance(info.value, cm.CodexRosterAbsentError)
        assert str(path) in str(info.value)
    # the legacy resolve() shim: fail-closed raises the same error, fail-open keeps the literal
    with pytest.raises(cm.CodexRosterInvalidError):
        cm.resolve(cm.AUDIT_CODEX_ARM, cache_path=path)
    assert cm.resolve(cm.AUDIT_CODEX_ARM, cache_path=path, fail_open=True).provenance_source == "harness_literal"


def test_r4_an_unreadable_or_undecodable_file_is_invalid_with_its_cause(tmp_path, no_live_roster):
    """Any OSError other than FileNotFoundError, and bytes that are not UTF-8, are INVALID. The
    cause is chained, so freshness_nudge (which tells absent from invalid by __cause__) still can."""
    directory = tmp_path / "is-a-directory.json"
    directory.mkdir()
    with pytest.raises(cm.CodexRosterInvalidError) as info:
        cm.load_roster_entries(directory)
    assert isinstance(info.value.__cause__, OSError) and not isinstance(info.value.__cause__, FileNotFoundError)
    undecodable = tmp_path / "latin1.json"
    undecodable.write_bytes(b'{"models": [{"slug": "caf\xe9"}]}')
    with pytest.raises(cm.CodexRosterInvalidError) as info:
        cm.load_roster_entries(undecodable)
    assert isinstance(info.value.__cause__, ValueError)
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() != 0:
        locked = write_meta_roster(tmp_path, [_entry(SOL, 4)], name="locked.json")
        locked.chmod(0)
        try:
            with pytest.raises(cm.CodexRosterInvalidError) as info:
                cm.load_roster_entries(locked)
            assert isinstance(info.value.__cause__, PermissionError)
        finally:
            locked.chmod(0o600)


def test_r4_a_missing_file_is_absent_not_invalid(tmp_path, no_live_roster):
    missing = tmp_path / "gone" / "models_cache.json"
    for call in (lambda: cm.load_roster_entries(missing), lambda: cm.load_roster(missing),
                 lambda: cm.select_top("xhigh", cache_path=missing)):
        with pytest.raises(cm.CodexRosterAbsentError) as info:
            call()
        assert isinstance(info.value, cm.CodexModelError)
        assert not isinstance(info.value, cm.CodexRosterInvalidError)
        assert isinstance(info.value.__cause__, FileNotFoundError)   # freshness_nudge's absent test
    # the default path (read at call time) is the same answer
    with pytest.raises(cm.CodexRosterAbsentError):
        cm.load_roster_entries()
    assert issubclass(cm.CodexRosterAbsentError, cm.CodexModelError)
    assert issubclass(cm.CodexRosterInvalidError, cm.CodexModelError)


def test_r4_absent_keys_and_null_priority_stay_lenient(tmp_path, no_live_roster):
    """CONTROL for the invalid predicate: ABSENT keys, a JSON-null priority, an object level without
    an `effort` string and odd types on fields K14 does not name keep today's lenient meaning."""
    path = write_meta_roster(tmp_path, [
        _entry("no-levels", 1, omit=("supported_reasoning_levels",)),
        _entry("null-priority", None),
        dict(_entry("odd-fields", 2), visibility=7, supported_in_api="true", upgrade=42,
             supported_reasoning_levels=[{"effort": 5}, {"no_effort": "x"}, "xhigh"]),
        _entry(SOL, 4),
    ])
    doc = cm.load_roster_entries(path)
    assert doc.entries["no-levels"].efforts == frozenset() and doc.entries["no-levels"].priority == 1
    assert doc.entries["null-priority"].priority is None
    odd = doc.entries["odd-fields"]
    assert (odd.visibility, odd.supported_in_api, odd.efforts) == (None, False, frozenset({"xhigh"}))
    assert cm.top_listed("xhigh", cache_path=path) == SOL


def test_r4_control_the_live_shape_fixture_parses(tmp_path, no_live_roster):
    doc = cm.load_roster_entries(live_roster_2026_09_14(tmp_path))
    assert len(doc.entries) == 7 and all(isinstance(e.priority, int) for e in doc.entries.values())
    assert cm.top_listed("xhigh", cache_path=doc.path) == LIVE_TOP


# =========================================================================== #
# #282 R16 (plan K25-K28) — a priority tie at the top never picks by slug
#
# The vendor roster refresh at 2026-09-15T20:45:50Z set gpt-5.6-sol to priority 1, level with
# gpt-6-astra, and the (priority, slug) order served sol on every codex TOP seat. Priority is the
# vendor's PICKER order, not a capability ranking. Among ELIGIBLE entries tied at the lowest
# priority select_top now prefers (1) the higher model generation parsed from the slug, then
# (2) the incumbent, then (3) slug; TopSelection names the deciding rule (tie_break) and the other
# tied slugs (tied_with), and both stay None / () when there is no tie.
#
# Every behaviour below carries a CONTROL. The pre-R16 CONTROL reproduces the old ranking key
# `(priority, slug)` over the same eligible entries, so the fixture is shown to produce the
# defect when the rule is absent.
# =========================================================================== #
def live_tie_roster_2026_09_15(tmp_path: Path, *, name="models_cache.json") -> Path:
    """Mirrors ~/.codex/models_cache.json as refreshed 2026-09-15T20:45:50Z (client 0.154.0,
    sha256 c039beea...9150): sol moved 4 -> 1 and now ties astra. File order as live (sol first)."""
    return write_meta_roster(tmp_path, [
        _entry(TIE_SOL, 1, ["low", "medium", "high", "xhigh", "max", "ultra"]),
        _entry(LIVE_TOP, 1, ["low", "medium", "high", "xhigh", "max", "ultra"]),
        _entry("gpt-reserve", 3, ["low", "medium", "high", "xhigh", "max"], visibility="hide"),
        _entry("gpt-5.6-terra", 7, ["low", "medium", "high", "xhigh", "max", "ultra"]),
        _entry("gpt-5.6-luna", 8, ["low", "medium", "high", "xhigh", "max"]),
        _entry("gpt-5.5", 12, ["low", "medium", "high", "xhigh"]),
        _entry("codex-auto-review", 43, ["low", "medium", "high", "xhigh", "max"], visibility="hide"),
    ], fetched_at="2026-09-15T20:45:50.262822553Z", name=name)


def _pre_r16_winner(path: Path, effort: str) -> str:
    """The pre-R16 priority winner: the old ranking key over the same eligible entries."""
    doc = cm.load_roster_entries(path)
    ranked = sorted((e for e in doc.entries.values()
                     if e.priority is not None and cm._ineligibility(e, effort) is None),
                    key=lambda e: (e.priority, e.slug))
    return ranked[0].slug


@pytest.mark.parametrize("effort", ["xhigh", "max", "medium"])
def test_r16_a_the_live_tie_roster_selects_astra_by_generation(tmp_path, no_live_roster, effort):
    roster = live_tie_roster_2026_09_15(tmp_path)
    sel = cm.select_top(effort, cache_path=roster)
    assert (sel.model, sel.priority_winner) == (LIVE_TOP, LIVE_TOP)
    assert (sel.tie_break, sel.tied_with) == ("generation", (TIE_SOL,))
    assert (sel.upgrade_followed, sel.upgrade_ignored_reason) == (False, None)
    assert cm.top_listed(effort, cache_path=roster) == LIVE_TOP
    # CONTROL: the same roster through the pre-R16 ordering serves sol (the live defect).
    assert _pre_r16_winner(roster, effort) == TIE_SOL


def test_r16_a_the_tie_answer_does_not_depend_on_file_order(tmp_path, no_live_roster):
    live = live_tie_roster_2026_09_15(tmp_path)
    entries = json.loads(live.read_text(encoding="utf-8"))["models"]
    flipped = write_meta_roster(tmp_path, list(reversed(entries)), name="flipped.json")
    for path in (live, flipped):
        sel = cm.select_top("xhigh", cache_path=path)
        assert (sel.model, sel.tie_break, sel.tied_with) == (LIVE_TOP, "generation", (TIE_SOL,))


def test_r16_b_equal_generations_prefer_the_incumbent(tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [_entry(TIE_SOL, 1), _entry("gpt-5.6-terra", 1), _entry("gpt-5.5", 4)])
    sel = cm.select_top("xhigh", cache_path=roster, incumbent="gpt-5.6-terra")
    assert (sel.model, sel.priority_winner, sel.tie_break, sel.tied_with) == \
        ("gpt-5.6-terra", "gpt-5.6-terra", "incumbent", (TIE_SOL,))
    # CONTROL: no incumbent -> slug (ascending), exactly as before R16.
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.tie_break, sel.tied_with) == (TIE_SOL, "slug", ("gpt-5.6-terra",))
    assert sel.model == _pre_r16_winner(roster, "xhigh")


@pytest.mark.parametrize("incumbent", [LIVE_TOP, "gpt-5.5", "gpt-not-listed", ""])
def test_r16_b_an_incumbent_outside_the_tied_set_is_not_consulted(tmp_path, no_live_roster, incumbent):
    """astra is in the roster but HIDDEN (not eligible), gpt-5.5 is eligible but not tied, the third
    is absent: none of them is among the entries tied at the lowest priority -> slug."""
    roster = write_meta_roster(tmp_path, [
        _entry(LIVE_TOP, 1, visibility="hide"), _entry(TIE_SOL, 1), _entry("gpt-5.6-terra", 1), _entry("gpt-5.5", 4),
    ])
    sel = cm.select_top("xhigh", cache_path=roster, incumbent=incumbent)
    assert (sel.model, sel.tie_break, sel.tied_with) == (TIE_SOL, "slug", ("gpt-5.6-terra",))
    # CONTROL: an incumbent that IS tied decides.
    assert cm.select_top("xhigh", cache_path=roster, incumbent="gpt-5.6-terra").tie_break == "incumbent"


def test_r16_b_generation_is_decided_before_the_incumbent(tmp_path, no_live_roster):
    """The incumbent counts only when it survives the generation rule (K26)."""
    roster = write_meta_roster(tmp_path, [_entry(TIE_SOL, 1), _entry(LIVE_TOP, 1), _entry("gpt-5.6-terra", 1)])
    sel = cm.select_top("xhigh", cache_path=roster, incumbent=TIE_SOL)
    assert (sel.model, sel.tie_break, sel.tied_with) == (LIVE_TOP, "generation", (TIE_SOL, "gpt-5.6-terra"))
    # CONTROL: without astra the same incumbent decides between the two equal generations.
    no_astra = write_meta_roster(tmp_path, [_entry(TIE_SOL, 1), _entry("gpt-5.6-terra", 1)], name="n.json")
    sel = cm.select_top("xhigh", cache_path=no_astra, incumbent="gpt-5.6-terra")
    assert (sel.model, sel.tie_break) == ("gpt-5.6-terra", "incumbent")


def test_r16_c_no_tie_is_unchanged(tmp_path, no_live_roster):
    roster = live_roster_2026_09_14(tmp_path)          # the pre-refresh shape: astra p1, sol p4
    for incumbent in (None, TIE_SOL, LIVE_TOP):
        sel = cm.select_top("xhigh", cache_path=roster, incumbent=incumbent)
        assert (sel.model, sel.priority_winner, sel.tie_break, sel.tied_with) == (LIVE_TOP, LIVE_TOP, None, ())
    # CONTROL: the pre-R16 ordering agrees on an untied roster (R16 changes nothing there).
    assert _pre_r16_winner(roster, "xhigh") == LIVE_TOP
    # CONTROL: the same shape with sol moved to 1 is a tie.
    assert cm.select_top("xhigh", cache_path=live_tie_roster_2026_09_15(tmp_path, name="t.json")).tie_break \
        == "generation"


def test_r16_d_an_upgrade_on_the_tie_winner_is_still_followed(tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [
        _entry(TIE_SOL, 1), _entry(LIVE_TOP, 1, upgrade="gpt-7-nova"), _entry("gpt-7-nova", 9),
    ])
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.priority_winner, sel.upgrade_followed) == ("gpt-7-nova", LIVE_TOP, True)
    assert (sel.tie_break, sel.tied_with) == ("generation", (TIE_SOL,))
    # An upgrade on the tie LOSER is never followed: the winner is decided first.
    loser = write_meta_roster(tmp_path, [
        _entry(TIE_SOL, 1, upgrade="gpt-7-nova"), _entry(LIVE_TOP, 1), _entry("gpt-7-nova", 9),
    ], name="loser.json")
    sel = cm.select_top("xhigh", cache_path=loser)
    assert (sel.model, sel.upgrade_followed, sel.tie_break) == (LIVE_TOP, False, "generation")


def test_r16_d_control_an_ineligible_upgrade_target_on_the_tie_winner_is_ignored_with_the_reason(
        tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [
        _entry(TIE_SOL, 1), _entry(LIVE_TOP, 1, upgrade="gpt-7-nova"), _entry("gpt-7-nova", 9, visibility="hide"),
    ])
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.priority_winner, sel.upgrade_followed) == (LIVE_TOP, LIVE_TOP, False)
    assert "visibility" in sel.upgrade_ignored_reason
    assert (sel.tie_break, sel.tied_with) == ("generation", (TIE_SOL,))


@pytest.mark.parametrize("slug, generation", [
    ("gpt-6-astra", (6, 0)),
    ("gpt-5.6-sol", (5, 6)),
    ("gpt-5.5", (5, 5)),
    ("gpt-6", (6, 0)),
    ("gpt-5.10-codex", (5, 10)),
    ("gpt-5.9-codex", (5, 9)),
    ("gpt-12.0-x", (12, 0)),
    ("gpt-reserve", None),
    ("codex-auto-review", None),
    ("gpt-5.6.1-sol", None),         # a third component does not match the K28 prefix
    ("gpt-6astra", None),            # the major must end at "-" or the end of the slug
    ("GPT-6-astra", None),
    ("gpt-\u0666-astra", None),      # ARABIC-INDIC DIGIT SIX: ASCII digits only
    ("gpt-6\n", None),               # a trailing newline is not the end of the slug
    ("xgpt-6-astra", None),
    ("", None),
])
def test_r16_e_generation_parse_table(slug, generation):
    assert cm._generation(slug) == generation


def test_r16_e_generations_compare_numerically_not_as_strings(tmp_path, no_live_roster):
    assert cm._generation("gpt-6-astra") > cm._generation("gpt-5.6-sol") > cm._generation("gpt-5.5")
    assert cm._generation("gpt-5.10-codex") > cm._generation("gpt-5.9-codex")
    roster = write_meta_roster(tmp_path, [_entry("gpt-5.9-codex", 1), _entry("gpt-5.10-codex", 1)])
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.tie_break, sel.tied_with) == ("gpt-5.10-codex", "generation", ("gpt-5.9-codex",))
    # CONTROL: compared as strings the minor "9" outranks "10", so a string compare would serve 5.9.
    # (The slug rule alone would also pick 5.10 here, which is why tie_break must say "generation".)
    assert "9" > "10"


def test_r16_e_unparseable_slugs_rank_below_parseable_and_equal_among_themselves(tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [_entry("alpha", 1), _entry("zeta", 1), _entry("gpt-5.5", 1)])
    sel = cm.select_top("xhigh", cache_path=roster, incumbent="alpha")
    assert (sel.model, sel.tie_break, sel.tied_with) == ("gpt-5.5", "generation", ("alpha", "zeta"))
    # Two unparseable slugs are equal on the generation rule: the incumbent, then slug, decides.
    both = write_meta_roster(tmp_path, [_entry("zeta", 1), _entry("alpha", 1)], name="both.json")
    sel = cm.select_top("xhigh", cache_path=both, incumbent="zeta")
    assert (sel.model, sel.tie_break, sel.tied_with) == ("zeta", "incumbent", ("alpha",))
    sel = cm.select_top("xhigh", cache_path=both)
    assert (sel.model, sel.tie_break, sel.tied_with) == ("alpha", "slug", ("zeta",))


@pytest.mark.parametrize("peer", [
    _entry("gpt-7-hidden", 1, visibility="hide"),
    _entry("gpt-7-noapi", 1, supported_in_api=False),
    _entry("gpt-7-shallow", 1, ["low", "medium"]),
], ids=["hidden", "not-in-api", "lacks-effort"])
def test_r16_f_an_ineligible_entry_at_the_same_priority_is_not_a_tie(tmp_path, no_live_roster, peer):
    roster = write_meta_roster(tmp_path, [_entry(TIE_SOL, 1), peer])
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.tie_break, sel.tied_with) == (TIE_SOL, None, ())
    # CONTROL: the same peer made eligible for the effort IS a tie, and its generation wins.
    eligible = dict(peer, visibility="list", supported_in_api=True,
                    supported_reasoning_levels=[{"effort": e} for e in ALL_EFFORTS])
    tied = write_meta_roster(tmp_path, [_entry(TIE_SOL, 1), eligible], name="tied.json")
    sel = cm.select_top("xhigh", cache_path=tied)
    assert (sel.model, sel.tie_break, sel.tied_with) == (peer["slug"], "generation", (TIE_SOL,))


def test_r16_the_tie_is_detected_per_effort(tmp_path, no_live_roster):
    """A tie at one effort is no tie at another where one of the two cannot serve."""
    roster = write_meta_roster(tmp_path, [_entry(TIE_SOL, 1), _entry(LIVE_TOP, 1, ["low", "medium", "high", "xhigh"])])
    assert cm.select_top("xhigh", cache_path=roster).tie_break == "generation"
    sel = cm.select_top("max", cache_path=roster)
    assert (sel.model, sel.tie_break, sel.tied_with) == (TIE_SOL, None, ())


def test_r16_top_selection_tie_fields_default_to_no_tie():
    sel = cm.TopSelection(model="m", effort="xhigh", priority_winner="m", upgrade_followed=False,
                          upgrade_ignored_reason=None, roster_fetched_at=None, roster_client_version=None)
    assert (sel.tie_break, sel.tied_with) == (None, ())
    assert cm.TIE_BREAKS == ("generation", "incumbent", "slug")


# =========================================================================== #
# #282 fix round 1 — F14 (plan K45): `tied_with` is the OTHER slugs, so it excludes
# the SERVED model as well as the priority winner. When the winner's `upgrade` names
# a slug from the same tie, the served model is a tie member and the pre-fix tuple
# still listed it, which is what let the digest print `sol = sol -> sol`.
# `tied_with` may therefore now be EMPTY while a tie happened; `tie_break` is what
# says a tie happened, and it is unchanged.
# =========================================================================== #

def test_f14_tied_with_excludes_the_served_model_when_the_upgrade_names_a_tie_member(
        tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [_entry(TIE_SOL, 1), _entry(LIVE_TOP, 1, upgrade=TIE_SOL)])
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.priority_winner, sel.upgrade_followed) == (TIE_SOL, LIVE_TOP, True)
    assert (sel.tie_break, sel.tied_with) == ("generation", ())     # a tie, and no OTHER slug left
    # CONTROL: the same tie with no upgrade keeps the loser in tied_with.
    plain = write_meta_roster(tmp_path, [_entry(TIE_SOL, 1), _entry(LIVE_TOP, 1)], name="plain.json")
    sel = cm.select_top("xhigh", cache_path=plain)
    assert (sel.model, sel.priority_winner, sel.tied_with) == (LIVE_TOP, LIVE_TOP, (TIE_SOL,))
    # A three-way tie drops only the served member; the other loser stays.
    three = write_meta_roster(tmp_path, [
        _entry(TIE_SOL, 1), _entry("gpt-5.6-terra", 1), _entry(LIVE_TOP, 1, upgrade=TIE_SOL),
    ], name="three.json")
    sel = cm.select_top("xhigh", cache_path=three)
    assert (sel.model, sel.priority_winner, sel.tied_with) == (TIE_SOL, LIVE_TOP, ("gpt-5.6-terra",))
    # CONTROL: an upgrade target OUTSIDE the tie leaves tied_with exactly as before (R16 d).
    outside = write_meta_roster(tmp_path, [
        _entry(TIE_SOL, 1), _entry(LIVE_TOP, 1, upgrade="gpt-7-nova"), _entry("gpt-7-nova", 9),
    ], name="outside.json")
    sel = cm.select_top("xhigh", cache_path=outside)
    assert (sel.model, sel.priority_winner, sel.tied_with) == ("gpt-7-nova", LIVE_TOP, (TIE_SOL,))


# =========================================================================== #
# #282 fix round 1 — F12 and F13 (plan K43).
#
# F12  `_generation`'s `int()` on an unbounded digit run raised ValueError (CPython's
#      4300-digit str->int limit) from inside `_break_tie`, i.e. PAST every fail-open
#      boundary: seat_model catches CodexModelError, not ValueError. The digit groups are
#      now `\d{1,9}`, so a longer run simply does not MATCH and the slug is unparseable —
#      the rule the module already had for an unparseable slug, and no exception anywhere.
#
# F13  A field-type fault on an entry that could never be selected (hidden, or not in the
#      API) invalidated the WHOLE document, taking every fail-closed codex seat and every
#      convene down. Such an entry is now SKIPPED and its slug recorded; a fault on a
#      SELECTABLE entry (visibility "list" AND supported_in_api true, read literally from
#      the raw entry) still invalidates, and SHAPE faults are untouched.
# =========================================================================== #
_LONG_RUN = "9" * 4301          # > CPython's 4300-digit int() limit: int() raised here
_NINE_NINES = "9" * 9           # the boundary the fix keeps parseable


def test_fr1_f12_a_4301_digit_generation_slug_never_raises_and_ranks_below_every_parseable_one(
        tmp_path, no_live_roster):
    """F12: the slug is UNPARSEABLE, not an exception, and the tie falls to the parseable peer."""
    giant = f"gpt-{_LONG_RUN}-x"
    assert cm._generation(giant) is None                       # unparseable, and it does not raise
    roster = write_meta_roster(tmp_path, [_entry(giant, 1), _entry(LIVE_TOP, 1)])
    sel = cm.select_top("xhigh", cache_path=roster)            # pre-fix: ValueError escapes here
    assert (sel.model, sel.priority_winner) == (LIVE_TOP, LIVE_TOP)
    assert (sel.tie_break, sel.tied_with) == ("generation", (giant,))
    assert cm.top_listed("xhigh", cache_path=roster) == LIVE_TOP
    assert cm.load_roster_entries(roster).entries[giant].priority == 1   # still a first-class entry
    # the incumbent rule is reached too: two unparseable slugs are equal on generation
    other = f"gpt-{_LONG_RUN}-y"
    both = write_meta_roster(tmp_path, [_entry(giant, 1), _entry(other, 1)], name="both.json")
    sel = cm.select_top("xhigh", cache_path=both, incumbent=other)
    assert (sel.model, sel.tie_break) == (other, "incumbent")


def test_fr1_f12_control_a_nine_digit_generation_still_parses_and_ten_does_not(tmp_path, no_live_roster):
    """CONTROL for F12: the bound is 9 digits, not "long slugs are unparseable"."""
    nine = f"gpt-{_NINE_NINES}-x"
    assert cm._generation(nine) == (int(_NINE_NINES), 0)
    assert cm._generation(f"gpt-{_NINE_NINES}") == (int(_NINE_NINES), 0)
    assert cm._generation(f"gpt-5.{_NINE_NINES}-x") == (5, int(_NINE_NINES))
    assert cm._generation(f"gpt-{'9' * 10}-x") is None          # one past the bound
    assert cm._generation(f"gpt-5.{'9' * 10}-x") is None        # the minor group is bounded too
    assert cm._generation(f"gpt-5.{_LONG_RUN}-x") is None
    assert cm._generation("gpt-6-astra") == (6, 0) and cm._generation(TIE_SOL) == (5, 6)
    # and the nine-digit generation WINS the tie it is in, so the rule still ranks by number
    roster = write_meta_roster(tmp_path, [_entry(nine, 1), _entry(LIVE_TOP, 1)])
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.tie_break, sel.tied_with) == (nine, "generation", (LIVE_TOP,))


def test_fr1_f13_a_field_type_fault_on_a_hidden_entry_skips_it_and_keeps_the_roster_valid(
        tmp_path, no_live_roster):
    """F13 headline: a hidden entry with `supported_reasoning_levels: null` is SKIPPED."""
    hidden = dict(_entry("gpt-hidden", 1, visibility="hide"), supported_reasoning_levels=None)
    roster = write_meta_roster(tmp_path, [hidden, _entry(LIVE_TOP, 1), _entry(SOL, 4)])
    doc = cm.load_roster_entries(roster)                      # pre-fix: CodexRosterInvalidError
    assert doc.entries_skipped == ("gpt-hidden",)
    assert "gpt-hidden" not in doc.entries and set(doc.entries) == {LIVE_TOP, SOL}
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.priority_winner) == (LIVE_TOP, LIVE_TOP)
    assert sel.roster_entries_skipped == ("gpt-hidden",)
    assert cm.top_listed("xhigh", cache_path=roster) == LIVE_TOP
    assert cm.load_roster(roster) == {slug: e.efforts for slug, e in doc.entries.items()}


def test_fr1_f13_control_the_same_fault_on_a_listed_api_entry_still_invalidates_the_document(
        tmp_path, no_live_roster):
    """CONTROL for F13: SELECTABLE = visibility "list" AND supported_in_api true, literally."""
    selectable = dict(_entry("gpt-listed", 1), supported_reasoning_levels=None)
    roster = write_meta_roster(tmp_path, [selectable, _entry(LIVE_TOP, 1)])
    for call in (lambda: cm.load_roster_entries(roster), lambda: cm.load_roster(roster),
                 lambda: cm.select_top("xhigh", cache_path=roster),
                 lambda: cm.top_listed("xhigh", cache_path=roster)):
        with pytest.raises(cm.CodexRosterInvalidError) as info:
            call()
        assert type(info.value) is cm.CodexRosterInvalidError
        assert "supported_reasoning_levels" in str(info.value) and str(roster) in str(info.value)
    # and it is the PAIR that decides: either half false makes the entry skippable
    for fields in ({"visibility": "hide"}, {"supported_in_api": False},
                   {"visibility": "list", "supported_in_api": False}):
        variant = write_meta_roster(
            tmp_path, [dict(selectable, **fields), _entry(LIVE_TOP, 1)], name=f"v{len(fields)}{fields}.json")
        assert cm.load_roster_entries(variant).entries_skipped == ("gpt-listed",)


def test_fr1_f13_every_invalid_field_reason_skips_a_non_selectable_entry(tmp_path, no_live_roster):
    """The exact `_invalid_field` reasons, each on a never-selectable entry -> skipped, not invalid."""
    faults = [
        ("srl-true", {"supported_reasoning_levels": True}),
        ("srl-str", {"supported_reasoning_levels": "x"}),
        ("srl-obj", {"supported_reasoning_levels": {}}),
        ("level-int", {"supported_reasoning_levels": [{"effort": "xhigh"}, 5]}),
        ("prio-float", {"priority": 1.0}),
        ("prio-nan", {"priority": float("nan")}),
        ("prio-bool", {"priority": True}),
        ("prio-str", {"priority": "1"}),
    ]
    for name, fields in faults:
        for guard in ({"visibility": "hide"}, {"supported_in_api": False}):
            bad = dict(_entry(name, 1), **guard)
            bad.update(fields)
            roster = write_meta_roster(tmp_path, [bad, _entry(LIVE_TOP, 1)], name=f"{name}-{guard}.json")
            doc = cm.load_roster_entries(roster)
            assert doc.entries_skipped == (name,), (name, guard)
            assert name not in doc.entries
            assert cm.select_top("xhigh", cache_path=roster).model == LIVE_TOP


def test_fr1_f13_a_non_api_entry_with_a_float_priority_is_skipped(tmp_path, no_live_roster):
    """The spec's second named case, with its own control: the float alone is not the fault."""
    bad = dict(_entry("gpt-noapi", 2, supported_in_api=False), priority=1.0)
    roster = write_meta_roster(tmp_path, [bad, _entry(LIVE_TOP, 1)])
    doc = cm.load_roster_entries(roster)
    assert doc.entries_skipped == ("gpt-noapi",) and "gpt-noapi" not in doc.entries
    assert cm.select_top("max", cache_path=roster).roster_entries_skipped == ("gpt-noapi",)
    # CONTROL: the SAME float priority on a listed, API entry is still document-invalid
    listed = write_meta_roster(tmp_path, [dict(_entry("gpt-noapi", 2), priority=1.0),
                                          _entry(LIVE_TOP, 1)], name="listed.json")
    with pytest.raises(cm.CodexRosterInvalidError):
        cm.load_roster_entries(listed)


def test_fr1_f13_shape_faults_and_an_empty_or_all_skipped_roster_stay_invalid(tmp_path, no_live_roster):
    """SHAPE faults are untouched by F13, and skipping never empties the roster silently."""
    shapes = ["{ not json", json.dumps([1, 2]), json.dumps({"no_models": []}),
              json.dumps({"models": "nope"}), json.dumps({"models": []}),
              json.dumps({"models": [7]}),
              json.dumps({"models": [dict(_entry("a", 1, visibility="hide"), priority=1.0), "s"]})]
    for index, raw in enumerate(shapes):
        path = tmp_path / f"shape{index}.json"
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(cm.CodexRosterInvalidError) as info:
            cm.load_roster_entries(path)
        assert type(info.value) is cm.CodexRosterInvalidError, raw
    # EVERY entry skipped -> "no usable", the same error an empty models list gives, and the
    # skipped slugs are NAMED so the state is never silent.
    all_skipped = write_meta_roster(tmp_path, [
        dict(_entry("gpt-skip-a", 1, visibility="hide"), priority=1.0),
        dict(_entry("gpt-skip-b", 2, supported_in_api=False), supported_reasoning_levels=True)],
        name="all.json")
    with pytest.raises(cm.CodexRosterInvalidError) as info:
        cm.load_roster_entries(all_skipped)
    assert "no usable" in str(info.value)
    assert "gpt-skip-a" in str(info.value) and "gpt-skip-b" in str(info.value)


def test_fr1_f13_a_slugless_skip_records_nothing_and_a_duplicate_slug_is_dropped_last_wins(
        tmp_path, no_live_roster):
    """K43's two edge rules: nothing to record without a slug; a skip is last-wins like an entry.

    RE-POINTED by #282 fix round 2 (G6, K58a). K43's last-wins half was written when the pop
    was unconditional, so its fixture made the EARLIER duplicate a default `_entry` — i.e.
    SELECTABLE — and pinned the silent-replacement behaviour G6 removes. Last-wins still holds
    for everything the skip may legally drop, which is what the narrowed fixture now pins; the
    selectable case belongs to
    `test_fr2_g6_a_faulty_duplicate_cannot_silently_replace_a_selectable_entry`.
    """
    slugless = dict(_entry("x", 1, visibility="hide"), supported_reasoning_levels=True)
    slugless.pop("slug")
    roster = write_meta_roster(tmp_path, [slugless, _entry(LIVE_TOP, 1)])
    doc = cm.load_roster_entries(roster)
    assert doc.entries_skipped == () and set(doc.entries) == {LIVE_TOP}
    # a LATER skipped entry drops the earlier NON-SELECTABLE one of the same slug, and is recorded
    dup = write_meta_roster(tmp_path, [
        _entry("gpt-dup", 1, visibility="hide"),
        dict(_entry("gpt-dup", 1, visibility="hide"), priority=1.0),
        _entry(LIVE_TOP, 2)], name="dup.json")
    doc = cm.load_roster_entries(dup)
    assert doc.entries_skipped == ("gpt-dup",) and "gpt-dup" not in doc.entries
    assert cm.select_top("xhigh", cache_path=dup).model == LIVE_TOP


def test_fr2_g6_a_faulty_duplicate_cannot_silently_replace_a_selectable_entry(
        tmp_path, no_live_roster):
    """#282 fix round 2 (G6, K58) half (a): last-wins must not DELETE a selectable entry.

    A listed API `gpt-x` followed by a HIDDEN faulty `gpt-x` used to pop the good entry and
    leave the document VALID with a silently different TOP — strictly WEAKER than the
    pre-F13 fail-closed behaviour F13's own control is meant to preserve. The fault is now
    the document's, named with the slug, the index and the reason.
    """
    good = _entry("gpt-x", 1)
    faulty_dup = dict(_entry("gpt-x", 1, visibility="hide"), supported_reasoning_levels=None)
    roster = write_meta_roster(tmp_path, [good, faulty_dup, _entry(LIVE_TOP, 2)])
    for call in (lambda: cm.load_roster_entries(roster), lambda: cm.load_roster(roster),
                 lambda: cm.select_top("xhigh", cache_path=roster),
                 lambda: cm.top_listed("xhigh", cache_path=roster)):
        with pytest.raises(cm.CodexRosterInvalidError) as info:   # pre-fix: the good entry vanished
            call()
        assert type(info.value) is cm.CodexRosterInvalidError
        text = str(info.value)
        assert "gpt-x" in text and "models[1]" in text and str(roster) in text
        assert "supported_reasoning_levels" in text
    # CONTROL (F13 intact): the SAME hidden faulty entry under a DIFFERENT slug is skipped
    other = write_meta_roster(tmp_path, [good, dict(faulty_dup, slug="gpt-other"),
                                         _entry(LIVE_TOP, 2)], name="other.json")
    doc = cm.load_roster_entries(other)
    assert doc.entries_skipped == ("gpt-other",) and set(doc.entries) == {"gpt-x", LIVE_TOP}
    assert cm.select_top("xhigh", cache_path=other).model == "gpt-x"
    # CONTROL: a faulty duplicate of a NON-SELECTABLE earlier entry keeps skip-and-record —
    # either half of the pair being false is enough, exactly as `_is_selectable` reads it.
    for label, guard in (("hide", {"visibility": "hide"}), ("noapi", {"supported_in_api": False})):
        hidden_first = write_meta_roster(
            tmp_path, [dict(_entry("gpt-x", 1), **guard), faulty_dup, _entry(LIVE_TOP, 2)],
            name=f"hidden-first-{label}.json")
        hdoc = cm.load_roster_entries(hidden_first)
        assert hdoc.entries_skipped == ("gpt-x",) and "gpt-x" not in hdoc.entries, label
        assert cm.select_top("xhigh", cache_path=hidden_first).model == LIVE_TOP, label


def test_fr2_g6_b_a_later_good_entry_clears_the_skip_record(tmp_path, no_live_roster):
    """#282 fix round 2 (G6, K58) half (b): a slug PRESENT in the roster is never also skipped.

    The skip set was add-only, so a faulty entry followed by a good duplicate left the slug in
    `entries_skipped` while it sat in `entries` — a provenance key naming a model that was in
    fact selected.
    """
    faulty = dict(_entry("gpt-y", 1, visibility="hide"), supported_reasoning_levels=None)
    good = _entry("gpt-y", 1)
    roster = write_meta_roster(tmp_path, [faulty, good, _entry(LIVE_TOP, 2)])
    doc = cm.load_roster_entries(roster)
    assert doc.entries_skipped == ()                    # pre-fix: ("gpt-y",), while present
    assert "gpt-y" in doc.entries and set(doc.entries) == {"gpt-y", LIVE_TOP}
    sel = cm.select_top("xhigh", cache_path=roster)
    assert (sel.model, sel.roster_entries_skipped) == ("gpt-y", ())
    # CONTROL: with no later good entry the slug IS recorded, and is absent from the roster
    control = write_meta_roster(tmp_path, [faulty, _entry(LIVE_TOP, 2)], name="control.json")
    cdoc = cm.load_roster_entries(control)
    assert cdoc.entries_skipped == ("gpt-y",) and "gpt-y" not in cdoc.entries
    assert cm.select_top("xhigh", cache_path=control).roster_entries_skipped == ("gpt-y",)
    # and the all-skipped "no usable" error still NAMES what it dropped (F13 unweakened)
    all_gone = write_meta_roster(tmp_path, [faulty], name="allgone.json")
    with pytest.raises(cm.CodexRosterInvalidError) as info:
        cm.load_roster_entries(all_gone)
    assert "no usable" in str(info.value) and "gpt-y" in str(info.value)


def test_fr1_f13_a_clean_roster_records_no_skips_anywhere(tmp_path, no_live_roster):
    """The event-key discipline: absent, not empty-and-present, on every clean path."""
    roster = write_meta_roster(tmp_path, [_entry(LIVE_TOP, 1), _entry(SOL, 4),
                                          _entry("gpt-reserve", 3, visibility="hide")])
    doc = cm.load_roster_entries(roster)
    assert doc.entries_skipped == () and set(doc.entries) == {LIVE_TOP, SOL, "gpt-reserve"}
    assert cm.select_top("xhigh", cache_path=roster).roster_entries_skipped == ()
    assert cm.RosterDocument(path=roster, fetched_at=None, client_version=None, entries={}).entries_skipped == ()
    assert cm.TopSelection(model="m", effort="xhigh", priority_winner="m", upgrade_followed=False,
                           upgrade_ignored_reason=None, roster_fetched_at=None,
                           roster_client_version=None).roster_entries_skipped == ()


# =========================================================================== #
# #302 WP-2 (challenger #4): gpt-6-sol and gpt-6-astra are ONE generation, so a vendor priority flap
# between them is NOT decided by generation (the 2026-09-15 guard above only covered 5.6-sol). A tie
# falls to the incumbent, then to slug; a strict inversion simply follows the roster (auto-follow),
# and seat_model makes that visible with `top_resolved_to_std` (tested in test_seat_model.py).
# Synthetic fixtures, literal slugs, no roster tier read: the point is the selection rule itself.
# =========================================================================== #
SOL6 = "gpt-6-sol"


def test_302_a_sol6_astra_tie_is_decided_by_the_incumbent(tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [_entry(SOL6, 1), _entry(LIVE_TOP, 1), _entry("gpt-5.6-terra", 7)])
    sel = cm.select_top("xhigh", cache_path=roster, incumbent=SOL6)
    assert (sel.model, sel.priority_winner, sel.tie_break, sel.tied_with) == (SOL6, SOL6, "incumbent", (LIVE_TOP,))
    sel = cm.select_top("xhigh", cache_path=roster, incumbent=LIVE_TOP)
    assert (sel.model, sel.tie_break, sel.tied_with) == (LIVE_TOP, "incumbent", (SOL6,))


def test_302_a_sol6_astra_tie_without_an_incumbent_is_decided_by_slug(tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [_entry(SOL6, 1), _entry(LIVE_TOP, 1)])
    for incumbent in (None, "gpt-5.6-terra", "gpt-not-listed"):
        sel = cm.select_top("xhigh", cache_path=roster, incumbent=incumbent)
        assert (sel.model, sel.tie_break, sel.tied_with) == (LIVE_TOP, "slug", (SOL6,)), incumbent
    # CONTROL: the generation rule does NOT fire between the two (both parse as generation 6).
    assert cm.select_top("xhigh", cache_path=roster).tie_break != "generation"


def test_302_a_strict_sol6_over_astra_inversion_follows_the_roster(tmp_path, no_live_roster):
    roster = write_meta_roster(tmp_path, [_entry(SOL6, 1), _entry(LIVE_TOP, 2)])
    for incumbent in (None, LIVE_TOP):
        sel = cm.select_top("xhigh", cache_path=roster, incumbent=incumbent)
        assert (sel.model, sel.tie_break, sel.tied_with) == (SOL6, None, ()), incumbent


def test_302_the_std_fallbacks_stay_on_the_std_tier_not_the_support_tier():
    """design #302 s3.3: DEFAULT_MODEL (and every _ROLE_PINS fallback built on it) is the std tier;
    the support tier is seat_model's consultant_support row only."""
    import model_roster  # type: ignore
    assert cm.DEFAULT_MODEL == cm.default_model() == model_roster.CODEX_STD
    if model_roster.CODEX_SUPPORT != model_roster.CODEX_STD:
        assert model_roster.CODEX_SUPPORT not in cm.reachable_models()
