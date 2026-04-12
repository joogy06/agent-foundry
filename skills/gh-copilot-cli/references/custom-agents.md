# Custom Agents in Copilot CLI

Verified flag: `--agent <agent>` from `copilot --help`. The flag exists and accepts a custom agent name.

The exact format for defining custom agents is **`[UNVERIFIED]`** locally — the help only confirms the flag exists, not the definition file format. This file documents what the design doc inferred from GitHub's blog posts; mark anything unconfirmed.

## Using `--agent`

```bash
copilot -p "review the diff" --agent reviewer --allow-all-tools
```

The exact resolution rules (where Copilot looks for the named agent) are **`[UNVERIFIED]`**.

## Definition file location `[UNVERIFIED]`

GitHub docs claim agent definition files live at:

```
.github/agents/<name>.agent.md
```

Format (research-grade):

```markdown
---
name: reviewer
description: Code reviewer focused on security and performance
tools: [read, search]
model: claude-sonnet-4-6
---

# Reviewer agent

You are a code reviewer. Focus on:
- Security vulnerabilities (OWASP top 10)
- Performance bottlenecks (N+1, hot paths)
- Type safety
- Error handling

Do NOT comment on:
- Style (linter handles it)
- Unrelated improvements
```

Verify by:

```bash
mkdir -p .github/agents
cat > .github/agents/reviewer.agent.md <<'EOF'
---
name: reviewer
---
You are a strict code reviewer.
EOF
copilot -p "review main.py" --agent reviewer --allow-all-tools
```

If Copilot picks up the agent: format confirmed. If not: try other paths (`~/.copilot/agents/`, etc.) and update this file.

## Invocation in interactive chat `[UNVERIFIED]`

Per GitHub docs, custom agents are invoked in interactive mode via `@<name>`:

```
> @reviewer please look at the diff
```

Not yet tested locally.

## Anti-patterns

| Don't | Why |
|---|---|
| Trust the agent format until verified | All `[UNVERIFIED]` — may differ in 1.0.21 |
| Put secrets in agent definitions | Plaintext, committed |
| Define overlapping agents | Confusing — pick one purpose per agent |
| Use `--agent` without confirming the name resolves | Will silently fall back to default agent |
