# Gemini Policy Engine

Gemini CLI 0.36.0 introduces a **Policy Engine** that replaces the deprecated `--allowed-tools` flag. The Policy Engine is more expressive: it can allow/deny tools, MCP servers, file paths, and command patterns.

## Verified flags (from `gemini --help`)

```
--policy <files>           Additional policy files or directories to load (comma-separated or multiple --policy)  [array]
--admin-policy <files>     Additional admin policy files or directories to load (comma-separated or multiple --admin-policy)  [array]
--allowed-tools <list>     [DEPRECATED: Use Policy Engine instead See https://geminicli.com/docs/core/policy-engine]
```

## Scope semantics

| Flag | Scope | Override-able? |
|---|---|---|
| `--policy` | Per-invocation, user scope | Yes — admin policies override |
| `--admin-policy` | Admin scope, locked | No — wins over `--policy` |

In a multi-user environment, an admin can deploy `--admin-policy` files that users cannot relax. In a single-dev environment, both behave similarly — use `--policy` for normal config.

## Policy file format (research-grade)

The exact policy file format is **UNVERIFIED** locally — pull from <https://geminicli.com/docs/core/policy-engine> on first deploy. The shape (based on Google's docs) is approximately:

```yaml
# read-only-ci.policy.yaml
version: 1
rules:
  - action: allow
    tools: [read_file, list_directory, web_search]
  - action: allow
    mcp_servers: [github, linter]
  - action: deny
    tools: [write_file, run_command, edit_file]
  - action: deny
    paths: ["/etc/**", "/var/**", "**/secrets/**"]
```

The actual schema may differ — verify before relying on this.

## Common patterns

### Read-only CI policy

For a CI/CD pipeline that only reads:

```bash
gemini -p \
  --approval-mode plan \
  --policy ./ci-readonly.policy.yaml \
  "Review this PR for issues"
```

Policy file (research-grade format):

```yaml
version: 1
rules:
  - action: allow
    tools: [read_file, list_directory, search_files, web_search]
  - action: deny
    tools: ["*"]   # default-deny everything else
```

### Allow only specific MCP servers

```bash
gemini -p \
  --policy ./allow-github-only.policy.yaml \
  --allowed-mcp-server-names github \
  "review this PR"
```

`--allowed-mcp-server-names` is a separate filter on the MCP server list. Use both for defence in depth.

### Lock down filesystem access

```yaml
version: 1
rules:
  - action: deny
    paths: ["/etc/**", "/var/**", "/usr/**", "**/.ssh/**", "**/.gnupg/**", "**/secrets/**"]
  - action: allow
    paths: ["./src/**", "./tests/**", "./docs/**"]
```

## Multiple policy files

`--policy` accepts comma-separated files OR repeated flags:

```bash
gemini -p \
  --policy ./base.policy.yaml,./project.policy.yaml \
  "..."

# or

gemini -p \
  --policy ./base.policy.yaml \
  --policy ./project.policy.yaml \
  "..."
```

Files are merged. Later rules override earlier ones (or AND together — verify on first deploy).

## Migration from `--allowed-tools`

`--allowed-tools` still works in 0.36.0 but emits a deprecation warning. Replace with policy files:

```bash
# OLD
gemini -p --allowed-tools read_file,list_directory "..."

# NEW
gemini -p --policy ./readonly.policy.yaml "..."
```

## Cross-tool note

Claude Code does NOT have a Policy Engine. Its closest equivalent is `--allowedTools "..."` plus `--permission-mode plan/dontAsk`. Don't try to share policy files between Claude and Gemini — use each tool's native mechanism.

## Anti-patterns

| Don't | Why |
|---|---|
| Use `--allowed-tools` in new code | Deprecated. Pre-existing scripts should be migrated. |
| Assume the policy file format is stable | Research-grade. Verify the schema on the actual `geminicli.com/docs/core/policy-engine` page before deploying. |
| Use `--admin-policy` for normal user config | `--admin-policy` is for system-administered restrictions; users cannot override. Use `--policy` for normal config. |
| Skip `--allowed-mcp-server-names` when policy controls tools | They're complementary. Policies cover the tool surface; `--allowed-mcp-server-names` cuts the MCP server list. |
| Forget to test the policy with `--approval-mode plan` first | Plan mode shows what the model would do without doing it. Validate the policy doesn't accidentally block legitimate work. |
