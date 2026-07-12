"""Behavior tests for the WP-4 forge `came_from_avengers` intake block.

forge SKILL.md Step 3 gains a `came_from_avengers: true` + `avengers_brief_path`
intake block (mirroring `came_from_founder`), a Step 6 recursion-guard note (a
forge-convened avengers cannot emit a brief back into forge), and verbatim dissent
surfacing at Step 7 presentation. The complete per-field mapping is pinned in the
design section 10; these tests lock it against drift (design section 13 risk 5).
"""

import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DOC = HERE.parent / "SKILL.md"
FIXTURES = HERE / "fixtures"


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def _mapping() -> dict:
    return json.loads((FIXTURES / "avengers_intake_mapping.json").read_text(encoding="utf-8"))


def test_doc_exists():
    assert DOC.is_file(), f"missing forge SKILL.md: {DOC}"


def test_required_markers_present():
    doc = _doc_text()
    for name, needle in _mapping()["required_markers"].items():
        assert needle in doc, f"required marker '{name}' missing: expected substring '{needle}'"


def test_intake_block_mirrors_came_from_founder():
    """The avengers intake block must sit alongside the founder handoff (same pattern)."""
    doc = _doc_text()
    assert "came_from_founder" in doc, "founder handoff pattern (the template) is missing"
    i_founder = doc.index("came_from_founder")
    i_avengers = doc.index("came_from_avengers: true")
    # The avengers block follows the founder block (mirrored, not replacing it).
    assert i_avengers > i_founder, "came_from_avengers block should follow the came_from_founder block"


@pytest.mark.parametrize(
    "field",
    ["problem", "constraints", "success_criteria", "ruled_out_approaches",
     "recommended_direction", "dissent", "confidence", "deliberation_record"],
)
def test_per_field_intake_mapping(field):
    doc = _doc_text()
    for needle in _mapping()["intake_field_mapping"][field]:
        assert needle in doc, (
            f"intake field '{field}' mapping drifted: '{needle}' not found "
            f"(must match design section 10 pinned mapping)"
        )


def test_always_false_fields_documented():
    doc = _doc_text()
    for field in _mapping()["always_false_fields"]:
        assert f"{field}" in doc, f"always-false field '{field}' not documented"
    assert "mechanically always-false" in doc, \
        "contract_map_signed / bob_ready must be stated mechanically always-false"


def test_recursion_guard_in_step6():
    """A forge-convened avengers session must not emit a brief back into forge."""
    doc = _doc_text()
    assert "Recursion guard (avengers ↔ forge)" in doc, "Step 6 recursion-guard note missing"
    # The guard must land in the Step 6 (design exploration) region, after the guard header.
    guard_idx = doc.index("Recursion guard (avengers ↔ forge)")
    step6_idx = doc.index("Step 6B: Design exploration team")
    guard_text = doc[guard_idx: guard_idx + 800]
    assert guard_idx > step6_idx, "recursion guard must live in the Step 6 design-exploration section"
    assert "never a `forge_brief`" in guard_text or "never a forge_brief" in guard_text, \
        "recursion guard must state a forge-convened avengers returns decision, never a forge_brief"
    assert "forge_session_id" in guard_text, "recursion guard must key on forge_session_id presence"


def test_dissent_surfaced_verbatim_at_presentation():
    doc = _doc_text()
    needle = _mapping()["required_markers"]["dissent_surfacing_step7"]
    assert needle in doc, "dissent must be surfaced verbatim during Present Design"
    # Must land in the Present Design section, not only in the intake block.
    present_idx = doc.index("### Step 3: Present Design")
    tail = doc[present_idx:]
    assert "avengers_brief.dissent[]" in tail, \
        "Present Design section must reference avengers_brief.dissent[] surfacing"


def test_absent_flag_falls_back_to_normal_flow():
    doc = _doc_text()
    assert "If `came_from_avengers` is absent or false" in doc, \
        "absent came_from_avengers must fall back to normal forge flow (mirror founder)"


def test_anti_patterns_updated():
    doc = _doc_text()
    assert "Reading an avengers session directory at session start" in doc, \
        "anti-patterns must warn against ambient avengers coupling"
    assert "Letting a forge-convened avengers session emit a `forge_brief`" in doc, \
        "anti-patterns must warn against the recursion path"
