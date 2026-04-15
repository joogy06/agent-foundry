# Plug-in Author Guide — wiring-extract-static v1

**Status:** frozen as of WP-2 (2026-04-15). WP-3 plug-ins (FastAPI, Express) and all future v2 plug-ins MUST conform to this contract.

**Source of truth for edge identity:** `~/.claude/skills/wiring-reconcile/scripts/edge_identity.py`. Never duplicate — always `import edge_identity` and call `compute_edge_id(...)`. Two plug-ins emitting the "same logical edge" (five-tuple match) MUST produce bit-identical `edge_id`.

---

## 1. Directory layout

Each plug-in lives at:

```
~/.claude/skills/wiring-extract-static/extractors/<plugin_name>/
├── plugin.json        # manifest (required)
└── extractor.py       # extract_edges() entry point (required)
```

`<plugin_name>` is the canonical id (e.g. `fastapi`, `express`, `generic-treesitter`). Lowercase, dashes, no spaces. Matches `plugin.json.id`.

## 2. `plugin.json` manifest

```json
{
  "id": "fastapi",
  "version": "1.0.0",
  "target_framework": "fastapi",
  "languages": ["python"],
  "edge_kinds": ["routes_to", "calls", "listens"],
  "is_fallback": false,
  "description": "FastAPI routes/Depends/events → static edges"
}
```

Required fields:

| field | type | constraints |
|---|---|---|
| `id` | string | non-empty, matches directory name |
| `version` | string | semver `MAJOR.MINOR.PATCH` (pattern enforced by wiring-source-edge.v1) |
| `target_framework` | string | framework discriminator: `fastapi`, `express`, `generic` (for fallback), etc. |
| `languages` | array[string] | one or more of `python`, `typescript`, `javascript`, `generic` |
| `edge_kinds` | array[string] | subset of the `edge_kind` enum in `wiring-source-edge.v1.json` |
| `is_fallback` | boolean | `true` only for `generic-treesitter`; at most one fallback per loader invocation |
| `description` | string | one-line human summary |

Unknown fields are permitted (forward-compat) but ignored by the v1 loader.

## 3. `extractor.py` entry point

```python
from pathlib import Path
from typing import Iterator, Callable, Optional
from collections.abc import Mapping

def extract_edges(
    project_dir: Path,
    symbols: Mapping,                     # unified symbol table (see §5); may be empty if SCIP unavailable
    source_files: list[Path],             # files matching this plug-in's languages, filtered to those under the project
    workspace_tree_hash: str,             # 40-hex git write-tree
    extractor_version: str,               # read from plugin.json.version (loader passes it in)
    config: dict,                         # free-form, from .ledger/config.yaml plugin section
    resolve_component: Callable[[Path], Optional[str]],  # file-path → contract-map component id, or None
) -> Iterator[dict]:
    """Yield edges conforming to wiring-source-edge.v1.

    REQUIREMENTS:
    - Every yielded edge MUST validate against
      ~/.claude/skills/wiring-extract-static/schemas/wiring-source-edge.v1.json
    - edge_id MUST be computed via edge_identity.compute_edge_id(...)
    - src_component / dst_component MUST come from resolve_component(file)
      or be explicitly declared (e.g. "external:requests") — NEVER free-form.
    - evidence_source MUST be "static_extract"
    - extractor_id MUST equal plugin.json.id
    - extractor_version MUST equal the version passed in (matches plugin.json.version)
    - emitted_at is set by the loader if absent; plug-in may set it explicitly.

    GUARANTEES:
    - Exceptions propagate to loader; loader records status=failed for this source.
    - Deterministic: same inputs → same edges in same order (enables reproducibility tests).
    - No LLM calls, no network I/O, no subprocess outside the project tree.
    """
```

## 4. Unmapped paths

If a file cannot be resolved to a component (the contract map has no matching `source_paths` glob for it), the plug-in has two options:

1. **Skip the file**, and record the gap by yielding nothing for it. The loader records a manifest gap entry `unmapped_path: <file>` on behalf of the plug-in (the plug-in does not need to do this directly — the loader inspects every path the plug-in iterated).
2. **Yield nothing and do not track**. The loader's post-pass will discover the unmapped files anyway.

Plug-ins MUST NOT invent component names. Re-check `resolve_component(file)` before every emission.

## 5. Symbol table (`symbols` argument)

In v1, the `symbols` parameter is a plain `dict` (may be empty):

```python
{
  "by_file": { "<abs/path>": [<SymbolEntry>, ...] },
  "by_name": { "<qualified.name>": <SymbolEntry> },
}
```

Where `SymbolEntry` is a dict with at least:

```python
{"name": "auth.validateToken", "file": "/abs/path/auth.py", "line": 42, "kind": "function"}
```

- If SCIP indexers are unavailable for the plug-in's language(s), `symbols == {"by_file": {}, "by_name": {}}`. Plug-ins MUST tolerate this (fall back to tree-sitter or AST-walk as appropriate).
- v1 does NOT guarantee any particular symbol schema beyond these two dict fields. Plug-ins should defensively `.get()` every key.

## 6. Required output fields on each yielded edge

Minimum populated keys on each `edge` dict (loader fills in defaults for the rest):

```python
{
  "schema_version": "1.0.0",
  "edge_id": edge_identity.compute_edge_id(src_comp, src_sym, dst_comp, dst_sym, kind),
  "src_component": <component id from resolve_component or "external:<id>">,
  "src_symbol": "<qualified dotted name>",
  "dst_component": <component id>,
  "dst_symbol": "<qualified dotted name>",
  "edge_kind": "routes_to" | "calls" | ...,   # must be in the v1 enum
  "evidence_source": "static_extract",
  "extractor_id": "<same as plugin.json.id>",
  "extractor_version": extractor_version,
  "workspace_tree_hash": workspace_tree_hash,
  "emitted_at": "<iso8601 Zulu>",                 # loader will fill if absent
  # optional:
  "callsite_ref": {"file": ..., "line": ..., "column": ...},
  "confidence": 0.0..1.0,
  "metadata": { ... },
}
```

## 7. External components

For edges that cross into external libraries (`requests.get`, `sqlalchemy.select`, etc.) that are NOT in the project's contract map:

- `dst_component` should be set to `external:<package-or-service>` (e.g. `external:requests`, `external:postgres`).
- `dst_symbol` should include the external qualified name (`external:requests.get`).

This keeps edge_ids stable and allows downstream consumers (impact query, G4) to treat externals as first-class terminal nodes without inventing ad-hoc component ids.

## 8. Performance expectations

- Plug-in `extract_edges` should run in <30s on a 50k-LOC repo. Exceeding this is permitted but the loader records `duration_seconds` and large values are flagged.
- No file I/O outside `project_dir`. No writes (plug-ins are pure functions from inputs to edges).
- No subprocess calls other than what the loader has already staged (SCIP indexer output is passed in via `symbols`).

## 9. Schema validation

Loader runs `jsonschema.validate(edge, wiring-source-edge.v1.json, format_checker=FORMAT_CHECKER)` on each yielded edge **in loader-invoked validation mode** (enabled by default). Plug-ins that yield invalid edges have those specific edges dropped with a `malformed_edge` entry recorded in the manifest gaps.

## 10. Testing convention

Each plug-in MUST ship with:

```
extractors/<plugin_name>/
├── plugin.json
├── extractor.py
└── (optional) tests/
    └── test_<plugin_name>.py         # unit-level checks beyond the shared fixture smoke test
```

The end-to-end fixture smoke tests live at:

```
~/.claude/skills/wiring-extract-static/fixtures/<plugin>-minimal/
├── <minimal project tree>
└── expected-edges.json               # canonical list the plug-in must emit

~/.claude/skills/wiring-extract-static/tests/test_plugin_<plugin>.py
```

## 11. Versioning

- Breaking changes to the plug-in API (signature of `extract_edges`) trigger a v2 guide. v1 plug-ins continue to work until explicit deprecation.
- Individual plug-ins are versioned independently (their `plugin.json.version`), separate from the skill's top-level version.
