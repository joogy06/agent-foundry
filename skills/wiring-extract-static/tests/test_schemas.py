#!/usr/bin/env python3
"""test_schemas.py — positive + negative fixtures for all 3 JSON Schemas.

Runs standalone:
    python3 ~/.claude/skills/wiring-extract-static/tests/test_schemas.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    sys.stderr.write("jsonschema not installed\n")
    sys.exit(3)

# Add wiring-reconcile scripts to path for edge_identity (single source of truth)
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "wiring-reconcile" / "scripts"))
from edge_identity import compute_edge_id  # noqa: E402

SKILLS = Path.home() / ".claude" / "skills"
EDGE_SCHEMA = json.loads((SKILLS / "wiring-extract-static" / "schemas" / "wiring-source-edge.v1.json").read_text())
MANIFEST_SCHEMA = json.loads((SKILLS / "wiring-extract-static" / "schemas" / "wiring-source-manifest.v1.json").read_text())
SNAPSHOT_SCHEMA = json.loads((SKILLS / "wiring-reconcile" / "schemas" / "wiring-snapshot.v1.json").read_text())


def make_valid_edge(**overrides):
    base = {
        "schema_version": "1.0.0",
        "edge_id": compute_edge_id("auth", "auth.validateToken", "users", "users.getUser", "calls"),
        "src_component": "auth",
        "src_symbol": "auth.validateToken",
        "dst_component": "users",
        "dst_symbol": "users.getUser",
        "edge_kind": "calls",
        "evidence_source": "static_extract",
        "extractor_id": "fastapi",
        "extractor_version": "1.0.0",
        "workspace_tree_hash": "0" * 40,
        "emitted_at": "2026-04-14T12:00:00Z",
    }
    base.update(overrides)
    return base


def make_valid_manifest(**overrides):
    base = {
        "schema_version": "1.0.0",
        "run_id": "12345678-1234-1234-1234-123456789012",
        "workspace_tree_hash": "a" * 40,
        "project_dir": "/tmp/proj",
        "started_at": "2026-04-14T12:00:00Z",
        "sources": [
            {
                "source_id": "wiring-extract-static.scip-python",
                "evidence_source": "static_extract",
                "status": "succeeded",
                "output_path": "static.jsonl",
                "edge_count": 3,
            }
        ],
    }
    base.update(overrides)
    return base


def make_valid_snapshot(**overrides):
    eid = compute_edge_id("auth", "auth.validateToken", "users", "users.getUser", "calls")
    base = {
        "schema_version": "1.0.0",
        "snapshot_id": "abcdef0123456789",
        "snapshot_generation": 1,
        "run_id": "12345678-1234-1234-1234-123456789012",
        "workspace_tree_hash": "b" * 40,
        "generated_at": "2026-04-14T12:00:00Z",
        "generated_by": "wiring-reconcile@1.0.0",
        "source_statuses": {
            "static": {"status": "succeeded", "edge_count": 1, "last_seen_at": "2026-04-14T12:00:00Z"}
        },
        "edges": [
            {
                "edge_id": eid,
                "src_component": "auth",
                "src_symbol": "auth.validateToken",
                "dst_component": "users",
                "dst_symbol": "users.getUser",
                "edge_kind": "calls",
                "status": "live",
                "blocking_eligible": True,
                "evidence": [
                    {
                        "evidence_source": "static_extract",
                        "extractor_id": "fastapi",
                        "extractor_version": "1.0.0",
                        "last_seen_at": "2026-04-14T12:00:00Z",
                        "workspace_tree_hash": "b" * 40,
                    }
                ],
            }
        ],
    }
    base.update(overrides)
    return base


FORMAT_CHECKER = jsonschema.FormatChecker()


def expect_valid(schema, doc, label):
    try:
        jsonschema.validate(doc, schema, format_checker=FORMAT_CHECKER)
    except jsonschema.ValidationError as e:
        raise AssertionError(f"expected valid ({label}) but got: {e.message}") from e


def expect_invalid(schema, doc, label):
    try:
        jsonschema.validate(doc, schema, format_checker=FORMAT_CHECKER)
    except jsonschema.ValidationError:
        return
    raise AssertionError(f"expected invalid ({label}) but passed")


def test_edge_positives():
    expect_valid(EDGE_SCHEMA, make_valid_edge(), "edge-basic")
    expect_valid(EDGE_SCHEMA, make_valid_edge(evidence_source="agent_asserted"), "edge-agent-asserted")
    expect_valid(EDGE_SCHEMA, make_valid_edge(edge_kind="routes_to"), "edge-routes")
    expect_valid(EDGE_SCHEMA, make_valid_edge(confidence=0.85), "edge-confidence")
    expect_valid(EDGE_SCHEMA, make_valid_edge(
        callsite_ref={"file": "app/auth.py", "line": 42, "column": 0}
    ), "edge-callsite")


def test_edge_negatives():
    e = make_valid_edge(schema_version="2.0.0"); expect_invalid(EDGE_SCHEMA, e, "edge-bad-version")
    e = make_valid_edge(edge_id="short"); expect_invalid(EDGE_SCHEMA, e, "edge-bad-id")
    e = make_valid_edge(edge_kind="teleports"); expect_invalid(EDGE_SCHEMA, e, "edge-bad-kind")
    e = make_valid_edge(evidence_source="runtime_trace"); expect_invalid(EDGE_SCHEMA, e, "edge-deferred-runtime")
    e = make_valid_edge(extractor_version="1.0"); expect_invalid(EDGE_SCHEMA, e, "edge-bad-semver")
    e = make_valid_edge(workspace_tree_hash="zzz"); expect_invalid(EDGE_SCHEMA, e, "edge-bad-tree-hash")
    e = make_valid_edge(); del e["src_symbol"]; expect_invalid(EDGE_SCHEMA, e, "edge-missing-field")


def test_manifest_positives():
    expect_valid(MANIFEST_SCHEMA, make_valid_manifest(), "manifest-basic")
    m = make_valid_manifest(completed_at="2026-04-14T12:05:00Z",
                            languages_detected=["python", "typescript"],
                            frameworks_detected=["fastapi"])
    expect_valid(MANIFEST_SCHEMA, m, "manifest-full")
    m = make_valid_manifest()
    m["sources"][0]["status"] = "skipped"
    m["sources"][0]["gaps"] = ["scip-typescript not installed"]
    expect_valid(MANIFEST_SCHEMA, m, "manifest-with-gap")


def test_manifest_negatives():
    m = make_valid_manifest(schema_version="2.0.0"); expect_invalid(MANIFEST_SCHEMA, m, "manifest-bad-ver")
    m = make_valid_manifest(run_id="not-a-uuid"); expect_invalid(MANIFEST_SCHEMA, m, "manifest-bad-uuid")
    m = make_valid_manifest()
    m["sources"][0]["status"] = "exploded"
    expect_invalid(MANIFEST_SCHEMA, m, "manifest-bad-status")
    m = make_valid_manifest()
    m["sources"][0]["evidence_source"] = "runtime_trace"
    expect_invalid(MANIFEST_SCHEMA, m, "manifest-deferred-runtime")
    m = make_valid_manifest(); del m["started_at"]; expect_invalid(MANIFEST_SCHEMA, m, "manifest-missing-started")


def test_snapshot_positives():
    expect_valid(SNAPSHOT_SCHEMA, make_valid_snapshot(), "snapshot-basic")
    s = make_valid_snapshot()
    s["edges"][0]["status"] = "stale"
    s["edges"][0]["blocking_eligible"] = False
    expect_valid(SNAPSHOT_SCHEMA, s, "snapshot-stale")
    s = make_valid_snapshot()
    s["edges"][0]["evidence"].append({
        "evidence_source": "agent_asserted",
        "extractor_id": "harness",
        "extractor_version": "1.0.0",
        "last_seen_at": "2026-04-14T12:00:00Z",
        "workspace_tree_hash": "b" * 40,
    })
    expect_valid(SNAPSHOT_SCHEMA, s, "snapshot-multi-evidence")
    s = make_valid_snapshot()
    s["signature"] = {
        "algorithm": "HMAC-SHA256",
        "key_id": "forge-session-abc",
        "signed_at": "2026-04-14T12:00:00Z",
        "signed_fields": ["snapshot_id", "edges"],
        "digest": "f" * 64,
    }
    expect_valid(SNAPSHOT_SCHEMA, s, "snapshot-signed")


def test_snapshot_negatives():
    s = make_valid_snapshot(generated_by="other@1.0.0"); expect_invalid(SNAPSHOT_SCHEMA, s, "snapshot-bad-generator")
    s = make_valid_snapshot(snapshot_generation=0); expect_invalid(SNAPSHOT_SCHEMA, s, "snapshot-gen-zero")
    s = make_valid_snapshot()
    s["edges"][0]["status"] = "flying"
    expect_invalid(SNAPSHOT_SCHEMA, s, "snapshot-bad-edge-status")
    s = make_valid_snapshot()
    s["edges"][0]["evidence"] = []
    expect_invalid(SNAPSHOT_SCHEMA, s, "snapshot-no-evidence")
    s = make_valid_snapshot()
    s["signature"] = {
        "algorithm": "HMAC-SHA256",
        "key_id": "k",
        "signed_at": "2026-04-14T12:00:00Z",
        "signed_fields": [],
        "digest": "shortdigest",
    }
    expect_invalid(SNAPSHOT_SCHEMA, s, "snapshot-bad-digest-length")


def main():
    tests = [
        test_edge_positives, test_edge_negatives,
        test_manifest_positives, test_manifest_negatives,
        test_snapshot_positives, test_snapshot_negatives,
    ]
    passed = 0
    failed = []
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            failed.append(f"{t.__name__}: {e}")
    total = len(tests)
    if failed:
        print(f"FAIL {len(failed)}/{total}")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)
    print(f"PASS {passed}/{total}")


if __name__ == "__main__":
    main()
