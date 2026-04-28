"""secret extractor — priority 1 (highest).

Catches paths that look like secrets/credentials:
  **/secrets/*, **/secrets.*, **/credentials*, **/*service-account*,
  **/*.pem, **/*.key, **/.ssh/**, **/.env, **/.env.*

Note: there is intentional overlap with CONTRACT_SCOPE_CRITICAL_GLOBS in
gates.py — extractors classify the *kind*, while gates.py classifies
*severity*. An env_var path lives in `secret` only when it also matches
secret-style globs; ordinary env_var paths go to the env_var extractor.
"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from . import ArtifactDelta, hash_file

PRIORITY = 1
ARTIFACT_KIND = "secret"

_PATTERNS = (
    "**/secrets/*",
    "**/secrets.*",
    "**/credentials*",
    "**/*service-account*",
    "**/*.pem",
    "**/*.key",
    "**/.ssh/**",
    "**/.env",
    "**/.env.*",
)


def _match(path: str, pattern: str) -> bool:
    """fnmatch-with-globstar: treat ** as 'zero or more directories'."""
    # Normalize: strip leading "./"
    if path.startswith("./"):
        path = path[2:]
    # Convert pattern: **/ -> match any prefix
    parts = pattern.split("/")
    candidates = [path]
    if "**" in pattern:
        # very simple globstar: try with and without leading directories stripped
        segs = path.split("/")
        for i in range(len(segs)):
            candidates.append("/".join(segs[i:]))
    for cand in candidates:
        if fnmatch(cand, pattern.replace("**/", "*/").replace("**", "*")):
            return True
        if fnmatch(cand, pattern.replace("**/", "")):
            return True
    return False


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
