# Integration: `G_DEP_CURRENCY` gate

## Dispatch

```bash
python3 ~/.claude/skills/_meta/gates.py G_DEP_CURRENCY <project_root> \
        [--mode advisory|strict] \
        [--changed-manifests <list>] \
        [--allow-deferred]
```

Follows existing G-pattern (G1-G_CONTRACT_SCOPE). ~50 LOC patch to `gates.py`.

## STRICT blocking criteria (gate fails ONLY if ALL met)

- `severity == "critical"` (HIGH+ is reported but does NOT block — too noisy)
- `is_direct == true` (transitive dep advisories never block — too many)
- `is_dev == false` (production dep only; dev / test / build deps advisory only)
- `cve.fixed_versions` is non-empty (a fix is actually available; "no fix yet" is not a gate-fail)
- AND `--mode strict` (the gate defaults to `advisory` — project opts into `--mode strict` via `.contract/gates.yaml`)

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Pass — no findings meeting strict blocking criteria, OR `--mode advisory`, OR all deferred with `--allow-deferred` |
| 2 | Fail — strict criteria met: critical CVE in production direct dep with known fix |
| 3 | Environmental error |
| 4 | Deferred-only findings (offline + cold cache for required packages) |

## Implementation

Gate dispatch shells out to `python3 -m dep_currency_check` and maps the CLI exit code:

```python
def check_G_DEP_CURRENCY(project_root, mode, changed_manifests, allow_deferred):
    cmd = [
        sys.executable, "-m", "dep_currency_check",
        str(project_root),
        "--format", "json",
        "--severity", "critical",  # gate only cares about critical
        "--mode", mode,
        "--quiet",
    ]
    if changed_manifests:
        cmd.extend(["--changed-manifests", changed_manifests])
    if allow_deferred:
        cmd.append("--allow-deferred")

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    rc = proc.returncode

    if rc == 0:
        ok("G_DEP_CURRENCY", "no critical findings in production direct deps")
    elif rc == 1:
        fail("G_DEP_CURRENCY", f"critical CVE in direct production dep with fix available")
    elif rc == 2:
        # Soft findings only; advisory mode — don't fail
        ok("G_DEP_CURRENCY", "soft findings only, advisory mode")
    elif rc == 4:
        if allow_deferred:
            ok("G_DEP_CURRENCY", "offline + cold cache, deferred allowed")
        else:
            sys.stderr.write("G_DEP_CURRENCY_DEFERRED\n")
            sys.exit(4)
    else:
        env_error(f"dep_currency_check failed: rc={rc} stderr={proc.stderr[:500]}")
```

## Why uniformity

The gate's value is **uniformity** — same dispatch idiom as G1-G_CONTRACT_SCOPE; opt-in via `.contract/gates.yaml`. Bob's existing gate-orchestration logic in `bob.md` doesn't need new handling for `G_DEP_CURRENCY` — it's just another gate that returns 0/2/3/4.

## Rationale for tight blocking criteria (Codex challenger §3 verbatim)

"A design-time gate will block harmless major gaps and dev-only/unreachable advisories. Split severity: security gate only for resolved production/runtime deps with fixed versions available; major gap stays advisory unless explicitly requested."

So:

- Major version gaps → advisory (helpful info, never blocks)
- High CVEs → advisory (might not apply to your usage)
- Critical CVE + transitive → advisory (might not be reachable)
- Critical CVE + dev/test → advisory (not in production attack surface)
- Critical CVE + direct + production + NO fix → advisory (you can't fix it anyway)
- **Critical CVE + direct + production + fix available + `--mode strict`** → BLOCK

That's a narrow, defensible blocking criterion.
