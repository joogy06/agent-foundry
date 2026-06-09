#!/usr/bin/env python3
"""render_navigator.py — deterministic, XSS-safe code-intelligence navigator.

Forked from lineage-extract-static/scripts/render_report.py. Reads the promoted
catalog (catalog/latest.json) and produces:
  - navigator.html — self-contained Cytoscape relationship DAG + sortable
    symbol/occurrence/relationship tables + client-side search + gold-accuracy
    badge in the header (design §6).
  - symbols.csv / occurrences.csv / relationships.csv / index.ndjson — searchable
    exports.

XSS safety (HARD-RULE 4): every user-controlled string (symbol names, evidence
snippets, paths) is interpolated via Jinja2 |e (html.escape) AND the embedded
Cytoscape JSON has < > & neutralised so a hostile symbol name cannot break out of
the <script> context. The JS side uses textContent= exclusively (never
innerHTML=). Enforced by tests/test_html_escape_hostile_symbols.py.

Determinism (HARD-RULE 3): output derives only from the (already-deterministic)
catalog; no wall-clock, stable ordering, atomic writes. Two renders of the same
catalog produce byte-identical files.

Air-gap (HARD-RULE 7 reuse): vendored cytoscape if present, else CDN with a
banner, else table-only fallback (--no-vendor forces table-only when vendor
absent). Pure stdlib + jinja2 (with the same import-guard as lineage).

CLI usage:
    render_navigator.py --store PATH --output-dir DIR [--no-vendor]
                        [--store-label LABEL]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import socket
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    HAVE_JINJA = True
except ImportError:
    HAVE_JINJA = False

EXTRACTOR_VERSION = "1.0.0"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

VENDOR_DIR = Path.home() / ".claude" / "skills" / "visual-companion" / "templates" / "vendor"
CYTOSCAPE_VENDOR = VENDOR_DIR / "cytoscape.min.js"
CDN_CYTOSCAPE = "https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"


# ---------------- I/O helpers ---------------- #

def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", suffix=f".{os.getpid()}", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def resolve_store_root(store: Optional[str]) -> Path:
    if store:
        root = Path(store)
        if not root.is_absolute():
            root = Path.cwd() / root
    elif os.environ.get("LCI_STORE"):
        root = Path(os.environ["LCI_STORE"])
    else:
        root = Path.home() / ".codelib"
    return root.resolve()


def load_catalog(root: Path) -> Optional[dict]:
    cat = root / "catalog" / "latest.json"
    if not cat.is_file():
        return None
    return json.loads(cat.read_text(encoding="utf-8"))


def _check_cdn_reachable(host: str = "unpkg.com", port: int = 443, timeout: float = 2.0) -> bool:
    if os.environ.get("HOST_NETWORK_AVAILABLE", "").lower() in ("false", "0", "no"):
        return False
    try:
        socket.setdefaulttimeout(timeout)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, socket.gaierror, OSError):
        return False


# ---------------- View model ---------------- #

def build_view(catalog: dict) -> dict:
    """Derive the deterministic render model from the catalog."""
    id2name = {s.get("symbol_id"): s.get("name", "") for s in catalog.get("symbols", [])}

    def_count: Dict[str, int] = defaultdict(int)
    ref_count: Dict[str, int] = defaultdict(int)
    conf_counts = {"grounded": 0, "inferred": 0, "speculative": 0}
    for occ in catalog.get("occurrences", []):
        sid = occ.get("symbol_id")
        if occ.get("role") == "definition":
            def_count[sid] += 1
        elif occ.get("role") == "reference":
            ref_count[sid] += 1
        c = occ.get("confidence")
        if c in conf_counts:
            conf_counts[c] += 1

    symbols = []
    for s in catalog.get("symbols", []):
        sid = s.get("symbol_id")
        symbols.append({
            "symbol_id": sid, "name": s.get("name", ""), "kind": s.get("kind", ""),
            "format": s.get("format", ""), "def_count": def_count.get(sid, 0), "ref_count": ref_count.get(sid, 0),
        })
    symbols.sort(key=lambda s: (s["name"], s["symbol_id"]))

    occurrences = []
    for o in catalog.get("occurrences", []):
        occurrences.append({
            "symbol_id": o.get("symbol_id"), "symbol_name": id2name.get(o.get("symbol_id"), ""),
            "role": o.get("role", ""), "source_path": o.get("source_path", ""),
            "range": o.get("range", {"start_line": 0, "end_line": 0}),
            "confidence": o.get("confidence", "speculative"),
            "evidence_snippet": o.get("evidence_snippet", ""),
        })
    occurrences.sort(key=lambda o: (o["range"].get("start_line", 0), o["symbol_name"], o["role"]))

    relationships = []
    for r in catalog.get("relationships", []):
        relationships.append({
            "from_id": r.get("from_id"), "from_name": id2name.get(r.get("from_id"), r.get("from_id", "")),
            "to_id": r.get("to_id"), "to_name": id2name.get(r.get("to_id"), r.get("to_id", "")),
            "rel": r.get("rel", ""), "confidence": r.get("confidence", "speculative"),
        })
    relationships.sort(key=lambda r: (r["rel"], r["from_name"], r["to_name"]))

    # Cytoscape elements (deterministic order).
    elements = []
    for s in symbols:
        elements.append({"data": {"id": s["symbol_id"], "label": s["name"]}})
    for i, r in enumerate(relationships):
        elements.append({"data": {
            "id": f"e{i}", "source": r["from_id"], "target": r["to_id"],
            "rel": r["rel"], "confidence": r["confidence"],
        }})

    # Accuracy badges.
    acc = catalog.get("accuracy", {})
    threshold = acc.get("precision_threshold", 0.85)
    accuracy_formats = []
    for fmt, data in sorted((acc.get("by_format", {}) or {}).items()):
        prec = data.get("precision")
        accuracy_formats.append({
            "format": fmt, "advisory": bool(data.get("advisory", True)),
            "precision_display": ("n/a" if prec is None else f"{prec:.2f}"),
        })

    counts = {
        "artifacts": len(catalog.get("artifacts", [])),
        "symbols": len(symbols), "occurrences": len(occurrences), "relationships": len(relationships),
        "grounded": conf_counts["grounded"], "inferred": conf_counts["inferred"], "speculative": conf_counts["speculative"],
    }
    return {
        "symbols": symbols, "occurrences": occurrences, "relationships": relationships,
        "elements": elements, "accuracy_formats": accuracy_formats,
        "precision_threshold": threshold, "counts": counts,
        "generation": catalog.get("generation", 0),
    }


def _escaped_json(elements: list) -> str:
    """Embed-safe JSON: neutralise < > & (and line/para separators) so a hostile
    symbol name cannot break out of the <script> context (XSS HARD-RULE 4)."""
    raw = json.dumps(elements, ensure_ascii=False, sort_keys=True)
    return (raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace(" ", "\\u2028").replace(" ", "\\u2029"))


# ---------------- CSV / ndjson exports ---------------- #

def _write_csv(path: Path, header: list, rows: list) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for row in rows:
        w.writerow(row)
    atomic_write_text(path, buf.getvalue())


def write_exports(view: dict, catalog: dict, output_dir: Path) -> None:
    _write_csv(output_dir / "symbols.csv",
               ["symbol_id", "name", "kind", "format", "def_count", "ref_count"],
               [[s["symbol_id"], s["name"], s["kind"], s["format"], s["def_count"], s["ref_count"]] for s in view["symbols"]])
    _write_csv(output_dir / "occurrences.csv",
               ["symbol_id", "symbol_name", "role", "source_path", "start_line", "end_line", "confidence"],
               [[o["symbol_id"], o["symbol_name"], o["role"], o["source_path"],
                 o["range"].get("start_line"), o["range"].get("end_line"), o["confidence"]] for o in view["occurrences"]])
    _write_csv(output_dir / "relationships.csv",
               ["rel", "from_id", "from_name", "to_id", "to_name", "confidence"],
               [[r["rel"], r["from_id"], r["from_name"], r["to_id"], r["to_name"], r["confidence"]] for r in view["relationships"]])
    # index.ndjson — one catalog record per line (symbols then relationships).
    lines = []
    for s in catalog.get("symbols", []):
        lines.append(json.dumps({"type": "symbol", **s}, ensure_ascii=False, sort_keys=True))
    for r in catalog.get("relationships", []):
        lines.append(json.dumps({"type": "relationship", **r}, ensure_ascii=False, sort_keys=True))
    atomic_write_text(output_dir / "index.ndjson", "\n".join(lines) + ("\n" if lines else ""))


# ---------------- HTML render ---------------- #

def render_navigator(catalog: dict, output_dir: Path, *, no_vendor: bool = False,
                     store_label: str = "codelib") -> dict:
    if not HAVE_JINJA:
        raise ImportError("Jinja2 not installed. Run `pip install jinja2>=3.0.0`.")

    view = build_view(catalog)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_exports(view, catalog, output_dir)

    # Vendor resolution (air-gap safe).
    cytoscape_src = None
    banner_cdn_fallback = False
    if not no_vendor:
        if CYTOSCAPE_VENDOR.exists():
            try:
                cytoscape_src = os.path.relpath(CYTOSCAPE_VENDOR, output_dir)
            except ValueError:
                cytoscape_src = str(CYTOSCAPE_VENDOR)
        elif _check_cdn_reachable():
            cytoscape_src = CDN_CYTOSCAPE
            banner_cdn_fallback = True
        # else: table-only fallback (cytoscape_src stays None)
    else:
        if CYTOSCAPE_VENDOR.exists():
            try:
                cytoscape_src = os.path.relpath(CYTOSCAPE_VENDOR, output_dir)
            except ValueError:
                cytoscape_src = str(CYTOSCAPE_VENDOR)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml", "jinja2"]),
        keep_trailing_newline=True,
    )
    template = env.get_template("navigator.html.j2")
    rendered = template.render(
        store_label=store_label, extractor_version=EXTRACTOR_VERSION,
        generation=view["generation"], counts=view["counts"],
        symbols=view["symbols"], occurrences=view["occurrences"], relationships=view["relationships"],
        accuracy_formats=view["accuracy_formats"], precision_threshold=view["precision_threshold"],
        cytoscape_src=cytoscape_src, banner_cdn_fallback=banner_cdn_fallback,
        cytoscape_elements_json=_escaped_json(view["elements"]),
    )
    out_path = output_dir / "navigator.html"
    atomic_write_text(out_path, rendered)
    return {"html_path": str(out_path), "table_only": cytoscape_src is None,
            "symbols": view["counts"]["symbols"], "relationships": view["counts"]["relationships"]}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--no-vendor", action="store_true")
    parser.add_argument("--store-label", default="codelib")
    args = parser.parse_args(argv)

    root = resolve_store_root(args.store)
    catalog = load_catalog(root)
    if catalog is None:
        print(json.dumps({"error": "no promoted catalog", "store": str(root)}))
        return 1
    try:
        res = render_navigator(catalog, args.output_dir, no_vendor=args.no_vendor, store_label=args.store_label)
    except (ImportError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
