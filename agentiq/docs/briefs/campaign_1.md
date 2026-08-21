# Gold Parse — Brief 1: Zephyr EV, "The Future Has No Tailpipe"

> **Hand-written, authoritative.** This is the Step 1.8 gold fixture for
> `Campaigns/campaign_1.docx`. The Phase 4 LLM extractor is tested *against* this
> file; where the two disagree, this file is right. Every binding in §5 is a
> measured count against the raw CSVs, not an assumption.

*Source:* `Campaigns/campaign_1.docx` · 32 paragraphs · 5 sections · brief number 1
*Parser status:* `parse_brief` recovers all 6 header fields, all 5 sections, 3 RFP items.
The 2 paragraphs reported as `unparsed` are the portfolio cover page
("Customer Campaign Briefs" / "Digital Out-of-Home Campaign Portfolio") — this is the
first document in the set and carries the cover. **Benign; not data loss.**

---

## 1. Stated header fields (verbatim)

| Label | Verbatim value |
|---|---|
| Company Name | `Voltaic Motors Inc. (Brand: Zephyr EV)` |
| Industry Vertical | `AUTOMOTIVE / ELECTRIC VEHICLES` |
| Campaign Objective | `Brand Awareness & Test-Drive Bookings` |
| Target Audience | `Urban professionals and eco-conscious upgraders (Ages 28-50)` |
| Campaign Budget | `USD 40,000` |
| Campaign Duration | `45 Days (Proposed: Q1 2027 — pre-monsoon launch window)` |

## 2. Gold parse → `CampaignBrief`

| Field | Gold value | Source | Confidence |
|---|---|---|---|
| `client_name` | Voltaic Motors Inc. | header | high |
| `brand` | Zephyr EV | header, parenthetical | high |
| `industry_vertical_raw` | AUTOMOTIVE / ELECTRIC VEHICLES | header | high |
| `industry_vertical` | `auto` | taxonomy | high — direct token match |
| `objective_raw` | Brand Awareness & Test-Drive Bookings | header | high |
| `objective_primary` | `awareness` | taxonomy | high |
| `objective_secondary` | `conversion` | taxonomy — "Test-Drive Bookings" is a response action | medium |
| `target_audience_raw` | Urban professionals and eco-conscious upgraders (Ages 28-50) | header | high |
| `age_min` / `age_max` | 28 / 50 | header | high |
| `audience_descriptors` | urban professional, eco-conscious upgrader, homeowner, senior professional, car-commuter, high-research buyer | header + §2 | high |
| `budget_amount` / `currency` | 40000.0 / USD | header | high |
| `duration_days` | 45 | header | high |
| `window_hint` | Q1 2027, "pre-monsoon launch window" | header | high |
| `start_date` / `end_date` | **null / null** | not stated | — |
| `city_id` | `LH` (Las Hackland) | **§1 prose, not the header** | high |
| `slots_requested` | 1 | §4 | high |
| `seconds_per_minute` | 15 | §4 | high |
| `digital_only` | true | §4 "on digital screens only" | high |
| `creative_format` | 16:9 ultra-wide; static/motion hybrid | §4 | high |
| `daypart_weighting` | none stated | — | — |
| `exclusions` | 2 (see §4) | §3 | high |
| `environment_requirements` | 2 (see §5) | §3 | high |
| `rfp_deliverables` | 3 (see §7) | §5 | high |

**Extractor trap.** The city is stated only in the §1 prose ("launching the Zephyr EV
… in Las Hackland"), never in a labelled field. An extractor that reads only the
header block loses the single most important eligibility constraint. Same trap in
briefs 4 and 5.

## 3. Hard constraints vs soft preferences

**Hard** (violating one makes a package invalid):

- `city_id = LH`
- Budget ceiling USD 40,000
- Flight length 45 days
- Exclude bus-rear screens
- Exclude value-tier inventory in high-density residential areas
- Digital-only inventory

**Soft** (scoring signals, not filters):

- High platform dwell time
- Business/financial-district character
- Auto-retail corridor proximity
- Affluent-commuter audience affinity
- Premium (non-mass-market) positioning
- 16:9 ultra-wide creative fit

## 4. Exclusions — resolution

| Stated exclusion | Data binding | Screens removed | Confidence |
|---|---|---|---|
| "bus-rear screens" | `screens.screen_type = 'bus' AND screens.position = 'back'` | **135** in LH | high — exact enumerated values |
| "value-tier inventory in high-density residential areas" | **no direct binding** — see below | 2,000 in LH under the proxy | **low** |

`cities.market_tier` is **city-grain** (one city per tier: LH premium, DAT standard,
ACS value). The campaign is in LH, the premium city, so "value-tier inventory" cannot
mean a market tier — there is no within-city inventory tier anywhere in the schema.
A derived zone-level tier is required. Proxy adopted for the gold parse:
`zone_demographics.income_index < 100 AND population_density_per_sqkm > 6000`, which
selects 4 of LH's 10 zones — **Market Quarter, Old Mill District, Riverside Junction,
Uptown Crescent** — covering 2,000 screens.

> This exclusion is a **clarification candidate**, not a silent proxy. The thresholds
> are ours, not the client's; the rep must confirm them, and the chosen rule must be
> shown in the response.

## 5. Environment requirements — measured bindings

### 5.1 "High-Dwell Business-District Platforms"

> *Metro platform boards in the city's primary commercial and financial districts, where affluent professional commuters typically spend three to six minutes waiting on the platform.*

| Element | Binding | Measured |
|---|---|---|
| "metro platform boards" | `screen_type = 'metro_station' AND position = 'platform'` | — |
| "primary commercial and financial districts" | LH zones with `daytime_population_multiplier` > 3 and `dominant_occupation = 'white_collar'` → **Downtown Core** (3.39, idx 141.7), **Financial Row** (3.21, idx 159.8) | 2 zones |
| **Candidate pool** | both conditions | **677 screens** |
| … of which `screen_size = 'L'` (16:9 wide-format fit) | | **229 screens** |
| Comparison: any position in those zones | | 845 screens |

The daytime multiplier is what makes this binding defensible: **Cathedral Heights**
has a *higher* income index (149.4) than Downtown Core but a daytime multiplier of
0.64 — an affluent *residential* zone, not a business district. Income alone would
have selected it wrongly. Confidence: **high**.

"three to six minutes of dwell" is not a data field. `locations.location_type =
'metro_station'` versus `'bus_stop'` is the only dwell proxy available, and it agrees
with the ask. Confidence on the dwell claim itself: **medium** — we can rank platform
above kerbside, but cannot quote minutes.

### 5.2 "Auto-Retail Arterial Corridors"

> *Roadside-adjacent transit screens on major arterial routes with a dense concentration of car dealerships, positioned to intercept shoppers already actively comparing vehicles.*

**No data anchor exists.** The 13 `poi_type` values contain no dealership, car-retail
or automotive category (`shopping_mall`, `grocery_anchor`, `office_park`,
`residential_tower`, `entertainment_district`, `government_building`, `hospital`,
`corporate_campus`, `university`, `hotel_convention`, `museum`, `tourist_landmark`,
`stadium_arena`). A network-wide search for "dealership" returns 0 POI rows.

Proxy ladder for Phase 5, in descending confidence:

1. **Historical auto demand** — screens with prior `bookings.industry_vertical = 'auto'`
   line items, ranked by density. *Blocked: `bookings.csv` is absent from the raw
   folder (see [../data_dictionary.md](../data_dictionary.md)); restore before relying on this.*
2. **Arterial proxy** — `route_stops` with high `num_stops` on `mode = 'bus'`
   corridors, roadside screens at those stops. LH business-district `bus_stop`
   screens: **150**.
3. Roadside-facing positions: `bus_stop` screens at `position ∈ {left, right}` (kerb-
   facing) rather than `top`.

Confidence: **low**. Must surface as an *unresolved requirement* in the response, with
the substitution stated. Do not silently present the proxy as the requested corridor.

## 6. Budget envelope

| Quantity | Value |
|---|---|
| Budget | USD 40,000 |
| Flight | 45 days |
| Budget per day | ~USD 889 |
| LH median quoted price/slot/day (from `lost_leads`) | 98.08 |
| **Screens affordable at 1 slot/day for 45 days** | **~9** |
| Candidate pool (§5.1) | 677 |
| Selection ratio | ~1.3% |

At the requested 15 s/min (≈1.5 slots if a slot is 10 s) the package shrinks to ~6
screens. **The budget, not eligibility, is the binding constraint here** — the
optimiser must choose ~9 of 677, so relevance ranking carries almost all of the
value. Price anchor caveat: `lost_leads` is a lost-deal sample, biased high on price;
it is an order-of-magnitude check, not a price model.

## 7. RFP deliverables → owning phase

| # | Stated deliverable | Produced by |
|---|---|---|
| 1 | Curated shortlist across premium business-district platforms and auto-retail arterial corridors, **ranked by affluent-commuter affinity** | D2 / Phase 5 |
| 2 | Optimal price reflecting premium-node demand, **platform dwell time**, and **proximity to competing dealerships** | D3 / Phase 6 |
| 3 | **Projected weekly impressions** and **test-drive-booking potential**, with logical justification for each recommended location | D1 §3.5 + D4 + narrative |

Two output requirements worth pinning now:

- **"Weekly"** impressions — the response needs a weekly breakdown, not a flight total.
- **"Test-drive-booking potential"** is a conversion estimate with no calibration data
  anywhere in the 14 tables. It must be presented as a modelled proxy with stated
  assumptions and a confidence band, never as a promised number.

## 8. Capability gaps this brief exposes

| Gap | Consequence |
|---|---|
| No dealership / auto-retail POI type | §5.2 unresolvable; proxy only |
| `market_tier` is city-grain | "value-tier inventory" needs a derived zone tier |
| No aspect-ratio, orientation or resolution column on `screens` | "16:9 ultra-wide" cannot be enforced; `screen_size = L` is the only proxy |
| All inventory is digital | "digital screens only" excludes nothing — must not be allowed to empty the candidate set |
| `dim_slot` has no slot-duration column | "15 seconds per minute" cannot be reconciled to `slots_booked_per_day`; 6 slots looping implies 10 s/slot, so the ask is ~1.5 slots |
| Data horizon | Q1 2027 runs to 2027-03-31; `bookings` end 2027-02-21, `events` end 2027-02-19, `ridership` ends 2026-08-19 — the flight's tail has no data of any kind |
| "pre-monsoon" | Climatologically inapplicable to `America/New_York`. Decorative brief-authoring artifact — do **not** parse it into a seasonality feature |

## 9. Acceptance assertions (Phase 2.5 / Phase 4 fixtures)

1. Parsed `city_id == "LH"` — extracted from §1 prose.
2. `budget_amount == 40000.0`, `duration_days == 45`, `age_min == 28`, `age_max == 50`.
3. `slots_requested == 1`, `seconds_per_minute == 15`.
4. `industry_vertical == "auto"`; `objective_primary == "awareness"`.
5. `start_date is None` → the clarification loop **must** ask for a start date.
6. No recommended screen has `screen_type == "bus" and position == "back"`.
7. Every screen in the response is in LH.
8. The response names the auto-retail corridor requirement as unresolved/proxied.
9. Recommended screen count is single-digit-to-low-teens at this budget; a package of
   50+ screens means the price model or the budget constraint is broken.
10. Impressions are reported weekly.
