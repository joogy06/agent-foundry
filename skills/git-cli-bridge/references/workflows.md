# Workflows Reference — git-cli-bridge

The four GitHub Actions workflows that run on the bridge repo, plus the helper scripts they depend on. All YAML files are templates shipped in `~/.claude/skills/git-cli-bridge/workflows/` and are copied into the bridge repo's `main` branch during first-boot setup. Each session branch gets a pinned snapshot of these files at `bridge init` time (M22).

## 1. The four workflows

| File | Trigger | Purpose | Approx LOC |
|---|---|---|---|
| `bridge-gemini.yml` | `push` to `session/**` with `requests/**/request.md` path filter | Install and run `@google/gemini-cli@0.36.0` with WIF auth, `--approval-mode plan`, and a closed policy | ~150 |
| `bridge-copilot.yml` | `push` to `session/**` with `requests/**/request.md` path filter | Install and run `@github/copilot@1.0.21` with a PAT fetched from GCP Secret Manager and narrow tool whitelisting | ~160 |
| `bridge-maintenance.yml` | `cron: '17 4 * * *'` | Prune stale session branches (>7d), archive before delete, opt-out via repo variable | ~100 |
| `bridge-budget.yml` | `cron: '0 6 1,15,28 * *'` | Report monthly Actions minutes via GitHub issue, flag `[ALERT]` above threshold | ~50 |

Both `bridge-gemini.yml` and `bridge-copilot.yml` are triggered by the same push. Each workflow reads `tool:` from the request frontmatter and exits early if it does not match. In practice `process-request.sh` routes, so a single "process" job is the one that actually invokes the CLI; the two workflows differ mainly in their install / auth / CLI invocation steps.

## 2. `bridge-gemini.yml` — step-by-step

```yaml
name: bridge-gemini

on:
  push:
    branches: ['session/**']
    paths: ['requests/**/request.md']

permissions:
  contents: write
  id-token: write

concurrency:
  group: bridge-gemini-${{ github.ref }}
  cancel-in-progress: false

jobs:
  process:
    runs-on: ubuntu-24.04
    timeout-minutes: 10                                     # SEC-12
    if: |
      github.actor == github.repository_owner &&
      !contains(github.event.head_commit.message, '[bridge-response]')

    steps:
      - name: Checkout session branch
        uses: actions/checkout@<pinned-sha>                 # SEC-9
        with:
          ref: ${{ github.ref }}
          fetch-depth: 0
          persist-credentials: true

      - name: Detect tool from request frontmatter
        id: detect
        run: |
          REQ_DIR=$(git diff --name-only HEAD^ HEAD | grep '^requests/.*/request\.md$' | head -1 | xargs -r dirname)
          TOOL=$(yq '.tool' "$REQ_DIR/request.md")
          echo "req_dir=$REQ_DIR" >> "$GITHUB_OUTPUT"
          echo "tool=$TOOL"       >> "$GITHUB_OUTPUT"

      - name: Exit if tool != gemini
        if: steps.detect.outputs.tool != 'gemini'
        run: echo "This workflow only handles gemini; copilot workflow will pick up."

      - name: Validate request
        if: steps.detect.outputs.tool == 'gemini'
        run: .github/scripts/validate-request.sh "${{ steps.detect.outputs.req_dir }}"

      - name: Authenticate to GCP (WIF)
        if: steps.detect.outputs.tool == 'gemini'
        id: auth
        uses: google-github-actions/auth@<pinned-sha>       # v2.1.8
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: ${{ vars.GCP_SA_EMAIL }}
          token_format: access_token
          access_token_lifetime: 1800s                      # 30 min, workflow is 10

      - name: Set BRIDGE_CANARY
        if: steps.detect.outputs.tool == 'gemini'
        run: echo "BRIDGE_CANARY=$(uuidgen)" >> "$GITHUB_ENV"

      - name: Install @google/gemini-cli (pinned)           # M8, M9
        if: steps.detect.outputs.tool == 'gemini'
        run: |
          npm install -g --ignore-scripts @google/gemini-cli@0.36.0
          .github/scripts/verify-integrity.sh @google/gemini-cli 0.36.0

      - name: Process request                                # M1..M7, M10, M11, M23
        if: steps.detect.outputs.tool == 'gemini'
        env:
          GOOGLE_CLOUD_PROJECT: ${{ vars.GOOGLE_CLOUD_PROJECT }}
          GOOGLE_CLOUD_LOCATION: ${{ vars.GOOGLE_CLOUD_LOCATION }}
          BRIDGE_CANARY: ${{ env.BRIDGE_CANARY }}
        run: .github/scripts/process-request.sh "${{ steps.detect.outputs.req_dir }}" gemini

      - name: Commit response
        if: steps.detect.outputs.tool == 'gemini'
        run: |
          git config user.name  "bridge-bot"
          git config user.email "bridge-bot@users.noreply.github.com"
          git add "${{ steps.detect.outputs.req_dir }}/status.json" \
                  "${{ steps.detect.outputs.req_dir }}/response.md" \
                  "${{ steps.detect.outputs.req_dir }}/error.md" 2>/dev/null || true
          git add "${{ steps.detect.outputs.req_dir }}/logs/" 2>/dev/null || true
          MARKER="[bridge-response]"
          REQ_ID=$(basename "${{ steps.detect.outputs.req_dir }}")
          git commit -m "bridge: response for $REQ_ID $MARKER" || echo "nothing to commit"
          git push origin HEAD:${{ github.ref }}
```

Notes on specific steps:

- The `if:` conditional on the job enforces the triple self-trigger prevention (M15): owner-only + commit marker absent.
- The `concurrency` group allows multiple requests on the same branch to queue rather than cancel each other.
- `actions/checkout@<pinned-sha>` must be a commit SHA, not a tag, per M11.
- The integrity verification step uses `verify-integrity.sh` (a small helper) which reads `workflows/bridge-integrity.lock` and compares `npm view @google/gemini-cli@0.36.0 dist.integrity` against it.

## 3. `bridge-copilot.yml` — differences from `bridge-gemini.yml`

Same skeleton, these steps differ:

```yaml
      - name: Exit if tool != copilot
        if: steps.detect.outputs.tool != 'copilot'
        run: echo "This workflow only handles copilot; gemini workflow will pick up."

      - name: Authenticate to GCP (WIF) — for Secret Manager only
        if: steps.detect.outputs.tool == 'copilot'
        id: auth
        uses: google-github-actions/auth@<pinned-sha>
        with:
          workload_identity_provider: ${{ vars.GCP_WIF_PROVIDER }}
          service_account: ${{ vars.GCP_SA_EMAIL }}

      - name: Fetch Copilot PAT from Secret Manager
        if: steps.detect.outputs.tool == 'copilot'
        id: secrets
        uses: google-github-actions/get-secretmanager-secrets@<pinned-sha>   # v2.2.2
        with:
          secrets: |
            COPILOT_GITHUB_TOKEN:${{ vars.GOOGLE_CLOUD_PROJECT }}/copilot-bridge-pat

      - name: Install @github/copilot (pinned)
        if: steps.detect.outputs.tool == 'copilot'
        run: |
          npm install -g --ignore-scripts @github/copilot@1.0.21
          .github/scripts/verify-integrity.sh @github/copilot 1.0.21

      - name: Process request
        if: steps.detect.outputs.tool == 'copilot'
        env:
          COPILOT_GITHUB_TOKEN: ${{ steps.secrets.outputs.COPILOT_GITHUB_TOKEN }}
          BRIDGE_CANARY: ${{ env.BRIDGE_CANARY }}
        run: .github/scripts/process-request.sh "${{ steps.detect.outputs.req_dir }}" copilot
```

Inside `process-request.sh`, the Copilot invocation uses:

```bash
copilot -p \
  --allow-tool='shell(git:status)' \
  --allow-tool='shell(git:diff)' \
  --deny-tool='shell(curl:*)' \
  --deny-tool='shell(wget:*)' \
  --deny-tool='shell(nc:*)' \
  --secret-env-vars COPILOT_GITHUB_TOKEN,GOOGLE_APPLICATION_CREDENTIALS \
  --no-ask-user \
  --output-format markdown \
  < "$PROMPT_FILE" > "$RESPONSE_STDOUT"
```

The Gemini invocation uses:

```bash
gemini \
  --approval-mode plan \
  --policy .github/bridge-gemini-policy.json \
  --model "$MODEL" \
  --output-format markdown \
  < "$PROMPT_FILE" > "$RESPONSE_STDOUT"
```

## 4. `bridge-maintenance.yml`

```yaml
name: bridge-maintenance
on:
  schedule:
    - cron: '17 4 * * *'
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  prune:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    if: vars.BRIDGE_MAINTENANCE_DISABLED != 'true'
    steps:
      - uses: actions/checkout@<pinned-sha>
        with:
          fetch-depth: 0
      - name: Fetch all session refs
        run: git fetch origin '+refs/heads/session/*:refs/remotes/origin/session/*'
      - name: Prune stale sessions (>7d)
        run: .github/scripts/prune-sessions.sh 7 60      # 7 days stale, 60 days archive tag retention
```

Safety gates inside `prune-sessions.sh`:
- Skip any branch where `git show <ref>:requests/*/status.json` contains `"state":"running"`.
- Archive before delete: push `archive/session/<id>-<YYYYMMDD>` tag.
- Prune archive tags older than 60 days.
- Opt-out via repo variable `BRIDGE_MAINTENANCE_DISABLED=true`.

## 5. `bridge-budget.yml`

```yaml
name: bridge-budget
on:
  schedule:
    - cron: '0 6 1,15,28 * *'
  workflow_dispatch: {}

permissions:
  issues: write
  actions: read

jobs:
  report:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - name: Fetch billing
        id: billing
        run: |
          MIN=$(gh api repos/${{ github.repository }}/actions/billing/usage --jq .total_minutes_used)
          echo "minutes=$MIN" >> "$GITHUB_OUTPUT"
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      - name: Open or update issue
        run: |
          THRESHOLD="${{ vars.BRIDGE_BUDGET_ALERT_MIN }}"
          THRESHOLD="${THRESHOLD:-4000}"
          TAG="[status]"
          if [ "${{ steps.billing.outputs.minutes }}" -gt "$THRESHOLD" ]; then
            TAG="[ALERT]"
          fi
          TITLE="$TAG bridge budget $(date -u +%Y-%m-%d): ${{ steps.billing.outputs.minutes }} min used"
          gh issue create --title "$TITLE" --body "Actions minutes this cycle: ${{ steps.billing.outputs.minutes }} / threshold $THRESHOLD" \
            --label bridge-budget || true
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Threshold is `vars.BRIDGE_BUDGET_ALERT_MIN` (repo variable), default 4000 when unset. If the current cycle exceeds it, the posted issue is titled `[ALERT] ...` and can be routed by label filters.

## 6. Helper scripts (under `workflows/scripts/`)

| Script | Purpose | Mitigations |
|---|---|---|
| `process-request.sh` | Per-request driver. Parses frontmatter, drives the state machine, assembles the prompt via M1, invokes the CLI with timeout, runs scrubber + canary, writes response.md with full frontmatter, captures scrubbed log tails. Background heartbeat updater updates `heartbeat_at` every 15s during `running_tool`. | M1, M2, M3, M4, M5, M6, M7, M22, M23 |
| `assemble-prompt.sh` | M1 delimiter wrapping. Writes `<system>...</system><request>...</request><user_data src="...">...</user_data>` assembled prompt to stdout. | M1 |
| `scrub-secrets.sh` | M5 regex scrubber. In-place sed on a file. Patterns for Google API key, OpenAI key, GitHub PATs, Slack tokens, OAuth access tokens, Bearer tokens, PEM blocks. | M5 |
| `canary-check.sh` | M6 canary detection. Exit 0 if canary value found (BAD), 1 if not (GOOD). | M6 |
| `sanitize-logs.sh` | M23 log scrubber. Stdin filter applying scrubber + ANSI strip. | M23 |
| `validate-request.sh` | Schema validation via yq. Enforces all `request.md` field constraints from `protocol.md` §3. | M22 |

## 7. Pinning policy

- `actions/checkout@<sha>` — pin by commit SHA from an official release, never a tag.
- `google-github-actions/auth@<sha>` — likewise, at v2.1.8 equivalent SHA.
- `google-github-actions/get-secretmanager-secrets@<sha>` — at v2.2.2 equivalent SHA.
- `google-github-actions/run-gemini-cli@<sha>` — if used; otherwise the raw `gemini` binary after `npm install -g` is preferred for a smaller trusted surface.
- `runs-on: ubuntu-24.04` — never `ubuntu-latest`.

Updates to any pinned SHA go through `scripts/bump-bridge-deps.sh` which refreshes `workflows/bridge-integrity.lock` (npm) and leaves Action SHAs to a manual PR with a note pointing at the official release commit.

## 8. Concurrency and rate limiting

- Per-session: `concurrency.group: bridge-gemini-${{ github.ref }}` serializes runs within one branch.
- Client-side: `bridge request` refuses to submit more than 10 requests in 60 seconds per session.
- Workflow side: `timeout-minutes: 10` hard cap plus per-CLI `--max-runtime 300`.

## 9. What a response commit looks like

```
Author: bridge-bot <bridge-bot@users.noreply.github.com>
Commit message: bridge: response for req-20260409-143501-9b4e2f18 [bridge-response]
Files changed:
  requests/req-20260409-143501-9b4e2f18/status.json  (M)
  requests/req-20260409-143501-9b4e2f18/response.md  (A)
  requests/req-20260409-143501-9b4e2f18/logs/runner.log      (A)
  requests/req-20260409-143501-9b4e2f18/logs/tool-stdout.log (A)
  requests/req-20260409-143501-9b4e2f18/logs/tool-stderr.log (A)
```

Note that `request.md` is NOT in the changed-files list on the response commit — which is exactly how the path filter `paths: ['requests/**/request.md']` guarantees the response commit does not re-trigger the workflow (third layer of M15).

## 10. Failure modes

| Symptom | Likely cause | Where to look |
|---|---|---|
| Workflow never triggers | Push was not on `session/**`, or request.md path filter did not match, or actor != owner | Actions tab, checked runs, workflow YAML |
| Auth step fails `invalid_grant` | WIF pool/SA missing; see `operations.md` Incident 5 | Step log + GCP IAM audit log |
| Integrity mismatch on install | Upstream dep integrity changed without bump | `workflows/bridge-integrity.lock` vs `npm view` |
| `canary_detected` terminal state | CLI echoed env var into response; prompt injection likely succeeded | error.md `phase_when_failed == running_tool`, review assembled prompt |
| `tool_timeout` | CLI ran longer than `max_runtime_sec` from request | error.md + workflow run log |
| Heartbeat stale >90s | Runner crashed or lost network; workflow might still complete | status.json + workflow run state |
