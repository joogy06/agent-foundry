#!/usr/bin/env python3
"""validate_finding.py — write-time validation of structure-recovery findings.

Part of the structure-recovery skill (S0xx; lineage-family sibling of
lineage-extract-static / legacy-code-intel). Validates a single
``structure-finding.v1`` object (per-chunk DECLARED facts) OR a
``structure-index.v1`` catalog (accumulated, offset-computed) against the
vendored JSON Schemas under ``../schemas/``.

WHY a custom validator instead of plain jsonschema
--------------------------------------------------
The SAFETY-CRITICAL invariant of this skill (design §3.2 / §3.3 / §9 note 1) is:

    a chunk-level structure-finding MUST NOT carry a non-null ``byte_offset``
    or ``length`` on any field — byte offsets are computed DETERMINISTICALLY
    downstream by ``cobol_offset_calc.py`` from the declared level-tree, and are
    NEVER declared/guessed by the LLM-as-parser.

That rule is enforced here in PURE stdlib Python (``_check_offset_rule``), so it
holds whether or not the optional ``jsonschema`` library is installed. The full
draft-2020-12 structural validation is layered ON TOP via ``jsonschema`` when it
is available (mirroring the sibling ``validate_ol.py`` fail-soft idiom). The
closed enums (confidence / evidence_kind / enforcement / object_kind) are ALSO
re-checked in pure Python so the acceptance tests pass in a jsonschema-free env.

This module is the single validator invoked before a finding is accumulated and
before a catalog is rendered. Failure to validate = reject the finding
(fail-closed; the caller decides whether to abort or downgrade).

CLI usage::

    validate_finding.py <finding_or_index.json> [--kind finding|index] [--schema-path PATH]

Returns 0 if valid, 2 if invalid (errors on stderr), 1 on I/O error.

Python API::

    from validate_finding import validate_finding, validate_index, OffsetRuleError
    is_valid, errors = validate_finding(finding_dict)          # auto-detects schema
    is_valid, errors = validate_index(index_dict)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

try:  # fail-soft, mirrors lineage-extract-static/scripts/validate_ol.py
    from jsonschema import Draft202012Validator
    HAVE_JSONSCHEMA = True
except ImportError:  # pragma: no cover - exercised only in jsonschema-free envs
    HAVE_JSONSCHEMA = False
    Draft202012Validator = None  # type: ignore

# ---------------------------------------------------------------------------
# Schema locations + closed enums (kept in sync with the .json schemas)
# ---------------------------------------------------------------------------

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
FINDING_SCHEMA_PATH = _SCHEMA_DIR / "structure-finding.v1.json"
INDEX_SCHEMA_PATH = _SCHEMA_DIR / "structure-index.v1.json"

CONFIDENCE_ENUM = {"grounded", "inferred", "speculative"}
EVIDENCE_KIND_ENUM = {
    "declared_constraint",
    "declared_column",
    "inferred_naming",
    "observed_usage",
}
ENFORCEMENT_ENUM = {"declared", "unknown"}
OBJECT_KIND_ENUM = {"table", "view", "cobol_record", "flatfile_layout"}

# Module-level schema cache (perf — load each schema once per process).
_SCHEMA_CACHE: dict[Path, dict] = {}
_VALIDATOR_CACHE: dict[Path, "Draft202012Validator"] = {}


class OffsetRuleError(ValueError):
    """Raised by the strict-abort helper when the safety-critical
    non-null-offset rule is violated on a chunk-level finding."""


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

def _load_schema(schema_path: Path) -> dict:
    if schema_path in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[schema_path]
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    with schema_path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)
    _SCHEMA_CACHE[schema_path] = schema
    return schema


def _get_validator(schema_path: Path) -> "Draft202012Validator":
    if schema_path in _VALIDATOR_CACHE:
        return _VALIDATOR_CACHE[schema_path]
    schema = _load_schema(schema_path)
    validator = Draft202012Validator(schema)
    _VALIDATOR_CACHE[schema_path] = validator
    return validator


# ---------------------------------------------------------------------------
# Pure-Python safety-critical checks (run with OR without jsonschema)
# ---------------------------------------------------------------------------

def _check_offset_rule(finding: dict) -> list[str]:
    """The CRITICAL rule (design §3.2 / §9 note 1): no field on a chunk-level
    finding may carry a non-null ``byte_offset`` or ``length``.

    Returns a list of human-readable error strings (empty == clean).

    Flat-file declared positions are the explicit exception, BUT they live in
    ``declared_start`` / ``declared_end`` (guarded by ``position_declared``),
    NOT in ``byte_offset`` / ``length`` — so this rule has no false positives
    on legitimate flat-file findings.
    """
    errors: list[str] = []
    fields = finding.get("fields")
    if not isinstance(fields, list):
        # Field-shape problems are reported by the structural check; nothing
        # to enforce here if there is no field list.
        return errors
    for idx, fld in enumerate(fields):
        if not isinstance(fld, dict):
            continue
        name = fld.get("name", f"<field#{idx}>")
        for key in ("byte_offset", "length"):
            # Use a sentinel so an explicitly-present null is accepted while a
            # missing key is reported by the structural (required) check.
            val = fld.get(key, None)
            if val is not None:
                errors.append(
                    f"fields[{idx}] ({name!r}): {key}={val!r} is non-null — "
                    f"chunk-level findings MUST leave {key} null; byte offsets are "
                    f"computed downstream by cobol_offset_calc.py (design §3.2 / §9 note 1)."
                )
    return errors


def _check_finding_enums(finding: dict) -> list[str]:
    """Pure-Python enum checks so the acceptance tests pass even without
    jsonschema. Only flags values that are PRESENT and wrong (absence/typing is
    the structural check's job)."""
    errors: list[str] = []

    ok = finding.get("object_kind", None)
    if ok is not None and ok not in OBJECT_KIND_ENUM:
        errors.append(
            f"object_kind={ok!r} not in {sorted(OBJECT_KIND_ENUM)}"
        )

    conf = finding.get("confidence", None)
    if conf is not None and conf not in CONFIDENCE_ENUM:
        errors.append(f"confidence={conf!r} not in {sorted(CONFIDENCE_ENUM)}")

    def _enum_in(container: dict, label: str) -> None:
        c = container.get("confidence", None)
        if c is not None and c not in CONFIDENCE_ENUM:
            errors.append(f"{label}.confidence={c!r} not in {sorted(CONFIDENCE_ENUM)}")
        ek = container.get("evidence_kind", None)
        if ek is not None and ek not in EVIDENCE_KIND_ENUM:
            errors.append(f"{label}.evidence_kind={ek!r} not in {sorted(EVIDENCE_KIND_ENUM)}")
        en = container.get("enforcement", None)
        if en is not None and en not in ENFORCEMENT_ENUM:
            errors.append(f"{label}.enforcement={en!r} not in {sorted(ENFORCEMENT_ENUM)}")

    for idx, fld in enumerate(finding.get("fields", []) or []):
        if isinstance(fld, dict):
            _enum_in(fld, f"fields[{idx}]")
    for idx, rel in enumerate(finding.get("relationships", []) or []):
        if isinstance(rel, dict):
            _enum_in(rel, f"relationships[{idx}]")
    return errors


# ---------------------------------------------------------------------------
# Structural validation (jsonschema when present)
# ---------------------------------------------------------------------------

def _structural_errors(obj: dict, schema_path: Path) -> list[str]:
    if not HAVE_JSONSCHEMA:
        return []  # fail-soft: pure-Python checks above still ran
    validator = _get_validator(schema_path)
    out: list[str] = []
    for err in validator.iter_errors(obj):
        path = ".".join(str(p) for p in err.absolute_path) if err.absolute_path else "<root>"
        out.append(f"{path}: {err.message}")
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_finding(
    finding: dict,
    schema_path: Optional[Path] = None,
) -> tuple[bool, list[str]]:
    """Validate a single ``structure-finding.v1`` object.

    Runs (always) the safety-critical non-null-offset rule + closed-enum checks
    in pure Python, then (when jsonschema is installed) the full draft-2020-12
    structural validation.

    Returns ``(is_valid, errors)``; ``errors`` is empty iff valid.
    """
    if schema_path is None:
        schema_path = FINDING_SCHEMA_PATH
    errors: list[str] = []
    errors.extend(_check_offset_rule(finding))
    errors.extend(_check_finding_enums(finding))
    errors.extend(_structural_errors(finding, schema_path))
    return (len(errors) == 0, errors)


def validate_index(
    index: dict,
    schema_path: Optional[Path] = None,
) -> tuple[bool, list[str]]:
    """Validate a ``structure-index.v1`` accumulated catalog. Here computed
    (non-null) offsets are EXPECTED, so the chunk-level offset-rejection rule is
    NOT applied; only structural + enum checks run."""
    if schema_path is None:
        schema_path = INDEX_SCHEMA_PATH
    errors: list[str] = []
    # Catalog-level enum sanity (entities + relationships).
    for eidx, ent in enumerate(index.get("entities", []) or []):
        if not isinstance(ent, dict):
            continue
        ok = ent.get("object_kind", None)
        if ok is not None and ok not in OBJECT_KIND_ENUM:
            errors.append(f"entities[{eidx}].object_kind={ok!r} not in {sorted(OBJECT_KIND_ENUM)}")
        conf = ent.get("confidence", None)
        if conf is not None and conf not in CONFIDENCE_ENUM:
            errors.append(f"entities[{eidx}].confidence={conf!r} not in {sorted(CONFIDENCE_ENUM)}")
    errors.extend(_structural_errors(index, schema_path))
    return (len(errors) == 0, errors)


def validate_finding_or_abort(finding: dict, schema_path: Optional[Path] = None) -> None:
    """Validate; raise OffsetRuleError/ValueError on failure. For callers that
    want a fail-closed posture (the offset rule is reported first so the caller
    can distinguish the safety violation from generic schema noise)."""
    offset_errors = _check_offset_rule(finding)
    if offset_errors:
        raise OffsetRuleError(
            "structure-finding offset-rule violation:\n"
            + "\n".join(f"  - {e}" for e in offset_errors)
        )
    is_valid, errors = validate_finding(finding, schema_path)
    if not is_valid:
        raise ValueError(
            f"structure-finding validation FAILED ({len(errors)} errors):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _detect_kind(obj: dict) -> str:
    """Auto-detect whether a parsed JSON object is a finding or an index."""
    if "entities" in obj or "generated_with" in obj:
        return "index"
    return "finding"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("path", type=Path, help="Path to a JSON finding or index file")
    parser.add_argument(
        "--kind",
        choices=["finding", "index", "auto"],
        default="auto",
        help="Which schema to validate against (default: auto-detect).",
    )
    parser.add_argument(
        "--schema-path",
        type=Path,
        default=None,
        help="Override the schema path (defaults to the vendored schema for the kind).",
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"ERROR: File not found: {args.path}", file=sys.stderr)
        return 1
    try:
        with args.path.open("r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Failed to parse JSON: {exc}", file=sys.stderr)
        return 1
    except (PermissionError, OSError) as exc:
        print(f"ERROR: I/O error reading file: {exc}", file=sys.stderr)
        return 1

    kind = args.kind if args.kind != "auto" else _detect_kind(obj)
    try:
        if kind == "index":
            is_valid, errors = validate_index(obj, schema_path=args.schema_path)
        else:
            is_valid, errors = validate_finding(obj, schema_path=args.schema_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if is_valid:
        print(json.dumps({"valid": True, "kind": kind, "errors": [], "jsonschema": HAVE_JSONSCHEMA}))
        return 0
    print(
        json.dumps({"valid": False, "kind": kind, "errors": errors, "jsonschema": HAVE_JSONSCHEMA}, indent=2),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
