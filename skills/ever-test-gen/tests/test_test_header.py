"""Unit tests for test_header.py — mandatory confidence header generation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import test_header  # noqa: E402


def test_python_header_has_required_markers() -> None:
    h = test_header.build_header(
        language="python",
        confidence_level="characterization-aid",
        mode="version-upgrade",
        source_basis="intent-map",
        source_seed="S-001",
        wiring_evidence="snap:foo:bar",
    )
    assert "EVO-generated test" in h
    assert "CONFIDENCE: characterization-aid" in h
    assert "Requires user review" in h
    assert "evo_generated" in h
    assert "evo_requires_review" in h


def test_javascript_header_has_required_markers() -> None:
    h = test_header.build_header(
        language="javascript",
        confidence_level="cve-proof-of-fix",
        mode="cve-fix",
        source_basis="cve",
        source_seed="CVE-2026-1",
        wiring_evidence="snap:x:y",
    )
    assert "/**" in h
    assert "EVO-generated test" in h
    assert "CONFIDENCE: cve-proof-of-fix" in h
    assert "evo_requires_review" in h


def test_header_present_detects_evo_header() -> None:
    h = test_header.build_header(
        language="python", confidence_level="characterization-aid",
        mode="version-upgrade", source_basis="x", source_seed="S-1",
        wiring_evidence="y",
    )
    assert test_header.header_present(h) is True


def test_header_present_rejects_unrelated_text() -> None:
    assert test_header.header_present("import pytest\n\ndef test_x(): pass\n") is False


def test_header_present_rejects_partial_header() -> None:
    """Missing 'Requires user review' is rejected."""
    assert test_header.header_present(
        '"""EVO-generated test\nCONFIDENCE: x\n"""\n'
    ) is False


def test_invalid_confidence_level_raises() -> None:
    with pytest.raises(ValueError):
        test_header.build_header(
            language="python", confidence_level="totally-trustworthy",
            mode="version-upgrade", source_basis="x", source_seed="y",
            wiring_evidence="z",
        )


def test_invalid_mode_raises() -> None:
    with pytest.raises(ValueError):
        test_header.build_header(
            language="python", confidence_level="characterization-aid",
            mode="mode-z", source_basis="x", source_seed="y",
            wiring_evidence="z",
        )


def test_invalid_language_raises() -> None:
    with pytest.raises(ValueError):
        test_header.build_header(
            language="brainfuck", confidence_level="characterization-aid",
            mode="version-upgrade", source_basis="x", source_seed="y",
            wiring_evidence="z",
        )


def test_confidence_for_test_type() -> None:
    assert test_header.confidence_for_test_type("regression") == "characterization-aid"
    assert test_header.confidence_for_test_type("migration") == "characterization-aid"
    assert test_header.confidence_for_test_type("cve_proof") == "cve-proof-of-fix"
    assert test_header.confidence_for_test_type("unknown") == "characterization-aid"
