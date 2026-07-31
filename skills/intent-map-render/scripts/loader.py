"""loader.py — read input artifacts for diagram rendering."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore[import-untyped]
except ImportError as e:
    raise RuntimeError("pyyaml required for intent-map-render") from e


class LoaderError(Exception):
    """Raised when an input artifact is missing or malformed."""


def load_intent_map(path: Path) -> Dict[str, Any]:
    """Load an intent-map.yaml. May be either:

      (a) a single functional-intent.v1 document (one component), or
      (b) a collection — yaml dict with "components: [<funct-intent>...]"

    Returns a normalised dict with key "components" mapping to a list.
    """
    if not path.is_file():
        raise LoaderError(f"intent-map not found at {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise LoaderError(f"intent-map yaml parse error: {e}") from e
    if not isinstance(data, dict):
        raise LoaderError(f"intent-map top-level must be mapping, got {type(data).__name__}")
    if "components" in data and isinstance(data["components"], list):
        return data
    # Single-document fallback (functional-intent.v1 directly)
    if "component_id" in data:
        return {"components": [data]}
    return {"components": []}


def load_wiring_snapshot(path: Path) -> Dict[str, Any]:
    """Load wiring-snapshot.v1 or v1.1 JSON."""
    if not path.is_file():
        raise LoaderError(f"wiring snapshot not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise LoaderError(f"wiring snapshot json error: {e}") from e
    if not isinstance(data, dict):
        raise LoaderError(f"wiring snapshot must be mapping, got {type(data).__name__}")
    return data


def load_api_delta(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """Load an api-delta JSON. Returns None if path is None (e.g. mode-a)."""
    if path is None:
        return None
    if not path.is_file():
        raise LoaderError(f"api-delta not found at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise LoaderError(f"api-delta json error: {e}") from e
