"""Regression tests for the WP-4 `arbiter_mode` top-level switch.

arbiter-synthesis.md is a SHARED file with five callers: the four pre-existing
tournament callers (ATB inline, founder-ideation, alf, adversarial-tournament
workflow) plus the new `avengers` caller. WP-4 added `arbiter_mode` as a
top-level switch WITHOUT changing tournament behavior:

  * an absent `arbiter_mode` defaults to `ideas`;
  * under `arbiter_mode: ideas` the existing `output_class` sub-switch (Step 7)
    operates verbatim (SEMANTIC EQUIVALENCE for the four output_class values);
  * the three new modes (decision | deliverable | forge_brief) do NOT consult
    `output_class` and emit a single-decision-plus-dissent schema.

These tests are the blast-radius controls (design section 10 / section 13 risk 5):
semantic-equivalence fixtures for all four output_class values, a caller sweep,
and a contract-hash tripwire over the arbiter_mode contract sections.
"""

import hashlib
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
DOC = HERE.parent / "references" / "arbiter-synthesis.md"
FIXTURES = HERE / "fixtures"


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def _section(doc: str, start_prefix: str, end_prefix: str) -> str:
    """Text from the first line starting with `start_prefix` (inclusive) up to
    the next line starting with `end_prefix` (exclusive)."""
    lines = doc.splitlines()
    out, capturing = [], False
    for line in lines:
        s = line.strip()
        if not capturing and s.startswith(start_prefix):
            capturing = True
        elif capturing and s.startswith(end_prefix):
            break
        if capturing:
            out.append(line)
    return "\n".join(out)


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Structural: the switch itself                                               #
# --------------------------------------------------------------------------- #

def test_doc_exists():
    assert DOC.is_file(), f"missing shared file: {DOC}"


def test_arbiter_mode_is_top_level_switch():
    sec = _section(_doc_text(), "## Arbiter Mode (top-level switch)", "## Arbiter Model Selection")
    assert sec, "no '## Arbiter Mode (top-level switch)' section"
    assert "top-level" in sec.lower()
    for mode in ("ideas", "decision", "deliverable", "forge_brief"):
        assert mode in sec, f"arbiter_mode value '{mode}' not documented in the switch section"


def test_absent_arbiter_mode_defaults_to_ideas():
    sec = _section(_doc_text(), "## Arbiter Mode (top-level switch)", "## Arbiter Model Selection")
    low = sec.lower()
    assert "absent" in low and "default" in low and "ideas" in low, \
        "the 'absent arbiter_mode defaults to ideas' guarantee is not stated"


def test_ideas_mode_preserves_output_class_subswitch():
    sec = _section(_doc_text(), "## Arbiter Mode (top-level switch)", "## Arbiter Model Selection")
    assert "output_class" in sec, "ideas mode must reference the output_class sub-switch"
    # Step 7 must be flagged as the sub-switch that applies only under arbiter_mode:ideas.
    step7 = _section(_doc_text(), "## Step 7: Output Class Sanity Check", "## Non-`ideas` modes")
    assert "arbiter_mode: ideas" in step7, \
        "Step 7 must state it applies only under arbiter_mode: ideas"


# --------------------------------------------------------------------------- #
# Semantic equivalence: the four output_class values are unchanged            #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("output_class", ["ideas", "signals", "proposals", "designs"])
def test_output_class_semantic_equivalence(output_class):
    contract = _load("output_class_contract.json")["output_class_rules"]
    step7 = _section(_doc_text(), "## Step 7: Output Class Sanity Check", "## Non-`ideas` modes")
    assert step7, "no Step 7 (Output Class Sanity Check) section"
    for needle in contract[output_class]:
        assert needle in step7, (
            f"output_class '{output_class}' semantic-equivalence broken: "
            f"'{needle}' not found verbatim in Step 7 (the frozen contract drifted)"
        )


# --------------------------------------------------------------------------- #
# Caller sweep                                                                #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "caller",
    ["atb-inline", "founder-ideation", "alf", "adversarial-tournament", "avengers"],
)
def test_caller_sweep(caller):
    sweep = _load("caller_sweep.json")["callers"]
    sec = _section(_doc_text(), "## Arbiter Mode (top-level switch)", "## Arbiter Model Selection")
    assert "### Caller sweep" in sec, "no caller-sweep regression table in the switch section"
    row_marker = sweep[caller]["row_marker"]
    assert row_marker in sec, f"caller '{caller}' ({row_marker}) missing from the caller-sweep table"


def test_four_pre_existing_callers_default_to_ideas():
    """The four tournament callers must NOT set arbiter_mode (inherit ideas)."""
    sweep = _load("caller_sweep.json")["callers"]
    sec = _section(_doc_text(), "## Arbiter Mode (top-level switch)", "## Arbiter Model Selection")
    for name, entry in sweep.items():
        if entry["sets_arbiter_mode"]:
            continue  # avengers is allowed to set a mode
        # Every non-avengers caller row must be marked as the default/unset mode.
        assert entry["expected_mode"] == "ideas", f"{name} must default to ideas"
    # And the table must state the default is inherited (unset), not a code change.
    assert "untouched by construction" in _doc_text(), \
        "the 'untouched by construction' guarantee for existing callers is missing"


# --------------------------------------------------------------------------- #
# New modes: single-decision + dissent, obligation-keyed, no output_class     #
# --------------------------------------------------------------------------- #

def test_new_modes_do_not_consult_output_class():
    sec = _section(_doc_text(), "## Non-`ideas` modes", "## Arbiter Output Format")
    assert sec, "no '## Non-`ideas` modes' section"
    low = sec.lower()
    assert "do not consult" in low and "output_class" in low, \
        "new modes must explicitly NOT consult output_class"


def test_new_modes_single_decision_plus_dissent_schema():
    sec = _section(_doc_text(), "## Non-`ideas` modes", "## Arbiter Output Format")
    assert "not a ranked list" in sec.lower(), "new modes must state 'not a ranked list'"
    assert "dissent_record" in sec, "single-decision schema must carry a dissent_record"
    assert "ALWAYS present" in sec, "dissent record must be mandatory (ALWAYS present)"


def test_new_modes_obligation_keyed_survival():
    sec = _section(_doc_text(), "## Non-`ideas` modes", "## Arbiter Output Format")
    low = sec.lower()
    assert "obligation" in low, "new modes must key survival on the obligation ledger"
    assert "stalemate" in low and "unresolved dissent" in low, \
        "stalemate obligations must flow to unresolved dissent (never silently dropped)"


def test_grounding_rule_preserved_in_new_modes():
    sec = _section(_doc_text(), "## Non-`ideas` modes", "## Arbiter Output Format")
    low = sec.lower()
    assert "speculative" in low and "grounding" in low, \
        "the grounding rule (no confidence above speculative without external grounding) must survive"


def test_forge_brief_mode_matches_forge_intake_shape():
    sec = _section(_doc_text(), "## Non-`ideas` modes", "## Arbiter Output Format")
    for field in ("problem", "constraints", "success_criteria", "ruled_out_approaches",
                  "recommended_direction", "dissent", "confidence", "deliberation_record"):
        assert field in sec, f"forge_brief schema missing field '{field}' (must match forge Step 3 intake)"
    assert "contract_map_signed: false" in sec and "bob_ready: false" in sec, \
        "forge_brief must carry contract_map_signed:false + bob_ready:false (mechanically always-false)"


# --------------------------------------------------------------------------- #
# Contract-hash tripwire (blast-radius control, design section 13 risk 5)     #
# --------------------------------------------------------------------------- #

def _contract_hash() -> str:
    doc = _doc_text()
    a = _section(doc, "## Arbiter Mode (top-level switch)", "## Arbiter Model Selection")
    b = _section(doc, "## Non-`ideas` modes", "## Arbiter Output Format")
    normalized = "\n".join(line.rstrip() for line in (a + "\n" + b).splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def test_arbiter_mode_contract_hash_tripwire():
    expected = (FIXTURES / "arbiter_mode_contract.sha256").read_text(encoding="utf-8").strip()
    actual = _contract_hash()
    assert actual == expected, (
        "arbiter-synthesis.md arbiter_mode CONTRACT sections changed.\n"
        "This is a SHARED file (avengers + 4 tournament callers). If the change is "
        "intentional: re-run the caller sweep, confirm semantic equivalence for the "
        "four output_class values, then update "
        "tests/fixtures/arbiter_mode_contract.sha256 to:\n"
        f"  {actual}\n"
        f"(was {expected})"
    )


if __name__ == "__main__":
    # Convenience: print the current contract hash for (re-)blessing the fixture.
    print(_contract_hash())
