#!/usr/bin/env python3
"""
agent-foundry installer.

Scans the host, shows a findings report, and ADAPTS the install — placing
skills + agents + commands from a cloned agent-foundry repo into the config
tree(s) of whichever AI CLIs you actually have installed:

    - Claude Code CLI    (~/.claude/{skills,agents,commands}/)
    - GitHub Copilot CLI (~/.claude/skills/ is auto-discovered by Copilot CLI
                          and VS Code 1.123+; plus ~/.copilot/ instructions and
                          an optional ~/.copilot/skills/ mirror)
    - Antigravity CLI    (`agy` — host directive at ~/.gemini/agy.md)
    - Gemini CLI         (LEGACY — ~/.gemini/skills/ via `gemini skills link`;
                          the gemini CLI retires 2026-06-18, agy is primary)

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
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
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

# Bundled templates (agy.md host directive, etc.) live next to this script in
# BOTH layouts (installer/templates/ in dev, <root>/templates/ when bundled).
_TEMPLATES_DIR = _HERE / "templates"

TARGETS_HELP = """\
Targets:
  c = Claude Code CLI         (~/.claude/skills/, ~/.claude/agents/, ~/.claude/commands/)
  p = GitHub Copilot CLI      (~/.copilot/ instructions + optional ~/.copilot/skills/ mirror;
                               note: ~/.claude/skills/ is already auto-discovered by Copilot CLI
                               and VS Code 1.123+ — no bridge needed)
  y = Antigravity CLI (agy)   (host directive at ~/.gemini/agy.md — primary delegate)
  g = Gemini CLI              (LEGACY — ~/.gemini/skills/ via `gemini skills link`; retires 2026-06-18)
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


# ---------------------------------------------------------------------------
# Run-log (Tee) — §8b
# ---------------------------------------------------------------------------
#
# A persistent debug log so a misbehaving run on a varied machine leaves a
# debuggable artifact. The RunLogger TEES sys.stdout + sys.stderr (it does NOT
# replace them), so every existing print() reaches the user UNCHANGED and is
# also mirrored to installer/logs/install-<UTC-ts>.log.
#
# HARD: logging MUST NEVER break the install. Log-dir/file creation is wrapped
# in try/except; an unwritable logs/ falls back to the OS temp dir with a
# one-line warning, never aborting. NO secrets: only the already-printed scan
# and step output are captured — os.environ is NEVER dumped.

# Where installer/logs/ lives (next to the scripts, both layouts).
DEFAULT_LOG_DIR = _HERE / "logs"


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
        n = self._real.write(data)
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
                        help="write the run-log to PATH (default: installer/logs/install-<UTC-ts>.log)")


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
        ("gemini", ["--version"], "Gemini CLI (LEGACY; retires 2026-06-18)", True),
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


# ---------------------------------------------------------------------------
# Per-target installers
# ---------------------------------------------------------------------------


def install_claude(
    repo_root: Path, claude_home: Path, mode: str, skip_existing: bool
) -> tuple[int, int, int, int, int, int]:
    """Install skills + agents + commands + workflows into Claude's config tree.

    Default behavior REPLACES existing entries at the destination (any kind:
    file, dir, or symlink — see _replace_existing). Pass skip_existing=True
    to opt into the old behavior of leaving existing entries untouched.

    `workflows/` are flat `*.js` saved-workflow files placed into
    ~/.claude/workflows/ (Claude-only — agy/Copilot/Gemini do not consume them).

    Returns (skill_n, agent_n, command_n, workflow_n, replaced_or_skipped, chmodded).
    """
    skills_target = claude_home / "skills"
    agents_target = claude_home / "agents"
    commands_target = claude_home / "commands"
    workflows_target = claude_home / "workflows"
    skills_target.mkdir(parents=True, exist_ok=True)
    agents_target.mkdir(parents=True, exist_ok=True)
    commands_target.mkdir(parents=True, exist_ok=True)

    skill_n = 0
    agent_n = 0
    command_n = 0
    workflow_n = 0
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

    # Saved workflows — flat *.js files placed into ~/.claude/workflows/ (S055).
    # Claude-only: agy/Copilot/Gemini do not consume saved workflows.
    workflows_dir = repo_root / "workflows"
    if workflows_dir.exists():
        for workflow in sorted(workflows_dir.glob("*.js")):
            if place(workflow, workflows_target / workflow.name):
                workflow_n += 1

    chmodded = 0
    if sys.platform != "win32":
        chmodded = chmod_scripts(skills_target)

    return skill_n, agent_n, command_n, workflow_n, touched_existing, chmodded


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


# Fallback agy directive used ONLY if the bundled installer/templates/agy.md is
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
    """True if target exists with content != expected (the hash-skip signal)."""
    try:
        return target.read_text(encoding="utf-8") != expected
    except (OSError, UnicodeDecodeError):
        return True


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

    if not target.exists():
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
| Gemini CLI  | `gemini skills link <path>` per skill (LEGACY; retires 2026-06-18) |

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

    if target.exists() and not force:
        print(f"    ⚠ {target} already exists — leaving as-is (use --force to overwrite)")
    else:
        target.write_text(COPILOT_AGENTS_MD)
        print(f"    + wrote {target}")

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
    print(f"    Model selection:   copilot --model <name>   (Claude / GPT / Gemini)")
    return True


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
        print(f"  • gemini   → {status('gemini')} — LEGACY, retires 2026-06-18; agy is primary")
    else:
        print(f"  • gemini   → not detected (legacy; agy is the primary delegate)")
    print()
    print("Recommendations:")
    if tools.get("agy", {}).get("found"):
        print("  - agy is your primary second-opinion/challenger delegate; its host directive")
        print("    (~/.gemini/agy.md, distinct from the gemini CLI) is created if absent.")
    if tools.get("gemini", {}).get("found"):
        print("  - gemini CLI is detected but is LEGACY (retires 2026-06-18) — prefer agy.")
    if report.get("skills_consumers"):
        print("  - " + " and ".join(report["skills_consumers"]) +
              " consume ~/.claude/skills/ for free; install the claude target.")
    print(f"  - pre-selected targets (interactive default): {', '.join(preselected)}")
    print()


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
             "(e.g. 'c,p' or 'claude,copilot'); 'a'/'all' = everything; "
             "'auto' = every CLI the scan detected",
        default=None,
    )
    parser.add_argument("--mode", choices=["link", "move"], default=None,
                        help="link = symlinks (recommended); move = copy")
    parser.add_argument("--claude-home", default=None,
                        help=f"override Claude config dir (default {DEFAULT_CLAUDE_HOME})")
    parser.add_argument("--gemini-home", default=None,
                        help=f"override Gemini config dir (default {DEFAULT_GEMINI_HOME})")
    parser.add_argument("--force", action="store_true",
                        help="(no-op for skills/agents — replace-existing is the default; "
                             "DOES force agy.md + copilot-instructions.md overwrite, with .bak)")
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
    add_log_args(parser)
    args = parser.parse_args()

    # §8b: tee all output to a run-log (on by default; --no-log opts out;
    # --log overrides the path). The logger NEVER aborts the install.
    with RunLogger(sys.argv, log_path=args.log, enabled=not args.no_log,
                   repo_root=REPO_ROOT, header_title="agent-foundry installer"):
        return _run(args)


def _run(args) -> int:
    banner()
    print()

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
        if "gemini" in targets or "agy" in targets:
            gemini_home = _ask_path_override("Gemini/agy", gemini_home)

    # ---- Confirm ----
    print()
    print("=" * 60)
    print("Plan:")
    if "claude" in targets:
        print(f"  Claude  ({mode}): {REPO_ROOT/'skills'}    → {claude_home/'skills'}")
        print(f"                    {REPO_ROOT/'agents'}    → {claude_home/'agents'}")
        print(f"                    {REPO_ROOT/'commands'}  → {claude_home/'commands'}")
        print(f"                    {REPO_ROOT/'workflows'} → {claude_home/'workflows'}")
    if "copilot" in targets:
        extra = " + ~/.copilot/skills mirror" if args.mirror_copilot_skills else ""
        print(f"  Copilot: write {DEFAULT_COPILOT_HOME/'copilot-instructions.md'}{extra}")
        print(f"           (~/.claude/skills already auto-discovered by Copilot CLI + VS Code 1.123+)")
    if "agy" in targets:
        print(f"  agy:     {gemini_home/'agy.md'} (host directive; create-if-absent, hash-skip, .bak on --force)")
    if "gemini" in targets:
        if report["tools"]["gemini"]["found"]:
            gemini_via = "via `gemini skills link`" if shutil.which("gemini") else "direct symlink"
            print(f"  Gemini  ({mode}, {gemini_via}, LEGACY — retires 2026-06-18): "
                  f"{REPO_ROOT/'skills'} → {gemini_home/'skills'}")
        else:
            print(f"  Gemini  (LEGACY): requested but `gemini` not detected — "
                  f"will use direct {mode} fallback into {gemini_home/'skills'}")
    if args.skip_existing:
        print("  Existing skills/agents/commands at the targets will be KEPT (--skip-existing).")
    else:
        print("  Existing skills/agents/commands at the targets will be REPLACED. Pass --skip-existing to keep them.")
    print("=" * 60)

    if not args.noninteractive:
        if not confirm("Proceed?", default=False):
            print("cancelled.")
            return 0

    # ---- Execute ----
    # Default: replace existing skills/agents/commands. `--skip-existing` keeps them.
    # `--force` forces agy.md / copilot-instructions.md overwrite (with .bak).
    skip_existing = bool(args.skip_existing)
    force = bool(args.force)
    print()
    if "claude" in targets:
        print("[Claude]")
        sc, ac, cc, wf, te, chm = install_claude(REPO_ROOT, claude_home, mode, skip_existing)
        verb = "kept" if skip_existing else "replaced"
        print(f"  ✓ {sc} skills, {ac} agents, {cc} commands, {wf} workflows installed ({te} {verb} existing)")
        if chm:
            print(f"    + chmod +x on {chm} skill scripts")
    if "copilot" in targets:
        print("[Copilot / VS Code]")
        install_copilot(REPO_ROOT, force=force, mirror_skills=args.mirror_copilot_skills,
                        mode=mode)
    if "agy" in targets:
        print("[agy]")
        install_agy(gemini_home, force=force)
    if "gemini" in targets:
        print("[Gemini — LEGACY]")
        # install_gemini uses `force`-style semantics; pass not-skip to mean replace.
        n, sk, used_cli = install_gemini(REPO_ROOT, gemini_home, mode, not skip_existing)
        if not used_cli:
            print(f"  ⚠ `gemini` CLI not found on PATH; used direct {mode} fallback")
        print(f"  ✓ {n} skills (skipped {sk}) — note: gemini CLI retires 2026-06-18; agy is primary")

    print()
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
