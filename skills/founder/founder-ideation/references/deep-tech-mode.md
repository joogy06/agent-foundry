# Deep-Tech Mode — TRL / SRL / BRL Overlay for Inventor / Hardware Work

Activated via `deep_tech_mode: true` on any founder-ideation call. This reference documents the
overlay rules that add inventor-specific frameworks to the adversarial brainstorm teams.

**When it activates:** parent `founder` skill detects deep-tech intent during intake (keywords:
"inventor", "hardware", "patent", "manufacturing", "research spin-out", "I built a prototype in my
garage", "IP-heavy", biz_type in {hardware, deep-tech}) and passes `deep_tech_mode: true` to
founder-ideation.

---

## What changes when deep-tech mode is on

### 1. Mandatory additional output fields

Every idea from every team MUST include:

```yaml
deep_tech_addenda:
  ip_landscape:
    existing_patents: list[string]     # patent IDs or "unknown, needs search"
    freedom_to_operate_concerns: list[string]
    patent_strategy: string            # file / don't file / trade secret
  regulatory_triggers:
    regulators: list[string]           # FDA | FCC | CE | UKCA | ISO | NRC | EPA | ...
    certification_requirements: list[string]
    approval_timeline_estimate: string # "6-18 months" etc.
  dfm_considerations:
    manufacturability_risks: list[string]
    supply_chain_dependencies: list[string]
    unit_cost_estimate: string         # "needs DFM review with contract manufacturer"
  readiness_levels:
    trl: int                           # 0-9 Technology Readiness Level
    srl: int                           # 0-9 System Readiness Level
    brl: int                           # 0-9 Business Readiness Level
```

Teams that produce outputs without these fields are rejected and re-spawned with a corrective
prompt. Max 1 retry; on failure, drop the output.

### 2. First-principles team replaces one of the default four

Default quad becomes: `[problem-first, first-principles, trend-first, contrarian]` (asset-first
is dropped because deep-tech founders' asset is usually the invention itself, captured elsewhere).

`first-principles` is run on Codex (strong at constraint propagation).

### 3. GDELT theme overlay

In addition to the niche themes, GDELT mining adds:
- `TECH_*` themes relevant to the invention category (TECH_BIOTECH, TECH_QUANTUM, TECH_DRONE, etc.)
- `LEG_REGULATORY` (always — regulatory shifts often create or destroy deep-tech windows)

### 4. Arbiter adds a `deep_tech_concerns` section to its notes

Synthesizes:
- Which outputs have the weakest IP position
- Which outputs face the most regulatory uncertainty
- Which outputs have the longest time-to-market
- Which outputs have the highest capital intensity

---

## TRL (Technology Readiness Level)

Standard NASA/DoD scale. Ask the team to rate each output:

| TRL | Definition |
|---|---|
| 1 | Basic principles observed |
| 2 | Technology concept formulated |
| 3 | Experimental proof of concept |
| 4 | Technology validated in lab |
| 5 | Technology validated in relevant environment |
| 6 | Technology demonstrated in relevant environment |
| 7 | System prototype demonstrated in operational environment |
| 8 | System complete and qualified |
| 9 | Actual system proven in operational environment |

For founder-ideation, TRL 3-6 is the typical zone (you have a prototype, you've demonstrated it
works in some environment, you're figuring out whether it can become a business). TRL < 3 = too
early for commercial ideation, defer to research.

## SRL (System Readiness Level)

System integration with ecosystem readiness. Scale 1-9 with emphasis on integration, not just the
technology artifact:

1. Components identified
2. Components verified in isolation
3. Components integrated in lab
4. System validated in simulated environment
5. System validated in relevant environment with real users
6. System demonstrated in operational environment
7. System qualified through test and demonstration
8. Actual system completed and qualified
9. Actual system proven through successful mission operations

## BRL (Business Readiness Level)

Ecosystem of buyers, distribution, economics:

1. Customer problem identified
2. Initial value proposition
3. Customer problem validated with evidence
4. Solution validated with willing buyers
5. Business model validated at small scale
6. Business model demonstrated at commercial scale
7. Business established with repeatable sales
8. Mature business with steady growth
9. Dominant market position

For deep-tech founder-ideation, expect most ideas to be TRL 3-6 / SRL 2-4 / BRL 1-3. The lopsided
distribution (tech ahead of business) is the classic deep-tech trap.

---

## IP Landscape Questions

For each proposed deep-tech idea, teams must answer:

1. **Freedom to operate**: do you know who owns the adjacent patents? Have you done a
   freedom-to-operate search, even informally? If not, flag "FTO unknown" as a kill risk.
2. **Patentability**: is your core technology patentable? Have you published? (Publications can
   kill patent eligibility in some jurisdictions.)
3. **Trade secret vs patent**: would you be better off filing or keeping as trade secret? (Patent
   = 20 years monopoly + public disclosure; trade secret = indefinite but no protection if
   discovered.)
4. **Existing patents to license**: could you license rather than file fresh? Who holds the
   relevant portfolio?
5. **Defensive publication**: is this something where defensive publication (preventing others
   from patenting) is better than filing?
6. **Jurisdiction strategy**: where do you need IP protection? Filing is expensive.

Founder-ideation does NOT answer these. It only asks them and flags outputs where the answers
are "unknown" with higher risk.

Important: the founder family's HR-2 (no legal advice) applies. We can ask IP questions but we
cannot advise on patent strategy. That's a patent attorney's job.

## Regulatory Trigger Checklist

For each idea, check which regulators might care:

- **Medical devices / drugs**: FDA (US), MHRA (UK), EMA (EU), PMDA (Japan), NMPA (China)
- **Consumer electronics**: FCC (US), CE mark (EU), UKCA (UK), VCCI (Japan)
- **Food / supplements / cosmetics**: FDA, FSA (UK), EFSA (EU)
- **Automotive / aerospace**: NHTSA, FAA, EASA
- **Financial**: FinCEN (US), FCA (UK), BaFin (DE), securities regulators
- **Data / AI**: GDPR (EU), UK-GDPR, CCPA (California), EU AI Act, sectoral regulators
- **Energy**: FERC, Ofgem, EPA, state PUCs
- **Telecommunications**: FCC, Ofcom
- **Chemicals / environmental**: EPA, REACH (EU), ECHA
- **Cryptography / export controls**: BIS (US), Wassenaar
- **Crypto / DeFi**: SEC, CFTC, FCA, BaFin, sectoral regulators

For each relevant regulator, estimate:
- Certification timeline (months / years)
- Approval cost
- Post-approval obligations

Again — founder-ideation ASKS these questions, it doesn't answer them. Regulatory strategy needs
specialized counsel.

---

## DFM (Design for Manufacturability) Considerations

For hardware / manufactured-goods ideas:

1. **Material availability**: is your material readily sourced or bespoke?
2. **Manufacturing process**: does this fit into existing contract manufacturer capabilities or
   does it need custom tooling?
3. **Tolerances**: are your tolerances achievable at commercial scale or do they require
   hand-assembly?
4. **Supply chain**: single-source dependencies? Geopolitical supply risk?
5. **Unit cost estimate**: rough BOM + labor — can you sell at a margin?
6. **Scale factors**: unit cost at 100 units / 10k units / 1M units — where does it break even?
7. **Testability**: can you test at production without destructive methods?
8. **Certification compatibility**: does your design process produce the documentation regulators
   want (ISO 13485 for medical, etc.)?

Teams that skip DFM for hardware/deep-tech are dangerous — they produce ideas that can't actually
ship. The arbiter specifically checks for DFM presence in deep-tech mode.

---

## Example deep-tech output

```yaml
content: "Low-cost open-source bioreactor for university microbiology labs, replacing $15k sealed units with a $2k modular open-source design"
source_team: first-principles
confidence: speculative
kill_criteria:
  - "Fails if FDA / EPA / IBC (Institutional Biosafety Committee) blocks use in teaching labs"
  - "Fails if contamination rate exceeds 5% at open-source hardware quality levels"
  - "Fails if the $2k BOM doesn't survive first DFM review"
first_experiment: "Partner with 1 university microbiology PI to pilot a single unit over one semester; measure contamination rate, teaching efficacy, and failure modes"
data_sources:
  - "reddit:r/labrats/post_xyz (pain: $15k sealed units block teaching labs)"
  - "gdelt:1234567890 (inflection: university STEM budget cuts)"
deep_tech_addenda:
  ip_landscape:
    existing_patents:
      - "US9876543 — proprietary stirred-tank bioreactor control"
      - "EP3456789 — sterilization protocol (expired 2021)"
    freedom_to_operate_concerns:
      - "US9876543 claims control algorithm; open-source alternative needed"
    patent_strategy: "Defensive publication of open-source design; no filing"
  regulatory_triggers:
    regulators: ["IBC (university-level)", "OSHA (if used in teaching)"]
    certification_requirements:
      - "Institutional Biosafety Committee approval per institution"
      - "No FDA pathway if not used clinically"
    approval_timeline_estimate: "3-6 months per institution"
  dfm_considerations:
    manufacturability_risks:
      - "Peristaltic pump reliability at low unit cost — key DFM challenge"
      - "Sterilization cycle timing — user safety risk if shortcuts"
    supply_chain_dependencies:
      - "Silicone tubing (commodity, low risk)"
      - "Thermistors (commodity)"
      - "Stepper motors (commodity)"
    unit_cost_estimate: "$1800-2200 BOM at low volume; $1200-1500 at 1000+ units/yr"
  readiness_levels:
    trl: 4    # tech validated in lab
    srl: 3    # components integrated in lab
    brl: 2    # initial value prop, not yet validated with buyers
```

---

## Limits

Deep-tech mode still refuses:
- Patent strategy advice (HR-2 — legal)
- Regulatory approval advice (HR-2)
- Specific contract manufacturer recommendations (can point at categories, not vendors)
- Unit cost estimates with high precision (LLMs are bad at this; call out as estimate)
- Capital requirement estimates for tooling / facilities (varies enormously)

Deep-tech founders need specialized counsel — patent attorneys, regulatory consultants, contract
manufacturers. Founder-ideation's job is to help them frame the questions before spending on the
specialists, not to replace the specialists.
