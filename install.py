#!/usr/bin/env python3
"""
agent-foundry installer.

Moves or symlinks skills + agents from a cloned agent-foundry repo into the
config tree(s) of one or more AI CLIs you have installed:

    - Claude Code CLI    (~/.claude/{skills,agents}/)
    - Gemini CLI         (~/.gemini/skills/  via `gemini skills link`)
    - GitHub Copilot CLI (AGENTS.md bridge — Copilot has no skill concept)

Tested on Linux + macOS + Windows 10/11. Pure-stdlib Python 3.8+ — no
dependencies. Works on enterprise machines without a Python virtualenv.

Usage
-----

    python3 install.py                                       # interactive
    python3 install.py --noninteractive                      # claude + link, no prompts
    python3 install.py --target claude --mode link
    python3 install.py --target claude,gemini --mode move --force
    python3 install.py --claude-home /opt/claude --target claude
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

TARGETS_HELP = """\
Targets:
  c = Claude Code CLI         (~/.claude/skills/, ~/.claude/agents/)
  g = Gemini CLI              (~/.gemini/skills/  — via `gemini skills link` if installed)
  p = GitHub Copilot CLI      (AGENTS.md bridge — Copilot has no skill concept)
  a = All of the above
"""

DEFAULT_CLAUDE_HOME = Path.home() / ".claude"
DEFAULT_GEMINI_HOME = Path.home() / ".gemini"


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------


def banner() -> None:
    line = "=" * 60
    print(line)
    print(" agent-foundry installer")
    print(line)


def ask(prompt: str, default: str | None = None, choices: list[str] | None = None) -> str:
    suffix = ""
    if choices:
        suffix = " [" + "/".join(choices) + "]"
    elif default is not None:
        suffix = f" [{default}]"
    while True:
        try:
            val = input(f"{prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(130)
        if not val and default is not None:
            return default
        if not choices:
            return val
        val_l = val.lower()
        if val_l in choices:
            return val_l
        print(f"  invalid choice: {val!r}; expected one of {choices}")


def confirm(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            val = input(f"{prompt} {suffix}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if not val:
            return default
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def detect(repo_root: Path) -> tuple[int, int]:
    skills = repo_root / "skills"
    agents = repo_root / "agents"
    skill_count = (
        sum(1 for d in skills.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
        if skills.exists()
        else 0
    )
    agent_count = sum(1 for f in agents.glob("*.md")) if agents.exists() else 0
    return skill_count, agent_count


# ---------------------------------------------------------------------------
# Filesystem ops
# ---------------------------------------------------------------------------


def _replace_existing(dest: Path) -> None:
    """Remove dest if present, handling both real dirs and symlinks."""
    if dest.is_symlink():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    elif dest.exists():
        dest.unlink()


def link_or_copy(src: Path, dest: Path, mode: str) -> str:
    """Place src at dest. Returns 'link' / 'copy' / 'fallback-copy'."""
    is_dir = src.is_dir()
    if mode == "link":
        try:
            os.symlink(src, dest, target_is_directory=is_dir)
            return "link"
        except (OSError, NotImplementedError) as exc:
            # Windows non-admin without dev mode + some enterprise filesystems
            # refuse symlinks. Fall back to copy with a warning.
            print(f"    ⚠ symlink failed for {src.name}: {exc}; copying instead")
            if is_dir:
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
            return "fallback-copy"
    if is_dir:
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return "copy"


# ---------------------------------------------------------------------------
# Per-target installers
# ---------------------------------------------------------------------------


def install_claude(
    repo_root: Path, claude_home: Path, mode: str, force: bool
) -> tuple[int, int, int]:
    """Install skills + agents into Claude's config tree."""
    skills_target = claude_home / "skills"
    agents_target = claude_home / "agents"
    skills_target.mkdir(parents=True, exist_ok=True)
    agents_target.mkdir(parents=True, exist_ok=True)

    skill_n = 0
    agent_n = 0
    skipped = 0

    for skill in sorted((repo_root / "skills").iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").exists():
            continue
        dest = skills_target / skill.name
        if (dest.exists() or dest.is_symlink()) and not force:
            skipped += 1
            continue
        _replace_existing(dest)
        link_or_copy(skill, dest, mode)
        skill_n += 1

    for agent in sorted((repo_root / "agents").glob("*.md")):
        dest = agents_target / agent.name
        if (dest.exists() or dest.is_symlink()) and not force:
            skipped += 1
            continue
        _replace_existing(dest)
        link_or_copy(agent, dest, mode)
        agent_n += 1

    return skill_n, agent_n, skipped


def install_gemini(
    repo_root: Path, gemini_home: Path, mode: str, force: bool
) -> tuple[int, int, bool]:
    """
    Install via `gemini skills link <path>` if the gemini CLI is on PATH.
    Otherwise create direct symlinks/copies under ~/.gemini/skills/.

    Returns (installed, skipped, used_gemini_cli).
    """
    has_gemini = shutil.which("gemini") is not None
    skills_target = gemini_home / "skills"
    skills_target.mkdir(parents=True, exist_ok=True)

    n = 0
    skipped = 0

    for skill in sorted((repo_root / "skills").iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").exists():
            continue
        if has_gemini:
            r = subprocess.run(
                ["gemini", "skills", "link", str(skill)],
                capture_output=True,
                text=True,
            )
            if r.returncode == 0:
                n += 1
            else:
                stderr = (r.stderr or "").strip().splitlines()
                first = stderr[0] if stderr else "(no stderr)"
                print(f"    ⚠ gemini skills link {skill.name}: {first}")
                skipped += 1
            continue

        dest = skills_target / skill.name
        if (dest.exists() or dest.is_symlink()) and not force:
            skipped += 1
            continue
        _replace_existing(dest)
        link_or_copy(skill, dest, mode)
        n += 1

    return n, skipped, has_gemini


COPILOT_AGENTS_MD = """\
# AGENTS.md

This is a cross-tool agent-context file consumed natively by:

- **GitHub Copilot CLI** — pass via `--instructions-file` or place at repo root
- **Codex CLI** — `@AGENTS.md` import in `~/.codex/CLAUDE.md`
- **Gemini CLI** — `@AGENTS.md` import in `~/.gemini/GEMINI.md`

## Skills + agents available on this machine

This file documents the canonical skills + agents tree that Claude Code uses.
For tools without a native skill concept (Copilot CLI, the VS Code Copilot
extension), this file points at the canonical location so the same context
is reachable.

- Skills: `~/.claude/skills/<name>/SKILL.md`
- Agents: `~/.claude/agents/<name>.md`

## VS Code Copilot per-project setup

VS Code's GitHub Copilot extension reads project-level instructions from:

  `<project-root>/.github/copilot-instructions.md`

For project-specific Copilot context, copy this file there or symlink:

```bash
ln -sfn ~/.claude/AGENTS.md <project-root>/.github/copilot-instructions.md
```

(On Windows from PowerShell:
`New-Item -ItemType SymbolicLink -Path .\\.github\\copilot-instructions.md -Target $env:USERPROFILE\\.claude\\AGENTS.md`)

## See also

- `~/.claude/skills/research-for-skills/cross-tool-portability/install-matrix.md`
  for the full per-tool install matrix.
"""


def install_copilot(repo_root: Path, claude_home: Path) -> bool:
    """
    Generate the AGENTS.md bridge at ~/.claude/AGENTS.md and print
    instructions for VS Code Copilot per-project setup.
    """
    target = claude_home / "AGENTS.md"
    if target.exists():
        print(f"    ⚠ {target} already exists — leaving as-is (use --force to overwrite)")
    else:
        claude_home.mkdir(parents=True, exist_ok=True)
        target.write_text(COPILOT_AGENTS_MD)
        print(f"    + wrote {target}")
    print(f"    For VS Code Copilot in a project, run:")
    print(f"      ln -sfn '{target}' <project-root>/.github/copilot-instructions.md")
    print(f"    (Windows: New-Item -ItemType SymbolicLink -Path '<project>\\.github\\copilot-instructions.md' -Target '{target}')")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="agent-foundry installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=TARGETS_HELP,
    )
    parser.add_argument(
        "--target",
        help="comma-separated single-letter codes or names "
             "(e.g. 'c,g' or 'claude,gemini'); 'a' or 'all' = everything",
        default=None,
    )
    parser.add_argument("--mode", choices=["link", "move"], default=None,
                        help="link = symlinks (recommended); move = copy")
    parser.add_argument("--claude-home", default=None,
                        help=f"override Claude config dir (default {DEFAULT_CLAUDE_HOME})")
    parser.add_argument("--gemini-home", default=None,
                        help=f"override Gemini config dir (default {DEFAULT_GEMINI_HOME})")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing skills/agents at the target")
    parser.add_argument("--noninteractive", action="store_true",
                        help="use defaults — claude + link mode — without prompting")
    args = parser.parse_args()

    banner()
    print()

    skill_n, agent_n = detect(REPO_ROOT)
    print(f"Repo root:    {REPO_ROOT}")
    print(f"Platform:     {sys.platform}")
    print(f"Python:       {sys.version.split()[0]}")
    print(f"Skills found: {skill_n}")
    print(f"Agents found: {agent_n}")
    print()

    if skill_n == 0 and agent_n == 0:
        print("⚠ no skills or agents found in this directory.")
        print(f"  expected: {REPO_ROOT / 'skills'} and {REPO_ROOT / 'agents'}")
        return 1

    # ---- Targets ----
    target_str = args.target
    if target_str is None and not args.noninteractive:
        print(TARGETS_HELP)
        target_str = ask("Choose targets", choices=["c", "g", "p", "a"], default="c")
    elif target_str is None:
        target_str = "claude"

    target_map = {"c": "claude", "g": "gemini", "p": "copilot",
                  "a": "all", "all": "all",
                  "claude": "claude", "gemini": "gemini", "copilot": "copilot"}
    raw = [t.strip().lower() for t in target_str.split(",") if t.strip()]
    targets: list[str] = []
    for t in raw:
        if t not in target_map:
            print(f"⚠ unknown target {t!r}; expected one of {list(target_map)}")
            return 1
        mapped = target_map[t]
        if mapped == "all":
            targets = ["claude", "gemini", "copilot"]
            break
        if mapped not in targets:
            targets.append(mapped)

    # ---- Mode ----
    mode = args.mode
    if mode is None and any(t in targets for t in ("claude", "gemini")):
        if args.noninteractive:
            mode = "link"
        else:
            print()
            print("Install mode:")
            print("  l = link  (symlinks; edits in agent-foundry propagate; recommended for dev)")
            print("  m = move  (copy; independent; agent-foundry edits don't propagate)")
            mode_choice = ask("Choose", choices=["l", "m"], default="l")
            mode = "link" if mode_choice == "l" else "move"
    elif mode is None:
        mode = "link"

    # ---- Paths ----
    claude_home = Path(args.claude_home).expanduser() if args.claude_home else DEFAULT_CLAUDE_HOME
    gemini_home = Path(args.gemini_home).expanduser() if args.gemini_home else DEFAULT_GEMINI_HOME

    if not args.noninteractive:
        if "claude" in targets:
            override = ask(f"Claude config dir override (Enter to keep {claude_home})", default="")
            if override:
                claude_home = Path(override).expanduser()
        if "gemini" in targets:
            override = ask(f"Gemini config dir override (Enter to keep {gemini_home})", default="")
            if override:
                gemini_home = Path(override).expanduser()

    # ---- Confirm ----
    print()
    print("=" * 60)
    print("Plan:")
    if "claude" in targets:
        print(f"  Claude  ({mode}): {REPO_ROOT/'skills'} → {claude_home/'skills'}")
        print(f"                    {REPO_ROOT/'agents'} → {claude_home/'agents'}")
    if "gemini" in targets:
        gemini_via = "via `gemini skills link`" if shutil.which("gemini") else "direct symlink (no `gemini` on PATH)"
        print(f"  Gemini  ({mode}, {gemini_via}): {REPO_ROOT/'skills'} → {gemini_home/'skills'}")
    if "copilot" in targets:
        print(f"  Copilot (AGENTS.md bridge): write {claude_home/'AGENTS.md'}")
    print("=" * 60)

    if not args.noninteractive:
        if not confirm("Proceed?", default=False):
            print("cancelled.")
            return 0

    # ---- Execute ----
    print()
    if "claude" in targets:
        print("[Claude]")
        sc, ac, sk = install_claude(REPO_ROOT, claude_home, mode, args.force)
        print(f"  ✓ {sc} skills, {ac} agents installed (skipped {sk} existing — use --force to overwrite)")
    if "gemini" in targets:
        print("[Gemini]")
        n, sk, used_cli = install_gemini(REPO_ROOT, gemini_home, mode, args.force)
        if not used_cli:
            print(f"  ⚠ `gemini` CLI not found on PATH; used direct {mode} fallback")
        print(f"  ✓ {n} skills (skipped {sk})")
    if "copilot" in targets:
        print("[Copilot]")
        install_copilot(REPO_ROOT, claude_home)

    print()
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
