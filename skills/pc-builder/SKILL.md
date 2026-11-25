---
name: pc-builder
description: PC building router for a UK PC retailer - how desktop parts depend on each other, the build-order chain, the deterministic pc_check.py checker and its publish gate. Use when explaining a build or validating a parts list end to end; routes to pc-compatibility (will parts fit), pc-power-sizing (PSU and cooling), pc-gpu-tiering (graphics and local AI) and pc-build-recommendations ("our pick" builds and pages).
---

# PC Builder (family router)

## Overview

A PC build is a chain of dependencies: every choice narrows the next. This family carries the **relationships, method and rules** for a UK PC retailer's agents and database workers. It carries **no prices and no product catalogue**: product specs and prices always come from the caller's database at runtime (the 2026 memory shock moved UK DDR5 to about 4.95x its Sep 2025 cost, so anything written down would be wrong within weeks).

The rules are enforced deterministically by `scripts/pc_check.py` against `data/rules.v1.json`, so a DB worker can validate a build, and gate a page, without an LLM.

## Knowledge horizon

- The rules data is dated: check `as_of` in `data/rules.v1.json` and `data/budget-bands.uk.v1.json`. `pc_check.py` warns when either is old (`RULES_DATA_STALE`, `BANDS_DATA_STALE`) and blocks `--final` and `--publish-gate` when it is too old.
- Treat anything newer than `as_of` (a new CPU or GPU generation, chipset, socket, PSU or connector standard) as **unknown** until it is verified live with the `web-research` skill and added to the rules. The checker reports it as `NOT_IN_RULES_DATA` and never maps it to the nearest known part.
- **Never fill a gap from memory:** a model's training data lags reality by 1-2 years. Refresh with [references/refresh-procedure.md](references/refresh-procedure.md).

## When to use

- Explaining a build, validating a parts list end to end, or gating a recommended-build page.

**Not for:** laptops or prebuilt OEM warranty support; Linux GPU driver, CUDA or Ollama server setup (see `rhel-ollama-nvidia` / `ubuntu-ollama-nvidia`); live pricing (the caller's database owns it).

## How a PC is built: roles and dependency order

| Step | Component | Role | Constrained by |
|---|---|---|---|
| 1 | CPU | Sets the platform (socket), memory type, PCIe lanes, sustained power and whether there is integrated graphics | Use case, budget |
| 2 | Motherboard | Must match the CPU socket; the chipset sets overclocking, PCIe generations, M.2 slots and DIMM count; its shipped BIOS must support the exact CPU; its video outputs matter when there is no GPU | CPU socket, CPU model |
| 3 | Memory (RAM) | DDR type is fixed by the board (AM4 DDR4; AM5 and LGA1851 DDR5; LGA1700 either, per board) | Board memory type, DIMM slots |
| 4 | GPU (or iGPU) | Display output and graphics/compute; its PCIe link depends on the slot, the CPU and board lane sharing | Use case, board, CPU lanes |
| 5 | Storage | M.2 or SATA; some M.2 slots share lanes with the GPU or SATA ports | Board lane-sharing data |
| 6 | PSU | Sized from CPU sustained power + GPU board power + rest of system, never below the card maker's minimum; must supply a power arrangement the card maker documents | CPU + GPU |
| 7 | Cooler | Sized from CPU sustained power; must fit the socket and the case | CPU power, socket, case |
| 8 | Case | Must fit the board, PSU, GPU length/thickness and cooler height or radiator | Board, PSU, GPU, cooler |

Decide in that order; if a later part does not fit, say so and change it, never silently.

## Operating systems

| OS | Suits | Route |
|---|---|---|
| Windows (default; `os` absent) | Everyone, and anyone who plays anti-cheat multiplayer (Fortnite, Valorant, CoD, Battlefield) or needs Game Pass or Office | No OS rules run |
| Linux (`os: linux`) | Buyers coming from Linux, developers, Steam players whose games are Supported/Running on Are We Anti-Cheat Yet | `pc-gpu-tiering` (drivers), `pc-compatibility` (kernel, Wi-Fi), `pc-build-recommendations` (`linux-gaming`, disclosures) |
| SteamOS (`os: steamos`) | A controller-first living-room PC on AMD graphics | `steamos-living-room` profile; never NVIDIA; "SteamOS preinstalled (community-supported install)", never a Valve mark without a licence |

About 3.9% of Steam users ran Linux in Aug 2026 [I]. Detail: [references/os-guide.md](references/os-guide.md).

## Route to the right child

| The request is about | Apply |
|---|---|
| Socket, chipset, DDR type, BIOS support, overclocking, APU lanes, x8 GPUs, lane sharing, display output, physical fit | `pc-compatibility` |
| PSU wattage, maker minimums, power-connector arrangements, PSU quality, cooler sizing, mesh vs glass | `pc-power-sizing` |
| GPU tiers, VRAM, creator and encoder choice, CUDA / ROCm / Intel AI stacks, model size vs VRAM | `pc-gpu-tiering` |
| Use-case profiles, budget allocation, UK bands, "our pick" pages, advertising and pricing compliance | `pc-build-recommendations` |

A full "our pick" build uses all four in the order above, then runs the checker in `--final` mode and the page through `--publish-gate`.

## Ambiguity gate (ask before generating)

A build needs: **use case**, **budget band** (from `data/budget-bands.uk.v1.json` or the caller's override) and **resolution or workload** (implied by `aaa-1080p` / `aaa-1440p` / `aaa-4k`, `school` and `office`).

- **Interactive caller:** ask ONE compact question covering every missing input, then generate.
- **DB worker or batch job:** do not guess and do not stop silently. Run
  `python3 scripts/pc_check.py --context-gate --use-case <id> --band <id> --workload "<text>"`.
  It prints a `needs-input.v1` result (`schemas/needs-input.v1.json`): `status` `ok` (exit 0) or `needs_input` (exit 3), the `missing` and `invalid` inputs, and one ready-made `question` to route to someone who can answer.

## Deterministic checker

`python3 scripts/pc_check.py build.json [--use-case <id>] [--band <id>] [--final]`, and `--publish-gate` for an `our-pick.v1` page. Exit 0 ok, 2 a HARD finding (or a publish blocker), 3 bad input or incomplete under `--final`. **Missing data is never a pass.** Modes, flags, schemas and reading findings: [references/checker-usage.md](references/checker-usage.md).

## Data files

- `data/rules.v1.json`: versioned rules and publish rules (each with a V/S/I source), platform tables, PSU policy, use-case profiles.
- `data/budget-bands.uk.v1.json`: default UK bands, dated; the caller overrides them.
- The caller's database: every spec and price, BIOS support lists, maker PSU minimums and power arrangements.

Labels: **V** read on the source, **S** search excerpt, **I** inference (engineering judgement, not published fact).

## Anti-patterns

| Don't | Why |
|---|---|
| Put prices, or "typical" part costs, in a skill or a prompt | Prices move weekly (2026 DDR5 shock); they come from the caller's database at runtime |
| Allocate a budget with fixed percentages ("GPU = 40%") | The right split depends on live prices; allocate from runtime prices by priority |
| Pass a build because a field was missing | Missing data is WARN "cannot check"; under `--final` a missing HARD input is incomplete (exit 3) |
| Publish "compatibility checked" on a non-final run | Only a clean `--final` run backs the claim; "cannot check" findings are never disclosed as checked |
| Guess the use case or budget band | Ask one compact question, or return the `needs-input.v1` result |
| Quote FPS without game, resolution, preset, upscaling, driver, date and source | CAP 3.7 substantiation; use a performance class instead |
| Recommend a part newer than the data from memory | Training data lags 1-2 years; verify live, add to the rules |

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: steamos-nvidia-and-desktop-policy
    source_url: https://www.club386.com/valve-steamos-diy-pc-nvidia/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "SteamOS 3.8 (kernel 6.16) is allowed on DIY desktops with AMD or Intel graphics; NVIDIA support is in development, not expected in 2026; dual-boot not recommended."
  - kind: external_fact
    subject: steam-survey-linux-share
    source_url: https://www.gamingonlinux.com/2026/09/steam-linux-user-share-dips-below-4-percent-for-august-2026/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Steam Survey Aug 2026: Linux 3.90% (peak 5.33% Mar 2026); SteamOS 21.07% and CachyOS 15.4% of Linux users."
  - kind: date_review
    subject: linux-distro-eols
    review_by: 2026-12-27
  - kind: date_review
    subject: pc-builder-family-research-base
    review_by: 2026-12-27
  - kind: external_fact
    subject: ddr5-gddr7-pricing-context
    source_url: https://dropreference.com/en/blog/news/shortage-ddr5-ram-global-status-july-2026
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "UK DDR5 cost about 4.95x its Sep 2025 level in July 2026, peaking at 5.28x in March 2026. Re-verify quarterly; it is why prices never live in the skills."
-->
