# Anchor and Expand — Algorithm Spec

The `intent-extract` skill anchors on contract-map components and expands
to a **1-hop call neighbourhood**. This document specifies what that means
operationally.

## Why 1-hop only

Per design §13 HARD-RULE 7 (and per S023/S024 precedent established in
`integration-flow-testing`), auto-traversal of the call graph is an
anti-pattern. The LLM only ever needs the immediate neighbourhood of a
component to describe what it does — anything deeper than 1-hop is "what
some other component does", which is that other component's intent-extract
output.

This also keeps token budgets bounded. A typical 1-hop expansion in a
50k-LOC project is 50-200 edges, which fits comfortably in a 12k-input-token
prompt.

## What counts as "direct"

An edge `e` is **direct** for component `C` iff
`e.src_component == C OR e.dst_component == C`. That includes:

- Outgoing call edges (this component calls X)
- Incoming call edges (X calls this component)
- Import edges (this component imports X)
- Inherits/implements edges (this component extends/implements X)

The `edge_kind` field is preserved so the LLM can distinguish "calls"
from "imports" when interpreting the neighbourhood.

## What counts as "1-hop"

A symbol `(C', s')` is "1-hop adjacent" to `C` iff there exists a direct
edge from `C` that ends at `(C', s')`, OR a direct edge to `C` that
originates at `(C', s')`. Then an edge `e'` is **neighbour** iff it
touches `(C', s')` AND it is NOT itself a direct edge of `C`.

This means: we collect everything one call-step away from anything in `C`,
but we never go two steps deep.

## Budget cap

`max_neighbour_edges` defaults to **200**. Components with rich
neighbourhoods get truncated. The truncation is by edge order (first 200
in the static.jsonl scan, which is approximately insertion order from
the SCIP indexer — alphabetical by file). The LLM is informed of
truncation via `files_visible_count` and `static_edges_visible_count` in
the rendered prompt.

## Evidence edges contract

Every `entry_points[].evidence_edges`, `side_effects[].evidence_edges`,
and `error_paths[].evidence_edges` MUST cite a non-empty list of edge
ids that appear in the neighbourhood. The LLM is instructed never to
invent edge ids. If the LLM does emit a non-existent id, the two-arm
verification step downgrades the corresponding claim to `interpretive`
(or `degraded` if the second arm is also unavailable).

## File enumeration

After collecting direct + neighbour edges, the skill harvests:
- `callsite_refs[].path` from each edge
- `source_paths[]` from the contract-map component block (resolved via
  `anchor_expand.load_component_source_paths`)

The union is sorted, dedup'd, and capped at 30 files for the prompt
context. Sorting is by absolute path string (stable, deterministic).

## When the static.jsonl is missing

This is a degraded mode. The skill proceeds with empty edges. The LLM
still produces an intent description from `source_paths` alone, but
**every** prose claim is `degraded` because there are no edges to cite.
The downstream verdict.yaml lists this as a follow-up: "Intent extraction
ran without static wiring — re-run wiring-extract-static before relying
on grounded intent."

This degraded path exists because evo's CLONING phase may finish before
ANALYZED, depending on race conditions in heavy-IO sandbox setups.
