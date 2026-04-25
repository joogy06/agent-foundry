#!/usr/bin/env python3
"""plugin_loader.py — discover and load extractor plug-ins.

Per design 2026-04-14 §5.1 and references/plugin-author-guide.md.

Plug-ins live at:
    ~/.claude/skills/wiring-extract-static/extractors/<plugin_name>/
        plugin.json
        extractor.py

The loader:
- Scans the extractors/ directory
- Parses + validates plugin.json
- Imports extractor.py via importlib.util (isolated namespace)
- Returns {plugin_id: LoadedPlugin} dict

LoadedPlugin exposes:
    manifest : dict         (the plugin.json contents)
    extract_edges: Callable (the plug-in's main entry)
    source_dir: Path        (plug-in directory on disk)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REQUIRED_MANIFEST_FIELDS = [
    "id",
    "version",
    "target_framework",
    "languages",
    "edge_kinds",
    "is_fallback",
    "description",
]

VALID_EDGE_KINDS = {
    "calls", "routes_to", "emits", "listens",
    "persists_to", "reads_from", "renders",
    "depends_on", "imports",
}

VALID_LANGUAGES = {"python", "typescript", "javascript", "generic"}

# Activation modes (added 2026-04-18, WP-WIRING-02-BOOTSTRAP skill patch):
#   "framework" (default, back-compat) — non-fallback plug-in runs only if
#       its target_framework appears in detected frameworks.
#   "augment"  — plug-in runs regardless of detected frameworks, on files
#       whose language matches the plug-in's `languages`. Used for
#       framework-agnostic extractors (e.g. redis-streams xadd/xreadgroup).
#   "fallback" — reserved synonym for `is_fallback: true`. Left for forward
#       compatibility; current fallback plug-ins still set `is_fallback`.
VALID_ACTIVATION_MODES = {"framework", "augment", "fallback"}


@dataclass
class LoadedPlugin:
    manifest: Dict[str, Any]
    extract_edges: Callable[..., Any]
    source_dir: Path

    @property
    def id(self) -> str:
        return self.manifest["id"]

    @property
    def version(self) -> str:
        return self.manifest["version"]

    @property
    def is_fallback(self) -> bool:
        return bool(self.manifest.get("is_fallback", False))

    @property
    def languages(self) -> List[str]:
        return list(self.manifest.get("languages", []))

    @property
    def target_framework(self) -> str:
        return str(self.manifest.get("target_framework", ""))

    @property
    def activation_mode(self) -> str:
        """Plug-in activation mode. Defaults to "framework" when absent,
        or "fallback" when is_fallback=true (for back-compat with older
        plugin.json files that pre-date activation_mode)."""
        mode = self.manifest.get("activation_mode")
        if mode:
            return str(mode)
        if self.is_fallback:
            return "fallback"
        return "framework"

    @property
    def is_augment(self) -> bool:
        return self.activation_mode == "augment"


class PluginLoadError(Exception):
    """Raised when a plug-in is malformed. Loader records it and continues."""


def _validate_manifest(manifest: Dict[str, Any], plugin_dir: Path) -> None:
    missing = [f for f in REQUIRED_MANIFEST_FIELDS if f not in manifest]
    if missing:
        raise PluginLoadError(
            f"{plugin_dir.name}/plugin.json missing fields: {missing}"
        )
    # id must match dir
    if manifest["id"] != plugin_dir.name:
        raise PluginLoadError(
            f"{plugin_dir.name}/plugin.json: id={manifest['id']!r} does not match dir name"
        )
    # version must be semver MAJOR.MINOR.PATCH
    parts = str(manifest["version"]).split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise PluginLoadError(
            f"{plugin_dir.name}/plugin.json: version {manifest['version']!r} not semver"
        )
    # edge_kinds must be subset of allowed
    bad_kinds = [k for k in manifest["edge_kinds"] if k not in VALID_EDGE_KINDS]
    if bad_kinds:
        raise PluginLoadError(
            f"{plugin_dir.name}/plugin.json: unsupported edge_kinds {bad_kinds}"
        )
    bad_langs = [l for l in manifest["languages"] if l not in VALID_LANGUAGES]
    if bad_langs:
        raise PluginLoadError(
            f"{plugin_dir.name}/plugin.json: unsupported languages {bad_langs}"
        )
    mode = manifest.get("activation_mode")
    if mode is not None and mode not in VALID_ACTIVATION_MODES:
        raise PluginLoadError(
            f"{plugin_dir.name}/plugin.json: unsupported activation_mode {mode!r} "
            f"(allowed: {sorted(VALID_ACTIVATION_MODES)})"
        )


def _load_extractor_module(extractor_py: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, str(extractor_py))
    if spec is None or spec.loader is None:
        raise PluginLoadError(f"cannot import {extractor_py}")
    mod = importlib.util.module_from_spec(spec)
    # Namespace isolation: register under unique name to avoid conflicts across plug-ins
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_plugin(plugin_dir: Path) -> LoadedPlugin:
    """Load a single plug-in directory. Raises PluginLoadError on problems."""
    manifest_path = plugin_dir / "plugin.json"
    extractor_path = plugin_dir / "extractor.py"
    if not manifest_path.is_file():
        raise PluginLoadError(f"{plugin_dir}: missing plugin.json")
    if not extractor_path.is_file():
        raise PluginLoadError(f"{plugin_dir}: missing extractor.py")
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        raise PluginLoadError(f"{plugin_dir.name}/plugin.json: {e}") from e
    _validate_manifest(manifest, plugin_dir)
    mod_name = f"wiring_extractor_{manifest['id'].replace('-', '_')}"
    mod = _load_extractor_module(extractor_path, mod_name)
    fn = getattr(mod, "extract_edges", None)
    if fn is None or not callable(fn):
        raise PluginLoadError(
            f"{plugin_dir.name}/extractor.py: missing extract_edges() callable"
        )
    return LoadedPlugin(manifest=manifest, extract_edges=fn, source_dir=plugin_dir)


def discover_plugins(
    extractors_root: Optional[Path] = None,
) -> Dict[str, LoadedPlugin]:
    """Walk extractors/ and load every plug-in.

    Returns a dict keyed by plug-in id. Malformed plug-ins are skipped with
    a stderr note so the harness can continue with remaining plug-ins.

    The generic-treesitter fallback is included as a regular entry; the caller
    is responsible for prioritizing framework plug-ins over fallback per file.
    """
    if extractors_root is None:
        extractors_root = (
            Path.home() / ".claude" / "skills" / "wiring-extract-static" / "extractors"
        )
    plugins: Dict[str, LoadedPlugin] = {}
    if not extractors_root.is_dir():
        return plugins
    for entry in sorted(extractors_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        try:
            lp = load_plugin(entry)
        except PluginLoadError as e:
            sys.stderr.write(f"plugin_loader: skip {entry.name}: {e}\n")
            continue
        plugins[lp.id] = lp
    return plugins


def plugins_for_language(
    plugins: Dict[str, LoadedPlugin], language: str
) -> List[LoadedPlugin]:
    """Return all plug-ins that accept this language, non-fallback first.

    Augment-mode plug-ins are included alongside framework plug-ins; run.py
    is responsible for deciding when each fires (augment always fires,
    framework fires only when its target_framework matches detected set).
    """
    framework = [p for p in plugins.values() if not p.is_fallback and language in p.languages]
    fallback = [p for p in plugins.values() if p.is_fallback and (language in p.languages or "generic" in p.languages)]
    return framework + fallback


def augment_plugins_for_language(
    plugins: Dict[str, LoadedPlugin], language: str
) -> List[LoadedPlugin]:
    """Return augment-mode plug-ins matching this language (sorted by id).

    Augment plug-ins fire regardless of detected frameworks; they cover
    cross-framework concerns like Redis Streams, OpenTelemetry spans, etc.
    """
    return sorted(
        [p for p in plugins.values() if p.is_augment and language in p.languages],
        key=lambda p: p.id,
    )


def fallback_plugin(plugins: Dict[str, LoadedPlugin]) -> Optional[LoadedPlugin]:
    """Return the fallback plug-in, or None if not loaded."""
    for p in plugins.values():
        if p.is_fallback:
            return p
    return None


if __name__ == "__main__":
    # Self-test: discover and print summary
    discovered = discover_plugins()
    for pid, plugin in discovered.items():
        kind = "fallback" if plugin.is_fallback else "framework"
        langs = ",".join(plugin.languages)
        print(f"{pid}@{plugin.version} [{kind}] langs={langs} framework={plugin.target_framework}")
    if not discovered:
        print("(no plug-ins found)")
