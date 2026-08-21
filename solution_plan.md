# Solution Plan — Hack Days 2026: The AgentIQ Frontier

**Project codename:** `AgentIQ` — Urban Media Commercial Intelligence Platform
**Source of truth:** [Hack Days 2026 Problem Statement.md](Hack%20Days%202026%20Problem%20Statement.md)
**Status:** Plan — no implementation started

---

## 0. How to read this document

This is a **step-wise build plan**, ordered so that every step produces something demoable and nothing is blocked on a later step. Phases 0→9 are sequential; within a phase, workstreams marked **∥** can run in parallel across team members.

Each step states:

- **Goal** — what "done" means
- **Inputs / Outputs** — the contract with neighbouring steps
- **Why** — which judging criterion or deliverable it serves
- **Exit criteria** — the checkable gate before moving on

> **Important:** Phase 1 is a dedicated **data-discovery phase**. This plan deliberately does *not* assume any column names, value distributions, or cardinalities. Every schema fact used from Phase 2 onward must come out of the Phase 1 data dictionary. Any assumption written in this plan that Phase 1 contradicts is a **plan bug** — fix the plan, not the data.

---

## 1. Mapping: problem statement → this plan

| Problem statement item | Where it is delivered here |
|---|---|
| D1 Audience Profile Engine | Phase 3 |
| D2 Campaign↔Screen Relevance Scorer | Phase 5 |
| D3 Demand Forecasting & Pricing Model | Phase 6 |
| D4 Impressions Optimizer | Phase 7 |
| D5 Agentic Orchestration | Phase 8 |
| D6 Unified Platform | Phase 9 |
| Sense | Phases 1–3 (+ brief intake, Phase 4) |
| Plan | Phases 5–7 |
| Adapt | Phase 8 (orchestration, feedback, re-plan) |
| Submission: codebase + README + CLAUDE.md | Phase 0 scaffolding, Phase 10 packaging |
| Submission: C4 diagrams | Phase 2 (drafted), Phase 10 (finalised) |
| Submission: demo video | Phase 10 |
| Nuance: non-linear impressions | Phase 3 (§ reach model), Phase 7 |
| Nuance: demand inferred from leads/events | Phase 6 |
| Nuance: explainability | Cross-cutting — Phase 2 `Explanation` contract |
| Nuance: cold-start / no history | Phase 6 (fallback ladder) |
| Nuance: shared audience on a route | Phase 3 (overlap graph), Phase 7 (de-dup reach) |
| Nuance: bundle = one deal | Phase 7 (joint optimisation) |
| Nuance: signal ageing / lead expiry | Phase 6 (recency decay) |
| Scaling to new cities | Cross-cutting — Phase 2 config-driven design |

---

## 2. Design principles (non-negotiable, applied throughout)

These exist so that the codebase reads as one coherent system — directly targeting *AI & Agentic Architecture* and *Code Quality & Engineering Rigor*.

1. **Deterministic core, agentic edge.**
   Pricing, scoring maths, reach estimation and allocation are **pure, testable, reproducible functions**. LLM agents handle the *fuzzy* work only: parsing unstructured briefs, inferring semantic audience affinity, composing narrative rationale, and orchestrating tool calls. A judge must never see a number that an LLM invented.

2. **Every number carries its provenance.**
   A single `Explanation` value object travels alongside every score, price and impression figure — listing contributing signals, weights, and the data rows behind them. Explainability is a *type*, not a prose afterthought.

3. **Config over code for anything city-specific.**
   No city ID, zone name, price constant, or POI type is hardcoded. New-city onboarding = drop in data + a YAML profile. This is the answer to the "scaling beyond these cities" nuance.

4. **Deep modules, thin interfaces** (per [codebase-design](.claude/skills)).
   Each engine (`audience`, `relevance`, `pricing`, `optimizer`) exposes a small interface over substantial internal logic. Engines depend on **repository protocols**, never on file paths or pandas frames from a caller.

5. **Offline precompute vs. online request path.**
   Anything not campaign-dependent (audience profiles, footfall curves, overlap graph, demand baselines) is **precomputed into an artifact store**. The request path does lookups + optimisation only. This is the Performance & Scalability answer.

6. **Graceful degradation is designed, not accidental.**
   Every model has an explicit fallback ladder ending in a rule that always works. A screen with zero history still gets a defensible price and a stated confidence level.

7. **Reproducibility.** Fixed seeds, pinned dependencies, deterministic artifact hashes, one command to rebuild everything from raw CSVs.

8. **Test the maths, snapshot the prose.** Unit tests assert numeric invariants; LLM outputs are checked for schema validity and grounding, never exact strings.

---

## Phase 0 — Foundation & Scaffolding

**Duration target:** first few hours. Everything after depends on this.

### Step 0.1 — Repository skeleton

**Goal:** A runnable, importable, testable project before any logic exists.

```
agentiq/
├─ README.md                  # run instructions (submission requirement)
├─ CLAUDE.md                  # AI coding context (submission requirement)
├─ pyproject.toml             # pinned deps
├─ requirements.txt           # submission requirement
├─ Makefile                   # make data | build | serve | test | demo
├─ config/
│  ├─ cities/                 # per-city YAML profiles
│  ├─ scoring.yaml            # relevance weights
│  ├─ pricing.yaml            # elasticity, guardrails, uplift caps
│  └─ taxonomy.yaml           # industry → POI/audience affinity maps
├─ data/
│  ├─ raw/                    # the 14 CSVs, read-only
│  └─ artifacts/              # precomputed parquet (git-ignored)
├─ src/agentiq/
│  ├─ domain/                 # value objects, enums, Explanation
│  ├─ data/                   # loaders, repository protocols, validation
│  ├─ audience/               # D1
│  ├─ relevance/              # D2
│  ├─ pricing/                # D3
│  ├─ optimizer/              # D4
│  ├─ agents/                 # D5
│  ├─ api/                    # FastAPI service
│  └─ observability/          # trace log, timings, token accounting
├─ ui/                        # D6 frontend
├─ notebooks/                 # Phase 1 EDA only
├─ docs/
│  ├─ data_dictionary.md      # Phase 1 output
│  ├─ c4/                     # Phase 2 + 10
│  └─ decisions/              # ADRs
└─ tests/
```

**Exit criteria:** `make test` passes on an empty test suite; `make serve` starts a health-check endpoint.

### Step 0.2 — `CLAUDE.md` and ADR habit

**Goal:** Capture conventions once so all AI-assisted coding stays consistent — this is itself a graded submission artifact.

Contents: architecture map, module boundaries, naming conventions, "deterministic core / agentic edge" rule, test commands, and an explicit *do-not* list (no LLM-generated numerics, no hardcoded city logic).

**Exit criteria:** `CLAUDE.md` committed; `docs/decisions/0001-deterministic-core.md` written.

### Step 0.3 — Observability spine ∥

**Goal:** A `TraceRecorder` that every engine and agent writes to: step name, duration, inputs hash, outputs, tokens used, fallbacks triggered.

**Why:** Powers the UI's "why did you do this" panel (Explainability), the latency numbers we quote (Performance), and the demo narrative.

**Exit criteria:** A trace of a stub end-to-end call renders as a readable timeline.

---

## Phase 1 — Data Discovery & Profiling *(the dedicated analysis step)*

**This phase is the empirical foundation. No modelling decision is made before it completes.** Output is a committed data dictionary that every later phase cites.

### Step 1.1 — Inventory and load all 14 tables

**Goal:** Load every CSV in the five layers (Geography, Network, Inventory, Context, Commercial) with a **CSV-safe parser** (quoted fields containing commas are expected — never parse positionally with shell tools).

**Outputs:** `src/agentiq/data/loaders.py`, one typed loader per table.

**Exit criteria:** Row count and column list printed for all 14 tables; zero parse errors.

### Step 1.2 — Build `docs/data_dictionary.md`

**Goal:** For every table, record: grain (what one row means), row count, primary key, foreign keys, and for every column — dtype, null %, cardinality, min/max or top-10 values.

**Method:** a single profiling script (`make profile`) that regenerates the dictionary from raw data, so it can never drift.

**Exit criteria:** Every column in all 14 tables appears in the dictionary with a stated meaning. Any column whose meaning is unclear is flagged `#TODO-semantics` and resolved before Phase 3.

### Step 1.3 — Map the join graph

**Goal:** An explicit entity-relationship map, verified by measurement rather than assumed from names.

Checks to run for each candidate join:
- Referential integrity: what % of child keys exist in the parent?
- Fan-out: is this 1:1, 1:N, or N:M?
- Orphans: which rows join to nothing? (These are the cold-start population.)

Key paths to establish and validate:
- screen → location → zone → city (static geography of a screen)
- screen → vehicle → corridor → route → stops (mobile screens' exposure path)
- location → POI (proximity context)
- location/zone → events (temporal context)
- screen → bookings (commercial history)
- client → bookings, client → leads
- slot dimension → bookings (how a booking claims inventory)

**Outputs:** `docs/data_dictionary.md#join-graph` + a diagram reused in the C4 component view.

**Exit criteria:** Every join used later has a measured integrity % recorded. Fan-out traps (e.g. a screen joining to many route rows) are documented with the intended aggregation.

### Step 1.4 — Profile the inventory (screens & slots)

**Goal:** Understand exactly what is being sold.

Questions to answer with numbers:
- Distribution of screens by **city**, **screen type** (the 5 deployment kinds), **mount position**, **screen size**.
- Which screen types are **static** (fixed location) vs **vehicle-mounted** (moving) — and therefore need a fundamentally different audience model.
- How many distinct sellable units exist: screens × time blocks × rotation slots × days. **This is the true optimisation problem size** — measure it before designing the solver.
- What the slot dimension actually contains (time blocks, labels, hour bounds, daypart mapping) and how a booking references it.

**Exit criteria:** A one-page "inventory shape" summary including the exact sellable-unit count per city per day. Solver design in Phase 7 must cite this number.

### Step 1.5 — Profile demand history (bookings & leads)

**Goal:** Understand pricing and demand reality.

Questions to answer:
- Date span of bookings; split by status (completed / active / upcoming). **Only settled history is training data**; future-dated rows are *committed occupancy*, which is a different input.
- Realised price distribution — overall and cut by city, screen type, time block, rotation type, size, market tier. Which cuts actually move price? (This drives the pricing feature set.)
- Occupancy: for each screen × time block × date, how many of the rotation slots are claimed? Requires expanding each booking across its date range — the **booking-expansion transform** is a core reusable artifact.
- Bundle prevalence: what share of value is transacted as multi-screen deals, and do bundled line items price differently from standalone? (Evidence for the "bundle is one deal" nuance.)
- Rotation-type mix and whether price per slot scales linearly with slots booked. **Test this explicitly** — the non-linearity nuance lives here.
- Lost leads: loss reasons, price-gap distribution, negotiation rounds, stage reached, and the age/expiry of each lead. Quantify: at what price gap does win probability collapse? This calibrates the pricing cap.

**Exit criteria:** A `notebooks/01_demand_profile.ipynb` with these findings, and a short list of **empirically supported** price drivers, ranked by effect size, committed to `docs/data_dictionary.md#price-drivers`.

### Step 1.6 — Profile context (POI, events, demographics, ridership)

**Goal:** Understand what makes a location valuable to an *audience*.

Questions to answer:
- POI types and their footfall scale; how many POIs sit within plausible walking distance of each location; what the distance and side-of-road fields let us infer about visibility.
- Events: frequency, attendance tiers, impact radius, and which dayparts they hit — the raw material for demand surges.
- Zone demographics: which attributes discriminate between zones (income index, age mix, education, dominant occupation, daytime population multiplier). Daytime multiplier is the key bridge between *residents* and *actual audience*.
- Ridership: scheduled vs actual, by day type and daypart. Derive a **normalised daypart exposure curve** per route/corridor. Check holiday and weekday/weekend effects.

**Exit criteria:** Documented, per-city daypart curves and a validated POI-proximity rule (which radius actually captures signal without pulling in noise).

### Step 1.7 — Data-quality register & cold-start census

**Goal:** Know the system's blind spots before building on them.

Deliverables:
- **DQ register:** nulls in critical fields, referential orphans, duplicates, outliers, impossible values, timezone/date-format inconsistencies — each with a chosen handling rule.
- **Cold-start census:** exactly how many screens have zero bookings, sparse bookings, no nearby POI, or no ridership coverage. Percentage matters: it sizes how visible the fallback logic will be in the demo.

**Exit criteria:** `docs/data_dictionary.md#dq-register` complete; cold-start counts drive Phase 6's fallback design.

### Step 1.8 — Parse the campaign briefs ∥

**Goal:** Derive the brief schema from the *actual* briefs, not from imagination.

For each supplied brief, extract by hand into a table: client, industry, objective, target audience (incl. age band), budget, duration, requested start window, location/environment requirements, **exclusion criteria**, slot/rotation request, creative format constraints, and the explicit RFP deliverables requested.

Then generalise: which fields are always present, which are optional, which are expressed as *soft preferences* vs *hard constraints*.

**Exit criteria:** A `CampaignBrief` schema justified field-by-field against the real briefs, plus a hand-written "gold" parse of each brief to use as the Phase 4 test fixture. Note explicitly which briefs demand things the data may not directly support (e.g. named venue types, walking-radius limits, weekend weighting, creative-format restrictions) — each becomes a required capability, not a surprise during the demo.

### Step 1.9 — Findings review gate 🚧

**Goal:** Team-wide 30-minute read-out of Phase 1. Reconcile every modelling assumption in this plan against measured reality; amend the plan in writing.

**Exit criteria:** Signed-off data dictionary. **Do not start Phase 3 before this gate.**

---

## Phase 2 — Architecture, Domain Model & Contracts

**Runs partly in parallel with Phase 1** (contracts can be drafted while profiling runs), finalised right after the gate.

### Step 2.1 — Domain model & ubiquitous language

**Goal:** One vocabulary, used identically in code, UI, diagrams and demo script.

Core entities: `Screen`, `SellableUnit` (screen × time-block × slot × date), `AudienceProfile`, `CampaignBrief`, `RelevanceScore`, `DemandSignal`, `PriceQuote` (floor/target/cap/recommended), `ReachEstimate`, `PackageLine`, `Package`, `Explanation`, `Recommendation`.

**Exit criteria:** `src/agentiq/domain/` with immutable, validated types. Glossary in `docs/`.

### Step 2.2 — The `Explanation` contract (cross-cutting)

**Goal:** Make explainability structural.

```
Explanation
├─ headline: str                  # one-line human reason
├─ contributions: [Contribution]  # signal, direction, weight, magnitude
├─ evidence: [EvidenceRef]        # table + row keys + values used
├─ confidence: Confidence         # high | medium | low + why
└─ fallbacks_used: [str]          # which defaults kicked in
```

**Why:** Judging criterion 4 (Explainability & Trust). Because it is a type, no engine can return a number without a reason, and the UI can render *any* explanation generically.

**Exit criteria:** Type defined; a lint/test rule enforces that public engine outputs carry one.

### Step 2.3 — Repository protocols & artifact store

**Goal:** Engines depend on interfaces (`ScreenRepository`, `BookingRepository`, …), with two implementations: in-memory parquet (hackathon) and a documented DB-backed path (scaling story).

**Exit criteria:** Engines import zero pandas-loading code; swapping the repo implementation requires no engine change.

### Step 2.4 — C4 diagrams, first draft ∥

**Goal:** Context, Container, Component diagrams as code (Mermaid/Structurizr) so they stay current.

- **Context:** sales rep, AgentIQ, data sources, LLM provider.
- **Container:** UI, API, agent orchestrator, engine library, artifact store, trace store.
- **Component:** the five engines + orchestrator internals, drawn from the real module tree.

**Exit criteria:** Diagrams render from source in CI; committed to `docs/c4/`.

### Step 2.5 — Scenario-driven acceptance tests

**Goal:** Turn each supplied brief into an end-to-end acceptance scenario with hand-checked expectations (e.g. the hyper-local brief must return only screens inside its walking radius; the premium brief must exclude the inventory it excludes).

**Why:** These double as the demo script and as proof of *Recommendation Quality & Personalization*.

**Exit criteria:** Failing acceptance tests committed — our definition of done for Phase 8.

---

## Phase 3 — D1: Audience Profile Engine

**Depends on:** Phase 1 gate.
**Deliverable:** For every screen — *who is near this screen, when, and why*.

### Step 3.1 — Static exposure model (fixed screens)

**Goal:** Quantify who passes a fixed location, by daypart.

Compose, per location:
- **Resident/zone base** — demographics, adjusted by the daytime-population multiplier.
- **Transit throughput** — ridership at the stops served, shaped by the daypart curve.
- **POI pull** — footfall of nearby POIs, weighted by distance decay, POI type, scale, and peak daypart.
- **Visibility modifier** — mount position, screen size, and side-of-road adjacency (a far-side POI is weaker evidence than a same-side one).

**Rules layer (noise filtering, per the D1 spec):** distance cut-offs validated in Step 1.6, side-of-road logic, POI-type relevance gating, capping any single POI's contribution.

**Outputs:** `audience_profile` artifact keyed by screen × daypart: exposure volume, composition (age/income/occupation mix), and top contributing signals.

### Step 3.2 — Mobile exposure model (vehicle-mounted screens)

**Goal:** A moving screen's audience is a *journey*, not a point.

Model exposure as the weighted union of the stops/segments the vehicle's route traverses, scaled by trip frequency by day type and daypart, and by rider dwell time inside the vehicle versus a passer-by glimpse outside it. Interior-facing and exterior-facing positions get different audiences — interior reaches captive riders, exterior reaches street pedestrians and adjacent traffic.

**Exit criteria:** Mobile and static screens are on a **comparable exposure scale**, with the normalisation documented and unit-tested.

### Step 3.3 — Semantic audience profiling (the AI Agent part)

**Goal:** Turn numeric exposure into a human-meaningful profile.

An LLM agent receives the *structured* evidence bundle (zone stats, POI list with types/distances, route context, daypart curve) and returns **strictly typed JSON**: audience segment labels, likely intents by daypart, environment descriptors (e.g. business-district platform, nightlife corridor, mall entry, campus edge, airport corridor, high-street retail), and a short rationale.

Guardrails: the agent may only assign labels from a controlled vocabulary in `config/taxonomy.yaml`; it must cite evidence IDs for each label; any label without evidence is dropped. Batched and cached — profiles are precomputed offline, never on the request path.

**Why:** This is what makes Phase 5 matching semantic rather than keyword-based, and it directly serves the environment types the real briefs ask for.

### Step 3.4 — Audience-overlap graph *(nuance: shared audience)*

**Goal:** Stop double-counting the same commuter.

Build a screen-to-screen overlap matrix from: same location, same corridor/route, shared stop sequence, and shared POI catchment. Store as a sparse graph plus per-cluster overlap coefficients.

**Why:** Phase 7 needs this for de-duplicated reach; without it, reach numbers are inflated and the model is, as the problem statement says, simply wrong.

### Step 3.5 — Impression & reach model *(nuance: non-linearity)*

**Goal:** Convert exposure into *impressions* and *unique reach*, honestly.

- **Impressions** = exposure × slot share within the block × attention factor. Attention rises with slots-per-minute but with **diminishing returns** — model the concave curve explicitly and expose its parameters in config.
- **Unique reach** = impressions de-duplicated via frequency assumptions and the overlap graph, with a saturation curve (adding the 20th screen on one corridor adds far less unique reach than the 2nd).
- Report **reach, frequency and impressions separately** — several briefs explicitly ask to trade frequency against breadth.

**Exit criteria:** Unit tests proving concavity (doubling slots < doubles impressions) and sub-additivity (reach of a set ≤ sum of individual reaches). These two tests are the mathematical proof that we handled the nuances.

---

## Phase 4 — Campaign Brief Intake

**Deliverable:** Solution-flow stage 1; feeds D2/D3/D4.

### Step 4.1 — Brief ingestion

**Goal:** Accept the messy reality: pasted text, uploaded documents, or partial form input.

Extraction into `CampaignBrief` separates **hard constraints** (budget ceiling, date window, exclusions, creative/format restrictions, geographic radius) from **soft preferences** (audience descriptors, environment types, daypart weighting, tone).

### Step 4.2 — Normalisation & resolution

**Goal:** Bind fuzzy brief language to real data entities.

Resolve stated locations/environments to zones, corridors, POI types and screen attributes using the Phase 3 taxonomy. Where a brief names something with no clean match, record it as an **unresolved requirement** rather than silently dropping it.

### Step 4.3 — Clarification loop

**Goal:** Ask, don't guess.

If a hard constraint is missing or contradictory (no budget, impossible window, exclusions that empty the inventory), the agent asks a targeted question and states the assumption it would otherwise use.

**Exit criteria:** All supplied briefs parse to within tolerance of the Step 1.8 gold parses; missing-field and contradiction cases produce questions, not silent defaults.

---

## Phase 5 — D2: Campaign↔Screen Relevance Scorer

**Deliverable:** Ranked screens with explainable affinity scores.

### Step 5.1 — Hard-constraint filter

Apply eligibility first — city/geography, exclusions, creative-format and screen-type restrictions, availability in the requested window. Cheap, exact, and it shrinks the candidate set before any expensive scoring.

**Every excluded screen records *why*** — the UI shows "excluded: bus-rear, brief excludes bus-rear" and that is a trust win.

### Step 5.2 — Multi-signal relevance score

Weighted, config-driven components:
- **Audience affinity** — brief's target segments vs the screen's audience composition (demographic distance + semantic label match).
- **Daypart alignment** — brief's requested weighting vs the screen's exposure curve.
- **Environment/POI fit** — requested environment types vs the screen's descriptors and POI adjacency.
- **Objective fit** — awareness favours breadth and high-exposure nodes; conversion/footfall favours proximity to the point of purchase; frequency favours captive, repeat-exposure inventory.
- **Historical performance prior** — how comparable campaigns performed on this screen; **down-weighted, never dominant**, so cold-start screens are not unfairly buried.

Weights live in `config/scoring.yaml`, are objective-dependent, and are tunable in the UI — a strong demo moment.

### Step 5.3 — Semantic re-ranking (the AI Agent part)

An agent reviews the top-N shortlist with full evidence and may **re-rank within a bounded band**, giving a reason. It cannot invent scores or promote an ineligible screen. This captures nuance the rule engine misses (e.g. "beauty-counter adjacency" vs generic "mall") while staying auditable.

### Step 5.4 — Score explanation

Each scored screen emits a full `Explanation`: per-signal contributions with direction and magnitude, cited evidence, and confidence. Comparative phrasing ("ranks above peers on affluent-commuter affinity, below on dwell time") reads far better in a demo than a bare number.

**Exit criteria:** Acceptance scenarios from Step 2.5 pass on ranking; every exclusion and every top-20 rank has a human-readable reason; scoring latency for a full city's inventory is measured and recorded.

---

## Phase 6 — D3: Demand Forecasting & Pricing Model

**Deliverable:** Floor / target / cap + recommended optimal price per screen-slot, in real time.

### Step 6.1 — Demand intensity index *(nuance: demand is inferred)*

**Goal:** One interpretable index per screen × time-block × date, built from signals that exist.

Components:
- **Committed occupancy** — from expanded future-dated bookings: how much of this unit is already claimed. Scarcity is the strongest honest signal.
- **Historical demand rhythm** — seasonality, day-of-week, daypart patterns from settled bookings.
- **Pipeline pressure** — open/lost leads requesting this geography, screen or window. Competition for the same inventory that week is exactly the blind spot the problem statement names.
- **Event surge** — scheduled events, weighted by attendance tier, impact radius and impacted daypart.
- **Segment heat** — recent demand from the brief's industry vertical.

**Recency decay *(nuance: signals age unequally)*:** every pipeline signal is weighted by an explicit decay function of age, with lead expiry as a hard cut. The decay half-life is a config parameter and is **shown in the UI** — an aged lead visibly counts for less.

### Step 6.2 — Expected-footfall forecast

Forecast exposure for the campaign's *future* window (not just historical average): daypart curve × day-type effects × seasonality × event uplift × holiday effects. Confidence intervals included — a forecast without one is a guess.

### Step 6.3 — Price band construction (floor / target / cap)

**Goal:** Guardrails, the exact thing the business lacks today.

- **Base rate** from a transparent, fitted model over the price drivers empirically confirmed in Step 1.5 (city tier, screen type, position, size, time block, rotation type, duration). Prefer an interpretable model (regularised linear / GBM with per-feature attributions) so each dollar is attributable.
- **Floor** — cost-and-dignity guard: a percentile of comparable realised prices, never below a configured margin floor.
- **Cap** — willingness-to-pay guard: calibrated against the lost-leads price-gap evidence, i.e. the gap at which deals demonstrably die.
- **Target** — base × demand multiplier (from Step 6.1) × relevance premium × client-relationship adjustment (tier, leverage, history), **clamped into [floor, cap]** with the clamp recorded in the explanation.
- **Uplift/discount caps** per adjustment so no single factor can run away.

### Step 6.4 — Recommended optimal price

Choose the point inside the band that maximises expected value = price × P(win | price, gap, client, demand). Win-probability is calibrated on won-vs-lost history and the price-gap curve. Output the recommendation *with* the trade-off curve so a rep can see the cost of discounting.

### Step 6.5 — Cold-start fallback ladder *(nuance: no history)*

An explicit, ordered ladder, each rung labelled with a confidence level:

1. This screen's own history
2. Peer screens — same location or corridor
3. Same zone × screen type × position × size cohort
4. City × screen-type baseline adjusted by market tier
5. Global rule-based rate card from physical attributes

The rung used is surfaced in the UI ("no direct history; priced from 14 peer screens on this corridor — medium confidence"). Turning a data weakness into a visible trust feature is worth more than hiding it.

### Step 6.6 — Human-in-the-loop inputs

The D3 spec includes human inputs: a rep can supply expected footfall, strategic-discount intent, or competitive intel. These enter as **explicit, logged overrides** that adjust the band and are recorded in the explanation and trace.

**Exit criteria:** Back-test on held-out settled bookings — report band coverage (what % of realised prices fall inside our band) and target-vs-realised error. Property tests: floor ≤ target ≤ cap always; monotonicity (more demand never lowers the target); every price cites its ladder rung.

---

## Phase 7 — D4: Impressions Optimizer

**Deliverable:** The optimal multi-location, multi-slot package within budget.

### Step 7.1 — Problem formulation

**Decision variables:** which sellable units (screen × time block × slot-count × date range) to include.
**Objective:** maximise expected **de-duplicated unique reach** (or a configurable blend of reach and impressions), with relevance as a quality weight.
**Constraints:**
- Budget ceiling (hard)
- Campaign date window and slot availability from committed occupancy
- Brief-imposed exclusions and format restrictions
- Minimum relevance threshold — never buy cheap junk to inflate volume
- Optional diversification: geographic spread, minimum effective frequency, daypart weighting from the brief

### Step 7.2 — De-duplicated reach objective *(nuances: overlap + non-linearity)*

The objective uses the Phase 3 overlap graph and saturation curves, making it **submodular** — diminishing returns are structural. Consequences:
- A greedy/lazy-greedy algorithm gives a strong solution with a known approximation guarantee.
- Add local search (swap/drop-add) and, where size permits, an ILP/CP formulation for a provably strong answer.
- **Strategy is selected by measured problem size** from Step 1.4, with the chosen strategy and its guarantee reported in the output.

This is where we visibly beat a naive "rank and fill until budget runs out" baseline.

### Step 7.3 — Joint bundle pricing & allocation *(nuance: one deal)*

Bus + metro + station is optimised as a **single package**: shared budget, joint reach de-duplication across modes, and a bundle-level price that reflects portfolio value rather than three independent quotes. Bundle discount/uplift logic is explicit and bounded, informed by the Step 1.5 bundle-pricing evidence.

### Step 7.4 — Alternatives, trade-offs and sensitivity

Return not one package but a small **efficient frontier**: e.g. max-reach, best value-per-impression, premium-quality, and frequency-heavy variants. Plus sensitivity: "+10% budget buys +X unique reach"; "dropping the weekend weighting saves $Y".

**Why:** Reps negotiate. A single take-it-or-leave-it package is a weaker product and a weaker demo.

**Exit criteria:** Beats greedy-by-relevance and beats cheapest-first on unique reach per dollar across all acceptance scenarios; budget/availability constraints never violated (property-tested); optimisation latency recorded.

---

## Phase 8 — D5: Agentic Orchestration

**Deliverable:** Raw brief in → complete, explained recommendation out. This is where the system becomes *one* system.

### Step 8.1 — Orchestrator design

A **planner-executor** orchestrator over typed tools, not a free-form chat loop:

`parse_brief` → `resolve_entities` → `profile_lookup` → `score_relevance` → `forecast_demand` → `price_units` → `optimize_package` → `compose_recommendation`

Properties:
- Every tool is a **typed, deterministic function** (except the two explicitly semantic ones from Phases 3 and 5).
- The agent decides *routing and iteration*, not arithmetic: whether to widen a filter, relax a soft constraint, ask a clarifying question, re-run the optimiser with an adjusted objective, or split into a bundle.
- Bounded loops with explicit termination and a step budget.

### Step 8.2 — Adaptive re-planning *(the "Adapt" pillar)*

Concrete adaptive behaviours to implement and demo:
- Budget can't meet the relevance threshold → propose fewer screens with higher frequency, or a shorter flight, and say so.
- Preferred inventory already committed → find the nearest-equivalent by audience overlap, not by name similarity.
- An event lands in the window → surface the surge and offer to shift dates.
- Availability changes mid-session → invalidate affected cache entries and re-optimise only the affected part.

### Step 8.3 — Feedback & learning loop

Rep feedback ("too expensive", "drop this corridor", "more weekend weight", "client wants premium only") is captured as **structured preference deltas**, applied immediately to a re-plan, and persisted per client/rep to bias future runs. Persisted, inspectable, and revertible — no opaque drift.

### Step 8.4 — Narrative composition

A final agent turns the structured `Explanation` objects into the client-ready RFP response the briefs actually request: shortlist with ranked rationale, price rationale, projected impressions/reach with the requested splits (e.g. weekend vs weekday, business vs leisure), and stated assumptions.

**Hard rule:** the narrative agent receives only computed numbers and may not alter them. A validation pass checks every figure in the prose against the structured payload and fails the response if they disagree.

**Exit criteria:** All Step 2.5 acceptance scenarios pass end-to-end; every response's numbers validate against structured output; full trace available for every run.

---

## Phase 9 — D6: Unified Platform

**Deliverable:** The interface a sales rep actually uses — and the surface the judges see.

### Step 9.1 — Core flow

1. **Brief intake** — paste text or upload a document; parsed fields shown for confirmation and editing.
2. **Clarification** — agent's questions answered inline.
3. **Live agent trace** — steps streaming as they execute. This makes the "agentic" claim visible instead of asserted.
4. **Recommendation** — package summary: screens, slots, dates, price, projected impressions/reach/frequency.
5. **Drill-down** — per-screen: why chosen, why this price, which ladder rung, what evidence, what confidence.
6. **What-if** — adjust budget, dates, exclusions, daypart weighting, or relevance threshold and re-plan.
7. **Feedback** — accept, reject with reason, or nudge; feeds Step 8.3.
8. **Export** — the client-ready proposal.

### Step 9.2 — Explainability surfaces

- Map view: recommended screens, POI context, overlap clusters.
- Score breakdown: per-signal contribution bars.
- Price band visual: floor / target / cap / recommended, with the win-probability curve.
- Reach saturation curve showing why the package stops where it does.
- Exclusion list with reasons.

Follow the [dataviz](.claude/skills) conventions for all charts: consistent palette, accessible contrast, light/dark parity, and labelled axes with units.

### Step 9.3 — Trust & control affordances

Confidence badges on every figure; visible fallback notices; editable config (weights, decay half-life, thresholds) with instant re-plan; full audit trail per recommendation.

**Exit criteria:** A non-technical person completes the whole flow unaided; every number on screen is clickable to its evidence.

---

## Phase 10 — Hardening, Scale Story & Submission

### Step 10.1 — Performance & scalability *(criterion 5)*

- Precompute all non-campaign-dependent artifacts; measure and publish cold vs warm latency.
- Cache profiles, availability and demand indices with correct invalidation.
- Candidate pruning before expensive scoring; vectorised numerics; batched, cached LLM calls.
- **Publish a latency/quality trade-off table** — e.g. fast mode (greedy, ~Xs) vs thorough mode (ILP + local search, ~Ys) with the reach delta between them. Explicitly reasoning about this trade-off is what the criterion asks for.
- Load test at multiples of current inventory (2×, 5×, 10×) by synthetic replication; report where it breaks and what the fix is.

### Step 10.2 — Multi-city / new-market readiness

Demonstrate onboarding a new city from data + a YAML profile, with no code change. Document which parameters need local calibration and how the cold-start ladder covers a market with zero history — which is exactly a brand-new city's situation.

### Step 10.3 — Testing & quality gates

- Unit tests on all numeric logic; property tests for the invariants named in Phases 3, 6, 7.
- Back-tests: pricing band coverage, ranking sanity against historical wins.
- Baseline comparisons for the optimiser.
- Schema/grounding validation for every LLM output.
- Acceptance tests for all supplied briefs.
- Lint, type-check, formatting in CI; one-command reproducible rebuild from raw CSVs.

### Step 10.4 — Submission artifacts

- **Codebase `.zip`** with `requirements.txt`, `README.md` (run instructions verified from a clean environment), `CLAUDE.md`.
- **C4 diagrams** finalised from the real module tree (Context, Container, Component), exported to PDF/image.
- **Demo video, 5–10 min** — see Step 10.5.
- ADRs and the Phase 1 data dictionary included as supporting evidence of rigour.

### Step 10.5 — Demo script *(criterion 7)*

Rehearsed, timed, and built around the judged criteria:

1. **0:00–0:45 — The pain.** The spreadsheet-and-guesswork status quo, in one sentence.
2. **0:45–2:00 — Messy brief in.** Paste a real brief; show parsing, resolved constraints, and one clarifying question.
3. **2:00–3:30 — Watch it think.** Live agent trace across the pipeline; land on the recommendation.
4. **3:30–5:00 — Why.** Drill into one screen: audience evidence, score contributions, price band, ladder rung, confidence.
5. **5:00–6:30 — The hard parts.** Show the three nuances explicitly: overlap de-duplication on a shared corridor, non-linear slot returns, and a cold-start screen priced from peers.
6. **6:30–8:00 — Adapt.** Cut the budget by 30%; watch the re-plan and the reasoned trade-off. Give feedback; watch it apply.
7. **8:00–9:00 — Scale.** Latency table, 10× load result, and a new city onboarded from config.
8. **9:00–9:30 — Close.** Value: consistent guarded pricing, demand-aware yield, audience-matched inventory — the exact three challenges, closed.

---

## Parallelisation plan (team of ~4–5)

| Track | Phases | Owner focus |
|---|---|---|
| **A — Data & Audience** | 1, 3 | Profiling, data dictionary, exposure models, overlap graph, reach maths |
| **B — Pricing & Demand** | 6 | Demand index, forecasting, price bands, win-probability, fallback ladder |
| **C — Optimisation** | 7 | Formulation, submodular objective, bundle logic, frontier, baselines |
| **D — Agents & API** | 4, 5, 8 | Brief intake, relevance scorer, orchestrator, narrative validation |
| **E — Platform & Story** | 0, 2, 9, 10 | Scaffolding, contracts, UI, C4, tests, demo |

**Hard sync points:** the Phase 1 gate (1.9), contracts freeze (2.2/2.3), and first end-to-end integration (start of Phase 8) — integrate early with stubs rather than at the end.

---

## Risk register

| Risk | Mitigation |
|---|---|
| Phase 1 reveals a signal is unusable | Every engine has a rules-based fallback; the fallback ladder is designed, not bolted on |
| Optimiser too slow at real scale | Size measured in Step 1.4; greedy path always available; latency/quality modes published |
| LLM latency or flakiness dominates the demo | Precompute and cache all semantic profiles offline; agents on the request path do routing and prose only; deterministic fallbacks for every agent step |
| LLM fabricates numbers | Structural rule: agents never produce numerics; post-hoc validation of prose against structured payload |
| Scope creep across six deliverables | Each phase ends demoable; thin end-to-end slice before deepening any single engine |
| Explainability becomes prose padding | `Explanation` is a required return type with cited evidence, enforced by tests |
| Integration crunch at the end | Contracts frozen in Phase 2; stubbed end-to-end run available from Phase 2 onward |

---

## Definition of done

- [ ] All six deliverables D1–D6 implemented and reachable through the UI
- [ ] All eight named nuances explicitly addressed, each with a test or a visible UI surface
- [ ] Every supplied campaign brief runs end-to-end and satisfies its stated RFP requirements
- [ ] Every number traceable to evidence; no LLM-authored numerics anywhere
- [ ] Data dictionary, ADRs, C4 diagrams committed and current
- [ ] One-command reproducible rebuild and run from raw CSVs in a clean environment
- [ ] Latency and scale numbers measured and published
- [ ] Demo video recorded, under 10 minutes, rehearsed
