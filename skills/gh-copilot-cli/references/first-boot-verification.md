# First-Boot Verification

After installing `@github/copilot` for the first time (or upgrading), run through this checklist to validate the install and the documented surface against your local reality.

## 1. Install

```bash
npm install -g @github/copilot
# OR if no root access:
mkdir -p ~/.npm-global && npm config set prefix ~/.npm-global
export PATH=~/.npm-global/bin:$PATH
npm install -g @github/copilot
```

## 2. Verify version and basic invocation

```bash
copilot --version
which copilot
copilot --help | head -5
```

Expected: Version 1.0.x, binary on PATH, help banner from `Usage: copilot [options] [command]`.

## 3. Verify all major flags exist

```bash
copilot --help | grep -E '^\s+--?(prompt|allow-all-tools|yolo|autopilot|silent|output-format|continue|resume|add-dir|model|effort|acp|no-custom-instructions)'
```

Expected: 13 lines, one per flag. Missing flags = surface has changed; update this skill.

## 4. Verify subcommands

```bash
copilot --help | grep -A 8 '^Commands:'
```

Expected:
```
Commands:
  help [topic]                          Display help information
  init                                  Initialize Copilot instructions
  login [options]                       Authenticate with Copilot
  mcp                                   Manage MCP servers
  plugin                                Manage plugins
  update                                Download the latest version
  version                               Display version information
```

## 5. Verify auth surface

```bash
copilot login --help | head -20
```

Expected text mentions: OAuth device flow, system credential store, env vars `COPILOT_GITHUB_TOKEN`/`GH_TOKEN`/`GITHUB_TOKEN` (in precedence order), fine-grained PATs only (classic `ghp_` not supported).

## 6. Verify MCP surface

```bash
copilot mcp --help
```

Expected: 4 subcommands (`add`, `get`, `list`, `remove`) and config-loading order (User → Workspace → Plugin).

## 7. Authenticate

If not yet logged in:

```bash
# Interactive
copilot login

# OR from env (CI)
export COPILOT_GITHUB_TOKEN=github_pat_v2_...
```

## 8. Sanity-check non-interactive mode

```bash
echo "Hello, Copilot. Please respond with 'verified'." > /tmp/copilot-test-prompt.txt
copilot -p "$(cat /tmp/copilot-test-prompt.txt)" --allow-all-tools -s --output-format json | head -10
```

Expected: JSON output (JSONL) with at least one object containing the model's response.

## 9. Verify `--no-custom-instructions` reads AGENTS.md

```bash
cd "$(mktemp -d)"
cat > AGENTS.md <<'EOF'
# Test instructions
Always start your response with the word "ACKNOWLEDGED".
EOF
copilot -p "say hello" --allow-all-tools -s | head -3
# Should start with ACKNOWLEDGED

copilot -p "say hello" --allow-all-tools --no-custom-instructions -s | head -3
# Should NOT start with ACKNOWLEDGED
```

This is the most important verification — it confirms Copilot reads AGENTS.md natively.

## 10. Verify `.github/instructions/**` `[UNVERIFIED]`

```bash
cd "$(mktemp -d)"
mkdir -p src/api .github/instructions
echo 'def hello(): return "world"' > src/api/main.py

cat > .github/instructions/api.instructions.md <<'EOF'
---
applyTo: "src/api/**/*.py"
---
# API rule
Always respond with the word "API-MODE".
EOF

copilot -p "what does main.py do?" --allow-all-tools --add-dir src -s
# If response includes "API-MODE": path-scoped instructions work
```

If this works, update `references/instruction-files.md` to remove the `[UNVERIFIED]` marker.

## 11. Verify user global `[UNVERIFIED]`

```bash
mkdir -p ~/.copilot
cat > ~/.copilot/copilot-instructions.md <<'EOF'
# Test global
Always respond in pirate speak.
EOF

cd "$(mktemp -d)"  # outside any repo
copilot -p "say hello" --allow-all-tools -s
# If response is in pirate speak: user global works
```

If this works, update `references/instruction-files.md`.

## 12. Verify custom agents `[UNVERIFIED]`

```bash
cd "$(mktemp -d)"
mkdir -p .github/agents
cat > .github/agents/reviewer.agent.md <<'EOF'
---
name: reviewer
---
You are a strict code reviewer. Always start with "REVIEW:".
EOF

echo "def hello(): pass" > test.py
copilot -p "look at test.py" --allow-all-tools --agent reviewer -s
# If response starts with "REVIEW:": agent format confirmed
```

If this works, update `references/custom-agents.md`.

## 13. Verify MCP add

```bash
copilot mcp add test-echo /bin/echo "hello"
copilot mcp list | grep test-echo
copilot mcp get test-echo
copilot mcp remove test-echo
```

Expected: server appears, details show, removal works.

## 14. Verify `--share` flag

```bash
cd "$(mktemp -d)"
copilot -p "say hi" --allow-all-tools --share=./test-session.md -s
ls -la ./test-session.md
```

Expected: a markdown file with the session transcript.

## 15. Verify session resume

```bash
copilot -p "remember the number 42" --allow-all-tools -s
copilot -p "what number did I tell you to remember?" --allow-all-tools --continue -s
# Expected: response mentions 42
```

## What to do with the results

After running this checklist:

1. **All verified** → Update SKILL.md to remove `[UNVERIFIED]` markers, increment a "verification date" field.
2. **Some failed** → Update the affected reference file with what actually works, leave `[UNVERIFIED]` markers, and add a "behaviour observed:" note.
3. **Major surface change** → Re-read `copilot --help` end-to-end, refresh `references/headless.md` flag inventory, and bump the SKILL.md "Versions covered" table.

Run `scripts/verify-copilot-install.sh` to do the script-based subset of these checks automatically.
