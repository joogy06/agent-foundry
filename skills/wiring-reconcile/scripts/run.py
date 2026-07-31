#!/usr/bin/env python3
"""run.py — wiring-reconcile CLI entry.

Per design 2026-04-14 §5.2 lifecycle. Executes:

  1. Validate claim (bob-issued).
  2. Start heartbeat (60s poll of `.ledger/claims/<uuid>.claim.yaml`).
  3. Read `.wiring/runs/<run_id>/manifest.json`; verify sources terminal.
  4. Read `static.jsonl` + all `asserted/*.jsonl` through `assertion_inbox`.
  5. Validate each static edge against `wiring-source-edge.v1`; skip+log bad.
  6. `reconciler.reconcile()` to produce snapshot dict.
  7. Schema-validate against `wiring-snapshot.v1`.
  8. Atomic write `.wiring/runs/<run_id>/snapshot.json`.
  9. Emit transition request to `.ledger/requests/<claim_uuid>.request.yaml`.
 10. Exit 0.

Failure behaviour: malformed-but-salvageable -> continue with reduced set;
unrecoverable (disk full, claim revoked, manifest missing, sources non-terminal)
-> exit 1 with log.

This script contains NO LLM calls. It is pure deterministic Python.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from jsonschema import Draft202012Validator
except ImportError as _e:  # pragma: no cover
    raise ImportError("wiring-reconcile requires jsonschema>=4.18") from _e

try:
    import yaml
except ImportError as _e:  # pragma: no cover
    raise ImportError("wiring-reconcile requires pyyaml") from _e

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from assertion_inbox import (  # noqa: E402
    load_component_ids,
    read_assertions_with_stats,
)
from reconciler import reconcile  # noqa: E402
from snapshot_writer import write_snapshot_atomic  # noqa: E402
from edge_identity import edge_id_for  # noqa: E402

SKILL_ROOT = SCRIPT_DIR.parent
SNAPSHOT_SCHEMA = json.loads(
    (SKILL_ROOT / "schemas" / "wiring-snapshot.v1.json").read_text(encoding="utf-8")
)
SOURCE_EDGE_SCHEMA = json.loads(
    (Path.home() / ".claude" / "skills" / "wiring-extract-static" / "schemas"
     / "wiring-source-edge.v1.json").read_text(encoding="utf-8")
)

SNAPSHOT_VALIDATOR = Draft202012Validator(SNAPSHOT_SCHEMA)
EDGE_VALIDATOR = Draft202012Validator(SOURCE_EDGE_SCHEMA)


# ---------------------------------------------------------------------------
# Logging + time
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Heartbeat thread
# ---------------------------------------------------------------------------


class HeartbeatThread(threading.Thread):
    """Background heartbeat. Stops skill on non-ok claim status."""

    def __init__(
        self,
        claim_uuid: str,
        project_root: Path,
        on_stop,
        interval_s: float = 60.0,
    ) -> None:
        super().__init__(daemon=True)
        self.claim_uuid = claim_uuid
        self.project_root = project_root
        self.on_stop = on_stop
        self.interval_s = interval_s
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        # Lazy import to avoid forcing claims.py at import time (unit tests
        # can skip heartbeat entirely).
        claims_path = (
            Path.home() / ".claude" / "skills" / "_meta"
        )
        sys.path.insert(0, str(claims_path))
        try:
            import claims as _claims  # type: ignore
        except ImportError:
            return
        while not self._stop.wait(self.interval_s):
            try:
                state = _claims.heartbeat_claim(self.claim_uuid, self.project_root)
            except Exception:
                state = "expired"
            if state != "ok":
                self.on_stop(state)
                return


# ---------------------------------------------------------------------------
# Helpers to load static.jsonl + manifest.json
# ---------------------------------------------------------------------------


def _read_manifest(run_dir: Path) -> Dict[str, Any]:
    p = run_dir / "manifest.json"
    if not p.is_file():
        raise FileNotFoundError(f"manifest.json missing at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _verify_sources_terminal(manifest: Dict[str, Any]) -> None:
    for s in manifest.get("sources", []) or []:
        st = s.get("status")
        if st in (None, "in_progress"):
            raise RuntimeError(
                f"source {s.get('source_id')!r} not terminal (status={st!r})"
            )


def _read_static_jsonl(run_dir: Path, logger: logging.Logger) -> List[Dict[str, Any]]:
    """Validate each line against wiring-source-edge.v1; skip + log bad lines."""
    p = run_dir / "static.jsonl"
    out: List[Dict[str, Any]] = []
    if not p.is_file():
        return out
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        try:
            edge = json.loads(s)
        except json.JSONDecodeError as e:
            logger.warning("static.jsonl:%d malformed JSON: %s", lineno, e)
            continue
        if not isinstance(edge, dict):
            logger.warning("static.jsonl:%d not a JSON object", lineno)
            continue
        errs = list(EDGE_VALIDATOR.iter_errors(edge))
        if errs:
            logger.warning(
                "static.jsonl:%d schema invalid: %s",
                lineno, "; ".join(f"{list(e.path)}: {e.message}" for e in errs[:3]),
            )
            continue
        out.append(edge)
    return out


def _read_manual_jsonl(run_dir: Path, logger: logging.Logger) -> List[Dict[str, Any]]:
    p = run_dir / "manual.jsonl"
    out: List[Dict[str, Any]] = []
    if not p.is_file():
        return out
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        try:
            edge = json.loads(s)
        except json.JSONDecodeError:
            logger.warning("manual.jsonl:%d malformed JSON", lineno)
            continue
        if not isinstance(edge, dict):
            continue
        errs = list(EDGE_VALIDATOR.iter_errors(edge))
        if errs:
            logger.warning("manual.jsonl:%d schema invalid", lineno)
            continue
        edge["evidence_source"] = "manual"
        out.append(edge)
    return out


def _load_previous_snapshot(project_dir: Path) -> Optional[Dict[str, Any]]:
    latest = project_dir / ".wiring" / "latest.json"
    if not latest.is_file():
        return None
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_suppressed(config_path: Optional[Path]) -> List[str]:
    if not config_path or not Path(config_path).is_file():
        return []
    try:
        doc = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return list((doc.get("reconcile") or {}).get("suppress_edge_ids") or [])


def _contract_map_binding(project_dir: Path) -> Dict[str, Any]:
    cm = project_dir / "progress" / "contract-map.yaml"
    if not cm.is_file():
        return {}
    import hashlib
    h = hashlib.sha256(cm.read_bytes()).hexdigest()
    try:
        doc = yaml.safe_load(cm.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {"contract_map_hash": h}
    return {
        "contract_map_hash": h,
        "contract_map_revision": int(doc.get("revision", 0) or 0),
    }


# ---------------------------------------------------------------------------
# Transition request emission
# ---------------------------------------------------------------------------


def _emit_transition_request(
    project_root: Path,
    claim_uuid: str,
    run_id: str,
    snapshot: Dict[str, Any],
    assertion_stats: Dict[str, Any],
    component: str = "wiring-reconcile",
    target_stage: str = "INTEGRATED",
) -> Path:
    req_dir = project_root / ".ledger" / "requests"
    req_dir.mkdir(parents=True, exist_ok=True)
    req_path = req_dir / f"{claim_uuid}.request.yaml"
    body = {
        "schema_version": 1,
        "request_id": f"{claim_uuid}-{snapshot['snapshot_id']}",
        "claim_uuid": claim_uuid,
        "component": component,
        "target_stage": target_stage,
        "emitted_at": now_iso(),
        "emitted_by": "wiring-reconcile@1.0.0",
        "run_id": run_id,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_statistics": snapshot.get("statistics", {}),
        "assertion_inbox_stats": assertion_stats,
        "drift_canary": "ALDEBARAN-7",
    }
    req_path.write_text(yaml.safe_dump(body, sort_keys=True), encoding="utf-8")
    return req_path


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def _run(
    project_dir: Path,
    run_id: str,
    claim_uuid: str,
    config: Optional[Path],
    skip_heartbeat: bool,
    skip_claim_check: bool,
    logger: logging.Logger,
) -> int:
    project_dir = project_dir.resolve()
    run_dir = project_dir / ".wiring" / "runs" / run_id
    if not run_dir.is_dir():
        logger.error("run dir missing: %s", run_dir)
        return 1

    # Verify claim (optional for unit-test harness)
    if not skip_claim_check:
        meta_path = Path.home() / ".claude" / "skills" / "_meta"
        sys.path.insert(0, str(meta_path))
        import claims as _claims  # type: ignore
        claim_path = project_dir / ".ledger" / "claims" / f"{claim_uuid}.claim.yaml"
        if not claim_path.is_file():
            logger.error("claim file missing: %s", claim_path)
            return 1
        try:
            claim = yaml.safe_load(claim_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            logger.error("claim file corrupt")
            return 1
        state = _claims.classify_claim(claim, project_dir / "progress" / "integration-ledger.md")
        if state != "ok":
            logger.error("claim status %s -> stop", state)
            return 1

    # Heartbeat
    stop_flag = {"triggered": False, "reason": None}
    heartbeat: Optional[HeartbeatThread] = None
    if not skip_heartbeat:
        def _stop(reason: str) -> None:
            stop_flag["triggered"] = True
            stop_flag["reason"] = reason
        heartbeat = HeartbeatThread(claim_uuid, project_dir, _stop)
        heartbeat.start()

    try:
        manifest = _read_manifest(run_dir)
        _verify_sources_terminal(manifest)

        static_edges = _read_static_jsonl(run_dir, logger)
        logger.info("static edges loaded: %d", len(static_edges))

        component_ids = load_component_ids(
            project_dir / "progress" / "contract-map.yaml"
        )
        asserted_edges, assertion_stats = read_assertions_with_stats(
            run_dir, component_ids, logger=logger
        )
        logger.info("asserted edges loaded: %d", len(asserted_edges))

        manual_edges = _read_manual_jsonl(run_dir, logger)

        suppressed = _load_suppressed(config)
        prev_snapshot = _load_previous_snapshot(project_dir)

        binding = _contract_map_binding(project_dir)

        workspace_tree_hash = manifest.get("workspace_tree_hash", "0" * 40)

        snapshot = reconcile(
            static_edges=static_edges,
            asserted_edges=asserted_edges,
            manual_edges=manual_edges,
            manifest=manifest,
            contract_map_components=component_ids,
            run_id=run_id,
            workspace_tree_hash=workspace_tree_hash,
            generated_at=now_iso(),
            snapshot_generation=1,  # provisional; bob re-writes on promote
            previous_snapshot=prev_snapshot,
            suppressed_edge_ids=suppressed,
            **binding,
        )

        # Schema-validate
        errors = sorted(SNAPSHOT_VALIDATOR.iter_errors(snapshot), key=lambda e: list(e.path))
        if errors:
            for err in errors[:5]:
                logger.error("snapshot schema invalid at %s: %s", list(err.path), err.message)
            return 1

        # Atomic write
        snapshot_path = run_dir / "snapshot.json"
        write_snapshot_atomic(snapshot_path, snapshot)
        logger.info("snapshot written: %s (id=%s, %d edges)",
                    snapshot_path, snapshot["snapshot_id"], len(snapshot["edges"]))

        # Transition request
        req_path = _emit_transition_request(
            project_root=project_dir,
            claim_uuid=claim_uuid,
            run_id=run_id,
            snapshot=snapshot,
            assertion_stats=assertion_stats.as_dict(),
        )
        logger.info("transition request emitted: %s", req_path)

        if stop_flag["triggered"]:
            logger.error("heartbeat stop: %s", stop_flag["reason"])
            return 1
        return 0
    finally:
        if heartbeat:
            heartbeat.stop()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="wiring-reconcile run")
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--claim-uuid", required=True)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--skip-heartbeat", action="store_true", help="for tests")
    parser.add_argument("--skip-claim-check", action="store_true", help="for tests")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("wiring-reconcile")
    return _run(
        project_dir=args.project_dir,
        run_id=args.run_id,
        claim_uuid=args.claim_uuid,
        config=args.config,
        skip_heartbeat=args.skip_heartbeat,
        skip_claim_check=args.skip_claim_check,
        logger=logger,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
