"""db_migration extractor — priority 2.

Glob: migrations/**/*.sql, **/migrations/**/*.sql

Detects SQL files inside any directory named `migrations`.
"""
from __future__ import annotations

from pathlib import Path

from . import ArtifactDelta, hash_file
from .secret import _match  # reuse helper

PRIORITY = 2
ARTIFACT_KIND = "db_migration"

_PATTERNS = (
    "migrations/**/*.sql",
    "**/migrations/**/*.sql",
)


def matches(project_root: Path, path: str) -> bool:
    return any(_match(path, pat) for pat in _PATTERNS)


def build(project_root: Path, path: str, operation: str) -> ArtifactDelta:
    return ArtifactDelta(
        kind=ARTIFACT_KIND,
        path=path,
        operation=operation,
        content_hash=hash_file(project_root, path) if operation != "removed" else None,
        extractor_meta={"matched_patterns": [p for p in _PATTERNS if _match(path, p)]},
    )
