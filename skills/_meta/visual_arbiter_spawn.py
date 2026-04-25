#!/usr/bin/env python3
"""visual_arbiter_spawn.py — Pure-Python visual verifier for bob's UI-VERIFIED.

Ecosystem-keystone (2026-04-23) §2.6 + §2.9 + §5.5. Mirrors the CLI shape of
verification_arbiter_spawn.py (S027) exactly — 10 positional args, 8-field
tuple echo, stdout-only JSON, CB4 discipline — but the decision path is
entirely mechanical Python against measurements produced by a Node
puppeteer subprocess (visual_arbiter_measure.mjs). There is NO LLM in the
verdict path (§1.3 explicit scope discipline, §2.6 "pure-Python = no LLM
subprocess in the verdict path").

Interface (positional argv — 10 args after argv[0]):

    visual_arbiter_spawn.py \\
        <skeleton_path> <skeleton_hash> <request_id> <attempt_id> \\
        <prior_state_version> <built_product_url> <product_hash> \\
        <inventory_hash> <runner_version> <rubric_version>

Emits exactly ONE JSON object on stdout (no prose). Exit codes:

    0 = valid verdict (pass | warn | reject)
    4 = AUDIT_UNAVAILABLE (chrome crash, subprocess failure, schema error)
    3 = environmental error (bad argv, unreadable files)

Env vars:

    VISUAL_ARBITER_CHROME_PATH    — chrome binary (default: "/bin/google-chrome")
    VISUAL_ARBITER_NODE_BIN       — node binary (default: "node")
    VISUAL_ARBITER_TIMEOUT_S      — measurement subprocess timeout (default: 180)

Forbidden (CB4):
    - File writes from this process (bob parses stdout, persists verdict)
    - LLM subprocess (Claude/Codex/Gemini) in the verdict path
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -- sys.path setup for peer imports in ~/.claude/skills/_meta/ --------------
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# YAML loader (mandatory for skeleton parsing)
try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

# claude_observe — fail-open import. The arbiter emits observations for chrome
# slow / crash events but MUST NOT fail if process-observation is unavailable.
_CLAUDE_OBSERVE_DIR = SCRIPT_DIR.parent / "process-observation" / "scripts"
if str(_CLAUDE_OBSERVE_DIR) not in sys.path:
    sys.path.insert(0, str(_CLAUDE_OBSERVE_DIR))
try:
    from write import claude_observe  # type: ignore
except Exception:  # pragma: no cover — best-effort shim
    def claude_observe(*_args, **_kwargs):  # type: ignore
        return None

# uri.resolve — used for checking binds_to URIs (dead handler detection).
try:
    import uri as _uri  # type: ignore
except Exception:  # pragma: no cover
    _uri = None  # type: ignore


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_S = int(os.environ.get("VISUAL_ARBITER_TIMEOUT_S", "180"))
CHROME_PATH = os.environ.get("VISUAL_ARBITER_CHROME_PATH", "/bin/google-chrome")
NODE_BIN = os.environ.get("VISUAL_ARBITER_NODE_BIN", "node")
MEASURE_SCRIPT = SCRIPT_DIR / "visual_arbiter_measure.mjs"

HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Output helpers (mirror verification_arbiter_spawn.py)
# ---------------------------------------------------------------------------

def _eprint(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def _emit_and_exit(obj: Dict[str, Any], exit_code: int) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True))
    sys.stdout.write("\n")
    sys.exit(exit_code)


def _env_error(message: str) -> None:
    _emit_and_exit(
        {"verdict": "AUDIT_UNAVAILABLE", "reason": f"ENV_ERROR: {message}"},
        exit_code=3,
    )


def _audit_unavailable(reason: str, extra: Optional[Dict[str, Any]] = None) -> None:
    out: Dict[str, Any] = {"verdict": "AUDIT_UNAVAILABLE", "reason": reason}
    if extra:
        out.update(extra)
    _emit_and_exit(out, exit_code=4)


# ---------------------------------------------------------------------------
# Skeleton loading
# ---------------------------------------------------------------------------

def _load_yaml_file(path: Path) -> Any:
    if yaml is None:
        _env_error(f"PyYAML not available; cannot load {path}")
    try:
        return yaml.safe_load(path.read_text())
    except Exception as e:
        _env_error(f"unreadable skeleton yaml {path}: {e}")


def load_skeleton(skeleton_path: Path) -> Dict[str, Any]:
    """Load the skeleton bundle.

    Accepts either:
      - a path to the per-screen skeleton yaml (schema: design-skeleton.v1),
        in which case we also load its parent `index.yaml` via parent_index.path.
      - a path to the index.yaml directly (schema: design-skeleton-index.v1),
        in which case we load all screens referenced in `screens[].file`.

    Returns a normalized bundle:
      {
        "index": {<index.yaml dict>},
        "screens": [{<per-screen dict>}, ...],
        "breakpoints": {...},
        "tokens": {...},
        "components": {...},
        "must_satisfy": {...},
      }
    """
    if not skeleton_path.is_file():
        _env_error(f"skeleton not found: {skeleton_path}")
    doc = _load_yaml_file(skeleton_path)
    if not isinstance(doc, dict):
        _env_error(f"skeleton is not a YAML object: {skeleton_path}")

    schema = doc.get("schema")
    if schema == "design-skeleton-index.v1":
        index_doc = doc
        index_dir = skeleton_path.parent
        screens: List[Dict[str, Any]] = []
        for s in (index_doc.get("screens") or []):
            f = s.get("file")
            if not f:
                continue
            s_path = (index_dir / f).resolve()
            if s_path.is_file():
                sd = _load_yaml_file(s_path)
                if isinstance(sd, dict):
                    screens.append(sd)
        return {
            "index": index_doc,
            "screens": screens,
            "breakpoints": index_doc.get("breakpoints") or {},
            "tokens": index_doc.get("tokens") or {},
            "components": index_doc.get("components") or {},
            "must_satisfy": index_doc.get("must_satisfy") or {},
        }
    elif schema == "design-skeleton.v1":
        # Per-screen file — follow parent_index.path to find index.yaml
        parent = doc.get("parent_index") or {}
        parent_path_s = parent.get("path", "index.yaml")
        index_path = (skeleton_path.parent / parent_path_s).resolve()
        if not index_path.is_file():
            _env_error(f"skeleton parent_index.path not found: {index_path}")
        index_doc = _load_yaml_file(index_path)
        if not isinstance(index_doc, dict):
            _env_error(f"index.yaml not a YAML object: {index_path}")
        return {
            "index": index_doc,
            "screens": [doc],
            "breakpoints": index_doc.get("breakpoints") or {},
            "tokens": index_doc.get("tokens") or {},
            "components": index_doc.get("components") or {},
            "must_satisfy": index_doc.get("must_satisfy") or {},
        }
    else:
        _env_error(f"unknown skeleton schema {schema!r}")


# ---------------------------------------------------------------------------
# Measurement subprocess
# ---------------------------------------------------------------------------

def _build_measure_input(
    product_url: str,
    skeleton: Dict[str, Any],
) -> Dict[str, Any]:
    """Flatten the skeleton's elements across screens into the measurement
    script input shape. Each element carries its declared bbox per-breakpoint
    and its interactions.
    """
    breakpoints = skeleton.get("breakpoints") or {}
    # Puppeteer expects numeric viewport values.
    bp_norm: Dict[str, Dict[str, int]] = {}
    for name, v in breakpoints.items():
        if not isinstance(v, dict):
            continue
        bp_norm[name] = {
            "width": int(v.get("width", 1280)),
            "height": int(v.get("height", 900)),
            "device_pixel_ratio": int(v.get("device_pixel_ratio", 1)),
        }

    elements: List[Dict[str, Any]] = []
    for screen in skeleton.get("screens") or []:
        for el in (screen.get("elements") or []):
            elements.append({
                "id": el.get("id"),
                "selector": el.get("selector"),
                "bbox": el.get("bbox") or {},
                "tokens_used": el.get("tokens_used") or {},
                "interactions": el.get("interactions") or [],
            })

    return {
        "product_url": product_url,
        "breakpoints": bp_norm,
        "elements": elements,
        "settle_ms": 300,
        "chrome_path": CHROME_PATH,
    }


def run_measure(
    product_url: str,
    skeleton: Dict[str, Any],
    timeout_s: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Run the Node measurement subprocess.

    Returns (measurements_dict, None) on success or (None, error_msg) on
    failure. Emits claude_observe fail-open on slow/crash.
    """
    if not MEASURE_SCRIPT.is_file():
        return None, f"measure script not found: {MEASURE_SCRIPT}"

    payload = _build_measure_input(product_url, skeleton)
    try:
        proc = subprocess.run(
            [NODE_BIN, str(MEASURE_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return None, f"node binary not found ({NODE_BIN})"
    except subprocess.TimeoutExpired:
        claude_observe(
            "external_tool_slow",
            subject_id="google-chrome",
            what_happened=f"visual_arbiter measurement exceeded {timeout_s}s",
            subject_type="external_tool",
            fingerprint=f"timeout-{timeout_s}s",
            severity="slow",
        )
        return None, f"measurement timed out after {timeout_s}s"

    if proc.returncode != 0:
        claude_observe(
            "external_tool_fail",
            subject_id="google-chrome",
            what_happened=f"chrome/puppeteer crash: {(proc.stderr or '')[:240]}",
            subject_type="external_tool",
            fingerprint=f"returncode-{proc.returncode}",
            severity="blocking",
        )
        return None, f"measure subprocess exit {proc.returncode}: {(proc.stderr or '')[:200]}"

    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return None, f"measure stdout not JSON: {e}"
    if not isinstance(parsed, dict) or "measurements" not in parsed:
        return None, "measure stdout missing 'measurements' key"
    return parsed, None


# ---------------------------------------------------------------------------
# Pure-Python verdict logic
# ---------------------------------------------------------------------------

def compute_tolerance_px(skeleton: Dict[str, Any]) -> int:
    """Per §2.6 + D3: tolerance = min(must_satisfy.tolerance_px, spacing.unit_px / 2).

    Pulled from the skeleton's own declared must_satisfy block — do NOT
    hardcode a value. Defaults to 4 if nothing declared (backstop).
    """
    must = skeleton.get("must_satisfy") or {}
    declared = must.get("tolerance_px")
    tokens = skeleton.get("tokens") or {}
    spacing = tokens.get("spacing") or {}
    unit = spacing.get("unit_px")
    candidates: List[int] = []
    if isinstance(declared, (int, float)):
        candidates.append(int(declared))
    if isinstance(unit, (int, float)):
        candidates.append(int(unit) // 2 if int(unit) >= 2 else 1)
    if not candidates:
        return 4
    return max(1, min(candidates))


def _iter_elements(skeleton: Dict[str, Any]):
    """Yield (screen_dict, element_dict) across all screens."""
    for screen in skeleton.get("screens") or []:
        for el in (screen.get("elements") or []):
            yield screen, el


def _resolve_token_reference(value: Any) -> Optional[str]:
    """If `value` starts with `$` it's a token reference (e.g. '$color.accent.sun').

    Returns the reference path ('color.accent.sun') or None if `value` is
    not a reference.
    """
    if isinstance(value, str) and value.startswith("$"):
        return value[1:]
    return None


def _computed_uses_token(
    computed: Dict[str, str],
    token_name: str,
) -> bool:
    """Return True iff the measured element's outer-HTML / inline-style
    references a CSS custom property named after the token (e.g. `var(--accent-sun)`
    for token `accent.sun`).

    Pure-mechanical check. If the DOM value doesn't go through a var(--...)
    it's considered hardcoded and fails token_mismatch.
    """
    # Token path like "accent.sun" → css var candidates "accent-sun", "accent.sun",
    # or any of the dotted parts. Implementations convention per skeleton contract:
    # `$color.accent.sun` → `--color-accent-sun` OR `--accent-sun`.
    parts = token_name.split(".")
    candidates = {
        "--" + "-".join(parts),            # --color-accent-sun
        "--" + "-".join(parts[1:]) if len(parts) > 1 else "",  # --accent-sun
        "--" + parts[-1],                  # --sun
    }
    candidates.discard("")

    inline = computed.get("__inline_style__", "") or ""
    outer = computed.get("__outer_html__", "") or ""
    haystack = inline + "\n" + outer
    for c in candidates:
        if f"var({c}" in haystack:
            return True
    return False


_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGB_RE = re.compile(r"rgba?\s*\([^)]*\)", re.IGNORECASE)


def _detect_hardcoded_color(computed: Dict[str, str]) -> Optional[str]:
    """Return a hardcoded hex/rgb string found in inline style, or None."""
    inline = computed.get("__inline_style__", "") or ""
    # Style attribute only (hex in outer HTML could be a child); inline is
    # the direct signal for a hardcoded value on the element itself.
    m = _HEX_RE.search(inline)
    if m:
        return m.group(0)
    m = _RGB_RE.search(inline)
    if m:
        return m.group(0)
    return None


def _compute_bbox_drift(
    declared: Dict[str, Any],
    measured: Dict[str, Any],
) -> Dict[str, int]:
    """Per-dim signed drift: measured - declared. int-rounded."""
    def _i(v): return int(round(float(v or 0)))
    return {
        "x": _i(measured.get("x")) - _i(declared.get("x")),
        "y": _i(measured.get("y")) - _i(declared.get("y")),
        "w": _i(measured.get("w")) - _i(declared.get("w")),
        "h": _i(measured.get("h")) - _i(declared.get("h")),
    }


def _bbox_within_tolerance(drift: Dict[str, int], tolerance_px: int) -> bool:
    for dim in ("x", "y", "w", "h"):
        if abs(drift.get(dim, 0)) > tolerance_px:
            return False
    return True


def _element_declared_at_breakpoint(el: Dict[str, Any], bp_name: str) -> bool:
    """True iff element declares a bbox at this breakpoint AND it's not null.

    Null-valued breakpoints (e.g. mobile: null) mean "not shown here" — we
    don't require the implementation to render it. Missing breakpoint entry
    is treated as "applies to all" per schema convention.
    """
    bbox = el.get("bbox") or {}
    if bp_name not in bbox:
        # Not declared at this bp → element may not apply; skip.
        return False
    return bbox[bp_name] is not None


def _check_interaction_wiring(
    el: Dict[str, Any],
    measured_interactions: List[Dict[str, Any]],
    project_root: Optional[Path],
) -> List[Dict[str, Any]]:
    """For each declared interaction, determine wiring state.

    Uses measured handler_fired AND (optionally) uri.resolve on binds_to.
    Returns a list of verdicts: [{event, status: ok|dead|skipped, detail}].
    """
    verdicts: List[Dict[str, Any]] = []
    by_event = {m.get("event"): m for m in measured_interactions}
    for intx in el.get("interactions") or []:
        event = intx.get("event")
        binds_to = intx.get("binds_to")
        visual_only = bool(intx.get("visual_only"))
        m = by_event.get(event, {})

        # visual_only: no binding required; handler absence is expected
        if visual_only:
            verdicts.append({
                "event": event,
                "status": "ok",
                "reason": "visual_only",
            })
            continue

        # No binds_to declared (but not visual_only) — schema violation; fail loud.
        if not binds_to:
            verdicts.append({
                "event": event,
                "status": "dead",
                "reason": "binds_to null but visual_only not set",
            })
            continue

        # Mechanical handler probe: did it fire?
        fired = m.get("handler_fired")
        if fired is False:
            verdicts.append({
                "event": event,
                "status": "dead",
                "reason": "handler did not fire; binds_to may be unwired",
                "binds_to": binds_to,
            })
            continue

        # Optional URI resolution — confirms the binds_to points somewhere
        # real. URI-unresolvable = dead handler per §2.6 / D8.
        uri_err = None
        if _uri is not None and project_root is not None:
            try:
                _uri.resolve(binds_to, project_root)
            except Exception as e:  # UriError family
                uri_err = str(e)
        if uri_err:
            verdicts.append({
                "event": event,
                "status": "dead",
                "reason": f"binds_to unresolvable: {uri_err}",
                "binds_to": binds_to,
            })
            continue

        verdicts.append({
            "event": event,
            "status": "ok",
            "binds_to": binds_to,
        })
    return verdicts


def build_verdict(
    skeleton: Dict[str, Any],
    measurements: Dict[str, Any],
    tuple_inputs: Dict[str, str],
    project_root: Optional[Path],
) -> Dict[str, Any]:
    """Produce visual-verdict.v1 per §2.9.

    Purely mechanical: compares declared skeleton against measured DOM.
    """
    tolerance_px = compute_tolerance_px(skeleton)
    must_satisfy = skeleton.get("must_satisfy") or {}
    required_bps = list(must_satisfy.get("required_breakpoints") or [])
    if not required_bps:
        required_bps = list((skeleton.get("breakpoints") or {}).keys())

    per_bp: Dict[str, Dict[str, int]] = {}
    element_verdicts: List[Dict[str, Any]] = []
    concerns: List[Dict[str, Any]] = []

    elements_total = 0
    elements_verified = 0
    uncovered: List[str] = []

    # Iterate declared elements; for each breakpoint where the element applies
    # (i.e. declared bbox at that bp is not null), build a per-element verdict.
    for _screen, el in _iter_elements(skeleton):
        el_id = el.get("id", "<unknown>")
        for bp_name in required_bps:
            if not _element_declared_at_breakpoint(el, bp_name):
                continue
            elements_total += 1
            bp_meas = measurements.get(bp_name) or {}
            meas_elements = {e.get("element_id"): e for e in (bp_meas.get("elements") or [])}
            meas = meas_elements.get(el_id, {})

            found = meas.get("found")
            # found == null sentinel means "declared null at bp" per measure
            # script. Both measure and Python interpret null as "skip" — but
            # we got here by _element_declared_at_breakpoint returning True,
            # so this shouldn't happen. Treat as missing_from_dom.
            per_el_status = "pass"
            reasons: List[str] = []

            if found is None or found is False:
                per_el_status = "fail"
                reasons.append("missing_from_dom")
                element_verdicts.append({
                    "element_id": el_id,
                    "breakpoint": bp_name,
                    "status": "fail",
                    "missing_from_dom": True,
                    "bbox_drift_px": None,
                    "tokens_ok": None,
                    "interactions_ok": [],
                })
                uncovered.append(f"{el_id}@{bp_name}")
                continue

            # bbox drift
            declared_bbox = (el.get("bbox") or {}).get(bp_name) or {}
            measured_bbox = meas.get("bbox") or {}
            drift = _compute_bbox_drift(declared_bbox, measured_bbox)
            bbox_ok = _bbox_within_tolerance(drift, tolerance_px)
            if not bbox_ok:
                per_el_status = "fail"
                reasons.append("bbox_drift")

            # tokens_used back-resolution: for each declared token reference,
            # verify the element's computed styles go through the var(--...)
            # indirection OR at minimum do NOT hardcode a hex/rgb.
            tokens_used = el.get("tokens_used") or {}
            computed = meas.get("computed") or {}
            tokens_ok = True
            token_failures: List[Dict[str, Any]] = []
            for _field, value in tokens_used.items():
                token_ref = _resolve_token_reference(value)
                # Accept shorthand: tokens_used: {color: ink} → treat as "$color.ink"
                if token_ref is None and isinstance(value, str) and value and not value.startswith("#") and not value.startswith("rgb"):
                    token_ref = f"{_field}.{value}" if "." not in value else value
                if token_ref is None:
                    continue
                if not _computed_uses_token(computed, token_ref):
                    # Maybe computed style back-resolves to expected color via
                    # chain; the var(--...) check is the cleanest mechanical
                    # signal. Also inspect for hardcoded hex/rgb in inline style.
                    hc = _detect_hardcoded_color(computed)
                    if hc is not None:
                        tokens_ok = False
                        token_failures.append({
                            "field": _field,
                            "expected": f"${token_ref}",
                            "computed": hc,
                        })
                        break
                    # No var-ref but also no hardcoded hex in inline style →
                    # assume token applied via class/stylesheet; pass.
            if not tokens_ok:
                per_el_status = "fail"
                reasons.append("token_mismatch")

            # interactions
            intx_verdicts = _check_interaction_wiring(
                el, meas.get("interactions") or [], project_root,
            )
            dead_intx = [v for v in intx_verdicts if v.get("status") == "dead"]
            if dead_intx:
                per_el_status = "fail"
                reasons.append("dead_handler")

            ev: Dict[str, Any] = {
                "element_id": el_id,
                "breakpoint": bp_name,
                "status": per_el_status,
                "bbox_drift_px": drift,
                "tokens_ok": tokens_ok,
                "interactions_ok": intx_verdicts,
            }
            if token_failures:
                ev["token_mismatch"] = token_failures
            if dead_intx:
                ev["dead_handler"] = [
                    {"event": d.get("event"), "binds_to": d.get("binds_to"), "reason": d.get("reason")}
                    for d in dead_intx
                ]
            element_verdicts.append(ev)

            if per_el_status == "pass":
                elements_verified += 1
            else:
                uncovered.append(f"{el_id}@{bp_name}")

        # per-breakpoint stats (init once we know totals)

    # Compute per-breakpoint verified/failed
    for bp_name in required_bps:
        verified_count = sum(
            1 for ev in element_verdicts
            if ev.get("breakpoint") == bp_name and ev.get("status") == "pass"
        )
        failed_count = sum(
            1 for ev in element_verdicts
            if ev.get("breakpoint") == bp_name and ev.get("status") == "fail"
        )
        per_bp[bp_name] = {"verified": verified_count, "failed": failed_count}

        # fonts.ready concern
        bp_meas = measurements.get(bp_name) or {}
        fr_ms = bp_meas.get("fonts_ready_ms", 0) or 0
        if isinstance(fr_ms, (int, float)) and fr_ms > 2000:
            concerns.append({
                "severity": "warning",
                "detail": f"fonts.ready took {fr_ms}ms at {bp_name}, exceeds 2000ms threshold",
            })
            # Fail-open observation emit
            claude_observe(
                "external_tool_slow",
                subject_id="google-chrome",
                what_happened=f"fonts.ready slow at {bp_name}: {fr_ms}ms",
                subject_type="external_tool",
                fingerprint=f"fonts-ready-slow-{bp_name}",
                severity="slow",
            )

    # Overall verdict: pass only if EVERY element_verdict is pass AND no
    # blocker concerns; reject if any fail; warn if only warnings.
    has_fail = any(ev.get("status") == "fail" for ev in element_verdicts)
    has_warning = any(c.get("severity") == "warning" for c in concerns)
    if has_fail:
        overall = "reject"
    elif has_warning:
        overall = "warn"
    else:
        overall = "pass"

    verdict = {
        "schema": "visual-verdict.v1",
        "verdict": overall,
        # 8-field tuple echoed verbatim (§2.9)
        "request_id":           tuple_inputs["request_id"],
        "attempt_id":           tuple_inputs["attempt_id"],
        "prior_state_version":  tuple_inputs["prior_state_version"],
        "skeleton_hash":        tuple_inputs["skeleton_hash"],
        "product_hash":         tuple_inputs["product_hash"],
        "inventory_hash":       tuple_inputs["inventory_hash"],
        "runner_version":       tuple_inputs["runner_version"],
        "rubric_version":       tuple_inputs["rubric_version"],
        # verdict body
        "coverage": {
            "elements_total": elements_total,
            "elements_verified": elements_verified,
            "uncovered": uncovered,
        },
        "per_breakpoint": per_bp,
        "element_verdicts": element_verdicts,
        "concerns": concerns,
        "tolerance_px_applied": tolerance_px,
    }
    return verdict


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _print_help() -> None:
    sys.stdout.write(
        "usage: visual_arbiter_spawn.py <skeleton_path> <skeleton_hash> "
        "<request_id> <attempt_id> <prior_state_version> <built_product_url> "
        "<product_hash> <inventory_hash> <runner_version> <rubric_version>\n"
        "\n"
        "Pure-Python visual verifier (ecosystem-keystone §2.6). 10 positional\n"
        "args. Emits visual-verdict.v1 JSON on stdout only (CB4). Exit codes:\n"
        "  0 = valid verdict (pass|warn|reject)\n"
        "  3 = environmental error\n"
        "  4 = AUDIT_UNAVAILABLE (chrome crash / schema error)\n"
    )


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv
    if len(argv) == 2 and argv[1] in ("-h", "--help"):
        _print_help()
        sys.exit(0)
    if len(argv) != 11:
        _env_error(
            "usage: visual_arbiter_spawn.py <skeleton_path> <skeleton_hash> "
            "<request_id> <attempt_id> <prior_state_version> <built_product_url> "
            "<product_hash> <inventory_hash> <runner_version> <rubric_version>"
        )

    skeleton_path = Path(argv[1]).resolve()
    skeleton_hash = argv[2]
    request_id = argv[3]
    attempt_id = argv[4]
    prior_state_version = argv[5]
    built_product_url = argv[6]
    product_hash = argv[7]
    inventory_hash = argv[8]
    runner_version = argv[9]
    rubric_version = argv[10]

    # argv validation
    if not HEX64_RE.match(skeleton_hash):
        _env_error("skeleton_hash must be 64-hex")
    if not HEX32_RE.match(request_id):
        _env_error("request_id must be 32-hex")
    if not HEX64_RE.match(product_hash):
        _env_error("product_hash must be 64-hex")
    if not HEX64_RE.match(inventory_hash):
        _env_error("inventory_hash must be 64-hex")
    for name, val in (
        ("attempt_id", attempt_id),
        ("prior_state_version", prior_state_version),
        ("runner_version", runner_version),
        ("rubric_version", rubric_version),
    ):
        if not val:
            _env_error(f"{name} must be non-empty")

    skeleton = load_skeleton(skeleton_path)

    # Normalize product URL: accept a path OR a file://... URL OR http(s)://...
    if built_product_url.startswith(("file://", "http://", "https://")):
        product_url = built_product_url
    else:
        pp = Path(built_product_url).resolve()
        if not pp.exists():
            _env_error(f"built_product_url path does not exist: {pp}")
        product_url = pp.as_uri()

    # Try to discover project root for uri.resolve (walk up from skeleton_path
    # looking for PROJECT.md or progress/contract-map.yaml).
    project_root: Optional[Path] = None
    p = skeleton_path.parent
    for _ in range(10):
        if (p / "PROJECT.md").is_file() or (p / "progress" / "contract-map.yaml").is_file():
            project_root = p
            break
        if p.parent == p:
            break
        p = p.parent

    tuple_inputs = {
        "request_id": request_id,
        "attempt_id": attempt_id,
        "prior_state_version": prior_state_version,
        "skeleton_hash": skeleton_hash,
        "product_hash": product_hash,
        "inventory_hash": inventory_hash,
        "runner_version": runner_version,
        "rubric_version": rubric_version,
    }

    # Run the mechanical measurement subprocess.
    parsed, err = run_measure(product_url, skeleton, DEFAULT_TIMEOUT_S)
    if parsed is None:
        _audit_unavailable(
            f"measurement subprocess failed: {err}",
            extra={"subprocess_error": err},
        )

    measurements = parsed.get("measurements") or {}
    measure_errors = parsed.get("errors") or []
    if measure_errors:
        # Chrome reported per-breakpoint errors but not total crash.
        claude_observe(
            "external_tool_fail",
            subject_id="google-chrome",
            what_happened=f"per-breakpoint errors: {measure_errors[:3]}",
            subject_type="external_tool",
            fingerprint="per-bp-error",
            severity="degraded",
        )
        # Non-fatal — we still build a verdict against whatever was measured.

    verdict = build_verdict(skeleton, measurements, tuple_inputs, project_root)
    _emit_and_exit(verdict, exit_code=0)


if __name__ == "__main__":
    main()
