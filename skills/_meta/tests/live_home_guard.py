#!/usr/bin/env python3
"""live_home_guard.py - fail any test that writes the REAL home's live model state (#282 H2).

Test-only (stdlib + pytest). The suite-level guard the #282 spec asks for under "Live-HOME tests",
implemented per plan interpretation K23, plus the isolation helpers the guarded tests use.

PROTECTED SET. Under the real home R - Path.home() when the first guarded suite's conftest.py is
IMPORTED, i.e. before collection:

  R/.claude/state/seat-model-*.json            (the freeze pins and the tops record) + `.lock` sidecars
  R/.claude/projects/*/astra-budget.jsonl      (every project's astra budget store)  + `.lock` sidecars

including the CREATION of a new match (a pytest / tmp slug store above all). A developer run under
the real HOME protects ~/.claude; the temp-HOME runner protects that temp HOME; a "sentinel home"
(a temp HOME seeded with a codex roster) therefore sees exactly the writes a developer run would make.

TWO ARMS, per test (setup + call + teardown) and per collector (collection), plus one whole-session
comparison (conftest import -> session finish):

  (i)  AUDIT. One sys.addaudithook hook sees, in THIS interpreter, every `open` whose flags or mode
       ask for write / append / create / truncate, and the DESTINATION of os.rename / os.replace.
       On a protected path it records the event and the path.
  (ii) STAT. An (inode, size, mtime_ns) snapshot of the protected set is taken when a window opens
       and compared when it reports. It catches child processes, deletions, and anything arm (i)
       cannot see.

MODES - `--live-home-guard=report|enforce`, default enforce:

  enforce  arm (i) also raises PermissionError at the write, so this interpreter never reaches the
           live file; a violation FAILS the test (its call report, else its teardown report) or the
           collector (a collection error); a violation outside every window turns a green session
           exit status red. The terminal summary lists every violation.
  report   records only - nothing raised, no outcome changed. The terminal summary is the inventory.

The guard opens nothing for writing: it never writes, deletes or restores a protected file. Every
message it prints is ASCII.

HONEST LIMITS.
  * Arm (ii) observes the host: a CONCURRENT live writer (another project's session admitting into its
    own store while a suite runs under the real HOME) trips it for whichever test is running. Re-run
    the named test alone to confirm.
  * Arm (i) sees only this interpreter. A child's write is seen only as a stat change, and a write
    that preserves inode, size and mtime_ns is invisible. An os.open relative to a dir_fd is resolved
    against the cwd.
  * An audit hook cannot be removed: after the session it stays installed but inert.

ISOLATION HELPERS for the tests that reach seat_model / codex_quota / convene (spec H2): the
`empty_live_home` fixture (per test) and `empty_home()` / `import_under_empty_home()` /
`import_audit_spawn()` (module-level imports) give an EMPTY temp HOME (HOME and USERPROFILE) and a
directory holding a stub `codex` PREPENDED to PATH - never a bare PATH, because shutil.which must
still find codex or every codex seat substitutes. Each asserts that Path.home() is not the real home.
A module-level import moves ONLY the module's own import-time work under the empty HOME: its
dependencies are imported first under the session HOME, so their module-level home bindings (for
example codex_model.MODELS_CACHE_PATH) do not silently point at a deleted temp dir.

WIRING. skills/{_meta,avengers,forge}/tests/conftest.py load this file BY PATH under the fixed module
name MODULE_NAME, so one session collecting several suites shares one module, one hook and one plugin.
They call capture() at import, addoption() from pytest_addoption and register() from
pytest_configure, and re-export the `empty_live_home` fixture.
"""
from __future__ import annotations

import contextlib
import errno
import fnmatch
import importlib
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple

import pytest

MODULE_NAME = "foundry_live_home_guard"
PLUGIN_NAME = "foundry-live-home-guard"
OPTION = "--live-home-guard"
OPTION_DEST = "live_home_guard"
MODES = ("report", "enforce")
DEFAULT_MODE = "enforce"

#: Basename patterns inside R/.claude/state (matched case-normalised).
STATE_PATTERNS = ("seat-model-*.json", "seat-model-*.json.lock",
                  # #322 fix round 1: codex_quota's account-wide exhausted-until record.
                  "codex-exhausted.json", "codex-exhausted.json.lock",
                  # #322 fix round 2 (item 10): the await lock/result, the notification claim and the
                  # timed-out marker moved here, account-wide, beside the exhausted record.
                  "codex-await-reset.lock", "codex-await-reset.json",
                  "codex-notify-wave.json", "codex-notify-wave.json.lock", "codex-await-timeout.json")
#: Basenames inside R/.claude/projects/<slug>.
BUDGET_NAMES = ("astra-budget.jsonl", "astra-budget.jsonl.lock",
                # #322 fix round 1: the per-project await-reset lock/result and notification wave.
                "codex-await-reset.lock", "codex-await-reset.json",
                "codex-notify-wave.json", "codex-notify-wave.json.lock")

#: CPython raises "os.rename" for BOTH os.rename and os.replace (verified on 3.13); "os.replace" is
#: listed as well so an interpreter that splits them is still covered.
AUDIT_EVENTS = frozenset({"open", "os.rename", "os.replace"})
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_WRITE_MODE_CHARS = frozenset("wax+")

ARM_AUDIT = "audit"
ARM_STAT = "stat"
OWNER_SESSION = "session"
COLLECT_PREFIX = "collect:"

#: A protected file's stat signature: (st_ino, st_size, st_mtime_ns).
Signature = Tuple[int, int, int]

_HOME_VARS = ("HOME", "USERPROFILE")
#: The skills tree this file lives in (skills/_meta/tests/live_home_guard.py).
_SKILLS_ROOT = Path(__file__).resolve().parents[2]
_STUB_CODEX_SH = (
    "#!/bin/sh\n"
    "# stub codex (#282 live-HOME isolation): on PATH so shutil.which finds codex; never a model call\n"
    "echo 'stub codex (live-HOME isolation): no model call from a test' >&2\n"
    "exit 2\n"
)
_STUB_CODEX_CMD = (
    "@echo off\r\n"
    "echo stub codex (live-HOME isolation): no model call from a test 1>&2\r\n"
    "exit /b 2\r\n"
)


def _ascii(text: Any) -> str:
    return str(text).encode("ascii", "backslashreplace").decode("ascii")


class Violation(NamedTuple):
    """One observed write to the protected set."""

    owner: str   # a test node id, "collect:<collector node id>", or "session"
    arm: str     # ARM_AUDIT | ARM_STAT
    event: str   # "open(mode='w', flags=0x241)", "os.rename destination", "created", "modified", "deleted"
    path: str

    def line(self) -> str:
        return _ascii(f"{self.owner} | arm {self.arm} | {self.event} | {self.path}")


class StatChange(NamedTuple):
    change: str                    # "created" | "modified" | "deleted"
    path: str
    before: Optional[Signature]
    after: Optional[Signature]


def _fspath(path: Any) -> Optional[str]:
    """A path-like audit argument as text; None for a file descriptor or anything unusable."""
    if path is None or isinstance(path, (int, bool)):
        return None
    try:
        value = os.fspath(path)
    except TypeError:
        return None
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    return value or None


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _real_key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _write_intent(mode: Any, flags: Any) -> bool:
    if isinstance(flags, int) and not isinstance(flags, bool) and flags & _WRITE_FLAGS:
        return True
    return isinstance(mode, str) and any(ch in _WRITE_MODE_CHARS for ch in mode)


def _listdir(path: str) -> List[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


class LiveHomeGuard:
    """The check API: which paths are protected, the arm (i) decision for one audit event, and the
    arm (ii) snapshot / comparison. Pure apart from reading directory listings and stat results -
    it records nothing, raises nothing and writes nothing."""

    def __init__(self, real_home: Any) -> None:
        home = os.path.abspath(os.fspath(real_home))
        self.real_home = home
        self.state_dir = os.path.join(home, ".claude", "state")
        self.projects_dir = os.path.join(home, ".claude", "projects")
        self._state_keys = {_key(self.state_dir), _real_key(self.state_dir)}
        self._projects_keys = {_key(self.projects_dir), _real_key(self.projects_dir)}

    def is_protected(self, path: Any) -> bool:
        text = _fspath(path)
        if text is None:
            return False
        absolute = os.path.abspath(text)
        name = os.path.normcase(os.path.basename(absolute))
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in STATE_PATTERNS):
            parent = os.path.dirname(absolute)
            return bool({_key(parent), _real_key(parent)} & self._state_keys)
        if name in BUDGET_NAMES:
            grandparent = os.path.dirname(os.path.dirname(absolute))
            return bool({_key(grandparent), _real_key(grandparent)} & self._projects_keys)
        return False

    def check_audit(self, event: str, args: Tuple[Any, ...]) -> Optional[Tuple[str, str]]:
        """Arm (i) for one audit event: (event label, absolute path) when it writes, creates or
        replaces a protected file; None otherwise (a read, an fd, an unprotected path)."""
        if event == "open":
            if len(args) < 3:
                return None
            path, mode, flags = args[0], args[1], args[2]
            if not _write_intent(mode, flags):
                return None
            if isinstance(flags, int) and not isinstance(flags, bool):
                label = f"open(mode={mode!a}, flags={flags:#x})"
            else:
                label = f"open(mode={mode!a})"
        elif event in ("os.rename", "os.replace"):
            if len(args) < 2:
                return None
            path, label = args[1], f"{event} destination"
        else:
            return None
        text = _fspath(path)
        if text is None or not self.is_protected(text):
            return None
        return label, os.path.abspath(text)

    def snapshot(self) -> Dict[str, Signature]:
        """Arm (ii): every protected file that exists now -> (inode, size, mtime_ns)."""
        found: Dict[str, Signature] = {}
        for name in _listdir(self.state_dir):
            if any(fnmatch.fnmatchcase(os.path.normcase(name), pattern) for pattern in STATE_PATTERNS):
                self._stat_into(found, os.path.join(self.state_dir, name))
        for slug in _listdir(self.projects_dir):
            for name in BUDGET_NAMES:
                self._stat_into(found, os.path.join(self.projects_dir, slug, name))
        return found

    @staticmethod
    def _stat_into(found: Dict[str, Signature], path: str) -> None:
        try:
            st = os.stat(path)
        except OSError:
            return
        found[path] = (st.st_ino, st.st_size, st.st_mtime_ns)

    @staticmethod
    def compare(before: Dict[str, Signature], after: Dict[str, Signature]) -> List[StatChange]:
        """Arm (ii): the differences between two snapshots, sorted by path."""
        changes: List[StatChange] = []
        for path in sorted(set(before) | set(after)):
            old, new = before.get(path), after.get(path)
            if old == new:
                continue
            kind = "created" if old is None else "deleted" if new is None else "modified"
            changes.append(StatChange(kind, path, old, new))
        return changes


class _Runtime:
    """One guarded session's mutable state. The live session uses the module-level _RT; tests of the
    dispatch logic build their own instance, so they never touch the running session's guard."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.local = threading.local()
        self.active = False
        self.guard: Optional[LiveHomeGuard] = None
        self.mode: Optional[str] = None     # None until register(): record, never raise
        self.baseline: Dict[str, Signature] = {}
        self.registrants: List[str] = []
        self.frames: List[Dict[str, Any]] = []
        self.pending: List[Violation] = []      # arm (i) events not yet collected by a window
        self.recorded: List[Violation] = []     # every violation, for the terminal summary
        self.unreported: List[Violation] = []   # recorded but applied to no report (a window's close)
        self.explained: Dict[str, Optional[Signature]] = {}

    def start(self, real_home: Any) -> None:
        with self.lock:
            self.guard = LiveHomeGuard(real_home)
            self.baseline = self.guard.snapshot()
            self.mode = None
            self.registrants = []
            self.frames = []
            self.pending = []
            self.recorded = []
            self.unreported = []
            self.explained = {}
            self.active = True

    def stop(self) -> None:
        with self.lock:
            self.active = False
            self.frames = []

    def owner(self) -> str:
        frames = self.frames
        return frames[-1]["owner"] if frames else OWNER_SESSION


def dispatch_audit(rt: _Runtime, event: str, args: Tuple[Any, ...]) -> None:
    """Arm (i) for one audit event against a runtime: record a violation and, in enforce mode, refuse
    the operation with PermissionError. Never raises anything else."""
    if event not in AUDIT_EVENTS or not rt.active or getattr(rt.local, "busy", False):
        return
    rt.local.busy = True
    try:
        guard = rt.guard
        hit = guard.check_audit(event, args) if guard is not None else None
        if hit is None:
            return
        violation = Violation(rt.owner(), ARM_AUDIT, hit[0], hit[1])
        with rt.lock:
            rt.pending.append(violation)
        refuse = rt.mode == "enforce"
    except Exception:
        return  # a guard defect must not break the code under test; arm (ii) still observes
    finally:
        rt.local.busy = False
    if refuse:
        raise PermissionError(
            errno.EACCES,
            _ascii(f"live-home-guard: {violation.event} on a protected real-home path is refused (#282)"),
            violation.path)


def open_window(rt: _Runtime, owner: str) -> Dict[str, Any]:
    with rt.lock:
        frame = {"owner": owner, "before": rt.guard.snapshot() if rt.guard else {}, "reported": {}}
        rt.frames.append(frame)
    return frame


def close_window(rt: _Runtime, frame: Dict[str, Any]) -> List[Violation]:
    """Report what the window has not reported yet, then close it."""
    found = window_violations(rt, frame)
    with rt.lock:
        if frame in rt.frames:
            rt.frames.remove(frame)
    return found


def window_violations(rt: _Runtime, frame: Dict[str, Any]) -> List[Violation]:
    """The window's not-yet-reported violations: its arm (i) events plus the stat changes since the
    window opened. A stat change is reported once, by the innermost window that sees it."""
    with rt.lock:
        owner = frame["owner"]
        found = [v for v in rt.pending if v.owner == owner]
        rt.pending = [v for v in rt.pending if v.owner != owner]
        if rt.guard is not None:
            for change in LiveHomeGuard.compare(frame["before"], rt.guard.snapshot()):
                if change.path in frame["reported"] and frame["reported"][change.path] == change.after:
                    continue
                found.append(Violation(owner, ARM_STAT, change.change, change.path))
                for open_frame in rt.frames:
                    open_frame["reported"][change.path] = change.after
                frame["reported"][change.path] = change.after
                rt.explained[change.path] = change.after
        rt.recorded.extend(found)
    return found


def session_violations(rt: _Runtime) -> List[Violation]:
    """Everything outside every window: unattributed arm (i) events and the stat changes since
    capture that no window explained."""
    with rt.lock:
        found = [Violation(OWNER_SESSION, v.arm, v.event, v.path) if v.owner != OWNER_SESSION else v
                 for v in rt.pending]
        rt.pending = []
        if rt.guard is not None:
            for change in LiveHomeGuard.compare(rt.baseline, rt.guard.snapshot()):
                if change.path in rt.explained and rt.explained[change.path] == change.after:
                    continue
                found.append(Violation(OWNER_SESSION, ARM_STAT, change.change, change.path))
                rt.explained[change.path] = change.after
        rt.recorded.extend(found)
    return found


def failure_text(found: List[Violation]) -> str:
    lines = ["live-home-guard: this wrote the REAL home's protected model state "
             "(seat-model-*.json / astra-budget.jsonl); run it under an empty temp HOME (#282):"]
    lines.extend("  " + v.line() for v in found)
    return "\n".join(lines)


def _fail_report(report: Any, found: List[Violation]) -> None:
    text = failure_text(found)
    if report.outcome == "failed" and report.longrepr is not None:
        text = f"{report.longrepr}\n\n{text}"
    report.outcome = "failed"
    report.longrepr = text
    if hasattr(report, "wasxfail"):
        del report.wasxfail


_RT = _Runtime()
_HOOK_INSTALLED = [False]


def _audit_hook(event: str, args: Tuple[Any, ...]) -> None:
    if event in AUDIT_EVENTS:
        dispatch_audit(_RT, event, args)


class _GuardPlugin:
    """The pytest plugin (registered once per session by register())."""

    def __init__(self, rt: _Runtime) -> None:
        self.rt = rt

    def pytest_report_header(self, config: Any) -> List[str]:
        rt = self.rt
        home = rt.guard.real_home if rt.guard else "?"
        return [_ascii(f"live-home-guard: {rt.mode} (real home {home!a}; registered by "
                       f"{', '.join(rt.registrants) or '?'})")]

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_make_collect_report(self, collector: Any) -> Iterator[None]:
        rt = self.rt
        frame = open_window(rt, COLLECT_PREFIX + (collector.nodeid or "<session>"))
        outcome = yield
        found = close_window(rt, frame)
        if not found or rt.mode != "enforce":
            return
        try:
            report = outcome.get_result()
        except BaseException:
            with rt.lock:
                rt.unreported.extend(found)
            return
        _fail_report(report, found)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item: Any, nextitem: Any) -> Iterator[None]:
        rt = self.rt
        frame = open_window(rt, item.nodeid)
        try:
            yield
        finally:
            # Anything after the teardown report is recorded and fails the session instead.
            leftover = close_window(rt, frame)
            with rt.lock:
                rt.unreported.extend(leftover)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: Any, call: Any) -> Iterator[None]:
        outcome = yield
        if call.when not in ("call", "teardown"):
            return
        rt = self.rt
        frame = next((f for f in reversed(rt.frames) if f["owner"] == item.nodeid), None)
        if frame is None:
            return
        found = window_violations(rt, frame)
        if not found or rt.mode != "enforce":
            return
        try:
            report = outcome.get_result()
        except BaseException:
            with rt.lock:
                rt.unreported.extend(found)
            return
        _fail_report(report, found)

    def pytest_sessionfinish(self, session: Any, exitstatus: Any) -> None:
        rt = self.rt
        found = session_violations(rt) + list(rt.unreported)
        if found and rt.mode == "enforce" and int(session.exitstatus) in (0, 5):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter: Any, exitstatus: Any, config: Any) -> None:
        rt = self.rt
        home = rt.guard.real_home if rt.guard else "?"
        terminalreporter.write_sep("-", "live-home-guard")
        terminalreporter.write_line(_ascii(
            f"live-home-guard: {rt.mode}; real home {home!a}; registered by "
            f"{', '.join(rt.registrants) or '?'}; {len(rt.recorded)} violation(s)"))
        for violation in rt.recorded:
            terminalreporter.write_line("  " + violation.line())

    def pytest_unconfigure(self, config: Any) -> None:
        self.rt.stop()


# --------------------------------------------------------------------------- #
# conftest glue
# --------------------------------------------------------------------------- #
def _registrant(conftest_file: Any) -> str:
    here = Path(os.path.abspath(os.fspath(conftest_file))).parent
    return f"{here.parent.name}/{here.name}"


def capture(conftest_file: Any) -> LiveHomeGuard:
    """Called when a guarded conftest is IMPORTED. The first call of a session captures the real home
    (Path.home() now, before collection), takes the session baseline and installs the audit hook;
    later calls only add the registrant."""
    with _RT.lock:
        if not _RT.active:
            _RT.start(Path.home())
        name = _registrant(conftest_file)
        if name not in _RT.registrants:
            _RT.registrants.append(name)
        if not _HOOK_INSTALLED[0]:
            sys.addaudithook(_audit_hook)
            _HOOK_INSTALLED[0] = True
        return _RT.guard  # type: ignore[return-value]


def addoption(parser: Any) -> None:
    try:
        parser.addoption(
            OPTION, action="store", dest=OPTION_DEST, default=None, choices=MODES,
            help=("live-HOME guard (#282): 'enforce' (default) fails any test or collector that writes "
                  "the real home's seat-model-*.json or astra-budget.jsonl; 'report' only lists them."))
    except ValueError:
        pass  # another guarded suite's conftest added it first


def register(config: Any, conftest_file: Any) -> _GuardPlugin:
    capture(conftest_file)
    manager = config.pluginmanager
    plugin = manager.get_plugin(PLUGIN_NAME)
    if plugin is None:
        mode = config.getoption(OPTION_DEST, default=None) or DEFAULT_MODE
        if mode not in MODES:
            raise pytest.UsageError(f"{OPTION} must be one of {', '.join(MODES)}, got {mode!a}")
        _RT.mode = mode
        plugin = _GuardPlugin(_RT)
        manager.register(plugin, PLUGIN_NAME)
    return plugin


def runtime() -> _Runtime:
    """The live session's runtime (read-only use: mode, real home, registrants)."""
    return _RT


# --------------------------------------------------------------------------- #
# Isolation helpers
# --------------------------------------------------------------------------- #
def real_home() -> Path:
    """The guard's captured real home; Path.home() now when no guarded session is active."""
    guard = _RT.guard if _RT.active else None
    return Path(guard.real_home if guard is not None else os.path.abspath(Path.home()))


def assert_not_real_home(real: Optional[Path] = None) -> None:
    """Assert Path.home() is not the real home. Pass `real` when HOME has already been swapped outside
    a guarded session (real_home() then falls back to Path.home() NOW)."""
    now, real_key = _real_key(str(Path.home())), _real_key(str(real if real is not None else real_home()))
    assert now != real_key, _ascii(
        f"live-HOME isolation failed: Path.home() is still the real home {real_key!a}")


def write_stub_codex(bin_dir: Path) -> Path:
    """A directory holding a stub `codex` (exit 2, stderr note) for PATH lookups; returns the stub."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "codex"
    stub.write_text(_STUB_CODEX_SH, encoding="utf-8", newline="\n")
    stub.chmod(0o755)
    if os.name == "nt":
        (bin_dir / "codex.cmd").write_text(_STUB_CODEX_CMD, encoding="utf-8", newline="")
    return stub


def _prepended_path(bin_dir: Path) -> str:
    current = os.environ.get("PATH", "")
    return str(bin_dir) + (os.pathsep + current if current else "")


@contextlib.contextmanager
def empty_home(prefix: str = "live-home-empty-") -> Iterator[Path]:
    """An EMPTY temp HOME + a stub codex PREPENDED to PATH for the block; restores the environment
    and removes the temp tree afterwards."""
    real = real_home()  # before HOME moves
    base = Path(tempfile.mkdtemp(prefix=prefix))
    saved = {var: os.environ.get(var) for var in _HOME_VARS + ("PATH",)}
    try:
        home = base / "home"
        home.mkdir()
        bin_dir = base / "bin"
        write_stub_codex(bin_dir)
        os.environ["PATH"] = _prepended_path(bin_dir)
        for var in _HOME_VARS:
            os.environ[var] = str(home)
        assert_not_real_home(real)
        yield home
    finally:
        for var, value in saved.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
        shutil.rmtree(base, ignore_errors=True)


def _in_skills_tree(module: Any) -> bool:
    location = getattr(module, "__file__", None)
    if not location:
        return False
    try:
        Path(os.path.realpath(location)).relative_to(os.path.realpath(str(_SKILLS_ROOT)))
    except ValueError:
        return False
    return True


def import_under_empty_home(name: str, preload: Tuple[str, ...] = ()) -> Any:
    """Import `name` - a module whose import itself resolves seat models - under empty_home().

    Its skills-tree dependencies in `preload` are imported FIRST, under the CURRENT HOME, so their
    module-level home bindings (codex_model.MODELS_CACHE_PATH, trusted_runner.DEFAULT_INVENTORY_PATH,
    write.GLOBAL_ROLLUP_PATH, ...) are exactly what a plain import gives them: only `name`'s own
    import-time work runs under the empty HOME. A dependency that cannot be imported is skipped (it
    binds nothing). Any OTHER skills-tree module first imported inside the empty-HOME window raises
    ImportError naming it - add it to `preload` - because it would otherwise stay bound, for the rest
    of the process, to a temp HOME that no longer exists. A cached `name` is returned as is."""
    for dependency in preload:
        try:
            importlib.import_module(dependency)
        except ImportError:
            pass
    if name in sys.modules:
        return sys.modules[name]
    before = set(sys.modules)
    with empty_home(prefix="live-home-import-"):
        module = importlib.import_module(name)
    strays = sorted(m for m in set(sys.modules) - before - {name} if _in_skills_tree(sys.modules.get(m)))
    if strays:
        raise ImportError(_ascii(
            f"import_under_empty_home({name!a}) first-imported {strays} under the empty temp HOME; "
            f"pass them in preload= so their module-level home bindings keep the session HOME"))
    return module


#: audit_spawn's skills-tree imports, verified by diffing sys.modules around `import audit_spawn`
#: (2026-09-15; re-diffed 2026-09-16). import_under_empty_home() raises if this list goes stale.
#: `codex_watch` joined the set in S081 revision 4 (WP-A03, D24), when the codex arm moved off
#: `subprocess.run` onto the activity watchdog. It binds NOTHING at module level (no expanduser,
#: no Path.home, no environ, no gettempdir — its sessions dir is resolved per call), so this
#: entry changes no binding; it is here because the guard fails closed on ANY skills-tree module
#: first imported inside the empty-HOME window, which is what keeps this list honest.
AUDIT_SPAWN_PRELOAD = ("portable_lock", "codex_model", "codex_quota", "codex_watch", "seat_model",
                       "spawn_usage", "trusted_runner", "write", "spawn_runs")


def import_audit_spawn() -> Any:
    """audit_spawn for tests that never read its pins (#282 H2): its dependencies under the session
    HOME, audit_spawn itself - whose import resolves both reviewer pins and, with a codex roster
    present, records a TOP into seat-model-tops.json - under empty_home(). sys.path gets skills/_meta
    and skills/process-observation/scripts exactly as audit_spawn adds them."""
    for path in (_SKILLS_ROOT / "_meta", _SKILLS_ROOT / "process-observation" / "scripts"):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return import_under_empty_home("audit_spawn", preload=AUDIT_SPAWN_PRELOAD)


@pytest.fixture
def empty_live_home(tmp_path_factory: Any, monkeypatch: Any) -> Path:
    """Per test: an EMPTY temp HOME (HOME, USERPROFILE) + a stub codex PREPENDED to PATH - the
    fixture_home pattern of test_codex_quota.py. Kept outside tmp_path so a test's own tmp tree is
    untouched."""
    real = real_home()  # before HOME moves
    base = tmp_path_factory.mktemp("live-home")
    home = base / "home"
    home.mkdir()
    bin_dir = base / "bin"
    write_stub_codex(bin_dir)
    monkeypatch.setenv("PATH", _prepended_path(bin_dir))
    for var in _HOME_VARS:
        monkeypatch.setenv(var, str(home))
    assert_not_real_home(real)
    return home
