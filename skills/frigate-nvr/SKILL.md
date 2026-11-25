---
name: frigate-nvr
description: Frigate NVR - local camera recording and AI object detection for Home Assistant. Covers deployment in a Proxmox VM or LXC with Docker, detectors (OpenVINO, ONNX on Nvidia/AMD, Hailo, Coral, MemryX, RKNN), hardware video decoding presets, shm_size, go2rtc restream, MQTT and the Frigate HA integration, recording retention (continuous, motion, alerts, detections), zones and masks, and choosing RTSP cameras over cloud-only ones. Use when installing, sizing, configuring or upgrading Frigate, or picking cameras for it.
---

# Frigate NVR

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: frigate-release
    source_url: https://github.com/blakeblackshear/frigate/releases/tag/v0.18.0
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Latest stable v0.18.0 (2026-09-12); go2rtc 1.9.14 bundled; FFmpeg 8.1.1; DeGirum detector removed, DeepStack deprecated for 0.19."
  - kind: external_fact
    subject: frigate-detectors
    source_url: https://docs.frigate.video/configuration/object_detectors
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Official: Coral, Hailo-8/8L, OpenVINO, ONNX (Nvidia via -tensorrt image, AMD via -rocm image), Apple Silicon, Jetson jp6, CPU; community: MemryX, Synaptics, RKNN, AXERA. TensorRT and rocm detectors removed in 0.16. Coral no longer recommended for new installs."
  - kind: external_fact
    subject: frigate-proxmox
    source_url: https://docs.frigate.video/frigate/installation
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Frigate recommends a Proxmox QEMU VM; LXC not officially supported; SHM per camera formula (w*h*1.5*20+270480)/1048576 MB."
  - kind: external_fact
    subject: frigate-hass-integration
    source_url: https://github.com/blakeblackshear/frigate-hass-integration
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "v5.15.6 (2026-09-03), HACS default repo, requires HA 2026.3.0+ and the MQTT integration."
-->

## Overview

Frigate records cameras and runs object detection locally, feeding HA over MQTT. **Principle: the NVR is non-critical.** It adds evidence and context; it must never gate the critical layer (leak detection, the alarm, their notifications). If Frigate, its GPU or its host is down, the alarm still arms, triggers and notifies.

Evidence labels: **[V]** fetched on 2026-09-27 from the cited page; **[I]** inferred, re-verify. Versions: Frigate **0.18.0** (2026-09-12) is the latest stable [V GitHub releases]; configs from 0.14-0.16 guides need migrating. Upgrade notes: [references/config-and-upgrades.md](references/config-and-upgrades.md).

## When to use

- Installing Frigate, choosing a detector, sizing a host or GPU.
- Writing or migrating `config.yml` (recording, zones, masks, review).
- Connecting Frigate to HA; choosing cameras.

**Not for:** the Proxmox host itself, VM creation and PCI passthrough mechanics (`proxmox-admin`); camera VLANs and firewall rules (`unifi-network`); alarm logic (`home-assistant-alarmo`); HA core (`home-assistant`).

## Ask before building

Ask one compact question when unknown, because each changes the design:
1. **Accelerator available**: Intel iGPU/Arc, Nvidia, AMD, Hailo, Coral, none?
2. **Cameras**: count, resolution, and whether each has RTSP with a sub stream.
3. **Retention goal**: days of continuous vs event-only recording, and the storage size.

## Where to run it

| Option | Status | Notes |
|---|---|---|
| **Proxmox VM** running Docker | **Recommended** by the docs [V installation] | Pass the GPU/iGPU or accelerator (PCIe) into the VM; clean isolation from other GPU workloads |
| Proxmox LXC running Docker | "Not officially supported" [V] | Needs `features: fuse=1,nesting=1` and often a privileged container or world-readable `/dev/dri/renderD128` [V]; works for many but upgrades of the host kernel/driver can break it [I] |
| HA OS app (add-on) | Supported [I] | Puts video load on the HA VM; avoid when HA is the critical layer |
| Separate mini PC | Fine [I] | Docs suggest an N100-class box for small setups [V] |

Choosing: the HA OS app is fine when the HA host has spare CPU/RAM and no alarm or leak layer depends on it. When HA hosts safety automations, run Frigate on a separate VM or box, so video load or OOM cannot take them down.

Docker essentials [V installation]: image `ghcr.io/blakeblackshear/frigate:stable` (or the `-tensorrt` / `-rocm` variant); `shm_size` from `(width × height × 1.5 × 20 + 270480) / 1048576` MB per detect stream plus ~40 MB; a tmpfs `/tmp/cache` (~1 GB); recordings on a separate disk or share, never the VM's root disk.

**Network exposure** [V installation]: port **5000** is unauthenticated with admin-equivalent access, and **8554** (RTSP restream) is unauthenticated by default. Expose only **8971** (authenticated UI/API) to users; bind or firewall 5000 and 8554/8555 to localhost or the HA host only; never port-forward Frigate to the internet.

## Detectors (0.18)

| Hardware | Detector | Model | Notes |
|---|---|---|---|
| Intel iGPU / Arc / NPU | `openvino` | YOLOv9 recommended [V] | Best default on Intel hosts |
| Nvidia GPU | `onnx` with the `-tensorrt` image | YOLOv9, YOLO-NAS, D-FINE, DEIMv2 [V] | The old `tensorrt` detector was **removed in 0.16** [V] |
| AMD GPU | `onnx` with the `-rocm` image | YOLOv9, YOLO-NAS (not D-FINE/DEIMv2) [V] | `rocm` detector removed in 0.16 [V] |
| Hailo-8 / 8L | `hailo8l` | Standard image [V] | Recommended low-power option [V] |
| Coral (USB, M.2, mPCIe) | `edgetpu` | YOLOv9 quantized since 0.17 [V] | "No longer recommended for new installations" except very low power [V hardware] |
| MemryX, RKNN, Synaptics, AXERA | community detectors [V] | per docs | Check support before buying |
| CPU | `cpu` | | Not recommended [V] |

Model input **320×320** suits most setups [V]. Enable detection explicitly: `detect: enabled: true` has been required since 0.16 [V]. Decode on the GPU too, e.g. `hwaccel_args: preset-vaapi` (Intel gen1-12), `preset-intel-qsv-h264`/`-h265` (gen8+/Arc; h265 for gen13+), `preset-nvidia` [V hardware_acceleration_video].

## Streams and go2rtc

- Frigate bundles **go2rtc 1.9.14** [V 0.18 notes]. Define each camera once in `go2rtc.streams`, then point Frigate at `rtsp://127.0.0.1:8554/<cam>` with `input_args: preset-rtsp-restream` [V restream]; HA and viewers share that one connection.
- **Sub stream for `detect`** (e.g. 1280×720 at 5 fps; max 10), **main stream for `record`** [V camera_setup]. I-frame interval ~30 main, ~5 sub [V].
- go2rtc `exec`/`expr`/`echo` sources are off by default since 0.17 [V]; leave them off.

## Recording, review, zones and masks

```yaml
record:
  enabled: true
  continuous: {days: 3}      # 24/7 footage; 0 = off (default)
  motion: {days: 7}          # segments with motion
  alerts:     {retain: {days: 30, mode: all}}      # contiguous evidence
  detections: {retain: {days: 14, mode: motion}}
review:
  alerts:
    required_zones: [front_path]
```
`mode: motion` saves space but can drop quiet parts of the pre/post capture; use `all` where contiguous evidence matters [V record docs]. Keys per [V docs/configuration/record, 0.18]; verify against the running version's reference config before applying.

- **Zones** decide what matters: a zone is entered when the bottom-centre of the box is inside [V]; use `review.alerts.required_zones` so only people on the path raise alerts [V].
- **Motion masks** only stop motion (timestamps, trees) from starting detection; they do not hide objects [V]. **Object filter masks** remove one fixed false positive [V]. Over-masking breaks tracking [V].
- Storage: `Mbit/s × 10.8 = GB/day` per camera [I].

## Home Assistant integration

- Requires **MQTT** (a broker shared by Frigate and HA) and the **Frigate integration** from HACS (default repo), v5.15.6, HA 2026.3.0+ [V].
- Notifications: from the `frigate/reviews` MQTT events, or the SgtBatten blueprint (maintained [V]) after reading it.
- A camera detection may feed Alarmo only as a **secondary, non-blocking input** (e.g. snapshot attached to an alarm notification); never as the only trigger, and never as a condition that must succeed before the alarm acts.

## Choosing cameras

Wired PoE cameras with a supported local stream and a sub stream, H.264, no cloud dependency; avoid cloud-only and Wi-Fi models [V hardware / I]. Checklist and brand notes: [references/cameras.md](references/cameras.md).

## Anti-patterns

| Don't | Why |
|---|---|
| Make the alarm or leak automations wait on Frigate | The NVR is non-critical; its outage must not disable safety |
| Run Frigate in the HA OS VM that hosts the alarm | Video load or OOM takes down the critical layer |
| Publish port 5000 or 8554 beyond the host | Unauthenticated admin and streams [V]; users get 8971 |
| Use the `tensorrt` or `rocm` detector from an old guide | Removed in 0.16 [V]; use `onnx` with the matching image |
| Buy a Coral for a new build by default | Docs no longer recommend it [V]; OpenVINO/Hailo/ONNX first |
| Detect on the main 4K stream | Wastes decode and detector capacity; use the sub stream |
| Leave `shm_size` at the Docker default | Frigate warns and crashes under load; size it per camera [V] |
| Record to the VM's root disk | Fills the disk and stops the VM; use a dedicated volume |
| Treat motion masks as privacy masks | They do not hide anything [V] |
| Give cameras internet access | Firmware phones home; isolate them (`unifi-network`) |
| Upgrade across majors unread | 0.15-0.18 each changed config keys [V] |
