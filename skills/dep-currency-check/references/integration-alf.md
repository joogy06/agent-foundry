# Integration: alf Step 2a — replace improvisation

## Current state (verbose, 3 model calls)

`~/.claude/agents/alf.md` Step 2a "Freshness Check" currently improvises:

```
- Research via /codex:rescue (preferred) or raw codex exec: current stable version,
  deprecation status, breaking changes since target's version
- Invoke web-research skill for claims that need triangulation
- Use mcp__gemini-cli__ask-gemini with Google Search grounding for real-time freshness
- Check official docs first, then community consensus
```

Per dep: 3 model calls + free-text prose to parse. Latency: minutes. Reliability: model-dependent.

## New state (one structured call)

Replace with:

```bash
python3 -m dep_currency_check "$TARGET_PATH" --format json --severity all \
  --ecosystems auto --output "$ALF_REPORT_DIR/dep-currency.json"
```

Alf reads the JSON and constructs **structured findings** (one per Finding) instead of free-text bullets. The 3 model calls per dep become 1 deterministic JSON read.

**Latency drop**: minutes → seconds.

## What alf's OTHER lenses keep using codex/gemini

- Best-practice drift (2b)
- Capability gaps (2c)
- Ecosystem fit (2e)

Those are **interpretive** lenses; codex/gemini still appropriate. ONLY 2a Freshness Check converts to structured data.

## Patch shape

Replace alf.md Step 2a "Freshness Check" bullet list with:

```markdown
**2a: Freshness Check** — Invoke `dep-currency-check` skill for deterministic dep-version + CVE data:

```bash
python3 -m dep_currency_check "$TARGET_PATH" --format json --severity all \
  --ecosystems auto --output "$ALF_REPORT_DIR/dep-currency.json"
```

Read `$ALF_REPORT_DIR/dep-currency.json` and construct one structured finding per entry in `findings[]`. For each finding:
- `package` + `ecosystem` + `declared_version` + `latest_stable` → version-drift finding
- `gap_kind == "deprecated"` → deprecation finding (consult `deprecation_verdict` for interpretive context if present, `confidence_level: interpretive`)
- `cves[]` non-empty → CVE finding (one per CVE)

For freshness claims that the skill could not resolve (`gap_kind: deferred_offline` or `gap_kind: unknown`), fall back to `/codex:rescue` + `mcp__gemini-cli__ask-gemini` for triangulation. Use `confidence_level: interpretive` for any inference not backed by the structured skill output.
```

## Why this is the right cut

Alf's 2a is currently the **most expensive lens** (3 LLM calls per dep × N deps = N×3 model invocations + parse). Converting it to one JSON read drops that to N×0 + 1 stdlib parse. Other lenses stay interpretive — that's their job.

The skill output's `advisories[]` field tells alf when to fall back to the old improvisation path (offline, rate-limited, partial data).
