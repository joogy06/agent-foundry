#!/usr/bin/env python3
"""skill_resolve.py — S073. Resolve and validate skill/agent assignments before a spawn.

DECIDING which skills a task needs stays judgement (forge, bob and team-manager already
do it via research-for-skills/gap-detection.md). This module does the mechanical half:
expand family tokens, then verify every resulting name actually resolves.

Why it exists: `work-packages.v1.json` types `skills` as `array of string`, so ANY string
validates. An uninstalled or misspelled name passes schema validation and then fails
silently at spawn — the specialist simply runs without the expertise it was assigned.
That is how `multi-platform-apps:ui-ux-designer` and `frontend-design:frontend-design`
survived in forge and team-manager: both were referenced for a long time, neither was
ever installed, and nothing ever said so.

Resolution rules:
  * bare name          -> <skills_root>/<name>/SKILL.md must exist
  * plugin:skill       -> the plugin must appear in settings.json `enabledPlugins`.
                          Presence in a marketplace listing is NOT installation.
  * family:<name>      -> expands to every skill declaring `family: <name>`; expanding
                          to nothing is an error, not an empty success
  * parent/sub         -> <skills_root>/<parent>/<sub>/SKILL.md (sub-skill directories,
                          e.g. founder/founder-ideation)

Agent types are checked more conservatively: a `plugin:agent` form whose plugin is not
enabled is definitively broken, but a bare name may be a harness built-in this module
cannot enumerate, so bare unknowns are reported as warnings rather than failures.

Stdlib only. PyYAML is used when present for --from-plan, with a regex fallback.

Public API (stable):
    load_enabled_plugins(claude_home) -> set[str]
    build_index(skills_root) -> dict  ({"skills": set, "families": dict[str, list]})
    resolve(names, index, enabled_plugins) -> dict
    resolve_agent_types(names, claude_home, enabled_plugins) -> dict
    main(argv) -> int

Exit codes (house convention: 0 pass / 2 block):
    0 — every name resolved
    2 — at least one name unresolvable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set

DEFAULT_CLAUDE_HOME = Path.home() / ".claude"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)
_FAMILY_RE = re.compile(r"^family:\s*(.+?)\s*$", re.M)
# Harness-provided agent types this module cannot enumerate from disk. Advisory only —
# used to avoid crying wolf on bare names, never to authorise one.
KNOWN_BUILTIN_AGENTS = {
    "general-purpose", "Explore", "Plan", "claude", "statusline-setup",
    "claude-code-guide", "fork",
}


def load_enabled_plugins(claude_home: Path = DEFAULT_CLAUDE_HOME) -> Set[str]:
    """Plugin names with a truthy entry in settings.json `enabledPlugins`.

    Keys look like `superpowers@claude-plugins-official`; the plugin name is the part
    before `@`.
    """
    settings = claude_home / "settings.json"
    if not settings.exists():
        return set()
    try:
        data = json.loads(settings.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        str(k).split("@", 1)[0]
        for k, v in (data.get("enabledPlugins") or {}).items()
        if v
    }


def _declared_family(skill_md: Path) -> str | None:
    try:
        head = skill_md.read_text(errors="ignore")[:8192]
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(head)
    if not m:
        return None
    fm = _FAMILY_RE.search(m.group(1))
    return fm.group(1).strip().strip("\"'") if fm else None


def build_index(skills_root: Path) -> Dict[str, object]:
    """Index installed skills and their declared families.

    Includes sub-skill directories (`parent/sub`) so references like
    `founder/founder-ideation` resolve.
    """
    skills: Set[str] = set()
    families: Dict[str, List[str]] = {}
    if not skills_root.is_dir():
        return {"skills": skills, "families": families}

    for skill_md in skills_root.glob("*/SKILL.md"):
        name = skill_md.parent.name
        skills.add(name)
        fam = _declared_family(skill_md)
        if fam:
            families.setdefault(fam, []).append(name)

    for skill_md in skills_root.glob("*/*/SKILL.md"):
        rel = f"{skill_md.parent.parent.name}/{skill_md.parent.name}"
        skills.add(rel)
        skills.add(skill_md.parent.name)  # sub-skills are often referenced bare
        fam = _declared_family(skill_md)
        if fam:
            families.setdefault(fam, []).append(rel)

    for names in families.values():
        names.sort()
    return {"skills": skills, "families": families}


def resolve(
    names: Sequence[str],
    index: Dict[str, object],
    enabled_plugins: Set[str],
) -> Dict[str, object]:
    """Expand families and verify each name resolves.

    Returns {resolved: [...], unresolved: [{name, reason}], expanded: {token: [...]}}.
    """
    skills: Set[str] = index["skills"]  # type: ignore[assignment]
    families: Dict[str, List[str]] = index["families"]  # type: ignore[assignment]

    resolved: List[str] = []
    unresolved: List[Dict[str, str]] = []
    expanded: Dict[str, List[str]] = {}

    for raw in names:
        name = str(raw).strip()
        if not name:
            continue

        if name.startswith("family:"):
            fam = name.split(":", 1)[1].strip()
            members = families.get(fam, [])
            if not members:
                unresolved.append({
                    "name": name,
                    "reason": f"family '{fam}' has no members — no installed skill declares `family: {fam}`",
                })
                continue
            expanded[name] = members
            resolved.extend(members)
            continue

        if ":" in name:
            plugin, _, sub = name.partition(":")
            if plugin in enabled_plugins:
                resolved.append(name)
            else:
                unresolved.append({
                    "name": name,
                    "reason": (
                        f"plugin '{plugin}' is not in enabledPlugins. Being listed in a "
                        f"marketplace is not installation."
                    ),
                })
            continue

        if name in skills:
            resolved.append(name)
        else:
            unresolved.append({"name": name, "reason": "no such skill directory with a SKILL.md"})

    # de-dupe, preserve order
    seen: Set[str] = set()
    ordered = [s for s in resolved if not (s in seen or seen.add(s))]
    return {"resolved": ordered, "unresolved": unresolved, "expanded": expanded}


def resolve_agent_types(
    names: Sequence[str],
    claude_home: Path = DEFAULT_CLAUDE_HOME,
    enabled_plugins: Set[str] | None = None,
) -> Dict[str, object]:
    """Validate subagent_type values. Plugin-qualified unknowns fail; bare ones warn."""
    enabled = enabled_plugins if enabled_plugins is not None else load_enabled_plugins(claude_home)
    custom = {p.stem for p in (claude_home / "agents").glob("*.md")} if (claude_home / "agents").is_dir() else set()

    ok: List[str] = []
    bad: List[Dict[str, str]] = []
    warn: List[Dict[str, str]] = []
    for raw in names:
        name = str(raw).strip()
        if not name:
            continue
        if ":" in name:
            plugin = name.split(":", 1)[0]
            (ok.append(name) if plugin in enabled else bad.append({
                "name": name,
                "reason": f"plugin '{plugin}' is not in enabledPlugins — this subagent_type does not exist",
            }))
        elif name in custom or name in KNOWN_BUILTIN_AGENTS:
            ok.append(name)
        else:
            warn.append({
                "name": name,
                "reason": "not a custom agent and not a known built-in — verify against the host's agent list",
            })
    return {"ok": ok, "unresolved": bad, "warnings": warn}


def _skills_from_plan(path: Path) -> List[str]:
    """Extract every `skills:` entry from a work-packages plan."""
    text = path.read_text()
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None  # type: ignore
    if yaml is not None:
        data = yaml.safe_load(text) or {}
        out: List[str] = []
        for wp in data.get("work_packages", []) or []:
            out.extend(wp.get("skills", []) or [])
        return out
    # Fallback: collect list items under a `skills:` key.
    out, capturing = [], False
    for line in text.splitlines():
        if re.match(r"^\s*skills:\s*$", line):
            capturing = True
            continue
        if capturing:
            m = re.match(r"^\s*-\s*(.+?)\s*$", line)
            if m:
                out.append(m.group(1).strip("\"'"))
            else:
                capturing = False
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Resolve and validate skill/agent assignments.")
    ap.add_argument("names", nargs="*", help="skill names, plugin:skill, or family:<name>")
    ap.add_argument("--claude-home", type=Path, default=DEFAULT_CLAUDE_HOME)
    ap.add_argument("--skills-root", type=Path, default=None)
    ap.add_argument("--from-plan", type=Path, help="read skills[] from a work-packages.yaml")
    ap.add_argument("--agent-types", nargs="*", default=None, help="also validate subagent_type values")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    skills_root = args.skills_root or (args.claude_home / "skills")
    names = list(args.names)
    if args.from_plan:
        try:
            names.extend(_skills_from_plan(args.from_plan))
        except OSError as exc:
            print(f"skill_resolve: cannot read plan ({exc})", file=sys.stderr)
            return 2

    if not names and args.agent_types is None:
        print("skill_resolve: nothing to resolve (pass names, --from-plan, or --agent-types)", file=sys.stderr)
        return 2

    enabled = load_enabled_plugins(args.claude_home)
    index = build_index(skills_root)
    result = resolve(names, index, enabled)

    agents_result = None
    if args.agent_types is not None:
        agents_result = resolve_agent_types(args.agent_types, args.claude_home, enabled)

    failed = bool(result["unresolved"]) or bool(agents_result and agents_result["unresolved"])

    if args.json:
        payload = dict(result)
        if agents_result is not None:
            payload["agent_types"] = agents_result
        payload["ok"] = not failed
        print(json.dumps(payload, indent=2))
    else:
        for token, members in result["expanded"].items():  # type: ignore[union-attr]
            print(f"  {token} -> {', '.join(members)}")
        for name in result["resolved"]:  # type: ignore[union-attr]
            print(f"  OK        {name}")
        for item in result["unresolved"]:  # type: ignore[union-attr]
            print(f"  UNRESOLVED {item['name']} — {item['reason']}")
        if agents_result:
            for name in agents_result["ok"]:  # type: ignore[index]
                print(f"  OK  agent {name}")
            for item in agents_result["warnings"]:  # type: ignore[index]
                print(f"  WARN agent {item['name']} — {item['reason']}")
            for item in agents_result["unresolved"]:  # type: ignore[index]
                print(f"  UNRESOLVED agent {item['name']} — {item['reason']}")
        if failed:
            sys.stdout.flush()  # keep the stderr note after the findings it refers to
            print("\nRefusing to report clean: an unresolvable assignment does not fail loudly "
                  "at spawn — the specialist just runs without it.", file=sys.stderr)

    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
