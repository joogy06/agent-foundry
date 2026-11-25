# pc-builder data

Versioned data consumed by `scripts/pc_check.py` and by the pc-* skills. JSON cannot carry a
FRESHNESS comment block, so the dated facts in the JSON files are anchored here. Each JSON file also
carries `as_of` and `review_by`.

| File | Contents | Dated facts |
|---|---|---|
| `rules.v1.json` | Rules, publish rules and platform tables (sockets, chipsets, overclocking, BIOS/AGESA minimums, APU lanes, x8 GPUs, official memory speeds, GPU tiers, use-case profiles) | AGESA minimums, socket horizons, GPU lineup and tiers |
| `awacy-snapshot.json` | Trimmed Are We Anti-Cheat Yet list (name, status), with `as_of` and a 30/60-day guard; regenerate with `scripts/refresh_awacy.py`, never edit by hand | The whole list goes stale weekly |
| `budget-bands.uk.v1.json` | Default UK budget bands (VAT-inclusive, no OS or monitor) | Band edges and typical builds move with DDR5/GPU pricing |

Rules to keep when editing:

- **No product prices.** Band edges are budgets, not prices. Specs and prices come from the caller's database.
- Every rule keeps `id`, `severity` (HARD/WARN/INFO), `inputs`, `relation`, `message`, and `source {label, url}`.
- A new rule needs an implementation in `RULE_IMPLS` and a failing-first test; `tests/` asserts the two sets are equal.
- Bump `version` on any rule change; the checker reports it as `rules_version`.
- `publish_rules` hold the page-gate blockers (`--publish-gate`); they follow the same shape and need a test each.
- Version 2.4.0: the `os` block (SteamOS policy and branding, Linux drivers, kernel/Mesa minimums, Wi-Fi, distros, disclosures), OS rules and the `linux-gaming` / `steamos-living-room` profiles. 2.3.0: staleness guards.
- Version 2.2.0: `cpu_families` (canonical slugs + aliases) and `cpu_family_from_model`; a human-form `cpu.family` is normalised for lookup, an absent one is derived from `cpu.model`, an unrecognised one is 'cannot check'. 2.1.0: `igpu_rules`.
- Version 2.0.0 (2026-09-27 revise round): display output, BIOS support, `--final` and `--publish-gate`, the no-overkill PSU policy, maker-documented GPU power configurations, scoped VRAM and use-case rules, sourced LGA1700/LGA1851 chipset lists.

<!-- FRESHNESS:v1
volatility: high
anchors:
  - kind: external_fact
    subject: agesa-minimums
    source_url: https://www.gigabyte.com/press/news/2374
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Ryzen 9000 on 600-series boards needs AGESA 1.2.0.0 or later; 9850X3D needs 1.2.8.0; 9950X3D2 needs 1.3.0.0a (all I-labelled)."
  - kind: external_fact
    subject: lga1954-lifespan
    source_url: https://en.wikipedia.org/wiki/LGA_1954
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "LGA1851 has no CPU upgrade path; LGA1954 (Nova Lake, 900-series) is expected Q1 2027."
  - kind: external_fact
    subject: zen7-socket
    source_url: https://www.techpowerup.com/351994/amd-confirms-am5-compatibility-with-olympic-ridge-desktop-zen-6
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Zen 6 is confirmed for AM5 (expected 2027); sources conflict on Zen 7 (AM5 vs AM6). Promise AM5 upgrades only as far as Zen 6."
  - kind: external_fact
    subject: nvidia-50-super-status
    source_url: https://www.nvidia.com/en-us/geforce/graphics-cards/compare/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "RTX 50 Super is unconfirmed and possibly cancelled; the gpu_tiers table does not list it."
  - kind: date_review
    subject: intel-arc-b770-status
    review_by: 2026-12-27
  - kind: external_fact
    subject: ddr5-gddr7-pricing-context
    source_url: https://dropreference.com/en/blog/news/shortage-ddr5-ram-global-status-july-2026
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "UK DDR5 about 4.95x its Sep 2025 level in July 2026 (peak 5.28x, March 2026). Re-check band edges and typical builds against it."
-->
