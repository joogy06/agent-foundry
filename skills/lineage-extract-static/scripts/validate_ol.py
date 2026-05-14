#!/usr/bin/env python3
"""validate_ol.py — write-time JSON Schema validation against pinned OpenLineage 2.0.2.

Component: validate-ol (WP-4 in S033 contract-map).

Validates a single OpenLineage event (DatasetEvent / JobEvent / RunEvent) against
the vendored OL 2.0.2 schema at schemas/openlineage-2.0.2-vendored.json. Called
by merge_into_ol.py on EVERY emitted event BEFORE writing to ndjson. Failure to
validate = abort the run (fail-closed per HARD-RULE 1).

Performance: schema is compiled ONCE per process via a module-level cache.
Validating 10000 events takes <2 seconds on a baseline machine.

The vendored schema's top-level oneOf selector + per-event-type definitions
are used to discriminate the event kind. This module also provides
`compile_validator` for callers that want to keep the validator instance hot.

CLI usage:
    validate_ol.py <ol_event_path> [--schema-path PATH]

Returns 0 if valid, 2 if invalid (with errors on stderr), 1 on I/O error.

Python API:
    from validate_ol import validate_event, ValidationError
    is_valid, errors = validate_event(event_dict, schema_path=None)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError as _JSValidationError
    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False
    Draft202012Validator = None  # type: ignore
    _JSValidationError = Exception  # type: ignore

PINNED_OL_VERSION = "2.0.2"
PINNED_OL_SCHEMA_URL = "https://openlineage.io/spec/2-0-2/OpenLineage.json"

DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "openlineage-2.0.2-vendored.json"
)

# Module-level caches (HARD-RULE 4 performance criterion)
_SCHEMA_CACHE: dict[Path, dict] = {}
_VALIDATOR_CACHE: dict[Path, dict[str, "Draft202012Validator"]] = {}


class SchemaPinMismatch(Exception):
    """Raised when the schema's $id does not match the pinned version."""

    pass


def _load_schema(schema_path: Path) -> dict:
    """Load + cache the schema. Verifies $id matches the pinned version."""
    if schema_path in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[schema_path]
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    schema_id = schema.get("$id", "")
    if schema_id != PINNED_OL_SCHEMA_URL:
        raise SchemaPinMismatch(
            f"Schema $id={schema_id!r} does not match pinned URL "
            f"{PINNED_OL_SCHEMA_URL!r}. Bumping the pin requires a deliberate "
            f"constants change in validate_ol.py + re-test + history entry."
        )
    _SCHEMA_CACHE[schema_path] = schema
    return schema


def _compile_event_validators(schema_path: Path) -> dict[str, "Draft202012Validator"]:
    """Compile per-event-type validators ONCE per process per schema path.

    To make local `$ref: '#/definitions/DatasetRef'` resolve correctly, we
    construct each per-event validator from a *root* schema whose top-level
    is the event-type sub-schema BUT which still carries the parent's
    `definitions` map at the same level.
    """
    if not HAVE_JSONSCHEMA:
        raise ImportError(
            "jsonschema library not installed. Run `pip install jsonschema>=4.21.0`."
        )
    if schema_path in _VALIDATOR_CACHE:
        return _VALIDATOR_CACHE[schema_path]
    schema = _load_schema(schema_path)
    defs = schema.get("definitions", {})

    def _scope(sub: dict) -> dict:
        # Return a copy that has 'definitions' at the same level as the schema body
        out = dict(sub)
        out["definitions"] = defs
        return out

    validators = {
        "DATASET_EVENT": Draft202012Validator(_scope(schema["DatasetEvent"])),
        "JOB_EVENT": Draft202012Validator(_scope(schema["JobEvent"])),
        "RUN_EVENT_START": Draft202012Validator(_scope(schema["RunEvent"])),
    }
    _VALIDATOR_CACHE[schema_path] = validators
    return validators


def compile_validator(schema_path: Optional[Path] = None) -> dict[str, "Draft202012Validator"]:
    """Public API: ensure validators are compiled and return them."""
    if schema_path is None:
        schema_path = DEFAULT_SCHEMA_PATH
    return _compile_event_validators(schema_path)


def validate_event(
    event: dict,
    schema_path: Optional[Path] = None,
) -> tuple[bool, list[str]]:
    """Validate a single OL event.

    Args:
        event: Dict representation of the event (parsed JSON).
        schema_path: Optional path to the schema. Defaults to vendored.

    Returns:
        (is_valid, errors) — errors is empty list if valid.
    """
    if schema_path is None:
        schema_path = DEFAULT_SCHEMA_PATH

    validators = compile_validator(schema_path)

    event_type = event.get("eventType", "")
    if event_type == "DATASET_EVENT":
        v = validators["DATASET_EVENT"]
    elif event_type == "JOB_EVENT":
        v = validators["JOB_EVENT"]
    elif event_type in ("START", "RUNNING", "COMPLETE", "ABORT", "FAIL", "OTHER"):
        v = validators["RUN_EVENT_START"]
    else:
        return (False, [f"unknown eventType: {event_type!r} (expected DATASET_EVENT, JOB_EVENT, or RunEvent eventType)"])

    errors: list[str] = []
    for err in v.iter_errors(event):
        path = ".".join(str(p) for p in err.absolute_path) if err.absolute_path else "<root>"
        errors.append(f"{path}: {err.message}")

    return (len(errors) == 0, errors)


def validate_event_or_abort(
    event: dict,
    schema_path: Optional[Path] = None,
) -> None:
    """Validate; raise ValueError on failure. Used by merge_into_ol.py for
    fail-closed posture per HARD-RULE 1."""
    is_valid, errors = validate_event(event, schema_path)
    if not is_valid:
        raise ValueError(
            f"OpenLineage event validation FAILED ({len(errors)} errors):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ol_event_path", type=Path, help="Path to a JSON file containing the OL event")
    parser.add_argument(
        "--schema-path",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help=f"Schema path (default: {DEFAULT_SCHEMA_PATH})",
    )
    args = parser.parse_args(argv)

    if not args.ol_event_path.exists():
        print(f"ERROR: Event file not found: {args.ol_event_path}", file=sys.stderr)
        return 1

    try:
        with args.ol_event_path.open("r", encoding="utf-8") as f:
            event = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse JSON: {e}", file=sys.stderr)
        return 1
    except (PermissionError, OSError) as e:
        print(f"ERROR: I/O error reading event: {e}", file=sys.stderr)
        return 1

    try:
        is_valid, errors = validate_event(event, schema_path=args.schema_path)
    except (ImportError, FileNotFoundError, SchemaPinMismatch) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if is_valid:
        print(json.dumps({"valid": True, "errors": []}))
        return 0
    print(json.dumps({"valid": False, "errors": errors}, indent=2), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
