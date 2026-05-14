"""Unit tests for two_arm_verify.py — HARD-RULE 7 enforcement."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import two_arm_verify as tav  # noqa: E402


def test_identical_strings_max_similarity() -> None:
    assert tav.text_similarity("hello world", "hello world") == 1.0


def test_empty_strings_score_zero() -> None:
    assert tav.text_similarity("", "anything") == 0.0
    assert tav.text_similarity("anything", "") == 0.0


def test_similar_punctuation_normalized() -> None:
    """Trailing period doesn't change score."""
    a = "Validates JWT tokens"
    b = "Validates JWT tokens."
    # Score should be very close to 1.0 after normalization (strips trailing .)
    assert tav.text_similarity(a, b) >= 0.99


def test_different_meaning_low_similarity() -> None:
    """Genuinely different text scores < threshold."""
    a = "Validates JWT tokens and enforces RBAC"
    b = "Generates random user IDs for testing"
    assert tav.text_similarity(a, b) < tav.GROUNDED_THRESHOLD


def test_best_match_picks_highest() -> None:
    candidate = "Validates tokens against the issuer"
    pool = ["Generates random IDs", "Validates tokens against issuer", "Unrelated"]
    score, matched = tav.best_match_similarity(candidate, pool)
    assert matched == "Validates tokens against issuer"
    assert score >= 0.85


def test_best_match_empty_pool() -> None:
    assert tav.best_match_similarity("anything", []) == (0.0, None)


def test_reconcile_responsibilities_promotes_grounded() -> None:
    """High-similarity match between arms promotes to grounded."""
    arm_a = [{"id": "R1", "text": "Validates JWT tokens"}]
    arm_b = [{"text": "Validates JWT tokens"}]
    out, disagree = tav.reconcile_responsibilities(arm_a, arm_b)
    assert out[0]["confidence_level"] == "grounded"
    assert disagree is False


def test_reconcile_responsibilities_demotes_interpretive() -> None:
    """Low-similarity match keeps interpretive + flags disagreement."""
    arm_a = [{"id": "R1", "text": "Validates JWT tokens"}]
    arm_b = [{"text": "Encrypts passwords with bcrypt"}]
    out, disagree = tav.reconcile_responsibilities(arm_a, arm_b)
    assert out[0]["confidence_level"] == "interpretive"
    assert disagree is True


def test_reconcile_responsibilities_empty_b_disagrees() -> None:
    """If arm B has no responsibilities, everything is interpretive."""
    arm_a = [{"id": "R1", "text": "Something specific"}]
    out, disagree = tav.reconcile_responsibilities(arm_a, [])
    assert out[0]["confidence_level"] == "interpretive"
    assert disagree is True


def test_evidence_edges_resolve_all_present() -> None:
    assert tav.evidence_edges_resolve(["e1", "e2"], ["e1", "e2", "e3"]) is True


def test_evidence_edges_resolve_one_missing() -> None:
    assert tav.evidence_edges_resolve(["e1", "e9"], ["e1", "e2"]) is False


def test_evidence_edges_resolve_empty_claimed() -> None:
    assert tav.evidence_edges_resolve([], ["e1"]) is False


def test_reconcile_intent_full_grounded() -> None:
    """Identical intent → full grounded promotion."""
    arm_a = {
        "one_line": "Validates JWT tokens for HTTP entry",
        "responsibilities": [{"id": "R1", "text": "Decode JWTs"}],
    }
    arm_b = {
        "one_line": "Validates JWT tokens for HTTP entry",
        "responsibilities": [{"text": "Decode JWTs"}],
    }
    out = tav.reconcile_intent(arm_a, arm_b, known_edges=["e1"])
    assert out["confidence_level"] == "grounded"
    assert out["responsibilities"][0]["confidence_level"] == "grounded"
    assert out.get("interpretive_disagreement") is False


def test_reconcile_intent_arm_b_unavailable_degrades() -> None:
    """Missing arm B → degraded everything."""
    arm_a = {
        "one_line": "Anything",
        "responsibilities": [{"id": "R1", "text": "Decode JWTs"}],
    }
    out = tav.reconcile_intent(arm_a, None, known_edges=[])
    assert out["confidence_level"] == "degraded"
    assert out["responsibilities"][0]["confidence_level"] == "degraded"
    assert out["interpretive_disagreement"] is True


def test_reconcile_intent_one_line_disagreement() -> None:
    """Different one_line → interpretive."""
    arm_a = {"one_line": "Validates JWT tokens", "responsibilities": []}
    arm_b = {"one_line": "Manages session lifecycle", "responsibilities": []}
    out = tav.reconcile_intent(arm_a, arm_b, known_edges=[])
    assert out["confidence_level"] == "interpretive"


def test_annotate_confidence_no_intent_field_passthrough() -> None:
    """Input without intent block is returned unchanged."""
    data = {"component_id": "x"}
    out = tav.annotate_confidence(data, None, known_edges=[])
    assert out == data


def test_annotate_confidence_normal_pipeline() -> None:
    """Top-level helper applies reconcile_intent in place via copy."""
    data = {
        "component_id": "x",
        "intent": {
            "one_line": "Auth service",
            "confidence_level": "interpretive",
        },
    }
    out = tav.annotate_confidence(data, {"one_line": "Auth service"}, known_edges=[])
    assert out["intent"]["confidence_level"] == "grounded"
    # Original was not mutated
    assert data["intent"]["confidence_level"] == "interpretive"


def test_normalize_case_insensitive() -> None:
    """Normalization is case-insensitive."""
    a = "VALIDATES TOKENS"
    b = "validates tokens"
    assert tav.text_similarity(a, b) >= 0.99


def test_grounded_threshold_constant() -> None:
    """Threshold is exactly 0.95 (locked by design §13)."""
    assert tav.GROUNDED_THRESHOLD == 0.95


def test_prose_fields_constant() -> None:
    """The 3 prose fields are exactly the schema's prose fields."""
    assert tav.PROSE_FIELDS == ("responsibilities", "assumptions", "invariants")
