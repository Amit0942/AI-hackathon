# Gold Parse — Brief 5: SkyNimbus Airlines, "Fly Further, Feel Closer"

> **Hand-written, authoritative.** Step 1.8 gold fixture for
> `Campaigns/campaign_5.docx`. The Phase 4 extractor is tested against this file.

*Source:* `Campaigns/campaign_5.docx` · 30 paragraphs · 5 sections · brief number 5
*Parser status:* all 6 header fields, all 5 sections, 3 RFP items, **0 unparsed paragraphs.**

Two firsts in this brief, and both are structural:

- Its **highest-priority environment does not exist in the data.** There is no airport
  anywhere in the network — not a POI, not a POI type, not a location, not a name.
- Its flight window falls **entirely beyond the horizon of every table**. This is a
  cold start on the *time* axis, not the screen axis, and the fallback ladder as
  currently specified does not cover it.

---

## 1. Stated header fields (verbatim)

| Label | Verbatim value |
|---|---|
| Company Name | `SkyNimbus Airlines Ltd.` |
| Industry Vertical | `TRAVEL & AVIATION` |
| Campaign Objective | `New Route Awareness & Bookings` |
| Target Audience | `Frequent flyers, business and leisure travelers (Ages 28-55)` |
| Campaign Budget | `USD 35,000` |
| Campaign Duration | `40 Days (Proposed: Route-launch window, Q2 2027)` |

## 2. Gold parse → `CampaignBrief`

| Field | Gold value | Source | Confidence |
|---|---|---|---|
| `client_name` | SkyNimbus Airlines Ltd. | header | high |
| `brand` | SkyNimbus | title | high |
| `industry_vertical_raw` | TRAVEL & AVIATION | header | high |
| `industry_vertical` | `hospitality` | taxonomy — nearest of the 13 values | **low — no token overlap; aviation has no home in the vocabulary** |
| `objective_raw` | New Route Awareness & Bookings | header | high |
| `objective_primary` | `awareness` | taxonomy | high |
| `objective_secondary` | `conversion` | taxonomy — §1 "secondary goal of driving direct bookings via the airline's app" | high |
| `target_audience_raw` | Frequent flyers, business and leisure travelers (Ages 28-55) | header | high |
| `age_min` / `age_max` | 28 / 55 | header | high |
| `audience_segments` | **two distinct, overlapping groups** — frequent business travellers; higher-income leisure travellers (§2) | §2 | high |
| `audience_descriptors` | frequent flyer, business traveller, leisure traveller, higher-income, advance planner, predictable-schedule commuter | header + §2 | high |
| `budget_amount` / `currency` | 35000.0 / USD | header | high |
| `duration_days` | 40 | header | high |
| `window_hint` | "Route-launch window, **Q2 2027**" | header | high — the most precise window in the set |
| `start_date` / `end_date` | **null / null** (Q2 2027 ⇒ 2027-04-01 … 2027-06-30) | derived, not stated | medium |
| `city_id` | `LH` (Las Hackland) | **§1 prose** — "twelve new international direct routes from Las Hackland" | high |
| `slots_requested` | null | not stated | — |
| `digital_only` | null (not stated) | — | — |
| `creative_format` | 16:9 wide-format, "premium wide-format"; motion asset | §3 + §4 | high |
| `daypart_weighting` | none stated; §2 implies commute predictability | — | low |
| `exclusions` | **none stated** | — | high |
| `environment_requirements` | 3 (see §5) | §3 | high |
| `rfp_deliverables` | 3 (see §7) | §5 | high |

**Extractor note.** `audience_segments` is a field the other five briefs do not need.
§2 explicitly defines *two overlapping groups* on the same inventory ("The audience
splits into two overlapping groups… Both groups pass through…"), and §5 item 3 then
demands separate estimates for each. A single flat audience descriptor cannot carry
that; the schema needs a list of named segments with per-segment output.

## 3. There is no airport in this dataset

§3's first and highest-priority requirement:

> *Airport Transit Corridor: Premium wide-format screens along the primary airport access corridor — the single highest-relevance environment for a travel campaign, reaching an audience already in a travel mindset.*

Measured, exhaustively:

- **0 rows** across `locations` and `points_of_interest` contain any of *airport,
  aviation, airline, airfield, aerodrome* in any field.
- The 13 `poi_type` values are `corporate_campus`, `entertainment_district`,
  `government_building`, `grocery_anchor`, `hospital`, `hotel_convention`, `museum`,
  `office_park`, `residential_tower`, `shopping_mall`, `stadium_arena`,
  `tourist_landmark`, `university`. **No aviation, transport-terminal or
  intercity-gateway category exists.**
- The 50 locations whose name contains "Terminal" are the metro terminus naming
  convention (`<Zone> Terminal`, e.g. `Financial Row Terminal`), all with
  `location_type = 'metro_station'`. **Not airports.**
- No corridor stands out as a "primary access" route either. The top six LH metro
  corridors by measured ridership are within **2%** of each other
  (15.44M / 15.44M / 15.36M / 15.29M / 15.20M / 15.14M total riders), so there is no
  dominant trunk line to nominate even by volume.

**This is an unresolved requirement, and it must be reported as one.** The brief calls
it "the single highest-relevance environment", so silently substituting something else
and presenting the result as fulfilment would be the worst available outcome.

Proxy ladder, in descending defensibility — to be offered *labelled*, with the
client's own words quoted back and the substitution stated:

| Rank | Proxy | Measured (LH) | Confidence |
|---|---|---|---|
| 1 | Ask the rep to name the corridor or terminus, then bind directly | — | high once answered |
| 2 | `hotel_convention` POI adjacency — travellers with luggage and intent | 29 POIs (13 flagship/major) · 632 screens | medium |
| 3 | `is_network_hub = True` POI adjacency — interchange-scale nodes | 101 anchor locations · 3,383 screens | low — 46% of all POIs are flagged hubs, so this barely discriminates |
| 4 | Highest-ridership metro corridor (`LH-RT-M005`, 15.44M riders, 17 stops, 725 static screens) | — | low — indistinguishable from the next five |
| 5 | `tourist_landmark` adjacency — leisure-traveller context | 21 POIs · 574 screens | low |

Recommended: **rank 1 as a clarification question**, with rank 2 offered as the stated
interim assumption. `hotel_convention` is the only POI type in the schema whose
semantics genuinely imply travel.

## 4. Hard constraints vs soft preferences

**Hard:** `city_id = LH` · budget ceiling USD 35,000 · 40-day flight · Q2 2027 window.

**Soft:** airport-corridor adjacency (unresolvable — see §3) · premium business-core
character · financial-district metro nodes · wide-format premium screens · repeated
exposure for the business segment · aspirational/premium positioning.

No exclusions are stated; the eligibility filter must not invent any.

## 5. Environment requirements — measured bindings

### 5.1 "Airport Transit Corridor"

See §3. **No binding.** Unresolved requirement + proxy ladder + clarification question.

### 5.2 "Premium Business Core"

> *Screens across the city's premium commercial core, reaching frequent business travellers on their daily commute.*

Binds to the same LH zones as briefs 1 and 4 — `daytime_population_multiplier > 3`
and `dominant_occupation = 'white_collar'`: **Downtown Core** (3.39, income index
141.7) and **Financial Row** (3.21, 159.8). Confidence: **high**.

Measured pool — 995 LH premium-core static screens:

| Cut | Count |
|---|---|
| By size | M 406 · **L 354** · S 235 |
| `metro_station` / `platform` | 677 |
| `metro_station` / `entrance_exit` | 168 |
| `bus_stop` (top / left / right) | 50 each = 150 |

"**Premium wide-format**" has no direct binding — `screens` carries no aspect ratio,
orientation or resolution. `screen_size = 'L'` is the only available proxy, giving
**354** candidates. Confidence in the proxy: **medium**; it plausibly correlates with
physical width but is a three-value ordinal, not a format.

### 5.3 "Financial District Coverage"

> *Supplementary placement at major financial-district metro nodes for repeated business-traveller exposure across the campaign window.*

Binds to `zone_name = 'Financial Row'` (LH-ZONE-005, income index **159.8** — the
highest in LH) with `screen_type = 'metro_station'`. Confidence: **high**.

Note the word **"supplementary"**: this is explicitly a tier-3 priority behind the
airport corridor and business core. The scorer should carry that stated priority
ordering rather than treating the three requirements as equal weights — this is the
only brief that ranks its own asks.

"Repeated exposure" makes this a **frequency** requirement on a subset of inventory
while the campaign objective is awareness (reach) overall — a mixed-objective package
within one deal.

## 6. The temporal cold start

Q2 2027 = 2027-04-01 … 2027-06-30. Measured horizons:

| Table | Latest date | Gap to flight start |
|---|---|---|
| `ridership_actuals` | `max(date) = 2026-08-19` | **~7.5 months before** |
| `events` | `max(end_date) = 2027-02-19` | ~1.4 months before |
| `bookings` | `max(end_date) = 2027-02-21` (per the data dictionary) | ~1.3 months before |

So for this flight there is **zero committed occupancy, zero event coverage and zero
ridership observation**. Consequences:

- **Scarcity cannot be measured.** Committed occupancy is the strongest honest demand
  signal in Phase 6 §6.1, and here it is empty — not low, *absent*. A demand index
  that reads "no competition, price at floor" would be an artefact of the data
  horizon, not a market fact.
- **Event surge is unknowable.** No events are scheduled that far out. Absence of
  events must not be read as absence of surge risk.
- **Exposure must be extrapolated ~10 months** past the last ridership observation,
  across a season boundary, with no year-over-year history to calibrate seasonality
  (ridership spans a single 6-month window, 2026-02-19 → 2026-08-19).
- **The Phase 6 §6.5 fallback ladder does not cover this.** Its five rungs all
  substitute *other screens* for a screen with no history. Here the screens have
  history; the **dates** do not. A parallel temporal ladder is needed — same
  screen/other window → same day-type/daypart profile → city-level seasonal baseline →
  flat rule — with confidence degraded accordingly and the extrapolation distance
  stated on the quote.

`ridership_actuals` also has no `is_holiday = True` coverage for Q2 2027, so holiday
effects in the window are unmodellable. Every figure for this brief should carry a
visibly wider confidence band than for briefs 2/3/4, and the response should say why.

## 7. Budget envelope

| Quantity | Value |
|---|---|
| Budget | USD 35,000 |
| Flight | 40 days |
| Budget per day | ~USD 875 |
| LH median quoted price/slot/day (`lost_leads`) | 98.08 |
| **Screens affordable at 1 slot/day** | **~9** |
| Candidate pool (premium core, size L) | 354 |
| Selection ratio | ~2.5% |

Premium positioning plus LH's premium market tier means realised prices will sit
**above** the LH median, so ~9 is an optimistic ceiling. With a stated frequency
requirement on the financial-district subset, the honest shape is ~5–7 screens with
multiple slots rather than 9 with one.

## 8. RFP deliverables → owning phase

| # | Stated deliverable | Produced by |
|---|---|---|
| 1 | Curated screen list anchored on the **airport transit corridor** and the premium business core | D2 / Phase 5 — item 1 is partly unsatisfiable; must be flagged |
| 2 | Pricing reflecting premium-corridor demand and **the overlap between the business and leisure traveller audiences** | D3 / Phase 6 + the overlap model |
| 3 | Projected reach across the 40-day window, with **separate estimates for repeat business-traveller frequency and one-time leisure-traveller exposure** | D1 §3.5 reach/frequency split, **per segment** |

Items 2 and 3 together demand something no other brief does: **audience overlap within
a single screen**. Phase 3 §3.4's overlap graph is screen-to-screen; here two segments
share the same inventory, and reach must be de-duplicated *across segments* as well as
across screens, then reported separately per segment — frequency for business, unique
exposure for leisure. That is a genuine extension of the reach model, not a
presentation choice, and it should be sized before Phase 7 rather than discovered in it.

## 9. Capability gaps this brief exposes

| Gap | Consequence |
|---|---|
| **No airport anywhere in the data** | The brief's highest-priority requirement is unsatisfiable; proxy ladder + clarification required |
| **Flight window beyond every table's horizon** | No occupancy, no events, no ridership; needs a *temporal* fallback ladder that Phase 6 §6.5 does not yet specify |
| Ridership covers one 6-month window | No year-over-year seasonality to extrapolate with |
| No aspect-ratio / orientation column | "Premium wide-format" → `screen_size = L` proxy only |
| Travel & Aviation has no home in the 13 verticals | `hospitality` is a low-confidence mapping |
| `is_network_hub` flags ~46% of POIs | Too coarse to isolate a gateway corridor |
| LH corridors are near-identical by ridership | No dominant trunk line to nominate as "primary" |
| Two overlapping audience segments on shared inventory | Requires per-segment reach/frequency output, beyond the current overlap model |
| Brief ranks its own requirements ("supplementary") | Scorer needs stated per-requirement priority, not equal weights |
| Age band 28–55 | Straddles **three** demographic bands (18–34, 35–54, 55+) — needs fractional overlap, not bucket matching |

## 10. Acceptance assertions (Phase 2.5 / Phase 4 fixtures)

1. `city_id == "LH"` — extracted from §1 prose.
2. `budget_amount == 35000.0`, `duration_days == 40`, `age_min == 28`, `age_max == 55`.
3. `industry_vertical_raw == "TRAVEL & AVIATION"` and the resolved vertical is flagged
   low-confidence rather than silently mapped.
4. `audience_segments` has 2 entries (business traveller, leisure traveller).
5. The airport-corridor requirement appears in the response as **unresolved**, with the
   proxy named and the substitution stated. A response that quietly presents
   hub-adjacent screens as "the airport corridor" fails.
6. `exclusions == ()` — empty, not missing.
7. Every price and impression figure for the Q2 2027 window carries a **degraded
   confidence** marker and names the extrapolation distance.
8. The demand index does **not** report "no competition" as a market fact for a window
   with no data.
9. Reach is reported **separately per segment**, with business-segment frequency
   distinguished from leisure-segment unique exposure.
10. The stated priority order (airport → business core → *supplementary* financial
    district) is reflected in the ranking weights.
