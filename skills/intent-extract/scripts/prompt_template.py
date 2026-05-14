"""prompt_template.py — Locked LLM prompt template loader + hasher.

The template_hash field in functional-intent.v1 is the sha256 of the EXACT
bytes of templates/prompt-base.txt. Any change to the template invalidates
all caches by changing the cache key (which includes template_hash).

This module is import-light so cache.py + the test suite can compute the
hash without touching the LLM stack.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def template_path() -> Path:
    return _TEMPLATE_DIR / "prompt-base.txt"


def template_hash() -> str:
    """sha256 of the template file bytes. Stable across runs."""
    return hashlib.sha256(template_path().read_bytes()).hexdigest()


def render(
    component_id: str,
    source_paths_count: int,
    files_visible_count: int,
    static_edges_visible_count: int,
) -> str:
    """Substitute the four mustache-style placeholders.

    The template is otherwise static — no Jinja2, no eval, no globals.
    """
    text = template_path().read_text(encoding="utf-8")
    return (
        text
        .replace("{{component_id}}", str(component_id))
        .replace("{{source_paths_count}}", str(source_paths_count))
        .replace("{{files_visible_count}}", str(files_visible_count))
        .replace("{{static_edges_visible_count}}", str(static_edges_visible_count))
    )


def build_context_payload(
    component_id: str,
    contract_map_block: Dict[str, Any],
    source_paths: list,
    file_contents: Dict[str, str],
    static_jsonl_excerpt: list,
    *,
    max_files: int = 30,
) -> Dict[str, Any]:
    """Build the structured context object passed to the LLM alongside the prompt.

    Truncates `file_contents` to the first `max_files` entries (sorted by path)
    for deterministic token budget control.
    """
    sorted_files = sorted(file_contents.items(), key=lambda kv: kv[0])[:max_files]
    return {
        "component_id": component_id,
        "contract_map_block": contract_map_block,
        "source_paths": sorted(source_paths),
        "file_contents": dict(sorted_files),
        "static_jsonl_excerpt": static_jsonl_excerpt,
        "files_visible_count": len(sorted_files),
        "static_edges_visible_count": len(static_jsonl_excerpt),
        "source_paths_count": len(source_paths),
    }
