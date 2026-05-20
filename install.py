#!/usr/bin/env python3
"""
agent-foundry installer.

Moves or symlinks skills + agents + commands from a cloned agent-foundry repo
into the config tree(s) of one or more AI CLIs you have installed:

    - Claude Code CLI    (~/.claude/{skills,agents,commands}/)
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

# REPO_ROOT auto-detection:
# - Bundled mode (public agent-foundry): install.py lives next to skills/agents/commands.
# - Dev mode (skill_factory/installer/): those siblings live in the parent directory.
_HERE = Path(__file__).resolve().parent
if any((_HERE / d).exists() for d in ("skills", "agents", "commands")):
    REPO_ROOT = _HERE                  # bundled mode
elif any((_HERE.parent / d).exists() for d in ("skills", "agents", "commands")):
    REPO_ROOT = _HERE.parent           # dev mode (script lives in installer/)
else:
    REPO_ROOT = _HERE                  # fall back; the "nothing found" check below will warn cleanly

TARGETS_HELP = """\
Targets:
  c = Claude Code CLI         (~/.claude/skills/, ~/.claude/agents/, ~/.claude/commands/)
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


def check_claude_cli() -> tuple[bool, str | None]:
    """Probe for the `claude` CLI on PATH. Returns (found, version_or_None)."""
    cli = shutil.which("claude")
    if not cli:
        return False, None
    try:
        r = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=5)
        version = (r.stdout or r.stderr or "").strip().splitlines()
        return True, version[0] if version else "(unknown version)"
    except (subprocess.SubprocessError, OSError):
        return True, "(version probe failed)"


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


# Tokens that almost certainly mean "user thought this was a y/N prompt".
# We refuse them as path overrides and re-prompt so we don't end up creating
# directories named `y/`, `n/`, `yes/`, etc. (real bug report 2026-05-18).
_NOT_A_PATH = frozenset({"y", "n", "yes", "no", "ok", "true", "false"})


def _ask_path_override(label: str, default_path: Path) -> Path:
    """Prompt for a path override; re-ask if the user types a y/N-style answer.

    Empty input → keep the default (returned unchanged). A typed path is
    expanded with `~`. If the user types `y`, `n`, `yes`, `no`, etc. we
    show a hint and re-prompt rather than silently treating it as a path.
    """
    prompt = f"{label} config dir override (press Enter to KEEP {default_path}, or paste a NEW path)"
    while True:
        raw = ask(prompt, default="")
        if not raw:
            return default_path
        if raw.lower() in _NOT_A_PATH:
            print(f"  ⚠ {raw!r} isn't a path — press Enter to keep {default_path}, or type the new directory.")
            continue
        return Path(raw).expanduser()


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


def detect(repo_root: Path) -> tuple[int, int, int]:
    skills = repo_root / "skills"
    agents = repo_root / "agents"
    commands = repo_root / "commands"
    skill_count = (
        sum(1 for d in skills.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
        if skills.exists()
        else 0
    )
    agent_count = sum(1 for f in agents.glob("*.md")) if agents.exists() else 0
    command_count = sum(1 for f in commands.glob("*.md")) if commands.exists() else 0
    return skill_count, agent_count, command_count


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


# Module-level state: once a symlink fails with a privilege/unsupported error
# on this host, stop trying for the rest of the run and copy directly. This
# turns a wall of 160 identical warnings into a single actionable note.
_SYMLINK_DISABLED_FOR_RUN = False


def _is_symlink_privilege_error(exc: BaseException) -> bool:
    """Return True if the OSError looks like Windows symlink privilege missing.

    WinError 1314 = SeCreateSymbolicLinkPrivilege not held by the process.
    Triggered when not running as Administrator AND Developer Mode is OFF.
    """
    s = str(exc).lower()
    if "1314" in s or "privilege is not held" in s:
        return True
    # POSIX EPERM on filesystems that don't support symlinks (rare).
    if getattr(exc, "errno", None) == 1 and isinstance(exc, OSError):
        return True
    return False


def link_or_copy(src: Path, dest: Path, mode: str) -> str:
    """Place src at dest. Returns 'link' / 'copy' / 'fallback-copy'."""
    global _SYMLINK_DISABLED_FOR_RUN
    is_dir = src.is_dir()
    if mode == "link" and not _SYMLINK_DISABLED_FOR_RUN:
        try:
            os.symlink(src, dest, target_is_directory=is_dir)
            return "link"
        except (OSError, NotImplementedError) as exc:
            if _is_symlink_privilege_error(exc):
                # First failure: print one actionable note, then suppress for the rest of the run.
                _SYMLINK_DISABLED_FOR_RUN = True
                print()
                print("    ⚠ Windows symlink privilege missing (WinError 1314).")
                print("      Falling back to COPY for all remaining items.")
                print("      To enable symlinks, EITHER:")
                print("        • run this installer from an elevated (Administrator) shell, OR")
                print("        • enable Developer Mode: Settings → Privacy & Security → For developers")
                print("        • or just rerun with --mode move to skip symlinks entirely")
                print()
            else:
                print(f"    ⚠ symlink failed for {src.name}: {exc}; copying instead")
            # fall through to copy
    if is_dir:
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return "fallback-copy" if mode == "link" else "copy"
    if is_dir:
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return "copy"


# ---------------------------------------------------------------------------
# Per-target installers
# ---------------------------------------------------------------------------


def install_claude(
    repo_root: Path, claude_home: Path, mode: str, skip_existing: bool
) -> tuple[int, int, int, int, int]:
    """Install skills + agents + commands into Claude's config tree.

    Default behavior REPLACES existing entries at the destination (any kind:
    file, dir, or symlink — see _replace_existing). Pass skip_existing=True
    to opt into the old behavior of leaving existing entries untouched.

    Returns (skill_n, agent_n, command_n, replaced_or_skipped, chmodded).
    """
    skills_target = claude_home / "skills"
    agents_target = claude_home / "agents"
    commands_target = claude_home / "commands"
    skills_target.mkdir(parents=True, exist_ok=True)
    agents_target.mkdir(parents=True, exist_ok=True)
    commands_target.mkdir(parents=True, exist_ok=True)

    skill_n = 0
    agent_n = 0
    command_n = 0
    touched_existing = 0  # replaced (default) or skipped (skip_existing)

    def place(src: Path, dest: Path) -> bool:
        """Place src at dest. Returns True if installed, False if skipped."""
        nonlocal touched_existing
        existed = dest.exists() or dest.is_symlink()
        if skip_existing and existed:
            touched_existing += 1
            return False
        if existed:
            touched_existing += 1
        _replace_existing(dest)
        link_or_copy(src, dest, mode)
        return True

    for skill in sorted((repo_root / "skills").iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").exists():
            continue
        if place(skill, skills_target / skill.name):
            skill_n += 1

    for agent in sorted((repo_root / "agents").glob("*.md")):
        if place(agent, agents_target / agent.name):
            agent_n += 1

    commands_dir = repo_root / "commands"
    if commands_dir.exists():
        for command in sorted(commands_dir.glob("*.md")):
            if place(command, commands_target / command.name):
                command_n += 1

    chmodded = 0
    if sys.platform != "win32":
        chmodded = chmod_scripts(skills_target)

    return skill_n, agent_n, command_n, touched_existing, chmodded


def chmod_scripts(skills_root: Path) -> int:
    """Ensure shell/python scripts inside *copied* skills are executable.

    Walks copied skills only — symlinked skills are skipped because their
    targets live in the source repo's working tree, which we should never
    mutate. On POSIX, copy-installed scripts can lose +x on filesystems that
    don't honor git's executable bit; this restores it. Idempotent — already
    +x files are left alone.

    Returns the count of files whose mode was changed.
    """
    if not skills_root.exists():
        return 0
    changed = 0
    extensions = {".sh", ".bash", ".py"}
    for skill in skills_root.iterdir():
        # Skip symlinked skill installs — chmod would follow into the source repo.
        if skill.is_symlink() or not skill.is_dir():
            continue
        scripts_dir = skill / "scripts"
        if not scripts_dir.is_dir() or scripts_dir.is_symlink():
            continue
        for f in scripts_dir.rglob("*"):
            if f.is_symlink() or not f.is_file() or f.suffix.lower() not in extensions:
                continue
            try:
                mode = f.stat().st_mode
                if mode & 0o100:  # already executable for owner; skip
                    continue
                f.chmod(mode | 0o111)
                changed += 1
            except OSError:
                continue  # broken symlink, permission denied, etc.
    return changed


def install_gemini(
    repo_root: Path, gemini_home: Path, mode: str, force: bool
) -> tuple[int, int, bool]:
    """
    Install via `gemini skills link <path>` if the gemini CLI is on PATH.
    Otherwise create direct symlinks/copies under ~/.gemini/skills/.

    Returns (installed, skipped, used_gemini_cli).
    """
    gemini_cli = shutil.which("gemini")
    has_gemini = gemini_cli is not None
    # On Windows, `shutil.which` typically returns `gemini.cmd` / `gemini.bat`.
    # `subprocess.run([...])` with a bare name fails (CreateProcess doesn't search
    # for .cmd/.bat extensions), and even with the full path, batch files need
    # cmd.exe to actually execute. Wrap accordingly.
    needs_cmd_wrap = (
        sys.platform == "win32"
        and gemini_cli is not None
        and gemini_cli.lower().endswith((".cmd", ".bat"))
    )
    skills_target = gemini_home / "skills"
    skills_target.mkdir(parents=True, exist_ok=True)

    n = 0
    skipped = 0
    gemini_cli_unusable = False  # flips True if the first invocation FileNotFoundErrors

    for skill in sorted((repo_root / "skills").iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").exists():
            continue
        if has_gemini and not gemini_cli_unusable:
            if needs_cmd_wrap:
                cmd_args = ["cmd.exe", "/c", gemini_cli, "skills", "link", str(skill)]
            else:
                cmd_args = [gemini_cli, "skills", "link", str(skill)]
            try:
                r = subprocess.run(cmd_args, capture_output=True, text=True)
            except (FileNotFoundError, OSError) as exc:
                # Gemini CLI is on PATH per shutil.which but unexecutable from here.
                # Fall through to the direct-symlink branch for this and remaining skills.
                print(f"    ⚠ gemini CLI present but unexecutable ({exc}); using direct {mode} fallback")
                gemini_cli_unusable = True
            else:
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

    return n, skipped, has_gemini and not gemini_cli_unusable


COPILOT_AGENTS_MD = """\
# Copilot CLI instructions (cross-tool agent context)

Loaded natively by GitHub Copilot CLI (`@github/copilot`) from any of:

- `.github/copilot-instructions.md`     (per-repo; `copilot init` bootstraps it)
- `AGENTS.md`                           (per-repo, repo root)
- `~/.copilot/copilot-instructions.md`  (user-global — this file when written there)

Verified by the `--no-custom-instructions` flag in `copilot --help`: Copilot
CLI reads `AGENTS.md` natively. No bridge or import syntax is required.

**Model selection:** Copilot CLI supports `--model <model>` — pick from the
Claude / GPT / Gemini variants available on your subscription. Instructions
in this file apply across every backend.

## Skills + agents on this machine

Claude Code's canonical tree (this is also what `agent-foundry` ships):

- Skills: `~/.claude/skills/<name>/SKILL.md`
- Agents: `~/.claude/agents/<name>.md`

| Tool        | Discovery                                                          |
|-------------|--------------------------------------------------------------------|
| Claude Code | auto, from `~/.claude/skills/`                                     |
| Gemini CLI  | `gemini skills link <path>` per skill (or `~/.gemini/skills/`)     |
| Copilot CLI | this file + per-repo `AGENTS.md` / `.github/copilot-instructions.md` |
| Codex CLI   | symlinks under `~/.codex/skills/<name>/`                           |

Skills are auto-discovered by Claude Code from frontmatter `description:`.
For Copilot, you can reference specific skills inline by reading their
`SKILL.md` files when relevant — Copilot has no native skill concept but
will treat this file's content as system context.

## Useful Copilot CLI invocations

```
copilot                                 # interactive mode
copilot -p "rewrite this function"      # headless, one-shot
copilot --model claude-sonnet-4 ...     # explicit model
copilot --no-custom-instructions ...    # disable AGENTS.md loading
copilot mcp list                        # list MCP servers
copilot init                            # bootstrap .github/copilot-instructions.md
```

Copilot's MCP config: `~/.copilot/mcp-config.json` (user-level) and
`.mcp.json` / `.vscode/mcp.json` (workspace). The built-in `github-mcp-server`
is enabled by default — disable with `--disable-builtin-mcps`.

## VS Code Copilot Chat (extension, not CLI)

The VS Code Copilot extension reads `<project>/.github/copilot-instructions.md`.
Same content, different path. To reuse this file project-wide:

```bash
ln -sfn ~/.copilot/copilot-instructions.md <project>/.github/copilot-instructions.md
```

(Windows PowerShell:
`New-Item -ItemType SymbolicLink -Path .\\.github\\copilot-instructions.md -Target $env:USERPROFILE\\.copilot\\copilot-instructions.md`)

## See also

- `~/.claude/skills/gh-copilot-cli/SKILL.md` — full Copilot CLI reference
- `~/.claude/skills/research-for-skills/cross-tool-portability/install-matrix.md`
"""


def install_copilot(repo_root: Path, force: bool = False) -> bool:
    """
    Install GitHub Copilot CLI integration.

    Copilot CLI (`@github/copilot`) reads instructions from (precedence order):
      1. .github/copilot-instructions.md  (per-repo; `copilot init` bootstraps it)
      2. AGENTS.md                        (per-repo, repo root)
      3. ~/.copilot/copilot-instructions.md  (user-global)

    Per the verified `--no-custom-instructions` flag in `copilot --help`,
    Copilot CLI loads AGENTS.md natively (no bridge or import syntax needed).

    We write the user-global file so Copilot has cross-tool context regardless
    of which project you're in. Per-project setup is left to `copilot init`
    (Copilot's own bootstrap, runs read-only repo analysis).

    Note: Copilot CLI supports `--model <model>` (Claude / GPT / Gemini
    variants depending on subscription). Instructions in this file apply
    across every backend.
    """
    copilot_dir = Path.home() / ".copilot"
    copilot_dir.mkdir(parents=True, exist_ok=True)
    target = copilot_dir / "copilot-instructions.md"

    if target.exists() and not force:
        print(f"    ⚠ {target} already exists — leaving as-is (use --force to overwrite)")
    else:
        target.write_text(COPILOT_AGENTS_MD)
        print(f"    + wrote {target}")

    has_copilot = shutil.which("copilot") is not None
    if not has_copilot:
        print(f"    ⚠ `copilot` not found on PATH; install via:")
        print(f"      npm install -g @github/copilot")
    print(f"    Per-project setup: cd <project> && copilot init")
    print(f"      (or copy/symlink {target.name} → <project>/AGENTS.md)")
    print(f"    Model selection:   copilot --model <name>   (Claude / GPT / Gemini)")
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
                        help="(no-op; replace-existing is now the default — kept for backward compat)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="leave existing skills/agents/commands at the target untouched (old --force=False behavior)")
    parser.add_argument("--noninteractive", action="store_true",
                        help="use defaults — claude + link mode — without prompting")
    args = parser.parse_args()

    banner()
    print()

    skill_n, agent_n, command_n = detect(REPO_ROOT)
    has_claude, claude_version = check_claude_cli()
    print(f"Repo root:      {REPO_ROOT}")
    print(f"Platform:       {sys.platform}")
    print(f"Python:         {sys.version.split()[0]}")
    print(f"Claude CLI:     {claude_version if has_claude else 'NOT FOUND on PATH'}")
    print(f"Skills found:   {skill_n}")
    print(f"Agents found:   {agent_n}")
    print(f"Commands found: {command_n}")
    print()
    if not has_claude:
        print("⚠ `claude` CLI not on PATH — install with:")
        print("    curl -fsSL https://claude.ai/install.sh | bash")
        print("  (or see https://docs.claude.com/en/docs/claude-code/setup)")
        print("  Continuing — files will land at ~/.claude/ and be picked up once `claude` is installed.")
        print()

    if skill_n == 0 and agent_n == 0 and command_n == 0:
        print("⚠ no skills, agents, or commands found in this directory.")
        print(f"  expected: {REPO_ROOT / 'skills'}, {REPO_ROOT / 'agents'}, or {REPO_ROOT / 'commands'}")
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
            claude_home = _ask_path_override("Claude", claude_home)
        if "gemini" in targets:
            gemini_home = _ask_path_override("Gemini", gemini_home)

    # ---- Confirm ----
    print()
    print("=" * 60)
    print("Plan:")
    if "claude" in targets:
        print(f"  Claude  ({mode}): {REPO_ROOT/'skills'}   → {claude_home/'skills'}")
        print(f"                    {REPO_ROOT/'agents'}   → {claude_home/'agents'}")
        print(f"                    {REPO_ROOT/'commands'} → {claude_home/'commands'}")
    if "gemini" in targets:
        gemini_via = "via `gemini skills link`" if shutil.which("gemini") else "direct symlink (no `gemini` on PATH)"
        print(f"  Gemini  ({mode}, {gemini_via}): {REPO_ROOT/'skills'} → {gemini_home/'skills'}")
    if "copilot" in targets:
        print(f"  Copilot: write {Path.home()/'.copilot'/'copilot-instructions.md'} (user-global; native AGENTS.md format; supports --model Claude/GPT/Gemini)")
    if args.skip_existing:
        print("  Existing entries at the targets will be KEPT (--skip-existing).")
    else:
        print("  Existing entries at the targets will be REPLACED. Pass --skip-existing to keep them.")
    print("=" * 60)

    if not args.noninteractive:
        if not confirm("Proceed?", default=False):
            print("cancelled.")
            return 0

    # ---- Execute ----
    # Default: replace existing entries. `--skip-existing` keeps them.
    # `--force` is preserved as a no-op for backward compat (replacement is now the default).
    skip_existing = bool(args.skip_existing)
    print()
    if "claude" in targets:
        print("[Claude]")
        sc, ac, cc, te, chm = install_claude(REPO_ROOT, claude_home, mode, skip_existing)
        verb = "kept" if skip_existing else "replaced"
        print(f"  ✓ {sc} skills, {ac} agents, {cc} commands installed ({te} {verb} existing)")
        if chm:
            print(f"    + chmod +x on {chm} skill scripts")
    if "gemini" in targets:
        print("[Gemini]")
        # install_gemini still uses `force`-style semantics; pass not-skip to mean replace.
        n, sk, used_cli = install_gemini(REPO_ROOT, gemini_home, mode, not skip_existing)
        if not used_cli:
            print(f"  ⚠ `gemini` CLI not found on PATH; used direct {mode} fallback")
        print(f"  ✓ {n} skills (skipped {sk})")
    if "copilot" in targets:
        print("[Copilot]")
        install_copilot(REPO_ROOT, force=not skip_existing)

    print()
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
