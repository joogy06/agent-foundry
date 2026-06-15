#!/usr/bin/env python3
"""sweep_scope.py — S055 §5.4 / §8. Single shared implementation of alf's
tier->scope resolution (extracted from alf.md Step 2g prose) PLUS the
priority-score recompute used by the alf-sweep `synthesize` reduce.

Used by `alf_sweep_launcher.sh` (to write the args file) AND by any future
caller. Pure / deterministic — no LLM, no clock, no network. Resolving the tier
in ONE place means the launcher and the workflow can never disagree on scope.

Tier -> args mapping (design §5.4):
  tier        targets                                feeds                       budget  finder  verify
  version     by_tool[<changed>] U rot tool (2-5)    history tail + drift        20-40k  sonnet  external-only
  freshness   RED/YELLOW rot + by_deadline horizon   rot + index                 40-80k  sonnet  external-only
  flow-pulse  ONE pseudo-target "orchestration-flow" rollup + open flow tasks    20k     sonnet  on-breach
  full        family / whole library, one per dir    all feeds                   high    opus    critical+external
  flow-review bob/alf/forge/pa/_meta (5 fixed)       identity + rollup           high    opus    all-critical
"""
from __future__ import annotations

from typing import Any, Dict, List

TIER_SPEC: Dict[str, Dict[str, Any]] = {
    "version": {
        "feeds": ["inventory-history.jsonl", "drift-report.json"],
        "budget_tokens": 40000,
        "finder_model": "sonnet",
        "verify_arm": "external-only",
        "scope_kind": "by_tool",
    },
    "freshness": {
        "feeds": ["rot-report.json", "freshness/index.json"],
        "budget_tokens": 80000,
        "finder_model": "sonnet",
        "verify_arm": "external-only",
        "scope_kind": "rot_and_deadline",
    },
    "flow-pulse": {
        "feeds": ["rollup.json", "open-flow-tasks"],
        "budget_tokens": 20000,
        "finder_model": "sonnet",
        "verify_arm": "on-breach",
        "scope_kind": "pseudo_target",
    },
    "full": {
        "feeds": ["*"],
        "budget_tokens": 400000,
        "finder_model": "opus",
        "verify_arm": "critical+external",
        "scope_kind": "library",
    },
    "flow-review": {
        "feeds": ["identity-report.json", "rollup.json"],
        "budget_tokens": 400000,
        "finder_model": "opus",
        "verify_arm": "all-critical",
        "scope_kind": "fixed_five",
    },
}

FLOW_REVIEW_FIXED = ["agents/bob.md", "agents/alf.md", "skills/forge", "agents/pa.md", "skills/_meta"]

VALID_TIERS = tuple(TIER_SPEC.keys())


def tier_spec(tier: str) -> Dict[str, Any]:
    if tier not in TIER_SPEC:
        raise ValueError(f"unknown sweep tier: {tier} (valid: {', '.join(VALID_TIERS)})")
    return dict(TIER_SPEC[tier])


def resolve_targets(tier: str, changed_tools: List[str] | None = None,
                    rot_targets: List[str] | None = None,
                    deadline_targets: List[str] | None = None,
                    library_dirs: List[str] | None = None) -> List[str]:
    """Resolve the in-scope target list for a tier. The caller supplies the
    feed-derived inputs (changed_tools/rot_targets/etc.) read once at args-write
    time; this function only composes them deterministically."""
    spec = tier_spec(tier)
    kind = spec["scope_kind"]
    changed_tools = changed_tools or []
    rot_targets = rot_targets or []
    deadline_targets = deadline_targets or []
    library_dirs = library_dirs or []
    if kind == "by_tool":
        return sorted(set(changed_tools) | set(rot_targets))
    if kind == "rot_and_deadline":
        return sorted(set(rot_targets) | set(deadline_targets))
    if kind == "pseudo_target":
        return ["orchestration-flow"]
    if kind == "library":
        return sorted(set(library_dirs))
    if kind == "fixed_five":
        return list(FLOW_REVIEW_FIXED)
    raise ValueError(f"unhandled scope_kind: {kind}")


def priority_score(impact: float, exposure: float, confidence: float,
                   urgency: float, effort: float) -> float:
    """The alf priority formula (alf.md Step 3), as a pure function so the
    synthesize reduce recomputes EVERY score from numeric inputs (never trusts
    a finder-supplied score). Effort floors at 1 to avoid div-by-zero.

    Score = Impact(1-5) * Exposure(1-5) * Confidence(0.5/0.75/1.0)
            * Urgency(1-5) / Effort(1-5)
    """
    eff = effort if effort and effort > 0 else 1.0
    return round((impact * exposure * confidence * urgency) / eff, 4)


def dedupe_keep_max(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedupe by (target_path, lens, normalized-title), keep the max
    priority_score; stable sort by priority_score desc then key. Deterministic
    FIELD content (not byte-identity, per challenger M-10)."""
    def norm_title(t: str) -> str:
        return " ".join((t or "").lower().split())

    best: Dict[tuple, Dict[str, Any]] = {}
    for f in findings:
        key = (f.get("target_path"), f.get("lens"), norm_title(f.get("title", "")))
        cur = best.get(key)
        if cur is None or (f.get("priority_score", 0) or 0) > (cur.get("priority_score", 0) or 0):
            best[key] = f
    out = list(best.values())
    out.sort(key=lambda f: (-(f.get("priority_score", 0) or 0),
                            str(f.get("target_path")), str(f.get("lens")),
                            norm_title(f.get("title", ""))))
    return out


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        sys.stderr.write("usage: sweep_scope.py <tier> [--spec|--targets]\n")
        sys.exit(2)
    tier = sys.argv[1]
    sys.stdout.write(json.dumps(tier_spec(tier), indent=2) + "\n")
