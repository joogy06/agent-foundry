#!/usr/bin/env python3
"""
agent-foundry installer.

Scans the host, shows a findings report, and ADAPTS the install — placing
skills + agents + commands from a cloned agent-foundry repo into the config
tree(s) of whichever AI CLIs you actually have installed:

    - Claude Code CLI    (~/.claude/{skills,agents,commands}/ AND the two files
                          that ACTIVATE the ecosystem: ~/.claude/CLAUDE.md +
                          ~/.claude/settings.json with the 6 SessionStart hooks —
                          create-if-absent / inject-missing-hooks by default,
                          --force-global-config to replace)
    - GitHub Copilot CLI (~/.claude/skills/ is auto-discovered by Copilot CLI
                          and VS Code 1.123+; plus ~/.copilot/ instructions and
                          an optional ~/.copilot/skills/ mirror)
    - Antigravity CLI    (`agy` — host directive at ~/.gemini/agy.md)
    - Gemini CLI         (SKILLS ONLY — a live target for legacy enterprise systems
                          that read the skill library. NOT a delegate: agy replaced it
                          on 2026-07-25 and foundry passes it no work.)

The scan uses OR'd detection (PATH lookup OR known install locations OR config
dir) so it sees CLIs that aren't on the installer process's PATH (npm-global,
~/.local/bin, GUI-app shims). Every probe is bounded (stdin closed + timeout);
no version number is ever hard-coded — the installer PRINTS the probed version.

Tested on Linux + macOS + Windows 10/11. Pure-stdlib Python 3.8+ — no
dependencies. Works standalone in a fresh agent-foundry clone with no
~/.claude/skills present and no env-adoption tooling.

Usage
-----

    python3 install.py                                       # interactive (scans + adapts)
    python3 install.py --noninteractive                      # claude + link, no prompts
    python3 install.py --auto                                # install into ALL detected CLIs
    python3 install.py --target claude --mode link
    python3 install.py --target claude,gemini --mode move --force
    python3 install.py --claude-home /opt/claude --target claude
    python3 install.py --scan-only                           # show findings report and exit
"""
from __future__ import annotations

import argparse
import collections
import copy
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

# Installer version (§11 A7). Read by the provenance manifest's
# `installer_version` field, so a manifest can always be traced back to the
# code that wrote it. Bump on any change to what the installer PLACES or to the
# manifest schema; `source_rev` (the git sha) carries the finer-grained
# provenance between bumps.
__version__ = "1.0.0"

# REPO_ROOT auto-detection:
# - Root layout (this repo + public agent-foundry): install.py lives at the repo
#   root, next to skills/agents/commands.
# - Legacy dev layout (script in an installer/ subdir): those siblings live in
#   the parent. Kept as a harmless fallback so an older checkout still works.
_HERE = Path(__file__).resolve().parent
if any((_HERE / d).exists() for d in ("skills", "agents", "commands")):
    REPO_ROOT = _HERE                  # root layout (install.py at repo root)
elif any((_HERE.parent / d).exists() for d in ("skills", "agents", "commands")):
    REPO_ROOT = _HERE.parent           # legacy: script in an installer/ subdir
else:
    REPO_ROOT = _HERE                  # fall back; the "nothing found" check below will warn cleanly

# Bundled templates (agy.md host directive, etc.) live in templates/ next to this
# script at the repo root.
_TEMPLATES_DIR = _HERE / "templates"

TARGETS_HELP = """\
Targets:
  c = Claude Code CLI         (~/.claude/skills/, ~/.claude/agents/, ~/.claude/commands/)
  p = GitHub Copilot CLI      (~/.copilot/ instructions + optional ~/.copilot/skills/ mirror;
                               note: ~/.claude/skills/ is already auto-discovered by Copilot CLI
                               and VS Code 1.123+ — no bridge needed)
  y = Antigravity CLI (agy)   (host directive at ~/.gemini/agy.md — primary delegate)
  g = Gemini CLI              (SKILLS ONLY — legacy enterprise systems read ~/.gemini/skills/; foundry passes it no work)
  a = All of the above
  auto = install into every CLI the scan actually detected
"""

DEFAULT_CLAUDE_HOME = Path.home() / ".claude"
DEFAULT_GEMINI_HOME = Path.home() / ".gemini"
DEFAULT_COPILOT_HOME = Path.home() / ".copilot"

# Overall wall-clock budget for the whole environment scan. Once exceeded,
# remaining version probes are skipped (detection still reports found/not-found
# from path/known-location/config-dir, which need no subprocess).
SCAN_BUDGET_SECONDS = 25.0
PROBE_TIMEOUT_SECONDS = 5
# Optional-dependency installs (#240) reach the network and can be slow on a cold
# cache or a corporate proxy. Generous, because the alternative — a half-finished
# pip run killed mid-download — is worse than waiting.
EXTRAS_INSTALL_TIMEOUT = 900


# ---------------------------------------------------------------------------
# Run-log (Tee) — §8b
# ---------------------------------------------------------------------------
#
# A persistent debug log so a misbehaving run on a varied machine leaves a
# debuggable artifact. The RunLogger TEES sys.stdout + sys.stderr (it does NOT
# replace them), so every existing print() reaches the user UNCHANGED and is
# also mirrored to logs/install-<UTC-ts>.log (next to this script).
#
# HARD: logging MUST NEVER break the install. Log-dir/file creation is wrapped
# in try/except; an unwritable logs/ falls back to the OS temp dir with a
# one-line warning, never aborting. NO secrets: only the already-printed scan
# and step output are captured — os.environ is NEVER dumped.

# Where logs/ lives (next to this script, at the repo root).
DEFAULT_LOG_DIR = _HERE / "logs"


def _force_utf8_streams() -> None:
    """Make stdout/stderr tolerate the Unicode glyphs the installer prints
    (→, ⚠, ✓, 📝, …) on hosts whose console defaults to a non-UTF-8 codec.

    On Windows the console (and a piped/redirected stream) commonly resolves to
    cp1252/cp437, which cannot encode those characters — an unguarded print()
    then raises UnicodeEncodeError and aborts the whole install (a real crash on
    Windows 11, Python 3.14). We reconfigure both streams to UTF-8 with
    errors='replace', so worst case a glyph degrades to '?' instead of killing
    the run. Called ONCE at the top of main(), before RunLogger captures the
    stream references (reconfigure mutates the TextIOWrapper in place, so the
    captured references stay valid). NEVER raises."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # already-wrapped / non-TextIOWrapper stream — leave it
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # never let stream setup break the install


def _utc_stamp() -> str:
    """Filename-safe UTC timestamp, e.g. 2026-06-08T21-30-00Z."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H-%M-%SZ")


def _git_sha(repo_root: Path) -> str | None:
    """Best-effort short git sha of the installer repo; None if unavailable.
    Bounded + stdin-closed; never raises."""
    git = shutil.which("git")
    if not git:
        return None
    try:
        r = subprocess.run(
            [git, "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
    except (subprocess.SubprocessError, OSError):
        return None
    if r.returncode != 0:
        return None
    sha = (r.stdout or "").strip()
    return sha or None


class _TeeStream:
    """A write-through proxy: every write goes to the real stream AND the log
    file. Failures writing to the log are swallowed (the user's stream must
    never be impacted by a logging problem)."""

    def __init__(self, real, logfile):
        self._real = real
        self._logfile = logfile

    def write(self, data):
        # The real stream first — the user's experience is sacred.
        try:
            n = self._real.write(data)
        except UnicodeEncodeError:
            # A console whose codec can't encode a glyph (cp1252/cp437 on
            # Windows) must degrade, never crash — _force_utf8_streams() is the
            # primary guard; this is the fallback if the stream refused it.
            enc = getattr(self._real, "encoding", None) or "ascii"
            safe = data.encode(enc, "replace").decode(enc, "replace")
            n = self._real.write(safe)
        try:
            if self._logfile is not None:
                self._logfile.write(data)
        except Exception:
            pass  # never let a logging failure surface to the caller
        return n

    def flush(self):
        try:
            self._real.flush()
        except Exception:
            pass
        try:
            if self._logfile is not None:
                self._logfile.flush()
        except Exception:
            pass

    # Pass-through niceties so libraries probing the stream don't choke.
    def isatty(self):
        try:
            return self._real.isatty()
        except Exception:
            return False

    def __getattr__(self, name):
        return getattr(self._real, name)


class RunLogger:
    """Tee sys.stdout + sys.stderr to a run-log file. Use as a context manager:

        with RunLogger(sys.argv, log_path=args.log, enabled=not args.no_log,
                       repo_root=REPO_ROOT, header_title="agent-foundry installer"):
            ...                       # all print()/Out output is tee'd

    `enabled=False` → a transparent no-op (no file, streams untouched, the
    'Full log' footer is suppressed). The constructor NEVER raises.
    """

    def __init__(self, argv, log_path=None, enabled=True, repo_root=None,
                 header_title="agent-foundry"):
        self.argv = list(argv)
        self.enabled = enabled
        self.repo_root = Path(repo_root) if repo_root else _HERE
        self.header_title = header_title
        self.log_path: Path | None = None
        self.fell_back = False
        self._fallback_reason = ""
        self._logfile = None
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        self._orig_excepthook = sys.excepthook
        self._active = False
        if not enabled:
            return
        # Resolve + open, with the never-abort fallback chain.
        self._open(log_path)

    # ---- open / fallback -------------------------------------------------

    def _open(self, log_path) -> None:
        primary = Path(log_path).expanduser() if log_path else (
            DEFAULT_LOG_DIR / f"install-{_utc_stamp()}.log")
        try:
            self._logfile = self._try_open(primary)
            self.log_path = primary
            return
        except Exception as exc:  # unwritable dir / read-only clone / perm denied
            self._fallback_reason = str(exc)
        # Fallback: OS temp dir. Must not abort the install.
        try:
            fb = Path(tempfile.gettempdir()) / f"agent-foundry-install-{_utc_stamp()}.log"
            self._logfile = self._try_open(fb)
            self.log_path = fb
            self.fell_back = True
        except Exception:
            # Even the temp dir failed — give up on logging entirely, but the
            # install proceeds with un-tee'd streams.
            self._logfile = None
            self.log_path = None

    @staticmethod
    def _try_open(path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Probe writability explicitly so a read-only dir raises HERE (caught by
        # _open) rather than later mid-run.
        return open(path, "w", encoding="utf-8")

    # ---- lifecycle -------------------------------------------------------

    def __enter__(self) -> "RunLogger":
        if not self.enabled:
            return self
        if self._logfile is not None:
            sys.stdout = _TeeStream(self._orig_stdout, self._logfile)
            sys.stderr = _TeeStream(self._orig_stderr, self._logfile)
            sys.excepthook = self._excepthook
            self._active = True
        # Warn (to the user, and tee'd) if we fell back — one line, never fatal.
        if self.fell_back:
            print(f"  ! run-log: default logs dir unwritable "
                  f"({self._fallback_reason or 'permission denied'}); "
                  f"logging to {self.log_path} instead")
        self._write_header()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # If an exception is propagating and our excepthook didn't fire (it only
        # fires for truly-uncaught exceptions at interpreter exit), record it.
        if exc is not None and self._logfile is not None:
            try:
                self._logfile.write("\n--- exception ---\n")
                traceback.print_exception(exc_type, exc, tb, file=self._logfile)
            except Exception:
                pass
        self._write_footer()
        self._restore()
        return False  # never suppress exceptions

    def _restore(self) -> None:
        if self._active:
            sys.stdout = self._orig_stdout
            sys.stderr = self._orig_stderr
            sys.excepthook = self._orig_excepthook
            self._active = False
        if self._logfile is not None:
            try:
                self._logfile.flush()
                self._logfile.close()
            except Exception:
                pass

    # ---- excepthook ------------------------------------------------------

    def _excepthook(self, exc_type, exc, tb):
        # Capture an otherwise-uncaught traceback into the log, then defer to the
        # original hook so the user still sees it on the terminal.
        if self._logfile is not None:
            try:
                self._logfile.write("\n--- uncaught exception ---\n")
                traceback.print_exception(exc_type, exc, tb, file=self._logfile)
                self._logfile.flush()
            except Exception:
                pass
        self._orig_excepthook(exc_type, exc, tb)

    # ---- header / footer -------------------------------------------------

    def _write_header(self) -> None:
        if self._logfile is None:
            return
        sha = _git_sha(self.repo_root)
        # NOTE: argv ONLY — never os.environ (no secrets).
        lines = [
            "=" * 78,
            f"{self.header_title} — run log",
            "=" * 78,
            f"UTC:      {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
            f"repo:     {self.repo_root}",
            f"git-sha:  {sha or '(unavailable)'}",
            f"OS:       {_os_release()}  ({sys.platform})",
            f"python:   {sys.version.split()[0]}",
            f"argv:     {' '.join(self.argv)}",
            "=" * 78,
            "",
        ]
        try:
            self._logfile.write("\n".join(lines))
            self._logfile.flush()
        except Exception:
            pass

    def _write_footer(self) -> None:
        # The 'Full log' line goes through sys.stdout (still tee'd here if active)
        # so the USER sees the path at the very end AND it's recorded in the file.
        if self.enabled and self.log_path is not None:
            print(f"\n\U0001F4DD Full log: {self.log_path}")


def add_log_args(parser: argparse.ArgumentParser) -> None:
    """Register the shared run-log flags on an argparse parser (§8b)."""
    parser.add_argument("--no-log", action="store_true",
                        help="disable the run-log file (logging is on by default)")
    parser.add_argument("--log", default=None, metavar="PATH",
                        help="write the run-log to PATH (default: logs/install-<UTC-ts>.log)")


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


def detect(repo_root: Path) -> tuple[int, int, int, int]:
    skills = repo_root / "skills"
    agents = repo_root / "agents"
    commands = repo_root / "commands"
    workflows = repo_root / "workflows"
    skill_count = (
        sum(1 for d in skills.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
        if skills.exists()
        else 0
    )
    agent_count = sum(1 for f in agents.glob("*.md")) if agents.exists() else 0
    command_count = sum(1 for f in commands.glob("*.md")) if commands.exists() else 0
    workflow_count = sum(1 for f in workflows.glob("*.js")) if workflows.exists() else 0
    return skill_count, agent_count, command_count, workflow_count


# ---------------------------------------------------------------------------
# Environment scan (scan → report → adapt)
# ---------------------------------------------------------------------------
#
# scan_environment() is pure-stdlib and self-contained. It deliberately does
# NOT call probe.sh (which needs jq+bash, writes inventory.json, and shells to
# skills that are absent in a fresh agent-foundry clone). Detection always runs
# inline so the installer works standalone.


def _user_base_bin() -> Path:
    """`<python user-base>/bin` (e.g. ~/.local/bin) — where `pip install --user`
    drops console scripts. Cheap, no subprocess."""
    try:
        import site
        return Path(site.getuserbase()) / ("Scripts" if sys.platform == "win32" else "bin")
    except Exception:
        return Path.home() / ".local" / "bin"


def _appdata() -> Path | None:
    val = os.environ.get("APPDATA")
    return Path(val) if val else None


def _localappdata() -> Path | None:
    val = os.environ.get("LOCALAPPDATA")
    return Path(val) if val else None


def run_probe(argv: list[str], timeout: int = PROBE_TIMEOUT_SECONDS) -> tuple[int, str]:
    """The ONE bounded runner for ALL version/identity probes.

    Hardened against the failure modes the 3-model review flagged:
      - stdin=DEVNULL  → never hangs on a CLI that reads stdin until EOF
                         (the agy-headless-hang class).
      - timeout        → bounded; a wedged probe can't stall the scan.
      - .cmd/.bat wrap → on Windows, batch-file shims need cmd.exe to run
                         (CreateProcess won't find/execute .cmd directly).

    Returns (returncode, combined_stdout_or_stderr_first_line). On any failure
    returns (-1, "") so callers degrade to "(version probe failed)" rather than
    raising.
    """
    if not argv:
        return -1, ""
    exe = argv[0]
    real_argv = argv
    # Windows: a resolved .cmd/.bat path must be run via cmd.exe /c.
    if sys.platform == "win32" and isinstance(exe, str) and exe.lower().endswith((".cmd", ".bat")):
        real_argv = ["cmd.exe", "/c", *argv]
    try:
        r = subprocess.run(
            real_argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return -1, ""
    out = (r.stdout or r.stderr or "").strip().splitlines()
    return r.returncode, (out[0] if out else "")


# Tool catalog: name → (probe argv tail, known-location resolver, config dirs,
# what installing/wiring it enables, whether it's legacy).
def _known_locations(name: str) -> list[Path]:
    """Platform-aware known install locations for a CLI, beyond PATH.

    Mirrors the Homebrew/rustup/gh known-location precedent: `shutil.which`
    only sees the installer process's PATH and false-negatives npm-global,
    ~/.local/bin, and GUI-app shims."""
    home = Path.home()
    ub = _user_base_bin()
    appdata = _appdata()
    local = _localappdata()
    locs: list[Path] = []
    if name == "agy":
        locs += [home / ".local" / "bin" / "agy", home / "bin" / "agy", ub / "agy"]
        if sys.platform == "win32":
            locs += [ub / "agy.exe", home / ".local" / "bin" / "agy.exe"]
    elif name == "copilot":
        locs += [home / ".npm-global" / "bin" / "copilot", Path("/usr/local/bin/copilot")]
        if appdata:
            locs += [appdata / "npm" / "copilot.cmd", appdata / "npm" / "copilot"]
    elif name == "code":
        # VS Code GUI-app CLI shims (macOS .app, Windows install dir).
        locs += [Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")]
        if local:
            locs += [local / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
                     local / "Programs" / "Microsoft VS Code" / "bin" / "code"]
        locs += [Path("/usr/local/bin/code"), Path("/snap/bin/code")]
    elif name == "gemini":
        locs += [home / ".npm-global" / "bin" / "gemini", Path("/usr/local/bin/gemini")]
        if appdata:
            locs += [appdata / "npm" / "gemini.cmd"]
    elif name == "claude":
        locs += [home / ".local" / "bin" / "claude", Path("/usr/local/bin/claude")]
    elif name == "codex":
        locs += [home / ".local" / "bin" / "codex", home / ".npm-global" / "bin" / "codex",
                 Path("/usr/local/bin/codex")]
        if appdata:
            locs += [appdata / "npm" / "codex.cmd"]
    return locs


def _config_dirs_for(name: str) -> list[Path]:
    """Config-dir existence is a third detection signal (a tool can be
    installed-then-removed-from-PATH but still leave its config)."""
    home = Path.home()
    mapping = {
        "claude": [home / ".claude"],
        "codex": [home / ".codex"],
        "agy": [home / ".antigravity"],
        "copilot": [home / ".copilot"],
        "gemini": [home / ".gemini"],
        "code": [home / ".vscode", home / ".config" / "Code"],
        "gh": [home / ".config" / "gh"],
        "docker": [home / ".docker"],
    }
    return mapping.get(name, [])


def _detect_one(name: str, version_argv: list[str], enables: str, legacy: bool,
                scan_deadline: float) -> dict:
    """OR'd detection for a single tool. Returns the per-tool report dict.

    Resolution order (first hit wins for `via`/`path`):
      1. shutil.which(name)            → via "which"
      2. known-location array exists   → via "path"
      3. config-dir exists             → via "config-dir" (found, but no exe to probe)
    Version is PROBED (never hard-coded) and only when we have an executable
    path AND the overall scan budget hasn't been exhausted.
    """
    found_path: str | None = None
    via: str | None = None

    which_hit = shutil.which(name)
    if which_hit:
        found_path, via = which_hit, "which"
    if found_path is None:
        for loc in _known_locations(name):
            try:
                if loc.exists():
                    found_path, via = str(loc), "path"
                    break
            except OSError:
                continue
    config_hit = None
    for cd in _config_dirs_for(name):
        try:
            if cd.exists():
                config_hit = cd
                break
        except OSError:
            continue
    if found_path is None and config_hit is not None:
        via = "config-dir"

    found = found_path is not None or config_hit is not None

    version = None
    if found_path is not None:
        if version_argv is None:
            version = "(installed)"
        elif (time.monotonic() < scan_deadline):
            rc, line = run_probe([found_path, *version_argv])
            version = line if (rc == 0 and line) else "(version probe failed)"
        else:
            version = "(version probe skipped — scan budget)"
    elif found:  # config-dir only
        version = "(config present; CLI not on PATH)"

    return {
        "found": found,
        "via": via,
        "path": found_path,
        "version": version,
        "config_dir": str(config_hit) if config_hit else None,
        "enables": enables,
        "legacy": legacy,
    }


def scan_environment() -> dict:
    """Scan the host for relevant AI CLIs / tools and return an EnvReport dict.

    Pure-stdlib, bounded, standalone. Shape:
        {
          "os": {...},
          "tools": { name: {found, via, path, version, config_dir, enables, legacy} },
          "config_dirs": { "~/.claude": bool, ... },
          "skills_consumers": [...],   # CLIs that natively read ~/.claude/skills
        }
    """
    scan_deadline = time.monotonic() + SCAN_BUDGET_SECONDS

    # (name, version_argv | None, enables, legacy)
    catalog = [
        ("claude", ["--version"], "Claude Code skills/agents/commands at ~/.claude/", False),
        ("codex",  ["--version"], "Codex CLI skill mirror at ~/.codex/skills/", False),
        ("agy",    ["--version"], "Antigravity CLI delegate (host directive ~/.gemini/agy.md)", False),
        ("copilot", ["--version"], "Copilot CLI — auto-discovers ~/.claude/skills/; + ~/.copilot/", False),
        ("code",   ["--version"], "VS Code — auto-discovers ~/.claude/skills/ (1.123+)", False),
        # legacy=True is still correct, but for the reason the messaging now gives:
        # the gemini CLI is used in LEGACY ENTERPRISE contexts, where it reads the
        # skill library. It is not deprecated as a skills target. What it is not, and
        # has not been since 2026-07-25, is a delegate foundry passes work to.
        ("gemini", ["--version"], "Gemini CLI — skills target only (legacy enterprise); "
                                  "not a delegate", True),
        ("python3", ["--version"], "runs install.py / bootstrap-environment.py", False),
        ("gh",     ["--version"], "GitHub CLI (publish, auth)", False),
        ("docker", ["--version"], "containerized tooling", False),
        ("git",    ["--version"], "clone / pull agent-foundry", False),
    ]

    tools: dict[str, dict] = {}
    for name, vargv, enables, legacy in catalog:
        # python3 may be registered as "python" on some hosts; detect both.
        probe_name = name
        if name == "python3" and shutil.which("python3") is None and shutil.which("python"):
            probe_name = "python"
        tools[name] = _detect_one(probe_name, vargv, enables, legacy, scan_deadline)

    home = Path.home()
    config_dirs = {
        "~/.claude": (home / ".claude").exists(),
        "~/.copilot": (home / ".copilot").exists(),
        "~/.gemini": (home / ".gemini").exists(),
        "~/.antigravity": (home / ".antigravity").exists(),
        "~/.codex": (home / ".codex").exists(),
    }

    # CLIs that natively read ~/.claude/skills/ (research-verified): Copilot CLI
    # and VS Code 1.123+. This corrects the stale "Copilot has no skill concept"
    # premise — the skills ship for free to both once present.
    skills_consumers = []
    if tools["copilot"]["found"]:
        skills_consumers.append("Copilot CLI")
    if tools["code"]["found"]:
        skills_consumers.append("VS Code")

    return {
        "os": {
            "platform": sys.platform,
            "release": _os_release(),
        },
        "tools": tools,
        "config_dirs": config_dirs,
        "skills_consumers": skills_consumers,
    }


def _os_release() -> str:
    try:
        import platform
        return platform.platform(terse=True)
    except Exception:
        return sys.platform


# ---------------------------------------------------------------------------
# Install mode — user-facing vocabulary vs. internal split (§6.C2, §11 A10)
# ---------------------------------------------------------------------------
#
# The CLI surface is `--mode {link, move, mc}` and STAYS that way. `move` is NOT
# renamed to `copy` (§11 A10): it is the documented flag users already have in
# scripts and muscle memory, and renaming it would break them for a purely
# internal tidiness win.
#
# Internally the two orthogonal decisions are split apart, because conflating
# them is what let cleanup leak:
#
#     placement_mode ∈ {link, copy}   — HOW files are placed
#     clean_claude   : bool           — WHETHER provenance-owned orphans are pruned
#
# `--mode` is threaded into install_gemini() and mirror_copilot_skills() as well
# as install_claude(). Before the split, an `mc` value would have arrived at
# ~/.gemini and ~/.copilot carrying its cleanup meaning with it. Now only
# placement_mode travels; clean_claude never leaves the Claude target.

CLI_MODES = ("link", "move", "mc")


def resolve_mode(cli_mode: str) -> "tuple[str, bool]":
    """PURE. Map the user-facing --mode onto (placement_mode, clean_claude).

        link → ('link', False)      symlinks, no cleanup
        move → ('copy', False)      copies, no cleanup
        mc   → ('copy', True)       copies, AND prunes provenance-owned orphans

    clean_claude is meaningful for the CLAUDE TARGET ONLY. Callers hand
    placement_mode — never the raw cli_mode — to any non-Claude installer, which
    is what keeps `mc` from meaning anything at all under ~/.gemini or
    ~/.copilot (see normalize_mode_for_other_targets)."""
    if cli_mode == "link":
        return "link", False
    if cli_mode == "move":
        return "copy", False
    if cli_mode == "mc":
        return "copy", True
    raise ValueError(f"unknown mode {cli_mode!r}; expected one of {CLI_MODES}")


def normalize_mode_for_other_targets(cli_mode: str, targets: "list[str]") -> "list[str]":
    """Return the human-readable normalization notes for non-Claude targets.

    HISTORY (S075): `mc` used to be Claude-only, and this function existed to
    ANNOUNCE that degradation rather than let it happen silently — a user who
    asked for "copy and clean" got a cleaned ~/.claude and an unannounced
    copy-only mirror, so a skill deleted from source lingered in every mirror
    forever.

    Cleanup now runs at every skills-mirror root under the same provenance rule,
    so the announcement changed from a limitation to a scope statement. What the
    user still needs told is WHICH roots will be cleaned and what authorizes it,
    because a destructive step should never be inferred.

    Pure: returns the lines, does not print them."""
    others = [t for t in targets if t != "claude"]
    if cli_mode != "mc" or not others:
        return []
    mirrors = [t for t in others if t in ("copilot", "gemini")]
    lines = [
        f"note: --mode mc = copy + CLEAN. {', '.join(others)} use `copy` placement.",
    ]
    if mirrors:
        lines += [
            f"      {', '.join(mirrors)} are cleaned too, each against its own "
            f".install-manifest.json:",
            "      only an entry this installer placed AND no longer ships can be "
            "removed, and it is archived first.",
            "      A root with no manifest yet defers and writes a baseline instead.",
        ]
    if "agy" in others:
        lines.append("      agy places a single host directive and has nothing to clean.")
    return lines


def reject_incompatible_flags(cli_mode: "str | None", skip_existing: bool) -> "str | None":
    """Return an error message if the flag combination is incoherent, else None.

    `--mode mc --skip-existing` is REJECTED. The two make contradictory
    promises: `--skip-existing` leaves existing destinations untouched, so the
    run cannot say what it placed at those paths, so the manifest cannot record
    ownership of them — and `mc`'s entire guarantee is "only ever remove what
    the installer provably placed". Running both would either prune paths whose
    ownership was never established, or defer forever and quietly do nothing.

    Rejected rather than degraded, and rejected BEFORE any write: silently
    dropping one of the two flags would leave the user believing a guarantee
    they did not get."""
    if cli_mode == "mc" and skip_existing:
        return (
            "--mode mc cannot be combined with --skip-existing.\n"
            "  mc removes only what the installer provably placed, and --skip-existing\n"
            "  leaves existing destinations untouched — so ownership of exactly the paths\n"
            "  in question would be undefined. Choose one:\n"
            "    --mode mc              copy + clean (replaces existing, archives first)\n"
            "    --mode move --skip-existing   copy, keep whatever is already there"
        )
    return None


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


def link_or_copy(src: Path, dest: Path, mode: str, copy_ignore=None) -> str:
    """Place src at dest. Returns 'link' / 'copy' / 'fallback-copy'.

    copy_ignore: an optional shutil.copytree `ignore` callable, applied ONLY when
    this ends up COPYING a directory (move mode, or a symlink-privilege fallback).
    Ignored for symlinks and files. Used to drop runtime-state/cache subpaths when
    copying skills/_meta as a unit."""
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
        shutil.copytree(src, dest, ignore=copy_ignore)
    else:
        shutil.copy2(src, dest)
    return "fallback-copy" if mode == "link" else "copy"


# Runtime-state / cache subpaths inside skills/_meta that are NOT shipped —
# logs, host inventory, caches — mirroring publish-config.json's `_meta`
# exclusions. Since §11 A4 made _meta a per-file merge, this set applies in
# EVERY mode: there is no longer a link-mode path where the whole directory is
# symlinked and these "ride along harmlessly".
_META_COPY_EXCLUDE_NAMES = frozenset({
    "archive", "evals", "cache", "__pycache__", ".pytest_cache",
    "creation-log.jsonl", "failure-deltas.jsonl", "gap-events.jsonl",
    "perf-findings.jsonl", "inventory.json",
})


def _meta_copy_ignore(dirpath, names):
    """shutil.copytree `ignore` fn: drop runtime-state / cache subpaths (logs,
    host inventory, caches) so only the toolchain ships. Mirrors
    publish-config.json's `_meta` exclusions (including the
    `inventory.json.before-*` snapshots).

    Since §11 A4, skills/_meta is placed per-file rather than copytree'd as a
    unit, so install_claude() no longer routes through this. It is kept as the
    top-level view of _META_COPY_EXCLUDE_NAMES and for any caller that does
    copy a directory wholesale; _meta_manifest_excluded() is the per-path form
    that the placement loop actually uses."""
    ignored = set()
    for n in names:
        if n in _META_COPY_EXCLUDE_NAMES or n.startswith("inventory.json.before-"):
            ignored.add(n)
    return ignored


# ---------------------------------------------------------------------------
# Provenance manifest — <claude_home>/.install-manifest.json (§6.C1, §11 A2/A7/A9)
# ---------------------------------------------------------------------------
#
# Records what this installer ACTUALLY placed, so a later cleanup run can PROVE
# ownership before it removes anything.
#
# THE SAFETY INVARIANT, stated once and enforced by compute_prune_candidates():
#
#     An entry ABSENT from the manifest is NEVER a prune candidate.
#
# Nothing is ever removed merely for being absent from the source tree. That is
# precisely what makes a hand-authored skill in ~/.claude/skills/ structurally
# safe: the installer never placed it, so it never enters the manifest, so it
# can never be proposed for removal — no heuristic, no percentage, no prompt is
# involved. Percentage floors and max-prune caps (§11 A8) are circuit breakers
# ONLY; they are never the ownership test.
#
# Both halves of the ownership test are required: an entry is a candidate only
# if it appears in the PREVIOUS successful manifest AND is absent from the set
# this run shipped.

MANIFEST_FILENAME = ".install-manifest.json"
MANIFEST_SCHEMA_VERSION = 1

# The four placement categories carried under manifest["entries"].
# skills/_meta is DELIBERATELY not one of them: §11 A4 requires it to be
# manifested PER-FILE under manifest["meta_files"], never as a single directory
# entry, so runtime-generated and foreign content inside it stays representable
# (and therefore protectable).
MANIFEST_CATEGORIES = ("skills", "agents", "commands", "workflows")

# The key naming an entry within its category. meta_files records a repo-
# relative path; everything else records a leaf name under its target dir.
_MANIFEST_NAME_KEYS = {"meta_files": "path"}


def manifest_path(claude_home: Path) -> Path:
    """Where the provenance manifest lives for a given Claude home."""
    return Path(claude_home) / MANIFEST_FILENAME


def _iso_utc_now() -> str:
    """ISO-8601 UTC instant, e.g. 2026-07-25T13:04:00Z (manifest timestamps)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_run_id() -> str:
    """Sortable UTC-microsecond stamp + random suffix, e.g.
    20260724T210000123456Z-a1b2c3.

    Sortable so runs order naturally; random-suffixed so two runs starting in
    the same microsecond cannot collide. WP-2 reuses this id to name the
    archive directory, which is why it is filename-safe on Windows too (no
    colons)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + os.urandom(3).hex()


def _sha256_file(path: Path) -> "str | None":
    """sha256 hex digest of a regular file, or None if it cannot be hashed.

    Never raises: provenance bookkeeping must not be able to break an install.
    Read in chunks so a large file does not have to fit in memory."""
    try:
        p = Path(path)
        if not p.is_file():
            return None
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def manifest_entry(name: str, kind: str, placement: str,
                   sha256: "str | None" = None) -> dict:
    """Build one ManifestEntry.

    kind:      'file' or 'dir'
    placement: whatever link_or_copy() returned — 'link', 'copy' or
               'fallback-copy'
    sha256:    see _entry_sha256 / §11 A9 — provenance metadata, NOT the
               ownership key. Omitted entirely when it would be unstable."""
    entry = {"name": name, "kind": kind, "placement": placement}
    if sha256:
        entry["sha256"] = sha256
    return entry


def _entry_sha256(src: Path, kind: str, placement: str) -> "str | None":
    """Decide whether an entry gets a sha256, per §11 A9.

    REQUIRED for kind='file'. OPTIONAL for kind='dir' and for any SYMLINKED
    entry — hashing a symlinked skill hashes the live repo working tree, which
    changes under you on the next repo edit and is therefore unstable
    provenance rather than useful provenance. A directory has no single hash.

    Prune ownership keys on `name` + manifest presence alone, so a missing
    sha256 never weakens the safety invariant."""
    if kind != "file":
        return None
    if placement == "link":
        return None
    return _sha256_file(src)


def validate_manifest_entry(entry: dict) -> None:
    """Raise ValueError if `entry` violates the §11 A9 sha256 contract.

    Required for a copied regular file; optional for dirs and symlinked
    entries. Exposed so the contract is directly assertable in tests rather
    than only implied by the writer."""
    if not isinstance(entry, dict):
        raise ValueError(f"manifest entry must be a dict, got {type(entry).__name__}")
    kind = entry.get("kind")
    placement = entry.get("placement")
    if kind == "file" and placement != "link" and not entry.get("sha256"):
        raise ValueError(
            f"sha256 is required for kind='file' entries that were copied "
            f"(entry={entry.get('name')!r}, placement={placement!r})")


def _category_entries(doc: dict, category: str) -> list:
    """Entries of one category, accepting EITHER inventory shape.

    Two shapes are legitimately in circulation and both are accepted here so no
    caller has to wrap one in the other just to compare them:

      * a full ManifestDocument — categories live under doc["entries"], with
        meta_files alongside at the top level;
      * the raw placed-shape install_claude() fills via placed_out —
        {"skills": [...], "agents": [...], ..., "meta_files": [...]}.

    Tolerant of a missing or malformed section, and that tolerance is
    load-bearing: a section we cannot read is treated as carrying NO ownership,
    which fails SAFE — unreadable provenance makes things LESS prunable, never
    more."""
    if category == "meta_files":
        section = doc.get("meta_files")
    else:
        entries = doc.get("entries")
        if isinstance(entries, dict) and category in entries:
            section = entries.get(category)
        else:
            section = doc.get(category)
    if not isinstance(section, list):
        return []
    return [e for e in section if isinstance(e, dict)]


def _entry_key(category: str, entry: dict) -> "str | None":
    """The identity of an entry within its category, or None if unusable."""
    key = entry.get(_MANIFEST_NAME_KEYS.get(category, "name"))
    return key if isinstance(key, str) and key else None


def compute_prune_candidates(previous_manifest: "dict | None",
                             shipped_inventory: "dict | None") -> list:
    """PURE. Return what this run is ALLOWED to consider for removal.

    BOTH conditions are REQUIRED for an entry to become a candidate:

      1. it appears in the PREVIOUS successful manifest, AND
      2. it is ABSENT from the set this run shipped.

    SAFETY INVARIANT — an entry absent from the manifest is NEVER a candidate.
    Condition 1 is what enforces it: the loop only ever iterates the previous
    manifest, so something the installer did not place is not merely filtered
    out, it is never considered. A hand-authored skill in ~/.claude/skills/ is
    therefore structurally safe, not safe-by-policy.

    `previous_manifest` of None (no prior successful run, or a manifest we
    cannot parse) yields an EMPTY list — that is the first-run bootstrap
    behavior and also the can't-read-it behavior, deliberately the same: no
    provable ownership means nothing may be removed.

    `shipped_inventory` of None yields an empty list for the same reason,
    inverted: if we cannot prove what this run shipped, we cannot prove
    condition 2 for ANY entry. Note the asymmetry is what keeps this safe — a
    naive implementation that treated an unreadable inventory as "shipped
    nothing" would propose pruning the entire manifest.

    sha256 is never consulted here (§11 A9). A changed hash means the content
    moved on, not that the installer stopped owning the path.

    Pure: no filesystem access, no I/O, no mutation of either argument.

    Returns a deterministically sorted list of
        {"category": <str>, "name": <str>, "entry": <previous manifest entry>}
    """
    if not isinstance(previous_manifest, dict):
        return []
    if not isinstance(shipped_inventory, dict):
        return []

    candidates = []
    for category in (*MANIFEST_CATEGORIES, "meta_files"):
        shipped_names = set()
        for entry in _category_entries(shipped_inventory, category):
            key = _entry_key(category, entry)
            if key:
                shipped_names.add(key)
        for entry in _category_entries(previous_manifest, category):
            name = _entry_key(category, entry)
            if name is None:
                continue
            if name in shipped_names:
                continue  # condition 2 fails — this run still ships it
            candidates.append({"category": category, "name": name, "entry": entry})

    candidates.sort(key=lambda c: (c["category"], c["name"]))
    return candidates


def _shipped_skill_names(repo_root: Path) -> "list[str]":
    """The skill leaf-names this run ships — the same filter every mirror uses.

    Derived from source rather than from a mirror's own contents, because it is
    condition 2 of the prune rule ("absent from what this run shipped"). Reading
    it from the mirror would make the mirror vouch for itself.
    """
    src = Path(repo_root) / "skills"
    if not src.is_dir():
        return []
    return sorted(d.name for d in src.iterdir()
                  if d.is_dir() and (d / "SKILL.md").is_file())


def _report_mirror_prune(label: str, result: dict) -> None:
    """One honest line per mirror. Silence would make 'cleaned' and 'could not
    prove ownership yet' look identical, which is the confusion the Claude
    target's baseline-only message already exists to prevent."""
    if result.get("baseline_only"):
        print(f"  {label} cleanup: DEFERRED — no ownership record existed here yet. "
              f"A baseline was written; the next run can clean.")
        return
    n = result.get("pruned", 0)
    cands = len(result.get("candidates") or [])
    if n:
        print(f"  {label} cleanup: {n} orphan(s) removed (archived first"
              + (f" to {result['archive']}" if result.get("archive") else "") + ")")
    elif cands:
        print(f"  {label} cleanup: {cands} candidate(s) identified, none removed "
              f"(not authorized, or a dry run)")


def prune_mirror_root(root: Path, subdir: str, shipped_names: "list[str]", *,
                      enabled: bool, dry_run: bool = False, authorized: bool = True,
                      archive=None, mode: "str | None" = None,
                      source_rev: "str | None" = None,
                      run_id: "str | None" = None) -> dict:
    """`--mode mc` for a skills-MIRROR root (~/.codex, ~/.copilot, ~/.gemini).

    S075. Cleanup used to be Claude-only, announced but not implemented
    elsewhere: a user who asked for "copy and clean" got a cleaned ~/.claude and
    an unannounced copy-only mirror, so a skill deleted from source lingered in
    every mirror forever. Same method everywhere now.

    Deliberately NO new prune logic. It reuses `compute_prune_candidates`
    unchanged, which is what keeps the safety invariant identical across roots:
    a candidate must be BOTH in the previous manifest AND absent from this run,
    so anything the installer did not place is never even considered. A
    hand-authored skill in a mirror is structurally safe, exactly as in
    ~/.claude.

    PER-ROOT provenance, not one central manifest. `<root>/.install-manifest.json`
    means a copilot-only or codex-only install is self-describing — there may be
    no ~/.claude on the machine at all — and it keeps each root's blast radius
    bounded by its own record.

    ARCHIVE-BEFORE-DELETE, per root. The Claude target's ArchiveSession refuses
    any path outside its own `claude_home` — deliberately, since `--rollback`
    restores by writing back into that tree — so a mirror cannot reuse it. Each
    mirror therefore gets its OWN session anchored at its own root, archiving to
    `<root>/.agent-foundry-archive/<run-id>/`. Nothing is ever deleted
    unpreserved, which is S069's R10 rule applied at every root instead of one.

    KNOWN LIMIT, stated rather than discovered: `--rollback <run-id>` restores
    the CLAUDE root only. A mirror's archive is written and complete, but there
    is no CLI to replay it yet; a wrongly-pruned mirror entry is also recoverable
    by simply re-running the install, since a mirror's content is by definition
    reproducible from source.

    Returns {"pruned", "candidates", "baseline_only", "manifest_written", "archive"}.
    Never raises: a provenance failure must not fail an otherwise-good install.
    """
    out = {"pruned": 0, "candidates": [], "baseline_only": False,
           "manifest_written": False, "archive": None}
    try:
        shipped = {"skills": [{"name": n} for n in sorted(set(shipped_names))]}
        previous = read_manifest(root)

        if enabled:
            # No previous manifest ⇒ no proven ownership ⇒ remove nothing, and
            # say so. Identical to the Claude target's first-run behaviour.
            if previous is None:
                out["baseline_only"] = True
            else:
                candidates = compute_prune_candidates(previous, shipped)
                out["candidates"] = candidates
                if candidates and authorized and not dry_run:
                    session = None
                    for cand in candidates:
                        victim = root / subdir / cand["name"]
                        if not (victim.exists() or victim.is_symlink()):
                            continue
                        try:
                            if session is None:
                                session = ArchiveSession.create(
                                    root, run_id or _new_run_id(), mode=mode,
                                    source_rev=source_rev, old_manifest=previous)
                                out["archive"] = str(session.root)
                            # Archive FIRST. before_replace raises rather than
                            # returning on failure, so an object we could not
                            # preserve is never removed.
                            session.before_replace(victim)
                            _replace_existing(victim)
                            out["pruned"] += 1
                        except (OSError, ArchiveError) as exc:
                            print(f"    ⚠ kept {victim.name} — could not archive it first: {exc}")
                    if session is not None:
                        # finalize() never raises by contract — the prune has
                        # already happened, and failing here would report a good
                        # cleanup as a bad one.
                        session.finalize()

        if not dry_run:
            doc = build_manifest(shipped, source_rev=source_rev, run_id=run_id, mode=mode)
            out["manifest_written"] = write_manifest(root, doc)
    except Exception as exc:                       # never fail the install
        print(f"    ⚠ mirror cleanup skipped for {root}: {exc}")
    return out


def build_manifest(placed: dict, *, source_rev: "str | None" = None,
                   run_id: "str | None" = None, mode: "str | None" = None,
                   canonical: "dict | None" = None,
                   updated_at: "str | None" = None) -> dict:
    """Assemble a ManifestDocument from what a run actually placed.

    `placed` is the structure install_claude() fills via its placed_out
    parameter: one list per MANIFEST_CATEGORIES plus 'meta_files'.

    `canonical` carries the per-file hash provenance for the two global config
    files. WP-1 only ships the field; WP-5 populates it. Callers pass the
    PREVIOUS manifest's canonical block through so a later default run does not
    silently drop provenance an earlier run recorded."""
    entries = {c: list(placed.get(c) or []) for c in MANIFEST_CATEGORIES}
    return {
        "version": MANIFEST_SCHEMA_VERSION,
        "updated_at": updated_at or _iso_utc_now(),
        "installer_version": __version__,
        "source_rev": source_rev or "unknown",
        "run_id": run_id or _new_run_id(),
        "mode": mode,
        "entries": entries,
        "meta_files": list(placed.get("meta_files") or []),
        "canonical": dict(canonical or {}),
    }


def read_manifest(claude_home: Path) -> "dict | None":
    """Read the previous manifest, or None if there isn't a usable one.

    None is the FIRST-RUN signal, and it is deliberately ALSO the
    cannot-read-it signal (missing, unreadable, malformed JSON, wrong shape,
    unknown schema version). Both mean the same thing to a cleanup run: no
    ownership has been proven, so prune nothing. An installer that guessed here
    would be guessing about deleting user files.

    A manifest written by a FUTURE schema version is rejected for the same
    reason — we cannot interpret its ownership claims, so we decline to act on
    them rather than misread them."""
    try:
        raw = manifest_path(claude_home).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    if doc.get("version") != MANIFEST_SCHEMA_VERSION:
        return None
    return doc


def write_manifest(claude_home: Path, manifest: dict) -> bool:
    """Persist the manifest ATOMICALLY. Call ONLY after a fully successful run.

    Returns True on success, False on failure, and never raises — a provenance
    problem must not fail an otherwise-good install.

    A failure leaves any previous manifest BYTE-IDENTICAL. The document is
    serialized in full BEFORE anything touches the destination, then written to
    a temp file in the same directory and renamed over the target
    (_atomic_write_text), so neither a serialization error, nor a full disk,
    nor a crash mid-write can leave a truncated manifest or destroy the
    previous one. That matters more than it looks: the previous manifest is the
    only record of what the installer owns, and losing it would strand every
    previously-placed entry as unownable."""
    try:
        text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError) as exc:
        print(f"    ⚠ could not serialize the install manifest: {exc}")
        return False
    try:
        _atomic_write_text(manifest_path(claude_home), text)
    except OSError as exc:
        print(f"    ⚠ could not write the install manifest: {exc}")
        return False
    return True


def _record_placed(placed: dict, category: str, src: Path, dest: Path,
                   placement: str) -> None:
    """Append one ManifestEntry for a just-placed object.

    Never raises — provenance bookkeeping must not be able to break a
    placement that already succeeded."""
    try:
        kind = "dir" if Path(src).is_dir() else "file"
        placed.setdefault(category, []).append(manifest_entry(
            name=Path(dest).name,
            kind=kind,
            placement=placement,
            sha256=_entry_sha256(Path(src), kind, placement),
        ))
    except OSError:
        pass


def _meta_manifest_excluded(rel_posix: str) -> bool:
    """True for runtime-state / cache paths inside skills/_meta.

    These are NEVER shipped, so the installer must NEVER claim to own them.
    Claiming ownership of e.g. _meta/inventory.json would make host-generated
    state a prune candidate on the next run — the exact opposite of what the
    manifest exists to prevent. Mirrors _META_COPY_EXCLUDE_NAMES, applied to
    every path component rather than just the top level."""
    for part in rel_posix.split("/"):
        if part in _META_COPY_EXCLUDE_NAMES or part.startswith("inventory.json.before-"):
            return True
    return False


def _iter_meta_shipped_files(meta_src: Path):
    """Yield (source_file, relative_posix_path) for every SHIPPED file under
    skills/_meta — the per-file placement set required by §11 A4.

    "Shipped" is the complement of _meta_manifest_excluded(): the toolchain, not
    the runtime state. The two must agree, because a file we PLACE but do not
    MANIFEST is unownable, and a file we MANIFEST but do not PLACE is a phantom
    prune candidate. One predicate, both jobs."""
    meta_src = Path(meta_src)
    try:
        candidates = sorted(meta_src.rglob("*"))
    except OSError:
        return
    for path in candidates:
        try:
            if not path.is_file():
                continue
            rel = path.relative_to(meta_src).as_posix()
        except (OSError, ValueError):
            continue
        if _meta_manifest_excluded(rel):
            continue
        yield path, rel


# NOTE (WP-2): the post-hoc destination walk that used to build the meta_files
# records lived here and has been REMOVED, not merely bypassed. It walked
# skills/_meta at the DESTINATION after placement, which — once §11 A4 made
# _meta a merged real directory rather than a replaced unit — would have swept
# up foreign and runtime files the installer never placed and recorded them as
# owned. Ownership is now recorded from what placement actually did, inline in
# install_claude(). The dead walker is gone so nothing can call it back into
# service and silently re-acquire that claim.


# ---------------------------------------------------------------------------
# What a run places — ONE enumeration, two consumers (§6.C2 CLI half)
# ---------------------------------------------------------------------------
#
# `--dry-run` has to print the exact copy / overwrite / prune sets WITHOUT
# mutating anything, which means something has to answer "what would this run
# place?" without placing it. The obvious implementation — a second walk of the
# repo inside the dry-run branch — is the one to avoid: two walks drift, and a
# dry run that drifts from the real run is worse than no dry run at all,
# because its whole value is that you can trust it before a destructive
# operation.
#
# So the enumeration lives here, once. install_claude() consumes it to PLACE;
# plan_install() consumes it to REPORT. Neither owns it.

InstallItem = collections.namedtuple("InstallItem", "src dest category meta_rel")
"""One object a run would place.

category: a MANIFEST_CATEGORIES member, or None for a skills/_meta file
          (which is manifested per-file under meta_files[] instead — §11 A4).
meta_rel: the path relative to skills/_meta for _meta files, else None.
"""


def iter_install_items(repo_root: Path, claude_home: Path):
    """Yield every InstallItem a Claude install would place, IN PLACEMENT ORDER.

    Order is part of the contract, not an accident: install_claude() places in
    this sequence and the archive journal records it, so a planner that
    enumerated differently would print a plan whose ordering did not match the
    run it describes.

    Reads the SOURCE tree only. It does not stat the destination, does not care
    whether anything already exists there, and never mutates — deciding
    create-vs-overwrite is plan_install()'s job, and doing it here would make
    this unusable as install_claude()'s loop."""
    repo_root = Path(repo_root)
    claude_home = Path(claude_home)
    skills_target = claude_home / "skills"

    skills_src = repo_root / "skills"
    if skills_src.is_dir():
        for skill in sorted(skills_src.iterdir()):
            if not skill.is_dir() or not (skill / "SKILL.md").exists():
                continue
            yield InstallItem(skill, skills_target / skill.name, "skills", None)

    meta_src = skills_src / "_meta"
    if meta_src.is_dir():
        meta_dest = skills_target / "_meta"
        for meta_file, rel in _iter_meta_shipped_files(meta_src):
            yield InstallItem(meta_file, meta_dest / Path(rel), None, rel)

    agents_src = repo_root / "agents"
    if agents_src.is_dir():
        for agent in sorted(agents_src.glob("*.md")):
            yield InstallItem(agent, claude_home / "agents" / agent.name, "agents", None)

    commands_src = repo_root / "commands"
    if commands_src.is_dir():
        for command in sorted(commands_src.glob("*.md")):
            yield InstallItem(command, claude_home / "commands" / command.name,
                              "commands", None)

    workflows_src = repo_root / "workflows"
    if workflows_src.is_dir():
        for workflow in sorted(workflows_src.glob("*.js")):
            yield InstallItem(workflow, claude_home / "workflows" / workflow.name,
                              "workflows", None)


def plan_install(repo_root: Path, claude_home: Path, placement_mode: str,
                 skip_existing: bool = False) -> dict:
    """What a run WOULD do. Reads the filesystem; mutates NOTHING.

    Returns:
        {
          "create":    [InstallItem, ...],   # destination does not exist yet
          "overwrite": [InstallItem, ...],   # destination exists and is replaced
          "skip":      [InstallItem, ...],   # exists and --skip-existing is on
          "shipped":   {<placed-shape inventory>},
        }

    `shipped` is deliberately in the placed-shape that install_claude() reports
    through placed_out, so it can be handed straight to
    compute_prune_candidates() as "what this run ships". A dry run's prune set
    is therefore computed by the SAME function that computes the real one — not
    by a parallel implementation that might disagree with it at the moment it
    matters most.

    The sha256 field is omitted from `shipped` entries: it costs a full read of
    every shipped file and prune ownership never consults it (§11 A9). A dry run
    that hashed the tree to print a list would be paying for provenance it does
    not use."""
    plan = {"create": [], "overwrite": [], "skip": [],
            "shipped": {c: [] for c in MANIFEST_CATEGORIES}}
    plan["shipped"]["meta_files"] = []

    for item in iter_install_items(repo_root, claude_home):
        exists = item.dest.exists() or item.dest.is_symlink()
        if skip_existing and exists:
            plan["skip"].append(item)
            continue
        plan["overwrite" if exists else "create"].append(item)

        # Only NON-skipped items are shipped. A skipped path was not placed by
        # this run, so claiming it here would assert an ownership the run never
        # earned — the same reason `mc` refuses --skip-existing outright.
        if item.category is None:
            plan["shipped"]["meta_files"].append({"path": "skills/_meta/" + item.meta_rel})
        else:
            placement = "link" if placement_mode == "link" else "copy"
            plan["shipped"][item.category].append({
                "name": item.dest.name,
                "kind": "dir" if item.src.is_dir() else "file",
                "placement": placement,
            })
    return plan


# ---------------------------------------------------------------------------
# Prune — remove provenance-owned orphans (mc only) (§6.C1, §11 A8)
# ---------------------------------------------------------------------------
#
# THE OWNERSHIP TEST IS compute_prune_candidates() AND NOTHING ELSE. Everything
# in this section runs strictly downstream of it: a path that is not already a
# candidate cannot be made one by any threshold, prompt, or flag here. The
# circuit breakers below can only ever REMOVE things from the list.

PRUNE_MAX_PATHS = 20          # absolute cap  (§11 A8)
PRUNE_MAX_FRACTION = 0.25     # 25% of manifest entries (§11 A8)


def _manifest_entry_count(manifest: "dict | None") -> int:
    """How many entries the previous manifest claims, across every category."""
    if not isinstance(manifest, dict):
        return 0
    total = 0
    for category in (*MANIFEST_CATEGORIES, "meta_files"):
        total += len(_category_entries(manifest, category))
    return total


def prune_threshold(manifest_entry_count: int) -> int:
    """PURE. The circuit-breaker threshold: 25% of the manifest, or 20 paths,
    WHICHEVER IS SMALLER (§11 A8).

    'Smaller' is the whole point. On a large install 25% is hundreds of paths,
    so the absolute cap is what actually catches a runaway; on a small install
    20 would never trip, so the percentage is what catches it. Taking the min
    means a mass deletion has to get past both."""
    return int(min(PRUNE_MAX_FRACTION * max(manifest_entry_count, 0), PRUNE_MAX_PATHS))


def prune_breaker_tripped(candidate_count: int, manifest_entry_count: int) -> bool:
    """PURE. True when the prune is large enough to demand explicit confirmation.

    A CIRCUIT BREAKER, NEVER THE OWNERSHIP TEST. It answers "is this a
    suspiciously large removal for this install?" — a question about volume. It
    never answers "may this path be removed?", which is
    compute_prune_candidates()' answer alone. Conflating the two would be the
    classic mistake: a percentage that lets deletions through because they are
    small enough looks like a safety feature and is the opposite of one."""
    return candidate_count > prune_threshold(manifest_entry_count)


def candidate_path(claude_home: Path, candidate: dict) -> "Path | None":
    """Where a prune candidate lives on disk, or None if it cannot be resolved.

    Refuses anything that would escape claude_home. The names come from a
    manifest file, and a manifest is on-disk data that a previous run wrote —
    so it is input, and input that resolves to `../../etc` gets rejected rather
    than deleted. Belt and braces: these names were placed by the installer, so
    a traversal here means something has already gone wrong upstream."""
    category = candidate.get("category")
    name = candidate.get("name")
    if not isinstance(name, str) or not name:
        return None
    if category == "meta_files":
        rel = name                      # already 'skills/_meta/<rel>'
    elif category in MANIFEST_CATEGORIES:
        if "/" in name or "\\" in name:
            return None                 # a category entry is a bare basename
        rel = f"{category}/{name}"
    else:
        return None

    claude_home = Path(claude_home)
    dest = (claude_home / Path(rel))
    try:
        dest.resolve().relative_to(claude_home.resolve())
    except (ValueError, OSError):
        # A SYMLINK inside claude_home pointing outside it resolves out of the
        # tree. Removing the link itself would be fine, but we cannot tell that
        # apart from a genuinely escaping path here, so decline both.
        return None
    return dest


def prune_orphans(claude_home: Path, candidates: list,
                  archive: "ArchiveSession | None") -> "tuple[int, list]":
    """ARCHIVE each candidate, then remove it. Returns (removed, failures).

    Archive-then-remove, in that order, for the same reason install_claude()
    archives before replacing: an archive written afterwards preserves nothing.
    A candidate whose archiving FAILS is left on disk and reported — refusing to
    delete something we could not preserve is the entire contract, and a prune
    is the one operation with no new content to fall back on.

    ArchiveError is caught per candidate rather than propagated: by the time we
    prune, the install itself has already succeeded, so aborting the whole run
    over one un-archivable orphan would be a worse outcome than leaving that
    orphan in place and saying so."""
    removed = 0
    failures: list = []
    for candidate in candidates:
        dest = candidate_path(claude_home, candidate)
        if dest is None:
            failures.append((candidate.get("name"), "unresolvable path"))
            continue
        if not (dest.exists() or dest.is_symlink()):
            continue  # already gone — the desired end state, nothing to do
        try:
            if archive is not None:
                # Moves the object INTO the archive, so it is already gone from
                # the destination when this returns.
                archive.before_replace(dest)
            _replace_existing(dest)
            removed += 1
        except (ArchiveError, OSError) as exc:
            failures.append((candidate.get("name"), str(exc)))
    return removed, failures


# ---------------------------------------------------------------------------
# Archive + journal — <claude_home>/.agent-foundry-archive/<run_id>/ (§6.C2, §11 A3/A10)
# ---------------------------------------------------------------------------
#
# THE BUG THIS EXISTS TO CLOSE (R10).
#
# install_claude()'s place() calls _replace_existing() — unlink/rmtree — on each
# destination BEFORE copying the new content over it. A customized same-name
# skill at the destination was therefore destroyed silently, with no copy kept
# anywhere, on EVERY run. Not on cleanup runs; on every run.
#
# ARCHIVE SCOPE IS ALL MODES (§11 A3). Any destination that already exists and
# is being REPLACED is archived first, in link / move / mc alike. Creating a new
# path archives nothing — there is nothing to lose. R10 is mode-independent, so
# scoping the archive to `mc` would leave the real data-loss vector wide open
# while advertising "we archive everything the run replaces"; a half-guarantee
# is worse than none precisely because it invites trust. PRUNING of
# provenance-owned orphans stays mc-only — that is a different operation with a
# different owner (WP-3).
#
# ZERO-DESTRUCTION, stated exactly:
#
#   * Archive-root creation happens BEFORE the first mutation. If it fails,
#     literally nothing has been touched and the run refuses.
#   * If an archive MOVE fails mid-run, the in-process handler rolls back what
#     already moved, so no destructive operation survives.
#
# HONEST LIMIT: a hard-killed process cannot roll itself back. No in-process
# handler runs when the kernel takes the process away. That is exactly why
# next-invocation detection (find_incomplete_runs) exists as the second path —
# the journal is on disk, so the NEXT run can offer what this run could not.

ARCHIVE_DIRNAME = ".agent-foundry-archive"
ARCHIVE_OBJECTS_DIRNAME = "objects"
JOURNAL_FILENAME = "journal.json"
ACTIONS_LOG_FILENAME = "actions.jsonl"
JOURNAL_SCHEMA_VERSION = 1

JOURNAL_IN_PROGRESS = "in_progress"
JOURNAL_COMPLETE = "complete"
JOURNAL_ROLLED_BACK = "rolled_back"


class ArchiveError(RuntimeError):
    """The archive cannot honor its contract, so the run must not proceed.

    Raised — never swallowed — because every caller of the archive is about to
    destroy something. Degrading to "carry on without an archive" would turn
    the one guarantee this component makes into a maybe."""


def archive_root_dir(claude_home: Path) -> Path:
    """The parent holding every run's archive, `<claude_home>/.agent-foundry-archive`."""
    return Path(claude_home) / ARCHIVE_DIRNAME


def _object_kind(path: Path) -> str:
    """'symlink' / 'dir' / 'file' / 'absent'.

    The symlink test comes FIRST and is never relaxed: a symlink to a directory
    answers True to is_dir(), and treating it as a directory is how an archive
    ends up dereferencing a link into a copy of the live repo working tree."""
    path = Path(path)
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "dir"
    if path.exists():
        return "file"
    return "absent"


def is_safe_run_id(run_id: str) -> bool:
    """True if `run_id` may be used as a directory name under the archive root.

    Validated rather than trusted because this value reaches code that MOVES
    AND REMOVES FILES: '../../..' would resolve the "archive directory" to
    somewhere else entirely. Accepts only the shape _new_run_id() produces —
    alphanumerics, dash, underscore — which also keeps it Windows-safe."""
    if not run_id or not isinstance(run_id, str):
        return False
    if run_id in (".", ".."):
        return False
    return all(ch.isalnum() or ch in "-_" for ch in run_id)


class ArchiveSession:
    """One run's archive: an exclusively-created root, a journal, and a log.

    Lifecycle:  create() → before_replace()/record_created()* → finalize()
                                                              ↘ rollback()

    Two durable records, deliberately:

      * `actions.jsonl` is the crash-durable one — a line is appended and
        flushed per state change, which is O(1) no matter how many objects the
        run touches. Rewriting a growing journal per action would be O(n²) I/O
        across a few hundred skills.
      * `journal.json` is the DOCUMENT the contract names (old manifest, new
        manifest, planned actions, completed actions, object kinds, hashes,
        installer + source revision, run id). It is written at creation as a
        discoverable in-progress header and rewritten in full at finalize.

    On a clean run the journal is complete and authoritative. On a crash it is
    still the in-progress header, and rollback reconstructs the action list
    from `actions.jsonl` — which is why the log exists at all.

    A planned action is logged BEFORE the destructive step and completed only
    AFTER the move has actually landed. A journal that claims more than
    happened is unrollbackable, and an unrollbackable journal is the exact
    failure this component exists to prevent."""

    def __init__(self, claude_home: Path, run_id: str, root: Path, *,
                 mode: "str | None" = None, source_rev: "str | None" = None,
                 old_manifest: "dict | None" = None, dry_run: bool = False):
        self.claude_home_raw = Path(claude_home)
        self.claude_home = self.claude_home_raw.resolve()
        self.run_id = run_id
        self.root = Path(root)
        self.mode = mode
        self.source_rev = source_rev or "unknown"
        self.old_manifest = old_manifest
        self.new_manifest: "dict | None" = None
        self.dry_run = bool(dry_run)
        self.started_at = _iso_utc_now()
        self.status = JOURNAL_IN_PROGRESS
        self.planned_actions: list = []
        self.completed_actions: list = []

    # -- construction --------------------------------------------------------

    @classmethod
    def create(cls, claude_home: Path, run_id: str, *, mode: "str | None" = None,
               source_rev: "str | None" = None, old_manifest: "dict | None" = None,
               dry_run: bool = False) -> "ArchiveSession":
        """Create the archive root EXCLUSIVELY, before the first mutation.

        Exclusive create (mkdir, which raises FileExistsError) rather than
        exist_ok=True: a directory that is already there may hold another run's
        objects, and merging two runs' archives makes BOTH unrollbackable.

        The root must be on the SAME FILESYSTEM as the targets, so archiving is
        an atomic rename. A cross-device root is a hard failure and NOT a silent
        copy fallback — a non-atomic archive move can be interrupted and leave
        the object in neither place, which is worse than the bug we are fixing.

        dry_run creates nothing at all: a dry run that left an empty directory
        behind would have mutated the tree and broken its only guarantee."""
        claude_home = Path(claude_home)
        if not is_safe_run_id(run_id):
            raise ArchiveError(f"unsafe run id for an archive directory: {run_id!r}")
        root = archive_root_dir(claude_home) / run_id
        if dry_run:
            return cls(claude_home, run_id, root, mode=mode, source_rev=source_rev,
                       old_manifest=old_manifest, dry_run=True)
        try:
            claude_home.mkdir(parents=True, exist_ok=True)
            archive_root_dir(claude_home).mkdir(parents=True, exist_ok=True)
            root.mkdir()  # EXCLUSIVE — FileExistsError if this run id is taken
        except OSError as exc:
            raise ArchiveError(f"could not create the archive root {root}: {exc}") from exc
        try:
            if os.stat(root).st_dev != os.stat(claude_home).st_dev:
                raise ArchiveError(
                    f"archive root {root} is on a different filesystem than {claude_home}; "
                    f"atomic archiving is impossible and a copy fallback is not permitted")
        except OSError as exc:
            raise ArchiveError(f"could not stat the archive root {root}: {exc}") from exc
        session = cls(claude_home, run_id, root, mode=mode, source_rev=source_rev,
                      old_manifest=old_manifest)
        session._write_journal()
        return session

    # -- paths ---------------------------------------------------------------

    @property
    def journal_path(self) -> Path:
        return self.root / JOURNAL_FILENAME

    @property
    def actions_log_path(self) -> Path:
        return self.root / ACTIONS_LOG_FILENAME

    def _relative_target(self, dest: Path) -> str:
        """`dest` as a POSIX path relative to claude_home.

        The PARENT is resolved, the leaf is not. Resolving the leaf would
        follow a symlinked destination and name the repo file it points at
        instead of the destination we are about to archive — which is the whole
        object of the exercise. Resolving the parent is what lets a symlinked
        home (macOS /tmp → /private/tmp) still match.

        Refuses anything outside the tree we are anchored to: restore writes
        back to `claude_home / target`, so a target that escaped claude_home
        would make rollback write outside it."""
        dest = Path(dest)
        if not dest.is_absolute():
            dest = self.claude_home / dest
        try:
            candidate = Path(os.path.realpath(str(dest.parent))) / dest.name
        except OSError:
            candidate = dest
        for base in (self.claude_home, self.claude_home_raw):
            try:
                return candidate.relative_to(base).as_posix()
            except ValueError:
                continue
        raise ArchiveError(f"refusing to archive {dest} — it is outside {self.claude_home}")

    # -- recording -----------------------------------------------------------

    def _log(self, state: str, action: dict) -> None:
        """Append one state change to the crash-durable log.

        Flushed and fsynced: this line is the only thing standing between a
        killed process and an object that cannot be found again."""
        if self.dry_run:
            return
        try:
            with open(self.actions_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"state": state, "action": action}, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            raise ArchiveError(f"could not write the archive action log: {exc}") from exc

    def _plan(self, action: dict) -> None:
        self.planned_actions.append(action)
        self._log("planned", action)

    def _complete(self, action: dict) -> None:
        self.completed_actions.append(action)
        self._log("completed", action)

    def before_replace(self, dest: Path) -> bool:
        """Archive `dest` if it exists. Call BEFORE anything touches it.

        Returns True if an object was archived, False if `dest` was absent
        (recorded as a `create`, which archives nothing but must still be
        journalled so rollback can REMOVE it to reach the pre-run state).

        Raises ArchiveError on any failure — the caller must abort rather than
        replace an object it could not preserve."""
        dest = Path(dest)
        kind = _object_kind(dest)
        if kind == "absent":
            self.record_created(dest)
            return False

        rel = self._relative_target(dest)
        action = {
            "op": "replace",
            "target": rel,
            "object_kind": kind,
            "sha256": _sha256_file(dest) if kind == "file" else None,
            "symlink_target": self._readlink(dest) if kind == "symlink" else None,
            "archived_to": ARCHIVE_OBJECTS_DIRNAME + "/" + rel,
        }
        if self.dry_run:
            self.planned_actions.append(action)
            return False

        self._plan(action)  # durable BEFORE the destructive step, never after
        archived = self.root / ARCHIVE_OBJECTS_DIRNAME / Path(rel)
        try:
            archived.parent.mkdir(parents=True, exist_ok=True)
            # os.rename, never shutil.move: rename is atomic on the same
            # filesystem, moves the SYMLINK rather than its target, and raises
            # EXDEV across devices instead of silently degrading to a copy.
            os.rename(dest, archived)
        except OSError as exc:
            raise ArchiveError(f"could not archive {dest} → {archived}: {exc}") from exc
        self._complete(action)
        return True

    def ensure_dir(self, path: Path) -> None:
        """mkdir -p, journalling every level this run actually creates.

        Container directories (`agents/`, `commands/`, `skills/_meta/`) are
        created by the install, not placed by it, so it is easy to forget they
        are part of the diff — and then a rollback that restored every file
        perfectly would still leave a tree that differs from the pre-run one by
        a handful of empty directories. "Byte-for-byte" has to mean it.

        Only strict descendants of claude_home are journalled. claude_home
        itself is created before the session exists, and removing a user's
        ~/.claude on a rollback would be a far bigger surprise than leaving an
        empty directory behind."""
        path = Path(path)
        missing: list = []
        cursor = path
        while not (cursor.exists() or cursor.is_symlink()):
            try:
                cursor.relative_to(self.claude_home_raw)
            except ValueError:
                break  # at or above claude_home — not ours to undo
            missing.append(cursor)
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
        if self.dry_run:
            return
        for directory in reversed(missing):  # outermost first
            action = {
                "op": "mkdir",
                "target": self._relative_target(directory),
                "object_kind": "dir",
                "sha256": None,
                "symlink_target": None,
                "archived_to": None,
            }
            self.planned_actions.append(action)
            self.completed_actions.append(action)
            self._log("completed", action)
        path.mkdir(parents=True, exist_ok=True)

    def record_created(self, dest: Path) -> None:
        """Record that the run is about to CREATE a path that did not exist.

        Nothing is archived — there is nothing to lose. It is journalled anyway
        because "restore the pre-run state byte-for-byte" means removing what
        the run added, not only putting back what it replaced."""
        action = {
            "op": "create",
            "target": self._relative_target(dest),
            "object_kind": "absent",
            "sha256": None,
            "symlink_target": None,
            "archived_to": None,
        }
        if self.dry_run:
            self.planned_actions.append(action)
            return
        self.planned_actions.append(action)
        self.completed_actions.append(action)
        self._log("completed", action)

    @staticmethod
    def _readlink(path: Path) -> "str | None":
        try:
            return os.readlink(str(path))
        except OSError:
            return None

    # -- journal -------------------------------------------------------------

    def journal_document(self) -> dict:
        return {
            "version": JOURNAL_SCHEMA_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": _iso_utc_now() if self.status != JOURNAL_IN_PROGRESS else None,
            "installer_version": __version__,
            "source_rev": self.source_rev,
            "mode": self.mode,
            "claude_home": str(self.claude_home),
            "archive_root": str(self.root),
            "old_manifest": self.old_manifest,
            "new_manifest": self.new_manifest,
            "planned_actions": list(self.planned_actions),
            "completed_actions": list(self.completed_actions),
        }

    def _write_journal(self) -> None:
        if self.dry_run:
            return
        try:
            _atomic_write_text(
                self.journal_path,
                json.dumps(self.journal_document(), indent=2, sort_keys=True) + "\n")
        except (OSError, TypeError, ValueError) as exc:
            raise ArchiveError(f"could not write the archive journal: {exc}") from exc

    def set_new_manifest(self, manifest: "dict | None") -> None:
        self.new_manifest = manifest

    def finalize(self) -> None:
        """Mark the run complete and write the full journal.

        Never raises: by the time this runs the install has already succeeded,
        and failing it would report a good install as a bad one. A journal that
        stays `in_progress` is the safe direction anyway — the next run offers a
        rollback that turns out to be unnecessary, rather than skipping one that
        was."""
        if self.dry_run:
            return
        self.status = JOURNAL_COMPLETE
        try:
            self._write_journal()
        except ArchiveError as exc:
            print(f"    ⚠ could not finalize the archive journal: {exc}")

    def rollback(self, reason: str = "") -> bool:
        """In-process auto-rollback (§11 A10, path 1). Undo this run.

        Covers the failure paths this process can see. It CANNOT cover a hard
        kill — nothing in-process can — which is why find_incomplete_runs()
        exists as the second path."""
        if self.dry_run:
            return True
        try:
            self._write_journal()  # persist what we know before undoing it
        except ArchiveError:
            pass
        if reason:
            print(f"    ↩ rolling back this run: {reason}")
        ok = _replay_journal_reverse(self.claude_home, self.root,
                                     list(self.completed_actions), self.old_manifest)
        self.status = JOURNAL_ROLLED_BACK
        try:
            self._write_journal()
        except ArchiveError:
            pass
        return ok


def read_journal(run_dir: Path) -> "dict | None":
    """Read one run's journal, or None if there is no usable one.

    None is deliberately BOTH "no journal" and "cannot parse it". Rollback is
    itself destructive — it removes what the run created — so an unreadable
    journal must refuse rather than restore on a guess."""
    try:
        raw = (Path(run_dir) / JOURNAL_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(doc, dict) or doc.get("version") != JOURNAL_SCHEMA_VERSION:
        return None
    return doc


def _completed_actions_from_log(run_dir: Path) -> list:
    """Reconstruct the completed-action list from `actions.jsonl`.

    The crash path: the journal is still the in-progress header, but every
    state change was appended and fsynced as it happened. A malformed trailing
    line (the process died mid-write) is skipped rather than fatal — one
    unparseable line must not cost us the hundreds of good ones above it."""
    actions: list = []
    try:
        text = (Path(run_dir) / ACTIONS_LOG_FILENAME).read_text(encoding="utf-8")
    except OSError:
        return actions
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("state") == "completed":
            action = record.get("action")
            if isinstance(action, dict):
                actions.append(action)
    return actions


def _replay_journal_reverse(claude_home: Path, run_dir: Path, actions: list,
                            old_manifest: "dict | None") -> bool:
    """Undo `actions` in reverse. Returns True if everything was restored.

    Reverse order is what makes nesting safe: whatever was touched last is put
    back first, so a parent is never restored over a child that still has to
    move.

    COMPLETED actions are the authority. A planned-but-not-completed action is
    never replayed, because it never happened — replaying it would move an
    object that is not where the journal says it is."""
    claude_home = Path(claude_home)
    run_dir = Path(run_dir)
    ok = True
    for action in reversed(actions):
        if not isinstance(action, dict):
            continue
        target = action.get("target")
        if not isinstance(target, str) or not target:
            continue
        dest = claude_home / Path(target)
        op = action.get("op")
        try:
            if op == "create":
                # The run added this path; the pre-run state did not have it.
                _replace_existing(dest)
                continue
            if op == "mkdir":
                # A container directory the run created. rmdir, never rmtree:
                # if anything is in there now it is not ours — either a later
                # run's or the user's — and removing it in the name of
                # restoring would be the same data loss we are undoing.
                try:
                    dest.rmdir()
                except OSError:
                    pass
                continue
            if op != "replace":
                continue
            archived_rel = action.get("archived_to") or (ARCHIVE_OBJECTS_DIRNAME + "/" + target)
            archived = run_dir / Path(archived_rel)
            if not (archived.exists() or archived.is_symlink()):
                print(f"    ⚠ archived object missing, cannot restore {target}")
                ok = False
                continue
            _replace_existing(dest)  # drop whatever the run put here
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(archived, dest)
        except OSError as exc:
            print(f"    ⚠ could not restore {target}: {exc}")
            ok = False

    # The provenance manifest is written outside the archive session, so
    # restoring the tree without restoring it would leave the manifest
    # describing a state that no longer exists.
    try:
        if old_manifest is None:
            mp = manifest_path(claude_home)
            if mp.exists():
                mp.unlink()
        else:
            write_manifest(claude_home, old_manifest)
    except OSError as exc:
        print(f"    ⚠ could not restore the previous install manifest: {exc}")
        ok = False
    return ok


def find_incomplete_runs(claude_home: Path) -> list:
    """Run ids whose journal never reached `complete` (§11 A10, path 2).

    The half of auto-rollback that survives a hard kill: the killed process
    could not undo itself, but it left the journal on disk, so the NEXT
    invocation can find it and offer what that run could not."""
    root = archive_root_dir(claude_home)
    found: list = []
    try:
        candidates = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return found
    for run_dir in candidates:
        journal = read_journal(run_dir)
        if journal is None:
            continue
        if journal.get("status") == JOURNAL_IN_PROGRESS:
            found.append(run_dir.name)
    return found


def rollback_run(claude_home: Path, run_id: str) -> int:
    """`--rollback <run-id>`. Returns a process exit code (0 = restored).

    Refuses — touching nothing — on anything it cannot prove out: an unsafe id,
    an unknown run, an unreadable journal. This function MOVES AND REMOVES
    FILES, so "do the best we can with what we have" is the wrong instinct
    here; not knowing what to put back is not a licence to guess."""
    claude_home = Path(claude_home)
    if not is_safe_run_id(run_id):
        print(f"✗ invalid run id {run_id!r} — expected the id of a directory under "
              f"{archive_root_dir(claude_home)}")
        return 2
    run_dir = archive_root_dir(claude_home) / run_id
    if not run_dir.is_dir():
        print(f"✗ no archived run {run_id!r} under {archive_root_dir(claude_home)}")
        return 2
    journal = read_journal(run_dir)
    if journal is None:
        print(f"✗ run {run_id!r} has no readable journal.json — refusing to restore on a guess")
        return 2
    if journal.get("status") == JOURNAL_ROLLED_BACK:
        print(f"✓ run {run_id!r} was already rolled back; nothing to do")
        return 0

    actions = journal.get("completed_actions")
    if not isinstance(actions, list) or (
            not actions and journal.get("status") == JOURNAL_IN_PROGRESS):
        # Crashed run: the journal is still the in-progress header, so the
        # append-only log carries the truth.
        actions = _completed_actions_from_log(run_dir)

    print(f"↩ rolling back run {run_id} — {len(actions)} action(s), "
          f"archive at {run_dir}")
    ok = _replay_journal_reverse(claude_home, run_dir, actions,
                                 journal.get("old_manifest"))
    journal["status"] = JOURNAL_ROLLED_BACK
    journal["finished_at"] = _iso_utc_now()
    try:
        _atomic_write_text(run_dir / JOURNAL_FILENAME,
                           json.dumps(journal, indent=2, sort_keys=True) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        print(f"    ⚠ restored, but could not update the journal status: {exc}")
    if ok:
        # The archive directory is deliberately LEFT IN PLACE. Archives are
        # never silently expired (§6.C2) — retention is an explicit, separate
        # operation, and deleting the evidence right after a restore is exactly
        # when a user is most likely to want it back.
        print(f"✓ restored the pre-run state. Archive kept at {run_dir}")
        return 0
    print(f"✗ rollback incomplete — see the warnings above. Archive kept at {run_dir}")
    return 1


def _offer_incomplete_rollback(claude_home: Path, noninteractive: bool) -> None:
    """Surface incomplete runs before this run starts mutating anything.

    Under --noninteractive we report and continue rather than rolling back
    unasked: an automatic restore is itself destructive (it removes what the
    previous run created), and doing that without consent in a scripted context
    is the same class of surprise this whole component exists to prevent."""
    try:
        runs = find_incomplete_runs(claude_home)
    except OSError:
        return
    if not runs:
        return
    print()
    print(f"⚠ {len(runs)} previous install run(s) never completed — a run was")
    print("  interrupted or killed before it could finish or roll itself back:")
    for run_id in runs:
        print(f"      {run_id}   ({archive_root_dir(claude_home) / run_id})")
    if noninteractive:
        print("  Restore any of them with:  python3 install.py --rollback <run-id>")
        print("  Continuing with this install; nothing has been rolled back.")
        print()
        return
    for run_id in runs:
        if confirm(f"Roll back run {run_id} now?", default=False):
            rollback_run(claude_home, run_id)
    print()


# ---------------------------------------------------------------------------
# Per-target installers
# ---------------------------------------------------------------------------


def install_claude(
    repo_root: Path, claude_home: Path, mode: str, skip_existing: bool,
    placed_out: "dict | None" = None, archive: "ArchiveSession | None" = None,
) -> tuple[int, int, int, int, int, int, int]:
    """Install skills + agents + commands + workflows into Claude's config tree,
    PLUS the `skills/_meta/` support dir (no SKILL.md, so the skill loop skips it).

    Default behavior REPLACES existing entries at the destination (any kind:
    file, dir, or symlink — see _replace_existing). Pass skip_existing=True
    to opt into the old behavior of leaving existing entries untouched.

    `workflows/` are flat `*.js` saved-workflow files placed into
    ~/.claude/workflows/ (Claude-only — agy/Copilot/Gemini do not consume them).

    `skills/_meta/` carries the scripts the wired SessionStart hooks reference
    (`scan_hard_rules.py`, `forge_reminder_hook.py`, `freshness_nudge.py`,
    `scope_delta_compact_nudge.py`, `memory_primer.py`, …) and the helpers many
    skills import (`gates.py`, `classify.py`, `claims.py`, …). Without it the
    wired hooks point at missing scripts on a fresh box. It is ALWAYS a real
    directory and is merged PER-FILE (§11 A4) — see the placement block below.

    `archive`, when given, is the run's ArchiveSession. EVERY destination that
    already exists is handed to it BEFORE _replace_existing() touches it, in
    every mode (§11 A3) — that is the R10 fix. An ArchiveError propagates out
    of this function on purpose: the caller must abort and roll back rather
    than replace an object the archive could not preserve.

    Returns (skill_n, agent_n, command_n, workflow_n, replaced_or_skipped,
    chmodded, meta_placed).

    `placed_out` is an optional OUT-parameter: when a dict is passed, it is
    filled with the provenance record of everything this call actually placed —
    one ManifestEntry list per MANIFEST_CATEGORIES plus per-file `meta_files`
    (§11 A4). It is an out-parameter rather than an extra return value
    precisely because the 7-tuple return shape is depended upon by callers and
    tests; widening it would be a breaking change for no benefit.

    An untouched `placed_out` (still empty after the call) therefore means "no
    placement provenance was reported", which is what _run() checks before
    writing a manifest — a mocked or stubbed install_claude leaves it empty and
    correctly produces no manifest write.
    """
    skills_target = claude_home / "skills"
    agents_target = claude_home / "agents"
    commands_target = claude_home / "commands"
    workflows_target = claude_home / "workflows"

    def ensure_dir(path: Path) -> None:
        """mkdir -p, journalled when there is an archive session.

        Container directories are created by the install rather than placed by
        it, which makes them easy to leave out of the diff — and a rollback
        that restored every file perfectly but left four empty directories
        behind would not be the byte-for-byte restore it claims to be."""
        if archive is not None:
            archive.ensure_dir(path)
        else:
            Path(path).mkdir(parents=True, exist_ok=True)

    ensure_dir(skills_target)
    ensure_dir(agents_target)
    ensure_dir(commands_target)

    skill_n = 0
    agent_n = 0
    command_n = 0
    workflow_n = 0
    meta_placed = 0
    touched_existing = 0  # replaced (default) or skipped (skip_existing)

    # Provenance record of what this call actually places (§6.C1). Populated by
    # place() and handed back through placed_out; a run that places nothing
    # still reports the empty categories, which is what distinguishes "ran and
    # placed nothing" from "never ran".
    placed: dict = {c: [] for c in MANIFEST_CATEGORIES}
    placed["meta_files"] = []

    def place(src: Path, dest: Path, copy_ignore=None,
              category: "str | None" = None) -> "str | None":
        """Place src at dest. Returns the placement kind, or None if skipped.

        The return value is the string link_or_copy() produced ('link' /
        'copy' / 'fallback-copy'), which is truthy, so `if place(...)` still
        reads as "was it installed". Callers that need to record provenance
        themselves (skills/_meta, per §11 A4) use the value.

        `category`, when given, records the placement in the provenance
        manifest. skills/_meta passes None and is recorded per-file instead.

        THE R10 ORDERING, and the only ordering that fixes it: the destination
        is archived BEFORE _replace_existing() runs. Anything else — archiving
        after, or archiving only in cleanup mode — destroys the object first
        and preserves it never."""
        nonlocal touched_existing
        existed = dest.exists() or dest.is_symlink()
        if skip_existing and existed:
            touched_existing += 1
            return None
        if existed:
            touched_existing += 1
        if archive is not None:
            # Raises ArchiveError if it cannot preserve the object; the caller
            # aborts and rolls back rather than proceeding to destroy it.
            archive.before_replace(dest)
        _replace_existing(dest)
        placement = link_or_copy(src, dest, mode, copy_ignore=copy_ignore)
        if category is not None:
            _record_placed(placed, category, src, dest, placement)
        return placement

    for skill in sorted((repo_root / "skills").iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").exists():
            continue
        if place(skill, skills_target / skill.name, category="skills"):
            skill_n += 1

    # ---- skills/_meta — ALWAYS a real directory, merged PER-FILE (§11 A4) ----
    #
    # _meta is MIXED-OWNERSHIP: the shipped toolchain lives beside runtime state
    # the host generates (inventory.json, the *.jsonl logs, caches) and beside
    # whatever else a user has put there. Placing it as a UNIT — the old
    # behavior, a symlink in link mode and a copytree in move mode — meant
    # _replace_existing() rmtree'd or unlinked the whole directory first, taking
    # every one of those target-side files with it. That is R10 at its worst,
    # because unlike a skill directory this content exists ONLY at the target.
    #
    # So: never a unit symlink, never rmtree'd as a unit, in any mode. Shipped
    # files are placed one by one (symlinked or copied per --mode); everything
    # else at the destination is left exactly where it is. This deliberately
    # changes link-mode behavior, and that change IS the point.
    meta_src = repo_root / "skills" / "_meta"
    if meta_src.is_dir():
        meta_dest = skills_target / "_meta"
        # Migrate off the old unit layout: a symlinked (or otherwise non-dir)
        # _meta is archived and removed so a real directory can take its place.
        # Archiving the SYMLINK is cheap and lossless — it is one link, and its
        # target is the repo, which we are not touching.
        if meta_dest.is_symlink() or (meta_dest.exists() and not meta_dest.is_dir()):
            if archive is not None:
                archive.before_replace(meta_dest)
            _replace_existing(meta_dest)
            touched_existing += 1
        ensure_dir(meta_dest)
        for meta_file, rel in _iter_meta_shipped_files(meta_src):
            dest_file = meta_dest / Path(rel)
            ensure_dir(dest_file.parent)
            placement = place(meta_file, dest_file)
            if not placement:
                continue
            meta_placed = 1
            # Recorded from what we ACTUALLY placed, never from a post-hoc walk
            # of the destination: a walk would sweep up foreign and runtime
            # files too, and claiming ownership of those would make them prune
            # candidates on the next run — the exact inversion of the
            # manifest's purpose.
            record = {"path": "skills/_meta/" + rel}
            if placement != "link":
                sha = _sha256_file(meta_file)
                if sha:
                    record["sha256"] = sha
            placed["meta_files"].append(record)

    for agent in sorted((repo_root / "agents").glob("*.md")):
        if place(agent, agents_target / agent.name, category="agents"):
            agent_n += 1

    commands_dir = repo_root / "commands"
    if commands_dir.exists():
        for command in sorted(commands_dir.glob("*.md")):
            if place(command, commands_target / command.name, category="commands"):
                command_n += 1

    # Saved workflows — flat *.js files placed into ~/.claude/workflows/ (S055).
    # Claude-only: agy/Copilot/Gemini do not consume saved workflows.
    workflows_dir = repo_root / "workflows"
    if workflows_dir.exists():
        # Create the target lazily — only when there are workflows to place — so
        # copy2/symlink don't fail with "path not found" on a fresh machine where
        # ~/.claude/workflows/ doesn't exist yet (WinError 3 on Windows).
        ensure_dir(workflows_target)
        for workflow in sorted(workflows_dir.glob("*.js")):
            if place(workflow, workflows_target / workflow.name, category="workflows"):
                workflow_n += 1

    chmodded = 0
    if sys.platform != "win32":
        chmodded = chmod_scripts(skills_target)

    if placed_out is not None:
        placed_out.update(placed)

    return skill_n, agent_n, command_n, workflow_n, touched_existing, chmodded, meta_placed


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


# Fallback agy directive used ONLY if the bundled templates/agy.md is
# somehow missing (e.g. a partial clone). Keeps install_agy() self-sufficient
# and publish-clean — generic, no host-specific paths.
_AGY_TEMPLATE_FALLBACK = """\
# agy — host directive (Antigravity CLI global context)

You are `agy` (the Antigravity CLI): the PRIMARY second-opinion / challenger /
research delegate for the primary coding agent. Invoked headlessly as
`agy -p "<self-contained prompt>"`.

- STDIN must be closed or piped: `timeout 600 agy -p "..." < /dev/null`
  (headless agy reads non-TTY stdin until EOF and otherwise hangs).
- No model flag by convention — use the Antigravity-account-configured model.
- Account auth under ~/.antigravity/ — no API-key/env prefix needed.
- Plain text out. Be a genuine challenger, not a rubber stamp. Stay on the
  prompt. Be decision-grade and concise.
"""


def _agy_template_text() -> str:
    """Read the bundled generic agy.md template; fall back to the inline copy."""
    tpl = _TEMPLATES_DIR / "agy.md"
    try:
        if tpl.exists():
            return tpl.read_text(encoding="utf-8")
    except OSError:
        pass
    return _AGY_TEMPLATE_FALLBACK


def _content_differs(target: Path, expected: str) -> bool:
    """True if target exists with content != expected (the hash-skip signal).

    Byte-compare (read_bytes), not text — a text compare mis-fires on Windows,
    where a checked-out template can carry CRLF line endings while a freshly
    written one is LF (or vice-versa), yielding a false "differs" that would
    trip the customisation guard on an otherwise-identical file."""
    try:
        return target.read_bytes() != expected.encode("utf-8")
    except OSError:
        return True


def _is_effectively_absent(path: Path) -> bool:
    """True if `path` is missing OR present-but-empty (whitespace-only counts).

    A zero-byte file is NOT a customisation — it is the residue of a write that
    opened the file (truncating it) and then raised. #244 was exactly that:
    `write_text` without an explicit encoding fell back to the LOCALE codec on a
    Windows console and died on U+2190, leaving ~/.copilot/copilot-instructions.md
    at 0 bytes. Every placement guard here is `exists() and not force`, so the
    empty file then reads as "the user already has one" and is NEVER repaired by
    a re-run — the layer looks configured and is inert. That is the #246
    "looks wired, isn't" class, one level up: the file is present, so a
    reference sweep cannot see it either.

    Whitespace-only counts as absent because a file holding one newline carries
    no instruction, no directive and no agent, and nobody authored it on purpose.

    Unreadable is treated as PRESENT (returns False): refusing to guess is safer
    than overwriting a file we could not inspect. A directory on the path lands
    here too, via IsADirectoryError.
    """
    if not path.exists():
        return True
    try:
        return not path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return False


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically (temp file in the same dir + fsync +
    os.replace).

    Atomicity matters for the two global-config files this installer wires:
      - a mid-write interruption never leaves a half-written settings.json /
        CLAUDE.md (the reader — Claude Code's own settings watcher — sees either
        the old file or the whole new one, never a truncated one);
      - os.replace on the same filesystem is atomic on POSIX and Windows.
    The target's mode bits are preserved when it already existed. NEVER writes a
    .bak — backup is the caller's job via _backup()."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    prior_mode = None
    try:
        prior_mode = path.stat().st_mode
    except OSError:
        pass
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if prior_mode is not None:
            try:
                os.chmod(tmp, prior_mode & 0o777)
            except OSError:
                pass  # Windows / unusual fs — mode bits are best-effort
        os.replace(tmp, path)
    except BaseException:
        # Never leave the temp file behind on failure.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _backup(path: Path) -> "Path | None":
    """copy2 `path` -> `path + '.bak'`. Returns the backup Path, or None on
    failure — in which case the caller MUST refuse to modify the original (never
    overwrite without a good backup; mirrors install_agy's data-loss guard)."""
    path = Path(path)
    backup = path.with_suffix(path.suffix + ".bak")
    try:
        shutil.copy2(path, backup)
        return backup
    except OSError:
        return None


def install_agy(gemini_home: Path, force: bool = False, dry_run: bool = False) -> bool:
    """Place the agy host directive at ~/.gemini/agy.md.

    Idempotency mirrors the bootstrap CLAUDE.md pattern (CRITICAL data-loss fix):
      - create-if-absent: write only if the file is missing.
      - hash-skip:        if present and byte-identical to the template, skip.
      - present+differs:  the user has CUSTOMISED it — SKIP unless --force.
      - --force overwrite: write a .bak FIRST, then overwrite.

    The user's live ~/.gemini/agy.md (which may be a hand-tuned host directive)
    is NEVER silently clobbered. Returns True on success/no-op.
    """
    target = gemini_home / "agy.md"
    expected = _agy_template_text()

    # `_is_effectively_absent`, not `.exists()`: a 0-byte agy.md is a failed
    # write, not a customisation, and the "present+differs" branch below would
    # otherwise protect it forever as if the user had authored it.
    if _is_effectively_absent(target):
        if dry_run:
            print(f"    would write {target} (create-if-absent)")
            return True
        gemini_home.mkdir(parents=True, exist_ok=True)
        target.write_text(expected, encoding="utf-8")
        print(f"    + wrote {target} (agy host directive)")
        return True

    if not _content_differs(target, expected):
        print(f"    = {target} already at template content — skipping")
        return True

    # Present and DIFFERENT — user-customised or a different template version.
    if not force:
        print(f"    ⚠ {target} exists and differs (likely your customisation) — leaving as-is")
        print(f"      (use --force to overwrite; a .bak will be written first)")
        return True

    if dry_run:
        print(f"    would back up {target} -> {target}.bak and overwrite (--force)")
        return True
    backup = target.with_suffix(target.suffix + ".bak")
    try:
        shutil.copy2(target, backup)
        print(f"    backup -> {backup}")
    except OSError as exc:
        print(f"    ⚠ could not write backup ({exc}); refusing to overwrite agy.md")
        return False
    target.write_text(expected, encoding="utf-8")
    print(f"    + overwrote {target} (--force; previous saved to {backup.name})")
    return True


# ---------------------------------------------------------------------------
# Global environment wiring — CLAUDE.md + settings.json
# ---------------------------------------------------------------------------
#
# The SINGLE advertised installer must leave a *working* environment. Placing
# skills/agents/commands is not enough — the ecosystem only ACTIVATES when
# ~/.claude/CLAUDE.md (forge routing, autonomy, session-start checks) and the 6
# SessionStart hooks in ~/.claude/settings.json are present. This section wires
# both, mirroring install_agy's create-if-absent / hash-skip / leave-on-differs
# / .bak-on-force safety so a user's customised files are never clobbered.
#
# CANONICAL_SESSION_START_HOOKS is the SINGLE SOURCE OF TRUTH for the 6 hooks;
# bootstrap-environment.py imports it (and merge_missing_session_start_hooks)
# from here so the two entry points cannot drift.

# The 6 canonical SessionStart hook entries the installer ensures are present.
# A hook's IDENTITY for dedup is its inner hooks[0].command string (so a user's
# custom `timeout` on a canonical hook is preserved, not treated as "missing"
# and not duplicated). Injecting only MISSING hooks never removes user-added
# hooks (mobile notifications, Stop hooks, etc.).
CANONICAL_SESSION_START_HOOKS = [
    {
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/skills/_meta/scan_hard_rules.py --hook",
            "timeout": 10,
        }],
    },
    {
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/skills/_meta/forge_reminder_hook.py --hook",
            "timeout": 10,
        }],
    },
    {
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "bash ~/.claude/skills/cross-project-mail/hooks/session-start.sh",
            "timeout": 5,
        }],
    },
    {
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/skills/_meta/freshness_nudge.py --hook",
            "timeout": 10,
        }],
    },
    {
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/skills/_meta/scope_delta_compact_nudge.py --hook",
            "timeout": 10,
        }],
    },
    {
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": "python3 ~/.claude/skills/_meta/memory_primer.py --hook",
            "timeout": 10,
        }],
    },
]


# ---------------------------------------------------------------------------
# Per-OS hook commands (S075) — the half of the matrix that has to WORK, not
# merely be described.
#
# Every canonical hook above is `python3 ~/…` or `bash ~/…`. On Windows all
# three assumptions fail: `python3` is usually absent (the launcher is `py -3`),
# `bash` may not exist at all, and `~` expansion by the hook runner cannot be
# relied on. A Windows install would therefore wire six hooks that never run —
# and hooks fail SILENTLY, so the session-start layer would be inert while
# looking configured. That is the exact failure mode PROJECT.md keeps warning
# about, and it is worth fixing before a machine ever sees it.
#
# Two rules shape the fix:
#
#   1. POSIX output must stay BYTE-IDENTICAL. A hook's identity for dedup is its
#      command string, so changing it on already-deployed machines would inject
#      duplicates of all six on the next install. Windows has no deployed base,
#      so it is free to differ. A test pins the byte-identity.
#
#   2. Windows gets ABSOLUTE paths, resolved at install time. It sidesteps both
#      `~` and %USERPROFILE% expansion questions — we know the real path while
#      installing, so there is nothing to expand later and nothing to get wrong.
# ---------------------------------------------------------------------------

WINDOWS_PYTHON_FALLBACK = "py -3"


def windows_python_command(probe: bool = True) -> str:
    """The interpreter to bake into a Windows hook command.

    Enterprise Windows is not uniform: python.org installs ship the `py` launcher,
    Store and conda installs often give only `python`, and `python3` is frequently
    missing entirely. So this PROBES on a real Windows box and only falls back to
    `py -3` when it cannot (which includes every simulated preview from another
    OS — hence the note in the preview output saying the real choice happens at
    install time).
    """
    if not probe or not sys.platform.startswith("win"):
        return WINDOWS_PYTHON_FALLBACK
    for cand in (["py", "-3"], ["python"], ["python3"]):
        exe = shutil.which(cand[0])
        if not exe:
            continue
        try:
            r = subprocess.run([exe, *cand[1:], "-c", "import sys;print(sys.version_info[0])"],
                               capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS)
            if r.returncode == 0 and (r.stdout or "").strip() == "3":
                return " ".join([cand[0], *cand[1:]])
        except (OSError, subprocess.SubprocessError):
            continue
    return WINDOWS_PYTHON_FALLBACK


def canonical_session_start_hooks(os_key: str | None = None,
                                  claude_home: Path | None = None,
                                  python_cmd: str | None = None) -> list:
    """The six canonical hooks, rendered for a target OS.

    On POSIX this returns CANONICAL_SESSION_START_HOOKS unchanged — same objects'
    content, same command strings, so dedup against existing installs is
    unaffected.
    """
    key = normalize_os(os_key)
    if key != "windows":
        return copy.deepcopy(CANONICAL_SESSION_START_HOOKS)

    home = claude_home if claude_home is not None else DEFAULT_CLAUDE_HOME
    py = python_cmd or windows_python_command()

    def win_path(rel: str) -> str:
        return str(Path(home) / rel).replace("/", "\\")

    out = []
    for entry in CANONICAL_SESSION_START_HOOKS:
        inner = copy.deepcopy(entry["hooks"][0])
        cmd = inner["command"]
        rel = cmd.split("~/.claude/", 1)[1].split(" ", 1)[0]
        tail = cmd[len(cmd.split(" --")[0]):] if " --" in cmd else ""
        # The one bash hook has a Python twin precisely so Windows is not asked
        # to provide bash. Same output, verified identical on POSIX.
        if rel.endswith("hooks/session-start.sh"):
            rel = "skills/cross-project-mail/hooks/session_start.py"
        inner["command"] = f'{py} "{win_path(rel)}"{tail}'
        out.append({"matcher": entry.get("matcher", ""), "hooks": [inner]})
    return out


def _settings_template_text() -> "str | None":
    """Read the bundled templates/settings.global.json, or None if it cannot be
    read.

    None means FAIL LOUDLY (§6.C4.2, R4). There used to be an inline
    `_SETTINGS_TEMPLATE_FALLBACK` here — a full second copy of the template that
    silently took over whenever the bundled file was missing. Two copies of the
    same content in one file is one copy too many: the inline one drifted (it
    still carried `"model": "opus[1m]"` after the tracked template was meant to
    be canonical), and because it engaged silently, the drift was invisible at
    exactly the moment it mattered — a partial clone would install stale config
    and report success.

    A missing template is now a loud refusal instead. The caller writes nothing
    and returns False, matching the malformed-file convention already used for a
    corrupt settings.json."""
    tpl = _TEMPLATES_DIR / "settings.global.json"
    try:
        return tpl.read_text(encoding="utf-8")
    except OSError:
        return None


def merge_missing_session_start_hooks(settings: dict, os_key: str | None = None,
                                      claude_home: Path | None = None) -> list:
    """PURE merge core (shared with bootstrap): mutate `settings` IN PLACE,
    appending each canonical SessionStart entry whose command is absent, and
    return the list of added command strings.

    Dedup identity = the inner hooks[0].command string, so a user's custom
    timeout on an already-present canonical hook is preserved (not re-added).
    User-added hooks are never removed.

    Raises TypeError / ValueError on a wrong-shaped settings object (top-level
    non-dict; hooks not a dict; hooks.SessionStart not a list; a SessionStart
    entry not a dict) so the caller can leave a wrong-shape file untouched
    rather than corrupt it."""
    if not isinstance(settings, dict):
        raise TypeError(f"settings root must be a JSON object, got {type(settings).__name__}")
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise TypeError("settings['hooks'] must be a JSON object")
    ss = hooks.setdefault("SessionStart", [])
    if not isinstance(ss, list):
        raise TypeError("settings['hooks']['SessionStart'] must be a list")

    existing_cmds = set()
    for entry in ss:
        if not isinstance(entry, dict):
            raise ValueError("each settings['hooks']['SessionStart'] entry must be a JSON object")
        for h in entry.get("hooks", []) or []:
            if isinstance(h, dict):
                cmd = h.get("command")
                if cmd:
                    existing_cmds.add(cmd)

    added = []
    # os_key defaults to THIS machine, so every existing caller is unchanged on
    # POSIX and correct on Windows without being updated.
    for new_entry in canonical_session_start_hooks(os_key, claude_home):
        new_cmd = new_entry["hooks"][0]["command"]
        if new_cmd in existing_cmds:
            continue
        added.append(new_cmd)
        ss.append(copy.deepcopy(new_entry))  # deepcopy: never alias the module constant
    return added


# ---------------------------------------------------------------------------
# canonical-config-provenance (WP-005, §6.C4.6 + §11 A1)
#
# The two global config files are the only things the installer writes
# WHOLE-FILE into a directory the user also owns and edits. Everything else
# under ~/.claude routes through place() and is covered by install-archive.
# That makes them the one place where "is this file mine to refresh, or the
# user's to leave alone?" cannot be answered from the filesystem — hence
# recorded provenance.
# ---------------------------------------------------------------------------

# Destination filename -> manifest key. The manifest is keyed by FILENAME so
# the accessor reads literally as `canonical.<file>.sha256` (§6.C4.6).
CANONICAL_CONFIG_FILES = ("CLAUDE.md", "settings.json")

# Verdicts. `absent` is separated from `customized` because it authorizes a
# write while carrying no risk (there is nothing to destroy), whereas
# `customized` forbids one.
PROVENANCE_ABSENT = "absent"
PROVENANCE_UNMODIFIED = "unmodified"
PROVENANCE_CUSTOMIZED = "customized"


def read_canonical_hash(canonical_block: "dict | None", filename: str) -> "str | None":
    """Extract `<filename>.sha256` from a manifest's `canonical` BLOCK, or None.

    Takes the block itself rather than the whole manifest, because that is what
    both production call sites hold and it keeps the function's job narrow:
    safely read one hash, decide nothing else.

    None is the NO-PROVENANCE signal, and — exactly as with read_manifest() —
    it is deliberately also the cannot-interpret-it signal. A missing block, a
    manifest predating this feature, a block of the wrong shape, and a hash that
    is not 64 lowercase hex characters all collapse to the same answer, because
    they all mean the same thing: nothing here proves the installer wrote that
    file.

    Near-miss forms (uppercase hex, a 'sha256:' prefix) are rejected rather than
    normalized. Normalizing them would turn an equality check into a heuristic,
    and this particular equality check is what authorizes overwriting a user's
    config file. Never raises."""
    try:
        block = canonical_block
        if not isinstance(block, dict):
            return None
        rec = block.get(filename)
        if not isinstance(rec, dict):
            return None
        digest = rec.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            return None
        if any(c not in "0123456789abcdef" for c in digest):
            return None
        return digest
    except (AttributeError, TypeError):
        return None


def classify_canonical_provenance(destination: Path,
                                  recorded_hash: "str | None") -> str:
    """Classify a global config destination: absent / unmodified / customized.

    `unmodified` requires BOTH a recorded hash AND a computable destination hash
    AND equality between them. Every other combination is `customized`, which is
    the fail-safe answer:

      - no recorded hash            -> customized. Content that merely HAPPENS to
                                       equal what the installer would write is not
                                       proof the installer wrote it. This is the
                                       case that protects a hand-copied config.
      - destination unreadable      -> customized. Cannot classify means must not
                                       overwrite.
      - both hashes absent          -> customized. Two Nones must not compare
                                       equal; this is the one input pair where a
                                       naive `==` returns exactly the wrong answer.

    Note this reads content, never mtime or size — the edit being detected is
    precisely the kind the filesystem metadata may not advertise."""
    destination = Path(destination)
    if not destination.exists() and not destination.is_symlink():
        return PROVENANCE_ABSENT
    if not recorded_hash:
        return PROVENANCE_CUSTOMIZED
    candidate = _sha256_file(destination)
    if not candidate:
        return PROVENANCE_CUSTOMIZED
    return (PROVENANCE_UNMODIFIED if candidate == recorded_hash
            else PROVENANCE_CUSTOMIZED)


def _record_canonical(canonical_out: "dict | None", filename: str,
                      text: str, write_kind: str) -> None:
    """Record the hash of content just written WHOLE-FILE (§11 A1).

    Callers must invoke this ONLY on the two sanctioned whole-file writes —
    create-if-absent, or an overwrite (--force-global-config / a provenance-
    authorized auto-update) — and NEVER on the merge path.

    That prohibition is the entire safety argument. The merge path writes the
    USER's parsed settings plus injected hooks; recording a hash there would
    make the NEXT run see a hash match, conclude "pure installer output", and
    whole-file overwrite a file that is largely the user's — on a default,
    non-mc run where the archive contract does not apply.

    Hashes the TEXT that was written rather than re-reading the destination, so
    the record describes what the installer produced, not whatever a concurrent
    writer may have left behind. Never raises."""
    if canonical_out is None:
        return
    try:
        canonical_out[filename] = {
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "recorded_at": _iso_utc_now(),
            "write_kind": write_kind,
        }
    except (TypeError, ValueError, UnicodeEncodeError):
        pass


def install_settings(claude_home: Path, force_global: bool = False,
                     dry_run: bool = False,
                     canonical_prev: "dict | None" = None,
                     canonical_out: "dict | None" = None) -> bool:
    """Wire ~/.claude/settings.json (the 6 SessionStart hooks + defaultMode).

    Behavior matrix (mirrors install_agy's safety; §3 of the design):
      - absent                         → write the full template (atomic).
      - present, byte-identical        → skip.
      - present, valid, differs        → inject ONLY the missing canonical hooks
                                         (.bak first, atomic); every other user
                                         value (model, defaultMode, …) untouched.
                                         --force_global → .bak + overwrite whole.
      - present, malformed / wrong-shape → leave UNTOUCHED, loud warning, return
                                         False (never crash, never false-"done").
                                         --force_global → .bak (raw bytes) + overwrite.

    NEW in WP-005 (§6.C4.6 / D6): a destination that differs from the template
    but whose hash equals the RECORDED canonical hash is provably byte-for-byte
    what the installer last wrote, so it is refreshed automatically (.bak first).
    That is what lets the removal of the installer-supplied `model` key reach
    boxes where the installer put it, without touching boxes where the user did.

    `canonical_prev` is the previous manifest's canonical block (read-only);
    `canonical_out` is a dict this function POPULATES on whole-file writes only
    (§11 A1 — never on the merge path).

    Byte-compare (read_bytes), not text — CRLF-safe. Returns False ONLY when it
    deliberately leaves a malformed/wrong-shape file untouched, when a backup
    could not be written, or when the bundled template is missing; True on
    success / legitimate no-op."""
    target = claude_home / "settings.json"
    template_text = _settings_template_text()

    # --- template missing → FAIL LOUDLY (§6.C4.2, R4) ---
    # There is no inline fallback any more, and that is the point: silently
    # installing a second, drifting copy of the template is worse than not
    # installing at all, because it reports success.
    if template_text is None:
        print(f"    ⚠ bundled template {_TEMPLATES_DIR / 'settings.global.json'} is missing "
              f"or unreadable — refusing to write {target}.")
        print(f"      Re-clone or repair the repository; the installer will not "
              f"substitute an embedded copy.")
        return False

    recorded = read_canonical_hash(canonical_prev, "settings.json")

    # --- absent → write full template (A1-sanctioned whole-file write) ---
    if not target.exists():
        if dry_run:
            print(f"    would write {target} (create-if-absent; 6 hooks + defaultMode)")
            return True
        _atomic_write_text(target, template_text)
        _record_canonical(canonical_out, "settings.json", template_text, "create")
        print(f"    + wrote {target} (settings.json — 6 SessionStart hooks + defaultMode)")
        return True

    # --- present: byte-compare against the template ---
    try:
        current_bytes = target.read_bytes()
    except OSError as exc:
        print(f"    ⚠ could not read {target} ({exc}) — leaving as-is")
        return False
    if current_bytes == template_text.encode("utf-8"):
        print(f"    = {target} already at template content — skipping")
        return True

    # --- present + differs + provenance says WE wrote it → auto-update (D6) ---
    # Deliberately ahead of the force_global branch: both end in a whole-file
    # write, and letting this one run first keeps the outcome identical whether
    # or not the flag is present (no double .bak, no double write).
    if (not force_global
            and classify_canonical_provenance(target, recorded) == PROVENANCE_UNMODIFIED):
        if dry_run:
            print(f"    would refresh {target} (hash matches recorded installer output; .bak first)")
            return True
        backup = _backup(target)
        if backup is None:
            # A1 item 4: the auto-update path gets the same refusal as every
            # other overwrite. "Provably installer output" is a claim about
            # bytes, not a guarantee the user has no use for them.
            print(f"    ⚠ could not write backup of {target}; refusing to refresh")
            return False
        print(f"    backup -> {backup}")
        _atomic_write_text(target, template_text)
        _record_canonical(canonical_out, "settings.json", template_text, "auto-update")
        print(f"    + refreshed {target} (was unmodified installer output; "
              f"previous saved to {backup.name})")
        return True

    # --- present + differs: parse to decide merge vs. malformed ---
    try:
        current = json.loads(current_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Malformed JSON.
        if not force_global:
            print(f"    ⚠ {target} is not valid JSON ({exc}) — leaving it UNTOUCHED.")
            print(f"      Fix it, or re-run with --force-global-config to replace it (a .bak is written first).")
            return False
        if dry_run:
            print(f"    would back up {target} -> {target.name}.bak (raw bytes) and overwrite (--force-global-config)")
            return True
        backup = _backup(target)
        if backup is None:
            print(f"    ⚠ could not write backup of {target}; refusing to overwrite")
            return False
        print(f"    backup -> {backup}")
        _atomic_write_text(target, template_text)
        _record_canonical(canonical_out, "settings.json", template_text, "force")
        print(f"    + overwrote {target} (--force-global-config; previous saved to {backup.name})")
        return True

    # --- present + valid JSON + differs ---
    if force_global:
        # Whole-file overwrite (.bak first) — A1-sanctioned, so it records
        # provenance. This is also how a customized box re-enters the
        # auto-update track: the user asserted the installer's copy is the one
        # they want, and from here the installer can prove it wrote it.
        if dry_run:
            print(f"    would back up {target} -> {target.name}.bak and overwrite whole file (--force-global-config)")
            return True
        backup = _backup(target)
        if backup is None:
            print(f"    ⚠ could not write backup of {target}; refusing to overwrite")
            return False
        print(f"    backup -> {backup}")
        _atomic_write_text(target, template_text)
        _record_canonical(canonical_out, "settings.json", template_text, "force")
        print(f"    + overwrote {target} (--force-global-config; previous saved to {backup.name})")
        return True

    # Default run: inject ONLY the missing canonical hooks; leave every other key.
    #
    # §11 A1 CRITICAL — everything below this line is the MERGE path, and it
    # must NEVER call _record_canonical(). What it writes is the user's parsed
    # settings plus injected hooks, not installer content. Recording a hash for
    # it would make the next run see a match, conclude "pure installer output",
    # and whole-file overwrite a file that is largely the user's.
    try:
        added = merge_missing_session_start_hooks(current)
    except (TypeError, ValueError) as exc:
        # Valid JSON but wrong shape (top-level array, hooks not a dict, …).
        print(f"    ⚠ {target} is valid JSON but the wrong shape ({exc}) — leaving it UNTOUCHED.")
        print(f"      Fix it, or re-run with --force-global-config to replace it (a .bak is written first).")
        return False

    if not added:
        # Differs in some non-hook key, but all 6 hooks already present — leave it.
        print(f"    = {target} has all 6 SessionStart hooks already — leaving your other settings as-is")
        return True

    if dry_run:
        for cmd in added:
            print(f"    would add SessionStart hook: {cmd}")
        return True
    backup = _backup(target)
    if backup is None:
        print(f"    ⚠ could not write backup of {target}; refusing to modify")
        return False
    print(f"    backup -> {backup}")
    _atomic_write_text(target, json.dumps(current, indent=2) + "\n")
    print(f"    + injected {len(added)} missing SessionStart hook(s) into {target} "
          f"(other settings preserved; previous saved to {backup.name})")
    for cmd in added:
        print(f"        + {cmd}")
    return True


def install_claude_md(repo_root: Path, claude_home: Path, force_global: bool = False,
                     dry_run: bool = False,
                     canonical_prev: "dict | None" = None,
                     canonical_out: "dict | None" = None) -> bool:
    """Wire ~/.claude/CLAUDE.md (forge routing, autonomy, session-start checks).

    Monolithic doc — no partial merge (§3):
      - absent                    → write (copy the repo CLAUDE.md, atomic).
      - present, byte-identical   → skip.
      - present, differs, hash matches recorded provenance
                                  → auto-update (.bak first). NEW in WP-005.
      - present, differs          → leave untouched (note: customised — use
                                    --force-global-config). --force_global → .bak
                                    + overwrite.

    Having no merge path makes provenance matter MORE here than for
    settings.json, not less: without it the only options for a differing file
    are "never update" or "overwrite the user's edits", and this cycle refuses
    both as defaults.

    `canonical_prev` is the previous manifest's canonical block (read-only);
    `canonical_out` is populated on whole-file writes only (§11 A1).

    Byte-compare (read_bytes), not text — CRLF-safe. Returns False only on a
    genuine failure (repo CLAUDE.md missing, or a backup could not be written)."""
    src = repo_root / "CLAUDE.md"
    target = claude_home / "CLAUDE.md"

    if not src.exists():
        print(f"    ⚠ repo CLAUDE.md missing ({src}) — cannot wire global instructions")
        return False
    try:
        expected_text = src.read_text(encoding="utf-8")
        expected_bytes = src.read_bytes()
    except OSError as exc:
        print(f"    ⚠ could not read {src} ({exc}) — skipping CLAUDE.md wiring")
        return False

    recorded = read_canonical_hash(canonical_prev, "CLAUDE.md")

    if not target.exists():
        if dry_run:
            print(f"    would write {target} (create-if-absent)")
            return True
        _atomic_write_text(target, expected_text)
        _record_canonical(canonical_out, "CLAUDE.md", expected_text, "create")
        print(f"    + wrote {target} (global instructions)")
        return True

    try:
        if target.read_bytes() == expected_bytes:
            print(f"    = {target} already at repo content — skipping")
            return True
    except OSError:
        pass  # fall through and treat as differing

    # --- present + differs + provenance says WE wrote it → auto-update (D6) ---
    if (not force_global
            and classify_canonical_provenance(target, recorded) == PROVENANCE_UNMODIFIED):
        if dry_run:
            print(f"    would refresh {target} (hash matches recorded installer output; .bak first)")
            return True
        backup = _backup(target)
        if backup is None:
            print(f"    ⚠ could not write backup of {target}; refusing to refresh")
            return False
        print(f"    backup -> {backup}")
        _atomic_write_text(target, expected_text)
        _record_canonical(canonical_out, "CLAUDE.md", expected_text, "auto-update")
        print(f"    + refreshed {target} (was unmodified installer output; "
              f"previous saved to {backup.name})")
        return True

    # Present and different — user-customised.
    if not force_global:
        print(f"    ⚠ {target} exists and differs (customised) — leaving as-is")
        print(f"      (use --force-global-config to overwrite; a .bak is written first)")
        return True

    if dry_run:
        print(f"    would back up {target} -> {target.name}.bak and overwrite (--force-global-config)")
        return True
    backup = _backup(target)
    if backup is None:
        print(f"    ⚠ could not write backup of {target}; refusing to overwrite")
        return False
    print(f"    backup -> {backup}")
    _atomic_write_text(target, expected_text)
    _record_canonical(canonical_out, "CLAUDE.md", expected_text, "force")
    print(f"    + overwrote {target} (--force-global-config; previous saved to {backup.name})")
    return True


def _hook_script_path(command: str, claude_home: Path) -> "Path | None":
    """Extract the `~/.claude/skills/...` script referenced by a hook command
    and remap it under `claude_home`. Returns the Path, or None if the command
    references no such script."""
    for tok in command.split():
        if tok.startswith("~/.claude/skills/"):
            rel = tok[len("~/.claude/"):]
            return claude_home / rel
    return None


def _missing_hook_scripts(claude_home: Path) -> list:
    """Post-install readiness check: return the canonical hook commands whose
    referenced script is missing under claude_home/skills (configured ≠ active —
    a hook is inert until its script exists). Read-only."""
    missing = []
    for entry in CANONICAL_SESSION_START_HOOKS:
        cmd = entry["hooks"][0]["command"]
        p = _hook_script_path(cmd, claude_home)
        if p is not None and not p.exists():
            missing.append(cmd)
    return missing


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

**Agent Skills (SKILL.md) are native to Copilot now.** The Copilot CLI AND
VS Code (1.123+) auto-discover skills from these locations — including
`~/.claude/skills/`, so the agent-foundry skills are consumed for free once
installed:

- `~/.copilot/skills/`
- `~/.claude/skills/`          ← agent-foundry installs here; Copilot reads it
- `<repo>/.github/skills/`
- `<repo>/.claude/skills/`

| Tool        | Discovery                                                          |
|-------------|--------------------------------------------------------------------|
| Claude Code | auto, from `~/.claude/skills/`                                     |
| Copilot CLI | auto, from `~/.claude/skills/` + `~/.copilot/skills/` + repo dirs  |
| VS Code 1.123+ | auto, from `~/.claude/skills/` (+ `chat.agentSkillsLocations`)  |
| Codex CLI   | symlinks under `~/.codex/skills/<name>/`                           |
| Gemini CLI  | `gemini skills link <path>` per skill (skills only — not a delegate) |

Skills are auto-discovered from each skill's frontmatter `description:`.
This file (and per-repo `AGENTS.md` / `.github/copilot-instructions.md`)
supplies cross-tool *instructions*; the skills themselves are discovered
natively from the directories above.

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


def mirror_copilot_skills(repo_root: Path, copilot_home: Path, mode: str,
                          force: bool = False) -> tuple[int, int]:
    """OPT-IN mirror of skills into ~/.copilot/skills/ (same pattern as the
    codex mirror). Copilot already auto-discovers ~/.claude/skills/, so this is
    purely additive for users who keep Copilot's own skills dir authoritative.

    Returns (installed, skipped).
    """
    skills_src = repo_root / "skills"
    if not skills_src.exists():
        print(f"    ⚠ {skills_src} missing — nothing to mirror")
        return 0, 0
    skills_target = copilot_home / "skills"
    skills_target.mkdir(parents=True, exist_ok=True)
    installed = skipped = 0
    for skill in sorted(skills_src.iterdir()):
        if not skill.is_dir() or not (skill / "SKILL.md").exists():
            continue
        dest = skills_target / skill.name
        if (dest.exists() or dest.is_symlink()) and not force:
            skipped += 1
            continue
        _replace_existing(dest)
        link_or_copy(skill, dest, mode)
        installed += 1
    return installed, skipped


def install_copilot(repo_root: Path, force: bool = False,
                    mirror_skills: bool = False, mode: str = "link",
                    copilot_home: Path | None = None) -> bool:
    """
    Install GitHub Copilot CLI / VS Code integration.

    IMPORTANT (research-verified): Agent Skills (SKILL.md) are native to Copilot
    CLI and VS Code 1.123+. Both auto-discover skills from ~/.claude/skills/ —
    so the agent-foundry skills installed by the `claude` target are ALREADY
    consumed by Copilot and VS Code with no bridge. The stale "Copilot has no
    skill concept" premise no longer holds.

    Copilot CLI (`@github/copilot`) reads *instructions* from (precedence order):
      1. .github/copilot-instructions.md  (per-repo; `copilot init` bootstraps it)
      2. AGENTS.md                        (per-repo, repo root)
      3. ~/.copilot/copilot-instructions.md  (user-global)

    We write the user-global instructions file (create-if-absent) so Copilot has
    cross-tool context regardless of project. Per-project `.github` setup is left
    to `copilot init` (Copilot's own read-only repo bootstrap).

    Optionally (`mirror_skills=True`) also mirror skills into ~/.copilot/skills/
    — opt-in, additive, same pattern as the codex mirror.
    """
    copilot_home = copilot_home or DEFAULT_COPILOT_HOME
    copilot_home.mkdir(parents=True, exist_ok=True)
    target = copilot_home / "copilot-instructions.md"

    if not _is_effectively_absent(target) and not force:
        print(f"    ⚠ {target} already exists — leaving as-is (use --force to overwrite)")
    else:
        # encoding="utf-8" is REQUIRED, not tidiness. COPILOT_AGENTS_MD contains
        # `←` (U+2190) and other non-Latin-1 glyphs; without an explicit encoding
        # Python uses the LOCALE codec, which on a Windows console is cp1252 and
        # raises `'charmap' codec can't encode character '←'`. Reported from
        # a real enterprise-laptop run, 2026-07-30. _force_utf8_streams() does not
        # help here — it reconfigures stdout/stderr, not file writes.
        target.write_text(COPILOT_AGENTS_MD, encoding="utf-8")
        print(f"    + wrote {target}")

    # VSPrime at USER scope, so it is in the agent picker in every project
    # rather than only where someone remembered to run --vscode-workspace.
    #
    # `~/.copilot/agents/` is the documented user-profile location for custom
    # agents (vscode-agents/references/custom-agents.md) and is read by both
    # Copilot CLI and VS Code. The workspace copy that --vscode-workspace
    # places is unchanged and still wins, because workspace scope is checked
    # first — a project that wants its own VSPrime keeps it.
    #
    # THE ASYMMETRY IS THE WHOLE POINT, so do not "tidy" this into
    # ~/.claude/agents/. VS Code reads BOTH trees at user scope (verified on
    # 1.131, 2026-07-30 — the doc table dated 2026-06-24 lists only the
    # workspace .claude/agents/ and is stale). Claude Code reads only its own.
    # So ~/.copilot/agents/ is the one-way home: VS Code and Copilot see
    # VSPrime, Claude Code never does.
    #
    # That matters because VSPrime exists to substitute for the SessionStart
    # hooks VS Code does not have — hooks Claude Code DOES have. In the Claude
    # Code picker it would be a redundant agent offering to do, worse, a job
    # already done before the first turn. Put it in the shared tree and every
    # Claude Code session gets that confusion permanently.
    #
    # Placed by the INSTALLER on purpose. Hand-dropping it into ~/.copilot
    # would leave a file no installer owns, reinstalls never refresh and
    # `--mode mc` never prunes — the same shape as scout.md living only in
    # ~/.claude (#208) and VSPrime's own flag never being registered (#245).
    # Every *.agent.md in vs-code/agents/, not just VSPrime. The filename used to
    # be hardcoded, so the consultation handles (#274) would have shipped in the
    # repo and been placed by nothing — the "looks wired, isn't" class that has
    # already cost this project four defects (#245 chief among them).
    #
    # OWNERSHIP SPLIT, and it is not cosmetic:
    #   * GENERATED files (they carry the render marker) are DERIVED artifacts and
    #     are always refreshed. A handle carrying a stale model id fails SILENTLY
    #     as a permissions error, so "leave as-is" is the wrong default for
    #     anything the renderer owns.
    #   * Hand-authored files (VSPrime) keep the previous skip-if-present
    #     behaviour. #270 — that they are in no manifest and so can never be
    #     pruned — is untouched here and still open.
    agents_src = repo_root / "vs-code" / "agents"
    if agents_src.is_dir():
        for src_file in sorted(agents_src.glob("*.agent.md")):
            dst = copilot_home / "agents" / src_file.name
            content = src_file.read_text(encoding="utf-8")
            is_generated = "generated by vs-code/scripts/render_handles.py" in content
            existing_is_ours = False
            if dst.is_file():
                try:
                    existing_is_ours = (
                        "generated by vs-code/scripts/render_handles.py"
                        in dst.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
            if (not _is_effectively_absent(dst) and not force
                    and not (is_generated and existing_is_ours)):
                print(f"    ⚠ {dst} already exists — leaving as-is (use --force)")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content, encoding="utf-8")
            label = "refreshed, generated" if is_generated else "user scope — all projects"
            handle_name = src_file.name[:-len(".agent.md")]
            print(f"    + wrote {dst} (@{handle_name}, {label})")

    has_copilot = shutil.which("copilot") is not None or any(
        loc.exists() for loc in _known_locations("copilot"))
    has_code = shutil.which("code") is not None or any(
        loc.exists() for loc in _known_locations("code"))
    if has_copilot or has_code:
        consumers = " + ".join(
            ([f"Copilot CLI"] if has_copilot else []) + (["VS Code"] if has_code else []))
        print(f"    ✓ {consumers} natively auto-discover ~/.claude/skills/ — agent-foundry")
        print(f"      skills are already available there (install the `claude` target).")
    if not has_copilot:
        print(f"    ⚠ `copilot` not found; install via: npm install -g @github/copilot")

    if mirror_skills:
        ins, sk = mirror_copilot_skills(repo_root, copilot_home, mode, force=force)
        print(f"    + mirrored {ins} skill(s) into {copilot_home/'skills'} (skipped {sk})")

    print(f"    Per-project setup: cd <project> && copilot init")
    print(f"      (or copy/symlink {target.name} → <project>/AGENTS.md)")
    print(f"    Model selection:   copilot --model <name>   (detect first — see below)")
    print(f"    VS Code workspace: python3 install.py --vscode-workspace <path>")
    print(f"      places AGENTS.md, .vscode/tasks.json + mcp.json, the VSPrime agent and")
    print(f"      the /prime command. Skills need no bridge; startup and agents do.")
    return True


GIT_HOOK_MARKER = "# managed-by: foundry-lab/skills/secret-scanning/hooks"

GIT_HOOKS = (
    ("pre-commit", "pre_commit.py"),
    ("pre-push", "pre_push.py"),
)


def _hook_shebang() -> str:
    """Bake the interpreter we are running under, rather than hoping for PATH.

    `writing-portable-python` rule 7. `#!/usr/bin/env python3` fails on exactly the
    machine this work exists for: enterprise Windows commonly has `py` or `python`
    and no `python3` at all, and a hook that cannot launch is a gate that does not
    exist -- which is #250 all over again.

    HONEST LIMIT: on Windows, Git runs hooks through its bundled MSYS shell, which
    wants `/c/Users/...` rather than `C:\\Users\\...`, so the drive letter is
    rewritten here. That conversion has NOT been executed on a Windows machine. It
    is the first thing to check when this reaches the laptop, and the failure would
    be loud (git reports a bad interpreter), not silent.
    """
    exe = Path(sys.executable).resolve()
    if os.name == "nt":
        text = str(exe).replace("\\", "/")
        if len(text) > 2 and text[1] == ":":
            text = "/" + text[0].lower() + text[2:]
        return "#!" + text
    return "#!" + str(exe)


def install_git_hooks(repo_root: Path, target_repo: Path, *, force: bool = False,
                      dry_run: bool = False) -> bool:
    """Install the Python pre-commit and pre-push hooks into `target_repo`.

    Wired into the installer because of #250: on the Windows laptop `.git/hooks/`
    held ONLY `.sample` files and `core.hooksPath` was unset, so every commit and
    push was unscanned -- including the commit made while diagnosing it. All of
    #239's rule-parity work is moot in a repo where no scanner runs at all, and
    nothing in the install path had ever placed a hook.

    Runs by DEFAULT rather than behind an opt-in flag. An opt-in security gate is
    how this hole existed, and #240's extras were made default-on for the same
    reason. `--no-git-hooks` opts out.

    REFUSES to install an inert hook, exactly as the bash installer it replaces
    did: a hook that cannot find a scanner advertises protection it does not
    provide, which is worse than no hook at all.
    """
    repo_root = Path(repo_root)
    target_repo = Path(target_repo).expanduser()

    git_dir = target_repo / ".git"
    if not git_dir.exists():
        print(f"  = {target_repo} is not a git repo — no hooks placed")
        return False

    # A worktree/submodule .git is a FILE pointing at the real dir.
    if git_dir.is_file():
        try:
            pointer = git_dir.read_text(encoding="utf-8").strip()
            if pointer.startswith("gitdir:"):
                git_dir = (target_repo / pointer.split(":", 1)[1].strip()).resolve()
        except OSError:
            print(f"  ⚠ cannot read {git_dir} — no hooks placed")
            return False

    # core.hooksPath wins over .git/hooks when set; writing to the wrong one
    # places a file git will never run, which looks exactly like success.
    hooks_dir = git_dir / "hooks"
    rc, out = run_probe(["git", "-C", str(target_repo), "config", "--get", "core.hooksPath"])
    if rc == 0 and out.strip():
        configured = Path(out.strip()).expanduser()
        hooks_dir = configured if configured.is_absolute() else (target_repo / configured)
        print(f"  i core.hooksPath is set — installing into {hooks_dir}")

    src_dir = repo_root / "skills" / "secret-scanning" / "hooks"
    scanner_repo = target_repo / "scripts" / "secrets-scan.py"
    scanner_home = Path.home() / ".claude" / "skills" / "secret-scanning" / "scripts" / "secrets-scan.py"
    if not scanner_repo.is_file() and not scanner_home.is_file():
        print("  ⚠ REFUSING to install git hooks: no secrets-scan.py resolves")
        print(f"      looked in: {scanner_repo}")
        print(f"                 {scanner_home}")
        print("      An inert hook would claim protection it cannot provide.")
        return False

    shebang = _hook_shebang()
    placed = 0
    for hook_name, src_name in GIT_HOOKS:
        src = src_dir / src_name
        if not src.is_file():
            print(f"  ⚠ {src_name} missing from the repo — {hook_name} not placed")
            continue
        dst = hooks_dir / hook_name

        if dst.exists():
            existing = ""
            try:
                existing = dst.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
            if GIT_HOOK_MARKER not in existing and "secrets-scan" not in existing:
                # Somebody else's hook. Never clobber it silently.
                backup = dst.with_name(f"{hook_name}.bak-{_utc_stamp()}")
                if not dry_run:
                    shutil.copy2(dst, backup)
                print(f"  i existing unmanaged {hook_name} backed up to {backup.name}")

        body = src.read_text(encoding="utf-8")
        if body.startswith("#!"):
            body = body.split("\n", 1)[1] if "\n" in body else ""
        content = shebang + "\n" + GIT_HOOK_MARKER + "\n" + body

        if dry_run:
            print(f"  + {hook_name} → {dst} (dry run)")
            placed += 1
            continue

        hooks_dir.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")
        try:
            dst.chmod(0o755)
        except OSError:
            pass  # no exec bit on Windows; git runs it via its shell regardless
        print(f"  ✓ {hook_name} → {dst}")
        placed += 1

    if placed:
        print(f"  interpreter baked into the hooks: {shebang[2:]}")
    return placed > 0


def install_vscode_workspace(repo_root: Path, workspace: Path, force: bool = False,
                             dry_run: bool = False) -> bool:
    """Place the VS Code / Copilot workspace files from `vs-code/`.

    Skills need NO bridge — VS Code and Copilot auto-discover ~/.claude/skills/. What does
    not come across for free is startup, the custom agents, slash commands and MCP wiring,
    and that is all this places.

    Idempotency mirrors install_agy: create-if-absent, and leave a customised file alone
    unless --force. A workspace file the user has edited is theirs.
    """
    # Coerce here rather than at the call site: argparse hands us a str, and this
    # function had NEVER ONCE EXECUTED (the --vscode-workspace flag was never
    # registered, S075 #245), so the `str / str` TypeError below sat undiscovered.
    # Accepting either type keeps every caller correct.
    repo_root = Path(repo_root)
    workspace = Path(workspace).expanduser()

    src = repo_root / "vs-code"
    if not src.is_dir():
        print(f"    ⚠ {src} not found — skipping VS Code workspace setup")
        return False

    # (source, destination-relative-to-workspace)
    placements = [
        (src / "AGENTS.md", workspace / "AGENTS.md"),
        (src / "tasks.json", workspace / ".vscode" / "tasks.json"),
        (src / "mcp.json", workspace / ".vscode" / "mcp.json"),
        (src / "agents" / "vsprime.agent.md", workspace / ".github" / "agents" / "vsprime.agent.md"),
        (src / "prompts" / "prime.prompt.md", workspace / ".github" / "prompts" / "prime.prompt.md"),
    ]

    placed = skipped = 0
    for s, d in placements:
        if not s.is_file():
            continue
        if not _is_effectively_absent(d) and not force:
            print(f"    ⚠ {d} exists — leaving as-is (use --force to overwrite)")
            skipped += 1
            continue
        if dry_run:
            print(f"    [dry-run] would write {d}")
            placed += 1
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text(s.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"    + wrote {d}")
        placed += 1

    print(f"    VS Code workspace: {placed} placed, {skipped} left as-is")
    print(f"    Startup: `foundry: session prime` runs on folderOpen — the only automatic")
    print(f"      trigger VS Code offers. It writes .foundry/session-state.json; it cannot")
    print(f"      make the model READ it. See vs-code/docs/startup.md for the four layers.")
    print(f"    Models:  python3 vs-code/scripts/detect_models.py  (detected, never hardcoded)")

    # Everything placed above is workspace-relative and therefore portable. What is NOT
    # portable is where VS Code keeps USER settings, and whether `code` is on PATH — so
    # report both rather than leaving the user to discover the difference.
    print(f"    User config: {vscode_user_dir()}")
    if sys.platform == "darwin" and shutil.which("code") is None:
        print(f"    ⚠ macOS: the `code` CLI is NOT on PATH by default.")
        print(f"      Command Palette → \"Shell Command: Install 'code' command in PATH\",")
        print(f"      then restart the terminal. See vs-code/docs/platforms.md §3.")
    return placed > 0


# ---------------------------------------------------------------------------
# The OS x TOOL install matrix (S075)
#
# Before this, per-OS behaviour lived in ~8 inline `sys.platform == "win32"`
# checks scattered through 4,000 lines. Nobody could answer "what does this do
# for VS Code on macOS?" without reading all of it, and nobody could answer it
# AT ALL from a different machine — which is the case that matters, because the
# harness is developed on Linux and run on a Windows laptop and a Mac.
#
# So the matrix is DECLARED, and every function that consumes it takes an
# explicit `os_key` rather than reading sys.platform. That is what makes
# `--preview --os windows` possible from anywhere, and what makes each cell
# unit-testable without the OS it describes. It follows the shape
# vscode_user_dir() already had, generalised.
#
# `native` is the field that keeps the matrix honest. Several tools READ our
# files without anything being placed — VS Code and Copilot both discover
# ~/.claude/skills, and VS Code reads ~/.claude/settings.json for hooks (#241).
# A matrix that only listed writes would imply those cells do nothing, when in
# fact they are the cells that work best.
# ---------------------------------------------------------------------------

OS_KEYS = ("windows", "macos", "linux")
MATRIX_TOOLS = ("claude", "codex", "copilot", "vscode", "agy", "gemini")

# TWO SCOPES, and conflating them is what made the gemini question confusing enough
# to need asking twice:
#
#   SKILLS CONSUMER — a tool that READS the skill library. gemini IS one, on legacy
#     enterprise systems, and therefore IS a live install target. Nothing about the
#     2026-07-25 change touches this.
#
#   DELEGATE — a tool the harness CALLS OUT TO for second opinions, challenger
#     review or research. gemini is NOT one: agy replaced it on 2026-07-25, and no
#     skill may reintroduce `gemini -p` or `mcp__gemini-cli__*`.
#
# So "gemini is retired" and "install skills for gemini" are both true, because they
# are statements about different scopes. The installer only ever spoke to the first;
# the retirement only ever spoke to the second. Every cell below declares which
# scopes it participates in, so the distinction survives the next person to read it.
SKILL_CONSUMERS = ("claude", "codex", "copilot", "vscode", "gemini")
DELEGATES = ("claude", "codex", "agy")


def normalize_os(platform_name: str | None = None) -> str:
    """sys.platform -> a matrix key. Accepts matrix keys unchanged so callers can
    pass either, which is what lets --os windows work on a Linux box."""
    p = (platform_name if platform_name is not None else sys.platform).lower()
    if p in OS_KEYS:
        return p
    if p.startswith("win") or p == "cygwin":
        return "windows"
    if p == "darwin":
        return "macos"
    return "linux"


def user_home(os_key: str, home: Path | None = None) -> Path:
    return home if home is not None else Path.home()


def _appdata_for(os_key: str, home: Path) -> Path:
    """%APPDATA% when we are actually ON Windows; the conventional path when we
    are only SIMULATING it. Reading the live env var during a simulation would
    silently produce a Linux path under a Windows heading."""
    if os_key == "windows" and sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    return home / "AppData" / "Roaming"


def resolve_cell(tool: str, os_key: str, home: Path | None = None) -> dict:
    """One matrix cell: where things go, what is already discovered, what bites.

    Pure — no filesystem probing, no sys.platform reads. Same inputs, same
    output, on any machine.
    """
    if tool not in MATRIX_TOOLS:
        raise ValueError(f"unknown tool {tool!r}; expected one of {MATRIX_TOOLS}")
    if os_key not in OS_KEYS:
        raise ValueError(f"unknown os {os_key!r}; expected one of {OS_KEYS}")
    h = user_home(os_key, home)
    win, mac = os_key == "windows", os_key == "macos"

    # Two facts that apply to every cell on a given OS.
    shell = "powershell" if win else "bash"
    os_notes: list[str] = []
    if win:
        os_notes += [
            "hook commands run in PowerShell by default — a bash/`python3` command "
            "needs a `windows:` override",
            "`python3` often does not exist; the launcher is `py -3` "
            "(see _meta/optional_deps.py::discover_python_interpreters)",
            "symlinks need Developer Mode or admin — `--mode link` falls back to copy",
        ]
    if mac:
        os_notes += [
            "BSD coreutils: `stat -c` is GNU-only — write `stat -c … || stat -f …` and "
            "fail loudly rather than defaulting; `sed -i` needs an argument; no `date -d`",
        ]

    cell = {
        "tool": tool, "os": os_key, "hook_shell": shell,
        "binaries": [], "config_root": None, "places": {}, "native": [],
        "notes": list(os_notes),
        # Declared per cell so "reads our skills" and "we call it" can never be
        # read as the same claim again.
        "skill_consumer": tool in SKILL_CONSUMERS,
        "delegate": tool in DELEGATES,
    }

    if tool == "claude":
        cell["binaries"] = ["claude.cmd", "claude.exe", "claude"] if win else ["claude"]
        cell["config_root"] = h / ".claude"
        cell["places"] = {
            "skills": h / ".claude" / "skills",
            "agents": h / ".claude" / "agents",
            "commands": h / ".claude" / "commands",
            "workflows": h / ".claude" / "workflows",
            "instructions": h / ".claude" / "CLAUDE.md",
            "settings": h / ".claude" / "settings.json",
            "optional-manifests": h / ".claude",
        }
        cell["notes"].append("the primary target — every other tool reads from this tree")

    elif tool == "codex":
        cell["binaries"] = ["codex.cmd", "codex"] if win else ["codex"]
        cell["config_root"] = h / ".codex"
        cell["places"] = {"skills": h / ".codex" / "skills"}
        cell["notes"].append("skills are symlinks into ~/.claude/skills where the OS allows it")
        if win:
            cell["notes"].append("without Developer Mode the mirror is COPIED, so it can "
                                 "drift from ~/.claude/skills — re-run install to refresh")

    elif tool == "copilot":
        cell["binaries"] = ["copilot.cmd", "copilot"] if win else ["copilot"]
        cell["config_root"] = h / ".copilot"
        cell["places"] = {"skills-optional": h / ".copilot" / "skills"}
        cell["native"] = [(h / ".claude" / "skills", "auto-discovered — nothing to place")]

    elif tool == "vscode":
        cell["binaries"] = ["code.cmd", "code"] if win else ["code"]
        if win:
            cell["config_root"] = _appdata_for(os_key, h) / "Code" / "User"
        elif mac:
            cell["config_root"] = h / "Library" / "Application Support" / "Code" / "User"
        else:
            cell["config_root"] = h / ".config" / "Code" / "User"
        cell["places"] = {
            "workspace-agents": Path(".github/agents/"),
            "workspace-prompts": Path(".github/prompts/"),
            "workspace-tasks": Path(".vscode/tasks.json"),
            "workspace-mcp": Path(".vscode/mcp.json"),
            "workspace-instructions": Path("AGENTS.md"),
        }
        # #241: the cell that places least is the one that works best.
        cell["native"] = [
            (h / ".claude" / "skills", "user skill location, auto-discovered"),
            (h / ".claude" / "settings.json", "hooks — SessionStart injects context (#241)"),
            (Path(".claude/agents"), "custom agents, with Claude->VS Code tool-name mapping"),
        ]
        cell["notes"].append("workspace files are workspace-relative and therefore identical "
                             "on all three OSes; only the user-config root below differs")
        if mac:
            cell["notes"].append("`code` is NOT on PATH by default — Command Palette -> "
                                 "\"Shell Command: Install 'code' command in PATH\"")

    elif tool == "agy":
        cell["binaries"] = ["agy.cmd", "agy"] if win else ["agy"]
        cell["config_root"] = h / ".gemini"
        cell["places"] = {"host-directive": h / ".gemini" / "agy.md"}
        cell["notes"].append("~/.gemini is AGY's config home despite the name — never delete it; "
                             "auth lives separately in ~/.antigravity")

    elif tool == "gemini":
        cell["binaries"] = ["gemini.cmd", "gemini"] if win else ["gemini"]
        cell["config_root"] = h / ".gemini"
        cell["places"] = {"skills": h / ".gemini" / "skills"}
        cell["notes"].append("SKILLS ONLY. foundry passes NO work to the gemini CLI — it is not "
                             "a delegate, not a challenger, not a second opinion. agy replaced "
                             "it on 2026-07-25 and no skill may reintroduce `gemini -p` or "
                             "`mcp__gemini-cli__*`. This target exists so legacy enterprise "
                             "systems can READ the skill library, and for nothing else.")
        cell["notes"].append("shares ~/.gemini with agy but writes only skills/ — agy owns "
                             "agy.md and antigravity-cli/, so the two targets do not collide")

    return cell


def simulated_home(os_key: str) -> Path:
    """A placeholder home for an OS we are not on.

    Using the LIVE Path.home() while simulating renders `/home/you/AppData/Roaming`
    under a Windows heading — a Linux path wearing a Windows label, which is worse
    than not offering the preview. The placeholder makes it obvious the value is a
    shape, not a location.
    """
    if os_key == "windows":
        return Path("C:/Users/<you>")
    if os_key == "macos":
        return Path("/Users/<you>")
    return Path("/home/<you>")


def _display(p, os_key: str) -> str:
    """Render with the target OS's separators. A Windows path shown with forward
    slashes invites someone to paste it into PowerShell and wonder why it fails."""
    if not isinstance(p, Path):
        return str(p)
    s = str(p)
    if os_key == "windows":
        return s.replace("/", "\\")
    return s


def render_matrix(os_key: str, tools: "tuple[str, ...] | list[str]" = MATRIX_TOOLS,
                  home: Path | None = None, simulated: bool = False) -> str:
    if home is None and simulated:
        home = simulated_home(os_key)
    L = []
    header = f"[install matrix] os={os_key}"
    if simulated:
        header += "   ** SIMULATED — not this machine **"
    L.append(header)
    if simulated:
        L.append("  Paths are computed, not probed: nothing was checked for existence and no")
        L.append("  tool detection ran. `<you>` stands in for the real home — this says what")
        L.append("  WOULD happen and where, not what is actually there.")
    L.append("")
    for tool in tools:
        c = resolve_cell(tool, os_key, home=home)
        scope = []
        if c["skill_consumer"]:
            scope.append("reads our skills")
        if c["delegate"]:
            scope.append("we delegate work to it")
        L.append(f"  {tool}" + (f"   [{'; '.join(scope)}]" if scope else ""))
        L.append(f"    detect as    {', '.join(c['binaries'])}")
        L.append(f"    config root  {_display(c['config_root'], os_key)}")
        L.append(f"    hook shell   {c['hook_shell']}")
        for label, dest in c["places"].items():
            L.append(f"    place        {label:<22} -> {_display(dest, os_key)}")
        for np, why in c["native"]:
            L.append(f"    free         {_display(np, os_key)}  ({why})")
        for n in c["notes"]:
            L.append(f"    ! {n}")
        L.append("")
    return "\n".join(L)


def vscode_user_dir(platform_name: str | None = None,
                    home: Path | None = None) -> Path:
    """Where VS Code keeps USER-level settings, per platform.

    Mirrors vs-code/scripts/detect_models.py — kept in step deliberately, since a
    divergence here would send the installer's advice somewhere the detector never looks.

    Delegates to the matrix rather than repeating the three branches. Two copies of
    this logic is exactly how the installer and the preview would come to disagree
    about the same machine, which is the failure the matrix exists to prevent.
    """
    return resolve_cell("vscode", normalize_os(platform_name), home=home)["config_root"]


# ---------------------------------------------------------------------------
# Findings report + adapted plan
# ---------------------------------------------------------------------------

# Which tools map to an installable target (used by --auto / adapt pre-select).
_TARGET_FOR_TOOL = {
    "claude": "claude",
    "copilot": "copilot",
    "agy": "agy",
    "gemini": "gemini",
}


def _describe_item(item: InstallItem, claude_home: Path) -> str:
    """One plan line: the destination, relative to claude_home when possible."""
    try:
        return str(Path(item.dest).relative_to(claude_home))
    except ValueError:
        return str(item.dest)


def print_install_plan(plan: dict, claude_home: Path, placement_mode: str,
                       limit: int = 12) -> None:
    """Print the create / overwrite / skip sets a run would produce.

    Truncated to `limit` per set with an explicit "... and N more": a full
    install is ~200 skills, and a wall of 600 lines is a dry run nobody reads.
    The PRUNE set is never truncated (see print_prune_set) — that one is the
    destructive half, and 'and 40 more' is not an acceptable summary of what is
    about to be deleted."""
    verb = "symlink" if placement_mode == "link" else "copy"
    for label, key in (("create", "create"), ("overwrite", "overwrite"),
                       ("keep (--skip-existing)", "skip")):
        items = plan.get(key) or []
        if not items:
            continue
        print(f"    {label}: {len(items)}"
              + (f"  ({verb})" if key != "skip" else ""))
        for item in items[:limit]:
            print(f"      {_describe_item(item, claude_home)}")
        if len(items) > limit:
            print(f"      ... and {len(items) - limit} more")


def print_prune_set(candidates: list, claude_home: Path) -> None:
    """Print EVERY prune candidate, in full, never truncated.

    This is the list the user is being asked to authorize the deletion of. A
    truncated version of it would make the confirmation meaningless."""
    print(f"    REMOVE: {len(candidates)} entr{'y' if len(candidates) == 1 else 'ies'} "
          f"previously installed here and no longer shipped:")
    for candidate in candidates:
        dest = candidate_path(claude_home, candidate)
        shown = candidate.get("name")
        if dest is not None:
            try:
                shown = str(dest.relative_to(claude_home))
            except ValueError:
                shown = str(dest)
        print(f"      - {shown}")


def authorize_prune(candidates: list, previous_manifest: "dict | None",
                    claude_home: Path, *, noninteractive: bool,
                    yes_prune: bool) -> "tuple[bool, str]":
    """Decide whether the prune may proceed. Returns (authorized, reason).

    Called BEFORE the run writes anything, which is the point: a
    `--noninteractive` run that is going to be refused must be refused while the
    tree is still untouched, not half-installed. That is why the candidate set
    is computed from plan_install() rather than from a completed install.

    Authorization is NEVER an ownership decision — every candidate reaching
    here already passed compute_prune_candidates(). This only decides whether
    the user has said yes."""
    n = len(candidates)
    entry_count = _manifest_entry_count(previous_manifest)
    tripped = prune_breaker_tripped(n, entry_count)

    if tripped:
        # §11 A8 — print the full list and demand an explicit answer, regardless
        # of how the run was invoked.
        print()
        print("  ⚠ CIRCUIT BREAKER: this cleanup is unusually large.")
        print(f"    {n} candidate(s) vs a threshold of "
              f"{prune_threshold(entry_count)} "
              f"(the smaller of 25% of {entry_count} manifest entries, or "
              f"{PRUNE_MAX_PATHS} paths).")
        print("    That is the shape of a mis-detected source tree, not a normal cleanup.")
        print_prune_set(candidates, claude_home)

    if noninteractive:
        if not yes_prune:
            return False, (
                "a destructive cleanup needs explicit authorization: re-run with "
                "--yes-prune,\n  or drop --mode mc. Under --noninteractive there is "
                "nobody to ask.")
        if tripped:
            # --yes-prune is the explicit confirmation the breaker demands; a
            # non-interactive run has no second channel to ask on.
            print("    --yes-prune supplied — proceeding despite the circuit breaker.")
        else:
            # Nobody is watching a --noninteractive run, which is exactly why it
            # has to say what it deleted: the run-log is the only record anyone
            # will have afterwards. (When the breaker tripped, the list is
            # already above.)
            print_prune_set(candidates, claude_home)
        return True, "authorized by --yes-prune"

    if yes_prune:
        print_prune_set(candidates, claude_home)
        return True, "authorized by --yes-prune"

    if not tripped:
        print_prune_set(candidates, claude_home)
    print("    Everything removed is archived first and can be restored with --rollback.")
    if not confirm("  Remove these?", default=False):
        return False, "declined at the prompt"
    return True, "confirmed interactively"


def _fmt_cell(s: str | None, width: int) -> str:
    s = s if s is not None else "-"
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s.ljust(width)


def render_findings(report: dict) -> None:
    """Print the findings table: tool | found? | via | version | what it enables."""
    print("=" * 78)
    print("Environment scan — findings")
    print("=" * 78)
    print(f"OS: {report['os']['release']}  ({report['os']['platform']})")
    print()
    hdr = (_fmt_cell("tool", 9) + _fmt_cell("found", 7) + _fmt_cell("via", 11)
           + _fmt_cell("version", 22) + "enables")
    print(hdr)
    print("-" * 78)
    for name, t in report["tools"].items():
        label = name + (" *legacy" if t.get("legacy") and t.get("found") else "")
        found = "yes" if t["found"] else "no"
        ver = t["version"] or "-"
        row = (_fmt_cell(label, 9) + _fmt_cell(found, 7) + _fmt_cell(t["via"], 11)
               + _fmt_cell(ver, 22) + (t["enables"] or ""))
        print(row)
    print("-" * 78)
    existing = [k for k, v in report["config_dirs"].items() if v]
    print("Existing config dirs: " + (", ".join(existing) if existing else "(none)"))
    print()


def adapted_targets(report: dict) -> list[str]:
    """Targets pre-selected because the scan DETECTED their tool (interactive
    default only — the user still confirms; --noninteractive ignores this)."""
    out: list[str] = []
    for tool, target in _TARGET_FOR_TOOL.items():
        if report["tools"].get(tool, {}).get("found"):
            if target not in out:
                out.append(target)
    if "claude" not in out:
        out.insert(0, "claude")  # claude is always the floor
    return out


def render_adapted_plan(report: dict, preselected: list[str]) -> None:
    """Print the adapted plan + recommendations (the 'adapt' surface)."""
    print("Adapted plan (detected → pre-selected; you confirm):")
    tools = report["tools"]

    def status(tool: str) -> str:
        t = tools.get(tool, {})
        if not t.get("found"):
            return "not detected"
        v = t.get("version") or ""
        via = t.get("via") or ""
        return f"detected (via {via}{', ' + v if v and 'fail' not in v else ''})"

    print(f"  • claude   → {status('claude')} — install skills/agents/commands [pre-selected]")
    # copilot / VS Code
    cp = tools.get("copilot", {}); vs = tools.get("code", {})
    if cp.get("found") or vs.get("found"):
        consumers = report.get("skills_consumers") or []
        print(f"  • copilot  → {status('copilot')}; VS Code {status('code')}")
        if consumers:
            print(f"               {' + '.join(consumers)} already auto-discover ~/.claude/skills/")
        print(f"               → optional ~/.copilot/skills mirror (use --mirror-copilot-skills)")
    else:
        print(f"  • copilot  → not detected")
    # agy
    if tools.get("agy", {}).get("found"):
        print(f"  • agy      → {status('agy')} — primary delegate; wire ~/.gemini/agy.md [pre-selected]")
    else:
        print(f"  • agy      → not detected (install Antigravity CLI to enable the primary delegate)")
    # gemini legacy
    if tools.get("gemini", {}).get("found"):
        print(f"  • gemini   → {status('gemini')} — skills target only; agy is the delegate")
    else:
        print(f"  • gemini   → not detected (legacy; agy is the primary delegate)")
    print()
    print("Recommendations:")
    if tools.get("agy", {}).get("found"):
        print("  - agy is your primary second-opinion/challenger delegate; its host directive")
        print("    (~/.gemini/agy.md, distinct from the gemini CLI) is created if absent.")
    if tools.get("gemini", {}).get("found"):
        print("  - gemini CLI detected: it READS the skill library (legacy enterprise use).")
        print("    foundry passes it no work — agy is the delegate.")
    if report.get("skills_consumers"):
        print("  - " + " and ".join(report["skills_consumers"]) +
              " consume ~/.claude/skills/ for free; install the claude target.")
    print(f"  - pre-selected targets (interactive default): {', '.join(preselected)}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    # Must run before ANY print() and before RunLogger captures the streams:
    # keeps the installer's Unicode glyphs from crashing a non-UTF-8 console.
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="agent-foundry installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=TARGETS_HELP,
    )
    parser.add_argument(
        "--target",
        help="comma-separated single-letter codes or names "
             "(e.g. 'c,p' or 'claude,copilot'); 'a'/'all' = everything; "
             "'auto' = every CLI the scan detected",
        default=None,
    )
    parser.add_argument("--mode", choices=list(CLI_MODES), default=None,
                        help="link = symlinks (recommended); move = copy; "
                             "mc = copy + CLEAN (removes ~/.claude entries this "
                             "installer previously placed and no longer ships; "
                             "Claude target only; everything removed is archived "
                             "first and is restorable with --rollback)")
    parser.add_argument("--claude-home", default=None,
                        help=f"override Claude config dir (default {DEFAULT_CLAUDE_HOME})")
    parser.add_argument("--gemini-home", default=None,
                        help=f"override Gemini config dir (default {DEFAULT_GEMINI_HOME})")
    parser.add_argument("--force", action="store_true",
                        help="(no-op for skills/agents — replace-existing is the default; "
                             "DOES force agy.md + copilot-instructions.md overwrite, with .bak; "
                             "does NOT touch ~/.claude/settings.json or CLAUDE.md — use "
                             "--force-global-config for those)")
    parser.add_argument("--force-global-config", action="store_true",
                        help="overwrite the whole ~/.claude/settings.json + CLAUDE.md from the "
                             "bundled template/repo (writes a .bak first). Without it, the default "
                             "run only creates them if absent and injects missing SessionStart hooks.")
    parser.add_argument("--skip-existing", action="store_true",
                        help="leave existing skills/agents/commands at the target untouched (old --force=False behavior)")
    parser.add_argument("--noninteractive", action="store_true",
                        help="use defaults — claude + link mode — without prompting (back-compat: unchanged)")
    parser.add_argument("--auto", action="store_true",
                        help="install into ALL detected CLIs (equivalent to --target auto)")
    parser.add_argument("--scan-only", action="store_true",
                        help="run the environment scan, print the findings report, and exit")
    parser.add_argument("--mirror-copilot-skills", action="store_true",
                        help="also mirror skills into ~/.copilot/skills/ (opt-in; additive)")
    parser.add_argument("--git-hooks", metavar="PATH", default=None,
                        help="install the secrets pre-commit/pre-push hooks into this "
                             "repo (default: the repo install.py is run from). #250 — "
                             "the Windows laptop had NO hooks, so every commit and push "
                             "was unscanned.")
    parser.add_argument("--no-git-hooks", action="store_true",
                        help="skip git-hook installation. The hooks are placed by "
                             "DEFAULT because an opt-in security gate is exactly how "
                             "the unscanned-repo hole (#250) happened.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the exact create / overwrite / prune sets and "
                             "exit WITHOUT touching anything. Recommended before "
                             "any --mode mc run.")
    parser.add_argument("--yes-prune", action="store_true",
                        help="pre-authorize the --mode mc cleanup. REQUIRED for a "
                             "destructive prune under --noninteractive; without it "
                             "such a run fails before writing anything.")
    parser.add_argument("--vscode-workspace", metavar="PATH", default=None,
                        help="place the VS Code / Copilot workspace files into PATH: "
                             "AGENTS.md, .vscode/tasks.json + mcp.json, the VSPrime "
                             "agent and the /prime command. Skills need no bridge — "
                             "VS Code auto-discovers ~/.claude/skills — but startup, "
                             "agents and MCP wiring do. Implies the copilot target.")
    parser.add_argument("--preview", action="store_true",
                        help="print the OS x tool install matrix and exit — where each "
                             "tool's files go, which shell its hooks run in, what it "
                             "discovers for free, and the per-OS traps. Combine with "
                             "--os / --tool.")
    parser.add_argument("--os", dest="os_key", default=None,
                        choices=list(OS_KEYS),
                        help="preview a DIFFERENT OS than this one (e.g. --preview --os "
                             "windows from Linux). Output is marked SIMULATED: paths are "
                             "computed, nothing is probed, no detection runs.")
    parser.add_argument("--tool", dest="matrix_tool", default=None,
                        choices=list(MATRIX_TOOLS),
                        help="preview a single tool's cell instead of all of them")
    parser.add_argument("--with-extras", metavar="GROUPS", default=None,
                        const="__ALL__", nargs="?",
                        help="install optional libraries for specific capabilities "
                             "(comma-separated). Extras are installed by DEFAULT; use this "
                             "only to narrow the set, or --no-extras to skip entirely. "
                             "Covers both pip and npm.")
    parser.add_argument("--no-extras", action="store_true",
                        help="do NOT install optional libraries. The harness is stdlib-only "
                             "and works without them; capabilities that need one report it "
                             "as unavailable. Use on locked-down or offline machines.")
    parser.add_argument("--extras-report", action="store_true",
                        help="report optional-capability readiness and exit. Says what is "
                             "missing, what stops working without it, and the exact install "
                             "command for this machine.")
    parser.add_argument("--rollback", metavar="RUN_ID", default=None,
                        help="undo a previous run: replays that run's archive journal in "
                             "reverse, restoring the tree byte-for-byte. Archives live under "
                             f"~/.claude/{ARCHIVE_DIRNAME}/<run-id>/ and are never expired "
                             "automatically. Run ids are printed at the end of each install.")
    add_log_args(parser)
    args = parser.parse_args()

    # Incoherent flag combinations are rejected here, BEFORE the run-log opens,
    # so a rejected invocation leaves nothing behind at all — not even a log
    # file. `--mode mc --skip-existing` is the case that matters (see
    # reject_incompatible_flags); the interactive mode prompt is re-checked in
    # _run() because it can select `mc` too.
    err = reject_incompatible_flags(args.mode, bool(args.skip_existing))
    if err:
        _force_utf8_streams()
        print(f"✗ {err}")
        return 2

    # §8b: tee all output to a run-log (on by default; --no-log opts out;
    # --log overrides the path). The logger NEVER aborts the install.
    with RunLogger(sys.argv, log_path=args.log, enabled=not args.no_log,
                   repo_root=REPO_ROOT, header_title="agent-foundry installer"):
        return _run(args)


# ---------------------------------------------------------------------------
# Optional dependencies (#240) — pip AND npm, opt-in, never fatal
#
# Everything here is OPTIONAL. 225 skills, the gates, the hooks and this
# installer all run stdlib-only, and a locked-down machine where `pip install`
# is refused must still end up with a working harness. So: report always,
# install only when asked, and NEVER let either turn a successful install into
# a failed one — turning "this skill cannot extract a PDF" into "the installer
# failed" is a strictly worse outcome.
#
# The logic lives in skills/_meta/optional_deps.py so that the installer, the
# env-adoption probe and a standalone caller all get the same answer. Loaded by
# path rather than imported, because install.py must keep working when the
# module is absent (an older checkout, a partial clone).
# ---------------------------------------------------------------------------

OPTIONAL_MANIFESTS = ("requirements-optional.txt", "package-optional.json")


def install_optional_manifests(repo_root: Path, claude_home: Path, archive=None) -> bool:
    """Place the optional-dependency manifests at ~/.claude/ (#240).

    They have to be at the INSTALLED root, not just in a checkout: the readiness
    report runs from ~/.claude/skills/_meta at session start, on machines that
    have no clone at all. Without them the report finds nothing — and "found no
    manifest" must never be mistaken for "nothing missing", which is why
    optional_deps.py reports that state as UNKNOWN rather than as 0/0 ready.

    Data files with no user-editable content, so the rule is simple: write when
    absent or when the content differs. There is no merge to preserve and no
    provenance question — unlike CLAUDE.md and settings.json, nobody customises
    a manifest that the harness regenerates from the repo.
    """
    ok = True
    for name in OPTIONAL_MANIFESTS:
        src, dest = repo_root / name, claude_home / name
        if not src.is_file():
            continue
        try:
            existed = dest.exists()
            if existed and dest.read_bytes() == src.read_bytes():
                print(f"  = {name} (already current)")
                continue
            claude_home.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if archive is not None and not existed:
                archive.record_created(dest)
            print(f"  {'~' if existed else '+'} {name}")
        except OSError as exc:
            print(f"  ⚠ could not place {name}: {exc}")
            ok = False
    return ok


def _load_optional_deps():
    """Returns the module, or None. Never raises — this is a convenience, not a
    dependency of installing."""
    mod_path = REPO_ROOT / "skills" / "_meta" / "optional_deps.py"
    if not mod_path.is_file():
        return None
    try:
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("_af_optional_deps", mod_path)
        if spec is None or spec.loader is None:
            return None
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _extras_preflight(args) -> None:
    """Say what is missing BEFORE placing anything. Never fails the install."""
    mod = _load_optional_deps()
    if mod is None:
        return
    try:
        import io as _io
        import contextlib as _ctx
        buf = _io.StringIO()
        with _ctx.redirect_stdout(buf):
            mod.main(["report", "--json"])
        data = json.loads(buf.getvalue())
    except Exception:
        return

    crit = data.get("critical_missing") or []
    gaps = [g["capability"] for g in data.get("groups", []) if g.get("state") != "ready"]
    skipping = bool(getattr(args, "no_extras", False))

    if crit:
        print("=" * 60)
        print("⚠  REQUIRED libraries are missing — this is not the optional set")
        print("=" * 60)
        print(f"   {', '.join(crit)}")
        print("   A SessionStart hook imports pyyaml on EVERY session, and the gates")
        print("   use jsonschema for validation — which fails toward 'not checked',")
        print("   not toward 'checked and passed'.")
        print("   These are usually already present, which is exactly why the")
        print("   dependency went undeclared until 2026-07-30. Being lucky is not")
        print("   the same as being declared.")
        if skipping:
            print("   --no-extras is set, so NOTHING will be installed. Install them")
            print("   yourself, or the harness will misbehave.")
        else:
            print("   They will be installed after placement.")
        print("=" * 60)
        print()
    elif gaps and not skipping:
        print(f"Optional libraries: {len(gaps)} capabilit"
              f"{'y' if len(gaps) == 1 else 'ies'} unavailable "
              f"({', '.join(gaps)}) — will install after placement.")
        print("  --no-extras skips it; --extras-report explains what each one costs.")
        print()
    elif gaps and skipping:
        print(f"Optional libraries: {len(gaps)} unavailable and --no-extras is set. "
              f"Skills needing them will report the capability as unavailable.")
        print()


def extras_report() -> int:
    """`--extras-report`: what is missing, what it costs, how to get it."""
    mod = _load_optional_deps()
    if mod is None:
        print("optional-dependency reporting is unavailable in this checkout")
        print(f"  expected: {REPO_ROOT / 'skills' / '_meta' / 'optional_deps.py'}")
        return 0
    try:
        argv = ["report"]
        return int(mod.main(argv) or 0)
    except Exception as exc:
        print(f"optional-dependency report skipped ({exc})")
        return 0


def run_extras(args) -> None:
    """Print readiness at the end of every install; install only if asked.

    A run WITHOUT --with-extras still gets the one-line digest, because the
    whole point of #240 is that a first run tells you what is missing instead of
    leaving it to be discovered one skill at a time.
    """
    mod = _load_optional_deps()
    if mod is None:
        return

    # S075: extras now install BY DEFAULT. Reporting-only left every fresh box a
    # step short of working — a user ran the installer, saw "9 capabilities
    # unavailable", and had to run a second command to get what they had just
    # asked for. Defaulting to install is the behaviour people expect from an
    # installer.
    #
    # What has NOT changed is the property that made opt-in defensible: a failed
    # optional install is REPORTED, never fatal. On a locked-down or offline
    # machine the install still succeeds and the capabilities simply stay
    # unavailable — `--no-extras` skips the attempt entirely.
    groups = getattr(args, "with_extras", None)
    if getattr(args, "no_extras", False):
        print()
        mod.main(["report", "--digest"])
        print("  (--no-extras: nothing installed. `--extras-report` for what that costs)")
        return
    try:
        only = None if (not groups or groups == "__ALL__") else groups
        print()
        print("=" * 60)
        print("Optional dependencies" + (f" — {only}" if only else " — all capabilities"))
        print("=" * 60)

        ns = ["install-cmd", "--json"] + (["--group", only] if only else [])
        import io as _io
        import contextlib as _ctx
        buf = _io.StringIO()
        with _ctx.redirect_stdout(buf):
            mod.main(ns)
        commands = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]

        if not commands:
            print("nothing missing — every requested capability is already available.")
            return

        for cmd in commands:
            print(f"\n$ {' '.join(cmd)}")
            try:
                proc = subprocess.run(cmd, timeout=EXTRAS_INSTALL_TIMEOUT)
                if proc.returncode != 0:
                    # A failed optional install is a reported outcome, not an
                    # installer failure. The user may be offline, behind a proxy,
                    # or on a machine where installing is simply not permitted.
                    print(f"  ⚠ exit {proc.returncode} — capability stays unavailable.")
                    print("    The harness is unaffected; skills needing it will say so.")
            except subprocess.TimeoutExpired:
                print(f"  ⚠ timed out after {EXTRAS_INSTALL_TIMEOUT}s — capability stays "
                      f"unavailable.")
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"  ⚠ could not run it ({exc}) — capability stays unavailable.")

        print()
        mod.main(["report", "--digest"])
    except Exception as exc:
        # Belt and braces: no failure in this block may change the install's outcome.
        print(f"optional-dependency step skipped ({exc})")


def _run(args) -> int:
    banner()
    print()

    # ---- --rollback <run-id>: restore and exit, before anything else ----
    # Handled first so a user recovering from a bad run does not have to sit
    # through an environment scan, and so no other code path can mutate the
    # tree we are about to restore.
    if getattr(args, "rollback", None):
        rb_home = Path(args.claude_home).expanduser() if args.claude_home else DEFAULT_CLAUDE_HOME
        return rollback_run(rb_home, args.rollback)

    # ---- --preview: the OS x tool matrix, then exit ----
    # Before the scan, and deliberately runnable for an OS this is not: the harness
    # is developed on one machine and run on others, so "what will my Windows laptop
    # do" has to be answerable from here. A simulated preview probes nothing and
    # says so in its header — a computed path presented as a detected one would be
    # worse than no preview at all.
    if getattr(args, "preview", False):
        requested = getattr(args, "os_key", None)
        os_key = normalize_os(requested)
        simulated = requested is not None and os_key != normalize_os()
        tools = (getattr(args, "matrix_tool", None),) if getattr(args, "matrix_tool", None) \
            else MATRIX_TOOLS
        print(render_matrix(os_key, tools, simulated=simulated))
        if not simulated:
            print("  Paths above are for THIS machine. Add --os windows|macos|linux to")
            print("  preview another (marked SIMULATED).")
        return 0

    # ---- --extras-report: readiness and exit ----
    # Before the scan, because someone asking "what am I missing?" should not have
    # to sit through an install they did not ask for.
    if getattr(args, "extras_report", False):
        return extras_report()

    skill_n, agent_n, command_n, workflow_n = detect(REPO_ROOT)
    print(f"Repo root:      {REPO_ROOT}")
    print(f"Python:         {sys.version.split()[0]}")
    print(f"Skills found:    {skill_n}")
    print(f"Agents found:    {agent_n}")
    print(f"Commands found:  {command_n}")
    print(f"Workflows found: {workflow_n}")
    print()

    # ---- Scan → findings report (always; this is the 'scan' surface) ----
    report = scan_environment()
    render_findings(report)
    preselected = adapted_targets(report)
    render_adapted_plan(report, preselected)

    has_claude = report["tools"]["claude"]["found"]
    if not has_claude:
        print("⚠ `claude` CLI not detected — install with:")
        print("    curl -fsSL https://claude.ai/install.sh | bash")
        print("  (or see https://docs.claude.com/en/docs/claude-code/setup)")
        print("  Continuing — files will land at ~/.claude/ and be picked up once `claude` is installed.")
        print()

    # ---- Optional-library readiness, ANNOUNCED UP FRONT (S075) ----
    #
    # Placement itself needs none of this: install.py is stdlib-only, pinned by
    # test_standalone. So extras are still installed AFTER placement — a long
    # network operation must never jeopardise the installer's actual job, and a
    # Ctrl-C during pip should leave a complete, usable install behind.
    #
    # But the ORDER OF INFORMATION is a separate question from the order of work,
    # and reporting only at the end meant you learned what was missing after
    # everything had already happened. The `core` group in particular is not
    # optional at all — a SessionStart hook imports pyyaml on every session — so
    # it is said before, not after.
    _extras_preflight(args)

    if args.scan_only:
        return 0

    if skill_n == 0 and agent_n == 0 and command_n == 0 and workflow_n == 0:
        print("⚠ no skills, agents, commands, or workflows found in this directory.")
        print(f"  expected: {REPO_ROOT / 'skills'}, {REPO_ROOT / 'agents'}, {REPO_ROOT / 'commands'}, or {REPO_ROOT / 'workflows'}")
        return 1

    # ---- Targets (adapt = pre-select interactive defaults; explicit flags win) ----
    # back-compat floor: --noninteractive with no --target is ALWAYS claude only.
    target_str = args.target
    if args.auto and target_str is None:
        target_str = "auto"

    if target_str is None and not args.noninteractive:
        print(TARGETS_HELP)
        # Adapt: pre-select the detected targets as the interactive DEFAULT.
        default_choice = ",".join(preselected)
        print(f"Detected → pre-selected default: {default_choice}")
        print("  (press Enter to accept, or type targets: c/p/y/g/a/auto, comma-separated)")
        target_str = ask("Choose targets", default=default_choice)
    elif target_str is None:
        target_str = "claude"  # --noninteractive floor (UNCHANGED)

    target_map = {"c": "claude", "p": "copilot", "y": "agy", "g": "gemini",
                  "a": "all", "all": "all", "auto": "auto",
                  "claude": "claude", "copilot": "copilot", "agy": "agy",
                  "gemini": "gemini"}
    raw = [t.strip().lower() for t in target_str.split(",") if t.strip()]
    targets: list[str] = []
    for t in raw:
        if t not in target_map:
            print(f"⚠ unknown target {t!r}; expected one of {sorted(set(target_map))}")
            return 1
        mapped = target_map[t]
        if mapped == "all":
            targets = ["claude", "copilot", "agy", "gemini"]
            break
        if mapped == "auto":
            # auto = every detected target (explicit user opt-in to adapt).
            targets = list(preselected)
            break
        if mapped not in targets:
            targets.append(mapped)

    if not targets:
        targets = ["claude"]

    # ---- Mode ----
    mode = args.mode
    needs_mode = any(t in targets for t in ("claude", "gemini", "copilot", "agy"))
    if mode is None and needs_mode:
        if args.noninteractive:
            mode = "link"
        else:
            print()
            print("Install mode:")
            print("  l = link  (symlinks; edits in agent-foundry propagate; recommended for dev)")
            print("  m = move  (copy; independent; agent-foundry edits don't propagate)")
            print("  c = mc    (copy + CLEAN: also REMOVES entries this installer")
            print("             previously placed here and no longer ships. Claude only.")
            print("             Hand-authored files are never touched; everything")
            print("             removed is archived first and restorable.)")
            mode_choice = ask("Choose", choices=["l", "m", "c"], default="l")
            mode = {"l": "link", "m": "move", "c": "mc"}[mode_choice]
    elif mode is None:
        mode = "link"

    # The interactive prompt above can select `mc`, so the rejection main()
    # applied to the FLAG has to be re-applied to the RESOLVED mode. Still
    # before any write.
    err = reject_incompatible_flags(mode, bool(args.skip_existing))
    if err:
        print(f"✗ {err}")
        return 2

    # ---- The internal split (§6.C2, §11 A10) ----
    # From here down, `mode` is only ever used for DISPLAY and for provenance
    # records. Every function that places files receives `placement_mode`, and
    # `clean_claude` is never passed to anything but the Claude target — which
    # is what stops `mc` from meaning anything under ~/.gemini or ~/.copilot.
    placement_mode, clean_claude = resolve_mode(mode)
    clean_claude = clean_claude and "claude" in targets
    for line in normalize_mode_for_other_targets(mode, targets):
        print(line)
    dry_run = bool(getattr(args, "dry_run", False))

    # ---- Paths ----
    claude_home = Path(args.claude_home).expanduser() if args.claude_home else DEFAULT_CLAUDE_HOME
    gemini_home = Path(args.gemini_home).expanduser() if args.gemini_home else DEFAULT_GEMINI_HOME

    if not args.noninteractive:
        if "claude" in targets:
            claude_home = _ask_path_override("Claude", claude_home)
        if "gemini" in targets or "agy" in targets:
            gemini_home = _ask_path_override("Gemini/agy", gemini_home)

    # ---- Cleanup pre-flight (§6.C2, §11 A8) — decided BEFORE any write ----
    #
    # The authorization question has to be answered while the tree is still
    # untouched. A `--noninteractive --mode mc` run with no `--yes-prune` must
    # fail having written NOTHING — discovering the refusal after 200 skills
    # have been placed would leave the user with a half-applied run they never
    # authorized. plan_install() exists precisely so this is answerable without
    # mutating: it reports what the run WOULD ship, which is the second half of
    # the ownership test.
    #
    # `mc_baseline_only` is the first-run case: no previous manifest means no
    # proven ownership, so this run installs, records a baseline, and prunes
    # NOTHING. It is not an error — it is the only safe first move.
    prune_authorized: list = []
    mc_baseline_only = False
    previous_manifest = read_manifest(claude_home) if "claude" in targets else None
    # Populated by the global-config writers below (WP-005). None means the
    # claude target never ran, in which case the manifest carries the previous
    # block forward untouched rather than claiming this run wrote anything.
    canonical_new: "dict | None" = None
    if clean_claude:
        preflight = plan_install(REPO_ROOT, claude_home, placement_mode, skip_existing=False)
        if previous_manifest is None:
            mc_baseline_only = True
        else:
            planned_candidates = compute_prune_candidates(previous_manifest,
                                                          preflight["shipped"])
            if planned_candidates and dry_run:
                # A dry run REPORTS the destructive set; it never asks to
                # perform it. Prompting here would be the one thing a dry run
                # must not do — offer the user a way to mutate the tree from
                # inside the command they ran to avoid mutating it.
                print()
                print("[cleanup — --mode mc]")
                print_prune_set(planned_candidates, claude_home)
                if prune_breaker_tripped(len(planned_candidates),
                                         _manifest_entry_count(previous_manifest)):
                    print("    ⚠ this exceeds the circuit-breaker threshold "
                          f"({prune_threshold(_manifest_entry_count(previous_manifest))}) "
                          "and a real run would demand explicit confirmation.")
            elif planned_candidates:
                print()
                print("[cleanup — --mode mc]")
                ok_to_prune, why = authorize_prune(
                    planned_candidates, previous_manifest, claude_home,
                    noninteractive=bool(args.noninteractive),
                    yes_prune=bool(getattr(args, "yes_prune", False)))
                if not ok_to_prune:
                    print(f"  ✗ cleanup not authorized — {why}")
                    print("    NOTHING has been installed, replaced, or removed.")
                    return 1
                prune_authorized = planned_candidates
            else:
                print()
                print("[cleanup — --mode mc] nothing to remove: everything this "
                      "installer owns here is still shipped.")

    # ---- Auto-rollback, second path (§11 A10) ----
    # A run that was hard-killed could not roll itself back — no in-process
    # handler runs when the kernel takes the process away. It did leave its
    # journal on disk, though, so THIS run can offer what that one could not.
    # Surfaced before the confirmation prompt: a user may well want to restore
    # first and install after.
    # Skipped under --dry-run: accepting the offer performs a rollback, and a
    # dry run must not be able to mutate the tree by any path at all.
    if "claude" in targets and not dry_run:
        _offer_incomplete_rollback(claude_home, noninteractive=bool(args.noninteractive))

    # ---- Confirm ----
    print()
    print("=" * 60)
    print("Plan:")
    if "claude" in targets:
        print(f"  Claude  ({mode}): {REPO_ROOT/'skills'}    → {claude_home/'skills'}")
        print(f"                    {REPO_ROOT/'agents'}    → {claude_home/'agents'}")
        print(f"                    {REPO_ROOT/'commands'}  → {claude_home/'commands'}")
        print(f"                    {REPO_ROOT/'workflows'} → {claude_home/'workflows'}")
        gc = "overwrite (.bak first)" if args.force_global_config else "create-if-absent"
        print(f"  Claude  (env):   {claude_home/'CLAUDE.md'} — {gc}")
        print(f"                    {claude_home/'settings.json'} — "
              f"{'overwrite whole file (.bak first)' if args.force_global_config else 'create-if-absent, else inject only missing SessionStart hooks'}")
    if "copilot" in targets:
        extra = " + ~/.copilot/skills mirror" if args.mirror_copilot_skills else ""
        print(f"  Copilot: write {DEFAULT_COPILOT_HOME/'copilot-instructions.md'}{extra}")
        print(f"           (~/.claude/skills already auto-discovered by Copilot CLI + VS Code 1.123+)")
    if "agy" in targets:
        print(f"  agy:     {gemini_home/'agy.md'} (host directive; create-if-absent, hash-skip, .bak on --force)")
    if "gemini" in targets:
        if report["tools"]["gemini"]["found"]:
            gemini_via = "via `gemini skills link`" if shutil.which("gemini") else "direct symlink"
            print(f"  Gemini  ({mode}, {gemini_via}, skills only): "
                  f"{REPO_ROOT/'skills'} → {gemini_home/'skills'}")
        else:
            print(f"  Gemini  (skills only): requested but `gemini` not detected — "
                  f"will use direct {mode} fallback into {gemini_home/'skills'}")
    if args.skip_existing:
        print("  Existing skills/agents/commands at the targets will be KEPT (--skip-existing).")
    else:
        print("  Existing skills/agents/commands at the targets will be REPLACED. Pass --skip-existing to keep them.")
    if clean_claude:
        if mc_baseline_only:
            print("  Cleanup: DEFERRED — no ownership provenance exists yet (first mc run here).")
        elif prune_authorized:
            print(f"  Cleanup: {len(prune_authorized)} previously-installed entr"
                  f"{'y' if len(prune_authorized) == 1 else 'ies'} will be REMOVED "
                  "(archived first).")
    print("=" * 60)

    # ---- --dry-run (§6.C2 CLI table, R6) ----
    #
    # Prints the exact sets and returns. Everything below this point mutates,
    # and everything above it either reads or asks — so this is the last line at
    # which "nothing has been touched" is still true, which is the only place a
    # dry run can honestly stop.
    #
    # install_claude() is NOT called with a dry_run flag; it is not called at
    # all. plan_install() answers the same question from the same enumeration
    # without a placement path that could mutate by accident. The three
    # functions that DO carry a dry_run parameter (install_claude_md,
    # install_settings, install_agy) are invoked with it, which is what finally
    # makes that parameter reachable — before this flag existed it was
    # unreachable dead code (R6).
    if dry_run:
        print()
        print("DRY RUN — nothing will be created, replaced, or removed.")
        if "claude" in targets:
            print("[Claude]")
            plan = plan_install(REPO_ROOT, claude_home, placement_mode,
                                skip_existing=bool(args.skip_existing))
            print_install_plan(plan, claude_home, placement_mode)
            print("  [environment]")
            # canonical_prev is passed so the dry run REPORTS an auto-update it
            # would perform; canonical_out is deliberately NOT passed, because a
            # dry run that recorded provenance would make the next real run
            # believe it had written a file it never wrote.
            dry_canonical_prev = (read_manifest(claude_home) or {}).get("canonical")
            install_claude_md(REPO_ROOT, claude_home,
                              force_global=bool(args.force_global_config), dry_run=True,
                              canonical_prev=dry_canonical_prev)
            install_settings(claude_home,
                             force_global=bool(args.force_global_config), dry_run=True,
                             canonical_prev=dry_canonical_prev)
        if "agy" in targets:
            print("[agy]")
            install_agy(gemini_home, force=bool(args.force), dry_run=True)
        for target in ("copilot", "gemini"):
            if target in targets:
                print(f"[{target}] — dry run not modelled for this target; it would "
                      "be installed as described in the plan above.")
        # Modelled here rather than left out: git hooks are placed by DEFAULT, and a
        # preview that omits a default action is a preview that misleads. The real
        # call sits after this early return, so without this the only way to learn
        # the installer touches .git/hooks was to run it for real.
        if not getattr(args, "no_git_hooks", False):
            print("[git hooks]")
            install_git_hooks(REPO_ROOT,
                              Path(getattr(args, "git_hooks", None) or REPO_ROOT),
                              force=bool(args.force), dry_run=True)
        print()
        print("dry run complete — nothing was changed.")
        return 0

    if not args.noninteractive:
        if not confirm("Proceed?", default=False):
            print("cancelled.")
            return 0

    # ---- Execute ----
    # Default: replace existing skills/agents/commands. `--skip-existing` keeps them.
    # `--force` forces agy.md / copilot-instructions.md overwrite (with .bak).
    skip_existing = bool(args.skip_existing)
    force = bool(args.force)
    force_global = bool(args.force_global_config)
    print()
    placed_claude: dict = {}
    run_id = _new_run_id()
    archive: "ArchiveSession | None" = None
    if "claude" in targets:
        print("[Claude]")
        # ---- Archive root: created BEFORE the first mutation (§6.C2, §11 A3) ----
        #
        # This is the whole zero-destruction guarantee in one place. Creation
        # precedes every destructive operation, so a failure here means the run
        # refuses having touched precisely nothing — no partial install, no
        # half-archived tree, no "we got most of it".
        try:
            archive = ArchiveSession.create(
                claude_home, run_id, mode=mode,
                source_rev=_git_sha(REPO_ROOT) or "unknown",
                old_manifest=previous_manifest)
        except ArchiveError as exc:
            print(f"  ✗ could not prepare the archive: {exc}")
            print("    REFUSING to install: this run replaces existing files, and without")
            print("    an archive a replaced file could not be recovered. Nothing was changed.")
            return 1
        print(f"  ✓ archive ready: {archive.root}")
        try:
            sc, ac, cc, wf, te, chm, mp = install_claude(
                REPO_ROOT, claude_home, placement_mode, skip_existing,
                placed_out=placed_claude, archive=archive)
        except ArchiveError as exc:
            # Auto-rollback, first path (§11 A10): an archive move failed
            # part-way, so undo what already moved and leave the tree as we
            # found it. No destructive operation survives.
            print(f"  ✗ archive failure during install: {exc}")
            archive.rollback("an object could not be archived")
            print("    The tree has been restored. Nothing was installed.")
            return 1
        verb = "kept" if skip_existing else "replaced"
        meta_note = " + _meta support dir" if mp else ""
        print(f"  ✓ {sc} skills, {ac} agents, {cc} commands, {wf} workflows{meta_note} installed ({te} {verb} existing)")
        if chm:
            print(f"    + chmod +x on {chm} skill scripts")
        # Wire the global environment so the single advertised installer leaves a
        # WORKING setup (the fix for the "settings.json present but 0 hooks" box).
        print("  [environment]")
        # The two global config files belong to a different component
        # (canonical-config-provenance) with its own .bak convention, so they
        # do not route through place(). What can be journalled here without
        # reaching into that path is the ones this run CREATED — otherwise
        # --rollback would leave a CLAUDE.md and a settings.json behind on a
        # box that had neither, which is not the pre-run state.
        #
        # SEAM, deliberately not closed here: a config file that already
        # existed and was MODIFIED is not archived. Archiving it would mean
        # moving it away before install_settings could read and merge it, and
        # the merge path is exactly what §11 A1 restructures. That case belongs
        # with the component that owns the write.
        env_files = [claude_home / "CLAUDE.md", claude_home / "settings.json"]
        env_existed = {p: (p.exists() or p.is_symlink()) for p in env_files}
        # canonical-config-provenance (WP-005): the PREVIOUS manifest's block is
        # read-only input (it says what the installer last wrote whole-file);
        # canonical_new collects what THIS run wrote whole-file. Starting from a
        # copy of the previous block means a run that touches neither file
        # carries provenance forward instead of dropping it.
        canonical_prev = (previous_manifest or {}).get("canonical")
        canonical_new = dict(canonical_prev) if isinstance(canonical_prev, dict) else {}
        install_claude_md(REPO_ROOT, claude_home, force_global=force_global,
                          canonical_prev=canonical_prev, canonical_out=canonical_new)
        ok = install_settings(claude_home, force_global=force_global,
                              canonical_prev=canonical_prev, canonical_out=canonical_new)
        install_optional_manifests(REPO_ROOT, claude_home, archive=archive)
        if archive is not None:
            for env_file in env_files:
                if not env_existed[env_file] and (env_file.exists() or env_file.is_symlink()):
                    archive.record_created(env_file)
        if not ok:
            print("  ⚠ settings.json was left untouched (malformed / wrong shape).")
            print("    Fix it, or re-run with --force-global-config to replace it (a .bak is written).")
        # Readiness note: configured ≠ active — warn if any referenced hook script
        # is missing under claude_home/skills (inert until the skills are installed).
        missing = _missing_hook_scripts(claude_home)
        if missing:
            print(f"    ⚠ {len(missing)} SessionStart hook script(s) referenced by settings.json "
                  f"are missing under {claude_home/'skills'} — inert until installed:")
            for cmd in missing:
                print(f"        {cmd}")
    # Non-Claude targets receive placement_mode, NEVER the raw `mode` — the
    # cleanup decision is made here, per root, rather than carried inside a
    # string. Each skills MIRROR now gets the same provenance-gated cleanup the
    # Claude target has (S075): `<root>/.install-manifest.json` records what the
    # installer placed, and only something in that record AND absent from this
    # run can be removed. Before this, `mc` cleaned ~/.claude and silently left
    # every mirror to accumulate deleted skills forever.
    shipped_skills = _shipped_skill_names(REPO_ROOT)
    source_rev = _git_sha(REPO_ROOT) or "unknown"
    # `mc` now means cleanup at EVERY root, so this is the raw flag rather than
    # the Claude-scoped one.
    clean_mirrors = resolve_mode(mode)[1]
    # Authorization is NOT re-asked per root. A mirror prunes only if the user
    # said yes explicitly (--yes-prune) or already authorized this run's cleanup
    # interactively. Under --noninteractive without --yes-prune, prune_authorized
    # is empty and mirrors clean nothing — the same fail-safe the Claude target
    # applies, and the reason a scripted run cannot destroy a mirror by accident.
    prune_ok = bool(getattr(args, "yes_prune", False)) or bool(prune_authorized)
    if "copilot" in targets:
        print("[Copilot / VS Code]")
        install_copilot(REPO_ROOT, force=force, mirror_skills=args.mirror_copilot_skills,
                        mode=placement_mode)
        if args.mirror_copilot_skills:
            _report_mirror_prune("Copilot", prune_mirror_root(
                DEFAULT_COPILOT_HOME, "skills", shipped_skills,
                enabled=clean_mirrors, dry_run=args.dry_run,
                authorized=prune_ok, mode=mode, source_rev=source_rev, run_id=run_id))

        if getattr(args, "vscode_workspace", None):
            install_vscode_workspace(REPO_ROOT, args.vscode_workspace,
                                     force=force, dry_run=args.dry_run)

    # ---- git hooks (#250) ----
    #
    # OUTSIDE the target loop on purpose. The hooks gate a git repo, not a CLI's
    # config home, so making them conditional on `claude` being in --target would
    # reproduce #271 exactly: a payload that is fine and a routing rule that
    # silently does nothing. They are placed on every run unless --no-git-hooks.
    if not getattr(args, "no_git_hooks", False):
        hook_target = Path(getattr(args, "git_hooks", None) or REPO_ROOT)
        print("[git hooks]")
        install_git_hooks(REPO_ROOT, hook_target,
                          force=force, dry_run=args.dry_run)
    if "agy" in targets:
        print("[agy]")
        install_agy(gemini_home, force=force)
    if "gemini" in targets:
        print("[Gemini — skills only]")
        # install_gemini uses `force`-style semantics; pass not-skip to mean replace.
        n, sk, used_cli = install_gemini(REPO_ROOT, gemini_home, placement_mode, not skip_existing)
        if not used_cli:
            print(f"  ⚠ `gemini` CLI not found on PATH; used direct {mode} fallback")
        print(f"  ✓ {n} skills (skipped {sk}) — skills only; foundry passes gemini no work")
        _report_mirror_prune("Gemini", prune_mirror_root(
            gemini_home, "skills", shipped_skills,
            enabled=clean_mirrors, dry_run=args.dry_run,
            authorized=prune_ok, mode=mode, source_rev=source_rev, run_id=run_id))

    # ---- Provenance manifest (§11 A2) ----
    #
    # EVERY successful run writes/updates it — not only `mc` runs. `mc`
    # ADDITIONALLY consumes it for prune ownership, but if only `mc` wrote it
    # then a first `mc` on a box that had been installed a dozen times would
    # find no provenance at all, and would have to either prune blind or defer
    # forever.
    #
    # Written HERE, at the end, so it is written only after the run has
    # completed without aborting. Every failure path above returns early, and
    # an exception propagates out of _run() — so in both cases this line is
    # never reached and any previous manifest is left byte-identical.
    #
    # The `placed_claude` guard is load-bearing beyond tidiness: an empty dict
    # means install_claude never reported placements (it was stubbed, or the
    # claude target was not selected), and writing a manifest claiming the
    # installer placed nothing would mark every previously-owned entry as an
    # orphan on the next run.
    # ---- Cleanup, executed (§6.C1 ownership, §11 A8 breakers) ----
    #
    # Runs AFTER placement and BEFORE the manifest write, in that order for two
    # reasons: the authoritative "what this run shipped" set is what
    # install_claude() actually placed (not what the pre-flight predicted), and
    # the manifest must describe the tree as it ends up, not as it was
    # mid-cleanup.
    #
    # The candidate set is RECOMPUTED here from the real placement record. The
    # pre-flight set authorized the removal; this set proves it. Anything in the
    # recomputed set that the user did not authorize is skipped — the two agree
    # in every normal run, and if they ever disagree the safe reading of the
    # disagreement is the smaller set.
    pruned_n = 0
    if clean_claude and placed_claude and not mc_baseline_only:
        actual_candidates = compute_prune_candidates(previous_manifest, placed_claude)
        authorized_keys = {(c["category"], c["name"]) for c in prune_authorized}
        to_prune = [c for c in actual_candidates
                    if (c["category"], c["name"]) in authorized_keys]
        unauthorized = len(actual_candidates) - len(to_prune)
        if unauthorized:
            print(f"  ⚠ {unauthorized} additional orphan(s) appeared since the "
                  "cleanup was authorized — left in place.")
        if to_prune:
            pruned_n, failures = prune_orphans(claude_home, to_prune, archive)
            print(f"  ✓ cleanup: removed {pruned_n} entr"
                  f"{'y' if pruned_n == 1 else 'ies'} (archived, restorable "
                  f"with --rollback {run_id})")
            for name, why in failures:
                print(f"    ⚠ could not remove {name}: {why} — left in place")

    manifest = None
    if placed_claude:
        previous = previous_manifest
        manifest = build_manifest(
            placed_claude,
            source_rev=_git_sha(REPO_ROOT) or "unknown",
            run_id=run_id,
            mode=mode,
            # WP-005 populates this from the global-config writers, which
            # record ONLY on whole-file writes (§11 A1). `canonical_new` was
            # seeded from the previous block, so a run that wrote neither file
            # carries provenance forward rather than dropping it; if the claude
            # target never ran at all, fall back to the previous block directly.
            canonical=(canonical_new if canonical_new is not None
                       else (previous or {}).get("canonical")),
        )
        if write_manifest(claude_home, manifest):
            n_entries = sum(len(v) for v in manifest["entries"].values())
            print(f"  ✓ provenance manifest: {n_entries} entries + "
                  f"{len(manifest['meta_files'])} _meta files → {manifest_path(claude_home)}")

    # ---- Seal the journal ----
    # Reached only on the success path; every failure above returns early or
    # raises, leaving the journal `in_progress` so the NEXT run offers the
    # rollback this one could not perform. Archives are never expired here —
    # retention is an explicit, separate operation (§6.C2).
    if archive is not None:
        archive.set_new_manifest(manifest)
        archive.finalize()
        n_replaced = sum(1 for a in archive.completed_actions if a.get("op") == "replace")
        if n_replaced:
            print(f"  ✓ archived {n_replaced} replaced object(s) → {archive.root}")
            print(f"    undo this run with:  python3 install.py --rollback {run_id}")

    print()

    # ---- First `mc` run with no provenance: baseline written, cleanup deferred ----
    #
    # Exit 2, not 0 and not 1. The install succeeded, so 1 would be a lie; the
    # cleanup the user asked for did not happen, so 0 would be a different lie.
    # A distinct code lets a script tell "installed and cleaned" from "installed,
    # cleanup deferred" without parsing prose.
    #
    # This is the honest first move: with no previous manifest there is no proof
    # that this installer placed ANY of what is already at the destination, and
    # deleting on the assumption that it did is exactly the failure the manifest
    # exists to prevent. The baseline written by this run makes the NEXT one able
    # to clean.
    if mc_baseline_only:
        print("=" * 60)
        print("⚠  CLEANUP DEFERRED — no ownership provenance existed for this target.")
        print()
        print("   --mode mc removes only entries this installer can PROVE it placed,")
        print("   and proof comes from " + MANIFEST_FILENAME + ", which did not exist here")
        print("   before this run. Nothing was removed.")
        print()
        print(f"   A baseline manifest has been written to {manifest_path(claude_home)}.")
        print("   Re-run with --mode mc once the source tree changes and the cleanup")
        print("   will have the ownership record it needs.")
        print("=" * 60)
        run_extras(args)
        print("done (cleanup deferred).")
        return 2

    run_extras(args)
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
