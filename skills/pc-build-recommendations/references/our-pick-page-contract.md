# "Our pick" page contract

The output contract for a recommended-build page, enforced by
`pc-builder/scripts/pc_check.py PAGE.json --publish-gate`. The page data is an `our-pick.v1` object
(`pc-builder/schemas/our-pick.v1.json`, validated strictly). Only exit 0 is published: exit 2 lists
`publish_blockers`, exit 3 is malformed input.

## How the gate decides

1. The embedded `build` is re-checked with `--final`. Its findings are never trusted from the page.
   - A HARD finding blocks (`PUB_CHECK_HARD`).
   - A HARD check that could not run blocks (`PUB_CHECK_INCOMPLETE`).
   - Any other "cannot check" finding blocks (`PUB_CANNOT_CHECK`). **A published compatibility claim may
     disclose genuine WARNs, but never "cannot check" findings**: an unchecked rule is not a checked one.
   - Every genuine WARN must be listed in `disclosed_warnings` and shown on the page (`PUB_UNDISCLOSED_WARN`).
2. Pricing (CMA209 3.3 and 4.4; DMCC drip pricing):
   - `line_items` and `mandatory_charges` must be present, each with `source: "db"`: read from the database
     at generation time (`PUB_MISSING_PRICING`, `PUB_LINE_ITEM_SOURCE`). `mandatory_charges` is an empty
     list only when there genuinely are none.
   - The gate **recomputes** the total: line items x quantity + every mandatory charge. It must equal
     `headline_total_gbp_inc_vat` (`PUB_TOTAL_MISMATCH`), with `vat_inclusive: true` (`PUB_NOT_VAT_INCLUSIVE`).
   - `priced_at` must be a real date, not in the future, and no older than `--max-price-age-days`
     (default 7; set it to the repricing cycle) (`PUB_PRICE_DATE`).
   - The total must sit inside the page's `band` (`PUB_BAND`).
3. Content: `use_case`, `band`, `workload`, `headline`, `performance_class` and `upgrade_path` are
   non-empty (`PUB_REQUIRED_FIELD`); `exclusions` include "operating system" and "monitor" (`PUB_EXCLUSIONS`).
4. Claims (CAP Code section 3):
   - `selection_criteria` with an ISO `as_of` date and at least one criterion: the documentary basis for
     calling this build "our pick" (CAP 3.7) (`PUB_SELECTION_CRITERIA`). The label itself is not a safe
     harbour.
   - A superlative in the headline or performance class ("best", "fastest", "cheapest", "number one",
     "unbeatable") needs `superlative_evidence` with a date and a source (CAP 3.7) (`PUB_SUPERLATIVE`).
   - A comparison with named competitors must compare products meeting the same need (CAP 3.33) on
     material, relevant, verifiable and representative features (CAP 3.34). The gate cannot judge this;
     a person must.

## Page sections

| Section | Content | Page field |
|---|---|---|
| Headline | Use case + band + "our pick"; no unsupported superlative | `headline` |
| Headline price | Total, VAT-inclusive, every mandatory charge included, "prices as of <date>" | `headline_total_gbp_inc_vat`, `priced_at` |
| Parts list | One row per part: role, why this one | `line_items[].role`, `.why` |
| Compatibility | "Checked: socket, memory type, BIOS support, PCIe link, display output, physical fit, power." Only from a clean `--final` run; list disclosed WARNs | `disclosed_warnings` |
| Performance | A performance class. FPS only with game, resolution, preset, upscaling/frame generation, driver, date and source | `performance_class` |
| Power and cooling | PSU size vs `recommended_psu_w` and the quality basis; cooler class vs CPU power | build |
| Upgrade path | Socket horizon (LGA1851: no CPU upgrade path; AM5: upgrades promised only to Zen 6), PSU headroom, free slots | `upgrade_path` |
| What you don't need to pay for | The upsells this build deliberately skips, and why | `skip` |
| Not included | "Operating system and monitor are not included." | `exclusions` |
| Selection basis | Dated criteria (internal evidence file; may also be shown) | `selection_criteria` |
| Reviews | Only genuine, traceable reviews (DMCC fake-review ban) | outside the gate |

## Wording rules

- Performance: "performance class", never a bare FPS number.
- Cases: "mesh is quieter at the same temperature", never "mesh is quieter".
- PSU: size to the recommendation (maker minimum and DC/0.80); never upsell wattage as a quality signal.
- AI: never recommend IPEX-LLM or IPEX; say "ROCm on Windows is partial".
- Label inference as judgement ("we recommend"), not as vendor fact.

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: cma209-price-transparency
    source_url: https://assets.publishing.service.gov.uk/media/698f4e3e7da91680ad7f4417/CMA209_Unfair_commercial_practices__price_transparency_13.2.26.pdf
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Headline prices include all mandatory charges (3.3); VAT and unavoidable fees are mandatory charges (4.4)."
  - kind: external_fact
    subject: cap-code-substantiation-and-comparisons
    source_url: https://www.asa.org.uk/type/non_broadcast/code_section/03.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "CAP 3.7 substantiation; 3.33 same-need comparisons; 3.34 objective, verifiable comparisons."
-->
