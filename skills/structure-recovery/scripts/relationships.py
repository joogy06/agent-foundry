"""structure-recovery — cross-file relationship resolution + K2 confidence caps.

This is the WP-10 relationship pass that the per-file accumulator
(``accumulate_structure.py``) deferred (see its ``_collect_relationships``
docstring: "Cross-file FK resolution (and the K2 caps) is a LATER pass
(WP-10)"). It runs AFTER the per-file ``summary.json`` fragments are merged into
a cross-file catalog and BEFORE rendering, and produces the ``relationships[]``
array of ``structure-index.v1`` that ``render_structure.py`` consumes.

The K2 confidence/honesty caps (design §5, structure-index.v1 schema) — enforced
HERE, deterministically, defense-in-depth over whatever the LLM emitted:

  * SQL declared FK (``kind=fk``, ``evidence_kind=declared_constraint``)  -> grounded,
    enforcement=declared. The only relationship that ``render_structure._is_grounded
    _declared_fk`` will promote to a LIVE ``FOREIGN KEY`` constraint.
  * Convention ``*_id`` -> ``id`` (a NAME heuristic, no declared constraint)  ->
    ``kind=fk``, ``evidence_kind=inferred_naming``, confidence CAPPED at ``inferred``,
    enforcement=unknown. An advisory join hint, commented-DDL only.
  * SQL ``JOIN ... ON``  -> ``kind=join`` (NOT fk), confidence at ``inferred``,
    enforcement=unknown. Advisory.
  * DSX key flag  -> ``kind=pk``, grounded, enforcement=declared (a declared PK hint).
  * COBOL cross-record FK  -> emitted ONLY when ``infer_relationships`` is True
    (decision O2), CAPPED at ``speculative``, requires a name + normalized-type +
    byte-length match between the from-field and a candidate key field, and is
    advisory/commented-DDL only — NEVER a live constraint, NEVER above speculative.

Honesty invariants (design §5 / §6):
  * Relationship/FK edges are ADVISORY-ONLY and NEVER feed a gate — they are
    advisory until a ``gold/`` schema oracle clears an accuracy gate (the
    legacy-code-intel precedent). This module ships NO gate hook.
  * Interpolation / dynamic / unresolved markers force ``speculative`` (the
    bright-line classifier idiom reused from legacy-code-intel/lineage).
  * ``confidence`` only ever moves DOWN here (lower-confidence-wins, reusing the
    ``conf_rank`` ordering). This pass never promotes an edge above what its
    evidence_kind allows.

Pure stdlib, no LLM, deterministic (sorted output, byte-identical on re-run).
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Confidence ordering — REUSE the lineage/accumulate conf_rank lower-wins idiom
# verbatim (accumulate.py:256-264; accumulate_structure.py:_CONF_RANK).
# ---------------------------------------------------------------------------

_CONF_RANK = {"grounded": 3, "inferred": 2, "speculative": 1}
_RANK_CONF = {3: "grounded", 2: "inferred", 1: "speculative"}


def _min_conf(a: str, b: str) -> str:
    """Lower-confidence-wins (mirrors accumulate.py conf_rank lower-wins)."""
    return _RANK_CONF[min(_CONF_RANK.get(a, 1), _CONF_RANK.get(b, 1))]


def _cap_conf(conf: str, ceiling: str) -> str:
    """Clamp ``conf`` so it never exceeds ``ceiling`` (the K2 caps)."""
    return _RANK_CONF[min(_CONF_RANK.get(conf, 1), _CONF_RANK.get(ceiling, 1))]


# ---------------------------------------------------------------------------
# Bright-line dynamic/interpolation markers — force speculative (defense in
# depth, reused from legacy-code-intel confidence-classifier _looks_dynamic).
# ---------------------------------------------------------------------------

_DYNAMIC_MARKERS = (
    "${",           # shell interpolation
    "$(",           # command substitution
    "%s", "%d",     # printf-style
    ".format(",     # python str.format
    "f'", 'f"',     # python f-strings
    "RCP",          # DSX runtime column propagation
)

# DSX parameter interpolation is ANY ``#NAME#`` token (``#PARAM#``, ``#SRC_TABLE#``,
# …), not a single literal — match the interpolation SHAPE, not one name.
_DSX_PARAM_RE = re.compile(r"#[A-Za-z0-9_.]+#")


def _looks_dynamic(*texts: Optional[str]) -> bool:
    for t in texts:
        if not t:
            continue
        up = str(t)
        for m in _DYNAMIC_MARKERS:
            if m in up:
                return True
        if _DSX_PARAM_RE.search(up):
            return True
    return False


# ---------------------------------------------------------------------------
# Convention FK detection (the *_id -> id naming heuristic).
# ---------------------------------------------------------------------------

# A column like ``customer_id`` / ``customerId`` / ``CUSTOMER_ID`` suggests a
# reference to entity ``customer``'s key. Bright-line: the field name ends in an
# ``id`` token after stripping a separator. We do NOT treat a bare ``id`` itself
# as a convention FK (that's the *target* key, not a referencing column).
_ID_SUFFIX_RE = re.compile(r"^(?P<base>.+?)[ _]?(?:id|ID|Id)$")


def _convention_target_base(field_name: str) -> Optional[str]:
    """If ``field_name`` looks like ``<base>_id``, return ``<base>`` (lowercased,
    separators normalized). Return None when it is not a convention FK column
    (including a bare ``id``/``ID``)."""
    if not field_name:
        return None
    name = field_name.strip()
    low = name.lower()
    if low in ("id", "_id"):
        return None
    m = _ID_SUFFIX_RE.match(name)
    if not m:
        return None
    base = m.group("base").strip().strip("_")
    if not base:
        return None
    return _normalize_token(base)


def _normalize_token(s: str) -> str:
    """Lowercase + collapse separators for convention matching (snake/camel)."""
    # camelCase -> camel_case
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"[ \-]+", "_", s)
    return s.strip("_").lower()


def _entity_local_name(qualified_name: str) -> str:
    """The unqualified entity name (drop schema/library qualifiers)."""
    if not qualified_name:
        return ""
    # split on '.', the SQL/DSX qualifier separator
    tail = qualified_name.split(".")[-1]
    return _normalize_token(tail)


def _entity_name_variants(qualified_name: str) -> set:
    """Match variants for an entity: the local name, plus a naive singular
    (drop a trailing 's'). e.g. ``app.customers`` matches a ``customer_id``."""
    local = _entity_local_name(qualified_name)
    variants = {local}
    if local.endswith("s") and len(local) > 1:
        variants.add(local[:-1])
    return {v for v in variants if v}


# ---------------------------------------------------------------------------
# Field lookups (for the COBOL name+type+length match predicate).
# ---------------------------------------------------------------------------

def _iter_fields(entity: dict):
    for f in entity.get("fields", []) or []:
        if isinstance(f, dict):
            yield f


def _field_match_signature(field: dict) -> tuple:
    """The (name, normalized_type, byte-length) signature used for the COBOL
    cross-record FK match. A None length is part of the signature (so an
    unresolved/ranged length does NOT spuriously match a fixed one)."""
    return (
        _normalize_token(str(field.get("name", ""))),
        (field.get("normalized_type") or "").strip().lower() or None,
        field.get("length"),
    )


def _candidate_key_fields(entity: dict):
    """Fields of ``entity`` that could be the *target* of a cross-record FK:
    a real (non-group, non-filler) field. Group/filler nodes carry no value."""
    for f in _iter_fields(entity):
        if f.get("is_group") or f.get("is_filler"):
            continue
        yield f


# ---------------------------------------------------------------------------
# Per-relationship K2 normalization (the deterministic re-check).
# ---------------------------------------------------------------------------

def _entities_by_qn(entities: list) -> dict:
    out: dict = {}
    for e in entities or []:
        if isinstance(e, dict):
            out[str(e.get("qualified_name", ""))] = e
    return out


def _normalize_declared_relationship(rel: dict) -> dict:
    """Apply the K2 caps to a relationship that was DECLARED in a chunk
    (carried forward by accumulate's ``_collect_relationships``). Deterministic
    re-check, defense-in-depth over the LLM's emitted confidence.

    The relationship's evidence_kind decides its ceiling:
      * declared_constraint -> a real DDL constraint (FK/PK/UNIQUE) -> grounded,
        enforcement=declared.
      * inferred_naming     -> convention hint -> cap inferred, enforcement=unknown.
      * observed_usage      -> a JOIN / usage edge -> cap inferred, enforcement=unknown,
        and a JOIN stays kind=join (never silently promoted to fk).
      * anything dynamic in the evidence -> forced speculative.
    """
    out = dict(rel)
    kind = out.get("kind", "join")
    ek = out.get("evidence_kind", "observed_usage")
    conf = out.get("confidence", "inferred")

    # Bright-line dynamic markers force speculative regardless of evidence_kind.
    ev = out.get("evidence") or {}
    if _looks_dynamic(
        out.get("from_field"), out.get("to_field"), out.get("to_object"),
        ev.get("snippet") if isinstance(ev, dict) else None,
    ):
        out["confidence"] = "speculative"
        out["enforcement"] = "unknown"
        return out

    if ek == "declared_constraint":
        # A declared SQL FK/PK/UNIQUE (or DSX declared key) is GROUNDED by the
        # bright-line classifier — the constraint is literally declared in the
        # artifact. Deterministic re-check NORMALIZES it to grounded + declared
        # (defense-in-depth: the LLM cannot accidentally under-mark a real
        # declared constraint). The only thing that holds a declared constraint
        # below grounded is a dynamic marker, which already returned above.
        out["confidence"] = "grounded"
        out["enforcement"] = "declared"
    elif ek == "inferred_naming":
        out["kind"] = "fk" if kind == "fk" else kind
        out["confidence"] = _cap_conf(conf, "inferred")
        out["enforcement"] = "unknown"
    else:  # observed_usage (or unknown) — a JOIN/usage edge, advisory.
        if kind == "join":
            out["kind"] = "join"  # never promote a JOIN to fk
        out["confidence"] = _cap_conf(conf, "inferred")
        out["enforcement"] = "unknown"
    return out


def _rel_identity(rel: dict) -> tuple:
    return (
        rel.get("kind", ""),
        rel.get("from_object", ""),
        rel.get("from_field", ""),
        str(rel.get("to_object") or ""),
        str(rel.get("to_field") or ""),
    )


def _project_to_index_shape(rel: dict) -> dict:
    """Project to the exact structure-index.v1 relationships[] item shape
    (additionalProperties:false — only the declared keys)."""
    return {
        "kind": rel.get("kind", "join"),
        "from_object": rel.get("from_object", ""),
        "from_field": rel.get("from_field", ""),
        "to_object": rel.get("to_object"),
        "to_field": rel.get("to_field"),
        "evidence_kind": rel.get("evidence_kind", "observed_usage"),
        "enforcement": rel.get("enforcement", "unknown"),
        "confidence": rel.get("confidence", "speculative"),
    }


# ---------------------------------------------------------------------------
# Convention FK synthesis (the *_id -> id inferred join hints).
# ---------------------------------------------------------------------------

def _synthesize_convention_fks(entities: list, existing: set) -> list:
    """For every relational (table/view) entity, scan its columns for the
    ``<base>_id`` convention and emit an INFERRED join hint to the matching
    entity's ``id`` key, when a target entity is present in the catalog.

    Capped at ``inferred``, evidence_kind=inferred_naming, enforcement=unknown.
    Skipped when a declared relationship already covers the (from_object,
    from_field) pair (declared always wins over the convention guess)."""
    by_qn = _entities_by_qn(entities)
    # Build a base-name -> qualified_name index for relational entities only.
    name_index: dict = {}
    for qn, e in by_qn.items():
        if e.get("object_kind") not in ("table", "view"):
            continue
        for variant in _entity_name_variants(qn):
            name_index.setdefault(variant, []).append(qn)

    out: list = []
    declared_from = {(r[1], r[2]) for r in existing}  # (from_object, from_field)

    for qn in sorted(by_qn):
        e = by_qn[qn]
        if e.get("object_kind") not in ("table", "view"):
            continue
        for f in sorted(_iter_fields(e), key=lambda x: (int(x.get("ordinal", 0) or 0), str(x.get("name", "")))):
            fname = str(f.get("name", ""))
            base = _convention_target_base(fname)
            if not base:
                continue
            targets = name_index.get(base, [])
            # Do not self-reference, and require an unambiguous single target.
            targets = [t for t in targets if t != qn]
            if len(targets) != 1:
                continue
            target_qn = targets[0]
            if (qn, fname) in declared_from:
                continue  # a declared edge already owns this column
            # Find the target's key field (prefer a column literally named 'id').
            tkey = _target_key_field(by_qn[target_qn])
            if tkey is None:
                continue
            rel = {
                "kind": "fk",
                "from_object": qn,
                "from_field": fname,
                "to_object": target_qn,
                "to_field": tkey,
                "evidence_kind": "inferred_naming",
                "enforcement": "unknown",
                "confidence": "inferred",
            }
            ident = _rel_identity(rel)
            if ident in existing:
                continue
            existing.add(ident)
            out.append(rel)
    return out


def _target_key_field(entity: dict) -> Optional[str]:
    """The likely key column of a target entity: a column named exactly ``id``
    (case-insensitive), else None (we do not guess composite/other keys)."""
    for f in _iter_fields(entity):
        if _normalize_token(str(f.get("name", ""))) == "id":
            return f.get("name", "")
    return None


# ---------------------------------------------------------------------------
# COBOL cross-record FK inference (decision O2 — gated, capped, matched).
# ---------------------------------------------------------------------------

def _infer_cobol_cross_record_fks(entities: list, existing: set) -> list:
    """COBOL cross-record FK inference. ONLY runs when the caller passes
    ``infer_relationships=True`` (decision O2). Every emitted edge:

      * is ``kind=fk``, evidence_kind=inferred_naming, enforcement=unknown,
        confidence CAPPED at ``speculative`` (never higher),
      * requires a name + normalized-type + byte-length match between the
        from-field and the target record's candidate key field,
      * is advisory only — it surfaces as a commented ``-- INFERRED FK:`` DDL line
        and NEVER as a live constraint (render_structure renders COBOL records as
        non-relational commented manifests, so it physically cannot become live).
    """
    by_qn = _entities_by_qn(entities)
    cobol = {qn: e for qn, e in by_qn.items() if e.get("object_kind") == "cobol_record"}
    if len(cobol) < 2:
        return []

    out: list = []
    for src_qn in sorted(cobol):
        src = cobol[src_qn]
        for f in sorted(_candidate_key_fields(src),
                        key=lambda x: (int(x.get("ordinal", 0) or 0), str(x.get("name", "")))):
            # The referencing field must look like a key reference (``*-ID`` /
            # ``*_ID``); a bare ``ID`` is the target key, not a referencing column.
            if _convention_target_base(str(f.get("name", ""))) is None:
                continue
            src_sig = _field_match_signature(f)
            # A ranged/unresolved length can't satisfy the length-match rule
            # (an ODO/SYNC-affected field is never a confident cross-record FK).
            if src_sig[2] is None:
                continue
            for tgt_qn in sorted(cobol):
                if tgt_qn == src_qn:
                    continue
                tkey = _matching_cobol_key(cobol[tgt_qn], src_sig)
                if tkey is None:
                    continue
                rel = {
                    "kind": "fk",
                    "from_object": src_qn,
                    "from_field": f.get("name", ""),
                    "to_object": tgt_qn,
                    "to_field": tkey,
                    "evidence_kind": "inferred_naming",
                    "enforcement": "unknown",
                    "confidence": "speculative",  # HARD cap — decision O2 / design §8
                }
                ident = _rel_identity(rel)
                if ident in existing:
                    continue
                existing.add(ident)
                out.append(rel)
    return out


def _matching_cobol_key(target_entity: dict, src_sig: tuple) -> Optional[str]:
    """Return the target record's field name that satisfies the K2 cross-record
    match: SAME normalized name AND SAME normalized type AND SAME byte length as
    the referencing field (``src_sig``). All three must match exactly — a name
    match alone, a type mismatch, or a length mismatch all fail the predicate.

    Matching on the SAME normalized name (e.g. ``CUST-ID`` in ORDER-REC against a
    ``CUST-ID`` key in CUSTOMER-REC) keeps this bright-line and conservative: we
    only infer a cross-record FK when the referencing column and the target key
    are the same declared key (name + type + width), never a coincidental
    same-width field of an unrelated name."""
    src_name, src_type, src_len = src_sig
    for f in _candidate_key_fields(target_entity):
        sig = _field_match_signature(f)
        if sig[0] != src_name:      # name must match
            continue
        if sig[1] != src_type:      # normalized type must match
            continue
        if sig[2] != src_len:       # byte length must match
            continue
        return f.get("name", "")
    return None


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------

def resolve_relationships(catalog: dict, infer_relationships: bool = False) -> list:
    """Resolve + K2-cap the relationships for a cross-file ``structure-index.v1``
    catalog. Returns the ``relationships[]`` array (sorted, deduped, projected to
    the schema item shape).

    Inputs:
      * ``catalog`` — a structure-index.v1-shaped dict with ``entities`` and the
        chunk-declared ``relationships`` carried forward by accumulate.
      * ``infer_relationships`` — decision O2. When False, NO COBOL cross-record
        FKs are produced (DoD #5). When True, they are produced but capped at
        ``speculative`` with the name+type+length match enforced.

    Output ordering is deterministic; re-running on the same catalog yields a
    byte-identical array. This module is advisory-only and feeds NO gate.
    """
    entities = catalog.get("entities", []) or []
    declared = catalog.get("relationships", []) or []

    resolved: list = []
    seen: set = set()

    # 1. Carry forward + deterministically K2-re-check the declared edges.
    for rel in declared:
        if not isinstance(rel, dict):
            continue
        norm = _normalize_declared_relationship(rel)
        ident = _rel_identity(norm)
        if ident in seen:
            continue
        seen.add(ident)
        resolved.append(norm)

    # 2. Synthesize convention (*_id -> id) inferred join hints (relational only).
    resolved.extend(_synthesize_convention_fks(entities, seen))

    # 3. COBOL cross-record FKs — ONLY when infer_relationships (decision O2).
    if infer_relationships:
        resolved.extend(_infer_cobol_cross_record_fks(entities, seen))

    # 4. Project to the schema shape and sort deterministically.
    projected = [_project_to_index_shape(r) for r in resolved]
    return sorted(
        projected,
        key=lambda r: (
            r.get("kind", ""),
            r.get("from_object", ""),
            r.get("from_field", ""),
            str(r.get("to_object") or ""),
            str(r.get("to_field") or ""),
        ),
    )


__all__ = [
    "resolve_relationships",
    "_min_conf",
    "_cap_conf",
    "_looks_dynamic",
    "_convention_target_base",
    "_field_match_signature",
]
