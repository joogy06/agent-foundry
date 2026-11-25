"""Codex review fix C3: a must-resolve defect's remedy still gets goal-fit, and the defect still gets resolved."""
from pathlib import Path

REFS = Path(__file__).resolve().parent.parent / "references"


def _read(name):
    return (REFS / name).read_text(encoding="utf-8")


def test_step_1a_separates_the_defect_from_its_remedy():
    text = _read("10-close-out.md")
    assert "This list governs leaving the defect unresolved, not recognising a harmful remedy" in text
    assert "The defect must still be resolved" in text
    assert "Never ruled `works-against`" not in text


def test_no_reference_keeps_the_old_list_name():
    for name in ("10-close-out.md", "external-finding-verification.md", "08-spec-review.md"):
        assert "never-ruled" not in _read(name), name


def test_both_worked_examples_state_it():
    text = _read("external-finding-verification.md")
    assert "correcting them to the true hours does not, so correcting them is the fix" in text
    assert "repair the markup so the gate passes and the accurate hours stay" in text
    assert "**If it were on the must-resolve list:**" in text
