"""Unit tests for llm_call.py — backend abstraction + budget guard."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import llm_call  # noqa: E402


def test_fake_backend_returns_canned() -> None:
    backend = llm_call.FakeBackend(
        canned_yaml="schema_version: \"1.0.0\"\n", tokens_in=100, tokens_out=50,
    )
    resp = backend.call("prompt", {"k": "v"}, model_id="claude-opus-4-7")
    assert resp.raw_yaml == "schema_version: \"1.0.0\"\n"
    assert resp.tokens_in == 100
    assert resp.tokens_out == 50
    assert resp.model_id == "claude-opus-4-7"


def test_fake_backend_records_calls() -> None:
    backend = llm_call.FakeBackend(canned_yaml="x: y\n")
    backend.call("p1", {"a": 1}, model_id="m")
    backend.call("p2", {"b": 2}, model_id="m")
    assert len(backend.calls) == 2


def test_fake_backend_can_raise() -> None:
    backend = llm_call.FakeBackend(fail_with=llm_call.LLMTransientError("net"))
    with pytest.raises(llm_call.LLMTransientError):
        backend.call("prompt", {})


def test_call_with_budget_blocks_pre_call() -> None:
    """Budget exhausted BEFORE the LLM is contacted."""
    backend = llm_call.FakeBackend(canned_yaml="x: y\n", tokens_in=1, tokens_out=1)
    with pytest.raises(llm_call.LLMBudgetExhausted):
        llm_call.call_with_budget(
            backend, "p", {},
            model_id="m",
            tokens_used_so_far=10000,
            tokens_budget=10500,  # remaining=500 < default max_tokens=4096
        )
    assert backend.calls == []  # Never called


def test_call_with_budget_passes_when_budget_ok() -> None:
    backend = llm_call.FakeBackend(canned_yaml="x: y\n")
    resp = llm_call.call_with_budget(
        backend, "p", {}, model_id="m",
        tokens_used_so_far=1000, tokens_budget=500000,
    )
    assert resp.raw_yaml == "x: y\n"


def test_call_with_budget_custom_max_tokens() -> None:
    backend = llm_call.FakeBackend(canned_yaml="x: y\n")
    # remaining = 1000; max_tokens=500 → ok
    resp = llm_call.call_with_budget(
        backend, "p", {}, model_id="m",
        tokens_used_so_far=9000, tokens_budget=10000, max_tokens=500,
    )
    assert resp.raw_yaml == "x: y\n"


def test_call_with_budget_tight_budget_blocks() -> None:
    backend = llm_call.FakeBackend(canned_yaml="x: y\n")
    # remaining = 100; max_tokens=500 → block
    with pytest.raises(llm_call.LLMBudgetExhausted) as exc:
        llm_call.call_with_budget(
            backend, "p", {}, model_id="m",
            tokens_used_so_far=9900, tokens_budget=10000, max_tokens=500,
        )
    assert "max_tokens" in str(exc.value)


def test_anthropic_backend_lazy_imports() -> None:
    """AnthropicBackend constructable without anthropic SDK installed."""
    backend = llm_call.AnthropicBackend()
    # Just constructing should not import anything
    assert backend._client is None


def test_anthropic_backend_raises_on_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ANTHROPIC_API_KEY is unset, _client_or_raise raises LLMPermanentError."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    backend = llm_call.AnthropicBackend()
    # Force the anthropic import to succeed via a stub
    import sys
    stub = type(sys)("anthropic")
    stub.Anthropic = lambda **k: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", stub)
    with pytest.raises(llm_call.LLMPermanentError) as exc:
        backend._client_or_raise()
    assert "API_KEY" in str(exc.value) or "api key" in str(exc.value).lower()


def test_default_backend_returns_anthropic() -> None:
    b = llm_call.default_backend()
    assert isinstance(b, llm_call.AnthropicBackend)


def test_exception_hierarchy() -> None:
    """Three exception classes exist and inherit from Exception."""
    assert issubclass(llm_call.LLMBudgetExhausted, Exception)
    assert issubclass(llm_call.LLMTransientError, Exception)
    assert issubclass(llm_call.LLMPermanentError, Exception)
