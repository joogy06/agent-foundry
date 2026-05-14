#!/usr/bin/env python3
"""test_evo_schemas.py — S032 WP-1 schema validation tests.

Validates the 5 new schemas in skills/_meta/schemas/ against representative
valid samples + per-field invalid samples:

    - functional-intent.v1.json
    - drift-report.v1.json
    - consult-decision.v1.json
    - evergreen-verdict.v1.json
    - evo-manifest.v1.json

Run:
    python -m pytest skills/_meta/tests/test_evo_schemas.py -v
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

SCRIPT_DIR = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = SCRIPT_DIR / "schemas"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Valid samples
# ---------------------------------------------------------------------------

VALID_FUNCTIONAL_INTENT = {
    "schema_version": "1.0.0",
    "component_id": "auth-service",
    "workspace_tree_hash": "a" * 40,
    "content_hash": "b" * 64,
    "extractor_id": "intent-extract",
    "extractor_version": "1.0.0",
    "model_id": "claude-opus-4-7",
    "sampled_at": "2026-05-13T14:30:00Z",
    "template_hash": "c" * 64,
    "function_class": "auth",
    "entry_points": [
        {
            "kind": "http_route",
            "detail": "POST /auth/verify",
            "handler_symbol": "src/auth/routes.py:verify",
            "framework": "fastapi",
            "evidence_edges": ["edge-uuid-1", "edge-uuid-2"],
        }
    ],
    "inputs": [
        {"name": "bearer_token", "semantic_type": "session_token", "nullable": False}
    ],
    "outputs": [
        {"name": "user_identity", "semantic_type": "user_identity"}
    ],
    "side_effects": [
        {
            "kind": "cache_write",
            "target": "redis://session-cache",
            "evidence_edges": ["edge-uuid-7"],
        }
    ],
    "flows_participated": [
        {"flow_id": "FLOW-LOGIN", "role": "validator"}
    ],
    "intent": {
        "one_line": "Validates session tokens against Redis and enforces RBAC.",
        "confidence_level": "grounded",
        "responsibilities": [
            {"id": "R1", "text": "Decode JWT tokens", "confidence_level": "grounded"}
        ],
    },
    "assumptions": ["JWTs are RS256 signed"],
    "invariants": ["Never returns user_identity with empty roles"],
    "error_paths": [
        {
            "condition": "JWT signature invalid",
            "error_kind": "raises",
            "error_type": "AuthError",
            "http_status": 401,
            "propagates_to": "caller",
            "evidence_edges": ["edge-uuid-11"],
        }
    ],
    "test_seeds": [
        {
            "seed_id": "S-001",
            "scenario": "Valid token returns user_identity",
            "given": "Token signed by trusted issuer, not expired",
            "when": "POST /auth/verify",
            "then": "200, user_identity in body",
        }
    ],
    "unknowns": ["JWT key rotation behaviour"],
    "determinism_class": "cached_interpretive",
    "consistency_score": 0.97,
}


VALID_DRIFT_REPORT = {
    "schema_version": "1.0.0",
    "run_id": "12345678-1234-1234-1234-123456789abc",
    "generated_at": "2026-05-13T14:30:00Z",
    "project_root": "/path/to/myapp",
    "mode": "version-upgrade",
    "findings": [
        {
            "finding_id": "f-001",
            "kind": "api_break",
            "severity": "critical",
            "package": "pandas",
            "declared_version": "1.5.3",
            "latest_stable": "2.2.3",
            "api_delta_summary": {
                "breaking_lines": ["Series.append() removed"],
                "affected_call_sites": 17,
                "affected_components": ["data-loader", "analytics"],
            },
            "recommendation": "upgrade with migration code-fixes",
            "requires_user_decision": True,
            "blocking": True,
        }
    ],
}


VALID_CONSULT_DECISION = {
    "decision_id": "d-007",
    "decided_at": "2026-05-13T14:30:22Z",
    "presented_finding_id": "f-014",
    "user_decision": "accept",
    "default_on_timeout": "reject",
    "decision_source": "user",
    "notes": "approved per slack thread",
}


VALID_EVERGREEN_VERDICT = {
    "schema_version": "1.0.0",
    "run_id": "12345678-1234-1234-1234-123456789abc",
    "mode": "version-upgrade",
    "started_at": "2026-05-13T14:00:00Z",
    "ended_at": "2026-05-13T15:30:00Z",
    "status": "SUCCESS",
    "status_reason": "",
    "branch_name": "evo/2026-05-13-version-upgrade-pandas",
    "scope_deltas_emitted": ["sd-001", "sd-002"],
    "tests_added": [
        {
            "path": "tests/test_evo_version-upgrade_data-loader__append.py",
            "confidence_level": "characterization-aid",
            "requires_user_review": True,
        }
    ],
    "tests_run": {
        "baseline": {"passed": 142, "failed": 0, "skipped": 3},
        "post_change": {"passed": 145, "failed": 0, "skipped": 3},
    },
    "follow_ups": [],
}


VALID_EVO_MANIFEST = {
    "schema_version": "1.0.0",
    "run_id": "12345678-1234-1234-1234-123456789abc",
    "mode": "version-upgrade",
    "phase": "AWAITING_USER",
    "started_at": "2026-05-13T14:00:00Z",
    "ttl_at": "2026-05-16T14:00:00Z",
    "sandbox_path": "/home/user/.cache/evo/sessions/12345/clone",
    "claim_uuid": "abcdef01-2345-6789-abcd-ef0123456789",
    "wiring_hash": "f" * 40,
    "dep_lock_hash": "9" * 64,
    "last_heartbeat_at": "2026-05-13T14:30:00Z",
    "target_package": "pandas",
    "project_root": "/path/to/myapp",
}


# ---------------------------------------------------------------------------
# functional-intent.v1 tests
# ---------------------------------------------------------------------------


class FunctionalIntentSchemaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMAS_DIR / "functional-intent.v1.json")

    def test_valid_sample(self):
        jsonschema.validate(VALID_FUNCTIONAL_INTENT, self.schema)

    def test_all_function_class_enum_values(self):
        valid = {
            "auth", "rbac", "crud", "pricing", "routing", "transform", "io",
            "persistence", "cache", "queue", "scheduler", "observability",
            "config", "metric", "glue", "test_harness", "unknown",
        }
        for fc in valid:
            with self.subTest(function_class=fc):
                sample = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
                sample["function_class"] = fc
                jsonschema.validate(sample, self.schema)

    def test_invalid_function_class_rejected(self):
        bad = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
        bad["function_class"] = "exotic"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_entry_point_kind_enum(self):
        for kind in ("http_route", "grpc_method", "queue_consumer", "cron",
                     "cli", "rpc_server", "lib_api", "sdk_init", "event_handler"):
            with self.subTest(entry_kind=kind):
                sample = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
                sample["entry_points"][0]["kind"] = kind
                jsonschema.validate(sample, self.schema)

    def test_entry_point_evidence_edges_required(self):
        bad = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
        bad["entry_points"][0]["evidence_edges"] = []
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_side_effect_kind_enum(self):
        for kind in ("cache_write", "db_write", "network_io", "file_io",
                     "log_emit", "metric_emit", "env_mutation", "clipboard",
                     "gpu_alloc"):
            with self.subTest(side_effect=kind):
                sample = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
                sample["side_effects"][0]["kind"] = kind
                jsonschema.validate(sample, self.schema)

    def test_error_kind_enum(self):
        for kind in ("raises", "returns_error", "http_status_5xx",
                     "swallowed", "unhandled"):
            with self.subTest(error_kind=kind):
                sample = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
                sample["error_paths"][0]["error_kind"] = kind
                jsonschema.validate(sample, self.schema)

    def test_confidence_level_enum(self):
        for cl in ("grounded", "interpretive", "degraded"):
            with self.subTest(confidence_level=cl):
                sample = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
                sample["intent"]["confidence_level"] = cl
                jsonschema.validate(sample, self.schema)

    def test_determinism_class_enum(self):
        for d in ("deterministic", "cached_interpretive", "fresh_interpretive"):
            with self.subTest(determinism_class=d):
                sample = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
                sample["determinism_class"] = d
                jsonschema.validate(sample, self.schema)

    def test_seed_id_pattern(self):
        bad = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
        bad["test_seeds"][0]["seed_id"] = "001"  # missing S- prefix
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_responsibility_id_pattern(self):
        bad = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
        bad["intent"]["responsibilities"][0]["id"] = "Resp1"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_max_responsibilities_10(self):
        bad = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
        bad["intent"]["responsibilities"] = [
            {"id": f"R{i}", "text": f"resp {i}"} for i in range(11)
        ]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_workspace_tree_hash_pattern(self):
        bad = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
        bad["workspace_tree_hash"] = "TOO_SHORT"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_extractor_version_semver(self):
        bad = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
        bad["extractor_version"] = "v1"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_additional_properties_rejected(self):
        bad = copy.deepcopy(VALID_FUNCTIONAL_INTENT)
        bad["mystery"] = "field"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


# ---------------------------------------------------------------------------
# drift-report.v1 tests
# ---------------------------------------------------------------------------


class DriftReportSchemaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMAS_DIR / "drift-report.v1.json")

    def test_valid_sample(self):
        jsonschema.validate(VALID_DRIFT_REPORT, self.schema)

    def test_mode_enum(self):
        for m in ("intent-map-only", "version-upgrade", "cve-fix"):
            with self.subTest(mode=m):
                sample = copy.deepcopy(VALID_DRIFT_REPORT)
                sample["mode"] = m
                jsonschema.validate(sample, self.schema)

    def test_finding_kind_enum(self):
        for k in ("api_break", "cve", "version_lag", "test_gap",
                  "optimization_suggestion"):
            with self.subTest(kind=k):
                sample = copy.deepcopy(VALID_DRIFT_REPORT)
                sample["findings"][0]["kind"] = k
                jsonschema.validate(sample, self.schema)

    def test_severity_enum(self):
        for s in ("critical", "high", "moderate", "low"):
            with self.subTest(severity=s):
                sample = copy.deepcopy(VALID_DRIFT_REPORT)
                sample["findings"][0]["severity"] = s
                jsonschema.validate(sample, self.schema)

    def test_fix_category_enum(self):
        for c in ("direct-fix-available", "override-possible",
                  "upstream-blocked", "workaround-required", "no-known-fix"):
            with self.subTest(fix_category=c):
                sample = copy.deepcopy(VALID_DRIFT_REPORT)
                sample["findings"][0]["fix_category"] = c
                jsonschema.validate(sample, self.schema)

    def test_cve_id_pattern(self):
        ok = copy.deepcopy(VALID_DRIFT_REPORT)
        ok["findings"][0]["cve_id"] = "CVE-2026-25990"
        jsonschema.validate(ok, self.schema)

        bad = copy.deepcopy(VALID_DRIFT_REPORT)
        bad["findings"][0]["cve_id"] = "CVE-25-90"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_finding_id_pattern(self):
        bad = copy.deepcopy(VALID_DRIFT_REPORT)
        bad["findings"][0]["finding_id"] = "finding-1"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_missing_recommendation_rejected(self):
        bad = copy.deepcopy(VALID_DRIFT_REPORT)
        del bad["findings"][0]["recommendation"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_additional_properties_rejected(self):
        bad = copy.deepcopy(VALID_DRIFT_REPORT)
        bad["sneaky"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


# ---------------------------------------------------------------------------
# consult-decision.v1 tests
# ---------------------------------------------------------------------------


class ConsultDecisionSchemaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMAS_DIR / "consult-decision.v1.json")

    def test_valid_sample(self):
        jsonschema.validate(VALID_CONSULT_DECISION, self.schema)

    def test_user_decision_enum(self):
        for d in ("accept", "reject", "defer", "modify", "abort"):
            with self.subTest(decision=d):
                sample = copy.deepcopy(VALID_CONSULT_DECISION)
                sample["user_decision"] = d
                jsonschema.validate(sample, self.schema)

    def test_decision_source_enum(self):
        for s in ("user", "timeout_default", "auto_applied"):
            with self.subTest(source=s):
                sample = copy.deepcopy(VALID_CONSULT_DECISION)
                sample["decision_source"] = s
                jsonschema.validate(sample, self.schema)

    def test_decision_id_pattern(self):
        bad = copy.deepcopy(VALID_CONSULT_DECISION)
        bad["decision_id"] = "decision-1"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_default_on_timeout_required(self):
        bad = copy.deepcopy(VALID_CONSULT_DECISION)
        del bad["default_on_timeout"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


# ---------------------------------------------------------------------------
# evergreen-verdict.v1 tests
# ---------------------------------------------------------------------------


class EvergreenVerdictSchemaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMAS_DIR / "evergreen-verdict.v1.json")

    def test_valid_sample(self):
        jsonschema.validate(VALID_EVERGREEN_VERDICT, self.schema)

    def test_status_enum(self):
        for s in ("SUCCESS", "PARTIAL", "HALTED"):
            with self.subTest(status=s):
                sample = copy.deepcopy(VALID_EVERGREEN_VERDICT)
                sample["status"] = s
                jsonschema.validate(sample, self.schema)

    def test_mode_a_with_branch_rejected(self):
        """Mode-a with non-empty scope_deltas_emitted is invalid (allOf clause)."""
        bad = copy.deepcopy(VALID_EVERGREEN_VERDICT)
        bad["mode"] = "intent-map-only"
        # scope_deltas_emitted has 2 entries — should fail
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_halted_degraded_data_no_branch(self):
        """HALTED with EVO_HALT_DEGRADED_DATA must have no scope_deltas / tests."""
        bad = copy.deepcopy(VALID_EVERGREEN_VERDICT)
        bad["status"] = "HALTED"
        bad["status_reason"] = "EVO_HALT_DEGRADED_DATA: pip-audit unknown"
        # scope_deltas_emitted has 2 entries — should fail
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_halted_degraded_data_clean(self):
        """HALTED with EVO_HALT_DEGRADED_DATA + empty arrays passes."""
        sample = copy.deepcopy(VALID_EVERGREEN_VERDICT)
        sample["status"] = "HALTED"
        sample["status_reason"] = "EVO_HALT_DEGRADED_DATA: pip-audit unknown"
        sample["scope_deltas_emitted"] = []
        sample["tests_added"] = []
        jsonschema.validate(sample, sample)  # noqa: dual-check
        jsonschema.validate(sample, self.schema)

    def test_branch_name_pattern(self):
        bad = copy.deepcopy(VALID_EVERGREEN_VERDICT)
        bad["branch_name"] = "feature/foo"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_confidence_level_for_tests(self):
        for cl in ("characterization-aid", "regression-aid", "cve-proof-of-fix"):
            with self.subTest(confidence_level=cl):
                sample = copy.deepcopy(VALID_EVERGREEN_VERDICT)
                sample["tests_added"][0]["confidence_level"] = cl
                jsonschema.validate(sample, self.schema)


# ---------------------------------------------------------------------------
# evo-manifest.v1 tests
# ---------------------------------------------------------------------------


class EvoManifestSchemaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = _load(SCHEMAS_DIR / "evo-manifest.v1.json")

    def test_valid_sample(self):
        jsonschema.validate(VALID_EVO_MANIFEST, self.schema)

    def test_phase_enum(self):
        for p in ("INIT", "CLONING", "ANALYZED", "INTENT_MAPPED",
                  "DRIFT_SURFACED", "PLANNED", "CONSULTED", "AWAITING_USER",
                  "APPLYING", "TESTED", "VERIFIED_OR_PARTIAL", "REPORTED",
                  "DONE", "HALTED"):
            with self.subTest(phase=p):
                sample = copy.deepcopy(VALID_EVO_MANIFEST)
                sample["phase"] = p
                jsonschema.validate(sample, self.schema)

    def test_invalid_phase_rejected(self):
        bad = copy.deepcopy(VALID_EVO_MANIFEST)
        bad["phase"] = "WAITING_FOR_INSPIRATION"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_wiring_hash_pattern(self):
        bad = copy.deepcopy(VALID_EVO_MANIFEST)
        bad["wiring_hash"] = "short"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_language_target_enum(self):
        for lang in ("python", "javascript", "typescript", "rust", "go",
                     "ruby", "java", "shallow-multi"):
            with self.subTest(language=lang):
                sample = copy.deepcopy(VALID_EVO_MANIFEST)
                sample["language_target"] = lang
                jsonschema.validate(sample, self.schema)

    def test_additional_properties_rejected(self):
        bad = copy.deepcopy(VALID_EVO_MANIFEST)
        bad["extra"] = "stuff"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


if __name__ == "__main__":
    unittest.main()
