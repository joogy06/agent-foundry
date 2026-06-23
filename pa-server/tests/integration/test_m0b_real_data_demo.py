"""WP-6 real-data briefing DEMO — verified end-to-end on a realistic workspace.

This is the executable proof for WP-6 acceptance criterion (b):

    "A real-data briefing demo composes pa_brief over a seeded fixture DB and
     asserts the 5-above-the-fold + mandatory [+N more] fold on realistic data."

It drives the runnable demo at ``pa-server/demo/m0b_briefing_demo.py`` (the SAME
module a human runs with ``python3 demo/m0b_briefing_demo.py``), composing the
briefing through the REAL routine-engine (pa_core.pa_brief) over a realistically
seeded pa.db, and asserts every M0b routine-engine behavior the WP must prove:

  * the 5-above-the-fold cap + the MANDATORY [+N more] fold affordance;
  * the urgency taxonomy ordering (CONFLICT first … FYI last);
  * the role-lens reweight (Scrum -> 'velocity' framing; membership invariant);
  * the in-composer nudge drain (a due, escalated ingested nudge surfaces);
  * remote-field delimiter-wrapping end-to-end (conflict_detail + ingested nudge
    message stay wrapped; the local blocker note does NOT).

The demo carries no business logic — it seeds + calls production code — so this
test verifies the PRODUCTION pipeline on realistic data, not a test double.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import sys
from pathlib import Path

import pytest

from tests.conftest import _load_pa_server  # noqa: F401

# Put pa-server/demo/ on the path so we can import the demo module by name.
_PA_SERVER_ROOT = Path(__file__).resolve().parent.parent.parent
_DEMO_DIR = _PA_SERVER_ROOT / "demo"
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

NOW = "2026-06-15T12:00:00"


@pytest.fixture(scope="session")
def pa_core_module(pa_server_module):
    import pa_core  # noqa: PLC0415

    return pa_core


@pytest.fixture
def demo_module(pa_server_module):
    """Import the demo module (depends on pa_server being loadable)."""
    import m0b_briefing_demo  # noqa: PLC0415

    return m0b_briefing_demo


@pytest.fixture
def brief(demo_module, tmp_path):
    """Compose the demo briefing over a freshly-seeded realistic workspace."""
    ws = tmp_path / "acme-platform"
    return demo_module.run_demo(now=NOW, workspace_path=ws)


class TestRealDataFold:
    def test_five_above_the_fold_with_mandatory_overflow(self, brief):
        """Criterion (b): exactly 5 above the fold; the realistic seed produces
        MORE than 5 concerns, so a MANDATORY [+N more] affordance is present."""
        assert len(brief["above_fold"]) == 5, "exactly 5 above the fold"
        assert brief["overflow_count"] >= 1, "realistic data overflows the fold"
        assert brief["overflow_affordance"] == f"[+{brief['overflow_count']} more]"
        assert brief["overflow_affordance"] in brief["rendered_text"]

    def test_fold_drops_nothing(self, brief):
        """T-RE-1: above_fold + overflow is a partition of items (no item lost)."""
        rejoined = {i["id"] for i in brief["above_fold"]} | {i["id"] for i in brief["overflow"]}
        assert rejoined == {i["id"] for i in brief["items"]}

    def test_rendered_text_is_about_twelve_lines(self, brief):
        """The rendered terminal briefing is compact (header + <=5 lines + the
        affordance) — the ~12-line briefing the design calls for."""
        lines = brief["rendered_text"].splitlines()
        assert lines[0].startswith("AMY briefing")
        # header(1) + above_fold(5) + affordance(1) == 7 here; cap the upper bound.
        assert 2 <= len(lines) <= 13


class TestRealDataUrgencyOrdering:
    def test_taxonomy_order_holds_on_realistic_data(self, brief):
        """The urgency taxonomy ordering survives end-to-end on realistic data."""
        rank = {
            "CONFLICT": 0, "OVERDUE_NUDGE": 1, "BLOCKER": 2, "DUE_TODAY": 3,
            "DELEGATION_FOLLOWUP": 4, "IN_FLIGHT": 5, "FYI": 6,
        }
        ranks = [rank[it["urgency"]] for it in brief["items"]]
        assert ranks == sorted(ranks), f"urgency taxonomy order violated: {ranks}"
        assert brief["items"][0]["urgency"] == "CONFLICT", "loudest concern leads"
        assert brief["above_fold"][0]["urgency"] == "CONFLICT"

    def test_critical_blocker_is_above_the_fold(self, brief):
        """A critical blocker is never demoted to invisibility — it is above the
        fold on this realistic seed (urgency dominates the role-lens weight)."""
        above_kinds = [it["source_kind"] for it in brief["above_fold"]]
        assert "blocker" in above_kinds, "critical blocker must stay visible"


class TestRealDataRoleLens:
    def test_scrum_methodology_yields_velocity_framing(self, brief):
        """The role-lens reads the workspace role_profile (Scrum) -> 'velocity'
        week-review framing — the in_process reweight seam on real data."""
        assert brief["week_review_framing"] == "velocity"


class TestRealDataNudgeDrain:
    def test_escalated_ingested_nudge_surfaces_as_overdue(self, brief):
        """The in-composer drain promotes the due, thrice-snoozed ingested nudge
        and surfaces it louder as OVERDUE_NUDGE on realistic data."""
        nudges = [it for it in brief["items"] if it["source_kind"] == "nudge"]
        assert nudges, "the due ingested nudge must be drained + surfaced"
        assert nudges[0]["urgency"] == "OVERDUE_NUDGE"


class TestRealDataRemoteWrapping:
    def test_remote_fields_wrapped_local_note_not(self, brief, pa_core_module):
        """Security floor L1 on real data: the remote conflict_detail and the
        ingested nudge message stay delimiter-wrapped end-to-end; the user's own
        blocker note is NOT wrapped."""
        OPEN, CLOSE = pa_core_module.UNTRUSTED_OPEN, pa_core_module.UNTRUSTED_CLOSE

        conflict = next(it for it in brief["items"] if it["source_kind"] == "conflict")
        assert conflict["detail"].startswith(OPEN) and conflict["detail"].endswith(CLOSE)

        nudge = next(it for it in brief["items"] if it["source_kind"] == "nudge")
        assert nudge["detail"].startswith(OPEN) and nudge["detail"].endswith(CLOSE)

        blocker = next(it for it in brief["items"] if it["source_kind"] == "blocker")
        assert OPEN not in (blocker["title"] or ""), "local blocker note must NOT be wrapped"


class TestDemoIsRunnable:
    def test_demo_main_runs_clean(self, demo_module, tmp_path, capsys):
        """The demo's CLI entry point runs end-to-end and prints the rendered
        briefing — so the documented `python3 demo/m0b_briefing_demo.py` works."""
        rc = demo_module.main(["--now", NOW, "--workspace", str(tmp_path / "ws")])
        assert rc == 0
        captured = capsys.readouterr().out
        assert "AMY briefing" in captured
        assert "more]" in captured, "the [+N more] fold affordance must print"
        assert "velocity" in captured, "the role-lens framing must print"
