# Prompt: redact-secrets (fail-closed, the FIRST of two redaction layers)

Legacy code is credential-DENSE: COBOL `EXEC SQL CONNECT ... IDENTIFIED BY`, DataStage
connector connection strings, ETL shell `PGPASSWORD=` / JDBC URLs / `aws_secret_access_key=`.
A code-intelligence index that leaks these is worse than useless. Redaction is
FAIL-CLOSED (HARD-RULE 1): if redaction cannot be performed, the artifact is aborted —
NEVER partially stored.

This prompt is the FIRST layer (you, during extraction). The SECOND layer is the
deterministic regex scrubber `scripts/redact.py`, which runs over your emitted index
before any store write. Both layers must clear. Do not rely on the scrubber to catch
what you can avoid emitting in the first place.

## Rule: never place a secret value in `evidence_snippet`
When a line contains a credential, emit the STRUCTURE but elide the secret:

- `EXEC SQL CONNECT TO PAYDB USER 'PAYUSR' IDENTIFIED BY 'sup3rs3cr3t'` →
  evidence_snippet: `EXEC SQL CONNECT TO PAYDB USER 'PAYUSR' IDENTIFIED BY '<REDACTED>'`
- `password = 's3cr3t'` → `password = '<REDACTED>'`
- `jdbc:db2://host:50000/PAYDB?password=hunter2` → `jdbc:db2://host:50000/PAYDB?password=<REDACTED>`
- `PGPASSWORD=topsecret psql ...` → `PGPASSWORD=<REDACTED> psql ...`
- `aws_secret_access_key=AKIA...` and any 40-char AWS secret → `<REDACTED>`
- Bearer / Basic auth headers, `ghp_*` / `sk-*` / `xox*-*` tokens → `<REDACTED>`

## Keep the non-secret structure
The symbol and relationship are still valuable — a `CONNECT TO PAYDB` is a `reads`/
config edge worth recording. Keep the table/DSN/host (those are not secrets), redact
ONLY the credential. Do NOT drop the whole occurrence.

## What is NOT a secret (do not over-redact)
- A `sha256` / `md5` hex digest standing alone.
- A table name, schema, host, port, database name, user name (user names are not
  passwords).
- A copybook member name, paragraph name, stage name.

## Fail-closed
If you encounter a line you believe contains a credential but you cannot confidently
separate the secret from the structure, redact the WHOLE value rather than risk
leaking it, and add a `gap` of kind `redaction_uncertain` with the line number. The
deterministic scrubber will also pass; if IT cannot parse the emitted index, the whole
artifact is aborted (never partial-stored).
