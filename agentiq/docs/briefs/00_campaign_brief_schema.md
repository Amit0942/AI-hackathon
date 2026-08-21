# Step 1.8 — Campaign Brief Intake: Schema, Gold Parses & Capability Register

> **This document is the Step 1.8 exit deliverable.** It states the `CampaignBrief`
> schema justified field-by-field against the six real briefs, and records explicitly
> which briefs demand things the data does not support. Per the plan, every schema fact
> here is derived from the *actual* documents and measured against the raw CSVs — not
> from imagination.

*Corpus:* `Campaigns/campaign_1.docx` … `campaign_6.docx` (6 documents, 183 paragraphs total)
*Structural parser:* `src/agentiq/data/briefs.py` — `parse_brief`, `derive_fields`
*Schema source of truth for data facts:* [../data_dictionary.md](../data_dictionary.md)
*Gold parses:* [campaign_1.md](campaign_1.md) · [campaign_2.md](campaign_2.md) · [campaign_3.md](campaign_3.md) · [campaign_4.md](campaign_4.md) · [campaign_5.md](campaign_5.md) · [campaign_6.md](campaign_6.md)

---

## 1. The corpus at a glance

| # | Client | Vertical (stated) | Objective (stated) | Budget | Days | City | Excl. | Env. reqs |
|---|---|---|---|---|---|---|---|---|
| 1 | Voltaic Motors (Zephyr EV) | AUTOMOTIVE / ELECTRIC VEHICLES | Brand Awareness & Test-Drive Bookings | $40,000 | 45 | LH *(prose)* | 2 | 2 |
| 2 | Ember Beverages | FMCG / BEVERAGES (ENERGY DRINKS) | Trial & Impulse Purchase | $12,000 | 21 | **none** | 0 | 3 + daypart |
| 3 | Loom & Thread Apparel | RETAIL / FASHION | Seasonal Footfall & Sale Awareness | $22,000 | 20 | **none** | 0* | 2 + daypart |
| 4 | Basil & Bloom Kitchens | FOOD & BEVERAGE / QSR | Lunch-Hour Footfall & Local Recall | $9,000 | 15 | LH *(prose)* | 1 | 2 |
| 5 | SkyNimbus Airlines | TRAVEL & AVIATION | New Route Awareness & Bookings | $35,000 | 40 | LH *(prose)* | 0 | 3 |
| 6 | Lumière Cosmetics | BEAUTY & PERSONAL CARE | New Product Launch Awareness | $20,000 | 25 | **none** | 0* | 3 |

\* Briefs 3 and 6 carry a **soft negative** in prose (residential/industrial corridors;
anti-impulse) that is not in labelled exclusion form. Retain as a scoring penalty, not
a filter.

All six documents share one layout: a 6-field header table, then §1 Executive Summary,
§2 Target Audience & Persona, §3 Digital Screen Selection & Location Requirements,
§4 Visual / Mockup Details & Slot Parameters, §5 RFP Requirements. `parse_brief`
recovers all of it; the only `unparsed` output across the corpus is the 2-paragraph
portfolio cover page on brief 1. **No paragraph is silently dropped anywhere.**

## 2. Field presence matrix — the basis for required vs optional

Measured across all six briefs. This table, not judgement, decides which schema fields
are non-optional.

| Field | B1 | B2 | B3 | B4 | B5 | B6 | n/6 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `client_name` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `campaign_title` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `industry_vertical_raw` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `objective_raw` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `target_audience_raw` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `age_min` / `age_max` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `budget_amount` (all USD) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `duration_days` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `window_hint` (prose) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `environment_requirements` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `creative_format` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `rfp_deliverables` (3 each) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **6** |
| `daypart_weighting` | — | ✓ | ✓ | ✓ | — | ✓ | 4 |
| `city_id` | ✓ | — | — | ✓ | ✓ | — | **3** |
| `exclusions` (labelled) | ✓ | — | — | ✓ | — | — | 2 |
| `priority_tier` ("supplementary") | — | — | — | — | ✓ | ✓ | 2 |
| `digital_only` | ✓ | ✓ | — | — | — | — | 2 |
| `slots_requested` | ✓ | — | — | — | — | — | 1 |
| `seconds_per_minute` | ✓ | — | — | — | — | — | 1 |
| `audience_segments` (named, plural) | — | — | — | — | ✓ | — | 1 |
| `audience_gender` | — | — | — | — | — | ✓ | 1 |
| **`start_date` / `end_date`** | — | — | — | — | — | — | **0** |
| **client present in `client_facts`** | — | — | — | — | — | — | **0** |

### The two rows that matter most

**`start_date` = 0/6.** Not one brief states a bookable date range. What they give is
prose: *"Q1 2027 — pre-monsoon launch window"*, *"Exam season / Fall semester"*,
*"Autumn Collection Launch"*, *"New-outlet launch window"*, *"Route-launch window,
Q2 2027"*, *"Spring product launch"*. Only briefs 1 and 5 narrow to a quarter.

Yet a date range is required by availability lookup, committed-occupancy scarcity,
event-surge matching and the footfall forecast — four of the five engines. **The
clarification loop is therefore not an edge case: it fires on 100% of real briefs.**
Phase 4 §4.3 must be built as a first-class path, and the demo should show it,
because there is no brief in which it can be skipped.

**Client in `client_facts` = 0/6.** All 520 accounts carry generic synthetic names
("Drive Motors", "Fresh Beverages", "Drive Dealerships"); none of the six brief clients
matches on any token. Every supplied brief is a **new prospect**, so
`client_tier`, `negotiation_leverage`, `typical_campaign_budget`, `bundle_affinity`,
`preferred_geographies`, `active_cities` and `relationship_start_date` are **all null
for every acceptance scenario we have.**

That directly undercuts Phase 6 §6.3's "client-relationship adjustment (tier,
leverage, history)" and §6.4's win-probability model, which is calibrated on client
leverage. Neither term has an input on any real brief. Two consequences:

- The pricing ladder needs an explicit **new-prospect rung** with its own default
  leverage assumption and a stated confidence, exactly parallel to the cold-start
  screen ladder.
- Any demo of the client-relationship adjustment must use a synthetic brief naming a
  real `client_facts` account. Worth building one deliberately rather than discovering
  the gap on stage.

## 3. The `CampaignBrief` schema

Two layers, matching the split already established in `briefs.py`: what the document
**states** (verbatim, lossless) and what we **resolve** it to (bound to data entities,
with confidence). Resolution never overwrites the raw value.

```
CampaignBrief
├─ provenance
│  ├─ source_file: str                      # 6/6 — audit trail
│  ├─ brief_number: int | None              # 6/6 — from the title line
│  └─ raw_sections: [BriefSection]          # 6/6 — lossless, nothing dropped
│
├─ client                                   # ── who is buying
│  ├─ client_name: str                      # REQUIRED, 6/6 header
│  ├─ brand: str | None                     # 1/6 explicit ("Brand: Zephyr EV"); else from title
│  ├─ client_id: str | None                 # RESOLVED — null on 6/6 (all new prospects)
│  └─ is_new_prospect: bool                 # derived; TRUE on 6/6 → pricing ladder rung
│
├─ commercial                               # ── the deal envelope
│  ├─ budget_amount: float                  # REQUIRED, 6/6
│  ├─ currency: str                         # REQUIRED, 6/6 (USD throughout)
│  ├─ duration_days: int                    # REQUIRED, 6/6
│  ├─ window_hint: str                      # REQUIRED, 6/6 — prose, never a date
│  ├─ start_date: date | None               # 0/6 → clarification trigger
│  └─ end_date: date | None                 # 0/6 → derived from start + duration
│
├─ intent                                   # ── what success means
│  ├─ industry_vertical_raw: str            # REQUIRED, 6/6
│  ├─ industry_vertical: Vertical | None    # RESOLVED to 1 of 13; 2/6 bind by token
│  ├─ industry_vertical_secondary: … | None # needed by B6 (retail + cpg)
│  ├─ objective_raw: str                    # REQUIRED, 6/6
│  ├─ objective_primary: Objective          # RESOLVED to 1 of 4
│  └─ objective_secondary: Objective | None # 5/6 are COMPOUND — see §5.2
│
├─ audience                                 # ── who we must reach
│  ├─ target_audience_raw: str              # REQUIRED, 6/6
│  ├─ age_min / age_max: int                # REQUIRED, 6/6 — all "(Ages N-M)"
│  ├─ descriptors: [str]                    # 6/6 — soft, from header + §2
│  ├─ segments: [AudienceSegment]           # 1/6 explicit (B5: business + leisure)
│  └─ gender: str | None                    # 1/6 (B6) — PARSED BUT UNMODELLABLE
│
├─ inventory                                # ── what to buy
│  ├─ city_id: str | None                   # 3/6, ALL from §1 prose → clarification on 3
│  ├─ city_scope: one_city | network | ambiguous   # B3 is ambiguous
│  ├─ environment_requirements: [Requirement]      # REQUIRED, 6/6, 2–3 each
│  │    └─ Requirement{ label, prose, priority_tier, bindings[], confidence }
│  ├─ exclusions: [Exclusion]               # 2/6 labelled — EMPTY IS VALID, not missing
│  ├─ soft_negatives: [str]                 # 2/6 — penalty, never a filter
│  └─ outlet_anchor: str | None             # B4 only — blocking if absent
│
├─ delivery                                 # ── how it runs
│  ├─ daypart_weighting: [DaypartWeight]    # 4/6
│  ├─ day_type_weighting: [DayTypeWeight]   # B3 (Fri–Sun), B6 (pre-weekend)
│  ├─ slots_requested: int | None           # 1/6 → otherwise a D4 DECISION VARIABLE
│  ├─ seconds_per_minute: int | None        # 1/6 — unverifiable, see §6 gap 12
│  ├─ digital_only: bool | None             # 2/6 — vacuous, see §6 gap 5
│  └─ creative_format: CreativeFormat       # 6/6 — aspect ratio UNENFORCEABLE
│
├─ deliverables
│  └─ rfp_requirements: [str]               # REQUIRED, 6/6 × 3 = 18 total
│
└─ resolution                               # ── honesty layer, cross-cutting
   ├─ unresolved_requirements: [Unresolved] # what we could not bind, and why
   ├─ proxies_applied: [Proxy]              # substitution + confidence + rationale
   └─ clarifications_needed: [Question]     # with the default we would otherwise use
```

### Field-by-field justification

| Field | Why it exists | Evidence |
|---|---|---|
| `client_name`, `campaign_title` | Present in every brief; the only client identity we get | 6/6 |
| `is_new_prospect` | 0/6 clients exist in `client_facts` — the pricing model must handle this as the *normal* case, not the exception | 0/6 matched |
| `budget_amount` + `currency` | Hard ceiling in every brief; all USD, but currency is explicit so a new market does not silently mis-scale | 6/6 |
| `duration_days` | Stated in every brief; drives the slot-day denominator | 6/6 |
| `window_hint` **separate from** `start_date` | Every brief gives prose, none gives dates. Conflating them would fabricate a bookable window | 6/6 vs 0/6 |
| `city_id` nullable + `city_scope` | Stated in only 3, and always in §1 prose, never in the header. Nullable is the honest type; B3 needs a third state ("network's largest" vs "citywide") | 3/6 |
| `objective_secondary` | 5/6 objectives are compound; the data has one objective per booking, so the mapping is 1→N | 5/6 |
| `industry_vertical_secondary` | B6 (Beauty) straddles `retail` and `cpg`; forcing one value discards signal | 1/6 |
| `age_min` / `age_max` as ints | Universally stated as "(Ages N-M)". 5/6 straddle demographic bands, so a fractional-overlap rule is required, not bucket matching | 6/6 |
| `segments: [AudienceSegment]` | B5 defines two overlapping groups and §5 demands separate per-segment output. A flat descriptor cannot carry it | 1/6 |
| `gender` | Stated in B6, **no data support anywhere**. Kept in the schema so it can be reported as *not modelled* rather than silently lost | 1/6 |
| `environment_requirements` as objects | 2–3 per brief, each a label + prose + bindings + confidence. Flattening to strings loses the per-requirement resolution status that the response must show | 6/6 |
| `priority_tier` on requirements | B5 and B6 rank their own asks ("supplementary"). Equal weighting would contradict the client | 2/6 |
| `exclusions` distinct from `soft_negatives` | B1/B4 use labelled `Exclusion Criteria` (hard); B3/B6 bury directional preferences in prose (soft). Promoting the latter to filters would wrongly empty inventory | 2/6 + 2/6 |
| `exclusions == ()` is valid | 4/6 briefs state none. The filter must distinguish "no exclusions" from "not parsed" | 4/6 |
| `outlet_anchor` | B4's entire eligibility rule depends on a point the brief never identifies | 1/6 |
| `slots_requested` nullable | Stated once. In the other 5 briefs slots are a **decision variable** for the optimiser — a key modelling fact, not an omission | 1/6 |
| `creative_format` | Every brief specifies an aspect ratio and static/motion. None is enforceable against `screens` | 6/6 |
| `unresolved_requirements`, `proxies_applied`, `clarifications_needed` | 6/6 briefs contain at least one unbindable requirement. Making these first-class fields is what stops the pipeline from silently substituting | 6/6 |

## 4. Hard vs soft — the classification rule

Derived from the corpus, not assumed:

**Hard** (eligibility filter; violation invalidates a package)
budget ceiling · flight duration · `city_id` once known · labelled `Exclusion Criteria`
· B4's walking-radius exclusion · stated slot count when given.

**Soft** (relevance score; direction and weight)
environment/POI character · audience affinity · daypart and day-type weighting ·
dwell-time preference · premium positioning · prose negatives · creative-format fit ·
priority tiers.

**Vacuous** (states a constraint that excludes nothing — must never be allowed to empty
the candidate set)
`digital_only` — every screen in the catalogue is digital.

**Unmodellable** (stated, retained, reported as not modelled)
`gender` · beauty-counter adjacency · dealership adjacency · airport corridor ·
academic calendar.

## 5. Findings that change the plan

### 5.1 The clarification loop fires on every brief

0/6 briefs state a date range; 3/6 omit the city; 1/6 omits the outlet its entire
eligibility rule depends on. Phase 4 §4.3 is on the critical path for **all six**
acceptance scenarios, not a defensive extra.

### 5.2 Objectives are compound; the data's are not

`bookings.campaign_objective` has exactly four values (awareness, conversion,
frequency, reach), one per booking. But 5/6 briefs state two intents at once
("Awareness **&** Test-Drive Bookings", "Seasonal Footfall **&** Sale Awareness"). Only
brief 6 is single-objective. And brief 2's `frequency` intent is stated in §5 (the RFP
section), not the objective header — an extractor reading only the header misses the
biggest lever on that package's shape.

So `config/scoring.yaml` weights must be keyed on a **(primary, secondary)** pair, and
Phase 5 §5.2's "objective fit" component needs to blend two objective profiles.

### 5.3 Every brief is budget-bound, and the ratios are extreme

Using `lost_leads.quoted_price_per_slot_per_day` as the only available price anchor
(**biased high** — these are deals that died, 305 of 1,450 on `price_too_high`;
medians LH 98.08 / DAT 62.64 / ACS 39.21):

| # | Budget | Days | $/day | Screens @ 1 slot | Candidate pool | Selection ratio |
|---|---|---|---|---|---|---|
| 1 | $40,000 | 45 | 889 | ~9 (LH) | 677 | ~1.3% |
| 2 | $12,000 | 21 | 571 | ~6 LH / ~15 ACS | 62–92 bus-rear | ~10% |
| 3 | $22,000 | 20 | **1,100** | ~11 (LH) | 541 | ~2% |
| 4 | $9,000 | 15 | 600 | ~6 (LH) | **3–34** | **eligibility-bound** |
| 5 | $35,000 | 40 | 875 | ~9 (LH) | 354 | ~2.5% |
| 6 | $20,000 | 25 | 800 | ~8 (LH) | 626 | ~1.3% |

Two structural consequences:

- **Packages are 5–15 screens, not hundreds.** Against 11,163 screens, the optimiser's
  job is severe selection, so relevance ranking carries almost all the value and the
  submodular reach objective operates in a small-k regime. Phase 7's solver should be
  sized for small-k selection over a pruned candidate set — which also makes the
  ILP/exact path far more affordable than the raw sellable-unit count suggests.
- **Brief 4 inverts.** If its outlet anchors a bus stop, the eligible set (3 screens,
  since *every* bus stop in the network carries exactly 3) is smaller than the budget
  affords (~6). Eligibility binds, not budget — and the correct response is more slots,
  a longer flight, or a stated relaxation, never ineligible inventory.

### 5.4 `time_block 1` is sellable inventory with no transit service

Measured from `route_schedules`: **zero scheduled trips depart between 00:00 and
03:59**, network-wide. Blocks 2–6 carry 2,763 / 4,815 / 4,092 / 5,325 / 2,843 trips.
Yet `dim_slot` sells block 1 and `bookings.time_block_id` spans 1–6.

Brief 2 asks for "late evening through **early morning**", i.e. blocks 6 and 1. For
mobile screens, block-1 exposure is genuinely zero — the vehicles are in the depot. The
exposure model must not interpolate a plausible-looking number into a block with no
service, and the pricing model should price block 1 accordingly.

### 5.5 Weekend delivery contradicts brief 3's premise

Measured over all 2,049,632 `ridership_actuals` rows: Sat+Sun mean ridership is
**0.332×** the Mon–Thu baseline (LH 0.346 · DAT 0.323 · ACS 0.311), with roughly half
the scheduled service. Friday is the strongest day of the week at **1.08×**. Holidays
run at 0.54×.

Brief 3 requests Friday-evening-through-Sunday weighting "aligned with peak
discretionary shopping behaviour". Transit exposure says that window delivers about a
third of the audience per slot, and **POI footfall has no day-of-week dimension**, so
the shopping-behaviour premise cannot be evidenced from the data at all. The response
must quantify the trade-off and attribute the premise to the client.

### 5.6 Mobile screens need the corridor path for any spatial language

All 2,615 vehicle-mounted screens have `location_id = NULL`, so they have no zone, no
demographics and no POI adjacency by the static path. Brief 2's primary ask — bus-rear
screens on nightlife routes — is only satisfiable through
`screens.vehicle_id → vehicles.corridor_id → route_stops.corridor_id → location_id → POI`,
which crosses a **documented N:N fan-out trap**. Measured with locations aggregated per
corridor first: 62 of 135 LH bus-rear screens (46%), 85 of 132 ACS (64%), 92 of 138 DAT
(67%) sit on a corridor traversing an `entertainment_district` POI.

The same fact makes these screens the textbook overlap case: 62 LH screens on just 21
corridors, so naive reach summation would inflate by roughly 6×.

### 5.7 Two briefs fall outside the data horizon

| Table | Latest date |
|---|---|
| `ridership_actuals` | 2026-08-19 |
| `events` | 2027-02-19 |
| `bookings` | 2027-02-21 *(per data dictionary; file currently absent)* |

Brief 1's Q1 2027 window runs past all of them at the tail; **brief 5's Q2 2027 window
falls entirely beyond every table.** For brief 5 there is zero committed occupancy,
zero event coverage and zero ridership observation — so "no competition" would be an
artefact of the horizon, not a market fact.

Phase 6 §6.5's fallback ladder substitutes *other screens* for a screen with no
history. Here the screens have history and the **dates** do not. A **parallel temporal
ladder** is needed (same screen/other window → same day-type & daypart profile →
city seasonal baseline → flat rule), with the extrapolation distance stated on the
quote. This is a genuine addition to the plan.

### 5.8 Sellable time grain is coarser than three briefs' targets

4-hour blocks cannot express an 11:00–14:00 lunch window (brief 4: buy blocks 3+4 and
waste 62% of delivery, or buy block 4 and lose an hour of the target), "Friday
evening" as distinct from Friday (brief 3), or "late evening through early morning"
without crossing the dead block 1 (brief 2). This is a fixed property of `dim_slot`,
so the honest move is to report coverage-versus-target explicitly rather than imply
precision the product does not have.

## 6. Capability register — what the briefs demand and the data cannot give

The Step 1.8 criterion: *note explicitly which briefs demand things the data may not
directly support — each becomes a required capability, not a surprise during the demo.*

| # | Gap | Briefs | Severity | Required capability |
|---|---|---|---|---|
| 1 | **No coordinates anywhere.** `locations` has no lat/long/address; the only distance field is `points_of_interest.distance_to_location_km` (POI→its own anchor) | **4** | **Blocking** | Radius reasoning via the POI anchor graph only; clarification question to identify the anchor; never claim computed walking distance |
| 2 | **No airport / aviation / transport-terminal POI type.** 0 rows network-wide mention one; the 50 "Terminal" locations are metro termini | **5** | **Unsatisfiable** | Unresolved-requirement reporting + labelled proxy ladder (`hotel_convention` → hub → top corridor) |
| 3 | **No dealership / auto-retail POI type** | **1** | **Unsatisfiable** | Proxy via historical `industry_vertical='auto'` density (needs `bookings.csv`) + arterial bus corridors |
| 4 | **No gender field in any table** (`zone_demographics` has 15 columns, none about sex) | **6** | **Unmodellable** | Parse, retain, and report as *not modelled*; substitute context (retail adjacency), never a gender-derived figure |
| 5 | **No aspect ratio / orientation / resolution on `screens`** (7 columns; `screen_size` is S/M/L only). Every brief states a format | **1–6** | High | `screen_size` proxy with stated confidence; `digital_only` recognised as vacuous and prevented from emptying the candidate set |
| 6 | **No mall tenant / concession / retail-category data.** `poi_type` stops at `shopping_mall` | **3, 6** | High | Phase 3 §3.3 semantic environment labels from controlled vocabulary + evidence, then semantic matching (Phase 5 §5.3) |
| 7 | **`market_tier` is city-grain** (one city per tier), so there is no within-city inventory tier | **1** | High | Derived zone-level tier (income index × density × occupation), surfaced and confirmable |
| 8 | **4-hour time blocks** cannot express sub-block targets | **2, 3, 4** | Medium | Report coverage-vs-target per block; do not imply hour-level precision |
| 9 | **`time_block 1` has zero scheduled trips** but is sellable | **2** | High | Exposure model must return zero (not interpolate) for mobile inventory; price accordingly |
| 10 | **Mobile screens have no `location_id`** (2,615 of 11,163) | **2** | High | Corridor-traversal path with per-corridor location aggregation before joining (N:N trap) |
| 11 | **Data horizon**: ridership → 2026-08-19, events → 2027-02-19, bookings → 2027-02-21 | **1, 5** | High | Temporal fallback ladder + widened confidence bands + stated extrapolation distance |
| 12 | **No slot-duration column in `dim_slot`**, so "15 seconds per minute" cannot be reconciled to `slots_booked_per_day` (6 looping slots imply ~10 s each ⇒ the ask is ~1.5 slots) | **1** | Medium | Record as stated, convert with an explicit documented assumption |
| 13 | **No day-of-week dimension on POI footfall** (`est_daily_footfall` is one daily average) | **3, 6** | Medium | Weekend/weekday intent attributed to the client; only ridership carries day-of-week |
| 14 | **No academic calendar** | **2** | Low | Resolve via daypart weighting + a client-supplied window |
| 15 | **No gym / fitness POI type** | **2** | Low | Audience descriptor only; no inventory binding |
| 16 | **`entrance_exit` exists only on `metro_station`** (1,275 screens) | **3, 6** | Medium | Describe "mall entry" accurately as a metro entrance near a mall |
| 17 | **`stadium_arena` = 1 POI per city** (3 network-wide) | **2** | Medium | "Precincts" (plural) unsatisfiable as stated; reconcile against the bus-rear ask |
| 18 | **Weekend ridership 0.33× weekday** — contradicts the stated premise | **3** | Medium | Quantify the trade-off; offer the Friday-weighted alternative |
| 19 | **No client in `client_facts`** for any brief | **1–6** | High | New-prospect rung in the pricing ladder; a synthetic brief naming a real account to exercise the relationship adjustment |
| 20 | **`bookings.csv` absent from the raw folder** (191,109 rows per the dictionary) | **1–6** | **Blocking downstream** | Restore before Phase 6; historical priors, occupancy and the auto-vertical proxy all depend on it |

## 7. `config/taxonomy.yaml` — required synonym coverage

The notebook found 4 verticals and 2 objectives with no binding. The gold parses
sharpen that into the full requirement:

### Verticals (13 data values: auto, cpg, education, entertainment, finance, government, healthcare, hospitality, nonprofit, real_estate, retail, technology, telecom)

| Brief | Stated | Resolves to | Confidence |
|---|---|---|---|
| 1 | AUTOMOTIVE / ELECTRIC VEHICLES | `auto` | **high** — token match |
| 3 | RETAIL / FASHION | `retail` | **high** — token match |
| 2 | FMCG / BEVERAGES (ENERGY DRINKS) | `cpg` | medium — FMCG ≡ CPG, no token overlap |
| 4 | FOOD & BEVERAGE / QSR | `hospitality` | **low** — no clean home in the vocabulary |
| 5 | TRAVEL & AVIATION | `hospitality` | **low** — no clean home |
| 6 | BEAUTY & PERSONAL CARE | `retail` + `cpg` | **low** — genuinely straddles two |

Only **2 of 6** bind by token match. The taxonomy must support many→one synonyms *and*
primary/secondary pairs, and must record a confidence per mapping — a low-confidence
vertical mapping should visibly weaken the segment-heat demand signal that depends on it.

### Objectives (4 data values: awareness, conversion, frequency, reach)

| Brief | Stated | Primary | Secondary |
|---|---|---|---|
| 1 | Brand Awareness & Test-Drive Bookings | `awareness` | `conversion` |
| 2 | Trial & Impulse Purchase | `conversion` | `frequency` *(from §5, not the header)* |
| 3 | Seasonal Footfall & Sale Awareness | `conversion` | `awareness` |
| 4 | Lunch-Hour Footfall & Local Recall | `conversion` | `awareness` |
| 5 | New Route Awareness & Bookings | `awareness` | `conversion` |
| 6 | New Product Launch Awareness | `awareness` | — |

**`reach` is never requested by name** in any brief, though brief 2's RFP asks for a
"reach plan" while explicitly preferring frequency. Note also that no brief maps to
`reach` as a primary objective, so scoring weights for that value cannot be validated
against any real brief.

### Environment vocabulary → `poi_type` / zone attributes

| Brief language | Binds to | Confidence |
|---|---|---|
| business / financial district | zone `daytime_population_multiplier > 3` + `dominant_occupation = white_collar` | high |
| metro platform | `screen_type = metro_station` + `position = platform` | high |
| bus-rear | `screen_type = bus` + `position = back` | high |
| nightlife / entertainment corridor | `poi_type = entertainment_district` (+ corridor path for mobile) | high |
| campus edge | `dominant_occupation = student` / `poi_type = university` | high |
| high-street retail | `dominant_occupation = retail_service` | high |
| mall entry | major/flagship `shopping_mall` + `position = entrance_exit` | high *(with the metro-entrance caveat)* |
| stadium / arena precinct | `poi_type = stadium_arena` (1 per city) | high but tiny |
| business park / food court | `poi_type ∈ {office_park, corporate_campus}` | high for the POI, none for "food court" |
| high-density residential | zone density + `residential_tower` POIs | medium |
| airport corridor | — | **none** |
| dealership corridor | — | **none** |
| beauty counter / concession | — | **none** |

## 8. Clarification-loop triggers, per brief

| Brief | Blocking question | Stated default if unanswered |
|---|---|---|
| 1 | Start date within Q1 2027? Confirm the "value-tier residential" rule we derived | Q1 2027 start; derived zone-tier proxy |
| 2 | **Which city?** Start date in the fall window? | ACS (value tier fits the smallest budget; highest nightlife share of bus-rear) |
| 3 | One city or a network-wide flagship buy? Sale dates? | LH (largest 2 malls, 93 of 225 mall POIs) |
| 4 | **Which office park / corporate campus is the outlet in?** Launch date? | **None — do not proceed.** 55 candidate POIs in the LH business district; a guess would invalidate the entire eligibility rule |
| 5 | **Which corridor is "the airport access corridor"?** Q2 2027 start date? | `hotel_convention`-adjacent premium-core inventory, labelled as a substitution |
| 6 | Which city? Spring launch dates? | LH (90 mall-entry screens vs 9 in ACS) |

Brief 4 is the only genuinely **blocking** case in the plan's sense — proceeding under
any assumption makes the output wrong rather than merely uncertain.

## 9. Acceptance-scenario coverage of the named nuances

Which brief exercises which problem-statement nuance — the input to Phase 2.5.

| Nuance | Exercised by | How |
|---|---|---|
| Non-linear impressions vs slots | **1** | Only brief stating slots + seconds/minute; ~1.5-slot ask |
| Demand inferred from leads/events | **2** | 109 events at stadium POIs, 82 `weekly_season` needing expansion |
| Explainability | **6**, **4** | B6 demands reasoning per *node type*; B4 demands the radius rule stated |
| Cold start / no history | **5** | Temporal cold start — window beyond every table |
| Shared audience on a route | **2**, **6** | 62 bus-rear on 21 corridors; 108 co-located mall+retail screens |
| Bundle = one deal | **2**, **3** | B2 "combining" mobile+static; B3 potential cross-city flagship buy |
| Signal ageing / lead expiry | **none** | ⚠ No brief exercises it — needs a synthetic scenario |
| Scaling to new cities | **2**, **3**, **6** | City unstated ⇒ resolution must be config-driven, not hardcoded |

Two coverage holes worth closing deliberately: **lead-signal ageing** and the
**client-relationship price adjustment** (§2) have no real-brief scenario. Both should
get a purpose-built synthetic brief rather than being demoed on faith.

## 10. Step 1.8 exit criteria

| Criterion (from the plan) | Status |
|---|---|
| Every brief hand-extracted into a table: client, industry, objective, audience incl. age band, budget, duration, start window, location/environment requirements, exclusions, slot/rotation request, creative constraints, RFP deliverables | **Met** — §1, §2 and the six gold-parse files |
| Generalised: which fields are always present, which optional, which are soft preferences vs hard constraints | **Met** — §2 presence matrix, §4 classification |
| A `CampaignBrief` schema justified field-by-field against the real briefs | **Met** — §3 |
| A hand-written gold parse of each brief as the Phase 4 test fixture | **Met** — 6 files, each with an acceptance-assertion list |
| Explicit note of what the briefs demand that the data may not support | **Met** — §6, 20 entries with brief references and severity |
| Each such demand becomes a required capability, not a demo surprise | **Met** — §6 right-hand column |

## 11. What Phase 4 (and Phases 5–7) inherit

| Artifact | Consumed by |
|---|---|
| §3 `CampaignBrief` schema | Phase 2.1 domain types; Phase 4.1 extraction target |
| Six gold parses + 61 acceptance assertions | Phase 4 extractor tests; Phase 2.5 scenarios |
| §7 taxonomy requirements | `config/taxonomy.yaml` — a **hard prerequisite** for Phase 4.2 |
| §6 capability register | Phase 3/5/6 required capabilities; the "unresolved requirement" UI surface |
| §8 clarification triggers | Phase 4.3 — fires on 6/6 briefs |
| §9 nuance coverage map | Phase 2.5 acceptance suite + demo script |
| §5.3 budget envelopes | Phase 7 solver sizing (small-k selection, 5–15 screens) |
| §5.7 temporal-ladder requirement | An addition to Phase 6 §6.5 |

**Immediate next steps**

1. **Transcribe the gold parses into machine-readable fixtures** —
   `tests/fixtures/briefs/campaign_{1..6}.yaml` — so Phase 4 can assert against them
   in CI. These markdown files stay the human-authoritative source.
2. **Draft `config/taxonomy.yaml`** from §7 before any Phase 4.2 resolution work.
3. **Restore `bookings.csv`** (gap 20) — it blocks the historical priors that briefs 1
   and 3 both lean on, and `scripts/build_data_dictionary.py` cannot currently run.
4. **Write the two synthetic briefs** identified in §9 (lead ageing; a named
   `client_facts` account).
5. Amend the plan in writing per Step 1.9 for: the temporal fallback ladder (§5.7), the
   new-prospect pricing rung (§2), and compound-objective scoring weights (§5.2).
