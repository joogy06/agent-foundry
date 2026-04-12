# Pricing Sensitivity

Pricing analysis methods adapted for pre-product founders. Covers value-based pricing,
competitive anchoring, Van Westendorp PSM (adapted for LLM context), and scenario generation.

---

## Value-Based Pricing

**Principle:** price based on the value you create, not the cost to produce.

### The Value Calculation

```
Value_to_customer = Cost_of_problem * Frequency * Time_saved_fraction

Example:
  Cost_of_problem: UK accountant billing £75/hr spends 12 hrs/month on FX reconciliation = £900/month
  Your tool saves 80% of that time
  Value_to_customer = £900 * 0.80 = £720/month
  
  Pricing at 10-20% of value created = £72-144/month
  Pricing at 5-10% of value created = £36-72/month (penetration)
```

**Formula:**
```
Value_ceiling = cost_of_problem_per_period * efficiency_gain_fraction
Price_range = Value_ceiling * capture_fraction (typically 5-20%)
```

### Capture Fraction by Stage

| Stage | Typical capture | Rationale |
|---|---|---|
| Pre-product (unknown brand) | 5-10% | Must win on price to overcome risk |
| Post-MVP (some traction) | 10-15% | Proven value, some social proof |
| Established (brand known) | 15-25% | Trusted, switching costs built |
| Market leader | 20-40% | Pricing power from dominance |

---

## Competitive Anchoring

Position relative to competitors. Requires user-supplied competitive data.

### Framework

```yaml
competitive_analysis:
  competitors:
    - name: string
      price: float
      features: list[string]
      positioning: string      # premium | mid-market | budget
  your_positioning: enum       # premium | mid-market | budget | niche-specialist
  price_rationale: string      # why your price is above/below/at parity
```

### Positioning Strategies

| Strategy | Price relative to competitors | When to use |
|---|---|---|
| Premium | 1.5-3x highest competitor | Clear differentiation, strong value prop, target is not price-sensitive |
| Parity | Within 20% of competitors | Similar offering, competing on UX/integration/support |
| Penetration | 50-70% of lowest competitor | New entrant, need market share, plan to raise later |
| Niche specialist | 2-5x average, for narrow segment | Deep expertise in underserved vertical |

---

## Van Westendorp PSM (Adapted for LLM Context)

The classic Van Westendorp Price Sensitivity Meter asks four questions to find the optimal
price range. In founder context, these are questions the user asks their CUSTOMERS (not
questions the LLM answers):

### The Four Questions

```
1. "At what price would you consider this TOO EXPENSIVE to consider?"
   → Upper bound of acceptable range

2. "At what price would you start to think it's getting EXPENSIVE but still consider it?"
   → Indifference point (upper end)

3. "At what price would you think it's a BARGAIN — a great deal?"
   → Indifference point (lower end)

4. "At what price would you think it's SO CHEAP you'd question the quality?"
   → Lower bound of acceptable range
```

### Interpreting Results

```
Too Cheap -------- Bargain -------- Expensive -------- Too Expensive
    |                 |                 |                    |
    |    [ACCEPTABLE RANGE]            |                    |
    |                 |                 |                    |
    |           [OPTIMAL PRICE POINT]  |                    |
```

- **Acceptable range:** between "bargain" and "expensive" (where most customers are comfortable)
- **Optimal price point:** where "too cheap" and "too expensive" curves cross
- **Point of marginal cheapness:** where "too cheap" and "bargain" cross
- **Point of marginal expensiveness:** where "too expensive" and "expensive" cross

### LLM Adaptation

The LLM does NOT answer these questions. The LLM:
1. Tells the user WHAT to ask their customers
2. Provides the framework for interpreting the answers
3. Computes the optimal range from user-reported data

If the user has not asked their customers yet: produce the question script and explain how
to interpret the results. Do NOT fabricate price sensitivity data.

---

## Pricing Scenario Generation

For each pricing strategy, compute:

```yaml
scenario:
  name: string                 # "penetration" / "value_based" / "competitive" / "premium"
  price: float
  rationale: string            # why this price for this strategy
  contribution_margin: float   # price - COGS
  break_even_customers: int    # fixed_costs / CM (if fixed costs known)
  monthly_revenue_at_N:        # revenue at 10, 50, 100, 500 customers
    - customers: 10
      revenue: float
      cm_total: float
    - customers: 50
      revenue: float
      cm_total: float
  trade_offs: string           # what you gain and lose at this price
  risk: string                 # what could go wrong
```

### Scenario Selection Guidance

| User's situation | Recommended scenario | Reasoning |
|---|---|---|
| Unknown brand, new market | Penetration | Need to overcome trust barrier |
| Clear differentiation, proven value | Value-based | Capture fair share of value created |
| Crowded market, similar offerings | Competitive (parity or slight discount) | Compete on other dimensions |
| Deep vertical expertise | Niche specialist (premium) | Underserved segment pays more |
| Solo bootstrapper, need revenue fast | Penetration with path to value-based | Get paying customers, then raise price |

---

## Price Testing Protocol

After analysis, guide the user on how to test pricing:

1. **Interview-based testing:** ask Van Westendorp questions during Mom Test interviews
2. **Landing page A/B:** show different prices to different traffic segments
3. **Tiered testing:** offer a free trial at premium price; measure conversion
4. **Pre-order testing:** the strongest signal — will someone actually pay this amount?

Each method feeds back into `founder-validation` evidence capture.
