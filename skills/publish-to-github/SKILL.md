---
name: publish-to-github
description: >
  Use when preparing to publish ~/.claude/skills/, ~/.claude/agents/, and ~/.claude/commands/
  to a public github repository. Wraps publish_prep.py to scrub embedded private content, run extended security
  checks, bundle README and documentation, and produce a clean staging directory ready for
  git init / commit / push. Also trigger on "publish skills to github", "deploy public skills",
  "prepare github release", "scan skills for secrets", "bump skill version", "create publish
  staging directory".
---

# Publish to GitHub

A focused workflow skill that takes your local `~/.claude/skills/` and `~/.claude/agents/`
trees and produces a clean, public-safe staging directory ready to push to a public GitHub
repository.

## Why this skill exists

Most Claude Code users accumulate private context inside their skills over time —
business names, internal paths, project-specific examples, customer details. Publishing
the skill tree to public github without cleanup is a privacy hazard. This skill is the
opposite of that: it produces a vetted, scrubbed copy in a staging directory while
**never modifying your live ~/.claude/ tree**.

## What this skill does NOT do

- Does not modify your live `~/.claude/skills/` or `~/.claude/agents/`
- Does not push to git (you do that yourself)
- Does not create the GitHub repository (you do that on github.com)
- Does not manage credentials, tokens, or SSH keys
- Does not auto-replace your local files
- Does not invent scrub rules — you control them via `~/.claude/publish-config.json`
- Does not try to detect implicit business fingerprints (manual review still required)

## Architecture

The skill is split into two parts:

1. **Generic engine** — `scripts/publish_prep.py` (publishable, contains zero project-specific strings)
2. **Private config** — `~/.claude/publish-config.json` (user-owned, NEVER published)

The engine reads its rules from the config: which directories to exclude, which strings
to find/replace, which patterns to grep for, and which README/docs files to bundle into
the staging dir.

This split is intentional: the engine can be safely published to a public github repo,
while every user maintains their own private rules in their own home directory.

## Operations

### `publish` — full workflow (most common)

Trigger phrases: "publish to github", "deploy public skills", "prepare publish",
"create publish staging", "publish skills".

Steps Claude follows:

1. **Locate the config**
   - Check `$PUBLISH_CONFIG` env var
   - Check `~/.claude/publish-config.json`
   - Check `./publish-config.json`
   - If none found, tell the user to copy `templates/publish-config.example.json`
     to `~/.claude/publish-config.json` and customise it.

2. **Pre-flight summary**
   - Read the config and show the user what will happen:
     - Which directories are excluded
     - How many scrub rules are configured
     - How many forbidden patterns will be checked
     - Where the staging dir will be created
   - Ask for confirmation before running.

3. **Run `publish_prep.py`** (pass `--extended-scan` to include the extended checks)
   ```bash
   python3 ~/.claude/skills/publish-to-github/scripts/publish_prep.py --extended-scan
   ```
   - The script handles all deterministic operations (file copy, scrubs, grep verification).
   - With `--extended-scan` it also runs the extended security patterns from
     `checks/security-patterns.md` against the staging directory.
   - Capture and present the output.

4. **Review extended security warnings**
   - The `--extended-scan` phase reports findings at critical / high / medium / low
     severity: API key shapes, private key blocks, DB connection strings, real-looking
     emails, public IPs, internal TLDs, E.164 phones, large files, dangling symlinks.
   - Findings are warnings, not errors. Review each and either add to config
     (`forbidden_patterns` / `scrubs` / `exclusions`) or accept as false positive.
   - **Suppressing false positives**: Add entries to `extended_scan_ignore` in your
     `publish-config.json` to suppress known false positives (e.g. networking skills
     that legitimately document public DNS IPs, mongodb skill that documents
     `mongodb://user:pass@` example strings). See the example template at
     `templates/publish-config.example.json` for the schema.

5. **Sync metadata — README counts/version + GitHub About** (mechanized; see `sync-metadata`)
   - Run `scripts/sync_metadata.py` to drive ALL THREE drift-prone surfaces from ONE
     live source (the `source.root`+`subdirs`+`exclusions` tree). This replaces the old
     hand-editing of counts, which silently drifted (the catalog README regressed to
     `159 skills / 4 agents` and the public About to `141+ … Gemini` before it was caught
     — see the `repo-metadata-maintenance` memory).
   ```bash
   # README: rewrite **N skills**/**M agents**/**K workflows** bullets + the
   # `**Version:** · **Last published:** · **N skills · …**` header (+ optional --bump).
   python3 scripts/sync_metadata.py readme --readme <staging>/README.md [--bump patch|minor|major]
   # GitHub About: substitutes {skills}/{agents}/… into the publish-config `about` block.
   # Dry-run prints the gh command; add --apply to set it (mirrors "print, don't auto-mutate").
   python3 scripts/sync_metadata.py about --repo <owner/repo> [--apply]
   ```
   - Also hand-add a `## Changelog` entry for the release (the one surface that needs prose).
   - Show the user the diff before committing.

6. **Publish gate — 3-tree `_meta` identity (S043 / #119 C2)**
   - When staging to the agent-foundry public repo via `scripts/stage-to-public.sh`,
     the script now reconciles the safety-critical `_meta` subset (`gates.py`,
     `claims.py`, `identity_check.py`, `classify*.py`, the arbiter spawners, the
     HARD-RULE scan/apply machinery, …) **from prod (`~/.claude`) into the public
     repo BEFORE `git add`**, then runs:
     ```bash
     python3 ~/.claude/skills/_meta/gates.py G_IDENTITY <public_repo> \
       --pair prod-foundry --strict --foundry-root <public_repo>
     ```
   - **Exit 2 BLOCKS the publish** — you cannot push a state that leaves the
     published `_meta` drifted from prod. This is the *authoritative* check (it
     lives in the script, not a hook, because `--no-verify` silently bypasses
     hooks with no log — C7). The agent-foundry pre-push hook, if installed, is
     verify-only defense-in-depth.
   - This makes the standing prod-vs-agent-foundry lag **self-healing**: the next
     publish reconciles it automatically.

7. **Print git commands**
   - First publish: `git init` → `add` → `commit` → `remote add` → `push`
   - Re-publish: detect existing remote in config, print equivalent commands
   - Never auto-execute git commands without explicit user confirmation.

8. **Print rollback / re-run instructions**

### `check` — security scan only

Trigger phrases: "scan skills for leaks", "security check on skills", "check for secrets".

Run only the verification phase against either:
- The current live tree (greps `~/.claude/skills/` and `~/.claude/agents/`)
- An existing staging directory (`--verify <path>`)

No staging dir is created, no files are modified.

### `bump-version` — README version bump only

Trigger phrases: "bump skill version", "increment version", "release new version".

Read the current README, increment the version, update counts and date, write back.
Does not run scrubs, does not create a staging dir.

### `sync-metadata` — reconcile README counts/version + GitHub About from the live tree

Trigger phrases: "sync repo metadata", "update the about section", "fix the skill
counts", "the README counts are stale", "update repo description/topics".

The single-source reconciler for the three surfaces that drift because no one tool
owned them (the `repo-metadata-maintenance` memory). `scripts/sync_metadata.py`:
- **`counts`** — print live `{skills,agents,workflows,commands}` from `source.root`
  applying `exclusions` (the same set the publisher uses, so it matches the published count).
- **`readme --readme P`** — rewrite the `**N skills**`/`**M agents**`/`**K workflows**`
  bullets, the `**N skills · M agents · …**` header tuple, and `**Last published:**`;
  `--bump {patch|minor|major}` also bumps `**Version:**`. Idempotent; reports changes.
- **`about --repo R`** — read the publish-config **`about`** block (a
  `{owner/repo: {description, topics, homepage}}` map whose description may use
  `{skills}`/`{agents}`/`{workflows}`/`{commands}` placeholders), substitute live counts,
  and **print** the `gh repo edit` command — or run it with **`--apply`** (the only
  mutating path; topics are additive via `--add-topic`).
- **`sync --readme P --repo R [--apply]`** — both at once.

Config: add an `about` block to `~/.claude/publish-config.json`. Read-only on the
source tree; `--apply` is the sole outward mutation and is opt-in.

### `validate-config` — sanity check the config

Trigger phrases: "validate publish config", "check publish config".

Parse `~/.claude/publish-config.json`, verify schema, report what's configured.

### `init-config` — create a starter config

Trigger phrases: "set up publish config", "create publish config", "init publish".

If `~/.claude/publish-config.json` does not exist, copy
`templates/publish-config.example.json` to it and walk the user through customising it.

## Config file format

See `templates/publish-config.example.json` for the full schema. Top-level structure:

```json
{
  "version": 1,
  "source": {
    "root": "~/.claude",
    "subdirs": ["skills", "agents"]
  },
  "exclusions": [
    "skills/private-skill-name"
  ],
  "scrubs": [
    {
      "file": "skills/some-skill/SKILL.md",
      "replacements": [
        { "find": "private-string", "replace": "generic-placeholder" }
      ]
    }
  ],
  "forbidden_patterns": [
    "private-string",
    "/absolute/private/path"
  ],
  "bundle_files": [
    { "source": "~/path/to/REPO_README.md", "dest": "README.md" },
    { "source": "~/path/to/docs/dependencies/", "dest": "docs/dependencies" }
  ]
}
```

The `source.root` is the base directory the script walks. Defaults to `~/.claude`.
The `source.subdirs` are the subdirectories to copy. Defaults to `skills` and `agents`.

**S055 — `workflows` subdir (workflow-adoption keystone):** the saved-workflow
library at `~/.claude/workflows/` publishes through the generic subdir walk
(zero engine change — it is just another entry in `source.subdirs`). **No scrub
rule may target `workflows/`** (G-W3): workflow files carry only
ecosystem-relative paths (`progress/`, `.alf/`, `.ledger/`), so prod↔foundry is
byte-identical. Scrubbing `workflows/` is exactly the self-watch divergence
that tripped `identity_check` in the P0c false positive — do not add one.

**Note on bundling directories**: When `bundle_files` points `source` at a directory, the recursive copy SKIPS hidden files (`.foo`) and underscore-prefixed files (`_bar`). To include such a file, add a per-file `bundle_files` entry pointing directly at it instead of its parent directory.

## Extended security checks

The base `publish_prep.py` greps for the `forbidden_patterns` you list in your config.
The skill workflow adds additional heuristic checks (see `checks/security-patterns.md`):

| Category | Patterns | Severity |
|---|---|---|
| API keys | `sk-`, `ghp_`, `xoxb-`, `xoxp-`, `AIza`, `eyJ` (JWT), `pk_live_`, `sk_live_` | critical |
| Private keys | `BEGIN RSA PRIVATE`, `BEGIN OPENSSH PRIVATE`, `BEGIN PGP` | critical |
| AWS / cloud | `AKIA`, `aws_access_key`, `arn:aws:`, `gcp-project-` | high |
| Passwords | `password=`, `passwd=`, `pwd=` followed by non-placeholder | high |
| Tokens | `token=`, `bearer ` followed by non-placeholder | high |
| Real emails | non-RFC-2606 domains (anything not example.com/test/contoso/etc) | medium |
| Public IPs | non-RFC1918, non-TEST-NET | medium |
| Private hostnames | `*.internal`, `*.corp`, `*.local`, `*.lan` | medium |
| Phone numbers | E.164 format `+\d{10,15}` | low |
| Large files | >1MB | warning |
| Binary files | non-text content | warning |
| Dangling symlinks | symlinks pointing outside the staging dir | warning |

These checks produce warnings, not errors. The user reviews each finding and decides
whether to add an exclusion, add a scrub rule, or accept the finding.

## README versioning

If a bundled README has a version header like:

```markdown
# My Claude Skills
Version: 1.2.3
Last published: 2026-04-08
```

The skill can auto-bump the version on each publish:

- **Patch bump (default)**: `1.2.3` → `1.2.4`
- **Minor bump**: `1.2.3` → `1.3.0` (user opts in: "bump minor")
- **Major bump**: `1.2.3` → `2.0.0` (user opts in: "bump major")

The skill also updates:
- `Last published: <today>` line
- Skill count in any "Skills: N skills, M agents" badge
- Category counts in collapsible sections (if recognisable as `<details>` blocks)

If the README has no version header, the skill prompts to add one on first publish.

## File layout

```
~/.claude/skills/publish-to-github/
├── SKILL.md                         (this file — workflow Claude follows)
├── scripts/
│   └── publish_prep.py              (generic engine — no private strings)
├── templates/
│   ├── publish-config.example.json  (config template for new users)
│   ├── README.example.md            (starter README template)
│   └── CHANGELOG.example.md         (changelog template)
├── checks/
│   └── security-patterns.md         (extended scan patterns + how to extend)
└── docs/
    └── workflow.md                  (detailed end-to-end walkthrough)
```

The user's private config lives at `~/.claude/publish-config.json` — outside the skill
directory, never published, gitignored at the user level.

## Hard rules

<HARD-RULE>
Never write to the live ~/.claude/skills/ or ~/.claude/agents/ trees. Every operation
this skill performs is read-only on the live tree. The only writes happen inside the
timestamped staging directory in /tmp/.
</HARD-RULE>

<HARD-RULE>
Never auto-run `git push` or `git commit`. The skill prints git commands; the user
runs them. This avoids accidental publishes and respects the user's git auth setup.
</HARD-RULE>

<HARD-RULE>
The script (`scripts/publish_prep.py`) must contain zero project-specific strings.
All scrub rules, forbidden patterns, and exclusions live in the user's private config
file. If a future change adds a hard-coded string to the script, it is a regression.
</HARD-RULE>

<HARD-RULE>
After running scrubs, the script must verify zero matches for forbidden patterns in
the staging dir before reporting success. If verification fails, the staging dir is
flagged as having leaks and the user is warned. If `grep` is unavailable (e.g.
Windows without WSL), the script fails loudly — it does NOT silently skip. The
user may override this with `PUBLISH_SKIP_VERIFY=1` at their own risk, which marks
the run as `skipped-unsafe`.
</HARD-RULE>

<HARD-RULE>
The skill warns about implicit fingerprints that grep cannot catch (currency symbols,
country names, demographic targeting, channel mixes, named competitors). It does not
attempt to detect them — that requires human judgement. The warning lives in
`checks/security-patterns.md` and is surfaced in the publish workflow.
</HARD-RULE>

## Anti-patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Hard-coding scrub rules in `publish_prep.py` | Couples the engine to one user's data; can't be published without leaking | Keep rules in `~/.claude/publish-config.json` (private) |
| Auto-running git push | One bad commit becomes a permanent public mistake | Print commands, let the user run them |
| Modifying the live ~/.claude/ tree | Loses local examples, breaks ongoing sessions | Operate only on the staging copy |
| Trying to detect implicit fingerprints automatically | False sense of security; LLMs can't reliably spot semantic leaks | Surface a manual review checklist |
| Skipping the forbidden-patterns grep | Defeats the purpose | The grep is the final safety net — never skip |
| Treating the example config as the user's config | Example contains placeholders, not real rules | First-run setup must copy → customise |

## When NOT to use this skill

- For one-off scrubbing of a single file → use `Edit` directly
- For managing private context at runtime (overlaying business names, brand voice on generic skills) → that needs a different design (an MCP server or Codex CLI integration). This skill is publish-time only.
- For managing secrets (API keys, tokens, credentials) → use a real secret manager (`gpg`, `pass`, OS keychain). This skill is for documentation and example data, not credentials.

## Quick reference

```
Skill's job: prepare a clean, scrubbed staging dir of ~/.claude/skills/ + ~/.claude/agents/
             ready for public github publish.
Engine:      scripts/publish_prep.py (generic, reads config)
Config:      ~/.claude/publish-config.json (private, user-owned, never published)
Output:      /tmp/claude-skills-public-<timestamp>/ (cleaned, scrubbed, verified)
Workflow:    config → exclude → scrub → bundle docs → verify → print git commands
What it doesn't do: push, commit, manage credentials, modify live tree, detect implicit fingerprints
```
