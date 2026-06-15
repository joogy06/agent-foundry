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
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- S046 / #124 observe-only cost telemetry (best-effort, never-raise) ------
# extract_usage pulls cost/duration/num_turns from the claude -p JSON envelope;
# record_spawn_run appends one line to .process-observations/spawn-runs.jsonl.
# Both are null-safe + never-raise. Loaded fail-open so a missing module / a
# broken backend can NEVER perturb this spawner's verdict-return API or exit
# code (the audit pipeline's correctness is independent of telemetry). See
# spawn_usage.py / spawn_runs.py headers and design §A/§G.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
try:
    from spawn_usage import extract_usage as _extract_usage  # noqa: E402
except Exception:  # pragma: no cover - fail-open: telemetry must never block audit
    def _extract_usage(envelope: Any) -> Dict[str, Optional[float]]:
        return {"cost_usd": None, "duration_ms": None, "num_turns": None}

# spawn_runs.py lives in the process-observation skill, not _meta. Add that
# scripts dir to sys.path; fail-open to a no-op recorder if unavailable.
_PROC_OBS_SCRIPTS = (
    _SCRIPT_DIR.parent / "process-observation" / "scripts"
)
if _PROC_OBS_SCRIPTS.is_dir() and str(_PROC_OBS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PROC_OBS_SCRIPTS))
try:
    from spawn_runs import record_spawn_run as _record_spawn_run  # noqa: E402
except Exception:  # pragma: no cover - fail-open: telemetry must never block audit
    def _record_spawn_run(**kwargs: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_S = 300  # per-auditor wall time (S030-quickwins #53; was 180s)
MIN_DISAGREEMENTS = 3    # spec section 11.5 — forced disagreements

CLAUDE_BIN = os.environ.get("AUDIT_CLAUDE_BIN", "claude")

# S059 smart-config: env > policy > hardcoded chain (design §7). The hardcoded
# fallback is refreshed to the current 1M-context Opus (was the stale
# claude-opus-4-6[1m]). The headless surface accepts alias[1m] natively (V-1), so a
# policy that resolves to e.g. "opus[1m]" is passed straight to `claude -p --model`.
# Fail-open at every step — a missing/broken resolver NEVER changes the audit model.
_AUDIT_HARDCODED_MODEL = "claude-opus-4-8[1m]"


def _resolve_spawn_model(env_var: str, hardcoded: str) -> str:
    """env > policy > hardcoded. ~15 LOC, fail-open, 10s timeout (design §7).

    1. If the env var is set, it wins (operator override / test pin).
    2. Else ask the smart-config resolver for the headless 'medium' tier (the
       verifier arm is a review/verify role -> medium). model:null -> hardcoded.
    3. Any error / timeout / missing resolver -> hardcoded. Never raises.
    """
    val = os.environ.get(env_var)
    if val:
        return val
    try:
        resolver = os.path.expanduser(
            "~/.claude/skills/smart-config/scripts/model_policy.py"
        )
        proc = subprocess.run(
            ["python3", resolver, "resolve", "--tier", "medium",
             "--surface", "headless", "--reason", "metacognitive audit arm",
             "--no-log"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            obj = json.loads(proc.stdout.strip().splitlines()[-1])
            m = obj.get("model")
            if m:
                return m
    except Exception:  # noqa: BLE001 - fail-open: policy never breaks the audit
        pass
    return hardcoded


CLAUDE_MODEL = _resolve_spawn_model("AUDIT_CLAUDE_MODEL", _AUDIT_HARDCODED_MODEL)

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
# Race-safe directory provisioning (S030-quickwins #54)
# ---------------------------------------------------------------------------
#
# The S028 #45 spawn 6 race surfaced when two parallel processes (verdict
# writer + symlink updater) hit a `mkdir -p` against the same `.ledger/`
# subdir at the same time. POSIX `mkdir(2)` itself is atomic per directory
# component, but `pathlib.Path.mkdir(parents=True, exist_ok=True)` walks the
# parent chain and a sibling process creating an intermediate component can
# race against `os.stat` -> `os.mkdir`. The defensive pattern is: provision
# the directory ONCE in the parent process BEFORE forking / spawning any
# parallel work that will write into it. This helper bakes that contract in.
#
# Use this from any future caller that wants to spawn audit_spawn alongside
# another verdict producer (e.g. a coverage arbiter, a drift-arbiter pipeline
# stage). The helper is intentionally narrow: it ensures the directory exists
# synchronously, then yields control to the caller. It does NOT spawn
# subprocesses itself — that's the caller's responsibility — because spawn
# semantics differ across callers (subprocess.Popen vs ThreadPoolExecutor vs
# asyncio.create_subprocess_exec). Keeping the directory provisioning
# separate from the spawn keeps this file a single self-contained module.

def ensure_verdicts_dir(verdicts_dir: Path) -> Path:
    """Synchronously create `verdicts_dir` (and parents) before any spawn.

    Resolves the directory path, calls `mkdir(parents=True, exist_ok=True)`
    once in the parent process, and returns the resolved path. After this
    call returns, the caller can safely fork / Popen multiple verdict
    producers that will all write into the same directory without racing on
    the directory's creation. CB4 boundary preserved (only bob ever calls
    this; only bob ever writes into `.ledger/verdicts/`).

    See `audit_spawn_race_note` for the full back-story.
    """
    verdicts_dir = Path(verdicts_dir).resolve()
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    return verdicts_dir


# RACE NOTE (S028 #45 spawn 6, fixed in S030-quickwins #54):
# Do NOT call `mkdir -p` (or pathlib's equivalent) from inside a backgrounded
# subshell or a child Python process if a sibling process is also writing into
# the same directory tree. The parent must provision the directory first via
# `ensure_verdicts_dir()` and then spawn the parallel workers.
audit_spawn_race_note = (
    "ensure_verdicts_dir() must be called by the caller BEFORE spawning any "
    "parallel verdict producer that will write into `.ledger/verdicts/` or a "
    "sibling subdir. Provisions the directory synchronously in the parent "
    "process so concurrent writers do not race on directory creation."
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

DEFERRED TEST PATHS (v2 roadmap):

- If a `test_paths` key (`integration`, `flow`, etc.) is declared as an object with `deferred_to_v2: true`, that path is **intentionally empty at v1**. Do NOT flag it as missing evidence. Do NOT count it as a coverage gap. The `reason` field explains why. You may still surface deferred coverage as a minor concern (v2 risk), but NOT as a critical or moderate disagreement, and NOT as grounds for `evidence_verified=false`.
- `evidence_verified` = true requires every success_criterion to map to a passing test in the bundle from the NON-deferred test paths (typically `unit`). Deferred paths are out of scope for v1 verification.

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


def _parse_agent_text_as_json(text: str) -> Optional[Any]:
    """Parse the agent's final assistant text as JSON.

    Handles three flavors of payload in order of preference:
      1. Clean JSON: `{"verdict": "pass", ...}`
      2. Fenced: ```json\n{...}\n``` or ```\n{...}\n```
      3. Prose + embedded JSON: use outermost `{` / `}` brace match.
    Returns None only if no parseable JSON object can be recovered.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    # Strip common markdown fences (``` or ```json)
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Prose + JSON fallback: outermost brace match
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(stripped[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _extract_json_from_claude_output(stdout: str) -> Optional[Any]:
    """Extract the inner verdict JSON produced by a `claude -p --output-format
    json` subprocess.

    Three envelope shapes are supported across CLI versions:

      (a) Current (claude 2.1.x) — top-level JSON **array** of stream messages:
          [
            {"type": "system", "subtype": "init", ...},
            {"type": "assistant", "message": {"content": [{"type": "text",
                "text": "<verdict JSON>"}], ...}, ...},
            {"type": "result", "subtype": "success", "result": "<verdict JSON>", ...}
          ]
          The final `{"type": "result", ...}` element carries the agent's final
          text in its `result` field. We prefer this; fall back to the last
          assistant text block if `result` is missing.

      (b) Legacy dict envelope — `{"result": "...", ...}` or `{"content": "..."}`
          or `{"text": "..."}` or `{"output": "..."}` (older CLI versions).

      (c) Raw verdict — the CLI occasionally prints the agent's JSON verbatim
          with no envelope. Parsed directly.

    For each shape, the extracted agent text is passed through
    `_parse_agent_text_as_json` which handles fences and prose-wrapped JSON.

    Returns None only when no recoverable JSON object exists, which triggers
    AUDIT_UNAVAILABLE upstream.
    """
    if not isinstance(stdout, str) or not stdout.strip():
        return None

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        # Raw-text fallback — no envelope at all
        return _parse_agent_text_as_json(stdout)

    # Shape (a): list of stream messages
    if isinstance(envelope, list):
        # Prefer the final {"type":"result", "result":"..."} element
        for msg in reversed(envelope):
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "result":
                result_text = msg.get("result")
                parsed = _parse_agent_text_as_json(result_text) if isinstance(result_text, str) else None
                if parsed is not None:
                    return parsed
                break  # result exists but unparseable — fall through to assistant text
        # Fallback: walk assistant messages in reverse, pull final text content
        for msg in reversed(envelope):
            if not isinstance(msg, dict) or msg.get("type") != "assistant":
                continue
            message = msg.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                # content is a list of blocks like [{"type":"text","text":"..."}]
                texts = [
                    block.get("text")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                for t in reversed(texts):
                    parsed = _parse_agent_text_as_json(t) if isinstance(t, str) else None
                    if parsed is not None:
                        return parsed
        return None

    # Shape (b): legacy dict envelope
    if isinstance(envelope, dict):
        for key in ("result", "content", "text", "output"):
            inner = envelope.get(key)
            if isinstance(inner, str):
                parsed = _parse_agent_text_as_json(inner)
                if parsed is not None:
                    return parsed
        # Shape (c) partial: the envelope itself might already be the verdict
        # (e.g. direct `{"verdict":"pass",...}` dump with no outer wrapper).
        if "verdict" in envelope:
            return envelope
        return None

    return None


def run_claude_auditor(
    prompt: str,
    timeout_s: int,
    usage_out: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Spawn a fresh Claude subagent via `claude -p --output-format json`.

    Returns (verdict_dict, None) or (None, error_message) — the verdict-return
    API is UNCHANGED (#124 constraint). The optional `usage_out` dict is a
    side-channel: when provided, it is populated in place with the arm's
    cost/duration/num_turns (from the JSON envelope) plus `wall_clock_s`. It is
    never read by this function and its absence changes nothing — so every
    existing caller / test that calls `run_claude_auditor(prompt, timeout)`
    behaves exactly as before.
    """
    cmd = [
        CLAUDE_BIN,
        "-p",
        "--model", CLAUDE_MODEL,
        "--output-format", "json",
        prompt,
    ]
    _arm_start = time.time()

    def _stamp_usage(envelope: Any) -> None:
        # Best-effort, never-raise: fill usage_out if the caller asked for it.
        if usage_out is None:
            return
        try:
            usage = _extract_usage(envelope)
            usage_out.update(usage)
            usage_out["wall_clock_s"] = round(time.time() - _arm_start, 3)
        except BaseException:  # noqa: BLE001
            usage_out.setdefault("wall_clock_s", round(time.time() - _arm_start, 3))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        _stamp_usage(None)
        return None, f"claude binary not found ({CLAUDE_BIN})"
    except subprocess.TimeoutExpired:
        _stamp_usage(None)
        return None, f"claude subprocess timed out after {timeout_s}s"
    except OSError as e:
        _stamp_usage(None)
        return None, f"claude subprocess OS error: {e}"

    # Parse the envelope ONCE; reuse it for both the verdict and the usage.
    envelope: Any = None
    if isinstance(proc.stdout, str) and proc.stdout.strip():
        try:
            envelope = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            envelope = proc.stdout  # extract_usage will null-out on non-JSON
    _stamp_usage(envelope)

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
    """codex exec emits the agent's output more or less verbatim. Reuse the
    shared prose/fence/brace-match parser used by the Claude arm.
    """
    return _parse_agent_text_as_json(stdout)


def run_codex_auditor(
    prompt: str,
    timeout_s: int,
    usage_out: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Spawn a Codex adversarial review via `codex exec --ephemeral`.

    Verdict-return API UNCHANGED (#124). `usage_out`, when provided, is filled
    with this arm's wall_clock_s; cost/duration/num_turns stay null because the
    Codex path is NOT a `claude -p --output-format json` envelope (this is the
    null-safe non-JSON path the design calls out — null, never error).
    """
    cmd = [
        CODEX_BIN,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-s", "read-only",
        prompt,
    ]
    _arm_start = time.time()

    def _stamp_usage(envelope: Any) -> None:
        if usage_out is None:
            return
        try:
            usage = _extract_usage(envelope)  # plain text -> all-None
            usage_out.update(usage)
            usage_out["wall_clock_s"] = round(time.time() - _arm_start, 3)
        except BaseException:  # noqa: BLE001
            usage_out.setdefault("wall_clock_s", round(time.time() - _arm_start, 3))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        _stamp_usage(None)
        return None, f"codex binary not found ({CODEX_BIN})"
    except subprocess.TimeoutExpired:
        _stamp_usage(None)
        return None, f"codex subprocess timed out after {timeout_s}s"
    except OSError as e:
        _stamp_usage(None)
        return None, f"codex subprocess OS error: {e}"

    # codex exec emits plain prose, not a JSON envelope -> usage stays null.
    _stamp_usage(proc.stdout)

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


def _parse_projection_table(text: str, component_id: str) -> Optional[Dict[str, Any]]:
    """Parse the ledger's projection table (authoritative current stage).

    The table has this shape (leading/trailing whitespace and cell padding
    are tolerated; ``—`` / ``-`` / ``—`` are all valid "empty" markers):

        | WP   | component              | stage      | generation | deps |
        |------|------------------------|------------|------------|------|
        | WP-2 | wiring-extract-static  | INTEGRATED | 3          | —    |

    Bob writes this table at the top of ``progress/integration-ledger.md``
    as the **authoritative** projection of component state. Event-log prose
    sections (``### <ts> — WP-N STAGE_A → STAGE_B ...``) are advisory
    history only; the projection table wins on conflict.

    Returns a dict with ``component_id``, ``stage``, ``generation`` (int),
    and optionally ``wp``, ``deps``. Returns None if the table is missing,
    malformed, or the component is absent.
    """
    import re

    # Locate the first markdown table that declares a "component" column and a
    # "stage" column. This tolerates extra columns in future schema revisions.
    lines = text.splitlines()
    table_start = -1
    header_cells: List[str] = []
    for i, line in enumerate(lines):
        if "|" not in line:
            continue
        cells = [c.strip().lower() for c in line.strip().strip("|").split("|")]
        if "component" in cells and "stage" in cells and "generation" in cells:
            table_start = i
            header_cells = cells
            break
    if table_start < 0:
        return None

    # The next line after the header must be the separator `|---|---|...`.
    sep_idx = table_start + 1
    if sep_idx >= len(lines):
        return None
    sep = lines[sep_idx].strip()
    if not re.match(r"^\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", sep):
        return None

    # Column indices
    col = {name: idx for idx, name in enumerate(header_cells)}
    comp_idx = col["component"]
    stage_idx = col["stage"]
    gen_idx = col["generation"]
    wp_idx = col.get("wp")
    deps_idx = col.get("deps")

    # Iterate data rows until a blank / non-table line.
    for row_line in lines[sep_idx + 1:]:
        stripped = row_line.strip()
        if not stripped or not stripped.startswith("|"):
            break
        cells_raw = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells_raw) <= max(comp_idx, stage_idx, gen_idx):
            continue  # malformed / short row — skip

        # Strip markdown emphasis from cells (``*smoke*``, ``**foo**``).
        def _clean(s: str) -> str:
            return s.strip().strip("*").strip("_").strip()

        component_cell = _clean(cells_raw[comp_idx])
        if component_cell != component_id:
            continue

        stage_cell = _clean(cells_raw[stage_idx])
        gen_cell = _clean(cells_raw[gen_idx])
        # Generation may be "—", "-", or missing — in those cases we emit 0.
        try:
            generation = int(gen_cell)
        except (ValueError, TypeError):
            generation = 0

        out: Dict[str, Any] = {
            "component_id": component_id,
            "stage": stage_cell or "UNKNOWN",
            "generation": generation,
        }
        if wp_idx is not None and len(cells_raw) > wp_idx:
            out["wp"] = _clean(cells_raw[wp_idx])
        if deps_idx is not None and len(cells_raw) > deps_idx:
            deps_cell = _clean(cells_raw[deps_idx])
            if deps_cell in ("", "—", "-", "–"):
                out["deps"] = []
            else:
                out["deps"] = [d.strip() for d in deps_cell.split(",") if d.strip()]
        return out

    return None


def _parse_yaml_fenced_events(text: str, component_id: str) -> Optional[Dict[str, Any]]:
    """Legacy event-log parser (spec §9.2 yaml-fenced shape).

    Kept for backward compatibility with ledgers that emit events as
    ``\\`\\`\\`yaml`` fenced blocks. Returns the row rebuilt from the most
    recent event, or None if no matching event exists.
    """
    import re

    blocks = re.findall(r"```yaml\s*\n(.*?)\n```", text, re.DOTALL)
    if not blocks:
        return None
    try:
        import yaml  # type: ignore
    except ImportError:
        return None

    row: Dict[str, Any] = {"component_id": component_id, "stage": "PLANNED", "generation": 0}
    latest_at = ""
    matched = False
    for block in blocks:
        try:
            evt = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if not isinstance(evt, dict):
            continue
        if evt.get("component_id") != component_id:
            continue
        matched = True
        at = str(evt.get("at", ""))
        if at >= latest_at:
            latest_at = at
            if "to" in evt:
                row["stage"] = evt["to"]
            if "generation" in evt:
                try:
                    row["generation"] = int(evt["generation"])
                except (ValueError, TypeError):
                    pass
    return row if matched else None


def load_ledger_row(project_root: Path, component_id: str) -> Dict[str, Any]:
    """Load a minimal ledger row projection for the component.

    Stage-resolution precedence (most authoritative first):

    1. **Projection table** — the markdown table at the top of
       ``progress/integration-ledger.md`` with columns
       ``| WP | component | stage | generation | deps |``. This is bob's
       authoritative projection and wins over everything else.
    2. **Yaml-fenced events (legacy §9.2)** — rebuilt from the most
       recent ``\\`\\`\\`yaml ... \\`\\`\\``` event that matches
       ``component_id``. Used only when no projection table exists.
    3. **Unknown** — if neither source has a row for the component,
       returns ``{stage: "UNKNOWN", ...}`` (NOT ``PLANNED``, which
       would falsely imply the component is tracked but un-started).

    Prose event sections like
    ``### 2026-04-15T00:52:00Z — WP-2 UNIT_TESTED → INTEGRATED (bob applied)``
    are advisory history. The parser intentionally does not try to derive
    stage from prose — bob's projection table is the single source of truth.
    """
    ledger_path = project_root / "progress" / "integration-ledger.md"
    if not ledger_path.is_file():
        return {"component_id": component_id, "stage": "UNKNOWN", "note": "ledger missing"}
    text = ledger_path.read_text()

    # Precedence 1: projection table wins.
    row = _parse_projection_table(text, component_id)
    if row is not None:
        return row

    # Precedence 2: legacy yaml-fenced event log.
    row = _parse_yaml_fenced_events(text, component_id)
    if row is not None:
        return row

    # Precedence 3: component is not tracked anywhere.
    return {"component_id": component_id, "stage": "UNKNOWN", "generation": 0, "note": "component not in projection table or events"}


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
# Observe-only spawn-run telemetry (S046 / #124)
# ---------------------------------------------------------------------------


def _emit_audit_spawn_runs(
    *,
    claude_usage: Dict[str, Any],
    codex_usage: Dict[str, Any],
    claude_verdict: Optional[Dict[str, Any]],
    claude_err: Optional[str],
    codex_verdict: Optional[Dict[str, Any]],
    codex_err: Optional[str],
    invocation_id: str,
    cycle_id: Optional[str],
    component_id: str,
    bundle_hash: Optional[str],
    project_root: Path,
) -> None:
    """Append one spawn-run record per audit arm. BEST-EFFORT; never raises.

    The audit arm is NOT request-bound (no verification request id), so
    request_id is left null; the arbiter arm (the other spawner) carries it.
    `status` is the arm's verdict string on success or an error sentinel on
    failure — observe-only context, never a gate signal.
    """
    try:
        claude_status = (
            claude_verdict.get("verdict") if isinstance(claude_verdict, dict)
            else f"ERROR: {claude_err}"
        )
        _record_spawn_run(
            tool="audit_claude",
            status=claude_status,
            cost_usd=claude_usage.get("cost_usd"),
            duration_ms=claude_usage.get("duration_ms"),
            num_turns=claude_usage.get("num_turns"),
            wall_clock_s=claude_usage.get("wall_clock_s"),
            model=CLAUDE_MODEL,
            cycle_id=cycle_id,
            component_id=component_id,
            bundle_hash=bundle_hash,
            request_id=None,
            invocation_id=invocation_id,
            project_root_override=project_root,
        )
    except BaseException:  # noqa: BLE001
        pass
    try:
        codex_status = (
            codex_verdict.get("verdict") if isinstance(codex_verdict, dict)
            else f"ERROR: {codex_err}"
        )
        _record_spawn_run(
            tool="audit_codex",
            status=codex_status,
            cost_usd=codex_usage.get("cost_usd"),
            duration_ms=codex_usage.get("duration_ms"),
            num_turns=codex_usage.get("num_turns"),
            wall_clock_s=codex_usage.get("wall_clock_s"),
            model="codex",
            cycle_id=cycle_id,
            component_id=component_id,
            bundle_hash=bundle_hash,
            request_id=None,
            invocation_id=invocation_id,
            project_root_override=project_root,
        )
    except BaseException:  # noqa: BLE001
        pass


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

    # #124 observe-only telemetry: per-arm usage side-channels. The audit
    # pipeline does not read these; they feed ONLY the spawn-runs.jsonl sidecar.
    claude_usage: Dict[str, Any] = {}
    codex_usage: Dict[str, Any] = {}
    invocation_id = uuid.uuid4().hex
    cycle_id = os.environ.get("FORGE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    bundle_hash = bundle.get("bundle_hash")

    started_at = time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claude_future = pool.submit(run_claude_auditor, prompt, timeout_s, claude_usage)
        codex_future = pool.submit(run_codex_auditor, prompt, timeout_s, codex_usage)

        try:
            claude_verdict, claude_err = claude_future.result(timeout=timeout_s + 30)
        except FuturesTimeout:
            claude_verdict, claude_err = None, "claude future exceeded outer timeout"
        try:
            codex_verdict, codex_err = codex_future.result(timeout=timeout_s + 30)
        except FuturesTimeout:
            codex_verdict, codex_err = None, "codex future exceeded outer timeout"

    elapsed = round(time.time() - started_at, 2)

    # Emit one observe-only spawn-run record per arm (best-effort, never-raise).
    # This is the ONLY new side effect; the stdout result dict below is
    # byte-for-byte the same shape it was before (#124: do not touch verdict
    # output / evidence bundle). cost/duration/num_turns are null for the Codex
    # arm (non-JSON path) and for any Claude arm whose envelope lacked them.
    _emit_audit_spawn_runs(
        claude_usage=claude_usage,
        codex_usage=codex_usage,
        claude_verdict=claude_verdict,
        claude_err=claude_err,
        codex_verdict=codex_verdict,
        codex_err=codex_err,
        invocation_id=invocation_id,
        cycle_id=cycle_id,
        component_id=component_id,
        bundle_hash=bundle_hash,
        project_root=project_root,
    )

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
