"""forge_amendment_helper — CONTRACT-C1 (S029 design §7.3, WP-6).

Public API for forge's amendment-mode subprocess. Forge proposes amendments
to the user; bob applies them. This module is the deterministic bridge:

    read_undecided_deltas(project_root)
        Convenience reader; delegates to scope_delta.read_records(status_filter="undecided").
    draft_amendment(map_path, decisions) -> str
        Pure function. Takes the current contract-map YAML + per-delta decisions
        (kind, path, target_component, target_field) and returns amended YAML
        text with revision +=1. Performs NO filesystem writes, NO HMAC signing,
        NO ledger writes, NO scope_delta status mutations.
    return_to_bob(amended_path, deltas_resolved) -> dict
        Returns the {amended_map_path, deltas_resolved} bundle that bob's
        Step 8.7 consumes.

Authority boundaries (HARD-RULEs from S029 §7.3 + Q3b + Q5a):

- USER IS SOLE AUTHORITY for amendments. Forge cannot self-approve.
  This helper does not encode approval; it only mechanically applies a
  user-approved decision list.
- This module does NOT call:
    * scope_delta.update_status — that is bob's job (Step 8.7 hand-off).
    * pause_state.* — that is the scope_reaction module's role (CB4).
    * any HMAC / signing primitive — bob signs at Step 8.7.
- Tests enforce these invariants via a static-scan grep (see test_amendment.py).

Decisions schema (each item):
    {
        "delta_id": "scope-delta-...",
        "kind": "amend" | "exclude",
        "path": "<project-rel path>",
        # When kind == "amend":
        "target_component": "<component-id>",   # required (kebab-case `id` field of a component)
        "target_field": "source_paths"          # default; v1 only supports source_paths
        # When kind == "exclude":
        # path is appended to top-level excluded_paths
    }

Note: The production contract-map uses kebab-case `id` for component identifiers
(per gates.py V3 / REQUIRED_COMPONENT_FIELDS); the design doc prose used the term
`component_id` for clarity. The helper accepts the kebab-case identifier in the
`target_component` decision field and matches it against each component's `id`.

Author: bob spawn-4 (S029 WP-6)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Local import (relative-ish but Python won't actually relativize without a package)
import importlib.util
import sys


def _load_scope_delta_module():
    """Load scope_delta.py from the same directory at import time.

    We avoid `from . import scope_delta` because skills/_meta is not a package
    in the conventional sense (no __init__.py); the existing codebase uses
    direct sys.path additions in tests. Keep this self-contained.
    """
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    import scope_delta  # noqa: E402  (intentional late import)
    return scope_delta


# ---------------------------------------------------------------------------
# Public API — CONTRACT-C1
# ---------------------------------------------------------------------------


def read_undecided_deltas(project_root: Path) -> List[Dict[str, Any]]:
    """Return all scope_delta records with status='undecided'.

    Convenience over scope_delta.read_records(project_root, status_filter='undecided').
    Returns [] when the deltas dir is missing or no undecided records exist.
    """
    sd = _load_scope_delta_module()
    return sd.read_records(project_root, status_filter="undecided")


def draft_amendment(map_path: Path, decisions: List[Dict[str, Any]]) -> str:
    """Pure function: produce amended contract-map YAML text.

    Args:
        map_path: path to the CURRENT signed contract-map.yaml (read-only here).
        decisions: list of {delta_id, kind, path, target_component?, target_field?}

    Returns:
        YAML text of the amended map. revision is bumped (rev_N -> rev_N+1).

    Side-effects: NONE. No filesystem writes. No ledger writes. No status
    mutations. Bob owns those.

    Validation:
        - Map must parse and contain top-level `revision` (int) and `components`.
        - Each amend decision must reference an existing component_id.
        - target_field defaults to 'source_paths'; v1 only supports source_paths.
        - exclude decisions append to top-level `excluded_paths`.
        - Duplicate paths within the same target list are deduped.
    """
    if not map_path.is_file():
        raise FileNotFoundError(f"contract-map not found: {map_path}")
    text = map_path.read_text()
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("contract-map root must be a mapping")
    if "revision" not in data or not isinstance(data["revision"], int):
        raise ValueError("contract-map missing integer 'revision'")
    if "components" not in data or not isinstance(data["components"], list):
        raise ValueError("contract-map missing list 'components'")

    # Bump revision (Q5a: bob signs; we just propose the new rev number).
    data["revision"] = int(data["revision"]) + 1

    # Apply each decision.
    excluded = list(data.get("excluded_paths") or [])
    for d in decisions:
        kind = d.get("kind")
        path = d.get("path")
        if not kind or not path:
            raise ValueError(f"decision missing kind/path: {d}")
        if kind == "amend":
            target = d.get("target_component")
            if not target:
                raise ValueError(f"amend decision missing target_component: {d}")
            field = d.get("target_field") or "source_paths"
            if field != "source_paths":
                # v1 lock — match docstring + design §7.3.
                raise ValueError(
                    f"target_field {field!r} not supported in v1 (use 'source_paths')"
                )
            comp = _find_component(data["components"], target)
            if comp is None:
                raise ValueError(f"target_component not found: {target}")
            paths = list(comp.get(field) or [])
            if path not in paths:
                paths.append(path)
            comp[field] = paths
        elif kind == "exclude":
            if path not in excluded:
                excluded.append(path)
        else:
            raise ValueError(f"decision kind must be 'amend'|'exclude': {kind!r}")

    if excluded:
        data["excluded_paths"] = excluded

    # Emit YAML with a stable shape; preserve ordering of top-level keys roughly.
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def return_to_bob(amended_path: Path, deltas_resolved: List[str]) -> Dict[str, Any]:
    """Bundle for bob's Step 8.7 consumption.

    Args:
        amended_path: path where forge has written the proposed amended map
            (forge writes; bob signs+commits).
        deltas_resolved: list of delta_id strings that the user approved.

    Returns:
        {
            "amended_map_path": str,
            "deltas_resolved": [delta_id, ...]
        }
    """
    return {
        "amended_map_path": str(amended_path),
        "deltas_resolved": list(deltas_resolved),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_component(components: List[Dict[str, Any]], component_id: str) -> Optional[Dict[str, Any]]:
    """Match against the kebab-case `id` field used by production contract-maps
    (see gates.py REQUIRED_COMPONENT_FIELDS / V3 unique-kebab-ids check).
    Falls back to `component_id` for backward compatibility with synthetic
    test fixtures that may emit the design-doc form.
    """
    for c in components:
        if not isinstance(c, dict):
            continue
        if c.get("id") == component_id:
            return c
        # Backwards-compat / fixtures that follow the prose form.
        if c.get("component_id") == component_id:
            return c
    return None
