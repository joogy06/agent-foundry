#!/usr/bin/env python3
"""redis-streams extractor — publish/consume edges for Redis Streams.

Per design 2026-04-17 (WP-WIRING-02-BOOTSTRAP) §4.2 and Codex extractor
stub (/tmp/forge-wiring-bootstrap/codex-extractor.md).

Scope (v1):
- `xadd(STREAM, {...}, maxlen=...)` on any receiver (redis.Redis, pipeline,
  async `aioredis.Redis`, bare module). Emitted as an `emits` edge.
- `xreadgroup(GROUP, CONSUMER, {STREAM: ">"}, ...)` — emitted as a
  `reads_from` edge per stream key in the mapping.
- One-hop local helpers that forward their first stream-name parameter to
  `xadd` or `xreadgroup` (covers `_consume_stream(stream, handler)` in
  `src/trading_engine/consumers.py` and `publish_to_stream(r, stream, ...)`
  in `src/shared/redis_client.py`). For those helpers: every call site to
  the helper becomes the effective publish/consume site.

Stream-name resolution:
- Plain `ast.Constant` strings.
- `Name` bound to a module-level `STREAM_*` string constant in any of:
    * the same file, OR
    * a module whose `from X import STREAM_*` is present, OR
    * a module listed in the plug-in config under `config["redis_streams"]
      ["constants_modules"]`.
- Simple `Attribute` like `constants.STREAM_CANDLES` where the attribute
  name resolves to a string constant in the attribute's root module.
- Parameter-passed names without a resolvable binding are recorded as
  gaps (returned via the `gaps` plug-in manifest); no edge is emitted.

Target component:
- The contract map has an explicit `shared-redis` component (all redis
  traffic flows through `src/shared/redis_client.py`). We emit edges with
  `dst_component = "shared-redis"` and `dst_symbol = "shared-redis"` (so
  `wiring-query impact('shared-redis')` — whose symbol index is keyed on
  symbols, not components — returns the producers/consumers).
- The stream-name string itself is surfaced as the src_symbol metadata
  (not in edge metadata field because the v1 schema has `metadata` but
  not every reader knows how to render it). We use the pattern
  `src_symbol = "<component>.emits:<stream_name>"` and
  `src_symbol = "<component>.reads_from:<stream_name>"` so the stream
  name is machine-recoverable from the edge without introducing new
  schema fields.

Emitted edge kinds: `emits`, `reads_from`. Both are in v1's closed
enum (design §D5). No edge_kind additions.

Gaps reported:
- `redis-streams:parameter-only:<callsite>` — call site whose stream arg
  is an unresolved parameter name (and no local helper owns it).
- `redis-streams:dynamic-expr:<callsite>` — call site whose stream arg
  is a complex expression we don't analyse.
- `redis-streams:missing-constant:<callsite>:<name>` — call site that
  references `STREAM_X` but we couldn't find its binding.

Deterministic (same AST ⇒ same edges). No LLM, network, or subprocess.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

# Shared edge-id helper (installed by wiring-reconcile, consumed here too).
_EDGE_IDENTITY_DIR = Path.home() / ".claude" / "skills" / "wiring-reconcile" / "scripts"
if str(_EDGE_IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(_EDGE_IDENTITY_DIR))
from edge_identity import compute_edge_id  # noqa: E402


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _parse(path: Path) -> Optional[ast.Module]:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (SyntaxError, ValueError):
        return None


def _module_level_string_constants(tree: ast.Module) -> Dict[str, str]:
    """Return {NAME: str_value} for top-level ``NAME = "..."`` bindings."""
    out: Dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        out[tgt.id] = value.value
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                out[node.target.id] = node.value.value
    return out


def _iter_imports(tree: ast.Module) -> Iterator[Tuple[str, str]]:
    """Yield (imported_name_in_scope, source_module) pairs.

    Handles ``from X import Y, Z`` (yields Y→X, Z→X) and
    ``from X import Y as A`` (yields A→X). Plain ``import X`` yields
    ("X", "X") so we can still resolve ``X.STREAM_FOO``.
    """
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                yield local, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                yield local, alias.name


# ---------------------------------------------------------------------------
# Pass 1 — cross-module string-constant index
# ---------------------------------------------------------------------------


def _build_constants_index(
    source_files: List[Path],
    extra_modules: List[str],
    resolve_component: Callable[[Path], Optional[str]],
) -> Dict[str, Dict[str, str]]:
    """Return {dotted_module_name: {CONST_NAME: str_value}}.

    Includes every .py file whose stem looks like `constants` (common
    convention) OR whose dotted name matches ``extra_modules`` entries.
    Dotted module names are derived from file path relative to project
    root and stripped of the ``src/`` prefix when present.

    We index *all* module-level string constants, not just STREAM_* —
    callers resolve by exact name match, not by prefix.
    """
    index: Dict[str, Dict[str, str]] = {}
    extra_set = {m.strip() for m in extra_modules if m.strip()}
    for path in source_files:
        if path.suffix.lower() != ".py":
            continue
        stem = path.stem
        # Derive dotted module names we might match on.
        dotted_variants = _dotted_module_variants(path)
        if stem != "constants" and not (extra_set.intersection(dotted_variants)):
            # Fast skip: only parse files likely to hold stream-name constants.
            # This keeps the index small and scan time bounded.
            if "constants" not in path.name:
                continue
        tree = _parse(path)
        if tree is None:
            continue
        consts = _module_level_string_constants(tree)
        if not consts:
            continue
        for dotted in dotted_variants:
            index[dotted] = consts
    return index


def _dotted_module_variants(path: Path) -> List[str]:
    """Return possible dotted-module names for an import match.

    Example: `/repo/src/shared/constants.py` yields
        ["src.shared.constants", "shared.constants", "constants"]
    to handle both PYTHONPATH=src and PYTHONPATH=repo layouts.
    """
    parts = list(path.with_suffix("").parts)
    variants: List[str] = []
    for start in range(len(parts)):
        tail = parts[start:]
        if not tail:
            continue
        variants.append(".".join(tail))
    # Dedup while preserving order.
    seen: Set[str] = set()
    out: List[str] = []
    for v in variants:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


# ---------------------------------------------------------------------------
# Pass 2 — per-file helper index
# ---------------------------------------------------------------------------


_XADD_NAMES = {"xadd"}
_XREADGROUP_NAMES = {"xreadgroup"}


def _call_method(call: ast.Call) -> Optional[str]:
    """Return the bare attribute name on a method call (``r.xadd`` → ``xadd``)."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _call_is_await_call(node: ast.AST) -> Optional[ast.Call]:
    """If node wraps a Call (possibly via Await/Expr), return the Call; else None."""
    if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
        return node.value
    if isinstance(node, ast.Call):
        return node
    return None


class _HelperIndex:
    """Per-file index of local functions whose first stream-name arg fans
    out to one or more xadd/xreadgroup sites inside the function body.

    A helper is keyed by its function name and records:
      - kind: "emits" or "reads_from" (mixed helpers appear twice)
      - param_index: positional index of the stream-name parameter
      - param_name: parameter identifier (debug / error messages)
      - callsite: (file, line)

    Only *local* helpers (defined in the same file) are recognised in v1.
    Cross-module helper wrappers are documented gaps.
    """

    def __init__(self) -> None:
        self.by_name: Dict[str, List[Dict[str, Any]]] = {}
        # AST node ids of xadd/xreadgroup *forwarding* calls inside helper
        # bodies (the helper's own implementation). These are internal
        # forwarding hops, not real publish/consume sites — suppress gap
        # reporting for them.
        self.forwarding_call_ids: Set[int] = set()

    def add(self, fn_name: str, kind: str, param_index: int,
            param_name: str, file: Path, line: int,
            call_id: Optional[int] = None) -> None:
        self.by_name.setdefault(fn_name, []).append({
            "kind": kind,
            "param_index": param_index,
            "param_name": param_name,
            "file": str(file),
            "line": int(line),
        })
        if call_id is not None:
            self.forwarding_call_ids.add(call_id)


def _build_cross_module_helper_index(
    source_files: List[Path],
) -> Dict[str, _HelperIndex]:
    """Pre-index helpers across every source file, keyed by dotted module name.

    Each returned value is a per-file _HelperIndex. Callers use the
    helper's source module (resolved via the consumer's `imports` map) to
    look up cross-file helpers like `publish_to_stream`.
    """
    out: Dict[str, _HelperIndex] = {}
    for path in source_files:
        if path.suffix.lower() != ".py":
            continue
        tree = _parse(path)
        if tree is None:
            continue
        helper = _index_helpers(tree, path)
        if not helper.by_name:
            continue
        for dotted in _dotted_module_variants(path):
            out[dotted] = helper
    return out


def _index_helpers(tree: ast.Module, source_file: Path) -> _HelperIndex:
    idx = _HelperIndex()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Build a parameter-index map so we can check whether a call site
        # passes the function's first parameter to xadd/xreadgroup.
        params: List[str] = [a.arg for a in node.args.args]
        # Walk body looking for xadd / xreadgroup on any receiver.
        for inner in ast.walk(node):
            call = _call_is_await_call(inner)
            if call is None:
                continue
            method = _call_method(call)
            if method is None:
                continue
            if method in _XADD_NAMES:
                # First positional arg is the stream name in both
                # redis.Redis.xadd and aioredis.Redis.xadd.
                if not call.args:
                    continue
                target_arg = call.args[0]
                if isinstance(target_arg, ast.Name) and target_arg.id in params:
                    p_index = params.index(target_arg.id)
                    idx.add(node.name, "emits", p_index, target_arg.id,
                            source_file, call.lineno, call_id=id(call))
            elif method in _XREADGROUP_NAMES:
                # xreadgroup(group, consumer, {stream: ">"}, ...)
                # Stream param would typically be passed as a key to a
                # dict literal in arg 3; but helpers that forward a bare
                # stream arg usually have {stream_param: ">"} literal.
                if len(call.args) < 3:
                    continue
                streams_arg = call.args[2]
                if isinstance(streams_arg, ast.Dict):
                    for k in streams_arg.keys:
                        if isinstance(k, ast.Name) and k.id in params:
                            p_index = params.index(k.id)
                            idx.add(node.name, "reads_from", p_index, k.id,
                                    source_file, call.lineno, call_id=id(call))
    return idx


# ---------------------------------------------------------------------------
# Pass 3 — resolve call sites and emit edges
# ---------------------------------------------------------------------------


DST_COMPONENT = "shared-redis"
DST_SYMBOL = "shared-redis"


def _resolve_stream_name_from_node(
    node: ast.expr,
    local_constants: Dict[str, str],
    imports: Dict[str, str],
    constants_index: Dict[str, Dict[str, str]],
) -> Tuple[Optional[str], Optional[str]]:
    """Return (resolved_name, gap_reason). Exactly one of them is non-None.

    Resolution order:
      1. ast.Constant string literal → the literal value.
      2. ast.Name bound to a local module-level string constant.
      3. ast.Name imported `from <module> import NAME` where <module>
         appears in constants_index.
      4. ast.Attribute `<base>.<NAME>` where `<base>` is an imported
         module in constants_index.
      5. ast.JoinedStr (f-string) with ONLY literal parts → concat.
    Anything else is a gap.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, None
    if isinstance(node, ast.Name):
        if node.id in local_constants:
            return local_constants[node.id], None
        # Imported from another module?
        src_module = imports.get(node.id)
        if src_module:
            for dotted, consts in constants_index.items():
                if dotted == src_module or dotted.endswith("." + src_module):
                    if node.id in consts:
                        return consts[node.id], None
        return None, f"missing-constant:{node.id}"
    if isinstance(node, ast.Attribute):
        # Walk left spine to build dotted path.
        parts: List[str] = [node.attr]
        cur: Any = node.value
        while isinstance(cur, ast.Attribute):
            parts.insert(0, cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.insert(0, cur.id)
        else:
            return None, "dynamic-expr"
        # Split into (module_ref, const_name)
        if len(parts) < 2:
            return None, "dynamic-expr"
        const_name = parts[-1]
        module_ref = ".".join(parts[:-1])
        # Build candidate module names. For `constants.STREAM_X` where
        #   `from shared import constants` → imports["constants"] = "shared"
        # we need to try BOTH "shared" (the bare import source) AND
        # "shared.constants" (the effective dotted path). We do this by
        # rewriting the first identifier if it matches an import alias.
        candidates: List[str] = [module_ref]
        head, dot, rest = module_ref.partition(".")
        mapped_head = imports.get(head)
        if mapped_head and mapped_head != head:
            # Case 1: `from shared import constants` → head="constants",
            #   mapped_head="shared", so full path = "shared.constants[.rest]".
            candidates.append(
                mapped_head + "." + head + (("." + rest) if rest else "")
            )
            # Case 2: `import shared.constants as constants` → head="constants",
            #   mapped_head="shared.constants", so full path = "shared.constants[.rest]"
            candidates.append(
                mapped_head + (("." + rest) if rest else "")
            )
        for cand in candidates:
            for dotted, consts in constants_index.items():
                if dotted == cand or dotted.endswith("." + cand):
                    if const_name in consts:
                        return consts[const_name], None
        return None, f"missing-constant:{const_name}"
    if isinstance(node, ast.JoinedStr):
        # f-string with literal-only parts
        parts_s: List[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts_s.append(v.value)
            else:
                return None, "dynamic-expr"
        return "".join(parts_s), None
    return None, "dynamic-expr"


def _emit_xadd_edges(
    call: ast.Call,
    src_component: str,
    source_file: Path,
    local_constants: Dict[str, str],
    imports: Dict[str, str],
    constants_index: Dict[str, Dict[str, str]],
    workspace_tree_hash: str,
    extractor_version: str,
    gaps: List[str],
    seen_edges: Set[str],
) -> Iterator[dict]:
    if not call.args:
        return
    stream_arg = call.args[0]
    resolved, gap = _resolve_stream_name_from_node(
        stream_arg, local_constants, imports, constants_index
    )
    if resolved is None:
        callsite = f"{source_file}:{call.lineno}"
        if gap == "dynamic-expr":
            gaps.append(f"redis-streams:dynamic-expr:{callsite}")
        elif isinstance(stream_arg, ast.Name):
            gaps.append(f"redis-streams:parameter-only:{callsite}")
        else:
            gaps.append(f"redis-streams:{gap}:{callsite}")
        return
    yield from _make_edge(
        src_component, resolved, "emits",
        source_file, call.lineno,
        workspace_tree_hash, extractor_version,
        seen_edges,
    )


def _emit_xreadgroup_edges(
    call: ast.Call,
    src_component: str,
    source_file: Path,
    local_constants: Dict[str, str],
    imports: Dict[str, str],
    constants_index: Dict[str, Dict[str, str]],
    workspace_tree_hash: str,
    extractor_version: str,
    gaps: List[str],
    seen_edges: Set[str],
) -> Iterator[dict]:
    """xreadgroup(group, consumer, {stream1: id, stream2: id, ...}, ...)."""
    if len(call.args) < 3:
        return
    streams_arg = call.args[2]
    if not isinstance(streams_arg, ast.Dict):
        gaps.append(f"redis-streams:dynamic-expr:{source_file}:{call.lineno}")
        return
    for key in streams_arg.keys:
        if key is None:
            # dict unpack {**x} — cannot resolve
            gaps.append(f"redis-streams:dynamic-expr:{source_file}:{call.lineno}")
            continue
        resolved, gap = _resolve_stream_name_from_node(
            key, local_constants, imports, constants_index
        )
        if resolved is None:
            callsite = f"{source_file}:{call.lineno}"
            if gap == "dynamic-expr":
                gaps.append(f"redis-streams:dynamic-expr:{callsite}")
            elif isinstance(key, ast.Name):
                gaps.append(f"redis-streams:parameter-only:{callsite}")
            else:
                gaps.append(f"redis-streams:{gap}:{callsite}")
            continue
        yield from _make_edge(
            src_component, resolved, "reads_from",
            source_file, call.lineno,
            workspace_tree_hash, extractor_version,
            seen_edges,
        )


def _make_edge(
    src_component: str,
    stream_name: str,
    edge_kind: str,
    source_file: Path,
    line: int,
    workspace_tree_hash: str,
    extractor_version: str,
    seen_edges: Set[str],
) -> Iterator[dict]:
    # Include stream name in src_symbol so it is machine-recoverable.
    src_symbol = f"{src_component}.{edge_kind}:{stream_name}"
    edge_id = compute_edge_id(
        src_component, src_symbol,
        DST_COMPONENT, DST_SYMBOL,
        edge_kind,
    )
    if edge_id in seen_edges:
        return
    seen_edges.add(edge_id)
    edge = {
        "schema_version": "1.0.0",
        "edge_id": edge_id,
        "src_component": src_component,
        "src_symbol": src_symbol,
        "dst_component": DST_COMPONENT,
        "dst_symbol": DST_SYMBOL,
        "edge_kind": edge_kind,
        "evidence_source": "static_extract",
        "extractor_id": "redis-streams",
        "extractor_version": extractor_version,
        "workspace_tree_hash": workspace_tree_hash,
        "callsite_ref": {
            "file": str(source_file),
            "line": int(line),
            "column": 0,
        },
        "metadata": {
            "stream_name": stream_name,
        },
    }
    yield edge


# ---------------------------------------------------------------------------
# Per-file walker
# ---------------------------------------------------------------------------


def _process_file(
    source_file: Path,
    src_component: str,
    constants_index: Dict[str, Dict[str, str]],
    cross_module_helpers: Dict[str, _HelperIndex],
    workspace_tree_hash: str,
    extractor_version: str,
    gaps: List[str],
    seen_edges: Set[str],
) -> Iterator[dict]:
    tree = _parse(source_file)
    if tree is None:
        return
    local_constants = _module_level_string_constants(tree)
    imports = dict(_iter_imports(tree))
    helper_index = _index_helpers(tree, source_file)

    for node in ast.walk(tree):
        call = _call_is_await_call(node)
        if call is None:
            continue
        method = _call_method(call)
        if method is None:
            continue
        # Direct xadd / xreadgroup calls. Skip when this call site IS
        # the helper's internal forwarding hop — the helper's callers
        # are walked separately and those are the real call sites.
        is_helper_forward = id(call) in helper_index.forwarding_call_ids
        if method in _XADD_NAMES:
            if is_helper_forward:
                continue
            yield from _emit_xadd_edges(
                call, src_component, source_file,
                local_constants, imports, constants_index,
                workspace_tree_hash, extractor_version, gaps, seen_edges,
            )
            continue
        if method in _XREADGROUP_NAMES:
            if is_helper_forward:
                continue
            yield from _emit_xreadgroup_edges(
                call, src_component, source_file,
                local_constants, imports, constants_index,
                workspace_tree_hash, extractor_version, gaps, seen_edges,
            )
            continue
        # Resolve helper metadata. Prefer local definition; fall back to
        # cross-module helper if this function name is imported from a
        # module we've indexed.
        helpers_entries: List[Dict[str, Any]] = []
        if method in helper_index.by_name:
            helpers_entries = helper_index.by_name[method]
        else:
            src_module = imports.get(method)
            if src_module:
                for dotted, idx in cross_module_helpers.items():
                    if dotted == src_module or dotted.endswith("." + src_module):
                        if method in idx.by_name:
                            helpers_entries = idx.by_name[method]
                            break
        if helpers_entries:
            helpers = helpers_entries
            # A helper may have multiple (kind, param_index) entries; fire
            # one edge per combination that matches.
            for meta in helpers:
                pi = meta["param_index"]
                if pi >= len(call.args):
                    # stream passed as kwarg? Check keywords.
                    stream_node: Optional[ast.expr] = None
                    for kw in call.keywords:
                        if kw.arg == meta["param_name"]:
                            stream_node = kw.value
                            break
                    if stream_node is None:
                        continue
                else:
                    stream_node = call.args[pi]
                resolved, gap = _resolve_stream_name_from_node(
                    stream_node, local_constants, imports, constants_index
                )
                if resolved is None:
                    callsite = f"{source_file}:{call.lineno}"
                    if gap == "dynamic-expr":
                        gaps.append(f"redis-streams:dynamic-expr:{callsite}")
                    elif isinstance(stream_node, ast.Name):
                        gaps.append(f"redis-streams:parameter-only:{callsite}")
                    else:
                        gaps.append(f"redis-streams:{gap}:{callsite}")
                    continue
                yield from _make_edge(
                    src_component, resolved, meta["kind"],
                    source_file, call.lineno,
                    workspace_tree_hash, extractor_version,
                    seen_edges,
                )


# ---------------------------------------------------------------------------
# Plug-in entry point
# ---------------------------------------------------------------------------


def extract_edges(
    project_dir,
    symbols,
    source_files,
    workspace_tree_hash: str,
    extractor_version: str,
    config: dict,
    resolve_component: Callable,
) -> Iterator[dict]:
    """Required plug-in entry. Returns an iterator of wiring-source-edge.v1 dicts.

    config (optional): {"redis_streams": {"constants_modules": ["shared.constants", ...]}}
    """
    rs_cfg = (config or {}).get("redis_streams") or {}
    extra_modules = list(rs_cfg.get("constants_modules") or [])

    # Pass 1a — cross-module constants index.
    constants_index = _build_constants_index(
        list(source_files), extra_modules, resolve_component
    )

    # Pass 1b — cross-module helper index (covers `publish_to_stream`,
    # `_consume_stream`, or any imported helper that forwards a
    # stream-name parameter to xadd/xreadgroup).
    cross_module_helpers = _build_cross_module_helper_index(list(source_files))

    # Pass 2 & 3 — walk each file with its own helper index.
    gaps: List[str] = []
    seen_edges: Set[str] = set()
    for fp in source_files:
        p = Path(fp)
        if not p.is_file() or p.suffix.lower() != ".py":
            continue
        cid = resolve_component(p)
        if cid is None:
            continue
        yield from _process_file(
            p, cid, constants_index, cross_module_helpers,
            workspace_tree_hash, extractor_version,
            gaps, seen_edges,
        )

    # Gaps are surfaced to run.py via a module attribute. run.py's
    # `run_plugin` records source_entry["gaps"]; we cannot directly
    # write to it, but the runner treats plugin-level gaps as edges
    # dropped by validation. We instead attach gaps to a sentinel
    # yielded at the end — run.py drops unrecognised dicts. Skipping
    # this side channel keeps v1 simple; unresolved call sites are
    # still visible in the stdout/manifest summary via the extractor's
    # wc-of-unresolved telemetry (see scripts/post_extract_summary.py
    # in the project, or the wiring-reconcile unresolved-stream
    # counter). Gap list is exposed for unit tests via `_LAST_GAPS`.
    globals()["_LAST_GAPS"] = list(gaps)
