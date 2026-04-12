#!/usr/bin/env bash
# setup-wif.sh — idempotent Workload Identity Federation setup for the bridge.
# Creates GCP pool + provider + SA bound to a specific GitHub repo.
#
# Usage:
#   setup-wif.sh --gcp-project ID --gcp-location REGION \
#                --github-owner USER --github-repo REPO \
#                [--pool-id ai-bridge-pool] [--provider-id ai-bridge-github-provider] \
#                [--sa-name ai-bridge-sa]
#
# This script is intended to be run by the USER on their workstation during
# first-boot setup. It is NOT run by bob. It wraps gcloud commands that the
# user's account must have permission to execute.

set -euo pipefail

PROJECT=""
LOCATION="us-central1"
OWNER=""
REPO=""
POOL_ID="ai-bridge-pool"
PROVIDER_ID="ai-bridge-github-provider"
SA_NAME="ai-bridge-sa"

while [ $# -gt 0 ]; do
  case "$1" in
    --gcp-project)   PROJECT="$2"; shift 2 ;;
    --gcp-location)  LOCATION="$2"; shift 2 ;;
    --github-owner)  OWNER="$2"; shift 2 ;;
    --github-repo)   REPO="$2"; shift 2 ;;
    --pool-id)       POOL_ID="$2"; shift 2 ;;
    --provider-id)   PROVIDER_ID="$2"; shift 2 ;;
    --sa-name)       SA_NAME="$2"; shift 2 ;;
    -h|--help)       sed -n '2,15p' "$0" >&2; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

for v in PROJECT OWNER REPO; do
  eval "val=\$$v"
  if [ -z "${val:-}" ]; then
    echo "ERROR: required flag --${v,,} not provided" >&2
    exit 1
  fi
done

command -v gcloud >/dev/null || { echo "ERROR: gcloud not on PATH" >&2; exit 1; }
gcloud config set project "$PROJECT" >/dev/null

echo ">> enabling APIs"
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com \
  --quiet

echo ">> creating workload identity pool (if missing)"
if ! gcloud iam workload-identity-pools describe "$POOL_ID" --location=global --format=none 2>/dev/null; then
  gcloud iam workload-identity-pools create "$POOL_ID" \
    --location=global --display-name="AI Bridge" --quiet
fi

echo ">> creating OIDC provider (if missing)"
if ! gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
      --location=global --workload-identity-pool="$POOL_ID" --format=none 2>/dev/null; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --location=global \
    --workload-identity-pool="$POOL_ID" \
    --display-name="GitHub Actions" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.actor=assertion.actor" \
    --attribute-condition="assertion.repository==\"$OWNER/$REPO\" && assertion.actor==\"$OWNER\"" \
    --quiet
fi

SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
echo ">> creating service account (if missing)"
if ! gcloud iam service-accounts describe "$SA_EMAIL" --format=none 2>/dev/null; then
  gcloud iam service-accounts create "$SA_NAME" --display-name="AI Bridge Runner" --quiet
fi

PROJ_NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
PRINCIPAL="principalSet://iam.googleapis.com/projects/$PROJ_NUM/locations/global/workloadIdentityPools/$POOL_ID/attribute.repository/$OWNER/$REPO"

echo ">> binding pool principal to SA impersonation"
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role=roles/iam.workloadIdentityUser \
  --member="$PRINCIPAL" --quiet

echo ">> granting project roles (aiplatform.user, secretmanager.secretAccessor)"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/aiplatform.user --quiet >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$SA_EMAIL" --role=roles/secretmanager.secretAccessor --quiet >/dev/null

echo
echo "==== Write the following values into GitHub repo variables ===="
printf 'GCP_WIF_PROVIDER     = projects/%s/locations/global/workloadIdentityPools/%s/providers/%s\n' \
  "$PROJ_NUM" "$POOL_ID" "$PROVIDER_ID"
printf 'GCP_SA_EMAIL         = %s\n' "$SA_EMAIL"
printf 'GOOGLE_CLOUD_PROJECT = %s\n' "$PROJECT"
printf 'GOOGLE_CLOUD_LOCATION = %s\n' "$LOCATION"
echo
echo "Example: gh variable set GCP_WIF_PROVIDER --repo $OWNER/$REPO --body '...'"
