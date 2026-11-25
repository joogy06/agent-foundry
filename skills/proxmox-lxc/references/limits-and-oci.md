# Resource limits and OCI images (pct)

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-oci-containers
    source_url: https://pve.proxmox.com/wiki/Roadmap
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "PVE 9.1 (2025-11-19) creates LXC containers from OCI images (upload or pull from a registry); application containers from OCI images are a technology preview; host-managed DHCP for containers without a network stack; 9.2 improved OCI reference parsing."
-->

Labels: [V] from the pct man page, pct chapter or Roadmap, fetched 2026-09-27; [I] inferred, re-verify. Apply the `proxmox-admin` guardrails first.

## Resource limits

| Option | Effect |
|---|---|
| `--cores <n>` | Visible CPUs [V] |
| `--cpulimit <float>` | CPU time cap, e.g. `0.5` [V] |
| `--cpuunits <n>` | Relative scheduler weight, default 100 on cgroup v2 [V] |
| `--memory <MiB>` / `--swap <MiB>` | Memory cap; extra swap from host swap [V] |
| `--rootfs ...,size=` | Disk quota by volume size [I] |

Check node capacity (`free -h`, `pvesm status`) before raising limits; over-commit starves the neighbours.

## OCI images (PVE 9.1+)

- Upload an OCI image or use **Pull from OCI registry** on a storage's CT Templates view, then create a container from it [V].
- System-type images give a normal LXC; **application containers** (single process, `--entrypoint`, `--env`) are a **technology preview** [V]. Host-managed DHCP covers images without a network stack [V].
- Not a Docker replacement: no compose, no registry auth workflow, image updates are manual [I]. Use for simple single-image services; keep complex stacks in Docker in a VM.
