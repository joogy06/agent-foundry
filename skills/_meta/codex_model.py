#!/usr/bin/env python3
"""codex_model.py — the single source of truth for codex model+effort resolution.

Both codex argv builders (`_meta/audit_spawn.py`'s codex arm and avengers'
`convene.py` guard stacks) call this module instead of hand-rolling `-m` /
`-c model_reasoning_effort=` fragments. One helper owns "which model does this
seat get", so the two axes cannot drift apart (design §2.2).

WHAT THIS FIXES. The premise that a codex model could be routed through
smart-config's `model-policy.yaml` was false and, worse, unsafe: that surface
merges a REPO-LOCAL `<project>/.claude/model-policy.yaml` per leaf, so a
pre-poisoned clone could downgrade the adversary reviewing it (design §2.1).
The pin therefore lives HERE, in the harness, global-only, with no repo-local
override path.

RESOLUTION ORDER — env > data > harness literal. `-m` is ALWAYS emitted; a null
from any layer maps to a literal, NEVER to "omit -m and inherit". Inheriting is
what let a TUI model selection silently upgrade (or downgrade) every headless
call, which is the failure this module exists to end.

  env             an explicit per-call-site environment override (the caller
                  names the variable; `env_var=None` SKIPS this layer entirely).
                  Supplies the MODEL SLUG only — effort stays the role's pin,
                  because §4.1 resolves MODEL FIRST and then validates effort
                  against THAT model's legal set.
  data            the role pin below, CORROBORATED against the local codex
                  roster data file `~/.codex/models_cache.json` (authoritative,
                  on-disk, NO NETWORK). This is the normal, healthy path.
  harness_literal the fail-open floor: the role's own pinned slug returned
                  UNVALIDATED because the roster could not be read or did not
                  corroborate. It preserves BOTH argv shape and model identity,
                  and the provenance string is what makes the breakage visible
                  in the run record instead of silent.

PER-ROLE HARNESS LITERAL, NOT ONE GLOBAL CONSTANT. The fail-open floor for a
named role is THAT ROLE'S OWN slug. A single global workhorse literal would
silently downgrade an adversarial audit to a weaker model on every resolver
hiccup while reporting success — exactly the silent-substitution failure this
cycle repairs. Design §4.1's fail-open clause is about ARGV SHAPE, not model
identity. In THIS revision every role and the default are the same slug, so the
distinction is behaviour-neutral here and only bites when the roles are re-pinned.

FAIL BEHAVIOUR IS THE CALLER'S CHOICE, deliberately (design §4.1):
  `fail_open=True`   -> the role's harness literal. `audit_spawn`'s contract:
                        resolver breakage must never change argv shape.
  `fail_open=False`  -> raises `CodexModelError`. `convene`'s charter is a
                        fail-CLOSED pre-spend gate; it must refuse to spend.

THE ROLE KEY SPACE IS EXACTLY THREE (design §11.3). Two of design §4.2's five
rows — stuck-after-2-attempts escalation, and the inner-loop / mechanical /
smoke / research fan-out — have NO code hook anywhere; they are documentation
deliverables. Giving them `resolve()` keys would create callers-of-nothing.
The fan-out row is served instead by `default_model()`, an ACCESSOR and not a
fourth role: a codex seat whose seat_class is a RAW TIER (`convene.py` passes
`"xhigh"` / `"max"` / a raw pinned token straight through to its guard stack)
takes the DEFAULT model with its own raw tier. Without that accessor a
fail-closed resolver would turn every such seat into a hard error.

OWNERSHIP SPLIT, stated so it is not re-invented (design §11.2):
  LEGALITY  — is this effort supported by this model?  -> HERE, from the roster.
  ADVISORY  — is this legal pair *recommended*?        -> `convene.py`'s
              MEASURED_EFFORT_FINDINGS, keyed (model, tier), from a benchmark.
A tier this module accepts may still carry a recorded "never beat medium" note
at the convene layer. Legal and recommended are different questions.

NO NETWORK, NO SUBPROCESS. Every input is a local file read. `convene.py`
consumes this module FAIL-CLOSED to materialise plans, so a network call in here
would make an offline host unable to materialise any plan at all — and would put
a socket inside a pre-spend gate.

THE CODEX ADAPTER (S081 design §4.2 m2, §4.3). From S081 stream 3 this module is
the codex adapter underneath `_meta/seat_model.py`, which owns the role table.
The adapter surface is:

  load_roster()          slug -> legal efforts (unchanged signature and value)
  load_roster_entries()  per-slug roster METADATA {priority, visibility,
                         supported_in_api, efforts, upgrade} plus the document's
                         fetched_at and client_version
  CodexRosterAbsentError / CodexRosterInvalidError
                         the two loader failures, told apart (#282 R4; below)
  top_listed(effort)     the auto-follow TOP selector (rules on `select_top`)
  select_top(effort, incumbent=)
                         the same selection, with the provenance seat_model records,
                         including how a priority tie was broken (#282 R16; below)
  timeout_for()          STILL the single codex timeout owner, still strict
  default_model()        unchanged

The legacy `resolve(role)` / `resolve_seat_class()` stay as a COMPATIBILITY
SHIM, and their 25 tests remain the regression guard. `_ROLE_PINS` (all
sol-pinned) is NO LONGER CONSULTED BY PRODUCTION CALLERS once S081 WP-R06
(audit_spawn, verification_arbiter_spawn) and WP-R07 (convene) are wired to
seat_model. Until then it serves exactly the callers it served in S080.

THREE ROSTER STATES (#282 R4, plan K14). The loader names two failures, both
CodexModelError subclasses so every existing `except CodexModelError` keeps working:
  absent   no models_cache.json (FileNotFoundError)    -> CodexRosterAbsentError
  invalid  SHAPE faults — any other OSError, bytes that are not UTF-8, not JSON, a top
           level that is not an object, no `models` list, a non-object entry, and no
           usable entry (`models: []` and an all-skipped document included) — plus a
           FIELD-TYPE fault on a SELECTABLE entry (below)
                                                        -> CodexRosterInvalidError
The FIELD-TYPE faults are: `supported_reasoning_levels` PRESENT and not a list, a level
that is neither an object nor a string, and `priority` PRESENT, non-null and not an int
(bool, float incl. nan, string).

#282 fix round 1 (F13, plan K43) narrows WHERE a field-type fault is fatal, without
weakening the predicate. SELECTABLE means the RAW entry has `visibility == "list"` AND
`supported_in_api is True` — the only entries `_ineligibility` can ever pass, so these are
the only ones whose parse decides what gets served. A field-type fault on any OTHER entry
(hidden, or not in the API) now SKIPS that entry and records its slug in
`RosterDocument.entries_skipped` / `TopSelection.roster_entries_skipped`, instead of
invalidating the document: one never-selectable entry used to take every fail-closed codex
seat and every convene down with it. An entry with no usable slug is skipped silently as
before, and a document left with NO usable entry is still invalid — naming what it dropped.

#282 fix round 2 (G6, plan K58) fixes the two DUPLICATE-ORDER holes that narrowing opened,
so a skip can never be a silent downgrade of the selectable set:
  (a) a faulty duplicate may not DELETE a selectable entry. When the slug is already in
      `entries` and the STORED entry was itself selectable, the document is invalid — the
      same fail-closed answer that fault gets on a selectable entry directly. Against a
      NON-selectable earlier entry the skip-and-record of (F13) is unchanged.
  (b) a slug that is PRESENT is never also reported skipped: a good entry replacing an
      earlier faulty one CLEARS the skip record instead of leaving the key naming a model
      that was in fact selected.

ABSENT keys and a JSON-null priority keep their lenient meaning (unranked / no
efforts), and so do fields the predicate does not name. No TypeError,
AttributeError or ValueError escapes the loader for any field type. The third
state, `no_eligible` (a valid roster with nothing selectable), is select_top's
CodexModelError. The OS / decode cause is chained (`raise ... from exc`).

PRIORITY TIES (#282 R16, plan K25-K28). `priority` is the vendor's PICKER order, not a
capability ranking, and it is NOT STABLE: gpt-5.6-sol has been observed at priority 4
(2026-09-15T14:38:49Z), 1 (20:45:50Z, tied with gpt-6-astra), 4 again (22:25:15Z) and 1 again
(22:38:08Z). The first move to 1 is what exposed the defect — ordering the tie by slug served
sol on every codex TOP seat until a freeze held astra — and the flapping since is why the rules
below, not any dated snapshot, are the guarantee: whenever the two tie, gpt-6-astra stays TOP by
generation. Among the ELIGIBLE entries tied at the lowest priority, select_top prefers
  1. generation  the higher model generation parsed from the slug, `gpt-<major>[.<minor>]`
                 (`_generation`: 6 > 5.6 > 5.5, 5.10 > 5.9; an unparseable slug ranks below
                 every parseable one, and two unparseable slugs are equal on this rule)
  2. incumbent   the caller's last recorded TOP (seat_model passes the codex `top` of
                 seat-model-tops.json), counted only when it is still among the entries the
                 generation rule left
  3. slug        ascending, as before, so the answer never depends on file order
TopSelection.tie_break names the rule that decided and tied_with the OTHER tied slugs — neither
the priority winner nor the SERVED model (#282 fix round 1, F14), so a followed upgrade naming a
member of the same tie leaves tied_with EMPTY rather than listing the model being served. Both are
None / () when the lowest priority holds one eligible entry, so an untied roster selects exactly
what it selected before R16; tie_break, not tied_with, is what says a tie happened. An ineligible
entry at the same priority is not a tie. The winner's `upgrade` is followed afterwards, unchanged.

Provenance mapping onto seat_model's SeatPin.provenance.source:
  data            -> `roster`  (the same local models_cache.json evidence)
  env             -> `env`     (carries over)
  harness_literal -> `harness_literal` (carries over)
  (none)          -> `freeze`  NEW, and owned by seat_model alone: a home-tier
                     freeze pin is a seat_model concept, never read here.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# #291: the codex std slug lives in model_roster.py (data only), the one source seat_model reads too.
_META_DIR = str(Path(__file__).resolve().parent)
if _META_DIR not in sys.path:
    sys.path.insert(0, _META_DIR)
import model_roster  # noqa: E402

# --------------------------------------------------------------------------- #
# Role key space — EXACTLY three. See the §11.3 note above before adding a key.
# --------------------------------------------------------------------------- #
CHALLENGER_FLOOR = "challenger_floor"          # avengers skeptic / adversarial critic
RATIFICATION_ARBITER = "ratification_arbiter"  # ratification ceiling (defensive; design §6)
AUDIT_CODEX_ARM = "audit_codex_arm"            # audit_spawn.run_codex_auditor()

#: Where the local codex roster lives. Written by the codex CLI itself; read
#: here for EFFORT LEGALITY only. Never fetched, never written.
MODELS_CACHE_PATH = Path.home() / ".codex" / "models_cache.json"

#: The workhorse. Cheap paths get an EXPLICIT pin — "omit -m" is what let a TUI
#: selection upgrade them. Also the model a raw-tier seat_class resolves onto.
#: #291: the codex std tier, read from model_roster.CODEX_STD (one source with seat_model).
#: #302: it is NOT the consultant_support model - that is model_roster.CODEX_SUPPORT, resolved only by
#: seat_model's consultant_support row. Nothing here reads the support tier: the std fallbacks
#: (_ROLE_PINS challenger floor / ratification arbiter / audit codex arm, raw-tier seat classes)
#: stay on std.
DEFAULT_MODEL = model_roster.CODEX_STD

#: Legal `CodexPin.provenance_source` values (design §11.3).
PROVENANCE_SOURCES = frozenset({"env", "data", "harness_literal"})

#: #282 R16: the rules that can decide a priority tie, in the order they are applied.
TIE_BREAKS: Tuple[str, ...] = ("generation", "incumbent", "slug")

#: #282 R16 (plan K28): the model generation prefix of a codex slug. ASCII digits only, and the
#: major (or major.minor) must end at "-" or at the end of the slug (`\Z`, so a trailing newline
#: never parses).
#: #282 fix round 1 F12: each digit group is BOUNDED at 9. `int()` on an unbounded run raises
#: ValueError past CPython's 4300-digit str->int limit, and it raised from inside the tie-break,
#: i.e. past every fail-open boundary (callers catch CodexModelError, not ValueError). A longer
#: run now simply does not MATCH, so the slug is unparseable — the rule this module already had.
_GENERATION = re.compile(r"gpt-(\d{1,9})(?:\.(\d{1,9}))?(?=-|\Z)", re.ASCII)


class CodexModelError(RuntimeError):
    """Resolution could not be completed against the local roster.

    Raised to fail-CLOSED callers. Fail-OPEN callers get the role's harness
    literal instead — except for a caller bug (an unknown role key), which has
    no literal to fall back to and therefore always raises.
    """


class CodexRosterAbsentError(CodexModelError):
    """#282 R4: there is no roster file at all (the read raised FileNotFoundError).

    The sanctioned state: seat_model serves its harness literal. The
    FileNotFoundError is chained as `__cause__`.
    """


class CodexRosterInvalidError(CodexModelError):
    """#282 R4: a roster file exists but cannot be read or does not have the roster's shape.

    See THREE ROSTER STATES in the module docstring for the exact predicate. Never
    "no roster": seat_model treats it as a resolution failure.
    """


@dataclass(frozen=True)
class _Pin:
    """A (model, effort) pin. The harness literal for one role."""

    model: str
    effort: str


# --------------------------------------------------------------------------- #
# The pin (design §4.2). THIS REVISION PINS CURRENT BEHAVIOUR, deliberately:
# the provenance plumbing ships before any model change, so the first rows
# recorded under the new provenance are not confounded by a simultaneous model
# swap. You cannot tell whether a new model beats the old one while provenance
# is broken.
#
# Efforts are the ones in force TODAY, not a fresh opinion:
#   challenger_floor      xhigh  — SEAT_CLASS_TABLE's codex anti-sycophancy floor
#   ratification_arbiter  max    — SEAT_CLASS_TABLE's codex ratification ceiling
#   audit_codex_arm       xhigh  — what the codex arm inherits from config.toml
#                                  today; pinning `medium` here would CHANGE
#                                  behaviour and confound the baseline (§11.4 M1)
# --------------------------------------------------------------------------- #
_ROLE_PINS: Dict[str, _Pin] = {
    CHALLENGER_FLOOR: _Pin(DEFAULT_MODEL, "xhigh"),
    RATIFICATION_ARBITER: _Pin(DEFAULT_MODEL, "max"),
    AUDIT_CODEX_ARM: _Pin(DEFAULT_MODEL, "xhigh"),
}

#: Public view of the role key space.
ROLES: FrozenSet[str] = frozenset(_ROLE_PINS)

# --------------------------------------------------------------------------- #
# Timeouts. Tier and model are a COUPLED pair (design §3.1): a pin whose call is
# cut short is an AUDIT_UNAVAILABLE, not a cheaper verdict.
#
# Two layers, both keyed on the pin, neither of them a bare scalar default:
#   _TIMEOUT_FLOOR_S          per-TIER floor. S081 revision 4 (D24) RAISED these
#                             to the watchdog's runaway caps: low/medium 1200s,
#                             high/xhigh 2400s, max 3600s, ultra 5400s. They are
#                             the SAME numbers as codex_watch.HARD_CAP_S and must
#                             stay that way — a caller asks this table for its
#                             timeout and hands the call to that watchdog, so a
#                             floor BELOW the cap makes the registry itself the
#                             thing that kills a healthy call at half its budget.
#                             That is the defect D24 removes; before it, these
#                             read 600/600/1200/1800 against tiers that measure
#                             ~2-2.5 min (xhigh) and 5-7 min (max).
#                             `minimal` alone keeps 120s and has NO watchdog row:
#                             no live roster model advertises the level, so no
#                             seat can reach it (RULING 3, WP-A02) — it is left
#                             tabulated rather than raised, and codex_watch
#                             RAISES on it. Both sides fail closed.
#   _MODEL_TIMEOUT_OVERRIDES_S  per-(model, tier) raise, for a model that needs
#                             MORE than its tier's floor. Empty today: no model
#                             in the reachable set does. Re-pinning a role onto
#                             a slower model adds a row HERE, in the same change
#                             as the pin — that is what "coupled" means.
#
# An UNKNOWN tier raises. The 300s figures elsewhere in the tree are already
# known to be wrong — xhigh measures ~2-2.5 min and max 5-7 min against a 300s
# ceiling, and a production served-by log records a real 300s timeout retried at
# 600s — and they got there through exactly the `.get(effort, 300)` shape this
# module refuses to have.
# --------------------------------------------------------------------------- #
_TIMEOUT_FLOOR_S: Dict[str, int] = {
    # Unreachable by any seat (RULING 3): no roster model advertises `minimal`,
    # the CLI exposes no --effort, and convene's PROVIDER_LEGAL_TIERS excludes it.
    # Left at 120 rather than raised — D24 gives it no cap.
    "minimal": 120,
    "low": 1200,
    "medium": 1200,
    # `high` is here because the ROSTER lists it as supported. Whether it is
    # *recommended* is a different question with a different owner:
    # convene.py's MEASURED_EFFORT_FINDINGS carries the benchmark note.
    # Legality here, advice there (design §11.2).
    "high": 2400,
    "xhigh": 2400,
    "max": 3600,
    "ultra": 5400,
}

_MODEL_TIMEOUT_OVERRIDES_S: Dict[Tuple[str, str], int] = {}


@dataclass(frozen=True)
class CodexPin:
    """A fully resolved codex invocation pin.

    `argv_fragment` is the ONLY sanctioned way to spell the pin on a command
    line. It always carries `-m`; there is no "inherit" shape.
    """

    model: str
    effort: str
    timeout: int
    provenance_source: str
    argv_fragment: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        if not self.argv_fragment:
            object.__setattr__(self, "argv_fragment", argv_fragment(self.model, self.effort))


def argv_fragment(model: str, effort: str) -> List[str]:
    """The pinned fragment. `-m` is ALWAYS emitted (design §4.1)."""
    return ["-m", model, "-c", f"model_reasoning_effort={effort}"]


def default_model() -> str:
    """The workhorse slug.

    An ACCESSOR, not a fourth role key. Used for design §4.2's cheap-path row
    (inner-loop / mechanical / smoke / research fan-out) and as the model a
    codex seat_class that is a RAW TIER rather than an emitter role resolves onto.
    """
    return DEFAULT_MODEL


def reachable_models() -> FrozenSet[str]:
    """Every slug this module can emit from its own tables.

    Derived, never hand-listed, so a test asserting the exact set catches ANY
    unexpected slug — not merely one the test author thought to name. Does NOT
    cover an operator's `env` override, which is by construction unbounded and
    is recorded as `provenance_source == "env"` instead.

    Nor does it cover `top_listed()`, deliberately. Auto-follow returns whatever
    the local roster ranks first, so that slug is roster data and not a table
    entry. Its visibility comes from seat_model's provenance and the served-model
    banner, not from this set.
    """
    return frozenset({DEFAULT_MODEL} | {pin.model for pin in _ROLE_PINS.values()})


@dataclass(frozen=True)
class RosterEntry:
    """One roster entry's selection-relevant metadata, parsed, never invented.

    A field the document does not carry in a usable shape is `None` (or `False`
    for `supported_in_api`). Nothing is defaulted towards eligibility.
      priority          the int as listed; `None` when absent or JSON null (any
                        other type makes the whole document invalid, #282 R4)
      visibility        the raw string (`"list"`, `"hide"`, ...) or `None`
      supported_in_api  True ONLY when the document says literally `true`
      efforts           legal efforts, the same parse `load_roster()` uses
      upgrade           the declared successor SLUG, or `None` when the field is
                        null/absent/empty OR populated but naming no slug
      upgrade_declared  True when the field is populated at all, so a populated
                        field that names no slug is reported instead of hidden
    """

    slug: str
    priority: Optional[int]
    visibility: Optional[str]
    supported_in_api: bool
    efforts: FrozenSet[str]
    upgrade: Optional[str]
    upgrade_declared: bool = False


@dataclass(frozen=True)
class RosterDocument:
    """The parsed roster: entries by slug plus the document-level provenance.

    entries_skipped  #282 fix round 1 (F13, K43): the slugs of entries dropped for a
                     FIELD-TYPE fault they could never be selected with (hidden, or not in
                     the API), sorted. Empty on a clean document — an event key, never a
                     present-and-empty one at the call sites that surface it.
    """

    path: Path
    fetched_at: Optional[str]
    client_version: Optional[str]
    entries: Dict[str, RosterEntry]
    entries_skipped: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TopSelection:
    """`select_top()`'s answer. `model` is what `top_listed()` returns.

    priority_winner          the lowest-priority eligible slug, before any upgrade; on a
                             priority tie, the entry the tie-break chose (#282 R16)
    upgrade_followed         True when `model` came from the winner's `upgrade`
    upgrade_ignored_reason   why a POPULATED upgrade was not followed (else None)
    roster_fetched_at        the document's `fetched_at` (seat_model's staleness input)
    roster_client_version    the document's `client_version`
    tie_break                the TIE_BREAKS rule that decided a priority tie, None when the
                             lowest priority held one eligible entry
    tied_with                the OTHER eligible slugs tied at that priority, sorted: neither the
                             priority winner nor `model` (#282 fix round 1 F14, so a followed
                             upgrade onto a tie member never lists the served slug). () with no
                             tie — and () is also legal WITH one, when the tie held exactly the
                             winner and the model served in its place; read `tie_break` for that
    roster_entries_skipped   the document's `entries_skipped` (#282 fix round 1 F13), carried so a
                             caller that only sees the selection still learns the roster was
                             partial; () on a clean document
    """

    model: str
    effort: str
    priority_winner: str
    upgrade_followed: bool
    upgrade_ignored_reason: Optional[str]
    roster_fetched_at: Optional[str]
    roster_client_version: Optional[str]
    tie_break: Optional[str] = None
    tied_with: Tuple[str, ...] = ()
    roster_entries_skipped: Tuple[str, ...] = ()


def _invalid_field(entry: Dict[str, Any]) -> Optional[str]:
    """#282 R4 (K14): why one roster entry makes the document invalid, else None. Pure.

    Only the fields the predicate names are checked, and only when PRESENT: an absent
    key keeps its lenient meaning, and so does a JSON-null priority.
    """
    if "supported_reasoning_levels" in entry:
        levels = entry["supported_reasoning_levels"]
        if not isinstance(levels, list):
            return f"supported_reasoning_levels is {type(levels).__name__}, not a list"
        for level in levels:
            if not isinstance(level, (dict, str)):
                return f"a supported_reasoning_levels element is {type(level).__name__}, not an object or string"
    if "priority" in entry:
        priority = entry["priority"]
        if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int)):
            return f"priority is {type(priority).__name__} {priority!r}, not an int"
    return None


def _is_selectable(entry: Dict[str, Any]) -> bool:
    """#282 fix round 1 (F13, K43): could this RAW entry ever be chosen as a TOP? Pure.

    Read LITERALLY off the unparsed dict, because the parse is exactly what a field-type fault
    makes unsafe. An entry that is not `visibility == "list"` AND `supported_in_api is True`
    cannot be eligible for any effort (see `_ineligibility`), so a bad field type on it costs
    that entry alone; the same fault on a SELECTABLE entry still invalidates the document,
    because there the parse would decide what gets served.
    """
    return entry.get("visibility") == "list" and entry.get("supported_in_api") is True


def _parse_efforts(entry: Dict[str, Any]) -> FrozenSet[str]:
    """Legal efforts. Call only on an entry `_invalid_field` accepted (a list or absent)."""
    efforts = set()
    for level in entry.get("supported_reasoning_levels") or []:
        if isinstance(level, dict):          # the live shape
            name = level.get("effort")
        else:                                # a bare string (defensive)
            name = level
        if isinstance(name, str) and name:
            efforts.add(name)
    return frozenset(efforts)


def _parse_priority(value: Any) -> Optional[int]:
    """The int priority, or None. Call only on an entry `_invalid_field` accepted."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_upgrade(value: Any) -> Tuple[Optional[str], bool]:
    """-> (successor slug or None, field populated?). Null, "" and {} are unpopulated."""
    if value is None or value == "" or value == {} or value == []:
        return None, False
    if isinstance(value, str):
        return value, True
    if isinstance(value, dict):
        for key in ("slug", "model"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate, True
    return None, True


def load_roster_entries(cache_path: Optional[Path] = None) -> RosterDocument:
    """Per-slug roster METADATA from the local codex roster. No network.

    Same file and same effort parse as `load_roster()` (which is built on this
    function). A missing file -> `CodexRosterAbsentError`; every other failure
    (unreadable, not JSON, the wrong shape or field types — THREE ROSTER STATES in
    the module docstring) -> `CodexRosterInvalidError`. Both are `CodexModelError`.
    A duplicated slug keeps the LAST USABLE entry: last-wins as `load_roster()` always
    had it, except that (#282 fix round 2, G6/K58) a later FAULTY duplicate may not
    delete a selectable entry — it invalidates the document instead — and a later GOOD
    duplicate clears any skip already recorded for that slug.

    IMPLEMENTATION FACT, verified against the live cache: each entry's
    `supported_reasoning_levels` is a list of OBJECTS keyed `effort`, NOT a list
    of bare strings. An emitter that assumes strings reads an EMPTY legal set
    for every model and then validates nothing at all while appearing to work.
    Bare strings are also accepted, defensively, in case the shape ever changes
    the other way.

    The default path is the module's `MODELS_CACHE_PATH`, read at CALL time.
    """
    path = Path(cache_path) if cache_path is not None else MODELS_CACHE_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CodexRosterAbsentError(f"codex roster absent at {path}: {exc}") from exc
    except OSError as exc:
        raise CodexRosterInvalidError(f"codex roster unreadable at {path}: {exc}") from exc
    except ValueError as exc:                     # UnicodeDecodeError: not UTF-8
        raise CodexRosterInvalidError(f"codex roster at {path} is not UTF-8: {exc}") from exc
    try:
        doc = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise CodexRosterInvalidError(f"codex roster at {path} is not valid JSON: {exc}") from exc
    models = doc.get("models") if isinstance(doc, dict) else None
    if not isinstance(models, list):
        raise CodexRosterInvalidError(f"codex roster at {path} has no `models` list")

    entries: Dict[str, RosterEntry] = {}
    skipped: set = set()
    for index, entry in enumerate(models):
        if not isinstance(entry, dict):
            raise CodexRosterInvalidError(
                f"codex roster at {path}: models[{index}] is {type(entry).__name__}, not an object")
        why = _invalid_field(entry)
        if why is not None:
            if _is_selectable(entry):
                raise CodexRosterInvalidError(f"codex roster at {path}: models[{index}] {why}")
            # #282 fix round 1 (F13, K43): a field-type fault on an entry that could never be
            # selected costs THAT ENTRY, not the document — one such entry used to take every
            # fail-closed codex seat and every convene down with it.
            faulty = entry.get("slug")
            if isinstance(faulty, str) and faulty:
                # #282 fix round 2 (G6, K58a): but last-wins must never DELETE a SELECTABLE
                # entry. Popping a good listed/API entry for a later hidden faulty duplicate
                # left the document VALID with a silently different TOP — strictly weaker than
                # the fail-closed answer F13 keeps for that same fault on that same slug. The
                # stored entry is read here, not the raw dict, because it is the parse already
                # committed to `entries` that the pop would discard.
                stored = entries.get(faulty)
                if stored is not None and stored.visibility == "list" and stored.supported_in_api:
                    raise CodexRosterInvalidError(
                        f"codex roster at {path}: models[{index}] {why} — and dropping it would "
                        f"remove the SELECTABLE entry already read for slug {faulty!r}")
                skipped.add(faulty)
                entries.pop(faulty, None)
            continue
        slug = entry.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        visibility = entry.get("visibility")
        upgrade, upgrade_declared = _parse_upgrade(entry.get("upgrade"))
        entries[slug] = RosterEntry(
            slug=slug,
            priority=_parse_priority(entry.get("priority")),
            visibility=visibility if isinstance(visibility, str) else None,
            supported_in_api=entry.get("supported_in_api") is True,
            efforts=_parse_efforts(entry),
            upgrade=upgrade,
            upgrade_declared=upgrade_declared,
        )
        # #282 fix round 2 (G6, K58b): the skip set was add-only, so a faulty entry followed
        # by a good duplicate left the slug in `entries_skipped` while it sat in `entries` —
        # a provenance key naming a model that was in fact selected. A slug that is PRESENT
        # is never also reported skipped.
        skipped.discard(slug)

    if not entries:
        # F13: skipping never empties the roster silently — an all-skipped document is as
        # invalid as an empty `models` list, and it NAMES what it dropped.
        detail = f" ({len(skipped)} skipped: {', '.join(sorted(skipped))})" if skipped else ""
        raise CodexRosterInvalidError(f"codex roster at {path} lists no usable models{detail}")
    fetched_at = doc.get("fetched_at")
    client_version = doc.get("client_version")
    return RosterDocument(
        path=path,
        fetched_at=fetched_at if isinstance(fetched_at, str) else None,
        client_version=client_version if isinstance(client_version, str) else None,
        entries=entries,
        entries_skipped=tuple(sorted(skipped)),
    )


def load_roster(cache_path: Optional[Path] = None) -> Dict[str, FrozenSet[str]]:
    """slug -> legal efforts, read from the local codex roster. No network.

    Unchanged contract. Built on `load_roster_entries()` so there is one parser.
    """
    doc = load_roster_entries(cache_path)
    return {slug: entry.efforts for slug, entry in doc.entries.items()}


def _ineligibility(entry: RosterEntry, effort: str) -> Optional[str]:
    """Why `entry` cannot serve `effort` as a TOP, or None when it can."""
    if entry.visibility != "list":
        return f"{entry.slug!r} has visibility {entry.visibility!r}, not 'list'"
    if not entry.supported_in_api:
        return f"{entry.slug!r} is not supported_in_api"
    if effort not in entry.efforts:
        return f"{entry.slug!r} does not support effort {effort!r} (roster: {sorted(entry.efforts)})"
    return None


def _generation(slug: Any) -> Optional[Tuple[int, int]]:
    """#282 R16 (K28): (major, minor) from a `gpt-<major>[.<minor>]` slug prefix, else None. Pure.

    The minor is 0 when absent, and both parts compare as integers, so gpt-6-astra (6, 0) >
    gpt-5.6-sol (5, 6) > gpt-5.5 (5, 5) and 5.10 > 5.9. None ranks below every parseable
    generation.

    #282 fix round 1 (F12): each digit group is bounded at 9 digits, so a longer run is
    UNPARSEABLE (None) rather than an `int()` that raises out of the tie-break past every
    fail-open boundary. Nine digits is far past any real generation and keeps the rule total.
    """
    match = _GENERATION.match(slug) if isinstance(slug, str) else None
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2) or 0)


def _break_tie(tied: List[RosterEntry], incumbent: Optional[str]) -> Tuple[RosterEntry, Optional[str]]:
    """-> (winner, the TIE_BREAKS rule that decided, or None when there was no tie). Pure.

    `tied` is every eligible entry at the lowest priority, sorted by slug.
    """
    if len(tied) == 1:
        return tied[0], None
    generations = {entry.slug: _generation(entry.slug) for entry in tied}
    parsed = [generation for generation in generations.values() if generation is not None]
    leaders = tied
    if parsed:
        newest = max(parsed)
        leaders = [entry for entry in tied if generations[entry.slug] == newest]
    if len(leaders) == 1:
        return leaders[0], "generation"
    for entry in leaders:
        if isinstance(incumbent, str) and entry.slug == incumbent:
            return entry, "incumbent"
    return leaders[0], "slug"


def select_top(effort: str, *, cache_path: Optional[Path] = None,
               incumbent: Optional[str] = None) -> TopSelection:
    """Select the codex TOP for `effort` from the local roster (design §4.3). No network.

    Mechanical rules, no judgment:
      1. ELIGIBLE = visibility == "list" AND supported_in_api is True AND `effort`
         is in the entry's supported efforts. An entry with no finite numeric
         `priority` cannot be ranked and is not eligible.
      2. The PRIORITY WINNER is the eligible entry with the LOWEST priority.
         `priority` is the vendor's picker order, NOT a capability ranking, and it
         FLAPS: gpt-5.6-sol was observed at 4 (2026-09-15T14:38:49Z), 1 (20:45:50Z,
         tied with gpt-6-astra), 4 (22:25:15Z) and 1 again (22:38:08Z), and the first
         tie let a slug order serve sol on every TOP seat (#282 R16). So a TIE among
         eligible entries at that priority breaks by (a) the higher model generation
         parsed from the slug, then (b) the `incumbent` — the caller's last recorded
         TOP — when it is still among the entries (a) left, then (c) slug, ascending,
         so the answer never depends on file order. `tie_break` names the rule that
         decided and `tied_with` the OTHER tied slugs — excluding the served model as
         well as the winner, so rule 3's upgrade can empty it (None / () without a
         tie; an ineligible entry at the same priority is not a tie). See PRIORITY
         TIES in the module docstring.
      3. If the winner's `upgrade` field is populated (a slug string, or an
         object carrying `slug` / `model`), follow it ONLY when the target is
         itself eligible under rule 1 for this effort. Vendor supersession
         outranks priority order, but it never jumps to a hidden, non-API or
         effort-incapable model. Otherwise keep the winner and record
         `upgrade_ignored_reason`.
         ONE HOP: the target's own `upgrade` is not chased, so selection is
         bounded and a cyclic upgrade chain cannot loop. The target's own
         priority is irrelevant once the winner names it.
      4. No eligible entry -> `CodexModelError`. There is no fail-open branch
         here; the harness literal is seat_model's decision, per call site.
    The loader's CodexRosterAbsentError / CodexRosterInvalidError propagate unchanged.
    """
    doc = load_roster_entries(cache_path)

    ranked = sorted(
        (
            entry
            for entry in doc.entries.values()
            if entry.priority is not None and _ineligibility(entry, effort) is None
        ),
        key=lambda entry: (entry.priority, entry.slug),
    )
    if not ranked:
        reasons = "; ".join(
            _ineligibility(entry, effort) or f"{entry.slug!r} has no numeric priority"
            for entry in doc.entries.values()
        )
        raise CodexModelError(
            f"no eligible codex TOP for effort {effort!r} in {doc.path}: {reasons}"
        )

    tied = [entry for entry in ranked if entry.priority == ranked[0].priority]
    winner, tie_break = _break_tie(tied, incumbent)
    model, followed, ignored = winner.slug, False, None
    if winner.upgrade_declared:
        target = winner.upgrade
        if target is None:
            ignored = f"upgrade field on {winner.slug!r} is populated but names no slug"
        elif target == winner.slug:
            ignored = f"upgrade field on {winner.slug!r} points at itself"
        elif target not in doc.entries:
            ignored = f"upgrade target {target!r} (from {winner.slug!r}) is not in the roster"
        else:
            why = _ineligibility(doc.entries[target], effort)
            if why is None:
                model, followed = target, True
            else:
                ignored = f"upgrade target from {winner.slug!r} ignored: {why}"

    # #282 fix round 1 (F14): the OTHER tied slugs — so the SERVED model is excluded as well
    # as the priority winner. A followed upgrade naming a member of the same tie would
    # otherwise leave the served slug in `tied_with` and the digest would read `X = X -> X`.
    # The tuple may now be empty while a tie happened; `tie_break` is what says one did.
    tied_with = tuple(entry.slug for entry in tied if entry.slug not in (winner.slug, model))

    return TopSelection(
        model=model,
        effort=effort,
        priority_winner=winner.slug,
        upgrade_followed=followed,
        upgrade_ignored_reason=ignored,
        roster_fetched_at=doc.fetched_at,
        roster_client_version=doc.client_version,
        tie_break=tie_break,
        tied_with=tied_with,
        roster_entries_skipped=doc.entries_skipped,
    )


def top_listed(effort: str, *, cache_path: Optional[Path] = None) -> str:
    """The codex TOP slug for `effort`: `select_top(effort).model`.

    Callers that must record WHY (an ignored upgrade, the roster's fetched_at, a
    priority tie-break) use `select_top()`; this form passes no incumbent, so a tie
    that generation leaves open falls to slug. Raises `CodexModelError` when nothing
    is eligible.
    """
    return select_top(effort, cache_path=cache_path).model


def timeout_for(model: str, effort: str) -> int:
    """Strict pin lookup: per-model override, else the tier floor. RAISES on a miss.

    There is no bare scalar default. A `.get(effort, 300)` is how an un-tabulated
    tier silently inherits a ceiling that is already too low for the tiers it IS
    tabulated for — the defect this module was written to stop repeating.
    """
    override = _MODEL_TIMEOUT_OVERRIDES_S.get((model, effort))
    if override is not None:
        return override
    try:
        return _TIMEOUT_FLOOR_S[effort]
    except KeyError:
        raise CodexModelError(
            f"no timeout recorded for ({model!r}, {effort!r}); model tier and "
            f"timeout are a coupled pair — add the row rather than defaulting"
        ) from None


def resolve(
    role: str,
    *,
    env_var: Optional[str] = None,
    fail_open: bool = False,
    cache_path: Optional[Path] = None,
) -> CodexPin:
    """Resolve one of the THREE role keys to a fully pinned invocation.

    `env_var=None` skips the env layer entirely; naming a variable that is unset
    or empty skips it too. An unknown `role` ALWAYS raises, even under
    `fail_open` — a typo has no literal to fall back to, and returning the
    workhorse for it would hide the bug behind a plausible call.
    """
    pin = _ROLE_PINS.get(role)
    if pin is None:
        raise CodexModelError(
            f"unknown codex role {role!r}; the key space is exactly {sorted(ROLES)}. "
            f"A raw effort tier goes through resolve_seat_class()."
        )
    return _resolve_pin(pin, env_var=env_var, fail_open=fail_open, cache_path=cache_path)


def resolve_seat_class(
    seat_class: str,
    *,
    env_var: Optional[str] = None,
    fail_open: bool = False,
    cache_path: Optional[Path] = None,
) -> CodexPin:
    """Resolve a convene seat_class, which may be a role key OR a RAW TIER.

    convene reaches its guard stack with raw tiers as the seat_class token (a
    non-ratification codex arbiter arrives as `"xhigh"`; an explicitly pinned
    token passes straight through). Those are NOT emitter roles and must not be
    given role keys; they take the DEFAULT model with their own raw tier.
    """
    if seat_class in _ROLE_PINS:
        return resolve(
            seat_class, env_var=env_var, fail_open=fail_open, cache_path=cache_path
        )
    return _resolve_pin(
        _Pin(DEFAULT_MODEL, seat_class),
        env_var=env_var,
        fail_open=fail_open,
        cache_path=cache_path,
    )


def _resolve_pin(
    pin: _Pin,
    *,
    env_var: Optional[str],
    fail_open: bool,
    cache_path: Optional[Path],
) -> CodexPin:
    env_model = ""
    if env_var is not None:
        env_model = (os.environ.get(env_var) or "").strip()

    try:
        roster = load_roster(cache_path)
        model, source = pin.model, "data"
        if env_model:
            if env_model not in roster:
                raise CodexModelError(
                    f"{env_var}={env_model!r} is not in the local codex roster "
                    f"({sorted(roster)}); refusing to pin a slug the CLI does not list"
                )
            model, source = env_model, "env"
        if model not in roster:
            raise CodexModelError(
                f"pinned model {model!r} is not in the local codex roster ({sorted(roster)})"
            )
        legal = roster[model]
        if pin.effort not in legal:
            raise CodexModelError(
                f"effort {pin.effort!r} is not supported by {model!r} "
                f"(roster says: {sorted(legal)})"
            )
        timeout = timeout_for(model, pin.effort)
    except CodexModelError:
        if not fail_open:
            raise
        # Fail-open floor: THIS role's own literal, unvalidated. Argv shape AND
        # model identity are both preserved; the provenance string is what makes
        # the breakage visible downstream. `timeout_for` is deliberately NOT
        # caught here — a literal missing from the timeout table is a harness
        # self-inconsistency, not an environment failure, and a test guards it.
        return CodexPin(
            model=pin.model,
            effort=pin.effort,
            timeout=timeout_for(pin.model, pin.effort),
            provenance_source="harness_literal",
            argv_fragment=argv_fragment(pin.model, pin.effort),
        )

    return CodexPin(
        model=model,
        effort=pin.effort,
        timeout=timeout,
        provenance_source=source,
        argv_fragment=argv_fragment(model, pin.effort),
    )
