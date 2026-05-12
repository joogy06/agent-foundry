# Anti-patterns (extended)

Beyond the SKILL.md tabletop summary, these are the deeper anti-patterns that caused real rework in the spec-review cycle.

| Don't | Why | Better |
|---|---|---|
| Add `requests` / `httpx` / `pydantic` to make the HTTP layer "nicer" | Skill MUST work in the global skills library without virtualenv. Stdlib is the contract. | Stick with `urllib.request` + `ssl.create_default_context()`. Verbose but adequate. |
| Block on the LLM fallback | Codex/Gemini can hang or wait. | 30s subprocess timeout, hard. On timeout, treat as "couldn't interpret" and continue with raw text. |
| Skip lockfile scanning ("manifest-only is enough") | Gemini's "As-Declared Fallacy" — majority of CVEs hide in transitive deps. | Read lockfiles for direct + first-level transitive minimum. |
| Wrap `npm audit` | FP rate too high (Gemini research). | Use OSV-direct for npm. NO `npm_audit_wrapper`. |
| Treat the cache TTL as a hard rule | 24h is the floor for AUTOMATIC refresh. Vulns get 2h TTL. | `--no-cache` always bypasses. Stale cache on offline mode is expected. |
| Fail loudly on a single registry being unreachable | Multi-ecosystem projects must produce partial reports. | Mark deferred + advisory; never abort. |
| Send registry response JSON straight into YAML dump | PyPI returns every release's metadata (huge). | Project to `VersionInfo` at parse time; cache full response, render only the trimmed dataclass. |
| Query GHSA directly | OSV aggregates GHSA. Direct GHSA = redundant queries + extra auth surface. | OSV-only. Use `$GH_TOKEN` for rate uplift, never for direct API. |
| Mint a new `scope_delta.v1 artifact_kind` for CVEs | Schema frozen at 7 kinds. | Reuse `file` + `extractor_meta.source: dep-currency-check`. Promote to dedicated kind in v2 if usage justifies. |
| Read `~/.claude/state/sources.json` once at module load | Sessions can flip air-gap state. | Read fresh on every CLI invocation. |
| Auto-install pre-commit hooks on session start | Too invasive. | Document the one-liner; never write to `.git/hooks/` automatically. |
| Print findings as ANSI-colored prose by default | Canonical JSON / markdown rendering is human + machine readable. | Color only via `--verbose` AND on TTY. Pre-commit output must be greppable. |
| Trust the User-Agent default for crates.io | crates.io REJECTS missing User-Agent. | Always set explicit User-Agent header. |
| Forget capital-letter escaping for Go modules | `github.com/Azure/foo` 404s without escaping. | Escape `[A-Z]` to `!a`-`!z` in URL path. |
| Use `-ExecutionPolicy Bypass` in `.ps1` pre-commit | Enterprise machines block this at GPO. Hook silently fails. | Use `-NoProfile -NonInteractive -File`. Mirror vs-code-foundry hardening. |
| Dedupe scope_delta AFTER `write_record` | Produces the 2000+-record explosion documented in `_meta/gates.py`. | Dedup key `(manifest_path, package, cve_id)` BEFORE write. |
| Use LLM output to set `blocks_build` flag or trigger scope_delta | LLM verdicts are `confidence_level: interpretive` — interpretive ≠ mechanical decision. | LLM enrichment is purely report-text decoration. |
| Pre-commit hook with `--mode strict` | Strict mode is for the gate, NOT for commit time. Commit hooks must be fast and noise-free. | Pre-commit always advisory. Only `G_DEP_CURRENCY` (opted in) passes strict. |
| `--format yaml` | Single canonical data contract is JSON. | `--render yaml` (presentation over canonical JSON). NO `--format yaml`. |
| Add `--format yaml` choice "for compatibility" | Rev-1 leftover; explicitly removed per spec C3. | Reject the PR if it adds `yaml` to the `--format` choices. |
| Auto-traverse Python deps via `pip install --dry-run` | Side effects, slow, requires network, depends on local Python | Stay with stdlib lockfile parsing; defer full resolver to v1.1 |
| Cache entire OSV /v1/querybatch response under one cache key | Different deps invalidate independently | Cache per-package: `vulns/<ecosystem>/<package>.json` |
| Forget to handle 304 Not Modified | Wastes time re-downloading unchanged bodies | ETag conditional GETs (`If-None-Match` header) refresh `mtime` only on 304 |
| Spawn a fresh subprocess per dep for LLM enrichment | Costly + slow (1s+ subprocess startup) | Batch deprecation interpretations into one LLM call when >5 in a run |
| Use `subprocess.run(..., check=True)` for wrapper invocation | Raises CalledProcessError on non-zero, breaks "return None on failure" semantics | `check=False` + manual `if proc.returncode != 0: return None` |
