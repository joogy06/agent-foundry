# Auth and Secrets Reference — git-cli-bridge

How the bridge handles Google Cloud auth (Gemini path) and GitHub auth (Copilot path) without storing long-lived credentials in GitHub. Ports Section 5.3 SEC-1, SEC-3 and Section 6.4 / 9.1 of the design doc.

## 1. The problem

Both AI CLIs need credentials to run inside a workflow runner:

- **Gemini CLI** needs a Google Cloud access token to call Vertex AI.
- **Copilot CLI** needs a GitHub personal access token (`COPILOT_GITHUB_TOKEN`) with the "Copilot Requests" permission.

Putting either directly in GitHub secrets has three problems: no rotation, no audit trail, large blast radius if the repo is compromised, and PATs cannot be scoped finely enough to satisfy SEC-3.

## 2. The solution

- **Gemini path**: Workload Identity Federation. GitHub Actions presents an OIDC token; GCP validates it via a pinned pool/provider that only accepts this one repo, and mints a short-lived (1h) Vertex AI access token. No secrets in GitHub at all.
- **Copilot path**: The PAT lives in GCP Secret Manager. The workflow uses WIF (same pool, same provider) to fetch the secret at runtime into `COPILOT_GITHUB_TOKEN` for exactly the CLI step. Rotation is done in GCP; GitHub never sees the stored PAT directly.

Both paths share the same WIF infrastructure, so first-boot setup is one `setup-wif.sh` invocation covering Gemini and Copilot simultaneously.

## 3. Workload Identity Federation overview

```
GitHub Actions runner                GCP IAM
---------------------                -------
oidc-token:
  iss=token.actions.githubusercontent.com
  aud=<configured audience>
  sub=repo:<owner>/ai-bridge-<user>:ref:refs/heads/session/xxx
  repository=<owner>/ai-bridge-<user>
  actor=<owner>

                 |
                 | exchange at sts.googleapis.com
                 v
  Workload Identity Pool: ai-bridge-pool
     Provider: ai-bridge-github-provider
        attribute_mapping:
          google.subject = assertion.sub
          attribute.repository = assertion.repository
          attribute.actor = assertion.actor
        attribute_condition:
          assertion.repository == "<owner>/ai-bridge-<user>" &&
          assertion.actor == "<owner>"
     Service Account impersonation:
        serviceAccountUser role on ai-bridge-sa@<proj>.iam.gserviceaccount.com

                 |
                 | impersonate
                 v
  Service Account: ai-bridge-sa@<proj>.iam.gserviceaccount.com
     IAM roles on the GCP project:
       roles/aiplatform.user               (Vertex AI for Gemini)
       roles/secretmanager.secretAccessor  (for copilot-bridge-pat)
```

The two attribute conditions together enforce SEC-1 / SEC-3: only this specific repo's pushes by the repo owner can federate. Any other repo or actor gets an `invalid_target` rejection at the STS exchange.

## 4. First-boot setup — the `setup-wif.sh` script

Expected inputs (prompted interactively or passed as flags):

```
setup-wif.sh \
  --gcp-project my-gcp-project \
  --gcp-location us-central1 \
  --github-owner <owner> \
  --github-repo  ai-bridge-<user> \
  [--pool-id ai-bridge-pool] \
  [--provider-id ai-bridge-github-provider] \
  [--sa-name ai-bridge-sa]
```

Steps performed (idempotent):

1. `gcloud config set project <proj>`
2. Enable required APIs: `iam.googleapis.com`, `iamcredentials.googleapis.com`, `sts.googleapis.com`, `secretmanager.googleapis.com`, `aiplatform.googleapis.com`.
3. Create the Workload Identity Pool:
   ```
   gcloud iam workload-identity-pools create ai-bridge-pool \
     --location=global --display-name="AI Bridge"
   ```
4. Create the GitHub OIDC Provider:
   ```
   gcloud iam workload-identity-pools providers create-oidc ai-bridge-github-provider \
     --location=global \
     --workload-identity-pool=ai-bridge-pool \
     --display-name="GitHub Actions" \
     --issuer-uri="https://token.actions.githubusercontent.com" \
     --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.actor=assertion.actor" \
     --attribute-condition="assertion.repository==\"$OWNER/$REPO\" && assertion.actor==\"$OWNER\""
   ```
5. Create the service account:
   ```
   gcloud iam service-accounts create ai-bridge-sa --display-name="AI Bridge Runner"
   ```
6. Grant the pool principal impersonation of the SA (scoped to this repo):
   ```
   PRINCIPAL="principalSet://iam.googleapis.com/projects/$PROJ_NUM/locations/global/workloadIdentityPools/ai-bridge-pool/attribute.repository/$OWNER/$REPO"
   gcloud iam service-accounts add-iam-policy-binding ai-bridge-sa@$PROJ.iam.gserviceaccount.com \
     --role=roles/iam.workloadIdentityUser \
     --member="$PRINCIPAL"
   ```
7. Grant SA minimal project roles:
   ```
   gcloud projects add-iam-policy-binding $PROJ --member=serviceAccount:ai-bridge-sa@$PROJ.iam.gserviceaccount.com --role=roles/aiplatform.user
   gcloud projects add-iam-policy-binding $PROJ --member=serviceAccount:ai-bridge-sa@$PROJ.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   ```
8. Print the values that go into GitHub repo variables:
   ```
   GCP_WIF_PROVIDER=projects/$PROJ_NUM/locations/global/workloadIdentityPools/ai-bridge-pool/providers/ai-bridge-github-provider
   GCP_SA_EMAIL=ai-bridge-sa@$PROJ.iam.gserviceaccount.com
   GOOGLE_CLOUD_PROJECT=$PROJ
   GOOGLE_CLOUD_LOCATION=$LOCATION
   ```
   The user then runs `gh variable set <NAME> --body <VALUE> --repo $OWNER/$REPO` for each.

On subsequent runs the script detects existing pool / provider / SA and only applies missing bindings. Each step is wrapped in a `--quiet` describe-before-create pattern so re-running does not error.

## 5. Copilot PAT lifecycle

1. **Create** a fine-grained personal access token at https://github.com/settings/personal-access-tokens/new:
   - Resource owner: your GitHub user (or the org that owns the bridge repo if different).
   - Repository access: **"Only select repositories"** -> `ai-bridge-<user>` ONLY.
   - Permissions:
     - Repository permissions: `Contents: Read and write` (for the PAT to act as the bridge-bot author on response commits when Copilot legitimately needs to edit — v1 does not need this, but the CLI internally requires the token for Copilot Requests permission).
     - Account permissions: **`Copilot Requests: Read`** (this is the key permission that authorizes `copilot -p` to consume Copilot entitlements).
   - Expiration: 90 days (maximum that fits the rotation cadence; set a calendar reminder).
2. **Store** in GCP Secret Manager:
   ```
   printf '%s' "$PAT" | gcloud secrets create copilot-bridge-pat --data-file=-
   gcloud secrets add-iam-policy-binding copilot-bridge-pat \
     --member=serviceAccount:ai-bridge-sa@$PROJ.iam.gserviceaccount.com \
     --role=roles/secretmanager.secretAccessor
   ```
3. **Use** in the workflow via `google-github-actions/get-secretmanager-secrets@<sha>`. The secret is exposed to the CLI step as `COPILOT_GITHUB_TOKEN` via `env:`.
4. **Rotate** every 90 days:
   ```
   printf '%s' "$NEW_PAT" | gcloud secrets versions add copilot-bridge-pat --data-file=-
   # Verify by running a hello-world copilot bridge request; workflow pulls the latest version.
   # Disable the old version once verified:
   gcloud secrets versions disable <OLD_VERSION> --secret=copilot-bridge-pat
   ```
   The workflow always fetches the `latest` enabled version, so there is zero downtime.

## 6. Why `COPILOT_GITHUB_TOKEN` and not a regular `GITHUB_TOKEN`

The bridge workflow already has `${{ secrets.GITHUB_TOKEN }}` which is scoped to the bridge repo with `contents: write`. That token can commit on behalf of the workflow, which is how the bridge-bot pushes response commits. But `GITHUB_TOKEN` CANNOT consume Copilot Requests — that requires a user-context token with the "Copilot Requests" permission.

Hence:

- `GITHUB_TOKEN` (auto-provided, ephemeral, never leaves runner) — used for committing responses.
- `COPILOT_GITHUB_TOKEN` (fine-grained PAT from Secret Manager) — used for `copilot -p` CLI auth.

`COPILOT_GITHUB_TOKEN` is `env:`-scoped only to the CLI step via `--secret-env-vars COPILOT_GITHUB_TOKEN` which tells Copilot CLI to treat it as a secret (masked in CLI output) and NOT to persist it.

## 7. SEC invariants this reference satisfies

| Invariant | How |
|---|---|
| SEC-1 (no long-lived creds in GitHub) | WIF OIDC exchange; no service account key, no long-lived PAT in GitHub repo secrets. The Copilot PAT is in Secret Manager, not GitHub. |
| SEC-3 (no write access to other repos) | `attribute_condition` on the WIF provider pins repository; PAT is fine-grained and scoped to `ai-bridge-<user>` only. `permissions:` block on the workflow is `contents: write` + `id-token: write` only. |

## 8. Failure modes and runbook

| Symptom | Likely cause | Response |
|---|---|---|
| `auth@v2` step fails `Not authorized` | WIF binding condition mismatch (wrong repo, wrong actor) | Re-run `setup-wif.sh` after verifying inputs; check GCP audit log for the assertion values that were presented |
| `get-secretmanager-secrets` fails `Permission denied` | SA missing `roles/secretmanager.secretAccessor` on the `copilot-bridge-pat` secret | Re-grant via step 5 of the script; verify with `gcloud secrets get-iam-policy copilot-bridge-pat` |
| `copilot -p` fails `401 Unauthorized` | PAT expired or missing Copilot Requests permission | Rotate PAT via `gcloud secrets versions add`; verify permission scope in GitHub UI |
| `gemini` fails `quota_exhausted` | Project-level Vertex quota hit | Check Vertex quotas; consider `--model gemini-2.5-flash` as a fallback in the request |
| Auth works mid-run then fails | WIF token TTL expired (rare: 1h TTL vs 10 min workflow cap) | See Incident 5 in `operations.md`; re-run `setup-wif.sh` if the SA was deleted |

## 9. What NOT to put in Secret Manager

- Don't put the bridge workflow's `GITHUB_TOKEN` in Secret Manager — it is auto-minted per run and has no value outside that run.
- Don't put user-scoped developer credentials in the `copilot-bridge-pat` secret — that secret is dedicated to the bridge's Copilot access, not to the developer's personal Copilot use.
- Don't store Gemini API keys in Secret Manager either — WIF replaces them entirely. Having both would create two auth paths, one of which (the API key) would violate SEC-1.

## 10. Decommissioning

When retiring a bridge repo:

1. `gh secret delete GCP_WIF_PROVIDER` (actually a variable, not a secret — `gh variable delete`).
2. Delete the Copilot PAT from GitHub settings.
3. `gcloud secrets delete copilot-bridge-pat`.
4. `gcloud iam service-accounts delete ai-bridge-sa@$PROJ.iam.gserviceaccount.com`.
5. `gcloud iam workload-identity-pools delete ai-bridge-pool --location=global`.
6. Archive and delete the `ai-bridge-<user>` GitHub repo.
