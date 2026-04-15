#!/usr/bin/env python3
"""fastapi extractor — routes / Depends / lifecycle events → edges.

Covers (per design §5.1):
- @app.get|post|put|delete|patch|websocket(path, ...)   -> routes_to edges
- @router.get|post|put|delete|patch|websocket(...)      -> routes_to edges
- Depends(dependency_callable) in handler signature     -> calls edges
- @app.on_event("startup"|"shutdown")                   -> listens edges

Component resolution uses the shared resolve_component callable (contract-map).
Handlers' symbols are derived from their containing component + function name.
Route paths show up as src_symbol on routes_to edges (e.g. "POST /users").

Deterministic, no LLM calls, no network / subprocess / foreign I/O.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Callable, Iterator, Optional

# Shared edge-id helper
_EDGE_IDENTITY_DIR = Path.home() / ".claude" / "skills" / "wiring-reconcile" / "scripts"
if str(_EDGE_IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(_EDGE_IDENTITY_DIR))
from edge_identity import compute_edge_id  # noqa: E402


HTTP_DECORATORS = {"get", "post", "put", "delete", "patch", "options", "head", "websocket"}


def _decorator_parts(dec: ast.AST):
    """Return (base, attr, args) tuple if dec looks like @name.attr(args).

    Handles @app.get("/p"), @router.post("/x"), @app.on_event("startup").
    """
    if isinstance(dec, ast.Call):
        func = dec.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return func.value.id, func.attr, dec.args
    return None


def _literal_str(node) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _method_verb(attr: str) -> str:
    if attr == "websocket":
        return "WS"
    return attr.upper()


def _handler_qname(component: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return f"{component}.{fn.name}"


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
        "extractor_id": "fastapi",
        "extractor_version": extractor_version,
        "workspace_tree_hash": workspace_tree_hash,
    }
    if callsite and callsite[1]:
        edge["callsite_ref"] = {
            "file": str(callsite[0]),
            "line": int(callsite[1]),
            "column": 0,
        }
    return edge


def _emit_depends_edges(
    handler: ast.FunctionDef | ast.AsyncFunctionDef,
    src_component: str,
    src_qname: str,
    source_file: Path,
    workspace_tree_hash: str,
    extractor_version: str,
) -> Iterator[dict]:
    """Scan the handler's parameter defaults for Depends(dep) and emit calls edges."""
    for arg, default in zip(handler.args.args, handler.args.defaults or [None] * len(handler.args.args)):
        if default is None:
            continue
        # Depends(dep) — direct call
        if isinstance(default, ast.Call) and isinstance(default.func, ast.Name) and default.func.id == "Depends":
            if default.args:
                dep = default.args[0]
                dep_name = None
                if isinstance(dep, ast.Name):
                    dep_name = dep.id
                elif isinstance(dep, ast.Attribute):
                    # Something like mod.fn
                    parts = []
                    cur = dep
                    while isinstance(cur, ast.Attribute):
                        parts.insert(0, cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        parts.insert(0, cur.id)
                    dep_name = ".".join(parts) if parts else None
                if dep_name:
                    dst_component = src_component  # v1: treat Depends as intra-component unless we see external.
                    if "." in dep_name and dep_name.split(".")[0] not in ("self", "cls"):
                        # Qualified name — still attribute to same component in v1
                        pass
                    yield _build_edge(
                        src_component=src_component,
                        src_symbol=src_qname,
                        dst_component=dst_component,
                        dst_symbol=f"{src_component}.{dep_name.split('.')[-1]}",
                        edge_kind="calls",
                        callsite=(source_file, getattr(default, "lineno", None)),
                        workspace_tree_hash=workspace_tree_hash,
                        extractor_version=extractor_version,
                    )


def _walk_file(
    source_file: Path,
    src_component: str,
    resolve_component: Callable[[Path], Optional[str]],
    workspace_tree_hash: str,
    extractor_version: str,
) -> Iterator[dict]:
    try:
        tree = ast.parse(source_file.read_text(errors="replace"), filename=str(source_file))
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = node
            qname = _handler_qname(src_component, fn)
            for dec in fn.decorator_list:
                parts = _decorator_parts(dec)
                if not parts:
                    continue
                base, attr, args = parts
                if base in ("app", "router") and attr in HTTP_DECORATORS:
                    path = _literal_str(args[0]) if args else None
                    verb = _method_verb(attr)
                    route_sym = f"{verb} {path}" if path else f"{verb} ?"
                    dst_component = src_component
                    yield _build_edge(
                        src_component=src_component,
                        src_symbol=route_sym,
                        dst_component=dst_component,
                        dst_symbol=qname,
                        edge_kind="routes_to",
                        callsite=(source_file, dec.lineno),
                        workspace_tree_hash=workspace_tree_hash,
                        extractor_version=extractor_version,
                    )
                if base == "app" and attr == "on_event":
                    event = _literal_str(args[0]) if args else "unknown"
                    yield _build_edge(
                        src_component=src_component,
                        src_symbol=f"event:{event}",
                        dst_component=src_component,
                        dst_symbol=qname,
                        edge_kind="listens",
                        callsite=(source_file, dec.lineno),
                        workspace_tree_hash=workspace_tree_hash,
                        extractor_version=extractor_version,
                    )
            # Depends() calls
            yield from _emit_depends_edges(
                fn,
                src_component=src_component,
                src_qname=qname,
                source_file=source_file,
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
        if not p.is_file() or p.suffix.lower() != ".py":
            continue
        cid = resolve_component(p)
        if cid is None:
            continue
        for edge in _walk_file(
            p,
            src_component=cid,
            resolve_component=resolve_component,
            workspace_tree_hash=workspace_tree_hash,
            extractor_version=extractor_version,
        ):
            key = edge["edge_id"]
            if key in seen:
                continue
            seen.add(key)
            yield edge
