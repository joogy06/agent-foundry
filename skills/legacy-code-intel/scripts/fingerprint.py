#!/usr/bin/env python3
"""fingerprint.py — pipeline-fingerprint + content-hash for legacy-code-intel dedup.

The dedup ("process once") key is the PAIR (content_sha256, pipeline_fingerprint).
This module computes both halves. It is the anti-requirement-#4 foundation: the
discarded agy build trusted an unset field, so re-ingesting the same bytes never
hit the cache. Here the fingerprint is computed in the ingest path and round-trips
through the store (see store.py probe + tests/test_dedup_cache_hit.py).

pipeline_fingerprint = sha256(
    schema_version + "\\x00" +
    prompt_hash + "\\x00" +
    extractor_version + "\\x00" +
    model_id + "\\x00" +
    normalizer_version
)

A change to ANY component (prompt edit, model swap, extractor bump, normalizer
change) yields a NEW fingerprint, so the store correctly RE-extracts instead of
serving a stale cache hit. Conversely, identical inputs yield the identical
fingerprint, so the second ingest of the same bytes with the same pipeline is a
pure store-hit (zero LLM calls).

NUL byte (\\x00) field separators make the concatenation injective: no choice of
field values can collide with a different field split (a NUL cannot appear in any
of the component strings, which are version strings / hex digests / identifiers).

Pure stdlib. No LLM calls. Deterministic.

CLI usage:
    fingerprint.py content <file_path>
        -> prints content_sha256
    fingerprint.py pipeline --prompt-hash H --model-id M
                   [--schema-version V] [--extractor-version V] [--normalizer-version V]
        -> prints pipeline_fingerprint
    fingerprint.py prompt-hash <prompt_file> [<prompt_file> ...]
        -> prints sha256 over the concatenated prompt files (the prompt_hash input)
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Iterable, Optional

# Pinned defaults — bumping any of these is a deliberate cache-invalidation event.
SCHEMA_VERSION = "1.0.0"
EXTRACTOR_VERSION = "1.0.0"
NORMALIZER_VERSION = "1.0.0"

_FIELD_SEP = b"\x00"


def content_sha256_of_file(path: Path) -> str:
    """Stream-hash a file's content (sha256 hex). Half of the dedup key."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for buf in iter(lambda: f.read(64 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def content_sha256_of_bytes(data: bytes) -> str:
    """sha256 hex of an in-memory byte string."""
    return hashlib.sha256(data).hexdigest()


def prompt_hash_of_files(paths: Iterable[Path]) -> str:
    """sha256 over the concatenated bytes of the extraction prompt set, in the
    given order. This becomes the `prompt_hash` fingerprint component. Editing
    any prompt changes this hash and therefore the pipeline fingerprint.
    """
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
        h.update(_FIELD_SEP)
    return h.hexdigest()


def pipeline_fingerprint(
    prompt_hash: str,
    model_id: str,
    schema_version: str = SCHEMA_VERSION,
    extractor_version: str = EXTRACTOR_VERSION,
    normalizer_version: str = NORMALIZER_VERSION,
) -> str:
    """Compute the pipeline fingerprint (sha256 hex).

    Order is fixed: schema_version, prompt_hash, extractor_version, model_id,
    normalizer_version — joined by NUL separators so the concatenation is
    injective (no field value can contain a NUL).
    """
    parts = [
        schema_version.encode("utf-8"),
        prompt_hash.encode("utf-8"),
        extractor_version.encode("utf-8"),
        model_id.encode("utf-8"),
        normalizer_version.encode("utf-8"),
    ]
    return hashlib.sha256(_FIELD_SEP.join(parts)).hexdigest()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_content = sub.add_parser("content", help="sha256 of a file's content")
    p_content.add_argument("file_path", type=Path)

    p_prompt = sub.add_parser("prompt-hash", help="sha256 over concatenated prompt files")
    p_prompt.add_argument("prompt_file", type=Path, nargs="+")

    p_pipe = sub.add_parser("pipeline", help="compute the pipeline fingerprint")
    p_pipe.add_argument("--prompt-hash", required=True)
    p_pipe.add_argument("--model-id", required=True)
    p_pipe.add_argument("--schema-version", default=SCHEMA_VERSION)
    p_pipe.add_argument("--extractor-version", default=EXTRACTOR_VERSION)
    p_pipe.add_argument("--normalizer-version", default=NORMALIZER_VERSION)

    args = parser.parse_args(argv)

    if args.cmd == "content":
        if not args.file_path.exists():
            print(f"ERROR: file not found: {args.file_path}", file=sys.stderr)
            return 1
        print(content_sha256_of_file(args.file_path))
        return 0

    if args.cmd == "prompt-hash":
        for p in args.prompt_file:
            if not p.exists():
                print(f"ERROR: prompt file not found: {p}", file=sys.stderr)
                return 1
        print(prompt_hash_of_files(args.prompt_file))
        return 0

    if args.cmd == "pipeline":
        print(
            pipeline_fingerprint(
                args.prompt_hash,
                args.model_id,
                schema_version=args.schema_version,
                extractor_version=args.extractor_version,
                normalizer_version=args.normalizer_version,
            )
        )
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
