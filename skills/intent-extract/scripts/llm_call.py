"""llm_call.py — Anthropic API wrapper for intent extraction.

Holds the LLM-side discipline:

  - temperature=0 for determinism
  - one call per (component_id, content_hash, model_id) combination
  - retry on transient errors (max 2 retries with exponential backoff)
  - budget check against EVO_MAX_TOKENS_PER_RUN
  - returns raw YAML string + token counts (no parsing — that's run.py's job)

The actual `anthropic` SDK call is isolated behind a thin abstraction so the
test suite can swap in a deterministic fake. Production code path is exercised
by integration tests (WP-9) only; unit tests use the fake.

This module never writes files. run.py owns all I/O.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol


class LLMBudgetExhausted(Exception):
    """Raised when EVO_MAX_TOKENS_PER_RUN is exceeded mid-run."""


class LLMTransientError(Exception):
    """Raised on retryable Anthropic API errors (network / 5xx / rate limit)."""


class LLMPermanentError(Exception):
    """Raised on non-retryable errors (auth / 4xx / API key missing)."""


@dataclass
class LLMResponse:
    """Single LLM call result. raw_yaml is the model's text body (whatever it
    emitted — we let schema_validate sort out validity downstream)."""
    raw_yaml: str
    tokens_in: int
    tokens_out: int
    model_id: str
    stop_reason: str


class LLMBackend(Protocol):
    """Abstract LLM interface. Production uses AnthropicBackend; tests use FakeBackend."""

    def call(
        self,
        prompt: str,
        context_payload: Dict[str, Any],
        *,
        model_id: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse: ...


class FakeBackend:
    """Deterministic test fake.

    Returns a canned YAML response built from `context_payload`. Useful for
    cache + manifest tests that should not require an Anthropic API key.
    """

    def __init__(self, canned_yaml: str = "", tokens_in: int = 1000,
                 tokens_out: int = 200, fail_with: Optional[Exception] = None) -> None:
        self.canned_yaml = canned_yaml
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.fail_with = fail_with
        self.calls: list[Dict[str, Any]] = []

    def call(
        self,
        prompt: str,
        context_payload: Dict[str, Any],
        *,
        model_id: str = "claude-opus-4-7",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append({
            "prompt_len": len(prompt),
            "context_payload": context_payload,
            "model_id": model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        if self.fail_with is not None:
            raise self.fail_with
        return LLMResponse(
            raw_yaml=self.canned_yaml,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            model_id=model_id,
            stop_reason="end_turn",
        )


class AnthropicBackend:
    """Production Anthropic API backend.

    Lazy-imports anthropic so this module is importable on hosts without the SDK
    installed (gates / test environments).
    """

    def __init__(self) -> None:
        self._client = None

    def _client_or_raise(self) -> Any:
        if self._client is None:
            try:
                import anthropic  # type: ignore[import-not-found]
            except ImportError as e:
                raise LLMPermanentError(
                    "anthropic SDK not installed; pip install anthropic"
                ) from e
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise LLMPermanentError("ANTHROPIC_API_KEY not set")
            self._client = anthropic.Anthropic(api_key=key)
        return self._client

    def call(
        self,
        prompt: str,
        context_payload: Dict[str, Any],
        *,
        model_id: str = "claude-opus-4-7",
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        client = self._client_or_raise()
        system = prompt
        user_msg = json.dumps(context_payload, sort_keys=True)

        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = client.messages.create(
                    model=model_id,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=[{"role": "user", "content": user_msg}],
                )
                # Extract text
                text_parts = []
                for block in resp.content:
                    if getattr(block, "type", None) == "text":
                        text_parts.append(block.text)
                return LLMResponse(
                    raw_yaml="".join(text_parts),
                    tokens_in=resp.usage.input_tokens,
                    tokens_out=resp.usage.output_tokens,
                    model_id=model_id,
                    stop_reason=str(resp.stop_reason),
                )
            except Exception as e:  # noqa: BLE001 — SDK exception hierarchy varies
                last_err = e
                msg = str(e).lower()
                # Classify
                if any(x in msg for x in ("auth", "401", "403", "api key")):
                    raise LLMPermanentError(str(e)) from e
                # Transient — backoff
                time.sleep(2 ** attempt)
        raise LLMTransientError(f"3 attempts failed: {last_err}")


def call_with_budget(
    backend: LLMBackend,
    prompt: str,
    context_payload: Dict[str, Any],
    *,
    model_id: str,
    tokens_used_so_far: int,
    tokens_budget: int,
    max_tokens: int = 4096,
) -> LLMResponse:
    """Wrapper that pre-checks the run-wide token budget.

    Raises LLMBudgetExhausted BEFORE the call if remaining budget is < max_tokens.
    The caller is responsible for soft-fail behaviour (HARD-RULE 8).
    """
    remaining = tokens_budget - tokens_used_so_far
    if remaining < max_tokens:
        raise LLMBudgetExhausted(
            f"remaining tokens {remaining} < max_tokens {max_tokens} "
            f"(used {tokens_used_so_far} of {tokens_budget})"
        )
    return backend.call(
        prompt, context_payload,
        model_id=model_id, max_tokens=max_tokens, temperature=0.0,
    )


def default_backend() -> LLMBackend:
    """Return production AnthropicBackend. Override in tests by passing FakeBackend."""
    return AnthropicBackend()
