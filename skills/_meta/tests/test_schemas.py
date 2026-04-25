#!/usr/bin/env python3
"""test_schemas.py — tester-split design §5.1 / §5.3 verification.

Validates the two JSON schemas shipped in Phase 1:

  - skills/_meta/verdict_schema.json
  - skills/_meta/test_plan_schema.json

against representative valid samples and per-field invalid samples
(missing required field, wrong type, wrong pattern, wrong enum, etc.).

Run:
    python -m pytest skills/_meta/tests/test_schemas.py -v
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

VERDICT_SCHEMA_PATH = SCRIPT_DIR / "verdict_schema.json"
TEST_PLAN_SCHEMA_PATH = SCRIPT_DIR / "test_plan_schema.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Valid sample fixtures
# ---------------------------------------------------------------------------

VALID_VERDICT = {
    "verdict": "VERIFIED",
    "request_id": "a" * 32,
    "attempt_id": "attempt-1",
    "prior_state_version": "ledger-rev-7",
    "bundle_hash": "b" * 64,
    "plan_hash": "c" * 64,
    "inventory_hash": "d" * 64,
    "runner_version": "trusted_runner/1.0",
    "rubric_version": "rubric/1.0",
    "coverage": {
        "requirements_total": 5,
        "requirements_covered": 5,
        "uncovered": [],
        "skipped_with_reason": [
            {
                "requirement_id": "REQ-005",
                "reason": "needs Tier 2 chrome",
                "tier_required": 2,
            }
        ],
    },
    "concerns": [
        {"severity": "warning", "detail": "fixture seed not logged"}
    ],
    "self_hash_check": {
        "bundle_recomputed_hash": "b" * 64,
        "matches_input": True,
    },
}


VALID_TEST_PLAN = {
    "schema_version": 1,
    "plan_id": "00000000-0000-0000-0000-000000000001",
    "plan_hash": "1" * 64,
    "design_doc_hash": "2" * 64,
    "contract_map_hash": "3" * 64,
    "inventory_hash": "4" * 64,
    "inventory_tier": 2,
    "created_at": "2026-04-21T12:00:00Z",
    "created_by": "test-architect",
    "forge_session_id": "session-xyz",
    "requirements": [
        {
            "id": "REQ-001",
            "description": "Auth endpoint rejects expired tokens",
            "test_types": ["unit", "integration"],
            "required_tier": 0,
            "required_capabilities": [],
            "fixture_dependencies": ["expired-jwt"],
            "rationale": "core security invariant",
        },
        {
            "id": "REQ-002",
            "description": "Login UI shows error on bad password",
            "test_types": ["ui"],
            "required_tier": 2,
            "required_capabilities": ["chrome_mcp"],
            "skip_if_tier_below": 2,
        },
    ],
    "testability_concerns": [
        {
            "requirement_id": "REQ-002",
            "severity": "warning",
            "issue": "needs Chrome MCP, only available in Tier 2",
            "recommendation": "split into headless API test (Tier 0) + UI test (Tier 2)",
        }
    ],
}


# ---------------------------------------------------------------------------
# Verdict schema tests
# ---------------------------------------------------------------------------


class VerdictSchemaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(VERDICT_SCHEMA_PATH)

    def test_valid_sample_passes(self):
        jsonschema.validate(VALID_VERDICT, self.schema)

    def test_all_four_verdict_enum_values(self):
        for v in ("VERIFIED", "VERIFIED_WITH_CONCERNS", "REJECTED", "AUDIT_UNAVAILABLE"):
            with self.subTest(verdict=v):
                sample = copy.deepcopy(VALID_VERDICT)
                sample["verdict"] = v
                jsonschema.validate(sample, self.schema)

    def test_missing_request_id_rejected(self):
        bad = copy.deepcopy(VALID_VERDICT)
        del bad["request_id"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_missing_self_hash_check_rejected(self):
        bad = copy.deepcopy(VALID_VERDICT)
        del bad["self_hash_check"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_wrong_type_for_requirements_total_rejected(self):
        bad = copy.deepcopy(VALID_VERDICT)
        bad["coverage"]["requirements_total"] = "five"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_invalid_verdict_enum_rejected(self):
        bad = copy.deepcopy(VALID_VERDICT)
        bad["verdict"] = "MAYBE"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_bad_request_id_pattern_rejected(self):
        bad = copy.deepcopy(VALID_VERDICT)
        bad["request_id"] = "not-hex-and-too-short"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_bad_bundle_hash_length_rejected(self):
        bad = copy.deepcopy(VALID_VERDICT)
        bad["bundle_hash"] = "b" * 63  # one short
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_concern_severity_enum_enforced(self):
        bad = copy.deepcopy(VALID_VERDICT)
        bad["concerns"] = [{"severity": "info", "detail": "x"}]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_additional_properties_rejected(self):
        bad = copy.deepcopy(VALID_VERDICT)
        bad["extra_field"] = "nope"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


# ---------------------------------------------------------------------------
# Test plan schema tests
# ---------------------------------------------------------------------------


class TestPlanSchemaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(TEST_PLAN_SCHEMA_PATH)

    def test_valid_sample_passes(self):
        jsonschema.validate(VALID_TEST_PLAN, self.schema)

    def test_schema_version_must_be_one(self):
        bad = copy.deepcopy(VALID_TEST_PLAN)
        bad["schema_version"] = 2
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_created_by_must_be_test_architect(self):
        bad = copy.deepcopy(VALID_TEST_PLAN)
        bad["created_by"] = "bob"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_inventory_tier_enum(self):
        for tier in (0, 1, 2):
            with self.subTest(tier=tier):
                ok = copy.deepcopy(VALID_TEST_PLAN)
                ok["inventory_tier"] = tier
                jsonschema.validate(ok, self.schema)
        bad = copy.deepcopy(VALID_TEST_PLAN)
        bad["inventory_tier"] = 3
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_requirement_id_pattern_enforced(self):
        bad = copy.deepcopy(VALID_TEST_PLAN)
        bad["requirements"][0]["id"] = "REQUIREMENT_001"  # missing REQ- prefix
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_test_type_enum_enforced(self):
        bad = copy.deepcopy(VALID_TEST_PLAN)
        bad["requirements"][0]["test_types"] = ["chaos"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_skip_if_tier_below_only_one_or_two(self):
        bad = copy.deepcopy(VALID_TEST_PLAN)
        bad["requirements"][1]["skip_if_tier_below"] = 0
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_empty_requirements_rejected(self):
        bad = copy.deepcopy(VALID_TEST_PLAN)
        bad["requirements"] = []
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_exception_type_enum(self):
        ok = copy.deepcopy(VALID_TEST_PLAN)
        ok["exceptions"] = [
            {"type": "PLAN_INCOMPLETE", "requirement_id": "REQ-003", "detail": "missing test"}
        ]
        jsonschema.validate(ok, self.schema)
        bad = copy.deepcopy(ok)
        bad["exceptions"][0]["type"] = "WHATEVER"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_additional_properties_rejected(self):
        bad = copy.deepcopy(VALID_TEST_PLAN)
        bad["mystery_field"] = 42
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


if __name__ == "__main__":
    unittest.main()
