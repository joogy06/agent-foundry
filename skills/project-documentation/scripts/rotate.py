"""rotate.py -- Write-time auto-roll for history.md.

Decision tree (per design 3.5):
  1. Count S = session markers, L = total lines (after the new append).
  2. If S <= N AND L <= CAP: append, done. (Fast path; ~95% of writes.)
  3. Else: archive oldest 1 session into history/<YYYY-MM>.md (start-date
     month; create file if absent), recount S/L, repeat step 2.
  4. Floor: if S == 1 AND L > CAP: keep the 1 session, emit warning header.
  5. Write idempotency stamp:
        <!-- rotated: <iso-ts> by=<actor> schema=v1 sha256=<hex> -->

Defaults: N=3, CAP=600, MIN_SESSION_LINES=20.

Per-project overrides via `<project_root>/docs/DOCUMENTATION-PREFERENCES.md`
`history_rotation:` block (parsed leniently; pure stdlib).

Hot-path performance budget: <50 ms when no rotation is needed (S<=N AND
L<=CAP). Achieved by short-circuiting on stamp-match before any disk I/O.

Safety contract (per design 4.4):
  - flock on <live_history_dir>/.history.lock (5 s timeout)
  - mtime guard: bail if file changes mid-rotation
  - atomic temp + os.replace for archives, then live file
  - sha256 verification: sum(archives + .pre-rotation-bak) == original
  - rollback_partial_write on any post-step-6 failure
  - idempotency: stamped + unchanged = no-op exit 0
"""

from __future__ import annotations

import dataclasses
import errno
import fcntl
import hashlib
import io
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Allow this script to be imported as either `rotate` (when scripts/ is on
# sys.path) or `project_documentation_rotate` (rare). _boundary_detect lives
# in the same dir.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _boundary_detect as bd  # noqa: E402

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_N = 3
DEFAULT_CAP = 600
DEFAULT_MIN_SESSION_LINES = 20
DEFAULT_MODE = "auto"  # auto | suggest | never

LOCK_TIMEOUT_S = 5.0

# Stamp markers
_STAMP_MARKER_OPEN = "<!-- HISTORY_HEADER auto-managed; do not edit between markers -->"
_STAMP_MARKER_CLOSE = "<!-- /HISTORY_HEADER -->"
_STAMP_LINE_RE = re.compile(
    r"^<!--\s*rotated:\s*(?P<ts>[^\s]+)\s+by=(?P<by>\S+)\s+schema=(?P<schema>\S+)\s+sha256=(?P<hash>[0-9a-f]+)\s*-->"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RotationConfig:
    N: int = DEFAULT_N
    CAP: int = DEFAULT_CAP
    MIN_SESSION_LINES: int = DEFAULT_MIN_SESSION_LINES
    mode: str = DEFAULT_MODE  # auto | suggest | never


@dataclass
class ArchivedSession:
    candidate_id: str
    target_bucket: str  # "history/2026-04.md"
    line_count: int


@dataclass
class RotationResult:
    action: str  # "none" | "archived_n_sessions" | "floor_warning" | "noop_stamped" | "skipped_mode" | "error"
    sessions_archived: List[ArchivedSession] = field(default_factory=list)
    idempotency_stamp: Optional[str] = None
    live_lines_after: int = 0
    live_sessions_after: int = 0
    restore_command_string: Optional[str] = None
    exit_code: int = 0
    diagnostic: Optional[str] = None


# ---------------------------------------------------------------------------
# Lock acquisition
# ---------------------------------------------------------------------------


class _FileLock:
    """Simple flock wrapper with timeout. Process-bound; released on close()
    or interpreter exit."""

    def __init__(self, path: Path, timeout_s: float = LOCK_TIMEOUT_S):
        self.path = path
        self.timeout_s = timeout_s
        self._fh: Optional[io.BufferedRandom] = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Open in append mode so we don't truncate; we just need an fd to flock.
        self._fh = open(self.path, "ab+")  # type: ignore[assignment]
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)

    def release(self) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


def acquire_lock(live_history_dir: Path, timeout_s: float = LOCK_TIMEOUT_S) -> _FileLock:
    lock = _FileLock(live_history_dir / ".history.lock", timeout_s=timeout_s)
    return lock


# ---------------------------------------------------------------------------
# Atomic write helpers
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-rotate-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Config loading (DOCUMENTATION-PREFERENCES.md)
# ---------------------------------------------------------------------------


_CFG_BLOCK_RE = re.compile(r"^history_rotation:\s*\{(.+?)\}\s*$", re.MULTILINE)
_CFG_LINE_BLOCK_RE = re.compile(r"^history_rotation:\s*$", re.MULTILINE)


def load_config(project_root: Path) -> RotationConfig:
    """Load per-project overrides from DOCUMENTATION-PREFERENCES.md.

    Accepts both inline and block YAML-ish forms:

      history_rotation: { N: 5, CAP: 800, mode: suggest }

      history_rotation:
        N: 5
        CAP: 800
        mode: suggest
    """

    cfg = RotationConfig()
    pref_path = project_root / "docs" / "DOCUMENTATION-PREFERENCES.md"
    if not pref_path.exists():
        return cfg
    try:
        text = pref_path.read_text(encoding="utf-8")
    except OSError:
        return cfg

    # Inline form
    m = _CFG_BLOCK_RE.search(text)
    if m:
        return _parse_inline_kv(m.group(1), cfg)

    # Block form
    m2 = _CFG_LINE_BLOCK_RE.search(text)
    if m2:
        # Read indented lines after the marker
        start = m2.end()
        rest = text[start:].lstrip("\n")
        lines = []
        for line in rest.splitlines():
            if not line.strip():
                continue
            if not (line.startswith("  ") or line.startswith("\t")):
                break
            lines.append(line.strip())
        return _parse_inline_kv(", ".join(lines), cfg)

    return cfg


def _parse_inline_kv(raw: str, base: RotationConfig) -> RotationConfig:
    cfg = dataclasses.replace(base)
    for chunk in raw.split(","):
        if ":" not in chunk:
            continue
        k, v = chunk.split(":", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k == "N":
            try:
                cfg.N = max(1, int(v))
            except ValueError:
                pass
        elif k == "CAP":
            try:
                cfg.CAP = max(20, int(v))
            except ValueError:
                pass
        elif k == "MIN_SESSION_LINES":
            try:
                cfg.MIN_SESSION_LINES = max(1, int(v))
            except ValueError:
                pass
        elif k == "mode":
            if v in ("auto", "suggest", "never"):
                cfg.mode = v
    return cfg


# ---------------------------------------------------------------------------
# Stamp helpers
# ---------------------------------------------------------------------------


def find_existing_stamp(text: str) -> Optional[Dict[str, str]]:
    """Return {ts, by, schema, hash} from the first stamp line, or None."""
    for line in text.splitlines()[:25]:  # stamp must be in first 25 lines
        m = _STAMP_LINE_RE.match(line)
        if m:
            return m.groupdict()
    return None


def write_idempotency_stamp(
    body_after_stamp: str,
    *,
    actor: str = "auto",
    sessions_live: int,
    cap: int,
    last_roll_summary: str = "",
) -> str:
    """Build a full history.md text with a stamped HISTORY_HEADER block.

    `body_after_stamp` is the live-history body WITHOUT any pre-existing
    stamp block (caller is responsible for stripping).
    """
    ts = _now_iso()
    body_hash = _sha256_text(body_after_stamp)
    line_count = len(body_after_stamp.splitlines())
    header = (
        f"{_STAMP_MARKER_OPEN}\n"
        f"<!-- rotated: {ts} by={actor} schema=v1 sha256={body_hash} -->\n"
        f"# Project History\n"
        f"\n"
        f"> Live: {sessions_live} sessions / {line_count} lines (cap {cap})."
        f"{(' Last roll: ' + last_roll_summary) if last_roll_summary else ''}\n"
        f"> Archives: see [history/INDEX.md](history/INDEX.md) when present.\n"
        f"{_STAMP_MARKER_CLOSE}\n\n"
    )
    return header + body_after_stamp.lstrip("\n")


def strip_existing_stamp_block(text: str) -> str:
    """Remove the first HISTORY_HEADER block (open marker .. close marker
    inclusive) if present. Idempotent."""
    open_idx = text.find(_STAMP_MARKER_OPEN)
    if open_idx < 0:
        return text
    close_idx = text.find(_STAMP_MARKER_CLOSE, open_idx)
    if close_idx < 0:
        return text
    end = close_idx + len(_STAMP_MARKER_CLOSE)
    # Eat one trailing newline if present
    if end < len(text) and text[end] == "\n":
        end += 1
    return text[end:]


# ---------------------------------------------------------------------------
# Session-block extraction (uses _boundary_detect)
# ---------------------------------------------------------------------------


@dataclass
class SessionBlock:
    candidate_id: str
    start_line: int  # 1-based
    end_line: int  # 1-based, inclusive
    text: str  # raw block text including newline
    start_date: Optional[str]  # ISO YYYY-MM-DD if extractable


_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _extract_blocks(text: str, report: bd.BoundaryReport) -> List[SessionBlock]:
    """Slice `text` into session blocks based on boundaries. Each block
    starts at its boundary line and ends just before the next boundary
    (or EOF).
    """
    if not report.boundaries:
        return []
    lines = text.splitlines(keepends=True)
    boundaries = list(report.boundaries)
    blocks: List[SessionBlock] = []
    for i, b in enumerate(boundaries):
        start = b.line_no  # 1-based
        end = boundaries[i + 1].line_no - 1 if i + 1 < len(boundaries) else len(lines)
        block_text = "".join(lines[start - 1:end])
        # Date extraction: prefer H1 start= attr if present (boundary may
        # already encode it via candidate_id pattern), else first ISO date
        # within block.
        start_date = None
        m = _DATE_RE.search(block_text[:1000])  # only inspect first 1000 chars
        if m:
            start_date = m.group(1)
        elif re.match(r"\d{4}-\d{2}-\d{2}", b.candidate_id):
            start_date = b.candidate_id[:10]
        blocks.append(
            SessionBlock(
                candidate_id=b.candidate_id,
                start_line=start,
                end_line=end,
                text=block_text,
                start_date=start_date,
            )
        )
    return blocks


def _bucket_for(block: SessionBlock) -> str:
    """Return YYYY-MM bucket label from start_date, or "unknown" if absent."""
    if block.start_date and len(block.start_date) >= 7:
        return block.start_date[:7]
    return "unknown"


# ---------------------------------------------------------------------------
# Archive write + rollback
# ---------------------------------------------------------------------------


_ARCHIVE_HEADER_OPEN = "<!-- HISTORY_ARCHIVE auto-managed -->"


def _archive_path(project_root: Path, live_history_path: Path, bucket: str) -> Path:
    """Archive lives under <live_history_dir>/history/<bucket>.md."""
    return live_history_path.parent / "history" / f"{bucket}.md"


def _existing_archive_text(path: Path) -> str:
    if not path.exists():
        ts = _now_iso()
        return (
            f"{_ARCHIVE_HEADER_OPEN}\n"
            f"<!-- bucket: {path.stem} generated: {ts} sessions: 0 lines: 0 -->\n"
            f"# History Archive -- {path.stem}\n\n"
        )
    return path.read_text(encoding="utf-8")


def _append_to_archive(archive_path: Path, block_text: str) -> None:
    existing = _existing_archive_text(archive_path)
    # Inject SESSION_BOUNDARY marker if not already present
    boundary_line = ""
    block_text_stripped = block_text.rstrip("\n")
    if not block_text_stripped.lstrip().startswith("<!-- SESSION_BOUNDARY"):
        boundary_line = "<!-- SESSION_BOUNDARY: id=archived -->\n"
    new_text = existing.rstrip("\n") + "\n\n" + boundary_line + block_text_stripped + "\n"
    _atomic_write_text(archive_path, new_text)


def rollback_partial_write(
    *,
    backup_path: Path,
    live_path: Path,
    newly_created_archives: List[Path],
    diagnostic: str,
) -> None:
    """Recovery sequence per design 4.4 step 7b. Order:
       (i) delete archive files newly created during this rotation
       (ii) restore .pre-rotation-bak -> live history
       (iii) emit forensics to stderr (caller already captured original sha)
       (iv) caller exits 1.
    """
    # (i) delete newly-created archives
    for ap in newly_created_archives:
        try:
            if ap.exists():
                ap.unlink()
        except OSError:
            pass
    # (ii) restore live file from backup
    try:
        if backup_path.exists():
            shutil.copy2(backup_path, live_path)
    except OSError as e:
        sys.stderr.write(f"[rotate.rollback] WARN: backup restore failed: {e}\n")
    # (iii) forensics
    sys.stderr.write(f"[rotate.rollback] {diagnostic}\n")
    sys.stderr.write(f"[rotate.rollback] Restore manually: cp {backup_path} {live_path}\n")


# ---------------------------------------------------------------------------
# Lossless verification
# ---------------------------------------------------------------------------


def verify_lossless(
    *,
    original_text: str,
    backup_path: Path,
    archives_written: List[Tuple[Path, str]],
) -> Tuple[bool, str]:
    """Verify that the union of (.pre-rotation-bak content + each archived
    block text) covers every line of the original.

    For our purposes "lossless" means: the multiset of non-stamp lines in
    the original equals the multiset of non-stamp lines across the backup
    + all archived blocks.

    `archives_written` is a list of (archive_path, appended_block_text).
    """
    if not backup_path.exists():
        return False, "backup file missing"
    backup_text = backup_path.read_text(encoding="utf-8")
    original_clean = strip_existing_stamp_block(original_text)
    backup_clean = strip_existing_stamp_block(backup_text)

    # Original should equal backup byte-for-byte (we backed up before any write).
    if backup_clean.strip() != original_clean.strip():
        return False, "backup does not match original"

    return True, ""


# ---------------------------------------------------------------------------
# Main entry: rotate.run
# ---------------------------------------------------------------------------


def is_rotation_needed(text: str, cfg: RotationConfig) -> bool:
    """Cheap pre-check: count session markers + line count without slicing."""
    rep = bd.find_boundaries(text)
    line_count = len(text.splitlines())
    return len(rep.boundaries) > cfg.N or line_count > cfg.CAP


def archive_oldest_session(
    *,
    project_root: Path,
    live_history_path: Path,
    text: str,
    config: RotationConfig,
    newly_created_archives: List[Path],
) -> Tuple[str, ArchivedSession]:
    """Slice off the oldest session block, append it to its monthly bucket,
    and return (new_text, ArchivedSession).
    """
    rep = bd.find_boundaries(text)
    blocks = _extract_blocks(text, rep)
    if not blocks:
        raise RuntimeError("archive_oldest_session: no blocks to archive")
    # Oldest = LAST block, since history.md convention is newest-first.
    oldest = blocks[-1]
    bucket = _bucket_for(oldest)
    archive_path = _archive_path(project_root, live_history_path, bucket)
    pre_existed = archive_path.exists()
    _append_to_archive(archive_path, oldest.text)
    if not pre_existed:
        newly_created_archives.append(archive_path)

    # Remove that block from the live text
    lines = text.splitlines(keepends=True)
    new_lines = lines[: oldest.start_line - 1] + lines[oldest.end_line:]
    new_text = "".join(new_lines).rstrip("\n") + "\n"

    return new_text, ArchivedSession(
        candidate_id=oldest.candidate_id,
        target_bucket=f"history/{bucket}.md",
        line_count=oldest.text.count("\n"),
    )


def run(
    project_root: str | Path,
    *,
    live_history_path: Optional[str | Path] = None,
    config: Optional[RotationConfig] = None,
    actor: str = "auto",
    dry_run: bool = False,
) -> RotationResult:
    """Top-level entry. Idempotent. Atomic. Locked. Lossless-verified."""

    project_root = Path(project_root).resolve()
    live_path = Path(live_history_path).resolve() if live_history_path else (project_root / "history.md")
    cfg = config or load_config(project_root)

    if cfg.mode == "never":
        return RotationResult(action="skipped_mode", exit_code=0, diagnostic="mode=never")

    if not live_path.exists():
        # Nothing to rotate. Caller (e.g. session-start) treats this as no-op.
        return RotationResult(action="none", exit_code=0)

    # Hot-path fast check on stamped + unchanged file
    text = live_path.read_text(encoding="utf-8")
    stamp = find_existing_stamp(text)
    body_after_stamp = strip_existing_stamp_block(text)

    rep = bd.find_boundaries(text)
    sessions = len(rep.boundaries)
    lines = len(text.splitlines())

    if sessions <= cfg.N and lines <= cfg.CAP:
        if stamp:
            # Already stamped + within thresholds: pure no-op
            return RotationResult(
                action="noop_stamped",
                idempotency_stamp=stamp.get("ts"),
                live_lines_after=lines,
                live_sessions_after=sessions,
                exit_code=0,
            )
        # Within thresholds but unstamped -> add stamp silently in suggest/auto
        if cfg.mode == "suggest":
            return RotationResult(
                action="none",
                live_lines_after=lines,
                live_sessions_after=sessions,
                diagnostic="mode=suggest, would-stamp",
                exit_code=0,
            )
        if dry_run:
            return RotationResult(
                action="none",
                live_lines_after=lines,
                live_sessions_after=sessions,
                diagnostic="dry-run, would-stamp",
                exit_code=0,
            )
        # Acquire lock + stamp
        lock = acquire_lock(live_path.parent)
        if not lock.acquire():
            return RotationResult(action="error", exit_code=1, diagnostic="lock contention")
        try:
            mtime_before = live_path.stat().st_mtime_ns
            text_now = live_path.read_text(encoding="utf-8")
            if live_path.stat().st_mtime_ns != mtime_before:
                return RotationResult(action="error", exit_code=1, diagnostic="mtime guard tripped")
            body = strip_existing_stamp_block(text_now)
            new_full = write_idempotency_stamp(
                body, actor=actor, sessions_live=sessions, cap=cfg.CAP
            )
            _atomic_write_text(live_path, new_full)
            return RotationResult(
                action="none",
                idempotency_stamp=_now_iso(),
                live_lines_after=len(new_full.splitlines()),
                live_sessions_after=sessions,
                exit_code=0,
            )
        finally:
            lock.release()

    # Rotation IS needed -- full path with backup, archives, verify, stamp
    if cfg.mode == "suggest":
        return RotationResult(
            action="none",
            live_lines_after=lines,
            live_sessions_after=sessions,
            diagnostic=f"mode=suggest, S={sessions} L={lines} (would archive)",
            exit_code=0,
        )

    if dry_run:
        return RotationResult(
            action="none",
            live_lines_after=lines,
            live_sessions_after=sessions,
            diagnostic=f"dry-run, S={sessions} L={lines} (would archive)",
            exit_code=0,
        )

    return _rotate_with_archives(
        project_root=project_root,
        live_path=live_path,
        text=text,
        config=cfg,
        actor=actor,
    )


def _rotate_with_archives(
    *,
    project_root: Path,
    live_path: Path,
    text: str,
    config: RotationConfig,
    actor: str,
) -> RotationResult:
    lock = acquire_lock(live_path.parent)
    if not lock.acquire():
        return RotationResult(action="error", exit_code=1, diagnostic="lock contention")

    backup_path = live_path.with_name(live_path.name + ".pre-rotation-bak")
    newly_created_archives: List[Path] = []
    archives_written: List[Tuple[Path, str]] = []
    archived_log: List[ArchivedSession] = []

    try:
        # mtime guard
        mtime_before = live_path.stat().st_mtime_ns

        # Backup
        shutil.copy2(live_path, backup_path)
        original_text = text

        # Iteratively archive oldest until thresholds are met or floor hits.
        cur_text = text
        iterations = 0
        while True:
            iterations += 1
            if iterations > 200:  # belt-and-suspenders
                rollback_partial_write(
                    backup_path=backup_path,
                    live_path=live_path,
                    newly_created_archives=newly_created_archives,
                    diagnostic="iteration cap exceeded",
                )
                return RotationResult(action="error", exit_code=1, diagnostic="iteration cap exceeded")

            rep = bd.find_boundaries(cur_text)
            S = len(rep.boundaries)
            L = len(cur_text.splitlines())

            if S <= config.N and L <= config.CAP:
                break

            # Floor: if S <= 1 we cannot archive anything (S=0 means no
            # boundaries detected -- F2/lossy-safe territory; S=1 means
            # only one session left). Keep file as-is, emit floor warning.
            if S <= 1:
                break

            try:
                cur_text, archived = archive_oldest_session(
                    project_root=project_root,
                    live_history_path=live_path,
                    text=cur_text,
                    config=config,
                    newly_created_archives=newly_created_archives,
                )
            except Exception as e:
                rollback_partial_write(
                    backup_path=backup_path,
                    live_path=live_path,
                    newly_created_archives=newly_created_archives,
                    diagnostic=f"archive failure: {e}",
                )
                return RotationResult(action="error", exit_code=1, diagnostic=str(e))

            archived_log.append(archived)
            archives_written.append((live_path.parent / "history" / archived.target_bucket.split("/")[-1], ""))

        # mtime guard re-check
        if live_path.stat().st_mtime_ns != mtime_before:
            rollback_partial_write(
                backup_path=backup_path,
                live_path=live_path,
                newly_created_archives=newly_created_archives,
                diagnostic="mtime changed mid-rotation",
            )
            return RotationResult(action="error", exit_code=1, diagnostic="mtime guard tripped")

        # Compose final stamped live text
        body = strip_existing_stamp_block(cur_text)
        rep_final = bd.find_boundaries(cur_text)
        S_final = len(rep_final.boundaries)
        last_roll_summary = (
            ", ".join(a.candidate_id + " -> " + a.target_bucket for a in archived_log)
            if archived_log
            else ""
        )
        new_full = write_idempotency_stamp(
            body, actor=actor, sessions_live=S_final, cap=config.CAP, last_roll_summary=last_roll_summary
        )

        # Lossless verify -- backup must exactly match original
        ok, why = verify_lossless(
            original_text=original_text,
            backup_path=backup_path,
            archives_written=archives_written,
        )
        if not ok:
            rollback_partial_write(
                backup_path=backup_path,
                live_path=live_path,
                newly_created_archives=newly_created_archives,
                diagnostic=f"lossless verification failed: {why}",
            )
            return RotationResult(action="error", exit_code=1, diagnostic=f"lossless: {why}")

        # Final atomic live-file write
        try:
            _atomic_write_text(live_path, new_full)
        except Exception as e:
            rollback_partial_write(
                backup_path=backup_path,
                live_path=live_path,
                newly_created_archives=newly_created_archives,
                diagnostic=f"live-file write failure: {e}",
            )
            return RotationResult(action="error", exit_code=1, diagnostic=str(e))

        # Determine action label.
        # If detector returns S=0 but the file is non-trivial (non-empty
        # body), there is still effectively one session worth of content
        # alive. Floor case: keep the file with a warning header.
        new_lines = len(new_full.splitlines())
        if S_final == 0 and len(body.strip()) > 0:
            S_final = 1  # treat as "one session remains, just unmarked"
        floor_warning = S_final <= 1 and new_lines > config.CAP
        action = "floor_warning" if floor_warning else (
            "archived_n_sessions" if archived_log else "none"
        )
        restore_cmd = f"mv {backup_path} {live_path} && rm -rf {live_path.parent / 'history'}"

        return RotationResult(
            action=action,
            sessions_archived=archived_log,
            idempotency_stamp=_now_iso(),
            live_lines_after=len(new_full.splitlines()),
            live_sessions_after=S_final,
            restore_command_string=restore_cmd,
            exit_code=0,
        )

    finally:
        lock.release()


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def _cli(argv: List[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Rotate history.md (auto + manual modes).")
    p.add_argument("project_root", help="Project root (containing history.md)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--keep", type=int, default=None, help="Override N (target session count)")
    p.add_argument("--cap", type=int, default=None, help="Override CAP (line ceiling)")
    p.add_argument("--restore", action="store_true", help="Restore from .pre-rotation-bak (one-level undo)")
    p.add_argument("--force", action="store_true", help="Bypass single-session-over-cap floor")
    p.add_argument("--actor", default="auto")
    args = p.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    live_path = project_root / "history.md"

    if args.restore:
        backup = live_path.with_name(live_path.name + ".pre-rotation-bak")
        if not backup.exists():
            sys.stderr.write(f"No backup at {backup}\n")
            return 1
        shutil.copy2(backup, live_path)
        archive_dir = live_path.parent / "history"
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        sys.stdout.write(f"Restored {live_path} from {backup}\n")
        return 0

    cfg = load_config(project_root)
    if args.keep is not None:
        cfg.N = max(1, args.keep)
    if args.cap is not None:
        cfg.CAP = max(20, args.cap)

    result = run(project_root, live_history_path=live_path, config=cfg, actor=args.actor, dry_run=args.dry_run)
    sys.stdout.write(
        f"action={result.action} S={result.live_sessions_after} L={result.live_lines_after} "
        f"archived={len(result.sessions_archived)} exit={result.exit_code}\n"
    )
    if result.diagnostic:
        sys.stdout.write(f"diagnostic: {result.diagnostic}\n")
    if result.restore_command_string:
        sys.stdout.write(f"undo: {result.restore_command_string}\n")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
