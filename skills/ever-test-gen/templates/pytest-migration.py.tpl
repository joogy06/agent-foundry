# Template for a generated migration-confirmation pytest test.
# Substituted with the same keys as pytest-regression.py.tpl plus:
#   {package}, {old_ver}, {new_ver}, {bl_slug}, {breaking_line}

"""
EVO-generated test — CONFIDENCE: {confidence_level}
Migration confirmation — bug-for-bug oracle (HARD-RULE 2).
Source: {source_basis}
Wiring: {wiring_evidence}
"""

import pytest


@pytest.fixture
def legacy_oracle_{bl_slug}():
    """Capture pre-migration output. The migration must preserve this."""
    return {{}}  # TODO-IMPLEMENT-ORACLE


def test_migration_{bl_slug}_bug_for_bug(legacy_oracle_{bl_slug}):
    """Bug-for-bug check for breaking_line: {breaking_line}."""
    pytest.skip("evo-generated migration stub — fill ARRANGE/ACT/ASSERT")
