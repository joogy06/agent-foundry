# PSU worked examples

Policy (revised 2026-09-27, no overkill): `recommended = smallest stocked size >= max(DC/0.80,
gpu.min_system_psu_w)`; HARD below `DC/0.90` or below the maker minimum; WARN below `DC/0.80`;
`DC/0.70` is an optional quiet target (INFO). Default catalog: `550, 650, 750, 850, 1000, 1200, 1300,
1500, 1600`. Vendor minimums are the card maker's figures (they assume a 9950X-class CPU [V]).
`tests/test_revise.py` asserts the four rows the retailer relies on.

| Combo | DC | DC/0.90 (HARD below) | DC/0.80 | Vendor minimum | Recommended | Quiet target DC/0.70 |
|---|---|---|---|---|---|---|
| 9600X + 5060 | 308 | 342 | 385 | 550 | **550** | 440 |
| 9800X3D + 5070 | 487 | 541 | 609 | 650 | **650** | 696 |
| 9800X3D + 5070 Ti | 537 | 597 | 671 | 750 | **750** | 767 |
| 9800X3D + 9070 XT OC | 571 | 635 | 714 | 750 | **750** | 816 |
| 9800X3D + 5080 | 597 | 663 | 746 | 850 | **850** | 853 |
| 265K + 5080 | 685 | 761 | 856 | 850 | **1000** | 979 |
| 9950X + 5090 | 880 | 978 | 1100 | 1000 | **1200** | 1257 |

How to read it:

- **9950X + 5090:** 230 + 575 + 75 = 880 W. An earlier version of the research table printed 905 W; that
  was an arithmetic error, corrected 2026-09-27. Size from the card's own TBP field in the caller's
  database.
- **9800X3D + 5080 on 850 W:** passes (above DC/0.80 and at NVIDIA's minimum). The quiet target of 853 W
  is reported as INFO only; nobody should be sold a 1000 W unit for it.
- **265K + 5080:** DC/0.80 is 856 W, just above 850, so the smallest stocked size is 1000 W. An 850 W
  unit is a WARN (above 90% is where it turns HARD: 761 W), not a failure.
- Vendor minimums without an entry in the database simply do not apply; the DC/0.80 floor still does.

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: nvidia-rtx-5080-5090-psu-and-connector-guidance
    source_url: https://www.nvidia.com/content/geforce-gtx/GeForce_RTX_5080_User_Guide_Rev1.pdf
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "Vendor minimum column: RTX 5080 FE 850 W, RTX 5090 FE 1000 W (geforce-rtx-5090-user-guide-r2.pdf); other rows use the research's vendor figures."
  - kind: external_fact
    subject: gpu-tbp-figures
    source_url: https://www.nvidia.com/en-us/geforce/graphics-cards/compare/
    verified_on: 2026-09-27
    review_by: 2026-12-27
    claim: "DC column uses TBP 5060 145 W, 5070 250 W, 5070 Ti 300 W, 5080 360 W, 5090 575 W; RX 9070 XT 304 W."
-->
