# cross-project-mail

A flat-file mailbox for AI agents in sibling projects on one host to leave
each other messages that survive session boundaries.

This is the **v1 walking skeleton** (single-host trust model, no HMAC, no
MCP server, no daemon). It replaces the manual `cross-repo-review.md`
Outbound/Inbound file convention with a real CLI + SessionStart notification
+ idempotent migrator.

Cross-machine messaging, HMAC signing, quarantine workflows, and the
`mcp_agent_mail` wrapper are deferred to **M3 (v2)**, conditional on
measured demand from a 2-4 week M2 observation window.

The global knowledge-search MCP (M4 / wiki-MCP) is a separate cycle.

## Install

```bash
bash install/install.sh
```

Then add the hook to your `~/.claude/settings.json` (the installer prints
the exact snippet). Run `cpmail doctor` to confirm.

## Quick start

```bash
# Send (body from stdin)
echo "PR looks good — merging" | cpmail send --to vs-code-foundry --subject "installer review"

# Inbox
cpmail list --unread

# Read (body is wrapped in <user_data>...</user_data> automatically)
cpmail read 01HXY7K3M9TBVN8P4ZQGRJ2WAD

# Acknowledge
cpmail ack 01HXY7K3M9TBVN8P4ZQGRJ2WAD

# Migrate an existing cross-repo-review.md (dry-run first)
cpmail migrate --from /path/to/vs-code-foundry/cross-repo-review.md --dry-run
cpmail migrate --from /path/to/vs-code-foundry/cross-repo-review.md
```

## Tests

```bash
cd tests && python3 -m pytest -v
```

## See also

- [SKILL.md](SKILL.md) — full skill discovery doc
- [Design doc](../../docs/plans/2026-05-16-cross-project-mail-v1-design.md)
- [Schema](schemas/envelope.v1.json)
