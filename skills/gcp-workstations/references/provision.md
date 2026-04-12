# Provisioning

GCP Workstations is a 3-level hierarchy:

```
Cluster (per region, per network)
  └── Config (machine type, image, persistent disk)
        └── Workstation (the actual instance)
```

## Region selection

Pick a region that:

1. Has Vertex AI Gemini and Claude availability (so you can use ADC for both)
2. Is close to your laptop (latency for the browser IDE)
3. Has Workstations API enabled (most major regions do)

`us-central1` is the safe default for North America.

## IAM minimum

The user/service account that creates the cluster needs:

- `roles/workstations.admin` (or `roles/workstations.workstationCreator` for limited)
- `roles/compute.networkUser` (for the network/subnet)

The workstation runtime service account needs:

- `roles/aiplatform.user` (for Vertex Gemini/Claude calls)
- `roles/secretmanager.secretAccessor` (for use-time secret fetch)
- `roles/artifactregistry.reader` (to pull the custom image)

## Cluster

```bash
PROJECT=my-gcp-project
REGION=us-central1
NETWORK=projects/$PROJECT/global/networks/default
SUBNET=projects/$PROJECT/regions/$REGION/subnetworks/default

gcloud workstations clusters create my-cluster \
  --project=$PROJECT \
  --region=$REGION \
  --network=$NETWORK \
  --subnetwork=$SUBNET
```

This takes ~15-20 minutes. The cluster fee starts immediately (~$144/mo per cluster, prorated).

### Private cluster option

```bash
gcloud workstations clusters create my-cluster-private \
  --project=$PROJECT \
  --region=$REGION \
  --network=$NETWORK \
  --subnetwork=$SUBNET \
  --enable-private-endpoint
```

Private endpoint disables public IPs on workstations. You access via IAP. See `references/networking.md`.

## Config

```bash
gcloud workstations configs create ai-dev-config \
  --project=$PROJECT \
  --cluster=my-cluster \
  --region=$REGION \
  --machine-type=e2-standard-4 \
  --container-custom-image=us-central1-docker.pkg.dev/$PROJECT/ai-dev/ai-dev:latest \
  --pd-disk-type=pd-ssd \
  --pd-disk-size=200 \
  --idle-timeout=1800s \
  --running-timeout=43200s \
  --service-account=workstation-runtime@$PROJECT.iam.gserviceaccount.com
```

### Machine type selection

| Machine type | vCPU | RAM | Use case |
|---|---|---|---|
| `e2-standard-2` | 2 | 8 GB | Minimum viable. Tight on RAM for VS Code + node + multiple AI CLIs running concurrently. |
| `e2-standard-4` | 4 | 16 GB | **Recommended.** Comfortable for everyday dev with VS Code, multiple AI CLIs, and a couple of Docker containers. |
| `e2-standard-8` | 8 | 32 GB | Heavy IDE plugins, large language model local runs, frequent Docker builds. |
| `n2-standard-4` | 4 | 16 GB | Higher per-vCPU price but better for CPU-bound tasks (compilation, tests). |

### Idle timeout

`--idle-timeout=1800s` (30 min) is a sensible default — workstations auto-stop when idle, saving compute cost.

`--running-timeout=43200s` (12 h) is the absolute max session duration before forced stop.

## Workstation

```bash
gcloud workstations create my-station \
  --project=$PROJECT \
  --cluster=my-cluster \
  --config=ai-dev-config \
  --region=$REGION
```

Then start it:

```bash
gcloud workstations start my-station \
  --cluster=my-cluster \
  --config=ai-dev-config \
  --region=$REGION
```

And open the browser-IDE:

```bash
gcloud workstations start-tcp-tunnel my-station \
  --cluster=my-cluster \
  --config=ai-dev-config \
  --region=$REGION \
  --port=80 \
  --local-host-port=:8080
```

Then visit `http://localhost:8080` in your laptop browser.

Or use the GCP Console: Workstations → my-station → Launch.

## Lifecycle commands

```bash
# Stop (preserves $HOME, releases compute)
gcloud workstations stop my-station --cluster=... --config=... --region=...

# Start
gcloud workstations start my-station --cluster=... --config=... --region=...

# Delete (preserves persistent disk; the disk lives on if reattached)
gcloud workstations delete my-station --cluster=... --config=... --region=...

# Delete config (preserves cluster)
gcloud workstations configs delete ai-dev-config --cluster=... --region=...

# Delete cluster (deletes everything underneath)
gcloud workstations clusters delete my-cluster --region=...
```

## What `scripts/create-workstation.sh` adds

The bundled script:

1. Validates env vars (`PROJECT`, `REGION`, `IMAGE`)
2. Checks if cluster exists; creates if not (idempotent)
3. Checks if config exists; creates if not
4. Checks if workstation exists; creates if not
5. Starts the workstation
6. Prints the URL to launch the browser IDE

Re-run safe — if any layer already exists, it skips.
