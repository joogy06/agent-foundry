"""test_html_escape_hostile_symbols — XSS HARD-RULE 4 (design §9).

A hostile symbol name / evidence snippet (e.g. a paragraph literally named
`<script>alert(1)</script>`, or an evidence line carrying `"><img onerror=...>`) must
NOT execute in the navigator. Server-side html.escape (Jinja |e) neutralises table
cells; the embedded Cytoscape JSON neutralises `< > &`; the JS uses textContent only.
This test renders the navigator with hostile inputs and asserts no unescaped payload
survives anywhere in the HTML.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import emit_index as ei  # noqa: E402
import render_navigator as rn  # noqa: E402
import store as st  # noqa: E402

HOSTILE = [
    "<script>alert(1)</script>",
    "\"><img src=x onerror=alert(2)>",
    "</title><svg/onload=alert(3)>",
    "'; DROP TABLE symbols;--",
    "<iframe src=javascript:alert(4)>",
]


def _render_with_hostile(store_root, output_dir):
    sha = "1" * 64
    fp = "b" * 64

    def sid(n):
        return f"codelib://sha256/{sha}#sym/{n}"

    symbols, occ, rels = [], [], []
    for i, payload in enumerate(HOSTILE):
        s = sid(f"H{i}")
        symbols.append({"symbol_id": s, "kind": "paragraph", "name": payload})
        occ.append({"symbol_id": s, "role": "definition", "range": {"start_line": i + 1, "end_line": i + 1},
                    "evidence_snippet": payload, "confidence": "speculative", "confidence_reason": payload})
        if i > 0:
            rels.append({"rel": "calls", "from_id": sid(f"H{i-1}"), "to_id": s, "evidence_line": i, "confidence": "speculative"})

    summary = {"symbols": symbols, "occurrences": occ, "relationships": rels, "gaps": []}
    index = ei.emit_index(summary, content_sha256=sha, fmt="cobol", source_path="<b>EVIL</b>.cbl", line_count=99,
                          model_id="t", prompt_hash="a" * 64, pipeline_fingerprint=fp, validate=True)
    root = st.resolve_store_root(str(store_root))
    st.persist(root, index)
    catalog = rn.load_catalog(root)
    rn.render_navigator(catalog, output_dir, no_vendor=True, store_label="<x>xss</x>")
    return (output_dir / "navigator.html").read_text(encoding="utf-8")


def test_no_executable_script_payload_survives(store_base):
    html = _render_with_hostile(store_base / "codelib", store_base / "nav")
    # The exact executable forms must NOT appear unescaped in the rendered HTML.
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(2)>" not in html
    assert "<svg/onload=alert(3)>" not in html
    assert "<iframe src=javascript:alert(4)>" not in html


def test_payloads_are_html_escaped_in_tables(store_base):
    html = _render_with_hostile(store_base / "codelib", store_base / "nav")
    # The escaped forms must be present (proving the data was rendered, just safely).
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_embedded_json_neutralises_angle_brackets(store_base, monkeypatch, tmp_path):
    """When the Cytoscape <script> block IS emitted (vendor present), the embedded
    elements JSON must neutralise '<' so a hostile node label cannot close the script
    tag. We stub a vendor file so the cytoscape path (not the table-only fallback) is
    exercised."""
    fake_vendor = tmp_path / "cytoscape.min.js"
    fake_vendor.write_text("// stub", encoding="utf-8")
    monkeypatch.setattr(rn, "CYTOSCAPE_VENDOR", fake_vendor)

    sha = "1" * 64
    fp = "b" * 64

    def sid(n):
        return f"codelib://sha256/{sha}#sym/{n}"

    summary = {
        "symbols": [{"symbol_id": sid("H0"), "kind": "paragraph", "name": "<script>alert(1)</script>"},
                    {"symbol_id": sid("H1"), "kind": "paragraph", "name": "B"}],
        "occurrences": [{"symbol_id": sid("H0"), "role": "definition", "range": {"start_line": 1, "end_line": 1},
                         "evidence_snippet": "x", "confidence": "speculative", "confidence_reason": "x"}],
        "relationships": [{"rel": "calls", "from_id": sid("H0"), "to_id": sid("H1"), "evidence_line": 1, "confidence": "speculative"}],
        "gaps": [],
    }
    index = ei.emit_index(summary, content_sha256=sha, fmt="cobol", source_path="E.cbl", line_count=2,
                          model_id="t", prompt_hash="a" * 64, pipeline_fingerprint=fp, validate=True)
    root = st.resolve_store_root(str(store_base / "codelib"))
    st.persist(root, index)
    catalog = rn.load_catalog(root)
    out = store_base / "nav"
    res = rn.render_navigator(catalog, out, no_vendor=False, store_label="x")
    assert res["table_only"] is False, "vendor stub should enable the cytoscape path"
    html = (out / "navigator.html").read_text(encoding="utf-8")

    # The hostile node label must be neutralised inside the embedded JSON.
    assert "\\u003cscript\\u003e" in html
    # No raw executable closing tag from the payload anywhere.
    assert "</script>alert" not in html
    assert "<script>alert(1)</script>" not in html


def test_no_innerHTML_assignment_in_template(store_base):
    """The navigator JS must use textContent, never innerHTML (XSS HARD-RULE 4)."""
    html = _render_with_hostile(store_base / "codelib", store_base / "nav")
    # No `.innerHTML =` assignment anywhere (the air-gap fallback uses textContent).
    assert ".innerHTML" not in html


def test_source_path_is_escaped(store_base):
    """Even the artifact source_path (here `<b>EVIL</b>.cbl`) must be escaped."""
    html = _render_with_hostile(store_base / "codelib", store_base / "nav")
    assert "<b>EVIL</b>.cbl" not in html
    assert "&lt;b&gt;EVIL&lt;/b&gt;.cbl" in html
