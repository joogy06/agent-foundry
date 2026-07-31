#!/usr/bin/env python3
"""graph_assemble.py — assemble all extractor IR into ONE lineage graph (WP-8).

Part of the ``mainframe-lineage-parsers`` skill (the deterministic v1.1 plug-in
track under ``lineage-extract-static`` anti-pattern #7 — a *complement*, not a
replacement, of the LLM-as-parser family). This module is the graph-assembly
stage of the deterministic pipeline (design §3):

    preprocess (WP-2) -> copybook_resolver (WP-3)
        -> {jcl_extract WP-5, cobol_extract WP-6, sql_extract WP-7}  (all emit IR)
            -> graph_assemble (WP-8)   <-- THIS MODULE
                -> openlineage_emit (WP-9)  (IR -> OpenLineage 2.0.2 ndjson)

It is **pure deterministic stdlib** + **OPTIONAL networkx** (import-if-present,
graceful stdlib fallback — design D1). It has NO LLM in the loop, ever (C2); NO
new mandatory pip dep; NO network; NO shell; NO runtime pip install. The module
is pure data transformation: it consumes a list of ``ir.IR`` slices and produces
ONE assembled ``ir.IR`` whose edges are canonical-sorted + deduped (provenance
merged) and whose gap nodes are carried through untouched.

The language here is model-neutral. The assembled graph is identical regardless
of which CLI host invokes the engine (Claude Code, Codex CLI, Copilot CLI,
Antigravity CLI).

------------------------------------------------------------------------------
Responsibilities (design §3 / WP-8 acceptance criteria)
------------------------------------------------------------------------------
(a) STITCH the precision-win join #1 across extractors. The JCL side (WP-5)
    emits, per DD-with-DSN, a ``DSN dataset -> job`` binding edge whose DSN node
    AND edge provenance carry the upper-cased ``ddname`` bind key. The COBOL side
    (WP-6) emits ``SELECT file ASSIGN TO ddname`` file nodes whose ``mainframe://
    FILE`` node carries the SAME upper-cased ``ddname``. This stage adds the
    bridging edge ``JCL-DSN-dataset -> COBOL-file-node`` for every ddname that
    appears on BOTH sides, so the physical-dataset-to-program-file lineage is
    connected end to end:

        JCL DSN -> DDNAME  ==  COBOL ASSIGN -> FILE -> READ/WRITE -> program

    The stitch edge is ``kind=inferred`` (a structurally indirect, cross-artifact
    join), ceiling ``inferred`` — NEVER ``grounded`` (it is a heuristic bind on a
    shared name across two separate source artifacts, not a single literal token).
    When EITHER side's ddname involved a symbolic/unresolved DSN the stitch is
    forced ``speculative`` (the JCL binding was itself speculative). The bind key
    is recorded on the stitch edge provenance (``rule_id=graph.stitch.ddname``,
    ``raw_tokens["ddname"]``). No ddname match -> no invented bridge (C3).

(b) CANONICAL node/edge sort + DEDUPE by the canonical edge key (the
    naming-contract §6 determinism rules, frozen by WP-1). Two edges with the same
    ``(source_node_id, target_node_id, kind)`` collapse into one whose provenance
    is the order-independent merge (``ir.Provenance.merge_from``). The final edge
    list is sorted by ``(canonical_key, confidence)`` so the assembled output is
    BYTE-IDENTICAL on re-run of the same input, in any input order.

(c) CARRY gap nodes through (``unresolved_copy`` / ``symbolic_dsn`` /
    ``catalog_less_column`` / ``free_format_unsupported``) without dropping them —
    deduped + sorted deterministically, never silently discarded (C3 honesty).

------------------------------------------------------------------------------
networkx (optional; design D1)
------------------------------------------------------------------------------
``networkx`` (verified present 3.6.1 at plan time) is used as a graph *container*
when importable: a ``networkx.MultiDiGraph`` is built so callers / diagnostics can
run graph algorithms (reachability, components) over the assembled lineage. It is
NOT required: when ``networkx`` is absent the assembler runs identically via a
pure-stdlib path and the canonical-sorted/deduped ``ir.IR`` is produced exactly
the same way. The assembled ``ir.IR`` (not the networkx object) is the contract
the WP-9 emitter consumes, so determinism never depends on networkx being present.
The test patches the import to ``None`` to prove the fallback path.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# ------------------------------------------------------------------------------
# Path-load the IR module (the sibling convention; keeps the assembler runnable
# from any tree slice / CWD, and resolves dataclass annotations under
# ``from __future__ import annotations`` on Python 3.12 by registering in
# sys.modules BEFORE exec).
# ------------------------------------------------------------------------------
def _import_ir():
    name = "mlp_ir"
    if name in sys.modules:
        return sys.modules[name]
    here = Path(__file__).resolve().parent
    target = here / "ir.py"
    spec = importlib.util.spec_from_file_location(name, target)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load ir.py from {target}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ir = _import_ir()


# ------------------------------------------------------------------------------
# Optional networkx (import-if-present; design D1). Never required.
# ------------------------------------------------------------------------------
def _try_import_networkx():
    """Return the ``networkx`` module if importable, else ``None``.

    A separate helper so the test can monkeypatch it to return ``None`` and prove
    the stdlib fallback path produces the same canonical-sorted/deduped graph."""
    try:
        import networkx  # type: ignore
    except Exception:  # pragma: no cover - exercised via monkeypatch
        return None
    return networkx


# ------------------------------------------------------------------------------
# Result container
# ------------------------------------------------------------------------------
@dataclass
class AssembledGraph:
    """The output of :func:`assemble`.

    ``ir`` is the canonical-sorted + deduped assembled :class:`ir.IR` (the WP-9
    contract). ``stitched_ddnames`` is the sorted list of ddnames that produced a
    precision-win stitch bridge (diagnostic / audit). ``backend`` records whether
    the optional ``networkx`` container was built (``"networkx"``) or the
    stdlib fallback ran (``"stdlib"``) — determinism is identical either way.
    ``graph`` is the ``networkx.MultiDiGraph`` when the networkx backend ran, else
    ``None``."""

    ir: "object"                              # an ir.IR instance
    stitched_ddnames: List[str] = field(default_factory=list)
    backend: str = "stdlib"
    graph: "object" = None                    # networkx.MultiDiGraph | None


# ------------------------------------------------------------------------------
# Deterministic sort + dedupe of edges (the naming-contract §6 determinism rules)
# ------------------------------------------------------------------------------
def _confidence_rank(conf: str) -> int:
    """Low -> high ranking used only to pick a STABLE representative confidence
    when two same-canonical-key edges declare different confidences. The merged
    edge keeps the HIGHEST honest confidence among the duplicates (they share the
    same kind, so the kind's floor/ceiling already bound them); provenance is
    merged so no evidence is lost. Falls back to 0 for an unknown value (defensive
    — make_edge already enforces the enum upstream)."""
    return {"speculative": 0, "inferred": 1, "grounded": 2}.get(conf, 0)


def dedupe_and_sort_edges(edges: Sequence["ir.Edge"]) -> List["ir.Edge"]:
    """Collapse edges with the same canonical key and return them canonical-sorted.

    Determinism (byte-identical on re-run, input-order-independent):
      * group by ``Edge.canonical_key`` == ``(src_id, tgt_id, kind)``;
      * within a group, the representative carries the highest-confidence value
        (ties resolved by the canonical key, which is identical across the group);
      * all duplicates' provenance is merged via the order-independent
        ``ir.Provenance.merge_from`` (spans/stacks/deps/notes unioned + sorted);
      * the final list is sorted by ``(canonical_key, confidence_rank)``.

    The provenance merge is applied in a DETERMINISTIC order (duplicates pre-sorted
    by ``(confidence_rank, source-span tuples)``) so the merged provenance is
    byte-identical regardless of the order the extractors were passed in."""
    groups: Dict[Tuple[str, str, str], List["ir.Edge"]] = {}
    for e in edges:
        groups.setdefault(e.canonical_key, []).append(e)

    merged: List["ir.Edge"] = []
    for key in sorted(groups.keys()):
        members = groups[key]
        # Deterministic merge order: highest confidence first, then by the
        # stringified source spans so the order never depends on input order.
        members_sorted = sorted(
            members,
            key=lambda e: (
                -_confidence_rank(e.confidence),
                tuple(s.as_tuple() for s in e.provenance.source_spans),
                e.provenance.rule_id,
            ),
        )
        rep = members_sorted[0]
        # Pick the highest honest confidence among the duplicates as the
        # representative (kind is shared, so the floor/ceiling already hold).
        best_conf = max(members_sorted, key=lambda e: _confidence_rank(e.confidence)).confidence
        rep.confidence = best_conf
        for other in members_sorted[1:]:
            rep.provenance.merge_from(other.provenance)
        merged.append(rep)

    merged.sort(key=lambda e: (e.canonical_key, _confidence_rank(e.confidence)))
    return merged


def dedupe_and_sort_gaps(gaps: Sequence["ir.GapNode"]) -> List["ir.GapNode"]:
    """Carry gap nodes through, deduped + canonical-sorted (never dropped — C3).

    Two gap nodes are duplicates iff they share ``(gap_type, sorted-facets,
    source_span)``; the survivor is canonical. The result is sorted by
    ``(gap_type, facets, source_span)`` so it is byte-identical on re-run."""
    def _gap_key(g: "ir.GapNode") -> Tuple:
        facet_items = tuple(sorted(g.facets.items()))
        span = g.source_span.as_tuple() if g.source_span is not None else ("", -1, -1)
        return (g.gap_type, g.confidence, facet_items, span)

    seen: Dict[Tuple, "ir.GapNode"] = {}
    for g in gaps:
        seen.setdefault(_gap_key(g), g)
    return [seen[k] for k in sorted(seen.keys())]


def dedupe_and_sort_nodes(nodes: Sequence["ir.Node"]) -> List["ir.Node"]:
    """Dedupe standalone nodes by ``node_id`` and sort by ``(namespace, name)``.

    (Most nodes are reachable from edges; this only handles any standalone nodes
    an extractor explicitly carried in ``IR.nodes``.) Deterministic on re-run."""
    seen: Dict[str, "ir.Node"] = {}
    for n in nodes:
        seen.setdefault(n.node_id, n)
    return [seen[k] for k in sorted(seen.keys(), key=lambda nid: (seen[nid].namespace, seen[nid].name))]


# ------------------------------------------------------------------------------
# The precision-win stitch (join #1): JCL DSN -> DDNAME  ==  COBOL ASSIGN -> FILE
# ------------------------------------------------------------------------------
_JCL_DSN_NAMESPACE = "mainframe://DSN"
_COBOL_FILE_NAMESPACE = "mainframe://FILE"


def _index_ddname_sources(edges: Sequence["ir.Edge"]):
    """Index, by upper-cased ddname, the JCL DSN dataset nodes and the COBOL file
    nodes that carry that ddname, so the stitch can bridge matching pairs.

    Returns ``(jcl_by_dd, cobol_by_dd)`` where each maps ``ddname -> {node_id:
    (node, was_symbolic)}``. ``was_symbolic`` is True when the JCL DSN binding
    edge for that node was itself ``kind=unresolved`` (a symbolic/unresolved DSN),
    so the stitch is forced ``speculative``."""
    jcl_by_dd: Dict[str, Dict[str, Tuple["ir.Node", bool]]] = {}
    cobol_by_dd: Dict[str, Dict[str, Tuple["ir.Node", bool]]] = {}

    for e in edges:
        # JCL side: the DSN dataset node is the SOURCE of a DSN->job binding edge
        # and carries the ddname facet. Identify it by namespace + facet.
        for node in (e.source, e.target):
            dd = node.facets.get("ddname")
            if not dd:
                continue
            dd_u = dd.upper()
            if node.namespace == _JCL_DSN_NAMESPACE:
                was_symbolic = (e.kind == "unresolved")
                bucket = jcl_by_dd.setdefault(dd_u, {})
                existing = bucket.get(node.node_id)
                # Preserve a symbolic flag if ANY binding edge for this node was
                # symbolic (the binding is at best speculative).
                sym = was_symbolic or (existing[1] if existing else False)
                bucket[node.node_id] = (node, sym)
            elif node.namespace == _COBOL_FILE_NAMESPACE:
                bucket = cobol_by_dd.setdefault(dd_u, {})
                bucket.setdefault(node.node_id, (node, False))

    return jcl_by_dd, cobol_by_dd


def stitch_ddname_joins(
    edges: Sequence["ir.Edge"],
    *,
    on_violation: str = "coerce",
) -> Tuple[List["ir.Edge"], List[str]]:
    """Build the precision-win bridge edges (JCL DSN dataset -> COBOL file node)
    for every ddname present on BOTH sides. Returns ``(stitch_edges,
    stitched_ddnames)``.

    The bridge edge is ``kind=inferred`` (cross-artifact heuristic join on a
    shared name; ceiling ``inferred`` — NEVER grounded). When the JCL DSN binding
    was symbolic/unresolved the bridge is forced ``speculative``. No ddname match
    -> no edge (C3 — never an invented bridge). Deterministic: ddnames and node
    pairs are sorted before emission so the bridge set is byte-identical on
    re-run."""
    jcl_by_dd, cobol_by_dd = _index_ddname_sources(edges)
    shared = sorted(set(jcl_by_dd) & set(cobol_by_dd))

    stitch_edges: List["ir.Edge"] = []
    stitched: List[str] = []
    for dd in shared:
        jcl_nodes = jcl_by_dd[dd]
        cobol_nodes = cobol_by_dd[dd]
        made_any = False
        for jcl_id in sorted(jcl_nodes.keys()):
            jcl_node, was_symbolic = jcl_nodes[jcl_id]
            for cobol_id in sorted(cobol_nodes.keys()):
                cobol_node, _ = cobol_nodes[cobol_id]
                prov = ir.Provenance(
                    parser="graph",
                    engine="stdlib",
                    rule_id="graph.stitch.ddname",
                    dialect="jcl+cobol",
                    raw_tokens={"ddname": dd},
                    notes=[f"precision-win stitch on ddname {dd}"],
                )
                # The bridge connects the physical JCL DSN dataset to the COBOL
                # logical file. inferred-kind (cross-artifact join); symbolic JCL
                # binding -> forced speculative; otherwise inferred (the kind's
                # ceiling — never grounded).
                edge = ir.make_edge(
                    jcl_node,
                    cobol_node,
                    kind="inferred",
                    confidence="inferred",
                    symbolic=was_symbolic,
                    provenance=prov,
                    on_violation=on_violation,
                )
                stitch_edges.append(edge)
                made_any = True
        if made_any:
            stitched.append(dd)
    return stitch_edges, stitched


# ------------------------------------------------------------------------------
# Optional networkx container (built for callers/diagnostics; never the contract)
# ------------------------------------------------------------------------------
def _build_networkx_graph(nx, assembled: "ir.IR"):
    """Build a deterministic ``networkx.MultiDiGraph`` from the assembled IR.

    Nodes are added in canonical (sorted) order, edges in canonical-key order, so
    the graph construction order is deterministic. The graph is a convenience for
    reachability / component diagnostics; the assembled ``ir.IR`` remains the WP-9
    contract regardless of whether this ran."""
    g = nx.MultiDiGraph()
    # Add nodes first (sorted) so isolated nodes survive and order is stable.
    node_ids = set()
    for e in assembled.edges:
        for node in (e.source, e.target):
            if node.node_id not in node_ids:
                node_ids.add(node.node_id)
    for nid in sorted(node_ids):
        g.add_node(nid)
    for e in assembled.edges:
        g.add_edge(
            e.source.node_id,
            e.target.node_id,
            key=e.kind,
            confidence=e.confidence,
            rule_id=e.provenance.rule_id,
        )
    return g


# ------------------------------------------------------------------------------
# The public entry point
# ------------------------------------------------------------------------------
def _coerce_to_ir(slice_obj) -> "ir.IR":
    """Accept either an ``ir.IR`` or a wrapper carrying ``.ir`` (e.g. the WP-7
    ``SqlExtractResult``) and return the underlying ``ir.IR``."""
    if isinstance(slice_obj, ir.IR):
        return slice_obj
    inner = getattr(slice_obj, "ir", None)
    if isinstance(inner, ir.IR):
        return inner
    raise TypeError(
        f"assemble() expects ir.IR slices (or objects carrying an .ir IR), "
        f"got {type(slice_obj).__name__}"
    )


def assemble(
    slices: Sequence["object"],
    *,
    on_violation: str = "coerce",
    use_networkx: bool = True,
) -> AssembledGraph:
    """Assemble extractor IR slices into ONE canonical, deduped, stitched graph.

    Parameters
    ----------
    slices : sequence of ir.IR (or objects carrying an ``.ir`` IR — e.g. the WP-7
        ``SqlExtractResult``)
        The per-extractor IR slices (jcl_extract WP-5, cobol_extract WP-6,
        sql_extract WP-7), in ANY order — the output is order-independent.
    on_violation : {"coerce", "reject"}
        Forwarded to :func:`ir.make_edge` for the stitch bridge edges.
    use_networkx : bool
        When True (default) the optional ``networkx`` container is built if
        importable. Set False to force the stdlib path even when networkx is
        present (used by the determinism test to prove parity). Either way the
        assembled ``ir.IR`` is byte-identical.

    Returns
    -------
    AssembledGraph
        ``.ir`` is the assembled IR (the WP-9 contract): all extractor edges +
        the precision-win stitch bridges, canonical-sorted + deduped, with gap
        nodes carried through. ``.backend`` is ``"networkx"`` or ``"stdlib"``.
    """
    irs = [_coerce_to_ir(s) for s in slices]

    all_edges: List["ir.Edge"] = []
    all_gaps: List["ir.GapNode"] = []
    all_nodes: List["ir.Node"] = []
    for one in irs:
        all_edges.extend(one.edges)
        all_gaps.extend(one.gaps)
        all_nodes.extend(one.nodes)

    # (a) Stitch the precision-win join #1 BEFORE the global dedupe/sort, so a
    #     stitch edge that happens to duplicate another collapses too.
    stitch_edges, stitched = stitch_ddname_joins(all_edges, on_violation=on_violation)
    all_edges.extend(stitch_edges)

    # (b) Canonical sort + dedupe (byte-identical on re-run, order-independent).
    assembled = ir.IR()
    assembled.edges = dedupe_and_sort_edges(all_edges)
    # (c) Carry gaps through (deduped + sorted; never dropped).
    assembled.gaps = dedupe_and_sort_gaps(all_gaps)
    assembled.nodes = dedupe_and_sort_nodes(all_nodes)

    backend = "stdlib"
    graph = None
    if use_networkx:
        nx = _try_import_networkx()
        if nx is not None:
            graph = _build_networkx_graph(nx, assembled)
            backend = "networkx"

    return AssembledGraph(
        ir=assembled,
        stitched_ddnames=sorted(set(stitched)),
        backend=backend,
        graph=graph,
    )


__all__ = [
    "AssembledGraph",
    "assemble",
    "stitch_ddname_joins",
    "dedupe_and_sort_edges",
    "dedupe_and_sort_gaps",
    "dedupe_and_sort_nodes",
]


# ------------------------------------------------------------------------------
# CLI (diagnostic only — the real wiring is run_lineage.py WP-10). Deterministic,
# zero prompts, no network, no shell beyond python3.
# ------------------------------------------------------------------------------
def _main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - thin CLI
    import argparse

    parser = argparse.ArgumentParser(
        prog="graph_assemble.py",
        description="Diagnostic: report the networkx backend availability for the "
                    "mainframe-lineage-parsers graph assembler (the real pipeline "
                    "wiring is run_lineage.py).",
    )
    parser.add_argument(
        "--check-backend", action="store_true",
        help="Print whether the optional networkx backend is importable.",
    )
    args = parser.parse_args(argv)
    if args.check_backend:
        nx = _try_import_networkx()
        if nx is not None:
            print(f"networkx backend available: {getattr(nx, '__version__', 'unknown')}")
        else:
            print("networkx absent — stdlib fallback path active (determinism unchanged)")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
