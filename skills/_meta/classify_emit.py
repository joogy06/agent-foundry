#!/usr/bin/env python3
"""
classify_emit.py — default `contract-classification.v1` artifact helper for
non-forge callers (alf, pa, standalone bob direct-fix).

S042 / #115 §4. The bare-assertion hole isn't only bob's; alf/pa/user spawns
also just say `Contract map: N/A`. So the classification becomes a RECORDED
artifact that travels with the cycle (analogous to the signed contract map).
Forge writes `.forge/classification.json` itself at Step 8a.0; non-forge callers
use THIS helper so they don't hand-write JSON. No artifact -> `G_CLASSIFY`
exit 2 (blocked); the skip is authorized SOLELY by a green `G_CLASSIFY`.

The emitted artifact is a CLAIM the gate re-derives and corroborates, never
trusted (the threat model includes a buggy/drifting producer). This helper just
populates sensible defaults from the same deterministic scan gates.py runs.

Output schema = `contract-classification.v1` (§12 R3):
  {schema, introduces_components, reason_code, design_doc, planned_globs,
   evidence:{confirmed_positives, negatives, prose_only}, classified_by,
   classified_at}

reason_code is a CLOSED enum (Codex: free-text reasons are a loophole). A
free-text / unrecognized reason is rejected here and (independently) lands as
`ambiguous -> escalate` in the gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import classify  # noqa: E402

ARTIFACT_SCHEMA = "contract-classification.v1"

REASON_CODES = frozenset({
    "skill_text",
    "doc_only",
    "direct_bugfix",
    "refactor",
    "self_contained_meta_helper",
    "sidecar_telemetry",
    "agent_text",
    "existing_component_extension",
    # S069 (2026-07-25): the eight members above all describe an EXEMPT or
    # EXTENSION cycle. There was no member meaning "this design introduces
    # genuinely new components", yet validate_artifact() requires a member
    # unconditionally — including on the introduces_components: "yes" branch.
    # Every yes-branch cycle was therefore structurally unable to pass the
    # G_CLASSIFY --verify-diff completion checkpoint (exit 3 ESCALATE), while
    # pre-flight passed green, so it only bit at the very end of a cycle.
    #
    # NOTE the deliberate asymmetry: gates.py extends the scope-check whitelist
    # (`ext_globs`) ONLY for `existing_component_extension`. `new_component`
    # must NOT be added there — a yes-branch cycle is exactly where the scope
    # check needs to stay fully armed, so the gate keeps checking every planned
    # glob. Adding it to that branch would silently disarm the gate.
    "new_component",
})

VALID_CLASSIFIED_BY = frozenset({
    "forge_design", "bob_direct", "alf", "pa",
})


def _default_reason_code(verdict: str, file_profile: List[str]) -> str:
    """Pick a defensible closed-enum reason_code from the scan verdict + files.

    Only used when the caller does not supply one. For `no` verdicts we infer
    the most specific exempt category we can; for `yes`/`ambiguous` the caller
    really should be going through forge Step 8a (this helper still emits an
    artifact so the gate can BLOCK/ESCALATE rather than silently skip)."""
    profiles = file_profile or []
    # S069: a `yes` verdict is NEW COMPONENTS by definition, so it must not fall
    # through the exempt-category heuristics below. Before this guard, a design
    # introducing four new components could be labelled `self_contained_meta_helper`
    # purely because it touched a _meta .py file — observed live on this cycle.
    # The exempt categories describe why a cycle needs no contract map; none of
    # them can be true when the scan says components are being introduced.
    if verdict == "yes":
        return "new_component"
    has_meta_py = any(classify._path_is_exempt(p) and "/_meta/" in ("/" + p)
                      and p.endswith(".py") for p in profiles)
    has_skill_md = any(p.endswith("SKILL.md") for p in profiles)
    has_agent_md = any("/agents/" in ("/" + p) and p.endswith(".md")
                       for p in profiles)
    only_docs = profiles and all(("/docs/" in ("/" + p)) or p.endswith(".md")
                                 for p in profiles)
    if has_meta_py:
        return "self_contained_meta_helper"
    if has_skill_md:
        return "skill_text"
    if has_agent_md:
        return "agent_text"
    if only_docs:
        return "doc_only"
    # No file signal — fall back to direct_bugfix for a `no` verdict.
    return "direct_bugfix"


def emit_artifact(
    project_root: Path,
    *,
    design_doc: Optional[Path] = None,
    file_profile: Optional[List[str]] = None,
    reason_code: Optional[str] = None,
    classified_by: str = "bob_direct",
    planned_globs: Optional[List[str]] = None,
) -> Dict:
    """Derive a default `contract-classification.v1` artifact via the same
    deterministic scan gates.py runs. Returns the artifact dict.

    Raises ValueError on an unrecognized reason_code or classified_by (closed
    enums — fail fast at emit time)."""
    if reason_code is not None and reason_code not in REASON_CODES:
        raise ValueError(
            f"reason_code {reason_code!r} not in closed enum {sorted(REASON_CODES)}"
        )
    if classified_by not in VALID_CLASSIFIED_BY:
        raise ValueError(
            f"classified_by {classified_by!r} not in {sorted(VALID_CLASSIFIED_BY)}"
        )

    # If no file profile supplied, derive from git (planned == actual at emit).
    if file_profile is None:
        file_profile = classify.git_changed_files(project_root)

    result = classify.classify(
        project_root, design_doc=design_doc, file_profile=file_profile,
    )
    verdict = result["verdict"]
    introduces = "yes" if verdict == "yes" else "no"
    # For ambiguous we still emit introduces="no" as a CLAIM; the gate will
    # independently re-derive `ambiguous` and ESCALATE (exit 3) regardless of
    # what we wrote here — the artifact is never trusted.

    final_reason = reason_code or _default_reason_code(verdict, file_profile)

    artifact = {
        "schema": ARTIFACT_SCHEMA,
        "introduces_components": introduces,
        "reason_code": final_reason,
        "design_doc": result["design_doc"],
        "planned_globs": planned_globs or sorted(set(file_profile)),
        "evidence": result["evidence"],
        "classified_by": classified_by,
        "classified_at": classify.now_iso(),
    }
    return artifact


def write_artifact(project_root: Path, artifact: Dict,
                   dest: Optional[Path] = None) -> Path:
    """Write the artifact to `.forge/classification.json` (or `dest`).
    Atomic replace-on-write. Returns the path."""
    out_path = dest or (project_root / ".forge" / "classification.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(out_path)
    return out_path


def validate_artifact(artifact: Dict) -> List[str]:
    """Structural validation of a `contract-classification.v1` artifact.
    Returns a list of problem strings ([] = valid). Used by gates.py to reject
    a malformed / free-text-reason artifact (-> escalate)."""
    problems: List[str] = []
    if artifact.get("schema") != ARTIFACT_SCHEMA:
        problems.append(f"schema must be {ARTIFACT_SCHEMA!r}")
    if artifact.get("introduces_components") not in ("yes", "no"):
        problems.append("introduces_components must be 'yes' or 'no'")
    rc = artifact.get("reason_code")
    if rc not in REASON_CODES:
        problems.append(f"reason_code {rc!r} not in closed enum")
    cb = artifact.get("classified_by")
    if cb not in VALID_CLASSIFIED_BY:
        problems.append(f"classified_by {cb!r} not recognized")
    if not isinstance(artifact.get("planned_globs"), list):
        problems.append("planned_globs must be a list")
    return problems


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="classify_emit.py",
        description="Emit a default contract-classification.v1 artifact for "
                    "non-forge callers (alf/pa/bob-direct).",
    )
    ap.add_argument("project_root")
    ap.add_argument("--design-doc", default=None)
    ap.add_argument("--reason-code", default=None)
    ap.add_argument("--classified-by", default="bob_direct")
    ap.add_argument("--files-from", default=None,
                    help="path-to-list-file or inline comma-separated paths")
    ap.add_argument("--dest", default=None,
                    help="output path (default .forge/classification.json)")
    ap.add_argument("--print", action="store_true",
                    help="print artifact to stdout instead of writing")
    args = ap.parse_args(argv)

    root = Path(args.project_root).resolve()
    doc = Path(args.design_doc) if args.design_doc else None
    file_profile = (classify.read_files_from(args.files_from, root)
                    if args.files_from else None)
    try:
        artifact = emit_artifact(
            root, design_doc=doc, file_profile=file_profile,
            reason_code=args.reason_code, classified_by=args.classified_by,
        )
    except ValueError as e:
        sys.stderr.write(f"EMIT_ERROR: {e}\n")
        return 2

    if args.print:
        sys.stdout.write(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    else:
        dest = Path(args.dest) if args.dest else None
        path = write_artifact(root, artifact, dest=dest)
        sys.stdout.write(f"wrote {path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
