# foundry-lab — project instructions

The global rules are not in this file. They live in `~/.claude/CLAUDE.md`, which Claude Code loads in every
project, and its source is `global/CLAUDE.md` in this repo. This file holds only what is specific to foundry-lab,
so that a foundry-lab session loads the global rules once instead of twice (#318).

## Editing the global rules (repo is primary)

1. Edit `global/CLAUDE.md` here, never `~/.claude/CLAUDE.md` directly: the home copy is installer output, and a
   hand edit there is unbacked state that the next install overwrites or refuses to touch.
2. Regenerate the migration manifest in the same commit, or `test_claude_md_adoption` fails:
   `python3 install.py --regen-global-manifest` (refuses without full git history; writes atomically).
3. Commit, then install: `python3 install.py --target c --dry-run`, then `python3 install.py --target c`. The home
   copy is create-if-absent; an unmodified installer copy is refreshed automatically, and a customised one needs
   `--force-global-config` (a numbered backup is written first).
4. Confirm `cmp global/CLAUDE.md ~/.claude/CLAUDE.md` is silent.

Do not copy a global section into this file: `tests/installer/test_claude_md_split.py` fails if any H2 heading of
`global/CLAUDE.md` appears here. Rules that apply only in foundry-lab go below.

## foundry-lab only

- The roster runbook is `docs/model-roster-swap.md`.
- New skills are created here under `skills/` and reach `~/.claude/skills/` and the Codex/agy mirrors through
  `install.py`, never by editing the home tree.
- The line budget and the pinned-text tests for the global rules (`skills/_meta/tests/test_contract_lint.py`)
  read `global/CLAUDE.md`.
