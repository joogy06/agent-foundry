"""test_host_detect.py — env-var matrix for the host-CLI detector."""
from __future__ import annotations

import detect_host_cli


def test_claudecode_env_var():
    host, _ = detect_host_cli.detect_from_env({"CLAUDECODE": "1"})
    assert host == "claude-code"


def test_claude_code_entrypoint_alone():
    host, _ = detect_host_cli.detect_from_env({"CLAUDE_CODE_ENTRYPOINT": "cli"})
    assert host == "claude-code"


def test_codex_env_var():
    host, _ = detect_host_cli.detect_from_env({"CODEX_VERSION": "0.130.0"})
    assert host == "codex"


def test_antigravity_cli_env_var():
    # TODO(agy): confirm agy host env var. ANTIGRAVITY_CLI_SESSION_ID is a
    # placeholder marker matching detect_host_cli._DETECTION_RULES until the
    # real agy session/host env var is verified.
    host, _ = detect_host_cli.detect_from_env({"ANTIGRAVITY_CLI_SESSION_ID": "abc-123"})
    assert host == "antigravity-cli"


def test_copilot_cli_via_cli_version():
    host, _ = detect_host_cli.detect_from_env({"COPILOT_CLI_VERSION": "1.0.21"})
    assert host == "copilot-cli"


def test_copilot_cli_via_token():
    host, _ = detect_host_cli.detect_from_env({"GH_COPILOT_TOKEN": "tok"})
    assert host == "copilot-cli"


def test_copilot_chat_vscode_marker():
    env = {
        "TERM_PROGRAM": "vscode",
        "VSCODE_PID": "12345",
        "GITHUB_COPILOT_CHAT": "1",
    }
    host, _ = detect_host_cli.detect_from_env(env)
    assert host == "copilot-chat"


def test_vscode_without_copilot_extension_is_unknown():
    env = {
        "TERM_PROGRAM": "vscode",
        "VSCODE_PID": "12345",
    }
    host, _ = detect_host_cli.detect_from_env(env)
    assert host == "unknown"


def test_precedence_claude_beats_codex():
    """If both CLAUDECODE and CODEX_VERSION are present (nested Codex inside
    a Claude session), the outer host wins because precedence is fixed."""
    env = {"CLAUDECODE": "1", "CODEX_VERSION": "0.130.0"}
    host, _ = detect_host_cli.detect_from_env(env)
    assert host == "claude-code"


def test_no_signals_returns_unknown():
    host, _ = detect_host_cli.detect_from_env({})
    assert host == "unknown"


def test_empty_string_does_not_match():
    """An env var that's set to the empty string should NOT trigger detection."""
    host, _ = detect_host_cli.detect_from_env({"CLAUDECODE": ""})
    assert host == "unknown"


def test_claudecode_wrong_value_does_not_match():
    """CLAUDECODE must equal '1' to match (defends against accidental exports)."""
    host, _ = detect_host_cli.detect_from_env({"CLAUDECODE": "false"})
    assert host == "unknown"


def test_signal_description_returned():
    host, signal = detect_host_cli.detect_from_env({"CLAUDECODE": "1"})
    assert host == "claude-code"
    assert "CLAUDECODE" in signal
