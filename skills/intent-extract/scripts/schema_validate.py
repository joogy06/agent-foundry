"""schema_validate.py — Validate a functional-intent YAML file against v1 schema.

Used by:
  - run.py before writing a fresh extract (rejects malformed LLM output)
  - the test suite as a fixture validator
  - downstream consumers (intent-map-render, ever-test-gen) as a runtime guard

Exit codes (CLI mode):
  0 = valid
  2 = schema violation
  3 = environmental error (file missing, parse error)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    import jsonschema
except ImportError:
    sys.stderr.write("FATAL: jsonschema not installed\n")
    sys.exit(3)

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed\n")
    sys.exit(3)


def _candidate_schema_paths() -> list[Path]:
    """Return ordered candidate paths for the v1 schema.

    Order:
      1. Skill-local copy: <skill>/schemas/functional-intent.v1.json
      2. Published _meta:  ~/.claude/skills/_meta/schemas/functional-intent.v1.json
      3. R&D _meta:        ../../skills/_meta/schemas/functional-intent.v1.json
    """
    skill_dir = Path(__file__).resolve().parent.parent
    return [
        skill_dir / "schemas" / "functional-intent.v1.json",
        Path.home() / ".claude" / "skills" / "_meta" / "schemas" / "functional-intent.v1.json",
        skill_dir.parent / "_meta" / "schemas" / "functional-intent.v1.json",
    ]


def load_schema() -> Dict[str, Any]:
    for p in _candidate_schema_paths():
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "functional-intent.v1.json not found in any candidate location"
    )


def validate_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (ok, error_message). On success error_message is empty."""
    try:
        schema = load_schema()
    except FileNotFoundError as e:
        return False, f"schema not found: {e}"
    try:
        jsonschema.validate(payload, schema)
        return True, ""
    except jsonschema.ValidationError as e:
        return False, f"{e.message} (path={list(e.absolute_path)})"


def validate_file(path: Path) -> Tuple[bool, str]:
    if not path.is_file():
        return False, f"file not found: {path}"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return False, f"yaml parse error: {e}"
    if not isinstance(payload, dict):
        return False, f"expected mapping at top level, got {type(payload).__name__}"
    return validate_payload(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate functional-intent.v1 YAML files",
    )
    parser.add_argument("--intent", required=True, type=Path,
                        help="path to intent YAML")
    args = parser.parse_args(argv)

    if not args.intent.is_file():
        sys.stderr.write(f"ENV_ERROR: file not found: {args.intent}\n")
        return 3
    ok, msg = validate_file(args.intent)
    if ok:
        sys.stdout.write(f"VALID: {args.intent}\n")
        return 0
    sys.stderr.write(f"INVALID: {args.intent} — {msg}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
