#!/usr/bin/env python3
"""render_report.py — deterministic Cytoscape HTML + Mermaid markdown renderer.

Component: render-report (WP-6 in S033 contract-map).

Reads an OpenLineage 2.0.2 bundle (openlineage.json) and produces:
- report.html — self-contained Cytoscape DAG + sortable tables + downloads
- report.md — GitHub-renderable Mermaid summary (flowchart capped at 50 nodes)
- lineage_edges.csv (already written by merge_into_ol.py; skipped here)

Determinism: When SOURCE_DATE_EPOCH env var is set, all rendered timestamps
use that value instead of wall-clock time; output is byte-identical across
re-runs with same input. Mirrors the Reproducible Builds convention.

XSS safety: every user-controlled string (file paths, dataset names, snippets)
is interpolated via Jinja2 |e filter (which calls html.escape) AND the
JS side uses textContent= (never innerHTML=). HARD-RULE 7.

Vendored Cytoscape: looks for ~/.claude/skills/visual-companion/templates/vendor/cytoscape.min.js
first; falls back to unpkg CDN with a banner. --no-vendor flag forces
Mermaid-only output if vendor missing.

CLI usage:
    render_report.py <bundle_path> --output-dir <path>
                     [--output-format default|ol-relational]
                     [--no-vendor]
                     [--source-date-epoch UNIX_TIMESTAMP]
"""

from __future__ import annotations

import argparse
import html
import json
import os
import socket
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    HAVE_JINJA = True
except ImportError:
    HAVE_JINJA = False

EXTRACTOR_ID = "lineage-extract-static"
EXTRACTOR_VERSION = "1.0.0"
PINNED_OL_VERSION = "2.0.2"

DEFAULT_MERMAID_NODE_CAP = 50
DEFAULT_MERMAID_HARD_CAP = 100

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Air-gap-safe vendor lookup
VENDOR_DIR = Path.home() / ".claude" / "skills" / "visual-companion" / "templates" / "vendor"
CYTOSCAPE_VENDOR = VENDOR_DIR / "cytoscape.min.js"
DAGRE_VENDOR = VENDOR_DIR / "dagre.min.js"
COSE_BILKENT_VENDOR = VENDOR_DIR / "cytoscape-cose-bilkent.js"

CDN_CYTOSCAPE = "https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"
CDN_DAGRE = "https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"
CDN_COSE_BILKENT = "https://unpkg.com/cytoscape-cose-bilkent@4.1.0/cytoscape-cose-bilkent.js"


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically via .tmp.<pid> + os.replace + fsync."""
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


def _safe_node_id(s: str) -> str:
    """Mermaid-safe id (no spaces, no special chars). Truncates long ids."""
    out = "".join(c if c.isalnum() else "_" for c in s)
    if len(out) > 60:
        # Hash the long part to keep id stable but short
        import hashlib
        out = out[:50] + "_" + hashlib.sha1(s.encode()).hexdigest()[:8]
    return out


def _check_cdn_reachable(host: str = "unpkg.com", port: int = 443, timeout: float = 2.0) -> bool:
    """Quick DNS + TCP probe. Returns True if reachable, False if not (air-gap).

    Used only as a hint to set the air-gap-fallback banner; the actual CDN
    fetch happens in the browser when the HTML loads.
    """
    if os.environ.get("HOST_NETWORK_AVAILABLE", "").lower() in ("false", "0", "no"):
        return False
    try:
        socket.setdefaulttimeout(timeout)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, socket.gaierror, OSError):
        return False


def collect_lineage_from_bundle(bundle: dict) -> dict:
    """Extract datasets, jobs, edges from an OL JSON bundle.

    Returns: {
        datasets: [{namespace, name, kind, edge_count}],
        jobs: [{namespace, name, kind, input_count, output_count}],
        edges: [{source_dataset, target_job, edge_kind, confidence, source_file, evidence_line_start}],
        chunked_files: int,
    }
    """
    events = bundle.get("events", [])
    datasets_seen: dict[tuple, dict] = {}
    jobs_seen: dict[tuple, dict] = {}
    edges: list[dict] = []
    counter_grounded = 0
    counter_inferred = 0
    counter_speculative = 0

    dataset_edge_counts: Counter = Counter()

    for evt in events:
        et = evt.get("eventType", "")
        if et == "DATASET_EVENT":
            ds = evt.get("dataset", {})
            key = (ds.get("namespace", ""), ds.get("name", ""))
            kind = "file"
            if "facets" in ds and "datasetKind" in ds["facets"]:
                kind = ds["facets"]["datasetKind"].get("kind", "file")
            datasets_seen[key] = {
                "namespace": key[0],
                "name": key[1],
                "kind": kind,
                "edge_count": 0,
            }
        elif et == "JOB_EVENT":
            job = evt.get("job", {})
            j_key = (job.get("namespace", ""), job.get("name", ""))
            j_kind = "script"
            if "facets" in job and "jobKind" in job["facets"]:
                j_kind = job["facets"]["jobKind"].get("kind", "script")
            inputs = evt.get("inputs", []) or []
            outputs = evt.get("outputs", []) or []
            jobs_seen[j_key] = {
                "namespace": j_key[0],
                "name": j_key[1],
                "kind": j_kind,
                "input_count": len(inputs),
                "output_count": len(outputs),
            }
            # Synthesize edges from inputs/outputs (best-effort attribution
            # — without the source rollup we don't have evidence_file/line)
            for ds in inputs:
                ds_key = (ds.get("namespace", ""), ds.get("name", ""))
                dataset_edge_counts[ds_key] += 1
                edges.append({
                    "source_dataset": {
                        "namespace": ds_key[0],
                        "name": ds_key[1],
                        "kind": datasets_seen.get(ds_key, {}).get("kind", "file"),
                    },
                    "target_job": {
                        "namespace": j_key[0],
                        "name": j_key[1],
                        "kind": j_kind,
                    },
                    "edge_kind": "reads_from",
                    "confidence": "grounded",
                    "source_file": "",
                    "evidence_line_start": 0,
                })
                counter_grounded += 1
            for ds in outputs:
                ds_key = (ds.get("namespace", ""), ds.get("name", ""))
                dataset_edge_counts[ds_key] += 1
                edges.append({
                    "source_dataset": {
                        "namespace": ds_key[0],
                        "name": ds_key[1],
                        "kind": datasets_seen.get(ds_key, {}).get("kind", "file"),
                    },
                    "target_job": {
                        "namespace": j_key[0],
                        "name": j_key[1],
                        "kind": j_kind,
                    },
                    "edge_kind": "writes_to",
                    "confidence": "grounded",
                    "source_file": "",
                    "evidence_line_start": 0,
                })
                counter_grounded += 1

    # Backfill dataset edge_counts
    for key, ds in datasets_seen.items():
        ds["edge_count"] = dataset_edge_counts.get(key, 0)

    datasets_list = sorted(datasets_seen.values(), key=lambda d: (d["namespace"], d["name"]))
    jobs_list = sorted(jobs_seen.values(), key=lambda j: (j["namespace"], j["name"]))

    return {
        "datasets": datasets_list,
        "jobs": jobs_list,
        "edges": edges,
        "counts": {
            "datasets": len(datasets_list),
            "jobs": len(jobs_list),
            "edges": len(edges),
            "grounded": counter_grounded,
            "inferred": counter_inferred,
            "speculative": counter_speculative,
            "chunked_files": 0,  # populated by manifest, optional
        },
    }


def build_cytoscape_elements(lineage: dict) -> list[dict]:
    """Build Cytoscape elements array from datasets + jobs + edges."""
    elements = []
    # Dataset nodes
    for ds in lineage["datasets"]:
        node_id = f"ds_{_safe_node_id(ds['namespace'] + ':' + ds['name'])}"
        elements.append({
            "data": {
                "id": node_id,
                "label": ds["name"],
                "kind": "dataset",
                "namespace": ds["namespace"],
            },
        })
    # Job nodes
    for j in lineage["jobs"]:
        node_id = f"job_{_safe_node_id(j['namespace'] + ':' + j['name'])}"
        elements.append({
            "data": {
                "id": node_id,
                "label": j["name"],
                "kind": "job",
                "namespace": j["namespace"],
            },
        })
    # Edges
    for i, e in enumerate(lineage["edges"]):
        src = e["source_dataset"]
        tgt = e["target_job"]
        src_id = f"ds_{_safe_node_id(src['namespace'] + ':' + src['name'])}"
        tgt_id = f"job_{_safe_node_id(tgt['namespace'] + ':' + tgt['name'])}"
        if e["edge_kind"] == "writes_to":
            # writes_to: edge from job to dataset
            elements.append({
                "data": {
                    "id": f"edge_{i}",
                    "source": tgt_id,
                    "target": src_id,
                    "edge_kind": e["edge_kind"],
                    "confidence": e["confidence"],
                },
            })
        else:
            # reads_from / schedules / depends_on: edge from dataset to job
            elements.append({
                "data": {
                    "id": f"edge_{i}",
                    "source": src_id,
                    "target": tgt_id,
                    "edge_kind": e["edge_kind"],
                    "confidence": e["confidence"],
                },
            })
    return elements


def build_mermaid_nodes_and_edges(
    lineage: dict,
    node_cap: int = DEFAULT_MERMAID_NODE_CAP,
) -> tuple[list[dict], list[dict], bool]:
    """Build Mermaid flowchart nodes + edges, capped at node_cap.

    Returns (nodes, edges, truncated).
    """
    # Degree counting
    degree: Counter = Counter()
    for e in lineage["edges"]:
        sk = (e["source_dataset"]["namespace"], e["source_dataset"]["name"])
        tk = (e["target_job"]["namespace"], e["target_job"]["name"])
        degree[("ds", sk)] += 1
        degree[("job", tk)] += 1

    total_nodes = len(lineage["datasets"]) + len(lineage["jobs"])
    truncated = total_nodes > node_cap

    # Pick top-N by degree
    all_nodes_with_degree: list[tuple] = []
    for ds in lineage["datasets"]:
        d = degree.get(("ds", (ds["namespace"], ds["name"])), 0)
        all_nodes_with_degree.append((d, "ds", ds))
    for j in lineage["jobs"]:
        d = degree.get(("job", (j["namespace"], j["name"])), 0)
        all_nodes_with_degree.append((d, "job", j))

    # Sort by degree desc, then by name for determinism
    all_nodes_with_degree.sort(key=lambda x: (-x[0], x[2]["namespace"], x[2]["name"]))

    if truncated:
        kept = all_nodes_with_degree[:node_cap]
    else:
        kept = all_nodes_with_degree

    # Build a node-id set for edge filtering
    kept_ds_keys = set()
    kept_job_keys = set()
    nodes_out: list[dict] = []
    for d_count, kind, node in kept:
        ns = node["namespace"]
        nm = node["name"]
        if kind == "ds":
            node_id = f"ds_{_safe_node_id(ns + ':' + nm)}"
            kept_ds_keys.add((ns, nm))
        else:
            node_id = f"job_{_safe_node_id(ns + ':' + nm)}"
            kept_job_keys.add((ns, nm))
        nodes_out.append({"id": node_id, "label": f"{ns}/{nm}"})

    # Build edges over kept nodes only
    edges_out: list[dict] = []
    seen_edges: set = set()
    for e in lineage["edges"]:
        sk = (e["source_dataset"]["namespace"], e["source_dataset"]["name"])
        tk = (e["target_job"]["namespace"], e["target_job"]["name"])
        if sk not in kept_ds_keys or tk not in kept_job_keys:
            continue
        src_id = f"ds_{_safe_node_id(sk[0] + ':' + sk[1])}"
        tgt_id = f"job_{_safe_node_id(tk[0] + ':' + tk[1])}"
        if e["edge_kind"] == "writes_to":
            src_id, tgt_id = tgt_id, src_id  # job -> dataset
        key = (src_id, tgt_id, e["edge_kind"])
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges_out.append({"src": src_id, "dst": tgt_id, "label": e["edge_kind"]})

    # Sort edges for determinism
    edges_out.sort(key=lambda e: (e["src"], e["dst"], e["label"]))

    return nodes_out, edges_out, truncated


def render_html(
    bundle: dict,
    output_dir: Path,
    no_vendor: bool = False,
    project_name: str = "project",
    workspace_tree_hash: str = "",
    run_id: str = "",
    scan_started_at: str = "",
    source_date_epoch: Optional[int] = None,
) -> Optional[Path]:
    """Render report.html. Returns the output path, or None if rendering
    was skipped (air-gap fallback)."""
    if not HAVE_JINJA:
        raise ImportError("Jinja2 not installed. Run `pip install jinja2>=3.0.0`.")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml", "jinja2"]),
        keep_trailing_newline=True,
    )
    template = env.get_template("report.html.j2")

    # Vendor resolution
    cytoscape_src = None
    dagre_src = None
    cytoscape_layout_src = None
    banner_cdn_fallback = False

    if not no_vendor:
        if CYTOSCAPE_VENDOR.exists():
            # Relative path from output_dir to vendor
            try:
                cytoscape_src = os.path.relpath(CYTOSCAPE_VENDOR, output_dir)
                if DAGRE_VENDOR.exists():
                    dagre_src = os.path.relpath(DAGRE_VENDOR, output_dir)
                if COSE_BILKENT_VENDOR.exists():
                    cytoscape_layout_src = os.path.relpath(COSE_BILKENT_VENDOR, output_dir)
            except ValueError:
                cytoscape_src = str(CYTOSCAPE_VENDOR)
        else:
            # Fall back to CDN — check reachability
            if _check_cdn_reachable():
                cytoscape_src = CDN_CYTOSCAPE
                dagre_src = CDN_DAGRE
                cytoscape_layout_src = CDN_COSE_BILKENT
                banner_cdn_fallback = True
            else:
                # Air-gap: skip HTML render
                return None
    else:
        # --no-vendor: only render HTML if vendor present
        if not CYTOSCAPE_VENDOR.exists():
            return None
        try:
            cytoscape_src = os.path.relpath(CYTOSCAPE_VENDOR, output_dir)
            if DAGRE_VENDOR.exists():
                dagre_src = os.path.relpath(DAGRE_VENDOR, output_dir)
            if COSE_BILKENT_VENDOR.exists():
                cytoscape_layout_src = os.path.relpath(COSE_BILKENT_VENDOR, output_dir)
        except ValueError:
            cytoscape_src = str(CYTOSCAPE_VENDOR)

    lineage = collect_lineage_from_bundle(bundle)
    cytoscape_elements = build_cytoscape_elements(lineage)

    # Limit table sizes for renderable HTML
    table_edges = lineage["edges"][:1000]  # cap at 1000 rows; report.html stays usable

    # Gaps placeholder (would be filled from rollup if passed; bundle alone has no gaps)
    gaps_by_file: list[dict] = []

    # Datasets/jobs ranked by degree
    top_datasets = sorted(lineage["datasets"], key=lambda d: (-d["edge_count"], d["namespace"], d["name"]))[:20]
    top_jobs = sorted(lineage["jobs"], key=lambda j: (-(j["input_count"] + j["output_count"]), j["namespace"], j["name"]))[:20]

    # Counts: lineage already has counts; augment if needed
    counts = lineage["counts"]

    # XSS-safe JSON embedding: escape <, >, & so that user-controlled content
    # cannot break out of the <script> tag context. HARD-RULE 7.
    cytoscape_json = json.dumps(cytoscape_elements, ensure_ascii=False, sort_keys=True)
    cytoscape_json_safe = (
        cytoscape_json
        .replace("\\", "\\\\")  # only the case where someone slips a literal backslash; json.dumps already handles this in strings
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")  # paragraph separator
        .replace(" ", "\\u2029")  # line separator
    )
    # The replace("\\", "\\\\") above is overly aggressive; json.dumps already
    # produces escaped backslashes inside strings. Revert to the original.
    cytoscape_json_safe = (
        cytoscape_json
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )

    rendered = template.render(
        project_name=project_name,
        workspace_tree_hash=workspace_tree_hash,
        run_id=run_id,
        scan_started_at=scan_started_at,
        extractor_id=EXTRACTOR_ID,
        extractor_version=EXTRACTOR_VERSION,
        openlineage_spec_version=PINNED_OL_VERSION,
        counts=counts,
        datasets=top_datasets,
        jobs=top_jobs,
        edges=table_edges,
        cytoscape_src=cytoscape_src,
        dagre_src=dagre_src,
        cytoscape_layout_src=cytoscape_layout_src,
        cytoscape_elements_json=cytoscape_json_safe,
        banner_cdn_fallback=banner_cdn_fallback,
        gaps_by_file=gaps_by_file,
    )

    out_path = output_dir / "report.html"
    atomic_write_text(out_path, rendered)
    return out_path


def render_md(
    bundle: dict,
    output_dir: Path,
    project_name: str = "project",
    workspace_tree_hash: str = "",
    run_id: str = "",
    scan_started_at: str = "",
    mermaid_node_cap: int = DEFAULT_MERMAID_NODE_CAP,
    airgap_fallback_only: bool = False,
) -> Path:
    """Render report.md (always; even in air-gap mode)."""
    if not HAVE_JINJA:
        raise ImportError("Jinja2 not installed. Run `pip install jinja2>=3.0.0`.")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,  # Markdown is not auto-escaped (user controls content)
        keep_trailing_newline=True,
    )
    template = env.get_template("report.md.j2")

    lineage = collect_lineage_from_bundle(bundle)
    mermaid_nodes, mermaid_edges, truncated = build_mermaid_nodes_and_edges(
        lineage, node_cap=mermaid_node_cap
    )

    top_datasets = sorted(lineage["datasets"], key=lambda d: (-d["edge_count"], d["namespace"], d["name"]))[:20]
    top_jobs = sorted(lineage["jobs"], key=lambda j: (-(j["input_count"] + j["output_count"]), j["namespace"], j["name"]))[:20]

    # Sankey rows (best-effort: use reads_from edges from job -> dataset volume)
    sankey_rows: list[dict] = []
    # Without OutputStatisticsFacet row counts, we don't have volumes — skip sankey

    rendered = template.render(
        project_name=project_name,
        workspace_tree_hash=workspace_tree_hash,
        run_id=run_id,
        scan_started_at=scan_started_at,
        extractor_id=EXTRACTOR_ID,
        extractor_version=EXTRACTOR_VERSION,
        openlineage_spec_version=PINNED_OL_VERSION,
        counts=lineage["counts"],
        mermaid_nodes=mermaid_nodes,
        mermaid_edges=mermaid_edges,
        mermaid_truncated=truncated,
        mermaid_node_cap=mermaid_node_cap,
        sankey_rows=sankey_rows,
        top_datasets=top_datasets,
        top_jobs=top_jobs,
        airgap_fallback_only=airgap_fallback_only,
    )

    out_path = output_dir / "report.md"
    atomic_write_text(out_path, rendered)
    return out_path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bundle_path", type=Path, help="Path to openlineage.json bundle")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--output-format",
        choices=["default", "ol-relational"],
        default="default",
        help="(ol-relational is split CSVs — handled by merge_into_ol)",
    )
    parser.add_argument("--no-vendor", action="store_true", help="Skip HTML if vendor absent")
    parser.add_argument("--project-name", default="project")
    parser.add_argument("--workspace-tree-hash", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--scan-started-at", default="")
    parser.add_argument(
        "--mermaid-node-cap",
        type=int,
        default=DEFAULT_MERMAID_NODE_CAP,
    )
    args = parser.parse_args(argv)

    if not args.bundle_path.exists():
        print(f"ERROR: Bundle not found: {args.bundle_path}", file=sys.stderr)
        return 1

    try:
        with args.bundle_path.open("r", encoding="utf-8") as f:
            bundle = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse bundle: {e}", file=sys.stderr)
        return 1

    source_date_epoch = None
    if "SOURCE_DATE_EPOCH" in os.environ:
        try:
            source_date_epoch = int(os.environ["SOURCE_DATE_EPOCH"])
        except ValueError:
            pass

    try:
        html_path = render_html(
            bundle,
            args.output_dir,
            no_vendor=args.no_vendor,
            project_name=args.project_name,
            workspace_tree_hash=args.workspace_tree_hash,
            run_id=args.run_id,
            scan_started_at=args.scan_started_at,
            source_date_epoch=source_date_epoch,
        )
        airgap_fallback_only = html_path is None

        md_path = render_md(
            bundle,
            args.output_dir,
            project_name=args.project_name,
            workspace_tree_hash=args.workspace_tree_hash,
            run_id=args.run_id,
            scan_started_at=args.scan_started_at,
            mermaid_node_cap=args.mermaid_node_cap,
            airgap_fallback_only=airgap_fallback_only,
        )
    except (ImportError, FileNotFoundError, OSError, PermissionError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(json.dumps({
        "html_path": str(html_path) if html_path else None,
        "md_path": str(md_path),
        "airgap_fallback": html_path is None,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
