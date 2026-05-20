"""test_advise_gate.py — verify the active-CLI gate and matching logic."""
from __future__ import annotations

import advise


def test_unknown_host_returns_empty():
    hints = advise.compute_hints(
        host_cli="unknown",
        completion_kind="ui-change",
        orchestrator="bob",
    )
    assert hints == []


def test_claude_code_ui_change_bob_returns_run_and_verify():
    hints = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="ui-change",
        orchestrator="bob",
        gh_on_path=False,
    )
    commands = [h["command"] for h in hints]
    assert "/run" in commands
    assert "/verify" in commands
    # Every hint must declare host_cli=claude-code (no util:gh leakage when we
    # opted gh out).
    for h in hints:
        assert h["host_cli"] == "claude-code"


def test_no_matching_kind_returns_empty():
    hints = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="this-kind-does-not-exist",
        orchestrator="bob",
    )
    assert hints == []


def test_orchestrator_filter_excludes_non_matching():
    """forge-only affordances should NOT appear when orchestrator='bob'."""
    hints = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="design-finalized-medium-or-higher",
        orchestrator="bob",
        gh_on_path=False,
    )
    # The matching affordance is /ultrareview with orchestrator: [forge].
    # With orchestrator='bob' we should see nothing from the claude-code registry.
    for h in hints:
        assert h["host_cli"] != "claude-code", \
            f"unexpected claude-code hint for bob: {h}"


def test_wildcard_orchestrator_matches_anyone():
    """/compact has orchestrator: ['*'] so it should match any orchestrator."""
    hints = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="context-window-pressure",
        orchestrator="random-orchestrator-name",
        gh_on_path=False,
    )
    assert any(h["command"] == "/compact" for h in hints)


def test_no_orchestrator_argument_matches_everything():
    """When orchestrator is None, every matching completion_kind passes."""
    hints = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="ui-change",
        orchestrator=None,
        gh_on_path=False,
    )
    commands = [h["command"] for h in hints]
    assert "/verify" in commands


def test_severity_cap_low_filters_high_risk():
    """When severity_cap='low', high-risk affordances must be excluded."""
    hints_high = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="design-finalized-medium-or-higher",
        orchestrator="forge",
        severity_cap="high",
        gh_on_path=False,
    )
    hints_low = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="design-finalized-medium-or-higher",
        orchestrator="forge",
        severity_cap="low",
        gh_on_path=False,
    )
    # /ultrareview is risk_class: high
    assert any(h["command"] == "/ultrareview" for h in hints_high)
    assert all(h["command"] != "/ultrareview" for h in hints_low)


def test_gh_utility_only_surfaces_when_on_path():
    hints_off = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="branch-ready-pr-follows",
        orchestrator="bob",
        gh_on_path=False,
    )
    hints_on = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="branch-ready-pr-follows",
        orchestrator="bob",
        gh_on_path=True,
    )
    gh_commands_off = [h for h in hints_off if h["host_cli"].startswith("util:gh")]
    gh_commands_on  = [h for h in hints_on  if h["host_cli"].startswith("util:gh")]
    assert gh_commands_off == []
    assert len(gh_commands_on) >= 1


def test_codex_registry_does_not_leak_to_claude():
    """Even if a completion kind exists in codex.yaml only, it must not
    surface when host_cli=claude-code."""
    hints = advise.compute_hints(
        host_cli="claude-code",
        completion_kind="diff-produced-ready-to-apply",  # codex-only
        orchestrator="bob",
        gh_on_path=False,
    )
    for h in hints:
        assert h["host_cli"] != "codex", \
            f"codex hint leaked into claude-code session: {h}"


def test_codex_host_returns_codex_hints():
    """When host=codex, codex.yaml affordances surface."""
    hints = advise.compute_hints(
        host_cli="codex",
        completion_kind="diff-produced-ready-to-apply",
        orchestrator="bob",
        gh_on_path=False,
    )
    commands = [h["command"] for h in hints]
    assert any("codex apply" in c for c in commands)


def test_severity_cap_invalid_raises():
    import pytest
    with pytest.raises(ValueError):
        advise.compute_hints(
            host_cli="claude-code",
            completion_kind="ui-change",
            severity_cap="catastrophic",
        )


def test_copilot_chat_stub_returns_empty():
    """The copilot-chat registry is a stub with affordances: []."""
    hints = advise.compute_hints(
        host_cli="copilot-chat",
        completion_kind="ui-change",
        orchestrator="bob",
        gh_on_path=False,
    )
    assert hints == []
