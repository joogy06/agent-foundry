# Business Idea Prompts — Templates per biz_type

Prompt templates for the `generate_ideas` mode, adapted per `biz_type`. Each biz_type has
different idea-shape conventions. These are the defaults; callers can override.

---

## software

```
Generate {N} software business ideas for {NICHE}.

Each idea should be:
- A specific product (name it, describe in 1-2 sentences)
- Addressing a concrete pain (ideally cited from the attached Reddit data)
- With a clear "who pays and how much" — e.g. "accounting practice at £80/mo/seat"
- With a realistic MVP scope — what can be built in 4-8 weeks by 1-2 people

Avoid:
- Me-too SaaS ("Better Salesforce for X")
- Ideas that require enterprise sales to start (start with bottom-up or PLG motion)
- Features without a product around them
- AI-for-X where AI is the product instead of the mechanism

Default output structure:
{
  "product_name": "...",
  "one_liner": "...",
  "pain_addressed": "... (cite source)",
  "who_pays": "...",
  "pricing": "...",
  "mvp_scope": "...",
  "first_distribution_channel": "..."
}
```

---

## service

```
Generate {N} service-business ideas for {NICHE}.

A "service business" is one where the user personally delivers value for time/retainer/hourly
fees — consulting, implementation, fractional, agency, coaching. Not productized unless the
productization is the specific idea.

Each idea should be:
- A specific service offering (name the deliverable)
- Leveraging the user's specific assets (from venture-brief)
- With a clear rate / retainer structure
- With a realistic first-client path

Avoid:
- "Consulting on X" without a specific deliverable
- Services that require certifications / licenses the user doesn't have
- Services in categories with crushing competition (unless the contrarian angle is strong)
- Ideas that look like "become a freelancer"

Default output structure:
{
  "service_name": "...",
  "deliverable": "...",
  "target_client": "...",
  "engagement_shape": "retainer | project | hourly | package",
  "rate_or_fee": "...",
  "first_client_path": "how user gets their first paying client",
  "scaling_barrier": "what stops this from being a 2-person business"
}
```

---

## marketplace

```
Generate {N} marketplace / two-sided business ideas for {NICHE}.

A marketplace connects two (or more) distinct user populations. Hard to bootstrap, hard to
monetize early. Be honest about which side is hard to acquire.

Each idea should:
- Name both sides explicitly (e.g. "side A: small accounting practices; side B: freelance
  bookkeepers")
- Identify the hard side (usually supply, sometimes demand)
- Propose a bootstrap strategy for the hard side
- Identify the monetization point (transaction fee / subscription / listing / ads)

Avoid:
- Generic "Uber for X" without a specific pain
- Ideas that require network effects before any value exists
- Ideas where one side is so weakly motivated they won't show up
- Platforms where the actual transaction happens off-platform (no capture)

Default output structure:
{
  "product_name": "...",
  "side_a": "...",
  "side_b": "...",
  "hard_side": "a | b",
  "bootstrap_strategy_for_hard_side": "...",
  "monetization": "...",
  "defensibility_once_both_sides_present": "..."
}
```

---

## hardware

Activates deep-tech mode by default. See `deep-tech-mode.md` for the full overlay.

```
Generate {N} hardware product ideas for {NICHE}.

Each idea must include:
- Physical product description
- Target customer + willingness to pay
- Unit cost estimate (rough BOM + labor)
- Scale factors (cost at 100 / 10k / 1M units)
- Manufacturing complexity (off-the-shelf parts vs custom tooling)
- Regulatory triggers (FCC, CE, UKCA, FDA, etc.)
- TRL / SRL / BRL assessment
- IP landscape (known patents, FTO risk)

Avoid:
- Ideas requiring > $5M tooling to start
- Ideas with medical / FDA approval path (unless user is already on it)
- Ideas with < $50 margin unless volume is extremely high
- "Better [commodity]" without a wedge
```

---

## deep-tech

Same as hardware, but emphasis on the invention itself:

```
Generate {N} commercialization paths for {NICHE} deep-tech research/invention.

The user has invented something (or is close). The question is: what business wraps it?

Each idea must include:
- The commercialization wrapper (product / licensing / consulting / spin-out / acquire-target)
- The first 3 customers (specific)
- TRL / SRL / BRL assessment
- IP landscape
- Regulatory path (if any)
- Capital requirement estimate (rough)
- Time to first revenue

Default output structure:
{
  "wrapper": "product | license | consulting | spin-out | acquire-target",
  "first_customers": ["...", "...", "..."],
  "trl_srl_brl": {...},
  "ip_landscape": {...},
  "regulatory_path": "...",
  "capital_requirement": "$X (rough)",
  "time_to_first_revenue": "N months"
}
```

---

## physical-retail

```
Generate {N} physical-retail business ideas for {NICHE}.

Physical retail = bricks-and-mortar, pop-up, stall, or hybrid with online component. High fixed
costs, tight margins, location-dependent.

Each idea should:
- Name the specific location type (high street, mall, specialist, near campus, etc.)
- Identify inventory / sourcing strategy
- Estimate fit-out cost and rent range
- Identify day-one cash-flow plan
- Identify the online complement (if any — most modern physical retail has one)

Avoid:
- Ideas with negative unit economics at any reasonable footfall
- Ideas that require > 6 months to first revenue without funding
- Ideas in categories being gutted by e-commerce (unless the counter-positioning is structural)

Default output structure:
{
  "product_name": "...",
  "location_type": "...",
  "inventory_source": "...",
  "fit_out_estimate": "...",
  "rent_range": "...",
  "day_one_plan": "...",
  "online_complement": "..."
}
```

---

## other

```
Generate {N} business ideas for {NICHE}.

The user's biz_type didn't map to one of the standard categories (software / service /
marketplace / hardware / deep-tech / physical-retail). Ask the user to clarify if ambiguous,
otherwise use this generic template:

Each idea should be:
- A specific offering (product or service — name it)
- Addressing a concrete pain with citation
- With a "who pays and how much"
- With a realistic first-customer path

Default output structure:
{
  "offering_name": "...",
  "one_liner": "...",
  "pain_addressed": "...",
  "who_pays": "...",
  "first_customer_path": "..."
}
```

---

## Universal rules

Regardless of biz_type:

1. **Every idea needs ≥2 kill criteria** — this is HR-4 from the founder family
2. **Every idea needs a first experiment** — HR-4 again
3. **Every idea needs a data source citation** — HR-5
4. **No LLM-generated TAM / valuation** — HR-3
5. **No legal / regulatory advice** — HR-2 — deep-tech can reference regulators but cannot advise
   on strategy
6. **Confidence capped at `speculative`** unless data grounding is present — arbiter enforces

These are injected into the spawn prompt by the adversarial-team-brainstorm primitive, not by
these biz_type-specific templates. The templates here are for idea SHAPE. The hard rules are for
idea DISCIPLINE.
