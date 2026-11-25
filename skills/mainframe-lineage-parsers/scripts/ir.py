#!/usr/bin/env python3
"""ir.py — the ONE internal representation for ``mainframe-lineage-parsers``.

Part of the ``mainframe-lineage-parsers`` skill (the deterministic v1.1 plug-in
track under ``lineage-extract-static`` anti-pattern #7 — a *complement*, not a
replacement, of the LLM-as-parser family). This module is the single typed
intermediate representation that every extractor emits and the OpenLineage
emitter consumes (design §3 "strict IR" / §6):

    preprocess (WP-2) -> copybook_resolver (WP-3)
        -> {jcl_extract WP-5, cobol_extract WP-6, sql_extract WP-7}  (all emit IR)
            -> graph_assemble (WP-8)  (canonical sort + dedupe of IR)
                -> openlineage_emit (WP-9)  (IR -> OpenLineage 2.0.2 ndjson)

It is **pure stdlib** — NO LLM, NO ``sqlglot``/``networkx``, NO new pip deps, NO
network, NO shell, NO runtime pip install (design D1). The deterministic engine
has no LLM in the loop, ever (C2). The module is **pure data + validation**: it
builds nodes / edges / gap-nodes, enforces the forcing rules, and rejects
out-of-enum / floor-violating edges. It writes nothing.

The language here is model-neutral. The IR is identical regardless of which CLI
host invokes the engine (Claude Code, Codex CLI, Copilot CLI, Antigravity CLI).

------------------------------------------------------------------------------
The two INDEPENDENT facets (naming-contract §4 / design §6)
------------------------------------------------------------------------------
Every edge carries TWO independent facets that are NOT conflated:

  * ``kind``        — the STRUCTURAL edge type. Closed enum:
                        {direct, inferred, unresolved, interproc_unknown}
  * ``confidence``  — the EVIDENCE tier. Closed enum, BYTE-IDENTICAL to the
                        siblings (C3 parity):
                        {grounded, inferred, speculative}

``inferred`` is a member of BOTH enums but means different things: an
``inferred``-*kind* edge can still be ``grounded``-*confidence* (a structurally
indirect but well-evidenced edge), while an ``unresolved``-*kind* edge is ALWAYS
forced to ``speculative``-*confidence*. The ``confidence`` enum is imported from
``structure-recovery/scripts/validate_finding.py`` so it is byte-identical (and
the tests assert that import equality — C3 parity).

------------------------------------------------------------------------------
The forcing rules (kind -> minimum confidence; design §6)
------------------------------------------------------------------------------
The structural ``kind`` (and any symbolic/interpolated resolution) puts a FLOOR
on the honest ``confidence``:

  * kind == unresolved          -> confidence forced to ``speculative``
  * kind == interproc_unknown   -> confidence forced to ``speculative``
  * any symbolic/interpolated resolution (``symbolic=True``)
                                -> confidence forced to ``speculative``
  * kind == direct AND the edge is a literal-token edge (``literal=True``)
                                -> confidence is ``grounded`` (a direct literal
                                   edge is the highest-evidence case)
  * kind == inferred            -> confidence may be ``inferred`` or lower
                                   (``inferred`` or ``speculative``); it may NOT
                                   claim ``grounded``.

An edge that *claims* a confidence ABOVE the floor its kind permits is, by the
default policy, **coerced down** to the floor and a coercion note is recorded on
the edge (so nothing is silently dropped and the user can see it happened). The
strict policy (``on_violation="reject"``) raises instead. Both are tested.

A ``direct``-kind edge that is NOT a literal-token edge has no forced floor and
keeps its declared confidence (a direct edge can still be merely ``inferred`` if,
e.g., it was derived from a near-miss heuristic — the extractor declares that).

------------------------------------------------------------------------------
Gap nodes (the frozen v1 closed set; naming-contract §5)
------------------------------------------------------------------------------
A gap is a typed node emitted in PLACE of an edge that cannot be honestly
claimed (C3 — never an invented edge). The frozen v1 gap-type vocabulary is:

  * ``unresolved_copy``         — a COPY member not found on any --copybook-path
  * ``free_format_unsupported`` — free-format COBOL (v1 is fixed-only)
  * ``symbolic_dsn``            — a DSN still holding an unresolved &SYMBOL
  * ``catalog_less_column``     — a DB2 column not resolvable to a catalog column

The Control-M amendment (design §4, WP-1; a VERSIONED extension of the set) adds
four scheduler gap kinds, all ``speculative``:

  * ``unresolved_variable``     — a ``%%VAR`` unresolved after Variables subst.
  * ``unresolved_connection``   — a ConnectionProfile absent from the supplied map
  * ``runtime_path``            — a ``%%``-interpolated / runtime-assigned path
  * ``unresolved_event_dep``    — an eventsToWaitFor with no in-scope producer

Any new gap type is a contract change (a new row in naming-contract §5) BEFORE an
extractor may emit it. ``make_gap_node`` rejects an out-of-set gap type so the
contract stays closed.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ------------------------------------------------------------------------------
# Confidence enum — BYTE-IDENTICAL import from the structure-recovery sibling.
#
# We import the actual ``CONFIDENCE_ENUM`` object so there is exactly ONE source
# of truth (C3 parity). The test asserts ``ir.CONFIDENCE_ENUM is the imported
# value`` AND ``ir.CONFIDENCE_ENUM == {"grounded", "inferred", "speculative"}``.
# A local fallback constant exists ONLY so this module never hard-fails if the
# sibling tree is unavailable at import time; the fallback is value-identical and
# the loader prefers the imported one. (Mirrors the sibling _import_preprocess
# path-load idiom: register in sys.modules before exec so dataclass annotation
# resolution under ``from __future__ import annotations`` succeeds on 3.12.)
# ------------------------------------------------------------------------------

_FALLBACK_CONFIDENCE_ENUM = frozenset({"grounded", "inferred", "speculative"})


def _import_validate_finding():
    """Import structure-recovery/scripts/validate_finding.py by file path.

    Path-load (not a package import) keeps the IR runnable from any tree slice /
    CWD, matching the sibling convention. Returns the module, or ``None`` if the
    sibling tree is not present (the caller then uses the value-identical
    fallback enum).
    """
    name = "sr_validate_finding"
    if name in sys.modules:
        return sys.modules[name]
    here = Path(__file__).resolve().parent
    target = here.parent.parent / "structure-recovery" / "scripts" / "validate_finding.py"
    if not target.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, target)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _resolve_confidence_enum():
    mod = _import_validate_finding()
    if mod is not None and hasattr(mod, "CONFIDENCE_ENUM"):
        imported = mod.CONFIDENCE_ENUM
        # Guard against silent drift: the imported set MUST equal the frozen
        # vocabulary or we fail closed (a sibling change to the enum is a
        # contract change that must be coordinated, not silently absorbed).
        if set(imported) != set(_FALLBACK_CONFIDENCE_ENUM):
            raise ConfidenceEnumDriftError(
                "structure-recovery CONFIDENCE_ENUM "
                f"{sorted(imported)!r} != frozen mainframe-lineage-parsers "
                f"vocabulary {sorted(_FALLBACK_CONFIDENCE_ENUM)!r} — C3 parity "
                "broken; this is a coordinated contract change, not a silent one."
            )
        return imported
    return _FALLBACK_CONFIDENCE_ENUM


# ------------------------------------------------------------------------------
# The two independent closed enums.
# ------------------------------------------------------------------------------

class ConfidenceEnumDriftError(RuntimeError):
    """Raised if the imported sibling CONFIDENCE_ENUM drifts from the frozen set."""


# Evidence tier — byte-identical to structure-recovery validate_finding.py:66.
CONFIDENCE_ENUM = _resolve_confidence_enum()

# Structural edge type — this skill's own independent vocabulary (design §6).
KIND_ENUM = frozenset({"direct", "inferred", "unresolved", "interproc_unknown"})

# Confidence tier ranking (low -> high) for floor comparison / coercion.
_CONFIDENCE_RANK: Dict[str, int] = {
    "speculative": 0,
    "inferred": 1,
    "grounded": 2,
}

# The frozen v1 gap-type closed set (naming-contract §5). Each maps to the
# contract confidence the gap node carries (free_format is a pure diagnostic —
# it is a *source*-level gap, not an edge, so it carries no edge confidence;
# we still tag it ``speculative`` on the node for uniformity but it never gates).
GAP_UNRESOLVED_COPY = "unresolved_copy"
GAP_FREE_FORMAT_UNSUPPORTED = "free_format_unsupported"
GAP_SYMBOLIC_DSN = "symbolic_dsn"
GAP_CATALOG_LESS_COLUMN = "catalog_less_column"

# --- Control-M scheduler gap kinds (design §4, WP-1; a VERSIONED contract
# amendment to the previously frozen-closed set). Each carries the contract
# confidence ``speculative`` and a single raw_* evidence facet, mirroring
# ``gap_symbolic_dsn``. These GATE the Control-M extractor (WP-2): make_gap_node
# rejects an unknown gap type, so they MUST land here before controlm_extract.py
# may emit them. naming-contract.md §5 documents the four new rows. ---
GAP_UNRESOLVED_VARIABLE = "unresolved_variable"
GAP_UNRESOLVED_CONNECTION = "unresolved_connection"
GAP_RUNTIME_PATH = "runtime_path"
GAP_UNRESOLVED_EVENT_DEP = "unresolved_event_dep"

GAP_TYPE_ENUM = frozenset({
    GAP_UNRESOLVED_COPY,
    GAP_FREE_FORMAT_UNSUPPORTED,
    GAP_SYMBOLIC_DSN,
    GAP_CATALOG_LESS_COLUMN,
    # Control-M amendment (WP-1)
    GAP_UNRESOLVED_VARIABLE,
    GAP_UNRESOLVED_CONNECTION,
    GAP_RUNTIME_PATH,
    GAP_UNRESOLVED_EVENT_DEP,
})

# The kinds whose mere presence forces confidence down to speculative.
_FORCE_SPECULATIVE_KINDS = frozenset({"unresolved", "interproc_unknown"})


# ------------------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------------------
class IRValidationError(ValueError):
    """Raised for an out-of-enum kind/confidence, an out-of-set gap type, or a
    forcing-rule violation under the strict (``reject``) policy."""


# ------------------------------------------------------------------------------
# Provenance facet (carried on every edge)
# ------------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceSpan:
    """An original source location range (file + 1-indexed line range).

    Mirrors the preprocess.py / copybook_resolver.py ``(file, line)`` provenance
    shape so spans flow through the pipeline unchanged.
    """

    file: str
    start_line: int
    end_line: Optional[int] = None  # None == single-line span at start_line

    def as_tuple(self) -> Tuple[str, int, int]:
        return (self.file, self.start_line, self.end_line if self.end_line is not None else self.start_line)


@dataclass
class Provenance:
    """Per-edge provenance facets (design §6 / naming-contract §3-§6).

    Every edge carries this so a side-by-side diff vs the LLM tool is fully
    attributable and the user can audit WHY an edge was claimed.
    """

    parser: str = ""                       # which extractor: jcl|cobol|sql
    engine: str = ""                       # the SQL/parse engine: sqlglot|regex|stdlib
    rule_id: str = ""                       # the extractor rule that fired
    source_spans: List[SourceSpan] = field(default_factory=list)
    copybook_expansion_stack: List[str] = field(default_factory=list)  # COPY-site trail
    dialect: str = ""                      # cobol|jcl|db2-sql etc.
    unresolved_deps: List[str] = field(default_factory=list)  # e.g. an unresolved &SYMBOL / COPY member
    raw_tokens: Dict[str, str] = field(default_factory=dict)   # raw_dsn / raw_host_var / raw_copy_member ...
    notes: List[str] = field(default_factory=list)             # coercion notes etc. (never silent)

    def merge_from(self, other: "Provenance") -> None:
        """Merge another provenance into this one deterministically (used by the
        WP-8 assembler when two edges with the same canonical key collapse).

        Spans / stacks / deps / notes are unioned and SORTED so the merged
        result is byte-identical regardless of merge order. Scalar fields keep
        the first non-empty value (the assembler sees canonically-sorted edges,
        so "first" is deterministic)."""
        self.source_spans = _dedupe_sorted_spans(self.source_spans + other.source_spans)
        self.copybook_expansion_stack = _dedupe_sorted_str(
            self.copybook_expansion_stack + other.copybook_expansion_stack
        )
        self.unresolved_deps = _dedupe_sorted_str(self.unresolved_deps + other.unresolved_deps)
        self.notes = _dedupe_sorted_str(self.notes + other.notes)
        for k, v in other.raw_tokens.items():
            self.raw_tokens.setdefault(k, v)
        if not self.parser:
            self.parser = other.parser
        if not self.engine:
            self.engine = other.engine
        if not self.rule_id:
            self.rule_id = other.rule_id
        if not self.dialect:
            self.dialect = other.dialect


def _dedupe_sorted_spans(spans: List[SourceSpan]) -> List[SourceSpan]:
    seen = {s.as_tuple() for s in spans}
    return [SourceSpan(f, a, b if b != a else None) for (f, a, b) in sorted(seen)]


def _dedupe_sorted_str(items: List[str]) -> List[str]:
    return sorted({s for s in items if s})


# ------------------------------------------------------------------------------
# Node
# ------------------------------------------------------------------------------
@dataclass
class Node:
    """A lineage graph node — a dataset, a job, or a gap.

    ``node_id`` is derived ONLY from canonical fields (namespace + name) by the
    extractor / emitter per the naming-contract §6 determinism rules; raw values
    live in ``facets`` and are never folded into the id.
    """

    namespace: str
    name: str
    node_type: str = "dataset"             # dataset|job|gap
    facets: Dict[str, str] = field(default_factory=dict)

    @property
    def node_id(self) -> str:
        """Canonical, deterministic node id: ``<namespace>|<name>`` (the canonical
        endpoint key the edge key is built from). Case-folding is applied by the
        extractor BEFORE construction per naming-contract §6, so the id is stable."""
        return f"{self.namespace}|{self.name}"


# ------------------------------------------------------------------------------
# Edge
# ------------------------------------------------------------------------------
@dataclass
class Edge:
    """A typed lineage edge carrying the two independent facets + provenance.

    Construct edges via :func:`make_edge` so the forcing rules + enum checks are
    enforced. Direct construction is allowed for tests but is unvalidated.
    """

    source: Node
    target: Node
    kind: str                              # KIND_ENUM
    confidence: str                        # CONFIDENCE_ENUM
    provenance: Provenance = field(default_factory=Provenance)

    @property
    def canonical_key(self) -> Tuple[str, str, str]:
        """The canonical edge key (naming-contract §6 rule 4):
        ``(source_node_id, target_node_id, kind)``. Edges with the same key are
        duplicates that collapse (provenance merged); edges between the same
        nodes with a different ``kind`` are distinct edges."""
        return (self.source.node_id, self.target.node_id, self.kind)


# ------------------------------------------------------------------------------
# Gap node
# ------------------------------------------------------------------------------
@dataclass
class GapNode:
    """A typed gap node from the frozen v1 closed set (naming-contract §5).

    Emitted in PLACE of an edge that cannot be honestly claimed (C3). It keeps
    the raw evidence as a facet (``raw_copy_member`` / ``raw_dsn`` /
    ``raw_host_var`` / ...) so the user can see what was unresolved, and carries
    the contract confidence (``speculative``; ``free_format_unsupported`` is a
    pure source diagnostic but is tagged uniformly)."""

    gap_type: str                          # GAP_TYPE_ENUM
    confidence: str = "speculative"
    facets: Dict[str, str] = field(default_factory=dict)
    source_span: Optional[SourceSpan] = None


# ------------------------------------------------------------------------------
# Forcing-rule logic
# ------------------------------------------------------------------------------
def confidence_floor(kind: str, *, symbolic: bool = False, literal: bool = False) -> Optional[str]:
    """Return the FORCED confidence for a (kind, symbolic, literal) combination,
    or ``None`` when there is no forced floor (the edge keeps its declared
    confidence subject only to the ceiling check).

    Rules (design §6):
      * unresolved / interproc_unknown / symbolic  -> forced ``speculative``
      * direct AND literal                          -> forced ``grounded``
      * inferred                                    -> ceiling ``inferred`` (no
                                                       forced floor; enforced via
                                                       :func:`confidence_ceiling`)
      * direct (non-literal)                        -> no force, no ceiling
    """
    if symbolic:
        return "speculative"
    if kind in _FORCE_SPECULATIVE_KINDS:
        return "speculative"
    if kind == "direct" and literal:
        return "grounded"
    return None


def confidence_ceiling(kind: str) -> Optional[str]:
    """Return the MAXIMUM honest confidence a kind may claim, or ``None`` for no
    ceiling. An ``inferred``-kind edge may NOT claim ``grounded`` — its ceiling
    is ``inferred``. (A ``direct`` non-literal edge has no ceiling: it may be
    grounded if the extractor has the evidence, or inferred if it was a
    near-miss; the extractor declares which.)"""
    if kind == "inferred":
        return "inferred"
    return None


# ------------------------------------------------------------------------------
# Validating constructors
# ------------------------------------------------------------------------------
def make_edge(
    source: Node,
    target: Node,
    kind: str,
    confidence: str,
    *,
    symbolic: bool = False,
    literal: bool = False,
    provenance: Optional[Provenance] = None,
    on_violation: str = "coerce",
) -> Edge:
    """Build a validated :class:`Edge`, enforcing the enum checks and the forcing
    rules (design §6).

    Parameters
    ----------
    kind, confidence : str
        Must be members of :data:`KIND_ENUM` / :data:`CONFIDENCE_ENUM`
        respectively (else :class:`IRValidationError`, always — out-of-enum is
        never coerced).
    symbolic : bool
        True when the resolution involved a symbolic / interpolated value (forces
        ``speculative``).
    literal : bool
        True when the edge is a direct literal-token edge (a ``direct``+literal
        edge is forced ``grounded``).
    on_violation : {"coerce", "reject"}
        How to handle a declared confidence ABOVE the floor / ceiling the kind
        permits. ``coerce`` (default) lowers the confidence to the permitted
        value and records a note (nothing silently dropped). ``reject`` raises
        :class:`IRValidationError`.
    """
    if kind not in KIND_ENUM:
        raise IRValidationError(
            f"out-of-enum kind {kind!r}; must be one of {sorted(KIND_ENUM)!r}"
        )
    if confidence not in CONFIDENCE_ENUM:
        raise IRValidationError(
            f"out-of-enum confidence {confidence!r}; must be one of "
            f"{sorted(CONFIDENCE_ENUM)!r}"
        )
    if on_violation not in ("coerce", "reject"):
        raise IRValidationError(
            f"on_violation must be 'coerce' or 'reject', got {on_violation!r}"
        )

    prov = provenance if provenance is not None else Provenance()
    final_confidence = confidence

    # 1. Apply the forced floor (the kind/symbolic/literal mandates a value).
    forced = confidence_floor(kind, symbolic=symbolic, literal=literal)
    if forced is not None and forced != confidence:
        if on_violation == "reject":
            raise IRValidationError(
                f"kind={kind!r} (symbolic={symbolic}, literal={literal}) forces "
                f"confidence={forced!r} but edge declared {confidence!r}"
            )
        final_confidence = forced
        prov.notes.append(
            f"confidence coerced {confidence}->{forced} "
            f"(forced by kind={kind}, symbolic={symbolic}, literal={literal})"
        )

    # 2. Apply the ceiling (the kind caps the maximum claim, e.g. inferred).
    ceiling = confidence_ceiling(kind)
    if ceiling is not None and _CONFIDENCE_RANK[final_confidence] > _CONFIDENCE_RANK[ceiling]:
        if on_violation == "reject":
            raise IRValidationError(
                f"kind={kind!r} caps confidence at {ceiling!r} but edge declared "
                f"{final_confidence!r}"
            )
        prov.notes.append(
            f"confidence coerced {final_confidence}->{ceiling} "
            f"(capped by kind={kind})"
        )
        final_confidence = ceiling

    return Edge(
        source=source,
        target=target,
        kind=kind,
        confidence=final_confidence,
        provenance=prov,
    )


def validate_edge(edge: Edge, *, on_violation: str = "reject", symbolic: bool = False, literal: bool = False) -> Edge:
    """Validate an already-constructed :class:`Edge` against the enums + forcing
    rules. Returns the (possibly coerced) edge, or raises under ``reject``.

    Use this to re-check an edge built by direct construction (e.g. in a test or
    a downstream merge). ``symbolic`` / ``literal`` carry the same semantics as
    :func:`make_edge`; they default to ``False`` (the common case for a
    re-validation pass where the structural facts already live in ``kind``)."""
    return make_edge(
        edge.source,
        edge.target,
        edge.kind,
        edge.confidence,
        symbolic=symbolic,
        literal=literal,
        provenance=edge.provenance,
        on_violation=on_violation,
    )


def make_gap_node(
    gap_type: str,
    *,
    facets: Optional[Dict[str, str]] = None,
    source_span: Optional[SourceSpan] = None,
    confidence: str = "speculative",
) -> GapNode:
    """Build a validated :class:`GapNode` from the frozen v1 closed set.

    Rejects an out-of-set gap type (keeps the contract closed — a new gap type is
    a naming-contract §5 change first). ``confidence`` defaults to the contract
    value ``speculative``; an out-of-enum confidence is rejected."""
    if gap_type not in GAP_TYPE_ENUM:
        raise IRValidationError(
            f"out-of-set gap_type {gap_type!r}; the frozen v1 closed set is "
            f"{sorted(GAP_TYPE_ENUM)!r} (a new gap type is a naming-contract §5 "
            "change before an extractor may emit it)"
        )
    if confidence not in CONFIDENCE_ENUM:
        raise IRValidationError(
            f"out-of-enum confidence {confidence!r} on gap node; must be one of "
            f"{sorted(CONFIDENCE_ENUM)!r}"
        )
    return GapNode(
        gap_type=gap_type,
        confidence=confidence,
        facets=dict(facets or {}),
        source_span=source_span,
    )


# --- Convenience gap constructors (the frozen v1 set; raw evidence as facets) ---
def gap_unresolved_copy(member: str, *, source_span: Optional[SourceSpan] = None) -> GapNode:
    """An unresolved COPY member -> ``unresolved_copy`` gap (raw_copy_member facet)."""
    return make_gap_node(
        GAP_UNRESOLVED_COPY,
        facets={"raw_copy_member": member},
        source_span=source_span,
    )


def gap_free_format_unsupported(*, source_span: Optional[SourceSpan] = None) -> GapNode:
    """Free-format COBOL source -> ``free_format_unsupported`` diagnostic gap."""
    return make_gap_node(GAP_FREE_FORMAT_UNSUPPORTED, source_span=source_span)


def gap_symbolic_dsn(raw_dsn: str, *, source_span: Optional[SourceSpan] = None) -> GapNode:
    """An unresolved-&SYMBOL DSN -> ``symbolic_dsn`` gap (raw_dsn facet)."""
    return make_gap_node(
        GAP_SYMBOLIC_DSN,
        facets={"raw_dsn": raw_dsn},
        source_span=source_span,
    )


def gap_catalog_less_column(host_var: str, *, source_span: Optional[SourceSpan] = None) -> GapNode:
    """A catalog-less DB2 column -> ``catalog_less_column`` gap (raw_host_var facet)."""
    return make_gap_node(
        GAP_CATALOG_LESS_COLUMN,
        facets={"raw_host_var": host_var},
        source_span=source_span,
    )


# --- Control-M scheduler gap constructors (WP-1; mirror gap_symbolic_dsn) ------
def gap_unresolved_variable(raw_variable: str, *, source_span: Optional[SourceSpan] = None) -> GapNode:
    """A ``%%VAR`` still unresolved after ``Variables`` substitution ->
    ``unresolved_variable`` gap (raw_variable facet). Forced ``speculative``."""
    return make_gap_node(
        GAP_UNRESOLVED_VARIABLE,
        facets={"raw_variable": raw_variable},
        source_span=source_span,
    )


def gap_unresolved_connection(raw_connection_profile: str, *, source_span: Optional[SourceSpan] = None) -> GapNode:
    """A ``ConnectionProfile`` absent from the supplied profiles map ->
    ``unresolved_connection`` gap (raw_connection_profile facet)."""
    return make_gap_node(
        GAP_UNRESOLVED_CONNECTION,
        facets={"raw_connection_profile": raw_connection_profile},
        source_span=source_span,
    )


def gap_runtime_path(raw_path: str, *, source_span: Optional[SourceSpan] = None) -> GapNode:
    """A ``FileName``/``Src``/``Dest`` that is ``%%``-interpolated or
    ``AssignFileNameToVariable`` runtime-bound -> ``runtime_path`` gap (raw_path
    facet). The path is only known at run time -> forced ``speculative``."""
    return make_gap_node(
        GAP_RUNTIME_PATH,
        facets={"raw_path": raw_path},
        source_span=source_span,
    )


def gap_unresolved_event_dep(raw_event: str, *, source_span: Optional[SourceSpan] = None) -> GapNode:
    """An ``eventsToWaitFor`` with no in-scope ``eventsToAdd`` producer ->
    ``unresolved_event_dep`` gap (raw_event facet)."""
    return make_gap_node(
        GAP_UNRESOLVED_EVENT_DEP,
        facets={"raw_event": raw_event},
        source_span=source_span,
    )


# ------------------------------------------------------------------------------
# contentSha256 stamping (WP-4d / WP-9 join key — INV-6)
# ------------------------------------------------------------------------------
def content_sha256_of_bytes(raw: bytes) -> str:
    """sha256 hex digest of RAW on-disk source bytes (INV-6: PRE-copybook-
    expansion / pre-symbol-substitution, NO encoding normalization). The byte
    definition is IDENTICAL across both engines so the v1.1 JOB<->artifact join
    never silently breaks."""
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def stamp_content_sha256(ir_obj: "IR", content_sha256: str, *, source_file: str = "") -> None:
    """Stamp ``content_sha256`` onto every JOB node in ``ir_obj`` so the emitter
    can surface the sourceCodeLocation.contentSha256 JOB facet (WP-4d). Also
    records it on each job edge's provenance raw_tokens (the emitter reads either
    location). Idempotent + deterministic."""
    if not content_sha256:
        return
    for n in ir_obj.nodes:
        if n.node_type == "job":
            n.facets.setdefault("content_sha256", content_sha256)
            if source_file:
                n.facets.setdefault("source_file", source_file)
    for e in ir_obj.edges:
        for n in (e.source, e.target):
            if n.node_type == "job":
                n.facets.setdefault("content_sha256", content_sha256)
                if source_file:
                    n.facets.setdefault("source_file", source_file)
        e.provenance.raw_tokens.setdefault("content_sha256", content_sha256)


# ------------------------------------------------------------------------------
# Node convenience constructor
# ------------------------------------------------------------------------------
def make_node(namespace: str, name: str, *, node_type: str = "dataset",
              facets: Optional[Dict[str, str]] = None) -> Node:
    """Build a :class:`Node`. Canonical-folding (upper-casing per naming-contract
    §6) is the extractor's responsibility BEFORE this call, so the node_id is
    stable; this constructor does not silently mutate the supplied strings."""
    return Node(namespace=namespace, name=name, node_type=node_type, facets=dict(facets or {}))


# ------------------------------------------------------------------------------
# IR container (what an extractor returns; the assembler consumes a list of these)
# ------------------------------------------------------------------------------
@dataclass
class IR:
    """The bundle an extractor emits: typed edges + gap nodes (+ the nodes are
    reachable from the edges; standalone nodes can be carried in ``nodes``).

    The assembler (WP-8) canonical-sorts + dedupes ``edges`` by
    :attr:`Edge.canonical_key` and carries ``gaps`` through untouched."""

    edges: List[Edge] = field(default_factory=list)
    gaps: List[GapNode] = field(default_factory=list)
    nodes: List[Node] = field(default_factory=list)

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def add_gap(self, gap: GapNode) -> None:
        self.gaps.append(gap)

    def add_node(self, node: Node) -> None:
        self.nodes.append(node)


__all__ = [
    # enums
    "CONFIDENCE_ENUM",
    "KIND_ENUM",
    "GAP_TYPE_ENUM",
    # gap-type constants
    "GAP_UNRESOLVED_COPY",
    "GAP_FREE_FORMAT_UNSUPPORTED",
    "GAP_SYMBOLIC_DSN",
    "GAP_CATALOG_LESS_COLUMN",
    "GAP_UNRESOLVED_VARIABLE",
    "GAP_UNRESOLVED_CONNECTION",
    "GAP_RUNTIME_PATH",
    "GAP_UNRESOLVED_EVENT_DEP",
    # dataclasses
    "SourceSpan",
    "Provenance",
    "Node",
    "Edge",
    "GapNode",
    "IR",
    # forcing-rule helpers
    "confidence_floor",
    "confidence_ceiling",
    # contentSha256 (WP-4d / WP-9 join key)
    "content_sha256_of_bytes",
    "stamp_content_sha256",
    # constructors
    "make_node",
    "make_edge",
    "validate_edge",
    "make_gap_node",
    "gap_unresolved_copy",
    "gap_free_format_unsupported",
    "gap_symbolic_dsn",
    "gap_catalog_less_column",
    "gap_unresolved_variable",
    "gap_unresolved_connection",
    "gap_runtime_path",
    "gap_unresolved_event_dep",
    # exceptions
    "IRValidationError",
    "ConfidenceEnumDriftError",
]
