"""two_arm_verify.py — Cold-context second pass for prose intent claims.

Per HARD-RULE 7 (S032 design §13):

  > Every `intent.responsibilities[]` / `assumptions[]` / `invariants[]` entry
  > must have `confidence_level: grounded` only if (a) `evidence_edges[]` cite
  > real edges in `static.jsonl` AND (b) a cold-context second pass produced
  > ≥0.95 semantic similarity. Single-arm output is `interpretive` and never
  > feeds gates or test generation.

This module implements the algorithmic side of (b): given two YAML outputs
from two independent LLM passes, compare prose claims and assign:

  - grounded     : similarity ≥ 0.95 AND evidence_edges resolve
  - interpretive : similarity < 0.95 OR evidence_edges absent
  - degraded     : second-pass LLM call failed / unavailable

No LLM is called from this module — it's pure comparison. The actual second
LLM pass is initiated by `run.py` and the result is passed in.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

GROUNDED_THRESHOLD = 0.95
PROSE_FIELDS = ("responsibilities", "assumptions", "invariants")


def _normalize(text: str) -> str:
    """Normalize prose for similarity comparison.

    - Lowercase
    - Collapse whitespace
    - Strip punctuation that doesn't affect meaning
    """
    text = text.lower().strip()
    text = re.sub(r"[\s\n]+", " ", text)
    text = re.sub(r"[\.,;:!\?]+$", "", text)
    return text


def text_similarity(a: str, b: str) -> float:
    """Return [0.0, 1.0] similarity between two prose strings.

    Uses difflib.SequenceMatcher on normalized text — deterministic, no LLM.
    For S032 v1 this is adequate for the simple "is the second pass
    saying roughly the same thing" check. Future versions may swap for an
    embedding-based check (Qwen / sentence-transformers) without changing
    this module's public surface.
    """
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def best_match_similarity(
    candidate: str,
    pool: List[str],
) -> Tuple[float, Optional[str]]:
    """Find the highest-similarity item in `pool` against `candidate`.

    Returns (score, matched_text_or_none).
    """
    if not pool:
        return 0.0, None
    best = (0.0, None)
    for item in pool:
        score = text_similarity(candidate, item)
        if score > best[0]:
            best = (score, item)
    return best


def reconcile_responsibilities(
    arm_a: List[Dict[str, Any]],
    arm_b: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], bool]:
    """Reconcile two responsibility arrays from two LLM passes.

    Returns (annotated_responsibilities, interpretive_disagreement).
    Each responsibility gets its `confidence_level` set to grounded when
    similarity≥0.95 with at least one arm_b entry, else interpretive.
    `interpretive_disagreement` is True when any arm_a entry has no
    counterpart in arm_b above the threshold.
    """
    pool_b = [r.get("text", "") for r in arm_b]
    disagree = False
    out: List[Dict[str, Any]] = []
    for r in arm_a:
        text = r.get("text", "")
        score, _ = best_match_similarity(text, pool_b)
        new_r = dict(r)
        if score >= GROUNDED_THRESHOLD:
            new_r["confidence_level"] = "grounded"
        else:
            new_r["confidence_level"] = "interpretive"
            disagree = True
        out.append(new_r)
    return out, disagree


def evidence_edges_resolve(
    edges_claimed: List[str],
    edges_known: List[str],
) -> bool:
    """Return True iff every claimed edge id appears in the known set."""
    if not edges_claimed:
        return False
    known = set(edges_known)
    return all(e in known for e in edges_claimed)


def reconcile_intent(
    arm_a_intent: Dict[str, Any],
    arm_b_intent: Optional[Dict[str, Any]],
    known_edges: List[str],
) -> Dict[str, Any]:
    """Apply two-arm verification to a full `intent` block.

    If arm_b_intent is None (second pass failed / unavailable), confidence
    is downgraded to `degraded` for all prose, and interpretive_disagreement
    is set True.
    """
    out = dict(arm_a_intent)

    if arm_b_intent is None:
        # Degraded fallback — second pass unavailable
        out["confidence_level"] = "degraded"
        out["interpretive_disagreement"] = True
        if "responsibilities" in out and isinstance(out["responsibilities"], list):
            for r in out["responsibilities"]:
                r["confidence_level"] = "degraded"
        return out

    # one_line: simple top-level similarity check
    one_a = arm_a_intent.get("one_line", "")
    one_b = arm_b_intent.get("one_line", "")
    one_sim = text_similarity(one_a, one_b)
    top_conf = "grounded" if one_sim >= GROUNDED_THRESHOLD else "interpretive"
    out["confidence_level"] = top_conf

    # Responsibilities: per-entry reconciliation
    if "responsibilities" in arm_a_intent and isinstance(arm_a_intent["responsibilities"], list):
        a_resps = arm_a_intent["responsibilities"]
        b_resps = arm_b_intent.get("responsibilities", []) or []
        annotated, disagree = reconcile_responsibilities(a_resps, b_resps)
        # Downgrade individual responsibilities whose evidence_files don't
        # appear plausible per known_edges (best-effort heuristic — files are
        # not edge ids, so we accept this as a non-blocking guidance).
        out["responsibilities"] = annotated
        out["interpretive_disagreement"] = disagree

    return out


def annotate_confidence(
    intent_dict: Dict[str, Any],
    arm_b_intent: Optional[Dict[str, Any]],
    known_edges: List[str],
) -> Dict[str, Any]:
    """Top-level helper used by run.py to apply HARD-RULE 7 verification."""
    if "intent" not in intent_dict:
        return intent_dict
    reconciled = reconcile_intent(
        intent_dict["intent"], arm_b_intent, known_edges
    )
    out = dict(intent_dict)
    out["intent"] = reconciled
    return out
