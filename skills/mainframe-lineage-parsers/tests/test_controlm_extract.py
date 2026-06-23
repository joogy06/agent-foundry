"""test_controlm_extract.py — WP-5 tests for the deterministic Control-M extractor.

Defends the design §10 / work-package INVARIANTS for the MAINFRAME track:

  * each Job:* type maps per the §3 table (Command/Script/EmbeddedScript/
    FileTransfer/Database:*/Dummy + unknown);
  * the program-id stitch collides with a COBOL upper-folded PROGRAM-ID (INV stitch);
  * determinism — byte-identical OL ndjson on re-run with SOURCE_DATE_EPOCH fixed
    (INV-2);
  * the four WP-1 Control-M gaps fire on the right input;
  * columnLineage 1-2-0 facet schema-validity against the vendored OL schema (WP-4a);
  * frozen expected-ids parity (output-vs-FROZEN-CONTRACT, NEVER vs live LLM — the
    naming-contract §7 discipline);
  * INV-6 cross-engine contentSha256 byte-equality;
  * INV-1 stdlib-only / no-LLM / no-network.

Pure stdlib + pytest. No LLM, no network. conftest.py wires sys.path.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import controlm_extract as cm
import ir as mlp_ir
import graph_assemble as ga
import openlineage_emit as emit
import cobol_extract as cob

_TESTS = Path(__file__).resolve().parent
_FIXTURE = _TESTS / "fixtures" / "controlm_jobs.json"
_SKILL = _TESTS.parent
_GOLD_COBOL = _SKILL / "gold" / "cobol" / "GOLDPAY.cbl"
_PROFILES = {"DWHPRD": {"host": "dwhprd1", "port": 446, "db": "DSNDB", "schema": "PAYROLL"}}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _extract(profiles=None):
    return cm.extract_controlm(
        _FIXTURE.read_text(encoding="utf-8"),
        file=str(_FIXTURE),
        connection_profiles=profiles if profiles is not None else _PROFILES,
    )


def _edges_by_rule(ir_obj, rule):
    return [e for e in ir_obj.edges if e.provenance.rule_id == rule]


def _gap_types(ir_obj):
    return sorted(g.gap_type for g in ir_obj.gaps)


# ---------------------------------------------------------------------------
# (1) Job:* type mapping coverage
# ---------------------------------------------------------------------------
def test_job_command_program_bind():
    ir_obj = _extract()
    edges = _edges_by_rule(ir_obj, "controlm.command.program_bind")
    # GOLDPAY.sh -> program node mainframe://GOLDPAY (upper-folded basename).
    pgm_targets = {e.source.node_id for e in edges}
    assert "mainframe://GOLDPAY|GOLDPAY" in pgm_targets
    # cross-artifact name bind -> inferred, never grounded.
    for e in edges:
        assert e.kind == "inferred"
        assert e.confidence == "inferred"


def test_job_command_case_sensitive_scheduler_identity():
    ir_obj = _extract()
    # The scheduler job node keeps original case (controlm://PayrollFolder|PayCalcJob),
    # NOT upper-folded (naming-contract §2a divergence).
    sched_ids = {e.target.node_id for e in _edges_by_rule(ir_obj, "controlm.command.program_bind")}
    assert "controlm://PayrollFolder|PayCalcJob" in sched_ids


def test_job_script_grounded_when_literal():
    ir_obj = _extract()
    edges = _edges_by_rule(ir_obj, "controlm.script.artifact")
    assert edges, "expected a grounded Job:Script artifact edge"
    # FilePath %%BINDIR resolves to /prod/bin (literal var) -> grounded direct.
    e = edges[0]
    assert e.kind == "direct" and e.confidence == "grounded"
    assert e.target.name == "/prod/bin/load_payroll.sh"


def test_job_embedded_script_opaque_node_only():
    ir_obj = _extract()
    # EmbeddedScript body is opaque -> a scheduler node carrying the diagnostic,
    # NO program/file edge from its body.
    nodes = [n for n in ir_obj.nodes if n.name == "EmbeddedJob"]
    assert nodes, "expected the EmbeddedJob scheduler node"
    assert "embedded_script" in nodes[0].facets
    # no edge should treat the inline body as a program/file.
    assert not any("EmbeddedJob" in e.source.name and e.source.namespace.startswith("controlm://file")
                   for e in ir_obj.edges)


def test_job_file_transfer_read_write_direction():
    ir_obj = _extract()
    reads = _edges_by_rule(ir_obj, "controlm.filetransfer.read")
    # Src=/incoming/feed.csv is a literal read edge (file -> job).
    assert any(e.source.name == "/incoming/feed.csv" for e in reads)
    for e in reads:
        assert e.target.namespace.startswith("controlm://")  # job is the target
    # Dest has a %%RUNDATE interpolation -> runtime_path gap + speculative write.
    rt = _edges_by_rule(ir_obj, "controlm.filetransfer.write.runtime_path")
    assert rt and rt[0].confidence == "speculative"


def test_job_file_transfer_watched_runtime_src():
    ir_obj = _extract()
    # FileWatcherOptions.AssignFileNameToVariable forces the Src side runtime.
    rt = _edges_by_rule(ir_obj, "controlm.filetransfer.read.runtime_path")
    assert rt, "watched-file Src should be a runtime_path edge"
    assert rt[0].confidence == "speculative"


def test_job_database_resolved_grounded():
    ir_obj = _extract()
    edges = _edges_by_rule(ir_obj, "controlm.database.table")
    # DbResolvedJob: literal SQL + resolved DWHPRD profile -> a grounded edge to a
    # real db2:// table node.
    grounded = [e for e in edges if e.confidence == "grounded"]
    assert any(e.source.namespace == "db2://dwhprd1:446/DSNDB" for e in grounded)


def test_job_dummy_node_only():
    ir_obj = _extract()
    dummy = [n for n in ir_obj.nodes if n.name == "DummyGate"]
    assert dummy and dummy[0].facets.get("controlm_type") == "Job:Dummy"


def test_unknown_type_never_crashes():
    ir_obj = _extract()
    unknown = [n for n in ir_obj.nodes if n.name == "UnknownTypeJob"]
    assert unknown and unknown[0].facets.get("unmapped_type") == "Job:SomeFutureType"


# ---------------------------------------------------------------------------
# (6) the four WP-1 Control-M gaps fire on the right input
# ---------------------------------------------------------------------------
def test_unresolved_variable_gap():
    ir_obj = _extract()
    # UnresolvedVarCommandJob: %%UNKNOWNBIN never declared -> unresolved_variable.
    assert "unresolved_variable" in _gap_types(ir_obj)


def test_unresolved_connection_gap():
    ir_obj = _extract()
    # DbUnresolvedConnJob references MISSING_PROFILE -> unresolved_connection.
    assert "unresolved_connection" in _gap_types(ir_obj)
    raws = {g.facets.get("raw_connection_profile") for g in ir_obj.gaps
            if g.gap_type == "unresolved_connection"}
    assert "MISSING_PROFILE" in raws


def test_runtime_path_gap():
    ir_obj = _extract()
    assert "runtime_path" in _gap_types(ir_obj)


def test_unresolved_event_dep_gap():
    ir_obj = _extract()
    # DummyGate waits on never-produced-event with no producer -> unresolved_event_dep.
    assert "unresolved_event_dep" in _gap_types(ir_obj)
    raws = {g.facets.get("raw_event") for g in ir_obj.gaps
            if g.gap_type == "unresolved_event_dep"}
    assert "never-produced-event" in raws


def test_interpolated_sql_speculative():
    ir_obj = _extract()
    # DbInterpolatedJob: %%SCHEMA in SQL -> the table edge is speculative + a gap.
    spec_db = [e for e in _edges_by_rule(ir_obj, "controlm.database.table")
               if e.confidence == "speculative"]
    assert spec_db, "interpolated SQL must yield a speculative table edge"


# ---------------------------------------------------------------------------
# event DAG resolution
# ---------------------------------------------------------------------------
def test_event_dag_resolves_producer_to_consumer():
    ir_obj = _extract()
    deps = _edges_by_rule(ir_obj, "controlm.dag.event_dependency")
    # PayCalcJob (eventsToAdd paycalc-done) -> LoadScriptJob (eventsToWaitFor).
    pairs = {(e.source.name, e.target.name) for e in deps}
    assert ("PayCalcJob", "LoadScriptJob") in pairs
    assert ("LoadScriptJob", "EmbeddedJob") in pairs


# ---------------------------------------------------------------------------
# (3) program-id stitch collides with a COBOL upper-folded PROGRAM-ID
# ---------------------------------------------------------------------------
def test_program_id_stitch_collides_with_cobol():
    ctm_ir = _extract()
    cob_ir = cob.extract_cobol_file(str(_GOLD_COBOL))
    assembled = ga.assemble([ctm_ir, cob_ir])
    # The Control-M GOLDPAY.sh program node and the COBOL GOLDPAY PROGRAM-ID node
    # are the SAME canonical node -> they collide on dedupe (one node, two edges).
    gp_node_ids = set()
    for e in assembled.ir.edges:
        for n in (e.source, e.target):
            if n.node_id == "mainframe://GOLDPAY|GOLDPAY":
                gp_node_ids.add(n.node_id)
    assert "mainframe://GOLDPAY|GOLDPAY" in gp_node_ids
    # Both a Control-M scheduler edge AND COBOL edges touch the shared node.
    touching_rules = {
        e.provenance.rule_id
        for e in assembled.ir.edges
        if "mainframe://GOLDPAY|GOLDPAY" in (e.source.node_id, e.target.node_id)
    }
    assert "controlm.command.program_bind" in touching_rules


def test_program_id_from_command_rule():
    # LOCKED stitch rule: basename of argv[0], ext stripped, upper-folded.
    assert cm.program_id_from_command("PAYCALC.sh -v") == "PAYCALC"
    assert cm.program_id_from_command("/prod/bin/paycalc.SH") == "PAYCALC"
    assert cm.program_id_from_command('"my prog.sh" -x') == "MY PROG"
    assert cm.program_id_from_command("DSNUTILB") == "DSNUTILB"


# ---------------------------------------------------------------------------
# (4) determinism — byte-identical OL ndjson on re-run (INV-2)
# ---------------------------------------------------------------------------
def test_determinism_byte_identical(tmp_path):
    env = dict(os.environ, SOURCE_DATE_EPOCH="1700000000")
    run = _SKILL / "scripts" / "run_lineage.py"
    out1 = tmp_path / "a.ndjson"
    out2 = tmp_path / "b.ndjson"
    for out in (out1, out2):
        r = subprocess.run(
            [sys.executable, str(run), "--controlm", str(_FIXTURE),
             "--out", str(out)],
            env=env, capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
    assert out1.read_bytes() == out2.read_bytes()


def test_determinism_in_isolation():
    # The extractor slice is itself byte-identical on re-run (canonical sort/dedupe).
    a = _extract()
    b = _extract()
    a_keys = [e.canonical_key for e in a.edges]
    b_keys = [e.canonical_key for e in b.edges]
    assert a_keys == b_keys
    assert _gap_types(a) == _gap_types(b)


# ---------------------------------------------------------------------------
# (5) columnLineage 1-2-0 schema-validity against the vendored OL schema
# ---------------------------------------------------------------------------
def _synthetic_column_edge():
    """Build a host-var->column edge exactly as sql_extract emits one (column node
    source -> program job target, rule_id sql.hostvar.column)."""
    col_node = mlp_ir.make_node(
        "db2://dwhprd1:446/DSNDB", "PAYROLL.EMPLOYEE.EMPNO",
        node_type="dataset",
        facets={"raw_column": "EMPNO", "of_table": "PAYROLL.EMPLOYEE"},
    )
    pgm_node = mlp_ir.make_node("mainframe://GOLDPAY", "GOLDPAY", node_type="job")
    prov = mlp_ir.Provenance(
        parser="sql", engine="regex", rule_id="sql.hostvar.column",
        dialect="db2-sql",
        raw_tokens={"raw_host_var": "WS-EMPNO", "raw_column": "EMPNO"},
    )
    return mlp_ir.make_edge(col_node, pgm_node, kind="inferred", confidence="inferred",
                            provenance=prov)


def test_column_lineage_facet_schema_valid():
    # The emitted columnLineage 1-2-0 facet must keep the DatasetEvent OL-valid
    # (WP-4a, INV-7 additive + self-describing).
    from validate_ol import validate_event, DEFAULT_SCHEMA_PATH
    col_edge = _synthetic_column_edge()
    assert emit._is_column_edge(col_edge)
    facet = emit._column_lineage_facet([col_edge])
    assert facet is not None
    assert facet["_schemaURL"].endswith("ColumnLineageDatasetFacet.json")
    # the standard facet shape: fields{<out_col>:{inputFields:[{namespace,name,field,
    # transformations:[{type,subtype,description,masking}]}]}}
    assert "EMPNO" in facet["fields"]
    tf = facet["fields"]["EMPNO"]["inputFields"][0]["transformations"][0]
    assert tf["type"] == "INDIRECT" and tf["subtype"] == "CONDITIONAL"
    assert tf["masking"] is False
    # The facet attached to a DatasetEvent must validate.
    evt = {
        "$schema": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
        "eventType": "DATASET_EVENT",
        "eventTime": "1970-01-01T00:00:00Z",
        "producer": emit.PRODUCER_URI,
        "schemaURL": "https://openlineage.io/spec/2-0-2/OpenLineage.json",
        "dataset": {"namespace": "db2://h:1/d", "name": "S.T",
                    "facets": {"columnLineage": facet}},
    }
    is_valid, errors = validate_event(evt, DEFAULT_SCHEMA_PATH)
    assert is_valid, errors


def test_controlm_dependencies_facet_schema_valid():
    ir_obj = _extract()
    assembled = ga.assemble([ir_obj])
    events = emit.build_events(assembled.ir)
    ctm_jobs = [e for e in events
                if e["eventType"] == "JOB_EVENT"
                and "controlmDependencies" in e["job"]["facets"]]
    assert ctm_jobs, "expected at least one controlmDependencies JOB facet"
    f = ctm_jobs[0]["job"]["facets"]["controlmDependencies"]
    assert f["static_design_time"] is True
    assert "_schemaURL" in f and "upstream" in f and "downstream" in f


# ---------------------------------------------------------------------------
# (2) frozen expected-ids parity (output-vs-FROZEN-CONTRACT, never vs live LLM)
# ---------------------------------------------------------------------------
# The frozen expected node ids for the fixture's program-bind + script edges.
# This is the naming-contract §2a/§3 discipline pinned as a table — asserted
# against THIS contract, NOT against any live LLM run (§7 honesty note).
_FROZEN_EXPECTED_EDGE_IDS = {
    # (source_node_id, target_node_id, kind)
    ("mainframe://GOLDPAY|GOLDPAY", "controlm://PayrollFolder|PayCalcJob", "inferred"),
    ("controlm://PayrollFolder|LoadScriptJob",
     "controlm://file|/prod/bin/load_payroll.sh", "direct"),
    ("controlm://file|/incoming/feed.csv",
     "controlm://PayrollFolder|TransferJob", "direct"),
    ("controlm://PayrollFolder|PayCalcJob",
     "controlm://PayrollFolder|LoadScriptJob", "inferred"),
}


def test_frozen_expected_ids_parity():
    ir_obj = _extract()
    got = {e.canonical_key for e in ir_obj.edges}
    missing = _FROZEN_EXPECTED_EDGE_IDS - got
    assert not missing, f"frozen contract edges missing from output: {sorted(missing)}"


# ---------------------------------------------------------------------------
# INV-6 cross-engine contentSha256 byte-equality
# ---------------------------------------------------------------------------
def test_contentsha256_cross_engine_identical():
    import importlib
    cf = importlib.import_module("chunk_file")
    mine = mlp_ir.content_sha256_of_bytes(_GOLD_COBOL.read_bytes())
    theirs = cf.sha256_of_file(_GOLD_COBOL)
    assert mine == theirs, "INV-6: mainframe + lineage contentSha256 must be byte-identical"


def test_contentsha256_on_controlm_job_events(tmp_path):
    ir_obj = cm.extract_controlm_file(str(_FIXTURE), connection_profiles=_PROFILES)
    assembled = ga.assemble([ir_obj])
    events = emit.build_events(assembled.ir)
    scl = [e for e in events
           if e["eventType"] == "JOB_EVENT"
           and "sourceCodeLocation" in e["job"]["facets"]]
    assert scl, "Control-M job events should carry sourceCodeLocation.contentSha256"
    sha = scl[0]["job"]["facets"]["sourceCodeLocation"]["contentSha256"]
    assert sha == mlp_ir.content_sha256_of_bytes(_FIXTURE.read_bytes())


# ---------------------------------------------------------------------------
# INV-1 stdlib-only / no-LLM / no-network in controlm_extract.py
# ---------------------------------------------------------------------------
def test_no_llm_or_network_imports():
    src = (_SKILL / "scripts" / "controlm_extract.py").read_text(encoding="utf-8")
    forbidden = re.compile(
        r"\b(import\s+(requests|openai|anthropic|httpx)"
        r"|urllib\.request|subprocess|os\.system|os\.popen)\b"
    )
    assert not forbidden.search(src), "controlm_extract.py must be stdlib-only, no LLM/network/shell"


def test_gold_controlm_fixture_parity():
    # The gold/controlm/ fixture must produce EXACTLY the edges the gold YAML
    # oracle pins (output-vs-FROZEN-CONTRACT). Zero gaps on this clean fixture.
    gold = _SKILL / "gold" / "controlm" / "GOLDSCHED.json"
    ir_obj = cm.extract_controlm_file(str(gold))
    got = {e.canonical_key for e in ir_obj.edges}
    expected = {
        ("mainframe://GOLDPAY|GOLDPAY", "controlm://GoldFolder|GoldPayJob", "inferred"),
        ("controlm://GoldFolder|GoldLoadJob",
         "controlm://file|/PROD/bin/gold_load.sh", "direct"),
        ("controlm://GoldFolder|GoldPayJob",
         "controlm://GoldFolder|GoldLoadJob", "inferred"),
    }
    assert got == expected, f"gold parity drift: got={sorted(got)}"
    assert ir_obj.gaps == [], "the clean gold fixture must emit zero gaps"


def test_gap_enum_has_eight_members():
    # WP-1: the 4 original + 4 Control-M gap kinds, contract stays closed.
    assert len(mlp_ir.GAP_TYPE_ENUM) == 8
    for new in ("unresolved_variable", "unresolved_connection",
                "runtime_path", "unresolved_event_dep"):
        assert new in mlp_ir.GAP_TYPE_ENUM
    with pytest.raises(mlp_ir.IRValidationError):
        mlp_ir.make_gap_node("not_a_real_gap_type")
