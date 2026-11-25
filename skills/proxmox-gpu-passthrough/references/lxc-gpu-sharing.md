# Sharing a host GPU into LXC containers

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: pct-dev-passthrough
    source_url: https://pve.proxmox.com/pve-docs/pct.1.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "pct --dev[n] [[path=]<Path>][,deny-write=<1|0>][,gid=<int>][,mode=<octal>][,uid=<int>]."
-->

Labels: **[V]** checked against the cited source on 2026-09-27; **[I]** inferred or community practice, so re-verify.

The host keeps the GPU and its driver; containers get the device nodes. Several containers can share one GPU. This is the usual choice for Jellyfin/Plex transcoding, Frigate detection/decoding and Ollama on a single-GPU host.

## Intel or AMD (`/dev/dri`)

```bash
# Host: driver loaded? (i915/xe for Intel, amdgpu for AMD)
ls -l /dev/dri                       # card0/card1, renderD128 [I]
lspci -nnk | grep -A3 -Ei 'vga|display'

# Container: find the render group's GID INSIDE the container
pct exec <ctid> -- getent group render     # e.g. render:x:993:  [I]

# Pass the render node (and card node if the app needs display/KMS) [V syntax]
pct set <ctid> --dev0 /dev/dri/renderD128,gid=993
pct set <ctid> --dev1 /dev/dri/card0,gid=44         # video group, only if needed [I]
pct reboot <ctid>                                    # scope: this container only
```

- `devN` works in unprivileged containers and avoids hand-written `lxc.cgroup2.devices.allow` / `lxc.mount.entry` lines [I].
- Node names can change between boots when there are several GPUs (`card0` vs `card1`); use `/dev/dri/by-path/` to identify, and re-check after hardware changes [I].
- Inside: install `vainfo` (Intel: `intel-media-va-driver-non-free` for newer iGPUs [I]); `vainfo --display drm --device /dev/dri/renderD128` should list profiles [I].

## NVIDIA

```bash
# Host: NVIDIA driver installed (DKMS against the PVE kernel headers) [I]
nvidia-smi
ls -l /dev/nvidia*                   # nvidia0, nvidiactl, nvidia-uvm, nvidia-uvm-tools, nvidia-modeset [I]

pct set <ctid> --dev0 /dev/nvidia0 --dev1 /dev/nvidiactl \
  --dev2 /dev/nvidia-uvm --dev3 /dev/nvidia-uvm-tools        # [V syntax]
# Container: same driver version, userspace only (runfile --no-kernel-module), or the
# NVIDIA Container Toolkit for Docker-in-LXC [I]
pct exec <ctid> -- nvidia-smi
```

- Host and container driver versions **must match exactly**; every host driver update means updating the container userspace too [I].
- `/dev/nvidia-uvm` appears only after something loads `nvidia-uvm`; add `nvidia-uvm` to `/etc/modules-load.d/` or run `nvidia-modprobe -u -c=0` at boot [I].
- Host kernel updates need the DKMS module rebuilt before containers start [I].

## App checks

| App | Proof it uses the GPU [I] |
|---|---|
| Jellyfin / Plex | Hardware transcoding enabled with VA-API/QSV (Intel/AMD) or NVENC; a transcode shows `(hw)` in the dashboard; `intel_gpu_top` or `nvidia-smi` on the host shows load |
| Frigate | `ffmpeg.hwaccel_args` preset matches the GPU; detector (OpenVINO on Intel, ONNX on NVIDIA/AMD) reports its inference speed; see `frigate-nvr` (Frigate recommends a VM, LXC not officially supported) |
| Ollama | Startup log names the CUDA/ROCm device; `ollama ps` shows GPU %; `nvidia-smi` shows VRAM used |

## Limits

- A GPU bound to `vfio-pci` for a VM has no host driver, so no container can use it at the same time [V: host loses the device].
- Docker inside an unprivileged LXC adds another layer (nesting, keyctl, idmaps): route general Docker-in-LXC setup to `proxmox-lxc` [I].
- Containers sharing a GPU are not isolated from each other's GPU memory; do not share with untrusted tenants [I].
- Containers with host device nodes cannot live-migrate; the target node needs the same device path [I].
