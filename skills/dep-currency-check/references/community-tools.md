# Community wrappers — primary data path

Per Codex challenger Rev 2 pivot: shell out to community scanners as PRIMARY; HTTP fallback when wrapper unavailable.

## The 4 wrappers

| Tool | Covers | Why | Install |
|---|---|---|---|
| `osv-scanner` | ALL 6 ecosystems | Google-maintained; lockfile-aware; uniform output | `brew install osv-scanner` or `go install github.com/google/osv-scanner/cmd/osv-scanner@latest` |
| `pip-audit` | Python | Native marker + extras + lockfile semantics | `pip install pip-audit` |
| `cargo-audit` | Rust | RustSec-maintained; tracks unsoundness + unmaintained | `cargo install cargo-audit` |
| `govulncheck` | Go | **CALL-AWARE** — does code actually use the vulnerable function? | `go install golang.org/x/vuln/cmd/govulncheck@latest` |

## No `npm audit` wrapper

Per research, npm audit's FP rate is too high. Use OSV-direct for npm.

## Dispatch priority

For each ecosystem present:

1. If `osv-scanner` installed → use it (covers ALL ecosystems with unified output; preferred over per-ecosystem wrappers)
2. Else if ecosystem-specific wrapper installed (pip-audit / cargo-audit / govulncheck) → use it
3. Else → fall back to stdlib HTTP via `registry.py`

## Failure semantics (M4 disambiguation)

A wrapper returns `None` (and the CLI falls through to stdlib HTTP + emits advisory) when ANY of:

- Tool binary not on `$PATH` (`shutil.which` returns None)
- Tool exits non-zero
- Tool times out (60s default per-wrapper)
- Tool's JSON output fails to parse OR doesn't match expected schema

All four cases produce an advisory like `"osv-scanner unavailable for python; fell back to OSV.dev HTTP"`.

## Reconciliation against our Manifest list

The wrappers don't always know which deps are dev / transitive / workspace-member. Always:

1. Parse manifests via `manifests.py` (stdlib) → `list[Manifest]` is authoritative for `is_direct`, `is_dev`, `transitive_depth`, etc.
2. Call wrapper → get its findings
3. Reconcile: for each wrapper finding, look up the matching `Dependency` in our `Manifest` list to fill in metadata
4. If wrapper finds a package we don't know about: emit advisory (resolver mismatch)

## Wrapper JSON shapes (verified)

### osv-scanner
```bash
osv-scanner --format=json --output=- /path/to/project
```
Output:
```json
{
  "results": [
    {
      "source": {"path": "pyproject.toml", "type": "lockfile"},
      "packages": [
        {
          "package": {"name": "...", "version": "...", "ecosystem": "PyPI"},
          "vulnerabilities": [{"id": "...", "summary": "...", ...}],
          "groups": [{"ids": [...], "aliases": [...]}]
        }
      ]
    }
  ]
}
```

### pip-audit
```bash
pip-audit -f json
```
Output (when run inside project dir or with -r requirements.txt):
```json
{
  "dependencies": [
    {
      "name": "...",
      "version": "...",
      "vulns": [{"id": "...", "fix_versions": [...], "description": "..."}]
    }
  ]
}
```

### cargo-audit
```bash
cargo audit --json
```
Output:
```json
{
  "vulnerabilities": {
    "list": [
      {"advisory": {"id": "RUSTSEC-...", "title": "...", ...}, "package": {"name": "...", "version": "..."}}
    ]
  }
}
```

### govulncheck
```bash
govulncheck -json ./...
```
Output: line-delimited JSON; each line is `{"finding": {...}}` or `{"osv": {...}}`. Call-aware — only reports findings whose vulnerable functions are reachable from the project's entry points.

## Probe command

```bash
shutil.which("osv-scanner")
shutil.which("pip-audit")
shutil.which("cargo-audit")
shutil.which("govulncheck")
```

Probe ONCE per CLI invocation; cache for the run.

## Subprocess invocation pattern

```python
import subprocess
proc = subprocess.run(
    [tool, *args],
    capture_output=True,
    text=True,
    timeout=60,  # hard cap per wrapper
    check=False,  # we handle non-zero ourselves
)
if proc.returncode != 0:
    return None
try:
    data = json.loads(proc.stdout)
except json.JSONDecodeError:
    return None
```
