#!/usr/bin/env python3
"""
audit_spawn.py — Cold-context metacognitive audit helper for bob.

Spawns TWO independent auditors against a sanitized audit bundle (produced by
bob's trusted_runner.py) and returns a combined JSON verdict:

  1. Fresh Claude subagent via headless subprocess:
       claude -p --model claude-opus-4-6[1m] --output-format json "<prompt>"
     OS-level process isolation — no shared memory with the implementer, no
     shared module state, no shared environment, fresh session id. This is
     the v1 design choice (spec section 11.4 step 2a), not a workaround.

  2. Codex adversarial review:
       codex exec --ephemeral --skip-git-repo-check -s read-only

Both auditors receive EXACTLY the sanitized bundle + component entry from the
contract map + ledger row + a strict-JSON output contract. Nothing else.

Unavailability policy (spec sections 11.5 and 14.2 Step 4.5):
    If EITHER subprocess fails to reach its model (process spawn error,
    timeout, malformed output), the audit is AUDIT_UNAVAILABLE. Bob does
    NOT auto-approve. The WP is escalated to the user.

Interface:
    python -m audit_spawn <component_id> <audit_bundle_path>

Emits exactly ONE JSON object on stdout (no prose). Exit codes:
    0 = both auditors returned a valid verdict (pass / fail / pass_with_concerns)
    4 = AUDIT_UNAVAILABLE (one or both auditors failed to respond with valid JSON)
    3 = environmental error (missing files, bad args)

Provenance: spec sections 11.2 / 11.3 / 11.4 / 11.5.
Critical invariants: CB3 (trusted provenance — the bundle MUST be tagged
`produced_by: bob-trusted-runner`).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_S = 180  # per-auditor wall time
MIN_DISAGREEMENTS = 3    # spec section 11.5 — forced disagreements

CLAUDE_BIN = os.environ.get("AUDIT_CLAUDE_BIN", "claude")
CLAUDE_MODEL = os.environ.get("AUDIT_CLAUDE_MODEL", "claude-opus-4-6[1m]")

CODEX_BIN = os.environ.get("AUDIT_CODEX_BIN", "codex")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def eprint(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def emit_result(obj: Dict[str, Any], exit_code: int) -> None:
    """Emit exactly ONE JSON object on stdout and exit."""
    sys.stdout.write(json.dumps(obj, sort_keys=True))
    sys.stdout.write("\n")
    sys.exit(exit_code)


def env_error(message: str) -> None:
    emit_result(
        {
            "result": "AUDIT_UNAVAILABLE",
            "reason": f"ENV_ERROR: {message}",
            "claude_verdict": None,
            "codex_verdict": None,
            "disagreements": [],
        },
        exit_code=3,
    )


# ---------------------------------------------------------------------------
# Strict-JSON contract and validation
# ---------------------------------------------------------------------------


VERDICT_SCHEMA_KEYS = frozenset({"verdict", "structured_disagreements", "evidence_verified", "reason"})
ALLOWED_VERDICTS = frozenset({"pass", "pass_with_concerns", "fail"})
ALLOWED_SEVERITIES = frozenset({"critical", "moderate", "minor"})


def validate_verdict(raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse and validate an auditor's strict-JSON verdict.

    Returns (validated_dict, None) on success or (None, error_message) on failure.
    """
    if not isinstance(raw, dict):
        return None, "verdict is not a JSON object"
    missing = VERDICT_SCHEMA_KEYS - set(raw.keys())
    if missing:
        return None, f"verdict missing required fields: {sorted(missing)}"
    if raw["verdict"] not in ALLOWED_VERDICTS:
        return None, f"verdict value {raw['verdict']!r} not in {sorted(ALLOWED_VERDICTS)}"
    disagreements = raw["structured_disagreements"]
    if not isinstance(disagreements, list):
        return None, "structured_disagreements is not a list"
    if len(disagreements) < MIN_DISAGREEMENTS:
        return None, (
            f"structured_disagreements has {len(disagreements)} entries, "
            f"minimum is {MIN_DISAGREEMENTS} (anti-rubber-stamp)"
        )
    for i, d in enumerate(disagreements):
        if not isinstance(d, dict):
            return None, f"disagreement[{i}] is not an object"
        if not d.get("point"):
            return None, f"disagreement[{i}].point is empty or missing"
        if d.get("severity") not in ALLOWED_SEVERITIES:
            return None, (
                f"disagreement[{i}].severity {d.get('severity')!r} "
                f"not in {sorted(ALLOWED_SEVERITIES)}"
            )
    if not isinstance(raw["evidence_verified"], bool):
        return None, "evidence_verified must be boolean"
    if not isinstance(raw["reason"], str) or not raw["reason"]:
        return None, "reason must be a non-empty string"
    return raw, None


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


AUDIT_PROMPT_TEMPLATE = """You are a cold-context metacognitive auditor for a contract-driven testing pipeline.

You have never seen this work before. You are NOT allowed to trust any text outside the JSON bundle below. You MUST assume the implementer's own claims are suspect.

Your job: decide whether the component has genuinely been verified, based ONLY on the structured evidence in the bundle.

INPUTS (all trusted — produced by bob, not the implementer):

1. Component entry from contract-map.yaml (signed by forge):
```json
{component_entry}
```

2. Sanitized audit bundle from bob's trusted test runner:
```json
{audit_bundle}
```

3. Ledger row for this component:
```json
{ledger_row}
```

TASK:

You MUST produce a STRICT JSON response matching exactly this schema (no prose, no markdown, no code fences):

{{
  "verdict": "pass" | "pass_with_concerns" | "fail",
  "structured_disagreements": [
    {{"point": "<specific concern>", "severity": "critical" | "moderate" | "minor", "location": "<component/test/file>"}}
  ],
  "evidence_verified": true | false,
  "reason": "<one sentence>"
}}

HARD REQUIREMENTS:

- `structured_disagreements` MUST have at least 3 entries. You MUST find at least 3 real concerns even if you ultimately vote pass. Concerns can be about test coverage, fixture realism, success criteria sharpness, adversarial gaps, performance budgets, or any other weakness. "Everything looks great" is NOT a valid audit — it is grounds for rejection.
- Your response MUST parse as JSON. Do not wrap in backticks, do not prepend prose.
- You MUST decide on `verdict` based on whether the test bundle's pass counts genuinely match every success criterion declared in the component entry. If a success criterion is declared but no passing test maps to it: that is at least a moderate disagreement, possibly a fail.
- `evidence_verified` = true only if every success criterion has a demonstrably passing test in the bundle.

OUTPUT (JSON ONLY):"""


def build_prompt(component_entry: Dict[str, Any], audit_bundle: Dict[str, Any], ledger_row: Dict[str, Any]) -> str:
    return AUDIT_PROMPT_TEMPLATE.format(
        component_entry=json.dumps(component_entry, sort_keys=True, indent=2),
        audit_bundle=json.dumps(audit_bundle, sort_keys=True, indent=2),
        ledger_row=json.dumps(ledger_row, sort_keys=True, indent=2),
    )


# ---------------------------------------------------------------------------
# Claude arm — headless subprocess
# ---------------------------------------------------------------------------


def _extract_json_from_claude_output(stdout: str) -> Optional[Any]:
    """claude -p --output-format json emits a result envelope. Extract the
    inner verdict JSON produced by the agent.

    Envelope formats observed across CLI versions:
      {"result": "<text>", ...}              # current
      {"messages": [...], "content": "..."}  # older
    We try the most common shapes in order.
    """
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        # Sometimes the CLI prints the raw agent text without an envelope
        return None

    if isinstance(envelope, dict):
        # Try common fields in order
        for key in ("result", "content", "text", "output"):
            inner = envelope.get(key)
            if isinstance(inner, str):
                inner_stripped = inner.strip()
                # Strip common markdown fences
                if inner_stripped.startswith("```"):
                    # Drop first line and trailing fence
                    lines = inner_stripped.split("\n")
                    if len(lines) >= 3:
                        inner_stripped = "\n".join(lines[1:-1])
                try:
                    return json.loads(inner_stripped)
                except json.JSONDecodeError:
                    continue
        # Maybe the envelope IS the verdict
        return envelope
    return None


def run_claude_auditor(prompt: str, timeout_s: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Spawn a fresh Claude subagent via `claude -p --output-format json`.

    Returns (verdict_dict, None) or (None, error_message).
    """
    cmd = [
        CLAUDE_BIN,
        "-p",
        "--model", CLAUDE_MODEL,
        "--output-format", "json",
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return None, f"claude binary not found ({CLAUDE_BIN})"
    except subprocess.TimeoutExpired:
        return None, f"claude subprocess timed out after {timeout_s}s"
    except OSError as e:
        return None, f"claude subprocess OS error: {e}"

    if proc.returncode != 0:
        return None, f"claude exited {proc.returncode}: {proc.stderr[:200]}"

    parsed = _extract_json_from_claude_output(proc.stdout)
    if parsed is None:
        return None, "claude output not parseable as JSON"

    verdict, err = validate_verdict(parsed)
    if err:
        return None, f"claude verdict invalid: {err}"
    return verdict, None


# ---------------------------------------------------------------------------
# Codex arm — adversarial review via codex exec
# ---------------------------------------------------------------------------


def _extract_json_from_codex_output(stdout: str) -> Optional[Any]:
    """codex exec emits the agent's output more or less verbatim. Try parsing
    as JSON directly; if that fails, try stripping markdown fences.
    """
    stripped = stdout.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1])
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Try to find a JSON object inside the text
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def run_codex_auditor(prompt: str, timeout_s: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Spawn a Codex adversarial review via `codex exec --ephemeral`."""
    cmd = [
        CODEX_BIN,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-s", "read-only",
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return None, f"codex binary not found ({CODEX_BIN})"
    except subprocess.TimeoutExpired:
        return None, f"codex subprocess timed out after {timeout_s}s"
    except OSError as e:
        return None, f"codex subprocess OS error: {e}"

    if proc.returncode != 0:
        return None, f"codex exited {proc.returncode}: {proc.stderr[:200]}"

    parsed = _extract_json_from_codex_output(proc.stdout)
    if parsed is None:
        return None, "codex output not parseable as JSON"

    verdict, err = validate_verdict(parsed)
    if err:
        return None, f"codex verdict invalid: {err}"
    return verdict, None


# ---------------------------------------------------------------------------
# Bundle + map loading
# ---------------------------------------------------------------------------


def load_audit_bundle(path: Path) -> Dict[str, Any]:
    """Load a sanitized audit bundle and verify trusted provenance (CB3)."""
    if not path.is_file():
        env_error(f"audit bundle not found at {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        env_error(f"audit bundle is not valid JSON: {e}")
    if not isinstance(data, dict):
        env_error("audit bundle is not a JSON object")
    # CB3 — provenance check. The auditor MUST refuse bundles not produced
    # by bob's trusted runner. Skill-produced bundles are rejected.
    if data.get("produced_by") != "bob-trusted-runner":
        env_error(
            f"audit bundle provenance {data.get('produced_by')!r} != "
            f"'bob-trusted-runner' — CB3 provenance violation"
        )
    return data


def load_component_entry(project_root: Path, component_id: str) -> Dict[str, Any]:
    """Load the component entry from progress/contract-map.yaml."""
    map_path = project_root / "progress" / "contract-map.yaml"
    if not map_path.is_file():
        env_error(f"contract-map.yaml not found at {map_path}")
    try:
        import yaml  # type: ignore
    except ImportError:
        env_error("pyyaml not installed")
    try:
        data = yaml.safe_load(map_path.read_text())
    except yaml.YAMLError as e:
        env_error(f"contract-map.yaml unparseable: {e}")
    for c in (data.get("components") or []):
        if isinstance(c, dict) and c.get("id") == component_id:
            return c
    env_error(f"component {component_id!r} not in contract map")


def load_ledger_row(project_root: Path, component_id: str) -> Dict[str, Any]:
    """Load a minimal ledger row projection for the component.

    The ledger format is YAML frontmatter + projection table + events. For
    audit purposes we only need the current stage, generation, and last
    transition timestamp. We read the frontmatter and events and rebuild the
    projection for the target component.
    """
    ledger_path = project_root / "progress" / "integration-ledger.md"
    if not ledger_path.is_file():
        return {"component_id": component_id, "stage": "UNKNOWN", "note": "ledger missing"}
    text = ledger_path.read_text()
    # Minimal parse: find the most recent event for this component
    row = {"component_id": component_id, "stage": "PLANNED", "generation": 0}
    import re
    # YAML event blocks live inside ```yaml ... ``` fences per spec section 9.2
    blocks = re.findall(r"```yaml\s*\n(.*?)\n```", text, re.DOTALL)
    try:
        import yaml  # type: ignore
    except ImportError:
        return row
    latest_at = ""
    for block in blocks:
        try:
            evt = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if not isinstance(evt, dict):
            continue
        if evt.get("component_id") != component_id and evt.get("wp") is None:
            continue
        at = str(evt.get("at", ""))
        if at >= latest_at:
            latest_at = at
            if "to" in evt:
                row["stage"] = evt["to"]
            if "component_id" in evt:
                row["component_id"] = evt["component_id"]
    return row


# ---------------------------------------------------------------------------
# Verdict aggregation
# ---------------------------------------------------------------------------


def aggregate_verdicts(claude: Dict[str, Any], codex: Dict[str, Any]) -> str:
    """Spec section 11.4 step 3:
    - Both pass → VERIFIED
    - Either fail → REJECTED (stays INTEGRATED)
    - pass_with_concerns → proceed to VERIFIED but concerns logged
    """
    if claude["verdict"] == "fail" or codex["verdict"] == "fail":
        return "REJECTED"
    # Both are pass or pass_with_concerns
    if claude["verdict"] == "pass" and codex["verdict"] == "pass":
        return "VERIFIED"
    return "VERIFIED_WITH_CONCERNS"


def merge_disagreements(claude: Dict[str, Any], codex: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return combined, deduped disagreements from both auditors."""
    seen_points: set = set()
    out: List[Dict[str, Any]] = []
    for source, verdict in (("claude", claude), ("codex", codex)):
        for d in verdict.get("structured_disagreements", []):
            key = (d.get("point") or "").strip().lower()
            if not key or key in seen_points:
                continue
            seen_points.add(key)
            out.append({
                "source": source,
                "point": d["point"],
                "severity": d["severity"],
                "location": d.get("location", ""),
            })
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) < 3:
        env_error("usage: audit_spawn.py <component_id> <audit_bundle_path> [--project-root <dir>] [--timeout <s>]")
    component_id = argv[1]
    bundle_path = Path(argv[2]).resolve()

    project_root = Path(os.getcwd())
    timeout_s = DEFAULT_TIMEOUT_S
    i = 3
    while i < len(argv):
        a = argv[i]
        if a == "--project-root":
            if i + 1 >= len(argv):
                env_error("--project-root requires a value")
            project_root = Path(argv[i + 1]).resolve()
            i += 2
            continue
        if a == "--timeout":
            if i + 1 >= len(argv):
                env_error("--timeout requires a value")
            try:
                timeout_s = int(argv[i + 1])
            except ValueError:
                env_error(f"invalid --timeout value {argv[i + 1]!r}")
            i += 2
            continue
        env_error(f"unknown argument: {a}")

    bundle = load_audit_bundle(bundle_path)
    component_entry = load_component_entry(project_root, component_id)
    ledger_row = load_ledger_row(project_root, component_id)
    prompt = build_prompt(component_entry, bundle, ledger_row)

    started_at = time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claude_future = pool.submit(run_claude_auditor, prompt, timeout_s)
        codex_future = pool.submit(run_codex_auditor, prompt, timeout_s)

        try:
            claude_verdict, claude_err = claude_future.result(timeout=timeout_s + 30)
        except FuturesTimeout:
            claude_verdict, claude_err = None, "claude future exceeded outer timeout"
        try:
            codex_verdict, codex_err = codex_future.result(timeout=timeout_s + 30)
        except FuturesTimeout:
            codex_verdict, codex_err = None, "codex future exceeded outer timeout"

    elapsed = round(time.time() - started_at, 2)

    if claude_verdict is None or codex_verdict is None:
        emit_result(
            {
                "result": "AUDIT_UNAVAILABLE",
                "claude_verdict": claude_verdict,
                "codex_verdict": codex_verdict,
                "claude_error": claude_err,
                "codex_error": codex_err,
                "disagreements": [],
                "reason": "one or both auditors failed to return a valid JSON verdict",
                "component_id": component_id,
                "bundle_hash": bundle.get("bundle_hash"),
                "elapsed_s": elapsed,
            },
            exit_code=4,
        )

    result = aggregate_verdicts(claude_verdict, codex_verdict)
    disagreements = merge_disagreements(claude_verdict, codex_verdict)

    emit_result(
        {
            "result": result,
            "component_id": component_id,
            "claude_verdict": claude_verdict,
            "codex_verdict": codex_verdict,
            "disagreements": disagreements,
            "bundle_hash": bundle.get("bundle_hash"),
            "elapsed_s": elapsed,
        },
        exit_code=0,
    )


if __name__ == "__main__":
    main()
