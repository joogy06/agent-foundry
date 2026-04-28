"""extractors — Artifact-kind extractor framework for G_CONTRACT_SCOPE.

Per design §7.2 / contracts.md CONTRACT-A1:
    Extractor priority order is LOCKED:
        secret > db_migration > env_var > public_api > config_key
        > generated_artifact > file
    First matching extractor wins. The `file` extractor is the catch-all.

Each extractor module exports:
    PRIORITY: int  (lower = higher priority; secret=1, file=99)
    ARTIFACT_KIND: ArtifactKind
    def matches(project_root: Path, path: str) -> bool
    def build(project_root: Path, path: str, operation: str) -> ArtifactDelta

Registry exports:
    get_extractors_in_priority_order() -> list[module]
    first_match(project_root: Path, path: str, operation: str) -> ArtifactDelta | None
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional

ArtifactKind = Literal[
    "secret",
    "db_migration",
    "env_var",
    "public_api",
    "config_key",
    "generated_artifact",
    "file",
]

OPERATIONS = ("added", "removed", "changed")


@dataclass(frozen=True)
class ArtifactDelta:
    kind: str
    path: str  # project-relative
    operation: str
    content_hash: Optional[str]  # sha256 of file content; None if removed
    extractor_meta: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d


def hash_file(project_root: Path, path: str) -> Optional[str]:
    """sha256 hex digest of file at <project_root>/<path>; None if file missing."""
    p = (project_root / path).resolve()
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _load_modules():
    """Lazy import to avoid circular references during module init."""
    from . import (  # noqa: F401  (used via locals)
        secret as _secret,
        db_migration as _db_migration,
        env_var as _env_var,
        public_api as _public_api,
        config_key as _config_key,
        generated_artifact as _generated_artifact,
        file as _file,
    )
    return [
        _secret, _db_migration, _env_var, _public_api,
        _config_key, _generated_artifact, _file,
    ]


def get_extractors_in_priority_order() -> List:
    mods = _load_modules()
    return sorted(mods, key=lambda m: m.PRIORITY)


def first_match(
    project_root: Path,
    path: str,
    operation: str,
) -> Optional[ArtifactDelta]:
    """Run extractors in LOCKED priority order; return the first ArtifactDelta produced.

    None means no extractor matched (should not happen because `file` is catch-all).
    """
    for mod in get_extractors_in_priority_order():
        if mod.matches(project_root, path):
            return mod.build(project_root, path, operation)
    return None


__all__ = [
    "ArtifactKind",
    "ArtifactDelta",
    "OPERATIONS",
    "hash_file",
    "get_extractors_in_priority_order",
    "first_match",
]
