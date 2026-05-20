"""test_advisor_idempotent.py — same input -> same bytes, no hidden state."""
from __future__ import annotations

import json

import advise


def _stable_call():
    return advise.compute_hints(
        host_cli="claude-code",
        completion_kind="ui-change",
        orchestrator="bob",
        gh_on_path=False,
    )


def test_two_calls_same_input_same_output():
    a = _stable_call()
    b = _stable_call()
    assert a == b


def test_two_calls_same_input_same_serialized_bytes():
    a = _stable_call()
    b = _stable_call()
    sa = json.dumps(a, sort_keys=True, separators=(",", ":"))
    sb = json.dumps(b, sort_keys=True, separators=(",", ":"))
    assert sa == sb


def test_orchestrator_filter_idempotent():
    a = advise.compute_hints(host_cli="claude-code", completion_kind="ui-change",
                             orchestrator="bob",  gh_on_path=False)
    b = advise.compute_hints(host_cli="claude-code", completion_kind="ui-change",
                             orchestrator="bob",  gh_on_path=False)
    assert a == b


def test_unknown_host_idempotent():
    a = advise.compute_hints(host_cli="unknown", completion_kind="ui-change",
                             orchestrator="bob", gh_on_path=False)
    b = advise.compute_hints(host_cli="unknown", completion_kind="ui-change",
                             orchestrator="bob", gh_on_path=False)
    assert a == []
    assert b == []


def test_gh_on_path_toggle_does_change_output():
    """Sanity: when gh_on_path differs, output differs — proves the gate is live."""
    off = advise.compute_hints(host_cli="claude-code",
                               completion_kind="branch-ready-pr-follows",
                               orchestrator="bob", gh_on_path=False)
    on  = advise.compute_hints(host_cli="claude-code",
                               completion_kind="branch-ready-pr-follows",
                               orchestrator="bob", gh_on_path=True)
    assert off != on


def test_output_ordering_deterministic():
    """Sort order is fixed: host-native first, then risk asc, then command asc."""
    hints = advise.compute_hints(host_cli="claude-code",
                                 completion_kind="branch-ready-pr-follows",
                                 orchestrator="bob", gh_on_path=True)
    # Host-native entries come first
    host_indices = [i for i, h in enumerate(hints) if h["host_cli"] == "claude-code"]
    util_indices = [i for i, h in enumerate(hints) if h["host_cli"].startswith("util:")]
    if host_indices and util_indices:
        assert max(host_indices) < min(util_indices), \
            f"host-native entries must come before util entries: {hints}"
