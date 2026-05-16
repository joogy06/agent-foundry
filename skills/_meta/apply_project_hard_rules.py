#!/usr/bin/env python3
"""apply_project_hard_rules.py — y / n / edit follow-up for scan_hard_rules.

Subcommands:

    apply           Insert directives under '## Project HARD-RULEs' in a
                    project's CLAUDE.md. Idempotent, dedupes by canonical
                    text, atomic write (symlink-aware), CRLF-preserving,
                    code-fence-aware section editor, fcntl LOCK_EX.

    suppress        Add directive hashes to
                    ~/.claude/state/hard-rules-suppressed.json under the
                    canonical project-id, so the scanner stops nudging.

    list-suppressed Print the suppression state (debugging aid).

    unsuppress      Remove specific hashes or clear all suppressions for
                    a project.

CLI shape: repeated --rule args (no JSON over stdin) so LLMs can copy-edit
the emitted commands without nested-JSON mangling.

Stdlib only. Python 3.10+.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import fcntl
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Import the shared canonicalization helpers.
_META = Path(__file__).resolve().parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

from hard_rules_common import (  # noqa: E402
    canonical_directive_text,
    directive_hash,
)

HOME = Path.home()
STATE_DIR = HOME / ".claude" / "state"
STATE_FILE = STATE_DIR / "hard-rules-suppressed.json"

PROJECT_HARD_RULES_SECTION_HEADER = "## Project HARD-RULEs"
PROJECT_HARD_RULES_MARKER = (
    "<!-- managed-by: scan_hard_rules.py — "
    "edit freely; new directives can be added below -->"
)

# Header regex: line-anchored, case-sensitive, exactly H2 with " Project HARD-RULEs".
_SECTION_HEADER_RE = re.compile(
    r"^##[ \t]+Project HARD-RULEs[ \t]*\r?$",
    re.MULTILINE,
)

# Subsequent H1/H2 heading that ends the section (outside a fence). Nested
# H3+ does NOT end the section.
_NEXT_H1_OR_H2_RE = re.compile(r"^#{1,2}[ \t]", re.MULTILINE)

# Top-level bullet at column 0.
_TOP_BULLET_RE = re.compile(r"^- ")

# Fence detection: ``` or ~~~ with optional language tag.
_FENCE_RE = re.compile(r"^(```|~~~)")

# Sanity bound: HARD-RULEs are short one-liners.
_MAX_RULE_LEN = 500

# Characters that warrant backtick-wrapping in a bullet (to prevent markdown
# rendering surprises).
_MARKDOWN_SPECIAL = set("<>[]*_`\\")


# ---------------------------------------------------------------------------
# Fence mask
# ---------------------------------------------------------------------------

def _build_fence_mask(lines: list[str]) -> list[bool]:
    """Returns a list of booleans, one per line: True if that line is INSIDE
    a fenced code block (header lines and content). The fence start/end
    lines themselves are considered inside the fence.

    Pairs ``` with ``` and ~~~ with ~~~ (independently). A fence open with
    ``` is closed by ``` only; same for ~~~. Unclosed fences extend to EOF.
    """
    mask = [False] * len(lines)
    open_fence: str | None = None  # "```" or "~~~" while inside
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        m = _FENCE_RE.match(stripped)
        if open_fence is None:
            if m:
                open_fence = m.group(1)
                mask[i] = True
        else:
            mask[i] = True
            if m and m.group(1) == open_fence:
                open_fence = None
    return mask


# ---------------------------------------------------------------------------
# Section locate / edit
# ---------------------------------------------------------------------------

def _find_section_bounds(
    text: str, fence_mask: list[bool]
) -> tuple[int, int] | None:
    """Locate the FIRST '## Project HARD-RULEs' section header outside any
    fence. Returns (header_line_index, end_line_index_exclusive) — end is
    the first H1/H2 heading line outside any fence after the header, or
    len(lines) if not found.

    Returns None if the section is missing.
    """
    lines = text.splitlines(keepends=False)
    header_idx: int | None = None
    for i, line in enumerate(lines):
        if fence_mask[i]:
            continue
        if _SECTION_HEADER_RE.match(line):
            header_idx = i
            break
    if header_idx is None:
        return None

    end_idx = len(lines)
    for j in range(header_idx + 1, len(lines)):
        if fence_mask[j]:
            continue
        if _NEXT_H1_OR_H2_RE.match(lines[j]):
            end_idx = j
            break

    # Detect multiple sections (warn but only edit the first).
    for k in range(end_idx, len(lines)):
        if fence_mask[k]:
            continue
        if _SECTION_HEADER_RE.match(lines[k]):
            sys.stderr.write(
                "apply_project_hard_rules: warning — multiple "
                "'## Project HARD-RULEs' sections found; editing only "
                "the first.\n"
            )
            break

    return header_idx, end_idx


def _existing_bullets_canonical(
    lines: list[str], header_idx: int, end_idx: int, fence_mask: list[bool]
) -> set[str]:
    """Canonical-text set of every top-level bullet in the section (outside
    any fence). Used to dedupe new insertions.
    """
    out: set[str] = set()
    for k in range(header_idx + 1, end_idx):
        if fence_mask[k]:
            continue
        line = lines[k]
        if _TOP_BULLET_RE.match(line):
            out.add(canonical_directive_text(line))
    return out


def _last_bullet_idx(
    lines: list[str], header_idx: int, end_idx: int, fence_mask: list[bool]
) -> int | None:
    """Index of the last top-level bullet in the section (outside fences),
    or None if there are none."""
    last: int | None = None
    for k in range(header_idx + 1, end_idx):
        if fence_mask[k]:
            continue
        if _TOP_BULLET_RE.match(lines[k]):
            last = k
    return last


def _marker_idx(
    lines: list[str], header_idx: int, end_idx: int, fence_mask: list[bool]
) -> int | None:
    """Index of the managed-by HTML comment marker line (outside fences),
    if present."""
    for k in range(header_idx + 1, end_idx):
        if fence_mask[k]:
            continue
        if lines[k].strip() == PROJECT_HARD_RULES_MARKER:
            return k
    return None


def _format_bullet(directive: str) -> str:
    """Format a single directive as a top-level markdown bullet.

    If the directive contains markdown special characters likely to render
    awkwardly, wrap the visible content in backticks. Multi-line directives
    are collapsed to one line with '; '.
    """
    cleaned = directive.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in cleaned:
        sys.stderr.write(
            "apply_project_hard_rules: warning — directive contains a "
            "newline; collapsing to one line.\n"
        )
        cleaned = cleaned.replace("\n", "; ")
    cleaned = cleaned.strip()
    if any(ch in _MARKDOWN_SPECIAL for ch in cleaned) and "`" not in cleaned:
        return f"- `{cleaned}`"
    return f"- {cleaned}"


# ---------------------------------------------------------------------------
# Read + write CLAUDE.md (CRLF-preserving, symlink-aware atomic)
# ---------------------------------------------------------------------------

def _detect_line_ending(raw: bytes) -> str:
    """Return '\\r\\n' if CRLF dominates, otherwise '\\n'."""
    crlf = raw.count(b"\r\n")
    lf_total = raw.count(b"\n")
    lf_only = lf_total - crlf
    return "\r\n" if crlf > lf_only else "\n"


def _normalize_to_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write_atomic_symlink_aware(target: Path, content: str, line_ending: str) -> None:
    """Atomic write that follows symlinks (writes to the real file). Falls
    back to in-place rewrite if tempfile placement crosses a filesystem.

    Preserves the symlink: os.replace() operates on the resolved real path,
    leaving any symlink at the original path still pointing to the same
    file.
    """
    resolved = target.resolve()
    # Restore line endings before write.
    if line_ending == "\r\n":
        encoded = content.replace("\n", "\r\n").encode("utf-8")
    else:
        encoded = content.encode("utf-8")

    parent = resolved.parent
    parent.mkdir(parents=True, exist_ok=True)

    # Try atomic tempfile + os.replace.
    try:
        fd, tmp_name = tempfile.mkstemp(
            prefix=resolved.name + ".",
            suffix=".tmp",
            dir=str(parent),
        )
        try:
            with os.fdopen(fd, "wb") as fp:
                fp.write(encoded)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_name, resolved)
            return
        except Exception:
            # Clean up the temp file if we never replaced.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        # Cross-filesystem or readonly tempdir — fall back to in-place
        # rewrite. Preserves inode + symlink semantics.
        sys.stderr.write(
            f"apply_project_hard_rules: atomic write fell back to "
            f"in-place rewrite ({exc}).\n"
        )
        with open(resolved, "wb") as fp:
            fp.seek(0)
            fp.write(encoded)
            fp.truncate()
            try:
                fp.flush()
                os.fsync(fp.fileno())
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Apply command
# ---------------------------------------------------------------------------

def _build_new_section(directives: list[str]) -> str:
    bullets = "\n".join(_format_bullet(d) for d in directives)
    return (
        f"{PROJECT_HARD_RULES_SECTION_HEADER}\n\n"
        f"{PROJECT_HARD_RULES_MARKER}\n\n"
        f"{bullets}\n"
    )


def cmd_apply(args: argparse.Namespace) -> int:
    target = Path(args.project_claude_md)
    rules: list[str] = args.rule or []

    if not rules:
        sys.stderr.write("apply: no rules to apply (--rule required).\n")
        return 2
    for r in rules:
        if len(r) > _MAX_RULE_LEN:
            sys.stderr.write(
                f"apply: rule longer than {_MAX_RULE_LEN} chars; refusing.\n"
            )
            return 2

    # Validate target.
    if target.exists() and target.is_dir():
        sys.stderr.write(f"apply: target is a directory: {target}\n")
        return 2

    # Ensure parent dir exists for new files.
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.stderr.write(f"apply: cannot create parent of {target}: {exc}\n")
        return 2

    # Create empty file under lock if missing (so we can flock something).
    if not target.exists():
        try:
            with open(target, "ab"):
                pass
        except OSError as exc:
            sys.stderr.write(f"apply: cannot create {target}: {exc}\n")
            return 2

    # flock LOCK_EX for the whole read-modify-write window (Codex #7).
    # Use a separate file handle for the lock so we can fully replace the
    # underlying file atomically.
    lock_path = target  # lock the resolved real path
    real = lock_path.resolve()
    try:
        lock_fd = open(real, "rb+" if real.stat().st_size > 0 else "ab+")
    except OSError as exc:
        sys.stderr.write(f"apply: cannot open {target} for lock: {exc}\n")
        return 2

    try:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            sys.stderr.write(
                f"apply: flock(LOCK_EX) failed on {real}: {exc}\n"
            )
            return 2

        # Read existing content under lock.
        lock_fd.seek(0)
        raw = lock_fd.read()
        line_ending = _detect_line_ending(raw)
        text = _normalize_to_lf(raw.decode("utf-8", errors="replace"))

        added = 0
        skipped = 0

        if not text.strip():
            # Empty (or whitespace-only) file: just write a fresh section.
            new_text = _build_new_section(rules)
            added = len(rules)
        else:
            lines = text.splitlines(keepends=False)
            fence_mask = _build_fence_mask(lines)
            bounds = _find_section_bounds(text, fence_mask)

            if bounds is None:
                # Section missing — append at end.
                trailing = "" if text.endswith("\n") else "\n"
                new_section = _build_new_section(rules)
                # Ensure exactly one blank line between prior content and
                # the new section.
                if not text.endswith("\n\n"):
                    if text.endswith("\n"):
                        sep = "\n"
                    else:
                        sep = "\n\n"
                else:
                    sep = ""
                new_text = text + trailing + sep + new_section
                added = len(rules)
            else:
                header_idx, end_idx = bounds
                existing = _existing_bullets_canonical(
                    lines, header_idx, end_idx, fence_mask
                )
                to_insert: list[str] = []
                for r in rules:
                    canon = canonical_directive_text(r)
                    if canon in existing:
                        skipped += 1
                        continue
                    existing.add(canon)
                    to_insert.append(r)
                    added += 1

                if to_insert:
                    last_b = _last_bullet_idx(
                        lines, header_idx, end_idx, fence_mask
                    )
                    if last_b is not None:
                        insert_at = last_b + 1
                    else:
                        marker_at = _marker_idx(
                            lines, header_idx, end_idx, fence_mask
                        )
                        if marker_at is not None:
                            insert_at = marker_at + 1
                            # If next line is blank, insert after the blank
                            # so bullets sit nicely.
                            if (
                                insert_at < len(lines)
                                and lines[insert_at].strip() == ""
                            ):
                                insert_at += 1
                        else:
                            # No marker, no bullets — insert right after
                            # the header (skip one blank if present).
                            insert_at = header_idx + 1
                            if (
                                insert_at < len(lines)
                                and lines[insert_at].strip() == ""
                            ):
                                insert_at += 1

                    new_lines = (
                        lines[:insert_at]
                        + [_format_bullet(r) for r in to_insert]
                        + lines[insert_at:]
                    )
                    new_text = "\n".join(new_lines)
                    # Preserve trailing newline if original had one.
                    if text.endswith("\n"):
                        new_text += "\n"
                else:
                    new_text = text  # nothing to do

        if new_text != text:
            _write_atomic_symlink_aware(target, new_text, line_ending)

        sys.stdout.write(
            f"Added {added} directive(s); skipped {skipped} duplicate(s). "
            f"Wrote {target}.\n"
        )
        return 0
    finally:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            lock_fd.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Suppression state I/O
# ---------------------------------------------------------------------------

def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _quarantine_state(reason: str) -> None:
    if not STATE_FILE.exists():
        return
    ts = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = STATE_FILE.with_suffix(STATE_FILE.suffix + f".bak.{ts}")
    try:
        STATE_FILE.rename(bak)
        sys.stderr.write(
            f"apply_project_hard_rules: state file quarantined to "
            f"{bak} ({reason}).\n"
        )
    except OSError as exc:
        sys.stderr.write(
            f"apply_project_hard_rules: could not quarantine corrupt "
            f"state file: {exc}\n"
        )


def _load_state_locked(fd) -> dict:
    """Load JSON from already-locked file handle. Returns {} on missing/empty;
    quarantines on corrupted JSON and returns {}.
    """
    try:
        fd.seek(0)
        raw = fd.read()
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("top-level not an object")
        return data
    except (ValueError, json.JSONDecodeError) as exc:
        _quarantine_state(f"corrupt JSON: {exc}")
        return {}


def _write_state_atomic(data: dict) -> None:
    """Atomic write of state file with 0o600 (best-effort)."""
    _ensure_state_dir()
    fd, tmp_name = tempfile.mkstemp(
        prefix=STATE_FILE.name + ".",
        suffix=".tmp",
        dir=str(STATE_DIR),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, sort_keys=True)
            fp.write("\n")
            fp.flush()
            try:
                os.fsync(fp.fileno())
            except OSError:
                pass
        try:
            os.chmod(tmp_name, 0o600)
        except OSError as exc:
            # FAT/exFAT: chmod is a no-op; log and continue.
            sys.stderr.write(
                f"apply_project_hard_rules: chmod 0o600 on state tmp "
                f"failed (continuing): {exc}\n"
            )
        os.replace(tmp_name, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    try:
        os.chmod(STATE_FILE, 0o600)
    except OSError as exc:
        sys.stderr.write(
            f"apply_project_hard_rules: chmod 0o600 on state file "
            f"failed (continuing): {exc}\n"
        )


# ---------------------------------------------------------------------------
# Suppress / list / unsuppress commands
# ---------------------------------------------------------------------------

def _open_state_for_rw_locked():
    """Open the state file in a way that supports fcntl.LOCK_EX over a
    read-modify-write sequence. Creates the file lazily."""
    _ensure_state_dir()
    if not STATE_FILE.exists():
        # Create empty so we have something to lock.
        try:
            with open(STATE_FILE, "a", encoding="utf-8"):
                pass
        except OSError as exc:
            sys.stderr.write(
                f"apply_project_hard_rules: cannot create state file: {exc}\n"
            )
            raise
        try:
            os.chmod(STATE_FILE, 0o600)
        except OSError:
            pass
    fd = open(STATE_FILE, "r+", encoding="utf-8")
    fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
    return fd


def cmd_suppress(args: argparse.Namespace) -> int:
    project_id = args.project_id
    rules: list[str] = args.rule or []
    if not rules:
        sys.stderr.write("suppress: no rules to suppress (--rule required).\n")
        return 2
    for r in rules:
        if len(r) > _MAX_RULE_LEN:
            sys.stderr.write(
                f"suppress: rule longer than {_MAX_RULE_LEN} chars; refusing.\n"
            )
            return 2

    try:
        fd = _open_state_for_rw_locked()
    except OSError:
        return 2

    try:
        state = _load_state_locked(fd)
        proj = state.setdefault(project_id, {"suppressed": []})
        if not isinstance(proj.get("suppressed"), list):
            proj["suppressed"] = []
        existing_hashes = {
            entry.get("hash")
            for entry in proj["suppressed"]
            if isinstance(entry, dict)
        }
        added = 0
        now_iso = _dt.datetime.now(tz=_dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        for r in rules:
            h = directive_hash(r)
            if h in existing_hashes:
                continue
            proj["suppressed"].append(
                {"hash": h, "directive": r, "ts": now_iso}
            )
            existing_hashes.add(h)
            added += 1
        _write_state_atomic(state)
        sys.stdout.write(
            f"Suppressed {added} hash(es) for {project_id}.\n"
        )
        return 0
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fd.close()


def cmd_list_suppressed(args: argparse.Namespace) -> int:
    if not STATE_FILE.exists():
        sys.stdout.write("(no suppression state file)\n")
        return 0
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fp:
            fcntl.flock(fp.fileno(), fcntl.LOCK_SH)
            try:
                raw = fp.read()
            finally:
                try:
                    fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    except OSError as exc:
        sys.stderr.write(f"list-suppressed: cannot read state: {exc}\n")
        return 2
    if not raw.strip():
        sys.stdout.write("(empty)\n")
        return 0
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"list-suppressed: corrupt state file: {exc}\n")
        return 2
    if args.project_id:
        slice_ = {args.project_id: data.get(args.project_id, {})}
        sys.stdout.write(json.dumps(slice_, indent=2, sort_keys=True))
    else:
        sys.stdout.write(json.dumps(data, indent=2, sort_keys=True))
    sys.stdout.write("\n")
    return 0


def cmd_unsuppress(args: argparse.Namespace) -> int:
    project_id = args.project_id
    hashes: list[str] = args.hash or []
    clear_all: bool = bool(args.all)

    if not clear_all and not hashes:
        sys.stderr.write(
            "unsuppress: pass --all or one or more --hash <hex>.\n"
        )
        return 2

    try:
        fd = _open_state_for_rw_locked()
    except OSError:
        return 2

    try:
        state = _load_state_locked(fd)
        proj = state.get(project_id)
        if not proj:
            sys.stdout.write(
                f"No suppression entries for {project_id}; nothing to do.\n"
            )
            return 0
        before = len(proj.get("suppressed", []))
        if clear_all:
            proj["suppressed"] = []
            removed = before
        else:
            target_set = set(hashes)
            proj["suppressed"] = [
                e for e in proj.get("suppressed", [])
                if isinstance(e, dict) and e.get("hash") not in target_set
            ]
            removed = before - len(proj["suppressed"])
        # Prune empty project entry.
        if not proj["suppressed"]:
            state.pop(project_id, None)
        _write_state_atomic(state)
        sys.stdout.write(
            f"Unsuppressed {removed} hash(es) for {project_id}.\n"
        )
        return 0
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fd.close()


# ---------------------------------------------------------------------------
# Argparse + dispatch
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="apply_project_hard_rules.py",
        description=(
            "Apply / suppress / list / unsuppress project HARD-RULE "
            "directives surfaced by scan_hard_rules.py."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("apply", help="Insert directives into project CLAUDE.md.")
    pa.add_argument("--project-id", required=False, default=None)
    pa.add_argument("--project-claude-md", required=True)
    pa.add_argument("--rule", action="append", required=True)

    ps = sub.add_parser("suppress", help="Suppress directives (skip future nudges).")
    ps.add_argument("--project-id", required=True)
    ps.add_argument("--rule", action="append", required=True)

    pl = sub.add_parser("list-suppressed", help="Print the suppression state.")
    pl.add_argument("--project-id", required=False, default=None)

    pu = sub.add_parser("unsuppress", help="Remove suppression entries.")
    pu.add_argument("--project-id", required=True)
    pu.add_argument("--hash", action="append", default=None)
    pu.add_argument("--all", action="store_true", default=False)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "apply":
        return cmd_apply(args)
    if args.cmd == "suppress":
        return cmd_suppress(args)
    if args.cmd == "list-suppressed":
        return cmd_list_suppressed(args)
    if args.cmd == "unsuppress":
        return cmd_unsuppress(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
