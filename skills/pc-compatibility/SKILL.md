---
name: pc-compatibility
description: PC part compatibility - will these parts work together? CPU socket and motherboard chipset (AM4, AM5, LGA1700, LGA1851), DDR4 vs DDR5, BIOS support for a new CPU, overclocking chipsets, APU and x8 GPU PCIe links, M.2 lane sharing, display output, and case fit for board, PSU, GPU and cooler. Use when a parts list must be validated or a mismatch explained.
---

# PC Compatibility

## Overview

Compatibility is a set of relations between component fields. Each rule below has an id in `pc-builder/data/rules.v1.json`, is enforced by `pc-builder/scripts/pc_check.py`, and reads its facts from the caller's component records first, using the platform tables only as a fallback or cross-check. Full tables: [references/platform-tables.md](references/platform-tables.md).

## When to use

- A parts list must be validated before it is shown or sold.
- A customer or agent asks "will X work with Y?".
- A `pc_check` finding needs explaining in plain English.

**Not for:** PSU wattage, power connectors or cooler capacity (`pc-power-sizing`); which GPU to buy (`pc-gpu-tiering`); budget allocation (`pc-build-recommendations`).

## Rules: what each means and how it is checked

### Platform (HARD unless noted)

| Rule id | Means | Checked as |
|---|---|---|
| `CPU_BOARD_SOCKET` | The CPU physically fits only a board with the same socket | `cpu.socket == board.socket` |
| `BOARD_CHIPSET_SOCKET` | A chipset belongs to one socket (B850 is AM5, Z890 is LGA1851) | chipset in the socket's chipset list |
| `BOARD_MEMORY_TYPE_SOCKET` | AM4 is DDR4 only; AM5 and LGA1851 DDR5 only; each LGA1700 **board** is DDR4 or DDR5, never both | `board.memory_type` allowed for the socket |
| `RAM_TYPE_BOARD` | DDR4 and DDR5 modules are keyed differently and cannot be swapped | `ram.type == board.memory_type` |
| `CPU_CHIPSET_UNSUPPORTED` | A520, B550 and X570 do not support Ryzen 1000/2000 | `(cpu.family, board.chipset)` not in the unsupported list |
| `BIOS_CPU_SUPPORT` | The board's **shipped** BIOS must support the **exact** CPU, or the PC will not POST | `board.bios.cpu_support_confirmed` true, or `cpu.model` on `board.bios.supported_cpus` (the vendor support list from the DB). Known unsupported: HARD. Unknown: "cannot check", and incomplete (exit 3) under `--final` |
| `DISPLAY_OUTPUT` | No graphics card needs an iGPU **and** board video outputs. F/KF SKUs (7500F, 265KF) and non-G Ryzen 5000 have none; a 9600X or 7600 does (iGPU table in the reference) | iGPU from `cpu.igpu`, else the sourced `igpu_rules`; a contradiction is `IGPU_DATA_CONFLICT` (WARN) and trusts neither |
| `RAM_MODULES_SLOTS` | More modules than slots cannot be installed (H610 and H810 boards have 2) | `ram.modules <= board.dimm_slots` |

### Firmware and memory (WARN / INFO)

| Rule id | Means | Checked as |
|---|---|---|
| `BIOS_MINIMUM` (WARN) | Dated diagnostic guidance on which BIOS a newer CPU needs: Ryzen 9000 on 600-series AGESA 1.2.0.0+; 9850X3D 1.2.8.0; 9950X3D2 1.3.0.0a; Ryzen 5000 on X370/B350/A320 a Selective Beta BIOS; Raptor Lake on 600-series and 200S Plus on 800-series may need an update. Confirmed support (`BIOS_CPU_SUPPORT`) supersedes it | `board.bios.agesa` vs the minimum, unless support is confirmed |
| `AM5_FOUR_DIMMS` (WARN) | On Ryzen 7000/9000 the official speed drops from DDR5-5600 (2 DIMMs) to 3600 (4 DIMMs). Two modules is the rule | AM5 and `ram.modules >= 4` |
| `RAM_SPEED_OFFICIAL` (INFO) | Speeds above the CPU's official rating run on an EXPO/XMP profile. On AM5 the sweet spot is DDR5-6000 CL30 at 1:1 | `ram.speed` vs the official table |
| `OC_CHIPSET_LOCKED` (WARN) | A620, B840, H610, H810, B660, B760, H670, H770 and B860 cannot overclock a K/X CPU, so the unlocked premium buys nothing | `cpu.unlocked` on a listed chipset |

Memory capacity by use lives in `pc-build-recommendations`.

### PCIe links (WARN / INFO)

| Rule id | Means | Checked as |
|---|---|---|
| `APU_GPU_LANES` (WARN) | Ryzen 8000G gives a graphics card x8 (8700G/8600G) or only **x4** (8500G/8300G) at PCIe 4.0 | GPU lanes vs the APU table |
| `X8_LINK_GEN_LOW_VRAM` (WARN) | x8 cards (RTX 5050/5060/5060 Ti, 4060/4060 Ti, RX 7600, Arc B570/B580) lose bandwidth on an older slot. With 8 GB, once VRAM overflows: -6% average and -7% 1% lows on 4.0 (8 titles -9% or worse); severe stutter on 3.0 | effective lanes <= 8, effective generation below the card's, `gpu.vram_gb <= 8` |
| `X8_LINK_GEN` (INFO) | Same link loss with more than 8 GB: little effect while VRAM is not exceeded | as above with `vram_gb > 8` |
| `LANE_SHARING` (WARN) | Some boards drop the GPU to x8 when a Gen5 M.2 is populated (some X870E and Z790), or disable SATA ports for a chipset M.2 | storage slot in `board.lane_sharing` triggers |

The RX 9060 XT is x16 (PCIe 5.0), so it is not an x8 card. The effective link is the minimum of the card, the slot (board record, else chipset table), the APU cap and any active lane sharing.

**Lane sharing is board-specific.** Read it from the board's own data (`board.lane_sharing`); never assume it from the chipset. An absent field is reported "cannot check" whenever storage is present; an empty list means "none".

### Physical fit (HARD, INFO)

| Rule id | Means | Checked as |
|---|---|---|
| `BOARD_CASE_FIT` | ATX 305x244 mm, mATX 244x244, ITX 170x170, E-ATX 305x330 | form factor in `case.board_form_factors` |
| `PSU_CASE_FIT` | ATX PSUs (150x86x140 mm) do not fit SFX-only cases; SFX (125x63.5x100) and SFX-L (125x63.5x130) fit an ATX bay | form factor vs `case.psu_form_factors` |
| `PSU_SFX_BRACKET` (INFO) | An SFX unit in an ATX bay needs a bracket | SFX/SFX-L in an ATX-only bay |
| `GPU_CASE_LENGTH`, `GPU_CASE_SLOTS` | The card must clear the case in length and thickness | `gpu.length_mm`, `gpu.slots` vs case limits |
| `COOLER_CASE_FIT` | Air: cooler height vs case clearance. AIO: radiator size vs supported mounts | per `cooler.type` |
| `COOLER_SOCKET` | The cooler needs a mount for the socket. LGA1851 uses the LGA1700 hole pattern | `cpu.socket` in `cooler.sockets` |
| `COOLER_REQUIRED` | 9600X, 9800X3D, 9950X and 265K ship without a cooler | no cooler and `cpu.box_cooler` false |

Cooler **capacity** is in `pc-power-sizing`.

## Linux kernel minimums and Wi-Fi (`os: linux` or `steamos`)

- `OS_KERNEL_MINIMUM` (HARD): RDNA4 kernel 6.12+ and Mesa 25.0+; Arc B-series 6.12+; Xe3 6.17+. `OS_KERNEL_RECOMMENDED` (WARN): Ryzen 9000 6.10+, Arrow Lake 6.14+.
- `OS_WIFI_UNSUPPORTED` (HARD): MT7927, fit an Intel card. WARN: RTL8922AE (regressed on 6.18+), and any chip not known good (MT7925, Intel AX2xx/BE2xx).
- SteamOS 3.8 ships kernel 6.16. Detail: [references/linux-platform.md](references/linux-platform.md).

## Knowledge horizon

Sockets, chipsets, BIOS minimums and iGPU rules are dated tables. Check `as_of` in `pc-builder/data/rules.v1.json`; anything newer is unknown until verified live with the `web-research` skill and added to the rules (`NOT_IN_RULES_DATA`). Never fill the gap from memory.

## Anti-patterns

| Don't | Why |
|---|---|
| Assume lane sharing from the chipset | It is board-specific; read `board.lane_sharing` |
| Treat LGA1700 as "DDR5" | Each LGA1700 board is DDR4 or DDR5 |
| Sell 4 DIMMs on AM5 for speed | Official speed drops to 3600; 2 larger modules is the rule |
| Pair an unlocked K/X CPU with a locked chipset and call it an overclocking build | Those chipsets cannot overclock it |
| Promise a CPU works because the AGESA number looks new enough | Only confirmed support for the exact shipped BIOS counts (`BIOS_CPU_SUPPORT`) |
| Ship a no-GPU build without checking the CPU has graphics and the board has outputs | No display output (`DISPLAY_OUTPUT`, HARD) |
| Put an 8 GB x8 card on a PCIe 3.0 board | Severe stutter once VRAM overflows (measured) |

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: linux-kernel-mesa-minimums
    source_url: https://www.gamingonlinux.com/2026/06/steamos-3-8-is-out-with-initial-steam-machine-support-desktop-mode-upgrades-new-graphics-drivers/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "RDNA4 kernel 6.12+/Mesa 25.0+; Arc B 6.12+; Xe3 6.17+; Ryzen 9000 6.10+; Arrow Lake 6.14+ (I-labelled). Add minimums for Zen 6, the RDNA successor and Nova Lake when they launch."
  - kind: external_fact
    subject: rtw89-mt7927-fixes
    source_url: https://www.linaro.org/blog/from-replace-it-with-intel-to-upstream-bringing-mediatek-bluetooth-wifi-7-to-linux/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "MT7927 patches not merged as of 19 Mar 2026; RTL8922AE (rtw89) regression on kernels 6.18+ with no fix yet."
  - kind: external_fact
    subject: agesa-minimums
    source_url: https://www.gigabyte.com/press/news/2374
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Ryzen 9000 on 600-series: AGESA 1.2.0.0+; 9850X3D: 1.2.8.0; 9950X3D2: 1.3.0.0a (I-labelled)."
  - kind: external_fact
    subject: zen7-socket
    source_url: https://www.techpowerup.com/351994/amd-confirms-am5-compatibility-with-olympic-ridge-desktop-zen-6
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Zen 6 confirmed for AM5; Zen 7 socket disputed (AM5 vs AM6)."
  - kind: external_fact
    subject: lga1954-lifespan
    source_url: https://en.wikipedia.org/wiki/LGA_1954
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "LGA1954 (Nova Lake, 900-series chipsets) expected Q1 2027; LGA1851 has no CPU upgrade path."
  - kind: external_fact
    subject: am5-chipset-table
    source_url: https://www.amd.com/en/products/processors/chipsets/am5.html
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "AM5 chipset PCIe generations and overclocking capability as tabulated; B650/B650E have dropped off AMD's page."
-->
