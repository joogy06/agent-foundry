# GPU and AI tables

Research base: `docs/research/2026-09-27-pc-builder-research.md` section C. Labels: V read on the
source, S search excerpt, I inference. No prices: the caller's database supplies them.

## Lineup (as of 2026-09-27)

| Vendor | Cards | Source |
|---|---|---|
| NVIDIA | RTX 5050 8 GB, 5060 8 GB, 5060 Ti 8/16 GB, 5070 12 GB, 5070 Ti 16 GB, 5080 16 GB, 5090 32 GB. 50 Super: unconfirmed, possibly cancelled | [V] https://www.nvidia.com/en-us/geforce/graphics-cards/compare/ |
| AMD RDNA4 | RX 9050 (APAC only), 9060, 9060 XT 8/16 GB, 9070 GRE 12 GB (worldwide 2 Jun 2026), 9070, 9070 XT | research section C |
| Intel | Arc B570 10 GB, B580 12 GB (consumer). B770 unreleased. Arc Pro B70 32 GB (workstation, Mar 2026) | research section C |

## Board power (for PSU sizing)

| Card | TBP | Source |
|---|---|---|
| RTX 5060 | 145 W (measured 150-165 W, Guru3D) | [V] nvidia.com |
| RTX 5070 | 250 W | [V] nvidia.com |
| RTX 5070 Ti | 300 W | [V] nvidia.com |
| RTX 5080 | 360 W | [V] nvidia.com |
| RTX 5090 | 575 W (FE about 569 W average in games; 901 W spikes under 1 ms [S]) | [V] nvidia.com, https://gamersnexus.net/gpus/nvidia-geforce-rtx-5090-founders-edition-review-benchmarks-gaming-thermals-power |
| RX 9070 XT | 304 W | [V] amd.com |

## Relative performance [S] (TechPowerUp via search excerpts; the site blocked direct reads)

| Comparison | Result |
|---|---|
| Arc B580 vs RTX 5050 | about +5% |
| RX 9060 XT 8 GB vs RTX 5050 | about +33% |
| RX 9060 XT 16 GB vs RTX 5060 Ti 16 GB | about -3% |
| RX 9070 XT vs RTX 5070 Ti | about equal in raster, -4% with RT |
| RTX 5090 vs RTX 5080 | +48-52% at 4K |

## VRAM evidence

- HUB, RTX 5060 Ti 8 vs 16 GB: 67 vs 109 fps in TLOU2 at 1080p Very High; 8 GB stutters and crashes. [S] Scope: esports and 1080p medium/high are fine on 8 GB; AAA at high settings is not. https://www.tomshardware.com/pc-components/gpus/rtx-5060-ti-8gb-struggles-due-to-lack-of-vram-and-not-just-at-4k-ultra

## Creators

Puget 2025 consumer GPU content-creation roundup [V] https://www.pugetsystems.com/labs/articles/2025-consumer-gpu-content-creation-roundup/

| Application | Finding |
|---|---|
| DaVinci Resolve | RTX leads; Arc B580 failed the suite |
| Blender | RTX leads (OptiX) |
| V-Ray, Redshift, Octane | NVIDIA-only |
| Premiere Pro | AMD +25% on Long-GOP |
| Encoders | Historically NVENC >= QSV > AMF; RDNA4 improved (vendor claim) |

## AI stacks

| Stack | Detail | Source |
|---|---|---|
| ROCm 10.0 (26 Aug 2026) | Official: RX 9070 XT/GRE/9070, 9060 XT/9060/9050, 7900/7800/7700/7600. Windows partial | [V] https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html |
| Ollama (Windows) | Lists only RDNA3 among AMD cards | [V] https://docs.ollama.com/gpu |
| llama.cpp | CUDA, HIP, Vulkan, SYCL, OpenVINO backends | [V] research section C |
| CUDA | Only day-one path for training, fine-tuning and vLLM [I]; vLLM needs CC 7.5+ [V] | research section C |
| Intel | IPEX-LLM archived 28 Jan 2026 (security issues); IPEX archived 30 Mar 2026. Use upstream PyTorch XPU, OpenVINO 2026.4, or llama.cpp SYCL/Vulkan | [V] research section C |

Server driver, CUDA toolkit and Ollama installation: `rhel-ollama-nvidia` / `ubuntu-ollama-nvidia`.

## VRAM to model size

| Precision | GB per billion parameters |
|---|---|
| Q4_K_M | about 0.6 |
| Q8 | about 1.05 |
| FP16 | 2 |
| Context | plus 1-3 GB |

| VRAM | Fits |
|---|---|
| 8 GB | 7-8B at Q4-Q6 |
| 12 GB | 14B at Q4 |
| 16 GB | 14B at Q8, or 20-24B at Q4 |
| 24 GB | about 32B at Q4-Q5 |
| 32 GB | 32B at Q8, or 70B at about Q2-Q3 or with offload |

<!-- FRESHNESS:v1
volatility: high
anchors:
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
    claim: "ROCm 10.0 support list as tabulated; Windows partial."
  - kind: external_fact
    subject: ollama-rdna4-windows
    source_url: https://docs.ollama.com/gpu
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Ollama on Windows lists only RDNA3 among AMD cards."
  - kind: external_fact
    subject: nvidia-50-super-status
    source_url: https://www.nvidia.com/en-us/geforce/graphics-cards/compare/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "RTX 50 lineup as tabulated; 50 Super unconfirmed."
  - kind: date_review
    subject: intel-arc-b770-status
    review_by: 2026-12-27
  - kind: date_review
    subject: techpowerup-relative-performance-figures
    review_by: 2026-12-27
  - kind: date_review
    subject: dlss-fsr-xess-frame-generation
    review_by: 2026-12-27
-->
