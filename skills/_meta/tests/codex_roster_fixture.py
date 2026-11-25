"""codex_roster_fixture.py - ONE shared SYNTHETIC codex roster for the harness tests (#302 WP-1).

Design #302 section 4 (challenger #5). The seat_model, convene, seat_model_check, model_roster and
freshness_nudge suites each used to hand-write their own copy of the live codex roster, with the
std model spelled out as a literal. When the codex tiers move, every copy had to move with them.
This module is the single place that knows how a synthetic `~/.codex/models_cache.json` is
shaped and which roster tiers it must list.

WHAT IT WRITES. A roster in the LIVE shape observed on 2026-09-14 (entries carry
`supported_reasoning_levels` as objects keyed `effort`, `fetched_at` has nanosecond precision):
a fixed base of listed and hidden slugs, plus whatever the roster tiers name TODAY:

  * `codex_std()`     -> model_roster.CODEX_STD
  * `codex_support()` -> model_roster.CODEX_SUPPORT when the roster defines it, else CODEX_STD
                         (the support tier did not exist before roster rev 3, and a HISTORY row
                         without `codex_support` reads as its `codex_std`)

A tier model already in the base keeps its base priority; one that is not is added, listed and
API-supported, offering low..max plus ultra. The tiers are read at CALL time, never at import, so
a monkeypatched model_roster is honoured.

NEVER the live roster: every writer takes the target HOME explicitly and nothing here reads
`~/.codex/models_cache.json`. No model is called.

Import: the file sits in skills/_meta/tests; a suite outside that directory puts the directory on
sys.path and imports `codex_roster_fixture` (see skills/avengers/tests/test_convene.py).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import model_roster  # type: ignore  # noqa: E402

#: Every effort a current codex model offers (the live shape, 2026-09-14).
ALL_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
#: The client version the live roster carried when these shapes were captured.
CLIENT_VERSION = "0.154.0"
#: The TOP model every base roster lists first.
TOP = "gpt-6-astra"

#: Where a tier model the base does not already list is placed. 2 is gpt-6-sol's live priority
#: (2026-09-24 roster); 7 is gpt-5.6-terra's.
STD_PRIORITY = 2
SUPPORT_PRIORITY = 7

#: The live roster of 2026-09-14, reduced to the selection-relevant fields:
#: (slug, priority, visibility, efforts). DATED DATA: these slugs are synthetic served ids in the
#: live shape, not claims about which tier serves which model.
_BASE = (
    ("gpt-6-astra", 1, "list", ALL_EFFORTS),
    ("gpt-reserve", 3, "hide", ("low", "medium", "high", "xhigh", "max")),
    ("gpt-5.6-sol", 4, "list", ALL_EFFORTS),
    ("gpt-5.6-terra", 7, "list", ALL_EFFORTS),
    ("gpt-5.6-luna", 8, "list", ("low", "medium", "high", "xhigh", "max")),
    ("gpt-5.5", 12, "list", ("low", "medium", "high", "xhigh")),
    ("codex-auto-review", 43, "hide", ("low", "medium", "high", "xhigh", "max")),
)
BASE_SLUGS = tuple(row[0] for row in _BASE)


def codex_std() -> str:
    """The codex std tier as the roster names it NOW (light/medium main seats)."""
    return model_roster.CODEX_STD


def codex_support() -> str:
    """The codex support tier (consultant_support): CODEX_SUPPORT, or CODEX_STD before rev 3."""
    return getattr(model_roster, "CODEX_SUPPORT", model_roster.CODEX_STD)


def entry(slug, priority, *, visibility="list", api=True, efforts=ALL_EFFORTS, upgrade=None) -> dict:
    """One roster entry in the live shape."""
    return {
        "slug": slug,
        "priority": priority,
        "visibility": visibility,
        "supported_in_api": api,
        "supported_reasoning_levels": [{"effort": e, "description": e} for e in efforts],
        "upgrade": upgrade,
    }


def codex_entries(*, slugs=None, drop=(), priorities=None, efforts=None, extra=(),
                  std_priority=STD_PRIORITY, support_priority=SUPPORT_PRIORITY) -> list:
    """The synthetic roster's entries, tier models always included.

    slugs       keep only these base slugs (the tier models are added regardless); None = all
    drop        base slugs to leave out (applied after `slugs`; never removes a tier model)
    priorities  {slug: priority} overrides, for tie and inversion fixtures (tier models included)
    efforts     {slug: efforts} overrides
    extra       further entries (e.g. an unknown listed slug) appended as given
    std_priority / support_priority
                where an unlisted tier model is placed
    """
    priorities = dict(priorities or {})
    efforts = dict(efforts or {})
    std, support = codex_std(), codex_support()
    keep = set(BASE_SLUGS if slugs is None else slugs) - set(drop)
    out = []
    for slug, priority, visibility, levels in _BASE:
        if slug in keep or slug in (std, support):
            out.append(entry(slug, priorities.get(slug, priority), visibility=visibility,
                             efforts=efforts.get(slug, levels)))
    present = {e["slug"] for e in out}
    for tier, default in ((std, std_priority), (support, support_priority)):
        if tier not in present:
            out.append(entry(tier, priorities.get(tier, default), efforts=efforts.get(tier, ALL_EFFORTS)))
            present.add(tier)
    out.sort(key=lambda e: (e["priority"] is None, e["priority"] if e["priority"] is not None else 0))
    out.extend(extra)
    return out


def with_tiers(entries, *, std_priority=STD_PRIORITY, support_priority=SUPPORT_PRIORITY) -> list:
    """`entries` (a hand-written or DATED roster, kept as written) plus any roster tier model it
    does not list, appended in file order. For fixtures whose own slugs are the point of the test
    (a dated tie roster, a ceiling fixture) but whose support/std seat must still resolve."""
    out = list(entries)
    present = {e.get("slug") for e in out if isinstance(e, dict)}
    for tier, priority in ((codex_std(), std_priority), (codex_support(), support_priority)):
        if tier not in present:
            out.append(entry(tier, priority))
            present.add(tier)
    return out


def slug_index(entries, slug) -> int:
    """The position of `slug` in `entries` (fixtures address entries by slug, never by position:
    the tier models an unlisted roster tier adds shift positions)."""
    return next(i for i, e in enumerate(entries) if e.get("slug") == slug)


def iso_nanos(epoch: float) -> str:
    """The live codex `fetched_at` shape: nine fractional digits."""
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".887906859Z"


def roster_doc(entries=None, *, fetched_at: str, client_version: str = CLIENT_VERSION, **entry_opts) -> dict:
    """A whole models_cache.json document. `entries` None -> codex_entries(**entry_opts)."""
    return {
        "fetched_at": fetched_at,
        "client_version": client_version,
        "models": codex_entries(**entry_opts) if entries is None else entries,
    }


def write_codex_roster(home, entries=None, *, fetched_at: str, client_version: str = CLIENT_VERSION,
                       **entry_opts) -> Path:
    """Write `<home>/.codex/models_cache.json` (the directory must exist) and return its path."""
    path = Path(home) / ".codex" / "models_cache.json"
    doc = roster_doc(entries, fetched_at=fetched_at, client_version=client_version, **entry_opts)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path
