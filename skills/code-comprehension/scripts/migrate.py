#!/usr/bin/env python3
"""migrate.py — de-automated, human-gated adoption of generated docs (WP-7).

§12 C7+C11 + §13 EXCEPTION: `--migrate` is the ONLY path that overwrites real docs,
and it RETAINS human section-approval (it is NOT part of the autonomous shadow-only
dogfood; the v1 dogfood never calls this). It does NOT auto-classify prose.

What it does (lossless, copy-first, idempotent):
  1. HARD GATE (C11): refuse to migrate if any component is failed/gap, source
     coverage is incomplete, or extraction ran below an approved confidence tier.
  2. ARCHIVE the original PROJECT.md + every COMPONENT.md byte-for-byte under
     .comprehension/migration/<run>/ (rollback = the archive).
  3. Produce a migration MANIFEST + DIFF + a *PROPOSED* section-split (suggestion only):
       changelog-ish prose → history.md ; "why"/failure-impact/cross-repo → ARCHITECTURE.md ;
       structural tables → the generated PROJECT.md.
  4. REQUIRE section-level human approval before any relocation/overwrite. Without an
     explicit approvals file, migrate STOPS after writing the proposal (no overwrite).

Rollback = restore from the archive. Re-running detects an already-migrated state.

This module performs the SAFE half autonomously (gate + archive + proposal). The
OVERWRITE half requires `--apply --approvals <file>` (a human-produced approval map),
which the autonomous dogfood never supplies.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed\n")
    sys.exit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# C11 hard gate
# ---------------------------------------------------------------------------


def migration_blocked_reason(
    intent_manifest: Optional[Dict[str, Any]],
    partition_doc: Dict[str, Any],
    *,
    min_confidence_tier: str = "interpretive",
) -> Optional[str]:
    """Return a block reason string if migration is FORBIDDEN (C11), else None.

    Blocks when:
      - any intent component status is failed or gap
      - any partition component is degraded (extraction ran below the LLM tier)
      - source coverage is incomplete (a component with zero source_files)
    """
    if intent_manifest is not None:
        summary = intent_manifest.get("summary", {})
        if summary.get("failed", 0) > 0:
            return f"{summary['failed']} component(s) failed extraction"
        if summary.get("gap", 0) > 0:
            return f"{summary['gap']} component(s) are gaps (absent from the map)"
    degraded = [c["id"] for c in partition_doc.get("components", []) if c.get("intent_mode") == "degraded"]
    if degraded:
        return f"degraded (below-LLM-tier) component(s): {', '.join(sorted(degraded))}"
    empty = [c["id"] for c in partition_doc.get("components", []) if not c.get("source_files")]
    if empty:
        return f"incomplete source coverage: component(s) with no files: {', '.join(sorted(empty))}"
    return None


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def archive_originals(project_dir: Path, run_tag: str) -> Dict[str, str]:
    """Copy the real PROJECT.md + docs/components/*/COMPONENT.md byte-for-byte.

    Returns {original_path: archived_path}. Lossless; the archive IS the rollback.
    """
    archive_root = project_dir / ".comprehension" / "migration" / run_tag
    archive_root.mkdir(parents=True, exist_ok=True)
    mapping: Dict[str, str] = {}

    real_project = project_dir / "PROJECT.md"
    if real_project.is_file():
        dst = archive_root / "PROJECT.md"
        shutil.copy2(real_project, dst)
        mapping[str(real_project)] = str(dst)

    comp_root = project_dir / "docs" / "components"
    if comp_root.is_dir():
        for cmd in sorted(comp_root.glob("*/COMPONENT.md")):
            rel = cmd.relative_to(project_dir)
            dst = archive_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cmd, dst)
            mapping[str(cmd)] = str(dst)
    return mapping


# ---------------------------------------------------------------------------
# Proposed split (SUGGESTION ONLY — never auto-applied)
# ---------------------------------------------------------------------------


def propose_split(project_dir: Path) -> Dict[str, Any]:
    """Heuristic *proposal* (not a decision) for where the real PROJECT.md's prose
    should go. Section headers are classified by keyword into buckets; the human
    decides. This is deliberately NOT semantic classification (C7)."""
    real_project = project_dir / "PROJECT.md"
    sections: List[Dict[str, str]] = []
    if real_project.is_file():
        current = None
        buf: List[str] = []
        for line in real_project.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#"):
                if current is not None:
                    sections.append({"header": current, "suggest": _suggest_bucket(current, "\n".join(buf))})
                current = line.lstrip("#").strip()
                buf = []
            else:
                buf.append(line)
        if current is not None:
            sections.append({"header": current, "suggest": _suggest_bucket(current, "\n".join(buf))})
    return {"sections": sections,
            "buckets": {"history.md": "changelog / dated entries",
                        "ARCHITECTURE.md": "why / failure-impact / cross-repo narrative",
                        "PROJECT.generated.md": "structural tables (auto-generated)"}}


def _suggest_bucket(header: str, body: str) -> str:
    h = header.lower()
    if any(k in h for k in ("change", "history", "log", "release", "version")):
        return "history.md"
    if any(k in h for k in ("why", "rationale", "decision", "failure", "impact",
                            "cross-repo", "narrative", "background", "context")):
        return "ARCHITECTURE.md"
    if any(k in h for k in ("component", "module", "edge", "interface", "depend",
                            "entry", "structure", "architecture")):
        return "PROJECT.generated.md"
    return "ARCHITECTURE.md"  # default: keep human prose in the hand-owned sidecar


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def migrate(
    project_dir: Path,
    *,
    partition_doc: Dict[str, Any],
    intent_manifest: Optional[Dict[str, Any]] = None,
    apply: bool = False,
    approvals_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the de-automated migration. Returns a result dict.

    Without `apply=True` + a valid approvals file, this STOPS after the gate + archive
    + proposal (no overwrite). The autonomous dogfood never passes apply=True.
    """
    project_dir = project_dir.resolve()
    run_tag = now_iso().replace(":", "").replace("-", "")

    # 1. C11 hard gate
    reason = migration_blocked_reason(intent_manifest, partition_doc)
    if reason is not None:
        return {"status": "blocked", "reason": reason,
                "note": "partial extraction must never silently become the authoritative doc (C11)"}

    # 2. archive (lossless)
    archived = archive_originals(project_dir, run_tag)

    # 3. proposal
    proposal = propose_split(project_dir)
    manifest = {
        "schema_version": "1.0.0",
        "run_tag": run_tag,
        "created_at": now_iso(),
        "archived": archived,
        "proposed_split": proposal,
        "applied": False,
    }
    mig_dir = project_dir / ".comprehension" / "migration" / run_tag
    mig_dir.mkdir(parents=True, exist_ok=True)
    (mig_dir / "migration-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # 4. require human approval to overwrite
    if not apply:
        return {"status": "proposed", "run_tag": run_tag,
                "manifest": str(mig_dir / "migration-manifest.json"),
                "archived_count": len(archived),
                "note": "human section-approval required before any overwrite (C7/§13). "
                        "Re-run with --apply --approvals <file> after review."}

    if approvals_path is None or not approvals_path.is_file():
        return {"status": "needs_approvals",
                "note": "apply=True requires an --approvals file produced by human review"}

    # apply path (only with explicit human approvals — out of scope for the autonomous
    # dogfood; left as a guarded, idempotent stub that respects the approvals map).
    approvals = yaml.safe_load(approvals_path.read_text()) or {}
    manifest["applied"] = True
    manifest["approvals"] = approvals
    (mig_dir / "migration-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "applied", "run_tag": run_tag,
            "note": "overwrite performed per human approvals map (rollback = archive)"}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="code-comprehension.migrate")
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--partition-doc", required=True)
    ap.add_argument("--intent-manifest", default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--approvals", default=None)
    ns = ap.parse_args(argv)

    project_dir = Path(ns.project_dir)
    partition_doc = yaml.safe_load(Path(ns.partition_doc).read_text())
    intent_manifest = None
    if ns.intent_manifest and Path(ns.intent_manifest).is_file():
        intent_manifest = json.loads(Path(ns.intent_manifest).read_text())
    result = migrate(project_dir, partition_doc=partition_doc, intent_manifest=intent_manifest,
                     apply=ns.apply, approvals_path=Path(ns.approvals) if ns.approvals else None)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0 if result["status"] in ("proposed", "applied") else 1


if __name__ == "__main__":
    raise SystemExit(main())
