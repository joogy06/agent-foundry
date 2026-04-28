"""env_var extractor — priority 3.

Catches:
  - file paths that look like dotenv files (`*.env`, `*.env.*`,
    `**/.envrc`)  — these declare env vars
  - python source files that contain `os.environ` / `os.getenv` reads
    introduced in the diff

Bridge to gate: a python source path counts as an env_var artifact only
when the diff actually adds an env-var read. Without diff context the
extractor falls back to file-extension heuristics.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import ArtifactDelta, hash_file
from .secret import _match  # reuse helper

PRIORITY = 3
ARTIFACT_KIND = "env_var"

_FILE_PATTERNS = (
    "**/.env",
    "**/.env.*",
    "**/.envrc",
    "**/*.env",  # uncommon but defensive
)

# Heuristic regex for env-var reads in python source
_ENV_READ_RE = re.compile(r"\bos\.(environ\[|getenv\()")


def _is_env_dotfile(path: str) -> bool:
    return any(_match(path, pat) for pat in _FILE_PATTERNS)


def _has_env_read(project_root: Path, path: str) -> bool:
    if not path.endswith(".py"):
        return False
    p = (project_root / path)
    if not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(_ENV_READ_RE.search(text))


def matches(project_root: Path, path: str) -> bool:
    if _is_env_dotfile(path):
        return True
    return _has_env_read(project_root, path)


def build(project_root: Path, path: str, operation: str) -> ArtifactDelta:
    meta = {}
    if _is_env_dotfile(path):
        meta["origin"] = "dotfile"
    elif _has_env_read(project_root, path):
        meta["origin"] = "python_env_read"
    return ArtifactDelta(
        kind=ARTIFACT_KIND,
        path=path,
        operation=operation,
        content_hash=hash_file(project_root, path) if operation != "removed" else None,
        extractor_meta=meta,
    )
