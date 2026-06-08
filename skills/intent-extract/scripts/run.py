"""run.py — intent-extract CLI entry point (S032 WP-2).

Per-component pipeline:

  1. Load contract-map + static.jsonl + workspace files
  2. For each requested component:
     a. Compute content_hash from source files
     b. Compute cache_key (content_hash + extractor_version + model_id + template_hash)
     c. Cache HIT? → link into per-run dir + record manifest
     d. Cache MISS? → anchor_and_expand, build prompt, LLM call (1st arm)
     e. If --two-arm strict (default): second cold-context LLM call, reconcile
     f. Validate against schema; write cache + per-run symlink + manifest record
  3. Emit transition request for bob (INTENT_MAPPED transition)

Heartbeats claim every 60s via background thread. Exits cleanly on
LLMBudgetExhausted with PARTIAL status in the manifest.

CB4 rules:
  - This skill NEVER writes claim files (.ledger/claims/)
  - This skill NEVER writes progress/integration-ledger.md
  - This skill DOES write under .wiring/ (it's the single writer of intent files)
  - This skill DOES emit one transition request when complete
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
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

# Allow direct script execution from any cwd
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import anchor_expand  # noqa: E402
import cache  # noqa: E402
import llm_call  # noqa: E402
import manifest as manifest_mod  # noqa: E402
import prompt_template  # noqa: E402
import schema_validate  # noqa: E402
import two_arm_verify  # noqa: E402

EXTRACTOR_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Heartbeat thread
# ---------------------------------------------------------------------------


class HeartbeatThread:
    """Heartbeat the bob-issued claim every 60s in background.

    Uses subprocess to call claims.py — keeps this skill from importing the
    full _meta module on hosts without it.
    """

    def __init__(
        self,
        claim_uuid: str,
        project_root: Path,
        interval_seconds: int = 60,
        claims_module: Optional[Path] = None,
    ) -> None:
        self.claim_uuid = claim_uuid
        self.project_root = project_root
        self.interval = interval_seconds
        self.claims_module = claims_module
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _heartbeat_once(self) -> None:
        if self.claims_module is None:
            return
        try:
            subprocess.run(
                [sys.executable, str(self.claims_module), "heartbeat",
                 self.claim_uuid, "--project-root", str(self.project_root)],
                capture_output=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._heartbeat_once()
            if self._stop.wait(self.interval):
                break

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="intent-heartbeat",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Per-component pipeline
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _read_text_capped(path: Path, max_bytes: int = 65536) -> str:
    """Read a file capped at max_bytes for token-budget guarding."""
    try:
        b = path.read_bytes()
    except OSError:
        return ""
    if len(b) <= max_bytes:
        return b.decode("utf-8", errors="replace")
    return b[:max_bytes].decode("utf-8", errors="replace") + "\n# ... [truncated]\n"


def process_component(
    *,
    project_root: Path,
    run_id: str,
    component_id: str,
    workspace_tree_hash: str,
    contract_map: Dict[str, Any],
    model_id: str,
    backend: llm_call.LLMBackend,
    static_jsonl_path: Path,
    tokens_used_so_far: int,
    tokens_budget: int,
    two_arm: bool,
    template_hash_val: str,
) -> Dict[str, Any]:
    """Process one component. Returns a record dict for the manifest:

    {status: hit|regenerated|failed|gap, cache_key, output_path, error?,
     tokens_in, tokens_out}
    """
    # 1. Locate sources
    source_paths = anchor_expand.load_component_source_paths(
        contract_map, component_id, project_root
    )
    component_block = None
    for c in contract_map.get("components", []):
        if c.get("id") == component_id:
            component_block = c
            break
    if component_block is None:
        return {
            "status": "gap",
            "cache_key": "",
            "output_path": "",
            "error": f"component {component_id} not in contract-map",
        }

    # 2. Compute hashes
    cont_hash = cache.content_hash(source_paths)
    key = cache.cache_key(
        component_id, cont_hash, EXTRACTOR_VERSION, model_id, template_hash_val
    )

    # 3. Cache hit?
    cached = cache.read_cache(project_root, key)
    if cached is not None:
        link = cache.link_per_run(
            project_root, run_id, component_id,
            cache.cache_path(project_root, key),
        )
        return {
            "status": "hit",
            "cache_key": key,
            "output_path": str(link),
            "tokens_in": 0,
            "tokens_out": 0,
        }

    # 4. Cache miss → anchor + expand
    expansion = anchor_expand.anchor_and_expand(static_jsonl_path, component_id)
    file_contents = {str(p): _read_text_capped(p) for p in source_paths}
    edges_excerpt = expansion.direct_edges + expansion.neighbour_edges

    context = prompt_template.build_context_payload(
        component_id=component_id,
        contract_map_block=component_block,
        source_paths=[str(p) for p in source_paths],
        file_contents=file_contents,
        static_jsonl_excerpt=edges_excerpt,
    )

    prompt = prompt_template.render(
        component_id=component_id,
        source_paths_count=len(source_paths),
        files_visible_count=context["files_visible_count"],
        static_edges_visible_count=context["static_edges_visible_count"],
    )

    # 5. LLM call (arm A)
    try:
        resp_a = llm_call.call_with_budget(
            backend, prompt, context,
            model_id=model_id,
            tokens_used_so_far=tokens_used_so_far,
            tokens_budget=tokens_budget,
        )
    except llm_call.LLMBudgetExhausted as e:
        return {
            "status": "failed",
            "cache_key": key,
            "output_path": "",
            "error": f"budget_exhausted: {e}",
        }
    except (llm_call.LLMTransientError, llm_call.LLMPermanentError) as e:
        return {
            "status": "failed",
            "cache_key": key,
            "output_path": "",
            "error": f"llm_error: {e}",
        }

    # 6. Parse arm-A YAML
    try:
        intent_dict = yaml.safe_load(resp_a.raw_yaml) or {}
    except yaml.YAMLError as e:
        return {
            "status": "failed",
            "cache_key": key,
            "output_path": "",
            "error": f"yaml_parse: {e}",
            "tokens_in": resp_a.tokens_in,
            "tokens_out": resp_a.tokens_out,
        }
    if not isinstance(intent_dict, dict):
        return {
            "status": "failed",
            "cache_key": key,
            "output_path": "",
            "error": f"arm_A_output_not_mapping: got {type(intent_dict).__name__}",
            "tokens_in": resp_a.tokens_in,
            "tokens_out": resp_a.tokens_out,
        }

    # 7. Force-set deterministic provenance fields (LLM doesn't always fill them)
    intent_dict["schema_version"] = "1.0.0"
    intent_dict["component_id"] = component_id
    intent_dict["workspace_tree_hash"] = workspace_tree_hash
    intent_dict["content_hash"] = cont_hash
    intent_dict["extractor_id"] = "intent-extract"
    intent_dict["extractor_version"] = EXTRACTOR_VERSION
    intent_dict["model_id"] = model_id
    intent_dict["template_hash"] = template_hash_val
    intent_dict.setdefault("sampled_at",
                           time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    intent_dict.setdefault("determinism_class", "fresh_interpretive")

    # 8. Two-arm verification (optional but default)
    arm_b_intent: Optional[Dict[str, Any]] = None
    tokens_in_b = 0
    tokens_out_b = 0
    if two_arm:
        try:
            resp_b = llm_call.call_with_budget(
                backend, prompt, context,
                model_id=model_id,
                tokens_used_so_far=tokens_used_so_far + resp_a.tokens_in + resp_a.tokens_out,
                tokens_budget=tokens_budget,
            )
            tokens_in_b = resp_b.tokens_in
            tokens_out_b = resp_b.tokens_out
            try:
                arm_b_dict = yaml.safe_load(resp_b.raw_yaml) or {}
                if isinstance(arm_b_dict, dict):
                    arm_b_intent = arm_b_dict.get("intent")
            except yaml.YAMLError:
                arm_b_intent = None
        except (llm_call.LLMBudgetExhausted, llm_call.LLMTransientError):
            arm_b_intent = None

    known_edges = expansion.evidence_edge_ids
    intent_dict = two_arm_verify.annotate_confidence(intent_dict, arm_b_intent, known_edges)

    # 9. Schema validation
    ok, err = schema_validate.validate_payload(intent_dict)
    if not ok:
        return {
            "status": "failed",
            "cache_key": key,
            "output_path": "",
            "error": f"schema_validation: {err}",
            "tokens_in": resp_a.tokens_in + tokens_in_b,
            "tokens_out": resp_a.tokens_out + tokens_out_b,
        }

    # 10. Write cache + per-run symlink
    cached_file = cache.write_cache(
        project_root, key,
        yaml.safe_dump(intent_dict, sort_keys=False, default_flow_style=False),
    )
    link = cache.link_per_run(project_root, run_id, component_id, cached_file)

    return {
        "status": "regenerated",
        "cache_key": key,
        "output_path": str(link),
        "tokens_in": resp_a.tokens_in + tokens_in_b,
        "tokens_out": resp_a.tokens_out + tokens_out_b,
    }


# ---------------------------------------------------------------------------
# Transition request emission
# ---------------------------------------------------------------------------


def emit_transition_request(
    project_root: Path,
    *,
    claim_uuid: str,
    run_id: str,
    manifest: Dict[str, Any],
    target_stage: str = "INTENT_MAPPED",
) -> Path:
    """Write a transition request for bob to consume.

    Bob applies via claims.apply_request_idempotent. Skill is single-writer
    of this file (one per run); bob is single-writer of the ledger.
    """
    rdir = project_root / ".ledger" / "requests"
    rdir.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex
    request = {
        "schema_version": "1.0.0",
        "request_id": request_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "produced_by": "intent-extract",
        "claim_uuid": claim_uuid,
        "target_stage": target_stage,
        "run_id": run_id,
        "manifest_summary": manifest.get("summary", {}),
    }
    rpath = rdir / f"{request_id}.request.yaml"
    rpath.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")
    return rpath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="intent-extract",
        description="Per-component functional-intent extraction (S032 WP-2)",
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--claim-uuid", required=False, default=None,
                        help="bob-issued claim UUID; REQUIRED unless --standalone")
    parser.add_argument("--workspace-tree-hash", required=True,
                        help="40-hex git write-tree hash")
    # --- code-comprehension standalone mode (CB4: claims structurally impossible) ---
    # In --standalone the claim is NOT required, the HeartbeatThread is NEVER
    # constructed, and transition-request emission is UNREACHABLE. Additive: the
    # normal bob-driven path is byte-identical (no --standalone => unchanged).
    parser.add_argument("--standalone", action="store_true",
                        help="claimless read-only mode for code-comprehension; "
                             "no claim required, no heartbeat thread, no transition request")
    parser.add_argument("--contract-map-path", default=None,
                        help="path to the contract-map (default progress/contract-map.yaml); "
                             "the literal 'none' means NO contract map (clean run). "
                             "Fallback to progress/contract-map.yaml when 'none' is PROHIBITED.")
    parser.add_argument("--static-jsonl-path", default=None,
                        help="explicit static.jsonl path (standalone runs locate it under "
                             "a configurable output root, not .wiring/runs/<id>/)")
    parser.add_argument("--components", required=True,
                        help="comma-separated component ids")
    parser.add_argument("--model-id", default="claude-opus-4-7")
    parser.add_argument("--mode", default="intent-map-only",
                        choices=["intent-map-only", "version-upgrade", "cve-fix"])
    parser.add_argument("--two-arm", default="strict",
                        choices=["strict", "skip"])
    parser.add_argument("--tokens-budget", type=int,
                        default=int(os.environ.get("EVO_MAX_TOKENS_PER_RUN", "500000")))
    parser.add_argument("--no-heartbeat", action="store_true",
                        help="disable background claim heartbeat (testing only)")
    parser.add_argument("--no-transition-request", action="store_true",
                        help="skip writing the transition request (testing only)")
    parser.add_argument("--backend", default="anthropic",
                        choices=["anthropic", "fake"],
                        help="LLM backend; fake is for tests")
    parser.add_argument("--fake-yaml", default="",
                        help="canned YAML for FakeBackend (testing only)")

    args = parser.parse_args(argv)

    project_root: Path = args.project_root.resolve()
    if not project_root.is_dir():
        sys.stderr.write(f"ENV_ERROR: project_root not a directory: {project_root}\n")
        return 3

    # Claim is REQUIRED unless --standalone (CB4 structural guard: a standalone run
    # cannot heartbeat or emit a transition request, so a claim is meaningless there).
    if not args.standalone and not args.claim_uuid:
        sys.stderr.write("ENV_ERROR: --claim-uuid is required unless --standalone\n")
        return 3

    # Resolve the contract map. --contract-map-path semantics:
    #   (unset)  → progress/contract-map.yaml (default, byte-identical to old behavior)
    #   'none'   → NO contract map (clean run); fallback to progress/ is PROHIBITED
    #   <PATH>   → that exact path
    cmp_arg = args.contract_map_path
    if cmp_arg is None:
        contract_map_path = project_root / "progress" / "contract-map.yaml"
        if not contract_map_path.is_file():
            sys.stderr.write(f"ENV_ERROR: contract-map not found at {contract_map_path}\n")
            return 3
        contract_map = _load_yaml(contract_map_path)
    elif cmp_arg == "none":
        # Clean run — no contract map. Components must be addressable some other way
        # (e.g. a synthetic map passed explicitly). Fallback to progress/ is prohibited.
        contract_map = {"components": []}
    else:
        contract_map_path = Path(cmp_arg)
        if not contract_map_path.is_file():
            sys.stderr.write(f"ENV_ERROR: contract-map not found at {contract_map_path}\n")
            return 3
        contract_map = _load_yaml(contract_map_path)

    if args.static_jsonl_path:
        static_jsonl = Path(args.static_jsonl_path)
    else:
        static_jsonl = (
            project_root / ".wiring" / "runs" / args.run_id / "static.jsonl"
        )
    # static.jsonl may not exist on first run if evo has not invoked
    # wiring-extract-static yet. We continue with empty edges; the
    # extraction will be lower-quality but not crash.
    if not static_jsonl.is_file():
        # Try .wiring/latest.json fallback
        latest = project_root / ".wiring" / "latest.json"
        if latest.is_file():
            # The latest doesn't have edges directly — we just accept no
            # edges for now (degraded mode).
            pass

    template_hash_val = prompt_template.template_hash()

    # Backend selection
    if args.backend == "fake":
        backend: llm_call.LLMBackend = llm_call.FakeBackend(canned_yaml=args.fake_yaml)
    else:
        backend = llm_call.default_backend()

    # Heartbeat — in --standalone mode the HeartbeatThread is NEVER constructed
    # (structural CB4 guard, not --no-heartbeat sugar: there is no object that could
    # touch a claim file). The pipeline path is byte-identical when --standalone is off.
    heartbeat: Optional[HeartbeatThread] = None
    if not args.standalone and not args.no_heartbeat:
        claims_module = Path.home() / ".claude" / "skills" / "_meta" / "claims.py"
        if not claims_module.is_file():
            claims_module = (
                project_root / "skills" / "_meta" / "claims.py"
            )
        heartbeat = HeartbeatThread(
            args.claim_uuid, project_root,
            claims_module=claims_module if claims_module.is_file() else None,
        )
        heartbeat.start()

    try:
        component_ids = [c.strip() for c in args.components.split(",") if c.strip()]

        manifest = manifest_mod.empty_manifest(args.run_id)
        tokens_used = 0

        for cid in component_ids:
            record = process_component(
                project_root=project_root,
                run_id=args.run_id,
                component_id=cid,
                workspace_tree_hash=args.workspace_tree_hash,
                contract_map=contract_map,
                model_id=args.model_id,
                backend=backend,
                static_jsonl_path=static_jsonl,
                tokens_used_so_far=tokens_used,
                tokens_budget=args.tokens_budget,
                two_arm=(args.two_arm == "strict"),
                template_hash_val=template_hash_val,
            )
            manifest_mod.record_component(
                manifest, cid,
                record["status"],
                cache_key=record.get("cache_key", ""),
                output_path=record.get("output_path", ""),
                error=record.get("error", ""),
                tokens_in=record.get("tokens_in", 0),
                tokens_out=record.get("tokens_out", 0),
            )
            tokens_used += record.get("tokens_in", 0) + record.get("tokens_out", 0)

        manifest_mod.write_manifest(project_root, args.run_id, manifest)

        # Transition-request emission is UNREACHABLE in --standalone mode (CB4: a
        # claimless run must be provably unable to drive a real ledger transition).
        # The standalone guard short-circuits BEFORE any .ledger/requests/ write.
        if not args.standalone and not args.no_transition_request:
            emit_transition_request(
                project_root,
                claim_uuid=args.claim_uuid,
                run_id=args.run_id,
                manifest=manifest,
            )

        summary = manifest["summary"]
        sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
        # Exit 0 on success (even partial). Exit 2 if any "failed" beyond a
        # budget exhaustion — those are real failures the caller must triage.
        return 0
    finally:
        if heartbeat is not None:
            heartbeat.stop()


if __name__ == "__main__":
    sys.exit(main())
