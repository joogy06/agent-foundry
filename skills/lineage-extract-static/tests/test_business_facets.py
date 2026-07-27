"""Business-analysis pass emission (S59 WP-1, design §3.1).

Asserts the producer side of the DLP report-tab cycle: a rollup carrying the
business-analysis keys yields ``staticAnalysis.business`` /
``staticAnalysis.dead_code`` facets on the matching Job/DatasetEvents,
``dataset_kinds`` seed/lookup tags override the ``datasetKind`` facet, and
``assemble_manifest_business`` produces the manifest.business block (sections
omitted when the source gives nothing; domains partition bundle members with a
single primary domain each). Dead flags require NAMED evidence and are never
padded. Runs against the real merge_into_ol + validate_ol with the vendored
OL 2.0.2 schema.
"""
from __future__ import annotations

import json

from merge_into_ol import merge_into_ol

NS = "postgres://jaffle-dwh:5432/analytics"
JOB_NS = "dbt://jaffle_shop"


def _edge(edge_kind, ds_name, job_name, ds_kind="table"):
    return {
        "edge_kind": edge_kind,
        "source_dataset": {"namespace": NS, "name": ds_name, "kind": ds_kind},
        "target_job": {"namespace": JOB_NS, "name": job_name, "kind": "script"},
        "evidence_line_start": 5,
        "evidence_line_end": 5,
        "evidence_snippet": "select ...",
        "confidence": "grounded",
        "confidence_reason": "literal name",
        "source_file": f"models/{job_name}.sql",
    }


def _jaffle_rollup(**extra):
    # raw_customers (seed) -> stg_customers -> customers; raw_orders unused.
    edges = [
        _edge("reads_from", "raw.raw_customers", "stg_customers"),
        _edge("writes_to", "public.stg_customers", "stg_customers"),
        _edge("reads_from", "public.stg_customers", "customers"),
        _edge("writes_to", "public.customers", "customers"),
    ]
    rollup = {
        "schema_version": "1.0.0",
        "extractor_id": "lineage-extract-static",
        "scope": "project_aggregate",
        "edges": edges,
        "gaps": [],
    }
    rollup.update(extra)
    return rollup


_BUSINESS = {
    "overview": "Jaffle Shop models orders and customers for a food chain.",
    "narrative": "Seeds land raw tables; staging renames; marts aggregate.",
    "flow_summary": "sources -> staging -> marts",
    "domains": [
        {"name": "Customers",
         "description": "Customer master and lifetime stats.",
         "flow": "raw_customers -> stg_customers -> customers",
         "members": [
             {"namespace": NS, "name": "raw.raw_customers"},
             {"namespace": NS, "name": "public.stg_customers"},
             {"namespace": NS, "name": "public.customers"},
             {"namespace": JOB_NS, "name": "stg_customers"},
             {"namespace": JOB_NS, "name": "customers"},
         ]},
    ],
}

_OBJECT_BUSINESS = [
    {"entity": "dataset", "namespace": NS, "name": "public.customers",
     "purpose": "One row per customer with lifetime order stats.",
     "domain": "Customers"},
    {"entity": "job", "namespace": JOB_NS, "name": "customers",
     "purpose": "Builds the customer mart.", "domain": "Customers"},
]


def _emit(tmp_path, rollup):
    summary = merge_into_ol(
        rollup,
        run_id="r1",
        workspace_tree_hash="jaffle-treehash-1",
        scan_started_at="2026-07-02T09:00:00Z",
        output_dir=tmp_path,
    )
    events = [json.loads(line) for line in
              (tmp_path / "openlineage.ndjson").read_text().splitlines() if line]
    return summary, events


def _by_name(events, event_type, key):
    return {e[key]["name"]: e for e in events if e["eventType"] == event_type}


def test_business_pass_attaches_facets_and_assembles_manifest(tmp_path):
    rollup = _jaffle_rollup(
        business=_BUSINESS,
        object_business=_OBJECT_BUSINESS,
        dataset_kinds=[{"namespace": NS, "name": "raw.raw_customers", "kind": "seed"}],
    )
    summary, events = _emit(tmp_path, rollup)
    ds = _by_name(events, "DATASET_EVENT", "dataset")
    jobs = _by_name(events, "JOB_EVENT", "job")
    # dataset-side staticAnalysis.business (same shape as the job facet).
    biz = ds["public.customers"]["dataset"]["facets"]["staticAnalysis"]["business"]
    assert biz == {"purpose": "One row per customer with lifetime order stats.",
                   "domain": "Customers"}
    # datasets without business info carry NO staticAnalysis facet.
    assert "staticAnalysis" not in ds["public.stg_customers"]["dataset"]["facets"]
    # job-side rides INSIDE the existing staticAnalysis facet.
    jfacet = jobs["customers"]["job"]["facets"]["staticAnalysis"]
    assert jfacet["business"] == {"purpose": "Builds the customer mart.",
                                  "domain": "Customers"}
    assert jfacet["extractor_id"] == "lineage-extract-static"  # existing keys intact
    assert "business" not in jobs["stg_customers"]["job"]["facets"]["staticAnalysis"]
    # seed tagging lands in the datasetKind facet (importer -> elements.subtype).
    assert ds["raw.raw_customers"]["dataset"]["facets"]["datasetKind"]["kind"] == "seed"
    assert summary["dataset_kinds_applied"] == 1
    assert summary["business_facets_attached"] == 2
    assert summary["dead_code_facets_attached"] == 0
    assert summary["business_gaps"] == []
    # manifest.business assembled with provenance stamps.
    mb = summary["manifest_business"]
    assert mb["overview"] == _BUSINESS["overview"]
    assert mb["generated_by"] == "lineage-extract-static"
    assert mb["tree_hash"] == "jaffle-treehash-1"
    assert [d["name"] for d in mb["domains"]] == ["Customers"]
    assert len(mb["domains"][0]["members"]) == 5


def test_dead_flag_negative_is_not_padded(tmp_path):
    # jaffle has no dead code -> zero flags, zero padding, pre-S59 byte shape.
    rollup = _jaffle_rollup(business=_BUSINESS, object_business=_OBJECT_BUSINESS)
    summary, events = _emit(tmp_path, rollup)
    assert summary["dead_code_facets_attached"] == 0
    for e in events:
        facets = (e.get("dataset") or e.get("job", {})).get("facets", {})
        assert "dead_code" not in facets.get("staticAnalysis", {})


def test_dead_flag_requires_named_evidence(tmp_path):
    dead = [
        # valid: full named evidence.
        {"entity": "job", "namespace": JOB_NS, "name": "stg_customers",
         "evidence_file": "models/staging/stg_customers.sql", "evidence_line": 3,
         "reason": "model body fully commented out"},
        # invalid: no evidence_line -> dropped with a gap, never attached.
        {"entity": "dataset", "namespace": NS, "name": "public.customers",
         "evidence_file": "models/marts/customers.sql",
         "reason": "looks unused"},
    ]
    summary, events = _emit(tmp_path, _jaffle_rollup(dead_code=dead))
    jobs = _by_name(events, "JOB_EVENT", "job")
    dc = jobs["stg_customers"]["job"]["facets"]["staticAnalysis"]["dead_code"]
    assert dc == {"flag": True,
                  "evidence_file": "models/staging/stg_customers.sql",
                  "evidence_line": 3,
                  "reason": "model body fully commented out"}
    ds = _by_name(events, "DATASET_EVENT", "dataset")
    assert "staticAnalysis" not in ds["public.customers"]["dataset"]["facets"]
    assert summary["dead_code_facets_attached"] == 1
    assert any("NAMED evidence" in g for g in summary["business_gaps"])


def test_domain_partition_rules(tmp_path):
    business = {
        "domains": [
            {"name": "Customers",
             "members": [{"namespace": NS, "name": "public.customers"}]},
            {"name": "Orders",
             "members": [
                 # already claimed by Customers -> dropped (single primary domain).
                 {"namespace": NS, "name": "public.customers"},
                 # not in the bundle -> dropped with gap.
                 {"namespace": NS, "name": "public.ghost"},
             ]},
        ],
    }
    summary, _events = _emit(tmp_path, _jaffle_rollup(business=business))
    mb = summary["manifest_business"]
    assert [d["name"] for d in mb["domains"]] == ["Customers"]
    gaps = summary["business_gaps"]
    assert any("already claimed" in g for g in gaps)
    assert any("not present in the bundle" in g for g in gaps)
    assert any("no surviving members" in g for g in gaps)


def test_sections_omitted_when_source_gives_nothing(tmp_path):
    summary, _events = _emit(
        tmp_path, _jaffle_rollup(business={"overview": "Only an overview.",
                                           "narrative": "", "domains": []}))
    mb = summary["manifest_business"]
    assert set(mb.keys()) == {"overview", "generated_by", "tree_hash"}


def test_rollup_without_business_keys_is_unchanged(tmp_path):
    summary, events = _emit(tmp_path, _jaffle_rollup())
    assert summary["manifest_business"] is None
    assert summary["business_facets_attached"] == 0
    assert summary["business_gaps"] == []
    for e in events:
        if e["eventType"] == "DATASET_EVENT":
            assert "staticAnalysis" not in e["dataset"]["facets"]
        else:
            sa = e["job"]["facets"]["staticAnalysis"]
            assert "business" not in sa and "dead_code" not in sa


def test_reemission_is_byte_identical(tmp_path):
    rollup = _jaffle_rollup(
        business=_BUSINESS,
        object_business=_OBJECT_BUSINESS,
        dataset_kinds=[{"namespace": NS, "name": "raw.raw_customers", "kind": "seed"}],
    )
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir(), d2.mkdir()
    s1, _ = _emit(d1, rollup)
    s2, _ = _emit(d2, rollup)
    assert (d1 / "openlineage.ndjson").read_bytes() == \
        (d2 / "openlineage.ndjson").read_bytes()
    assert s1["manifest_business"] == s2["manifest_business"]
