"""test_schema_valid — ANTI-REQUIREMENT #1 (design §10).

The discarded agy build used uppercase JSON-Schema types ("STRING"/"OBJECT") and
could never validate. Every schema MUST pass Draft7Validator.check_schema, and the
core objects MUST use lowercase draft-07 types. This test fails if that regresses.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
SCHEMA_FILES = sorted(SCHEMAS_DIR.glob("*.json"))


def test_schema_dir_has_all_three():
    names = {p.name for p in SCHEMA_FILES}
    assert names == {"code-index.v1.json", "code-finding.v1.json", "library-catalog.v1.json"}, names


@pytest.mark.parametrize("schema_path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_is_valid_draft7(schema_path: Path):
    """The CORE anti-requirement check: check_schema must not raise."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # Raises jsonschema.exceptions.SchemaError on an invalid schema (e.g. an
    # unknown/uppercase type keyword value).
    Draft7Validator.check_schema(schema)


@pytest.mark.parametrize("schema_path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_types_are_lowercase(schema_path: Path):
    """Belt-and-braces: walk every "type" value and assert it is a valid lowercase
    draft-07 primitive (or a list thereof). Catches the exact agy bug directly."""
    valid = {"string", "number", "integer", "object", "array", "boolean", "null"}
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    bad: list = []

    def walk(node):
        if isinstance(node, dict):
            if "type" in node:
                t = node["type"]
                types = t if isinstance(t, list) else [t]
                for tv in types:
                    if tv not in valid:
                        bad.append(tv)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    assert not bad, f"{schema_path.name} has non-lowercase/invalid type values: {bad}"


def test_declares_draft7():
    """Each schema must declare the draft-07 meta-schema explicitly."""
    for p in SCHEMA_FILES:
        schema = json.loads(p.read_text(encoding="utf-8"))
        assert schema.get("$schema") == "http://json-schema.org/draft-07/schema#", p.name
