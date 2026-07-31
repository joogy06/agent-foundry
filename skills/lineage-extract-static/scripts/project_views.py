#!/usr/bin/env python3
"""project_views.py — deterministic L1/L2 view projection over the emitted graph.

Component: project-views (WP-7, lineage multi-view + Control-M cycle, 2026-06-23).

A DETERMINISTIC, stdlib-only, NO-LLM post-pass. It consumes the ALREADY-emitted
artifacts produced by ``merge_into_ol.py``:

  * ``openlineage.ndjson`` — the canonical JobEvent/DatasetEvent stream. Carries
    the typed bipartite graph (datasets with kind; jobs with inputs/outputs/kind)
    plus any ``columnLineage`` (facet 1-2-0) on output datasets. The OL events
    DROP per-edge confidence/evidence.
  * ``lineage_edges.csv`` — the denormalized edge table that DOES carry per-edge
    ``confidence`` + ``evidence_file`` + ``evidence_line`` (and the ``schedules`` /
    ``depends_on`` edges that never reach OL inputs/outputs).

It rebuilds the typed bipartite graph, REATTACHES per-edge confidence/evidence
from the CSV, and emits two honest abstraction views plus a single
``views.json`` render payload consumed by ``render_report.py`` (WP-8):

  * L1 — file interaction, JOB-RETAINED. Filter the graph to ``kind=file``
    datasets but KEEP the job node (dataset -> job -> dataset). It does NOT
    collapse jobs and does NOT emit any file->file cross-product edge. A
    fabricated file->file edge is a correctness failure (LOCKED user decision,
    design §6 / INV-5).
  * L2 — table/data. Filter to ``kind in {table, topic, queue}``, keep job
    nodes. Column lineage is read from the ``columnLineage`` 1-2-0 facet (when
    present) and nested under its parent table edge. Tolerant of an absent
    facet — table-level L2 still works.

INVARIANTS (design §10):
  * NO LLM calls, NO network, NO new mandatory dependency (stdlib only).
  * Pure graph algebra over the two emitted artifacts. NEVER imports
    intent-extract / legacy-code-intel. NEVER writes ``.ledger/`` or claim files.
  * Atomic writes + ``sort_keys`` + ``SOURCE_DATE_EPOCH`` => byte-identical
    re-runs.
  * L1 fabricates no edges (job-retained; zero file->file edges).

CLI usage:
    project_views.py --ndjson <openlineage.ndjson> --csv <lineage_edges.csv>
                     --output-dir <path> [--views l1,l2]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

# kinds that L2 retains (table/data view). file is L1-only.
L2_DATASET_KINDS = frozenset({"table", "topic", "queue"})
FILE_DATASET_KIND = "file"

# columnLineage facet pin (design §2 / §5a — live-verified current).
COLUMN_LINEAGE_FACET = "columnLineage"
COLUMN_LINEAGE_SCHEMA_URL = (
    "https://openlineage.io/spec/facets/1-2-0/ColumnLineageDatasetFacet.json"
)


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via .tmp.<pid> + os.replace + fsync.

    Mirrors merge_into_ol.atomic_write_text / render_report.atomic_write_text so
    every emitter in this skill shares one durable-write idiom.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".tmp.",
        suffix=f".{os.getpid()}",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


# ---------------------------------------------------------------------------
# Graph reconstruction from the two emitted artifacts.
# ---------------------------------------------------------------------------


def load_ndjson_events(ndjson_path: Path) -> list[dict]:
    """Read the OL ndjson stream. Blank lines tolerated. Returns event dicts."""
    events: list[dict] = []
    with ndjson_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def _dataset_kind(ds_obj: dict) -> str:
    """Read the datasetKind.kind facet off a DATASET_EVENT dataset object."""
    facets = ds_obj.get("facets", {}) or {}
    dk = facets.get("datasetKind", {}) or {}
    return dk.get("kind", FILE_DATASET_KIND)


def _job_kind(job_obj: dict) -> str:
    facets = job_obj.get("facets", {}) or {}
    jk = facets.get("jobKind", {}) or {}
    return jk.get("kind", "script")


def build_graph(events: list[dict]) -> dict:
    """Rebuild the typed bipartite graph from OL events.

    Returns:
        {
          "datasets": {(ns, name): {"namespace","name","kind"}},
          "jobs": {(ns, name): {"namespace","name","kind",
                                "inputs":[(ns,name)], "outputs":[(ns,name)]}},
          "column_lineage": {(out_ns, out_name): <columnLineage facet fields dict>},
        }

    The OL stream is authoritative for node TYPES (datasetKind / jobKind) and the
    job input/output topology. columnLineage is read off OUTPUT datasets that
    appear in a JobEvent's ``outputs`` (the L2 column source) AND off standalone
    DATASET_EVENTs, whichever carries it.
    """
    datasets: dict[tuple, dict] = {}
    jobs: dict[tuple, dict] = {}
    column_lineage: dict[tuple, dict] = {}

    def _record_column_lineage(ns: str, name: str, facets: dict) -> None:
        cl = (facets or {}).get(COLUMN_LINEAGE_FACET)
        if not isinstance(cl, dict):
            return
        fields = cl.get("fields")
        if isinstance(fields, dict) and fields:
            column_lineage[(ns, name)] = fields

    for evt in events:
        et = evt.get("eventType", "")
        if et == "DATASET_EVENT":
            ds = evt.get("dataset", {}) or {}
            key = (ds.get("namespace", ""), ds.get("name", ""))
            datasets[key] = {
                "namespace": key[0],
                "name": key[1],
                "kind": _dataset_kind(ds),
            }
            _record_column_lineage(key[0], key[1], ds.get("facets", {}))
        elif et == "JOB_EVENT":
            job = evt.get("job", {}) or {}
            j_key = (job.get("namespace", ""), job.get("name", ""))
            inputs = evt.get("inputs", []) or []
            outputs = evt.get("outputs", []) or []
            in_keys = [(d.get("namespace", ""), d.get("name", "")) for d in inputs]
            out_keys = [(d.get("namespace", ""), d.get("name", "")) for d in outputs]
            jobs[j_key] = {
                "namespace": j_key[0],
                "name": j_key[1],
                "kind": _job_kind(job),
                "inputs": in_keys,
                "outputs": out_keys,
            }
            # Datasets referenced inline in a JobEvent (no standalone DATASET_EVENT
            # may carry the kind facet) — register at default kind if unseen, and
            # harvest any inline columnLineage off the output datasetRef.
            for d in inputs:
                k = (d.get("namespace", ""), d.get("name", ""))
                datasets.setdefault(
                    k, {"namespace": k[0], "name": k[1], "kind": FILE_DATASET_KIND}
                )
            for d in outputs:
                k = (d.get("namespace", ""), d.get("name", ""))
                datasets.setdefault(
                    k, {"namespace": k[0], "name": k[1], "kind": FILE_DATASET_KIND}
                )
                _record_column_lineage(k[0], k[1], d.get("facets", {}))

    return {
        "datasets": datasets,
        "jobs": jobs,
        "column_lineage": column_lineage,
    }


def load_edges_csv(csv_path: Path) -> list[dict]:
    """Read lineage_edges.csv. Returns the per-edge rows with confidence/evidence.

    Each row keys back to a (dataset, job, edge_kind) triple plus the
    (confidence, evidence_file, evidence_line) provenance the OL events drop.
    """
    rows: list[dict] = []
    if not csv_path.exists():
        return rows
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def index_edge_provenance(csv_rows: list[dict]) -> dict:
    """Index CSV rows by (src_ns, src_name, job_ns, job_name, edge_kind).

    The value carries (confidence, evidence_file, evidence_line). The CSV is the
    sole carrier of per-edge confidence/evidence (OL drops it) AND of the
    schedules/depends_on edges that never reach OL inputs/outputs.
    """
    idx: dict[tuple, dict] = {}
    for r in csv_rows:
        key = (
            r.get("src_dataset_namespace", ""),
            r.get("src_dataset_name", ""),
            r.get("target_job_namespace", ""),
            r.get("target_job_name", ""),
            r.get("edge_kind", ""),
        )
        idx[key] = {
            "confidence": r.get("confidence", "") or "",
            "evidence_file": r.get("evidence_file", "") or "",
            "evidence_line": r.get("evidence_line", "") or "",
            "src_kind": r.get("src_kind", "") or "",
            "target_job_kind": r.get("target_job_kind", "") or "",
        }
    return idx


# ---------------------------------------------------------------------------
# View projection — pure graph algebra.
# ---------------------------------------------------------------------------


def _edge_provenance(
    prov_idx: dict,
    src_key: tuple,
    job_key: tuple,
    edge_kind: str,
) -> dict:
    """Look up (confidence, evidence_file, evidence_line) for a graph edge."""
    key = (src_key[0], src_key[1], job_key[0], job_key[1], edge_kind)
    p = prov_idx.get(key)
    if p is not None:
        return {
            "confidence": p["confidence"],
            "evidence_file": p["evidence_file"],
            "evidence_line": p["evidence_line"],
        }
    # OL-derived edge with no CSV row (defensive): no provenance recoverable.
    return {"confidence": "", "evidence_file": "", "evidence_line": ""}


def project_view(
    graph: dict,
    prov_idx: dict,
    retained_kinds: frozenset,
    include_columns: bool,
) -> dict:
    """Build a JOB-RETAINED view filtered to ``retained_kinds`` datasets.

    The view is a bipartite (dataset, job) element set. For every job, an edge is
    emitted dataset->job for each retained INPUT and job->dataset for each
    retained OUTPUT. The JOB NODE IS ALWAYS KEPT — there is no job collapse and
    therefore NO dataset->dataset (file->file or table->table) cross-product edge
    is ever fabricated (INV-5).

    Returns {"nodes":[...], "edges":[...]} where every edge has exactly one job
    endpoint and one dataset endpoint.
    """
    datasets = graph["datasets"]
    jobs = graph["jobs"]
    column_lineage = graph["column_lineage"]

    kept_dataset_keys: set = set()
    nodes: list[dict] = []
    edges: list[dict] = []

    # Stable iteration order for byte-identical output.
    for job_key in sorted(jobs.keys()):
        job = jobs[job_key]
        job_touches_retained = False

        for in_key in job["inputs"]:
            ds = datasets.get(in_key)
            if ds is None or ds["kind"] not in retained_kinds:
                continue
            job_touches_retained = True
            kept_dataset_keys.add(in_key)
            prov = _edge_provenance(prov_idx, in_key, job_key, "reads_from")
            edges.append({
                "from": {"kind": "dataset", "namespace": in_key[0], "name": in_key[1]},
                "to": {"kind": "job", "namespace": job_key[0], "name": job_key[1]},
                "edge_kind": "reads_from",
                "confidence": prov["confidence"],
                "evidence_file": prov["evidence_file"],
                "evidence_line": prov["evidence_line"],
            })

        for out_key in job["outputs"]:
            ds = datasets.get(out_key)
            if ds is None or ds["kind"] not in retained_kinds:
                continue
            job_touches_retained = True
            kept_dataset_keys.add(out_key)
            prov = _edge_provenance(prov_idx, out_key, job_key, "writes_to")
            edge = {
                "from": {"kind": "job", "namespace": job_key[0], "name": job_key[1]},
                "to": {"kind": "dataset", "namespace": out_key[0], "name": out_key[1]},
                "edge_kind": "writes_to",
                "confidence": prov["confidence"],
                "evidence_file": prov["evidence_file"],
                "evidence_line": prov["evidence_line"],
            }
            if include_columns:
                cols = _build_column_edges(column_lineage.get(out_key))
                if cols:
                    edge["columns"] = cols
            edges.append(edge)

        if job_touches_retained:
            nodes.append({
                "kind": "job",
                "namespace": job_key[0],
                "name": job_key[1],
                "job_kind": job["kind"],
            })

    # Dataset nodes for every retained dataset that an edge actually touched.
    for ds_key in sorted(kept_dataset_keys):
        ds = datasets[ds_key]
        nodes.append({
            "kind": "dataset",
            "namespace": ds["namespace"],
            "name": ds["name"],
            "dataset_kind": ds["kind"],
        })

    nodes.sort(key=lambda n: (n["kind"], n["namespace"], n["name"]))
    edges.sort(key=lambda e: (
        e["from"]["kind"], e["from"]["namespace"], e["from"]["name"],
        e["to"]["kind"], e["to"]["namespace"], e["to"]["name"],
        e["edge_kind"],
    ))
    return {"nodes": nodes, "edges": edges}


def _build_column_edges(fields: Optional[dict]) -> list[dict]:
    """Flatten a columnLineage 1-2-0 ``fields`` map into nested column edges.

    Shape per OL 1-2-0: fields{<out_col>:{inputFields:[{namespace,name,field,
    transformations:[...]}]}}. Returns a deterministically-sorted list of
    {output_field, input_namespace, input_name, input_field, transformations}.
    """
    if not isinstance(fields, dict) or not fields:
        return []
    out: list[dict] = []
    for out_col in sorted(fields.keys()):
        spec = fields[out_col] or {}
        for inf in spec.get("inputFields", []) or []:
            out.append({
                "output_field": out_col,
                "input_namespace": inf.get("namespace", ""),
                "input_name": inf.get("name", ""),
                "input_field": inf.get("field", ""),
                "transformations": inf.get("transformations", []) or [],
            })
    out.sort(key=lambda c: (
        c["output_field"], c["input_namespace"], c["input_name"], c["input_field"]
    ))
    return out


# ---------------------------------------------------------------------------
# Render-payload assembly + driver.
# ---------------------------------------------------------------------------


def _cy_node_id(prefix: str, namespace: str, name: str) -> str:
    """Stable cytoscape-safe element id. Mirrors render_report._safe_node_id but
    self-contained so this module has zero cross-script import."""
    raw = f"{namespace}:{name}"
    out = "".join(c if c.isalnum() else "_" for c in raw)
    if len(out) > 60:
        import hashlib
        out = out[:50] + "_" + hashlib.sha1(raw.encode()).hexdigest()[:8]
    return f"{prefix}_{out}"


def view_to_cytoscape(view: dict) -> list[dict]:
    """Translate a {nodes,edges} view into a Cytoscape elements array.

    Column lineage is carried as edge ``data.columns`` (consumed by the L2
    <details> expand panel in WP-8), never rendered as graph clutter.
    """
    elements: list[dict] = []
    for n in view["nodes"]:
        if n["kind"] == "dataset":
            nid = _cy_node_id("ds", n["namespace"], n["name"])
            elements.append({"data": {
                "id": nid, "label": n["name"], "kind": "dataset",
                "namespace": n["namespace"], "dataset_kind": n.get("dataset_kind", ""),
            }})
        else:
            nid = _cy_node_id("job", n["namespace"], n["name"])
            elements.append({"data": {
                "id": nid, "label": n["name"], "kind": "job",
                "namespace": n["namespace"], "job_kind": n.get("job_kind", ""),
            }})
    for i, e in enumerate(view["edges"]):
        if e["from"]["kind"] == "dataset":
            src = _cy_node_id("ds", e["from"]["namespace"], e["from"]["name"])
            tgt = _cy_node_id("job", e["to"]["namespace"], e["to"]["name"])
        else:
            src = _cy_node_id("job", e["from"]["namespace"], e["from"]["name"])
            tgt = _cy_node_id("ds", e["to"]["namespace"], e["to"]["name"])
        data = {
            "id": f"edge_{i}",
            "source": src,
            "target": tgt,
            "edge_kind": e["edge_kind"],
            "confidence": e.get("confidence", "") or "grounded",
            "evidence_file": e.get("evidence_file", ""),
            "evidence_line": e.get("evidence_line", ""),
        }
        if e.get("columns"):
            data["columns"] = e["columns"]
        elements.append({"data": data})
    return elements


def build_views(
    ndjson_path: Path,
    csv_path: Path,
    views: list[str],
) -> dict:
    """Build the requested views + the render payload. Pure function of inputs."""
    events = load_ndjson_events(ndjson_path)
    graph = build_graph(events)
    prov_idx = index_edge_provenance(load_edges_csv(csv_path))

    result_views: dict[str, dict] = {}
    cytoscape: dict[str, list] = {}

    if "l1" in views:
        l1 = project_view(graph, prov_idx, frozenset({FILE_DATASET_KIND}),
                          include_columns=False)
        result_views["l1"] = l1
        cytoscape["l1"] = view_to_cytoscape(l1)
    if "l2" in views:
        l2 = project_view(graph, prov_idx, L2_DATASET_KINDS, include_columns=True)
        result_views["l2"] = l2
        cytoscape["l2"] = view_to_cytoscape(l2)

    payload = {
        "schema_version": "1.0.0",
        "producer": "lineage-extract-static/project_views",
        "views": sorted(views),
        "view_meta": {
            "l1": {"label": "L1 — file interaction (job-retained)",
                   "retained_kinds": [FILE_DATASET_KIND]},
            "l2": {"label": "L2 — table / data",
                   "retained_kinds": sorted(L2_DATASET_KINDS)},
            "l3": {"label": "L3 — functional (deferred to v1.1)", "hidden": True},
        },
        "graph_views": result_views,
        "cytoscape": cytoscape,
    }
    return payload


def write_views(payload: dict, output_dir: Path) -> Path:
    """Atomically write views.json (sort_keys => byte-identical re-runs)."""
    out_path = output_dir / "views.json"
    atomic_write_text(
        out_path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return out_path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ndjson", type=Path, required=True,
                        help="Path to openlineage.ndjson")
    parser.add_argument("--csv", type=Path, required=True,
                        help="Path to lineage_edges.csv")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--views", default="l1,l2",
                        help="Comma-separated views to build (default: l1,l2)")
    args = parser.parse_args(argv)

    if not args.ndjson.exists():
        print(f"ERROR: ndjson not found: {args.ndjson}", file=sys.stderr)
        return 1

    requested = [v.strip() for v in args.views.split(",") if v.strip()]
    valid = {"l1", "l2"}
    unknown = [v for v in requested if v not in valid]
    if unknown:
        print(f"ERROR: unknown view(s): {','.join(unknown)} (valid: l1,l2)",
              file=sys.stderr)
        return 1
    if not requested:
        print("ERROR: no views requested", file=sys.stderr)
        return 1

    payload = build_views(args.ndjson, args.csv, requested)
    out_path = write_views(payload, args.output_dir)

    print(json.dumps({
        "views_path": str(out_path),
        "views": sorted(requested),
        "l1_edges": len(payload["graph_views"].get("l1", {}).get("edges", [])),
        "l2_edges": len(payload["graph_views"].get("l2", {}).get("edges", [])),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
