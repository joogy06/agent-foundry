#!/usr/bin/env python3
"""freeze.py — visual-architect design-phase freeze (WP-8 of S028).

Transforms an unsigned draft skeleton (from skeleton-extractor) + an approved
HTML mockup + user edits into two HMAC-signed frozen YAML files:

    .design-ledger/skeletons/index.yaml       (design-skeleton-index.v1)
    .design-ledger/skeletons/<screen>.yaml    (design-skeleton.v1)

plus a `skeleton_frozen` transition request at `.ledger/requests/` that bob
applies via `claims.apply_request_idempotent` (CB4: skill NEVER writes to
`progress/integration-ledger.md` or `.ledger/claims/`).

Public API:
    freeze_skeleton(draft_path, mockup_path, user_edits, out_index_path,
                    out_screen_path, session_key_path, project_root,
                    claim_uuid=None) -> dict

CLI:
    python3 freeze.py freeze \
        --draft <path> --mockup <path> --user-edits <path> \
        --out-index <path> --out-screen <path> \
        --forge-session-key <path> \
        [--claim-uuid <uuid>] [--project-root <dir>]

Exit codes:
    0  frozen
    1  rejected — unresolved `binds_to` URI (challenge filed)
    2  rejected — unresolved token without explicit user approval (D2 strict)
    3  environmental / usage error

HMAC signature pattern (S025-compatible):
    key   = session_key_path.read_bytes()  # includes trailing newline
    payload = {"skeleton_hash": ..., "skeleton_version": ...,
               "design_doc_hash": ..., "created_at": ...}
    msg   = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")
    digest = hmac.new(key, msg, hashlib.sha256).hexdigest()

Forbidden (HARD invariants):
    - modifying Foundation primitives
    - invoking skeleton-extractor
    - writing `.ledger/claims/` or `progress/integration-ledger.md`
    - silent token skip (D2 strict)
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed. freeze.py requires pyyaml.\n")
    sys.exit(3)


# ---------------------------------------------------------------------------
# Foundation primitive imports (fail-open on ImportError -> env error)
# ---------------------------------------------------------------------------

_META_DIR = Path.home() / ".claude" / "skills" / "_meta"


def _ensure_meta_on_path() -> None:
    """Allow tests to inject alt _meta dir via VISUAL_ARCHITECT_META_DIR."""
    override = os.environ.get("VISUAL_ARCHITECT_META_DIR")
    target = Path(override) if override else _META_DIR
    if target.is_dir() and str(target) not in sys.path:
        sys.path.insert(0, str(target))


_ensure_meta_on_path()

try:
    import trusted_runner  # type: ignore
except ImportError as e:  # pragma: no cover -- env error
    sys.stderr.write(f"FATAL: trusted_runner unavailable: {e}\n")
    sys.exit(3)

try:
    import uri as uri_mod  # type: ignore
except ImportError as e:  # pragma: no cover -- env error
    sys.stderr.write(f"FATAL: uri module unavailable: {e}\n")
    sys.exit(3)

try:
    import claims as claims_mod  # type: ignore
except ImportError as e:  # pragma: no cover -- env error
    sys.stderr.write(f"FATAL: claims module unavailable: {e}\n")
    sys.exit(3)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_INDEX = "design-skeleton-index.v1"
SCHEMA_SCREEN = "design-skeleton.v1"
DEFAULT_SKELETON_VERSION = "1.0"
VISUAL_ONLY_SENTINEL = "visual_only"
SIGNED_FIELDS = ("skeleton_hash", "skeleton_version", "design_doc_hash", "created_at")
LEDGER_REQUESTS_SUBDIR = ".ledger/requests"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_json_bytes(obj: Any) -> bytes:
    """Canonical JSON encoding used for hashing + HMAC.

    Matches trusted_runner.canonical_bundle_bytes exactly: sort_keys=True,
    compact separators, UTF-8, ensure_ascii=False.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _load_yaml(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"malformed YAML at {path}: {e}") from e


def _load_user_edits(path: Path) -> Dict[str, Any]:
    """Accept YAML or JSON; return a dict."""
    if not path.is_file():
        raise FileNotFoundError(f"user-edits not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"malformed user-edits YAML at {path}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"user-edits at {path} must be a mapping, got {type(data).__name__}")
    return data


def _yaml_dump(obj: Any) -> bytes:
    """Deterministic YAML output for signed files."""
    return yaml.safe_dump(
        obj, sort_keys=True, default_flow_style=False, allow_unicode=True,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Token block assembly
# ---------------------------------------------------------------------------


def _set_nested(root: Dict[str, Any], dotted_path: str, value: Any) -> None:
    """Set `root[a][b][c] = value` when dotted_path == 'a.b.c'.

    Creates intermediate dicts as needed. Overwrites any existing scalar.
    """
    keys = dotted_path.split(".")
    node: Any = root
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            node[k] = {}
        node = node[k]
    node[keys[-1]] = value


def _apply_token_approvals(
    tokens_block: Dict[str, Any],
    unresolved_tokens: List[Dict[str, Any]],
    approved: List[Dict[str, Any]],
    rejected: List[str],
) -> Tuple[Dict[str, Any], List[str]]:
    """Return (updated_tokens_block, unresolved_and_unaddressed_values).

    D2 strict semantics: every unresolved token MUST appear in either
    `approved` (-> added to tokens) or `rejected` (-> causes caller to fail).
    Silent drop is forbidden.
    """
    approved_by_value: Dict[str, str] = {
        str(entry["value"]): str(entry["add_as"])
        for entry in (approved or [])
        if isinstance(entry, dict) and "value" in entry and "add_as" in entry
    }
    rejected_set = {str(v) for v in (rejected or [])}

    updated = _deep_copy_dict(tokens_block)
    gap: List[str] = []
    for entry in unresolved_tokens:
        value = str(entry.get("value") if isinstance(entry, dict) else entry)
        if value in rejected_set:
            gap.append(value)
            continue
        if value in approved_by_value:
            _set_nested(updated, approved_by_value[value], value)
            continue
        # D2 strict: neither approved nor rejected == gap.
        gap.append(value)
    return updated, gap


def _deep_copy_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(d)) if d else {}


# ---------------------------------------------------------------------------
# binds_to assembly
# ---------------------------------------------------------------------------


def _iter_interactions(elements: List[Dict[str, Any]]):
    """Yield (element_index, interaction_index, element, interaction)."""
    for ei, el in enumerate(elements or []):
        for ii, inter in enumerate(el.get("interactions") or []):
            yield ei, ii, el, inter


def _apply_binds_to(
    screen_body: Dict[str, Any],
    binds_to_assignments: Dict[str, Any],
) -> List[str]:
    """Apply user binds_to assignments. Return list of still-unwired keys.

    binds_to_assignments maps 'element_id#event' -> capability URI or the
    literal string 'visual_only' (sets visual_only: true on the interaction).
    """
    missing: List[str] = []
    elements = screen_body.get("elements") or []
    for _ei, _ii, el, inter in _iter_interactions(elements):
        if inter.get("binds_to") is not None or inter.get("visual_only"):
            # already wired (skeleton-extractor preserved a prior binding,
            # or draft already marked visual_only)
            continue
        key = f"{el.get('id')}#{inter.get('event')}"
        assignment = binds_to_assignments.get(key)
        if assignment is None:
            missing.append(key)
            continue
        if assignment == VISUAL_ONLY_SENTINEL:
            inter["visual_only"] = True
            inter["binds_to"] = None
        else:
            inter["binds_to"] = str(assignment)
    return missing


def _collect_capability_bindings(
    screen_body: Dict[str, Any],
) -> List[Tuple[str, str, str]]:
    """Return list of (element_id, event, capability_uri) for every wired
    non-visual-only interaction with a `capability://` URI. Skip
    visual_only + non-capability schemes (validator only checks capabilities)."""
    out: List[Tuple[str, str, str]] = []
    for _ei, _ii, el, inter in _iter_interactions(screen_body.get("elements") or []):
        binds = inter.get("binds_to")
        if not binds or inter.get("visual_only"):
            continue
        if not isinstance(binds, str) or not binds.startswith("capability://"):
            continue
        out.append((str(el.get("id")), str(inter.get("event")), binds))
    return out


# ---------------------------------------------------------------------------
# HMAC signature
# ---------------------------------------------------------------------------


def _build_signature(
    skeleton_hash: str,
    skeleton_version: str,
    design_doc_hash: str,
    created_at: str,
    session_key_bytes: bytes,
) -> Dict[str, Any]:
    payload = {
        "skeleton_hash": skeleton_hash,
        "skeleton_version": skeleton_version,
        "design_doc_hash": design_doc_hash,
        "created_at": created_at,
    }
    msg = _canonical_json_bytes(payload)
    digest = hmac.new(session_key_bytes, msg, hashlib.sha256).hexdigest()
    return {
        "algorithm": "HMAC-SHA256",
        "key_id": ".forge/session.key",
        "signed_fields": list(SIGNED_FIELDS),
        "signed_at": created_at,
        "digest": digest,
    }


def _compute_index_hash(index_body: Dict[str, Any]) -> str:
    """sha256 of canonical-JSON(index_body) excluding `index_hash` + `signature`."""
    filtered = {k: v for k, v in index_body.items() if k not in ("index_hash", "signature")}
    return _sha256_hex(_canonical_json_bytes(filtered))


def _compute_screen_hash(screen_body: Dict[str, Any]) -> str:
    """sha256 of canonical-JSON(screen_body) excluding `signature`."""
    filtered = {k: v for k, v in screen_body.items() if k != "signature"}
    return _sha256_hex(_canonical_json_bytes(filtered))


# ---------------------------------------------------------------------------
# Transition request emission
# ---------------------------------------------------------------------------


def _emit_skeleton_frozen_request(
    project_root: Path,
    *,
    claim_uuid: Optional[str],
    out_index_path: Path,
    out_screen_path: Path,
    index_hash: str,
    screen_hash: str,
    index_bytes: bytes,
    screen_bytes: bytes,
    design_doc_hash: str,
    skeleton_version: str,
) -> Path:
    """Write a `skeleton_frozen` transition request.

    CB4: bob is sole ledger writer. This emits a REQUEST only; bob applies via
    `claims.apply_request_idempotent`.
    """
    req_dir = project_root / LEDGER_REQUESTS_SUBDIR
    req_dir.mkdir(parents=True, exist_ok=True)
    req_id = str(uuid.uuid4())
    payload = {
        "request_id": req_id,
        "claim_uuid": claim_uuid,
        "skill": "visual-architect",
        "wp": "WP-8",
        "event": "skeleton_frozen",
        "emitted_at": _now_iso(),
        "index_path": str(out_index_path),
        "index_hash": index_hash,
        "index_bytes_hash": _sha256_hex(index_bytes),
        "screen_path": str(out_screen_path),
        "screen_hash": screen_hash,
        "screen_bytes_hash": _sha256_hex(screen_bytes),
        "design_doc_hash": design_doc_hash,
        "skeleton_version": skeleton_version,
    }
    text = yaml.safe_dump(payload, sort_keys=True)
    req_path = req_dir / f"{req_id}.request.yaml"
    trusted_runner.atomic_write_bytes(req_path, text.encode("utf-8"))
    return req_path


# ---------------------------------------------------------------------------
# Validation — unresolved binds_to -> file_challenge
# ---------------------------------------------------------------------------


def _validate_binds_to_resolve(
    project_root: Path,
    screen_body: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Validate every capability:// URI resolves. Return list of failures.

    Failure record: {element_id, event, binds_to, reason}. An empty list
    means all URIs resolve cleanly.
    """
    failures: List[Dict[str, Any]] = []
    for element_id, event, binds in _collect_capability_bindings(screen_body):
        if uri_mod.exists(binds, project_root):
            continue
        failures.append({
            "element_id": element_id,
            "event": event,
            "binds_to": binds,
            "reason": "uri_does_not_resolve",
        })
    return failures


def _file_binds_to_challenges(
    project_root: Path,
    screen_id: str,
    screen_uuid: Optional[str],
    failures: List[Dict[str, Any]],
) -> List[str]:
    """File `functional_requirement_conflict` challenge for each failure.

    Each challenge auto-emits a process-observation via fail-open
    claude_observe (see claims.py._CHALLENGE_REASON_TO_OBS_CATEGORY).
    """
    filed_ids: List[str] = []
    for failure in failures:
        skeleton_ref = f"skeleton://{screen_id}#{failure['element_id']}"
        record = claims_mod.file_challenge(
            project_root,
            skeleton_ref=skeleton_ref,
            reason="functional_requirement_conflict",
            details={
                "event": failure["event"],
                "binds_to": failure["binds_to"],
                "reason": failure["reason"],
                "screen_uuid": screen_uuid,
            },
            proposed_resolution={"note": "add missing capability to contract-map"},
            filed_by="visual-architect",
        )
        filed_ids.append(record["challenge_id"])
    return filed_ids


# ---------------------------------------------------------------------------
# Main freeze entry point
# ---------------------------------------------------------------------------


def freeze_skeleton(
    *,
    draft_path: Path,
    mockup_path: Path,
    user_edits: Dict[str, Any],
    out_index_path: Path,
    out_screen_path: Path,
    session_key_path: Path,
    project_root: Path,
    claim_uuid: Optional[str] = None,
    skeleton_version: str = DEFAULT_SKELETON_VERSION,
    forge_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Freeze the draft skeleton into signed index + screen YAML.

    Returns a dict with keys:
        status              'frozen' | 'rejected_binds_to' | 'rejected_tokens'
        index_path          Path    (only when status == 'frozen')
        screen_path         Path    (only when status == 'frozen')
        request_path        Path    (only when status == 'frozen')
        signature           dict    (only when status == 'frozen')
        challenges_filed    list[str]
        unresolved_tokens   list[str]  (only when status == 'rejected_tokens')
        failures            list[dict] (only when status == 'rejected_binds_to')
    """
    draft_path = Path(draft_path).resolve()
    mockup_path = Path(mockup_path).resolve()
    out_index_path = Path(out_index_path)
    out_screen_path = Path(out_screen_path)
    session_key_path = Path(session_key_path).resolve()
    project_root = Path(project_root).resolve()

    # Load draft
    draft = _load_yaml(draft_path)
    if not isinstance(draft, dict):
        raise ValueError(f"draft at {draft_path} is not a mapping")

    # Load mockup bytes for design_doc_hash
    if not mockup_path.is_file():
        raise FileNotFoundError(f"mockup not found: {mockup_path}")
    mockup_bytes = mockup_path.read_bytes()
    design_doc_hash = _sha256_hex(mockup_bytes)

    # Load session.key (bytes INCLUDING trailing newline — S024/S025 invariant)
    if not session_key_path.is_file():
        raise FileNotFoundError(f"session.key not found: {session_key_path}")
    session_key_bytes = session_key_path.read_bytes()

    # Split draft into screen body + tokens block
    tokens_block_initial: Dict[str, Any] = dict(draft.get("tokens") or {})
    unresolved_tokens = list(draft.get("unresolved_tokens") or [])
    screen_body_raw = {k: v for k, v in draft.items() if k not in ("tokens", "unresolved_tokens")}
    screen_body: Dict[str, Any] = _deep_copy_dict(screen_body_raw)

    screen_id = str(screen_body.get("screen_id") or out_screen_path.stem)
    screen_uuid = screen_body.get("screen_uuid")

    # Apply user edits ---------------------------------------------------
    # 1) binds_to
    binds_to_assignments = dict(user_edits.get("binds_to_assignments") or {})
    missing_binds = _apply_binds_to(screen_body, binds_to_assignments)
    if missing_binds:
        raise ValueError(
            f"user-edits missing binds_to_assignments for: {sorted(missing_binds)} "
            f"(every null binds_to must be addressed before freeze)"
        )

    # 2) bbox confirmations (optional; default = keep extractor's bbox)
    bbox_confirmations = dict(user_edits.get("bbox_confirmations") or {})
    if bbox_confirmations:
        for el in screen_body.get("elements") or []:
            eid = el.get("id")
            if eid in bbox_confirmations:
                # user's confirmed bbox replaces draft's per-breakpoint map
                el_bbox = el.get("bbox") or {}
                el_bbox.update(bbox_confirmations[eid])
                el["bbox"] = el_bbox

    # 3) tokens (D2 strict)
    tokens_approved = list(user_edits.get("tokens_approved") or [])
    tokens_rejected = list(user_edits.get("tokens_rejected") or [])
    tokens_block, token_gap = _apply_token_approvals(
        tokens_block_initial, unresolved_tokens, tokens_approved, tokens_rejected,
    )
    if token_gap:
        # D2 strict — fail the freeze WITHOUT filing a challenge (this is a
        # user-input gap, not a functional conflict). Caller should loop back
        # to the user for explicit approval/rejection.
        return {
            "status": "rejected_tokens",
            "unresolved_tokens": sorted(token_gap),
            "challenges_filed": [],
        }

    # Validate binds_to URIs AFTER user edits have been applied ---------
    failures = _validate_binds_to_resolve(project_root, screen_body)
    if failures:
        # File one challenge per failure — each auto-emits an observation.
        filed = _file_binds_to_challenges(project_root, screen_id, screen_uuid, failures)
        return {
            "status": "rejected_binds_to",
            "failures": failures,
            "challenges_filed": filed,
        }

    # Build frozen index body --------------------------------------------
    created_at = _now_iso()
    index_body: Dict[str, Any] = {
        "schema": SCHEMA_INDEX,
        "index_id": str(draft.get("index_id") or uuid.uuid4()),
        "design_doc_hash": design_doc_hash,
        "skeleton_version": skeleton_version,
        "parent_version": draft.get("parent_version"),
        "created_at": created_at,
        "created_by": "visual-architect",
        "forge_session_id": forge_session_id or str(draft.get("forge_session_id") or ""),
        "breakpoints": draft.get("breakpoints") or {},
        "tokens": tokens_block,
        "components": draft.get("components") or {},
        "screens": [{
            "screen_id": screen_id,
            "screen_uuid": screen_uuid,
            "file": out_screen_path.name,
            "entry": bool(screen_body.get("entry", True)),
        }],
        "must_satisfy": draft.get("must_satisfy") or {
            "all_interactions_wired": True,
            "tokens_match_by_reference_only": True,
        },
    }
    index_hash = _compute_index_hash(index_body)
    index_body["index_hash"] = index_hash
    index_body["signature"] = _build_signature(
        skeleton_hash=index_hash,
        skeleton_version=skeleton_version,
        design_doc_hash=design_doc_hash,
        created_at=created_at,
        session_key_bytes=session_key_bytes,
    )

    # Build frozen screen body -------------------------------------------
    screen_body["schema"] = SCHEMA_SCREEN
    screen_body["screen_id"] = screen_id
    if screen_uuid is not None:
        screen_body["screen_uuid"] = screen_uuid
    screen_body["parent_index"] = {
        "path": out_index_path.name,
        "hash": index_hash,
    }
    screen_body["skeleton_version"] = skeleton_version
    screen_hash = _compute_screen_hash(screen_body)
    screen_body["signature"] = _build_signature(
        skeleton_hash=screen_hash,
        skeleton_version=skeleton_version,
        design_doc_hash=design_doc_hash,
        created_at=created_at,
        session_key_bytes=session_key_bytes,
    )

    # Serialize ----------------------------------------------------------
    index_bytes = _yaml_dump(index_body)
    screen_bytes = _yaml_dump(screen_body)

    # Atomic two-file write via trusted_runner.bundle_write --------------
    rollback_dir = project_root / ".tmp" / "rollback"
    trusted_runner.bundle_write(
        [(out_index_path, index_bytes), (out_screen_path, screen_bytes)],
        rollback_dir=rollback_dir,
    )

    # Emit transition request -------------------------------------------
    request_path = _emit_skeleton_frozen_request(
        project_root,
        claim_uuid=claim_uuid,
        out_index_path=out_index_path,
        out_screen_path=out_screen_path,
        index_hash=index_hash,
        screen_hash=screen_hash,
        index_bytes=index_bytes,
        screen_bytes=screen_bytes,
        design_doc_hash=design_doc_hash,
        skeleton_version=skeleton_version,
    )

    return {
        "status": "frozen",
        "index_path": out_index_path,
        "screen_path": out_screen_path,
        "request_path": request_path,
        "signature": index_body["signature"],
        "index_hash": index_hash,
        "screen_hash": screen_hash,
        "design_doc_hash": design_doc_hash,
        "challenges_filed": [],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="visual-architect")
    sub = parser.add_subparsers(dest="op", required=True)

    f = sub.add_parser("freeze", help="Freeze draft skeleton into signed artifacts")
    f.add_argument("--draft", required=True)
    f.add_argument("--mockup", required=True)
    f.add_argument("--user-edits", required=True)
    f.add_argument("--out-index", required=True)
    f.add_argument("--out-screen", required=True)
    f.add_argument("--forge-session-key", required=True)
    f.add_argument("--claim-uuid", default=None)
    f.add_argument("--project-root", default=None)
    f.add_argument("--skeleton-version", default=DEFAULT_SKELETON_VERSION)

    ns = parser.parse_args(argv)

    if ns.op != "freeze":
        parser.error(f"unknown op {ns.op!r}")

    project_root = Path(ns.project_root) if ns.project_root else Path.cwd()
    try:
        user_edits = _load_user_edits(Path(ns.user_edits))
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"ENV_ERROR: {e}\n")
        return 3

    try:
        result = freeze_skeleton(
            draft_path=Path(ns.draft),
            mockup_path=Path(ns.mockup),
            user_edits=user_edits,
            out_index_path=Path(ns.out_index),
            out_screen_path=Path(ns.out_screen),
            session_key_path=Path(ns.forge_session_key),
            project_root=project_root,
            claim_uuid=ns.claim_uuid,
            skeleton_version=ns.skeleton_version,
        )
    except FileNotFoundError as e:
        sys.stderr.write(f"ENV_ERROR: {e}\n")
        return 3
    except ValueError as e:
        sys.stderr.write(f"ENV_ERROR: {e}\n")
        return 3

    status = result.get("status")
    if status == "frozen":
        sys.stdout.write(json.dumps({
            "status": "frozen",
            "index_path": str(result["index_path"]),
            "screen_path": str(result["screen_path"]),
            "request_path": str(result["request_path"]),
            "index_hash": result["index_hash"],
            "screen_hash": result["screen_hash"],
            "design_doc_hash": result["design_doc_hash"],
            "signature_digest": result["signature"]["digest"],
        }, sort_keys=True) + "\n")
        return 0
    if status == "rejected_binds_to":
        sys.stdout.write(json.dumps({
            "status": "rejected_binds_to",
            "failures": result["failures"],
            "challenges_filed": result["challenges_filed"],
        }, sort_keys=True) + "\n")
        return 1
    if status == "rejected_tokens":
        sys.stdout.write(json.dumps({
            "status": "rejected_tokens",
            "unresolved_tokens": result["unresolved_tokens"],
        }, sort_keys=True) + "\n")
        return 2
    sys.stderr.write(f"ENV_ERROR: unknown status {status!r}\n")
    return 3


def main() -> None:
    sys.exit(_cli())


if __name__ == "__main__":
    main()
