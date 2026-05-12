"""llm_fallback.py — bounded subprocess to codex/gemini for deprecation prose.

Per Codex challenger Rev 2: LLM output is `confidence_level: interpretive` ONLY.
NEVER feeds:
    - blocks_build computation
    - G_DEP_CURRENCY gate
    - scope_delta entries
    - pre-commit hook exit code

LLM enrichment is purely report-text decoration.

Public API:
    DeprecationVerdict (frozen dataclass)
    interpret_deprecation(text, package, *, prefer) -> DeprecationVerdict | None
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Literal, Optional

LLM_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class DeprecationVerdict:
    is_deprecated: bool
    successor: Optional[str]
    urgency: Literal["immediate", "near-term", "informational"]
    evidence: str
    consulted_model: str
    confidence_level: Literal["interpretive"] = "interpretive"


def _codex_available() -> bool:
    return shutil.which("codex") is not None


def _gemini_available() -> bool:
    return shutil.which("gemini") is not None


def _build_prompt(text: str, package: str) -> str:
    truncated = text[:2000]  # cap input
    return f"""You are reading a registry deprecation notice for package `{package}`.

Notice text (verbatim):
---
{truncated}
---

Return ONLY this JSON (no prose, no markdown fences):
{{
  "is_deprecated": true|false,
  "successor": "<package name>" or null,
  "urgency": "immediate"|"near-term"|"informational",
  "evidence": "<verbatim quote from notice>"
}}

Rules:
- "immediate" = security/breaking; users MUST migrate now
- "near-term" = author recommends migrating soon; no security issue
- "informational" = "we've moved" / aesthetic
- successor: ONLY if the notice names a specific replacement package; otherwise null
"""


def _try_codex(prompt: str) -> Optional[tuple]:
    """Returns (response_text, model_id) or None."""
    if not _codex_available():
        return None
    try:
        proc = subprocess.run(
            ["codex", "exec", "--ephemeral", "-s", "read-only", prompt],
            capture_output=True, text=True,
            timeout=LLM_TIMEOUT_S, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout, "codex")


def _try_gemini(prompt: str) -> Optional[tuple]:
    if not _gemini_available():
        return None
    env = os.environ.copy()
    # Host directive: force OAuth subscription path
    env["GOOGLE_CLOUD_PROJECT"] = ""
    env["GEMINI_API_KEY"] = ""
    try:
        proc = subprocess.run(
            ["gemini", "-m", "gemini-3.1-pro-preview", "-p", prompt],
            capture_output=True, text=True, env=env,
            timeout=LLM_TIMEOUT_S, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout, "gemini-3.1-pro-preview")


def _parse_verdict_json(text: str) -> Optional[dict]:
    """Extract JSON object from LLM output. Tolerates surrounding prose."""
    if not text:
        return None
    # Find the first '{' and matching '}'
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def interpret_deprecation(
    text: str,
    package: str,
    *,
    prefer: Literal["codex", "gemini"] = "codex",
) -> Optional[DeprecationVerdict]:
    """Interpret a deprecation notice via LLM subprocess.

    Returns None when:
    - both CLIs unavailable
    - subprocess fails / times out
    - LLM returns non-JSON or malformed JSON
    - LLM verdict is internally contradictory

    Never raises. Never blocks.
    """
    if not text or len(text.strip()) < 20:
        return None
    prompt = _build_prompt(text, package)

    # Try preferred first, then the other
    chain = [_try_codex, _try_gemini] if prefer == "codex" else [_try_gemini, _try_codex]
    for fn in chain:
        result = fn(prompt)
        if result is None:
            continue
        response, model = result
        parsed = _parse_verdict_json(response)
        if parsed is None:
            continue
        # Sanity-check the verdict
        is_dep = bool(parsed.get("is_deprecated", False))
        urgency = parsed.get("urgency", "informational")
        if urgency not in ("immediate", "near-term", "informational"):
            urgency = "informational"
        # Internal-contradiction check: not-deprecated but urgent
        if not is_dep and urgency == "immediate":
            return None
        successor = parsed.get("successor")
        if successor is not None and not isinstance(successor, str):
            successor = None
        evidence = parsed.get("evidence", "")[:500] if isinstance(
            parsed.get("evidence"), str) else ""
        return DeprecationVerdict(
            is_deprecated=is_dep,
            successor=successor,
            urgency=urgency,
            evidence=evidence,
            consulted_model=model,
        )
    return None
