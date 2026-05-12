# Ecosystem-specific quirks (verified URLs + gotchas)

| Ecosystem | Version API | CVE source | Quirks (verified) |
|---|---|---|---|
| **Python** | `https://pypi.org/pypi/<pkg>/json` (or PEP 691 `https://pypi.org/simple/<pkg>/` with `Accept: application/vnd.pypi.simple.v1+json`) | OSV `/v1/querybatch` with `ecosystem: PyPI` | `yanked: true` flag per release; treat as `gap_kind=yanked`. Markers + extras + dep groups complex — let pip-audit handle when available. |
| **npm** | `https://registry.npmjs.org/<pkg>/latest` | OSV with `ecosystem: npm` | dist-tags include `next`, `beta` — filter to `latest`. Workspace traversal via `pnpm-workspace.yaml` / `package.json#workspaces`. No npm-audit wrapper (FP rate). |
| **Rust** | `https://crates.io/api/v1/crates/<pkg>` **1 req/s hard limit + MANDATORY User-Agent**, OR sparse index `https://index.crates.io/<prefix>/<pkg>` | OSV with `ecosystem: crates.io` | Use sparse index by default for v1 to avoid rate limits. Cargo workspaces: `[workspace] members = [...]` traversal. RustSec tracks unsoundness + unmaintained crates. |
| **Go** | `https://proxy.golang.org/<module>/@latest` | OSV with `ecosystem: Go` (aggregates GoVulnDB) | **Capital letters MUST be escaped with `!`** (`github.com/Azure` → `github.com/!azure`). govulncheck is call-aware. |
| **Ruby** | `https://rubygems.org/api/v1/gems/<pkg>.json` | OSV with `ecosystem: RubyGems` | gemspec resolution outside scope; parse `Gemfile.lock`. |
| **Java** | Maven Central: `https://search.maven.org/solrsearch/select?q=g:<group>+AND+a:<artifact>&core=gav&rows=1&wt=json` | OSV with `ecosystem: Maven` | Gradle `build.gradle.kts` parsing simpler than `build.gradle`; both supported v1. |

## Token bucket and backoff

- 10 req/s default per host (crates.io overridden to 1 req/s when using `crates.io/api/v1`, unlimited when using sparse index).
- On 429: exponential backoff (1s/2s/4s, max 3 retries).
- Exhausted → mark deferred, never fail entire run.

## HTTP client

`urllib.request` with `ssl.create_default_context()`. Reads `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` env vars for custom CA bundles (enterprise networks). User-Agent: `dep-currency-check/0.1.0` — mandatory for crates.io, recommended for others.

## Common gotchas

- **Yanked PyPI versions** — `yanked: true` flag per release. Treat as `gap_kind=yanked` (critical).
- **npm dist-tags** — `latest` is one of many tags; explicitly filter on `latest` not `[0]`.
- **crates.io 1 RPS API limit** — sparse index has no rate limit.
- **Go uppercase letters** — proxy.golang.org REJECTS `github.com/Azure/...` — always escape to `!azure`.
- **Maven group+artifact composite key** — search.maven.org requires both with `+AND+`.
- **Gradle Kotlin vs Groovy DSL** — `.kts` is simpler; `.gradle` requires more careful parsing.
