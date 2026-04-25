#!/usr/bin/env python3
"""test_visual_architect.py — contract-map TS-VA-01..03 coverage for WP-8.

TS-VA-01  happy freeze — draft + 3 user-edits (2 binds_to assignments +
          1 unresolved-token approval) -> index.yaml + screen.yaml both
          HMAC-signed + transition request emitted with event=skeleton_frozen.
TS-VA-02  reject freeze on unresolved binds_to — user enters
          capability://nonexistent.method -> visual-architect emits challenge
          via claims.file_challenge, exits non-zero.
TS-VA-03  reject freeze on unresolved tokens without approval — mockup
          has hardcoded '#ac3b3b', user_edits neither approves nor rejects
          -> D2 strict fails the freeze.

Run:
    pytest ~/.claude/skills/visual-architect/tests/ -v
"""
from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

_META_DIR = Path.home() / ".claude" / "skills" / "_meta"
sys.path.insert(0, str(_META_DIR))

import claims as claims_mod  # noqa: E402
import freeze as freeze_mod  # noqa: E402
import trusted_runner  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session_key(tmp_path: Path) -> Path:
    """Produce a 65-byte session.key (64-hex + trailing newline) — S024/S025
    invariant. `openssl rand -hex 32` produces 64 hex characters + newline."""
    try:
        out = subprocess.run(
            ["openssl", "rand", "-hex", "32"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        hex_key = out.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Fallback: deterministic key if openssl unavailable
        hex_key = "a" * 64
    forge_dir = tmp_path / ".forge"
    forge_dir.mkdir(parents=True, exist_ok=True)
    key_path = forge_dir / "session.key"
    # Write hex + trailing newline (total 65 bytes)
    key_path.write_bytes((hex_key + "\n").encode("ascii"))
    return key_path


def _make_mockup(tmp_path: Path) -> Path:
    mockup = tmp_path / "mockup.html"
    mockup.write_text(
        "<!doctype html><html><body>"
        "<header class='masthead'>Weather</header>"
        "<div id='grid'>"
        "<div class='card'><h2>Step 1</h2></div>"
        "<div class='card'><h2>Step 2</h2></div>"
        "</div>"
        "</body></html>",
        encoding="utf-8",
    )
    return mockup


def _make_contract_map(tmp_path: Path, capabilities: Dict[str, Any]) -> Path:
    """Write a minimal contract-map.yaml with the given capabilities.

    capabilities = {"journey_controller": ["advance_step"], ...}

    _lookup_capability expects `capabilities` under a component to be a DICT
    keyed by capability_id (uri.py:257-259); list shape won't resolve.
    """
    components = []
    for comp_id, caps in capabilities.items():
        components.append({
            "id": comp_id,
            "purpose": f"Stub component {comp_id} for visual-architect tests",
            "capabilities": {
                c: {"purpose": f"stub capability {c}"} for c in caps
            },
        })
    doc = {
        "schema_version": "1.0.0",
        "revision": 1,
        "design_doc": "docs/plans/test.md",
        "generated_at": "2026-04-22T00:00:00Z",
        "generated_by": "test",
        "components": components,
    }
    path = tmp_path / "progress" / "contract-map.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=True))
    return path


def _make_draft(tmp_path: Path, *, unresolved_tokens=None) -> Path:
    """Write a draft skeleton YAML (output of skeleton-extractor shape)."""
    draft = {
        "schema": "design-skeleton.draft.v1",
        "index_id": "8c3f9e2c-1a7d-4b6e-9a08-f1c2d3e4f567",
        "screen_id": "journey_main",
        "screen_uuid": "b2f1c8e4-5a9d-4f2c-8b1e-a4d5e6f7a8b9",
        "forge_session_id": "fs-test",
        "breakpoints": {
            "mobile":  {"width": 420,  "height": 900},
            "desktop": {"width": 1280, "height": 900},
        },
        "tokens": {
            "color": {
                "ink":        "#0a0a0a",
                "paper":      "#f5f1e8",
            },
        },
        "components": {},
        "elements": [
            {
                "id": "masthead",
                "kind": "structural",
                "selector": "header.masthead",
                "bbox": {
                    "mobile":  {"x": 0, "y": 0, "w": 420,  "h": 80},
                    "desktop": {"x": 0, "y": 0, "w": 1280, "h": 120},
                },
                "interactions": [],
            },
            {
                "id": "step_card.1",
                "kind": "component_instance",
                "selector": "#grid .card:nth-child(1)",
                "bbox": {
                    "mobile":  {"x": 16, "y": 96,  "w": 388, "h": 260},
                    "desktop": {"x": 48, "y": 136, "w": 384, "h": 220},
                },
                "interactions": [
                    {"event": "click", "binds_to": None},
                    {"event": "hover", "binds_to": None},
                ],
            },
        ],
        "unresolved_tokens": unresolved_tokens or [],
    }
    path = tmp_path / "draft.yaml"
    path.write_text(yaml.safe_dump(draft, sort_keys=True))
    return path


# ---------------------------------------------------------------------------
# TS-VA-01 — happy freeze
# ---------------------------------------------------------------------------


def test_ts_va_01_happy_freeze_signed_and_request_emitted(tmp_path, monkeypatch):
    """Happy path: draft + 3 user edits -> signed index + screen + request."""
    # Contract map with capability://journey_controller.advance_step
    _make_contract_map(tmp_path, {"journey_controller": ["advance_step"]})

    mockup = _make_mockup(tmp_path)
    session_key = _make_session_key(tmp_path)
    draft = _make_draft(
        tmp_path,
        unresolved_tokens=[{"value": "#ac3b3b", "seen_at": [".card"]}],
    )

    # User edits: 2 binds_to + 1 token approval
    user_edits = {
        "binds_to_assignments": {
            "step_card.1#click": "capability://journey_controller.advance_step",
            "step_card.1#hover": "visual_only",
        },
        "tokens_approved": [
            {"value": "#ac3b3b", "add_as": "color.accent.brick"},
        ],
    }

    out_index = tmp_path / ".design-ledger" / "skeletons" / "index.yaml"
    out_screen = tmp_path / ".design-ledger" / "skeletons" / "journey_main.yaml"

    result = freeze_mod.freeze_skeleton(
        draft_path=draft,
        mockup_path=mockup,
        user_edits=user_edits,
        out_index_path=out_index,
        out_screen_path=out_screen,
        session_key_path=session_key,
        project_root=tmp_path,
        claim_uuid="test-claim-0001",
    )

    assert result["status"] == "frozen", f"expected frozen, got {result!r}"
    assert out_index.is_file()
    assert out_screen.is_file()

    # Parse persisted files
    index_doc = yaml.safe_load(out_index.read_text())
    screen_doc = yaml.safe_load(out_screen.read_text())

    # Schema + provenance
    assert index_doc["schema"] == "design-skeleton-index.v1"
    assert screen_doc["schema"] == "design-skeleton.v1"
    assert index_doc["design_doc_hash"] == hashlib.sha256(mockup.read_bytes()).hexdigest()
    assert index_doc["skeleton_version"] == "1.0"

    # Token approval written
    assert index_doc["tokens"]["color"]["accent"]["brick"] == "#ac3b3b"

    # binds_to assignment applied (step_card.1.click now bound)
    click_inter = next(
        inter for el in screen_doc["elements"] if el["id"] == "step_card.1"
        for inter in el["interactions"] if inter["event"] == "click"
    )
    assert click_inter["binds_to"] == "capability://journey_controller.advance_step"

    # visual_only applied to hover
    hover_inter = next(
        inter for el in screen_doc["elements"] if el["id"] == "step_card.1"
        for inter in el["interactions"] if inter["event"] == "hover"
    )
    assert hover_inter.get("visual_only") is True

    # HMAC signature recomputes (S025 pattern — key.read_bytes() + trailing newline)
    key_bytes = session_key.read_bytes()
    created_at = index_doc["signature"]["signed_at"]
    expected_payload = {
        "skeleton_hash": index_doc["index_hash"],
        "skeleton_version": "1.0",
        "design_doc_hash": index_doc["design_doc_hash"],
        "created_at": created_at,
    }
    expected_msg = json.dumps(
        expected_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    expected_digest = hmac.new(key_bytes, expected_msg, hashlib.sha256).hexdigest()
    assert index_doc["signature"]["digest"] == expected_digest, (
        "HMAC signature must match S025 pattern exactly: canonical JSON + "
        "session_key.read_bytes() (including trailing newline)"
    )
    assert index_doc["signature"]["algorithm"] == "HMAC-SHA256"
    assert index_doc["signature"]["key_id"] == ".forge/session.key"

    # Both files are bundle_write-atomic (no orphan rollback left)
    rollback_dir = tmp_path / ".tmp" / "rollback"
    if rollback_dir.is_dir():
        assert not any(rollback_dir.iterdir()), (
            "successful bundle_write must leave no rollback residuals"
        )

    # Transition request emitted with event=skeleton_frozen
    req_dir = tmp_path / ".ledger" / "requests"
    requests = list(req_dir.glob("*.request.yaml"))
    assert len(requests) == 1, f"expected 1 request, got {len(requests)}"
    req = yaml.safe_load(requests[0].read_text())
    assert req["event"] == "skeleton_frozen"
    assert req["claim_uuid"] == "test-claim-0001"
    assert req["index_hash"] == index_doc["index_hash"]
    assert req["skill"] == "visual-architect"
    assert req["wp"] == "WP-8"

    # CB4: no write to progress/integration-ledger.md or .ledger/claims/
    assert not (tmp_path / "progress" / "integration-ledger.md").exists()
    assert not (tmp_path / ".ledger" / "claims").exists()


# ---------------------------------------------------------------------------
# TS-VA-02 — reject on unresolved binds_to
# ---------------------------------------------------------------------------


def test_ts_va_02_reject_on_unresolved_binds_to(tmp_path, monkeypatch):
    """User enters capability://nonexistent.method -> freeze rejected +
    claims.file_challenge invoked with reason=functional_requirement_conflict."""
    _make_contract_map(tmp_path, {"journey_controller": ["advance_step"]})
    mockup = _make_mockup(tmp_path)
    session_key = _make_session_key(tmp_path)
    draft = _make_draft(tmp_path)

    user_edits = {
        "binds_to_assignments": {
            "step_card.1#click": "capability://phantom_controller.nonexistent_method",
            "step_card.1#hover": "visual_only",
        },
    }

    # Patch claims.file_challenge to observe the call
    original_file_challenge = claims_mod.file_challenge
    call_spy: Dict[str, Any] = {"count": 0, "kwargs": []}

    def _spy(project_root, **kwargs):
        call_spy["count"] += 1
        call_spy["kwargs"].append(kwargs)
        return original_file_challenge(project_root, **kwargs)

    monkeypatch.setattr(freeze_mod.claims_mod, "file_challenge", _spy)

    out_index = tmp_path / ".design-ledger" / "skeletons" / "index.yaml"
    out_screen = tmp_path / ".design-ledger" / "skeletons" / "journey_main.yaml"

    result = freeze_mod.freeze_skeleton(
        draft_path=draft,
        mockup_path=mockup,
        user_edits=user_edits,
        out_index_path=out_index,
        out_screen_path=out_screen,
        session_key_path=session_key,
        project_root=tmp_path,
        claim_uuid="test-claim-0002",
    )

    assert result["status"] == "rejected_binds_to"
    assert len(result["failures"]) == 1
    assert result["failures"][0]["binds_to"] == "capability://phantom_controller.nonexistent_method"
    assert len(result["challenges_filed"]) == 1

    # claims.file_challenge was invoked exactly once with expected reason
    assert call_spy["count"] == 1
    filed_kwargs = call_spy["kwargs"][0]
    assert filed_kwargs["reason"] == "functional_requirement_conflict"
    assert filed_kwargs["filed_by"] == "visual-architect"
    assert filed_kwargs["skeleton_ref"] == "skeleton://journey_main#step_card.1"

    # No signed artifacts written
    assert not out_index.exists()
    assert not out_screen.exists()
    # No transition request emitted
    req_dir = tmp_path / ".ledger" / "requests"
    if req_dir.is_dir():
        assert list(req_dir.glob("*.request.yaml")) == []


# ---------------------------------------------------------------------------
# TS-VA-03 — reject on unresolved tokens without approval (D2 strict)
# ---------------------------------------------------------------------------


def test_ts_va_03_reject_on_unresolved_tokens_without_approval(tmp_path, monkeypatch):
    """Mockup has hardcoded '#ac3b3b' but user_edits neither approves nor
    rejects it -> D2 strict fails the freeze."""
    _make_contract_map(tmp_path, {"journey_controller": ["advance_step"]})
    mockup = _make_mockup(tmp_path)
    session_key = _make_session_key(tmp_path)
    draft = _make_draft(
        tmp_path,
        unresolved_tokens=[
            {"value": "#ac3b3b", "seen_at": [".card"]},
            {"value": "#ff00aa", "seen_at": [".btn"]},
        ],
    )

    # User edits: binds_to complete, but tokens_approved does NOT mention
    # the unresolved values. tokens_rejected also empty.
    # This is the D2-strict violation scenario.
    user_edits = {
        "binds_to_assignments": {
            "step_card.1#click": "capability://journey_controller.advance_step",
            "step_card.1#hover": "visual_only",
        },
        # no tokens_approved, no tokens_rejected
    }

    out_index = tmp_path / ".design-ledger" / "skeletons" / "index.yaml"
    out_screen = tmp_path / ".design-ledger" / "skeletons" / "journey_main.yaml"

    result = freeze_mod.freeze_skeleton(
        draft_path=draft,
        mockup_path=mockup,
        user_edits=user_edits,
        out_index_path=out_index,
        out_screen_path=out_screen,
        session_key_path=session_key,
        project_root=tmp_path,
        claim_uuid="test-claim-0003",
    )

    assert result["status"] == "rejected_tokens"
    assert set(result["unresolved_tokens"]) == {"#ac3b3b", "#ff00aa"}, (
        "D2 strict: every unresolved token must surface as a gap (no silent skip)"
    )
    # No challenges filed for tokens (challenges are only for functional
    # binds_to conflicts, not user-input gaps)
    assert result["challenges_filed"] == []

    # No signed artifacts written
    assert not out_index.exists()
    assert not out_screen.exists()

    # Rejecting one token but not the other -> still fails (at least one gap)
    user_edits_partial = {
        "binds_to_assignments": user_edits["binds_to_assignments"],
        "tokens_rejected": ["#ff00aa"],
        # #ac3b3b still neither approved nor rejected
    }
    result2 = freeze_mod.freeze_skeleton(
        draft_path=draft,
        mockup_path=mockup,
        user_edits=user_edits_partial,
        out_index_path=out_index,
        out_screen_path=out_screen,
        session_key_path=session_key,
        project_root=tmp_path,
        claim_uuid="test-claim-0003b",
    )
    assert result2["status"] == "rejected_tokens"
    assert "#ac3b3b" in result2["unresolved_tokens"]
    # #ff00aa was explicitly rejected — it still counts as a gap, because
    # D2 strict means EITHER add-to-tokens OR reject-the-freeze; rejecting
    # does not silently drop — it signals the user wants to redo the mockup.
    assert "#ff00aa" in result2["unresolved_tokens"]


# ---------------------------------------------------------------------------
# Library importability check (caller can `from freeze import freeze_skeleton`)
# ---------------------------------------------------------------------------


def test_library_entry_point_importable():
    assert callable(freeze_mod.freeze_skeleton)
    # signature sanity — keyword-only args
    import inspect
    sig = inspect.signature(freeze_mod.freeze_skeleton)
    for required in (
        "draft_path", "mockup_path", "user_edits",
        "out_index_path", "out_screen_path", "session_key_path",
        "project_root",
    ):
        assert required in sig.parameters, f"freeze_skeleton missing param {required}"
