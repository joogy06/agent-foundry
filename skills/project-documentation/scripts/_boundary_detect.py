"""_boundary_detect.py -- Shared boundary-detection ladder for history.md.

Internal/private helper imported by sibling scripts (rotate, first_touch,
migrate). The leading underscore signals "not a public CLI; do not invoke
directly from outside the project-documentation skill."

Detection ladder (priority order; first tier with >=2 matches AND <30%
ambiguous lines wins):

  H1: explicit `<!-- SESSION_BOUNDARY: id=... -->` markers      DETERMINISTIC
  H2: `^## Session [SI]?\\d+`                                    HIGH
  H3: `^## \\d{4}-\\d{2}-\\d{2}` (top-level date heading)        HIGH
  H4: `^### S\\d+` or `^### Session \\d+` (sub-session)          HIGH
  H5: `^### \\d{4}-\\d{2}-\\d{2}` (date as sub-header)           MEDIUM
  F1: paragraph + 24h-gap heuristic                              LOW
  F2: bulk-archive (no parsing, never drops content)             LOSSY-SAFE

Critical safety rule: F2 is preferred over a low-confidence parse. A bad
parse silently drops or duplicates content; F2 (whole file as one unit)
loses bucketing convenience but never loses content.

Code-fence-aware: tracks ``` and ~~~ fences and ignores heading-pattern
matches inside fenced blocks. Lines inside fences do not count toward
ambiguity.

Performance target: 2,000-line input < 100 ms (largest fleet file is
2,542 lines).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Tier patterns (compiled once)
# ---------------------------------------------------------------------------

_RE_H1 = re.compile(r"^<!--\s*SESSION_BOUNDARY:\s*id=([^\s>]+?)(?:\s+start=(\S+?))?\s*-->\s*$")
_RE_H2 = re.compile(r"^##\s+Session\s+([SI]?\d+)\b", re.IGNORECASE)
_RE_H2_S = re.compile(r"^##\s+(S\d+)\b")  # bare `## S027`
_RE_H3 = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\b")
_RE_H4 = re.compile(r"^###\s+(S\d+|Session\s+\d+)\b", re.IGNORECASE)
_RE_H5 = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\b")

# Code fence opens and closes (we accept lines starting with at least 3
# backticks or 3 tildes; trailing language tag allowed).
_RE_FENCE = re.compile(r"^(```+|~~~+)")

# Lines that are "noise" for ambiguity counting: blank, fenced-out,
# whitespace-only, list-marker only.
_RE_BLANK = re.compile(r"^\s*$")

# Fallback ambiguity heuristic: any heading-shaped line we did NOT match.
_RE_ANY_H2 = re.compile(r"^##\s+\S")
_RE_ANY_H3 = re.compile(r"^###\s+\S")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Boundary:
    """A detected session boundary."""

    line_no: int  # 1-based
    kind: str  # "H1" | "H2" | "H3" | "H4" | "H5" | "F1"
    candidate_id: str  # canonical id= value per design 3.2 table


@dataclass(frozen=True)
class BoundaryReport:
    """Result of `find_boundaries`."""

    tier: str  # "H1" | "H2" | "H3" | "H4" | "H5" | "F1" | "F2"
    boundaries: Tuple[Boundary, ...]
    confidence: str  # "DETERMINISTIC" | "HIGH" | "MEDIUM" | "LOW" | "LOSSY-SAFE"
    ambiguous_line_count: int
    code_fence_ranges: Tuple[Tuple[int, int], ...]  # (start_line, end_line) 1-based, inclusive
    total_lines: int


# ---------------------------------------------------------------------------
# Code-fence tracker
# ---------------------------------------------------------------------------


def _compute_fence_ranges(lines: List[str]) -> List[Tuple[int, int]]:
    """Return (start, end) 1-based inclusive line ranges that are inside
    a fenced code block. Handles same-marker open/close (``` -> ```)
    correctly. Different markers (``` and ~~~) do NOT close each other.
    """

    ranges: List[Tuple[int, int]] = []
    open_marker: Optional[str] = None  # "`" or "~"
    open_line: int = 0

    for idx, line in enumerate(lines, start=1):
        m = _RE_FENCE.match(line)
        if not m:
            continue
        marker = m.group(1)[0]  # ` or ~
        if open_marker is None:
            open_marker = marker
            open_line = idx
        elif marker == open_marker:
            ranges.append((open_line, idx))
            open_marker = None
            open_line = 0
        # else: different marker mid-fence -- ignore as content

    # Unterminated fence: close at EOF so the whole tail is treated as fenced.
    if open_marker is not None and lines:
        ranges.append((open_line, len(lines)))

    return ranges


def is_inside_code_fence(line_no: int, ranges: Tuple[Tuple[int, int], ...]) -> bool:
    """True if `line_no` (1-based) falls within any fence range."""
    for start, end in ranges:
        if start <= line_no <= end:
            return True
    return False


# ---------------------------------------------------------------------------
# Per-tier scanners
# ---------------------------------------------------------------------------


def _scan_tier(
    lines: List[str],
    fences: Tuple[Tuple[int, int], ...],
    tier: str,
) -> List[Boundary]:
    out: List[Boundary] = []
    h3_dates_seen: dict = {}  # for H3 multi-per-day suffix

    for idx, raw in enumerate(lines, start=1):
        if is_inside_code_fence(idx, fences):
            continue

        if tier == "H1":
            m = _RE_H1.match(raw)
            if m:
                out.append(Boundary(idx, "H1", m.group(1)))
            continue

        if tier == "H2":
            m = _RE_H2.match(raw) or _RE_H2_S.match(raw)
            if m:
                token = m.group(1).strip()
                # Normalize: bare "12" -> "S12"; "S027" stays
                if token.isdigit():
                    cid = f"S{int(token):03d}"
                elif token.upper().startswith("S") or token.upper().startswith("I"):
                    cid = token.upper()
                else:
                    cid = token
                out.append(Boundary(idx, "H2", cid))
            continue

        if tier == "H3":
            m = _RE_H3.match(raw)
            if m:
                date = m.group(1)
                # Multi-per-day suffix tracking
                seq = h3_dates_seen.get(date, 0) + 1
                h3_dates_seen[date] = seq
                # We can only know multi-per-day once we've seen 2+; postprocess after loop.
                out.append(Boundary(idx, "H3", date))
            continue

        if tier == "H4":
            m = _RE_H4.match(raw)
            if m:
                token = m.group(1).strip()
                if token.lower().startswith("session"):
                    num_match = re.search(r"\d+", token)
                    if num_match:
                        cid = f"S{int(num_match.group(0)):03d}"
                    else:
                        cid = token
                else:
                    cid = token.upper()
                out.append(Boundary(idx, "H4", cid))
            continue

        if tier == "H5":
            m = _RE_H5.match(raw)
            if m:
                out.append(Boundary(idx, "H5", m.group(1)))
            continue

    # H3 post-pass: if any date appears 2+ times, append -1/-2/...
    if tier == "H3" and out:
        date_counts: dict = {}
        for b in out:
            date_counts[b.candidate_id] = date_counts.get(b.candidate_id, 0) + 1
        # Re-walk and assign sequence numbers only to dates with > 1 occurrence
        seq_per_date: dict = {}
        rebuilt: List[Boundary] = []
        for b in out:
            if date_counts[b.candidate_id] > 1:
                seq_per_date[b.candidate_id] = seq_per_date.get(b.candidate_id, 0) + 1
                cid = f"{b.candidate_id}-{seq_per_date[b.candidate_id]}"
                rebuilt.append(Boundary(b.line_no, "H3", cid))
            else:
                rebuilt.append(b)
        out = rebuilt

    return out


def _count_ambiguous(
    lines: List[str],
    fences: Tuple[Tuple[int, int], ...],
    matched_lineset: set,
) -> int:
    """Count lines that look like a heading (## or ###) but were not
    matched by the chosen tier and are not inside a code fence."""
    n = 0
    for idx, raw in enumerate(lines, start=1):
        if idx in matched_lineset:
            continue
        if is_inside_code_fence(idx, fences):
            continue
        if _RE_BLANK.match(raw):
            continue
        if _RE_ANY_H2.match(raw) or _RE_ANY_H3.match(raw):
            n += 1
    return n


# ---------------------------------------------------------------------------
# F1 fallback (paragraph + 24h-gap)
# ---------------------------------------------------------------------------


def _scan_f1(lines: List[str], fences: Tuple[Tuple[int, int], ...]) -> List[Boundary]:
    """Last-resort heuristic: split on big blank-line gaps. We do NOT use
    real timestamps -- the design's "24h gap" is a metaphor for "natural
    paragraph break of >=3 blank lines", which is the only signal an
    unstamped, dateless file actually carries.

    Each block becomes one boundary at its first non-blank line, with
    candidate_id = `session-<sha8>` per design 3.2 F1 row.
    """

    blocks_starts: List[int] = []
    in_block = False
    blank_run = 0
    block_start = 0

    for idx, raw in enumerate(lines, start=1):
        if is_inside_code_fence(idx, fences):
            in_block = True
            if block_start == 0:
                block_start = idx
            blank_run = 0
            continue

        if _RE_BLANK.match(raw):
            blank_run += 1
            if blank_run >= 3 and in_block:
                in_block = False
                blank_run = 0
            continue

        # non-blank, not fenced
        if not in_block:
            in_block = True
            block_start = idx
            blocks_starts.append(idx)
        blank_run = 0

    out: List[Boundary] = []
    for start in blocks_starts:
        # sha8 of the line at start (stable seed; cheap)
        h = hashlib.sha256(lines[start - 1].encode("utf-8", errors="replace")).hexdigest()[:8]
        out.append(Boundary(start, "F1", f"session-{h}"))
    return out


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


_THRESHOLD_MATCHES = 2  # need >= 2 matches to accept a tier
_THRESHOLD_AMBIGUITY = 0.30  # < 30% ambiguous lines


def find_boundaries(history_text: str) -> BoundaryReport:
    """Detect session boundaries in raw history.md text.

    Returns a `BoundaryReport`. NEVER raises on malformed input -- worst
    case returns tier=F2, boundaries=(), confidence=LOSSY-SAFE.
    """

    if history_text is None:
        history_text = ""
    lines = history_text.splitlines()
    total = len(lines)
    fences = tuple(_compute_fence_ranges(lines))

    # Try tiers in priority order
    tier_order = [("H1", "DETERMINISTIC"), ("H2", "HIGH"), ("H3", "HIGH"), ("H4", "HIGH"), ("H5", "MEDIUM")]

    for tier, conf in tier_order:
        boundaries = _scan_tier(lines, fences, tier)
        if len(boundaries) < _THRESHOLD_MATCHES:
            continue
        matched = {b.line_no for b in boundaries}
        ambiguous = _count_ambiguous(lines, fences, matched)
        # H1 is deterministic regardless of ambiguity; for others enforce ratio
        if tier == "H1":
            return BoundaryReport(
                tier=tier,
                boundaries=tuple(boundaries),
                confidence=conf,
                ambiguous_line_count=ambiguous,
                code_fence_ranges=fences,
                total_lines=total,
            )
        if total > 0 and (ambiguous / max(total, 1)) >= _THRESHOLD_AMBIGUITY:
            continue
        return BoundaryReport(
            tier=tier,
            boundaries=tuple(boundaries),
            confidence=conf,
            ambiguous_line_count=ambiguous,
            code_fence_ranges=fences,
            total_lines=total,
        )

    # F1 (low-confidence paragraph heuristic)
    f1 = _scan_f1(lines, fences)
    if len(f1) >= _THRESHOLD_MATCHES:
        # Self-rated LOW; caller (rotate/first-touch) decides whether to F2-fallback.
        return BoundaryReport(
            tier="F1",
            boundaries=tuple(f1),
            confidence="LOW",
            ambiguous_line_count=0,
            code_fence_ranges=fences,
            total_lines=total,
        )

    # F2 lossy-safe: no boundaries emitted; whole file becomes one unit.
    return BoundaryReport(
        tier="F2",
        boundaries=(),
        confidence="LOSSY-SAFE",
        ambiguous_line_count=0,
        code_fence_ranges=fences,
        total_lines=total,
    )


def classify_tier(report: BoundaryReport) -> str:
    """Public accessor for callers who want only the tier label."""
    return report.tier


__all__ = [
    "Boundary",
    "BoundaryReport",
    "find_boundaries",
    "classify_tier",
    "is_inside_code_fence",
]
