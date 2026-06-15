"""WP-6 unit tests for the stdio adapter's MCP protocolVersion currency bump.

Covers the contract-map ``stdio-adapter`` component (protocol-staleness arm) and
the WP-6 acceptance criteria:

  * The ``protocolVersion`` advertised in ``initialize`` is the current
    negotiated MCP spec ("2025-11-25"), NOT the stale "2024-11-05".
  * A ``# FRESHNESS:v1`` anchor is present in pa_server.py so the S041 evergreen
    freshness loop nags on future protocol-version drift.
  * ``initialize`` / ``tools/list`` / ``tools/call`` are still handled (the bump
    is a low-risk currency change that breaks nothing in the dispatch surface).

These drive the REAL ``JsonRpcServer`` handlers (the ``server`` fixture) loaded
in-process via SourceFileLoader (conftest), so the test pins the actual served
constant, not a copy.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json
import re
from pathlib import Path

import pytest

# The MCP spec version this WP bumps TO, and the stale one it bumps OFF.
CURRENT_MCP_PROTOCOL_VERSION = "2025-11-25"
STALE_MCP_PROTOCOL_VERSION = "2024-11-05"

# pa_server.py on disk (for the source-level FRESHNESS anchor assertion).
PA_SERVER_PATH = Path(__file__).resolve().parent.parent.parent / "pa_server.py"


def _payload(result):
    """Decode the JSON text payload out of an MCP tools/call result."""
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# AC-1 — protocolVersion advertised in initialize is the current spec
# ---------------------------------------------------------------------------

class TestProtocolVersionBumped:
    def test_initialize_advertises_current_spec(self, server):
        """The `initialize` result advertises the current negotiated MCP spec."""
        result = server._handle_initialize({})
        assert result["protocolVersion"] == CURRENT_MCP_PROTOCOL_VERSION

    def test_initialize_no_longer_advertises_stale_2024_spec(self, server):
        """Regression pin: the dead "2024-11-05" version is gone."""
        result = server._handle_initialize({})
        assert result["protocolVersion"] != STALE_MCP_PROTOCOL_VERSION

    def test_protocol_version_constant_is_single_source_of_truth(self, pa_server_module):
        """The served version is driven by the module-level MCP_PROTOCOL_VERSION
        constant (not a hard-coded literal buried in the handler)."""
        assert pa_server_module.MCP_PROTOCOL_VERSION == CURRENT_MCP_PROTOCOL_VERSION

    def test_server_info_unchanged(self, server):
        """The bump is surgical: serverInfo name/version are untouched."""
        result = server._handle_initialize({})
        assert result["serverInfo"]["name"] == "pa-server"
        assert "capabilities" in result


# ---------------------------------------------------------------------------
# AC-2 — a FRESHNESS:v1 anchor is present so the evergreen loop nags on drift
# ---------------------------------------------------------------------------

class TestFreshnessAnchorPresent:
    def test_freshness_v1_anchor_present_in_source(self):
        text = PA_SERVER_PATH.read_text(encoding="utf-8")
        assert "FRESHNESS:v1" in text, "WP-6: missing FRESHNESS:v1 anchor in pa_server.py"

    def test_freshness_anchor_targets_mcp_protocol_version(self):
        """The anchor names the protocol-version subject so the evergreen loop
        knows WHAT it is watching when it nags."""
        text = PA_SERVER_PATH.read_text(encoding="utf-8")
        # The HTML-comment FRESHNESS block (universal convention, also valid
        # inside the module docstring) must mention the protocol-version subject.
        block = re.search(r"<!--\s*FRESHNESS:v1\s*\n(?P<body>.*?)\n?-->", text, re.DOTALL)
        assert block is not None, "WP-6: FRESHNESS:v1 block not found"
        assert "mcp-protocol-version" in block.group("body")

    def test_freshness_block_records_current_version(self):
        """The anchor's verified_against carries the version actually served, so a
        future bump that forgets to restamp the anchor is mechanically detectable."""
        text = PA_SERVER_PATH.read_text(encoding="utf-8")
        block = re.search(r"<!--\s*FRESHNESS:v1\s*\n(?P<body>.*?)\n?-->", text, re.DOTALL)
        assert CURRENT_MCP_PROTOCOL_VERSION in block.group("body")


# ---------------------------------------------------------------------------
# AC-3 — initialize / tools_list / tools_call still handled (no regression)
# ---------------------------------------------------------------------------

class TestDispatchSurfaceIntact:
    def test_initialize_still_handled(self, server):
        result = server._handle_initialize({})
        assert "protocolVersion" in result and "capabilities" in result

    def test_tools_list_still_handled_and_nonempty(self, server):
        result = server._handle_tools_list({})
        assert "tools" in result
        assert len(result["tools"]) > 0  # the ~18-20 tool surface survives

    def test_tools_call_still_dispatches(self, server):
        """A well-formed tools/call still flows through to pa-core and back."""
        result = server._handle_tools_call({"name": "pa_health", "arguments": {}})
        assert result["isError"] is False
        assert _payload(result)["transport"] == "json-rpc"

    def test_method_map_wires_initialize_and_tools(self, server):
        """The JSON-RPC method map still routes the three core methods."""
        for method in ("initialize", "tools/list", "tools/call"):
            assert method in server._method_map
