#!/usr/bin/env python3
"""redact.py — secret-redaction pass for lineage-extract-static (post-LLM).

Component: redact (WP-5 in S033 contract-map).

The SECOND of two redaction layers (HARD-RULE 4). The first layer is the
prompt-level instruction in `prompts/redact-secrets.md`. This script provides
regex-based scrubbing as belt-and-braces. Both layers must clear for the
pipeline to proceed.

FAIL-CLOSED: any error during pattern application aborts the run via SystemExit.
NEVER emits partial output.

Patterns (per design §11):
- password = '...'                → <REDACTED:password>
- passwd = ...                    → <REDACTED:password>
- Authorization: Bearer <token>   → <REDACTED:bearer>
- Authorization: Basic <token>    → <REDACTED:basic_auth>
- aws_access_key_id=AKIA...       → <REDACTED:aws_access_key>
- aws_secret_access_key=<base64>  → <REDACTED:aws_secret>
- AKIA[0-9A-Z]{16}                → <REDACTED:aws_access_key>
- ghp_/gho_/github_pat_           → <REDACTED:github_pat/oauth>
- sk-[a-zA-Z0-9]{48}              → <REDACTED:openai_key>
- xoxb-/xoxp- tokens              → <REDACTED:slack_*_token>
- Generic high-entropy ONLY when surrounded by token=/secret=/key=/auth=/password= context

False-positive mitigation:
- Generic high-entropy pattern requires a credential-context anchor within 30 chars BEFORE.
- Hash-shaped tokens (sha256 / md5) are NOT redacted by themselves.
- Already-redacted text (containing <REDACTED:...> markers) is left unchanged (idempotent).

CLI usage:
    redact.py <rollup_path> --output <path>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional


# ---------------- Pattern catalog ---------------- #
# Each pattern: (regex, replacement, label_for_log)

# A name with the surrounding `'` quotes; covers Python/JS/YAML password=...
_PWD_QUOTED = re.compile(
    r"""(?ix)
    \b(password|passwd|pwd)\b   # the literal key
    \s* [:=] \s*                # = or :
    (['"])([^'"]+?)(\2)         # quoted value (group 3 is the secret)
    """,
)

_PWD_UNQUOTED = re.compile(
    r"""(?ix)
    \b(password|passwd|pwd)\b
    \s* [:=] \s*
    (\S+)                       # unquoted value
    """,
)

_AUTH_BEARER = re.compile(
    r"""(?ix)
    \bAuthorization\b \s* : \s*
    Bearer \s+ ([A-Za-z0-9._\-~+/=]+)
    """,
)
_AUTH_BASIC = re.compile(
    r"""(?ix)
    \bAuthorization\b \s* : \s*
    Basic \s+ ([A-Za-z0-9+/=]+)
    """,
)

_AWS_AK_KV = re.compile(
    r"""(?ix)
    \baws_access_key_id\b \s* [:=] \s*
    (['"]?)([A-Z0-9]{20})\1
    """,
)
_AWS_SK_KV = re.compile(
    r"""(?ix)
    \baws_secret_access_key\b \s* [:=] \s*
    (['"]?)([A-Za-z0-9+/]{40,})\1
    """,
)
_AWS_AK_BARE = re.compile(r"\b(AKIA[0-9A-Z]{16})\b")

_GH_PAT_CLASSIC = re.compile(r"\b(ghp_[a-zA-Z0-9]{20,36})\b")
_GH_OAUTH = re.compile(r"\b(gho_[a-zA-Z0-9]{20,36})\b")
_GH_PAT_FG = re.compile(r"\b(github_pat_[a-zA-Z0-9_]{20,82})\b")

_OPENAI_KEY = re.compile(r"\b(sk-[a-zA-Z0-9]{40,48})\b")

_SLACK_BOT = re.compile(r"\b(xoxb-[A-Za-z0-9-]{50,})\b")
_SLACK_USER = re.compile(r"\b(xoxp-[A-Za-z0-9-]{50,})\b")

# Generic high-entropy with credential-context anchor.
# We use a separate two-pass approach for this one.
_HIGH_ENTROPY_CANDIDATE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_CREDENTIAL_CONTEXT_BEFORE = re.compile(
    r"""(?ix)
    \b(
        token|secret|api[_-]?key|key|auth|password|passwd|pwd
    )\b
    \s* [:=] \s*
    ['"]?
    """,
)

# Hash-shaped tokens to EXCLUDE from generic high-entropy redaction
_SHA256_HEX = re.compile(r"\b[a-fA-F0-9]{64}\b")
_MD5_HEX = re.compile(r"\b[a-fA-F0-9]{32}\b")

# Already-redacted markers (idempotency)
_ALREADY_REDACTED = re.compile(r"<REDACTED:[a-z_]+>")


def _redact_quoted_pwd(text: str, log: list, source_file: str, line: int) -> str:
    def sub(m: re.Match) -> str:
        # Idempotency guard: if the value is already <REDACTED:...>, skip
        val = m.group(3)
        if "<REDACTED:" in val:
            return m.group(0)
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "password"})
        # Keep the key and the quote chars; replace the value
        key = m.group(1)
        quote = m.group(2)
        return f"{key}={quote}<REDACTED:password>{quote}"
    return _PWD_QUOTED.sub(sub, text)


def _redact_unquoted_pwd(text: str, log: list, source_file: str, line: int) -> str:
    # Apply ONLY to remaining password= patterns the quoted regex didn't catch.
    # The quoted regex is greedy; if it matched, the substring is already
    # <REDACTED:password>. The unquoted regex matches the value-without-quote;
    # to avoid clobbering already-redacted, we explicitly skip lines containing it.
    def sub(m: re.Match) -> str:
        key = m.group(1)
        val = m.group(2)
        if "<REDACTED:" in val:
            return m.group(0)  # already redacted; leave alone
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "password"})
        return f"{key}=<REDACTED:password>"
    return _PWD_UNQUOTED.sub(sub, text)


def _redact_auth_bearer(text: str, log: list, source_file: str, line: int) -> str:
    def sub(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "bearer"})
        return "Authorization: Bearer <REDACTED:bearer>"
    return _AUTH_BEARER.sub(sub, text)


def _redact_auth_basic(text: str, log: list, source_file: str, line: int) -> str:
    def sub(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "basic_auth"})
        return "Authorization: Basic <REDACTED:basic_auth>"
    return _AUTH_BASIC.sub(sub, text)


def _redact_aws_ak_kv(text: str, log: list, source_file: str, line: int) -> str:
    def sub(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "aws_access_key"})
        q = m.group(1)
        return f"aws_access_key_id={q}<REDACTED:aws_access_key>{q}"
    return _AWS_AK_KV.sub(sub, text)


def _redact_aws_sk_kv(text: str, log: list, source_file: str, line: int) -> str:
    def sub(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "aws_secret"})
        q = m.group(1)
        return f"aws_secret_access_key={q}<REDACTED:aws_secret>{q}"
    return _AWS_SK_KV.sub(sub, text)


def _redact_aws_ak_bare(text: str, log: list, source_file: str, line: int) -> str:
    def sub(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "aws_access_key"})
        return "<REDACTED:aws_access_key>"
    return _AWS_AK_BARE.sub(sub, text)


def _redact_github(text: str, log: list, source_file: str, line: int) -> str:
    def sub_classic(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "github_pat"})
        return "<REDACTED:github_pat>"
    def sub_oauth(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "github_oauth"})
        return "<REDACTED:github_oauth>"
    def sub_fg(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "github_pat"})
        return "<REDACTED:github_pat>"
    text = _GH_PAT_CLASSIC.sub(sub_classic, text)
    text = _GH_OAUTH.sub(sub_oauth, text)
    text = _GH_PAT_FG.sub(sub_fg, text)
    return text


def _redact_openai(text: str, log: list, source_file: str, line: int) -> str:
    def sub(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "openai_key"})
        return "<REDACTED:openai_key>"
    return _OPENAI_KEY.sub(sub, text)


def _redact_slack(text: str, log: list, source_file: str, line: int) -> str:
    def sub_bot(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "slack_bot_token"})
        return "<REDACTED:slack_bot_token>"
    def sub_user(m: re.Match) -> str:
        log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "slack_user_token"})
        return "<REDACTED:slack_user_token>"
    text = _SLACK_BOT.sub(sub_bot, text)
    text = _SLACK_USER.sub(sub_user, text)
    return text


def _redact_high_entropy(text: str, log: list, source_file: str, line: int) -> str:
    """Generic high-entropy redaction ONLY when surrounded by credential context.

    Strategy:
    - For each candidate match position, look backwards up to 30 chars.
    - If a credential-context anchor (token=, secret=, etc.) is found, redact.
    - Exclude hash-shaped tokens (sha256 64-hex, md5 32-hex) — they're not credentials.
    """
    # Find all candidate positions
    matches = list(_HIGH_ENTROPY_CANDIDATE.finditer(text))
    if not matches:
        return text

    # Identify hash-shaped tokens to exclude
    hash_positions: set[tuple[int, int]] = set()
    for m in _SHA256_HEX.finditer(text):
        hash_positions.add((m.start(), m.end()))
    for m in _MD5_HEX.finditer(text):
        hash_positions.add((m.start(), m.end()))

    # Process in reverse so positions remain valid
    out = text
    for m in reversed(matches):
        # Skip hash-shaped
        if (m.start(), m.end()) in hash_positions:
            continue
        # Skip if value is purely hex (likely a hash even if not 64/32 length exactly)
        cand = m.group(0)
        if re.fullmatch(r"[a-fA-F0-9]+", cand) and len(cand) in (40, 56, 64):
            continue
        # Look backward for credential-context anchor within 30 chars
        window_start = max(0, m.start() - 30)
        window = out[window_start:m.start()]
        if _CREDENTIAL_CONTEXT_BEFORE.search(window):
            log.append({"source_file": source_file, "source_file_line": line, "redaction_type": "high_entropy"})
            out = out[:m.start()] + "<REDACTED:high_entropy>" + out[m.end():]
    return out


# Pipeline order matters: apply most-specific patterns FIRST so that the
# generic high-entropy catch-all doesn't over-redact (e.g. won't catch what
# the AWS specific patterns already redacted).
_PIPELINE = [
    _redact_quoted_pwd,
    _redact_unquoted_pwd,
    _redact_auth_bearer,
    _redact_auth_basic,
    _redact_aws_ak_kv,
    _redact_aws_sk_kv,
    _redact_aws_ak_bare,
    _redact_github,
    _redact_openai,
    _redact_slack,
    _redact_high_entropy,
]


def redact_string(
    text: str,
    log: list,
    source_file: str = "",
    line: int = 0,
) -> str:
    """Apply the full redaction pipeline to a string. Returns redacted text;
    log entries are appended to `log` in place.

    Idempotent: re-running redact_string on already-redacted text is a no-op.
    """
    if not text:
        return text
    # Already-redacted check: if the text consists only of redaction markers
    # + non-secret chars, skip (idempotency optimization).
    # The pipeline itself is idempotent because patterns won't match
    # <REDACTED:...> tokens, but we save work.
    if _ALREADY_REDACTED.search(text) and not any(
        p.search(text) for p in [
            _PWD_QUOTED, _PWD_UNQUOTED, _AUTH_BEARER, _AUTH_BASIC,
            _AWS_AK_KV, _AWS_SK_KV, _AWS_AK_BARE, _GH_PAT_CLASSIC, _GH_OAUTH,
            _GH_PAT_FG, _OPENAI_KEY, _SLACK_BOT, _SLACK_USER,
        ]
    ):
        return text
    out = text
    for fn in _PIPELINE:
        out = fn(out, log, source_file, line)
    return out


def redact_rollup(rollup: dict) -> dict:
    """Apply redaction to every evidence_snippet in the rollup. Returns a
    new rollup (does not mutate input) with redaction_log + redaction_count
    populated.

    Idempotent: a second run on an already-redacted rollup produces
    byte-identical output (same redaction_log, same redaction_count).

    Fail-closed: re-raises any exception encountered during redaction.
    """
    import copy
    out = copy.deepcopy(rollup)

    new_log: list = []
    for edge in out.get("edges", []):
        snippet = edge.get("evidence_snippet", "")
        source_file = edge.get("source_file", "")
        line = edge.get("evidence_line_start", 0)
        new_snippet = redact_string(snippet, new_log, source_file=source_file, line=line)
        edge["evidence_snippet"] = new_snippet

    # Idempotency: preserve existing redaction_log if present and no new
    # redactions occurred. Otherwise append.
    existing_log = rollup.get("redaction_log", [])
    if not new_log:
        # No new redactions: preserve existing log byte-identically
        out["redaction_log"] = existing_log
        out["redaction_count"] = rollup.get("redaction_count", 0)
    else:
        # New redactions: append to existing log
        out["redaction_log"] = list(existing_log) + new_log
        out["redaction_count"] = rollup.get("redaction_count", 0) + len(new_log)
    return out


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically. HARD-RULE 5."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".tmp.",
        suffix=f".{os.getpid()}",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rollup_path", type=Path, help="Path to project-aggregate JSON (pre-redaction)")
    parser.add_argument("--output", type=Path, required=True, help="Output redacted rollup path")
    args = parser.parse_args(argv)

    if not args.rollup_path.exists():
        print(f"ERROR: Rollup not found: {args.rollup_path}", file=sys.stderr)
        return 1

    try:
        with args.rollup_path.open("r", encoding="utf-8") as f:
            rollup = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # FAIL-CLOSED: cannot parse = abort
        print(f"FAIL-CLOSED: Cannot parse rollup JSON: {e}", file=sys.stderr)
        return 1

    try:
        redacted = redact_rollup(rollup)
    except Exception as e:
        # FAIL-CLOSED: any error during redaction = abort
        print(f"FAIL-CLOSED: Redaction error: {e}", file=sys.stderr)
        return 1

    try:
        atomic_write_json(args.output, redacted)
    except (PermissionError, OSError) as e:
        print(f"FAIL-CLOSED: Cannot write output: {e}", file=sys.stderr)
        return 1

    print(json.dumps({
        "redaction_count": redacted["redaction_count"],
        "output_path": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
