"""run.py — ever-test-gen CLI entry point (S032 WP-7).

Generates characterization tests from a frozen intent-map + optional
api_delta + plan.yaml. Writes test files to <project_root>/tests/.

Bob's trusted_runner EXECUTES these tests (CB3 provenance) — this skill
writes files only.

Pipeline:
  1. Read intent-map.yaml (per-component test_seeds[])
  2. Read api_delta.json (mode-b only) — for migration tests
  3. Read drift-report.yaml CVE findings (mode-c only)
  4. For each component in scope:
     a. Generate regression-replay tests from test_seeds[]
     b. Mode-b: generate migration-confirmation tests from api_delta
     c. Mode-c: generate CVE proof-of-fix tests from findings
  5. Collision-check filenames against existing tests/
  6. Write all generated files atomically
  7. Emit one transition request for bob (TESTED transition)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed\n")
    sys.exit(3)

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import compose_iflow  # noqa: E402
import cve_proof  # noqa: E402
import migration_confirm  # noqa: E402
import regression_replay  # noqa: E402
import test_header  # noqa: E402


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class HeartbeatThread:
    def __init__(self, claim_uuid: str, project_root: Path,
                 interval_seconds: int = 60) -> None:
        self.claim_uuid = claim_uuid
        self.project_root = project_root
        self.interval = interval_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            pass

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop,
                                        name="ever-test-gen-heartbeat",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _components_from_intent_map(intent_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    comps = intent_map.get("components", [])
    if isinstance(comps, list):
        return [c for c in comps if isinstance(c, dict)]
    return []


def generate_for_component(
    component: Dict[str, Any],
    *,
    mode: str,
    language: str,
    api_delta: Optional[Dict[str, Any]],
    drift_findings: List[Dict[str, Any]],
    wiring_snapshot_hash: str,
) -> List[Dict[str, Any]]:
    """Generate all test files for one component. Returns list of {filename, content, ...}."""
    cid = component.get("component_id") or component.get("name") or "unknown"
    results: List[Dict[str, Any]] = []

    # Regression replay
    if language == "python":
        results.extend(regression_replay.emit_pytest(
            cid, component, mode=mode, wiring_snapshot_hash=wiring_snapshot_hash,
        ))
    else:
        results.extend(regression_replay.emit_jest(
            cid, component, mode=mode, wiring_snapshot_hash=wiring_snapshot_hash,
        ))

    # Migration confirmation (mode-b)
    if mode == "version-upgrade" and api_delta is not None:
        if language == "python":
            results.extend(migration_confirm.emit_pytest(
                cid, api_delta, mode=mode, wiring_snapshot_hash=wiring_snapshot_hash,
            ))
        else:
            results.extend(migration_confirm.emit_jest(
                cid, api_delta, mode=mode, wiring_snapshot_hash=wiring_snapshot_hash,
            ))

    # CVE proof of fix (mode-c)
    if mode == "cve-fix" and drift_findings:
        if language == "python":
            results.extend(cve_proof.emit_pytest(
                cid, drift_findings, mode=mode, wiring_snapshot_hash=wiring_snapshot_hash,
            ))
        else:
            results.extend(cve_proof.emit_jest(
                cid, drift_findings, mode=mode, wiring_snapshot_hash=wiring_snapshot_hash,
            ))

    return results


def check_collisions(
    project_root: Path,
    tests_dir: Path,
    proposed: List[Dict[str, Any]],
) -> List[str]:
    """Return list of proposed filenames that already exist (collision-protect)."""
    collisions: List[str] = []
    for entry in proposed:
        fname = entry["filename"]
        target = tests_dir / fname
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if not test_header.header_present(existing):
                # Existing user test — collision
                collisions.append(fname)
            # If existing is evo-generated, overwrite is allowed (regen)
    return collisions


def write_tests(
    tests_dir: Path,
    proposed: List[Dict[str, Any]],
) -> List[Path]:
    """Write all proposed test files atomically. Returns list of paths written."""
    tests_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for entry in proposed:
        path = tests_dir / entry["filename"]
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{int(time.time() * 1e6)}")
        tmp.write_text(entry["content"], encoding="utf-8")
        os.replace(str(tmp), str(path))
        written.append(path)
    return written


def emit_transition_request(
    project_root: Path,
    *,
    claim_uuid: str,
    run_id: str,
    written_paths: List[Path],
    target_stage: str = "TESTED",
) -> Path:
    rdir = project_root / ".ledger" / "requests"
    rdir.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    request = {
        "schema_version": "1.0.0",
        "request_id": request_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "produced_by": "ever-test-gen",
        "claim_uuid": claim_uuid,
        "target_stage": target_stage,
        "run_id": run_id,
        "tests_added": [str(p.relative_to(project_root)) for p in written_paths],
    }
    rpath = rdir / f"{request_id}.request.yaml"
    rpath.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")
    return rpath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ever-test-gen",
                                     description="EVO characterization-test generator")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--claim-uuid", required=True)
    parser.add_argument("--plan-path", required=True, type=Path)
    parser.add_argument("--intent-map-path", required=True, type=Path)
    parser.add_argument("--mode", required=True,
                        choices=["version-upgrade", "cve-fix"])
    parser.add_argument("--api-delta-path", type=Path, default=None)
    parser.add_argument("--drift-report-path", type=Path, default=None)
    parser.add_argument("--language-target", default="python",
                        choices=["python", "javascript", "typescript"])
    parser.add_argument("--wiring-snapshot-hash", default="unknown")
    parser.add_argument("--no-heartbeat", action="store_true")
    parser.add_argument("--no-transition-request", action="store_true")
    args = parser.parse_args(argv)

    project_root: Path = args.project_root.resolve()
    if not project_root.is_dir():
        sys.stderr.write(f"ENV_ERROR: project_root not a directory: {project_root}\n")
        return 3
    if not args.intent_map_path.is_file():
        sys.stderr.write(f"ENV_ERROR: intent-map not found: {args.intent_map_path}\n")
        return 3
    if not args.plan_path.is_file():
        sys.stderr.write(f"ENV_ERROR: plan not found: {args.plan_path}\n")
        return 3

    intent_map = _load_yaml(args.intent_map_path)
    api_delta = _load_json(args.api_delta_path) if args.api_delta_path else None
    drift_report = _load_yaml(args.drift_report_path) if args.drift_report_path else {}
    drift_findings = drift_report.get("findings", []) if isinstance(drift_report, dict) else []

    components = _components_from_intent_map(intent_map)
    if not components:
        sys.stderr.write("no components in intent-map; nothing to generate\n")
        return 0

    # Heartbeat
    hb: Optional[HeartbeatThread] = None
    if not args.no_heartbeat:
        hb = HeartbeatThread(args.claim_uuid, project_root)
        hb.start()

    try:
        proposed: List[Dict[str, Any]] = []
        for c in components:
            proposed.extend(generate_for_component(
                c,
                mode=args.mode,
                language=args.language_target,
                api_delta=api_delta,
                drift_findings=drift_findings,
                wiring_snapshot_hash=args.wiring_snapshot_hash,
            ))
        # Composition stub (v1)
        for c in components:
            cid = c.get("component_id") or c.get("name") or "unknown"
            proposed.extend(compose_iflow.compose(
                cid, args.plan_path, args.intent_map_path, mode=args.mode,
            ))

        tests_dir = project_root / "tests"
        collisions = check_collisions(project_root, tests_dir, proposed)
        if collisions:
            sys.stderr.write(
                "REFUSE: collision with existing user tests:\n"
                + "\n".join(f"  - {c}" for c in collisions) + "\n"
            )
            return 2

        # Filter out tests we are going to overwrite of our own — informational
        written = write_tests(tests_dir, proposed)

        if not args.no_transition_request:
            emit_transition_request(
                project_root,
                claim_uuid=args.claim_uuid,
                run_id=args.run_id,
                written_paths=written,
            )

        summary = {
            "tests_written": len(written),
            "components_processed": len(components),
            "mode": args.mode,
            "language": args.language_target,
        }
        sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
        return 0
    finally:
        if hb is not None:
            hb.stop()


if __name__ == "__main__":
    sys.exit(main())
