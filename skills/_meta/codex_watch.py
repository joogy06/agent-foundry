#!/usr/bin/env python3
"""codex_watch.py -- activity-based watchdog for `codex exec` and `agy -p`.

S081 revision 4, stream A0 (design 2026-09-15 section 2.0, decision D24). This
module is THE ONE WAY any harness code runs `codex exec`. Nothing else in the
tree should spell `subprocess.run(["codex", ...], timeout=N)`, `timeout N codex
exec ...`, or a bare foreground Bash call.

WHY A HEARTBEAT AND NOT A WALL CLOCK
------------------------------------
Measured on the 2026-09-14/15 rollouts: completed `gpt-6-astra` calls ran
172-521 s against a 600 s xhigh floor, and two `gpt-5.6-sol` sessions (896 s and
538 s) ended with NO completion event while still emitting reasoning events up
to their last second -- longest silences 183 s and 19 s. They were not stuck.
They were killed mid-work by a wall clock. A wall clock cannot tell "thinking
hard" from "hung", so it must either kill healthy long calls or wait out dead
ones. INACTIVITY can tell them apart, so inactivity is what stops a call here.

The wall clock survives only as a RUNAWAY GUARD (the per-effort hard cap), never
as the normal stop.

HEARTBEAT SOURCES
-----------------
codex mode -- ANY of these is a heartbeat:
  * the stdout file grew;
  * the stderr file grew (codex prints its transcript there, so a call that
    looks silent on stdout is usually loud on stderr);
  * the session rollout file's mtime advanced. The rollout is located from the
    session id codex announces -- the `session id: <uuid>` line of the banner a
    plain `codex exec` prints on stderr (CODEX_BANNER_SESSION_RE, the ONE
    definition; audit_spawn binds the same object), or, for a `--json` run, the
    id that `thread.started` / `session_meta` carries -- and it is matched under
    $CODEX_HOME/sessions (CODEX_HOME set and non-empty: codex relocates its
    whole home with it, and the child inherits this process's environment),
    else ~/.codex/sessions, as YYYY/MM/DD/rollout-*<session id>*.jsonl. Until
    S081 rev 4 D21 F8 only the --json form was read, and no caller runs --json,
    so this source never fired in production. An `--ephemeral` call writes no
    rollout and relies on the two byte counters.

agy mode -- stdout growth ONLY. agy prints to stdout; its stderr is not a
progress channel, so counting it would keep a dead call alive.

THRESHOLDS
----------
  IDLE_TIMEOUT_S        300   CODEX ONLY. 1.6x the longest silence seen in a
                              real, healthy session (183 s). THE NORMAL STOP.
  HARD_CAP_S            low/medium 1200 - high/xhigh 2400 - max 3600 -
                        ultra 5400. Runaway protection only.
  AGY_IDLE_TIMEOUT_S    None  DISABLED -- see the next section.
  AGY_HARD_CAP_S        900   agy's ONLY stop.
  PROGRESS_INTERVAL_S   60    a line to the CALLER's stderr so a human can see
                              a long call is healthy rather than hung.

WHY AGY HAS NO IDLE TIMEOUT (S081 rev 4, WP-A01b, team-lead ruling 4)
---------------------------------------------------------------------
agy's only heartbeat here is STDOUT GROWTH, and agy emits nothing at all while
it is reasoning. Probed live on 2026-09-16 against a real `agy --sandbox -p`
call, sampling stdout every 5 s: 0 bytes at t=5 s, 0 at t=10 s, 250 at t=15 s,
10,730 at completion t~20 s. The silent reasoning prefix was ~75% of the call.
Raise `--print-timeout` for a deliberative call -- which the host directive
explicitly contemplates -- and that prefix plausibly runs past 300 s while the
call is perfectly healthy.

So a stdout-growth idle timeout on the agy arm can ONLY ever fire on a healthy
call. It is not a mistuned number; it is a mechanism with no signal to read --
the exact failure this watchdog exists to remove, reintroduced on the agy side.

It is therefore DISABLED: `AGY_IDLE_TIMEOUT_S = None`, NOT a large number. A
large number reads as a tuned value and invites someone to tune it later; None
says the mechanism does not apply. agy runs on AGY_HARD_CAP_S alone, and that
cap is still enforced -- disabling the idle timeout does not disable the runaway
guard.

THE ASYMMETRY WITH CODEX IS THE POINT, not an inconsistency. codex's heartbeat
is stdout OR stderr OR THE SESSION ROLLOUT'S MTIME, and the rollout advances
DURING reasoning -- the two killed sol sessions above were still emitting
reasoning events to their last second. codex has a liveness signal while it
thinks, so 300 s is well founded there. agy has none, so no number is.

CONDITIONAL ON THE EVIDENCE, NOT DOGMA. Give agy a real liveness signal -- a
progress channel, a rollout equivalent, a stderr that means something -- and an
idle timeout may be reinstated on that signal, at a value derived from it. Until
then there is nothing to derive one from. `TestFrozenConstants` asserts the
constant IS None, so reinstating it is a deliberate change that updates a test
rather than a number that drifts back in unnoticed.

`hard_cap_for()` RAISES on an effort it does not tabulate -- including
`minimal`, which codex_model tabulates for timeouts but which the D24 design
does not give a cap. That is deliberate and it is codex_model's own doctrine:
a `.get(effort, <scalar>)` is exactly how an untabulated tier silently inherits
a ceiling meant for a different one. Add the row in the change that needs it.

EXIT CODE CONTRACT -- FROZEN HERE
---------------------------------
Every later work package and every prose call site reads THIS table, so the
values do not move:

    stop_reason "ok"            -> the child's OWN exit code, passed through
                                   unchanged (0, 1, 2, anything).
    stop_reason "idle_timeout"  -> 111  (EXIT_IDLE_TIMEOUT)
    stop_reason "hard_cap"      -> 112  (EXIT_HARD_CAP)

Why 111 and 112. They must collide with nothing else in this chain:
  * 0-2      codex's and agy's own exits;
  * 124      GNU `timeout`'s "timed out" -- the very code a reader would
             otherwise confuse with ours;
  * 125-127  `timeout`/shell reserved (125 timeout itself, 126 not executable,
             127 command not found);
  * 128+N    death by signal (137 = SIGKILL, 143 = SIGTERM).
111 and 112 sit in the otherwise unused 100-123 band. A caller that sees 111
knows the call went quiet; 112 means it ran away; anything else came from the
child itself.

A SIGTERM or SIGHUP to the watchdog CLI stops the call as well: the child's
process group is terminated and REAPED first, then the CLI exits 128+N (143,
129) -- the death-by-signal band the table above already keeps clear of. See
STOP SIGNALS.

On EVERY stop path the child is terminated and reaped -- no orphan, no zombie --
and the partial stdout/stderr files are left in place for the caller's
classifier to read.

STOP SIGNALS (S081 rev 4 D21 F9)
--------------------------------
The child runs in its own session (`start_new_session=True`) so a stop can
signal its whole process group -- which also means nothing reaches it when the
watchdog itself dies. A SIGTERM (a harness cancel, a `timeout` wrapper, a killed
foreground call) used to kill the watchdog WITHOUT running its `finally`,
orphaning a `codex exec` that went on running -- and metering quota -- for an
answer nobody would read. So `main()`, and only main() (a handler can only be
installed from the main thread), holds SIGTERM and SIGHUP handlers for the
duration of the call:

  * the handler LATCHES the first stop and raises it (`_StopSignal`, a
    BaseException, so no `except Exception` on the way out swallows it) only
    while the reap is ARMED. watch() arms it the instant Popen returns, and a
    stop that landed before that -- even inside Popen -- is raised at that
    instant, inside the try whose `finally` reaps: no window between the spawn
    and the reap;
  * the `finally` disarms before it reaps, and a second stop never raises, so
    no stop can abort a reap in progress;
  * the CLI then exits 128+N, and the previous handlers are restored;
  * a signal the caller IGNORES (`nohup` ignores SIGHUP) stays ignored: it
    cannot stop the watchdog, so it cannot orphan the child either.

A stream failure never stops a call; a stop request always does, the progress
write included (D21 fix round 2, N1): that write catches only Exception -- a
closed stream, a broken pipe, a console that cannot encode the line -- where it
used to catch BaseException and swallow the stop, after which the latch ignored
every later one and the call ran on to its own end.

SIGINT keeps Python's KeyboardInterrupt, which always ran the `finally`.

An IN-PROCESS caller whose watch() runs in a worker thread (audit_spawn's codex
arm, #292) installs the handlers itself, on its main thread, with a
`_StopLatch(record_only=True)`: the handler only records the stop, and watch()'s
poll loop raises it in the worker within one poll interval, so the child is
reaped there before the caller exits 128+N.

TELEMETRY
---------
One row per call through `skills/process-observation/scripts/spawn_runs.py`
(`record_spawn_run`), the sidecar the ecosystem already uses -- not a second
log. `elapsed_s` is carried by the existing `wall_clock_s` field and
`stop_reason` by the existing `status` field, both exact semantic matches.

The five watchdog fields in `TELEMETRY_EXTRA_FIELDS` -- `max_silence_s`,
`stop_reason`, `exit_code`, `idle_timeout_s`, `hard_cap_s` -- are accepted by
the sidecar as of S081 rev 4 WP-A01b (team-lead ruling 1; WP-A01 shipped with
them offered but dropped). `max_silence_s` is the one that earns its place: it
is the only field that can say how close a HEALTHY call came to tripping the
idle timeout, which is the question the threshold has to be tuned against.
`elapsed_s` and `stop_reason` cannot answer it -- they describe calls that
stopped, not the margin on calls that did not.

An agy row carries no `idle_timeout_s`: the value is None and the sidecar omits
a None optional. That absence is the honest record that the mechanism does not
apply there, not a lost field.

The signature filter stays deliberately: a sidecar copy older than that
amendment (a half-copied tree) drops the five rather than raising TypeError and
losing the whole row. Telemetry is best-effort and never raises: a broken
backend cannot change this module's return value or exit code.

PORTABILITY
-----------
Process management is the highest portability risk in this cycle, so: no
platform-exclusive import at module scope (`signal` is imported inside the
functions that need it -- the reap and the CLI's handler install -- SIGHUP is
reached through `getattr` because Windows has none, and POSIX-only `os.killpg`
is reached through a `hasattr` branch with a `terminate()` fallback);
`encoding=` on every text read; ASCII-only console output.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import stat
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "CodexWatchError",
    "AgyArgvError",
    "WatchResult",
    "IDLE_TIMEOUT_S",
    "AGY_IDLE_TIMEOUT_S",
    "AGY_HARD_CAP_S",
    "HARD_CAP_S",
    "PROGRESS_INTERVAL_S",
    "EXIT_IDLE_TIMEOUT",
    "EXIT_HARD_CAP",
    "STOP_OK",
    "STOP_IDLE_TIMEOUT",
    "STOP_HARD_CAP",
    "STOP_REASONS",
    "TELEMETRY_EXTRA_FIELDS",
    "CODEX_BANNER_SESSION_RE",
    "hard_cap_for",
    "validate_agy_argv",
    "watch",
    "codex_watch",
    "agy_watch",
    "telemetry_row",
    "main",
]


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class CodexWatchError(Exception):
    """Any watchdog contract violation (unknown effort, unusable argv)."""


class AgyArgvError(CodexWatchError):
    """An agy argv that breaks the stdin, flag-order or sandbox rule."""


# --------------------------------------------------------------------------- #
# Constants -- the frozen numbers
# --------------------------------------------------------------------------- #
IDLE_TIMEOUT_S: int = 300

#: DISABLED, not a large number -- see "WHY AGY HAS NO IDLE TIMEOUT" above.
#: agy emits nothing while it reasons, so a stdout-growth idle timeout on the
#: agy arm can only ever fire on a HEALTHY call. `None` says the mechanism does
#: not apply; a number would say it is tuned. agy stops on AGY_HARD_CAP_S alone.
#: Reinstate this ONLY against a real agy liveness signal.
AGY_IDLE_TIMEOUT_S: Optional[int] = None

AGY_HARD_CAP_S: int = 900
PROGRESS_INTERVAL_S: int = 60

#: Per-effort runaway cap. STRICT: a miss raises rather than defaulting.
HARD_CAP_S: Dict[str, int] = {
    "low": 1200,
    "medium": 1200,
    "high": 2400,
    "xhigh": 2400,
    "max": 3600,
    "ultra": 5400,
}

EXIT_IDLE_TIMEOUT: int = 111
EXIT_HARD_CAP: int = 112

STOP_OK = "ok"
STOP_IDLE_TIMEOUT = "idle_timeout"
STOP_HARD_CAP = "hard_cap"
STOP_REASONS: Tuple[str, ...] = (STOP_OK, STOP_IDLE_TIMEOUT, STOP_HARD_CAP)

MODE_CODEX = "codex"
MODE_AGY = "agy"

#: The five watchdog telemetry fields beyond the sidecar's core row (see the
#: module docstring's TELEMETRY section). Offered on every call; the installed
#: spawn_runs.record_spawn_run accepts all five since S081 rev 4 WP-A01b. The
#: signature filter in _record_telemetry stays for a half-copied older sidecar,
#: which then drops these rather than losing the whole row.
TELEMETRY_EXTRA_FIELDS: Tuple[str, ...] = (
    "max_silence_s",
    "stop_reason",
    "exit_code",
    "idle_timeout_s",
    "hard_cap_s",
)

_DEFAULT_POLL_INTERVAL_S = 1.0
_DEFAULT_REAP_GRACE_S = 5.0

#: Codex's own banner line naming the session, printed on STDERR by every plain
#: `codex exec` before the model call, with and without --ephemeral:
#:     session id: 01a0cb17-355b-7f32-92f6-010c8f42b7d6      (codex-cli 0.155.1)
#: ONE definition (S081 rev 4 D21 F8): the watchdog needs it to find the rollout
#: heartbeat, and audit_spawn binds this same object for its token lookup. Moved
#: verbatim from audit_spawn; the charset (hex and dashes only) keeps the id safe
#: inside the rollout glob.
CODEX_BANNER_SESSION_RE = re.compile(
    r"^session id:[ \t]*([0-9A-Fa-f][0-9A-Fa-f-]{7,63})[ \t]*$", re.MULTILINE
)

# A codex session id as it appears in `thread.started` / `session_meta` -- the
# `--json` event form, read after the banner form.
_SESSION_ID_RE = re.compile(
    r"\b([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)
_SESSION_KEY_RE = re.compile(r"(thread\.started|thread_id|session_id|session_meta)")

# Bytes of a stream we are willing to re-scan for a session id. The id appears
# in the first event, so this never needs to grow with the transcript.
_SESSION_SCAN_BYTES = 65536

_AGY_PROMPT_FLAGS = ("-p", "--print", "--prompt")


def hard_cap_for(effort: str) -> int:
    """Return the runaway cap for `effort`. RAISES on an untabulated effort.

    No scalar default, on purpose -- see the module docstring. `minimal` is
    untabulated by the D24 design and therefore raises; give it a row in the
    change that needs it rather than letting it inherit another tier's cap.
    """
    try:
        return HARD_CAP_S[effort]
    except (KeyError, TypeError):
        raise CodexWatchError(
            "no hard cap recorded for effort {0!r}; the watchdog refuses to "
            "default an untabulated tier onto another tier's cap -- add the "
            "row. Known: {1}".format(effort, ", ".join(sorted(HARD_CAP_S)))
        ) from None


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WatchResult:
    """Everything a caller or a classifier needs about one watched call."""

    stop_reason: str
    exit_code: int
    child_exit_code: Optional[int]
    elapsed_s: float
    max_silence_s: float
    mode: str
    argv: Tuple[str, ...]
    stdout_path: Path
    stderr_path: Path
    #: None when no idle timeout applies (agy mode). Not 0, not a sentinel
    #: number -- a reader must be able to tell "no idle timeout" from "an idle
    #: timeout of N seconds".
    idle_timeout_s: Optional[float]
    hard_cap_s: float
    rollout_path: Optional[Path] = None
    model: Optional[str] = None
    progress_lines: Tuple[str, ...] = field(default=())

    @property
    def timed_out(self) -> bool:
        """True when the WATCHDOG stopped the call (either kind of stop)."""
        return self.stop_reason in (STOP_IDLE_TIMEOUT, STOP_HARD_CAP)


def telemetry_row(result: WatchResult) -> Dict[str, Any]:
    """The full watchdog telemetry row, including the fields the installed
    sidecar cannot yet persist. Pure; safe to log, diff or assert on."""
    return {
        "tool": "{0}_watch".format(result.mode),
        "status": result.stop_reason,
        "stop_reason": result.stop_reason,
        "elapsed_s": result.elapsed_s,
        "wall_clock_s": result.elapsed_s,
        "max_silence_s": result.max_silence_s,
        "exit_code": result.exit_code,
        "child_exit_code": result.child_exit_code,
        "idle_timeout_s": result.idle_timeout_s,
        "hard_cap_s": result.hard_cap_s,
        "model": result.model,
    }


# --------------------------------------------------------------------------- #
# agy argv rules -- #135 (stdin) and S052 (un-sandboxed) cannot be reintroduced
# --------------------------------------------------------------------------- #
def validate_agy_argv(argv: Sequence[str]) -> Tuple[str, ...]:
    """Check an agy command line against the host's three standing rules.

    Returns the argv as a tuple when it is legal; raises `AgyArgvError` naming
    the broken rule otherwise.

      FLAG ORDER  every flag goes BEFORE the prompt flag and the prompt is the
                  LAST token. `-p` is a string flag, so `agy -p --sandbox "X"`
                  runs UN-sandboxed with the literal prompt "--sandbox" and
                  silently discards "X" -- the root cause of the 2026-07-01/02
                  rogue-edit incidents.
      SANDBOX     `--sandbox` must be present, before the prompt flag. The rule
                  is "never drop --sandbox; add --dangerously-skip-permissions
                  instead" -- so there is no opt-out here.
      STDIN       enforced by `watch()` itself, which spawns with stdin=DEVNULL,
                  or with a caller's REGULAR FILE (stdin_path=) that EOFs at its
                  end; anything that might never EOF is refused before the spawn. Headless agy waits on a non-TTY stdin to EOF
                  before it calls the model, so an inherited stdin that never
                  EOFs hangs it forever at 0 bytes (#135), and --print-timeout
                  does not fire because it only guards the print phase.
    """
    tokens = [str(t) for t in argv]
    if not tokens:
        raise AgyArgvError("agy argv is empty")

    positions = [i for i, t in enumerate(tokens) if t in _AGY_PROMPT_FLAGS]
    if not positions:
        raise AgyArgvError(
            "agy argv has no prompt flag; expected one of {0}".format(
                ", ".join(_AGY_PROMPT_FLAGS)
            )
        )
    if len(positions) > 1:
        raise AgyArgvError(
            "agy argv repeats the prompt flag at indices {0}; exactly one "
            "prompt is allowed".format(positions)
        )

    at = positions[0]
    trailing = tokens[at + 1:]
    if len(trailing) != 1:
        raise AgyArgvError(
            "FLAG ORDER: the prompt flag {0!r} must be followed by exactly one "
            "token (the prompt) and nothing else; found {1} trailing token(s): "
            "{2}. Every flag goes BEFORE the prompt.".format(
                tokens[at], len(trailing), trailing
            )
        )

    stray = [t for t in tokens[:at] if t in ("--sandbox",)]
    if not stray:
        raise AgyArgvError(
            "SANDBOX: --sandbox is missing before {0!r}. agy has write, shell "
            "and git tools on by default and headless -p auto-approves them; "
            "never drop --sandbox, add --dangerously-skip-permissions when the "
            "call genuinely needs tools.".format(tokens[at])
        )
    return tuple(tokens)


# --------------------------------------------------------------------------- #
# Rollout discovery
# --------------------------------------------------------------------------- #
def _default_sessions_dir() -> Path:
    """Where the CHILD writes its rollout, read at call time (S081 rev 4 D21 F8).

    $CODEX_HOME/sessions when CODEX_HOME is set and non-empty -- the codex CLI
    relocates its whole home with it, and the child inherits this process's
    environment -- else ~/.codex/sessions. The asymmetry with codex_quota, whose
    meter does not honour CODEX_HOME, is deliberate (plan L40): the watchdog must
    look where the child writes; the meter's limit is recorded there.
    """
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "sessions"
    return Path.home() / ".codex" / "sessions"


def _tail_text(path: Path, limit: int) -> str:
    """Read at most `limit` bytes of `path` as lenient utf-8. Never raises."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit)
    except OSError:
        return ""
    return data.decode("utf-8", "replace")


def _complete_lines(text: str) -> str:
    """`text` up to and including its last newline. A poll can land while codex is
    still writing a line, and the banner regex's `$` also matches at the end of
    the text, so a half-written `session id:` line would yield a TRUNCATED id."""
    return text[: text.rfind("\n") + 1]


def _find_session_id(stdout_path: Path, stderr_path: Path) -> Optional[str]:
    """Pull a codex session id out of whichever stream announced it.

    BANNER FIRST (S081 rev 4 D21 F8): a plain `codex exec` -- every caller's
    shape -- announces `session id: <uuid>` in its stderr banner, and only on
    stderr; its stdout is the model's own answer, so stderr is read first, and
    only completed lines. The first banner line wins over a prompt echoed after
    it. THEN the `--json` form: a `thread.started` / `session_meta` event carries
    the id. That rule takes the first uuid anywhere once a key word appears, so
    it runs second -- on a plain call it would take the uuid of a workdir path
    whenever the echoed prompt happened to say `session_meta`.
    """
    texts = {path: _tail_text(path, _SESSION_SCAN_BYTES) for path in (stdout_path, stderr_path)}
    for path in (stderr_path, stdout_path):
        found = CODEX_BANNER_SESSION_RE.search(_complete_lines(texts[path]))
        if found:
            return found.group(1)
    for path in (stdout_path, stderr_path):
        text = texts[path]
        if not text or not _SESSION_KEY_RE.search(text):
            continue
        found = _SESSION_ID_RE.search(text)
        if found:
            return found.group(1)
    return None


def _find_rollout(sessions_dir: Path, session_id: str) -> Optional[Path]:
    """Locate the rollout whose filename carries `session_id`."""
    try:
        if not sessions_dir.is_dir():
            return None
        matches = sorted(sessions_dir.glob("**/rollout-*{0}*.jsonl".format(session_id)))
    except OSError:
        return None
    return matches[0] if matches else None


# --------------------------------------------------------------------------- #
# Child lifecycle
# --------------------------------------------------------------------------- #
def _open_streams(stdout_path: Path, stderr_path: Path):
    """The two output files, opened for the child. Never leaks the first on a
    failure to open the second."""
    out = open(stdout_path, "wb")
    try:
        err = open(stderr_path, "wb")
    except BaseException:
        out.close()
        raise
    return out, err


def _open_stdin(stdin_path):
    """The child's stdin: DEVNULL, or a REGULAR FILE opened for reading (#291 fix round 2 N2).

    STDIN RULE (#135 / #155): the child's stdin must reach EOF. /dev/null does at once, and
    a regular file does at its end -- no pipe, so no writer thread and no pipe-buffer
    deadlock. Anything else (a FIFO, a directory, a device, a missing path) might never
    EOF and is refused with CodexWatchError BEFORE the spawn."""
    if stdin_path is None:
        return None
    path = Path(stdin_path)
    # O_NONBLOCK: a plain open() of a FIFO blocks until a writer appears -- the very hang
    # this refuses. Harmless for a regular file (reads never block on one). Windows has no
    # O_NONBLOCK and no FIFOs, so the flag is simply absent there.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise CodexWatchError("stdin file {0} cannot be opened: {1}".format(path, exc))
    try:
        mode = os.fstat(fd).st_mode
    except OSError as exc:
        os.close(fd)
        raise CodexWatchError("stdin file {0} cannot be inspected: {1}".format(path, exc))
    if not stat.S_ISREG(mode):
        os.close(fd)
        raise CodexWatchError(
            "stdin file {0} is not a regular file; only a regular file is guaranteed to "
            "reach EOF (STDIN RULE)".format(path))
    # Undo O_NONBLOCK only where the open set it. On Windows there is no O_NONBLOCK, and
    # os.set_blocking (3.12+) works on pipes only - on a regular file it raises (#291 final
    # re-review F1) - so it is not called there at all. Any failure is a refused call,
    # before the spawn, and never leaks the descriptor.
    if getattr(os, "O_NONBLOCK", 0) and hasattr(os, "set_blocking"):
        try:
            os.set_blocking(fd, True)
        except OSError as exc:
            os.close(fd)
            raise CodexWatchError("stdin file {0} cannot be made blocking: {1}".format(path, exc))
    return os.fdopen(fd, "rb")


def _spawn(argv: Sequence[str], out, err, stdin_handle=None):
    """Popen with stdin CLOSED (or a regular file that EOFs) and both streams
    redirected to the open files.

    Called INSIDE watch()'s try, so the `finally` that reaps is already in force
    when this returns (S081 rev 4 D21 F9)."""
    return subprocess.Popen(  # noqa: S603 - argv is a list, never a shell
        list(argv),
        stdin=stdin_handle if stdin_handle is not None else subprocess.DEVNULL,
        stdout=out,
        stderr=err,
        start_new_session=True,
        close_fds=True,
    )


class _StopSignal(BaseException):
    """A SIGTERM / SIGHUP delivered to the watchdog CLI (S081 rev 4 D21 F9).

    A BaseException, like KeyboardInterrupt, so no `except Exception` between the
    handler and main() can swallow it; watch()'s `finally` reaps on the way out.
    """

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


class _StopLatch:
    """The CLI's SIGTERM / SIGHUP handler state (S081 rev 4 D21 F9).

    `handler` records the FIRST stop and raises it only while the reap is ARMED;
    a stop that lands earlier -- before or even inside Popen -- is held, and
    `arm()` raises it the instant watch() has the child in hand, inside the try
    whose `finally` reaps. A second stop never raises: raised during the reap, it
    would abort it. watch()'s `finally` sets `armed = False` before it reaps.

    `record_only=True` is the IN-PROCESS caller's latch (#292): watch() runs in a
    worker thread there, and a signal handler always runs in the MAIN thread, so
    raising from it would land in the wrong thread and leave the child running.
    Its handler only records the stop; watch()'s poll loop, which checks
    `signum` on every pass, raises in the worker, inside the try that reaps.
    """

    def __init__(self, record_only: bool = False) -> None:
        self.signum: Optional[int] = None
        self.armed = False
        self.record_only = record_only

    def handler(self, signum, _frame=None) -> None:
        # No call before the store: a nested stop landing here finds it set.
        if self.signum is not None:
            return
        self.signum = signum
        if self.armed and not self.record_only:
            raise _StopSignal(signum)

    def arm(self) -> None:
        self.armed = True
        if self.signum is not None:
            raise _StopSignal(self.signum)


#: The stop signals the CLI takes over for the duration of a call. SIGINT is not
#: among them: Python's KeyboardInterrupt already runs watch()'s `finally`.
_STOP_SIGNAL_NAMES: Tuple[str, ...] = ("SIGTERM", "SIGHUP")


def _install_stop_handlers(latch: _StopLatch) -> List[Tuple[int, Any]]:
    """Point SIGTERM and SIGHUP at `latch.handler`; return what to restore.

    MAIN THREAD ONLY -- `signal.signal` raises ValueError anywhere else, and such
    a signal is simply left alone. SIGHUP is reached through getattr (Windows has
    none). A signal the caller IGNORES stays ignored: `nohup` asked to survive a
    hangup, and a signal that cannot stop the watchdog cannot orphan its child.
    """
    import signal as _signal  # deferred: keeps POSIX signal names out of import

    previous: List[Tuple[int, Any]] = []
    for name in _STOP_SIGNAL_NAMES:
        signum = getattr(_signal, name, None)
        if signum is None:
            continue
        try:
            current = _signal.getsignal(signum)
            if current == _signal.SIG_IGN:
                continue
            _signal.signal(signum, latch.handler)
        except (ValueError, OSError, RuntimeError):
            continue
        previous.append((signum, current))
    return previous


def _restore_stop_handlers(previous: List[Tuple[int, Any]]) -> None:
    """Put back what `_install_stop_handlers` replaced. Never raises. A handler
    installed outside Python reads back as None and is restored as SIG_DFL."""
    import signal as _signal  # deferred: keeps POSIX signal names out of import

    for signum, handler in previous:
        try:
            _signal.signal(signum, _signal.SIG_DFL if handler is None else handler)
        except (ValueError, OSError, RuntimeError, TypeError):
            pass


def _terminate_and_reap(proc, grace_s: float) -> Optional[int]:
    """Stop the child, then REAP it. No orphan, no zombie, never raises.

    POSIX gets a process-group signal first so a codex that spawned helpers does
    not leave them behind; `start_new_session=True` is what makes the child its
    own group leader. Everything else -- and any POSIX call that fails -- falls
    back to `terminate()`, then `kill()`.
    """
    if proc.poll() is not None:
        return proc.returncode

    import signal as _signal  # deferred: keeps POSIX signal names out of import

    def _group_signal(sig) -> bool:
        if os.name != "posix" or not hasattr(os, "killpg"):
            return False
        try:
            os.killpg(os.getpgid(proc.pid), sig)
            return True
        except (OSError, AttributeError):
            return False

    if not _group_signal(getattr(_signal, "SIGTERM", None)):
        try:
            proc.terminate()
        except OSError:
            pass
    try:
        return proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        pass

    if not _group_signal(getattr(_signal, "SIGKILL", getattr(_signal, "SIGTERM", None))):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        return proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        # Reaped as far as this process can; the caller still gets a result.
        return None


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _mtime_ns(path: Optional[Path]) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


# --------------------------------------------------------------------------- #
# Telemetry (best-effort, never raises)
# --------------------------------------------------------------------------- #
def _load_record_spawn_run() -> Optional[Callable[..., None]]:
    here = Path(__file__).resolve().parent
    sidecar = here.parent / "process-observation" / "scripts"
    try:
        if str(sidecar) not in sys.path:
            sys.path.insert(0, str(sidecar))
        from spawn_runs import record_spawn_run  # noqa: E402

        return record_spawn_run
    except BaseException:  # noqa: BLE001 - telemetry never breaks the call
        return None


def _record_telemetry(result: WatchResult, extra: Optional[Dict[str, Any]] = None) -> None:
    """Append one spawn-run row. BEST-EFFORT; never raises, never alters exits."""
    try:
        record = _load_record_spawn_run()
        if record is None:
            return
        row = telemetry_row(result)
        kwargs: Dict[str, Any] = {
            "tool": row["tool"],
            "status": row["status"],
            "cost_usd": None,
            "duration_ms": round(result.elapsed_s * 1000.0, 3),
            "num_turns": None,
            "wall_clock_s": result.elapsed_s,
            "model": result.model,
        }
        for name in TELEMETRY_EXTRA_FIELDS:
            kwargs[name] = row.get(name)
        if extra:
            kwargs.update(extra)

        import inspect

        accepted = set(inspect.signature(record).parameters)
        filtered = {k: v for k, v in kwargs.items() if k in accepted}
        record(**filtered)
    except BaseException as exc:  # noqa: BLE001 - #124 never-raise contract
        try:
            sys.stderr.write(
                "CODEX_WATCH_TELEMETRY_FAIL: {0}: {1}\n".format(type(exc).__name__, exc)
            )
        except BaseException:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# The watchdog
# --------------------------------------------------------------------------- #
def _checked_seconds(name: str, value) -> float:
    """A finite number of seconds > 0, else CodexWatchError naming `name`.

    ONE checker for every duration a caller hands the watchdog, called before
    any path handling, the pre-spawn stop check or the spawn. What a bad value
    used to do:

      progress interval  (S081 rev 4 D21 f9) 0, a negative or -inf made
                         `next_progress += interval` spin forever after the
                         first line, past the idle timeout and the hard cap;
                         NaN silently disabled the line, +inf never printed one.
      poll interval      (D21 fix round 2, R2-12) 0 busy-polled at full CPU; a
                         negative, NaN, +inf or a string raised from sleep()
                         AFTER the spawn; True was a 1 s poll.
      hard cap,          (D21 fix round 2, R2-12b) NaN or +inf switched the stop
      idle timeout       OFF (`elapsed >= nan` is always False); 0 or a negative
                         stopped the call the instant it spawned; a string raised
                         AFTER the spawn; True was a 1 s stop.

    A bool is refused like any non-number. Only a value the CALLER supplied
    reaches this: a None hard cap or idle timeout keeps its meaning (the
    effort's cap; the mode default, which in agy mode is no idle stop at all).
    """
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise CodexWatchError(
            "{0} must be a finite number of seconds > 0, got {1!r}".format(name, value)
        )
    return float(value)


def watch(
    argv: Sequence[str],
    *,
    mode: str = MODE_CODEX,
    effort: Optional[str] = None,
    stdout_path,
    stderr_path,
    stdin_path=None,
    model: Optional[str] = None,
    idle_timeout_s: Optional[float] = None,
    hard_cap_s: Optional[float] = None,
    progress_interval_s: Optional[float] = None,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    reap_grace_s: float = _DEFAULT_REAP_GRACE_S,
    sessions_dir=None,
    rollout_path=None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    progress_stream=None,
    record_telemetry: bool = True,
    telemetry_extra: Optional[Dict[str, Any]] = None,
    _stop_latch: Optional[_StopLatch] = None,
) -> WatchResult:
    """Run `argv` under the activity watchdog and return a `WatchResult`.

    `mode` is "codex" (stdout, stderr and rollout mtime are heartbeats, 300 s
    idle timeout) or "agy" (stdout growth only, and NO idle timeout -- agy is
    silent while it reasons, so the hard cap is its only stop). `effort` picks
    the codex hard cap and is required in codex mode unless `hard_cap_s` is
    given outright. `clock` and `sleep` are injected so a test can drive the
    REAL thresholds without spending real seconds. `progress_interval_s`,
    `poll_interval_s` and a caller-supplied `hard_cap_s` or `idle_timeout_s`
    must each be a finite number > 0 (CodexWatchError, before any spawn,
    otherwise); a None hard cap or idle timeout keeps its default meaning.

    `_stop_latch` is the CLI's plumbing (STOP SIGNALS in the module docstring):
    main() passes the latch its SIGTERM / SIGHUP handler feeds, and watch()
    arms it the instant the child exists. An in-process caller running watch() on
    a worker thread passes a `_StopLatch(record_only=True)` its own main thread
    feeds (#292); the poll loop raises that stop within one poll interval.

    `stdin_path` (#291 fix round 2, N2) feeds the child's stdin from a REGULAR FILE, which
    reaches EOF at its end, so a prompt too large for argv (MAX_ARG_STRLEN, E2BIG) can
    travel on stdin without breaking the STDIN RULE. None keeps stdin DEVNULL. A path
    that is not a regular file (a FIFO may never EOF) raises CodexWatchError before any
    spawn. The heartbeats, idle timeout and hard cap are unchanged.
    """
    if mode not in (MODE_CODEX, MODE_AGY):
        raise CodexWatchError(
            "unknown mode {0!r}; expected {1!r} or {2!r}".format(mode, MODE_CODEX, MODE_AGY)
        )

    tokens = tuple(str(t) for t in argv)
    if not tokens:
        raise CodexWatchError("argv is empty; nothing to watch")
    if mode == MODE_AGY:
        tokens = validate_agy_argv(tokens)

    if idle_timeout_s is None:
        # agy resolves to AGY_IDLE_TIMEOUT_S, which IS None: no idle timeout
        # applies in agy mode. A caller that has its own liveness signal may
        # still pass an explicit number.
        idle_timeout_s = AGY_IDLE_TIMEOUT_S if mode == MODE_AGY else IDLE_TIMEOUT_S
    else:
        # D21 fix round 2, R2-12b: a value the caller supplied. NaN or +inf
        # would switch the idle stop off; the None default above is never
        # checked, so agy keeps "no idle stop".
        idle_timeout_s = _checked_seconds("idle timeout", idle_timeout_s)
    if hard_cap_s is None:
        if mode == MODE_AGY:
            hard_cap_s = AGY_HARD_CAP_S
        else:
            if effort is None:
                raise CodexWatchError(
                    "codex mode needs an `effort` (for the hard cap) or an "
                    "explicit `hard_cap_s`"
                )
            hard_cap_s = hard_cap_for(effort)
    else:
        # D21 fix round 2, R2-12b: NaN or +inf would switch the runaway stop off.
        hard_cap_s = _checked_seconds("hard cap", hard_cap_s)
    if progress_interval_s is None:
        progress_interval_s = PROGRESS_INTERVAL_S
    progress_interval_s = _checked_seconds("progress interval", progress_interval_s)
    poll_interval_s = _checked_seconds("poll interval", poll_interval_s)

    stdout_path = Path(stdout_path)
    stderr_path = Path(stderr_path)
    for path in (stdout_path, stderr_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    rollout = Path(rollout_path) if rollout_path is not None else None
    sessions_root = Path(sessions_dir) if sessions_dir is not None else None
    stream = progress_stream if progress_stream is not None else sys.stderr

    latch = _stop_latch
    if latch is not None and latch.signum is not None:
        # D21 F9: a stop that landed before the spawn never starts the child.
        raise _StopSignal(latch.signum)

    max_silence = 0.0
    seen = {"stdout": 0, "stderr": 0, "rollout": 0}
    progress_lines: List[str] = []
    stop_reason = STOP_OK
    child_exit: Optional[int] = None

    def _activity() -> bool:
        """True when any heartbeat source moved since the last poll."""
        moved = False
        size_out = _size(stdout_path)
        if size_out > seen["stdout"]:
            seen["stdout"] = size_out
            moved = True
        if mode == MODE_CODEX:
            size_err = _size(stderr_path)
            if size_err > seen["stderr"]:
                seen["stderr"] = size_err
                moved = True
            stamp = _mtime_ns(rollout)
            if stamp > seen["rollout"]:
                seen["rollout"] = stamp
                moved = True
        return moved

    stdin_handle = _open_stdin(stdin_path)
    try:
        out_handle, err_handle = _open_streams(stdout_path, stderr_path)
    except BaseException:
        if stdin_handle is not None:
            stdin_handle.close()
        raise
    proc = None
    try:
        # D21 F9: the child is spawned INSIDE the try whose `finally` reaps, and
        # the stop latch is armed the instant Popen returns. A stop that landed
        # earlier -- even inside Popen, before `proc` was bound -- was held by
        # the latch and is raised by arm() HERE, where the reap is in force.
        proc = _spawn(tokens, out_handle, err_handle, stdin_handle)
        if latch is not None:
            latch.arm()

        started = clock()
        last_activity = started
        next_progress = started + progress_interval_s
        seen["stdout"] = _size(stdout_path)
        seen["stderr"] = _size(stderr_path)
        seen["rollout"] = _mtime_ns(rollout)

        while True:
            if latch is not None and latch.signum is not None:
                # #292: a record-only latch is fed from the main thread while this
                # loop runs in a worker; the stop is raised HERE, where `finally` reaps.
                raise _StopSignal(latch.signum)
            child_exit = proc.poll()
            now = clock()

            if _activity():
                max_silence = max(max_silence, now - last_activity)
                last_activity = now

            if child_exit is not None:
                # Final sweep: the child may have written between polls.
                if _activity():
                    last_activity = now
                max_silence = max(max_silence, now - last_activity)
                stop_reason = STOP_OK
                break

            if mode == MODE_CODEX and rollout is None:
                session_id = _find_session_id(stdout_path, stderr_path)
                if session_id:
                    root = sessions_root if sessions_root is not None else _default_sessions_dir()
                    found = _find_rollout(root, session_id)
                    if found is not None:
                        rollout = found
                        seen["rollout"] = _mtime_ns(rollout)

            silence = now - last_activity
            elapsed = now - started

            if now >= next_progress:
                line = (
                    "{0} alive: {1} s elapsed, last activity {2} s ago, model {3}".format(
                        mode, int(elapsed), int(silence), model or "unknown"
                    )
                )
                progress_lines.append(line)
                try:
                    stream.write(line + "\n")
                    stream.flush()
                except Exception:  # noqa: BLE001 - a broken stream never stops a call
                    # D21 fix round 2, N1: Exception, NEVER BaseException. Every
                    # way a progress stream FAILS is an Exception (a closed
                    # stream, a broken pipe, an unencodable console); every way
                    # a call is asked to STOP is not (_StopSignal,
                    # KeyboardInterrupt, SystemExit), and must reach the
                    # `finally` that reaps.
                    pass
                while now >= next_progress:
                    next_progress += progress_interval_s

            # `idle_timeout_s is None` means the mechanism does not apply (agy:
            # no liveness signal to read while it reasons). The hard cap below
            # is then the ONLY stop -- it is never skipped with it.
            if idle_timeout_s is not None and silence >= idle_timeout_s:
                max_silence = max(max_silence, silence)
                stop_reason = STOP_IDLE_TIMEOUT
                break
            if elapsed >= hard_cap_s:
                max_silence = max(max_silence, silence)
                stop_reason = STOP_HARD_CAP
                break

            sleep(poll_interval_s)

        if stop_reason != STOP_OK:
            child_exit = _terminate_and_reap(proc, reap_grace_s)
        elapsed_s = clock() - started
    finally:
        if latch is not None:
            # D21 F9: FIRST, and a plain attribute store rather than a call, so
            # no stop is raised from here on -- raised during the reap below, it
            # would abort it. A stop that lands now is held for main().
            latch.armed = False
        # Reap unconditionally: an exception on the way out must not orphan.
        try:
            if proc is not None and proc.poll() is None:
                _terminate_and_reap(proc, reap_grace_s)
        except BaseException:  # noqa: BLE001
            pass
        out_handle.close()
        err_handle.close()
        if stdin_handle is not None:
            stdin_handle.close()

    if stop_reason == STOP_OK:
        exit_code = child_exit if child_exit is not None else 0
    elif stop_reason == STOP_IDLE_TIMEOUT:
        exit_code = EXIT_IDLE_TIMEOUT
    else:
        exit_code = EXIT_HARD_CAP

    result = WatchResult(
        stop_reason=stop_reason,
        exit_code=exit_code,
        child_exit_code=child_exit,
        elapsed_s=elapsed_s,
        max_silence_s=max_silence,
        mode=mode,
        argv=tokens,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        idle_timeout_s=None if idle_timeout_s is None else float(idle_timeout_s),
        hard_cap_s=float(hard_cap_s),
        rollout_path=rollout,
        model=model,
        progress_lines=tuple(progress_lines),
    )
    if record_telemetry:
        _record_telemetry(result, telemetry_extra)
    return result


def codex_watch(argv: Sequence[str], *, effort: str, **kwargs) -> WatchResult:
    """`watch()` in codex mode. `effort` selects the hard cap."""
    kwargs.pop("mode", None)
    return watch(argv, mode=MODE_CODEX, effort=effort, **kwargs)


def agy_watch(argv: Sequence[str], **kwargs) -> WatchResult:
    """`watch()` in agy mode: stdout-only heartbeat, NO idle timeout, 900 s cap
    as the only stop, argv rules enforced before the spawn."""
    kwargs.pop("mode", None)
    kwargs.pop("effort", None)
    return watch(argv, mode=MODE_AGY, **kwargs)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex_watch.py",
        description=(
            "Run a codex or agy call under the activity watchdog. Exit: the "
            "child's own code on a normal finish, {0} on idle timeout, {1} on "
            "hard cap.".format(EXIT_IDLE_TIMEOUT, EXIT_HARD_CAP)
        ),
    )
    parser.add_argument("--mode", choices=(MODE_CODEX, MODE_AGY), default=MODE_CODEX)
    parser.add_argument("--effort", default=None, help="codex effort tier (picks the hard cap)")
    parser.add_argument("--model", default=None, help="model name, for the progress line")
    parser.add_argument("--stdout-file", required=True)
    parser.add_argument("--stderr-file", required=True)
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=None,
        help=(
            "seconds of silence that stop the call, a finite number > 0; omit "
            "for the mode default ({0} s in codex mode, NONE in agy mode -- agy "
            "has no liveness signal while it reasons)".format(IDLE_TIMEOUT_S)
        ),
    )
    parser.add_argument(
        "--hard-cap",
        type=float,
        default=None,
        help=(
            "runaway cap in seconds, a finite number > 0; omit for the effort's "
            "own cap (codex) or {0} s (agy)".format(AGY_HARD_CAP_S)
        ),
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=None,
        help="seconds between progress lines, a finite number > 0 (default {0})".format(
            PROGRESS_INTERVAL_S
        ),
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=_DEFAULT_POLL_INTERVAL_S,
        help="seconds between heartbeat polls, a finite number > 0 (default {0})".format(
            _DEFAULT_POLL_INTERVAL_S
        ),
    )
    parser.add_argument("--json", action="store_true", help="print the result row on stdout")
    parser.add_argument("--no-telemetry", action="store_true")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="the command to run, after `--` (e.g. -- codex exec -m ... 'prompt')",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("codex_watch.py: error: no command given after `--`", file=sys.stderr)
        return 2
    # D21 F9: SIGTERM / SIGHUP stop the call through the latch, so the child is
    # reaped before this process exits 128+N. Held for the call only.
    latch = _StopLatch()
    previous = _install_stop_handlers(latch)
    try:
        try:
            result = watch(
                command,
                mode=args.mode,
                effort=args.effort,
                model=args.model,
                stdout_path=Path(args.stdout_file),
                stderr_path=Path(args.stderr_file),
                idle_timeout_s=args.idle_timeout,
                hard_cap_s=args.hard_cap,
                progress_interval_s=args.progress_interval,
                poll_interval_s=args.poll_interval,
                record_telemetry=not args.no_telemetry,
                _stop_latch=latch,
            )
        except CodexWatchError as exc:
            print("codex_watch.py: error: {0}".format(exc), file=sys.stderr)
            return 2
        except _StopSignal as stop:
            return 128 + stop.signum
        if latch.signum is not None:
            # The stop landed after the child was reaped (while telemetry was
            # written): nothing was orphaned, but the caller asked us to stop.
            return 128 + latch.signum
        if args.json:
            print(json.dumps(telemetry_row(result), sort_keys=True, separators=(",", ":")))
        return result.exit_code
    finally:
        _restore_stop_handlers(previous)


if __name__ == "__main__":
    from portable_cli import run_cli  # noqa: E402  (#251 stream hardening)

    sys.exit(run_cli(main))
