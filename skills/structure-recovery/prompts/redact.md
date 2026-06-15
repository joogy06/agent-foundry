# Redact Secrets

You are the FIRST of TWO redaction layers. This is the prompt-level pass; the
regex-based pass `scripts/redact.py` (reused from the lineage family) runs
afterwards. Belt + braces — **both** layers must clear for the pipeline to
proceed. This prompt is model-neutral (Claude Code / Codex CLI / GitHub Copilot
CLI / Antigravity CLI `agy`).

## Why this exists in a STRUCTURE skill

structure-recovery extracts table/record layouts, not data — so most findings
carry no secrets. But credentials still leak into structural artifacts:

- A DDL/connection script comment: `-- conn: db.prod IDENTIFIED BY 'hunter2'`.
- An `EXEC SQL CONNECT ... IDENTIFIED BY '<pw>'` near a copybook.
- A DataStage `.dsx` property bag carrying a DSN password.
- Any string a finding copied verbatim (`qualified_name`, `declared_type`,
  `gaps[].description`, an `evidence` pointer's surrounding text).

You scan the structure findings (and the accumulated catalog, when this prompt is
applied at that stage) for credential material and replace it with
`<REDACTED:reason>` tokens — without removing or altering the structural facts
(field names, ordinals, levels, PIC clauses, types, relationships).

## Patterns to redact

| Pattern | Replace with |
|---|---|
| `password\s*[:=]\s*['"][^'"]+['"]` (quoted password=/passwd=/pwd=) | `<REDACTED:password>` |
| `passwd\s*=\s*\S+` (Unix passwd-style, unquoted) | `<REDACTED:password>` |
| `IDENTIFIED BY\s+'[^']+'` (SQL/DB2 connect) | `IDENTIFIED BY '<REDACTED:password>'` |
| `Authorization:\s*Bearer\s+\S+` | `<REDACTED:bearer>` |
| `Authorization:\s*Basic\s+\S+` | `<REDACTED:basic_auth>` |
| `aws_access_key_id\s*=\s*[A-Z0-9]{20}` | `<REDACTED:aws_access_key>` |
| `aws_secret_access_key\s*=\s*[A-Za-z0-9+/]{40,}` | `<REDACTED:aws_secret>` |
| `AKIA[0-9A-Z]{16}` (AWS access-key shape, standalone) | `<REDACTED:aws_access_key>` |
| `ghp_[a-zA-Z0-9]{36}` (GitHub PAT classic) | `<REDACTED:github_pat>` |
| `gho_[a-zA-Z0-9]{36}` (GitHub OAuth token) | `<REDACTED:github_oauth>` |
| `github_pat_[a-zA-Z0-9_]{82}` (GitHub fine-grained PAT) | `<REDACTED:github_pat>` |
| `sk-[a-zA-Z0-9]{48}` (OpenAI API key shape) | `<REDACTED:openai_key>` |
| `xoxb-[a-zA-Z0-9-]{50,}` / `xoxp-[a-zA-Z0-9-]{50,}` (Slack tokens) | `<REDACTED:slack_bot_token>` / `<REDACTED:slack_user_token>` |
| Generic high-entropy `[A-Za-z0-9+/]{40,}={0,2}` — ONLY in a credential context | `<REDACTED:high_entropy>` |

These mirror `scripts/redact.py`'s catalog so the two layers agree.

## Important — false-positive resistance

The generic base64-ish pattern (`[A-Za-z0-9+/]{40,}={0,2}`) is a MASSIVE
false-positive risk. Apply it ONLY when one of these anchors is present within 30
chars BEFORE the candidate:

- `token=`, `token =`, `Token:`, `_token=`
- `secret=`, `secret =`, `_secret=`, `Secret:`
- `key=`, `key =`, `apikey=`, `api_key=`, `_key=`
- `auth=`, `auth =`, `_auth=`, `Auth:`
- `password=`, `password =`, `_password=`

Do NOT redact in a non-credential context. In a STRUCTURE skill especially:

- **A `file_sha256` (64 hex chars) is NOT a secret** — it is the content-address
  key. Never redact it.
- A SHA-256 (64 hex) or MD5 (32 hex) hash inline is NOT a credential by itself.
- A `pic_clause`, a `declared_type` (`VARCHAR(255)`, `Decimal(11,2)`), a column
  name, a `qualified_name`, an ordinal, or a level number is NEVER a secret —
  do not touch structural fields.

## Idempotency

If a string already contains `<REDACTED:...>` (a previous run redacted it), do
NOT re-redact. The patterns must not match `<REDACTED:...>` text. Re-running the
redaction over already-redacted findings yields byte-identical output.

## What you emit (one JSON object only)

The SAME structure as the input (a single finding, a per-file `summary.json`, or
the accumulated catalog — whatever you were given), with:

- Every credential-bearing string redacted **in place** (structural fields left
  intact).
- A new `redaction_log` array recording each redaction (metadata only — see the
  no-leak rule below):

```json
{
  "...": "same shape as input; structural facts unchanged",
  "redaction_log": [
    {
      "source_file": "ddl/connect.sql",
      "source_file_line": 12,
      "redaction_type": "password"
    }
  ],
  "redaction_count": 1
}
```

Also append a finding/catalog `gap` of kind `redaction_applied` at each redaction
site so the honesty trail is visible in the structure output itself:

```json
{ "kind": "redaction_applied", "line": 12, "description": "Credential elided at line 12 (password)" }
```

## Important — DO NOT include the actual secret anywhere

- Do NOT put the secret value in `redaction_log`, in a `gap.description`, or in
  any emitted string. Record the **type** of redaction, not the credential.
- `source_file` + `source_file_line` + `redaction_type` is sufficient. If you are
  tempted to include a `snippet_before`, redact it too (`password=<REDACTED:password>`).

## Fail-closed posture

If you encounter ANY of:

- A pattern you cannot match cleanly because of encoding issues.
- A string that appears credential-bearing but matches no pattern.
- An ambiguous high-entropy string you cannot classify.

…do NOT pass it through as-is. Replace the suspect substring with
`<REDACTION_AMBIGUOUS>` and emit a `gap`:

```json
{ "kind": "redaction_applied", "line": <line>, "description": "Ambiguous redaction at line <line> — flagged for review" }
```

The downstream `scripts/redact.py` provides the second-layer regex pass; even if
you miss something it catches it. But if BOTH layers are unsure, the run
**aborts** (fail-closed) — structure-recovery never emits partially-redacted
output. `redact.py` raises `SystemExit` on any pattern-application error and never
writes a partial file.

## Anti-patterns — DO NOT DO

- Do NOT leak the actual secret value in `redaction_log`, a gap, or any string.
- Do NOT redact a `file_sha256`, a bare sha256/md5 hash, a PIC clause, a SQL/DSX
  type, a column/table name, an ordinal, or a level — these are structure, not
  secrets.
- Do NOT remove or reorder fields/relationships. Only redact credential strings
  and append the `redaction_log` + `redaction_applied` gaps.
- Do NOT re-redact already-`<REDACTED:...>` text (idempotency).
- Do NOT alter `qualified_name` or `evidence.file_path` unless the path literally
  embeds a credential (rare; if so, redact only the credential substring).

## You will now receive the structure finding / catalog JSON. Emit the redacted JSON + redaction_log (structural facts unchanged).
