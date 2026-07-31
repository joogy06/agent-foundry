#!/usr/bin/env python3
"""Cross-platform advisory file locking -- the one place OS internals are allowed.

WHY THIS EXISTS (#249)
----------------------
Nine shipped modules imported fcntl at MODULE level. fcntl is POSIX-only, so on
Windows they raised ModuleNotFoundError at IMPORT -- not at use. claims.py is one
of them, which is why bob could not execute on Windows in any host. A missing jq
is exit 127 at runtime; an unguarded platform import kills the module before it
runs, so the whole ledger/verification spine was unreachable.

The chosen fix (ratified 2026-07-30, over os.mkdir directory locking) is a thin
fcntl/msvcrt adapter behind one module. The reason is semantic, not stylistic:
seven of ten call sites are single-writer promote/claim paths that rely on
"the lock dies with the process". Both flock and Windows byte-range locks release
when the handle closes, and the handle closes when the process dies -- an
os.mkdir lock does not, so it would have needed stale-lock detection via PID and
timestamp, inventing a new failure mode inside the ledger spine.

THE CONTRACT, identical on both platforms
-----------------------------------------
  * contention with blocking=False raises BlockingIOError (a subclass of OSError,
    so existing `except OSError` handlers keep working unchanged)
  * blocking=True waits; timeout=None waits indefinitely
  * blocking=True with a timeout that expires raises BlockingIOError
  * unlock() releases; closing the handle also releases, on both platforms

WHAT DIFFERS, stated rather than hidden
---------------------------------------
  1. SHARED LOCKS DEGRADE TO EXCLUSIVE ON WINDOWS. msvcrt offers no shared mode.
     Readers therefore serialize against each other there. That is a concurrency
     cost, never a correctness one -- the mutual-exclusion property callers
     depend on is strictly stronger, not weaker.
  2. POSIX flock is ADVISORY; Windows byte-range locks are MANDATORY. Two
     consequences bite in practice, and both are why the helpers below exist:
       - open(lock_path, "w") TRUNCATES at open, before any lock is taken. On
         Windows that open fails while another process holds the range. Use
         file_lock(), which opens "a+" and never truncates.
       - msvcrt.locking() locks nbytes from the CURRENT file position, so the
         descriptor must be seeked to 0 first and restored after. We do that on
         the raw fd via os.lseek, which leaves Python's buffered layer untouched.

VERIFICATION STATUS -- read this before trusting the Windows half
-----------------------------------------------------------------
The POSIX path is tested against REAL cross-process contention (subprocess holds
the lock; the test observes the block). The Windows path is unit-tested against
an injected fake msvcrt that asserts the call sequence, the byte count, the
position restore and the retry loop -- because no Windows machine has run it yet.
That is the same honest limit rules 5 and 7 of writing-portable-python carry.
When this first runs on Windows, the thing to check is an EMPTY lock file:
locking a range beyond EOF is legal under LockFileEx, and unverified here.
"""

from __future__ import annotations

import errno
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Platform imports live inside an `if`, which is what makes this module importable
# everywhere -- the exact property whose absence produced #249. portability_lint
# rule P001 counts an `if`-guarded import as guarded, and this module is in its
# clean set.
if sys.platform == "win32":  # pragma: no cover - selected by platform
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None

__all__ = [
    "lock_exclusive",
    "lock_shared",
    "unlock",
    "file_lock",
    "LockTimeout",
]

# One byte at offset 0. The range is a rendezvous, never the data -- locking the
# whole file would make the mandatory-lock semantics on Windows block the owner's
# own reads through other handles.
_LOCK_BYTES = 1

# How often a blocking Windows acquire retries. msvcrt's own LK_LOCK retries 10
# times at 1s and then gives up, which is neither "blocking" nor a timeout we
# chose; the poll loop below replaces it so both platforms mean the same thing.
_POLL_SECONDS = 0.05


class LockTimeout(BlockingIOError):
    """A blocking acquire whose timeout expired.

    Subclasses BlockingIOError so callers that only care about "someone else has
    it" need no change, while callers that distinguish waited-and-gave-up from
    was-already-held can.
    """


# ---------------------------------------------------------------------------
# fd helpers
# ---------------------------------------------------------------------------

def _fileno(fh) -> int:
    """Accept a file object or a raw fd, so call sites need not care."""
    return fh if isinstance(fh, int) else fh.fileno()


@contextmanager
def _at_offset_zero(fd: int):
    """Seek the DESCRIPTOR to 0 for the duration, then restore it exactly.

    os.lseek rather than fh.seek: msvcrt.locking reads the descriptor position,
    and going through the buffered layer would force a flush and could move the
    caller's logical position. Restoring the fd position exactly means Python's
    buffer never observes that anything happened.
    """
    try:
        pos = os.lseek(fd, 0, os.SEEK_CUR)
    except OSError:
        # Not seekable (a pipe, a device). Nothing to restore; let the lock call
        # decide whether it can proceed.
        yield
        return
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        yield
    finally:
        os.lseek(fd, pos, os.SEEK_SET)


def _deadline(timeout: float | None) -> float | None:
    return None if timeout is None else time.monotonic() + timeout


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


# ---------------------------------------------------------------------------
# POSIX
# ---------------------------------------------------------------------------

def _posix_lock(fd: int, *, exclusive: bool, blocking: bool,
                timeout: float | None) -> None:
    op = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH

    if blocking and timeout is None:
        # The common case: hand the wait to the kernel rather than polling.
        try:
            fcntl.flock(fd, op)
        except OSError as exc:
            raise _translate(exc) from exc
        return

    deadline = _deadline(timeout) if blocking else None
    while True:
        try:
            fcntl.flock(fd, op | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
                raise
            if not blocking:
                raise BlockingIOError(
                    errno.EAGAIN, "lock is held by another process") from exc
            if _expired(deadline):
                raise LockTimeout(
                    errno.EAGAIN,
                    f"timed out after {timeout}s waiting for the lock") from exc
            time.sleep(_POLL_SECONDS)


def _posix_unlock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)


def _translate(exc: OSError) -> OSError:
    if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
        return BlockingIOError(errno.EAGAIN, "lock is held by another process")
    return exc


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def _windows_lock(fd: int, *, exclusive: bool, blocking: bool,
                  timeout: float | None) -> None:
    """Note `exclusive` is accepted and ignored -- see the docstring's point 1.

    Every Windows lock is exclusive because msvcrt has no shared mode. Taking a
    stronger lock than asked is safe; silently taking a WEAKER one would not be,
    which is why this degrades rather than raising NotImplementedError and
    forcing every caller to grow a platform branch.
    """
    deadline = _deadline(timeout) if blocking else None
    with _at_offset_zero(fd):
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, _LOCK_BYTES)
                return
            except OSError as exc:
                if not blocking:
                    raise BlockingIOError(
                        errno.EAGAIN,
                        "lock is held by another process") from exc
                if _expired(deadline):
                    raise LockTimeout(
                        errno.EAGAIN,
                        f"timed out after {timeout}s waiting for the lock"
                    ) from exc
                time.sleep(_POLL_SECONDS)


def _windows_unlock(fd: int) -> None:
    with _at_offset_zero(fd):
        msvcrt.locking(fd, msvcrt.LK_UNLCK, _LOCK_BYTES)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _is_windows() -> bool:
    """Read at call time, not import time, so a test can exercise either branch."""
    return msvcrt is not None


def lock_exclusive(fh, *, blocking: bool = True,
                   timeout: float | None = None) -> None:
    """Take an exclusive lock. Raises BlockingIOError if it cannot be had."""
    fd = _fileno(fh)
    if _is_windows():
        _windows_lock(fd, exclusive=True, blocking=blocking, timeout=timeout)
    else:
        _posix_lock(fd, exclusive=True, blocking=blocking, timeout=timeout)


def lock_shared(fh, *, blocking: bool = True,
                timeout: float | None = None) -> None:
    """Take a shared (read) lock -- EXCLUSIVE on Windows, see docstring point 1."""
    fd = _fileno(fh)
    if _is_windows():
        _windows_lock(fd, exclusive=False, blocking=blocking, timeout=timeout)
    else:
        _posix_lock(fd, exclusive=False, blocking=blocking, timeout=timeout)


def unlock(fh) -> None:
    """Release. Safe to call once; closing the handle also releases."""
    fd = _fileno(fh)
    if _is_windows():
        _windows_unlock(fd)
    else:
        _posix_unlock(fd)


@contextmanager
def file_lock(path, *, exclusive: bool = True, blocking: bool = True,
              timeout: float | None = None):
    """Open a dedicated lock file, hold a lock over the body, always release.

    Opens "a+", never "w". Six call sites used "w" before this existed, and on
    Windows the truncation happens at open -- BEFORE any lock is taken -- so it
    fails against a range another process holds. "a+" creates without truncating
    and needs no write permission dance.

    Yields the open handle for callers that want to record something in it.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")
    try:
        if exclusive:
            lock_exclusive(fh, blocking=blocking, timeout=timeout)
        else:
            lock_shared(fh, blocking=blocking, timeout=timeout)
        try:
            yield fh
        finally:
            try:
                unlock(fh)
            except OSError:
                # The handle close below releases regardless. Failing here would
                # replace the caller's real exception with a teardown one.
                pass
    finally:
        fh.close()
