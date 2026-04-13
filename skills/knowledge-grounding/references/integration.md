# Integration: How Other Skills Consume the Manifest

## Reading the Manifest

### From Shell (via get subcommand)

```bash
# Check if internet is available
INTERNET=$(bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh get internet_reachable)

# Check grounding mode
MODE=$(bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh get grounding_mode)

# Check strict_airgap
STRICT=$(bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh get strict_airgap)

# Get a specific source path
WIKI_PATH=$(bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh get sources.wiki_trading.path)
```

### From Shell (direct jq -- faster for hot paths)

```bash
# Read from persistent manifest
INTERNET=$(jq -r '.internet_reachable' ~/.claude/state/sources.json 2>/dev/null || echo "unknown")

# Read from session state
ACTIVE=$(jq -r '.active_sources | join(", ")' "$XDG_RUNTIME_DIR/knowledge-grounding/session-*.json" 2>/dev/null || echo "none")
```

### From Skills/Agents (read the file)

Skills should read `~/.claude/state/sources.json` directly. The file is JSON with schema version 1. Key fields:

- `internet_reachable` (bool) -- can the internet be reached?
- `grounding_mode` (string) -- "internal-only" or "full"
- `strict_airgap` (bool) -- is strict air-gap mode enabled?
- `sources` (object) -- map of source_id to source metadata

## Integration Points

### forge (design phase)

In forge Step 1, read sources.json and include in shared_context for design agents:

```
shared_context.knowledge_sources = read sources.json
shared_context.grounding_mode = sources.grounding_mode
```

This lets design agents know what sources are available for grounding their proposals.

### web-research (search gate)

Before running web searches, web-research should check:

```
if sources.json.internet_reachable == false:
  "Internet is not reachable. Suggesting local sources instead:"
  list active_sources from session state
  offer to search wikis, project docs, or configured paths
```

### wiki auto_consult (composition, not replacement)

Knowledge grounding does NOT replace wiki auto_consult. The relationship:

1. `.wiki-link` with `auto_consult: true` triggers silent wiki grep (existing behavior)
2. Knowledge grounding discovers these wikis and includes them in the manifest
3. When routing a query, wikis with `auto_consult: true` get priority 1

The wiki agent operates independently. Knowledge grounding augments it with additional sources and transparency (grounding tiers).

### hard-rules-checklist

Added check: "Before claiming factual statements, check grounding tier." This ensures agents consider whether their answer is verified, grounded, inferred, or training-only.

### Answer generation

Every agent generating a factual answer should:

1. Check if the answer came from an internal source
2. Assign a grounding tier
3. Append the grounding citation

This is advisory, not enforced by tooling. The skill provides the framework; agents apply it.

## State File Locations

| File | Lifecycle | Written By |
|------|-----------|-----------|
| `~/.claude/state/sources.json` | Persistent, re-probed if >24h | discover.sh |
| `$XDG_RUNTIME_DIR/knowledge-grounding/session-<id>.json` | Volatile, per-session | discover.sh |
| `~/.knowledge-grounding.yaml` | User-managed config | User |
| `~/.wiki-registry.yaml` | User/wiki-agent managed | wiki skill |
