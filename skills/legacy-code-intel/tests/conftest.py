"""Shared pytest fixtures for legacy-code-intel.

Path setup so `scripts/` modules import cleanly, plus a hand-authored extraction of
the PAYROLL.cbl fixture. The hand-authored finding stands in for the in-session AI
CLI's LLM analysis (the lineage-extract-static precedent: the skill is a framework;
the LLM is the parser; tests provide a deterministic stand-in extraction so the
deterministic pipeline — accumulate/emit/store/query/render/goldcheck — can be
exercised end-to-end without an actual model call).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = SKILL_ROOT / "tests" / "fixtures"
GOLD = SKILL_ROOT / "gold"

sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(scope="session")
def skill_root() -> Path:
    return SKILL_ROOT


@pytest.fixture(scope="session")
def scripts_dir() -> Path:
    return SCRIPTS


@pytest.fixture(scope="session")
def payroll_path() -> Path:
    return FIXTURES / "PAYROLL.cbl"


@pytest.fixture(scope="session")
def payroll_sha(payroll_path) -> str:
    return hashlib.sha256(payroll_path.read_bytes()).hexdigest()


@pytest.fixture
def store_base(request) -> Path:
    """A per-test store base OUTSIDE /tmp.

    store.resolve_store_root refuses any /tmp root (HARD-RULE 8), and pytest's
    tmp_path roots under /tmp on this host — so we cannot use tmp_path for the
    store. Instead we create a unique dir under the skill's own tests/.store_tmp/
    (gitignored) and clean it up after the test."""
    import shutil
    base = SKILL_ROOT / "tests" / ".store_tmp" / request.node.name.replace("/", "_")
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def store_root(store_base) -> Path:
    """The per-test content-addressed store root (under store_base, never /tmp)."""
    return store_base / "codelib"


def payroll_finding(sha: str) -> dict:
    """Hand-authored code-finding.v1 for PAYROLL.cbl (single chunk).

    This is the deterministic stand-in for the LLM extraction. It encodes the TRUE
    call-graph of the fixture (matching gold/cobol/sample.gold.json) PLUS the dynamic
    CALL WS-PROGRAM-NAME (which the classifier must force to speculative) PLUS a
    credential-bearing CONNECT occurrence (which redact must scrub)."""
    def sid(n: str) -> str:
        return f"codelib://sha256/{sha}#sym/{n}"

    paras = [
        "0000-MAIN-CONTROL", "1000-INITIALIZE", "1100-LOAD-TAX-TABLE",
        "2000-PROCESS-EMPLOYEES", "2100-COMPUTE-PAY", "2200-WRITE-PAYSLIP", "9000-TERMINATE",
    ]
    symbols = [{"symbol_id": sid("PAYROLL"), "kind": "program", "name": "PAYROLL"}]
    for p in paras:
        symbols.append({
            "symbol_id": sid(f"PAYROLL/{p}"), "kind": "paragraph", "name": p,
            "container_symbol_id": sid("PAYROLL"),
        })
    # the literal CALL target + dynamic CALL target + copybook
    symbols.append({"symbol_id": sid("program/TAXCALC"), "kind": "call_target", "name": "TAXCALC"})
    symbols.append({"symbol_id": sid("PAYROLL/dyn/WS-PROGRAM-NAME"), "kind": "call_target", "name": "WS-PROGRAM-NAME"})
    symbols.append({"symbol_id": sid("copybook/EMPWS"), "kind": "copybook", "name": "EMPWS"})

    occurrences = [
        {"symbol_id": sid("PAYROLL"), "role": "definition", "range": {"start_line": 2, "end_line": 2},
         "evidence_snippet": "PROGRAM-ID. PAYROLL.", "confidence": "grounded", "confidence_reason": "literal_program"},
    ]
    para_lines = {
        "0000-MAIN-CONTROL": 29, "1000-INITIALIZE": 35, "1100-LOAD-TAX-TABLE": 42,
        "2000-PROCESS-EMPLOYEES": 48, "2100-COMPUTE-PAY": 53, "2200-WRITE-PAYSLIP": 57, "9000-TERMINATE": 59,
    }
    for p, ln in para_lines.items():
        occurrences.append({
            "symbol_id": sid(f"PAYROLL/{p}"), "role": "definition", "range": {"start_line": ln, "end_line": ln},
            "evidence_snippet": f"{p}.", "confidence": "grounded", "confidence_reason": "literal_paragraph",
        })
    # credential-bearing CONNECT occurrence (UN-redacted on purpose — redact must scrub)
    occurrences.append({
        "symbol_id": sid("PAYROLL/1000-INITIALIZE"), "role": "reference", "range": {"start_line": 38, "end_line": 39},
        "evidence_snippet": "CONNECT TO PAYDB USER 'PAYUSR' IDENTIFIED BY 'sup3rs3cr3tpw'",
        "confidence": "inferred", "confidence_reason": "sql_connect",
    })
    # dynamic CALL occurrence (LLM wrongly says grounded; classifier must force speculative)
    occurrences.append({
        "symbol_id": sid("PAYROLL/dyn/WS-PROGRAM-NAME"), "role": "reference", "range": {"start_line": 58, "end_line": 58},
        "evidence_snippet": "CALL WS-PROGRAM-NAME USING EMPLOYEE-RECORD",
        "confidence": "grounded", "confidence_reason": "wrongly_grounded_by_llm",
    })

    # call edges (matching gold)
    def call(frm, to, line, conf="grounded"):
        return {"rel": "calls", "from_id": sid(frm), "to_id": sid(to), "evidence_line": line, "confidence": conf}

    relationships = [
        call("PAYROLL/0000-MAIN-CONTROL", "PAYROLL/1000-INITIALIZE", 30),
        call("PAYROLL/0000-MAIN-CONTROL", "PAYROLL/2000-PROCESS-EMPLOYEES", 31),
        call("PAYROLL/0000-MAIN-CONTROL", "PAYROLL/9000-TERMINATE", 33),
        call("PAYROLL/1000-INITIALIZE", "PAYROLL/1100-LOAD-TAX-TABLE", 41),
        call("PAYROLL/2000-PROCESS-EMPLOYEES", "PAYROLL/2100-COMPUTE-PAY", 51),
        call("PAYROLL/2100-COMPUTE-PAY", "program/TAXCALC", 55),
        call("PAYROLL/2100-COMPUTE-PAY", "PAYROLL/2200-WRITE-PAYSLIP", 56),
        call("PAYROLL/2200-WRITE-PAYSLIP", "PAYROLL/dyn/WS-PROGRAM-NAME", 58, "speculative"),
    ]
    # containment + copy
    relationships.append({"rel": "copies", "from_id": sid("PAYROLL"), "to_id": sid("copybook/EMPWS"),
                          "evidence_line": 23, "confidence": "grounded"})

    return {
        "schema_version": "1.0.0", "extractor_id": "legacy-code-intel", "format": "cobol",
        "file_sha256": sha, "chunk_id": 1, "start_line": 1, "end_line": 62,
        "boundary_status": "complete",
        "symbols": symbols, "occurrences": occurrences, "relationships": relationships, "gaps": [
            {"kind": "dynamic_call", "line": 60, "detail": "CALL WS-PROGRAM-NAME (data-name target)"},
        ],
    }


@pytest.fixture
def payroll_finding_fixture(payroll_sha) -> dict:
    return payroll_finding(payroll_sha)
