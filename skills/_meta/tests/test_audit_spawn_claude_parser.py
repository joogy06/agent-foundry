#!/usr/bin/env python3
"""test_audit_spawn_claude_parser.py — tasks.md #58 fix verification.

Covers `_meta/audit_spawn.py._extract_json_from_claude_output` across the
envelope shapes emitted by `claude -p --output-format json` over time:

  (a) Current CLI (claude 2.1.109) — top-level JSON **array** of stream
      messages. Final element is `{"type":"result","subtype":"success",
      "result":"<verdict text>"}`. Assistant content block carries the
      same text.
  (b) Legacy dict envelope — `{"result":"..."}` / `{"content":"..."}`.
  (c) Raw verdict (no envelope at all).
  (d) Prose-wrapped / fenced / malformed cases.

Also covers the shared `_parse_agent_text_as_json` helper and the Codex
extractor which now delegates to the same helper.

Run:
    python -m pytest /home/USER/.claude/skills/_meta/tests/test_audit_spawn_claude_parser.py -v
Or plain unittest:
    python -m unittest _meta.tests.test_audit_spawn_claude_parser -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# Add _meta/ to sys.path so we can import audit_spawn
SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import audit_spawn  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: realistic valid verdict as it appears in agent output
# ---------------------------------------------------------------------------

VALID_VERDICT = {
    "verdict": "pass",
    "structured_disagreements": [
        {"point": "coverage thin", "severity": "moderate", "location": "tests/unit/"},
        {"point": "no perf budget", "severity": "moderate", "location": "criteria[2]"},
        {"point": "fixture seed not logged", "severity": "minor", "location": "tests/fixtures/"},
    ],
    "evidence_verified": True,
    "reason": "all declared success criteria have at least one passing test.",
}


def _stream_array(agent_text: str, include_result: bool = True, include_assistant: bool = True):
    """Build a realistic current-CLI stream-json array envelope."""
    messages = [
        {
            "type": "system",
            "subtype": "init",
            "cwd": "/tmp/probe",
            "session_id": "abc-123",
            "model": "claude-opus-4-6",
        },
    ]
    if include_assistant:
        messages.append({
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_x",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": agent_text}],
                "stop_reason": None,
            },
            "session_id": "abc-123",
        })
    if include_result:
        messages.append({
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 1459,
            "num_turns": 1,
            "result": agent_text,
            "session_id": "abc-123",
        })
    return json.dumps(messages)


# ---------------------------------------------------------------------------
# Tests: current stream-json array shape (claude 2.1.109)
# ---------------------------------------------------------------------------


class TestStreamArrayEnvelope(unittest.TestCase):
    """Shape (a) — current CLI."""

    def test_clean_json_in_result_field(self):
        stdout = _stream_array(json.dumps(VALID_VERDICT))
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_fenced_json_in_result_field(self):
        # Some models fence their output even when told not to
        fenced = "```json\n" + json.dumps(VALID_VERDICT) + "\n```"
        stdout = _stream_array(fenced)
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_prose_wrapped_json_in_result_field(self):
        prose = (
            "Based on the bundle, my verdict is below.\n\n"
            + json.dumps(VALID_VERDICT)
            + "\n\nLet me know if you need more detail."
        )
        stdout = _stream_array(prose)
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_result_missing_fallback_to_assistant_content(self):
        """If the final result element is missing, walk back through
        assistant messages for the verdict text."""
        stdout = _stream_array(json.dumps(VALID_VERDICT), include_result=False)
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_result_unparseable_fallback_to_assistant_content(self):
        """Result text is garbage but assistant content holds valid JSON
        (edge case — should recover from the assistant block)."""
        messages = [
            {"type": "system", "subtype": "init"},
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": json.dumps(VALID_VERDICT)}],
                },
            },
            {"type": "result", "subtype": "success", "result": "totally not json {{{"},
        ]
        stdout = json.dumps(messages)
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_multiple_assistant_blocks_takes_last_parseable(self):
        messages = [
            {"type": "system", "subtype": "init"},
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "thinking out loud..."}]},
            },
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": json.dumps(VALID_VERDICT)}]},
            },
        ]
        stdout = json.dumps(messages)
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)


# ---------------------------------------------------------------------------
# Tests: legacy dict envelope (older CLI / forward-compat)
# ---------------------------------------------------------------------------


class TestLegacyDictEnvelope(unittest.TestCase):
    """Shape (b) — legacy dict envelope (pre-2.1.x)."""

    def test_result_field(self):
        stdout = json.dumps({"result": json.dumps(VALID_VERDICT), "session_id": "x"})
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_content_field(self):
        stdout = json.dumps({"content": json.dumps(VALID_VERDICT)})
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_text_field_fenced(self):
        fenced = "```\n" + json.dumps(VALID_VERDICT) + "\n```"
        stdout = json.dumps({"text": fenced})
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_envelope_is_verdict_directly(self):
        """Some older dumps had the verdict as the top-level dict itself."""
        stdout = json.dumps(VALID_VERDICT)
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)


# ---------------------------------------------------------------------------
# Tests: raw / malformed cases
# ---------------------------------------------------------------------------


class TestMalformedAndRaw(unittest.TestCase):
    """Shapes (c) and (d) — raw text + failure cases."""

    def test_raw_text_no_envelope(self):
        # CLI sometimes prints the agent's output without an envelope
        stdout = json.dumps(VALID_VERDICT)  # naked verdict, but still valid top-level dict
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_raw_text_with_prose_no_envelope(self):
        stdout = "Here you go:\n" + json.dumps(VALID_VERDICT)
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertEqual(parsed, VALID_VERDICT)

    def test_empty_input_returns_none(self):
        self.assertIsNone(audit_spawn._extract_json_from_claude_output(""))
        self.assertIsNone(audit_spawn._extract_json_from_claude_output("   \n\n  "))

    def test_garbage_returns_none(self):
        self.assertIsNone(
            audit_spawn._extract_json_from_claude_output("not json, not a envelope, nothing {{{ ]]]")
        )

    def test_stream_array_with_no_result_no_assistant_returns_none(self):
        stdout = json.dumps([
            {"type": "system", "subtype": "init"},
            {"type": "tool_use", "id": "tu_1"},
        ])
        self.assertIsNone(audit_spawn._extract_json_from_claude_output(stdout))

    def test_stream_array_with_non_json_result_and_non_json_assistant(self):
        stdout = json.dumps([
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello world"}]}},
            {"type": "result", "subtype": "success", "result": "hello world"},
        ])
        self.assertIsNone(audit_spawn._extract_json_from_claude_output(stdout))

    def test_non_string_input_returns_none(self):
        # Defensive: None or non-str should not explode
        self.assertIsNone(audit_spawn._extract_json_from_claude_output(None))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests: shared helper _parse_agent_text_as_json
# ---------------------------------------------------------------------------


class TestSharedParseHelper(unittest.TestCase):
    def test_clean_json(self):
        self.assertEqual(
            audit_spawn._parse_agent_text_as_json(json.dumps({"a": 1})),
            {"a": 1},
        )

    def test_fenced_json(self):
        self.assertEqual(
            audit_spawn._parse_agent_text_as_json('```json\n{"a": 1}\n```'),
            {"a": 1},
        )

    def test_bare_fenced(self):
        self.assertEqual(
            audit_spawn._parse_agent_text_as_json('```\n{"a": 1}\n```'),
            {"a": 1},
        )

    def test_prose_wrapped_brace_match(self):
        text = 'Here is my verdict: {"a": 1} -- thanks.'
        self.assertEqual(audit_spawn._parse_agent_text_as_json(text), {"a": 1})

    def test_empty_returns_none(self):
        self.assertIsNone(audit_spawn._parse_agent_text_as_json(""))
        self.assertIsNone(audit_spawn._parse_agent_text_as_json("   "))

    def test_non_string_returns_none(self):
        self.assertIsNone(audit_spawn._parse_agent_text_as_json(None))  # type: ignore[arg-type]
        self.assertIsNone(audit_spawn._parse_agent_text_as_json(123))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests: Codex extractor now delegates to the shared helper
# ---------------------------------------------------------------------------


class TestCodexExtractor(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(
            audit_spawn._extract_json_from_codex_output(json.dumps(VALID_VERDICT)),
            VALID_VERDICT,
        )

    def test_fenced(self):
        fenced = "```json\n" + json.dumps(VALID_VERDICT) + "\n```"
        self.assertEqual(audit_spawn._extract_json_from_codex_output(fenced), VALID_VERDICT)

    def test_prose(self):
        prose = "My verdict follows.\n" + json.dumps(VALID_VERDICT) + "\nDone."
        self.assertEqual(audit_spawn._extract_json_from_codex_output(prose), VALID_VERDICT)

    def test_malformed_returns_none(self):
        self.assertIsNone(audit_spawn._extract_json_from_codex_output("no verdict here"))


# ---------------------------------------------------------------------------
# Tests: end-to-end validate_verdict gate remains intact
# ---------------------------------------------------------------------------


class TestEndToEndWithValidator(unittest.TestCase):
    """The whole pipeline: extract → validate. Regression guard that the
    patched extractor still produces a dict the validator accepts."""

    def test_current_cli_shape_passes_validator(self):
        stdout = _stream_array(json.dumps(VALID_VERDICT))
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertIsNotNone(parsed)
        verdict, err = audit_spawn.validate_verdict(parsed)
        self.assertIsNone(err)
        self.assertEqual(verdict, VALID_VERDICT)

    def test_current_cli_shape_with_insufficient_disagreements_rejected(self):
        bad = dict(VALID_VERDICT)
        bad["structured_disagreements"] = VALID_VERDICT["structured_disagreements"][:2]
        stdout = _stream_array(json.dumps(bad))
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertIsNotNone(parsed)  # parser succeeded
        verdict, err = audit_spawn.validate_verdict(parsed)
        self.assertIsNone(verdict)
        self.assertIn("minimum is 3", err)  # validator caught it

    def test_unparseable_triggers_audit_unavailable_upstream(self):
        stdout = json.dumps([
            {"type": "system", "subtype": "init"},
            {"type": "result", "subtype": "success", "result": "I refuse to respond in JSON."},
        ])
        parsed = audit_spawn._extract_json_from_claude_output(stdout)
        self.assertIsNone(parsed)  # this is what triggers AUDIT_UNAVAILABLE in run_claude_auditor


if __name__ == "__main__":
    unittest.main(verbosity=2)
