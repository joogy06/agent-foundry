"""M0b unit tests for the role-lens REWEIGHT ordering (WP-4).

Covers the contract-map ``role-lens`` ordering behavior:

  * Reweighting changes ORDER only — the urgency taxonomy is the PRIMARY key
    (CONFLICT > OVERDUE_NUDGE > BLOCKER > DUE_TODAY > DELEGATION_FOLLOWUP >
    IN_FLIGHT > FYI); within an equal urgency rank the role_profile
    category_weight is the reweight signal (higher weight sorts earlier).
  * methodology selects the week-review framing (Scrum velocity vs Kanban
    cycle-time) as an ORDERING signal only — never executed/interpreted.
  * The function is total over opaque BriefItems with missing/None fields.

``reweight_brief_items`` is a PURE function (only brief_items + role_profile;
no conn, no DB). Tests load pa_core directly via the shared conftest idiom and
drive the opaque scaffolded fixtures.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json
from pathlib import Path

import pytest

from tests.conftest import _load_pa_server  # noqa: F401 — triggers pa_core import path


FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "role-lens"


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415 — importable after pa_server load

    return pa_core


def _load(rel):
    return json.loads((FIXTURES / rel).read_text())


def _ids(items):
    return [it["id"] for it in items]


def _urg(items):
    return [it["urgency"] for it in items]


class TestUrgencyIsPrimaryKey:
    def test_taxonomy_order_drives_primary_sort(self, pa_core_module):
        """Whatever the role profile, the urgency taxonomy is the PRIMARY sort
        key — a CONFLICT always precedes a BLOCKER precedes ... a FYI."""
        bi = _load("brief_items/happy/0.json")["brief_items"]
        rp = _load("role_profile/happy/0.json")["role_profile"]
        out = pa_core_module.reweight_brief_items(bi, rp)
        ranks = [pa_core_module.URGENCY_RANK.get(u, pa_core_module.URGENCY_RANK_DEFAULT)
                 for u in _urg(out)]
        assert ranks == sorted(ranks), f"urgency not monotonic: {_urg(out)}"

    def test_full_taxonomy_ordering(self, pa_core_module):
        """The canonical taxonomy CONFLICT>OVERDUE_NUDGE>BLOCKER>DUE_TODAY>
        DELEGATION_FOLLOWUP>IN_FLIGHT>FYI is reflected in URGENCY_RANK."""
        order = ["CONFLICT", "OVERDUE_NUDGE", "BLOCKER", "DUE_TODAY",
                 "DELEGATION_FOLLOWUP", "IN_FLIGHT", "FYI"]
        ranks = [pa_core_module.URGENCY_RANK[u] for u in order]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == len(order), "ranks must be distinct"


class TestCategoryWeightBreaksTies:
    def test_higher_category_weight_sorts_earlier_within_same_urgency(self, pa_core_module):
        """Two items with the SAME urgency are ordered by role category_weight:
        the up-weighted category comes first."""
        items = [
            {"id": "lo", "urgency": "DUE_TODAY", "critical": False, "category": "fyi"},
            {"id": "hi", "urgency": "DUE_TODAY", "critical": False, "category": "engineering"},
        ]
        rp = {"category_weights": {"engineering": 5.0, "fyi": 0.5}}
        out = pa_core_module.reweight_brief_items(items, rp)
        assert _ids(out) == ["hi", "lo"]

    def test_down_weight_reorders_within_urgency(self, pa_core_module):
        """People-leaning profile pulls people-category items ahead of
        engineering ones at equal urgency."""
        items = [
            {"id": "eng", "urgency": "IN_FLIGHT", "critical": False, "category": "engineering"},
            {"id": "ppl", "urgency": "IN_FLIGHT", "critical": False, "category": "people"},
        ]
        rp = _load("role_profile/happy/1.json")["role_profile"]  # people up-weighted
        out = pa_core_module.reweight_brief_items(items, rp)
        assert _ids(out) == ["ppl", "eng"]

    def test_category_weight_never_crosses_urgency_boundary(self, pa_core_module):
        """A massively up-weighted category CANNOT pull a low-urgency item above
        a high-urgency item — urgency dominates category weight."""
        items = [
            {"id": "blocker", "urgency": "BLOCKER", "critical": True, "category": "fyi"},
            {"id": "fyi", "urgency": "FYI", "critical": False, "category": "engineering"},
        ]
        rp = {"category_weights": {"engineering": 1000.0, "fyi": 0.001}}
        out = pa_core_module.reweight_brief_items(items, rp)
        assert _ids(out) == ["blocker", "fyi"], "urgency must dominate category weight"


class TestTiebreaks:
    def test_due_then_age_then_order_index_stable(self, pa_core_module):
        """Equal urgency AND equal category weight -> due_at asc, then
        age_seconds desc, then order_index asc as the final STABLE tiebreak."""
        items = [
            {"id": "later",  "urgency": "DUE_TODAY", "category": "x", "due_at": "2026-06-15T20:00:00Z", "age_seconds": 100, "order_index": 1},
            {"id": "sooner", "urgency": "DUE_TODAY", "category": "x", "due_at": "2026-06-15T10:00:00Z", "age_seconds": 100, "order_index": 0},
        ]
        rp = {"category_weights": {"x": 1.0}}
        out = pa_core_module.reweight_brief_items(items, rp)
        assert _ids(out) == ["sooner", "later"]

    def test_missing_due_sorts_after_present_due(self, pa_core_module):
        """An item with no due_at sorts AFTER one with a due_at at equal
        urgency/weight (a dated item is more actionable)."""
        items = [
            {"id": "nodue", "urgency": "DUE_TODAY", "category": "x", "due_at": None, "age_seconds": 0, "order_index": 0},
            {"id": "dued",  "urgency": "DUE_TODAY", "category": "x", "due_at": "2026-06-15T10:00:00Z", "age_seconds": 0, "order_index": 1},
        ]
        rp = {"category_weights": {"x": 1.0}}
        out = pa_core_module.reweight_brief_items(items, rp)
        assert _ids(out) == ["dued", "nodue"]


class TestMethodologyFraming:
    @pytest.mark.parametrize("methodology,expected", [
        ("Scrum", "velocity"),
        ("scrum", "velocity"),
        ("Kanban", "cycle-time"),
        ("kanban", "cycle-time"),
        ("", "unknown"),
        (None, "unknown"),
        ("Waterfall", "unknown"),
        ("Scrum; DROP TABLE role_profile; --", "velocity"),  # injection-ish: matched as a token, never executed
        (12345, "unknown"),
    ])
    def test_week_review_framing_mapping(self, pa_core_module, methodology, expected):
        """methodology maps to a week-review framing bucket as an ordering signal
        ONLY; unrecognized/garbage -> 'unknown'; never executed."""
        assert pa_core_module.week_review_framing(methodology) == expected


class TestNeutralAndEmptyProfile:
    def test_no_category_weights_is_identity_on_category(self, pa_core_module):
        """A profile with no category_weights reorders by urgency + tiebreak
        only (category weight is uniform 1.0) — a no-op on the category axis."""
        bi = _load("brief_items/happy/2.json")["brief_items"]
        rp = _load("role_profile/happy/2.json")["role_profile"]  # no weights
        out = pa_core_module.reweight_brief_items(bi, rp)
        assert set(_ids(out)) == set(_ids(bi))
        # urgency monotonic still holds
        ranks = [pa_core_module.URGENCY_RANK.get(u, pa_core_module.URGENCY_RANK_DEFAULT)
                 for u in _urg(out)]
        assert ranks == sorted(ranks)

    def test_none_profile_does_not_crash(self, pa_core_module):
        bi = _load("brief_items/happy/0.json")["brief_items"]
        out = pa_core_module.reweight_brief_items(bi, None)
        assert set(_ids(out)) == set(_ids(bi))

    def test_empty_list_returns_empty(self, pa_core_module):
        assert pa_core_module.reweight_brief_items([], {"category_weights": {"x": 1.0}}) == []


class TestAdversarialOrdering:
    def test_malformed_weights_coerced_not_crash(self, pa_core_module):
        bi = _load("brief_items/adversarial/0.json")["brief_items"]
        rp = _load("role_profile/adversarial/1.json")["role_profile"]  # string/neg/None weights
        out = pa_core_module.reweight_brief_items(bi, rp)
        assert set(_ids(out)) == set(_ids(bi))

    def test_unknown_urgency_sorts_last_block(self, pa_core_module):
        bi = _load("brief_items/adversarial/1.json")["brief_items"]
        out = pa_core_module.reweight_brief_items(bi, {"category_weights": {}})
        # the UNKNOWN_CLASS item must still be present and not crash the sort
        assert "x-4" in _ids(out)
        # BLOCKER (x-3) must precede the UNKNOWN_CLASS item (x-4)
        assert _ids(out).index("x-3") < _ids(out).index("x-4")
