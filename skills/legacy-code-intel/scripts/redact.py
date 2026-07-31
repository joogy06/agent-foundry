#!/usr/bin/env python3
"""redact.py — fail-closed secret-redaction pass for legacy-code-intel.

Forked from lineage-extract-static/scripts/redact.py (HARD-RULE 1). The pattern
catalog and fail-closed discipline are preserved verbatim; the ONLY adaptation is
the carrier: lineage redacts `edges[].evidence_snippet`; legacy-code-intel redacts
`occurrences[].evidence_snippet` in a code-index.v1 document. Legacy artifacts
(COBOL, DSX, ETL) are credential-DENSE (DB2 DSNs, FTP creds, connection strings),
so redaction runs BEFORE any store write and aborts the whole artifact on error —
NEVER a partial store (HARD-RULE 1, anti-pattern: emitting partial output after a
redaction error).

Two-layer redaction: the prompt-level instruction (prompts/redact-secrets.md) is
the first layer; this regex scrubber is the belt-and-braces second layer.

FAIL-CLOSED: any error during pattern application aborts via return-code 1 (CLI)
or a re-raised exception (library). NEVER emits partial output.

Idempotent: re-running on already-redacted text is a no-op (markers are skipped).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

# ---------------- Pattern catalog (forked verbatim from lineage) ---------------- #

_PWD_QUOTED = re.compile(
    r"""(?ix)
    \b(password|passwd|pwd)\b
    \s* [:=] \s*
    (['"])([^'"]+?)(\2)
    """,
)
_PWD_UNQUOTED = re.compile(
    r"""(?ix)
    \b(password|passwd|pwd)\b
    \s* [:=] \s*
    (\S+)
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

# Legacy-specific additions: connection-string / DSN passwords are extremely
# common in COBOL EXEC SQL CONNECT, DSX connector stages, and ETL shell scripts.
# These augment (do not replace) the inherited catalog.
_CONNECT_PWD = re.compile(
    r"""(?ix)
    \b(connect|identified \s+ by|using)\b
    \s+
    (['"]?)([^\s'"]{3,})(\2)
    """,
)
_JDBC_PWD = re.compile(
    r"""(?ix)
    ([?;&] \s* (?:password|pwd) \s* = )
    ([^;&\s]+)
    """,
)
# Environment-variable passwords common in ETL shell scripts: PGPASSWORD,
# MYSQL_PWD, ORACLE_PASSWORD, <ANY>_PASSWORD=, <ANY>_PWD=, etc. These do NOT
# word-boundary-match the bare `password` key (no boundary in PG|PASSWORD), so
# they need their own pattern. The key keeps a `PASSWORD`/`PWD`/`PASSWD` suffix.
_ENVVAR_PWD = re.compile(
    r"""(?x)
    \b([A-Z][A-Z0-9]*_?(?:PASSWORD|PASSWD|PWD))   # ENV-style key (e.g. PGPASSWORD, MYSQL_PWD)
    \s* = \s*
    (?:
        (")([^"]+)(")        # double-quoted value (may contain spaces)  -> groups 2,3,4
      | (')([^']+)(')        # single-quoted value (may contain spaces)  -> groups 5,6,7
      | ([^\s'";&]+)         # bare value (no spaces)                     -> group 8
    )
    """,
)

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
_SHA256_HEX = re.compile(r"\b[a-fA-F0-9]{64}\b")
_MD5_HEX = re.compile(r"\b[a-fA-F0-9]{32}\b")
_ALREADY_REDACTED = re.compile(r"<REDACTED:[a-z_]+>")


def _log(log: list, source_path: str, line: int, kind: str) -> None:
    log.append({"source_path": source_path, "line": line, "redaction_type": kind})


def _redact_quoted_pwd(text, log, src, line):
    def sub(m):
        if "<REDACTED:" in m.group(3):
            return m.group(0)
        _log(log, src, line, "password")
        return f"{m.group(1)}={m.group(2)}<REDACTED:password>{m.group(2)}"
    return _PWD_QUOTED.sub(sub, text)


def _redact_unquoted_pwd(text, log, src, line):
    def sub(m):
        if "<REDACTED:" in m.group(2):
            return m.group(0)
        _log(log, src, line, "password")
        return f"{m.group(1)}=<REDACTED:password>"
    return _PWD_UNQUOTED.sub(sub, text)


def _redact_auth_bearer(text, log, src, line):
    def sub(m):
        _log(log, src, line, "bearer")
        return "Authorization: Bearer <REDACTED:bearer>"
    return _AUTH_BEARER.sub(sub, text)


def _redact_auth_basic(text, log, src, line):
    def sub(m):
        _log(log, src, line, "basic_auth")
        return "Authorization: Basic <REDACTED:basic_auth>"
    return _AUTH_BASIC.sub(sub, text)


def _redact_aws_ak_kv(text, log, src, line):
    def sub(m):
        _log(log, src, line, "aws_access_key")
        q = m.group(1)
        return f"aws_access_key_id={q}<REDACTED:aws_access_key>{q}"
    return _AWS_AK_KV.sub(sub, text)


def _redact_aws_sk_kv(text, log, src, line):
    def sub(m):
        _log(log, src, line, "aws_secret")
        q = m.group(1)
        return f"aws_secret_access_key={q}<REDACTED:aws_secret>{q}"
    return _AWS_SK_KV.sub(sub, text)


def _redact_aws_ak_bare(text, log, src, line):
    def sub(m):
        _log(log, src, line, "aws_access_key")
        return "<REDACTED:aws_access_key>"
    return _AWS_AK_BARE.sub(sub, text)


def _redact_github(text, log, src, line):
    def s_classic(m):
        _log(log, src, line, "github_pat")
        return "<REDACTED:github_pat>"
    def s_oauth(m):
        _log(log, src, line, "github_oauth")
        return "<REDACTED:github_oauth>"
    def s_fg(m):
        _log(log, src, line, "github_pat")
        return "<REDACTED:github_pat>"
    text = _GH_PAT_CLASSIC.sub(s_classic, text)
    text = _GH_OAUTH.sub(s_oauth, text)
    text = _GH_PAT_FG.sub(s_fg, text)
    return text


def _redact_openai(text, log, src, line):
    def sub(m):
        _log(log, src, line, "openai_key")
        return "<REDACTED:openai_key>"
    return _OPENAI_KEY.sub(sub, text)


def _redact_slack(text, log, src, line):
    def s_bot(m):
        _log(log, src, line, "slack_bot_token")
        return "<REDACTED:slack_bot_token>"
    def s_user(m):
        _log(log, src, line, "slack_user_token")
        return "<REDACTED:slack_user_token>"
    text = _SLACK_BOT.sub(s_bot, text)
    text = _SLACK_USER.sub(s_user, text)
    return text


def _redact_connect_pwd(text, log, src, line):
    def sub(m):
        val = m.group(3)
        if "<REDACTED:" in val:
            return m.group(0)
        # Avoid eating obvious non-credentials like CONNECT TO <db-name> for COBOL.
        # We only redact when the keyword is a credential-bearing one.
        kw = m.group(1).lower()
        if kw in ("identified by", "using"):
            _log(log, src, line, "connection_password")
            return f"{m.group(1)} {m.group(2)}<REDACTED:connection_password>{m.group(2)}"
        return m.group(0)
    return _CONNECT_PWD.sub(sub, text)


def _redact_jdbc_pwd(text, log, src, line):
    def sub(m):
        if "<REDACTED:" in m.group(2):
            return m.group(0)
        _log(log, src, line, "connection_password")
        return f"{m.group(1)}<REDACTED:connection_password>"
    return _JDBC_PWD.sub(sub, text)


def _redact_envvar_pwd(text, log, src, line):
    def sub(m):
        key = m.group(1)
        # value is in group 3 (double-quoted), 6 (single-quoted), or 8 (bare)
        if m.group(3) is not None:
            quote, value = '"', m.group(3)
        elif m.group(6) is not None:
            quote, value = "'", m.group(6)
        else:
            quote, value = "", m.group(8)
        if "<REDACTED:" in value:
            return m.group(0)
        _log(log, src, line, "env_password")
        return f"{key}={quote}<REDACTED:env_password>{quote}"
    return _ENVVAR_PWD.sub(sub, text)


def _redact_high_entropy(text, log, src, line):
    matches = list(_HIGH_ENTROPY_CANDIDATE.finditer(text))
    if not matches:
        return text
    hash_positions = set()
    for m in _SHA256_HEX.finditer(text):
        hash_positions.add((m.start(), m.end()))
    for m in _MD5_HEX.finditer(text):
        hash_positions.add((m.start(), m.end()))
    out = text
    for m in reversed(matches):
        if (m.start(), m.end()) in hash_positions:
            continue
        cand = m.group(0)
        if re.fullmatch(r"[a-fA-F0-9]+", cand) and len(cand) in (40, 56, 64):
            continue
        window_start = max(0, m.start() - 30)
        window = out[window_start:m.start()]
        if _CREDENTIAL_CONTEXT_BEFORE.search(window):
            _log(log, src, line, "high_entropy")
            out = out[:m.start()] + "<REDACTED:high_entropy>" + out[m.end():]
    return out


# Most-specific first so the generic catch-all does not over-redact.
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
    _redact_envvar_pwd,
    _redact_jdbc_pwd,
    _redact_connect_pwd,
    _redact_high_entropy,
]

_ALL_SECRET_PATTERNS = [
    _PWD_QUOTED, _PWD_UNQUOTED, _AUTH_BEARER, _AUTH_BASIC, _AWS_AK_KV, _AWS_SK_KV,
    _AWS_AK_BARE, _GH_PAT_CLASSIC, _GH_OAUTH, _GH_PAT_FG, _OPENAI_KEY, _SLACK_BOT,
    _SLACK_USER, _ENVVAR_PWD, _JDBC_PWD, _CONNECT_PWD,
]


def redact_string(text: str, log: list, source_path: str = "", line: int = 0) -> str:
    """Apply the full pipeline to a string. Idempotent; fail-closed via the
    caller's try/except (any exception propagates)."""
    if not text:
        return text
    if _ALREADY_REDACTED.search(text) and not any(p.search(text) for p in _ALL_SECRET_PATTERNS):
        return text
    out = text
    for fn in _PIPELINE:
        out = fn(out, log, source_path, line)
    return out


def redact_index(index: dict) -> dict:
    """Redact every occurrence.evidence_snippet in a code-index.v1 document.

    Returns a NEW document (does not mutate the input) with redaction_log +
    redaction_count populated at the top level. Idempotent: a second run on an
    already-redacted index produces byte-identical output.

    Fail-closed: re-raises any exception encountered during redaction. The caller
    (ingest path / store.persist) MUST abort the artifact on exception — never
    partial-store.
    """
    out = copy.deepcopy(index)
    source_path = (out.get("artifact") or {}).get("source_path", "")

    new_log: list = []
    for occ in out.get("occurrences", []):
        snippet = occ.get("evidence_snippet", "")
        line = (occ.get("range") or {}).get("start_line", 0)
        occ["evidence_snippet"] = redact_string(snippet, new_log, source_path=source_path, line=line)

    existing_log = index.get("redaction_log", [])
    if not new_log:
        out["redaction_log"] = existing_log
        out["redaction_count"] = index.get("redaction_count", 0)
    else:
        out["redaction_log"] = list(existing_log) + new_log
        out["redaction_count"] = index.get("redaction_count", 0) + len(new_log)
    return out


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically via .tmp.<pid> + os.replace + fsync (HARD-RULE 3)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".tmp.", suffix=f".{os.getpid()}", dir=str(path.parent))
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("index_path", type=Path, help="Path to a code-index.v1 JSON (pre-redaction)")
    parser.add_argument("--output", type=Path, required=True, help="Output redacted index path")
    args = parser.parse_args(argv)

    if not args.index_path.exists():
        print(f"ERROR: index not found: {args.index_path}", file=sys.stderr)
        return 1
    try:
        with args.index_path.open("r", encoding="utf-8") as f:
            index = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"FAIL-CLOSED: cannot parse index JSON: {e}", file=sys.stderr)
        return 1
    try:
        redacted = redact_index(index)
    except Exception as e:  # FAIL-CLOSED
        print(f"FAIL-CLOSED: redaction error: {e}", file=sys.stderr)
        return 1
    try:
        atomic_write_json(args.output, redacted)
    except (PermissionError, OSError) as e:
        print(f"FAIL-CLOSED: cannot write output: {e}", file=sys.stderr)
        return 1

    print(json.dumps({"redaction_count": redacted["redaction_count"], "output_path": str(args.output)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
