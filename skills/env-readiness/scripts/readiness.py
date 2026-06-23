#!/usr/bin/env python3
"""readiness.py — read-only environment-readiness doctor.

Reviews a Claude Code environment (`~/.claude` global + an optional per-project
`.claude/`) across every dimension that makes the local forge/bob/alf/skills setup
work — install completeness, SessionStart hooks, config files, gates, 3-tree
identity, tooling tier, freshness, and per-project hygiene — and prints a single
READY / READY-WITH-WARNINGS / NOT-READY verdict with a prioritized repair list.

DESIGN STANCE: **read-only**. The doctor REVIEWS and REPORTS; it never mutates the
environment. Repairs are the installer's job — most repair pointers are simply
`python3 installer/bootstrap-environment.py` (idempotent) or a specific probe.
Each check is isolated (a failing probe degrades to a FAIL row, never crashes the
sweep), so the doctor is safe to run anywhere, anytime.

Usage:
    python3 readiness.py [--claude-home DIR] [--project DIR] [--repo DIR]
                         [--json] [--strict]
Exit codes:
    0  READY or READY-WITH-WARNINGS (advisory)            — always 0 unless --strict
    0  --strict and verdict READY/READY-WITH-WARNINGS
    1  --strict and verdict NOT-READY (for CI gating)
"""
# NOTE: deliberately NOT using `from __future__ import annotations` — this module
# defines @dataclasses and must stay loadable via importlib.spec_from_file_location
# (where the module is absent from sys.modules and stringized annotations cannot be
# resolved by dataclasses). Real annotations keep it loader-agnostic.

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# The SessionStart hooks the installer wires (matched by basename substring).
CANONICAL_HOOKS = [
    "scan_hard_rules.py",
    "forge_reminder_hook.py",
    "session-start.sh",            # cross-project-mail
    "freshness_nudge.py",
    "scope_delta_compact_nudge.py",
]
# A few load-bearing skills/agents whose ABSENCE means a broken install.
KEY_SKILLS = ["forge", "env-adoption", "dep-currency-check", "research-for-skills"]
KEY_AGENTS = ["bob", "alf", "pa", "evo", "wiki"]


@dataclass
class Result:
    dimension: str
    status: str            # PASS | WARN | FAIL
    detail: str
    repair: str = ""


@dataclass
class Section:
    name: str
    results: List[Result] = field(default_factory=list)

    def add(self, status, detail, repair=""):
        self.results.append(Result(self.name, status, detail, repair))


def _safe(fn, section: Section):
    """Run a check; any exception becomes a FAIL row instead of crashing."""
    try:
        fn(section)
    except Exception as e:  # noqa: BLE001 — a doctor must never crash on a probe
        section.add(FAIL, f"check raised {type(e).__name__}: {e}",
                    "inspect the probe; this is a doctor bug or a broken env")


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def check_install(s: Section, home: Path, repo: Optional[Path]):
    n_skills = len(list((home / "skills").glob("*/"))) if (home / "skills").is_dir() else 0
    n_agents = len(list((home / "agents").glob("*.md"))) if (home / "agents").is_dir() else 0
    n_wf = len(list((home / "workflows").glob("*.*"))) if (home / "workflows").is_dir() else 0
    s.add(PASS if n_skills > 50 else (WARN if n_skills else FAIL),
          f"{n_skills} skills, {n_agents} agents, {n_wf} workflows installed",
          "" if n_skills > 50 else "run: python3 installer/install.py")
    missing_sk = [k for k in KEY_SKILLS if not (home / "skills" / k).is_dir()]
    s.add(PASS if not missing_sk else FAIL,
          "key skills present" if not missing_sk else f"MISSING key skills: {missing_sk}",
          "" if not missing_sk else "run: python3 installer/install.py")
    missing_ag = [k for k in KEY_AGENTS if not (home / "agents" / f"{k}.md").is_file()]
    s.add(PASS if not missing_ag else FAIL,
          "key agents present" if not missing_ag else f"MISSING key agents: {missing_ag}",
          "" if not missing_ag else "run: python3 installer/install.py")
    # CLAUDE.md + AGENTS.md symlink + pa-server + claude-observe
    s.add(PASS if (home / "CLAUDE.md").is_file() else FAIL,
          "CLAUDE.md present" if (home / "CLAUDE.md").is_file() else "CLAUDE.md MISSING",
          "" if (home / "CLAUDE.md").is_file() else "run: python3 installer/bootstrap-environment.py")
    ag = home / "AGENTS.md"
    ag_ok = ag.is_symlink() or ag.is_file()
    s.add(PASS if ag_ok else WARN, "AGENTS.md present" if ag_ok else "AGENTS.md missing",
          "" if ag_ok else "run: python3 installer/bootstrap-environment.py")
    co = home / "bin" / "claude-observe"
    s.add(PASS if co.exists() else WARN,
          "claude-observe bin linked" if co.exists() else "claude-observe bin missing",
          "" if co.exists() else "run: python3 installer/bootstrap-environment.py")
    # Codex mirror parity (advisory)
    codex = Path.home() / ".codex" / "skills"
    if shutil.which("codex") and codex.is_dir():
        n_codex = len(list(codex.glob("*/")))
        s.add(PASS if n_codex >= n_skills - 2 else WARN,
              f"Codex mirror: {n_codex} skills",
              "" if n_codex >= n_skills - 2 else "run: python3 installer/bootstrap-environment.py")


def check_hooks(s: Section, home: Path):
    sj = home / "settings.json"
    if not sj.is_file():
        s.add(FAIL, "settings.json missing", "run: python3 installer/bootstrap-environment.py")
        return
    try:
        d = json.loads(sj.read_text())
    except Exception as e:  # noqa: BLE001
        s.add(FAIL, f"settings.json does not parse: {e}", "fix settings.json JSON syntax")
        return
    cmds = " ".join(
        h.get("command", "")
        for e in d.get("hooks", {}).get("SessionStart", [])
        for h in e.get("hooks", [])
    )
    missing = [h for h in CANONICAL_HOOKS if h not in cmds]
    if not missing:
        s.add(PASS, f"all {len(CANONICAL_HOOKS)} SessionStart hooks wired")
    else:
        s.add(FAIL, f"SessionStart hooks NOT wired: {missing}",
              "run: python3 installer/bootstrap-environment.py --skip-install")


def check_config(s: Section, home: Path):
    pl = home / "policy-limits.json"
    if pl.is_file():
        mode = oct(pl.stat().st_mode & 0o777)[-3:]
        s.add(PASS if mode == "600" else WARN, f"policy-limits.json present (mode {mode})",
              "" if mode == "600" else "chmod 600 ~/.claude/policy-limits.json")
    else:
        s.add(WARN, "policy-limits.json missing",
              "run: python3 installer/bootstrap-environment.py --skip-install")
    for name, level in (("model-policy.yaml", WARN), ("publish-config.json", WARN)):
        p = home / name
        ok = p.is_file()
        if ok and name.endswith(".json"):
            try:
                json.loads(p.read_text())
            except Exception:  # noqa: BLE001
                s.add(FAIL, f"{name} present but does NOT parse", f"fix {p}")
                continue
        s.add(PASS if ok else level, f"{name} {'present' if ok else 'absent'}",
              "" if ok else f"optional — provided by installer/bootstrap if desired")


def check_gates(s: Section, home: Path):
    gp = home / "skills" / "_meta" / "gates.py"
    if not gp.is_file():
        s.add(FAIL, "gates.py missing", "run: python3 installer/install.py")
        return
    # Import-smoke: load gates.py in a child process so a broken module can't taint us.
    # READ-ONLY discipline: -B + PYTHONDONTWRITEBYTECODE so no __pycache__/*.pyc is
    # written, and the path is passed via argv (NOT interpolated into -c source) so a
    # crafted --claude-home cannot break out of the string.
    code = ("import importlib.util as u,sys;"
            "s=u.spec_from_file_location('g',sys.argv[1]);m=u.module_from_spec(s);"
            "sys.modules['g']=m;s.loader.exec_module(m);print('OK')")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-B", "-c", code, str(gp)],
                       capture_output=True, text=True, timeout=30, env=env)
    if r.returncode == 0 and "OK" in r.stdout:
        s.add(PASS, "gates.py imports + loads cleanly")
    else:
        s.add(FAIL, f"gates.py failed to import: {r.stderr.strip()[:120]}",
              "inspect ~/.claude/skills/_meta/gates.py")


def check_identity(s: Section, home: Path):
    ic = home / "skills" / "_meta" / "identity_check.py"
    if not ic.is_file():
        s.add(WARN, "identity_check.py absent (3-tree parity not checkable)", "")
        return
    # --no-write keeps the doctor read-only (the advisory path would otherwise write
    # ~/.claude/state/freshness/identity-report.json).
    r = subprocess.run([sys.executable, str(ic), "--pair", "prod-shadow", "--no-write"],
                       capture_output=True, text=True, timeout=60)
    # advisory: exit 0 = match; non-zero = mismatch/unavailable
    if r.returncode == 0:
        s.add(PASS, "3-tree identity (prod-shadow) OK")
    else:
        s.add(WARN, f"identity check non-zero (advisory): {(r.stdout + r.stderr).strip()[:100]}",
              "review with: identity_check.py --pair prod-shadow")


def check_tooling(s: Section, home: Path):
    inv = home / "state" / "inventory.json"
    if inv.is_file():
        try:
            d = json.loads(inv.read_text())
            caps = d.get("capabilities", {}) or {}
            tools = d.get("tools", {}) or {}
            have = [t for t in ("codex", "agy", "gh", "docker") if shutil.which(t)]
            s.add(PASS, f"env-adoption inventory present; on PATH: {', '.join(have) or 'none'}")
        except Exception as e:  # noqa: BLE001
            s.add(WARN, f"inventory.json present but unreadable: {e}",
                  "run: bash ~/.claude/skills/env-adoption/scripts/probe.sh check")
    else:
        s.add(WARN, "env-adoption inventory.json absent",
              "run: bash ~/.claude/skills/env-adoption/scripts/probe.sh check")
    src = home / "state" / "sources.json"
    if src.is_file():
        try:
            d = json.loads(src.read_text())
            s.add(PASS, f"knowledge-grounding: mode={d.get('grounding_mode', '?')}")
        except Exception:  # noqa: BLE001
            s.add(WARN, "sources.json unreadable",
                  "run: bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh discover")
    else:
        s.add(WARN, "knowledge-grounding sources.json absent",
              "run: bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh discover")


def check_project(s: Section, project: Path):
    cd = project / ".claude"
    if not cd.is_dir():
        s.add(WARN, f"{project} has no .claude/ (not a configured project)", "")
        return
    sl = cd / "settings.local.json"
    if sl.is_file():
        try:
            json.loads(sl.read_text())
            s.add(PASS, ".claude/settings.local.json parses")
        except Exception as e:  # noqa: BLE001
            s.add(FAIL, f".claude/settings.local.json does NOT parse: {e}", f"fix {sl}")
    s.add(PASS if (project / "CLAUDE.md").is_file() else WARN,
          "project CLAUDE.md present" if (project / "CLAUDE.md").is_file() else "no project CLAUDE.md", "")
    # stale forge/bob/ledger artifacts
    stale = []
    for pat in (".ledger/.bob-stage-current-token", ".bob-checkpoint.md", ".forge/session.key"):
        if (project / pat).exists():
            stale.append(pat)
    if stale:
        s.add(WARN, f"stale orchestration artifacts present: {stale}",
              "review/clear if no bob/forge run is active")
    else:
        s.add(PASS, "no stale forge/bob/ledger artifacts")


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def run(home: Path, repo: Optional[Path], project: Optional[Path]) -> List[Section]:
    sections: List[Section] = []

    def section(name, fn):
        sec = Section(name)
        _safe(fn, sec)
        sections.append(sec)

    section("Install", lambda s: check_install(s, home, repo))
    section("Hooks", lambda s: check_hooks(s, home))
    section("Config", lambda s: check_config(s, home))
    section("Gates", lambda s: check_gates(s, home))
    section("Identity", lambda s: check_identity(s, home))
    section("Tooling", lambda s: check_tooling(s, home))
    if project:
        section("Project", lambda s: check_project(s, project))
    return sections


def verdict(sections: List[Section]) -> str:
    rs = [r for sec in sections for r in sec.results]
    if any(r.status == FAIL for r in rs):
        return "NOT-READY"
    if any(r.status == WARN for r in rs):
        return "READY-WITH-WARNINGS"
    return "READY"


def render_human(sections: List[Section], v: str) -> str:
    mark = {PASS: "OK ", WARN: "!! ", FAIL: "XX "}
    lines = ["", "Claude Code environment — readiness review", "=" * 44]
    repairs = []
    for sec in sections:
        lines.append(f"\n[{sec.name}]")
        for r in sec.results:
            lines.append(f"  {mark.get(r.status,'?')} {r.status:<4} {r.detail}")
            if r.repair and r.status != PASS:
                repairs.append((r.status, r.dimension, r.repair))
    lines.append("\n" + "=" * 44)
    lines.append(f"VERDICT: {v}")
    if repairs:
        lines.append("\nPrioritized repairs (the doctor never runs these — read-only):")
        seen = set()
        for status, dim, rep in sorted(repairs, key=lambda x: 0 if x[0] == FAIL else 1):
            if rep in seen:
                continue
            seen.add(rep)
            lines.append(f"  [{status}] {dim}: {rep}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Read-only Claude Code environment readiness doctor.")
    p.add_argument("--claude-home", default=str(Path.home() / ".claude"))
    p.add_argument("--project", default=None,
                   help="a project dir to also review (defaults to CWD if it has .claude/).")
    p.add_argument("--repo", default=None, help="agent-foundry/skill_factory repo root (for installer pointers).")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 1 when verdict is NOT-READY.")
    a = p.parse_args(argv)

    home = Path(a.claude_home).expanduser()
    repo = Path(a.repo).expanduser() if a.repo else None
    project = None
    if a.project:
        project = Path(a.project).expanduser()
    elif (Path.cwd() / ".claude").is_dir():
        project = Path.cwd()

    sections = run(home, repo, project)
    v = verdict(sections)

    if a.json:
        print(json.dumps({
            "verdict": v,
            "claude_home": str(home),
            "project": str(project) if project else None,
            "sections": [
                {"dimension": sec.name,
                 "results": [{"status": r.status, "detail": r.detail, "repair": r.repair}
                             for r in sec.results]}
                for sec in sections
            ],
        }, indent=2, sort_keys=True))
    else:
        print(render_human(sections, v))

    if a.strict and v == "NOT-READY":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
