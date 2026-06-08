#!/usr/bin/env python3
"""component_resolver.py — resolve file paths to contract-map component ids.

Per design 2026-04-14 §4.1.1 canonical component naming invariant.

Reads progress/contract-map.yaml and builds a list of
    (component_id, [glob_pattern_resolved_to_abs_path, ...])
pairs. Given a file path, returns the first component whose source_paths
glob matches, or None if the file is unmapped.

The contract-map uses globs with leading ``~/`` (home-relative) or
project-relative entries. Both are supported. Tilde is expanded; project-
relative entries are resolved against ``project_dir``.

The skill plug-ins call ``resolver.resolve(file_path)`` via a curried
helper passed into extract_edges; the resolver itself is stateful only
for caching.
"""
from __future__ import annotations

import fnmatch
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    sys.stderr.write("FATAL: pyyaml not installed. component_resolver requires pyyaml.\n")
    raise


class ComponentResolver:
    """Resolve filesystem paths to contract-map component ids via glob matching.

    code-comprehension (§12 C5): when the map carries a canonical expanded file
    inventory (``components[].source_files`` — explicit project-relative files), the
    resolver matches against THAT exact file set first (so wiring resolution and
    intent-extract agree on membership), falling back to the directory-prefix globs
    in ``source_paths`` only for files not in the canonical inventory. A real signed
    contract-map has no ``source_files`` key, so this path is inert there (the glob
    behavior is byte-identical to before).
    """

    def __init__(self, contract_map_path: Path, project_dir: Path) -> None:
        self.contract_map_path = contract_map_path
        self.project_dir = project_dir.resolve()
        self._rules: List[Tuple[str, List[str]]] = []  # (component_id, [glob_strings])
        # canonical inventory: abs_file_path -> component_id (C5)
        self._canonical: Dict[str, str] = {}
        self.unmapped_paths: List[str] = []
        self._load()

    def _expand_glob(self, glob_pattern: str) -> str:
        """Expand ~, resolve project-relative, and normalize trailing slash.

        The trailing "/" convention means "directory and everything under it".
        We detect it on the raw string (before pathlib normalization strips it)
        and convert to "/**" to keep the prefix-match semantics.
        """
        g = glob_pattern.strip()
        trailing_dir = g.endswith("/")
        if g.startswith("~/"):
            g = os.path.expanduser(g)
        elif not g.startswith("/"):
            # Preserve trailing slash by rejoining after Path normalizes
            g = str(self.project_dir / g.rstrip("/"))
            if trailing_dir:
                g = g + "/"
        if trailing_dir and not g.endswith("/"):
            g = g + "/"
        if g.endswith("/"):
            g = g + "**"
        return g

    def _load(self) -> None:
        if not self.contract_map_path.is_file():
            return
        try:
            doc = yaml.safe_load(self.contract_map_path.read_text()) or {}
        except yaml.YAMLError:
            return
        for comp in (doc.get("components") or []):
            cid = comp.get("id")
            if not cid:
                continue
            globs = [self._expand_glob(p) for p in (comp.get("source_paths") or [])]
            if globs:
                self._rules.append((cid, globs))
            # Canonical expanded file inventory (C5) — explicit project-relative files.
            for sf in (comp.get("source_files") or []):
                abs_sf = str((self.project_dir / sf).resolve())
                # first component wins (exclusive coverage is enforced by the partitioner)
                self._canonical.setdefault(abs_sf, cid)

    @staticmethod
    def _glob_match(path: str, pattern: str) -> bool:
        """Match a path against a glob-with-double-star pattern.

        Supports the subset we need: plain globs plus trailing /** which matches any
        path whose prefix is the directory component. fnmatch itself does not
        understand **, so we translate trailing /** into a prefix match.
        """
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            return path == prefix or path.startswith(prefix + "/") or path.startswith(prefix.rstrip("/") + "/")
        return fnmatch.fnmatch(path, pattern)

    def resolve(self, file_path: Path) -> Optional[str]:
        """Return the component id for file_path, or None.

        C5: the canonical expanded file inventory (``source_files``) is consulted
        FIRST — an exact file→component map — so wiring resolution matches
        intent-extract's retained-files semantics. Directory-prefix globs are the
        fallback for files not in the inventory (and the only path for a real signed
        map, which carries no ``source_files``).
        """
        abs_str = str(Path(file_path).resolve())
        cid = self._canonical.get(abs_str)
        if cid is not None:
            return cid
        for cid, globs in self._rules:
            for g in globs:
                if self._glob_match(abs_str, g):
                    return cid
        # Cache unmapped
        if abs_str not in self.unmapped_paths:
            self.unmapped_paths.append(abs_str)
        return None

    def rule_count(self) -> int:
        return len(self._rules)


def make_resolver(project_dir: Path) -> ComponentResolver:
    """Convenience: open the contract map at the conventional path.

    We prefer ``$project_dir/progress/contract-map.yaml`` (per S014 convention);
    absent that, we return an empty resolver (everything is unmapped, which the
    plug-in records as gaps rather than aborting extraction).
    """
    candidate = project_dir / "progress" / "contract-map.yaml"
    return ComponentResolver(candidate, project_dir)


class _NullResolver:
    """A resolver that maps NOTHING (clean ``unmapped_path:*`` first pass).

    Used for ``--contract-map-path none``. Fallback to progress/contract-map.yaml is
    PROHIBITED (§12 C5) so a stale partial map can't contaminate the first pass.
    Records every queried path as unmapped (the first-pass behavior the orchestrator
    expects).
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir.resolve()
        self.unmapped_paths: List[str] = []

    def resolve(self, file_path: Path) -> Optional[str]:
        abs_str = str(Path(file_path).resolve())
        if abs_str not in self.unmapped_paths:
            self.unmapped_paths.append(abs_str)
        return None

    def rule_count(self) -> int:
        return 0


def make_resolver_for_path(project_dir: Path, contract_map_arg: Optional[str]):
    """Build a resolver per the ``--contract-map-path`` argument.

      (None)  → progress/contract-map.yaml (default, byte-identical to make_resolver)
      'none'  → _NullResolver (NO resolution; fallback to progress/ PROHIBITED)
      <PATH>  → ComponentResolver(<PATH>) (e.g. the synthetic map; canonical-inventory aware)
    """
    if contract_map_arg is None:
        return make_resolver(project_dir)
    if contract_map_arg == "none":
        return _NullResolver(project_dir)
    return ComponentResolver(Path(contract_map_arg), project_dir)
