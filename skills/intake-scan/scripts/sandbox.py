#!/usr/bin/env python3
"""sandbox.py -- the bwrap sandbox for third-party scanners (#350).

A third-party scanner is itself code we did not write, and it parses content chosen by an
attacker. So it runs inside `bwrap` with:

    no network             --unshare-all puts it in a new, empty network namespace
    new PID, IPC, UTS      it sees no host process and no host shared memory
    read-only /usr         the interpreter and system libraries, nothing else of the host
    read-only toolchain    the scanner's venv, at /tools/venv
    read-only target       the extracted target, at /target
    one writable directory /out, for the scanner's report
    tmpfs home and /tmp    the real home, the repo and the host /tmp are not bound at all
    cleared environment    --clearenv, then only the few variables named below

When `bwrap` is absent or cannot start (Windows, a container, a host with user namespaces
switched off, or the forced-absent switch), NOTHING is run: the result says `isolation:
none` and carries a named gap. There is no un-sandboxed fallback. A caller that wants a
scanner to run without a sandbox has to write that code somewhere else, on purpose.

`run()` never raises for an expected failure. The exit status of the scanner is returned
as evidence; it is the caller's business what a non-zero status means.

Stdlib only. Importing this module has no side effects.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

ISOLATION_BWRAP = "bwrap"
ISOLATION_NONE = "none"

# Named gaps. The text is ours; nothing from the target or the scanner is ever in it.
GAP_UNAVAILABLE = "sandbox-unavailable"      # no bwrap on this host, or forced absent
GAP_UNUSABLE = "sandbox-unusable"            # bwrap exists but cannot build a namespace
GAP_BAD_REQUEST = "sandbox-request-invalid"  # a path in the request is missing or unsafe
GAP_TIMEOUT = "scanner-timeout"
GAP_START = "scanner-start-failed"

GAPS = {
    GAP_UNAVAILABLE: "bwrap is not available on this host; third-party scanners did not run",
    GAP_UNUSABLE: "bwrap is installed but could not create a sandbox; third-party scanners did not run",
    GAP_BAD_REQUEST: "the sandbox request named a missing or unsafe path; nothing was run",
    GAP_TIMEOUT: "the scanner did not finish inside its time limit and was stopped",
    GAP_START: "the scanner could not be started inside the sandbox",
}

# Set to "none" to force the no-bwrap path (tests, and to rehearse the Windows behaviour).
FORCE_ENV = "FOUNDRY_INTAKE_ISOLATION"

# Where things appear inside the sandbox.
TARGET = "/target"
TOOLS = "/tools/venv"
OUT = "/out"
CONF = "/conf"
HOME = "/home/sandbox"

# The whole environment a scanner sees. No provider key, no token, no proxy, no host PATH.
SANDBOX_ENV = (
    ("HOME", HOME),
    ("PATH", "/usr/bin"),
    ("LANG", "C.UTF-8"),
    ("LC_ALL", "C.UTF-8"),
    ("TMPDIR", "/tmp"),
    ("PYTHONDONTWRITEBYTECODE", "1"),
    ("PYTHONIOENCODING", "utf-8"),
    ("NO_COLOR", "1"),
)

# Top-level directories that are links into /usr on a merged-usr host and real
# directories elsewhere. Either way the scanner gets them read-only.
_USR_ALIASES = ("bin", "sbin", "lib", "lib32", "lib64", "libx32")

DEFAULT_TIMEOUT_S = 300
PROBE_TIMEOUT_S = 20
# One scanner may not write more than this to any single file (its report, its logs).
MAX_OUTPUT_BYTES = 256 * 1024 * 1024

STDOUT_NAME = "stdout.txt"
STDERR_NAME = "stderr.txt"
OUT_NAME = "out"


class SandboxRequest(NamedTuple):
    argv: Tuple[str, ...]          # the scanner command, written with IN-SANDBOX paths
    target_dir: str                # host path; appears read-only at /target
    work_dir: str                  # host path we own; gets out/, stdout.txt and stderr.txt
    toolchain_dir: Optional[str] = None   # host path of the venv; read-only at /tools/venv
    conf_dir: Optional[str] = None        # host path of trusted config; read-only at /conf
    timeout_s: int = DEFAULT_TIMEOUT_S


class SandboxResult(NamedTuple):
    isolation: str                 # "bwrap" or "none"
    ran: bool                      # False when nothing was started
    exit_status: Optional[int]     # the scanner's own exit status; evidence only
    timed_out: bool
    out_dir: Optional[str]         # host path of /out
    stdout_path: Optional[str]
    stderr_path: Optional[str]
    duration_s: float
    gap: Optional[str]             # a key of GAPS, or None

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._asdict())


_PROBE_CACHE: Dict[str, bool] = {}


def forced_none(force_none: bool = False) -> bool:
    """True when the caller or the environment asks for the no-bwrap path."""
    return bool(force_none) or os.environ.get(FORCE_ENV, "").strip().lower() == ISOLATION_NONE


def find_bwrap(force_none: bool = False) -> Optional[str]:
    """The bwrap binary, or None when there is none (or it was forced absent)."""
    if forced_none(force_none) or os.name != "posix":
        return None
    for candidate in ("/usr/bin/bwrap", "/bin/bwrap"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("bwrap")


def _base_argv(bwrap: str) -> List[str]:
    argv = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
            "--cap-drop", "ALL", "--hostname", "sandbox",
            "--ro-bind", "/usr", "/usr"]
    for name in _USR_ALIASES:
        host = "/" + name
        if os.path.islink(host):
            argv += ["--symlink", os.readlink(host), host]
        elif os.path.isdir(host):
            argv += ["--ro-bind", host, host]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", HOME]
    return argv


def build_argv(bwrap: str, request: SandboxRequest, out_dir: str) -> List[str]:
    """The full bwrap command line for `request`. Pure: it starts nothing.

    Only four host paths are ever bound: /usr (read-only), the toolchain (read-only), the
    target (read-only) and `out_dir` (read-write). The trusted config directory, when one
    is given, is a fifth read-only bind. Neither the real home nor the repo is in the list.
    """
    argv = _base_argv(bwrap)
    if request.toolchain_dir:
        argv += ["--ro-bind", request.toolchain_dir, TOOLS]
    if request.conf_dir:
        argv += ["--ro-bind", request.conf_dir, CONF]
    argv += ["--ro-bind", request.target_dir, TARGET, "--bind", out_dir, OUT]
    for name, value in SANDBOX_ENV:
        argv += ["--setenv", name, value]
    argv += ["--chdir", OUT, "--"]
    argv += list(request.argv)
    return argv


def _limit_output() -> None:  # pragma: no cover - runs in the child, before exec
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError):
        pass


def probe(bwrap: str) -> bool:
    """Can this bwrap build the sandbox on this host? Cached for the life of the process.

    Runs /usr/bin/true inside the same namespaces a scanner would get. A host where
    unprivileged user namespaces are switched off fails here, before any scanner is tried.
    """
    cached = _PROBE_CACHE.get(bwrap)
    if cached is not None:
        return cached
    argv = _base_argv(bwrap) + ["--", "/usr/bin/true"]
    try:
        proc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, env={}, timeout=PROBE_TIMEOUT_S)
        ok = proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    _PROBE_CACHE[bwrap] = ok
    return ok


def isolation(force_none: bool = False) -> Tuple[str, Optional[str], Optional[str]]:
    """(isolation, bwrap path, gap). `bwrap` with a path, or `none` with the named gap."""
    bwrap = find_bwrap(force_none)
    if bwrap is None:
        return ISOLATION_NONE, None, GAP_UNAVAILABLE
    if not probe(bwrap):
        return ISOLATION_NONE, None, GAP_UNUSABLE
    return ISOLATION_BWRAP, bwrap, None


def _not_run(isolation_value: str, gap: str) -> SandboxResult:
    return SandboxResult(isolation_value, False, None, False, None, None, None, 0.0, gap)


def _usable_dir(path: Optional[str]) -> bool:
    return bool(path) and os.path.isabs(str(path)) and os.path.isdir(str(path))


def run(request: SandboxRequest, *, force_none: bool = False,
        bwrap: Optional[str] = None) -> SandboxResult:
    """Run one scanner inside the sandbox and return what happened.

    With no usable bwrap nothing is started and the result is `isolation: none` plus a gap.
    The scanner's stdout and stderr go to files beside `out/` in `work_dir`; they are
    scanner text and so are for the triage sheet only, never for the terminal.
    """
    if bwrap is None or forced_none(force_none):
        isolation_value, bwrap, gap = isolation(force_none)
        if gap is not None:
            return _not_run(isolation_value, gap)
    assert bwrap is not None
    if not request.argv or not _usable_dir(request.target_dir) or not _usable_dir(request.work_dir):
        return _not_run(ISOLATION_BWRAP, GAP_BAD_REQUEST)
    for optional in (request.toolchain_dir, request.conf_dir):
        if optional is not None and not _usable_dir(optional):
            return _not_run(ISOLATION_BWRAP, GAP_BAD_REQUEST)

    out_dir = os.path.join(request.work_dir, OUT_NAME)
    stdout_path = os.path.join(request.work_dir, STDOUT_NAME)
    stderr_path = os.path.join(request.work_dir, STDERR_NAME)
    try:
        os.makedirs(out_dir, 0o700, exist_ok=True)
    except OSError:
        return _not_run(ISOLATION_BWRAP, GAP_BAD_REQUEST)

    argv = build_argv(bwrap, request, out_dir)
    started = time.monotonic()
    timed_out = False
    status: Optional[int] = None
    try:
        with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    env={}, cwd=request.work_dir, close_fds=True,
                                    preexec_fn=_limit_output)
            try:
                status = proc.wait(timeout=max(1, int(request.timeout_s)))
            except subprocess.TimeoutExpired:
                # bwrap dies, and --die-with-parent takes the whole PID namespace with it.
                timed_out = True
                proc.kill()
                proc.wait()
    except (OSError, subprocess.SubprocessError):
        return SandboxResult(ISOLATION_BWRAP, False, None, False, out_dir, stdout_path,
                             stderr_path, time.monotonic() - started, GAP_START)
    duration = time.monotonic() - started
    if timed_out:
        return SandboxResult(ISOLATION_BWRAP, True, None, True, out_dir, stdout_path,
                             stderr_path, duration, GAP_TIMEOUT)
    return SandboxResult(ISOLATION_BWRAP, True, status, False, out_dir, stdout_path,
                         stderr_path, duration, None)
