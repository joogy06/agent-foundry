# Operations Reference — git-cli-bridge

Daily operations, debugging playbook, incident response, and monitoring. Ports Section 6 of the design doc.

## 1. Daily operations cheat sheet

| Want to... | Command |
|---|---|
| Start a new session | `bridge init` (forge auto-invokes) |
| Submit a review | `bridge request --tool gemini --kind review --context diff.patch --wait "Review for security issues"` |
| Submit a research task | `bridge request --tool gemini --kind research --wait "Best practices for JWT revocation in 2026"` |
| Free-form prompt | `bridge request --tool copilot --kind prompt --wait "Suggest a simpler way to do X"` |
| Check status | `bridge status` |
| Get a response | `bridge result <req-id>` |
| Close the session | `bridge close` |
| Prune stale sessions | `bridge cleanup --dry-run` then `bridge cleanup` |

## 2. Debugging playbook

Failed request investigation order:

1. **`bridge result <req-id> --verbose`** — reads `error.md` (if present) and prints the `remediation` block to stderr before the error body. Often tells you exactly what to do next.
2. **Open `workflow_run_url`** from `status.json` / `error.md` and inspect the workflow run in the GitHub Actions UI. The step that failed shows in red.
3. **Heartbeat stale >90s with `state == running`** — the runner crashed or lost network. Delete the request directory (`rm -rf requests/<req-id>`), commit/push, re-submit.
4. **`canary_detected` terminal state** — CRITICAL. See Incident 1 below. Rotate the Copilot PAT if the request used Copilot; review the prompt + context for injection; do not re-submit verbatim.
5. **`tool_install_failed`** — npm transient flake. Wait 5 minutes, re-submit. If it persists, check `workflows/bridge-integrity.lock` against `npm view <pkg>@<ver> dist.integrity`.
6. **`schema_invalid`** — client/workflow version mismatch. Check `.bridge/workflow-version` on the current session branch against `main:.bridge/setup-version`. If they differ, the fix is a fresh `bridge init` for new requests; in-flight requests stay pinned to their original workflow version.
7. **`auth_failed`** — usually WIF setup drift. Re-run `setup-wif.sh`, then see Incident 5 below.

`bridge logs <req-id>` wraps `gh run view --log --job=<job-id>` scoped to the request's workflow run. All output is sanitized (ANSI strip + scrubber) before display.

## 3. Monitoring

Per user ruling B4 (monitoring-only, no hard cost cap):

| Signal | Source | Action threshold |
|---|---|---|
| Monthly Actions minutes | `bridge-budget.yml` cron (day 1 / 15 / 28) | > `vars.BRIDGE_BUDGET_ALERT_MIN` (default 4000) -> posted issue title is prefixed `[ALERT]` instead of `[status]` |
| Daily requests count | `bridge status --all --json` | Spikes -> investigate who/what is submitting |
| Canary detections | Actions run list + error filtering on `error_code: canary_detected` | Any -> incident response (Incident 1) |
| Heartbeat staleness | `bridge status --all --json` parsed for `heartbeat_at` older than 90s with `state == running` | >1/week -> runner stability or CLI hang |
| Copilot PAT expiry | Calendar reminder | 7 days before the 90-day mark -> rotate via `gcloud secrets versions add copilot-bridge-pat --data-file=-` |

## 4. Incident response runbook

### Incident 1 — suspected secret leak in response.md

Symptom: `status: canary_detected` OR user visually spots what looks like a secret in a `bridge result` output.

1. **Halt**: `gh workflow disable bridge-gemini.yml --repo <owner>/ai-bridge-<user>` and `gh workflow disable bridge-copilot.yml`.
2. **Rotate** all credentials that could have been present in the runner environment at the time:
   - Copilot PAT (if Copilot was the tool) — `gcloud secrets versions add copilot-bridge-pat --data-file=-` with a freshly generated PAT.
   - Any `GOOGLE_CLOUD_PROJECT` / SA keys? There should be none (WIF), but verify no `gcloud auth application-default` keys were injected.
3. **Purge history**: `git filter-repo --replace-text patterns.txt` on the affected session branch, OR simpler — delete the branch entirely and let `bridge-maintenance.yml` clean up. Also delete the archive tag.
4. **Update scrubber patterns**: add the leaked shape to `workflows/scripts/scrub-secrets.sh` so it is caught mechanically next time.
5. **Post-mortem**: file an issue in the bridge repo with timeline, root cause, and what mitigations failed.
6. **Re-enable** workflows only after steps 2-4 complete and an unreviewed replay test passes with a dummy secret to confirm the scrubber catches it.

### Incident 2 — runaway Actions minutes

Symptom: `[ALERT]` issue from `bridge-budget.yml` with unusual minute count, or a session branch with hundreds of request directories.

1. `gh workflow disable` both bridge workflows.
2. `gh run list --workflow=bridge-gemini.yml --status=in_progress --json databaseId,headBranch,createdAt --jq '.[] | .databaseId' | xargs -n1 gh run cancel`.
3. Investigate: what client is submitting? (Check `caller.name` in recent request.md frontmatters.)
4. Fix the client or rate-limit the session.
5. Re-enable workflows.

### Incident 3 — bridge repo compromised

Symptom: unauthorized commits, unknown session branches, unexpected workflow runs, unexpected changes to `.github/`.

1. Disable both workflows immediately.
2. Revoke the Copilot PAT in GitHub settings (delete, don't just rotate — you want the token invalid in the old git index as well).
3. Rotate the WIF binding: `gcloud iam service-accounts remove-iam-policy-binding` to remove the `roles/iam.workloadIdentityUser` from the old pool, then create a new pool/provider pair.
4. Nuke the repo: `gh repo delete <owner>/ai-bridge-<user> --yes` and recreate from templates.
5. Audit the workstation for any leaked response files that may have exfiltrated data.
6. Post-mortem and tighten any controls that failed.

### Incident 4 — GitHub Actions outage

Symptom: requests sit in `queued` forever; `gh run list` shows workflows not triggering at all.

1. Confirm outage on https://www.githubstatus.com .
2. Set `AI_BRIDGE_DISABLE=1` for the current shell session to force local CLI use (if available).
3. Wait for recovery.
4. Re-submit any failed requests with fresh request IDs.

### Incident 5 — WIF token refresh fails mid-workflow

Symptom: a workflow step after the initial `google-github-actions/auth@v2` step fails with `invalid_grant` or `token expired`. This is rare — WIF tokens have 1h TTL and workflows are capped at 10 minutes, so expiry should never happen mid-run.

Causes and response:

1. **Service account deleted or disabled**: check GCP IAM audit log for the SA. If disabled, re-enable. If deleted, recreate via `setup-wif.sh` and re-bind.
2. **Pool/provider deleted**: `gcloud iam workload-identity-pools describe ai-bridge-pool --location=global` — if missing, recreate.
3. **Attribute condition changed**: verify `attribute.repository == "<owner>/ai-bridge-<user>"` still matches the actual repo. If the repo was renamed or transferred, update the condition.
4. **Quick workaround** while debugging: fail the request with `error_code: auth_failed`, surface remediation to the user, ask them to re-run after fix.
5. **Blast radius** is bounded by the 10-minute workflow cap — at worst, one request window is lost.

## 5. Version bump playbook (bi-monthly)

```bash
# Check for new versions
npm view @google/gemini-cli version     # expect >= 0.36.0
npm view @github/copilot version         # expect >= 1.0.21

# Run the bump helper (updates bridge-integrity.lock)
bash ~/.claude/skills/git-cli-bridge/scripts/bump-bridge-deps.sh \
  --gemini 0.37.0 --copilot 1.1.0

# Review the generated diff carefully — this is a supply-chain choke point
git diff workflows/bridge-integrity.lock

# If happy, commit
git add workflows/bridge-integrity.lock
git commit -m "bridge: bump gemini 0.36.0 -> 0.37.0, copilot 1.0.21 -> 1.1.0"

# Open a PR on the bridge repo with the updated lock + workflow YAML version strings
# Next bridge init after merge picks up the new versions

# Smoke test the bump: bridge init + a hello-world request on each tool
bridge init
bridge request --tool gemini --kind prompt --wait "say hi"
bridge request --tool copilot --kind prompt --wait "say hi"
bridge close
```

Bumps should happen on a roughly bi-monthly cadence, and any security advisory on either CLI should trigger an immediate out-of-band bump.

## 6. End-of-life / decommissioning

When retiring the bridge entirely (e.g., moving off the sandboxed environment permanently):

1. Close all active sessions: `bridge cleanup --older 0` (forces archive-and-delete on everything).
2. Destroy GCP resources via `auth-and-secrets.md` section 10.
3. Revoke the Copilot PAT from GitHub settings.
4. Delete the bridge repo: `gh repo delete <owner>/ai-bridge-<user> --yes`.
5. Remove the local workspace: `rm -rf $BRIDGE_LOCAL_WORKSPACE/ai-bridge-<user>`.
6. Remove the client skill: `rm -rf ~/.claude/skills/git-cli-bridge ~/.codex/skills/git-cli-bridge`.
7. Remove the `~/.local/bin/bridge` symlink.
8. Remove `git config --global --unset bridge.repo` if you set it during setup.

A `bridge destroy` helper script may be added in a follow-up; the manual steps above are authoritative.

## 7. Observability recipe — per-session summary

Quick one-liner to summarize today's bridge activity:

```bash
bridge status --all --json | jq -r '
  .sessions[] |
  "\(.session_id)\t\(.created_at)\t\(.requests | length) reqs\t\(.requests | map(select(.state == "succeeded")) | length) ok\t\(.requests | map(select(.state != "succeeded" and .state != "running")) | length) err"
'
```

Returns one line per session with ID, creation time, total requests, successful, errored. Pipe to `awk` or `sort` to spot outliers.

## 8. Anti-patterns (operations-specific)

- **Hand-editing `status.json`** to unstick a request. Instead, delete the request directory and re-submit.
- **Manually cancelling workflow runs while leaving `status.json` in `running`**. Use `bridge cleanup --hashes` to clear the state, or delete the request dir.
- **Running `bridge` from cron/CI** — no human-in-the-loop escalation, no rate-limit enforcement by a user, runaway cost risk.
- **Storing the bridge repo URL in a shared dotfile** that could be committed to a work repo — use `git config --global bridge.repo` which lives in `~/.gitconfig`, not tracked.
- **Ignoring `[ALERT]` budget issues** until the monthly report arrives — monitor the label `bridge-budget` and respond within 24h of an alert.
