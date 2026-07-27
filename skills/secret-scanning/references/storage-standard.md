# Secrets storage standard — `~/.secrets/` + loader + pre-commit

Host-wide standard for where secrets LIVE and how processes RECEIVE them.
Adopted 2026-07-25 from a cross-project proposal (`a sibling project`).

## The framing that matters

**Storage and delivery are different questions.** An environment variable is how a
process *receives* a secret; it is not where one is *kept*. The standard is both, in
sequence:

```
~/.secrets/<project>.env   ->   loader   ->   process environment   ->   your code
   storage (0600)                              delivery (ephemeral)
```

Getting this backwards — treating `.env` files scattered through repos as "storage" —
is what produces the failure this standard exists to prevent.

## The rules

| Layer | Rule |
|---|---|
| Storage | `~/.secrets/<project>.env`, mode **0600**; directory `~/.secrets/` mode **0700**. Values shared by several projects go in `~/.secrets/common.env`. |
| Delivery | A loader exports them into the process environment at run time. **Real environment variables WIN over file values**, so one-off overrides, CI, and container injection keep working. |
| In the repo | `.env.example` (names only, never values), a `.gitignore` rule, and the loader invocation. Nothing else. |
| Never | Values in code, in `.md` docs, in committed `.claude/*.json`, or typed into shell history. |
| Enforcement | A **pre-commit** hook refuses the commit. See "Enforcement" below. |

### Why central, not per-repo

In priority order:

1. **Rotation becomes possible at all.** A shared credential gets exactly one home.
2. **Directory copies stop multiplying credentials.** This is structural, not
   disciplinary — copying a project no longer copies its keys.
3. **Survives non-interactive contexts** — cron, background runs, restarted shells.
4. **One thing to `chmod`, back up, and audit.**

The motivating case, from the originating report: the same WooCommerce REST consumer
key was embedded in *both* a storefront repo and an ETL repo. A "rotate credentials"
task stayed open for months — not because rotation is hard, but because **nobody could
enumerate the copies**.

## Honest caveats — do not oversell this

- **`~/.secrets/` is plaintext on disk.** It is a large improvement (far fewer copies,
  one audit point, one thing to back up) but it is **NOT encryption and NOT a secret
  manager**. The upgrade path when you need real secrecy at rest is `age` + `sops`, or
  `pass`. None of those are installed on this host today.
- **Environment variables are not a security boundary.** They are readable via
  `/proc/<pid>/environ` by the same user, inherited by every subprocess, and can surface
  in `ps` output. That is fine for *delivery*; it is not an argument for using them as
  *storage*.
- **Scrubbing is not rotation.** Removing a secret from files keeps it out of future
  git history. It does **nothing** for a credential that has already been exposed —
  that one must be rotated at the provider.
- **A standard without enforcement is decoration.** The pre-commit hook is the
  load-bearing part; the layout is just the thing it protects.

## Enforcement

One pattern set, two enforcement points — they cannot drift because both call the same
scanner:

| When | Mechanism |
|---|---|
| `git commit` | `.git/hooks/pre-commit` → `scripts/secrets-scan.py --staged` (reads content from the **git index**, so it scans exactly what is about to be committed) |
| `git push` | `.git/hooks/pre-push` → `scripts/secrets-scan.py` (full worktree) |
| Agent cycles | `G_SECRETS_SCAN` gate in `_meta/gates.py`, same scanner |

Install both hooks in a repo:

```bash
python3 scripts/install-pre-push-hook.py        # push-time (existing)
bash   skills/secret-scanning/hooks/install.sh  # commit-time (this standard)
```

Commit-time is the one that matters most: it stops the secret before it ever enters
history, where push-time only stops it before it leaves the machine.

## Migration recipe — explicitly NOT big-bang

Adopt for new work immediately. Migrate an existing project **when you next touch it**,
not in a sweep:

1. `mkdir -p ~/.secrets && chmod 700 ~/.secrets`
2. Move the project's real values: `mv <repo>/.env ~/.secrets/<project>.env && chmod 600 ~/.secrets/<project>.env`
3. Leave a names-only `.env.example` in the repo. Verify it holds **no values**.
4. Add `.env` to `.gitignore` if it is not already there.
5. Source the loader at the entry point (see `scripts/load-secrets.sh` / `load_secrets.py`).
6. Install the pre-commit hook.
7. **Rotate anything that was ever committed.** Step 7 is not optional and not covered
   by steps 1-6.

## Scope note

`~/.secrets/` is per-user and per-host. It is deliberately outside any repo, so it is
never in a git working tree, never in a backup of a project directory, and never copied
by duplicating a project folder.
