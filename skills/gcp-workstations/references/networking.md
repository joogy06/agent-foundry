# Networking

GCP Workstations supports both public and private network topologies. Pick based on whether you want anonymous Internet exposure or IAP-only access.

## Public vs private cluster

| Mode | Public IP | Access via | Use when |
|---|---|---|---|
| **Public** (default) | Yes | Direct HTTPS to the workstation URL or `gcloud workstations start-tcp-tunnel` | Personal dev, no compliance constraint |
| **Private** (`--enable-private-endpoint`) | No | Identity-Aware Proxy (IAP) tunnel only | Compliance, sensitive data, defence in depth |

For a single-developer workstation in a non-regulated environment, public is fine. For anything that touches customer data or production systems, use private.

## Private cluster setup

```bash
gcloud workstations clusters create my-cluster-private \
  --project=$PROJECT \
  --region=$REGION \
  --network=$NETWORK \
  --subnetwork=$SUBNET \
  --enable-private-endpoint
```

Then use IAP to tunnel:

```bash
# On laptop
gcloud workstations start-tcp-tunnel my-station \
  --cluster=my-cluster-private \
  --config=ai-dev-config \
  --region=$REGION \
  --port=80 \
  --local-host-port=:8080
```

The IAP tunnel uses the `roles/iap.tunnelResourceAccessor` permission. The user accessing the tunnel needs that role on the workstation resource.

## Egress allow-list

By default, the workstation can reach the public Internet. For an AI dev workstation, the minimum egress targets are:

| Endpoint | Used by | Notes |
|---|---|---|
| `api.anthropic.com` | Claude Code (direct API) | Skip if using Vertex |
| `*.googleapis.com` | Vertex AI, Secret Manager, Artifact Registry, Logging | Always required |
| `github.com`, `api.github.com` | Copilot CLI, gh, git | Always required |
| `objects.githubusercontent.com` | gh release downloads | |
| `registry.npmjs.org` | npm install | |
| `pypi.org`, `files.pythonhosted.org` | Python pip | |
| `*.docker.io`, `gcr.io`, `*.pkg.dev` | Container pulls | |
| `aistudio.google.com` | Gemini AI Studio (only if not using Vertex) | |

Set up via VPC Service Controls or Cloud Firewall rules. Out of scope for this skill — see GCP networking docs.

## Cloud NAT for egress (for private clusters)

Private clusters have no public IP, so they need a Cloud NAT gateway for outbound traffic:

```bash
gcloud compute routers create my-nat-router \
  --network=$NETWORK \
  --region=$REGION

gcloud compute routers nats create my-nat-config \
  --router=my-nat-router \
  --nat-all-subnet-ip-ranges \
  --auto-allocate-nat-external-ips \
  --region=$REGION
```

Without NAT, `npm install`, `gh auth login`, and any external API call from a private workstation will fail.

## Workstation port forwarding

Workstations expose port 80 for the browser IDE. To access additional ports (e.g., a local dev server on 3000):

```bash
gcloud workstations start-tcp-tunnel my-station \
  --cluster=... --config=... --region=... \
  --port=3000 \
  --local-host-port=:3000
```

Then visit `http://localhost:3000` on your laptop.

For web servers running on the workstation that need to be exposed publicly (rare for personal dev), use Cloud Run or App Engine in front, not the workstation directly.

## DNS

The workstation gets a public hostname like `<station>-<region>.cloudworkstations.dev`. This is auto-managed by GCP. For a personal workstation you don't need a custom domain.

## TLS

The browser IDE access URL is HTTPS-terminated by GCP's load balancer. Inside the workstation, you can use whatever you want.

## Anti-patterns

| Don't | Why |
|---|---|
| Open inbound port 22 (SSH) on a public workstation | Use IAP. SSH bypasses GCP's auth layer. |
| Skip Cloud NAT on private clusters | All outbound calls fail |
| Use a custom domain for personal dev | Adds DNS/cert overhead with no benefit |
| Allow `0.0.0.0/0` outbound | Defeats the egress allow-list. Use SVCs or fine-grained rules. |
| Use the workstation as a public web server | It's a dev environment, not production. Use Cloud Run / App Engine. |
| Forget that `start-tcp-tunnel` blocks the laptop terminal | Run in tmux or background |
