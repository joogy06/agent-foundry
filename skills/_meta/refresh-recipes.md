# Refresh Recipes — typed bob-executable updates (Evergreening v1, S041)

When the user approves an evergreen sweep finding (D1: detect → report → **user
approves** → bob applies), bob turns it into an update using one of these **4 typed
recipes**. The point of typing them is cost discipline: **a patch bump is a re-stamp,
never a forge cycle** (the HARD guardrail). Each recipe declares its routing (SIMPLE
batch WP vs MEDIUM) and its acceptance checks.

The detection bus has NO skill-write path (D1). These recipes are the ONLY way a
finding becomes a change, and they run ONLY under bob with explicit user approval.

---

## Recipe (1) — `cli-reference`

**When:** a CLI/plugin version bump changed a documented surface (flags, commands,
version anchors) in a CLI-reference skill (`claude-code-cli`, `codex-orchestration`,
`gh-copilot-cli`, `antigravity-cli`, `gemini-cli`).

**Steps:**
1. Run the verify script for the tool:
   - `claude-code-cli/scripts/verify-claude-install.sh`
   - `gh-copilot-cli/scripts/verify-copilot-install.sh`
   - `codex-orchestration/scripts/verify-codex-install.sh` (S041)
   - `antigravity-cli/scripts/verify-agy-install.sh` (S041)
2. Take the **normalized** flag/command diff (sorted token sets; no prose/order).
3. Update the version anchors + any affected command/flag tables in the skill body.
4. `python3 ~/.claude/skills/_meta/freshness.py restamp <skill>/SKILL.md --tool <t> --to <ver>`
   (atomic anchor + date update; inserts a FRESHNESS:v1 block if absent).
5. Emit a `claude-observe` maintenance event (best-effort).

**Routing (HARD guardrail):**
- **patch or minor** version, no command-set change → **SIMPLE batch WP (restamp-only).
  NEVER a forge cycle.**
- **command-set delta** (a command/flag added or removed) → **MEDIUM** (new prose
  sections describing the change; the surface actually moved).

**Cross-repo step:** if `surface_class == cli-reference` AND the change affects the VS
Code wrapper → `cpmail send --to vs-code-foundry` notification. The edge is
**notify-only, never edit** (vs-code-foundry has its own release cadence).

---

## Recipe (2) — `orchestration-pattern`

**When:** a delegation/orchestration pattern (in `codex-orchestration`, `forge` Step 4b,
`cross-cli-deliberation`, `git-cli-bridge`) may have changed behaviour — NOT just a flag.

**Steps:**
1. **EMPIRICAL re-verification** — actually EXECUTE the documented commands. The
   stdin-pipe class of change (e.g. `echo prompt | codex exec -s read-only`) cannot be
   caught by a flag diff; you have to run it.
2. Capture the real output; compare against what the doc claims.
3. Update the pattern doc + restamp.

**Routing:** **MEDIUM always.** Behaviour verification is never a blind restamp.

---

## Recipe (3) — `knowledge-snapshot`

**When:** a dated knowledge snapshot is in horizon (e.g. `market-snapshot-2026-06.md`
REVIEW-BY 2027-01; the OWASP/NIST freshness anchors).

**Steps:** This is the **S040 market-snapshot pattern** — reference it, do NOT redesign.
1. Web-refresh each `[AS_OF: <date>]` row (per the snapshot's own protocol).
2. Rename/bump the file + header to the new date.
3. Propagate qualitative-claim changes into the consuming skill bodies (they carry
   claims + pointers only).

**Routing:** **Deadline-driven MEDIUM.**

---

## Recipe (4) — `registry-data`

**When:** the drift runner reports a CONFIRMED command addition/removal for a CLI →
the affordance registry needs new/removed rows.

**Steps:**
1. Add/remove the affordance rows in `affordance-advisor/registry/<host>.yaml`.
2. Bump `validated_against: {cli_version, date}` in that registry's header.
3. Re-run the affordance-advisor lint + tests.

**Routing:** **SIMPLE.**

---

## Acceptance checks (run per refresh WP, every recipe)

Before a refresh WP is "done", bob verifies:

1. **FRESHNESS block valid** — `freshness.py lint <file>` returns no errors.
2. **Anchor == inventory** — the restamped version matches `inventory.json` for that tool.
3. **YAML frontmatter lint** — the skill's frontmatter still parses (the recurring
   unquoted-colon class bug — S034/S040).
4. **No banned-phrase regression** — the publish forbidden-patterns grep is clean.
5. **Symlink / sentinel intact** — Codex symlink resolves (or the `.no-codex-symlink`
   sentinel is honored, e.g. affordance-advisor).
6. **Shadow sync LAST** — the skill_factory shadow copy is updated only after the
   production edit + checks pass (mirrors the publish pipeline order).

## Cost guardrail (the throughline)

The single most important rule: **patch/minor cli-reference = restamp-only SIMPLE batch
WP, never a forge cycle.** A re-stamp is `freshness.py restamp` + an anchor table edit —
minutes, not a design cycle. Reserve MEDIUM for genuine surface movement (new commands,
changed behaviour, knowledge refresh). Cost fields are reserved (`tokens_spent: null`)
until #124 threads cost through the flow.
