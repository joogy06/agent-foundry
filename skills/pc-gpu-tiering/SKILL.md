---
name: pc-gpu-tiering
description: Graphics card choice for a desktop PC - NVIDIA RTX 50, AMD Radeon RX 9000 (RDNA4) and Intel Arc tiers, how much VRAM (is 8 GB enough), creator and video-encoder picks, and local AI hardware (CUDA, ROCm, OpenVINO, PyTorch XPU, llama.cpp, Ollama) with VRAM vs LLM model size. Use when recommending or comparing a GPU.
---

# PC GPU Tiering

## Overview

The GPU is the biggest single lever for gaming, creator and AI builds, and the part where marketing and reality diverge most. This skill tiers cards by relative performance class, sets VRAM rules, and maps AI workloads to software stacks. The card's actual specs (VRAM, TBP, lanes) always come from the caller's database. Tables: [references/gpu-and-ai-tables.md](references/gpu-and-ai-tables.md).

## When to use

- Recommending or comparing graphics cards for a use case.
- "Is 8 GB enough?", "NVIDIA or AMD?", "which card for Blender / Resolve / Premiere?"
- Choosing hardware for running LLMs locally.

**Not for:** installing drivers, CUDA or Ollama on a Linux server: apply `rhel-ollama-nvidia` or `ubuntu-ollama-nvidia`. PCIe link rules are in `pc-compatibility`; PSU sizing in `pc-power-sizing`.

## Tiers [I]

| Tier | Cards | CPU pairing |
|---|---|---|
| Entry | RTX 5050, 5060, RX 9060 XT 8 GB, RX 9050, Arc B570, B580 | Ryzen 5 5600/7600, Core i5. The B580 wants a 7600-class CPU or newer (driver CPU overhead) |
| Mainstream | RTX 5060 Ti 16 GB, RX 9060 XT 16 GB, RX 9070 GRE | Ryzen 5 7600/9600, Core Ultra 5 |
| Upper | RTX 5070, 5070 Ti, RX 9070, 9070 XT | Ryzen 7 7700/9700X, 7800X3D |
| Enthusiast | RTX 5080, 5090 | 9800X3D class |
| Workstation-AI | RTX 5090 32 GB, Radeon AI PRO R9700 32 GB, Arc Pro B70/B60 | RAM, lanes and multi-GPU matter more than the CPU |

Relative performance anchors (TechPowerUp, search excerpts [S]): B580 about 5050 +5%; 9060 XT 8 GB about 5050 +33%; 9060 XT 16 GB about 5060 Ti 16 GB -3%; 9070 XT about 5070 Ti in raster, -4% with RT; 5090 about 5080 +48-52% at 4K. Present these as **performance classes**, never as FPS promises.

The checker reads the tier from `gpu.tier` or matches `gpu.model` against `data/rules.v1.json` `gpu_tiers` for the balance rule (`UC_BALANCE`).

## VRAM rules

| VRAM | Verdict (scope it to the workload) |
|---|---|
| 8 GB | Fine for esports and 1080p medium/high. **Wrong buy for AAA at high settings:** HUB measured an 8 GB RTX 5060 Ti at 67 vs 109 fps (16 GB) in TLOU2 at 1080p Very High, with stutter and crashes [S] |
| 12 GB | **The floor** for AAA gaming; a preference (not a floor) for esports |
| 16 GB | **The 2026 default** for AAA at 1080p high and above, and for creators |

`VRAM_8GB_SCOPE` (INFO) states that scope whenever a card has 8 GB or less. The per-use-case floors are `UC_VRAM_MIN` (WARN); esports uses `UC_VRAM_PREFERRED` (INFO). An 8 GB **x8** card is also hurt by an older PCIe slot (see `pc-compatibility`).

## Creators and encoders

- Puget 2025: RTX leads in DaVinci Resolve and Blender (OptiX). V-Ray, Redshift and Octane are NVIDIA-only. The Arc B580 failed the Resolve suite. AMD was +25% on Long-GOP in Premiere.
- Encoders: historically NVENC >= Quick Sync (QSV) > AMF. RDNA4 improved AMF (vendor claim, not independently verified here).
- Creator floor: 16 GB+ VRAM (see `pc-build-recommendations`).

## Upscaling and frame generation (re-verify quarterly)

DLSS 4.5 (RTX 50 multi-frame generation up to 6x); FSR 4 / Redstone on RDNA4 (FSR 4.1 upscaling reached RDNA3); XeSS 3 MFG on Arc. Frame-generated FPS is not comparable with native FPS; never mix them in a comparison.

## Local AI

**Recommendation:** NVIDIA for AI. RDNA4 is viable only for **inference-only, Linux-first** use.

| Stack | Status |
|---|---|
| CUDA | The only day-one path for training, fine-tuning and vLLM [I]. vLLM needs compute capability 7.5+ |
| ROCm 10.0 (26 Aug 2026) | Officially supports RX 9070 XT/GRE/9070, 9060 XT/9060/9050 and 7900/7800/7700/7600. **Windows support is partial.** Ollama on Windows lists only RDNA3 among AMD cards |
| Intel | Upstream **PyTorch XPU**, **OpenVINO** (2026.4, actively maintained) or **llama.cpp** SYCL/Vulkan |
| llama.cpp | Backends: CUDA, HIP, Vulkan, SYCL, OpenVINO |

**Never recommend IPEX-LLM or IPEX.** IPEX-LLM was archived on 28 Jan 2026 (security issues) and IPEX on 30 Mar 2026.

### VRAM to model size

Per billion parameters: Q4_K_M about 0.6 GB, Q8 about 1.05 GB, FP16 2 GB, plus 1-3 GB of context.

| VRAM | Fits |
|---|---|
| 8 GB | 7-8B at Q4-Q6 |
| 12 GB | 14B at Q4 |
| 16 GB | 14B at Q8, or 20-24B at Q4 |
| 24 GB | about 32B at Q4-Q5 |
| 32 GB | 32B at Q8, or 70B at about Q2-Q3 or with offload |

`UC_LOCAL_AI_VRAM` (INFO) reports this for `--use-case local-ai`. VRAM is the gate: buy VRAM before GPU speed.

## Knowledge horizon

GPU lineups, tiers, VRAM evidence and AI-stack support are dated and move fastest. Check `as_of` in `pc-builder/data/rules.v1.json`; anything newer is unknown until verified live with the `web-research` skill and added to the rules (`NOT_IN_RULES_DATA`). Never fill the gap from memory.

## Linux drivers (`os: linux` or `steamos`)

| Vendor | Stance | Notes |
|---|---|---|
| AMD | **Default** for Linux and SteamOS | RADV/Mesa, in-tree, no Secure Boot signing; the only vendor fully supported on SteamOS. RDNA4 needs kernel 6.12+ and Mesa 25.0+ |
| Intel Arc | **Budget** | Xe driver: B580 from kernel 6.12; SteamOS community tier |
| NVIDIA | **With caveats** | Not on SteamOS (HARD). 595.58.03 recommended; 580 is the last driver for Maxwell/Pascal/Volta; DX12 runs slower than on Windows; MOK enrolment under Secure Boot. Fine on Bazzite, CachyOS, Pop!_OS |

All driver facts are I-labelled secondary coverage. For local AI on Linux, the ROCm and CUDA notes above still apply.

## Anti-patterns

| Don't | Why |
|---|---|
| Recommend an 8 GB card for AAA at high settings | Measured stutter at 1080p Very High; 12 GB floor, 16 GB default. Fine for esports |
| Quote FPS from a tier table | Tiers are relative classes; FPS needs game, resolution, preset, upscaling, driver, date and source |
| Compare frame-generated FPS with native FPS | Different quantities |
| Recommend IPEX-LLM or IPEX | Archived (Jan and Mar 2026) |
| Promise ROCm on Windows, or Ollama on RDNA4 under Windows | Partial; Ollama for Windows lists only RDNA3 |
| Sell AMD or Intel for training or vLLM | CUDA is the only day-one path |
| Pair a B580 with an old CPU | It wants a 7600-class CPU or newer |
| Recommend AMD/Intel for V-Ray, Redshift or Octane | NVIDIA-only renderers |
| Repeat driver/CUDA install steps here | Apply `rhel-ollama-nvidia` / `ubuntu-ollama-nvidia` |
| Sell NVIDIA for SteamOS, or as the default Linux card | Unsupported on SteamOS; AMD is the Linux default |
| Name an RTX 50 Super or Arc B770 as available | Unconfirmed / unreleased as of 2026-09-27 |

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: nvidia-linux-driver-branch
    source_url: https://www.club386.com/valve-steamos-diy-pc-nvidia/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "NVIDIA on Linux: 595.58.03 recommended stable, 610 feature branch targets the DX12 deficit, 580 last for Maxwell/Pascal/Volta (I-labelled); not supported on SteamOS."
  - kind: external_fact
    subject: puget-2025-creator-results
    source_url: https://www.pugetsystems.com/labs/articles/2025-consumer-gpu-content-creation-roundup/
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Puget 2025: RTX leads in DaVinci Resolve and Blender OptiX; V-Ray, Redshift and Octane are NVIDIA-only; Arc B580 failed the Resolve suite; AMD +25% on Long-GOP in Premiere."
  - kind: external_fact
    subject: hub-8gb-vram-verdict
    source_url: https://www.tomshardware.com/pc-components/gpus/rtx-5060-ti-8gb-struggles-due-to-lack-of-vram-and-not-just-at-4k-ultra
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "HUB (S-labelled): RTX 5060 Ti 8 GB vs 16 GB, 67 vs 109 fps in TLOU2 at 1080p Very High, 8 GB stuttering and crashing. Basis for scoping 8 GB to esports and 1080p medium/high."
  - kind: external_fact
    subject: rocm-version-and-windows-support
    source_url: https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "ROCm 10.0 (26 Aug 2026) supports RX 9070 XT/GRE/9070, 9060 XT/9060/9050 and 7900/7800/7700/7600; the Windows stack is partial."
  - kind: external_fact
    subject: ollama-rdna4-windows
    source_url: https://docs.ollama.com/gpu
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Ollama on Windows lists only RDNA3 among AMD cards."
  - kind: date_review
    subject: dlss-fsr-xess-frame-generation
    review_by: 2026-12-27
  - kind: external_fact
    subject: nvidia-50-super-status
    source_url: https://www.nvidia.com/en-us/geforce/graphics-cards/compare/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "RTX 50 Super unconfirmed, possibly cancelled."
  - kind: date_review
    subject: intel-arc-b770-status
    review_by: 2026-12-27
  - kind: date_review
    subject: techpowerup-relative-performance-figures
    review_by: 2026-12-27
  - kind: date_review
    subject: intel-ipex-archived-and-openvino-version
    review_by: 2027-03-27
  - kind: external_fact
    subject: ddr5-gddr7-pricing-context
    source_url: https://dropreference.com/en/blog/news/shortage-ddr5-ram-global-status-july-2026
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Memory pricing shock (DDR5 about 4.95x Sep 2025 in July 2026) moves GPU and VRAM value; re-check quarterly."
-->
