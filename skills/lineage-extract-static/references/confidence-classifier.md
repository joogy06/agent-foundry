# Confidence Classifier — Bright-Line Rules

Reference for HARD-RULE 2: every edge emitted by `prompts/analyze-file.md` MUST be classified into one of three tiers using these bright-line rules. The prompt template forbids `grounded` when any interpolation/dynamic-resolution marker is present.

## The three tiers

| Tier | Rule | OL emission style |
|---|---|---|
| **grounded** | Literal string token (path/table-name) with NO interpolation; AND all symbols resolve in the local context (function args, top-level constants visible in the chunk). | Solid edge; feeds gate decisions; default-visible in HTML. |
| **inferred** | Name-resolution heuristic — env-var resolved against in-repo `.env` / `config.yaml`; OR relative path resolved against `__file__`; OR SQL `FROM <alias>` resolved against same-file CTE. | Dashed edge; advisory; default-visible but visually distinct. |
| **speculative** | String interpolation (f-string / `.format()` / `%`-format / template literal) within ±20 lines; OR env-var without in-repo resolution; OR unresolved symbol; OR `SELECT *` without schema metadata; OR basename-only match. | Dotted edge; collapsed by default in HTML; NEVER feeds gates. |

## Worked examples — grounded

```python
# grounded — literal path
df = pd.read_csv("data/landing/users.csv")
```
→ edge `reads_from` with `source_dataset = file://repo/data/landing/users.csv`, `confidence: grounded`, `confidence_reason: "literal string path"`.

```python
# grounded — local const resolution
USERS_PATH = "data/landing/users.csv"
df = pd.read_csv(USERS_PATH)
```
→ same edge, `confidence: grounded`, `confidence_reason: "literal const resolved in same chunk"`.

```sql
-- grounded — fully qualified table name in DDL
CREATE TABLE analytics.public.users (id INTEGER, email TEXT);
```
→ edge `writes_to` with `source_dataset = postgres://<host>:<port>/analytics, public.users, table`, `confidence: grounded`, `confidence_reason: "literal FQN in DDL"`.

## Worked examples — inferred

```python
# inferred — env-var resolved against in-repo .env
import os
df = pd.read_csv(os.getenv("USERS_PATH"))
# ... AND in same repo there's a .env: USERS_PATH=/data/users.csv
```
→ edge with `confidence: inferred`, `confidence_reason: "env-var USERS_PATH resolved against repo .env"`.

```python
# inferred — relative path resolved against __file__
HERE = os.path.dirname(__file__)
df = pd.read_csv(os.path.join(HERE, "fixtures/users.csv"))
```
→ edge with `confidence: inferred`, `confidence_reason: "__file__-relative path"`.

```sql
-- inferred — alias resolved against same-file CTE
WITH active_users AS (SELECT * FROM public.users WHERE active = true)
SELECT id FROM active_users;
```
→ edge `reads_from active_users` resolved to `reads_from public.users`, `confidence: inferred`, `confidence_reason: "CTE alias resolved within same statement"`.

## Worked examples — speculative

```python
# speculative — f-string interpolation
base_dir = get_base_dir()
df = pd.read_csv(f"{base_dir}/users.csv")
```
→ edge with `confidence: speculative`, `confidence_reason: "f-string interpolation; base_dir not resolvable"`.

```python
# speculative — .format() call
df = pd.read_csv("{0}/users.csv".format(base_dir))
```
→ edge with `confidence: speculative`, `confidence_reason: ".format() interpolation"`.

```python
# speculative — %-format
df = pd.read_csv("/data/%s/users.csv" % year)
```
→ edge with `confidence: speculative`, `confidence_reason: "%-format interpolation"`.

```python
# speculative — env-var without in-repo resolution
df = pd.read_csv(os.environ["UNKNOWN_PATH"])
# ... no .env file declares UNKNOWN_PATH
```
→ edge with `confidence: speculative`, `confidence_reason: "env-var UNKNOWN_PATH not resolved in repo"`.

```sql
-- speculative — SELECT * without schema metadata
SELECT * FROM some_table;
```
→ edges for `some_table` reads_from, BUT no column-level lineage emitted. `confidence: speculative` for any downstream attribution about which columns are used. (For the table-level read, `grounded` is appropriate; the speculative tag is for column-level inferences.)

```yaml
# speculative — template variable in YAML
schedule:
  path: ${USERS_PATH}/load.py
```
→ edge with `confidence: speculative`, `confidence_reason: "${...} template variable"`.

## Anti-patterns — DO NOT classify as grounded when…

- `evidence_snippet` contains `f"..."` or `f'...'` (Python f-string)
- `.format(...)` call wrapping a string literal
- `%`-format like `"... %s ..." % var` or `"... %(name)s ..." % d`
- `${...}` shell/env template (Bash, YAML, Jinja, etc.)
- `{{ ... }}` Jinja/Mustache/Handlebars template
- `<%= ... %>` ERB-style template
- Any string concatenation involving a variable, regardless of operator (`+`, `,`, `||`, `..`)
- A symbol that cannot be traced to a literal within the same chunk (LLM context window)
- `SELECT *` with no schema declaration — table read is grounded, but column-level claims are speculative

## What ties happen at the boundary

When the same edge appears in BOTH a `partial_end` chunk AND a `partial_start` chunk (i.e. the LLM emitted it twice across a chunk boundary), `accumulate.py`'s deterministic pairing predicate (per `references/chunking-strategy.md`) decides:

- **Single best match**: paired, merged into one edge with line range spanning both chunks. Confidence is the MORE CONSERVATIVE of the two (speculative wins over inferred wins over grounded).
- **Tied matches**: both edges downgraded to `confidence: speculative` + `boundary_issue: true`.
- **No match**: orphan partial downgraded to `confidence: speculative` + `boundary_issue: true`.

This is bake into HARD-RULE 2 at the script level: the LLM cannot upgrade confidence by re-emitting the same edge in adjacent chunks.

## Why bright lines instead of nuanced judgment

Static analysis is fundamentally lossy at runtime-resolved values. A nuanced `medium-confidence` tier would invite the LLM to upgrade speculative edges to "looks pretty solid", defeating the safety property. The three-tier system gives consumers a clear signal: feed gates only on `grounded`, surface `inferred` as advisory, hide `speculative` by default.

Forge S033 design intake settled on this scheme after a 4-team brainstorm; A3 proposed a confidence-percentile tier which was rejected by both challengers as easier to game.

## Tests

`tests/lineage-extract-static/unit/test_confidence_classifier.py` enforces the bright-line rules with fixture suites of 3+ positive and 3+ negative examples per tier.
