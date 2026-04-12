# Theme Taxonomy — V2Themes + CAMEO Codes for Founder Use Cases

The full GDELT V2Themes catalog has tens of thousands of codes. For founder-ideation and research
use cases, callers need a curated subset. This reference organizes the commonly useful themes by
industry and founder use case.

---

## Core Founder-Relevant V2Themes

### Economic — Tax, Regulation, Finance

| Theme | Use case |
|---|---|
| `ECON_TAXATION` | Tax policy changes, enforcement, loopholes — regulatory ideation fuel |
| `ECON_INTEREST_RATES` | Macro tightening/loosening cycles |
| `ECON_INFLATION` | Cost-of-living pressure — consumer pain signals |
| `ECON_WORLDCURRENCIES` | FX volatility — cross-border commerce ideation |
| `ECON_SUBSIDIES` | Government subsidy flows — grant ideation |
| `ECON_BANKRUPTCY` | Distressed asset signals |
| `ECON_TRADE` | Trade policy, tariffs, embargoes |
| `ECON_STOCKMARKET` | Market volatility events |

### Technology

| Theme | Use case |
|---|---|
| `TECH_ARTIFICIAL_INTELLIGENCE` | AI regulation, AI deployment events |
| `TECH_AUTOMATION` | Automation impact, job displacement, RPA adoption |
| `TECH_BIOTECH` | Biotech approvals, funding, controversies |
| `TECH_CYBER_ATTACK` | Cyber incidents (signal for security ideation) |
| `TECH_CYBER_DEFENSE` | Defensive cyber events |
| `TECH_CRYPTO_CURRENCY` | Crypto regulation, exchanges, adoption |
| `TECH_DRONE` | Drone regulation and deployment |
| `TECH_QUANTUM` | Quantum computing milestones |
| `TECH_SPACE` | Space launches, treaties, commerce |

### Regulatory / Legal

| Theme | Use case |
|---|---|
| `LEG_REGULATORY` | Regulatory change events (compliance ideation) |
| `LEG_LEGISLATION` | New laws and bills |
| `LEG_COURT` | Court rulings affecting industries |
| `LEG_ENFORCEMENT` | Enforcement actions (fines, bans) |
| `LEG_LAWSUIT` | Major lawsuits affecting markets |

### Labor / Workforce

| Theme | Use case |
|---|---|
| `LABOR_DISPUTE` | Union disputes, strikes |
| `LABOR_UNEMPLOYMENT` | Unemployment shifts — macro signal |
| `LABOR_RIGHTS` | Worker rights legislation |
| `LABOR_SAFETY` | Workplace safety incidents |
| `LABOR_CHILD_LABOR` | Supply chain risk signals |

### Energy / Environment

| Theme | Use case |
|---|---|
| `ENV_CLIMATE` | Climate policy and events |
| `ENV_DEFORESTATION` | Deforestation events (agritech / offset ideation) |
| `ENV_FOSSIL_FUELS` | Oil / gas / coal industry events |
| `ENV_RENEWABLE_ENERGY` | Renewable investment flows |
| `ENV_NUCLEAR` | Nuclear policy / incidents |
| `ENV_WATER` | Water scarcity / utility events |

### Healthcare

| Theme | Use case |
|---|---|
| `HEALTH_PANDEMIC` | Outbreak events |
| `HEALTH_DRUGS` | Drug approvals, controversies |
| `HEALTH_MENTAL_HEALTH` | Mental health policy / crises |
| `HEALTH_VACCINATION` | Vaccination campaigns / hesitancy |
| `HEALTH_ELDERLY` | Aging-related health events |
| `HEALTH_INSURANCE` | Insurance policy changes |
| `HEALTH_MATERNAL` | Maternal health events |

### Geopolitical

| Theme | Use case |
|---|---|
| `CONFLICT_WAR` | Active war zones |
| `TERROR_ATTACK` | Terror events |
| `SANCTIONS` | Sanctions events |
| `MIGRATION` | Migration flows |
| `TREATIES` | International agreements |

---

## CAMEO Event Codes — Founder Use Cases

CAMEO codes group events into 20 root categories (01 through 20), each with subcodes.

### Cooperative (01x-08x) — signals of activity

| Root | Description | Founder use case |
|---|---|---|
| `01` | Make public statement | Announcement tracking (launches, pivots, earnings) |
| `02` | Appeal | Demand / request signals |
| `03` | Express intent to cooperate | Deal-in-progress signals (LOIs, term sheets announced) |
| `04` | Consult | Due-diligence signals |
| `05` | Engage in diplomatic cooperation | Alliance signals |
| `06` | Engage in material cooperation | Deal-signed signals (M&A, partnerships) |
| `07` | Provide aid | Funding flows (grants, investments) |
| `08` | Yield | Concessions / policy changes |

### Escalatory (09x-20x) — signals of conflict / risk

| Root | Description | Founder use case |
|---|---|---|
| `09` | Investigate | Regulatory investigation signals |
| `10` | Demand | Escalating demands |
| `11` | Disapprove | Public pushback / boycotts |
| `12` | Reject | Rejection of offers / proposals |
| `13` | Threaten | Threat escalation |
| `14` | Protest | Protest events |
| `15` | Exhibit military posture | Mil positioning |
| `16` | Reduce relations | Relationship breakdown |
| `17` | Coerce | Coercion events |
| `18` | Assault | Physical violence |
| `19` | Fight | Combat events |
| `20` | Use unconventional mass violence | Terror / WMD events |

For founder-ideation, **codes 01x-08x** are the most relevant — they're signals of activity and
commerce. Codes 09x-14x are relevant for regulatory / risk / geopolitical-flavored ideation.

---

## Industry → Theme Mapping

When a founder-ideation caller passes a niche, map to V2Themes like this:

| Niche | Primary themes | Secondary themes |
|---|---|---|
| "small accounting firms" | `ECON_TAXATION`, `LEG_REGULATORY` | `ECON_INFLATION`, `TECH_AUTOMATION` |
| "healthcare SaaS" | `HEALTH_INSURANCE`, `LEG_REGULATORY` | `TECH_AI`, `HEALTH_PANDEMIC` |
| "climate tech / agritech" | `ENV_CLIMATE`, `ENV_DEFORESTATION`, `ECON_SUBSIDIES` | `ENV_WATER`, `TECH_DRONE` |
| "crypto / DeFi" | `TECH_CRYPTO_CURRENCY`, `LEG_REGULATORY` | `ECON_STOCKMARKET`, `LEG_ENFORCEMENT` |
| "labor / workforce tools" | `LABOR_RIGHTS`, `TECH_AUTOMATION` | `LABOR_DISPUTE`, `LABOR_UNEMPLOYMENT` |
| "cybersecurity" | `TECH_CYBER_ATTACK`, `TECH_CYBER_DEFENSE` | `LEG_REGULATORY`, `LEG_LAWSUIT` |
| "energy / renewables" | `ENV_RENEWABLE_ENERGY`, `ENV_FOSSIL_FUELS` | `ECON_SUBSIDIES`, `LEG_REGULATORY` |
| "AI infrastructure / tooling" | `TECH_AI`, `TECH_AUTOMATION` | `LEG_REGULATORY`, `ENV_CLIMATE` |
| "gig economy / labor platforms" | `LABOR_RIGHTS`, `LEG_REGULATORY` | `LABOR_DISPUTE`, `ECON_UNEMPLOYMENT` |

Callers are free to extend / override these mappings. The taxonomy is a curated starting point, not
an exhaustive catalog.

---

## How to get the full V2Themes list

```bash
curl -s http://data.gdeltproject.org/api/v2/guides/LOOKUP-GKGTHEMES.TXT | wc -l
# ~45,000 themes
```

The full list is too big to inline here. Cache locally, grep for relevant subsets per niche.
