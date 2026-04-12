# Cost Optimization

Realistic monthly numbers for a single-developer GCP Workstation. All figures are USD, current as of April 2026 — verify against the live pricing page at <https://cloud.google.com/workstations/pricing>.

## Cost structure

GCP Workstations bills three things:

1. **Cluster fee** — fixed per-cluster, per-hour, regardless of how many workstations are running
2. **Compute** — per-vCPU-hour, only while a workstation is running
3. **Persistent disk** — per-GB-month, always (whether the workstation is running or stopped)

Plus:
- **Network egress** — per-GB out of GCP (usually negligible)
- **Container Registry / Artifact Registry** — per-GB-month for image storage (negligible)
- **Vertex AI usage** — separate, depends on token volume

## The cluster fee

The cluster fee is the most surprising line item. From <https://cloud.google.com/workstations/pricing>:

- Per-hour cluster fee for the standard cluster type
- Approximately $0.20/hr × 24 × 30 = **~$144/mo**

You pay this even if you have zero workstations running. So if you create a cluster, run a workstation for 30 minutes, and stop it: you still pay $144 that month.

**Implication: do not create multiple clusters unless you need them.** One cluster per project per region.

## Compute

| Machine type | vCPU | RAM | Approx $/hr | $/day @ 6h | $/mo @ 30 days |
|---|---|---|---|---|---|
| `e2-standard-2` | 2 | 8 GB | ~$0.067 | $0.40 | $12 |
| `e2-standard-4` | 4 | 16 GB | ~$0.134 | $0.81 | $24 |
| `e2-standard-8` | 8 | 32 GB | ~$0.268 | $1.60 | $48 |
| `n2-standard-4` | 4 | 16 GB | ~$0.194 | $1.16 | $35 |

These are rough order-of-magnitude figures. **Verify on the live pricing page** before committing — GCP changes pricing.

Compute only accrues while the workstation is running. With a 30-min idle timeout, a typical 8-hour day uses ~6h of actual compute.

## Persistent disk

| Type | Size | Approx $/GB-month | $/mo for 200 GB |
|---|---|---|---|
| `pd-standard` | 200 GB | $0.040 | $8 |
| `pd-balanced` | 200 GB | $0.100 | $20 |
| `pd-ssd` | 200 GB | $0.170 | $34 |

`pd-ssd` is the recommended default for `$HOME` — IDE responsiveness matters.

The disk fee accrues 24/7, including when the workstation is stopped. To stop paying, you must `delete --delete-storage`.

## Realistic monthly bill (single dev, daily use)

| Item | Cost |
|---|---|
| Cluster fee | $144 |
| Compute (e2-standard-4, 6h/day, 22 working days/mo) | ~$18 |
| Persistent disk (200 GB pd-ssd) | ~$34 |
| Network egress (heavy AI use) | ~$5 |
| Vertex AI usage (Gemini + Claude, moderate use) | ~$30-100 |
| **Total** | **~$230-310/mo** |

The cluster fee dominates if you don't use the workstation much. The Vertex AI usage dominates if you use the AI CLIs heavily.

## Reducing the bill

### Stop the workstation when not in use

The 30-minute idle timeout helps automatically. Set even shorter (e.g. 10 min) if you frequently forget:

```bash
gcloud workstations configs update ai-dev-config \
  --idle-timeout=600s \
  --cluster=... --region=...
```

### Smaller machine type

If you're not running heavy Docker builds, `e2-standard-2` saves ~$12/mo over `e2-standard-4`.

### Smaller persistent disk

100 GB instead of 200 GB saves ~$17/mo on pd-ssd. Audit `du -sh ~/.npm ~/.cargo` etc. to see what's actually using space.

### Cheaper disk type

`pd-balanced` (200 GB) saves ~$14/mo over `pd-ssd`. Some loss of IDE responsiveness — acceptable for occasional use.

### Delete the cluster when on a long break

If you're going to be away for weeks: delete the cluster (and `--delete-storage` for the disks). The data is gone, but you stop paying $144/mo. Recreate when you come back.

### Use Vertex AI judiciously

Vertex token costs add up. Use the cheapest model that works:

| Model | Tier |
|---|---|
| `gemini-3-flash` | Cheapest, fast |
| `gemini-3-pro` | Better reasoning, ~3x cost |
| `claude-haiku` | Cheap Claude tier |
| `claude-sonnet-4-6` | Mid-tier Claude |
| `claude-opus-4-6` | Most expensive |

Set defaults via env vars in `~/.bashrc` so you don't accidentally use the expensive model.

## Alternative: plain GCE VM

You can build the same dev environment on a regular GCE VM for ~50% less:

| Item | GCP Workstation | Plain GCE VM |
|---|---|---|
| Cluster fee | $144/mo | $0 |
| Compute (e2-standard-4, 6h/day) | $18/mo | $18/mo |
| Persistent disk (200 GB pd-ssd) | $34/mo | $34/mo |
| Image management | Managed (Artifact Registry) | Manual (custom image, snapshots) |
| Browser IDE | Built-in (code-oss) | DIY (code-server, Theia, etc.) |
| Auto-stop on idle | Built-in | DIY (cron + `gcloud compute instances stop`) |
| **Total** | **$196/mo + Vertex** | **$52/mo + Vertex** |

**Trade-off:** ~$144/mo for the managed lifecycle. Worth it if you value the browser IDE and auto-stop, not worth it if you're comfortable rolling your own.

## Spot VMs — NOT recommended

Spot/preemptible VMs are 60-80% cheaper than on-demand but interruptions kill any in-flight work. For a personal dev workstation where you may have AI agents running long-running tasks, this is a bad trade. Use spot VMs only for batch workloads, not interactive dev.

## Free tier and credits

| Source | Amount | Notes |
|---|---|---|
| GCP Free Trial | $300 over 90 days | Burns through ~1 month of typical workstation use |
| Always Free tier | Some compute + storage | Not enough for a dedicated workstation |
| GCP Innovators / startup credits | Variable | Apply at <https://cloud.google.com/startup> |

A $300 free trial covers ~1 month of moderate use after the cluster fee. Plan accordingly.

## Anti-patterns

| Don't | Why |
|---|---|
| Create multiple clusters when one will do | Each cluster = $144/mo |
| Skip the idle timeout | You'll pay for compute 24/7 |
| Use `pd-ssd` for the entire 500 GB when 100 GB would do | $51/mo wasted on unused disk |
| Use spot VMs for personal dev | Interruptions kill work |
| Use Claude Opus for everything | $$$. Use Sonnet/Haiku/Flash for routine tasks. |
| Run `--running-timeout` at the max (43200s) without auto-stop | Forgotten sessions burn money |
| Ignore the cluster fee in your math | It's the largest fixed cost |
| Trust pre-configured pricing in this file blindly | GCP changes prices. Verify on the live page. |
