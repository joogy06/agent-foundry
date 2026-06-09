#!/usr/bin/env python3
"""install-pre-push-hook.py -- cross-platform pre-push hook installer.

Wires ``scripts/secrets-scan.py`` as a git ``pre-push`` hook on Linux, macOS,
and Windows -- including locked-down enterprise Windows laptops where PowerShell
is blocked (Execution Policy / AppLocker / Constrained Language Mode) but a
Python interpreter is available. Pure stdlib, Python 3.8+.

This replaces the PowerShell installer (``install-pre-push-hook.ps1``): ``.ps1``
cannot run where corporate policy blocks script execution, whereas this Python
path runs anywhere ``python3`` / ``py`` / ``python`` is present. The POSIX bash
installer (``install-pre-push-hook.sh``) is kept for shell users.

The hook this WRITES is a small ``#!/bin/sh`` script that invokes the Python
scanner (trying ``python3`` -> ``python`` -> ``py -3``). On Windows it runs via
Git-for-Windows' bundled shell, exactly like the hooks the ``.sh`` / ``.ps1``
installers wrote.

Idempotent: re-running replaces ONLY our hook (matched by the marker comment).
An existing UNMANAGED pre-push hook is backed up to ``pre-push.bak`` first -- a
user's own hook is never clobbered.

  Usage:
    python3 scripts/install-pre-push-hook.py                      # install into cwd
    python3 scripts/install-pre-push-hook.py --target-repo PATH   # install into PATH
    python3 scripts/install-pre-push-hook.py --uninstall          # remove our hook
    python3 scripts/install-pre-push-hook.py --help               # full help

  Exit codes:
    0 -- installed / uninstalled OK (possibly with warnings)
    2 -- could not proceed (not a git repo, hooks dir read-only, bad args)

HONEST LIMITATION
-----------------
A LOCAL pre-push hook is a best-effort developer safety net. It can be bypassed
(``git push --no-verify``) and is NOT installed where hooks are locked down by
corporate policy. It does NOT force anything. The authoritative secret gate is
server-side / CI -- this tool detects what it can do and reports honestly; it
never claims enforcement.
"""
from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

# Marker identifying a hook we manage. Re-installs match on this; only a hook
# carrying this line is ever overwritten or removed by us.
MARKER = "# managed-by: skill_factory/scripts/install-pre-push-hook.py"

# Seconds to bound every git subprocess. Generous, but guarantees we never hang
# on a wedged git (e.g. a stuck credential helper / network filesystem stat).
GIT_TIMEOUT = 30

# Honest, reused-everywhere limitation note.
LIMITATION_NOTE = (
    "Note: a local pre-push hook is a best-effort developer safety net -- it can\n"
    "be bypassed with `git push --no-verify` and is not installed where hooks are\n"
    "locked down by corporate policy. It does NOT force anything. The authoritative\n"
    "secret gate is server-side / CI."
)


# ---------------------------------------------------------------------------
# Reporting helpers (plain, no color -- safe for any terminal / CI log)
# ---------------------------------------------------------------------------

def _info(msg: str) -> None:
    print("[install] " + msg)


def _check(msg: str) -> None:
    print("[check]   " + msg)


def _warn(msg: str) -> None:
    print("[warn]    " + msg, file=sys.stderr)


def _error(msg: str) -> None:
    print("[error]   " + msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# git plumbing -- every call bounded by timeout + stdin closed
# ---------------------------------------------------------------------------

def _run_git(args, cwd):
    """Run ``git <args>`` in ``cwd``. Returns (rc, stdout, stderr).

    Never raises for an ordinary git failure: a missing git binary, a non-zero
    exit, or a timeout all come back as a normal (rc, out, err) tuple with rc
    != 0. This is what keeps the installer traceback-free on locked machines.
    """
    cmd = ["git"] + list(args)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=GIT_TIMEOUT,
            universal_newlines=True,  # text mode; 3.8-compatible spelling
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "git executable not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", "git timed out after {}s".format(GIT_TIMEOUT)
    except OSError as exc:  # pragma: no cover - exotic OS-level failure
        return 1, "", "git could not be launched: {}".format(exc)


def _is_git_worktree(target: Path) -> bool:
    """True if ``target`` is inside a git work tree.

    Belt-and-braces: accepts either a ``.git`` entry present OR a successful
    ``git rev-parse --is-inside-work-tree``. Covers plain repos, worktrees, and
    submodules (where ``.git`` is a file, not a dir).
    """
    if (target / ".git").exists():
        return True
    rc, out, _ = _run_git(["rev-parse", "--is-inside-work-tree"], target)
    return rc == 0 and out.strip() == "true"


def _resolve_hooks_dir(target: Path):
    """Resolve the effective hooks directory, honoring ``core.hooksPath``.

    Returns (hooks_dir: Path or None, hookspath_override: str or None).

    ``git rev-parse --git-path hooks`` returns the hooks dir git itself would
    use -- so if ``core.hooksPath`` points at a corporate-managed directory, we
    learn the real target instead of blindly writing ``.git/hooks``. The second
    element is the configured ``core.hooksPath`` value when one is set (so the
    caller can warn that local hooks are overridden), else None.
    """
    hookspath_override = None
    rc, out, _ = _run_git(["config", "--get", "core.hooksPath"], target)
    if rc == 0 and out.strip():
        hookspath_override = out.strip()

    rc, out, _ = _run_git(["rev-parse", "--git-path", "hooks"], target)
    if rc == 0 and out.strip():
        hp = Path(out.strip())
        if not hp.is_absolute():
            hp = (target / hp).resolve()
        return hp, hookspath_override

    # Fallback to the conventional location if rev-parse is unavailable for some
    # reason (very old git). Still honors an explicit absolute core.hooksPath.
    if hookspath_override:
        hp = Path(hookspath_override)
        if not hp.is_absolute():
            hp = (target / hp).resolve()
        return hp, hookspath_override
    return (target / ".git" / "hooks").resolve(), hookspath_override


def _dir_is_writable(path: Path) -> bool:
    """True if we can create/replace a file in ``path``.

    Tries to actually create+delete a probe file -- the only reliable test
    across NTFS ACLs, read-only mounts, and POSIX perms. ``os.access`` alone
    lies on Windows.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    probe = path / ".hook-write-probe.tmp"
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("probe")
        probe.unlink()
        return True
    except OSError:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass
        return False


def _python_on_path():
    """Return the first usable Python launcher name on PATH, or None.

    Mirrors the hook's own fallback order. Probing ``--version`` (bounded, stdin
    closed) confirms the candidate actually runs rather than being a stale shim
    (notably the Windows Store ``python``/``python3`` App-Execution-Alias stubs).
    """
    candidates = [("python3", ["--version"]),
                  ("python", ["--version"]),
                  ("py", ["-3", "--version"])]
    for exe, args in candidates:
        try:
            proc = subprocess.run(
                [exe] + args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                universal_newlines=True,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        if proc.returncode == 0:
            return exe
    return None


# ---------------------------------------------------------------------------
# Hook content
# ---------------------------------------------------------------------------

def _build_hook(scanner_path: Path) -> str:
    """Render the pre-push hook body.

    A POSIX ``#!/bin/sh`` script (runs under Git-for-Windows' bundled shell on
    Windows). It locates a Python interpreter the same way this installer does,
    then execs the scanner against the repo root. Missing scanner or missing
    Python => WARN and let the push through (a safety net must never wedge a
    developer out of pushing; the authoritative gate is server-side).
    """
    scanner_fwd = str(scanner_path).replace("\\", "/")
    # NOTE: this is the hook's shell source -- every $ that the shell must see is
    # written literally here (this is a normal Python string, not an f-string).
    return (
        "#!/bin/sh\n"
        + MARKER + "\n"
        "# Runs secrets-scan.py before every git push (cross-platform Python).\n"
        "# Override per-push with: git push --no-verify\n"
        "# Installed by scripts/install-pre-push-hook.py\n"
        "\n"
        "set -e\n"
        "\n"
        'SCANNER="' + scanner_fwd + '"\n'
        'REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"\n'
        "\n"
        'if [ ! -f "$SCANNER" ]; then\n'
        '    echo "[pre-push] WARN: scanner not found at $SCANNER -- letting push through" >&2\n'
        "    exit 0\n"
        "fi\n"
        "\n"
        "# Prefer python3, fall back to python, then the py launcher.\n"
        "for PY in python3 python py; do\n"
        '    if command -v "$PY" >/dev/null 2>&1; then\n'
        '        if [ "$PY" = "py" ]; then\n'
        '            exec py -3 "$SCANNER" "$REPO_ROOT"\n'
        "        else\n"
        '            exec "$PY" "$SCANNER" "$REPO_ROOT"\n'
        "        fi\n"
        "    fi\n"
        "done\n"
        "\n"
        'echo "[pre-push] WARN: no python found -- letting push through" >&2\n'
        "exit 0\n"
    )


def _looks_managed(hook_path: Path) -> bool:
    """True if the file at ``hook_path`` is one of ours (carries the marker)."""
    try:
        text = hook_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return MARKER in text


def _make_executable(path: Path) -> None:
    """Best-effort chmod +x. A no-op effect on Windows (no exec bit) -- Git for
    Windows honors the shebang regardless -- so failure here is never fatal."""
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def _uninstall(hook_path: Path) -> int:
    """Remove our managed hook; restore pre-push.bak if present. Exit 0."""
    backup = hook_path.with_name(hook_path.name + ".bak")

    if hook_path.exists() and _looks_managed(hook_path):
        try:
            hook_path.unlink()
            _info("removed managed hook: {}".format(hook_path))
        except OSError as exc:
            _error("could not remove {}: {}".format(hook_path, exc))
            return 2
        # Restore a previously backed-up unmanaged hook, if any.
        if backup.exists():
            try:
                backup.replace(hook_path)
                _make_executable(hook_path)
                _info("restored previous hook from {}".format(backup.name))
            except OSError as exc:
                _warn("could not restore {}: {}".format(backup.name, exc))
        return 0

    if hook_path.exists():
        _info("hook at {} is not managed by us -- leaving it untouched".format(hook_path))
    else:
        _info("no hook at {} -- nothing to uninstall".format(hook_path))
    # Even with no managed hook, offer to restore a stray backup so the repo is
    # not left missing a hook the user had before. Only act if there is no live
    # hook in the way.
    if not hook_path.exists() and backup.exists():
        _info("a {} exists but no live hook -- leaving the backup in place "
              "(restore manually if intended)".format(backup.name))
    return 0


def _install(target: Path, hooks_dir: Path, hookspath_override, scanner: Path) -> int:
    """Write our hook into ``hooks_dir``. Returns process exit code."""
    hook_path = hooks_dir / "pre-push"
    backup = hook_path.with_name(hook_path.name + ".bak")

    # Scanner sanity: warn (do not block) if it's missing -- the hook itself
    # also degrades to WARN-and-pass, and the path may legitimately be created
    # later / live elsewhere in a checkout.
    if not scanner.exists():
        _warn("scanner not found at {} -- installing anyway; the hook will "
              "WARN-and-skip until it exists".format(scanner))
    else:
        _make_executable(scanner)

    # Back up an existing UNMANAGED hook before we overwrite -- never clobber a
    # user's own hook.
    if hook_path.exists() and not _looks_managed(hook_path):
        try:
            backup.write_bytes(hook_path.read_bytes())
            _make_executable(backup)
            _info("backed up existing unmanaged hook -> {}".format(backup.name))
        except OSError as exc:
            _error("refusing to overwrite an unmanaged hook we can't back up "
                   "({}): {}".format(hook_path, exc))
            return 2
    elif hook_path.exists() and _looks_managed(hook_path):
        _info("replacing our previously-installed hook (idempotent)")

    # Write the hook atomically: temp file in the same dir, then replace.
    content = _build_hook(scanner)
    tmp = hook_path.with_name(hook_path.name + ".tmp")
    try:
        # newline="\n" guarantees LF line endings even on Windows -- required
        # for the hook to run under Git-for-Windows' sh.
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        _make_executable(tmp)
        os.replace(str(tmp), str(hook_path))
    except OSError as exc:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        _error("could not write hook at {}: {}".format(hook_path, exc))
        return 2
    _make_executable(hook_path)

    _info("pre-push hook installed at {}".format(hook_path))
    _info("hook runs: {}".format(scanner))
    if hookspath_override:
        _info("(installed into core.hooksPath target, not .git/hooks)")
    _info("override any single push with: git push --no-verify")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install-pre-push-hook.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Wire scripts/secrets-scan.py as a cross-platform git pre-push hook\n"
            "(Linux / macOS / Windows, including enterprise Windows where\n"
            "PowerShell is blocked but Python runs).\n\n"
            + LIMITATION_NOTE
        ),
        epilog=(
            "Idempotent via a marker comment; re-running replaces only our hook.\n"
            "An existing unmanaged pre-push hook is backed up to pre-push.bak first.\n"
            "Exit codes: 0 = ok (maybe with warnings), 2 = could not proceed."
        ),
    )
    parser.add_argument(
        "--target-repo",
        metavar="PATH",
        default=os.getcwd(),
        help="Git repository to install into (default: current directory).",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove our managed hook and restore pre-push.bak if present.",
    )
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    target = Path(args.target_repo).expanduser()
    try:
        target = target.resolve()
    except OSError:
        target = target.absolute()

    if not target.exists() or not target.is_dir():
        _error("target is not a directory: {}".format(target))
        return 2

    # --- capability check 1: is this a git work tree? -----------------------
    if not _is_git_worktree(target):
        _error("{} is not a git repository (no .git, and "
               "`git rev-parse --is-inside-work-tree` failed)".format(target))
        _info("run this from inside a git repo, or pass --target-repo PATH")
        return 2
    _check("git repository: {}".format(target))

    # --- capability check 2: resolve hooks dir (honor core.hooksPath) -------
    hooks_dir, hookspath_override = _resolve_hooks_dir(target)
    if hooks_dir is None:
        _error("could not resolve the git hooks directory")
        return 2
    if hookspath_override:
        _check("core.hooksPath is set -> {}".format(hookspath_override))
        _warn("core.hooksPath overrides per-repo hooks (corporate policy?); "
              "installing into the resolved path: {}".format(hooks_dir))
    else:
        _check("hooks directory: {}".format(hooks_dir))

    hook_path = hooks_dir / "pre-push"

    # --- uninstall short-circuit -------------------------------------------
    if args.uninstall:
        # Uninstall needs to read/remove within hooks_dir; if the dir is gone
        # there is simply nothing to do.
        if not hooks_dir.exists():
            _info("hooks directory does not exist -- nothing to uninstall")
            return 0
        return _uninstall(hook_path)

    # --- capability check 3: hooks dir writable? ----------------------------
    if not _dir_is_writable(hooks_dir):
        _error("can't install -- hooks directory is read-only "
               "(corporate policy?): {}".format(hooks_dir))
        _info("nothing was changed. The authoritative secret gate is "
              "server-side / CI; a local hook is only a best-effort net.")
        return 2
    _check("hooks directory is writable")

    # --- capability check 4: python on PATH (hook needs it to run) ----------
    py = _python_on_path()
    if py is None:
        _warn("no python3 / py / python found on PATH -- the hook needs Python "
              "to run. Install Python 3 (e.g. `winget install Python.Python.3`).")
        _warn("installing the hook anyway; it will WARN-and-skip until Python "
              "is available.")
    else:
        _check("python interpreter for the hook: {}".format(py))

    # Scanner lives next to this installer.
    scanner = (Path(__file__).resolve().parent / "secrets-scan.py")

    rc = _install(target, hooks_dir, hookspath_override, scanner)
    print()
    print(LIMITATION_NOTE)
    return rc


if __name__ == "__main__":
    sys.exit(main())
