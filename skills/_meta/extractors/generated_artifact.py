"""generated_artifact extractor — priority 6.

Catches paths that almost always represent build/output artefacts that
should NOT be tracked as source. Marks the kind so callers can choose
to skip these from severity classification entirely.
"""
from __future__ import annotations

from pathlib import Path

from . import ArtifactDelta, hash_file
from .secret import _match  # reuse helper

PRIORITY = 6
ARTIFACT_KIND = "generated_artifact"

_PATTERNS = (
    "dist/**",
    "**/dist/**",
    "build/**",
    "**/build/**",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/node_modules/**",
    "**/.next/**",
    "**/coverage/**",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/.tox/**",
    "**/*.egg-info/**",
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
