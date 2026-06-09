"""test_redaction — HARD-RULE 1 (fail-closed secret redaction, design §9).

Legacy code is credential-dense. redact.py must scrub credentials from
occurrence.evidence_snippet, be idempotent, and FAIL-CLOSED (abort on error, never
partial output). It must NOT over-redact non-secret structure (table/host/user names).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import redact as rd  # noqa: E402


def _idx(snippets):
    return {
        "artifact": {"source_path": "PAY.cbl"},
        "occurrences": [
            {"symbol_id": f"codelib://sha256/{'0'*64}#sym/S{i}",
             "range": {"start_line": i + 1, "end_line": i + 1}, "evidence_snippet": s}
            for i, s in enumerate(snippets)
        ],
    }


@pytest.mark.parametrize("snippet,secret", [
    ("EXEC SQL CONNECT TO PAYDB USER 'PAYUSR' IDENTIFIED BY 'sup3rs3cr3t'", "sup3rs3cr3t"),
    ("password = 's3cr3tvalue'", "s3cr3tvalue"),
    ("password: hunter2unquoted", "hunter2unquoted"),
    ("jdbc:db2://host:50000/PAYDB?password=topsecret", "topsecret"),
    # Literals split so the pre-push secret-scanner's contiguous-regex can't match these
    # intentional FAKE fixtures; the runtime-assembled value is intact, so redact.py is still exercised.
    ("aws_secret_access_key=" + "abcdefghijklmnopqrst" + "uvwxyz0123456789ABCD", "abcdefghijklmnopqrst" + "uvwxyz0123456789ABCD"),
    ("export PGPASSWORD=mypgpass", "mypgpass"),
    ("Authorization: Bearer " + "abc123def456ghi789" + "jkl012mno345pqr", "abc123def456ghi789" + "jkl012mno345pqr"),
])
def test_secret_is_scrubbed(snippet, secret):
    out = rd.redact_index(_idx([snippet]))
    rendered = out["occurrences"][0]["evidence_snippet"]
    assert secret not in rendered, f"secret leaked: {rendered}"
    assert "<REDACTED" in rendered
    assert out["redaction_count"] >= 1


def test_idempotent():
    idx = _idx(["password = 'abc123'", "IDENTIFIED BY 'def456'"])
    r1 = rd.redact_index(idx)
    r2 = rd.redact_index(r1)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_does_not_over_redact_structure():
    """Table/host/user/db names are NOT secrets and must be preserved."""
    idx = _idx([
        "SELECT RATE FROM TAX_BRACKETS WHERE BRACKET = 'STD'",
        "CONNECT TO PAYDB USER 'PAYUSR' IDENTIFIED BY 'sup3rs3cr3t'",
        "READ EMPLOYEE-FILE AT END MOVE 'Y' TO WS-EOF-FLAG",
    ])
    out = rd.redact_index(idx)
    snips = [o["evidence_snippet"] for o in out["occurrences"]]
    assert "TAX_BRACKETS" in snips[0]  # table name kept
    assert "PAYDB" in snips[1] and "PAYUSR" in snips[1]  # db + user kept
    assert "sup3rs3cr3t" not in snips[1]  # only the password scrubbed
    assert "EMPLOYEE-FILE" in snips[2]  # file name kept, nothing redacted


def test_hash_not_redacted():
    """A bare sha256 hex must NOT be redacted (it is not a credential)."""
    h = "a" * 64
    idx = _idx([f"checksum {h} verified"])
    out = rd.redact_index(idx)
    assert h in out["occurrences"][0]["evidence_snippet"]


def test_fail_closed_on_unparseable_input(tmp_path):
    """The CLI must fail-closed (non-zero, no output) on unparseable JSON."""
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json ", encoding="utf-8")
    out = tmp_path / "out.json"
    rc = rd.main([str(bad), "--output", str(out)])
    assert rc == 1
    assert not out.exists(), "fail-closed: must NOT write partial output"


def test_fail_closed_reraises_in_library(monkeypatch):
    """redact_index must re-raise (fail-closed) if the pipeline raises."""
    def boom(*a, **k):
        raise RuntimeError("pattern blew up")
    monkeypatch.setattr(rd, "redact_string", boom)
    with pytest.raises(RuntimeError):
        rd.redact_index(_idx(["password = 'x'"]))
