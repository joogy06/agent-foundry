"""config_key extractor — priority 5.

Catches changes to *.yaml, *.yml, *.toml, *.ini, *.json config files.
v1: file-level granularity only. Symbol-level (which key changed) is a
future extension once SCIP/structured-diff is wired in.
"""
from __future__ import annotations

from pathlib import Path

from . import ArtifactDelta, hash_file

PRIORITY = 5
ARTIFACT_KIND = "config_key"

_EXTS = (".yaml", ".yml", ".toml", ".ini", ".json", ".cfg", ".conf")


def matches(project_root: Path, path: str) -> bool:
    return path.lower().endswith(_EXTS)


def build(project_root: Path, path: str, operation: str) -> ArtifactDelta:
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return ArtifactDelta(
        kind=ARTIFACT_KIND,
        path=path,
        operation=operation,
        content_hash=hash_file(project_root, path) if operation != "removed" else None,
        extractor_meta={"ext": ext},
    )
