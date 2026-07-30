---
name: antigravity-cli
description: Use when delegating to or working with the Antigravity CLI (`agy`) — headless single-prompt orchestration (`agy -p`), interactive/resume modes, model selection, plugins, sandbox, and auth. `agy` is this host's SOLE second-opinion / challenger / research delegate — the gemini CLI was retired from this ecosystem on 2026-07-25 and has no fallback path. Covers Antigravity CLI 1.1.6 (verified locally 2026-07-24 from `agy --help`, `agy models`, `agy --version`).
disambiguation: The `agy` binary itself — its flags, headless invocation patterns, model policy and failure modes. Deciding WHICH external model to delegate to, and how to structure a cross-CLI review, is codex-orchestration.
---

# Antigravity CLI (`agy`)

Task-indexed reference for the Antigravity CLI. **`agy` is the SOLE second-opinion /
challenger / research delegate** on this host. Verified locally 2026-07-24 from `agy --help`,
`agy help <sub>`, `agy models`, and `agy --version` (1.1.6).

> **`agy` is the SOLE second-opinion / challenger / research delegate on this host.**
> The gemini CLI was **retired from this ecosystem on 2026-07-25** by user directive — not
> because Google withdrew it, but because `agy` replaced it. The `gemini-cli` skill, the
> `nano-banana` image skill that wrapped it, and its affordance registry were **deleted**.
> **There is no gemini fallback path. Do not add one**, and do not reintroduce `gemini -p`
> or `mcp__gemini-cli__*` calls to any skill.
>
> **Do NOT confuse this with the Vertex AI Gemini API, which is alive and in use** —
> `vertex-banana` calls it directly via `VERTEX_API_KEY` with no CLI dependency. Retiring the
> *CLI* did not retire the *API*.

**Two CLIs matter on this host:** `agy` (`~/.local/bin/agy`, v1.1.6) = the Antigravity-runtime
delegate (this skill) — the SOLE second-opinion delegate; `antigravity` (`/bin/antigravity`,
v1.107.0) = the editor (VS Code/code-server fork), NOT for headless orchestration. Note that
`~/.gemini/` is **agy's own config home** (`agy.md`, `antigravity-cli/`, OAuth creds) despite
the name — never delete it.

> Canonical host directive: `~/.claude/CLAUDE.md` → "Antigravity CLI (`agy`) — host-specific
> directive". This skill is the operational detail behind it.

## When to use

- Delegating a headless prompt to a non-Claude model for a second opinion, challenger
  review, design ratification, or research — the `agy -p "..."` pattern.
- Authoring skills/agents that shell out to `agy`.
- Managing agy plugins, sessions, sandbox, or auth.
- Any skill needing a non-Claude second opinion — route it through
  `agy -p` now.

## The headless orchestration pattern (primary use)

Two patterns, chosen by whether agy must USE TOOLS (read files, run commands,
search) or only reason over content you pipe in:

```bash
# Pattern 1 — ADVISORY (default): agy reasons over an inline/self-contained prompt.
# Under --sandbox, headless agy auto-denies EVERY tool, so this prompt MUST NOT
# need to read a file or run a command — give it everything inline.
timeout 600 agy --sandbox -p "<full self-contained prompt>" < /dev/null

# Pattern 2 — TOOL-CAPABLE (opt-in): agy must read files / run commands / search.
# --dangerously-skip-permissions is the ONLY thing that unlocks headless tool use;
# it still runs INSIDE --sandbox (shell/git stay gated). Verified working 2026-07-17.
timeout 600 agy --sandbox --dangerously-skip-permissions -p "<prompt>" < /dev/null
git -C <repo> status --short   # tripwire after any repo-exposed call
```

- **HEADLESS-TOOL RULE (verified 2026-07-17 on agy 1.1.3; RE-VERIFIED 2026-07-24 on 1.1.6
  with `--model gemini-3.6-flash-high` — Pattern 2 read a real file successfully, ~29s).**
  `--sandbox` in headless
  `-p` mode auto-denies **every** tool — not just shell/git but `read_file` too
  ("jetski: no output produced — a tool required the … permission that headless
  mode cannot prompt for"). The `permissions.allow` list in
  `~/.gemini/antigravity-cli/settings.json` is **inert under `--sandbox`** (its
  `action(*)` grants only take effect un-sandboxed, and un-sandboxed `agy -p` is
  blocked by the Claude Code auto-mode classifier). So a Pattern-1 call that needs
  to READ a file silently no-shows — inline everything, or switch to Pattern 2.
  `--dangerously-skip-permissions` overrides the auto-deny while `--sandbox` keeps
  shell/git capped (the S052 commit vector); native `write_file` is the accepted
  residual → keep the `git status --short` tripwire, never `--add-dir` a writable
  repo. Standing config stays TIGHT (`command(agy)`, `command(cpmail)` only) —
  capability is a per-call flag, not a standing broad grant. This SUPERSEDES the
  older "omit `--sandbox` for writes" advice below: never drop `--sandbox`, add the
  skip-permissions flag instead.

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
  and revert anything agy touched. **Never omit `--sandbox`** (superseded 2026-07-17 by the
  HEADLESS-TOOL RULE above): when agy must write/run tools, keep `--sandbox` AND add
  `--dangerously-skip-permissions` — that gives tool use with shell/git still capped, which is
  strictly safer than dropping the sandbox.
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
  pattern still does NOT apply to agy.) See **Models** below — the account default moved to
  **Gemini 3.6 Flash** on 2026-07-24, so the omit-the-flag convention now gets 3.6 for free.
- `agy` takes **no API-key env prefix** — it authenticates via the Antigravity account
  (`~/.antigravity/`). The gemini `GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY=` prefix does NOT apply to agy.
- Output is **plain text on stdout** — parse text, not JSON. There are no structured
  response fields.
- `--print-timeout` defaults to `5m`; raise it for long deliberations:
  `agy --print-timeout 15m -p "..."`.
- For verdict provenance, append a `served_by` probe line to the prompt — self-reported
  model identity is unreliable. Observed 2026-06-05: the account default served
  `gemini-3.5-flash`. Observed 2026-07-24: the account default serves **Gemini 3.6 Flash**.
  Both are **flash-tier** — weight challenger/analyst verdicts accordingly (advisory tier),
  per the established tier-stratified-verdict practice. Flash-tier is not a limitation to work
  around: **agy is flash-only by standing directive** (see the Models HARD-RULE). If a decision
  needs pro-tier reasoning, escalate to a different arm rather than repointing agy's model.

## Models (verified 2026-07-24, `agy models` on 1.1.6)

```
gemini-3.6-flash-{high,medium,low}    gemini-3.1-pro-{high,low}
gemini-3.5-flash-{high,medium,low}    claude-sonnet-4-6
                                      claude-opus-4-6-thinking
                                      gpt-oss-120b-medium
```

- **Account default = `gemini-3.6-flash`** (verified 2026-07-24 via a `served_by` probe with
  no `--model` flag). The omit-the-flag convention therefore rides the 3.6 line automatically.
- **Effort suffixes** (`-high` / `-medium` / `-low`) are new relative to the 3.5 line and select
  reasoning effort within a model. Measured on this host (Pattern 1, trivial prompt):
  `gemini-3.6-flash-high` ≈ 5s, `gemini-3.6-flash-low` ≈ 5s; Pattern 2 (tool-capable, one
  `read_file`) ≈ 29s on `-high`. Both patterns verified working on 3.6.
<HARD-RULE>
**agy runs GEMINI FLASH MODELS ONLY. No exceptions, no roles, no "utility work" carve-out.**
(User directive, 2026-07-24.)

| Verdict | Models |
|---|---|
| ✅ ALLOWED | `gemini-3.6-flash-{high,medium,low}` (current line — the account default) |
| ✅ allowed, legacy | `gemini-3.5-flash-{high,medium,low}` |
| ❌ FORBIDDEN | `claude-sonnet-4-6`, `claude-opus-4-6-thinking` |
| ❌ FORBIDDEN | `gpt-oss-120b-medium` |
| ❌ FORBIDDEN | `gemini-3.1-pro-{high,low}` — pro tier is NOT used on agy |

Two independent reasons, both binding:

1. **Provider diversity (the `claude-*` / `gpt-oss-*` half).** agy occupies the third-model slot
   precisely because it is *not* Anthropic and *not* OpenAI. A claude-backed "third model" shares
   the Claude arm's blind spots and the cross-check becomes theatre; `gpt-oss-*` collapses into
   the Codex arm the same way. This is a live trap: agy seats in `avengers` already fail over to
   claude hosts when the headless permission auto-deny fires (S062–S067 carry-over), and the
   tempting "fix" for an agy no-show is `--model claude-sonnet-4-6`. That is the WRONG fix — it
   converts a *recorded* provider gap into a *hidden* one.
2. **Flash-only tier discipline (the `gemini-3.1-pro-*` half).** agy is a flash-tier delegate by
   standing directive. Do not reach for pro to "get a better answer" — treat agy verdicts as
   advisory-tier and weight them accordingly. If a decision genuinely needs pro-tier reasoning,
   that is a reason to escalate to a different arm (Claude/Codex), not to repoint agy.

**Correct responses to an agy no-show or a weak agy answer:** (a) re-apply the STDIN +
FLAG-ORDER + Pattern-2 rules and retry, (b) record the provider gap honestly and proceed short-handed. There is no gemini fallback —
that CLI was retired from this ecosystem 2026-07-25. Never repoint
the model.
</HARD-RULE>

## Verified flags (from `agy --help`, v1.1.6)

| Flag | Meaning |
|---|---|
| `-p`, `--print`, `--prompt` | Run a single prompt non-interactively and print the response |
| `--print-timeout <dur>` | Timeout for `-p` wait (default `5m0s`) |
| `-i`, `--prompt-interactive` | Run an initial prompt, then continue interactively |
| `-c`, `--continue` | Continue the most recent conversation |
| `--conversation <id>` | Resume a specific conversation by ID |
| `--add-dir <path>` | Add a directory to the workspace (repeatable) |
| `--model <name>` | Model for the current CLI session (added in 1.0.5; no short `-m` alias). **Convention: omit it** — let agy use the account default (`gemini-3.6-flash` as of 2026-07-24). List choices with `agy models`. If you must pass it, **gemini flash models ONLY** — `claude-*`, `gpt-oss-*`, and `gemini-3.1-pro-*` are all FORBIDDEN on agy (Models HARD-RULE). |
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
| `agy models` | List available models (added in 1.0.5; pairs with the `--model` flag). Verified output on 1.1.6 in **Models** above. Note that most of what it lists is OFF-LIMITS here: agy is **flash-only**, so 3.1-pro, `claude-*`, and `gpt-oss-*` all appear in the listing but must never be selected |
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
- Binary: `~/.local/bin/agy` (v1.1.6). A separate `antigravity` binary is the IDE; for CLI
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


## Not verified / do NOT assume

The following have **no verified `agy` equivalent** — do not assume agy supports them without
checking `agy help`:

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
    verified_against: "1.1.6"
    verified_on: "2026-07-24"
-->
