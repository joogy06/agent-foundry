#!/usr/bin/env python3
"""chunk_file.py — line-based chunker for legacy-code-intel (forked from lineage).

Splits an artifact into chunks (when needed) and emits placeholder JSONL records
for the in-session AI CLI's LLM to populate via prompts/analyze-symbols.md. Pure
I/O: NO LLM calls, NO parsing semantics, NO format-specific logic. The LLM is the
parser; this script is format-agnostic.

Forked verbatim from lineage-extract-static/scripts/chunk_file.py with three
adaptations:
  - cache root -> ~/.cache/legacy-code-intel/runs/<run_id>/files/<file_sha256>/ (0700, NEVER /tmp)
  - extractor_id -> legacy-code-intel
  - language hints broadened for legacy formats (cobol/copybook/dsx/jcl/sql/shell)

DoS caps reused from lineage (HARD-RULE 7):
    LCI_INLINE_LIMIT_MB=5          # <= 5 MB and <= 20000 lines = single chunk
    LCI_INLINE_LIMIT_LINES=20000
    LCI_CHUNK_LINES=2000
    LCI_OVERLAP_LINES=50
    LCI_HARD_FILE_LIMIT_MB=50      # >50 MB skipped with gap: oversized_file

Atomic writes via .tmp.<pid> + os.replace (HARD-RULE 3). Idempotent on re-run.

Exit codes: 0 success, 2 oversized (non-fatal gap), 1 hard error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

DEFAULT_INLINE_LIMIT_MB = int(os.environ.get("LCI_INLINE_LIMIT_MB", "5"))
DEFAULT_INLINE_LIMIT_LINES = int(os.environ.get("LCI_INLINE_LIMIT_LINES", "20000"))
DEFAULT_CHUNK_LINES = int(os.environ.get("LCI_CHUNK_LINES", "2000"))
DEFAULT_OVERLAP_LINES = int(os.environ.get("LCI_OVERLAP_LINES", "50"))
DEFAULT_HARD_LIMIT_MB = int(os.environ.get("LCI_HARD_FILE_LIMIT_MB", "50"))

DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "legacy-code-intel" / "runs"

# Format auto-detect hint (extension-based). The LLM makes the final call; this
# only narrows the analyze-symbols addendum (cobol.md / dsx.md / etl.md).
_FORMAT_HINTS = {
    "cbl": "cobol", "cob": "cobol", "cpy": "cobol", "copy": "cobol", "cobol": "cobol",
    "jcl": "cobol",
    "dsx": "dsx", "xml": "dsx", "isx": "dsx", "pjb": "dsx",
    "sh": "etl", "bash": "etl", "ksh": "etl",
    "sql": "etl", "ddl": "etl", "dml": "etl",
    "py": "etl",
    # Pick / MultiValue BASIC. Often has NO canonical extension (programs live as
    # items inside a BP file), so the LLM's content detection (SUBROUTINE / READNEXT /
    # <a,v,s> / OCONV / CRT / EQUATE ... TO @) is the real signal — see prompts/pick.md.
    # These extensions are the conventional ones when a filesystem export exists.
    "b": "pick", "mvb": "pick", "qm": "pick", "bp": "pick", "jbc": "pick",
}


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(64 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def detect_format_hint(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    return _FORMAT_HINTS.get(ext, "unknown")


def is_binary(path: Path, sample_bytes: int = 8192) -> bool:
    try:
        with path.open("rb") as f:
            buf = f.read(sample_bytes)
        if b"\x00" in buf:
            return True
        try:
            buf.decode("utf-8", errors="strict")
            return False
        except UnicodeDecodeError:
            ctrl = sum(1 for b in buf if b < 32 and b not in (9, 10, 13))
            return ctrl > len(buf) * 0.3
    except (PermissionError, OSError):
        return False


def count_lines_and_bytes(path: Path) -> tuple:
    line_count = 0
    byte_count = path.stat().st_size
    with path.open("rb") as f:
        for _ in f:
            line_count += 1
    return line_count, byte_count


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".tmp.", suffix=f".{os.getpid()}", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def ensure_cache_dir(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(cache_dir, 0o700)


def compute_chunk_boundaries(line_count, chunk_size_lines, overlap_lines):
    if line_count == 0:
        return [(1, 1)]
    if line_count <= chunk_size_lines:
        return [(1, line_count)]
    boundaries = []
    start = 1
    while start <= line_count:
        end = min(start + chunk_size_lines - 1, line_count)
        boundaries.append((start, end))
        if end >= line_count:
            break
        start = max(end + 1 - overlap_lines, start + 1)
    return boundaries


def get_byte_positions_for_chunks(path: Path, line_boundaries):
    line_starts_bytes = {1: 0}
    line_ends_bytes = {}
    current_line = 1
    current_byte = 0
    with path.open("rb") as f:
        for line in f:
            line_starts_bytes.setdefault(current_line, current_byte)
            current_byte += len(line)
            line_ends_bytes[current_line] = current_byte
            current_line += 1
            line_starts_bytes[current_line] = current_byte
    total_bytes = current_byte
    if current_line - 1 in line_ends_bytes:
        line_ends_bytes[current_line - 1] = total_bytes
    out = []
    for start_line, end_line in line_boundaries:
        out.append((line_starts_bytes.get(start_line, 0), line_ends_bytes.get(end_line, total_bytes)))
    return out


def chunk_file(
    file_path: Path,
    run_id: str,
    chunk_size_lines: int = DEFAULT_CHUNK_LINES,
    overlap_lines: int = DEFAULT_OVERLAP_LINES,
    inline_limit_mb: int = DEFAULT_INLINE_LIMIT_MB,
    inline_limit_lines: int = DEFAULT_INLINE_LIMIT_LINES,
    hard_limit_mb: int = DEFAULT_HARD_LIMIT_MB,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> dict:
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Not a regular file: {file_path}")

    file_size_bytes = file_path.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)
    file_sha = sha256_of_file(file_path)

    file_cache_dir = cache_root / run_id / "files" / file_sha
    ensure_cache_dir(file_cache_dir)

    format_hint = detect_format_hint(file_path)
    binary = is_binary(file_path)

    if file_size_mb > hard_limit_mb:
        manifest = {
            "schema_version": "1.0.0", "extractor_id": "legacy-code-intel",
            "path": str(file_path), "sha256": file_sha, "size_bytes": file_size_bytes,
            "line_count": 0, "chunked": False, "chunk_count": 0,
            "format_hint": format_hint, "binary": False,
            "gaps": [{"kind": "oversized_file", "line": 1,
                      "detail": f"File size {file_size_mb:.2f} MB exceeds LCI_HARD_FILE_LIMIT_MB={hard_limit_mb} MB"}],
        }
        atomic_write_json(file_cache_dir / "manifest.json", manifest)
        return manifest

    if binary:
        manifest = {
            "schema_version": "1.0.0", "extractor_id": "legacy-code-intel",
            "path": str(file_path), "sha256": file_sha, "size_bytes": file_size_bytes,
            "line_count": 0, "chunked": False, "chunk_count": 0,
            "format_hint": format_hint, "binary": True,
            "gaps": [{"kind": "binary_file", "line": 1,
                      "detail": "File detected as binary; no symbol extraction performed"}],
        }
        atomic_write_json(file_cache_dir / "manifest.json", manifest)
        return manifest

    line_count, _ = count_lines_and_bytes(file_path)
    is_chunked = file_size_mb > inline_limit_mb or line_count > inline_limit_lines
    line_boundaries = (
        compute_chunk_boundaries(line_count, chunk_size_lines, overlap_lines)
        if is_chunked else [(1, max(line_count, 1))]
    )
    byte_boundaries = get_byte_positions_for_chunks(file_path, line_boundaries)
    chunk_count = len(line_boundaries)

    for i, ((sl, el), (sb, eb)) in enumerate(zip(line_boundaries, byte_boundaries), start=1):
        placeholder = {
            "schema_version": "1.0.0", "extractor_id": "legacy-code-intel",
            "file_path": str(file_path), "file_sha256": file_sha,
            "chunk_id": i, "start_line": sl, "end_line": el,
            "start_byte": sb, "end_byte": eb,
            "format_hint": format_hint, "status": "awaiting_analysis",
        }
        placeholder_path = file_cache_dir / f"chunk_{i:04d}.jsonl.placeholder"
        fd, tmp_path = tempfile.mkstemp(prefix=placeholder_path.name + ".tmp.", suffix=f".{os.getpid()}", dir=str(file_cache_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(placeholder, ensure_ascii=False, sort_keys=True))
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, placeholder_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    manifest = {
        "schema_version": "1.0.0", "extractor_id": "legacy-code-intel",
        "path": str(file_path), "sha256": file_sha, "size_bytes": file_size_bytes,
        "line_count": line_count, "chunked": is_chunked, "chunk_count": chunk_count,
        "format_hint": format_hint, "binary": False, "gaps": [],
        "chunk_size_lines": chunk_size_lines if is_chunked else None,
        "overlap_lines": overlap_lines if is_chunked else None,
    }
    atomic_write_json(file_cache_dir / "manifest.json", manifest)
    return manifest


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file_path", type=Path)
    parser.add_argument("run_id")
    parser.add_argument("--chunk-size-lines", type=int, default=DEFAULT_CHUNK_LINES)
    parser.add_argument("--overlap-lines", type=int, default=DEFAULT_OVERLAP_LINES)
    parser.add_argument("--inline-limit-mb", type=int, default=DEFAULT_INLINE_LIMIT_MB)
    parser.add_argument("--inline-limit-lines", type=int, default=DEFAULT_INLINE_LIMIT_LINES)
    parser.add_argument("--hard-limit-mb", type=int, default=DEFAULT_HARD_LIMIT_MB)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    args = parser.parse_args(argv)

    try:
        manifest = chunk_file(
            args.file_path, args.run_id,
            chunk_size_lines=args.chunk_size_lines, overlap_lines=args.overlap_lines,
            inline_limit_mb=args.inline_limit_mb, inline_limit_lines=args.inline_limit_lines,
            hard_limit_mb=args.hard_limit_mb, cache_root=args.cache_root,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except (PermissionError, OSError) as e:
        print(f"ERROR: I/O error reading {args.file_path}: {e}", file=sys.stderr)
        return 1

    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    if any(g["kind"] == "oversized_file" for g in manifest.get("gaps", [])):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
