#!/usr/bin/env python3
"""GOLDEN: the committed model roster, pinned by hand (#291 design s3.9, WP-6).

Every other test reads the Claude tiers from model_roster (the DATA) instead of spelling a model, so a
roster swap does not turn hundreds of assertions red. That leaves one place where the committed
values are written out literally: here. It is the tripwire that makes a swap DELIBERATE — editing
model_roster.py fails this file until the same person edits it by hand to the new values.

ON EACH SWAP (docs/model-roster-swap.md, the runbook): bump REVISION, move CLAUDE_MAIN /
CLAUDE_SUPPORT / CLAUDE_BENCHED together (or the codex tiers CODEX_STD / CODEX_SUPPORT, #302, or the
reserve CODEX_TOP_ROLES, rev 4, or the agy family AGY_FAMILY / AGY_HARNESS_VERSION, rev 6, or the agy
level map AGY_LEVEL_BY_SIZE, rev 7), append
the HISTORY row — then update the literals below to
match, in the same commit. Never re-derive them from model_roster; that would pin nothing.
"""
import sys
from pathlib import Path

_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import model_roster  # type: ignore  # noqa: E402

# --- the committed roster, by hand --------------------------------------------------------------- #
GOLDEN_REVISION = 8
GOLDEN_CLAUDE_MAIN = "opus"
GOLDEN_CLAUDE_SUPPORT = "sonnet"
GOLDEN_CLAUDE_BENCHED = frozenset({"fable"})
GOLDEN_CODEX_STD = "gpt-6.1-sol"
GOLDEN_CODEX_SUPPORT = "gpt-6.1-terra"
GOLDEN_CODEX_TOP_ROLES = ("code_reviewer@complex", "escalation")   # rev 4: the astra reserve
GOLDEN_AGY_FAMILY = "argon"                                          # rev 6: Gemini 4 Argon (#367)
GOLDEN_AGY_HARNESS_VERSION = "4"
GOLDEN_AGY_LEVEL_BY_SIZE = {"light": "low", "medium": "medium", "complex": "high"}  # rev 7 (#367 WP-C)
# ------------------------------------------------------------------------------------------------- #


def test_the_committed_roster_is_exactly_the_golden_values():
    assert model_roster.SCHEMA == "model-roster.v1"
    assert model_roster.REVISION == GOLDEN_REVISION
    assert model_roster.CLAUDE_MAIN == GOLDEN_CLAUDE_MAIN
    assert model_roster.CLAUDE_SUPPORT == GOLDEN_CLAUDE_SUPPORT
    assert model_roster.CLAUDE_BENCHED == GOLDEN_CLAUDE_BENCHED
    assert model_roster.CODEX_STD == GOLDEN_CODEX_STD
    assert model_roster.CODEX_SUPPORT == GOLDEN_CODEX_SUPPORT
    assert model_roster.CODEX_TOP_ROLES == GOLDEN_CODEX_TOP_ROLES
    assert model_roster.AGY_FAMILY == GOLDEN_AGY_FAMILY
    assert model_roster.AGY_HARNESS_VERSION == GOLDEN_AGY_HARNESS_VERSION
    assert model_roster.AGY_LEVEL_BY_SIZE == GOLDEN_AGY_LEVEL_BY_SIZE


def test_the_golden_values_are_the_last_history_row():
    """The golden values and the roster's own HISTORY agree, so this file cannot be updated to values
    the roster never recorded."""
    last = model_roster.HISTORY[-1]
    assert (last["rev"], last["claude_main"], last["claude_support"], frozenset(last["benched"]),
            last["codex_std"], last["codex_support"], last["codex_top_roles"], last["agy_family"],
            last["agy_level_by_size"]) == (
        GOLDEN_REVISION, GOLDEN_CLAUDE_MAIN, GOLDEN_CLAUDE_SUPPORT, GOLDEN_CLAUDE_BENCHED,
        GOLDEN_CODEX_STD, GOLDEN_CODEX_SUPPORT, GOLDEN_CODEX_TOP_ROLES, GOLDEN_AGY_FAMILY,
        GOLDEN_AGY_LEVEL_BY_SIZE)


def test_the_resolver_serves_the_golden_values():
    """End to end through the shipped resolver: the protected Claude seats serve the golden main tier,
    consultant_support the golden support tier, the codex consultant_support literal the golden support
    slug, the sized std seats the golden std slug, and the roster revision rides on the emitted document."""
    import seat_model  # type: ignore  # noqa: E402

    for role in ("code_reviewer", "consultant_main", "arbiter", "escalation"):
        assert seat_model.ROLE_TABLE[role]["claude"].value == GOLDEN_CLAUDE_MAIN, role
    assert seat_model.ROLE_TABLE["consultant_support"]["claude"].value == GOLDEN_CLAUDE_SUPPORT
    assert seat_model.ROLE_TABLE["consultant_support"]["codex"].value == GOLDEN_CODEX_SUPPORT
    # rev 4, the astra reserve: consultant_main and arbiter are the golden std slug; the reserve is TOP.
    for role in ("consultant_main", "arbiter"):
        assert seat_model.ROLE_TABLE[role]["codex"].value == GOLDEN_CODEX_STD, role
    for role in ("code_reviewer", "escalation"):
        assert seat_model.ROLE_TABLE[role]["codex"].kind == seat_model.KIND_TOP, role
    assert seat_model.CODEX_STD_MODEL == GOLDEN_CODEX_STD
    assert seat_model.CODEX_SUPPORT_MODEL == GOLDEN_CODEX_SUPPORT
    assert seat_model.ROSTER_REVISION == GOLDEN_REVISION
    # rev 6 (#367): the agy family rule and the harness literal are built from the golden family.
    assert seat_model.AGY_FAMILY == GOLDEN_AGY_FAMILY
    assert seat_model.AGY_HARNESS_TEMPLATE.format(level="high") == \
        f"gemini-{GOLDEN_AGY_HARNESS_VERSION}-{GOLDEN_AGY_FAMILY}-high"
    assert seat_model.is_agy_family(f"gemini-{GOLDEN_AGY_HARNESS_VERSION}-{GOLDEN_AGY_FAMILY}-medium")
    assert not seat_model.is_agy_family("gemini-3.8-flash-high")
    # rev 7 (#367 WP-C): the size picks the agy level.
    assert dict(seat_model.AGY_LEVEL_BY_SIZE) == GOLDEN_AGY_LEVEL_BY_SIZE
    for benched in GOLDEN_CLAUDE_BENCHED:
        assert seat_model.is_benched(benched)
    assert not seat_model.is_benched(GOLDEN_CLAUDE_MAIN)
    assert not seat_model.is_benched(GOLDEN_CLAUDE_SUPPORT)
