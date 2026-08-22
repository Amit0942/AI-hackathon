# ADR 0004: D4 (Impressions Optimizer) build scope and algorithm choice

## Status

Accepted

## Context

Phase 7 of `solution_plan.md` specifies four steps for D4: problem
formulation (7.1), the de-duplicated reach objective (7.2), joint bundle
pricing & allocation (7.3), and alternatives/sensitivity (7.4).
`src/agentiq/optimizer/` is currently an empty stub. D1 (audience/overlap/
reach — `docs/decisions` §10 of `HANDOFF.md`) and part of D3 (demand index,
price band, cold-start ladder — ADR-0003) are already built and tested; D2
(relevance scoring, Phase 5) is not yet built. Before writing any code,
several scope and dependency questions had no single correct answer
dictated by the plan, so they were decided explicitly rather than assumed —
same discipline as ADR-0003.

## Decisions

### 1. Scope: thin slice first — Steps 7.1 + 7.2 only

Build candidate generation + eligibility filtering (7.1) and the
de-duplicated, submodular reach-maximization objective under a budget
constraint (7.2) first, producing a real, invariant-checked `Package`.
Step 7.3 (bundle-level joint pricing across bus/metro/station as one deal)
and Step 7.4 (efficient-frontier variants — max-reach, best-value,
premium-quality, frequency-heavy — plus sensitivity analysis) are deferred
to a fast-follow pass.

**Why:** Matches ADR-0003 decision 1's reasoning exactly: a vertical slice
that produces a real `Package` end-to-end (with a correct, tested reach
objective and a hard budget constraint) is demoable and testable sooner
than a wide half-built pipeline. `Package.bundle_discount_pct` already
defaults to `0.0` on the domain type (Phase 2), so deferring 7.3 costs
nothing structurally — a real bundle discount slots in later with no
signature change, exactly like `PriceQuote.recommended == target` did for
D3 until 6.4 landed.

### 2. `relevance_score` dependency (D2 not built): optional input, neutral default

`PackageLine.relevance_score` is a **required** field on the domain type
(Phase 2) — there is no producer for it anywhere in the codebase today,
since `src/agentiq/relevance/__init__.py` is an empty stub. The optimizer
takes relevance scores as an **optional** `Mapping[str, RelevanceScore]`
parameter; any candidate with no entry is assigned `config/optimizer.yaml`'s
`neutral_relevance_score` (`1.0`), and every such default is recorded in
`Package.explanation.fallbacks_used` as
`relevance_score_defaulted_neutral_pending_D2`.

**Why:** Identical reasoning to ADR-0003 decision 6 (`segment_heat`'s
optional `IndustryVertical` parameter). This keeps D4 independently
buildable and unit-testable today, and lets D5 orchestration (or a direct
caller) pass real `RelevanceScore`s the moment D2 lands, with no signature
change — versus hardcoding `relevance_score=1.0` in the function body,
which would need touching again later. It also means `minimum_relevance_threshold`
from `CampaignBrief` is honoured today (defaulted candidates pass at 1.0
unless the brief's threshold exceeds it), rather than being unenforceable
until D2 exists.

### 2b. Relevance's role this pass: hard threshold gate only, not a weighted blend

Step 7.1 names relevance in two places: a **minimum threshold** ("never buy
cheap junk to inflate volume") and relevance "as a quality weight" on the
objective. This pass implements only the threshold
(`CampaignBrief.minimum_relevance_threshold`, enforced in
`optimizer/candidates.py::filter_eligible`) — the objective itself
maximizes de-duplicated reach unweighted by relevance among eligible
candidates.

**Why:** With every relevance score defaulted to a single neutral constant
today (decision 2), a "relevance-weighted reach" blend would be
mathematically indistinguishable from unweighted reach — implementing the
blend now would be untested against any real variation and could not be
verified to do anything until D2 exists. This is tracked as part of the
same fast-follow as 7.3/7.4, to be built once D2 supplies real,
differentiated scores worth weighting by.

### 3. Algorithm: cost-effective greedy + best-singleton comparison, not plain greedy

Implement the reach objective as **monotone submodular maximization under
a budget (knapsack) constraint**, solved by the standard two-candidate
comparison: (a) greedy selection by marginal-reach-gain-per-dollar until no
affordable candidate improves reach, and (b) the single best affordable
candidate alone — return whichever of the two has higher total reach.

**Why:** Plain greedy-by-ratio alone has no worst-case guarantee under a
budget constraint (a single very expensive, very high-reach candidate can
dominate the optimum while greedy fills the budget with many small ones).
Comparing against the best singleton and taking the max of the two is the
well-known fix that restores a **(1 − 1/e)/2 ≈ 0.316** approximation
guarantee for this exact problem class (monotone submodular maximization
subject to one knapsack constraint) — matching `solution_plan.md`'s "a
greedy/lazy-greedy algorithm gives a strong solution with a known
approximation guarantee" instruction precisely, rather than asserting a
guarantee the plain-greedy algorithm doesn't actually have. An exact
ILP/local-search "thorough" mode (the plan's other named strategy) is
deferred — Step 1.4's inventory-shape findings size the real post-filter
candidate count in the low thousands per brief, so greedy is not a
compute-forced choice yet, but building the exact path without a caller
that needs it would be speculative work this pass skips.

### 4. Reach objective scope: single time-block, single day-type per allocation

This pass optimizes reach for **one `time_block_id` and one `day_type`**
per `Package` (the brief's stated block preference, or a caller-supplied
default), reusing `AudienceProfileEngine.impressions_for` /
`reach_for` verbatim — Step 3.5's own docstring states these are "reusable
by D4's optimizer without modification," so no reach math is duplicated
here. Multi-block joint allocation (optimizing across several time blocks
in one pass, with cross-block frequency accumulation over the flight's
`duration_days`) is deferred.

**Why:** The true decision space is `screen × time_block × slot-count ×
date-range` (Step 7.1), but reach and overlap are proven per-time-block
constructs today (D1 computes a daypart-weighted *daily* exposure, not a
multi-day cumulative one). Building genuine multi-day frequency
accumulation now would mean inventing an audience-repeat-exposure model
that Step 3.5 does not yet supply — speculative complexity this pass
avoids per CLAUDE.md's "no half-finished implementations" guidance. A
single-block allocation is still a real, budget-constrained, de-duplicated
selection with a provable guarantee — a complete thin slice, not a stub.
Multi-block joint allocation is the natural Step 7.1 fast-follow once a
caller (D5, or a direct multi-block test) needs it.

### 5. Baselines are part of the deliverable, not just a demo aside

`optimizer/greedy.py` ships two named baseline strategies —
`cheapest_first` and `greedy_by_relevance` — alongside the submodular
selection, all operating on the same `Candidate`/`OverlapGraph` inputs.

**Why:** Step 7.2's exit criterion is explicitly comparative ("beats
greedy-by-relevance and beats cheapest-first on unique reach per dollar").
Building the baselines as real, callable functions (not prose in a demo
script) makes that comparison a property test, matching this repo's
testing convention (CLAUDE.md: "assert numeric invariants, never a spot
check").

### 6. Dependency note: cannot be integration-tested on every machine yet

`InMemoryRepositories.__init__` eagerly loads `bookings.csv`
(`InMemoryBookingRepository`'s constructor calls `compute_as_of_date`
immediately), and `PricingEngine.__init__` uses `repos.bookings` directly.
`bookings.csv` is a known, pre-existing gap (Step 1.1's data dictionary —
see `docs/data_dictionary.md` — and `HANDOFF.md` §2) that is **not present
on this machine's checkout**. As a direct consequence, `OptimizerEngine`
(the wiring layer, §Consequences below) cannot be constructed against real
data here today — not because of anything in this pass's code, but because
its two upstream dependencies (`AudienceProfileEngine`, `PricingEngine`)
both require `InMemoryRepositories`, which requires `bookings.csv`.

**Why this doesn't block this pass:** The core algorithm
(`optimizer/candidates.py`, `optimizer/greedy.py`) takes plain domain
objects (`Screen`, `RelevanceScore`, `PriceQuote`, `OverlapGraph`) and has
**zero** repository dependency — it is built and property-tested against
hand-constructed fixtures, the same pattern `audience/reach.py`'s own
property tests use. Only the thin wiring layer (`OptimizerEngine` in
`optimizer/__init__.py`, which generates candidates from real screens and
calls `AudienceProfileEngine`/`PricingEngine`) is blocked from a real
end-to-end run until `bookings.csv` is sourced. This is recorded here so it
is not rediscovered as a surprise, per this repo's own convention
(ADR-0003 §Consequences did the same for the `client_target_price` gap).

## Consequences

- `src/agentiq/optimizer/` exposes candidate generation, eligibility
  filtering, the cost-effective-greedy + best-singleton reach objective,
  two baseline strategies, and the `OptimizerEngine` wiring entrypoint —
  not bundle-level joint pricing (7.3) or the efficient-frontier/sensitivity
  output (7.4).
- `Package.bundle_discount_pct` is always `0.0` from this engine until 7.3
  lands; `Package.optimizer_guarantee` states the `(1-1/e)/2` figure
  precisely so no downstream caller overclaims it.
- Every `Package` this engine returns is for a single `time_block_id` /
  `day_type`; a caller wanting a multi-block flight-length recommendation
  must call it once per block and compose the results — tracked here as
  the Step 7.1 fast-follow, not silently assumed handled.
- `OptimizerEngine.allocate()` cannot be run end-to-end on a checkout
  missing `bookings.csv`; the pure algorithm layer can and is tested
  without it. Restoring `bookings.csv` unblocks integration testing with no
  code change required.
- Once D2 lands, real `RelevanceScore`s should be passed into
  `OptimizerEngine.allocate()`'s `relevance_scores` parameter — no
  signature change needed, matching decision 2.
