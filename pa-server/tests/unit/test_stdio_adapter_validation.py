"""WP-2 unit tests for the stdio adapter's pre-dispatch validation + honest isError.

Covers the contract-map ``stdio-adapter`` component success criteria and T-ADP-1:

  * T-ADP-1 — Malformed arguments rejected before dispatch: a tools/call whose
    arguments violate the tool's JSON-Schema (missing required field / wrong
    type / bad enum) is rejected pre-dispatch with isError=true; pa-core is
    NEVER invoked.
  * Unknown / unregistered tool -> isError=true (never a silent success).
  * Handlers that RAISE pa_core typed errors map to isError=true honestly
    (no more isError:False-wrapped {"error": ...} dicts — BUG-1 fix).
  * A well-formed call still dispatches and returns isError=false.

These drive the REAL ``JsonRpcServer._handle_tools_call`` dispatcher (the
``server`` fixture), which is where the validation + isError contract lives.

stdlib + pytest only — no new pip deps (AMY D-plus lock).
"""
import json

import pytest


def _call(server, name, arguments):
    """Drive a tool through the real dispatcher; return the MCP result dict."""
    return server._handle_tools_call({"name": name, "arguments": arguments})


def _payload(result):
    """Decode the JSON text payload out of an MCP tools/call result."""
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# T-ADP-1 — Malformed arguments rejected BEFORE dispatch; pa-core never invoked
# ---------------------------------------------------------------------------

class TestAdp1MalformedArgumentsRejectedPreDispatch:
    def test_missing_required_field_is_rejected_pre_dispatch(
        self, server, pa_server_module, monkeypatch
    ):
        """T-ADP-1: pa_create_task requires `title`. A call missing it must be
        rejected with isError=true, and pa_core.create_task must NEVER run.
        """
        # Spy on the pa_core entry point: if validation lets a malformed call
        # through, this would be invoked and flip the flag.
        called = {"hit": False}

        def _boom(*_a, **_k):
            called["hit"] = True
            raise AssertionError("pa_core.create_task must not be invoked on a schema-invalid call")

        monkeypatch.setattr(pa_server_module.pa_core, "create_task", _boom)

        result = _call(server, "pa_create_task", {"priority": "high"})  # no title
        assert result["isError"] is True
        payload = _payload(result)
        assert "title" in payload["error"]  # message names the missing field
        assert payload.get("code") == "validation_error"
        assert called["hit"] is False  # pa-core was never invoked

    def test_wrong_type_field_is_rejected_pre_dispatch(
        self, server, pa_server_module, monkeypatch
    ):
        """pa_get_task.id is typed integer; a string id is a schema violation
        rejected pre-dispatch (pa_core.get_task never runs)."""
        called = {"hit": False}

        def _boom(*_a, **_k):
            called["hit"] = True
            raise AssertionError("pa_core.get_task must not be invoked on a schema-invalid call")

        monkeypatch.setattr(pa_server_module.pa_core, "get_task", _boom)

        result = _call(server, "pa_get_task", {"id": "not-an-int"})
        assert result["isError"] is True
        payload = _payload(result)
        assert payload.get("code") == "validation_error"
        assert called["hit"] is False

    def test_bad_enum_value_is_rejected_pre_dispatch(
        self, server, pa_server_module, monkeypatch
    ):
        """pa_create_task.priority is a closed enum; an out-of-enum value is a
        schema violation rejected pre-dispatch."""
        called = {"hit": False}
        monkeypatch.setattr(
            pa_server_module.pa_core,
            "create_task",
            lambda *_a, **_k: called.__setitem__("hit", True),
        )

        result = _call(
            server, "pa_create_task", {"title": "t", "priority": "ULTRA-MEGA-HIGH"}
        )
        assert result["isError"] is True
        assert _payload(result).get("code") == "validation_error"
        assert called["hit"] is False


# ---------------------------------------------------------------------------
# Unknown / unregistered tool
# ---------------------------------------------------------------------------

class TestUnknownTool:
    def test_unknown_tool_is_iserror_true(self, server):
        result = _call(server, "pa_definitely_not_a_tool", {})
        assert result["isError"] is True
        assert "Unknown tool" in _payload(result)["error"]

    def test_non_registered_attribute_is_not_callable_as_a_tool(self, server):
        # `pa_health` is registered, but a real Python attribute that is NOT in
        # TOOL_SCHEMAS (e.g. the dispatcher's own helper) must not be reachable
        # as a tool via getattr — the registry is the gate.
        result = _call(server, "_handle_initialize", {})
        assert result["isError"] is True
        assert "Unknown tool" in _payload(result)["error"]


# ---------------------------------------------------------------------------
# Honest isError on a RAISED typed error (BUG-1 fix verified at the adapter)
# ---------------------------------------------------------------------------

class TestHonestIsErrorOnRaise:
    def test_update_missing_task_raises_and_maps_to_iserror_true(self, server):
        result = _call(server, "pa_update_task", {"id": 424242, "status": "done"})
        assert result["isError"] is True
        payload = _payload(result)
        # The typed NotFoundError carries its stable code through the adapter.
        assert payload.get("code") == "not_found"

    def test_sync_missing_env_raises_and_maps_to_iserror_true(self, server, monkeypatch):
        monkeypatch.delenv("JIRA_BASE", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)
        result = _call(
            server,
            "pa_sync_jira",
            {"source_config": {"base_url_env": "JIRA_BASE", "token_env": "JIRA_TOKEN"}},
        )
        assert result["isError"] is True
        assert _payload(result).get("code") == "sync_error"


# ---------------------------------------------------------------------------
# Well-formed call still dispatches and returns isError=false
# ---------------------------------------------------------------------------

class TestWellFormedStillDispatches:
    def test_valid_create_task_dispatches_and_iserror_false(self, server):
        result = _call(server, "pa_create_task", {"title": "valid one", "priority": "high"})
        assert result["isError"] is False
        payload = _payload(result)
        assert payload["title"] == "valid one"
        assert isinstance(payload["id"], int)

    def test_health_with_empty_args_dispatches(self, server):
        result = _call(server, "pa_health", {})
        assert result["isError"] is False
        payload = _payload(result)
        assert payload["transport"] == "json-rpc"
