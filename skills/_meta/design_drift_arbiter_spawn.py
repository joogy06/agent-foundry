#!/usr/bin/env python3
"""design_drift_arbiter_spawn.py — Pure-Python micro-drift auto-approver.

Phase 3 / WP-10 of the ecosystem-keystone design
(docs/plans/2026-04-23-ecosystem-keystone-design.md §2.7, §6.1 D3).

Runs AFTER visual-arbiter returns `reject`. Examines per-element failures:
micro-drift (bbox within profile tolerance, token swap within same family) is
auto-approved as a patch-version bump; anything else escalates to the user.

NO LLM SUBPROCESS. NO BROWSER. Pure algorithmic comparison — the verdict is a
deterministic function of the input verdict + profile + declared tokens
(reproducibility invariant, matches hash-chain semantics).

CLI shape mirrors `verification_arbiter_spawn.py` (10-positional-arg) for
consistency: bob treats drift-arbiter as a drop-in follow-on spawn.

Invocation:

    design_drift_arbiter_spawn.py \\
        <verdict_path> <verdict_hash> <request_id> <attempt_id> \\
        <prior_state_version> <tokens_path> <skeleton_hash> \\
        <inventory_hash> <runner_version> <rubric_version>

`--verdict-path PATH` / `--tokens-path PATH` / `--profile NAME` are also
accepted as overrides. `--help` prints usage and exits 0.

Output: exactly ONE JSON object on stdout:

    {
      "status": "auto_approved" | "escalate_to_user",
      "tuple_echo": { ... 8 fields ... },
      "classification_per_element": [
        {"element_id": "...", "breakpoint": "...", "failures": [...],
         "classification": "micro-drift" | "material",
         "reasons": ["..."]}
      ],
      "profile_used": "strict" | "lenient" | "...",
      "rubric_version": "..."
    }

Exit codes:
    0 = valid verdict emitted
    3 = environmental / usage error (bad args, unreadable inputs)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "strict":  {"bbox_tolerance_px": 2, "token_swap_allowed": False},
    "lenient": {
        "bbox_tolerance_px": 8,
        "token_swap_allowed": True,
        "token_swap_same_family_only": True,
    },
}

# Failure kinds visual-arbiter may emit (design §2.6).
# `missing_from_dom`, `dead_handler`, `interaction_fail` are NEVER micro-drift.
NEVER_MICRO_DRIFT = frozenset({
    "missing_from_dom",
    "dead_handler",
    "interaction_fail",
})
DRIFT_CANDIDATE = frozenset({"bbox_drift", "token_mismatch"})


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def eprint(msg: str) -> None:
    sys.stderr.write(msg + "\n")


def emit_and_exit(obj: Dict[str, Any], exit_code: int) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True))
    sys.stdout.write("\n")
    sys.exit(exit_code)


def env_error(message: str) -> None:
    emit_and_exit(
        {"status": "env_error", "reason": message},
        exit_code=3,
    )


def _safe_observe(category: str, fingerprint: str, detail: str) -> None:
    """Fail-open claude_observe (skill_bug on profile/config malformation).

    Per design §2.7 + contract-map.yaml component drift-arbiter, the arbiter
    emits `skill_bug` when profile config is malformed — but never raises.
    """
    try:
        # Defer import so module can be tested without process-observation
        script_dir = Path(__file__).resolve().parent
        sys.path.insert(0, str(script_dir.parent / "process-observation" / "scripts"))
        from write import claude_observe  # type: ignore
        claude_observe(
            category=category,
            subject={"type": "skill", "id": "design-drift-arbiter"},
            what_happened=detail,
            fingerprint=fingerprint,
        )
    except Exception:
        pass  # fail-open — never block verdict emission


# ---------------------------------------------------------------------------
# ΔE2000 — CIE DE2000 color difference (inline, no external dep)
# Reference: Sharma, Wu, Dalal 2005; http://zschuessler.github.io/DeltaE/
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_str: str) -> Tuple[float, float, float]:
    s = hex_str.lstrip("#").strip()
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"bad hex color: {hex_str!r}")
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return r, g, b


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _rgb_to_xyz(r: float, g: float, b: float) -> Tuple[float, float, float]:
    r_l = _srgb_to_linear(r)
    g_l = _srgb_to_linear(g)
    b_l = _srgb_to_linear(b)
    # sRGB D65
    x = r_l * 0.4124564 + g_l * 0.3575761 + b_l * 0.1804375
    y = r_l * 0.2126729 + g_l * 0.7151522 + b_l * 0.0721750
    z = r_l * 0.0193339 + g_l * 0.1191920 + b_l * 0.9503041
    return x * 100.0, y * 100.0, z * 100.0


def _xyz_to_lab(x: float, y: float, z: float) -> Tuple[float, float, float]:
    # D65 reference white
    xn, yn, zn = 95.047, 100.000, 108.883
    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > 0.008856 else (7.787 * t + 16.0 / 116.0)
    fx = f(x / xn)
    fy = f(y / yn)
    fz = f(z / zn)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return L, a, b


def hex_to_lab(hex_str: str) -> Tuple[float, float, float]:
    r, g, b = _hex_to_rgb(hex_str)
    x, y, z = _rgb_to_xyz(r, g, b)
    return _xyz_to_lab(x, y, z)


def delta_e_2000(lab1: Tuple[float, float, float],
                 lab2: Tuple[float, float, float]) -> float:
    """CIE ΔE2000 — Sharma/Wu/Dalal 2005 canonical formulation."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2

    # Step 1: C1, C2
    C1 = math.sqrt(a1 * a1 + b1 * b1)
    C2 = math.sqrt(a2 * a2 + b2 * b2)
    C_bar = (C1 + C2) / 2.0

    G = 0.5 * (1.0 - math.sqrt((C_bar ** 7) / (C_bar ** 7 + 25 ** 7)))
    a1_p = (1.0 + G) * a1
    a2_p = (1.0 + G) * a2

    C1_p = math.sqrt(a1_p * a1_p + b1 * b1)
    C2_p = math.sqrt(a2_p * a2_p + b2 * b2)

    def _h(a_p: float, b: float) -> float:
        if a_p == 0 and b == 0:
            return 0.0
        h = math.degrees(math.atan2(b, a_p))
        return h + 360.0 if h < 0 else h

    h1_p = _h(a1_p, b1)
    h2_p = _h(a2_p, b2)

    # Step 2
    dL_p = L2 - L1
    dC_p = C2_p - C1_p

    if C1_p * C2_p == 0:
        dh_p = 0.0
    else:
        diff = h2_p - h1_p
        if diff > 180:
            diff -= 360
        elif diff < -180:
            diff += 360
        dh_p = diff

    dH_p = 2.0 * math.sqrt(C1_p * C2_p) * math.sin(math.radians(dh_p / 2.0))

    # Step 3
    L_bar_p = (L1 + L2) / 2.0
    C_bar_p = (C1_p + C2_p) / 2.0

    if C1_p * C2_p == 0:
        h_bar_p = h1_p + h2_p
    else:
        if abs(h1_p - h2_p) <= 180:
            h_bar_p = (h1_p + h2_p) / 2.0
        elif h1_p + h2_p < 360:
            h_bar_p = (h1_p + h2_p + 360) / 2.0
        else:
            h_bar_p = (h1_p + h2_p - 360) / 2.0

    T = (1.0
         - 0.17 * math.cos(math.radians(h_bar_p - 30))
         + 0.24 * math.cos(math.radians(2 * h_bar_p))
         + 0.32 * math.cos(math.radians(3 * h_bar_p + 6))
         - 0.20 * math.cos(math.radians(4 * h_bar_p - 63)))

    dTheta = 30.0 * math.exp(-(((h_bar_p - 275.0) / 25.0) ** 2))
    R_C = 2.0 * math.sqrt((C_bar_p ** 7) / (C_bar_p ** 7 + 25 ** 7))
    S_L = 1.0 + ((0.015 * ((L_bar_p - 50) ** 2)) /
                 math.sqrt(20 + (L_bar_p - 50) ** 2))
    S_C = 1.0 + 0.045 * C_bar_p
    S_H = 1.0 + 0.015 * C_bar_p * T
    R_T = -math.sin(math.radians(2 * dTheta)) * R_C

    kL = kC = kH = 1.0
    dE = math.sqrt(
        (dL_p / (kL * S_L)) ** 2 +
        (dC_p / (kC * S_C)) ** 2 +
        (dH_p / (kH * S_H)) ** 2 +
        R_T * (dC_p / (kC * S_C)) * (dH_p / (kH * S_H))
    )
    return dE


# ---------------------------------------------------------------------------
# Same-family classifiers (mechanical, per §2.7)
# ---------------------------------------------------------------------------


def _color_namespace(token_ref: str) -> Optional[str]:
    """Extract the prefix of a token reference.

    `accent.sun` -> 'accent'
    `$color.accent.sun` -> 'accent'
    `colors.primary` -> 'colors'
    `#ffd23f` -> None (not a token reference, it's a hardcoded hex)
    """
    if not isinstance(token_ref, str) or not token_ref:
        return None
    s = token_ref.strip().lstrip("$")
    if s.startswith("#"):
        return None
    # strip a "color." or "colors." leading segment if present
    for pfx in ("color.", "colors."):
        if s.startswith(pfx):
            s = s[len(pfx):]
            break
    dot = s.find(".")
    if dot < 0:
        return s
    return s[:dot]


def color_same_family(
    expected_token: str,
    computed_value: str,
    tokens: Dict[str, Any],
) -> Tuple[bool, str]:
    """Return (is_same_family, reason).

    Rules (§2.7):
      - Same token namespace prefix (both `accent.*`, both `colors.*`).
      - ΔE2000 ≤ 3 in CIELAB.
      - Same lightness bucket (L* within 10).

    `expected_token` is a token reference like `accent.sun` (or `$color.accent.sun`).
    `computed_value` is a hardcoded hex like `#ffd180`, OR another token ref.
    """
    ns_expected = _color_namespace(expected_token)
    if ns_expected is None:
        return False, f"expected-token {expected_token!r} has no namespace"

    # Resolve expected token to hex via the tokens map
    color_map = tokens.get("color") or tokens.get("colors") or {}
    expected_hex = _resolve_color_token(expected_token, color_map)
    if expected_hex is None:
        return False, f"expected token {expected_token!r} not in tokens.color"

    if not isinstance(computed_value, str):
        return False, "computed value not a string"

    # If computed is a token reference, enforce namespace equality up-front
    if not computed_value.strip().startswith("#"):
        ns_computed = _color_namespace(computed_value)
        if ns_computed != ns_expected:
            return False, (f"namespace mismatch: expected {ns_expected!r}, "
                           f"computed {ns_computed!r}")
        computed_hex = _resolve_color_token(computed_value, color_map)
        if computed_hex is None:
            return False, f"computed token {computed_value!r} not in tokens.color"
    else:
        computed_hex = computed_value
        # Hardcoded hex has no namespace; we cannot prove same-family.
        # Policy: hardcoded hex is NEVER same-family (D2 strict token binding).
        # Exception: if the hardcoded hex equals the expected token's hex, it's
        # a definitional match (not a drift at all), but the caller wouldn't
        # have raised token_mismatch in that case.
        if computed_hex.lower() != expected_hex.lower():
            return False, (
                f"hardcoded hex {computed_hex!r} is not a token reference; "
                "cannot establish same-family for non-token value (D2)"
            )

    try:
        lab_e = hex_to_lab(expected_hex)
        lab_c = hex_to_lab(computed_hex)
    except ValueError as e:
        return False, f"hex parse error: {e}"

    dE = delta_e_2000(lab_e, lab_c)
    if dE > 3.0:
        return False, f"ΔE2000={dE:.3f} exceeds 3.0"

    dL = abs(lab_e[0] - lab_c[0])
    if dL > 10.0:
        return False, f"ΔL*={dL:.3f} exceeds lightness bucket 10"

    return True, f"ΔE2000={dE:.3f}, ΔL*={dL:.3f}, same namespace={ns_expected!r}"


def _resolve_color_token(ref: str, color_map: Dict[str, Any]) -> Optional[str]:
    """Look up a color token ref (e.g. 'accent.sun') in the tokens.color map."""
    if not isinstance(ref, str):
        return None
    s = ref.strip().lstrip("$")
    for pfx in ("color.", "colors."):
        if s.startswith(pfx):
            s = s[len(pfx):]
            break
    # Direct flat match (e.g. "accent.sun" as literal key)
    if s in color_map and isinstance(color_map[s], str):
        return color_map[s]
    # Nested match: split on "." and walk
    parts = s.split(".")
    cur: Any = color_map
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur if isinstance(cur, str) else None


def typography_same_family(
    expected: Dict[str, Any],
    computed: Dict[str, Any],
) -> Tuple[bool, str]:
    """Same family name, weight step ±1 (400->600 ok, 400->900 no), size ≤10%."""
    if not isinstance(expected, dict) or not isinstance(computed, dict):
        return False, "typography values must be dicts with family/weight/size"

    fe = expected.get("family")
    fc = computed.get("family")
    if fe != fc:
        return False, f"family mismatch: expected {fe!r}, computed {fc!r}"

    we = expected.get("weight")
    wc = computed.get("weight")
    if not isinstance(we, int) or not isinstance(wc, int):
        return False, "weight must be integer"
    # Standard CSS weights: 100, 200, ..., 900. "step" = 100 units.
    step = abs(wc - we) // 100
    if abs(wc - we) % 100 != 0:
        return False, f"weight {wc} not a canonical CSS step"
    if step > 1:
        return False, f"weight step ±{step} exceeds 1"

    se = expected.get("size_px")
    sc = computed.get("size_px")
    if se is not None and sc is not None:
        try:
            se_f = float(se)
            sc_f = float(sc)
        except (TypeError, ValueError):
            return False, "size_px must be numeric"
        if se_f <= 0:
            return False, "expected size_px must be > 0"
        drift = abs(sc_f - se_f) / se_f
        if drift > 0.10:
            return False, f"size drift {drift*100:.1f}% exceeds 10%"

    return True, "family+weight+size within tolerance"


def spacing_same_family(
    expected_token: str,
    computed_token: str,
    tokens: Dict[str, Any],
) -> Tuple[bool, str]:
    """scale[] array index ±1 (spacing.8 -> spacing.12 ok; spacing.8 -> spacing.32 no).

    Token refs look like `spacing.8` or `$spacing.scale.8` — numeric suffix is
    the value in the scale array, NOT the index. We look them up in the scale.
    """
    scale = (tokens.get("spacing") or {}).get("scale")
    if not isinstance(scale, list) or not scale:
        return False, "tokens.spacing.scale missing or not a list"

    def _extract_value(ref: str) -> Optional[int]:
        if not isinstance(ref, str):
            return None
        s = ref.strip().lstrip("$")
        for pfx in ("spacing.scale.", "spacing."):
            if s.startswith(pfx):
                s = s[len(pfx):]
                break
        try:
            return int(s)
        except ValueError:
            return None

    ve = _extract_value(expected_token)
    vc = _extract_value(computed_token)
    if ve is None or vc is None:
        return False, f"cannot parse spacing tokens {expected_token!r}/{computed_token!r}"

    try:
        ie = scale.index(ve)
        ic = scale.index(vc)
    except ValueError:
        return False, f"spacing values {ve}/{vc} not in scale {scale}"

    step = abs(ie - ic)
    if step > 1:
        return False, f"scale index step ±{step} exceeds 1"

    return True, f"scale index step ±{step}"


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------


def load_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.is_file():
        return {}
    try:
        data = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as e:
        _safe_observe(
            "skill_bug",
            "config-yaml-parse-error",
            f"_meta/config.yaml unparseable: {e}",
        )
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def resolve_profile(
    cfg: Dict[str, Any],
    project_root: Optional[Path],
    override_profile: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    """Return (profile_name, profile_dict).

    Order (explicit user choice wins):
      1. --profile override (CLI)
      2. cfg['design_drift_arbiter']['active_profile']
      3. 'strict' default
    """
    section = cfg.get("design_drift_arbiter") or {}
    profiles = {**DEFAULT_PROFILES, **(section.get("profiles") or {})}
    # Normalize: profile values may themselves be dicts referencing another path
    active = override_profile or section.get("active_profile") or "strict"

    # project_override may point to a per-project YAML file
    if active == "project_override" and project_root is not None:
        po = profiles.get("project_override") or {}
        rel = po.get("path") or ".design-ledger/drift-profile.yaml"
        po_path = (project_root / rel).resolve()
        if po_path.is_file():
            try:
                po_data = yaml.safe_load(po_path.read_text()) or {}
                if isinstance(po_data, dict):
                    return "project_override", {
                        **DEFAULT_PROFILES["strict"],
                        **po_data,
                    }
            except yaml.YAMLError as e:
                _safe_observe(
                    "skill_bug",
                    "project-profile-parse-error",
                    f"project drift-profile.yaml unparseable: {e}",
                )
        # Fall through: malformed/missing override → strict
        return "strict", DEFAULT_PROFILES["strict"]

    prof = profiles.get(active)
    if not isinstance(prof, dict):
        _safe_observe(
            "skill_bug",
            f"profile-missing-{active}",
            f"active profile {active!r} not found; falling back to strict",
        )
        return "strict", DEFAULT_PROFILES["strict"]
    # Merge on top of strict defaults to fill missing keys
    merged = {**DEFAULT_PROFILES["strict"], **prof}
    return active, merged


# ---------------------------------------------------------------------------
# Classification engine
# ---------------------------------------------------------------------------


def classify_element(
    ev: Dict[str, Any],
    profile: Dict[str, Any],
    tokens: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify one element's failures.

    Returns:
      {
        "element_id": str,
        "breakpoint": str,
        "failures": [orig...],
        "classification": "micro-drift" | "material",
        "reasons": [str...]
      }
    """
    element_id = ev.get("element_id", "<unknown>")
    breakpoint = ev.get("breakpoint", "<unknown>")
    failures = ev.get("failures") or []
    # For backward compat, also accept the flat fields from visual-verdict.v1
    if not failures:
        inferred: List[Dict[str, Any]] = []
        bbox = ev.get("bbox_drift_px")
        if isinstance(bbox, dict) and any(abs(bbox.get(k, 0) or 0) > 0
                                          for k in ("x", "y", "w", "h")):
            inferred.append({"kind": "bbox_drift", "bbox_drift_px": bbox})
        # token_mismatch as flat field
        tm = ev.get("token_mismatch")
        if isinstance(tm, dict):
            inferred.append({"kind": "token_mismatch", **tm})
        if ev.get("missing_from_dom"):
            inferred.append({"kind": "missing_from_dom"})
        if ev.get("dead_handler"):
            inferred.append({"kind": "dead_handler", **(ev.get("dead_handler") if isinstance(ev.get("dead_handler"), dict) else {})})
        failures = inferred

    reasons: List[str] = []
    all_micro = True if failures else False

    for fail in failures:
        kind = fail.get("kind") if isinstance(fail, dict) else None
        if not kind:
            all_micro = False
            reasons.append(f"failure has no 'kind' field: {fail!r}")
            continue
        if kind in NEVER_MICRO_DRIFT:
            all_micro = False
            reasons.append(f"{kind} can never be auto-approved")
            continue
        if kind not in DRIFT_CANDIDATE:
            all_micro = False
            reasons.append(f"unknown failure kind {kind!r}")
            continue

        if kind == "bbox_drift":
            bbox = fail.get("bbox_drift_px") or fail.get("bbox") or {}
            tol = profile.get("bbox_tolerance_px", 2)
            dims_ok = True
            worst = 0
            for axis in ("x", "y", "w", "h"):
                v = abs(int(bbox.get(axis, 0) or 0))
                if v > worst:
                    worst = v
                if v > tol:
                    dims_ok = False
            if dims_ok:
                reasons.append(
                    f"bbox_drift worst={worst}px ≤ tolerance {tol}px → micro"
                )
            else:
                all_micro = False
                reasons.append(
                    f"bbox_drift worst={worst}px exceeds tolerance {tol}px → material"
                )
            continue

        if kind == "token_mismatch":
            if not profile.get("token_swap_allowed", False):
                all_micro = False
                reasons.append(
                    "token_mismatch not auto-approvable under this profile "
                    "(token_swap_allowed=false)"
                )
                continue
            # Profile permits swaps; require same_family_only check
            field = fail.get("field", "")  # e.g. "color", "typography.family", "spacing"
            expected = fail.get("expected")
            computed = fail.get("computed")
            family_kind = _field_to_family_kind(field)
            if family_kind == "color":
                ok, why = color_same_family(expected, computed, tokens)
            elif family_kind == "typography":
                ok, why = typography_same_family(expected, computed)
            elif family_kind == "spacing":
                ok, why = spacing_same_family(expected, computed, tokens)
            else:
                ok = False
                why = f"unknown token family for field {field!r}"
            if ok:
                reasons.append(f"token_mismatch {field!r} same-family: {why}")
            else:
                all_micro = False
                reasons.append(
                    f"token_mismatch {field!r} NOT same-family: {why}"
                )
            continue

    if not failures:
        # No failures to analyze (shouldn't happen on a reject, but guard).
        all_micro = False
        reasons.append("no failures listed — cannot classify")

    return {
        "element_id": element_id,
        "breakpoint": breakpoint,
        "failures": failures,
        "classification": "micro-drift" if all_micro else "material",
        "reasons": reasons,
    }


def _field_to_family_kind(field: str) -> str:
    """Map a token_mismatch field name to its family classifier."""
    if not isinstance(field, str):
        return "unknown"
    f = field.lower()
    if f.startswith("color") or f.startswith("background") or f.startswith("border-color") or f in ("fill", "stroke"):
        return "color"
    if f.startswith("typography") or f.startswith("font") or "family" in f or "weight" in f:
        return "typography"
    if f.startswith("spacing") or f.startswith("padding") or f.startswith("margin") or f.startswith("gap"):
        return "spacing"
    return "unknown"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="design_drift_arbiter_spawn.py",
        description=(
            "Pure-Python micro-drift auto-approver. Consumes a REJECTED "
            "visual-verdict and returns status=auto_approved (micro-drift "
            "within profile) or status=escalate_to_user (material)."
        ),
        add_help=True,
    )
    p.add_argument("verdict_path", nargs="?", help="Path to visual-verdict JSON")
    p.add_argument("verdict_hash", nargs="?", help="64-hex content hash of the verdict file")
    p.add_argument("request_id", nargs="?", help="32-hex request_id (echoed)")
    p.add_argument("attempt_id", nargs="?", help="attempt_id (echoed)")
    p.add_argument("prior_state_version", nargs="?", help="prior_state_version (echoed)")
    p.add_argument("tokens_path", nargs="?", help="Path to skeleton index.yaml (tokens)")
    p.add_argument("skeleton_hash", nargs="?", help="64-hex skeleton hash (echoed)")
    p.add_argument("inventory_hash", nargs="?", help="64-hex inventory_hash (echoed)")
    p.add_argument("runner_version", nargs="?", help="runner_version (echoed)")
    p.add_argument("rubric_version", nargs="?", help="rubric_version (echoed)")
    p.add_argument("--verdict-path", dest="opt_verdict_path", default=None)
    p.add_argument("--tokens-path", dest="opt_tokens_path", default=None)
    p.add_argument("--profile", dest="opt_profile", default=None,
                   help="Override active profile (strict|lenient|project_override|...)")
    p.add_argument("--config-path", dest="opt_config_path", default=None,
                   help="Override _meta/config.yaml path (for tests)")
    p.add_argument("--project-root", dest="opt_project_root", default=None,
                   help="Project root (for project_override profile)")
    return p


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)

    verdict_path_str = args.opt_verdict_path or args.verdict_path
    tokens_path_str = args.opt_tokens_path or args.tokens_path

    if not verdict_path_str:
        env_error("usage: design_drift_arbiter_spawn.py <verdict_path> ... (see --help)")
    verdict_path = Path(verdict_path_str).resolve()
    if not verdict_path.is_file():
        env_error(f"verdict not found: {verdict_path}")
    try:
        verdict = json.loads(verdict_path.read_text())
    except json.JSONDecodeError as e:
        env_error(f"verdict is not valid JSON: {e}")

    tokens: Dict[str, Any] = {}
    if tokens_path_str:
        tokens_path = Path(tokens_path_str).resolve()
        if tokens_path.is_file():
            try:
                td = yaml.safe_load(tokens_path.read_text()) or {}
                if isinstance(td, dict):
                    tokens = td.get("tokens") or td  # accept both shapes
            except yaml.YAMLError as e:
                env_error(f"tokens file not parseable: {e}")

    # Argv-positional hash/tuple sanity (env errors are non-fatal with
    # placeholder values when called via --verdict-path test mode)
    request_id = args.request_id or (verdict.get("request_id") or "")
    attempt_id = args.attempt_id or (verdict.get("attempt_id") or "")
    prior_state_version = args.prior_state_version or (verdict.get("prior_state_version") or "")
    skeleton_hash = args.skeleton_hash or (verdict.get("skeleton_hash") or "")
    inventory_hash = args.inventory_hash or (verdict.get("inventory_hash") or "")
    runner_version = args.runner_version or (verdict.get("runner_version") or "")
    rubric_version = args.rubric_version or (verdict.get("rubric_version") or "drift-arbiter-v1.0.0")
    impl_hash = verdict.get("impl_hash") or verdict.get("product_hash") or ""

    # Config & profile
    cfg_path = (
        Path(args.opt_config_path).resolve()
        if args.opt_config_path
        else Path(__file__).resolve().parent / "config.yaml"
    )
    cfg = load_config(cfg_path)

    project_root = (
        Path(args.opt_project_root).resolve()
        if args.opt_project_root
        else None
    )

    profile_name, profile = resolve_profile(cfg, project_root, args.opt_profile)

    # Element verdicts — accept both `element_verdicts` (design §2.9) and
    # `per_element_failures` (shorthand).
    elements = verdict.get("element_verdicts") or verdict.get("per_element_failures") or []
    if not isinstance(elements, list):
        elements = []

    classifications: List[Dict[str, Any]] = []
    all_auto = True
    for ev in elements:
        if not isinstance(ev, dict):
            continue
        # Only analyze elements that visual-arbiter flagged as failing.
        status = ev.get("status")
        if status == "pass":
            continue  # nothing to auto-approve
        cls = classify_element(ev, profile, tokens)
        classifications.append(cls)
        if cls["classification"] != "micro-drift":
            all_auto = False

    if not classifications:
        # No failures at all — nothing to auto-approve, nothing material either.
        # Escalate by default; bob can distinguish via the empty classifications.
        all_auto = False

    tuple_echo = {
        "request_id": request_id,
        "attempt_id": attempt_id,
        "prior_state_version": prior_state_version,
        "skeleton_hash": skeleton_hash,
        "impl_hash": impl_hash,
        "inventory_hash": inventory_hash,
        "runner_version": runner_version,
        "rubric_version": rubric_version,
    }

    out: Dict[str, Any] = {
        "status": "auto_approved" if all_auto else "escalate_to_user",
        "tuple_echo": tuple_echo,
        "classification_per_element": classifications,
        "profile_used": profile_name,
        "rubric_version": rubric_version,
    }
    emit_and_exit(out, exit_code=0)


if __name__ == "__main__":
    main()
