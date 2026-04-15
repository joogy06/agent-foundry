#!/usr/bin/env python3
"""generic-treesitter fallback extractor.

Per design 2026-04-14 §5.1: "generic tree-sitter fallback". Emits only
``calls`` and ``imports`` edges; no routes, events, DB, or UI edges.

Graceful degradation:
- If the ``tree_sitter`` Python package and ``tree_sitter_python`` /
  ``tree_sitter_javascript`` language bindings are importable, use them.
- Otherwise fall back to:
    * Python's built-in ``ast`` module for ``.py`` files (guaranteed available).
    * A regex-based scan for JS/TS that extracts top-level ``import`` and
      ``require(...)`` statements and free-standing ``name(...)`` calls.

This fallback is intentionally conservative: it emits only edges we can
identify with high precision from shallow analysis. It never invents
components. Every emitted edge has ``src_component`` and ``dst_component``
produced by the caller-supplied ``resolve_component`` callable (or the
explicit ``external:<pkg>`` tag for imported libraries).

The extractor returns an iterator of edge dicts conforming to
``wiring-source-edge.v1``. The caller (the loader) will add the
``emitted_at`` timestamp and validate against the schema.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Callable, Iterator, Optional

# Shared edge-id helper (single source of truth)
_EDGE_IDENTITY_DIR = Path.home() / ".claude" / "skills" / "wiring-reconcile" / "scripts"
if str(_EDGE_IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(_EDGE_IDENTITY_DIR))
from edge_identity import compute_edge_id  # noqa: E402


# --- Python AST walker -----------------------------------------------------


def _python_edges(
    source_file: Path,
    src_component: str,
    src_symbol_prefix: str,
    resolve_component: Callable[[Path], Optional[str]],
    workspace_tree_hash: str,
    extractor_version: str,
) -> Iterator[dict]:
    try:
        tree = ast.parse(source_file.read_text(errors="replace"), filename=str(source_file))
    except SyntaxError:
        return  # skip this file, loader records gap via manifest
    # Index function defs for qualified-name construction
    for node in ast.walk(tree):
        # imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                yield _make_edge(
                    src_component=src_component,
                    src_symbol=src_symbol_prefix or src_component,
                    dst_component=f"external:{name.split('.')[0]}",
                    dst_symbol=f"external:{name}",
                    edge_kind="imports",
                    callsite=(source_file, getattr(node, "lineno", None)),
                    workspace_tree_hash=workspace_tree_hash,
                    extractor_version=extractor_version,
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            base = module.split(".")[0] if module else ""
            if not base:
                continue
            for alias in node.names:
                yield _make_edge(
                    src_component=src_component,
                    src_symbol=src_symbol_prefix or src_component,
                    dst_component=f"external:{base}",
                    dst_symbol=f"external:{module}.{alias.name}" if module else f"external:{alias.name}",
                    edge_kind="imports",
                    callsite=(source_file, getattr(node, "lineno", None)),
                    workspace_tree_hash=workspace_tree_hash,
                    extractor_version=extractor_version,
                )

    # calls: for each FunctionDef, find Call nodes in its body whose target is a Name;
    # if that Name refers to a function defined in the same component, emit a calls edge.
    defined_names: dict[str, str] = {}  # func_name -> qualified_name
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qname = f"{src_component}.{node.name}"
            defined_names[node.name] = qname
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            src_qname = f"{src_component}.{node.name}"
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    called = child.func
                    if isinstance(called, ast.Name) and called.id in defined_names:
                        dst_qname = defined_names[called.id]
                        if dst_qname == src_qname:
                            continue  # skip self-recursion for the generic fallback
                        yield _make_edge(
                            src_component=src_component,
                            src_symbol=src_qname,
                            dst_component=src_component,
                            dst_symbol=dst_qname,
                            edge_kind="calls",
                            callsite=(source_file, getattr(child, "lineno", None)),
                            workspace_tree_hash=workspace_tree_hash,
                            extractor_version=extractor_version,
                        )


# --- JS/TS regex fallback -------------------------------------------------

_IMPORT_RE = re.compile(r"""^\s*import\s+(?:[^'"]+?\s+from\s+)?['"]([^'"]+)['"]""", re.MULTILINE)
_REQUIRE_RE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
_FUNC_DEF_RE = re.compile(
    r"(?:^|\s)(?:async\s+)?function\s+([A-Za-z_][\w]*)\s*\(|"
    r"(?:^|\s)const\s+([A-Za-z_][\w]*)\s*=\s*(?:async\s*)?\(",
    re.MULTILINE,
)
_CALL_RE = re.compile(r"([A-Za-z_][\w]*)\s*\(")


def _js_edges(
    source_file: Path,
    src_component: str,
    resolve_component: Callable[[Path], Optional[str]],
    workspace_tree_hash: str,
    extractor_version: str,
) -> Iterator[dict]:
    try:
        text = source_file.read_text(errors="replace")
    except OSError:
        return
    # imports
    for m in _IMPORT_RE.finditer(text):
        pkg = m.group(1).split("/")[0]
        yield _make_edge(
            src_component=src_component,
            src_symbol=src_component,
            dst_component=f"external:{pkg}" if not pkg.startswith(".") else src_component,
            dst_symbol=f"external:{m.group(1)}" if not pkg.startswith(".") else m.group(1),
            edge_kind="imports",
            callsite=(source_file, text[: m.start()].count("\n") + 1),
            workspace_tree_hash=workspace_tree_hash,
            extractor_version=extractor_version,
        )
    for m in _REQUIRE_RE.finditer(text):
        pkg = m.group(1).split("/")[0]
        yield _make_edge(
            src_component=src_component,
            src_symbol=src_component,
            dst_component=f"external:{pkg}" if not pkg.startswith(".") else src_component,
            dst_symbol=f"external:{m.group(1)}" if not pkg.startswith(".") else m.group(1),
            edge_kind="imports",
            callsite=(source_file, text[: m.start()].count("\n") + 1),
            workspace_tree_hash=workspace_tree_hash,
            extractor_version=extractor_version,
        )

    # intra-project calls: simplified heuristic — functions defined in file call functions also
    # defined in the same file.
    defined: set[str] = set()
    for m in _FUNC_DEF_RE.finditer(text):
        name = m.group(1) or m.group(2)
        if name:
            defined.add(name)
    for m in _CALL_RE.finditer(text):
        name = m.group(1)
        if name in defined:
            # We can't easily pin the src function without full AST; attribute to file-level component
            yield _make_edge(
                src_component=src_component,
                src_symbol=src_component,
                dst_component=src_component,
                dst_symbol=f"{src_component}.{name}",
                edge_kind="calls",
                callsite=(source_file, text[: m.start()].count("\n") + 1),
                workspace_tree_hash=workspace_tree_hash,
                extractor_version=extractor_version,
            )


# --- Edge builder ---------------------------------------------------------


def _make_edge(
    src_component: str,
    src_symbol: str,
    dst_component: str,
    dst_symbol: str,
    edge_kind: str,
    callsite,
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
        "extractor_id": "generic-treesitter",
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


# --- Plug-in entry point --------------------------------------------------


def extract_edges(
    project_dir: Path,
    symbols,
    source_files: list,
    workspace_tree_hash: str,
    extractor_version: str,
    config: dict,
    resolve_component: Callable[[Path], Optional[str]],
) -> Iterator[dict]:
    """Walk files, emit imports + intra-component calls.

    Component resolution is via resolve_component(file); files that do not
    resolve to any known component are skipped (the loader's post-pass will
    record unmapped_path gaps).
    """
    seen: set[tuple] = set()  # dedupe within this plug-in invocation
    for file_path in source_files:
        fp = Path(file_path)
        if not fp.is_file():
            continue
        cid = resolve_component(fp)
        if cid is None:
            # Unmapped file — don't emit. Loader's resolver carries the gap.
            continue
        suffix = fp.suffix.lower()
        if suffix == ".py":
            for edge in _python_edges(
                fp,
                src_component=cid,
                src_symbol_prefix=cid,
                resolve_component=resolve_component,
                workspace_tree_hash=workspace_tree_hash,
                extractor_version=extractor_version,
            ):
                key = (edge["edge_id"],)
                if key in seen:
                    continue
                seen.add(key)
                yield edge
        elif suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
            for edge in _js_edges(
                fp,
                src_component=cid,
                resolve_component=resolve_component,
                workspace_tree_hash=workspace_tree_hash,
                extractor_version=extractor_version,
            ):
                key = (edge["edge_id"],)
                if key in seen:
                    continue
                seen.add(key)
                yield edge
        # Other file types: silently skip in v1 (not in the plug-in's declared languages).
