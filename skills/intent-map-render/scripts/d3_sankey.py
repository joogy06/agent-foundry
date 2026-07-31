"""d3_sankey.py — Mermaid sankey-beta emitter for version delta.

Reads api_delta JSON (from dep-currency-check / mode-b runs) and emits a
Mermaid sankey diagram showing breaking changes flowing through affected
components. Flow widths reflect call_count.

Triggers in mode-b when api_delta.breaking_lines is non-empty. >30
breaking_lines triggers a D2 Cytoscape fallback recommendation in the
advisory log (caller's responsibility — this skill just emits).
"""
from __future__ import annotations

from typing import Any, Dict, List


def render(api_delta: Dict[str, Any]) -> str:
    """Render D3 Mermaid sankey-beta block.

    Expects api_delta with optional shape:
      {
        "package": "pandas",
        "old_version": "1.5.3",
        "new_version": "2.2.3",
        "breaking_lines": ["..."],
        "affected_components": [
          {"name": "data-loader", "call_sites": 8},
          ...
        ]
      }
    """
    if not api_delta:
        return "<!-- D3: no api_delta provided -->\n"

    package = api_delta.get("package", "package")
    old_ver = api_delta.get("old_version", "old")
    new_ver = api_delta.get("new_version", "new")
    breaking_lines = api_delta.get("breaking_lines", []) or []
    affected = api_delta.get("affected_components", []) or []

    out: List[str] = []
    out.append("## D3 — Version Delta Sankey")
    out.append("")
    out.append(f"Package: `{package}` {old_ver} → {new_ver}")
    out.append("")
    out.append(f"Breaking changes: **{len(breaking_lines)}**")
    out.append("")
    if not affected:
        out.append("<!-- no affected components — sankey suppressed -->")
        return "\n".join(out) + "\n"

    out.append("```mermaid")
    out.append("sankey-beta")
    out.append("")
    # Deterministic sort
    sorted_affected = sorted(affected, key=lambda c: c.get("name", ""))
    upgrade_node = f"{package} {old_ver} → {new_ver}"
    for comp in sorted_affected:
        name = comp.get("name", "unknown")
        sites = int(comp.get("call_sites", 1) or 1)
        out.append(f'"{upgrade_node}","{name}",{sites}')
    out.append("```")
    out.append("")

    if len(breaking_lines) > 30:
        out.append(
            f"> Advisory: {len(breaking_lines)} breaking lines exceeds "
            "Mermaid sankey clarity threshold (30). Consider D2 Cytoscape "
            "for blast-radius detail."
        )
        out.append("")

    return "\n".join(out).rstrip() + "\n"
