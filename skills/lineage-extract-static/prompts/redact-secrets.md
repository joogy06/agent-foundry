# Redact Secrets

You are the FIRST of TWO redaction layers (HARD-RULE 4). This is the prompt-level pass; `scripts/redact.py` runs the regex-based pass afterwards. Belt + braces.

## Your task

Scan the project-aggregate JSON for any `evidence_snippet` that contains credentials, API keys, or secrets, and replace them with `<REDACTED:reason>` tokens.

## Patterns to redact

| Pattern | Replace with |
|---|---|
| `password\s*=\s*['"][^'"]+['"]` (Python / JS / YAML password=...) | `<REDACTED:password>` |
| `passwd\s*=\s*\S+` (Unix passwd-style) | `<REDACTED:password>` |
| `Authorization:\s*Bearer\s+\S+` (HTTP bearer token) | `<REDACTED:bearer>` |
| `Authorization:\s*Basic\s+\S+` (HTTP basic auth) | `<REDACTED:basic_auth>` |
| `aws_access_key_id\s*=\s*[A-Z0-9]{20}` | `<REDACTED:aws_access_key>` |
| `aws_secret_access_key\s*=\s*[A-Za-z0-9+/]{40,}` | `<REDACTED:aws_secret>` |
| `AKIA[0-9A-Z]{16}` (AWS access key shape standalone) | `<REDACTED:aws_access_key>` |
| `ghp_[a-zA-Z0-9]{36}` (GitHub PAT classic) | `<REDACTED:github_pat>` |
| `gho_[a-zA-Z0-9]{36}` (GitHub OAuth token) | `<REDACTED:github_oauth>` |
| `github_pat_[a-zA-Z0-9_]{82}` (GitHub fine-grained PAT) | `<REDACTED:github_pat>` |
| `sk-[a-zA-Z0-9]{48}` (OpenAI API key shape) | `<REDACTED:openai_key>` |
| `xoxb-[a-zA-Z0-9-]{50,}` (Slack bot token) | `<REDACTED:slack_bot_token>` |
| `xoxp-[a-zA-Z0-9-]{50,}` (Slack user token) | `<REDACTED:slack_user_token>` |
| Generic high-entropy `[A-Za-z0-9+/]{40,}={0,2}` matched ONLY when surrounding context strongly suggests a credential (token=, secret=, auth=, key=, password=) | `<REDACTED:high_entropy>` |

## Important — false-positive resistance

The generic base64-ish pattern (`[A-Za-z0-9+/]{40,}={0,2}`) is a MASSIVE false-positive risk. Apply it ONLY when one of these tokens is present within 30 chars BEFORE the candidate:

- `token=`, `token =`, `Token:`, `_token=`, `Token =`
- `secret=`, `secret =`, `_secret=`, `Secret:`
- `key=`, `key =`, `apikey=`, `api_key=`, `_key=`
- `auth=`, `auth =`, `_auth=`, `Auth:`
- `password=`, `password =`, `_password=`

If the high-entropy string is in a non-credential context (e.g. inside a base64-encoded payload, a SHA-256 hash inline, or part of a comment about a public encoding example), DO NOT redact it.

Hash-shaped tokens — SHA-256 (64 hex chars) and MD5 (32 hex chars) — are NOT credentials by themselves. Do NOT redact bare hashes unless they're labeled as credentials.

## Idempotency

If an `evidence_snippet` already contains `<REDACTED:...>` tokens (a previous run redacted it), DO NOT re-redact. The patterns should not match `<REDACTED:...>` strings.

## What you emit (one JSON object only)

Same structure as the input project-aggregate JSON, but with:
- Every `evidence_snippet` redacted in-place.
- A new `redaction_log` array recording every redaction:

```json
{
  ...same as input...,
  "edges": [
    /* same shape; evidence_snippet values may be redacted */
  ],
  "redaction_log": [
    {
      "source_file": "etl/load_users.py",
      "source_file_line": 412,
      "redaction_type": "password",
      "pattern_matched": "password=...",
      "snippet_before_redaction": "password='hunter2'",
      "snippet_after_redaction": "password=<REDACTED:password>"
    }
  ],
  "redaction_count": <count of redactions applied>
}
```

## Important — DO NOT include the actual secret in `redaction_log`

The `snippet_before_redaction` field should ALSO be redacted to `<REDACTED:password>` etc. — do NOT leak the credential in the log. The log records WHICH redaction was applied, not the secret itself.

Corrected example:
```json
{
  "snippet_before_redaction": "password=<REDACTED:password>",  // ← already redacted, even in the log
  "snippet_after_redaction": "password=<REDACTED:password>"
}
```

OR just record the pattern type without the snippet:
```json
{
  "source_file": "etl/load_users.py",
  "source_file_line": 412,
  "redaction_type": "password"
}
```

## Fail-closed posture (HARD-RULE 4)

If you encounter ANY of:
- A pattern you cannot regex-match cleanly because of encoding issues.
- A snippet that appears credential-bearing but doesn't match any pattern.
- An ambiguous high-entropy string you can't classify.

Emit a `gap` entry instead and set the edge's `evidence_snippet` to `<REDACTION_AMBIGUOUS>`:

```json
{
  "kind": "redaction_applied",
  "line": <source_file_line>,
  "description": "Ambiguous redaction at line X — see gap log for context"
}
```

The downstream `scripts/redact.py` provides the second-layer regex pass; even if you miss something, that catches it. But if BOTH layers are unsure, the run aborts (fail-closed).

## Anti-patterns — DO NOT DO

- Do NOT leak the actual secret value in `redaction_log` or anywhere else.
- Do NOT redact hash-shaped tokens (sha256, md5) just because they look high-entropy.
- Do NOT redact public-knowledge example values like `AKIAIOSFODNN7EXAMPLE` (the AWS docs example key) — actually, DO redact those (they match `AKIA[0-9A-Z]{16}`). False-positive on this example is acceptable; better safe.
- Do NOT remove edges. Only redact `evidence_snippet` content.
- Do NOT modify `source_dataset` or `target_job` namespaces or names — credentials don't appear there.

## You will now receive the identity-resolved project-aggregate JSON. Emit the redacted JSON + redaction log.
