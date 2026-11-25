---
name: antigravity-cli
description: Use when delegating to or working with the Antigravity CLI (`agy`) — headless single-prompt orchestration (`agy -p`), interactive/resume modes, model selection, plugins, sandbox, and auth. `agy` is this host's SOLE second-opinion / challenger / research delegate — the gemini CLI was retired from this ecosystem on 2026-07-25 and has no fallback path. Covers Antigravity CLI 1.4.12 (flags and sandbox behaviour verified locally 2026-11-01).
disambiguation: The `agy` binary itself — its flags, headless invocation patterns, model policy and failure modes. Deciding WHICH external model to delegate to, and how to structure a cross-CLI review, is codex-orchestration.
---

# Antigravity CLI (`agy`)

Task-indexed reference for the Antigravity CLI. **`agy` is the SOLE second-opinion /
challenger / research delegate** on this host. Flags verified 2026-11-01 from `agy --help` and `agy --version` (1.4.12); the rest of
this page from `agy help <sub>` and `agy models`, dated where it stands.

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

**Two CLIs matter on this host:** `agy` (`~/.local/bin/agy`, v1.4.12) = the Antigravity-runtime
delegate (this skill) — the SOLE second-opinion delegate; `antigravity` (`/bin/antigravity`,
v1.107.0) = the editor (VS Code/code-server fork), NOT for headless orchestration. Note that
`~/.gemini/` is **agy's own config home** (`agy.md`, `antigravity-cli/`, OAuth creds) despite
the name — never delete it.

> Canonical host directive: `~/.claude/CLAUDE.md` → "Antigravity CLI (`agy`) — host-specific
> directive". This skill is the operational detail behind it.

## When to use

- Delegating a headless prompt to a non-Claude model for a second opinion, challenger
  review, design ratification, or research — the `agy --sandbox --mode plan --model <slug> -p "..."` pattern (the slug from `seat_model.py argv`).
- Authoring skills/agents that shell out to `agy`.
- Managing agy plugins, sessions, sandbox, or auth.
- Any skill needing a non-Claude second opinion — route it through
  Pattern 1 below.

## The headless orchestration pattern (primary use)

Two patterns, chosen by whether agy only advises or must run tools:

```bash
# Each recipe is self-contained: it resolves $AGY_MODEL through seat_model itself, and
# the `&&` means agy never runs with an empty model when resolution fails.

# Pattern 1 — ADVISORY (default): reads and web search; no native writes, no shell. Content goes
# inline in -p, from an EMPTY cwd: the cwd is agy's workspace, so a call from a repo can read it.
AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_support --provider agy)" &&
(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --mode plan $AGY_MODEL -p "<full self-contained prompt>" < /dev/null)

# Pattern 2 — TOOL-CAPABLE (opt-in, NO containment): full shell and git, reads home and repos.
# Throwaway directory only, never with a live repo as cwd or --add-dir.
AGY_MODEL="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role consultant_support --provider agy)" &&
BASE="$(git -C <repo> log -1 --oneline)" &&
(d="$(mktemp -d)" && cd "$d" && timeout 600 agy --sandbox --dangerously-skip-permissions $AGY_MODEL -p "<prompt>" < /dev/null)
git -C <repo> status --short; [ "$(git -C <repo> log -1 --oneline)" = "$BASE" ]   # tripwire: status cannot see a commit
```

### What agy does (measured 2026-11-01 on agy 1.4.12, #366)

Observed behaviour on one version with harmless canaries, not a documented security boundary. An
upgrade can change it, so the `model-eval-pack` `harness` category re-checks it. Raw results:
`docs/reviews/2026-11-01-366-agy-sandbox/`. "Empty cwd" means a call from an empty temp directory.

With `allowNonWorkspaceAccess` off (raw results: `summary3.txt`, `summary4.txt`):

| Action | `--sandbox` | `--sandbox --mode plan` | `--sandbox --dangerously-skip-permissions` |
|---|---|---|---|
| Read in cwd | yes | yes (`h-sandbox-read` missed 1 of 3 at `-medium`) | yes |
| Read a temp dir outside cwd | yes | yes | not tested |
| Read under home | **no**, 3 of 3 | **no**, 3 of 3 | **yes**, 3 runs |
| Read a repo from empty cwd, in `trustedWorkspaces` | not tested | **no**, 3 of 3 | **yes**, 3 of 3 |
| Read a repo from empty cwd, not in `trustedWorkspaces` | not tested | **no**, 3 of 3 | **yes**, 3 of 3 |
| Native write in cwd or temp dir | yes | **no**, 6 of 6 | not tested |
| Shell | not tested | no, 3 of 3 | yes |
| Shell write under `~/.cache` | not tested | not tested | **yes**, 3 of 3 |
| Web search | not tested | yes, 3 of 3 | not tested |

`--sandbox --mode plan --dangerously-skip-permissions`, native write in cwd: no file, 3 of 3.

Measured with the setting on (as found on this host; one run per case, plan column three):

| Action | `--sandbox` | `--sandbox --mode plan` | `--sandbox --dangerously-skip-permissions` |
|---|---|---|---|
| Read outside cwd (temp dir, `~/.cache`) | yes | yes | yes (temp dir) |
| Native write in cwd or temp dir | yes, no prompt | no, 6 of 6 | yes |
| Native write under `~/.cache` | no | no, 3 of 3 | not tested |
| Shell, `git commit` | no (denied, empty output) | no, 6 of 6 | **yes** |
| Web search | yes | yes, 3 of 3 | not tested |
| Fetch a URL | no (model said it cannot) | not tested | not tested |

- **`--sandbox` restricts only the shell.** A model that reaches for a shell tool still no-shows
  ("jetski: no output produced — a tool required the … permission that headless mode cannot prompt
  for"); a read does not.
- **`--mode plan`** removes native writes and the shell. agy may write its own plan file under
  `~/.gemini/antigravity-cli/brain/`; nothing else changed.
- **Plan-mode narration.** A turn that uses a tool can open with a line of narration before the
  answer: `sa-native-trigger` failed its first-line check 3 of 4 runs with the content right
  (2026-11-01, `-medium`). Parse an advisory reply from its last lines, not its first. Tool-free
  deliberation was unaffected: 21/21 strict-format runs through the shim, 7/7 with the real flag.
- **Containment comes from three things together:** `allowNonWorkspaceAccess` off, `--mode plan`
  and an empty cwd. Reads of temp directories and web search remain, so a call can still send text
  out. Plan mode is not a security boundary, and real isolation (agy under `bwrap`) is not in place.
- **Pattern 2 has no containment.** `--dangerously-skip-permissions` bypasses the setting and, without
  plan mode, everything else: shell and git run, and their write scope was not found to be limited.
  Added to `--mode plan`, it stayed in plan in 3 of 3 runs; Pattern 2 does not use that combination.
- **`trustedWorkspaces` made no difference:** a repo on the list and one off it behaved alike from an
  empty cwd.
- **Allocate the directory, check it, then `cd`:** `d="$(mktemp -d)" && cd "$d" && …`. A `cd` on an empty
  result succeeds and stays where it was, so a failed `mktemp` would otherwise leave agy in a live repo.
- **A Pattern 1 prompt that names a path no-shows** (`read_file` denied, empty output), from an
  empty cwd. Inline the content.
- **Piped stdin never reaches the model:** with `-p`, under plan and under `--sandbox` alone, a codeword
  on stdin came back NOTHING, 6 of 6, rc 0 (`summary5.txt`). The older "or piped" advice was wrong; a
  seat reviewing a pipe reviews nothing and looks fine.
- **Content goes inline.** Read it into a variable before the subshell, so relative paths still work:
  `C="$(cat f)" && (d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan --model <slug> -p "…$C" < /dev/null)`. 120 KB arrived whole; one
  argument cannot pass 128 KB (rc 126, loud), so split at 100 KB, one call per chunk.
- **`--input-format stream-json` works but has no size advantage.** Needs `--output-format stream-json`
  and no `-p`; the line is `{"event":"user","message":{"role":"user","content":[{"type":"text","text":"…"}]}}`
  and the reply is `.result.response`. 120 KB arrived whole; at
  200 KB and 500 KB input tokens stopped near 58k and the tail was lost, status SUCCESS. Plan-mode
  denials held under it (write and home read, 3 of 3). Not used by any recipe.
- **Each `mktemp -d` recipe leaves one empty directory behind** in the temp dir; `agy_call.sh` removes
  its own.
- **Host settings (owner's decision, 2026-11-01):** in `~/.gemini/antigravity-cli/settings.json`,
  `allowNonWorkspaceAccess` is off, because that is what denies reads under home and of live repos
  (`true` as found; the key is now absent, and that absent state is what the "off" table measured),
  and the allow list is `command(agy)`, `command(cpmail)`, because capability is a per-call flag, not a
  standing grant. Nothing in `install.py` manages this file, so a new machine is not covered:
  `env-readiness` warns on `true`. The allow list did nothing under `--sandbox` when last checked
  (2026-07-24, 1.1.6; not re-measured).
- **A caller that needs repo files:** inline them, or do not make the call. Pattern 2 is for work that needs tools, never a way to give a reviewer context.
- **Superseded history.** The 2026-07-17 HEADLESS-TOOL RULE (verified on 1.1.3, re-verified 2026-07-24
  on 1.1.6) said `--sandbox` auto-denies every tool, read_file included, and that Pattern 2 keeps
  shell and git capped. Neither held on 1.4.12.

- **FLAG ORDER RULE — every flag BEFORE `-p`** (root-caused 2026-07-02). `-p` is a Go *string*
  flag: it consumes the NEXT token as the prompt, even if that token starts with `-`. So
  `agy -p --sandbox "X"` silently runs with prompt = literal `--sandbox`, sandbox OFF, and
  "X" discarded — agy then improvises from its implicit memory (observed: authored AND executed
  a repo-editing script across two such malformed calls; also the cause of the 2026-07-01
  smart-analyst incident where an "analyst" edited two tracked test files after its brief
  never reached it). It can also fork-bomb: the inner agent re-tests the same broken command
  recursively until timeout. Always `agy --sandbox --mode plan --print-timeout 15m --model <slug> -p "…"` —
  `-p "<prompt>"` LAST.
- **SANDBOX RULE — every call that should only advise is Pattern 1** (#157, S052 rogue auto-commit
  incident; #366). Without `--sandbox`, agy's write/shell/git tools are on and headless `-p`
  auto-approves them — a plain `agy -p "create a file …"` probe wrote the file (2026-07-02, 1.0.15).
  Therefore: (1) `--sandbox --mode plan` from an empty cwd on every advise-only call; (2) no
  `--add-dir` on an advisory call — inline content (`C="$(cat file)" && (d="$(mktemp -d)" && cd "$d" && agy --sandbox --mode plan --model <slug> -p "…$C" < /dev/null)`);
  (3) open consultancy prompts with "Advisory only — do not modify any files; answer on stdout"
  (`~/.gemini/agy.md` also enforces an advise-only default at the directive layer); (4) **Never omit
  `--sandbox`**: when agy must run tools, keep it AND add `--dangerously-skip-permissions`.
- **STDIN RULE — `< /dev/null` is MANDATORY for headless calls** (root-caused 2026-06-05, task #135).
  agy waits on non-TTY stdin until EOF **before** running the prompt, and discards what it reads; in background/harness/cron
  shells stdin is an open stream that never EOFs, so agy blocks forever with 0 bytes of output —
  and `--print-timeout` does NOT protect you (it only guards the response-print phase, which is
  never reached). Close stdin (`< /dev/null`). ALWAYS also wrap in a shell `timeout`. Prompt SIZE is irrelevant to this hang (the separate limit is 128 KB for one argument; see the content rule above): a 30-char
  prompt hung in the bad context; an 11KB prompt with stdin closed answered in 9 seconds.
  (Discriminating evidence: T1 bare/background = exit 124 @ 0B; T2 identical + `< /dev/null` =
  answer in 5s. Same stdin-until-EOF behavior class as `codex exec`.)
- **Convention: pin the model on EVERY call, through `seat_model` (revised 2026-10-21, #367).**
  `--model` exists as of agy ≥1.0.5 (`agy models` lists the choices; no short `-m` alias).
  Resolve it, never hand-type it: `seat_model.py argv --role <role> --provider agy` prints
  `--model <slug>` — deliberative seats `consultant_main` / `arbiter` (`-high`), research and
  operational calls `consultant_support` (`-medium`); add `--size light|medium|complex` to let the
  task's complexity pick the level instead (`-low` / `-medium` / `-high`, roster rev 7). The account default was an older Gemini model,
  a family the roster now forbids, so an unpinned call rides a forbidden line. The one
  sanctioned exception is `model-eval-pack`, which passes `--model` literally because choosing
  the model under test is its purpose.
- `agy` takes **no API-key env prefix** — it authenticates via the Antigravity account
  (`~/.antigravity/`). The gemini `GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY=` prefix does NOT apply to agy.
- Output is **plain text on stdout** — parse text, not JSON. There are no structured
  response fields.
- `--print-timeout` defaults to `5m`; raise it for long deliberations:
  `agy --sandbox --mode plan --print-timeout 15m --model <slug> -p "..."`.
- For verdict provenance, append a `served_by` probe line to the prompt — self-reported
  model identity is unreliable. (History: the unpinned account default served
  older Gemini models of a now-forbidden family on 2026-06-05 and 2026-07-24.) agy serves ONE family,
  the roster's (see the Models HARD-RULE). If a decision needs other reasoning, escalate to a
  different arm rather than repointing agy's model.

## Models (2026-10-20 roster cache, `agy models` via env-adoption `probe.sh`, agy 1.4.3)

```
gemini-4-argon-{high,medium,low}      (the one family agy may serve)
```

The cache also lists models of other families and vendors; `seat_model` refuses every one of
them on every agy path, so they are not reproduced here.

Read `~/.claude/state/agy-models.json` (or `seat_model.py emit --json`) for what is listed and
what resolves now; this block is a dated snapshot. The `-high` / `-medium` / `-low` suffix selects
reasoning effort within a model; the seat role supplies it, or, when the call passes
`--size light|medium|complex`, the task size does (roster rev 7, `model_roster.AGY_LEVEL_BY_SIZE`:
light → `-low`, medium → `-medium`, complex → `-high`; `--user-request` → `-high`).

<HARD-RULE>
**agy serves ONE Gemini family — the one named by `model_roster.AGY_FAMILY`. No role and no
"utility work" carve-out. The one exception is measurement: `model-eval-pack` may name any model
agy lists, only to measure it, never for a seat or delegated work.** (User directive; roster rev 6, 2026-10-21. It replaced the
FLASH-ONLY rule of 2026-07-24: Gemini 4 Argon replaced flash 3.8 on eval evidence — #365, argon
63/63, flash 3.8 53/63 with every loss a tool-reaching no-show.) `seat_model` enforces it in code
on every agy path (roster, freeze pin, env, harness literal); a family swap is a roster revision
(`docs/model-roster-swap.md`).

| Verdict | Models |
|---|---|
| ✅ ALLOWED | `gemini-<v>-argon-{high,medium,low}` — currently `gemini-4-argon-*`; a newer argon version is auto-followed |
| ❌ FORBIDDEN | `gemini-*-flash-*` — the retired family, although agy still lists it |
| ❌ FORBIDDEN | `gemini-*-pro-*` — any pro line |
| ❌ FORBIDDEN | `claude-*`, `gpt-oss-*` — every non-Google slug |

Two independent reasons, both binding:

1. **Provider diversity (the `claude-*` / `gpt-oss-*` half).** agy occupies the third-model slot
   precisely because it is *not* Anthropic and *not* OpenAI. A claude-backed "third model" shares
   the Claude arm's blind spots and the cross-check becomes theatre; `gpt-oss-*` collapses into
   the Codex arm the same way. This is a live trap: agy seats in `avengers` already fail over to
   claude hosts when a shell tool is denied (S062–S067 carry-over), and the
   tempting "fix" for an agy no-show is `--model claude-sonnet-5-5-high`. That is the WRONG fix —
   it converts a *recorded* provider gap into a *hidden* one.
2. **One family, chosen on evidence (the other-Gemini half).** The roster names the strongest
   Google line the account serves, measured with the eval pack; reaching for a different line —
   an older flash or a pro — buys nothing and breaks the comparison the family was chosen on.

**Correct responses to an agy no-show or a weak agy answer:** (a) re-apply the STDIN and
FLAG-ORDER rules and retry from an empty cwd, (b) record the provider gap honestly and proceed short-handed. There is no gemini fallback —
that CLI was retired from this ecosystem 2026-07-25. Never repoint
the model.
</HARD-RULE>

## Verified flags (from `agy --help`, v1.4.12)

| Flag | Meaning |
|---|---|
| `-p`, `--print`, `--prompt` | Run a single prompt non-interactively and print the response |
| `--print-timeout <dur>` | Timeout for `-p` wait (default `5m0s`) |
| `-i`, `--prompt-interactive` | Run an initial prompt, then continue interactively |
| `-c`, `--continue` | Continue the most recent conversation |
| `--conversation <id>` | Resume a specific conversation by ID |
| `--add-dir <path>` | Add a directory to the workspace (repeatable) |
| `--model <name>` | Model for the current CLI session (added in 1.0.5; no short `-m` alias). **Convention: always pass it, resolved by `seat_model.py argv --role <role> --provider agy`** — only the roster family (`model_roster.AGY_FAMILY`, currently argon) is allowed; flash, pro, `claude-*` and `gpt-oss-*` are FORBIDDEN on agy (Models HARD-RULE). List choices with `agy models`. |
| `--sandbox` | Run with terminal restrictions enabled (bubblewrap on Linux). MANDATORY on every call, and MUST come BEFORE `-p` (see FLAG ORDER + SANDBOX RULEs). Restricts the shell only (measured 2026-11-01, 1.4.12) |
| `--mode <accept-edits\|auto\|plan>` | Agent execution mode. `plan` removes native writes and the shell: the advisory call (#366) |
| `--disable-slash-commands` | Disables slash commands and skill expansion in print mode. Does NOT stop native skills: one still ran under it (2026-11-01, 1.4.12) |
| `--dangerously-skip-permissions` | Auto-approve all tool permission requests. Bypasses `allowNonWorkspaceAccess` and, without `--mode plan`, everything else: Pattern 2 only |
| `--log-file <path>` | Override the CLI log file path |

Bare `agy` (no `-p`/`-i`) opens an interactive session.

## Subcommands (verified)

| Command | Notes |
|---|---|
| `agy changelog` | Show changelog / release notes |
| `agy help [sub]` | Help for a subcommand |
| `agy install [--dir D] [--skip-aliases] [--skip-path]` | Configure shell PATH + aliases |
| `agy models` | List available models (added in 1.0.5; pairs with the `--model` flag). Listed output (2026-10-20 cache, agy 1.4.3) in **Models** above. Note that most of what it lists is OFF-LIMITS here: agy serves the roster family only (argon), so flash, `claude-*` and `gpt-oss-*` all appear in the listing but must never be selected |
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
- Binary: `~/.local/bin/agy` (v1.4.12). A separate `antigravity` binary is the IDE; for CLI
  orchestration always use `agy`.

## Context / instructions files (VERIFIED 2026-06-03, empirical probes)

`agy` DOES honour markdown instruction files — the contract was confirmed by writing distinct
sentinels and reading them back via `agy -p` from a clean working directory:

| Path | Scope | Read by agy? |
|---|---|---|
| `~/.gemini/agy.md` | **global** (every invocation, any cwd) | ✅ YES — **the host directive lives here** |
| `~/.gemini/GEMINI.md` | global | ✅ YES — but left **empty** (we use `agy.md`; GEMINI.md is the retired gemini CLI's file) |
| `<cwd>/AGENTS.md` | per-workspace (additive) | ✅ YES |
| `<cwd>/agy.md` | per-workspace (additive) | ✅ YES |
| `~/agy.md` (home root) | — | ❌ NO — not a context path |
| `~/.gemini/antigravity-cli/brain/`, `implicit/*.pb` | agy internal memory | binary protobuf — NOT user-editable |

- **The host directive is `~/.gemini/agy.md`** (created 2026-06-03; hardened 2026-07-02): establishes
  agy's second-opinion/challenger role, an ADVISE-ONLY default (no file writes / state-changing
  commands / git commits unless the prompt explicitly grants them), plain-text output,
  anti-sycophancy, stay-on-prompt, and the `served_by` probe convention. Every `agy -p` call
  inherits it. It is a behavioural layer only — keep the Pattern 1 flags AND the advise-only
  prompt line on every read-only call: the directive can be ignored.
- **Identity caveat:** agy keeps its baked-in "pair-programmer" self-concept — asked "what is
  your role," it recites that, NOT the agy.md text. But it *follows specific instructions* placed
  in agy.md (proven: an exact-string instruction round-tripped verbatim). So put behavioural
  rules in agy.md; don't expect it to re-describe its role from the file.
- **Pollution note:** because agy reads `<cwd>/AGENTS.md` + `<cwd>/agy.md`, calling `agy -p` from
  a project root pulls that project's workspace context in as additive context, and makes the
  project readable. Pattern 1 runs from an empty cwd, so a second opinion stays clean.


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
    verified_against: "1.4.12"
    verified_on: "2026-11-01"
-->
