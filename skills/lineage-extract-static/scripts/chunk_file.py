#!/usr/bin/env python3
"""chunk_file.py — line-based chunker for lineage-extract-static.

Splits a file into chunks (when needed) and emits placeholder JSONL records
for the agent's LLM to populate via `prompts/analyze-file.md`. Pure I/O:
NO LLM calls, NO parsing semantics, NO format-specific logic.

Component: chunk-file (WP-3 in S033 contract-map).

Outputs (per HARD-RULE 5 sandbox path discipline at
~/.cache/lineage-extract-static/runs/<run_id>/files/<file_sha256>/, mode 0700):
- manifest.json — {path, sha256, size, line_count, chunked, chunk_count, language_hint, gaps[]}
- chunk_NNNN.jsonl.placeholder — one per chunk, carrying {chunk_id, start_line, end_line, start_byte, end_byte}
  for the agent's LLM to populate via per-chunk analysis. Each placeholder file
  contains the chunk metadata as a single JSON line; the agent appends its
  analyze-file.md output as a second line in the .jsonl file.

Atomic writes via .tmp.<pid> + os.replace(). Idempotent on re-run with same inputs.

CLI usage:
    chunk_file.py <file_path> <run_id> [--chunk-size-lines N] [--overlap-lines N]
                  [--inline-limit-mb N] [--inline-limit-lines N] [--hard-limit-mb N]
                  [--cache-root PATH]

Defaults (per design §9):
    LINEAGE_INLINE_LIMIT_MB=5          # File <= 5 MB and <= 20000 lines = single chunk
    LINEAGE_INLINE_LIMIT_LINES=20000
    LINEAGE_CHUNK_LINES=2000
    LINEAGE_OVERLAP_LINES=50
    LINEAGE_HARD_FILE_LIMIT_MB=50      # >50 MB skipped with gap: oversized_file

Returns exit code 0 on success, 2 on oversized file (gap emitted, non-fatal),
1 on hard error (permission, decode).
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

# Defaults (env-overrideable per HARD-RULE 6)
DEFAULT_INLINE_LIMIT_MB = int(os.environ.get("LINEAGE_INLINE_LIMIT_MB", "5"))
DEFAULT_INLINE_LIMIT_LINES = int(os.environ.get("LINEAGE_INLINE_LIMIT_LINES", "20000"))
DEFAULT_CHUNK_LINES = int(os.environ.get("LINEAGE_CHUNK_LINES", "2000"))
DEFAULT_OVERLAP_LINES = int(os.environ.get("LINEAGE_OVERLAP_LINES", "50"))
DEFAULT_HARD_LIMIT_MB = int(os.environ.get("LINEAGE_HARD_FILE_LIMIT_MB", "50"))

DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "lineage-extract-static" / "runs"


def sha256_of_file(path: Path) -> str:
    """Compute sha256 of the file content, streaming."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(64 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def detect_language_hint(path: Path) -> str:
    """Cheap extension-based language hint. Used only to help the LLM target
    its extraction; chunk_file.py itself is format-agnostic.
    """
    ext = path.suffix.lower().lstrip(".")
    mapping = {
        "py": "python",
        "sql": "sql",
        "ddl": "sql",
        "dsx": "datastage-dsx",
        "yaml": "yaml",
        "yml": "yaml",
        "json": "json",
        "toml": "toml",
        "ini": "ini",
        "sh": "shell",
        "bash": "shell",
        "ts": "typescript",
        "tsx": "typescript",
        "js": "javascript",
        "jsx": "javascript",
        "java": "java",
        "scala": "scala",
        "go": "go",
        "rs": "rust",
        "rb": "ruby",
        "cbl": "cobol",
        "cob": "cobol",
        "jcl": "jcl",
        "md": "markdown",
        "html": "html",
        "xml": "xml",
        "csv": "csv",
        "tsv": "tsv",
        "log": "log",
    }
    return mapping.get(ext, "unknown")


def is_binary(path: Path, sample_bytes: int = 8192) -> bool:
    """Cheap binary check: read first sample_bytes, look for NUL byte.
    Robust enough for most cases; the LLM emits gap: binary_file if it sees
    something unparseable.
    """
    try:
        with path.open("rb") as f:
            buf = f.read(sample_bytes)
        if b"\x00" in buf:
            return True
        # Try decoding as UTF-8; if it fails entirely, treat as binary
        try:
            buf.decode("utf-8", errors="strict")
            return False
        except UnicodeDecodeError:
            # Try latin-1 as fallback (many log files); only flag as binary
            # if even latin-1 has weird control bytes density
            ctrl = sum(1 for b in buf if b < 32 and b not in (9, 10, 13))
            return ctrl > len(buf) * 0.3
    except (PermissionError, OSError):
        return False  # let the caller decide; we'll error on open


def count_lines_and_bytes(path: Path) -> tuple[int, int]:
    """Returns (line_count, byte_count)."""
    line_count = 0
    byte_count = path.stat().st_size
    with path.open("rb") as f:
        for _ in f:
            line_count += 1
    return line_count, byte_count


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically via .tmp.<pid> + os.replace. HARD-RULE 5."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".tmp.",
        suffix=f".{os.getpid()}",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Clean up tmp on any failure
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def ensure_cache_dir(cache_dir: Path) -> None:
    """Create cache directory with mode 0700. HARD-RULE 5."""
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Re-chmod in case it already existed with different mode
    os.chmod(cache_dir, 0o700)


def compute_chunk_boundaries(
    line_count: int,
    chunk_size_lines: int,
    overlap_lines: int,
) -> list[tuple[int, int]]:
    """Return list of (start_line, end_line) tuples (1-indexed, inclusive)
    for the chunks. Overlap_lines is the carry-over: chunk N+1's start_line
    is chunk N's end_line + 1 - overlap_lines, clamped at >=1.

    For files with line_count <= chunk_size_lines, returns single tuple.
    """
    if line_count == 0:
        return [(1, 1)]  # empty file: one degenerate chunk
    if line_count <= chunk_size_lines:
        return [(1, line_count)]

    boundaries: list[tuple[int, int]] = []
    start = 1
    while start <= line_count:
        end = min(start + chunk_size_lines - 1, line_count)
        boundaries.append((start, end))
        if end >= line_count:
            break
        # Next chunk starts overlap_lines back from end + 1
        start = max(end + 1 - overlap_lines, start + 1)  # guarantee progress
    return boundaries


def get_byte_positions_for_chunks(
    path: Path,
    line_boundaries: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """For each (start_line, end_line) chunk, compute (start_byte, end_byte).
    end_byte is exclusive (Python slice end). Streams through the file once.
    """
    line_starts_bytes: dict[int, int] = {1: 0}
    line_ends_bytes: dict[int, int] = {}
    current_line = 1
    current_byte = 0
    with path.open("rb") as f:
        for line in f:
            line_starts_bytes.setdefault(current_line, current_byte)
            current_byte += len(line)
            line_ends_bytes[current_line] = current_byte
            current_line += 1
            line_starts_bytes[current_line] = current_byte
    # Total bytes
    total_bytes = current_byte
    # Last-line correction: if file doesn't end with newline, the loop above
    # doesn't increment current_line for the final partial line. Make sure
    # the final line's end_byte is total_bytes.
    if current_line - 1 in line_ends_bytes:
        line_ends_bytes[current_line - 1] = total_bytes

    byte_boundaries: list[tuple[int, int]] = []
    for start_line, end_line in line_boundaries:
        start_byte = line_starts_bytes.get(start_line, 0)
        end_byte = line_ends_bytes.get(end_line, total_bytes)
        byte_boundaries.append((start_byte, end_byte))
    return byte_boundaries


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
    """Chunk a file. Returns the manifest dict that was written.

    Raises FileNotFoundError if file doesn't exist.
    Returns manifest with gap: oversized_file if file > hard_limit_mb (does
    not raise; caller decides whether to continue).
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Not a regular file: {file_path}")

    file_size_bytes = file_path.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)
    file_sha = sha256_of_file(file_path)

    # Per-file cache directory: ~/.cache/lineage-extract-static/runs/<run_id>/files/<file_sha256>/
    file_cache_dir = cache_root / run_id / "files" / file_sha
    ensure_cache_dir(file_cache_dir)

    language_hint = detect_language_hint(file_path)
    binary = is_binary(file_path)

    # Hard cap: skip oversized files (HARD-RULE 6)
    if file_size_mb > hard_limit_mb:
        manifest = {
            "schema_version": "1.0.0",
            "path": str(file_path),
            "sha256": file_sha,
            "size_bytes": file_size_bytes,
            "line_count": 0,
            "chunked": False,
            "chunk_count": 0,
            "language_hint": language_hint,
            "binary": False,
            "gaps": [
                {
                    "kind": "oversized_file",
                    "line": 1,
                    "description": f"File size {file_size_mb:.2f} MB exceeds LINEAGE_HARD_FILE_LIMIT_MB={hard_limit_mb} MB",
                }
            ],
        }
        manifest_path = file_cache_dir / "manifest.json"
        atomic_write_json(manifest_path, manifest)
        return manifest

    if binary:
        manifest = {
            "schema_version": "1.0.0",
            "path": str(file_path),
            "sha256": file_sha,
            "size_bytes": file_size_bytes,
            "line_count": 0,
            "chunked": False,
            "chunk_count": 0,
            "language_hint": language_hint,
            "binary": True,
            "gaps": [
                {
                    "kind": "binary_file",
                    "line": 1,
                    "description": "File detected as binary; no lineage extraction performed",
                }
            ],
        }
        manifest_path = file_cache_dir / "manifest.json"
        atomic_write_json(manifest_path, manifest)
        return manifest

    # Count lines + bytes
    line_count, _ = count_lines_and_bytes(file_path)

    # Decide inline vs chunked
    is_chunked = (
        file_size_mb > inline_limit_mb or line_count > inline_limit_lines
    )

    if is_chunked:
        line_boundaries = compute_chunk_boundaries(
            line_count, chunk_size_lines, overlap_lines
        )
    else:
        line_boundaries = [(1, max(line_count, 1))]

    # Compute byte boundaries
    byte_boundaries = get_byte_positions_for_chunks(file_path, line_boundaries)

    # Emit placeholder files
    chunk_count = len(line_boundaries)
    for i, ((start_line, end_line), (start_byte, end_byte)) in enumerate(
        zip(line_boundaries, byte_boundaries), start=1
    ):
        placeholder = {
            "schema_version": "1.0.0",
            "extractor_id": "lineage-extract-static",
            "file_path": str(file_path),
            "file_sha256": file_sha,
            "chunk_id": i,
            "start_line": start_line,
            "end_line": end_line,
            "start_byte": start_byte,
            "end_byte": end_byte,
            "language_hint": language_hint,
            "status": "awaiting_analysis",
        }
        placeholder_path = file_cache_dir / f"chunk_{i:04d}.jsonl.placeholder"
        # Atomic write of the placeholder JSON (single line at this stage)
        fd, tmp_path = tempfile.mkstemp(
            prefix=placeholder_path.name + ".tmp.",
            suffix=f".{os.getpid()}",
            dir=str(file_cache_dir),
        )
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

    # Write the manifest
    manifest = {
        "schema_version": "1.0.0",
        "path": str(file_path),
        "sha256": file_sha,
        "size_bytes": file_size_bytes,
        "line_count": line_count,
        "chunked": is_chunked,
        "chunk_count": chunk_count,
        "language_hint": language_hint,
        "binary": False,
        "gaps": [],
        "chunk_size_lines": chunk_size_lines if is_chunked else None,
        "overlap_lines": overlap_lines if is_chunked else None,
    }
    manifest_path = file_cache_dir / "manifest.json"
    atomic_write_json(manifest_path, manifest)
    return manifest


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file_path", type=Path, help="File to chunk")
    parser.add_argument("run_id", help="Run identifier")
    parser.add_argument("--chunk-size-lines", type=int, default=DEFAULT_CHUNK_LINES)
    parser.add_argument("--overlap-lines", type=int, default=DEFAULT_OVERLAP_LINES)
    parser.add_argument("--inline-limit-mb", type=int, default=DEFAULT_INLINE_LIMIT_MB)
    parser.add_argument("--inline-limit-lines", type=int, default=DEFAULT_INLINE_LIMIT_LINES)
    parser.add_argument("--hard-limit-mb", type=int, default=DEFAULT_HARD_LIMIT_MB)
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help=f"Cache root (default: {DEFAULT_CACHE_ROOT})",
    )
    args = parser.parse_args(argv)

    try:
        manifest = chunk_file(
            args.file_path,
            args.run_id,
            chunk_size_lines=args.chunk_size_lines,
            overlap_lines=args.overlap_lines,
            inline_limit_mb=args.inline_limit_mb,
            inline_limit_lines=args.inline_limit_lines,
            hard_limit_mb=args.hard_limit_mb,
            cache_root=args.cache_root,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except (PermissionError, OSError) as e:
        print(f"ERROR: I/O error reading {args.file_path}: {e}", file=sys.stderr)
        return 1

    # Print manifest JSON to stdout (single line, for capture by the agent)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))

    # Exit code 2 if oversized (non-fatal gap), else 0
    if any(gap["kind"] == "oversized_file" for gap in manifest.get("gaps", [])):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
