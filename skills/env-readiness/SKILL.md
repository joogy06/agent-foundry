---
name: env-readiness
description: "Use when you want a READ-ONLY readiness review of a Claude Code environment — does this machine have everything wired for the local forge/bob/alf/skills setup? Reviews ~/.claude (global) plus an optional per-project .claude/ across every dimension (skills/agents/workflows installed, SessionStart hooks wired, config files present, gates import, 3-tree identity, tooling tier, knowledge-grounding, per-project hygiene) and prints a single READY / READY-WITH-WARNINGS / NOT-READY verdict with a prioritized repair list. NEVER mutates — repairs are the installer's job (it points at installer/bootstrap-environment.py). Composes the existing probes (env-adoption, identity_check, gates, knowledge-grounding). Trigger on: \"is my environment ready\", \"readiness sweep\", \"review my claude setup\", \"check ~/.claude\", \"env doctor\", \"is this a new machine set up correctly\", \"are the hooks/gates/skills wired\"."
---

# env-readiness — read-only environment readiness doctor

The **review** counterpart to `installer/bootstrap-environment.py` (which **installs
and wires**). The doctor answers one question — *"is this environment ready for our
setup?"* — and **never changes anything**. It composes the existing probes into one
verdict and points every fix at the installer or a specific probe.

## When to use it

- A fresh machine / new clone — confirm everything is wired before relying on it.
- After `bootstrap-environment.py` — verify the wire-up actually took.
- Anytime a session "feels off" (no hooks firing, a gate missing, drift suspected).
- In CI — `--strict --json` to fail a pipeline when the env is NOT-READY.

## Run it

```bash
python3 ~/.claude/skills/env-readiness/scripts/readiness.py            # review ~/.claude (+ CWD project if it has .claude/)
python3 .../readiness.py --project /path/to/repo                       # also review a specific project
python3 .../readiness.py --json                                        # machine-readable
python3 .../readiness.py --strict                                      # exit 1 when NOT-READY (CI gate)
python3 .../readiness.py --claude-home /custom/.claude                 # non-default home
```

## What it checks (each → PASS / WARN / FAIL + a repair pointer)

| Dimension | Checks | Composes |
|---|---|---|
| **Install** | skills/agents/workflows counts + key skills (forge, env-adoption, …) and agents (bob, alf, pa, evo, wiki); CLAUDE.md; AGENTS.md symlink; claude-observe bin; Codex mirror parity | `install.py`, `bootstrap` |
| **Hooks** | the 5 canonical SessionStart hooks wired in `settings.json` | settings.json |
| **Config** | `policy-limits.json` (mode 0600), `model-policy.yaml`, `publish-config.json` present + parse | file probes |
| **Gates** | `_meta/gates.py` imports + loads in a child process | gates.py |
| **Identity** | 3-tree (prod/shadow/agent-foundry) parity (advisory) | `identity_check.py` |
| **Tooling** | env-adoption inventory + tools on PATH; knowledge-grounding mode | `probe.sh`, `discover.sh` |
| **Project** | `.claude/settings.local.json` parses, project CLAUDE.md, stale `.forge`/`.bob`/`.ledger` artifacts | per-project walk |

Verdict: **READY** (all PASS) / **READY-WITH-WARNINGS** (≥1 WARN, no FAIL) /
**NOT-READY** (≥1 FAIL).

## Design guarantees

- **Read-only.** No file is written, no setting changed. Every repair is a pointer
  (usually `python3 installer/bootstrap-environment.py`), never an action.
- **Crash-proof.** Each check is isolated — a broken probe becomes a FAIL row, never
  a traceback that aborts the sweep.
- **Stdlib-only.** No third-party dependency; runs on any `python3`.

## Relationship to other tooling

- `installer/bootstrap-environment.py` — the **fix** side (idempotent install + wire).
  The doctor reviews; bootstrap repairs. Run bootstrap, then the doctor to confirm.
- `env-adoption` — the tool-tier probe the doctor reads (`inventory.json`).
- `knowledge-grounding` — the source/internet probe the doctor reads (`sources.json`).
- `_meta/identity_check.py` — the 3-tree byte-parity check the doctor invokes.
- `_meta/gates.py` — the gate registry the doctor import-smokes.
