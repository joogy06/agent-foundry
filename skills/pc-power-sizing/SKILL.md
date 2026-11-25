---
name: pc-power-sizing
description: PSU sizing and quality for a desktop PC - how many watts (is 750 W / 850 W / 1000 W enough), the card maker's minimum system PSU, 12V-2x6 / 12VHPWR cables and 8-pin adapters, ATX 3.x, Cybenetics ETA, SPL tier list, plus CPU cooler sizing and mesh vs glass case airflow. Use when choosing or checking a power supply or cooler.
---

# PC Power Sizing (PSU, cooling, cases)

## Overview

**No overkill.** A quality 750/850 W unit is right for everything below the RTX 5090 class. PSU size follows from numbers the caller's database already holds: the CPU's sustained power limit, the GPU's total board power, and the card maker's minimum system PSU. The policy is deterministic and implemented in `pc-builder/scripts/pc_check.py`. Worked examples: [references/psu-worked-examples.md](references/psu-worked-examples.md).

## When to use

- Picking or checking a PSU: "is 750 W / 850 W enough?", "adapter or native cable?"
- Picking a CPU cooler, or explaining mesh vs glass fronts.

**Not for:** socket, memory or physical-fit rules (`pc-compatibility`); GPU choice (`pc-gpu-tiering`).

## The policy [I]

```
DC               = CPU_limit + GPU_TBP x (1.10 if factory OC) + 75
hard minimum     = max(DC / 0.90, gpu.min_system_psu_w)           below: HARD
recommended      = smallest stocked size >= max(DC / 0.80, gpu.min_system_psu_w)
                                                                   below DC/0.80: WARN
quiet target     = DC / 0.70   (optional, INFO only, never required)
```

- **CPU_limit** is the sustained limit (AMD PPT, Intel max turbo power), not the marketing TDP: 9600X 88 W, 9800X3D 162 W, 9950X 230 W, 265K 250 W.
- **GPU_TBP** is the vendor total board power: RTX 5060 145 W, 5070 250 W, 5070 Ti 300 W, 5080 360 W, 5090 575 W; RX 9070 XT 304 W. Factory-OC cards draw about 10% more [I]; 75 W covers the rest of the system [I].
- **`gpu.min_system_psu_w`** is the card maker's figure from the database, e.g. NVIDIA: 850 W for the RTX 5080 FE, 1000 W for the 5090 FE [V]. It is optional; when present it is a floor.
- **Stocked size** is the smallest size the retailer stocks in a unit that passes the quality rules below (`--psu-catalog` or `build.psu_catalog_w`; empty is rejected).
- The 50-70% load band buys **low noise and headroom**, not efficiency: Gold and Platinum curves are fairly flat from 20% to 80% load. That is why the 0.70 figure is only an optional quiet target.

`pc_check.py` reports `psu_sizing {dc_w, hard_minimum_w, recommended_min_w, maker_min_system_psu_w, recommended_psu_w, quiet_target_w}`.

Worked results (9600X + 5060 = 550 W, 9800X3D + 5070 Ti = 750 W, 9800X3D + 5080 = 850 W, 9950X + 5090 = 1200 W) are tabulated in the reference file.

## The honest statement

- **750/850 W is fine below the 5090 class.** A 9800X3D + RTX 5080 is 597 W DC and about 555 W in games; NVIDIA's own minimum is 850 W.
- **The 5090 needs 1000 W or more.** NVIDIA's minimum is 1000 W; with a 9950X (880 W DC) the recommendation is 1200 W. The 5090 FE averages about 569 W in games, with spikes of 901 W for under 1 ms.
- Vendor "recommended PSU" figures assume a 9950X, so they overstate the need for smaller CPUs; use them as the maker minimum, not as a target to exceed.

## Power connectors: follow the card maker

| Rule id (checker) | Rule | Why |
|---|---|---|
| `GPU_POWER_CONFIG` (HARD) | The PSU must supply at least one arrangement the card maker documents (`gpu.supported_power_configs` from the DB). NVIDIA: RTX 5080 FE on its included adapter with **at least three independent dedicated 8-pin cables**, or one native 16-pin cable rated 450 W+; RTX 5090 FE on the adapter with **at least four**, or one native cable rated 600 W+ [V] | Anything else is outside the maker's documentation |
| `PSU_NATIVE_12V2X6_PREFERRED` (WARN) | For a 16-pin card, a native 12V-2x6 cable on an ATX 3.x unit is **preferred** over the adapter, which is still permitted | Fewer connections; GN traced melting to plugs not fully seated or inserted at an angle [S]. Seat the plug fully and straight |
| `PSU_ATX3_PREFERRED` (WARN) | ATX 3.x for GPUs of 300 W or more | ATX 3.x units over 450 W with 12V-2x6 must survive 200% of rating for 100 us; a GPU may pull 2.5x its sustained power for up to 100 us. ATX 3.1 kept 200% and set hold-up to 12 ms |

## PSU quality rules

| Rule id (checker) | Rule | Why |
|---|---|---|
| `PSU_EFFICIENCY` (WARN) | Units of 650 W and above: Cybenetics ETA Gold or better | ETA averages 1,450+ load combinations measured warm; 80 Plus checks only a few load points |
| `PSU_TIER` (WARN) | SPL tier A for GPUs of 300 W or more; tier B or better otherwise | Tier lists judge the platform/OEM, not the brand label |
| `PSU_CULTISTS_IGNORED` (WARN) | Never use the Cultists list | It is stale (rev 17.0g, 2023-04-11) |

**Never save on PSU quality**, and never "upgrade" by buying watts you do not need.

## Cooling by sustained CPU power

| Sustained CPU power | Cooler | Checker class |
|---|---|---|
| up to ~100 W | A single tower | `single_tower` |
| up to ~160 W | A good dual tower | `dual_tower` |
| ~230 W and above | A 360 mm AIO or a top dual tower | `aio_360`, `top_dual_tower` |

Evidence: GN 2025 at 25 dBA: the NH-D15 G2 matched the best 360 AIO at 157 W and was the only air cooler to finish at 276 W. The 9600X, 9800X3D, 9950X and 265K ship without a cooler (`COOLER_REQUIRED`). `COOLER_CAPACITY` warns when the class is under-sized; a class the research does not cover (e.g. 240 mm AIO) is reported as "cannot check".

## Cases: the defensible statement

- **At the same noise**, a mesh front runs several degrees cooler: up to ~18 C in GN's airflow-vs-silent test, and 45.6 vs 51 C for the same case in mesh vs glass (H500M vs H500P) at about equal noise.
- **At the same fan speed, or at idle**, a solid or damped front is as quiet or quieter.
- Therefore say: **"mesh is quieter at the same temperature"**. Never say "mesh is quieter". GN's case methodology normalises to 27 dBA.

## Knowledge horizon

TBP figures, maker PSU minimums, connector arrangements and PSU standards are dated. Check `as_of` in `pc-builder/data/rules.v1.json`; anything newer is unknown until verified live with the `web-research` skill and added to the rules (`NOT_IN_RULES_DATA`). Never fill the gap from memory.

## Anti-patterns

| Don't | Why |
|---|---|
| Size from TDP, or treat DC/0.70 as the requirement | Use sustained CPU power + GPU TBP; 0.70 is only an optional quiet target |
| Upsell 1000 W+ for a mid-range build | 750/850 W is fine below the 5090 class |
| Sell a PSU below the card maker's minimum system PSU | HARD rule (`PSU_BELOW_MINIMUM`) |
| Sell a 5090 build on 850 W | NVIDIA's minimum is 1000 W; 1200 W with a 9950X |
| Refuse the maker's adapter as "unsafe" | NVIDIA documents it; the native cable is a preference (WARN), not a requirement |
| Rank PSUs by brand or by 80 Plus badge | Judge the platform/OEM; use Cybenetics ETA and the SPL tier |
| Cite the Cultists PSU list | Stale since 2023-04-11 |
| Say "mesh is quieter" | Only at the same temperature |
| Put a single tower on a 160 W+ CPU | Below the research's cooling class for that power |

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: nvidia-rtx-5080-5090-psu-and-connector-guidance
    source_url: https://www.nvidia.com/content/geforce-gtx/GeForce_RTX_5080_User_Guide_Rev1.pdf
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "RTX 5080 FE: 850 W minimum; at least three independent 8-pin cables with the included adapter, or one 450 W+ 16-pin cable. RTX 5090 FE (geforce-rtx-5090-user-guide-r2.pdf): 1000 W minimum; at least four 8-pin cables with the adapter, or one 600 W+ 16-pin cable."
  - kind: external_fact
    subject: spl-psu-tier-list-update-date
    source_url: https://psutierlist.org/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "SPL tier list is the tier source (A for GPUs of 300 W+, B otherwise); its update date was unconfirmed on 2026-09-27. The Cultists list is stale (rev 17.0g, 2023-04-11)."
  - kind: external_fact
    subject: gpu-tbp-figures
    source_url: https://www.nvidia.com/en-us/geforce/graphics-cards/compare/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "RTX 5060 145 W, 5070 250 W, 5070 Ti 300 W, 5080 360 W, 5090 575 W TBP; RX 9070 XT 304 W."
  - kind: external_fact
    subject: atx31-transient-rules
    source_url: https://knowledge.seasonic.com/article/79-comparison-atx-3-0-vs-atx-3-1-standards
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "ATX 3.1 kept the 200% power-excursion rule and set hold-up time to 12 ms."
-->
