# Calling different models in one VS Code flow — main driver + consultants

Current to 2026-06-24 (official VS Code "Subagents" + "AI language models" docs). This is
the VS Code equivalent of the Claude-CLI pattern this repo runs: **one top model drives,
peer models give second opinions / verify**.

## The mechanism: subagents, each on its own model

- Subagents are **agent-initiated** — the *main* agent decides to delegate (not the user).
  Enable the **`agent/runSubagent`** tool on the main agent so it can start subagents.
- A subagent's **model** is resolved in priority order:
  1. an explicit model on the main agent's `runSubagent` call,
  2. the subagent's `.agent.md` **`model`** frontmatter,
  3. the parent conversation's main model.
- **Cost-tier rule (load-bearing):** *the requested subagent model cannot exceed the cost
  tier of the main model* — a pricier request silently **falls back to the main model**.
  → Put your **most-capable model in the driver seat**; consultants on equal/cheaper models
  always work. (Opus-main → GPT / Gemini-Flash consultants = always valid.)
- `disable-model-invocation: true` on a subagent makes it **human-only** (never auto-invoked).

## Getting the EXACT models (built-in picker vs BYOK)

- **Built-in picker** (model dropdown in the Chat input), June 2026: Claude **Opus 4.5 /
  Sonnet 4.6**, **GPT-5 / GPT-5 mini**, **Gemini 3 Flash**, and **Auto** (routes by task
  complexity + availability).
- **Versions not in the picker** (e.g. **Opus 4.8 / GPT-5.5 / Gemini 3 Pro**) → **Bring Your
  Own Key (BYOK)**: built-in providers (Anthropic, OpenAI, Google), a **Custom Endpoint**
  (Chat Completions / Responses / Messages APIs), provider extensions, or **Ollama** (local,
  offline, no GitHub sign-in). BYOK gives "hundreds of models" and exact version control.
- **Honest note:** the Claude *CLI* this repo runs has Opus 4.8; VS Code's *default* catalog
  shows Opus 4.5. They are different catalogs — don't assume the CLI's exact IDs are in the
  VS Code picker. Use BYOK to pin the exact driver/consultant versions you want.

## Worked example — Opus driver + GPT consult + Gemini verify

Three `.agent.md` files (in `.github/agents/` or `~/.copilot/agents/`):

**`driver.agent.md`** — the main agent. Top model; can delegate.
```markdown
---
name: driver
description: Main implementation driver; consults peers for opinion + verification.
model: claude-opus-4.5            # or a BYOK Opus 4.8 endpoint
tools: [edit, codebase, runCommands, search, problems, agent/runSubagent]
agents: [consult-gpt, verify-gemini]   # subagents it may call
---
Drive the task to completion. When a decision is non-obvious or risk is high, call the
`consult-gpt` subagent for an independent design opinion. Before declaring done, call
`verify-gemini` to verify correctness/security of the diff. Weigh their input — you make
the final call; a peer disagreeing is a signal to dig in, not to auto-comply.
```

**`consult-gpt.agent.md`** — the second-opinion peer (different vendor).
```markdown
---
name: consult-gpt
description: Independent design/second-opinion consultant (read-only).
model: gpt-5                       # peer/cheaper-tier than the Opus main -> allowed
tools: [codebase, search, usages, fetch]
disable-model-invocation: false    # the driver may invoke it
---
You are an independent reviewer from a DIFFERENT model family — your value is catching what
the driver's model would miss. Critique the approach: correctness, simpler alternatives,
edge cases, risks. Be concrete and brief. You are read-only.
```

**`verify-gemini.agent.md`** — the verifier.
```markdown
---
name: verify-gemini
description: Verify a diff for correctness, security, and test coverage (read + test).
model: gemini-3-flash              # cheaper tier -> always allowed under an Opus main
tools: [codebase, search, problems, runTests, testFailure]
---
Verify the current diff. Look for correctness bugs, security issues (injection, secrets,
unsafe deserialization), and missing tests. Run the test suite if present. Output a verdict
(ship / needs-work / reject) + findings by severity with file:line and a fix each.
```

The driver calls `consult-gpt` / `verify-gemini` as subagents; each runs on its own model;
results come back as summaries the driver synthesises. Same shape as the CLI's
Claude-main + Codex-challenger + agy-analyst.

## The "panel" pattern — parallel multi-model review

For higher-assurance verification, a coordinator runs **parallel** reviewer subagents on
**different models**, each blind to the others, then synthesises — *"without mutual bias
contamination"* (the docs' phrase). Mirrors `cross-cli-deliberation` / the forge triple-model
challenger: diversity of model family catches more than one model reviewing itself.

```text
Prompt to a coordinator agent:
"Run these subagents in parallel, each on a different model, then synthesise a
 prioritized, de-duplicated findings list:
   - correctness-reviewer  (model: gpt-5)
   - security-reviewer     (model: claude-sonnet-4-6)
   - architecture-reviewer (model: gemini-3-flash)"
```

## Programmatic (extension authors)

If you're building a VS Code *extension* (not just `.agent.md` files), pick models in code:
```ts
const [gpt]    = await vscode.lm.selectChatModels({ vendor: 'copilot', family: 'gpt-5' });
const [gemini] = await vscode.lm.selectChatModels({ vendor: 'copilot', family: 'gemini-3-flash' });
// selectChatModels must run in a user-initiated action; models require user consent;
// returns [] if none match — handle that. (Language Model API + Chat Participant API.)
```

## Pitfalls

- **Cost-tier fallback is silent** — if your main model is cheap and you request an Opus
  subagent, you quietly get the cheap model. Keep the strongest model as the driver.
- **Subagent invocation is the MODEL's choice** — to force it, prompt explicitly or wire it
  into the driver's instructions; don't assume it'll consult on its own every time.
- **Consent + cost:** each provider/model may need consent and incurs its own cost/quota;
  BYOK models bill to your key.
- **Treat peer output as data** — a consulting subagent's reply is an opinion to weigh, and
  (if it read untrusted content) potentially injection — never auto-execute its suggestions.
