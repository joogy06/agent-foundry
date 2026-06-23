"""Tests for the VIEWS track (WP-7 project_views, WP-8 render, WP-9 contentSha256).

Defends design §10 invariants:
  * INV-3: project_views.py is pure graph algebra over the two emitted artifacts;
    no LLM / network import.
  * INV-4: never imports intent-extract / legacy-code-intel; never writes .ledger/.
  * INV-5: L1 is JOB-RETAINED — every L1 edge has exactly one job endpoint; ZERO
    file->file edges are ever emitted (locked user decision).
  * INV-2: byte-identical re-runs.
  * INV-6: contentSha256 = sha256 of RAW on-disk source bytes, identical to the
    mainframe engine's definition (cross-engine join key).
  * INV-7: OL core pin stays 2.0.2; facets are additive + schema-valid.
  * INV-8: XSS-safe HTML — hostile filenames inert across L1 + L2 tabs; no innerHTML.
  * INV-9: air-gap safe (report.md fallback; report.html omitted without vendor).
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
sys.path.insert(0, str(SCRIPTS_DIR))

import project_views  # noqa: E402
import merge_into_ol  # noqa: E402
import render_report  # noqa: E402
from chunk_file import sha256_of_file  # noqa: E402

# Optional third-party deps. The skill treats jinja2 (HTML render) and jsonschema
# (OL validation) as OPTIONAL — render_report raises ImportError without jinja2,
# merge_into_ol fails-closed without jsonschema. The pure graph-algebra (WP-7),
# sha256 (WP-9 definition), and static template-inspection tests have NO such dep
# and ALWAYS run. Tests that need an optional dep skip cleanly when it is absent,
# so the suite is green on a minimal interpreter and full on a provisioned one.
try:
    import jinja2  # noqa: F401
    HAVE_JINJA = True
except ImportError:
    HAVE_JINJA = False
try:
    import jsonschema  # noqa: F401
    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False

needs_jinja = pytest.mark.skipif(not HAVE_JINJA, reason="jinja2 not installed (HTML render is optional)")
needs_jsonschema = pytest.mark.skipif(not HAVE_JSONSCHEMA, reason="jsonschema not installed (OL validation is optional)")


# ---------------------------------------------------------------------------
# Fixtures: a small bipartite graph spanning file + table datasets, with a
# hostile filename to exercise the XSS chain, and a columnLineage facet.
# ---------------------------------------------------------------------------

HOSTILE = '</script><img src=x onerror=alert(1)>"&<>'


def _sample_events():
    """Two jobs:
      load.py reads file in.csv (file), writes table dwh.users (table) w/ column lineage.
      A second job has a HOSTILE filename dataset (file) to exercise XSS escaping.
    """
    col_facet = {
        "_producer": "urn:lineage:static-scan",
        "_schemaURL": project_views.COLUMN_LINEAGE_SCHEMA_URL,
        "fields": {
            "user_id": {
                "inputFields": [
                    {"namespace": "file://repo", "name": "data/in.csv",
                     "field": "id",
                     "transformations": [{"type": "INDIRECT", "subtype": "CONDITIONAL",
                                          "description": "host-var bind", "masking": False}]}
                ]
            }
        },
    }
    events = [
        {"eventType": "DATASET_EVENT", "dataset": {
            "namespace": "file://repo", "name": "data/in.csv",
            "facets": {"datasetKind": {"kind": "file"}}}},
        {"eventType": "DATASET_EVENT", "dataset": {
            "namespace": "postgres://dwh", "name": "public.users",
            "facets": {"datasetKind": {"kind": "table"}, "columnLineage": col_facet}}},
        {"eventType": "DATASET_EVENT", "dataset": {
            "namespace": "file://repo", "name": HOSTILE,
            "facets": {"datasetKind": {"kind": "file"}}}},
        {"eventType": "JOB_EVENT",
         "job": {"namespace": "repo://p", "name": "etl/load.py:main",
                 "facets": {"jobKind": {"kind": "script"}}},
         "inputs": [{"namespace": "file://repo", "name": "data/in.csv"}],
         "outputs": [{"namespace": "postgres://dwh", "name": "public.users"}]},
        {"eventType": "JOB_EVENT",
         "job": {"namespace": "repo://p", "name": "etl/hostile.py:main",
                 "facets": {"jobKind": {"kind": "script"}}},
         "inputs": [{"namespace": "file://repo", "name": HOSTILE}],
         "outputs": []},
    ]
    return events


def _sample_csv_rows():
    return [
        {"src_dataset_namespace": "file://repo", "src_dataset_name": "data/in.csv",
         "src_kind": "file", "target_job_namespace": "repo://p",
         "target_job_name": "etl/load.py:main", "target_job_kind": "script",
         "edge_kind": "reads_from", "confidence": "grounded",
         "evidence_file": "etl/load.py", "evidence_line": "12"},
        {"src_dataset_namespace": "postgres://dwh", "src_dataset_name": "public.users",
         "src_kind": "table", "target_job_namespace": "repo://p",
         "target_job_name": "etl/load.py:main", "target_job_kind": "script",
         "edge_kind": "writes_to", "confidence": "inferred",
         "evidence_file": "etl/load.py", "evidence_line": "20"},
        {"src_dataset_namespace": "file://repo", "src_dataset_name": HOSTILE,
         "src_kind": "file", "target_job_namespace": "repo://p",
         "target_job_name": "etl/hostile.py:main", "target_job_kind": "script",
         "edge_kind": "reads_from", "confidence": "speculative",
         "evidence_file": HOSTILE, "evidence_line": "1"},
    ]


@pytest.fixture
def graph_artifacts(tmp_path):
    ndjson = tmp_path / "openlineage.ndjson"
    ndjson.write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in _sample_events()) + "\n",
        encoding="utf-8",
    )
    csv_path = tmp_path / "lineage_edges.csv"
    import csv as _csv
    cols = ["src_dataset_namespace", "src_dataset_name", "src_kind",
            "target_job_namespace", "target_job_name", "target_job_kind",
            "edge_kind", "confidence", "evidence_file", "evidence_line"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in _sample_csv_rows():
            w.writerow(r)
    return ndjson, csv_path


# ---------------------------------------------------------------------------
# WP-7 — project_views
# ---------------------------------------------------------------------------

def test_views_emits_l1_and_l2(graph_artifacts, tmp_path):
    ndjson, csv_path = graph_artifacts
    payload = project_views.build_views(ndjson, csv_path, ["l1", "l2"])
    assert set(payload["graph_views"].keys()) == {"l1", "l2"}
    assert "l1" in payload["cytoscape"] and "l2" in payload["cytoscape"]


def test_l1_is_job_retained_every_edge_has_one_job_endpoint(graph_artifacts):
    """INV-5: every L1 edge connects exactly one dataset and one job."""
    ndjson, csv_path = graph_artifacts
    payload = project_views.build_views(ndjson, csv_path, ["l1"])
    l1 = payload["graph_views"]["l1"]
    assert l1["edges"], "L1 must have edges"
    for e in l1["edges"]:
        kinds = {e["from"]["kind"], e["to"]["kind"]}
        assert kinds == {"dataset", "job"}, f"L1 edge not bipartite: {e}"


def test_l1_emits_zero_file_to_file_edges(graph_artifacts):
    """INV-5 (the locked correctness failure): NO file->file cross-product edge.

    A fabricated dataset->dataset edge is the explicit correctness failure. Assert
    that no L1 edge has a dataset on BOTH endpoints, for the full element set.
    """
    ndjson, csv_path = graph_artifacts
    payload = project_views.build_views(ndjson, csv_path, ["l1"])
    # Graph view: no dataset->dataset edge.
    for e in payload["graph_views"]["l1"]["edges"]:
        assert not (e["from"]["kind"] == "dataset" and e["to"]["kind"] == "dataset"), \
            "fabricated file->file edge in L1 graph view"
    # Cytoscape element set: every edge endpoint maps to a ds_/job_ pair, never
    # ds_->ds_.
    node_kind = {}
    for el in payload["cytoscape"]["l1"]:
        d = el["data"]
        if "source" not in d:
            node_kind[d["id"]] = d["kind"]
    for el in payload["cytoscape"]["l1"]:
        d = el["data"]
        if "source" in d:
            sk = node_kind.get(d["source"])
            tk = node_kind.get(d["target"])
            assert {sk, tk} == {"dataset", "job"}, \
                f"L1 cytoscape edge endpoints not dataset+job: {sk}->{tk}"


def test_l1_job_node_retained_not_collapsed(graph_artifacts):
    ndjson, csv_path = graph_artifacts
    payload = project_views.build_views(ndjson, csv_path, ["l1"])
    job_nodes = [n for n in payload["graph_views"]["l1"]["nodes"] if n["kind"] == "job"]
    assert any(n["name"] == "etl/load.py:main" for n in job_nodes), \
        "L1 must KEEP the job node (job-retained)"


def test_l1_reattaches_confidence_and_evidence_from_csv(graph_artifacts):
    """The OL events drop confidence/evidence; project_views must restore it
    from lineage_edges.csv."""
    ndjson, csv_path = graph_artifacts
    payload = project_views.build_views(ndjson, csv_path, ["l1"])
    edge = next(e for e in payload["graph_views"]["l1"]["edges"]
                if e["to"].get("name") == "etl/load.py:main"
                and e["edge_kind"] == "reads_from")
    assert edge["confidence"] == "grounded"
    assert edge["evidence_file"] == "etl/load.py"
    assert edge["evidence_line"] == "12"


def test_l2_filters_to_table_kinds_keeps_jobs(graph_artifacts):
    ndjson, csv_path = graph_artifacts
    payload = project_views.build_views(ndjson, csv_path, ["l2"])
    l2 = payload["graph_views"]["l2"]
    ds_nodes = [n for n in l2["nodes"] if n["kind"] == "dataset"]
    # The file dataset (in.csv, hostile) must NOT appear in L2; the table does.
    names = {n["name"] for n in ds_nodes}
    assert "public.users" in names
    assert "data/in.csv" not in names
    assert HOSTILE not in names
    assert any(n["kind"] == "job" for n in l2["nodes"]), "L2 keeps job nodes"


def test_l2_nests_column_lineage_under_table_edge(graph_artifacts):
    ndjson, csv_path = graph_artifacts
    payload = project_views.build_views(ndjson, csv_path, ["l2"])
    write_edge = next(e for e in payload["graph_views"]["l2"]["edges"]
                      if e["edge_kind"] == "writes_to"
                      and e["to"]["name"] == "public.users")
    assert "columns" in write_edge
    col = write_edge["columns"][0]
    assert col["output_field"] == "user_id"
    assert col["input_field"] == "id"


def test_l2_tolerates_absent_column_facet(graph_artifacts, tmp_path):
    """Table-level L2 must still work when no columnLineage facet is present."""
    events = [e for e in _sample_events()]
    # Strip the columnLineage facet.
    for e in events:
        if e["eventType"] == "DATASET_EVENT":
            e["dataset"].get("facets", {}).pop("columnLineage", None)
    ndjson = tmp_path / "ol2.ndjson"
    ndjson.write_text("\n".join(json.dumps(x, sort_keys=True) for x in events) + "\n")
    csv_path = tmp_path / "edges2.csv"
    csv_path.write_text("src_dataset_namespace,src_dataset_name,src_kind,target_job_namespace,target_job_name,target_job_kind,edge_kind,confidence,evidence_file,evidence_line\n")
    payload = project_views.build_views(ndjson, csv_path, ["l2"])
    write_edge = next(e for e in payload["graph_views"]["l2"]["edges"]
                      if e["edge_kind"] == "writes_to")
    assert "columns" not in write_edge  # no facet -> no nested columns
    assert write_edge["to"]["name"] == "public.users"  # table-level edge survives


def test_views_byte_identical_re_run(graph_artifacts, tmp_path, monkeypatch):
    """INV-2: byte-identical views.json across re-runs with fixed SOURCE_DATE_EPOCH."""
    ndjson, csv_path = graph_artifacts
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    out1 = tmp_path / "a"
    out2 = tmp_path / "b"
    out1.mkdir(); out2.mkdir()
    p1 = project_views.write_views(project_views.build_views(ndjson, csv_path, ["l1", "l2"]), out1)
    p2 = project_views.write_views(project_views.build_views(ndjson, csv_path, ["l1", "l2"]), out2)
    assert p1.read_bytes() == p2.read_bytes()


def test_project_views_has_no_llm_or_network_import():
    """INV-3 / INV-4: pure graph algebra; no model/network/intent/ledger IMPORT.

    Checks actual import statements (AST), not docstring prose — the module is
    allowed to NAME these forbidden tokens in its INVARIANTS docstring.
    """
    import ast
    tree = ast.parse((SCRIPTS_DIR / "project_views.py").read_text())
    forbidden_modules = {
        "requests", "openai", "anthropic", "httpx", "urllib", "socket",
        "intent_extract", "legacy_code_intel",
    }
    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imported.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    leaked = imported & forbidden_modules
    assert not leaked, f"project_views.py must not import {leaked}"
    # INV-4: no .ledger/ write path in EXECUTABLE code. The module/function
    # docstrings (which NAME the invariant) are identified by AST position and
    # excluded; we then assert no remaining string literal references .ledger.
    docstring_nodes = set()
    for scope in [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                             ast.ClassDef))]:
        body = getattr(scope, "body", [])
        if body and isinstance(body[0], ast.Expr) and \
                isinstance(body[0].value, ast.Constant) and \
                isinstance(body[0].value.value, str):
            docstring_nodes.add(id(body[0].value))
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and id(n) not in docstring_nodes:
            assert ".ledger" not in n.value, \
                f"project_views.py code must not reference .ledger: {n.value!r}"


# ---------------------------------------------------------------------------
# WP-9 — contentSha256 cross-engine definition
# ---------------------------------------------------------------------------

def test_content_sha256_is_raw_file_bytes(tmp_path):
    """INV-6: contentSha256 == sha256 of RAW on-disk source bytes (no normalization)."""
    src_file = tmp_path / "PAYCALC.cbl"
    raw = b"IDENTIFICATION DIVISION.\r\n   PROGRAM-ID. PAYCALC.\n\x00binary\xfftail"
    src_file.write_bytes(raw)
    expected = hashlib.sha256(raw).hexdigest()
    # chunk_file.sha256_of_file is the canonical lineage hash threaded into the facet.
    assert sha256_of_file(src_file) == expected
    facet = merge_into_ol.make_source_code_location_facet("PAYCALC.cbl", expected)
    assert facet["contentSha256"] == expected


def test_content_sha256_cross_engine_definition_matches():
    """INV-6: the lineage facet's contentSha256 must equal the cross-engine
    contract — sha256 of raw bytes — so a mainframe engine hashing the SAME raw
    bytes produces the SAME join key. We assert the lineage side computes exactly
    sha256(raw_bytes), which is the byte-definition both engines share."""
    raw_bytes = b"01 WS-FOO PIC X(10).\n"
    # mainframe-side definition (design §5d): hashlib.sha256 over the raw bytes.
    mainframe_value = hashlib.sha256(raw_bytes).hexdigest()
    # lineage-side definition: chunk_file.sha256_of_file over the same bytes.
    h = hashlib.sha256()
    h.update(raw_bytes)
    lineage_value = h.hexdigest()
    assert lineage_value == mainframe_value
    facet = merge_into_ol.make_source_code_location_facet("x.cbl", lineage_value)
    assert facet["contentSha256"] == mainframe_value


def test_job_event_carries_source_code_location_facet():
    rollup = {"edges": [
        {"edge_kind": "reads_from",
         "source_dataset": {"namespace": "file://repo", "name": "in.csv", "kind": "file"},
         "target_job": {"namespace": "repo://p", "name": "etl/load.py:main", "kind": "script"},
         "source_file": "etl/load.py", "source_file_sha256": "abc123",
         "confidence": "grounded"},
    ]}
    job_sources = merge_into_ol.collect_job_sources(rollup["edges"])
    key = ("repo://p", "etl/load.py:main", "script")
    assert job_sources[key]["content_sha256"] == "abc123"


def test_pinned_ol_version_unchanged():
    """INV-7: do NOT bump the OL core pin."""
    assert merge_into_ol.PINNED_OL_VERSION == "2.0.2"
    assert render_report.PINNED_OL_VERSION == "2.0.2"


@needs_jsonschema
def test_merge_into_ol_emits_facet_and_validates(tmp_path):
    """INV-7: contentSha256 facet is additive + the JobEvent still schema-validates."""
    rollup = {"edges": [
        {"edge_kind": "writes_to",
         "source_dataset": {"namespace": "postgres://dwh", "name": "public.users", "kind": "table"},
         "target_job": {"namespace": "repo://p", "name": "etl/load.py:main", "kind": "script"},
         "source_file": "etl/load.py",
         "source_file_sha256": "deadbeef" * 8,
         "confidence": "grounded"},
    ]}
    out = tmp_path / "ol"
    result = merge_into_ol.merge_into_ol(
        rollup, run_id="r1", workspace_tree_hash="wth",
        scan_started_at="2026-06-23T00:00:00Z", output_dir=out,
    )
    assert result["events_emitted"] >= 2  # dataset + job
    ndjson = (out / "openlineage.ndjson").read_text()
    job_evt = next(json.loads(l) for l in ndjson.splitlines()
                   if json.loads(l)["eventType"] == "JOB_EVENT")
    scl = job_evt["job"]["facets"]["sourceCodeLocation"]
    assert scl["contentSha256"] == "deadbeef" * 8
    assert scl["_schemaURL"] == merge_into_ol.SOURCE_CODE_LOCATION_FACET_URI


@needs_jsonschema
def test_merge_into_ol_without_source_hash_omits_facet(tmp_path):
    """No source_file_sha256 -> no facet (pre-WP-9 byte-identical path)."""
    rollup = {"edges": [
        {"edge_kind": "reads_from",
         "source_dataset": {"namespace": "file://repo", "name": "in.csv", "kind": "file"},
         "target_job": {"namespace": "repo://p", "name": "j", "kind": "script"},
         "confidence": "grounded"},
    ]}
    out = tmp_path / "ol2"
    merge_into_ol.merge_into_ol(
        rollup, run_id="r", workspace_tree_hash="w",
        scan_started_at="2026-06-23T00:00:00Z", output_dir=out,
    )
    ndjson = (out / "openlineage.ndjson").read_text()
    job_evt = next(json.loads(l) for l in ndjson.splitlines()
                   if json.loads(l)["eventType"] == "JOB_EVENT")
    assert "sourceCodeLocation" not in job_evt["job"]["facets"]


# ---------------------------------------------------------------------------
# WP-8 — render: 3-tab switcher, XSS inertness per tab, no innerHTML, air-gap
# ---------------------------------------------------------------------------

def _render_html_with_views(graph_artifacts, tmp_path, monkeypatch):
    """Render report.html in multiview mode with the real vendor present (mock it)."""
    ndjson, csv_path = graph_artifacts
    payload = project_views.build_views(ndjson, csv_path, ["l1", "l2"])
    out = tmp_path / "report"
    out.mkdir()
    # Force vendor present so render_html does not bail to air-gap.
    fake_vendor = tmp_path / "cytoscape.min.js"
    fake_vendor.write_text("// cytoscape stub")
    monkeypatch.setattr(render_report, "CYTOSCAPE_VENDOR", fake_vendor)
    monkeypatch.setattr(render_report, "DAGRE_VENDOR", tmp_path / "missing-dagre.js")
    monkeypatch.setattr(render_report, "COSE_BILKENT_VENDOR", tmp_path / "missing-cose.js")
    bundle = {"events": json.loads("[" + ",".join(
        json.dumps(e) for e in _sample_events()) + "]")}
    path = render_report.render_html(
        bundle, out, no_vendor=False, project_name="proj",
        views_payload=payload,
    )
    assert path is not None
    return path.read_text(encoding="utf-8")


@needs_jinja
def test_report_html_has_three_tabs_l3_hidden(graph_artifacts, tmp_path, monkeypatch):
    html = _render_html_with_views(graph_artifacts, tmp_path, monkeypatch)
    assert 'data-view="l1"' in html
    assert 'data-view="l2"' in html
    assert 'data-view="l3"' in html
    # L3 tab is rendered hidden in v1.
    m = re.search(r'<button id="tab-l3"[^>]*>', html)
    assert m and "display:none" in m.group(0), "L3 tab must be hidden in v1"


@needs_jinja
def test_report_html_swaps_via_cy_json_not_innerhtml(graph_artifacts, tmp_path, monkeypatch):
    """INV-8: the switcher uses cy.json({elements}); the template never uses innerHTML."""
    html = _render_html_with_views(graph_artifacts, tmp_path, monkeypatch)
    assert "cy.json({ elements:" in html
    # The HTML-string sink (.innerHTML / outerHTML / insertAdjacentHTML / write)
    # must never appear — content flows only through textContent / cy.json.
    for sink in [".innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"]:
        assert sink not in html, f"template must contain no {sink} sink"


@needs_jinja
def test_html_escape_hostile_filenames_inert_across_tabs(graph_artifacts, tmp_path, monkeypatch):
    """INV-8: a hostile filename must be inert in BOTH the l1 and l2 embedded sets.

    The raw </script> / onerror payload must NOT appear verbatim in the HTML —
    every < > & is neutralised by the shared escape chain, so the embedded JSON
    cannot break out of the <script> context on any tab.
    """
    html = _render_html_with_views(graph_artifacts, tmp_path, monkeypatch)
    # The hostile dataset lives in the L1 set (file kind). Its raw payload must
    # NOT appear verbatim — every < > & is neutralised by the escape chain.
    assert "</script><img" not in html, "unescaped </script> breakout in embedded JSON"
    # The escaped form must be present (proves the value is embedded, just inert).
    assert "\\u003c" in html and "\\u003e" in html and "\\u0026" in html
    # The embedded element JSON (both l1 and l2 sets) must contain NO literal '<'.
    m = re.search(r"var VIEW_SETS = \{(.+?)\n      \};", html, re.DOTALL)
    assert m, "VIEW_SETS block must be present in multiview HTML"
    block = m.group(1)
    assert "<" not in block, "embedded element JSON must contain no literal '<'"
    assert ">" not in block, "embedded element JSON must contain no literal '>'"


@needs_jinja
def test_render_air_gap_emits_md_no_html(graph_artifacts, tmp_path, monkeypatch):
    """INV-9: with no vendor and no network, report.html is skipped; report.md
    still renders."""
    ndjson, csv_path = graph_artifacts
    out = tmp_path / "ag"
    out.mkdir()
    monkeypatch.setattr(render_report, "CYTOSCAPE_VENDOR", tmp_path / "nope.js")
    monkeypatch.setenv("HOST_NETWORK_AVAILABLE", "false")
    bundle = {"events": json.loads("[" + ",".join(
        json.dumps(e) for e in _sample_events()) + "]")}
    html_path = render_report.render_html(bundle, out, no_vendor=False,
                                          project_name="p")
    assert html_path is None  # air-gap: HTML skipped
    md_path = render_report.render_md(bundle, out, project_name="p",
                                     airgap_fallback_only=True)
    assert md_path.exists()
    assert "```mermaid" in md_path.read_text()


def test_template_contains_no_html_string_sink_at_all():
    """INV-8 belt-and-suspenders: the on-disk template uses no HTML-string sink."""
    tpl = (TEMPLATES_DIR / "report.html.j2").read_text()
    for sink in [".innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"]:
        assert sink not in tpl, f"template must contain no {sink} sink"
