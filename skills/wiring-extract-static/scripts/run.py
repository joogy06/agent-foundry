#!/usr/bin/env python3
"""run.py — wiring-extract-static CLI entry point.

Per design 2026-04-14 §5.1. Produces per-run isolated artifacts under
    $PROJECT_DIR/.wiring/runs/<run_id>/
        manifest.json      (source-manifest.v1, status advances in_progress → terminal)
        static.jsonl       (edges from ALL plug-in sources, one per line)
        source-statuses.yaml  (optional convenience dump for wiring-reconcile)

Never creates .wiring/ root — that's bob's job (single-creator invariant).

Invocation:
    python3 run.py --project-dir DIR --run-id UUID --claim-uuid UUID [--config PATH]

Exit codes:
    0   full or partial success (gaps recorded in manifest)
    1   unrecoverable: claim revoked, tree-hash unobtainable, disk full, bad args
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid as uuid_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# Local imports (co-located in scripts/)
_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "wiring-reconcile" / "scripts"))

try:
    import jsonschema
except ImportError:
    sys.stderr.write("FATAL: jsonschema not installed.\n")
    sys.exit(1)

from edge_identity import compute_edge_id  # noqa: E402
from plugin_loader import (  # noqa: E402
    discover_plugins,
    fallback_plugin,
    plugins_for_language,
    augment_plugins_for_language,
    LoadedPlugin,
)
from component_resolver import make_resolver, make_resolver_for_path, ComponentResolver  # noqa: E402
from heartbeat import HeartbeatThread  # noqa: E402


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = SKILL_ROOT / "schemas"
EDGE_SCHEMA = json.loads((SCHEMAS_DIR / "wiring-source-edge.v1.json").read_text())
MANIFEST_SCHEMA = json.loads((SCHEMAS_DIR / "wiring-source-manifest.v1.json").read_text())

LEDGER_REQUESTS = ".ledger/requests"

FORMAT_CHECKER = jsonschema.FormatChecker()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_tree_hash(project_dir: Path) -> str:
    """git write-tree at project_dir. Requires it to be a git repo."""
    cp = subprocess.run(
        ["git", "-C", str(project_dir), "write-tree"],
        capture_output=True, text=True, timeout=30,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"git write-tree failed: {cp.stderr.strip()}")
    out = cp.stdout.strip()
    if len(out) != 40 or not all(c in "0123456789abcdef" for c in out):
        raise RuntimeError(f"unexpected git write-tree output: {out!r}")
    return out


# --- context detection (graceful if sub-skill missing) ---------------------


def detect_languages_and_frameworks(project_dir: Path) -> tuple[List[str], List[str]]:
    """Call project-documentation context-detection if available; otherwise sniff.

    Returns (languages, frameworks). On any failure falls back to filesystem sniffing.
    """
    try:
        # Try the documented import path first
        sys.path.insert(0, str(Path.home() / ".claude" / "skills"))
        from project_documentation import context_detection  # type: ignore
        langs = list(getattr(context_detection, "detect_languages", lambda _p: [])(project_dir))
        fws = list(getattr(context_detection, "detect_frameworks", lambda _p: [])(project_dir))
        if langs or fws:
            return langs, fws
    except Exception:
        pass
    # Filesystem sniff fallback
    langs: List[str] = []
    fws: List[str] = []
    if (project_dir / "pyproject.toml").exists() or list(project_dir.rglob("*.py")):
        langs.append("python")
    if (project_dir / "package.json").exists() or list(project_dir.rglob("*.ts")) or list(project_dir.rglob("*.tsx")):
        langs.append("typescript")
    if list(project_dir.rglob("*.js")) or list(project_dir.rglob("*.jsx")):
        if "typescript" not in langs:
            langs.append("javascript")
    # Cheap framework hints
    try:
        reqs = (project_dir / "pyproject.toml").read_text(errors="replace").lower() if (project_dir / "pyproject.toml").exists() else ""
        if "fastapi" in reqs:
            fws.append("fastapi")
    except OSError:
        pass
    try:
        pkg = (project_dir / "package.json").read_text(errors="replace").lower() if (project_dir / "package.json").exists() else ""
        if '"express"' in pkg:
            fws.append("express")
    except OSError:
        pass
    return langs, fws


# --- source file discovery -------------------------------------------------


_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build", ".wiring", ".ledger", ".forge"}


def walk_source_files(project_dir: Path, exts: set[str]) -> List[Path]:
    out: List[Path] = []
    for root, dirs, files in os.walk(project_dir):
        # Prune noisy dirs
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in exts:
                out.append(p)
    return sorted(out)


_LANG_EXTS = {
    "python": {".py"},
    "typescript": {".ts", ".tsx"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs"},
    "generic": set(),
}


def files_for_languages(project_dir: Path, languages: Iterable[str]) -> Dict[str, List[Path]]:
    """Return {language: [files]} for each requested language."""
    out: Dict[str, List[Path]] = {}
    for lang in languages:
        exts = _LANG_EXTS.get(lang, set())
        if not exts:
            continue
        out[lang] = walk_source_files(project_dir, exts)
    return out


# --- extraction orchestration ---------------------------------------------


class ExtractionContext:
    """Thread-safe accumulator for status and edges from plug-in runs."""

    def __init__(self, run_dir: Path, workspace_tree_hash: str) -> None:
        self.run_dir = run_dir
        self.workspace_tree_hash = workspace_tree_hash
        self.sources: List[Dict[str, Any]] = []
        self.edge_lines: List[str] = []
        self.dropped_edges: int = 0


def validate_and_serialize(edge: dict) -> Optional[str]:
    """Schema-validate, fill in emitted_at if missing, return canonical JSON string or None."""
    edge.setdefault("emitted_at", now_iso())
    try:
        jsonschema.validate(edge, EDGE_SCHEMA, format_checker=FORMAT_CHECKER)
    except jsonschema.ValidationError:
        return None
    # deterministic ordering: sort keys
    return json.dumps(edge, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def run_plugin(
    plugin: LoadedPlugin,
    language: str,
    files: List[Path],
    project_dir: Path,
    resolver: ComponentResolver,
    workspace_tree_hash: str,
    symbols: Dict[str, Any],
    config: Dict[str, Any],
    ctx: ExtractionContext,
) -> None:
    """Run one plug-in against the files list. Records a manifest source entry."""
    source_id = f"wiring-extract-static.{plugin.id}"
    started = time.perf_counter()
    src_entry = {
        "source_id": source_id,
        "evidence_source": "static_extract",
        "status": "in_progress",
        "output_path": "static.jsonl",
        "edge_count": 0,
        "plugin_id": plugin.id,
        "plugin_version": plugin.version,
        "detected_framework": plugin.target_framework,
        "duration_seconds": 0.0,
        "gaps": [],
    }
    ctx.sources.append(src_entry)
    try:
        edges_iter = plugin.extract_edges(
            project_dir=project_dir,
            symbols=symbols,
            source_files=files,
            workspace_tree_hash=workspace_tree_hash,
            extractor_version=plugin.version,
            config=config,
            resolve_component=resolver.resolve,
        )
        count = 0
        malformed = 0
        for edge in edges_iter:
            line = validate_and_serialize(edge)
            if line is None:
                malformed += 1
                ctx.dropped_edges += 1
                continue
            ctx.edge_lines.append(line)
            count += 1
        src_entry["edge_count"] = count
        src_entry["status"] = "succeeded" if malformed == 0 else "partial"
        if malformed:
            src_entry["gaps"].append(f"malformed_edges={malformed}")
    except Exception as e:  # noqa: BLE001
        src_entry["status"] = "failed"
        src_entry["error"] = f"{type(e).__name__}: {e}"
    finally:
        src_entry["duration_seconds"] = round(time.perf_counter() - started, 3)


def atomic_write_jsonl(path: Path, lines: List[str]) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(line)
            f.write("\n")
    os.replace(str(tmp), str(path))


def atomic_write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(str(tmp), str(path))


def emit_transition_request(
    project_dir: Path,
    claim_uuid: str,
    run_id: str,
    manifest_path: Path,
    static_jsonl_path: Path,
    target_stage: str,
) -> Path:
    """Write a transition request for bob to consume.

    Bob owns ledger state; this file is read-only to bob's request handler.
    """
    req_dir = project_dir / LEDGER_REQUESTS
    req_dir.mkdir(parents=True, exist_ok=True)
    req_id = str(uuid_mod.uuid4())
    payload = {
        "request_id": req_id,
        "claim_uuid": claim_uuid,
        "skill": "wiring-extract-static",
        "wp": "WP-2",
        "run_id": run_id,
        "target_stage": target_stage,
        "manifest_path": str(manifest_path),
        "manifest_hash": f"sha256:{sha256_file(manifest_path)}",
        "static_jsonl_path": str(static_jsonl_path),
        "static_jsonl_hash": f"sha256:{sha256_file(static_jsonl_path)}" if static_jsonl_path.exists() else None,
        "emitted_at": now_iso(),
    }
    # YAML format per bob's claims.apply_request_idempotent expectations (bob parses yaml)
    try:
        import yaml
        text = yaml.safe_dump(payload, sort_keys=True)
    except ImportError:
        text = json.dumps(payload, indent=2, sort_keys=True)
    req_path = req_dir / f"{req_id}.request.yaml"
    tmp = req_path.with_suffix(req_path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text)
    os.replace(str(tmp), str(req_path))
    return req_path


# --- main -----------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="wiring-extract-static.run")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--claim-uuid", required=False, default=None,
                        help="bob-issued claim UUID; REQUIRED unless --standalone")
    parser.add_argument("--config", default=None)
    parser.add_argument("--target-stage", default="SCAFFOLDED", help="ledger stage to advance to on success")
    parser.add_argument("--no-heartbeat", action="store_true", help="disable heartbeat (for local smoke runs without bob)")
    # --- code-comprehension standalone mode (CB4: claims structurally impossible) ---
    # In --standalone: no claim required, HeartbeatThread NEVER constructed,
    # transition-request emission UNREACHABLE, output root configurable, and the
    # orchestrator (not bob) is the single creator of the wiring root. Additive:
    # the normal bob-driven path is byte-identical when --standalone is off.
    parser.add_argument("--standalone", action="store_true",
                        help="claimless read-only mode for code-comprehension")
    parser.add_argument("--contract-map-path", default=None,
                        help="contract-map path (default progress/contract-map.yaml); "
                             "the literal 'none' means NO resolution (clean unmapped_path:* "
                             "first pass; fallback to progress/ PROHIBITED).")
    parser.add_argument("--wiring-root", default=None,
                        help="output root for .wiring/ (standalone runs put it under "
                             ".comprehension/). Default: <project-dir>/.wiring")
    parser.add_argument("--no-transition-request", action="store_true",
                        help="skip writing the transition request (testing only)")
    ns = parser.parse_args(argv)

    project_dir = Path(ns.project_dir).resolve()
    if not project_dir.is_dir():
        sys.stderr.write(f"project-dir not found: {project_dir}\n")
        return 1

    # Claim is REQUIRED unless --standalone (CB4 structural guard).
    if not ns.standalone and not ns.claim_uuid:
        sys.stderr.write("--claim-uuid is required unless --standalone\n")
        return 1

    # Validate run_id looks like a uuid
    try:
        uuid_mod.UUID(ns.run_id)
    except ValueError:
        sys.stderr.write(f"--run-id not a UUID: {ns.run_id}\n")
        return 1

    # .wiring/ root location. Normal mode: <project>/.wiring (bob is the single
    # creator — we refuse if absent). Standalone mode: the orchestrator owns the
    # root (it plays the single-creator role for the non-bob run), so we accept a
    # configurable --wiring-root and CREATE it if absent (the orchestrator passes a
    # path under .comprehension/). This preserves the single-creator invariant:
    # exactly one creator (the orchestrator) per standalone run.
    if ns.wiring_root:
        wiring_root = Path(ns.wiring_root).resolve()
    else:
        wiring_root = project_dir / ".wiring"
    if ns.standalone:
        wiring_root.mkdir(parents=True, exist_ok=True)
    elif not wiring_root.is_dir():
        sys.stderr.write(f"{wiring_root} missing — bob must create .wiring/ before extractor runs\n")
        return 1

    run_dir = wiring_root / "runs" / ns.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    static_jsonl_path = run_dir / "static.jsonl"

    # Tree hash (fail-fast if git fails)
    try:
        workspace_tree_hash = compute_tree_hash(project_dir)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"tree hash failure: {e}\n")
        return 1

    # Heartbeat — in --standalone the HeartbeatThread is NEVER constructed
    # (structural CB4 guard: no object exists that could touch a claim file). The
    # pipeline path is byte-identical when --standalone is off.
    stop_event = threading.Event()
    hb: Optional[HeartbeatThread] = None
    if not ns.standalone and not ns.no_heartbeat:
        hb = HeartbeatThread(ns.claim_uuid, project_dir, stop_event)
        hb.start()
        # Abort if first beat failed
        if stop_event.is_set():
            sys.stderr.write(f"heartbeat failed at startup: {hb.last_state}\n")
            return 1

    try:
        # Initial manifest (in_progress)
        langs, fws = detect_languages_and_frameworks(project_dir)
        # Write initial manifest with placeholder in_progress sources (one per detected language)
        initial_manifest = {
            "schema_version": "1.0.0",
            "run_id": ns.run_id,
            "workspace_tree_hash": workspace_tree_hash,
            "project_dir": str(project_dir),
            "started_at": now_iso(),
            "sources": [
                {
                    "source_id": f"wiring-extract-static.scan-{lang}",
                    "evidence_source": "static_extract",
                    "status": "in_progress",
                    "output_path": "static.jsonl",
                    "edge_count": 0,
                }
                for lang in langs
            ] or [
                {
                    "source_id": "wiring-extract-static.scan",
                    "evidence_source": "static_extract",
                    "status": "in_progress",
                    "output_path": "static.jsonl",
                    "edge_count": 0,
                }
            ],
            "languages_detected": langs,
            "frameworks_detected": fws,
        }
        # contract_map_hash (if the file exists — strict pattern enforced only if set).
        # Respect --contract-map-path: 'none' => stamp nothing (do NOT touch the stale
        # progress/ map); explicit PATH => hash that; default => progress/contract-map.yaml.
        if ns.contract_map_path == "none":
            cm_path = None
        elif ns.contract_map_path:
            cm_path = Path(ns.contract_map_path)
        else:
            cm_path = project_dir / "progress" / "contract-map.yaml"
        if cm_path is not None and cm_path.is_file():
            initial_manifest["contract_map_hash"] = sha256_file(cm_path)
        atomic_write_json(manifest_path, initial_manifest)

        # Early claim check
        if stop_event.is_set():
            sys.stderr.write("claim no longer ok; aborting\n")
            return 1

        # Load plug-ins and resolve components. --contract-map-path selects the
        # resolver: default (progress/contract-map.yaml), 'none' (NullResolver — clean
        # unmapped first pass, no progress/ fallback), or an explicit synthetic map.
        plugins = discover_plugins()
        resolver = make_resolver_for_path(project_dir, ns.contract_map_path)
        config_dict: Dict[str, Any] = {}
        if ns.config:
            try:
                import yaml
                config_dict = yaml.safe_load(Path(ns.config).read_text()) or {}
            except Exception:
                config_dict = {}

        ctx = ExtractionContext(run_dir=run_dir, workspace_tree_hash=workspace_tree_hash)
        per_language_files = files_for_languages(project_dir, langs)

        # For each language, invoke plug-ins. Framework plug-ins run on their language
        # files; generic-treesitter runs as a final pass on any language files that had
        # no framework plug-in cover them. Augment plug-ins ALWAYS run on their
        # language files regardless of detected frameworks (WP-WIRING-02-BOOTSTRAP).
        # The "only fallback when no framework matches" rule is per-language, not per-file
        # (design §4 open-Q resolution). Augment plug-ins do not gate the fallback.
        for lang, files in per_language_files.items():
            lang_plugins = plugins_for_language(plugins, lang)
            # Split by activation mode. `plugins_for_language` returns non-fallback
            # first, then fallback; we carve out augment to handle separately and
            # limit `framework_plugins` to the true framework-gated set.
            framework_plugins = [
                p for p in lang_plugins
                if not p.is_fallback and not p.is_augment
            ]
            augment_plugins = augment_plugins_for_language(plugins, lang)

            # Only run the framework plug-in if its detected framework is in fws set.
            matched_any_framework = False
            for p in framework_plugins:
                if p.target_framework in fws:
                    matched_any_framework = True
                    run_plugin(p, lang, files, project_dir, resolver,
                               workspace_tree_hash, symbols={"by_file": {}, "by_name": {}},
                               config=config_dict, ctx=ctx)
            # Augment plug-ins fire unconditionally (framework-agnostic).
            for p in augment_plugins:
                run_plugin(p, lang, files, project_dir, resolver,
                           workspace_tree_hash, symbols={"by_file": {}, "by_name": {}},
                           config=config_dict, ctx=ctx)
            # Fallback only when no framework plug-in matched. Augment plug-ins
            # do NOT satisfy this gate: if the only non-fallback coverage for a
            # language is an augment plug-in (e.g. redis-streams on a non-fastapi
            # Python project), the generic-treesitter fallback still runs to
            # capture the broader call graph.
            if not matched_any_framework:
                fb = fallback_plugin(plugins)
                if fb is not None and (lang in fb.languages or "generic" in fb.languages):
                    run_plugin(fb, lang, files, project_dir, resolver,
                               workspace_tree_hash, symbols={"by_file": {}, "by_name": {}},
                               config=config_dict, ctx=ctx)

            if stop_event.is_set():
                sys.stderr.write("claim revoked mid-run; aborting\n")
                return 1

        # Record unmapped paths as a skill-level gap (attached to the first source entry)
        if resolver.unmapped_paths:
            scan_gap_entry = next((s for s in ctx.sources if s["source_id"].startswith("wiring-extract-static.scan")), None) \
                             or (ctx.sources[0] if ctx.sources else None)
            if scan_gap_entry is not None:
                scan_gap_entry["gaps"].extend(f"unmapped_path:{p}" for p in resolver.unmapped_paths[:50])
                if len(resolver.unmapped_paths) > 50:
                    scan_gap_entry["gaps"].append(f"unmapped_path_truncated:{len(resolver.unmapped_paths) - 50} more")

        # Replace in_progress scan entries with terminal aggregate
        non_progress = [s for s in ctx.sources if not s["source_id"].startswith("wiring-extract-static.scan")]
        scan_entries = [s for s in ctx.sources if s["source_id"].startswith("wiring-extract-static.scan")]
        for s in scan_entries:
            # If we never ran a scan-<lang> placeholder (we use it only as the initial seed),
            # mark it succeeded if langs present; else skipped.
            if s.get("status") == "in_progress":
                if ns.no_heartbeat is False and s.get("edge_count", 0) > 0:
                    s["status"] = "succeeded"
                else:
                    s["status"] = "skipped"
                    s["gaps"] = s.get("gaps") or []
        final_manifest = dict(initial_manifest)
        final_manifest["sources"] = scan_entries + non_progress
        final_manifest["completed_at"] = now_iso()

        # Atomic writes
        atomic_write_jsonl(static_jsonl_path, ctx.edge_lines)
        atomic_write_json(manifest_path, final_manifest)

        # Validate final manifest against schema
        try:
            jsonschema.validate(final_manifest, MANIFEST_SCHEMA, format_checker=FORMAT_CHECKER)
        except jsonschema.ValidationError as e:
            sys.stderr.write(f"final manifest schema error: {e.message}\n")
            return 1

        # Emit transition request — UNREACHABLE in --standalone (CB4: a claimless run
        # must be provably unable to drive a real ledger transition). The standalone
        # guard short-circuits BEFORE any .ledger/requests/ write.
        req_path = None
        if not ns.standalone and not ns.no_transition_request:
            req_path = emit_transition_request(
                project_dir=project_dir,
                claim_uuid=ns.claim_uuid,
                run_id=ns.run_id,
                manifest_path=manifest_path,
                static_jsonl_path=static_jsonl_path,
                target_stage=ns.target_stage,
            )
        sys.stdout.write(
            f"extraction ok run_id={ns.run_id} edges={len(ctx.edge_lines)} "
            f"sources={len(final_manifest['sources'])} request={req_path}\n"
        )
        return 0
    finally:
        if hb is not None:
            stop_event.set()
            hb.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
