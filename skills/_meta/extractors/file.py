"""file extractor — priority 99 (lowest, catch-all).

Always matches. Used when no higher-priority extractor recognised the
path. The gate consumes this and either raises severity to critical (if
the path matches CONTRACT_SCOPE_CRITICAL_GLOBS) or treats it as advisory.
"""
from __future__ import annotations

from pathlib import Path

from . import ArtifactDelta, hash_file

PRIORITY = 99
ARTIFACT_KIND = "file"


def matches(project_root: Path, path: str) -> bool:
    return True


def build(project_root: Path, path: str, operation: str) -> ArtifactDelta:
    return ArtifactDelta(
        kind=ARTIFACT_KIND,
        path=path,
        operation=operation,
        content_hash=hash_file(project_root, path) if operation != "removed" else None,
        extractor_meta={"catch_all": True},
    )
