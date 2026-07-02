---
name: antigravity-cli
description: Use when delegating to or working with the Antigravity CLI (`agy`) — headless single-prompt orchestration (`agy -p`), interactive/resume modes, plugins, sandbox, and auth. `agy` is this host's PRIMARY second-opinion / challenger / research delegate; the gemini CLI (v0.45.0) remains an available fallback until Google retires the gemini CLI on 2026-06-18. Covers Antigravity CLI 1.0.5 (verified locally 2026-06-05 from `agy --help`).
---

# Antigravity CLI (`agy`)

Task-indexed reference for the Antigravity CLI. **`agy` is the PRIMARY second-opinion /
challenger / research delegate** on this host. The `gemini` CLI (v0.45.0, `/usr/local/bin/gemini`)
is still installed and remains an available **fallback** — **until Google retires the gemini
CLI on 2026-06-18**, after which `agy` is the sole delegate. Prefer `agy` now so nothing breaks
at the cutover. Verified locally 2026-06-05 from `agy --help`, `agy help <sub>`, and
`agy --version` (1.0.5).

**Three CLIs coexist on this host — don't confuse them:** `gemini` (`/usr/local/bin/gemini`,
v0.45.0) = the standard Gemini CLI (`mcp`/`extensions`/`skills`/`hooks`/`gemma`, `-p` headless) —
the retiring fallback; `agy` (`~/.local/bin/agy`, v1.0.5) = the Antigravity-runtime delegate
(this skill) — primary; `antigravity` (`/bin/antigravity`, v1.107.0) = the editor itself
(VS Code/code-server fork — `chat`/`serve-web`/`tunnel`/`--diff`/`--goto`), NOT for headless
orchestration.

> Canonical host directive: `~/.claude/CLAUDE.md` → "Antigravity CLI (`agy`) — host-specific
> directive". This skill is the operational detail behind it.

## When to use

- Delegating a headless prompt to a non-Claude model for a second opinion, challenger
  review, design ratification, or research — the `agy -p "..."` pattern.
- Authoring skills/agents that shell out to `agy`.
- Managing agy plugins, sessions, sandbox, or auth.
- Anywhere a skill previously called `gemini -p` / `mcp__gemini-cli__*` — route it through
  `agy -p` now.

## The headless orchestration pattern (primary use)

```bash
timeout 600 agy --sandbox -p "<full self-contained prompt>" < /dev/null
```

- **FLAG ORDER RULE — every flag BEFORE `-p`** (root-caused 2026-07-02). `-p` is a Go *string*
  flag: it consumes the NEXT token as the prompt, even if that token starts with `-`. So
  `agy -p --sandbox "X"` silently runs with prompt = literal `--sandbox`, sandbox OFF, and
  "X" discarded — agy then improvises from its implicit memory (observed: authored AND executed
  a repo-editing script across two such malformed calls; also the cause of the 2026-07-01
  smart-analyst incident where an "analyst" edited two tracked test files after its brief
  never reached it). It can also fork-bomb: the inner agent re-tests the same broken command
  recursively until timeout. Always `agy --sandbox --add-dir D --print-timeout 15m -p "…"` —
  `-p "<prompt>"` LAST.
- **SANDBOX RULE — `--sandbox` is MANDATORY for consultancy/read-only delegation, but know its
  scope** (#157, S052 rogue auto-commit incident; re-verified 2026-07-02 on 1.0.15). agy has
  write/shell/git tools ON by default, and headless `-p` auto-approves them without
  `--dangerously-skip-permissions` — a plain `agy -p "create a file …"` probe wrote the file.
  `--sandbox` enables bubblewrap *terminal* restrictions: it constrains shell/git commands
  (the S052 rogue-commit class) but does NOT gate agy's native file-write tool — a correctly
  sandboxed call still edited a file in its `--add-dir` workspace on request (verified
  2026-07-02). Therefore: (1) `--sandbox` on every advise-only call; (2) do NOT `--add-dir` a
  writable live repo for consultancy — pipe content (`cat file | agy --sandbox -p "…"`) or
  point at a read-only copy; (3) open consultancy prompts with "Advisory only — do not modify
  any files; answer on stdout" (`~/.gemini/agy.md` also enforces an advise-only default at the
  directive layer); (4) tripwire: after any call that exposed a repo, run `git status --short`
  and revert anything agy touched. Omit `--sandbox` ONLY when the task explicitly requires
  writes, and say so in the prompt.
- **STDIN RULE — `< /dev/null` is MANDATORY for headless calls** (root-caused 2026-06-05, task #135).
  agy reads non-TTY stdin until EOF **before** running the prompt; in background/harness/cron
  shells stdin is an open stream that never EOFs, so agy blocks forever with 0 bytes of output —
  and `--print-timeout` does NOT protect you (it only guards the response-print phase, which is
  never reached). Close stdin (`< /dev/null`) or pipe real input (`cat file | agy -p "..."` —
  the pipe EOFs). ALWAYS also wrap in a shell `timeout`. Prompt SIZE is irrelevant: a 30-char
  prompt hung in the bad context; an 11KB prompt with stdin closed answered in 9 seconds.
  (Discriminating evidence: T1 bare/background = exit 124 @ 0B; T2 identical + `< /dev/null` =
  answer in 5s. Same stdin-until-EOF behavior class as `codex exec`.)
- **Convention: pass no model flag.** As of agy ≥1.0.5 a `--model` flag DOES exist (and an
  `agy models` subcommand lists the choices) — but our convention is to omit it and let agy use
  the Antigravity-account configured model. Do **not** add `--model` unless a call explicitly
  needs a specific model. (There is no short `-m` alias; the gemini `-m gemini-3.1-pro-preview`
  pattern still does NOT apply to agy.)
- `agy` takes **no API-key env prefix** — it authenticates via the Antigravity account
  (`~/.antigravity/`). The gemini `GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY=` prefix does NOT apply to agy.
- Output is **plain text on stdout** — parse text, not JSON. (The old `mcp__gemini-cli__*`
  tools returned structured fields; agy `-p` does not.)
- `--print-timeout` defaults to `5m`; raise it for long deliberations:
  `agy --print-timeout 15m -p "..."`.
- For verdict provenance, append a `served_by` probe line to the prompt — self-reported
  model identity is unreliable. Observed 2026-06-05: the account default served
  `gemini-3.5-flash` — a **flash-tier** model. Weight challenger/analyst verdicts accordingly
  (advisory tier), per the established tier-stratified-verdict practice.

## Verified flags (from `agy --help`, v1.0.5)

| Flag | Meaning |
|---|---|
| `-p`, `--print`, `--prompt` | Run a single prompt non-interactively and print the response |
| `--print-timeout <dur>` | Timeout for `-p` wait (default `5m0s`) |
| `-i`, `--prompt-interactive` | Run an initial prompt, then continue interactively |
| `-c`, `--continue` | Continue the most recent conversation |
| `--conversation <id>` | Resume a specific conversation by ID |
| `--add-dir <path>` | Add a directory to the workspace (repeatable) |
| `--model <name>` | Model for the current CLI session (added in 1.0.5; no short `-m` alias). **Convention: omit it** — let agy use the account default. List choices with `agy models`. |
| `--sandbox` | Run with terminal restrictions enabled (bubblewrap on Linux). MANDATORY for consultancy/read-only calls, and MUST come BEFORE `-p` (see FLAG ORDER + SANDBOX RULEs). Scope: constrains shell/git commands only — does NOT gate native file writes (verified 2026-07-02, 1.0.15) |
| `--dangerously-skip-permissions` | Auto-approve all tool permission requests (fully-headless only) |
| `--log-file <path>` | Override the CLI log file path |

Bare `agy` (no `-p`/`-i`) opens an interactive session.

## Subcommands (verified)

| Command | Notes |
|---|---|
| `agy changelog` | Show changelog / release notes |
| `agy help [sub]` | Help for a subcommand |
| `agy install [--dir D] [--skip-aliases] [--skip-path]` | Configure shell PATH + aliases |
| `agy models` | List available models (added in 1.0.5; pairs with the `--model` flag) |
| `agy update` | Update the CLI |
| `agy plugin …` | Plugin management (see below); alias `agy plugins` |

### Plugins (`agy plugin <cmd>`)

| Command | Notes |
|---|---|
| `list` | List imported plugins |
| `import [source]` | Import plugins from **gemini or claude** (e.g. `agy plugin import claude`) |
| `install <target>` | Install a plugin (`plugin@marketplace` supported) |
| `uninstall <name>` / `enable <name>` / `disable <name>` | Lifecycle |
| `validate [path]` | Validate a plugin |
| `link <marketplace> <target>` | Generate a link to a marketplace |

> `agy plugin import claude` can pull Claude plugins into agy — useful for reusing the
> existing skill set rather than re-authoring.

## Auth / config

- Authenticates via the Antigravity account; no per-call API-key env var.
- Config lives under `~/.antigravity/` (`argv.json`, `extensions/`) and
  `~/.gemini/antigravity-cli/`. (`argv.json` is JSONC-style — not strict JSON.)
- Binary: `~/.local/bin/agy` (v1.0.5). A separate `antigravity` binary is the IDE; for CLI
  orchestration always use `agy`.

## Context / instructions files (VERIFIED 2026-06-03, empirical probes)

`agy` DOES honour markdown instruction files — the contract was confirmed by writing distinct
sentinels and reading them back via `agy -p` from a clean working directory:

| Path | Scope | Read by agy? |
|---|---|---|
| `~/.gemini/agy.md` | **global** (every invocation, any cwd) | ✅ YES — **the host directive lives here** |
| `~/.gemini/GEMINI.md` | global | ✅ YES — but left **empty** (we use `agy.md`; GEMINI.md is gemini's own file, and gemini retires 2026-06-18) |
| `<cwd>/AGENTS.md` | per-workspace (additive) | ✅ YES |
| `<cwd>/agy.md` | per-workspace (additive) | ✅ YES |
| `~/agy.md` (home root) | — | ❌ NO — not a context path |
| `~/.gemini/antigravity-cli/brain/`, `implicit/*.pb` | agy internal memory | binary protobuf — NOT user-editable |

- **The host directive is `~/.gemini/agy.md`** (created 2026-06-03; hardened 2026-07-02): establishes
  agy's second-opinion/challenger role, an ADVISE-ONLY default (no file writes / state-changing
  commands / git commits unless the prompt explicitly grants them), plain-text output,
  anti-sycophancy, stay-on-prompt, and the `served_by` probe convention. Every `agy -p` call
  inherits it. It is a behavioural layer only — keep the `--sandbox` flag AND the advise-only
  prompt line on every read-only call: the directive can be ignored, and `--sandbox` covers
  shell/git but not native file writes, so the layers only work together.
- **Identity caveat:** agy keeps its baked-in "pair-programmer" self-concept — asked "what is
  your role," it recites that, NOT the agy.md text. But it *follows specific instructions* placed
  in agy.md (proven: an exact-string instruction round-tripped verbatim). So put behavioural
  rules in agy.md; don't expect it to re-describe its role from the file.
- **Pollution note:** because agy reads `<cwd>/AGENTS.md` + `<cwd>/agy.md`, calling `agy -p` from
  a project root pulls that project's workspace context in as additive context. For a clean
  second opinion, call from a neutral cwd or keep the prompt fully self-contained.

## Differences from the Gemini CLI (migration notes)

> The gemini CLI is still installed (v0.45.0) as a fallback until its 2026-06-18 retirement;
> this table is how to translate a gemini-orchestration call into the agy-primary equivalent.

| Gemini CLI (fallback → retires 2026-06-18) | Antigravity CLI (`agy`, primary) |
|---|---|
| `gemini -m <model> -p "X"` | `agy -p "X"` (convention: omit `--model`; a `--model` flag exists from 1.0.5 but is not used by default) |
| `GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini …` | `agy …` (no env prefix; account auth) |
| `--yolo` approval mode | `--dangerously-skip-permissions` |
| `mcp__gemini-cli__ask-gemini` / `brainstorm` MCP tools | direct `agy -p` Bash call (plain-text out) |
| `-o json` / `stream-json` output | plain text on stdout (no verified JSON mode) |
| Model tiers / "don't accept downgrades" | Account-default model used by convention; `agy models` + `--model` exist (1.0.5) but no documented tier hierarchy |

## Not verified / do NOT assume

The following were **Gemini-CLI-specific** and have **no verified `agy` equivalent** — do not
assume agy supports them without checking `agy help`:

- Policy engine (`--policy` / `--admin-policy`), `--allowed-tools` semantics.
- Hooks, A2A/ACP servers, `--output-format json/stream-json`, settings-schema specifics.

(The `GEMINI.md` / `AGENTS.md` / `agy.md` context-file contract is now **verified** — see
"Context / instructions files" above.)

If a workflow needs one of these, probe `agy help` / `agy <sub> --help` and confirm before
documenting it as supported.

## The Antigravity editor (out of scope — B3 sentinel, Evergreening v1 S041)

`antigravity` (`/bin/antigravity`, v1.107.0) is the **Antigravity IDE/editor** — a separate
product from this CLI (`agy`). It is **explicitly out of scope** for this skill and for the
evergreening detection bus in v1: we watch the `agy` CLI surface (commands/flags/version via
`verify-agy-install.sh` + the affordance registry), but we do **not** track the editor's
release notes, settings schema, or internal capabilities (IDE release-note monitoring is on
the §3 not-watched list). The editor is mentioned here only so the boundary is explicit: if you
need editor behaviour, that is a separate, unmanaged surface — probe it directly and do not
infer it from `agy`. (Deep IDE semantic analysis is a deferred v1.1 item.)

<!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: agy
    verified_against: "1.0.15"
    verified_on: "2026-07-02"
-->
