"""public_api extractor — priority 4.

Catches python source files that declare HTTP route handlers via the
common decorator patterns:
  @app.route(...)        # Flask
  @router.get(...) etc.  # FastAPI/Starlette
  @blueprint.route(...)  # Flask blueprint
"""
from __future__ import annotations

import re
from pathlib import Path

from . import ArtifactDelta, hash_file

PRIORITY = 4
ARTIFACT_KIND = "public_api"

# Common framework decorators
_ROUTE_RE = re.compile(
    r"^\s*@\w+\.(route|get|post|put|patch|delete|head|options|websocket)\(",
    re.MULTILINE,
)


def _has_route_decorator(project_root: Path, path: str) -> bool:
    if not path.endswith(".py"):
        return False
    p = project_root / path
    if not p.is_file():
        return False
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(_ROUTE_RE.search(text))


def matches(project_root: Path, path: str) -> bool:
    return _has_route_decorator(project_root, path)


def build(project_root: Path, path: str, operation: str) -> ArtifactDelta:
    return ArtifactDelta(
        kind=ARTIFACT_KIND,
        path=path,
        operation=operation,
        content_hash=hash_file(project_root, path) if operation != "removed" else None,
        extractor_meta={"detection": "route_decorator_regex"},
    )
