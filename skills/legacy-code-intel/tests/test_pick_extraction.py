"""test_pick_extraction — Pick / MultiValue is the 4th legacy-code-intel format.

Additive coverage for the Pick extension (design 2026-06-09). Mirrors the COBOL
round-trip shape (test_roundtrip_and_gold) using a hand-authored Pick code-finding as
the LLM-as-parser stand-in, and asserts:

  - the new Pick `kind` closed set is accepted by emit_index + schema-validates the
    code-index.v1 (the new kinds are wired into KIND_BY_FORMAT and both schemas);
  - the indirect `CALL @POST.HOOK` occurrence is forced to speculative by the
    bright-line classifier (HARD-RULE 2 defense-in-depth, like the COBOL dynamic CALL);
  - Pick relationships (calls / reads / writes / references) survive into the index;
  - the prompts/pick.md addendum is present and wired (kinds match the enforced set);
  - Pick is registered in both JSON schemas' format enums and in KIND_BY_FORMAT.

Pick BASIC frequently has no canonical extension, so the fixture is detected by content
in the live flow; here we drive the deterministic pipeline directly with fmt="pick".
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
SCHEMAS = SKILL_ROOT / "schemas"
PROMPTS = SKILL_ROOT / "prompts"
FIXTURES = SKILL_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import accumulate as ac  # noqa: E402
import emit_index as ei  # noqa: E402
import query as q  # noqa: E402
import redact as rd  # noqa: E402
import store as st  # noqa: E402

PICK_KINDS = {"program", "subroutine", "paragraph", "dict_item", "file", "common_block", "label", "variable"}


@pytest.fixture(scope="module")
def pick_path() -> Path:
    return FIXTURES / "ORD.POST.b"


@pytest.fixture(scope="module")
def pick_sha(pick_path) -> str:
    return hashlib.sha256(pick_path.read_bytes()).hexdigest()


def pick_finding(sha: str) -> dict:
    """Hand-authored code-finding.v1 for ORD.POST.b (single chunk).

    Encodes the TRUE structure of the fixture PLUS the indirect CALL @POST.HOOK
    (which the classifier must force to speculative even though the stand-in says
    'grounded', exactly like the COBOL dynamic-CALL fixture)."""
    def sid(n: str) -> str:
        return f"codelib://sha256/{sha}#sym/{n}"

    symbols = [
        {"symbol_id": sid("ORD.POST"), "kind": "program", "name": "ORD.POST"},
        {"symbol_id": sid("ORD.POST/common/ORD.CTX"), "kind": "common_block", "name": "ORD.CTX",
         "container_symbol_id": sid("ORD.POST")},
        {"symbol_id": sid("file/ORDERS"), "kind": "file", "name": "ORDERS"},
        {"symbol_id": sid("file/CUSTOMERS"), "kind": "file", "name": "CUSTOMERS"},
        {"symbol_id": sid("ORD.POST/label/INIT"), "kind": "label", "name": "INIT",
         "container_symbol_id": sid("ORD.POST")},
        {"symbol_id": sid("ORD.POST/label/POST.ONE"), "kind": "label", "name": "POST.ONE",
         "container_symbol_id": sid("ORD.POST")},
        {"symbol_id": sid("subroutine/ORD.AUDIT"), "kind": "subroutine", "name": "ORD.AUDIT"},
        {"symbol_id": sid("ORD.POST/dyn/POST.HOOK"), "kind": "subroutine", "name": "POST.HOOK"},
        {"symbol_id": sid("dict/ORDERS/CUST.NAME"), "kind": "dict_item", "name": "CUST.NAME",
         "attributes": {"dict_type": "I"}},
        {"symbol_id": sid("ORD.POST/var/RUN.DATE"), "kind": "variable", "name": "RUN.DATE"},
    ]

    occurrences = [
        {"symbol_id": sid("ORD.POST"), "role": "definition", "range": {"start_line": 3, "end_line": 3},
         "evidence_snippet": "PROGRAM ORD.POST", "confidence": "grounded", "confidence_reason": "literal_program"},
        {"symbol_id": sid("file/ORDERS"), "role": "definition", "range": {"start_line": 7, "end_line": 7},
         "evidence_snippet": 'OPEN "ORDERS" TO F.ORD ELSE STOP', "confidence": "grounded", "confidence_reason": "literal_open"},
        {"symbol_id": sid("subroutine/ORD.AUDIT"), "role": "reference", "range": {"start_line": 24, "end_line": 24},
         "evidence_snippet": "CALL ORD.AUDIT(RUN.DATE)", "confidence": "grounded", "confidence_reason": "literal_call"},
        # indirect CALL @POST.HOOK -- stand-in WRONGLY says grounded; classifier must force speculative
        {"symbol_id": sid("ORD.POST/dyn/POST.HOOK"), "role": "reference", "range": {"start_line": 25, "end_line": 25},
         "evidence_snippet": "CALL @POST.HOOK(OID)", "confidence": "grounded", "confidence_reason": "wrongly_grounded_by_llm"},
    ]

    def rel(r, frm, to, line, conf="grounded"):
        return {"rel": r, "from_id": sid(frm), "to_id": sid(to), "evidence_line": line, "confidence": conf}

    relationships = [
        rel("calls", "ORD.POST", "subroutine/ORD.AUDIT", 24),
        rel("calls", "ORD.POST", "ORD.POST/dyn/POST.HOOK", 25, "speculative"),
        rel("reads", "ORD.POST", "file/ORDERS", 13),
        rel("writes", "ORD.POST", "file/ORDERS", 19),
        rel("reads", "ORD.POST", "file/CUSTOMERS", 38),
        rel("writes", "ORD.POST", "file/CUSTOMERS", 40),
        rel("references", "dict/ORDERS/CUST.NAME", "file/CUSTOMERS", 0),  # Tfile/TRANS join = the SQL-JOIN substitute
        rel("calls", "ORD.POST", "ORD.POST/label/INIT", 10),
        {"rel": "contains", "from_id": sid("ORD.POST"), "to_id": sid("ORD.POST/common/ORD.CTX"),
         "evidence_line": 4, "confidence": "grounded"},
    ]

    return {
        "schema_version": "1.0.0", "extractor_id": "legacy-code-intel", "format": "pick",
        "file_sha256": sha, "chunk_id": 1, "start_line": 1, "end_line": 46,
        "boundary_status": "complete",
        "symbols": symbols, "occurrences": occurrences, "relationships": relationships,
        "gaps": [{"kind": "dynamic_call", "line": 25, "detail": "CALL @POST.HOOK (indirect, data-name target)"}],
    }


def _emit(finding, sha, pick_path) -> dict:
    summary = {
        "symbols": ac.merge_symbols([finding]),
        "occurrences": ac.merge_occurrences([finding]),
        "relationships": ac.merge_relationships([finding], 50)[0],
        "gaps": finding["gaps"],
    }
    return ei.emit_index(
        summary, content_sha256=sha, fmt="pick",
        source_path=str(pick_path), line_count=46,
        model_id="test-llm", prompt_hash="c" * 64, pipeline_fingerprint="d" * 64, validate=True,
    )


# ---- the fixture exists and looks like Pick -------------------------------------

def test_pick_fixture_present_and_looks_like_pick(pick_path):
    assert pick_path.is_file(), "ORD.POST.b fixture missing"
    text = pick_path.read_text(encoding="utf-8")
    # content signatures the pick.md addendum lists as Pick detectors
    assert "READNEXT" in text
    assert "SUBROUTINE" in text or "PROGRAM" in text
    assert "OCONV(" in text
    assert "<" in text and ">" in text  # dynamic-array indexing present


# ---- the new Pick kind set is wired everywhere ----------------------------------

def test_pick_in_kind_by_format():
    assert ei.KIND_BY_FORMAT.get("pick") == PICK_KINDS


def test_pick_in_both_schema_format_enums():
    for name in ("code-index.v1.json", "code-finding.v1.json"):
        schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
        # find every "enum" that lists the known formats and assert pick is in it
        text = json.dumps(schema)
        assert '"pick"' in text, f"pick not present in {name}"
    # code-finding's kind_by_format reference must include a pick array
    cf = json.loads((SCHEMAS / "code-finding.v1.json").read_text(encoding="utf-8"))
    pick_enum = cf["definitions"]["kind_by_format"]["properties"]["pick"]["items"]["enum"]
    assert set(pick_enum) == PICK_KINDS


def test_pick_md_addendum_present_and_consistent():
    p = PROMPTS / "pick.md"
    assert p.is_file(), "prompts/pick.md missing"
    body = p.read_text(encoding="utf-8")
    # every kind in the enforced closed set must be documented in the addendum
    for k in PICK_KINDS:
        assert f"`{k}`" in body, f"pick.md does not document kind {k!r}"
    # the model-neutral / dialect cautions must be present
    assert "dialect" in body.lower()
    assert "Tfile" in body or "TRANS" in body  # the JOIN substitute


# ---- emit_index accepts the Pick kinds and schema-validates ---------------------

def test_emit_index_accepts_pick_kinds_and_validates(pick_sha, pick_path):
    index = _emit(pick_finding(pick_sha), pick_sha, pick_path)
    # all emitted symbol kinds are within the closed Pick set
    kinds = {s["kind"] for s in index["symbols"]}
    assert kinds <= PICK_KINDS, f"out-of-set kinds: {kinds - PICK_KINDS}"
    # explicit schema validation against code-index.v1 (the new format enum value must pass)
    schema = json.loads((SCHEMAS / "code-index.v1.json").read_text(encoding="utf-8"))
    Draft7Validator(schema).validate(index)
    assert index["artifact"]["format"] == "pick"


def test_emit_index_rejects_out_of_set_pick_kind(pick_sha, pick_path):
    """A bogus kind for format=pick must be a hard error (closed-set enforcement)."""
    bad = pick_finding(pick_sha)
    bad["symbols"].append({
        "symbol_id": f"codelib://sha256/{pick_sha}#sym/ORD.POST/bogus",
        "kind": "stage", "name": "BOGUS",  # 'stage' is a DSX kind, illegal for pick
    })
    with pytest.raises(ValueError):
        _emit(bad, pick_sha, pick_path)


# ---- HARD-RULE 2: indirect CALL @ forced speculative ----------------------------

def test_indirect_call_forced_speculative(pick_sha, pick_path):
    index = _emit(pick_finding(pick_sha), pick_sha, pick_path)
    dyn = [o for o in index["occurrences"]
           if o["symbol_id"].endswith("#sym/ORD.POST/dyn/POST.HOOK")]
    assert dyn, "indirect CALL @POST.HOOK occurrence missing"
    assert dyn[0]["confidence"] == "speculative", "CALL @var must be forced speculative (HARD-RULE 2)"


# ---- Pick relationships survive into the queryable store ------------------------

def test_pick_relationships_in_store(store_root, pick_sha, pick_path):
    index = _emit(pick_finding(pick_sha), pick_sha, pick_path)
    redacted = rd.redact_index(index)
    root = st.resolve_store_root(str(store_root))
    st.persist(root, redacted)

    catalog = q.load_catalog(root)
    idx = q.build_symbol_index(catalog)

    # reads/writes edges to the file symbols are present
    rels = catalog["relationships"]
    rkinds = {r["rel"] for r in rels}
    assert {"calls", "reads", "writes", "references", "contains"} <= rkinds

    # impact from the program reaches the literal subroutine and the files
    im = q.op_impact(catalog, idx, "ORD.POST", max_depth=5)
    assert im["anchor_found"] and im["edge_count"] >= 4
    # Pick has no gold file yet -> impact stays advisory (same gate as DSX/ETL)
    assert im["advisory"] is True
