#!/usr/bin/env python3
"""cobol_offset_calc.py — deterministic COBOL byte-offset calculator (the SAFETY CRUX).

Part of the structure-recovery skill (lineage-family sibling of
lineage-extract-static / legacy-code-intel). This module is the place the design
calls "the safety crux": **the LLM is the parser, Python is the calculator.**

The analyze-cobol prompt (WP-4) emits a ``structure-finding.v1`` whose every
``fields[].byte_offset`` and ``fields[].length`` is ``null`` — the LLM NEVER
declares or guesses a byte offset (``validate_finding.py`` REJECTS a non-null
value). This module takes that declared level-tree and computes
``byte_offset`` / ``length`` (and the variable/ranged variants) DETERMINISTICALLY
from the PICTURE / USAGE / OCCURS / REDEFINES facts, producing the field shape of
``structure-index.v1`` (``byte_offset``, ``length``, ``byte_offset_min``,
``byte_offset_max``, ``ranged``, ``variable_length``, ``offset_confidence``) plus
the record-length rollup and honest ``gaps[]``.

Sizing rules (design §3.3, cross-checked against the cobol-developer skill PIC
table):

* DISPLAY: ``len = digit_count`` (``X(n)`` -> n; ``V`` / ``S``-overpunch -> 0
  extra; ``SIGN ... SEPARATE`` -> +1).
* COMP-3 / PACKED-DECIMAL: ``len = floor(d/2) + 1`` == ``(d+1)//2 + (1 - d%2)`` ...
  i.e. ``d//2 + 1`` (odd and even both round up to the next half-byte + sign nibble).
* COMP / COMP-4 / COMP-5 / BINARY: 1-4 digits -> 2B, 5-9 -> 4B, 10-18 -> 8B.
* COMP-1 -> 4B; COMP-2 -> 8B; INDEX -> 4B.
* NATIONAL / DBCS -> 2 bytes per character.
* POINTER / PROCEDURE-POINTER / FUNCTION-POINTER -> 4 or 8B (flagged assumption;
  defaults to 4, configurable via ``pointer_size``).
* Group length = sum(children) (REDEFINES is non-additive). Record length =
  01-level length.

Hard cases (each exercised by >= 3 fixtures in the test suite):

* COMP-3 odd/even rounding cascade.
* OCCURS / nested-OCCURS multiply.
* OCCURS DEPENDING ON -> ``byte_offset_min`` + ``byte_offset_max`` +
  ``variable_length: true``; REFUSE a single authoritative post-ODO offset
  (Codex Finding 1).
* REDEFINES non-additive (shares the offset, does NOT advance the cursor; a
  larger REDEFINES extends the group).
* USAGE group-inheritance (propagate a group's USAGE to its children).
* SIGN SEPARATE +1.
* SYNCHRONIZED -> compute WITHOUT slack but emit offsets as RANGED/UNKNOWN +
  ``gap: sync_alignment``, NEVER a confident "without-slack" value
  (Codex Finding 1).
* level-88 / level-66 (RENAMES) = zero bytes.
* V / P implied-decimal = zero bytes.
* NATIONAL / DBCS 2 bytes per char.

COPY splicing is cross-file: WP-6 resolves the COPY member THEN calls this. An
unresolved COPY surfaces as ``gap: unresolved_copybook`` and forces the affected
subtree to ``speculative``.

Offset confidence (per field, design §3.4):

* ``grounded`` — a clean DISPLAY / COMP / COMP-3 chain with an explicit USAGE.
* ``inferred`` — a field whose USAGE was inherited from its group (not declared
  on the field itself), or that lives under such a group.
* ``speculative`` — anything inside a SYNCHRONIZED group, the variable tail after
  an OCCURS DEPENDING ON, an unresolved COPY subtree, or a field whose PIC could
  not be sized.

Pure stdlib (no per-format parser deps, sibling parity). Python 3.12 target.

Python API::

    from cobol_offset_calc import compute_offsets, compute_finding_offsets
    result = compute_finding_offsets(finding_dict)   # -> ComputeResult
    # result.fields  -> list[dict] in structure-index.v1 field shape
    # result.record_length / record_length_min / record_length_max
    # result.variable_length
    # result.gaps    -> list[dict] (sync_alignment / odo_variable_length / ...)

CLI usage::

    cobol_offset_calc.py <finding.json>   # prints the computed index-entity JSON
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field as _dc_field
from pathlib import Path
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Confidence helpers (kept consistent with the lineage conf_rank idiom)
# ---------------------------------------------------------------------------

_CONF_RANK = {"grounded": 3, "inferred": 2, "speculative": 1}
_RANK_CONF = {3: "grounded", 2: "inferred", 1: "speculative"}


def _min_conf(a: str, b: str) -> str:
    """Lower-confidence-wins (mirrors accumulate.py conf_rank lower-wins)."""
    return _RANK_CONF[min(_CONF_RANK.get(a, 1), _CONF_RANK.get(b, 1))]


# ---------------------------------------------------------------------------
# Gap kinds (closed set — must be a subset of structure-finding.v1 gaps.kind)
# ---------------------------------------------------------------------------

GAP_SYNC = "sync_alignment"
GAP_ODO = "odo_variable_length"
GAP_UNRESOLVED_COPY = "unresolved_copybook"

# Levels that occupy zero storage.
_ZERO_BYTE_LEVELS = {66, 88}


# ---------------------------------------------------------------------------
# PIC parsing — count declared digit/char positions WITHOUT executing anything
# ---------------------------------------------------------------------------

# A PIC body is a sequence of symbols, each optionally followed by a (n)
# repeat-count. We only care about the *position-bearing* symbols:
#   9  -> a numeric digit position
#   X  -> an alphanumeric character position
#   A  -> an alphabetic character position
#   N  -> a national (DBCS) character position  (2 bytes/char in DISPLAY usage)
#   Z  -> a zero-suppressed digit (edited DISPLAY; one char position)
#   *  -> check-protect digit (one char position)
#   S  -> sign (overpunched: 0 extra positions unless SIGN SEPARATE)
#   V  -> implied decimal point (0 bytes)
#   P  -> assumed decimal scaling position (0 bytes — scaling only)
# Editing/insertion symbols that DO occupy a display position:
#   . , / B 0 + - CR DB $  -> each is one character position in an edited PIC.
# We keep the parser conservative: it counts digit positions (for COMP/COMP-3
# sizing) AND total character positions (for DISPLAY sizing) separately.

_PIC_TOKEN_RE = re.compile(
    r"""
    (?P<sym>
        CR | DB |          # two-letter editing symbols first
        [9XANZ*SVP./,B0+\-$]   # single-char symbols
    )
    (?:\((?P<count>\d+)\))?    # optional explicit repeat count
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Symbols that contribute a *digit* position (used for COMP / COMP-3 sizing).
_DIGIT_SYMS = {"9", "Z", "*"}
# Symbols that contribute a *display character* position (used for DISPLAY len).
# (digit symbols + alpha + national + edit-insertion chars; S/V/P excluded.)
_DISPLAY_CHAR_SYMS = {
    "9", "X", "A", "N", "Z", "*",
    ".", ",", "/", "B", "0", "+", "-", "$", "CR", "DB",
}


@dataclass
class PicInfo:
    digit_count: int          # number of 9/Z/* digit positions
    char_count: int           # number of display character positions
    has_national: bool        # PIC contains N (DBCS)
    has_sign: bool            # PIC contains S
    is_numeric: bool          # PIC is a pure numeric (9/S/V/P only, no X/A/N)
    parse_ok: bool            # we recognised every token


def parse_pic(pic: Optional[str]) -> Optional[PicInfo]:
    """Parse a COBOL PICTURE string into position counts. Returns ``None`` for an
    empty/None PIC (a group item, which has no PIC). Never raises — an
    unrecognised body yields ``parse_ok=False`` so the caller can downgrade.
    """
    if pic is None:
        return None
    body = pic.strip()
    if not body:
        return None
    # Strip a leading "PIC"/"PICTURE" and "IS" if a verbatim clause slipped in.
    body = re.sub(r"^\s*PIC(?:TURE)?\s+(?:IS\s+)?", "", body, flags=re.IGNORECASE)
    # Drop a trailing usage/edit word that is sometimes glued on (defensive;
    # usage is normally a separate field). We only look at the picture token run.
    digit = 0
    chars = 0
    has_national = False
    has_sign = False
    has_alpha = False
    consumed = 0
    pos = 0
    upper = body.upper()
    for m in _PIC_TOKEN_RE.finditer(upper):
        if m.start() != pos:
            # A gap of unrecognised characters between tokens.
            gap = upper[pos:m.start()].strip()
            if gap:
                # Unknown content inside the picture run -> not fully parseable.
                return PicInfo(digit, chars, has_national, has_sign,
                               is_numeric=False, parse_ok=False)
        sym = m.group("sym").upper()
        cnt = int(m.group("count")) if m.group("count") else 1
        consumed += cnt
        if sym in _DIGIT_SYMS:
            digit += cnt
        if sym == "N":
            has_national = True
            chars += cnt
        elif sym in ("X",):
            has_alpha = True
            chars += cnt
        elif sym == "A":
            has_alpha = True
            chars += cnt
        elif sym == "S":
            has_sign = True
        elif sym in ("V", "P"):
            pass  # zero bytes — implied decimal / scaling position
        elif sym in _DISPLAY_CHAR_SYMS:
            chars += cnt
        pos = m.end()
    if pos != len(upper):
        trailing = upper[pos:].strip()
        if trailing:
            return PicInfo(digit, chars, has_national, has_sign,
                           is_numeric=False, parse_ok=False)
    is_numeric = (not has_alpha) and (digit > 0 or has_sign)
    return PicInfo(
        digit_count=digit,
        char_count=chars,
        has_national=has_national,
        has_sign=has_sign,
        is_numeric=is_numeric,
        parse_ok=True,
    )


# ---------------------------------------------------------------------------
# USAGE normalisation
# ---------------------------------------------------------------------------

_USAGE_ALIASES = {
    "COMPUTATIONAL": "COMP",
    "COMP": "COMP",
    "COMPUTATIONAL-1": "COMP-1",
    "COMP-1": "COMP-1",
    "COMPUTATIONAL-2": "COMP-2",
    "COMP-2": "COMP-2",
    "COMPUTATIONAL-3": "COMP-3",
    "COMP-3": "COMP-3",
    "PACKED-DECIMAL": "COMP-3",
    "COMPUTATIONAL-4": "COMP-4",
    "COMP-4": "COMP-4",
    "BINARY": "COMP-4",
    "COMPUTATIONAL-5": "COMP-5",
    "COMP-5": "COMP-5",
    "INDEX": "INDEX",
    "POINTER": "POINTER",
    "PROCEDURE-POINTER": "POINTER",
    "FUNCTION-POINTER": "POINTER",
    "DISPLAY": "DISPLAY",
    "DISPLAY-1": "DISPLAY-1",  # DBCS display
    "NATIONAL": "NATIONAL",
}


def normalize_usage(usage: Optional[str]) -> Optional[str]:
    """Canonicalise a USAGE token; ``None`` means 'not declared on this item'."""
    if usage is None:
        return None
    key = usage.strip().upper()
    if not key:
        return None
    return _USAGE_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Field length computation (single elementary item, no OCCURS multiply)
# ---------------------------------------------------------------------------

class SizingError(ValueError):
    """An elementary item could not be sized from PIC+USAGE."""


def _binary_len(digits: int) -> int:
    """COMP/COMP-4/COMP-5/BINARY storage size from declared digit count."""
    if digits <= 0:
        # No digits declared on a binary item — assume a fullword, flag upstream.
        return 4
    if digits <= 4:
        return 2
    if digits <= 9:
        return 4
    if digits <= 18:
        return 8
    # 19-31 digits (extended) -> 16 bytes on many compilers; flag as assumption.
    return 16


def elementary_length(
    pic_info: Optional[PicInfo],
    usage: Optional[str],
    *,
    pointer_size: int = 4,
) -> tuple[int, str]:
    """Compute the storage length of ONE elementary item (no OCCURS).

    Returns ``(length_bytes, basis)`` where ``basis`` is a short tag describing
    how the size was derived (used to set offset_confidence and for debugging):
    ``display`` / ``comp3`` / ``binary`` / ``float`` / ``index`` / ``pointer`` /
    ``national`` / ``unsized``.

    Raises nothing — an unsizeable item returns ``(0, "unsized")`` so the caller
    can record a gap and downgrade rather than crash.
    """
    u = normalize_usage(usage)

    # Usages whose size is independent of PIC.
    if u == "COMP-1":
        return 4, "float"
    if u == "COMP-2":
        return 8, "float"
    if u == "INDEX":
        return 4, "index"
    if u == "POINTER":
        return pointer_size, "pointer"

    if pic_info is None or not pic_info.parse_ok:
        # No usable PIC. For a declared binary/packed usage with no digits we
        # still can't size confidently; return unsized so caller downgrades.
        return 0, "unsized"

    if u == "COMP-3":
        d = pic_info.digit_count
        if d <= 0:
            return 0, "unsized"
        # floor(d/2)+1 ; odd and even both: 1->1, 2->2, 3->2, 4->3, 5->3 ...
        return d // 2 + 1, "comp3"

    if u in ("COMP", "COMP-4", "COMP-5"):
        d = pic_info.digit_count
        if d <= 0:
            return 0, "unsized"
        return _binary_len(d), "binary"

    if u in ("NATIONAL", "DISPLAY-1") or pic_info.has_national:
        # National / DBCS: 2 bytes per character position.
        chars = pic_info.char_count
        if chars <= 0:
            return 0, "unsized"
        return chars * 2, "national"

    # DISPLAY (explicit or defaulted). Length is the count of character
    # positions; S overpunch adds nothing unless SIGN SEPARATE (handled by the
    # caller via the field flag), V/P add nothing.
    chars = pic_info.char_count
    if chars <= 0:
        return 0, "unsized"
    return chars, "display"


# ---------------------------------------------------------------------------
# Level-tree reconstruction from a flat field list
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """A node in the reconstructed COBOL level tree."""
    src: dict                       # the original structure-finding field dict
    name: str
    level: int
    ordinal: int
    index: int                      # position in the original flat list
    children: list["Node"] = _dc_field(default_factory=list)
    parent: Optional["Node"] = None

    # Computed (filled in by the calculator):
    length: int = 0
    length_min: int = 0
    length_max: int = 0
    byte_offset: Optional[int] = None
    byte_offset_min: Optional[int] = None
    byte_offset_max: Optional[int] = None
    # Group-relative layout positions (filled by _size_group, shifted absolute
    # by _assign_offsets):
    rel_offset: int = 0
    rel_offset_min: int = 0
    rel_offset_max: int = 0
    ranged: bool = False
    variable_length: bool = False
    # True when this field's ABSOLUTE byte_offset is deterministic (no preceding
    # ODO/SYNC sibling shifted it, and the field itself is neither SYNC-slacked
    # nor variable-length). ODO fields have a KNOWN start but a variable LENGTH,
    # so offset_known stays True for the ODO field itself; SYNC fields get
    # offset_known=False (slack may push them forward).
    offset_known: bool = True
    offset_confidence: str = "grounded"
    basis: str = ""
    # Effective usage after group inheritance:
    eff_usage: Optional[str] = None
    usage_inherited: bool = False

    @property
    def is_group(self) -> bool:
        return bool(self.children)


def build_tree(fields: list[dict]) -> list[Node]:
    """Reconstruct the COBOL level hierarchy from a flat, declaration-ordered
    field list using level numbers.

    Standard COBOL rule: a field is a child of the most recent earlier field
    whose level number is strictly lower. level-88 (condition-name) and level-66
    (RENAMES) are NOT structural parents/children in the storage tree — they are
    attached to the record root as zero-byte siblings so they round-trip but do
    not perturb offsets. level-77 is an independent elementary item (treated as a
    top-level node).
    """
    roots: list[Node] = []
    # Stack of (level, node) for genuine structural items only (not 66/88).
    stack: list[Node] = []
    specials: list[Node] = []  # 66/88 nodes, re-attached at the end

    for idx, fld in enumerate(fields):
        lvl = fld.get("level")
        name = str(fld.get("name", f"<field#{idx}>"))
        ordn = int(fld.get("ordinal", idx))
        node = Node(src=fld, name=name,
                    level=int(lvl) if lvl is not None else 1,
                    ordinal=ordn, index=idx)

        if lvl in _ZERO_BYTE_LEVELS:
            # 66 RENAMES / 88 condition-name — zero bytes, not in the storage tree.
            specials.append(node)
            continue

        # Pop deeper-or-equal levels off the stack to find this node's parent.
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            parent = stack[-1]
            node.parent = parent
            parent.children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    # Attach specials to the nearest preceding structural node's root chain.
    # For offset purposes they are zero-byte; we attach them to the top-level
    # record (first root) so they survive in output without affecting layout.
    for sp in specials:
        if roots:
            sp.parent = roots[0]
            # do NOT add to children (would corrupt group length); keep separate
    return roots


# ---------------------------------------------------------------------------
# The calculator
# ---------------------------------------------------------------------------

@dataclass
class ComputeResult:
    """Result of computing offsets for ONE record (01-level) or field list."""
    fields: list[dict]                       # structure-index.v1 field shape
    record_length: Optional[int]             # None when variable/unknown
    record_length_min: Optional[int]
    record_length_max: Optional[int]
    variable_length: bool
    gaps: list[dict]
    confidence: str                          # most-conservative field confidence


def _flatten(node: Node) -> Iterable[Node]:
    yield node
    for ch in node.children:
        yield from _flatten(ch)


@dataclass
class _Ctx:
    """Mutable computation context threaded through the recursion."""
    pointer_size: int
    copy_unresolved: bool
    gaps: list[dict] = _dc_field(default_factory=list)
    seen_gap_keys: set = _dc_field(default_factory=set)

    def add_gap(self, kind: str, line: int, description: str) -> None:
        key = (kind, line, description)
        if key in self.seen_gap_keys:
            return
        self.seen_gap_keys.add(key)
        self.gaps.append({"kind": kind, "line": int(line), "description": description})


def _field_line(node: Node) -> int:
    ev = node.src.get("evidence")
    if isinstance(ev, dict) and isinstance(ev.get("line"), int):
        return ev["line"]
    return 1


def _resolve_usage(node: Node, inherited: Optional[str]) -> tuple[Optional[str], bool]:
    """Effective USAGE for a node: its own declared usage, else the inherited
    group usage. Returns (usage, was_inherited)."""
    own = normalize_usage(node.src.get("usage"))
    if own is not None:
        return own, False
    if inherited is not None:
        return inherited, True
    return None, False


def _occurs_factor(node: Node) -> tuple[int, int, bool]:
    """Return ``(min_factor, max_factor, is_odo)`` for a node's OCCURS.

    Fixed OCCURS n          -> (n, n, False)
    OCCURS m TO n DEPENDING  -> (m, n, True)   (m defaults to occurs when only
                                                occurs_max given; lower bound 1
                                                if neither present)
    No OCCURS                 -> (1, 1, False)
    """
    src = node.src
    odo = src.get("occurs_depending_on")
    occ = src.get("occurs")
    occ_max = src.get("occurs_max")
    if odo:
        # Variable. occurs is the (declared) max in our schema; occurs_max the TO.
        hi = occ_max if isinstance(occ_max, int) else (occ if isinstance(occ, int) else 1)
        lo = occ if isinstance(occ, int) and isinstance(occ_max, int) else 1
        # When only `occurs` is present (== max), the floor is the ODO minimum,
        # which we cannot know statically; use 0 to be honest about the tail.
        if not isinstance(occ_max, int):
            lo = 0
            hi = occ if isinstance(occ, int) else 1
        return max(lo, 0), max(hi, 0), True
    if isinstance(occ, int) and occ > 0:
        return occ, occ, False
    return 1, 1, False


def _compute_node(node: Node, ctx: _Ctx, inherited_usage: Optional[str],
                  in_sync: bool, in_odo_tail: bool, in_unresolved: bool) -> None:
    """Recursively size ``node`` (sets length/length_min/length_max + basis +
    a *local* offset_confidence floor). Offsets are assigned in a second pass."""
    # SYNCHRONIZED is a property of this item OR an enclosing group.
    node_sync = bool(node.src.get("synchronized")) or in_sync
    # Effective usage (group inheritance).
    eff_usage, inherited = _resolve_usage(node, inherited_usage)
    node.eff_usage = eff_usage
    node.usage_inherited = inherited

    # Unresolved COPY subtree?
    sub_unresolved = in_unresolved
    if node.src.get("redefines") is None and _is_unresolved_copy_marker(node):
        sub_unresolved = True

    if node.is_group:
        # Group: size = sum of children (per declared order), honouring REDEFINES
        # (non-additive). Children inherit this group's effective usage.
        _size_group(node, ctx, eff_usage, node_sync, in_odo_tail, sub_unresolved)
    else:
        _size_elementary(node, ctx, node_sync, in_odo_tail, sub_unresolved)

    # OCCURS multiply (applies to the node's own length AFTER it is sized).
    lo, hi, is_odo = _occurs_factor(node)
    if is_odo:
        # True variable length. The ODO field has a KNOWN start offset, but its
        # LENGTH is variable, so it reports a ranged length (min!=max) and its
        # single authoritative length is refused. Fields AFTER it inherit an
        # unknown offset (handled by the group layout's offset_known cascade).
        node.variable_length = True
        node.length_min = node.length_min * max(lo, 0)
        node.length_max = node.length_max * max(hi, 1)
        node.length = node.length_max  # MAX is used to size the parent group max
        ctx.add_gap(
            GAP_ODO, _field_line(node),
            f"{node.name}: OCCURS DEPENDING ON {node.src.get('occurs_depending_on')!r} "
            f"— variable length; refusing a single authoritative post-ODO offset.",
        )
        node.offset_confidence = _min_conf(node.offset_confidence, "speculative")
    elif lo != 1 or hi != 1:
        # Fixed OCCURS multiply.
        node.length = node.length * lo
        node.length_min = node.length_min * lo
        node.length_max = node.length_max * hi

    # SYNCHRONIZED: we computed WITHOUT slack, but MUST NOT present a confident
    # single offset. The slack can push this field (and everything after it)
    # forward, so its absolute offset is UNKNOWN (offset_known=False), not merely
    # ranged-by-a-fixed-amount. Speculative + gap (Codex Finding 1).
    if node_sync:
        node.offset_known = False
        node.offset_confidence = _min_conf(node.offset_confidence, "speculative")
        ctx.add_gap(
            GAP_SYNC, _field_line(node),
            f"{node.name}: SYNCHRONIZED — alignment slack is compiler-dependent; "
            f"offsets are RANGED/UNKNOWN, not a confident without-slack value.",
        )

    if sub_unresolved:
        node.offset_confidence = _min_conf(node.offset_confidence, "speculative")


def _is_unresolved_copy_marker(node: Node) -> bool:
    """A COPY that WP-6 could not splice may arrive as a placeholder field. We do
    not invent COPY handling here (cross-file is WP-6's job); we only react if the
    finding explicitly marks the subtree unresolved via a gap-ish flag."""
    return bool(node.src.get("unresolved_copy"))


def _size_elementary(node: Node, ctx: _Ctx, node_sync: bool,
                     in_odo_tail: bool, in_unresolved: bool) -> None:
    pic_info = parse_pic(node.src.get("pic_clause"))
    length, basis = elementary_length(
        pic_info, node.eff_usage, pointer_size=ctx.pointer_size
    )
    node.basis = basis

    if node.src.get("sign_separate") and pic_info is not None and pic_info.has_sign:
        length += 1  # SIGN ... SEPARATE adds one display byte for the sign.

    node.length = length
    node.length_min = length
    node.length_max = length

    # Offset confidence floor for an elementary item.
    if basis == "unsized":
        node.offset_confidence = "speculative"
        # An unsized field's length is unknown, so the cursor after it (and thus
        # every following sibling) is unknown — treat like SYNC slack.
        node.offset_known = False
        ctx.add_gap(
            "language_unsupported", _field_line(node),
            f"{node.name}: could not size PIC {node.src.get('pic_clause')!r} "
            f"USAGE {node.src.get('usage')!r}.",
        )
    elif basis == "pointer":
        # POINTER size is a model assumption (4 vs 8). Flag as inferred.
        node.offset_confidence = "inferred"
    elif node.usage_inherited:
        # USAGE came from the enclosing group, not the item -> inferred.
        node.offset_confidence = "inferred"
    else:
        node.offset_confidence = "grounded"


def _size_group(node: Node, ctx: _Ctx, eff_usage: Optional[str], node_sync: bool,
                in_odo_tail: bool, in_unresolved: bool) -> None:
    """Size a group: lay children out left-to-right honouring REDEFINES.

    REDEFINES is NON-ADDITIVE: a redefining child shares the offset of the field
    it redefines and does NOT advance the running cursor; if the redefining child
    is LARGER than the redefined field, the group is extended by the difference
    (the redefinition wins the larger footprint).
    """
    # Size every child first (recurse).
    child_odo_tail = in_odo_tail
    for ch in node.children:
        _compute_node(ch, ctx, eff_usage, node_sync, child_odo_tail, in_unresolved)
        # Once a variable child appears, everything after it is in the ODO tail.
        if ch.variable_length:
            child_odo_tail = True

    # Lay out children left-to-right. Track a running cursor (min/max separately
    # for ODO ranges) AND a ``cursor_known`` flag. The cursor stays KNOWN until a
    # child either is variable-length (ODO shifts everything after it) or has an
    # unknown absolute offset of its own (SYNC slack / unsized). Once the cursor
    # is unknown, every following sibling gets offset_known=False.
    cursor = 0
    cursor_min = 0
    cursor_max = 0
    cursor_known = True
    group_extent = 0
    group_extent_min = 0
    group_extent_max = 0
    any_ranged = False
    any_variable = False
    worst_conf = "grounded"

    # Map name -> the cursor position it was laid at, so a REDEFINES can reuse it.
    laid_offset: dict[str, int] = {}
    laid_offset_min: dict[str, int] = {}
    laid_offset_max: dict[str, int] = {}
    laid_len: dict[str, int] = {}
    laid_known: dict[str, bool] = {}

    for ch in node.children:
        redef = ch.src.get("redefines")
        if redef is not None and redef in laid_offset:
            base = laid_offset[redef]
            base_min = laid_offset_min[redef]
            base_max = laid_offset_max[redef]
            base_known = laid_known.get(redef, cursor_known)
            is_redef = True
        else:
            base = cursor
            base_min = cursor_min
            base_max = cursor_max
            base_known = cursor_known
            is_redef = False

        # This child's absolute-offset-known status: its base must be known AND
        # the child itself must not introduce its own offset uncertainty.
        # (A variable-length ODO child still has a KNOWN start, so offset_known
        # for the field itself is governed by base_known and its own
        # offset_known flag — NOT by its variable_length.)
        ch_known = base_known and ch.offset_known
        ch.offset_known = ch_known
        # Store group-relative position on the child for the absolute pass.
        ch.rel_offset = base
        ch.rel_offset_min = base_min
        ch.rel_offset_max = base_max

        laid_offset[ch.name] = base
        laid_offset_min[ch.name] = base_min
        laid_offset_max[ch.name] = base_max
        laid_len[ch.name] = ch.length
        laid_known[ch.name] = ch_known

        if is_redef:
            # Non-additive: do NOT advance the cursor. But extend the group if
            # this redefinition is larger than the field it redefines.
            group_extent = max(group_extent, base + ch.length)
            group_extent_min = max(group_extent_min, base_min + ch.length_min)
            group_extent_max = max(group_extent_max, base_max + ch.length_max)
            redefined_len = laid_len.get(redef, 0)
            if ch.length > redefined_len:
                cursor = max(cursor, base + ch.length)
                cursor_min = max(cursor_min, base_min + ch.length_min)
                cursor_max = max(cursor_max, base_max + ch.length_max)
        else:
            # Normal advance.
            cursor = base + ch.length
            cursor_min = base_min + ch.length_min
            cursor_max = base_max + ch.length_max
            group_extent = max(group_extent, cursor)
            group_extent_min = max(group_extent_min, cursor_min)
            group_extent_max = max(group_extent_max, cursor_max)

        # The cursor AFTER this child is unknown if it was already unknown, or
        # this child made it unknown (variable length, or its own offset unknown).
        if (not ch_known) or ch.variable_length:
            cursor_known = False

        any_ranged = any_ranged or ch.ranged or (not ch_known)
        any_variable = any_variable or ch.variable_length
        worst_conf = _min_conf(worst_conf, ch.offset_confidence)

    node.length = group_extent
    node.length_min = group_extent_min
    node.length_max = group_extent_max
    node.ranged = any_ranged
    node.variable_length = any_variable
    # A group's own offset_known is True only if every child's offset was known
    # AND the group itself has not been independently flagged unknown.
    node.offset_known = node.offset_known and cursor_known and not any_variable
    # A group's confidence is the worst of its children (USAGE inheritance can
    # only lower it).
    node.offset_confidence = _min_conf(node.offset_confidence or "grounded", worst_conf)


def _assign_offsets(node: Node, abs_base: int, abs_base_min: int, abs_base_max: int,
                    start_known: bool) -> None:
    """Second pass: shift the group-relative layout into ABSOLUTE offsets.

    ``abs_base`` is this node's absolute START offset (meaningful only when
    ``start_known``). ``start_known`` says whether this node BEGINS at a
    deterministic position — it depends on the parent base and on whether any
    EARLIER sibling introduced offset uncertainty, NOT on whether this node's own
    children contain a later ODO/SYNC.

    A node emits a concrete ``byte_offset`` iff its start is known AND it is not
    itself variable-length (an ODO item refuses a single authoritative offset for
    its variable tail). A group whose start is known but that CONTAINS a later
    ODO/SYNC still reports a known START offset; only the children laid AFTER the
    uncertain sibling get ``byte_offset=None``.
    """
    node.byte_offset_min = abs_base_min
    node.byte_offset_max = abs_base_max
    if start_known and not node.variable_length:
        node.byte_offset = abs_base
        # ranged stays as computed (a group may be ranged because a child is).
    else:
        node.byte_offset = None
        node.ranged = True

    if node.is_group:
        for ch in node.children:
            # Child absolute start = this group's absolute base + the child's
            # group-relative offset. The child STARTS at a known position iff this
            # group's start is known AND the child was laid before any uncertainty
            # in this group (captured by ch.offset_known in _size_group).
            child_abs = abs_base + ch.rel_offset
            child_abs_min = abs_base_min + ch.rel_offset_min
            child_abs_max = abs_base_max + ch.rel_offset_max
            child_start_known = start_known and ch.offset_known
            _assign_offsets(ch, child_abs, child_abs_min, child_abs_max,
                            child_start_known)


def _node_to_index_field(node: Node) -> dict:
    """Project a computed Node back into a structure-index.v1 ``fields[]`` item."""
    src = node.src
    out = {
        "name": node.name,
        "ordinal": int(src.get("ordinal", node.ordinal)),
        "level": src.get("level"),
        "parent": node.parent.name if node.parent is not None else None,
        "byte_offset": node.byte_offset,
        # length is None ONLY for true variable length (ODO) or an unsized field
        # (length 0 with basis 'unsized'). A SYNCHRONIZED field has a KNOWN length
        # (computed without slack) but an UNKNOWN offset — keep its length.
        "length": (None if node.variable_length else node.length),
        "byte_offset_min": node.byte_offset_min,
        "byte_offset_max": node.byte_offset_max,
        "ranged": bool(node.ranged),
        "variable_length": bool(node.variable_length),
        "pic_clause": src.get("pic_clause"),
        "usage": src.get("usage"),
        "declared_type": src.get("declared_type"),
        "normalized_type": src.get("normalized_type"),
        "nullable": src.get("nullable"),
        "occurs": src.get("occurs"),
        "occurs_max": src.get("occurs_max"),
        "occurs_depending_on": src.get("occurs_depending_on"),
        "redefines": src.get("redefines"),
        "renames": src.get("renames"),
        "is_group": bool(node.is_group) if node.children or src.get("is_group") else src.get("is_group"),
        "is_filler": src.get("is_filler"),
        "offset_confidence": node.offset_confidence,
        "confidence": src.get("confidence", node.offset_confidence),
        "evidence_kind": src.get("evidence_kind", "declared_column"),
        "enforcement": src.get("enforcement", "unknown"),
        "evidence": src.get("evidence"),
    }
    # length_min/length_max for variable items live implicitly in the byte_offset
    # range; the index schema models length as nullable for ranged fields.
    return out


def _zero_byte_field(src: dict, parent_name: Optional[str]) -> dict:
    """Project a 66/88 special item: present, zero bytes, no offset."""
    return {
        "name": str(src.get("name", "")),
        "ordinal": int(src.get("ordinal", 0)),
        "level": src.get("level"),
        "parent": parent_name,
        "byte_offset": None,
        "length": 0,
        "byte_offset_min": None,
        "byte_offset_max": None,
        "ranged": False,
        "variable_length": False,
        "pic_clause": src.get("pic_clause"),
        "usage": src.get("usage"),
        "declared_type": src.get("declared_type"),
        "normalized_type": src.get("normalized_type"),
        "nullable": src.get("nullable"),
        "occurs": src.get("occurs"),
        "occurs_max": src.get("occurs_max"),
        "occurs_depending_on": src.get("occurs_depending_on"),
        "redefines": src.get("redefines"),
        "renames": src.get("renames"),
        "is_group": False,
        "is_filler": src.get("is_filler"),
        "offset_confidence": "grounded",
        "confidence": src.get("confidence", "grounded"),
        "evidence_kind": src.get("evidence_kind", "declared_column"),
        "enforcement": src.get("enforcement", "unknown"),
        "evidence": src.get("evidence"),
    }


def compute_offsets(
    fields: list[dict],
    *,
    pointer_size: int = 4,
    copy_unresolved: bool = False,
) -> ComputeResult:
    """Compute byte offsets/lengths for a declared COBOL field list.

    ``fields`` is the ``fields[]`` array of a ``structure-finding.v1`` record
    (every ``byte_offset`` / ``length`` null). Returns a :class:`ComputeResult`
    whose ``fields`` are in ``structure-index.v1`` field shape.

    The first declared structural node (lowest-numbered level, typically the
    01-level) defines the record. Multiple top-level roots (e.g. several 77-level
    items) are each laid out from offset 0 independently is NOT COBOL-correct for
    a single record; in practice analyze-cobol emits ONE 01-record per finding,
    so we treat the first root as the record and lay any sibling roots after it.
    """
    if not isinstance(fields, list):
        raise TypeError("fields must be a list")

    ctx = _Ctx(pointer_size=pointer_size, copy_unresolved=copy_unresolved)
    roots = build_tree(fields)

    # Size every root (recursive); this fills lengths + group-relative offsets.
    for root in roots:
        _compute_node(root, ctx, inherited_usage=None,
                      in_sync=False, in_odo_tail=False,
                      in_unresolved=copy_unresolved)

    # Assign absolute offsets. Lay roots sequentially (record then trailing 77s).
    base = 0
    base_min = 0
    base_max = 0
    base_known = True
    record_variable = False   # true ODO variability
    record_ranged = False     # SYNC slack / unknown-offset uncertainty
    for root in roots:
        _assign_offsets(root, base, base_min, base_max, base_known)
        record_variable = record_variable or root.variable_length
        record_ranged = record_ranged or root.ranged or not root.offset_known
        # Advance the running cursor. min/max always accumulate; the single
        # `base` only stays meaningful while everything so far is known & fixed.
        base += root.length_max if (root.variable_length or not root.offset_known) else root.length
        base_min += root.length_min
        base_max += root.length_max
        if root.variable_length or not root.offset_known:
            base_known = False

    # Build the output field list in ORIGINAL declaration order (including 66/88).
    index_by_orig: dict[int, Node] = {}
    for root in roots:
        for n in _flatten(root):
            index_by_orig[n.index] = n

    out_fields: list[dict] = []
    root_name = roots[0].name if roots else None
    for idx, src in enumerate(fields):
        lvl = src.get("level")
        if lvl in _ZERO_BYTE_LEVELS:
            out_fields.append(_zero_byte_field(src, root_name))
            continue
        node = index_by_orig.get(idx)
        if node is None:
            # Should not happen, but never drop a declared field.
            out_fields.append(_zero_byte_field(src, root_name))
            continue
        out_fields.append(_node_to_index_field(node))

    # Record length rollup. A single authoritative record_length is emitted ONLY
    # when the record is neither ODO-variable NOR ranged (SYNC slack). In both
    # uncertain cases record_length is None and the min/max bracket the size.
    if not roots:
        rec_len: Optional[int] = 0
        rec_min: Optional[int] = 0
        rec_max: Optional[int] = 0
        variable = False
    else:
        variable = record_variable
        rec_min = base_min
        rec_max = base_max
        rec_len = None if (record_variable or record_ranged) else base

    # Most-conservative confidence across computed fields.
    worst = "grounded"
    for f in out_fields:
        worst = _min_conf(worst, f.get("offset_confidence", "grounded"))

    if copy_unresolved:
        ctx.add_gap(
            GAP_UNRESOLVED_COPY, 1,
            "record contains an unresolved COPY member — downstream offsets are "
            "speculative until the copybook is spliced (cross-file pass).",
        )

    return ComputeResult(
        fields=out_fields,
        record_length=rec_len,
        record_length_min=rec_min,
        record_length_max=rec_max,
        variable_length=variable,
        gaps=ctx.gaps,
        confidence=worst,
    )


def compute_finding_offsets(
    finding: dict,
    *,
    pointer_size: int = 4,
) -> ComputeResult:
    """Convenience wrapper: compute offsets from a whole ``structure-finding.v1``
    dict (reads ``finding['fields']``). Honours a finding-level unresolved-COPY
    gap by treating the record as COPY-unresolved.
    """
    fields = finding.get("fields", []) or []
    copy_unresolved = any(
        isinstance(g, dict) and g.get("kind") == GAP_UNRESOLVED_COPY
        for g in (finding.get("gaps", []) or [])
    )
    return compute_offsets(
        fields, pointer_size=pointer_size, copy_unresolved=copy_unresolved
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _result_to_entity(finding: dict, result: ComputeResult) -> dict:
    """Project a ComputeResult into a structure-index.v1 *entity* fragment."""
    return {
        "object_kind": finding.get("object_kind", "cobol_record"),
        "qualified_name": finding.get("qualified_name", ""),
        "record_length": result.record_length,
        "record_length_min": result.record_length_min,
        "record_length_max": result.record_length_max,
        "variable_length": result.variable_length,
        "fields": result.fields,
        "confidence": result.confidence,
        "evidence": finding.get("evidence", {"file_path": finding.get("file_path", ""), "line": 1}),
        "gaps": result.gaps,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("path", type=Path, help="Path to a structure-finding.v1 JSON file")
    parser.add_argument(
        "--pointer-size", type=int, choices=(4, 8), default=4,
        help="Assumed POINTER/INDEX storage size in bytes (default 4).",
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"ERROR: File not found: {args.path}", file=sys.stderr)
        return 1
    try:
        with args.path.open("r", encoding="utf-8") as fh:
            finding = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Failed to parse JSON: {exc}", file=sys.stderr)
        return 1
    except (PermissionError, OSError) as exc:
        print(f"ERROR: I/O error: {exc}", file=sys.stderr)
        return 1

    result = compute_finding_offsets(finding, pointer_size=args.pointer_size)
    entity = _result_to_entity(finding, result)
    print(json.dumps(entity, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
