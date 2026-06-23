#!/usr/bin/env python3
"""memory_primer.py — SessionStart awareness digest (memory tiers + capabilities).

Prints one compact block every session so the agent starts FULLY AWARE of (a) which
memory tiers loaded — global always, per-project when inside a project — plus which
preference domains are populated, and (b) the live capability surface (N skills ·
M agents · K gates). Crash-proof and fast: any probe failure degrades to a partial
line, never a traceback (a hook must never break session start).

Invoked as a SessionStart hook:  python3 ~/.claude/skills/_meta/memory_primer.py --hook
"""
import os
import re
import sys
from pathlib import Path

HOME = Path.home()
CLAUDE = HOME / ".claude"


def _count_memories(memdir: Path) -> int:
    if not memdir.is_dir():
        return 0
    return sum(1 for p in memdir.glob("*.md") if p.name != "MEMORY.md")


def _project_slug(cwd: Path) -> str:
    # Claude Code derives the project dir by replacing every non-alphanumeric run in
    # the absolute path with '-' (e.g. /mnt/data/dev04/skill_factory ->
    # -mnt-data-dev04-skill-factory). Match that exactly so the project memory is found.
    return re.sub(r"[^a-zA-Z0-9]+", "-", str(cwd))


def _pref_domains(store: Path) -> list[str]:
    out = []
    if store.is_dir():
        for p in sorted(store.glob("*.md")):
            try:
                txt = p.read_text()
                m = re.match(r"^---\n(.*?)\n---", txt, re.DOTALL)
                keys = [l for l in (m.group(1).splitlines() if m else [])
                        if ":" in l and l.split(":")[0].strip() not in ("domain", "updated")
                        and l.split(":", 1)[1].strip()]
                if keys:
                    out.append(p.stem)
            except Exception:
                continue
    return out


def _counts() -> dict:
    c = {"skills": 0, "agents": 0, "gates": "?"}
    try:
        c["skills"] = sum(1 for p in (CLAUDE / "skills").glob("*/") if p.is_dir())
    except Exception:
        pass
    try:
        c["agents"] = sum(1 for _ in (CLAUDE / "agents").glob("*.md"))
    except Exception:
        pass
    try:
        gp = CLAUDE / "skills" / "_meta" / "gates.py"
        if gp.is_file():
            names = set(re.findall(r"\bG_[A-Z][A-Z0-9_]+\b", gp.read_text()))
            if names:
                c["gates"] = len(names)
    except Exception:
        pass
    return c


def build_digest(cwd: Path | None = None) -> str:
    cwd = cwd or Path.cwd()
    g_mem = _count_memories(CLAUDE / "memory")
    prefs = _pref_domains(CLAUDE / "memory" / "preferences")
    slug = _project_slug(cwd)
    proj_dir = CLAUDE / "projects" / slug / "memory"
    in_project = proj_dir.is_dir()
    p_mem = _count_memories(proj_dir) if in_project else 0

    if in_project:
        mem_line = f"Memory: global ({g_mem}) + project ({p_mem}) loaded"
    else:
        mem_line = f"Memory: global ({g_mem}) loaded (outside a tracked project)"
    if prefs:
        mem_line += f" · Preferences: {', '.join(prefs)}"

    c = _counts()
    cap_line = f"Environment: {c['skills']} skills · {c['agents']} agents · {c['gates']} gates"
    return f"🧠 {mem_line}\n🛠  {cap_line}"


def main(argv=None) -> int:
    # --hook (SessionStart) and bare invocation behave the same: print the digest.
    try:
        print(build_digest())
    except Exception as e:  # noqa: BLE001 — never break session start
        print(f"🧠 memory primer unavailable ({type(e).__name__})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
