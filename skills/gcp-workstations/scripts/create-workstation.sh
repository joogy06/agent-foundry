#!/usr/bin/env bash
# create-workstation.sh
#
# Idempotent end-to-end provisioning of a GCP Workstation for AI dev.
# Creates: cluster (if missing), config (if missing), workstation (if missing), starts it.
#
# Required env vars:
#   PROJECT       — GCP project ID
#   REGION        — e.g. us-central1
#   IMAGE         — full custom image URL (e.g. us-central1-docker.pkg.dev/PROJECT/ai-dev/ai-dev:latest)
#
# Optional env vars (with defaults):
#   CLUSTER       — cluster name (default: ai-dev-cluster)
#   CONFIG        — config name (default: ai-dev-config)
#   STATION       — workstation name (default: ai-dev-station)
#   MACHINE_TYPE  — e2-standard-4
#   DISK_SIZE     — 200
#   DISK_TYPE     — pd-ssd
#   IDLE_TIMEOUT  — 1800s
#   RUN_TIMEOUT   — 43200s
#   NETWORK       — projects/$PROJECT/global/networks/default
#   SUBNET        — projects/$PROJECT/regions/$REGION/subnetworks/default
#   SERVICE_ACCOUNT — workstation-runtime@$PROJECT.iam.gserviceaccount.com
#
# Usage:
#   PROJECT=my-project REGION=us-central1 IMAGE=us-central1-docker.pkg.dev/my-project/ai-dev/ai-dev:latest \
#     bash scripts/create-workstation.sh
#
# Re-run safe — if any layer already exists, it skips.

set -o errexit
set -o nounset
set -o pipefail

# Required
: "${PROJECT:?PROJECT env var is required}"
: "${REGION:?REGION env var is required}"
: "${IMAGE:?IMAGE env var is required}"

# Optional
CLUSTER="${CLUSTER:-ai-dev-cluster}"
CONFIG="${CONFIG:-ai-dev-config}"
STATION="${STATION:-ai-dev-station}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-4}"
DISK_SIZE="${DISK_SIZE:-200}"
DISK_TYPE="${DISK_TYPE:-pd-ssd}"
IDLE_TIMEOUT="${IDLE_TIMEOUT:-1800s}"
RUN_TIMEOUT="${RUN_TIMEOUT:-43200s}"
NETWORK="${NETWORK:-projects/${PROJECT}/global/networks/default}"
SUBNET="${SUBNET:-projects/${PROJECT}/regions/${REGION}/subnetworks/default}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-workstation-runtime@${PROJECT}.iam.gserviceaccount.com}"

ok() { printf "  [OK]   %s\n" "$1"; }
info() { printf "  [..]   %s\n" "$1"; }
warn() { printf "  [WARN] %s\n" "$1"; }

printf "create-workstation.sh\n"
printf "  project        = %s\n" "$PROJECT"
printf "  region         = %s\n" "$REGION"
printf "  cluster        = %s\n" "$CLUSTER"
printf "  config         = %s\n" "$CONFIG"
printf "  workstation    = %s\n" "$STATION"
printf "  machine type   = %s\n" "$MACHINE_TYPE"
printf "  disk           = %s GB %s\n" "$DISK_SIZE" "$DISK_TYPE"
printf "  image          = %s\n" "$IMAGE"
printf "  service account= %s\n" "$SERVICE_ACCOUNT"
echo

# 1. Cluster
printf "1) cluster\n"
if gcloud workstations clusters describe "$CLUSTER" \
     --project="$PROJECT" --region="$REGION" >/dev/null 2>&1; then
  ok "cluster '$CLUSTER' already exists"
else
  info "creating cluster '$CLUSTER' (this can take 15-20 minutes)"
  gcloud workstations clusters create "$CLUSTER" \
    --project="$PROJECT" \
    --region="$REGION" \
    --network="$NETWORK" \
    --subnetwork="$SUBNET"
  ok "cluster '$CLUSTER' created"
fi
echo

# 2. Config
printf "2) config\n"
if gcloud workstations configs describe "$CONFIG" \
     --cluster="$CLUSTER" --project="$PROJECT" --region="$REGION" >/dev/null 2>&1; then
  ok "config '$CONFIG' already exists"
else
  info "creating config '$CONFIG'"
  gcloud workstations configs create "$CONFIG" \
    --project="$PROJECT" \
    --cluster="$CLUSTER" \
    --region="$REGION" \
    --machine-type="$MACHINE_TYPE" \
    --container-custom-image="$IMAGE" \
    --pd-disk-type="$DISK_TYPE" \
    --pd-disk-size="$DISK_SIZE" \
    --idle-timeout="$IDLE_TIMEOUT" \
    --running-timeout="$RUN_TIMEOUT" \
    --service-account="$SERVICE_ACCOUNT"
  ok "config '$CONFIG' created"
fi
echo

# 3. Workstation
printf "3) workstation\n"
if gcloud workstations describe "$STATION" \
     --cluster="$CLUSTER" --config="$CONFIG" \
     --project="$PROJECT" --region="$REGION" >/dev/null 2>&1; then
  ok "workstation '$STATION' already exists"
else
  info "creating workstation '$STATION'"
  gcloud workstations create "$STATION" \
    --project="$PROJECT" \
    --cluster="$CLUSTER" \
    --config="$CONFIG" \
    --region="$REGION"
  ok "workstation '$STATION' created"
fi
echo

# 4. Start
printf "4) starting workstation\n"
STATE=$(gcloud workstations describe "$STATION" \
    --cluster="$CLUSTER" --config="$CONFIG" \
    --project="$PROJECT" --region="$REGION" \
    --format='value(state)' 2>/dev/null || echo "UNKNOWN")
case "$STATE" in
  STATE_RUNNING)
    ok "workstation already running"
    ;;
  STATE_STOPPED|UNKNOWN|*)
    info "starting workstation (state was '$STATE')"
    gcloud workstations start "$STATION" \
      --cluster="$CLUSTER" \
      --config="$CONFIG" \
      --project="$PROJECT" \
      --region="$REGION"
    ok "workstation started"
    ;;
esac
echo

# 5. Hint
printf "5) launch URL\n"
ok "open in browser via the GCP Console:"
printf "       https://console.cloud.google.com/workstations/list?project=%s\n" "$PROJECT"
ok "or tunnel from your laptop:"
cat <<EOF
       gcloud workstations start-tcp-tunnel $STATION \\
         --cluster=$CLUSTER --config=$CONFIG --region=$REGION \\
         --port=80 --local-host-port=:8080
       # then visit http://localhost:8080
EOF
echo
ok "done"
