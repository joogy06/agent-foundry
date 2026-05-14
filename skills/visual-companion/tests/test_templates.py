"""Test that visual-companion templates are present + minimally well-formed."""
from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def test_existing_templates_present() -> None:
    """Original templates from before WP-6 still exist."""
    for fname in ("base.html", "comparison.html", "mockup.html", "options.html"):
        assert (TEMPLATES_DIR / fname).is_file()


def test_graph_cytoscape_html_present() -> None:
    """S032 WP-6: graph-cytoscape.html template exists."""
    assert (TEMPLATES_DIR / "graph-cytoscape.html").is_file()


def test_heatmap_html_present() -> None:
    """S032 WP-6: heatmap.html template exists."""
    assert (TEMPLATES_DIR / "heatmap.html").is_file()


def test_vendor_dir_present() -> None:
    """S032 WP-6: vendor directory with README exists."""
    vendor = TEMPLATES_DIR / "vendor"
    assert vendor.is_dir()
    assert (vendor / "README.md").is_file()


def test_graph_cytoscape_has_cdn_fallback() -> None:
    """Template falls back to unpkg CDN when vendor file missing (air-gap design)."""
    text = (TEMPLATES_DIR / "graph-cytoscape.html").read_text()
    assert "unpkg.com" in text
    assert "vendor/cytoscape.min.js" in text


def test_graph_cytoscape_has_truncation_banner() -> None:
    """Template surfaces truncation status from D2.json."""
    text = (TEMPLATES_DIR / "graph-cytoscape.html").read_text()
    assert "truncation-banner" in text


def test_heatmap_has_confidence_legend() -> None:
    """Heatmap renders the 3 confidence levels."""
    text = (TEMPLATES_DIR / "heatmap.html").read_text()
    assert "grounded" in text
    assert "interpretive" in text
    assert "degraded" in text


def test_heatmap_columns_match_d4() -> None:
    """Heatmap columns match D4 markdown table from intent-map-render."""
    text = (TEMPLATES_DIR / "heatmap.html").read_text()
    for col in ("Component", "function_class", "confidence",
                "test_seeds", "error_paths", "evidence_edges"):
        assert col in text


def test_templates_are_self_contained_html() -> None:
    """Both new templates have <!DOCTYPE html> and balanced <html></html>."""
    for fname in ("graph-cytoscape.html", "heatmap.html"):
        text = (TEMPLATES_DIR / fname).read_text()
        assert "<!DOCTYPE html>" in text
        assert "</html>" in text


def test_templates_have_no_external_css() -> None:
    """Templates are self-contained (no <link rel='stylesheet'>)."""
    for fname in ("graph-cytoscape.html", "heatmap.html"):
        text = (TEMPLATES_DIR / fname).read_text()
        # External fonts/icons OK, but no CSS links
        for line in text.split("\n"):
            if "rel=\"stylesheet\"" in line:
                pytest.fail(f"{fname} uses external stylesheet: {line.strip()}")
