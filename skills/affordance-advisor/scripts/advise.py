#!/usr/bin/env python3
"""advise.py — workflow-completion advisor.

Reads the active host CLI from detect_host_cli.py, loads the matching
registry/<host>.yaml plus any utility CLIs whose activation gate is "tool on
PATH", filters affordances by --completion-kind / --orchestrator /
--severity-cap, and emits a JSON array of applicable hints.

Empty array when:
  - active host is "unknown"
  - no affordances match the filters
  - every match exceeds --severity-cap

The script is deterministic: same flags + same env + same registry contents
-> same bytes on stdout. No hidden state, no file writes.

stdlib-only (json, re, pathlib, argparse, shutil, subprocess for invoking
the sibling detect_host_cli.py). YAML is parsed with a tiny embedded parser
that handles the closed schema in registry/*.yaml — no third-party deps.

Usage:
    advise.py --completion-kind ui-change
    advise.py --completion-kind ui-change --orchestrator bob
    advise.py --completion-kind ui-change --orchestrator bob --severity-cap medium
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


_RISK_ORDER = {"low": 1, "medium": 2, "high": 3}
_VALID_RISKS = set(_RISK_ORDER)


# ─── locate the skill root ─────────────────────────────────────────────────────

def _skill_root() -> Path:
    """Return the affordance-advisor/ directory containing this script."""
    return Path(__file__).resolve().parent.parent


def _registry_dir() -> Path:
    return _skill_root() / "registry"


# ─── host detection (delegates to detect_host_cli.py) ──────────────────────────

def _detect_host_cli() -> str:
    """Invoke detect_host_cli.py in a subprocess and return the printed token.

    Done as a subprocess (not an import) to keep the detection contract
    machine-readable — any caller in any language can shell out to the same
    binary and get the same string.
    """
    script = _skill_root() / "scripts" / "detect_host_cli.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    out = (proc.stdout or "").strip()
    return out or "unknown"


# ─── minimal YAML loader (closed schema) ───────────────────────────────────────
#
# We parse a strict subset:
#   - top-level scalar keys: schema_version, host_cli, affordances, activation
#   - activation is a single-key mapping (tool_on_path: <name>)
#   - affordances is a list of mappings
#   - each affordance is:
#       id, command, risk_class, hint, reference -> strings
#       workflow_match -> {orchestrator: [list], completion_kind: [list]}
#       skip_when      -> {orchestrator_failed: bool, already_suggested_this_session: bool}
#   - block-scalar hints use the leading '|' marker and are indent-stripped
#
# Everything else fails — by design. This is not a general YAML parser, it's
# a closed-schema validator that doubles as a loader.

class RegistryParseError(ValueError):
    pass


def _parse_yaml_registry(text: str, source: str) -> Dict[str, Any]:
    """Parse one registry/*.yaml file into a Python dict."""
    lines = text.splitlines()
    i = 0
    result: Dict[str, Any] = {}

    def _skip_blank_and_comment(idx: int) -> int:
        while idx < len(lines):
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith("#"):
                idx += 1
                continue
            return idx
        return idx

    while i < len(lines):
        i = _skip_blank_and_comment(i)
        if i >= len(lines):
            break
        raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        if raw.startswith(" "):
            # Top-level indent — malformed
            raise RegistryParseError(f"{source}: unexpected indent at line {i+1}")
        if ":" not in raw:
            raise RegistryParseError(f"{source}: missing ':' at line {i+1}")

        key, _, val = raw.partition(":")
        key = key.strip()
        val = val.strip()

        if key == "affordances":
            if val and val != "[]":
                raise RegistryParseError(
                    f"{source}: 'affordances:' must be either '[]' or a block list at line {i+1}"
                )
            if val == "[]":
                result["affordances"] = []
                i += 1
                continue
            # Parse block list of mappings
            i += 1
            affordances, i = _parse_affordance_list(lines, i, source)
            result["affordances"] = affordances
            continue

        if key == "activation":
            if val:
                raise RegistryParseError(
                    f"{source}: 'activation:' must be a mapping (no inline value) at line {i+1}"
                )
            i += 1
            activation: Dict[str, Any] = {}
            while i < len(lines):
                sub = lines[i]
                if not sub.strip() or sub.lstrip().startswith("#"):
                    i += 1
                    continue
                if not sub.startswith("  "):
                    break
                if ":" not in sub:
                    raise RegistryParseError(f"{source}: malformed activation entry at line {i+1}")
                sk, _, sv = sub.strip().partition(":")
                activation[sk.strip()] = sv.strip()
                i += 1
            result["activation"] = activation
            continue

        # Plain scalar key
        result[key] = val
        i += 1

    return result


def _parse_affordance_list(lines: List[str], i: int, source: str) -> (List[Dict[str, Any]], int):
    """Starting at the first line after 'affordances:', parse a block list."""
    out: List[Dict[str, Any]] = []
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        # Block-list item begins with "  - "
        if not raw.startswith("  - "):
            break
        # Item body is the rest of "  - key: value" plus subsequent indented lines
        item, i = _parse_affordance_item(lines, i, source)
        out.append(item)
    return out, i


def _parse_affordance_item(lines: List[str], i: int, source: str) -> (Dict[str, Any], int):
    """Parse one affordance starting with '  - '."""
    item: Dict[str, Any] = {}
    first = lines[i]
    body = first[len("  - "):]
    if ":" not in body:
        raise RegistryParseError(f"{source}: malformed first key in affordance at line {i+1}")
    fk, _, fv = body.partition(":")
    item[fk.strip()] = _scalar(fv.strip())
    i += 1

    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        # The item body is indented with at least 4 spaces ("    "); a new
        # affordance starts at "  - "; a new top-level key has no leading space.
        if raw.startswith("  - "):
            break
        if not raw.startswith("    "):
            break

        # Strip the 4-space prefix to get the key
        stripped = raw[4:]
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            i += 1
            continue

        if ":" not in stripped:
            raise RegistryParseError(f"{source}: malformed line {i+1}: {raw!r}")
        key, _, val = stripped.partition(":")
        key = key.strip()
        val_raw = val.strip()

        # Mapping: workflow_match or skip_when
        if not val_raw and key in ("workflow_match", "skip_when"):
            i += 1
            sub_map, i = _parse_indented_mapping(lines, i, indent=6, source=source)
            item[key] = sub_map
            continue

        # Block scalar (hint: |)
        if val_raw == "|":
            i += 1
            block, i = _parse_block_scalar(lines, i, indent=6)
            item[key] = block
            continue

        # Inline scalar
        item[key] = _scalar(val_raw)
        i += 1

    return item, i


def _parse_indented_mapping(lines: List[str], i: int, indent: int, source: str) -> (Dict[str, Any], int):
    """Parse a mapping where every key is indented `indent` spaces."""
    out: Dict[str, Any] = {}
    prefix = " " * indent
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if not raw.startswith(prefix):
            break
        stripped = raw[indent:]
        if stripped.startswith(" "):
            # Deeper nesting — only inline lists / scalars expected at this level
            break
        if ":" not in stripped:
            raise RegistryParseError(f"{source}: malformed mapping line {i+1}: {raw!r}")
        key, _, val = stripped.partition(":")
        key = key.strip()
        val_raw = val.strip()
        if val_raw:
            out[key] = _scalar(val_raw)
        else:
            # Could be a nested list — only `orchestrator` / `completion_kind` use this
            i += 1
            items, i = _parse_indented_list(lines, i, indent=indent + 2, source=source)
            out[key] = items
            continue
        i += 1
    return out, i


def _parse_indented_list(lines: List[str], i: int, indent: int, source: str) -> (List[Any], int):
    """Parse a block list where every '- item' is indented `indent` spaces."""
    out: List[Any] = []
    prefix = " " * indent + "- "
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if not raw.startswith(prefix):
            break
        item_raw = raw[len(prefix):].strip()
        out.append(_scalar(item_raw))
        i += 1
    return out, i


def _parse_block_scalar(lines: List[str], i: int, indent: int) -> (str, int):
    """Parse a '|' literal block scalar at the given indent."""
    prefix = " " * indent
    collected: List[str] = []
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            # Preserve blank lines inside the block
            collected.append("")
            i += 1
            continue
        if not raw.startswith(prefix):
            break
        collected.append(raw[indent:])
        i += 1
    # Strip leading/trailing blank lines, join with newline
    while collected and not collected[0]:
        collected.pop(0)
    while collected and not collected[-1]:
        collected.pop()
    return "\n".join(collected), i


def _scalar(raw: str) -> Any:
    """Coerce a raw scalar string to bool / int / unquoted string."""
    s = raw.strip()
    if not s:
        return ""
    # Strip surrounding double quotes
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1]
    # Inline list
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip() for p in inner.split(",")]
        return [_scalar(p) for p in parts]
    # Booleans
    if s == "true":
        return True
    if s == "false":
        return False
    # Integer
    try:
        return int(s)
    except ValueError:
        pass
    return s


# ─── schema validation ─────────────────────────────────────────────────────────

_REQUIRED_AFFORDANCE_KEYS = {
    "id", "command", "risk_class", "workflow_match", "skip_when", "hint", "reference"
}
_ALLOWED_AFFORDANCE_KEYS = _REQUIRED_AFFORDANCE_KEYS
_REQUIRED_WORKFLOW_KEYS = {"orchestrator", "completion_kind"}
_ALLOWED_SKIP_KEYS = {"orchestrator_failed", "already_suggested_this_session"}


def _validate_registry(data: Dict[str, Any], source: str) -> None:
    """Raise RegistryParseError if `data` doesn't conform to the closed schema."""
    if data.get("schema_version") != "affordance.v1":
        raise RegistryParseError(f"{source}: schema_version must be 'affordance.v1'")

    has_host = "host_cli" in data
    has_activation = "activation" in data
    if not (has_host or has_activation):
        raise RegistryParseError(f"{source}: must declare host_cli or activation")
    if has_host and has_activation:
        raise RegistryParseError(f"{source}: cannot declare both host_cli and activation")

    if has_activation:
        act = data["activation"]
        if not isinstance(act, dict) or list(act.keys()) != ["tool_on_path"]:
            raise RegistryParseError(f"{source}: activation must be {{tool_on_path: <name>}}")

    affordances = data.get("affordances", [])
    if not isinstance(affordances, list):
        raise RegistryParseError(f"{source}: affordances must be a list")

    seen_ids = set()
    for idx, aff in enumerate(affordances):
        ctx = f"{source} #{idx}"
        if not isinstance(aff, dict):
            raise RegistryParseError(f"{ctx}: not a mapping")

        extra = set(aff.keys()) - _ALLOWED_AFFORDANCE_KEYS
        if extra:
            raise RegistryParseError(f"{ctx}: unknown keys {sorted(extra)}")
        missing = _REQUIRED_AFFORDANCE_KEYS - set(aff.keys())
        if missing:
            raise RegistryParseError(f"{ctx}: missing required keys {sorted(missing)}")

        for k in ("id", "command", "risk_class", "hint", "reference"):
            if not isinstance(aff[k], str) or not aff[k]:
                raise RegistryParseError(f"{ctx}: {k} must be a non-empty string")

        if aff["risk_class"] not in _VALID_RISKS:
            raise RegistryParseError(
                f"{ctx}: risk_class must be one of {sorted(_VALID_RISKS)}, got {aff['risk_class']!r}"
            )

        if aff["id"] in seen_ids:
            raise RegistryParseError(f"{ctx}: duplicate id {aff['id']!r}")
        seen_ids.add(aff["id"])

        wm = aff["workflow_match"]
        if not isinstance(wm, dict):
            raise RegistryParseError(f"{ctx}: workflow_match must be a mapping")
        wm_extra = set(wm.keys()) - _REQUIRED_WORKFLOW_KEYS
        if wm_extra:
            raise RegistryParseError(f"{ctx}: workflow_match has unknown keys {sorted(wm_extra)}")
        wm_missing = _REQUIRED_WORKFLOW_KEYS - set(wm.keys())
        if wm_missing:
            raise RegistryParseError(f"{ctx}: workflow_match missing {sorted(wm_missing)}")
        for k in ("orchestrator", "completion_kind"):
            if not isinstance(wm[k], list) or not all(isinstance(x, str) for x in wm[k]):
                raise RegistryParseError(f"{ctx}: workflow_match.{k} must be a list of strings")

        sw = aff["skip_when"]
        if not isinstance(sw, dict):
            raise RegistryParseError(f"{ctx}: skip_when must be a mapping")
        sw_extra = set(sw.keys()) - _ALLOWED_SKIP_KEYS
        if sw_extra:
            raise RegistryParseError(f"{ctx}: skip_when has unknown keys {sorted(sw_extra)}")
        for k, v in sw.items():
            if not isinstance(v, bool):
                raise RegistryParseError(f"{ctx}: skip_when.{k} must be bool, got {v!r}")


def load_registry(path: Path) -> Dict[str, Any]:
    """Load + validate one registry/*.yaml file."""
    text = path.read_text(encoding="utf-8")
    data = _parse_yaml_registry(text, source=path.name)
    _validate_registry(data, source=path.name)
    return data


# ─── advisor core ──────────────────────────────────────────────────────────────

def _matches(aff: Dict[str, Any], completion_kind: str, orchestrator: Optional[str]) -> bool:
    wm = aff["workflow_match"]
    kinds = wm["completion_kind"]
    if completion_kind not in kinds:
        return False
    if orchestrator is None:
        return True
    orchs = wm["orchestrator"]
    if "*" in orchs:
        return True
    return orchestrator in orchs


def _under_severity_cap(aff: Dict[str, Any], cap: str) -> bool:
    return _RISK_ORDER[aff["risk_class"]] <= _RISK_ORDER[cap]


def compute_hints(
    host_cli: str,
    completion_kind: str,
    orchestrator: Optional[str] = None,
    severity_cap: str = "high",
    registry_dir: Optional[Path] = None,
    gh_on_path: Optional[bool] = None,
) -> List[Dict[str, str]]:
    """Pure-function core. Returns the JSON-ready list of hints.

    Parameters
    ----------
    host_cli       active host, one of the 6 known tokens or 'unknown'
    completion_kind workflow event the caller is reporting
    orchestrator   optional caller-orchestrator name
    severity_cap   highest risk_class the caller wants to see (default high)
    registry_dir   override for testing
    gh_on_path     override for testing the utility-CLI gate
    """
    if severity_cap not in _VALID_RISKS:
        raise ValueError(f"severity_cap must be one of {sorted(_VALID_RISKS)}")
    if host_cli == "unknown":
        return []

    reg_dir = registry_dir or _registry_dir()
    out: List[Dict[str, str]] = []

    # Host-specific registry
    host_file = reg_dir / f"{host_cli}.yaml"
    if host_file.exists():
        data = load_registry(host_file)
        # Sanity check: the file should declare the same host
        if data.get("host_cli") and data["host_cli"] != host_cli:
            return []
        for aff in data.get("affordances", []):
            if not _matches(aff, completion_kind, orchestrator):
                continue
            if not _under_severity_cap(aff, severity_cap):
                continue
            out.append({
                "command":   aff["command"],
                "host_cli":  host_cli,
                "risk_class": aff["risk_class"],
                "hint":      aff["hint"],
                "reference": aff["reference"],
            })

    # Utility-CLI registries (activation: tool_on_path)
    for util_file in sorted(reg_dir.glob("*.yaml")):
        if util_file.name == f"{host_cli}.yaml":
            continue
        data = load_registry(util_file)
        if "activation" not in data:
            continue
        tool_name = data["activation"].get("tool_on_path")
        if not tool_name:
            continue
        if gh_on_path is None:
            present = shutil.which(tool_name) is not None
        else:
            # Test injection: only honours the override for the literal gh tool
            present = gh_on_path if tool_name == "gh" else (shutil.which(tool_name) is not None)
        if not present:
            continue
        for aff in data.get("affordances", []):
            if not _matches(aff, completion_kind, orchestrator):
                continue
            if not _under_severity_cap(aff, severity_cap):
                continue
            out.append({
                "command":   aff["command"],
                "host_cli":  f"util:{tool_name}",
                "risk_class": aff["risk_class"],
                "hint":      aff["hint"],
                "reference": aff["reference"],
            })

    # Deterministic ordering: by host first (host-native before util), then risk asc, then id-equivalent (command)
    out.sort(key=lambda h: (0 if h["host_cli"] == host_cli else 1,
                            _RISK_ORDER[h["risk_class"]],
                            h["command"]))
    return out


# ─── CLI entry point ───────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--completion-kind", required=True,
                        help="workflow completion event (e.g. ui-change)")
    parser.add_argument("--orchestrator", default=None,
                        help="orchestrator name (bob, forge, alf, pa, evo) or omit")
    parser.add_argument("--severity-cap", default="high",
                        choices=sorted(_VALID_RISKS),
                        help="max risk class to include (default: high)")
    parser.add_argument("--host-cli", default=None,
                        help="override host detection (for testing)")
    args = parser.parse_args()

    host = args.host_cli if args.host_cli is not None else _detect_host_cli()
    try:
        hints = compute_hints(
            host_cli=host,
            completion_kind=args.completion_kind,
            orchestrator=args.orchestrator,
            severity_cap=args.severity_cap,
        )
    except RegistryParseError as e:
        sys.stderr.write(f"affordance-advisor: registry error: {e}\n")
        return 2

    sys.stdout.write(json.dumps(hints, indent=2, sort_keys=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
