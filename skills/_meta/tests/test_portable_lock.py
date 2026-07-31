#!/usr/bin/env python3
"""Tests for portable_lock (#249).

Two halves, deliberately unequal in the evidence they provide:

  POSIX  -- tested against REAL cross-process contention. A subprocess takes the
            lock and holds it; the test observes what this process then sees.
            Nothing is mocked, so a passing test means the lock locks.

  WINDOWS -- tested against an INJECTED FAKE msvcrt, because no Windows machine
            has run this. These tests pin the call sequence, the byte count, the
            seek discipline and the retry loop. They CANNOT prove the lock
            excludes anything on Windows -- only that we call the API the way
            its contract requires. Said plainly here so nobody reads a green
            suite as Windows verification.
"""

from __future__ import annotations

import errno
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import portable_lock as pl  # noqa: E402
import portability_lint as lint  # noqa: E402

META = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the POSIX half needs flock; the Windows half fakes msvcrt anyway",
)


# ---------------------------------------------------------------------------
# The property that made this module necessary
# ---------------------------------------------------------------------------

def test_module_is_importable_with_no_platform_module_available():
    """#249 in one assertion: the module must survive on a host with neither
    fcntl nor msvcrt importable, because import-time death is the whole defect."""
    src = textwrap.dedent(f"""
        import sys, importlib
        class Blocker:
            def find_module(self, name, path=None):
                if name in ("fcntl", "msvcrt"):
                    raise ImportError("simulated: platform module absent")
                return None
        sys.meta_path.insert(0, Blocker())
        sys.path.insert(0, {str(META)!r})
        importlib.import_module("portable_lock")
        print("imported")
    """)
    out = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "imported" in out.stdout


def test_portable_lock_lints_clean():
    """Its own platform imports must satisfy the rule it exists to serve."""
    assert lint.check_path(META / "portable_lock.py") == []


# The ten modules #249 named. Kept as data so a new one is added here, not just
# fixed quietly -- the list IS the inventory the lint's P001 count agrees with.
SPINE = [
    ("_meta", "claims"),                              # bob's ledger claims
    ("_meta", "workflow_dispatch"),
    ("_meta", "apply_project_hard_rules"),
    ("wiring-reconcile/scripts", "promote"),          # sole writer of .wiring/latest.json
    ("process-observation/scripts", "write"),         # all telemetry
    ("project-documentation/scripts", "rotate"),
    ("legacy-code-intel/scripts", "store"),
    ("avengers/scripts", "memory_writeback"),
    ("structure-recovery/scripts", "run_state"),
    ("smart-config/scripts", "model_policy"),         # the 1 latent, not import-fatal
]


@pytest.mark.parametrize("subdir,module", SPINE, ids=[m for _, m in SPINE])
def test_the_whole_spine_imports_with_fcntl_absent(subdir, module):
    """#249's actual claim, tested the only way Linux can test it.

    A meta_path hook makes `import fcntl` raise, which is what a Windows host looks
    like from Python's point of view. Before the adapter, nine of these raised
    ModuleNotFoundError HERE -- at import, before any code ran -- and claims.py being
    among them is the whole reason bob could not execute on Windows in any host.

    This is a stronger guard than the P001 lint count: the lint reads the source, this
    executes it, so it also catches an import that is guarded at the top and then used
    unconditionally further down.
    """
    src = textwrap.dedent(f"""
        import sys, importlib
        class Blocker:
            def find_module(self, name, path=None):
                if name == "fcntl":
                    raise ImportError("simulated Windows: fcntl does not exist")
                return None
        sys.meta_path.insert(0, Blocker())
        sys.path.insert(0, {str(META.parent / subdir)!r})
        importlib.import_module({module!r})
    """)
    out = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    assert out.returncode == 0, (
        f"{subdir}/{module}.py does not import without fcntl -- #249 regressed:\n"
        f"{out.stderr}")


# ---------------------------------------------------------------------------
# POSIX -- real contention, real processes
# ---------------------------------------------------------------------------

_HOLDER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[1])
    import portable_lock as pl
    fh = open(sys.argv[2], "a+")
    pl.lock_exclusive(fh)
    print("held", flush=True)
    time.sleep(float(sys.argv[3]))
""")


def _spawn_holder(lock_path: Path, hold_for: float) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(META), str(lock_path), str(hold_for)],
        stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"  # lock is genuinely taken
    return proc


def test_nonblocking_acquire_raises_when_another_process_holds_it(tmp_path):
    lock = tmp_path / "contended.lock"
    proc = _spawn_holder(lock, 5)
    try:
        with open(lock, "a+") as fh:
            with pytest.raises(BlockingIOError):
                pl.lock_exclusive(fh, blocking=False)
    finally:
        proc.kill()
        proc.wait()


def test_lock_is_released_when_the_holding_process_DIES(tmp_path):
    """The property that decided the design over os.mkdir locking. If this ever
    fails, the adapter has stopped being the right choice."""
    lock = tmp_path / "dies.lock"
    proc = _spawn_holder(lock, 60)
    proc.kill()
    proc.wait()
    with open(lock, "a+") as fh:
        pl.lock_exclusive(fh, blocking=False)  # no exception == released
        pl.unlock(fh)


def test_blocking_acquire_waits_for_the_holder_and_then_succeeds(tmp_path):
    lock = tmp_path / "waits.lock"
    proc = _spawn_holder(lock, 1.0)
    try:
        started = time.monotonic()
        with open(lock, "a+") as fh:
            pl.lock_exclusive(fh, blocking=True)
            waited = time.monotonic() - started
            pl.unlock(fh)
        assert waited >= 0.5, f"returned in {waited:.2f}s -- it did not actually wait"
    finally:
        proc.kill()
        proc.wait()


def test_blocking_with_a_timeout_raises_LockTimeout_and_honours_the_deadline(tmp_path):
    lock = tmp_path / "timeout.lock"
    proc = _spawn_holder(lock, 10)
    try:
        started = time.monotonic()
        with open(lock, "a+") as fh:
            with pytest.raises(pl.LockTimeout):
                pl.lock_exclusive(fh, blocking=True, timeout=0.3)
        elapsed = time.monotonic() - started
        assert 0.25 <= elapsed < 3.0, f"timeout ignored or overshot: {elapsed:.2f}s"
    finally:
        proc.kill()
        proc.wait()


def test_LockTimeout_is_catchable_as_BlockingIOError_and_as_OSError(tmp_path):
    """Existing call sites catch OSError. The new type must not slip past them."""
    assert issubclass(pl.LockTimeout, BlockingIOError)
    assert issubclass(pl.LockTimeout, OSError)


class FakeFcntl:
    LOCK_SH, LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4, 8

    def __init__(self, errno_code):
        self.errno_code = errno_code

    def flock(self, fd, op):
        raise OSError(self.errno_code, "simulated contention")


@pytest.mark.parametrize("blocking,timeout", [(False, None), (True, 0.05)])
def test_posix_contention_reported_as_EACCES_is_still_BlockingIOError(
        tmp_path, monkeypatch, blocking, timeout):
    """The negative control for the errno normalisation, and it took a second
    attempt to write one that could fail.

    Deleting the translation and re-raising the original exception did NOT break
    the EAGAIN tests, because CPython's OSError constructor already maps EAGAIN
    to BlockingIOError -- the property came from the interpreter, not from our
    code, and the test could not tell. EACCES is the case that separates them:
    it maps to PermissionError, which no call site in this repo catches, so
    without normalisation a contended lock would surface as a hard failure.
    """
    monkeypatch.setattr(pl, "fcntl", FakeFcntl(errno.EACCES))
    monkeypatch.setattr(pl, "msvcrt", None)
    monkeypatch.setattr(pl, "_POLL_SECONDS", 0.001)
    with open(tmp_path / "eacces.lock", "a+") as fh:
        with pytest.raises(BlockingIOError):
            pl.lock_exclusive(fh, blocking=blocking, timeout=timeout)


def test_posix_a_genuine_error_is_NOT_swallowed_as_contention(tmp_path, monkeypatch):
    """Normalising too eagerly would hide real faults as 'someone else has it'."""
    monkeypatch.setattr(pl, "fcntl", FakeFcntl(errno.ENOSPC))
    monkeypatch.setattr(pl, "msvcrt", None)
    with open(tmp_path / "enospc.lock", "a+") as fh:
        with pytest.raises(OSError) as caught:
            pl.lock_exclusive(fh, blocking=False)
        assert not isinstance(caught.value, BlockingIOError)
        assert caught.value.errno == errno.ENOSPC


def test_shared_locks_do_not_exclude_each_other_on_posix(tmp_path):
    lock = tmp_path / "shared.lock"
    with open(lock, "a+") as a, open(lock, "a+") as b:
        pl.lock_shared(a)
        pl.lock_shared(b, blocking=False)  # must not raise
        pl.unlock(a)
        pl.unlock(b)


def test_exclusive_excludes_a_shared_holder(tmp_path):
    lock = tmp_path / "mixed.lock"
    with open(lock, "a+") as a, open(lock, "a+") as b:
        pl.lock_shared(a)
        with pytest.raises(BlockingIOError):
            pl.lock_exclusive(b, blocking=False)
        pl.unlock(a)


def test_file_lock_context_manager_releases_even_when_the_body_raises(tmp_path):
    lock = tmp_path / "ctx.lock"
    with pytest.raises(ValueError):
        with pl.file_lock(lock):
            raise ValueError("boom")
    with open(lock, "a+") as fh:
        pl.lock_exclusive(fh, blocking=False)
        pl.unlock(fh)


def test_file_lock_does_not_truncate_an_existing_lock_file(tmp_path):
    """Six call sites opened their .lock with "w". On Windows that truncation
    happens at open, BEFORE the lock is taken, and fails against a held range."""
    lock = tmp_path / "keeps.lock"
    lock.write_text("owner-note\n", encoding="utf-8")
    with pl.file_lock(lock):
        pass
    assert lock.read_text(encoding="utf-8") == "owner-note\n"


def test_locking_does_not_disturb_the_callers_file_position(tmp_path):
    data = tmp_path / "data.txt"
    data.write_text("0123456789", encoding="utf-8")
    with open(data, "r+", encoding="utf-8") as fh:
        fh.seek(4)
        pl.lock_exclusive(fh)
        assert fh.read(2) == "45", "the lock moved the caller's position"
        pl.unlock(fh)


def test_lock_accepts_a_raw_fd_as_well_as_a_file_object(tmp_path):
    lock = tmp_path / "fd.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        pl.lock_exclusive(fd, blocking=False)
        pl.unlock(fd)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Windows -- fake msvcrt. Pins the API contract, proves nothing about Windows.
# ---------------------------------------------------------------------------

class FakeMsvcrt:
    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls: list[tuple[int, int, int, int]] = []

    def locking(self, fd, mode, nbytes):
        # Record the DESCRIPTOR position at call time -- msvcrt locks from there,
        # so a wrong position is a wrong lock, silently.
        pos = os.lseek(fd, 0, os.SEEK_CUR)
        self.calls.append((fd, mode, nbytes, pos))
        if mode == self.LK_NBLCK and self.fail_times > 0:
            self.fail_times -= 1
            raise OSError(errno.EACCES, "simulated: range already locked")


@pytest.fixture
def as_windows(monkeypatch):
    fake = FakeMsvcrt()
    monkeypatch.setattr(pl, "msvcrt", fake)
    monkeypatch.setattr(pl, "fcntl", None)
    return fake


def test_windows_branch_is_selected_when_msvcrt_is_present(as_windows, tmp_path):
    fh = open(tmp_path / "w.lock", "a+")
    try:
        pl.lock_exclusive(fh)
        assert as_windows.calls, "the POSIX branch ran on a Windows-shaped host"
    finally:
        fh.close()


def test_windows_locks_exactly_one_byte_from_offset_zero(as_windows, tmp_path):
    """The seek discipline IS the correctness of the Windows path. msvcrt locks
    nbytes from the current position, so locking at a stale offset locks the
    wrong range and excludes nobody."""
    data = tmp_path / "w.data"
    data.write_text("0123456789", encoding="utf-8")
    with open(data, "r+", encoding="utf-8") as fh:
        fh.seek(7)
        pl.lock_exclusive(fh)
        (_, mode, nbytes, pos) = as_windows.calls[-1]
        assert (mode, nbytes, pos) == (FakeMsvcrt.LK_NBLCK, 1, 0)


def test_windows_restores_the_file_position_after_locking(as_windows, tmp_path):
    """Asserted on the DESCRIPTOR across each call, not after a buffered read.

    The first version of this test read through the file object between lock and
    unlock and expected the fd to sit at the logical position. It does not: a
    buffered text read pulls the whole 10-byte file in, leaving the fd at 10 with
    the logical position at 6. Both numbers were correct and the assertion was
    not. What the adapter owes the caller is that the fd is where it found it
    once each call returns -- that, and the logical position surviving, which the
    posix test above already pins with a real read.
    """
    data = tmp_path / "w2.data"
    data.write_text("0123456789", encoding="utf-8")
    with open(data, "r+", encoding="utf-8") as fh:
        fh.seek(4)
        before = os.lseek(fh.fileno(), 0, os.SEEK_CUR)
        assert before == 4
        pl.lock_exclusive(fh)
        assert os.lseek(fh.fileno(), 0, os.SEEK_CUR) == before
        pl.unlock(fh)
        assert os.lseek(fh.fileno(), 0, os.SEEK_CUR) == before


def test_windows_unlock_also_locks_from_offset_zero(as_windows, tmp_path):
    with open(tmp_path / "w3.lock", "a+") as fh:
        pl.lock_exclusive(fh)
        pl.unlock(fh)
        (_, mode, nbytes, pos) = as_windows.calls[-1]
        assert (mode, nbytes, pos) == (FakeMsvcrt.LK_UNLCK, 1, 0)


def test_windows_nonblocking_contention_raises_BlockingIOError_not_OSError(
        as_windows, tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "msvcrt", FakeMsvcrt(fail_times=1))
    with open(tmp_path / "w4.lock", "a+") as fh:
        with pytest.raises(BlockingIOError):
            pl.lock_exclusive(fh, blocking=False)


def test_windows_blocking_retries_until_the_range_frees(tmp_path, monkeypatch):
    """msvcrt's own LK_LOCK gives up after ~10s, which is neither blocking nor a
    timeout we chose. The poll loop must keep going."""
    fake = FakeMsvcrt(fail_times=3)
    monkeypatch.setattr(pl, "msvcrt", fake)
    monkeypatch.setattr(pl, "fcntl", None)
    monkeypatch.setattr(pl, "_POLL_SECONDS", 0.001)
    with open(tmp_path / "w5.lock", "a+") as fh:
        pl.lock_exclusive(fh, blocking=True)
    assert len(fake.calls) == 4, "expected 3 failures then success"


def test_windows_blocking_timeout_raises_LockTimeout(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "msvcrt", FakeMsvcrt(fail_times=10_000))
    monkeypatch.setattr(pl, "fcntl", None)
    monkeypatch.setattr(pl, "_POLL_SECONDS", 0.001)
    with open(tmp_path / "w6.lock", "a+") as fh:
        with pytest.raises(pl.LockTimeout):
            pl.lock_exclusive(fh, blocking=True, timeout=0.05)


def test_windows_shared_lock_degrades_to_exclusive_rather_than_failing(
        as_windows, tmp_path):
    """Documented divergence 1. Taking a STRONGER lock than asked is safe; the
    alternative -- raising NotImplementedError -- would push a platform branch
    into every caller, which is the thing this module exists to prevent."""
    with open(tmp_path / "w7.lock", "a+") as fh:
        pl.lock_shared(fh)
        (_, mode, nbytes, _pos) = as_windows.calls[-1]
        assert (mode, nbytes) == (FakeMsvcrt.LK_NBLCK, 1)


# ---------------------------------------------------------------------------
# Same-process behaviour both platforms must agree on
# ---------------------------------------------------------------------------

def test_two_threads_sharing_one_handle_are_not_serialized_by_this(tmp_path):
    """Honest scope statement: these are PROCESS locks. flock on one descriptor
    does not exclude threads in the same process, and neither does msvcrt. A
    caller needing thread safety needs its own threading.Lock -- pinned so the
    module is never mistaken for something it is not."""
    lock = tmp_path / "threads.lock"
    seen: list[str] = []
    with open(lock, "a+") as fh:
        pl.lock_exclusive(fh)

        def other():
            with open(lock, "a+") as fh2:
                try:
                    pl.lock_exclusive(fh2, blocking=False)
                    seen.append("acquired")
                except BlockingIOError:
                    seen.append("blocked")

        t = threading.Thread(target=other)
        t.start()
        t.join()
        pl.unlock(fh)
    # A SEPARATE handle in the same process IS excluded by flock; the point of
    # the test is that the answer is pinned rather than assumed either way.
    assert seen == ["blocked"]
