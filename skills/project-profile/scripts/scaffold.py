#!/usr/bin/env python3
"""scaffold.py — S074. Build a project-profile skeleton from what is observable.

Reads the tree and the standing context files, infers what it honestly can, and leaves
everything else EXPLICITLY blank rather than guessed.

The design rule, which is the whole point: an inferred stack is usually right, an inferred
PURPOSE is usually shallow and confidently wrong. So the stack is filled in and marked
`inferred`, while purpose, constraints and decisions are left empty with a prompt — because
a plausible-sounding purpose nobody corrected is worse than a blank one, and it will be
trusted for months.

Exit: 0 written · 2 profile already exists (not overwritten) · 3 bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

MANIFESTS = {
    "pyproject.toml": "python", "requirements.txt": "python", "setup.py": "python",
    "package.json": "node", "go.mod": "go", "Cargo.toml": "rust",
    "pom.xml": "java", "build.gradle": "java", "Gemfile": "ruby", "composer.json": "php",
}
INFRA = {
    "Dockerfile": "docker", "docker-compose.yml": "docker-compose",
    ".github/workflows": "github-actions", ".gitlab-ci.yml": "gitlab-ci",
    "Jenkinsfile": "jenkins", "terraform": "terraform", "k8s": "kubernetes",
}
CONTEXT_FILES = ("PROJECT.md", "history.md", "tasks.md", "README.md", "CLAUDE.md",
                 "session_control.md", "index.md")


def observe(root: Path) -> Dict[str, Any]:
    found_manifests, found_infra = [], []
    for name, label in MANIFESTS.items():
        if (root / name).exists():
            found_manifests.append({"file": name, "ecosystem": label})
    for name, label in INFRA.items():
        if (root / name).exists():
            found_infra.append(label)

    # Node frameworks are declared, not guessed — read the manifest.
    frameworks = []
    pkg = root / "package.json"
    if pkg.exists():
        try:
            deps = json.loads(pkg.read_text(errors="ignore"))
            all_deps = {**deps.get("dependencies", {}), **deps.get("devDependencies", {})}
            for f in ("next", "react", "vue", "svelte", "@angular/core", "express", "fastify"):
                if f in all_deps:
                    frameworks.append(f"{f}@{all_deps[f]}")
        except (json.JSONDecodeError, OSError):
            pass
    for f, label in (("pyproject.toml", None), ("requirements.txt", None)):
        p = root / f
        if p.exists():
            txt = p.read_text(errors="ignore").lower()
            for lib in ("django", "flask", "fastapi", "sqlalchemy", "pandas", "pytest"):
                if re.search(rf"\b{lib}\b", txt):
                    frameworks.append(lib)

    tests = [d for d in ("tests", "test", "spec", "__tests__") if (root / d).is_dir()]
    context = [c for c in CONTEXT_FILES if (root / c).exists()]

    return {
        "manifests": found_manifests,
        "frameworks": sorted(set(frameworks)),
        "infra": sorted(set(found_infra)),
        "test_dirs": tests,
        "context_files": context,
        "is_git": (root / ".git").exists(),
    }


def build(root: Path, obs: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": "project-profile.v1",
        "project": root.name,
        "reviewed": None,
        "purpose": {
            "value": None, "provenance": "unset",
            "_prompt": "One paragraph: what does this exist to do, and for whom? "
                       "ASK — this is the field inference gets wrong and nobody corrects.",
        },
        "domain": {"value": None, "provenance": "unset"},
        "stage": {"value": None, "provenance": "unset",
                  "_prompt": "exploration | build | operate | maintain | wind-down"},
        "stack": {
            "value": {
                "ecosystems": sorted({m["ecosystem"] for m in obs["manifests"]}),
                "frameworks": obs["frameworks"],
                "infra": obs["infra"],
                "tests": obs["test_dirs"],
            },
            "provenance": "inferred",
            "_note": "observed from manifests and tree — confirm versions that matter",
        },
        "constraints": {
            "value": [], "provenance": "unset",
            "_prompt": "air-gapped · regulated · single-operator · legacy interop · budget · latency. "
                       "These change harness defaults, so an empty list is a real answer only if asked.",
        },
        "conventions": {"value": [], "provenance": "unset"},
        "decisions": {
            "value": [], "provenance": "unset",
            "_prompt": "Each: what was decided, WHY, when, and what would reverse it. "
                       "A decision without its reason gets re-litigated.",
        },
        "glossary": {"value": {}, "provenance": "unset"},
        "key_surfaces": {"value": [], "provenance": "unset",
                         "_prompt": "endpoints, files and entry points that come up repeatedly"},
        "capability": {
            "value": [], "provenance": "unset",
            "_prompt": "Per recurring need, in order: existing skill > existing skill + project "
                       "reference > project-local skill > script > custom agent. Option 2 is usually "
                       "right and usually skipped.",
        },
        "_observed": obs,
        "_next": [
            "Read the context files found below before filling anything in.",
            "Fill purpose, constraints and decisions by ASKING — they are not inferable.",
            "Mark every field confirmed or inferred; a profile of assumptions specialises wrongly.",
            "Set `reviewed` when done, and treat a stale profile as suspect, not authoritative.",
        ],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Scaffold a project profile from observable facts.")
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        sys.stderr.write(f"PROFILE_ENV_ERROR: not a directory: {root}\n")
        return 3
    out = args.out or (root / ".project-profile.json")

    if out.exists() and not args.force:
        sys.stderr.write(
            f"PROFILE_EXISTS: {out}\n"
            "  Not overwritten. LOAD it rather than rebuilding — a profile carries decisions and\n"
            "  reasons that cannot be re-derived from the tree. Use --force only to start over.\n")
        return 2

    obs = observe(root)
    profile = build(root, obs)
    out.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(profile, indent=2))
    else:
        print(f"PROFILE SCAFFOLDED -> {out}\n")
        st = profile["stack"]["value"]
        print(f"  observed (inferred): {', '.join(st['ecosystems']) or 'no manifest found'}")
        if st["frameworks"]:
            print(f"  frameworks:          {', '.join(st['frameworks'])}")
        if st["infra"]:
            print(f"  infra:               {', '.join(st['infra'])}")
        print(f"  context files:       {', '.join(obs['context_files']) or 'none'}")
        print("\n  LEFT BLANK ON PURPOSE — ask, do not infer:")
        for f in ("purpose", "constraints", "decisions", "capability"):
            print(f"    {f}: {profile[f]['_prompt'][:88]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
