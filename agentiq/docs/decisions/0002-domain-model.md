# ADR 0002: Domain model & glossary (Step 2.1)

## Status

Accepted

## Context

Five deliverables (D1–D5) each hand off a typed output to the next: audience
profiles feed relevance scores, relevance scores feed pricing and
optimisation, optimisation feeds the final recommendation. Without one
vocabulary used identically in code, docs, and demo script, each phase would
invent its own shape for "a priced screen" or "a scored package," and the
seams between phases would become ad hoc translation code instead of a
shared contract. ADR-0001 already establishes *that* engines must be
deterministic; this ADR establishes *what the typed values passing between
them actually are*.

## Decision

`src/agentiq/domain/` is the single place these types are declared. Every
type is an immutable, validated pydantic model — invalid states (a screen
with both a location and a vehicle, a price band with `floor > cap`, a
reach estimate where de-duplication somehow *created* audience) raise at
construction, not at first use three phases later.

## Glossary

Each entry names the file it lives in and the invariant that protects it.

| Term | Type / file | Meaning | Protected invariant |
| --- | --- | --- | --- |
| **Screen** | `inventory.Screen` | One physical screen — the unit that is sold. | Exactly one of `location_id` / `vehicle_id` is set, and it must agree with `screen_type.is_static` (Step 1.4 §2.1 — measured 1:1). |
| **SellableUnit** | `inventory.SellableUnit` | `screen × time_block × date`, holding up to 6 rotation slots. The atomic thing Phase 6 prices and Phase 7 allocates. | `time_block_id` ∈ 1–6; slot count checked against `MAX_ROTATION_SLOTS` (the measured, proved ceiling from Step 1.4 §1.3). |
| **AudienceProfile** | `inventory.AudienceProfile` | D1 output: who is near this screen, when, and why. | Weekday/weekend daypart weights are keyed only by known `time_block_id`s (Step 1.6 — the two day types peak on genuinely different blocks, so they are two separate dicts, never one blended curve). |
| **CampaignBrief** | `campaign.CampaignBrief` | The *resolved* form of a sales rep's brief — zones, screen types, POI types bound against the real vocabulary. Distinct from `agentiq.data.briefs.DerivedBriefFields`, which is the *literal* parse of the document text. | `time_block_ids` ∈ 1–6; `duration_days` > 0; `budget` > 0. |
| **GeographyConstraint** | `campaign.GeographyConstraint` | One resolved location requirement or exclusion (e.g. a walking-radius rule). | `radius_km`, when set, should fall in the Step 1.6 §3 validated 0.3–0.5 km signal-carrying range — engines building these should not invent radii outside it without a stated reason. |
| **RelevanceScore** | `scoring.RelevanceScore` | D2 output: why this screen fits this campaign. | `score` ∈ [0, 1] so it composes uniformly with the Step 7.1 minimum-relevance-threshold constraint. |
| **DemandSignal** | `pricing.DemandSignal` | D3's Step 6.1 demand-intensity index for one screen × time-block, broken into its five named components (committed occupancy, historical rhythm, pipeline pressure, event surge, segment heat). | `index` ≥ 0; `committed_occupancy` ∈ [0, 1]. |
| **PriceQuote** | `pricing.PriceQuote` | D3 output: floor / target / cap / recommended price for one screen-slot. | `floor ≤ target ≤ cap` and `floor ≤ recommended ≤ cap`, always — this is the Step 6 exit-criterion property test, enforced at construction rather than trusted to the caller. |
| **ReachEstimate** | `optimizer.ReachEstimate` | Projected audience reach for one unit or a de-duplicated group. | `unique_reach ≤ gross_impressions` — de-duplication cannot create audience (the Step 7.2 nuance, enforced structurally). |
| **PackageLine** | `optimizer.PackageLine` | One screen × time-block × date-range × slot-count decision inside a package. | `end_date ≥ start_date`. |
| **Package** | `optimizer.Package` | A multi-location, multi-slot recommendation, reasoned about as *one deal* (Step 7.3), carrying the optimiser strategy and its stated guarantee (Step 7.2). | At least one line; `confidence` is the weakest-link merge of its lines' price-quote confidences (`merge_confidence`), never optimistic rounding up. |
| **Recommendation** | `recommendation.Recommendation` | D5's full answer to one brief: a small efficient frontier of packages (Step 7.4), not one take-it-or-leave-it option, plus narrative prose composed *from* the structured packages (Step 8.4). | At least one package; `primary_package_id` must resolve to a package actually present in `packages`. |
| **Explanation** | `explanation.Explanation` | The structural embodiment of Criterion 4 (Explainability & Trust) — headline, weighted contributions, cited evidence, a confidence level with its reason, and any fallbacks used. | Every `Contribution.direction` must agree in sign with its `magnitude` (`positive` ⇒ magnitude ≥ 0, etc.) — an explanation cannot claim a positive effect while reporting a negative number. |
| **Contribution** | `explanation.Contribution` | One signal's share of a computed number's total effect. | `weight` ∈ [0, 1]; evidence is attached per-contribution so a UI can show *which* signal a given data row backs. |
| **EvidenceRef** | `explanation.EvidenceRef` | A pointer to the real row (table + primary key + field + value) behind a claim. | None beyond required fields — but every `EvidenceRef` is expected to resolve against a real catalogue table; this is checked by acceptance tests (Step 2.5), not by the type itself. |
| **Confidence** | `enums.Confidence` | `high` / `medium` / `low`, always paired with a stated reason. | `merge_confidence()` always returns the weakest input — confidence can only degrade when combining sub-results, never improve by averaging. |
| **ColdStartRung** | `enums.ColdStartRung` | The Step 6.5 fallback ladder: `screen_own_history` → `peer_screens_same_location_or_corridor` → `cohort_zone_type_position_size` → `city_screen_type_baseline` → `global_rate_card`. | Each rung carries a `default_confidence` that only decreases moving down the ladder. |

## Consequences

- Engines never hand a caller a raw dict, a pandas row, or a bare float
  where a domain type exists — a `PriceQuote` is always a `PriceQuote`, not
  `{"floor": ..., "cap": ...}`.
- Adding a new scored/priced/ranked output type without giving it an
  `Explanation` field is a design mistake to catch in review, per the
  CLAUDE.md do-not list.
- Because invariants raise at construction, a bug that would violate
  `floor <= cap` or manufacture reach out of nothing fails loudly at the
  point it is created, not silently three engines downstream.

## Alternatives considered

- **Plain dataclasses instead of pydantic models.** Rejected — pydantic
  gives free JSON (de)serialisation for the FastAPI boundary (Phase 9) and
  `model_validator` for the cross-field invariants above; dataclasses would
  need the same validation hand-rolled with no schema benefit.
- **One big `Recommendation` type with inline dicts for scores/prices/reach.**
  Rejected — it would make `Explanation` a per-caller convention instead of
  a structural requirement, defeating the point of Step 2.2.
