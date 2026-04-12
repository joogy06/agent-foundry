# Workflow Walkthrough — End-to-End

This document walks through the complete `publish-to-github` workflow for both first-time
setup and ongoing re-publishes. Read this if you want to understand exactly what happens
when you say "publish skills to github".

---

## First-time setup

### Step 1 — Install the skill

If you cloned this repo from public github, the skill is already at
`~/.claude/skills/publish-to-github/`. If you got it some other way, copy it there.

Verify Claude can see it:
```bash
ls ~/.claude/skills/publish-to-github/SKILL.md
```

### Step 2 — Create your private config

Copy the example template to your private config location:
```bash
cp ~/.claude/skills/publish-to-github/templates/publish-config.example.json \
   ~/.claude/publish-config.json
```

Edit `~/.claude/publish-config.json` to match your situation. The fields:

- **`source.root`** — base directory to copy from (default: `~/.claude`)
- **`source.subdirs`** — which subdirs to copy (default: `["skills", "agents"]`)
- **`exclusions`** — directories to exclude entirely (e.g. private skills)
- **`scrubs`** — find/replace rules for files with embedded private content
- **`forbidden_patterns`** — strings to grep for as final safety check
- **`bundle_files`** — external files (README, docs) to include in the staging dir

### Step 3 — Validate the config

```bash
python3 ~/.claude/skills/publish-to-github/scripts/publish_prep.py --validate-config
```

Should print the count of exclusions, scrubs, patterns, and bundles. If it errors,
fix the JSON syntax or schema issues it reports.

### Step 4 — Run a first publish

In Claude Code, say:

> publish skills to github

Claude follows the SKILL.md workflow:
1. Locates your config
2. Shows what will be excluded/scrubbed/bundled
3. Asks for confirmation
4. Runs `publish_prep.py --extended-scan` (the `--extended-scan` flag runs the
   extra security regex patterns described in `checks/security-patterns.md` as a
   Phase 5b step inside the script itself, instead of Claude hand-running them)
5. Reports findings as warnings
6. Prints git commands

You inspect the staging directory:
```bash
cd /tmp/claude-skills-public-<timestamp>
ls -la
cat README.md
```

### Step 5 — Review extended security warnings

The skill workflow runs additional grep checks beyond what's in your config. If it
finds potential leaks (real emails, public IPs, API key shapes, etc.), it reports them
as warnings.

For each warning, decide:
- **It's a leak** → add to `forbidden_patterns` in your config, re-run publish
- **It's a known string that needs scrubbing** → add a `scrub` rule, re-run publish
- **It's a whole file you don't want published** → add to `exclusions`, re-run publish
- **False positive** → add to `extended_scan_ignore` in your config to suppress it
  on future runs, then proceed

**Common false positives**: Skills that document credential-shaped strings (e.g.
`mongodb://user:pass@` in mongodb skill), networking skills with public DNS IPs
(1.1.1.1, 8.8.8.8), `.local` TLDs in mDNS examples, and the publish-to-github
skill's own pattern definitions matching themselves. Add these to
`extended_scan_ignore` in your config (see
`templates/publish-config.example.json` for schema) to suppress them.

### Step 6 — Manual review for implicit fingerprints

The grep cannot catch implicit business fingerprints. You must manually skim the
key skill files for:
- Currency symbols (£, $, €) and price examples
- Country/jurisdiction references
- Industry-specific framings that uniquely identify your business
- Tone of voice and personal phrasing

This is the part that will always require human judgement.

### Step 7 — Initialise the git repo

The skill prints these commands. Copy/paste them yourself — the skill never auto-runs git:

```bash
cd /tmp/claude-skills-public-<timestamp>
git init -b main
git add .
git commit -m "Initial commit: Claude Code skills and agents"
```

### Step 8 — Create the GitHub repo

On github.com:
1. Create a new repository (empty, no README, no .gitignore — your staging already has them)
2. Copy the SSH or HTTPS URL

### Step 9 — Push to GitHub

```bash
git remote add origin git@github.com:YOURNAME/REPONAME.git
git push -u origin main
```

### Step 10 — Verify

```bash
# Optional: re-verify the staging dir is still clean
python3 ~/.claude/skills/publish-to-github/scripts/publish_prep.py --verify /tmp/claude-skills-public-<timestamp>

# Visit your github repo and spot-check a few files
```

### Step 11 — Clean up the staging dir (optional)

```bash
rm -rf /tmp/claude-skills-public-<timestamp>
```

The `/tmp` directory clears on reboot anyway, so this is optional.

---

## Re-publishing after updates

When you've added new skills, updated existing ones, or changed any configuration,
run the workflow again. The script creates a fresh timestamped staging directory
each time — there's no state to manage.

```
You: publish skills to github
Claude: [runs the workflow, produces a new staging dir]
You: cd /tmp/claude-skills-public-<new-timestamp>
You: git init -b main
You: git remote add origin git@github.com:YOURNAME/REPONAME.git
You: git fetch origin
You: git reset --soft origin/main      # adopt the existing remote history
You: git add .
You: git commit -m "Update: skill changes since last publish"
You: git push origin main
```

For convenience, the skill workflow can detect an existing local clone of your repo and
print the equivalent "update existing clone" commands.

### Alternative re-publish: clone-and-overwrite

```bash
# Clone the existing public repo
git clone git@github.com:YOURNAME/REPONAME.git /tmp/claude-skills-clone

# Run the publish prep
python3 ~/.claude/skills/publish-to-github/scripts/publish_prep.py

# Copy the new staging contents over (preserving .git)
rsync -av --delete --exclude='.git/' /tmp/claude-skills-public-<ts>/ /tmp/claude-skills-clone/

# Commit and push from the clone
cd /tmp/claude-skills-clone
git add .
git diff --staged    # spot-check
git commit -m "Update: <date>"
git push origin main
```

---

## When something goes wrong

### "Verify failed — N leaks remaining"

The script's grep found one or more `forbidden_patterns` matches in the staging dir
AFTER scrubbing. Possibilities:

1. **A scrub rule didn't fire** — the find string in your scrub rule doesn't exactly
   match the text in the file. Fix the find string and re-run.
2. **A new occurrence appeared** — you added new content to an existing skill that
   contains the forbidden string. Add a new scrub rule or remove the content.
3. **The forbidden string appears in a file the scrubs don't target** — add a new
   scrub entry for that file, or add the file to exclusions.

The script's output tells you which file and line.

### "Bundle file not found"

Your `bundle_files` config has a `source` path that doesn't exist. Check:
- Is the path correct?
- Did you move/rename the source recently?
- Is `~` expansion working? (the script handles `~` and `$VARS`)

### "Config not found"

The script searched these locations and found nothing:
- `$PUBLISH_CONFIG`
- `~/.claude/publish-config.json`
- `./publish-config.json`

Create one at `~/.claude/publish-config.json` from the example template.

### "skills/publish-to-github already exists"

That's fine — the script overwrites the staging dir on each run. If you're seeing this
in your live `~/.claude/skills/`, it means the skill is already installed. Don't try
to install it twice.

### Staging dir from a previous run is huge / has stale content

The script recreates the staging dir from scratch each run. If you have many old
staging dirs cluttering `/tmp/`, clean them up:
```bash
rm -rf /tmp/claude-skills-public-*
```

---

## What the workflow does NOT cover

- **Secrets management** — use a real secret manager (`pass`, `gpg`, OS keychain)
- **CI/CD** — this is a one-shot manual workflow, not continuous deployment
- **Multi-machine sync** — your private config doesn't sync between machines automatically;
  copy it manually or use a private dotfile manager
- **History rewriting** — if you accidentally pushed a leak in a prior commit, this skill
  can't help you scrub git history. Use `git filter-repo` or `BFG Repo-Cleaner`.

---

## Related skills and tools

- **`mcp-server-creator`** — if you eventually want a runtime context system instead
  of publish-time scrubbing, build an MCP server
- **`docker-cicd`** — if you want to automate the publish in CI (would need to be
  configured to read the private config from somewhere safe)
- **`gh-copilot-cli`** — the GitHub Copilot CLI skill, for git/github operations
