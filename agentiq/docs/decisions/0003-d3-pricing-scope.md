# ADR 0003: D3 (Demand Forecasting & Pricing) build scope and model choices

## Status

Accepted

## Context

Phase 6 of `solution_plan.md` specifies six steps for D3: demand intensity
index (6.1), expected-footfall forecast (6.2), price band construction
(6.3), recommended optimal price via win-probability (6.4), cold-start
fallback ladder (6.5), and human-in-the-loop overrides (6.6). `src/agentiq/pricing/`
is currently an empty stub. Step 1.5 (`docs/decisions/1.5_demand_profile.md`)
already supplies the empirical grounding this phase needs: ranked price
drivers, the `screen_type × slot_count` confound, the price-gap survival
curve, and the competitor/recency signals. Before writing any code, several
scope and modelling questions had no single correct answer dictated by the
plan or the data, so they were decided explicitly with the user rather than
assumed.

## Decisions

### 1. Scope: thin slice first, not all six steps at once

Build Steps **6.1 (demand index) + 6.3 (price band) + 6.5 (cold-start
ladder)** first, producing a working, testable `PriceQuote`. Steps 6.2
(footfall forecast), 6.4 (win-probability recommended price), and 6.6
(human overrides) are deferred to a fast-follow pass.

**Why:** A vertical slice that produces a real, invariant-checked
`PriceQuote` end-to-end is demoable and testable sooner than a wide
half-built pipeline. It also matches design principle 6 (graceful
degradation is designed) — the floor/target/cap band with a cited
cold-start rung is already a defensible, explainable output without the
optimizer layer on top. Risk: `recommended` will initially equal `target`
(no win-probability optimisation yet) until 6.4 lands.

### 2. Base-rate model: regularised linear regression with interaction terms

Use ElasticNet/Ridge over `city_id, screen_type, screen_size,
time_block_id, rotation_type, slots_booked_per_day`, with explicit
`screen_type × slots_booked_per_day` interaction terms, over a GBM+SHAP
approach or a pure stratified-median lookup table.

**Why:** The `Explanation` contract (ADR via `domain/explanation.py`)
requires every price to cite per-signal `Contribution`s with a direction
and magnitude — a linear model's coefficients map onto this directly and
losslessly. 1.5 §2 and §5 show effect sizes and a confound, not a
non-linearity severe enough to justify GBM's extra dependency and SHAP
compute cost for a hackathon timeline. A pure median lookup was rejected
because it can't interpolate sparse cells and duplicates the cold-start
ladder's own cohort logic (Step 6.5) rather than complementing it.

### 3. `screen_type × slot_count` interaction: full categorical interaction, not per-type models

Encode as one-hot `screen_type` × continuous `slots_booked_per_day`
product terms inside a single model, rather than fitting four independent
per-screen-type models.

**Why:** 1.5 §5.2 measured this exactly as a 24-cell
(`screen_type × time_block_id`) slope table — `bus` and `metro_station`
show a real discount, `bus_stop` inverts it. A single model with explicit
interaction terms reproduces this directly while still sharing sample
efficiency across screen types for the other coefficients (`city_id`,
`time_block_id`, etc.). Four separate models would waste data on
coefficients that don't actually vary by screen type.

### 4. Win-probability model (Step 6.4, deferred): logistic regression, not a bucket lookup

When built, `P(win | price_gap, competitor_mentioned, client_tier)` will be
a fitted logistic regression on `lost_leads` outcomes, not a step function
off the six price-gap buckets in 1.5 §6.2.

**Why:** Step 6.4 needs `argmax(price × P(win))`, which requires a smooth,
differentiable-enough curve to optimise over. A step function from six
buckets is coarser and creates flat regions with no useful gradient for
the argmax search. Logistic regression closely tracks the empirical
survival curve (40–48% up to 15% gap, collapsing above) while remaining
smoothly optimisable and just as auditable (coefficients are still
inspectable, unlike a black-box classifier).

### 5. Price-gap definition at generation time (Step 6.4, deferred): relative to client target price

`gap = (recommended - client_target_price) / client_target_price`,
matching `lost_leads.price_gap_pct`'s own definition exactly, rather than
gap relative to the model's own base rate.

**Why:** The logistic model in decision 4 will be fit on `lost_leads`,
where `price_gap_pct` is defined relative to `client_target_price_per_slot_per_day`.
Reusing the same reference point means the fitted model applies unchanged
at prediction time. The alternative (gap relative to base rate) is a
different quantity than what any model would be trained on and would
require refitting or a reinterpretation step for no clear benefit.

**Consequence:** this introduces a **new required input**,
`client_target_price`, into `PriceQuote` generation once Step 6.4 is
built — no such input exists in `data/repositories.py` today. Resolved in
decision 8: the input is *optional*, mirroring decision 6's pattern, so it
never blocked 6.1/6.3/6.5 and does not block 6.4 either.

**Consequence (amended 2026-08-21) — the Step 6.3 cap uses a different
reference point, and this must not be glossed over.** 1.5 §6.2 measures the
survival collapse as a gap over `client_target_price_per_slot_per_day`. But
Step 6.3's `compute_cap()` runs before any client-target input exists, so it
applies `cap_price_gap_pct` relative to **our own base rate** instead. These
are different quantities: a 15% premium over our modelled base rate is not
the same thing as a 15% premium over what a specific client wanted to pay.

Two things follow, both now done rather than left implicit:

1. `config/pricing.yaml`'s `cap_price_gap_pct` was **0.35** while the file
   header still read "placeholders until Steps 1.5/6.3 calibrate them" —
   i.e. 1.5 delivered the calibration (10–15%) and the config was never
   updated. A cap at +35% sat inside the measured dead zone (>20% gap →
   3.5% survival), which directly undercut the deliverable: the problem
   statement's challenge #1 is "no floor, no cap, no guardrails," and the
   strongest claim D3 has is that its cap is *measured, not invented*. It is
   now **0.15**, the last gap 1.5 §6.2's evidence supports.
2. The reference-point mismatch is a **stated approximation**, surfaced in
   every quote's `Explanation.fallbacks_used` as
   `cap_relative_to_base_rate_not_client_target`, not buried in a docstring.
   Step 6.4 (decision 8) narrows this: where a `client_target_price` *is*
   supplied, the win-probability model uses the correct client-relative gap,
   and the quote says so.

**Further amendment (2026-08-21, same day) — one constant cannot serve both
reference points; the Phase 6 exit-criteria back-test proved it.** Running
the back-test (`pricing/backtest.py`) with the single 0.15 figure applied to
the base-rate reference point (the only one live today, since no caller
supplies `client_target_price` yet) gave **65.9% band coverage, with 24.4%
of held-out realised prices landing above cap**. Diagnosis: the base-rate
model has R²=0.62 with **$22.59 residual std** on held-out data — price
varies around the model's prediction for reasons the model doesn't capture,
which is a different and *larger* source of uncertainty than "how far a
client will negotiate" (1.5 §6.2's basis for 0.15). Applying the
client-negotiation figure to the model-uncertainty problem was a category
error, not a rounding issue — relative residuals `(realised/predicted − 1)`
run p75=+14.3%, p80=+20.6%, p85=+27.5%, p90=+35.7%, so 0.15 sat at only the
p76 of the very distribution it was being asked to bound.

**Resolution: two named constants, one per reference point**, replacing the
single `cap_price_gap_pct`:

- `cap_gap_pct_vs_client_target = 0.15` — used when `client_target_price` is
  supplied (Step 6.4). Unchanged; this is exactly what 1.5 §6.2 measured.
- `cap_gap_pct_vs_base_rate = 0.35` — used otherwise (today's default path).
  Fit as the **p90 of train-split relative residuals**, chosen over p85
  (rejects 15% of real historical deals as "impossible," too aggressive for
  a guardrail meant to describe the market) or p95 (lets through so much
  that the cap stops doing guardrail work). Validated out-of-sample: applying
  the train-fit p90 cap to the held-out split gives a 10.2% above-cap rate,
  matching the ~10% implied by construction — no material overfitting.

Re-running the back-test with both constants live: **79.9% coverage (9.7%
below floor, 10.4% above cap)** — the honest number for the exit criterion,
superseding the 65.9% figure above, which was measuring a config mismatch
rather than the pricing model's real accuracy.

This is not a case of "tuning until coverage looks good" — the discipline
was to name what each cap's dispersion actually represents (client
negotiation vs. model residual) and measure that specific thing, the same
way 1.5 §6.2 measured the client-gap figure from deal-survival curves rather
than picking a round number.

### 6. `segment_heat` / industry-vertical dependency (Step 6.1): optional parameter, not a hardcoded stub

`DemandSignal` computation accepts an optional `IndustryVertical`
parameter; `segment_heat` defaults to a neutral `1.0` multiplier when
`None` is passed, rather than hardcoding `segment_heat = 1.0`
unconditionally in the function body.

**Why:** Step 6.1's `segment_heat` is defined as "recent demand from the
brief's industry vertical," but D2/brief-intake (Phases 4–5, which would
supply `CampaignBrief.industry_vertical`) don't exist yet. Making it an
optional parameter with a neutral default keeps D3 independently buildable
and unit-testable today, and lets D5 orchestration pass a real value later
with no signature change — versus a hardcoded stub, which would require
touching this function again when brief intake lands.

### 7. Step 6.6 (human overrides): deferred until D6/API exists

`PriceQuote.human_overrides` already exists as a field on the domain type
(Phase 2). The *consumption* logic — a pure function that adjusts the band
given a rep-supplied override — will be built when 6.6 is picked up. No API
endpoint or UI stub is created now.

**Why:** D6 (API/UI, Phase 9) is not scaffolded yet, so there is no caller
for an override endpoint. Building the pure adjustment function without a
caller would be untested, speculative code (violates the "no half-finished
implementations" and "don't design for hypothetical future requirements"
guidance) — better to build it against the real API shape once D6 exists.

## Consequences

- `src/agentiq/pricing/` will initially expose demand-index computation,
  base-rate fitting, price-band construction, and the cold-start ladder —
  not a full recommended-price optimiser or override handling.
- `recommended` will temporarily equal `target` until Step 6.4 lands; this
  is a known, stated gap, not a silent shortcut.
- Implementing Step 6.4 later requires adding a `client_target_price`
  input path that does not exist yet — tracked here so it isn't rediscovered
  as a surprise.
- Carried forward in `HANDOFF.md` §8 for narrative context; this ADR is the
  durable record of *why*.
