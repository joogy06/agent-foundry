# Integration Reference — git-cli-bridge

> **STALE NOTE (2026-06-10):** This reference predates the gemini→agy migration. Examples below
> that call `mcp__gemini-cli__ask-gemini`, probe `mcp__gemini-cli__ping()`, or pass
> `--tool gemini` are the historical patch record — the live equivalents are
> `timeout 600 agy --sandbox -p "..." < /dev/null` (`--sandbox` mandatory for advise-only calls,
> #157), `tools.agy.installed` from inventory.json, and
> `--tool agy` (the gemini CLI retired 2026-06-18; `bridge-request` accepts only `agy|copilot`).

How the bridge plugs into `codex-orchestration` and `forge`. Ports Section 5 of the design doc. Bob / alf / pa are NOT patched (integration scope C per user ruling Q4).

## 1. Shared helper: `bridge-mode-detect.sh`

Lives at `~/.claude/skills/git-cli-bridge/scripts/bridge-mode-detect.sh`. Returns `"local"` or `"bridge"` on stdout, exit 0. Both `codex-orchestration` and `forge` Step 4b call it at most once per session and cache the result.

Priority (implemented in full in `client-scripts.md` §11):

1. `AI_BRIDGE_DISABLE=1` -> always `local`.
2. `AI_BRIDGE_MODE=1` -> always `bridge`.
3. Cached decision at `$XDG_RUNTIME_DIR/bridge-mode-<session-tag>` -> reuse (sticky, M21).
4. Otherwise probe `gemini --version` + `copilot --version` with 3s timeout each.
5. Both reachable -> `local`, reset fail counter.
6. Either fails -> increment counter; at counter >= 3 -> `bridge` (cached).
7. Counter 1 and 2 still return `local` — this is the **hysteresis** that prevents flapping on transient network blips.

Session-tag resolution: `$FORGE_SESSION_ID` | `$CLAUDE_SESSION_ID` | PID. This keeps concurrent forge sessions isolated from each other (IT9 verifies non-contamination).

## 2. Patch to `codex-orchestration/SKILL.md`

Five patches; all additive.

### Patch 1 — new HARD-RULE at the top

Inserted after the existing three HARD-RULEs (at the block starting line ~10 in the current file). Verbatim text:

```markdown
<HARD-RULE>
When delegating to Gemini or Copilot, check `bridge-mode-detect.sh` first. If it reports "bridge", route the call through `bridge request` instead of calling the local CLI. Explicit `AI_BRIDGE_MODE=1` forces bridge; explicit `AI_BRIDGE_DISABLE=1` forces local; otherwise auto-detection with 3-failure hysteresis. See `git-cli-bridge` skill.
</HARD-RULE>
```

### Patch 2 — new section `## Sandbox-Aware Routing via git-cli-bridge`

Inserted AFTER the existing `### Gemini Availability Check` subsection. Content (roughly 60 lines):

```markdown
## Sandbox-Aware Routing via git-cli-bridge

In sandboxed environments where `gemini` or `copilot` CLIs are unreachable locally, route delegation through the `git-cli-bridge` skill. It pushes requests via git to a dedicated `ai-bridge-<user>` repo and executes the CLI on GitHub Actions runners.

### Routing matrix

| AI_BRIDGE_MODE | AI_BRIDGE_DISABLE | Local gemini --version | Local copilot --version | Effective mode |
|---|---|---|---|---|
| unset | unset | ok | ok | local |
| unset | unset | fail | ok | local (1-2 fails) -> bridge (3+ fails) |
| unset | unset | fail | fail | local (1-2 fails) -> bridge (3+ fails) |
| 1 | unset | any | any | bridge |
| unset | 1 | any | any | local |
| 1 | 1 | any | any | local (DISABLE wins) |

### Bridge call template

```bash
MODE=$("$HOME/.claude/skills/git-cli-bridge/scripts/bridge-mode-detect.sh")
if [ "$MODE" = "bridge" ]; then
  # Submit via bridge. Requires `bridge init` to have been run already in this session.
  BRIDGE_CALLER=codex-orchestration \
  bridge request \
    --tool gemini --kind review \
    --context "$CONTEXT_FILE" \
    --wait --timeout 720 \
    "$PROMPT_BODY"
else
  # Local path
  mcp__gemini-cli__ask-gemini(prompt: "$PROMPT_BODY")
fi
```

### Latency expectations

- Local Gemini call: ~2-5 seconds.
- Bridge Gemini call: ~90 seconds cold (workflow install + run), ~40 seconds warm (runner cache). This is the price of sandboxed operation. If latency is unacceptable, the user can switch back with `AI_BRIDGE_DISABLE=1`.

### When bridge mode is wrong

- Bridge mode activates but the user's local CLI is actually fine: run `AI_BRIDGE_DISABLE=1 bridge-mode-detect.sh --reset` then re-probe.
- Local CLI activates but the user's local CLI is blocked by a transient network issue: wait 1 minute, retry; hysteresis will catch it on the third failure.
- Bridge mode activates but `bridge init` was never run: the next `bridge request` will fail; either `bridge init` or set `AI_BRIDGE_DISABLE=1` for the rest of the session.
```

### Patch 3 — row added to "When to Delegate to Codex vs Keep in Claude" table

Append a new row:

```markdown
| Gemini delegation in sandboxed env | Via git-cli-bridge (see Sandbox-Aware Routing) |
```

### Patch 4 — row added to `## Related Skills` table

Append:

```markdown
| Git-based CLI bridge for sandboxed environments | git-cli-bridge |
```

### Patch 5 — skill description suffix

Append to the `description:` field in the frontmatter:

```
Sandbox-aware: routes Gemini/Copilot calls through git-cli-bridge when local CLIs are unreachable.
```

## 3. Patch to `forge/SKILL.md`

Six patches (F1-F6).

### Patch F1 — rewrite Step 4b

**Match by heading/prefix, not line number.** Find the checklist item that begins with `4b. **Check Codex + Gemini availability**` and replace with a sandbox-aware version:

```markdown
4b. **Check Codex + Gemini availability — sandbox-aware** — Compute `MODE=$(bash ~/.claude/skills/git-cli-bridge/scripts/bridge-mode-detect.sh)` first and cache it for the session (forge re-uses this value for every downstream Gemini/Copilot call). Branch on MODE:

   - **MODE=local**: use the existing behavior — `/codex:setup` or `CODEX_AVAILABLE=$(codex --version 2>/dev/null && echo yes || echo no)` for Codex; `mcp__gemini-cli__ping()` for Gemini MCP. Note gaps, continue.
   - **MODE=bridge**: verify `bridge init` has been run in this session. If not, halt and tell the user to run `bridge init <bridge-repo>` first. With the bridge initialized, treat Gemini and Copilot as AVAILABLE via bridge transport (latency budget ~90s per call instead of ~2-5s). Codex is unchanged — it runs locally inside the sandbox.

   Cache the MODE + both availability flags for the rest of the session — do not re-check on every use. If Codex is unavailable, note the gap explicitly but continue with what's available. See `git-cli-bridge` skill.
```

### Patch F2 — update Adaptive Checklist row for 4b

```markdown
| 4b. Codex + Gemini check (sandbox-aware) | Skip | Check both + detect mode | Check both + detect mode |
```

### Patch F3 — note in `#### Spawning Codex Agents`

Insert after the "Check Codex availability first" sentence:

```markdown
**Note on bridge mode**: Codex has no bridge fallback. Codex is the caller in this architecture, not a callee. If `bridge-mode-detect.sh` reports `bridge`, Codex still runs locally (it must be installed in the sandbox — it is the only CLI with that constraint). The bridge only affects Gemini and Copilot delegation.
```

### Patch F4 — add bridge example to `#### Spawning Gemini Analyst`

Insert after the existing `mcp__gemini-cli__ask-gemini` examples, inside the same section:

```markdown
### Bridge-mode Gemini analyst

When `bridge-mode-detect.sh` returned `bridge`, call Gemini via the bridge:

```bash
# Uses the already-initialized session from bridge init
BRIDGE_CALLER=forge BRIDGE_CALLER_TASK_ID="forge-$(date +%s)-gemini-analyst" \
bridge request --tool gemini --kind review \
  --context "$PROJECT_SUMMARY_PATH" \
  --wait --timeout 720 \
  "Analyze this design for architecture trade-offs, scalability limits, security surface.
  Cite real-world precedents."
```

Latency expectation: ~90s cold, ~40s warm. The parallel-model design pattern (Claude + Codex + Gemini in parallel) still holds — launch this alongside the Claude challenger and Codex adversarial review at the start of the design exploration team phase, not sequentially after.
```

### Patch F5 — update Red Flags section

Replace the existing line:

```markdown
- Skipping the Gemini analyst without checking `mcp__gemini-cli__ping()` first
```

with:

```markdown
- Skipping the Gemini analyst without checking `bridge-mode-detect.sh` first (even in sandboxed environments, Gemini should be available via the bridge)
```

### Patch F6 — new HARD-RULE block

Insert after the existing HARD-RULEs but before the HARD-GATE (currently that is between line ~34 and line ~36):

```markdown
<HARD-RULE>
**Sandbox-Aware Routing**: For MEDIUM/COMPLEX tasks that call Gemini or Copilot (design exploration, challenger review, research analysis), compute `bridge-mode-detect.sh` output once at Step 4b and cache it for the session. In MODE=bridge, every downstream Gemini/Copilot call transparently routes through `bridge request`. Never mix modes within a single forge session — the caching is there precisely to prevent this. If the bridge is required but not initialized, halt Step 4b and tell the user to run `bridge init` first. See `git-cli-bridge` skill.
</HARD-RULE>
```

## 4. No changes to bob, alf, pa (per C ruling)

- **Bob** delegates Gemini/Copilot calls via `codex-orchestration` which becomes bridge-aware after Patch 1. No direct bob changes needed.
- **Alf** uses forge for evolution design; when forge is bridge-aware, alf inherits it.
- **Pa** delegates complex work to forge/bob, which are bridge-aware after the patches.

If a future bob/alf/pa code path introduces a direct `mcp__gemini-cli__ask-gemini` or `copilot -p` call that bypasses `codex-orchestration`, that is a v2.6 revisit trigger.

## 5. Backward compatibility guarantee

All six forge patches and all five codex-orchestration patches are **additive**. A user running forge with:

- No bridge skill installed (`~/.claude/skills/git-cli-bridge` does not exist)
- No `AI_BRIDGE_MODE` env var
- Working local `gemini` and `copilot` CLIs

Gets **byte-identical behavior** to the pre-patch version. Specifically:

1. Step 4b computes `MODE`, but the detector script is absent, so the conditional `if [ -x ... ]` falls through and uses the legacy `/codex:setup` + `mcp__gemini-cli__ping()` path.
2. The HARD-RULE text is new, but the existing behavior it describes is already the default.
3. The adaptive checklist gains the `(sandbox-aware)` suffix, which is a label change, not a behavior change.
4. The Red Flags update is cosmetic.
5. The new HARD-RULE block is a no-op when the bridge is absent.

This property is verified by test `IT1_happy_local.sh` — it runs a forge-style harness with no bridge installed and asserts byte-level identical spawn prompts and routing decisions.

## 6. Session caching contract

When forge is in MODE=bridge at Step 4b, it writes the MODE value to `$XDG_RUNTIME_DIR/bridge-mode-<forge-session-id>` (the same file the detector uses). Subsequent calls — from forge itself, from codex-orchestration delegated to by forge agents, and from any agents spawned by the forge team — read this cached value. Nothing in the session re-probes. This is M21 in action.

If the user explicitly resets the mode mid-session with `bridge-mode-detect.sh --reset`, forge will re-probe on the NEXT call but only after completing the current step. Mode flips never happen mid-step.

## 7. Why bob is untouched in v1

Forge owns the design phase, including all "talk to Gemini" calls. Bob owns the execution phase, where Gemini/Copilot delegation is less critical — most WPs are implementation, not exploration. Bob's dependency on Gemini/Copilot is indirect via codex-orchestration, which becomes bridge-aware in Patch 1. This keeps the v1 patch surface small (2 files, 11 patches total) while covering the primary use case.

Bob's contract-map / audit flow uses `audit_spawn.py` which in turn may call Gemini; if that happens in a sandboxed environment, the audit will degrade. This is a known v1 limitation. Workaround: run the audit interactively outside bob after the sandboxed work completes, before declaring VERIFIED.
