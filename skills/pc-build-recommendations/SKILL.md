---
name: pc-build-recommendations
description: Recommended ("our pick") desktop PC builds for a UK retailer - use-case profiles, budget allocation from live prices, UK GBP budget bands, the build page contract and publish gate, and UK pricing and advertising compliance (CAP Code, CMA price transparency, DMCC). Use when generating or reviewing a recommended build or its page.
---

# PC Build Recommendations

## Overview

An "our pick" build is a claim the retailer must be able to defend. This skill turns a use case and a budget band into a build using **live prices from the caller's database**, writes the page data, and gates it with `pc_check.py --publish-gate` before anyone sees it. It carries method and rules only; no prices. Profiles: [references/use-case-profiles.md](references/use-case-profiles.md). Page contract: [references/our-pick-page-contract.md](references/our-pick-page-contract.md).

## When to use

- Generating an "our pick" or "PC for X" build and its page.
- Reviewing a build page for honesty and UK compliance.
- Splitting a budget across parts.

**Not for:** whether two parts fit (`pc-compatibility`), PSU wattage (`pc-power-sizing`), GPU tier detail (`pc-gpu-tiering`). This skill uses all three.

## Ambiguity gate (ask before generating)

A build needs three answers: **use case** (a profile id below), **budget band** (from `pc-builder/data/budget-bands.uk.v1.json` or the caller's override) and **resolution or workload** (implied by `aaa-*`, `school`, `office`).

- **Interactive caller:** ask ONE compact question covering every missing answer, then generate.
- **DB worker or batch job:** run `pc_check.py --context-gate --use-case <id> --band <id> --workload "<text>"`. A `needs_input` result (exit 3, `schemas/needs-input.v1.json`) lists what is missing and carries one ready-made question; route it, do not guess.

## Use-case profiles (summary)

| Profile id | Gate |
|---|---|
| `school`, `office` | APU or any non-F CPU with an iGPU (a 9600X/7600 iGPU is enough for display), 16 GB (office 16 to 32 GB), 1 TB SSD. No discrete GPU, no RGB |
| `media` | APU or entry GPU, low noise |
| `esports` | 6-core + 9060 XT-class; 12 GB VRAM preferred, not required |
| `aaa-1080p` / `aaa-1440p` / `aaa-4k` | 9060 XT/5060 Ti 16 GB; 9070/5070 with 9700X/9800X3D; 5080/5090 |
| `streaming` | GPU encoder; 8 cores only when encoding on the CPU (`workload.encoding_mode`) |
| `creator` | 12-16 cores, 64 GB, 16 GB+ VRAM |
| `dev` | 8 cores, 32 to 64 GB, 2 TB |
| `local-ai` | VRAM is the gate |
| `linux-gaming`, `steamos-living-room` | See "Linux and SteamOS builds" below |
| `workstation` | ECC: AM5 support is board-dependent; W880 on LGA1851 |

The checker's per-profile minimums (RAM, VRAM, cores) live in `pc-builder/data/rules.v1.json` `use_cases`.

## Budget method: allocate from runtime prices

Never use fixed percentage splits. The 2026 memory shock (UK DDR5 about 4.95x its Sep 2025 level in July 2026) breaks any fixed split. Instead:

1. **Fix the non-negotiables first:** a PSU that meets `pc-power-sizing` (the smallest stocked quality unit at or above the recommendation, never more), and a cooler and case that fit. **Never save on PSU quality.**
2. **Spend by priority when the band is tight:** GPU, then CPU, RAM capacity, storage speed, case and cooling (for gaming; for productivity, the workload's bottleneck part first).
3. **Save on:** a feature-light board (right chipset, no extras) and a 6-core CPU for gaming.
4. **Keep balance:** no flagship CPU with an entry GPU for gaming; no flagship GPU with a weak CPU for productivity, unless GPU compute is the workload.
5. **Price every candidate from the database now**, add every mandatory charge, and keep the total inside the band. If it cannot fit, drop down one step in step 2's order; never cut the PSU.
6. **Check the build:** `pc_check.py build.json --use-case <id> --band <id> --final`. Exit 2 = cannot ship; exit 3 = incomplete data, fix the data. Every WARN is resolved or disclosed.
7. **Gate the page:** `pc_check.py page.json --publish-gate`. Only exit 0 is published.

## UK budget bands are data

Default bands (VAT-inclusive, full tower, no OS or monitor) live in `pc-builder/data/budget-bands.uk.v1.json`, with an `as_of` date and a typical build per band. **The caller overrides them** (`--bands <file>`). Never restate band edges or typical costs in page copy as if they were fixed facts.

## The "our pick" page contract (summary)

The page data is an `our-pick.v1` object (`pc-builder/schemas/our-pick.v1.json`); the publish gate enforces it:

- **Line items and mandatory charges from the database**, a headline total the gate **recomputes**, VAT-inclusive, dated, inside the band.
- **Per part: role and why.**
- **Compatibility claims only from a clean `--final` run.** Genuine WARNs may be disclosed; "cannot check" findings never are.
- **A performance class**, not FPS (FPS only with game, resolution, preset, upscaling/frame generation, driver, date and source).
- **Upgrade path:** LGA1851 has no CPU upgrade path; AM5 upgrades promised only as far as Zen 6; PSU headroom.
- **What not to pay for**, and **exclusions:** OS and monitor not included.
- **Dated selection criteria** behind "our pick"; dated market-wide evidence behind any superlative.

## UK compliance

CAP Code 3.7: hold dated evidence for every objective claim, including the basis for "our pick". CAP 3.33 and 3.34: comparisons with named competitors must cover products meeting the same need, on verifiable features. CMA209: the headline price includes every mandatory charge. DMCC: no drip pricing, no fake reviews. Table and sources: [references/uk-compliance.md](references/uk-compliance.md).

## Linux and SteamOS builds

- Profiles: `linux-gaming` (AMD by default, NVIDIA with caveats; `buyer.games` checked against the anti-cheat snapshot) and `steamos-living-room` (AMD graphics, Intel community tier, never NVIDIA; no dual boot). A profile/OS mismatch is `OS_PROFILE_MISMATCH`.
- A must-have game that is Denied or Broken on Are We Anti-Cheat Yet is HARD (`OS_GAME_ANTICHEAT`): sell Windows instead.
- The publish gate requires `os_disclosures` on every Linux or SteamOS page: anti-cheat titles, no Game Pass or Office, RGB software, support scope, return path (`PUB_OS_DISCLOSURES`).
- SteamOS pages say "SteamOS preinstalled (community-supported install)". A Valve mark ("Powered by SteamOS", "Steam Machine") without a licence blocks publication (`PUB_STEAMOS_BRANDING`). Detail: [references/os-builds.md](references/os-builds.md).

## Knowledge horizon

Profiles, bands (`as_of` in the bands file, stricter limits) and compliance guidance are dated. Check `as_of` in `pc-builder/data/rules.v1.json`; anything newer is unknown until verified live with the `web-research` skill and added to the rules (`NOT_IN_RULES_DATA`). Never fill the gap from memory.

## Anti-patterns

| Don't | Why |
|---|---|
| Split a budget by fixed percentages | Live prices decide; the 2026 memory shock broke every fixed split |
| Cut the PSU to fit the band, or oversize it to look premium | Never save on PSU quality; never buy watts you do not need |
| Quote FPS without full test conditions | CAP 3.7 substantiation; use a performance class |
| Treat "our pick" as a safe label, or call a build "the best" without dated evidence | CAP 3.7 applies to the objective basis of either |
| Cite CAP 3.33 as the basis for superlatives | 3.33 is about comparing products that meet the same need; superlatives rest on 3.7 evidence |
| Publish a total that excludes a mandatory charge, or an ex-VAT price | CMA209 3.3 and 4.4; DMCC drip pricing |
| Publish "compatibility checked" with any "cannot check" finding | Only a clean `--final` run backs the claim |
| Invent or seed reviews | DMCC fake-review ban |
| Promise an LGA1851 CPU upgrade, or AM5 beyond Zen 6 | LGA1851 has no path; Zen 7 socket is disputed |
| Generate a build without a use case, band and workload | Ask one question, or return the `needs-input.v1` result |

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: awacy-anti-cheat-list
    source_url: https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/HEAD/games.json
    verified_on: 2026-09-27
    review_by: 2026-10-27
    claim: "The anti-cheat list is data (data/awacy-snapshot.json, 1,167 games on 2026-09-27); refresh with scripts/refresh_awacy.py (the checker warns at 30 days, blocks --final at 60)."
  - kind: date_review
    subject: anticheat-new-cod-battlefield
    review_by: 2026-12-27
  - kind: date_review
    subject: game-pass-on-linux
    review_by: 2026-12-27
  - kind: external_fact
    subject: ddr5-gddr7-pricing-context
    source_url: https://dropreference.com/en/blog/news/shortage-ddr5-ram-global-status-july-2026
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "UK DDR5 about 4.95x its Sep 2025 level in July 2026 (peak 5.28x, March 2026); budgets must allocate from runtime prices."
  - kind: external_fact
    subject: zen7-socket
    source_url: https://www.techpowerup.com/351994/amd-confirms-am5-compatibility-with-olympic-ridge-desktop-zen-6
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "AM5 upgrades promised only as far as Zen 6; Zen 7 socket disputed."
  - kind: external_fact
    subject: lga1954-lifespan
    source_url: https://en.wikipedia.org/wiki/LGA_1954
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "LGA1851 has no CPU upgrade path; LGA1954 expected Q1 2027."
  - kind: date_review
    subject: techpowerup-relative-performance-figures
    review_by: 2026-12-27
  - kind: external_fact
    subject: cma209-price-transparency
    source_url: https://assets.publishing.service.gov.uk/media/698f4e3e7da91680ad7f4417/CMA209_Unfair_commercial_practices__price_transparency_13.2.26.pdf
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "CMA209 (13 Feb 2026): headline prices include all mandatory charges (3.3); mandatory charges include VAT and unavoidable fees (4.4)."
  - kind: external_fact
    subject: dmcc-act-drip-pricing-fake-reviews
    source_url: https://cms.law/en/gbr/legal-updates/the-dmcc-act-consumer-elements-come-into-force-from-6-april-2025
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "DMCC Act 2024 consumer provisions in force from 6 Apr 2025: drip pricing and fake reviews banned."
  - kind: external_fact
    subject: cap-code-substantiation-and-comparisons
    source_url: https://www.asa.org.uk/type/non_broadcast/code_section/03.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "CAP 3.7: documentary evidence for objective claims. CAP 3.33: compare products meeting the same needs or intended for the same purpose. CAP 3.34: objectively compare material, relevant, verifiable and representative features."
-->
