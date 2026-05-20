---
name: affordance-advisor
description: Use at workflow-completion boundaries to optionally surface host-native command suggestions when running on a known CLI host (Claude Code, Codex, Gemini, Copilot CLI). Reads a per-host affordance registry and returns zero or one structured hint per completion kind. Never executes commands. Activates only when the active host CLI is detected from environment variables; returns an empty result on unknown hosts so portable skills stay safe.
exception_to_codex_symlink_rule: true
---

# affordance-advisor

A single-CLI sidekick that maps **completion events** (bob finished a UI change, alf finished a security pass, forge finalized a MEDIUM+ design, etc.) to **one-line hints** about host-native commands that could accelerate the next step.

The advisor is a **suggestion layer**, not an execution layer. It never runs anything. It hands back a JSON array of recommendations. The caller (model writing a completion report) chooses whether to weave a hint into the report as a final tip.

## Why this exists (the contamination problem)

Every other skill in this fleet is host-agnostic — it must work identically under Claude Code, Codex CLI, Gemini CLI, and Copilot CLI/Chat. If a portable skill body contained a host-native command token (the kind that begins with a forward slash on Claude/Gemini, or a subcommand of `codex`/`gemini`/`gh` etc.), and that skill were symlinked into another host's skill corpus, the foreign host would either follow the suggestion literally (broken) or carry noisy text in its loaded descriptions.

The mitigation is mechanical: host-native command strings live ONLY in this skill's `registry/*.yaml` data files. The body of every other skill stays neutral. A lint test (see `tests/test_lint_portability.py`) enforces this by scanning the entire skill corpus.

**HARD-RULE (advisor):** Skills MUST NOT grep `registry/*.yaml` directly. The only legal read path is `scripts/advise.py`. Direct registry reads bypass the active-CLI gate and re-introduce the contamination risk through copy-paste.

## Mechanism

```
+-----------------------------+        +-------------------------------+
| caller writes completion    | -----> | advise.py --completion-kind X |
| report and looks for hints  |        +---------------+---------------+
+-----------------------------+                        |
                                                       v
                                       +---------------+---------------+
                                       | detect_host_cli.py            |
                                       | reads env vars -> one of:     |
                                       |   claude-code / codex /       |
                                       |   gemini / copilot-cli /      |
                                       |   copilot-chat / unknown      |
                                       +---------------+---------------+
                                                       |
                                  unknown -> [] (no-op, safe everywhere)
                                                       |
                                  known   -> read registry/<host>.yaml,
                                             filter by completion_kind +
                                             orchestrator + risk_class,
                                             return JSON array
```

### Detection signals (env vars only — no process-tree shells, no PATH)

| Signal | Host |
|---|---|
| `CLAUDECODE=1` or `CLAUDE_CODE_ENTRYPOINT` set | claude-code |
| `CODEX_VERSION` set | codex |
| `GEMINI_CLI_SESSION_ID` set (interactive), or `GEMINI_API_KEY` + parent is gemini binary | gemini |
| `COPILOT_*` env var present | copilot-cli |
| `VSCODE_PID` + `TERM_PROGRAM=vscode` | copilot-chat |
| none | unknown |

Detection runs on every advise call (env vars are the live answer). `env-adoption` may cache the result in `inventory.json` under `current_cli` for skills that prefer a manifest read, but the env-var path always works.

### Registry schema (closed)

Every entry in `registry/<host>.yaml`:

```
schema_version: affordance.v1
host_cli: <claude-code|codex|gemini|copilot-cli|copilot-chat>     # or
activation: { tool_on_path: <name> }                              # for utility CLIs like gh

affordances:
  - id: <host>/<short-id>
    command: <opaque token — only this field carries the host-native string>
    risk_class: low | medium | high
    workflow_match:
      orchestrator: [bob|forge|alf|pa|evo|*]
      completion_kind: [ui-change, frontend-route-change, >5-files-edited, ...]
    skip_when:
      orchestrator_failed: true | false
      already_suggested_this_session: true | false
    hint: <one-line description of what to do and why>
    reference: <abs or ~-relative path into another skill or doc>
```

Unknown keys fail the schema test (closed schema). `command` is the only field where host-native command strings live.

## API surface

One CLI:

```
scripts/advise.py --completion-kind <kind> [--orchestrator <name>] [--severity-cap low|medium|high]
```

Returns a JSON array (possibly empty). Each element:

```
{
  "command": <token>,
  "host_cli": <one of the 5 known hosts>,
  "risk_class": "low" | "medium" | "high",
  "hint": "<one-line text>",
  "reference": "<path-to-supporting-doc>"
}
```

Empty array when:
- host is `unknown`
- no affordances match `--completion-kind` (and `--orchestrator` if given)
- every match exceeds `--severity-cap`

Calling the script twice with the same flags returns the same bytes. No hidden state.

## Special design notes

### Not symlinked to ~/.codex/skills/ (or ~/.gemini/, ~/.copilot/)

This skill is the deliberate exception to the global "all new skills MUST be symlinked to ~/.codex/skills/" convention (see `~/.claude/CLAUDE.md` Skill Library section and the `copilot-compatibility` memory). The reason is identical to the reason the registry files exist: this skill is allowed to contain host-native command strings inside `registry/*.yaml`, and any host outside the active one must never read them. Symlinking the directory into another host's skill tree would defeat the active-CLI gate (the foreign host would happily load a description that mentions the wrong host's commands).

The skill ships a sentinel file `.no-codex-symlink` in its root directory. The lab bootstrap installer (`installer/bootstrap-environment.py` step 8) is responsible for honouring the sentinel and skipping the link.

Verification: after install, `ls -la ~/.codex/skills/ | grep affordance-advisor` must return nothing.

### Why no orchestrator code changes

Forge, bob, alf, pa, and evo are intentionally not edited. They discover this skill the same way they discover any other — by description. When a model is about to write a completion report, the advisor's description ("Use at workflow-completion boundaries...") matches; the model invokes `advise.py`, receives 0-or-1 hint, and weaves it into the report as a final tip. If the gate refuses or the registry has no match → no hint, no harm, the report ships as-is.

Future enhancement (deferred): orchestrators add a one-line HARD-RULE "always check the advisor at output time" for guaranteed coverage. Defer until day-one usage tells us whether description-discovery is reliable enough.

### Drift maintenance

Each host CLI iterates its command surface independently. A weekly (manual) drift probe (`tests/test_drift_probe.py`, `@pytest.mark.manual`) diffs the registry against the current help output and reports new/removed commands. Auto-running this is out of scope today.

## Layout

```
~/.claude/skills/affordance-advisor/
+-- SKILL.md                       (this file — mechanism only, no host-native command tokens)
+-- .no-codex-symlink              (sentinel — tells bootstrap installer to skip this skill)
+-- registry/
|   +-- claude-code.yaml
|   +-- codex.yaml
|   +-- gemini.yaml
|   +-- copilot-cli.yaml
|   +-- gh.yaml                    (host-independent, gated on tool_on_path)
|   +-- copilot-chat.yaml          (stub, affordances: [])
+-- scripts/
|   +-- detect_host_cli.py
|   +-- advise.py
|   +-- lint_registry.py
+-- tests/
    +-- test_host_detect.py
    +-- test_advise_gate.py
    +-- test_registry_schema.py
    +-- test_lint_portability.py
    +-- test_advisor_idempotent.py
    +-- test_drift_probe.py        (@pytest.mark.manual)
```

## When this skill does NOT trigger

- Pure information requests ("what does X do?", "explain Y") — no completion event
- TRIVIAL or SIMPLE tasks that didn't run through forge/bob/alf/pa/evo
- Interactive UI loops inside an IDE Chat panel where the user is already in a host-native flow

If the model isn't writing a completion report, it shouldn't be invoking the advisor. The description is deliberately narrow to keep the trigger surface small.
