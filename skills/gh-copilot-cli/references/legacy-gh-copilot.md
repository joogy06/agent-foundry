# Legacy `gh copilot` extension

Before the standalone `@github/copilot` package existed, GitHub provided Copilot CLI features as an extension to the `gh` CLI:

```bash
gh extension install github/gh-copilot
gh copilot suggest "find files modified in the last week"
gh copilot explain "git rebase --onto main feature^ feature"
```

This extension is **separate** from the standalone `copilot` binary. It still works, but its featureset is much smaller (no agent mode, no autopilot, no MCP servers, no instruction files).

## Subcommands (verified by historical usage)

| Command | Purpose |
|---|---|
| `gh copilot suggest "<query>"` | Suggest a shell command for the query |
| `gh copilot explain "<command>"` | Explain what a shell command does |
| `gh copilot config` | Configure preferences |

## Deprecation status `[UNVERIFIED]`

The legacy extension is **claimed** to be deprecated but it has not been formally archived as of 2026-04. Use it for one-off shell-command suggestions if you don't want to install the full `@github/copilot` package.

```bash
gh extension list | grep gh-copilot
gh extension upgrade github/gh-copilot
```

## Migration to standalone

| Legacy `gh copilot` | Standalone `copilot` |
|---|---|
| `gh copilot suggest "<query>"` | `copilot -p "<query>" --allow-all-tools` (returns much more) |
| `gh copilot explain "<cmd>"` | `copilot -p "explain this command: <cmd>" --allow-all-tools` |
| `gh copilot config` | `copilot login`, edit `~/.copilot/`, environment variables |

The standalone `copilot` is much more powerful — it can edit files, run commands, do agentic loops. The legacy `gh copilot` is just a one-shot suggester.

## When to use which

| Scenario | Use |
|---|---|
| Quick shell command suggestion in a terminal where you already have `gh` | Legacy `gh copilot suggest` |
| Anything beyond a one-line suggestion | Standalone `copilot` |
| CI/CD automation | Standalone `copilot` (legacy doesn't have headless mode) |
| Editing files | Standalone `copilot` (legacy can't edit) |

## Anti-patterns

| Don't | Why |
|---|---|
| Use `gh copilot` for anything that touches files | It can't. Use the standalone. |
| Maintain both installations long-term | Pick one. Confusing for users. |
| Assume `gh copilot suggest` and `copilot -p` produce the same output | They have different system prompts and capabilities. |
| Run `gh extension upgrade` and expect new agent features | The legacy extension is on a slower release cadence; new agent features land in `@github/copilot`. |
