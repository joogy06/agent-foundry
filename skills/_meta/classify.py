#!/usr/bin/env python3
# <!-- FRESHNESS:v1 -->
"""
classify.py — Deterministic component-classification engine for `G_CLASSIFY`.

S042 / #115. Closes the S039-review G1 hole: whether bob enters the
contract-map -> gates -> ledger -> dual-verdict integrity pipeline hinges on two
*unverified* judgments at bob's front door (bob.md:180 prose heuristic +
bob.md:176 bare `Contract map: N/A` assertion). This module replaces the prose
judgment with a checkable, reproducible verdict and makes `Contract map: N/A` a
*corroborated* decision, not a bare assertion.

Framing = CORROBORATION, not classify-from-scratch: the scan produces an
independent verdict from evidence (design doc + file-touch set), then checks the
*asserted* classification AGREES. Dangerous mismatch (asserted-N/A +
components-evidence) -> BLOCK. Genuine uncertainty -> escalate to user, NEVER
silent-pass, NEVER LLM-decides.

This module is PURE: stdlib only (`re`, `pathlib`, `subprocess` for git,
`hashlib`, `json`). No LLM calls. Deterministic. It WRITES only to
`progress/.classify/` (best-effort verdict.json) and reads design docs + git.
The corroboration-matrix -> exit-code mapping lives in gates.py
(`check_G_CLASSIFY`); this module returns structured results, never sys.exit.

Authoritative spec: docs/plans/2026-06-05-component-classification-gate-design.md
§12 (R1-R8) is BINDING and supersedes §3-§6 where they conflict. Built to §12
literally:
  R1  scan-scope: a positive structural signal counts (CONFIRMED) only if fenced
      OR file-touch-corroborated; prose-only candidates are disregarded for the
      verdict (recorded as `prose_only`).
  R2  the literal regex table (pinned constants below, ship verbatim).
  R3  `contract-classification.v1` artifact schema + `--verify-diff` membership
      map (component-evidence paths). (Schema/verify-diff consumed by gates.py.)
  R4  exit-3 escalate must NOT emit `gate_false_pass` (handled in gates.py).
  R5  usage/docstring (gates.py).
  R7  P5 is DROPPED — a "new gate in gates.py" is the canonical N/A category,
      NOT a component signal. Removed from the catalog entirely.
  R8  N4 exempt set includes `_meta/*.py`; the critical-path exclusion refers to
      COMPONENT-evidence paths only (not `_meta/*.py` source edits).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ===========================================================================
# Locked constants (git-reviewable, anti-rubber-stamp — the
# CONTRACT_SCOPE_CRITICAL_GLOBS / TECHNICAL_CLOSED_LIST precedent).
# NOT mutable config. Re-validate (bump FRESHNESS) when a new exempt class
# appears.
# ===========================================================================

CLASSIFY_VERSION = "1.0.0"

# --- R3 component-evidence corroboration map ------------------------------
# A positive structural signal is "file-corroborated" iff the cycle's
# file-touch set actually touches the corresponding file-class. These same
# globs define `--verify-diff` membership (component-evidence paths). Stored as
# (signal_id -> predicate-kind) so both the scanner (R1(b)) and gates.py
# `--verify-diff` (R3) consult ONE source of truth.
#
# P5 intentionally absent (R7). P2/P3/P7/P8 have no file corroborator (they are
# fenced-only or heading/prose), so they only ever confirm via R1(a) fenced.

# Component-evidence path predicates (used by R1(b) corroboration AND
# --verify-diff). Each entry is a callable path-str -> bool. Pure, no I/O.


def _is_contract_map(p: str) -> bool:
    return p == "progress/contract-map.yaml" or p.endswith("/progress/contract-map.yaml")


def _is_meta_schema(p: str) -> bool:
    # _meta/schemas/<n>.json (anywhere in the tree)
    return bool(re.search(r"(^|/)_meta/schemas/[^/]+\.json$", p))


def _is_services_path(p: str) -> bool:
    return bool(re.search(r"(^|/)services/", p))


def _is_sig(p: str) -> bool:
    return p.endswith(".sig")


def _is_migration_sql(p: str) -> bool:
    return bool(re.search(r"(^|/)migrations/[^/]+\.sql$", p))


# Signal-id -> component-evidence predicate (R1(b)). P1/P4/P6/P9 only.
# P5 dropped (R7); P2/P3/P7/P8 confirm via fenced/heading only.
SIGNAL_CORROBORATORS = {
    "P1": _is_contract_map,
    "P4": _is_meta_schema,
    "P6": _is_services_path,
    "P9": _is_sig,
}

# The full component-evidence predicate set for `--verify-diff` (R3): a path is
# component-evidence if ANY of these match. (Superset of the per-signal
# corroborators: adds migrations/*.sql which has no positive signal but IS a
# typed-contract surface.)
COMPONENT_EVIDENCE_PREDICATES = [
    _is_contract_map,
    _is_meta_schema,
    _is_services_path,
    _is_sig,
    _is_migration_sql,
]


def is_component_evidence_path(path: str) -> bool:
    """R3 membership rule: True iff `path` is a component-evidence path."""
    return any(pred(path) for pred in COMPONENT_EVIDENCE_PREDICATES)


# --- R2 literal regex table (compiled re.MULTILINE) -----------------------
# Each positive entry: id -> (pattern, scope, base_weight, increment, cap,
#                             proximity_kw, proximity_lines)
#   scope: "any" | "fenced" | "heading"
#   "fenced" signals only ever CONFIRM via R1(a) (they have no corroborator).
#   "any (corrob. req.)" signals (P4/P6/P9) CONFIRM via R1(a) fenced OR R1(b).
#   P1 confirms via R1(a) fenced OR R1(b) (contract-map.yaml touched).
# P5 is DROPPED (R7) — not in this table.

# Compiled patterns:
P1_RE = re.compile(r"contract-map\.yaml", re.MULTILINE)
P2_RE = re.compile(
    r"^\s*(integration_points|flows|flow_entry_point|flow_terminal)\s*:",
    re.MULTILINE,
)
P3_RE = re.compile(r"^\s*semantic_type\s*:", re.MULTILINE)
P4_RE_SCHEMA_PATH = re.compile(r"_meta/schemas/[\w.-]+\.json", re.MULTILINE)
P4_RE_PHRASE = re.compile(
    r"\b(frozen|signed)\b.{0,30}\bschema(s)?\b.{0,30}\b(API|contract)\b",
    re.MULTILINE | re.IGNORECASE,
)
P6_RE_MCP = re.compile(r"\bnew MCP server\b", re.MULTILINE | re.IGNORECASE)
P6_RE_SERVICES = re.compile(r"(^|\s)services/", re.MULTILINE)
P6_RE_ENDPOINT = re.compile(r"\b(endpoint|REST|http handler)\b", re.MULTILINE)
P7_RE = re.compile(
    r"\b([2-9]|\d{2,})\s+new\s+(linked\s+)?(components?|ledgers?|services?|modules?)\b",
    re.MULTILINE | re.IGNORECASE,
)
P8_RE = re.compile(r"^#+\s+.*(Contract Map|Components?)\b", re.MULTILINE)
P9_RE_SIG = re.compile(r"contract-map\.yaml\.sig", re.MULTILINE)
P9_RE_HMAC = re.compile(r"\bHMAC\b.{0,20}\bmap\b", re.MULTILINE | re.IGNORECASE)

# Negatives:
N1_RE = re.compile(r"Contract\s+[Mm]ap:?\s*\*{0,2}\s*N/A\s*[—-]", re.MULTILINE)
# N2 exempt lexicon (§3.2 N2 list) — word-boundaried alternation. Order longest-
# first inside alternation groups so e.g. "no new services" matches before
# "services" sub-phrases. Each match counts once per distinct phrase token.
N2_LEXICON = [
    r"knowledge-skill",
    r"skill[- ]?markdown",
    r"markdown text only",
    r"prose-only",
    r"deterministic[ ]+(?:[\w-]+[ ]+){0,3}stdlib",
    r"stdlib",
    r"sidecar",
    r"JSONL writer",
    r"read-only query",
    r"agent text",
    r"extension of existing",
    r"pure extension",
    r"bugfix",
    r"refactor",
    r"no new components",
    r"no services",
    r"no new services",
    r"no endpoints",
    r"no schemas",
]
N2_RE = re.compile(
    r"(?<![\w-])(" + "|".join(N2_LEXICON) + r")(?![\w-])",
    re.MULTILINE | re.IGNORECASE,
)
N3_RE = re.compile(r"precedent[:\s]+S0\d\d", re.MULTILINE)

# Catalog-grammar exclusion (R1 belt-and-suspenders): lines that are catalog/
# table rows are skipped by the scanner so a doc describing the catalog (THIS
# doc's §3.2 / §7 tables) never self-matches.
CATALOG_LINE_RE = re.compile(r"^\s*[-*|]\s*\*\*P\d")
TABLE_ROW_RE = re.compile(r"^\s*\|\s")

# Fenced-code block delimiter (``` ... ```), at line start, optional info string.
FENCE_RE = re.compile(r"^\s*```")

# --- N4 exempt file-touch set (R8) ----------------------------------------
# A file path is "exempt" iff it matches one of these globs. Editing/adding
# _meta/*.py helpers (incl. gates.py, classify.py) IS exempt (R8 — canonical
# N/A category) even though gates.py is #119-safety-critical (different
# concern). The N4 signal fires iff the ENTIRE file-touch profile is within
# this set AND contains zero component-evidence paths (R8 critical-path
# exclusion = component-evidence only).
N4_EXEMPT_PATTERNS = [
    re.compile(r"(^|/)skills/[^/]+/SKILL\.md$"),
    re.compile(r"(^|/)skills/[^/]+/references/.+"),
    re.compile(r"(^|/)_meta/[^/]+\.py$"),
    re.compile(r"(^|/)_meta/[^/]+\.sh$"),
    re.compile(r"(^|/)_meta/[^/]+\.md$"),
    re.compile(r"(^|/)skills/[^/]+/scripts/[^/]+\.py$"),
    re.compile(r"(^|/)agents/[^/]+\.md$"),
    re.compile(r"(^|/)docs/.+"),
    # Test files are canonically exempt (R8 — not component-evidence; the §12
    # self-classify trace lists `tests/`/`tests/fixtures` in the exempt
    # profile). Covers _meta/tests/, skills/*/tests/, and any tests/** subtree.
    re.compile(r"(^|/)_meta/tests/.+\.py$"),
    re.compile(r"(^|/)skills/[^/]+/tests/.+\.(py|json|ya?ml)$"),
    re.compile(r"(^|/)tests/.+"),
    re.compile(r"[^/]+\.md$"),  # bare *.md (top-level)
    re.compile(r"(^|/).+\.md$"),  # any *.md (tests fixtures md, etc.)
]


def _path_is_exempt(path: str) -> bool:
    return any(p.search(path) for p in N4_EXEMPT_PATTERNS)


# ===========================================================================
# Data structures
# ===========================================================================


class SignalHit:
    """One catalog signal evaluation result."""

    __slots__ = ("sid", "weight", "confirmed", "candidate", "detail")

    def __init__(self, sid: str, weight: int, confirmed: bool, candidate: bool,
                 detail: str):
        self.sid = sid
        self.weight = weight
        self.confirmed = confirmed
        self.candidate = candidate
        self.detail = detail

    def as_dict(self) -> Dict:
        return {
            "id": self.sid,
            "weight": self.weight,
            "confirmed": self.confirmed,
            "candidate": self.candidate,
            "detail": self.detail,
        }


# ===========================================================================
# Doc / fenced-stream preprocessing (R1)
# ===========================================================================


def split_fenced(doc_text: str) -> Tuple[str, str]:
    """Split `doc_text` into (prose_stream, fenced_stream).

    R1: `scan()` strips fenced blocks into a SEPARATE stream so fenced-vs-prose
    is decidable per match. Lines inside ``` ... ``` go to the fenced stream;
    everything else to the prose stream. Fence-delimiter lines themselves go to
    neither (they are not content).

    Also applies the R1 catalog-grammar exclusion to the PROSE stream only
    (catalog/table lines never self-match). Fenced content is preserved as-is
    (real YAML/JSON decls are exactly what we want to confirm).

    Line numbering is preserved positionally by substituting excluded/elided
    lines with a blank line, so MULTILINE `^`/`$` anchoring stays faithful and
    proximity (±N lines) math is correct.
    """
    prose_lines: List[str] = []
    fenced_lines: List[str] = []
    in_fence = False
    for line in doc_text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            # delimiter line -> blank in both streams (preserve line count)
            prose_lines.append("")
            fenced_lines.append("")
            continue
        if in_fence:
            fenced_lines.append(line)
            prose_lines.append("")
        else:
            # R1 catalog-grammar exclusion (prose only)
            if CATALOG_LINE_RE.match(line) or TABLE_ROW_RE.match(line):
                prose_lines.append("")
            else:
                prose_lines.append(line)
            fenced_lines.append("")
    return "\n".join(prose_lines), "\n".join(fenced_lines)


def _within_lines(text: str, kw_re: re.Pattern, anchor_re: re.Pattern,
                  span_lines: int) -> bool:
    """True iff some `anchor_re` match is within ±span_lines of some `kw_re`
    match (line-distance). Used for P5-style proximity — but P5 is dropped, so
    this is currently unused; retained for parity / future signals."""
    lines = text.splitlines()
    kw_line_nums = [i for i, ln in enumerate(lines) if kw_re.search(ln)]
    if not kw_line_nums:
        return False
    for i, ln in enumerate(lines):
        if anchor_re.search(ln):
            for k in kw_line_nums:
                if abs(i - k) <= span_lines:
                    return True
    return False


# ===========================================================================
# Scanner (R1 + R2) — produces per-signal SignalHit list
# ===========================================================================


def _confirm(sid: str, fenced_match: bool, file_profile: Optional[List[str]]) -> bool:
    """R1: a CANDIDATE positive is CONFIRMED iff (a) fenced OR (b)
    file-corroborated. P2/P3 are fenced-only (no corroborator). P1/P4/P6/P9
    have corroborators in SIGNAL_CORROBORATORS."""
    if fenced_match:
        return True
    pred = SIGNAL_CORROBORATORS.get(sid)
    if pred is None:
        return False  # fenced-only signal, no file corroborator
    if not file_profile:
        return False
    return any(pred(p) for p in file_profile)


def scan(doc_text: str, file_profile: Optional[List[str]] = None) -> List[SignalHit]:
    """Scan `doc_text` against the locked R2 catalog under R1 scan-scope.

    Returns a list of SignalHit (one per signal that has at least a candidate
    match, plus the negatives that fire). CONFIRMED positives carry their
    weight; candidate-but-unconfirmed positives carry weight 0 and
    confirmed=False (recorded as prose_only). Negatives always count when they
    match (they push toward `no` and are not gameable by fencing).
    """
    prose, fenced = split_fenced(doc_text)
    combined = prose + "\n" + fenced  # for "any"-scope candidate detection
    file_profile = file_profile or []
    hits: List[SignalHit] = []

    # ---- P1: contract-map.yaml referenced -------------------------------
    p1_fenced = len(P1_RE.findall(fenced))
    p1_any = len(P1_RE.findall(combined))
    if p1_any > 0:
        confirmed = _confirm("P1", p1_fenced > 0, file_profile)
        if confirmed:
            # weight = +5 first, +1/hit, cap 9. "hits" = confirmed evidence
            # count: use fenced count if fenced-confirmed, else 1 (file-corrob).
            n = p1_fenced if p1_fenced > 0 else 1
            w = min(5 + max(0, n - 1), 9)
            hits.append(SignalHit("P1", w, True, True,
                                  f"contract-map.yaml x{n} (confirmed)"))
        else:
            hits.append(SignalHit("P1", 0, False, True,
                                  f"contract-map.yaml x{p1_any} (prose_only)"))

    # ---- P2: fenced contract keys (fenced-only) --------------------------
    p2_n = len(P2_RE.findall(fenced))
    if p2_n > 0:
        w = min(4 * p2_n, 8)
        hits.append(SignalHit("P2", w, True, True,
                              f"integration_points/flows keys x{p2_n} (fenced)"))
    else:
        # candidate in prose? (record prose_only if present anywhere)
        if P2_RE.search(prose):
            hits.append(SignalHit("P2", 0, False, True,
                                  "contract keys in prose (prose_only)"))

    # ---- P3: semantic_type: (fenced-only) --------------------------------
    if P3_RE.search(fenced):
        hits.append(SignalHit("P3", 4, True, True, "semantic_type: (fenced)"))
    elif P3_RE.search(prose):
        hits.append(SignalHit("P3", 0, False, True,
                              "semantic_type in prose (prose_only)"))

    # ---- P4: _meta/schemas/*.json OR frozen/signed schema-as-API ---------
    p4_path_fenced = len(P4_RE_SCHEMA_PATH.findall(fenced))
    p4_path_any = len(P4_RE_SCHEMA_PATH.findall(combined))
    p4_phrase_fenced = len(P4_RE_PHRASE.findall(fenced))
    p4_phrase_any = len(P4_RE_PHRASE.findall(combined))
    p4_any = p4_path_any + p4_phrase_any
    if p4_any > 0:
        fenced_match = (p4_path_fenced + p4_phrase_fenced) > 0
        confirmed = _confirm("P4", fenced_match, file_profile)
        if confirmed:
            # +3 each, cap 6. Count confirmed evidence.
            n = (p4_path_fenced + p4_phrase_fenced) if fenced_match else 1
            w = min(3 * max(1, n), 6)
            hits.append(SignalHit("P4", w, True, True,
                                  f"schema-as-API evidence x{n} (confirmed)"))
        else:
            hits.append(SignalHit("P4", 0, False, True,
                                  f"schema-as-API talk x{p4_any} (prose_only)"))

    # ---- P5: DROPPED (R7) — intentionally not scanned --------------------

    # ---- P6: new MCP server / services/ / endpoint -----------------------
    p6_fenced = (len(P6_RE_MCP.findall(fenced)) + len(P6_RE_SERVICES.findall(fenced))
                 + len(P6_RE_ENDPOINT.findall(fenced)))
    p6_any = (len(P6_RE_MCP.findall(combined)) + len(P6_RE_SERVICES.findall(combined))
              + len(P6_RE_ENDPOINT.findall(combined)))
    if p6_any > 0:
        confirmed = _confirm("P6", p6_fenced > 0, file_profile)
        if confirmed:
            n = p6_fenced if p6_fenced > 0 else 1
            w = min(4 * max(1, n), 8)
            hits.append(SignalHit("P6", w, True, True,
                                  f"service/endpoint evidence x{n} (confirmed)"))
        else:
            hits.append(SignalHit("P6", 0, False, True,
                                  f"service/endpoint talk x{p6_any} (prose_only)"))

    # ---- P7: ">=2 new linked components" — only if P1 CONFIRMED ----------
    p1_confirmed = any(h.sid == "P1" and h.confirmed for h in hits)
    if P7_RE.search(combined) and p1_confirmed:
        hits.append(SignalHit("P7", 2, True, True, ">=2 new linked components (P1-gated)"))
    elif P7_RE.search(combined):
        hits.append(SignalHit("P7", 0, False, True,
                              ">=2 new linked components (P1 not confirmed -> 0)"))

    # ---- P8: ## Contract Map / ## Components heading ---------------------
    if P8_RE.search(combined):
        hits.append(SignalHit("P8", 1, True, True, "Contract Map/Components heading"))

    # ---- P9: signed .sig / HMAC-of-map -----------------------------------
    p9_fenced = (len(P9_RE_SIG.findall(fenced)) + len(P9_RE_HMAC.findall(fenced)))
    p9_any = (len(P9_RE_SIG.findall(combined)) + len(P9_RE_HMAC.findall(combined)))
    if p9_any > 0:
        confirmed = _confirm("P9", p9_fenced > 0, file_profile)
        if confirmed:
            hits.append(SignalHit("P9", 3, True, True, "signed map .sig/HMAC (confirmed)"))
        else:
            hits.append(SignalHit("P9", 0, False, True,
                                  f"signed-map talk x{p9_any} (prose_only)"))

    # ---- N1: explicit Contract Map: N/A — <reason> -----------------------
    if N1_RE.search(combined):
        hits.append(SignalHit("N1", -3, True, True, "explicit Contract Map: N/A — line"))

    # ---- N2: exempt lexicon ----------------------------------------------
    n2_phrases = set(m.group(0).lower() for m in N2_RE.finditer(combined))
    if n2_phrases:
        n = len(n2_phrases)
        w = max(-4 - (n - 1), -7)  # -4 first, -1/extra, cap -7
        hits.append(SignalHit("N2", w, True, True,
                              f"exempt lexicon x{n}: {sorted(n2_phrases)[:6]}"))

    # ---- N3: precedent: S0NN citation ------------------------------------
    if N3_RE.search(combined):
        hits.append(SignalHit("N3", -2, True, True, "precedent: S0NN citation"))

    # ---- N4: file-profile entirely exempt + zero component-evidence ------
    if file_profile:
        all_exempt = all(_path_is_exempt(p) for p in file_profile)
        any_component = any(is_component_evidence_path(p) for p in file_profile)
        if all_exempt and not any_component:
            hits.append(SignalHit("N4", -5, True, True,
                                  "file profile entirely exempt, 0 component-evidence"))

    return hits


# ===========================================================================
# Scorer / decision rule (§3.3 O1/O2 + asymmetric band)
# ===========================================================================

VERDICT_YES = "yes"
VERDICT_NO = "no"
VERDICT_AMBIGUOUS = "ambiguous"

# Positive structural signal ids (P1-P6, P9; P5 dropped per R7). P7/P8 are
# weak/derived and do NOT count as "positive structural signal present" for the
# O1/O2 gates (O1 lists P2/P3/P4/P6/P9; O2 keys on P1-P6,P9 absence).
POSITIVE_STRUCTURAL = {"P1", "P2", "P3", "P4", "P6", "P9"}
O1_SECONDARY = {"P2", "P3", "P4", "P6", "P9"}


def derive_class(hits: List[SignalHit]) -> Tuple[str, int, Dict]:
    """Apply §3.3: hard overrides first (O1, O2), then asymmetric score band.

    Operates on CONFIRMED positives ONLY (R1). Returns
    (verdict, score, decision_trace).
    """
    confirmed_pos = {h.sid for h in hits if h.confirmed and h.weight > 0
                     and h.sid in POSITIVE_STRUCTURAL}
    has_p1 = "P1" in confirmed_pos
    has_n4 = any(h.sid == "N4" and h.confirmed for h in hits)

    # Score = sum of all confirmed weights (positives confirmed only carry
    # weight; candidate-only positives carry weight 0; negatives always count).
    score = sum(h.weight for h in hits if h.confirmed)

    trace = {
        "confirmed_positive_signals": sorted(confirmed_pos),
        "has_p1_confirmed": has_p1,
        "has_n4": has_n4,
        "score": score,
        "rule_fired": None,
    }

    # O1 (positive floor): P1 confirmed AND any of P2/P3/P4/P6/P9 confirmed
    if has_p1 and (confirmed_pos & O1_SECONDARY):
        trace["rule_fired"] = "O1"
        return VERDICT_YES, score, trace

    # O2 (clean-negative fast path): ZERO confirmed positive structural signals
    # AND N4 holds.
    if not confirmed_pos and has_n4:
        trace["rule_fired"] = "O2"
        return VERDICT_NO, score, trace

    # Asymmetric band.
    if score >= 5:
        trace["rule_fired"] = "band:yes"
        return VERDICT_YES, score, trace
    if score <= -4:
        trace["rule_fired"] = "band:no"
        return VERDICT_NO, score, trace
    trace["rule_fired"] = "band:ambiguous"
    return VERDICT_AMBIGUOUS, score, trace


# ===========================================================================
# Doc locator (§3.1.1)
# ===========================================================================


def locate_design_doc(project_root: Path, explicit: Optional[Path]) -> Optional[Path]:
    """Resolve the design doc: explicit if given+exists; else freshest
    docs/plans/*-design.md by mtime; else None (no-doc fallback)."""
    if explicit is not None:
        p = explicit if explicit.is_absolute() else (project_root / explicit)
        return p if p.is_file() else None
    plans = project_root / "docs" / "plans"
    if not plans.is_dir():
        return None
    candidates = sorted(
        plans.glob("*-design.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


# ===========================================================================
# File-profile collection (git) — §3.1.3 / §6.4
# ===========================================================================


def git_changed_files(project_root: Path, base: str = "HEAD") -> List[str]:
    """Return repo-relative changed paths: `git diff --name-only <base>` UNION
    untracked. Best-effort: returns [] on any git failure (caller decides)."""
    out: List[str] = []
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-only", base],
            cwd=str(project_root), capture_output=True, text=True, timeout=30,
        )
        if diff.returncode == 0:
            out.extend([ln.strip() for ln in diff.stdout.splitlines() if ln.strip()])
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(project_root), capture_output=True, text=True, timeout=30,
        )
        if untracked.returncode == 0:
            out.extend([ln.strip() for ln in untracked.stdout.splitlines() if ln.strip()])
    except Exception:
        return []
    # de-dup, stable order
    seen = set()
    result = []
    for p in out:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def read_files_from(spec: str, project_root: Path) -> List[str]:
    """Parse a `--files-from` value: either a path to a newline/comma file list,
    or an inline comma-separated list. Returns repo-relative-ish path strings."""
    if not spec:
        return []
    candidate = Path(spec) if Path(spec).is_absolute() else (project_root / spec)
    if candidate.is_file():
        text = candidate.read_text(encoding="utf-8", errors="replace")
        parts = re.split(r"[\n,]+", text)
    else:
        parts = re.split(r"[\n,]+", spec)
    return [p.strip() for p in parts if p.strip()]


# ===========================================================================
# Top-level classify() — assembles scan -> derive -> structured verdict
# ===========================================================================


def classify(
    project_root: Path,
    *,
    design_doc: Optional[Path] = None,
    file_profile: Optional[List[str]] = None,
) -> Dict:
    """Produce an independent verdict from evidence (design doc + file profile).

    Returns a structured dict:
      {verdict, score, signals:[...], design_doc, file_profile,
       decision_trace, evidence:{confirmed_positives, negatives, prose_only}}

    No I/O beyond reading the design doc. Does NOT consult the asserted
    classification — that comparison (the corroboration matrix) is gates.py's
    job. Does NOT sys.exit.
    """
    resolved_doc = locate_design_doc(project_root, design_doc)
    doc_text = ""
    if resolved_doc is not None:
        try:
            doc_text = resolved_doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            doc_text = ""

    hits = scan(doc_text, file_profile=file_profile)
    verdict, score, trace = derive_class(hits)

    # No-doc fallback nuance (§6.5): if there is NO doc text AND no confirmed
    # positives, the verdict is driven purely by the file profile via N4/score.
    # That already flows through scan()/derive_class() (N4 fires -> O2 -> no;
    # a positive-path touch -> P-signal confirmed via R1(b) -> score/ambiguous).
    # Empty file set + no doc -> no signals -> score 0 -> ambiguous (escalate),
    # which §6.5 mandates.

    confirmed_positives = [h.as_dict() for h in hits
                           if h.confirmed and h.weight > 0]
    negatives = [h.as_dict() for h in hits if h.confirmed and h.weight < 0]
    prose_only = [h.as_dict() for h in hits if not h.confirmed]

    return {
        "verdict": verdict,
        "score": score,
        "signals": [h.as_dict() for h in hits],
        "design_doc": str(resolved_doc) if resolved_doc else None,
        "file_profile": list(file_profile) if file_profile else [],
        "decision_trace": trace,
        "evidence": {
            "confirmed_positives": confirmed_positives,
            "negatives": negatives,
            "prose_only": prose_only,
        },
        "classify_version": CLASSIFY_VERSION,
    }


# ===========================================================================
# verdict.json writer (best-effort, replace-on-write) — §3.4 audit trail
# ===========================================================================


def write_verdict(project_root: Path, payload: Dict) -> Optional[Path]:
    """Write the verdict + score + per-signal evidence + asserted + outcome to
    `progress/.classify/verdict.json` (replace-on-write, best-effort).

    Returns the path on success, None on any failure (never raises — this is an
    audit convenience, not a gate input). This is the ONLY filesystem write
    classify.py performs (D1: writes ONLY under progress/.classify/).
    """
    try:
        out_dir = project_root / "progress" / ".classify"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "verdict.json"
        tmp = out_dir / "verdict.json.tmp"
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(out_path)
        return out_path
    except Exception:
        return None


# ===========================================================================
# --verify-diff membership computation (R3 / §6.4) — gates.py consumes
# ===========================================================================


def verify_diff_violations(
    project_root: Path,
    introduces_components: str,
    existing_extension_globs: Optional[List[str]] = None,
    base: str = "HEAD",
    file_profile_override: Optional[List[str]] = None,
) -> List[str]:
    """R3 `--verify-diff` rule: let D = git diff --name-only <base> UNION
    untracked. If introduces_components == "no" AND D contains >=1
    component-evidence path NOT covered by an `existing_component_extension`
    declaration -> return the offending paths (BLOCK). Else [].

    `existing_extension_globs` are fnmatch-style globs from the artifact's
    declaration that whitelist specific component-evidence paths under the
    `existing_component_extension` reason_code.
    """
    import fnmatch

    if introduces_components != "no":
        return []  # over-declaring is safe; only the N/A route is policed
    diff = (file_profile_override if file_profile_override is not None
            else git_changed_files(project_root, base=base))
    existing_extension_globs = existing_extension_globs or []
    violations = []
    for p in diff:
        if not is_component_evidence_path(p):
            continue
        covered = any(fnmatch.fnmatch(p, g) for g in existing_extension_globs)
        if not covered:
            violations.append(p)
    return violations


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def doc_hash(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.is_file():
        return None
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
