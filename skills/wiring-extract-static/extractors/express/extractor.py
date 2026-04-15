#!/usr/bin/env python3
"""express extractor — routes / middleware / listen → edges.

Covers (per design §5.1):
- app.get|post|put|delete|patch|head|options(path, handler)   -> routes_to
- app.all(path, handler)                                      -> routes_to
- router.get|post|... (path, handler)                         -> routes_to
- app.use(mw) and app.use('/prefix', mw)                      -> calls edges from component to middleware
- app.listen(port)                                            -> listens edge (component -> port)

Uses regex-based detection. Full AST via Babel would be v2. Regex covers the
common 90% of idiomatic Express apps. Each match yields a schema-conforming
edge; the loader handles schema validation and defers malformed edges to gaps.

Deterministic, no LLM calls, no network / subprocess / foreign I/O.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, Iterator, Optional

# Shared edge-id helper
_EDGE_IDENTITY_DIR = Path.home() / ".claude" / "skills" / "wiring-reconcile" / "scripts"
if str(_EDGE_IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(_EDGE_IDENTITY_DIR))
from edge_identity import compute_edge_id  # noqa: E402


_METHODS = r"(?:get|post|put|delete|patch|head|options|all)"

# app.method('path', handler) or router.method('path', handler)
_ROUTE_RE = re.compile(
    r"(?P<base>app|router)\s*\.\s*(?P<method>" + _METHODS + r")\s*\(\s*['\"](?P<path>[^'\"]+)['\"]\s*,\s*(?P<handler>[A-Za-z_$][\w$]*)",
    re.MULTILINE,
)

# app.use(middleware)  or  app.use('/prefix', middleware)
_USE_RE = re.compile(
    r"(?P<base>app|router)\s*\.\s*use\s*\(\s*(?:['\"](?P<prefix>[^'\"]+)['\"]\s*,\s*)?(?P<mw>[A-Za-z_$][\w$]*)\s*[\),]",
    re.MULTILINE,
)

# app.listen(PORT)
_LISTEN_RE = re.compile(
    r"(?P<base>app)\s*\.\s*listen\s*\(\s*(?P<port>[A-Za-z_0-9$][\w$]*)",
    re.MULTILINE,
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _build_edge(
    src_component: str,
    src_symbol: str,
    dst_component: str,
    dst_symbol: str,
    edge_kind: str,
    callsite: tuple,
    workspace_tree_hash: str,
    extractor_version: str,
) -> dict:
    edge_id = compute_edge_id(src_component, src_symbol, dst_component, dst_symbol, edge_kind)
    edge = {
        "schema_version": "1.0.0",
        "edge_id": edge_id,
        "src_component": src_component,
        "src_symbol": src_symbol,
        "dst_component": dst_component,
        "dst_symbol": dst_symbol,
        "edge_kind": edge_kind,
        "evidence_source": "static_extract",
        "extractor_id": "express",
        "extractor_version": extractor_version,
        "workspace_tree_hash": workspace_tree_hash,
    }
    if callsite and callsite[1]:
        edge["callsite_ref"] = {"file": str(callsite[0]), "line": int(callsite[1]), "column": 0}
    return edge


def _walk_file(
    source_file: Path,
    src_component: str,
    workspace_tree_hash: str,
    extractor_version: str,
) -> Iterator[dict]:
    try:
        text = source_file.read_text(errors="replace")
    except OSError:
        return

    # routes
    for m in _ROUTE_RE.finditer(text):
        verb = m.group("method").upper()
        path = m.group("path")
        handler = m.group("handler")
        yield _build_edge(
            src_component=src_component,
            src_symbol=f"{verb} {path}",
            dst_component=src_component,
            dst_symbol=f"{src_component}.{handler}",
            edge_kind="routes_to",
            callsite=(source_file, _line_of(text, m.start())),
            workspace_tree_hash=workspace_tree_hash,
            extractor_version=extractor_version,
        )

    # middleware (use)
    for m in _USE_RE.finditer(text):
        mw = m.group("mw")
        prefix = m.group("prefix") or ""
        src_sym = f"{src_component}.use" + (f"[{prefix}]" if prefix else "")
        yield _build_edge(
            src_component=src_component,
            src_symbol=src_sym,
            dst_component=src_component,
            dst_symbol=f"{src_component}.{mw}",
            edge_kind="calls",
            callsite=(source_file, _line_of(text, m.start())),
            workspace_tree_hash=workspace_tree_hash,
            extractor_version=extractor_version,
        )

    # listen
    for m in _LISTEN_RE.finditer(text):
        port = m.group("port")
        yield _build_edge(
            src_component=src_component,
            src_symbol=f"{src_component}.app",
            dst_component=f"external:http",
            dst_symbol=f"external:http.listen[{port}]",
            edge_kind="listens",
            callsite=(source_file, _line_of(text, m.start())),
            workspace_tree_hash=workspace_tree_hash,
            extractor_version=extractor_version,
        )


def extract_edges(
    project_dir,
    symbols,
    source_files,
    workspace_tree_hash: str,
    extractor_version: str,
    config: dict,
    resolve_component: Callable,
) -> Iterator[dict]:
    seen: set = set()
    for fp in source_files:
        p = Path(fp)
        if not p.is_file() or p.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            continue
        cid = resolve_component(p)
        if cid is None:
            continue
        for edge in _walk_file(
            p,
            src_component=cid,
            workspace_tree_hash=workspace_tree_hash,
            extractor_version=extractor_version,
        ):
            key = edge["edge_id"]
            if key in seen:
                continue
            seen.add(key)
            yield edge
