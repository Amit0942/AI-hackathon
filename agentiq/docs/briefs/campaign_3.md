# Gold Parse — Brief 3: Loom & Thread, "Wear Your Story"

> **Hand-written, authoritative.** Step 1.8 gold fixture for
> `Campaigns/campaign_3.docx`. The Phase 4 extractor is tested against this file.

*Source:* `Campaigns/campaign_3.docx` · 30 paragraphs · 5 sections · brief number 3
*Parser status:* all 6 header fields, all 5 sections, 3 RFP items, **0 unparsed paragraphs.**

This brief is the set's **contradiction case**: it explicitly requests weekend-weighted
delivery, and the ridership data says weekends deliver roughly **one third** of the
weekday transit audience. Handling that honestly — rather than silently selling the
weekend at full price — is the whole test here.

---

## 1. Stated header fields (verbatim)

| Label | Verbatim value |
|---|---|
| Company Name | `Loom & Thread Apparel Co.` |
| Industry Vertical | `RETAIL / FASHION` |
| Campaign Objective | `Seasonal Footfall & Sale Awareness` |
| Target Audience | `Style-conscious shoppers (Ages 20-40)` |
| Campaign Budget | `USD 22,000` |
| Campaign Duration | `20 Days (Proposed: Autumn Collection Launch)` |

## 2. Gold parse → `CampaignBrief`

| Field | Gold value | Source | Confidence |
|---|---|---|---|
| `client_name` | Loom & Thread Apparel Co. | header | high |
| `brand` | Loom & Thread | title | high |
| `industry_vertical_raw` | RETAIL / FASHION | header | high |
| `industry_vertical` | `retail` | taxonomy | high — direct token match |
| `objective_raw` | Seasonal Footfall & Sale Awareness | header | high |
| `objective_primary` | `conversion` | taxonomy — "Footfall" is the stated success measure (§1: "objective is footfall") | medium |
| `objective_secondary` | `awareness` | taxonomy — "Sale Awareness" | high |
| `target_audience_raw` | Style-conscious shoppers (Ages 20-40) | header | high |
| `age_min` / `age_max` | 20 / 40 | header | high |
| `audience_descriptors` | style-conscious shopper, working professional, student, seasonal (non-impulse) shopper, brand-follower, editorial-responsive | header + §2 | high |
| `budget_amount` / `currency` | 22000.0 / USD | header | high |
| `duration_days` | 20 | header | high |
| `window_hint` | "Autumn Collection Launch"; §1 adds "citywide seasonal sale" tied to sale dates | header + §1 | high |
| `start_date` / `end_date` | **null / null** | not stated | — |
| `city_id` | **null — never stated** | — | **gap; but see §3** |
| `slots_requested` | null | not stated | — |
| `seconds_per_minute` | null | not stated | — |
| `digital_only` | null (not stated) | — | — |
| `creative_format` | tall vertical (9:16); **static** editorial visual | §4 | high |
| `daypart_weighting` | Friday evening → Sunday; §2 adds post-work weekday evenings | §3 + §2 | high |
| `exclusions` | **none stated as a labelled criterion** — but see §4 | — | high |
| `environment_requirements` | 2 + 1 daypart directive (see §5) | §3 | high |
| `rfp_deliverables` | 3 (see §7) | §5 | high |

**Extractor trap.** §2 contains a *soft negative* — "favoring mall and high-street
retail nodes **over purely residential or industrial corridors**". This is not in the
labelled `Exclusion Criteria` form the other briefs use, so `derive_fields` does not
pick it up as an exclusion, and it should not be promoted to a hard filter. It belongs
in the relevance score as a penalty on `residential_tower`-dominant and
`blue_collar`-zone inventory. Recording it as a *soft preference with direction* is
the correct parse; dropping it loses real signal.

## 3. City scope — "the network's largest shopping centres"

`city_id` is never stated, but this brief is different from brief 2: §3 says *"the
**network's** largest shopping centres"*, while §1 says *"a **citywide** seasonal
sale"*. Those pull in opposite directions — network-wide implies a multi-city buy,
citywide implies one. The gold parse records `city_scope = ambiguous` and requires a
clarification question.

Measured, if read network-wide: **225 `shopping_mall` POIs** (93 LH / 72 DAT / 60 ACS),
of which **13 are `scale = flagship`**. A multi-city flagship package is buildable and
would be a legitimate **cross-city bundle** — the "bundle is one deal" nuance applied
across cities rather than modes.

Recommended assumption to state alongside the question: **LH**, on the grounds that it
holds the largest and second-largest malls in the network and 93 of 225 mall POIs.

## 4. Hard constraints vs soft preferences

**Hard:** budget ceiling USD 22,000 · 20-day flight · `city_scope` once resolved.

**Soft:** mall-entry positioning · high-street retail corridor character · competing-
apparel-retailer adjacency · weekend + Friday-evening daypart weighting · post-work
weekday evening · penalty on purely residential / industrial corridors · vertical
static creative fit.

## 5. Environment requirements — measured bindings

### 5.1 "Premium Mall Entry Points"

> *High-footfall digital boards at the entrances of the network's largest shopping centres, where shoppers arrive with purchase intent already formed.*

| Element | Binding | Measured |
|---|---|---|
| "largest shopping centres" | `poi_type = 'shopping_mall'`, ranked by `est_daily_footfall`, `scale ∈ {flagship, major}` | 77 flagship/major network-wide |
| "high-footfall … boards at the entrances" | `screens.position = 'entrance_exit'` at the mall's `anchor_location_id` | **90 LH · 48 DAT · 9 ACS** |
| Major/flagship-mall anchor locations | | 37 LH · 29 DAT · 11 ACS |
| All screens at those anchors (any position) | | 534 LH · 300 DAT · 72 ACS |

**Two hard caveats, both material.**

1. **`entrance_exit` exists only on `metro_station` screens** — all 1,275 of them. There
   is no such position on `bus_stop`, `bus` or `metro_rail_coach`. So a "mall entry
   point" screen is, in this dataset, a *metro-station entrance screen whose nearest
   POI is a mall* — not a screen at the mall's own door. The recommendation must
   describe it that way or it overstates what is being sold.
2. **The largest mall has almost no inventory.** Ranked by footfall:

| Rank | POI | Zone | Footfall | Scale | Side | Screens at anchor | of which `entrance_exit` |
|---|---|---|---|---|---|---|---|
| 1 | `LH-POI-0306` | Downtown Core | 50,690 | flagship | far_side | **3** | **0** |
| 2 | `LH-POI-0328` | Downtown Core | 35,050 | flagship | near_side | **45** | **9** |
| 3 | `LH-POI-0320` | Harborfront | 20,084 | flagship | far_side | 3 | 0 |
| 4 | `DAT-POI-0349` | Bellwood | 18,810 | flagship | far_side | 3 | 0 |
| 5 | `LH-POI-0131` | Financial Row | 18,556 | major | far_side | 3 | 0 |

The network's biggest mall by footfall is `far_side` (audience across the road — weaker
visibility evidence per the POI side-of-road field) and its anchor location carries 3
screens with zero entrance positions. The genuinely buyable flagship-mall node is
**rank 2**, `LH-POI-0328`: near_side, `peak_daypart = evening`, 45 screens, 9 of them
entrance positions. **Footfall ranking and inventory availability disagree**, and a
scorer that ranks on POI footfall alone will put its top recommendation on a node it
cannot fill. Confidence in the binding: **high**; in "largest = best": **low**.

### 5.2 "High-Street Retail Corridors"

> *Screens along established high-street shopping strips with a concentration of competing apparel retailers.*

| Binding | Measured |
|---|---|
| `zone_demographics.dominant_occupation = 'retail_service'` | LH **Market Quarter**, ACS **Cobblestone Village**, DAT **Founders Square** — one per city |
| Screens in those zones | **451 LH · 122 ACS · 236 DAT** |

Clean binding, **high** confidence — `retail_service` is one of five
`dominant_occupation` values and picks out exactly one zone per city.

"A concentration of **competing apparel retailers**" has **no data anchor**: `poi_type`
has `shopping_mall` and `grocery_anchor` but no apparel, fashion or category-level
retail sub-type, and there is no tenant or brand-level table. Proxy: mall/retail POI
*density* per location plus, once `bookings.csv` is restored, prior
`industry_vertical = 'retail'` booking density on the screen. Confidence: **low**.

### 5.3 "Weekend Weighting" — measured, and it contradicts the ask

> *Requesting weighted delivery from Friday evening through Sunday, aligned with peak discretionary shopping behaviour.*

The binding itself is fully supported: `ridership_actuals.day_of_week` and
`is_holiday` exist on all 2,049,632 rows, and `route_schedules.day_type` gives the
scheduled view. Combining `day_of_week` with `time_block_id` expresses "Friday
evening" exactly. Confidence in the binding: **high**.

Measured transit exposure by day (mean `actual_ridership` per trip, whole network):

| Day | Observations | Mean actual ridership | vs Mon–Thu |
|---|---|---|---|
| Monday | 339,352 | 187.2 | 0.94× |
| Tuesday | 339,352 | 200.8 | 1.00× |
| Wednesday | 339,352 | 204.7 | 1.02× |
| Thursday | 339,352 | 206.4 | 1.03× |
| **Friday** | 339,352 | **216.5** | **1.08×** |
| Saturday | 176,436 | 74.4 | 0.37× |
| Sunday | 176,436 | 58.1 | **0.29×** |

**Weekend factor = 0.332×** (Sat+Sun mean 66.2 vs Mon–Thu 199.8), consistent across
all three cities (LH 0.346× · DAT 0.323× · ACS 0.311×). Weekends also carry roughly
**half the scheduled service** (176,436 observations vs 339,352 — fewer trips run).
Holidays behave like weekends: mean 98.0 vs 180.4 on non-holidays (0.54×).

So the brief's central delivery request buys an audience about **one third the size**
per slot. Three things follow:

- **Friday is the best day in the entire week (1.08×)**, and the brief's own wording
  starts at "Friday evening". Friday evening (`day_of_week = Friday`,
  `time_block ∈ {5, 6}`) is the defensible core of a weekend-weighted plan and should
  carry disproportionate weight within the requested window.
- **Weekend slots should price lower**, and the demand index should say so. Selling
  Saturday and Sunday at weekday rates because the client asked for them is exactly
  the unguarded pricing this system exists to prevent.
- **The "peak discretionary shopping behaviour" premise cannot be evidenced.**
  `points_of_interest.est_daily_footfall` is a single daily average with **no
  day-of-week dimension**, so there is no data anywhere showing malls are busier at
  weekends. The client's premise may well be true of shoppers; it is simply not
  observable in these 14 tables, and the response must label it a client assumption
  rather than a modelled result.

The right output is the trade-off, not a refusal: honour the weighting, quantify what
it costs in impressions, and show the Friday-weighted alternative beside it.

## 6. Budget envelope

| Quantity | Value |
|---|---|
| Budget | USD 22,000 |
| Flight | 20 days |
| Budget per day | ~USD 1,100 — **the highest daily budget of the six briefs** |
| Median quoted price/slot/day (`lost_leads`) | LH 98.08 · DAT 62.64 · ACS 39.21 |
| Screens affordable at 1 slot/day | ~11 (LH) · ~18 (DAT) · ~28 (ACS) |
| Candidate pool (LH mall-entry + high-street) | 90 + 451 |

Because weekend delivery costs ~3× more per impression, the effective package is
smaller than the headline suggests if the weighting is honoured strictly. That is a
concrete "+X% budget buys +Y reach" sensitivity line for the Phase 7 frontier.

## 7. RFP deliverables → owning phase

| # | Stated deliverable | Produced by |
|---|---|---|
| 1 | Inventory plan anchored on premium mall entry points and high-street retail corridors | D2 / Phase 5 |
| 2 | Pricing reflecting **weekend-weighted delivery** and premium mall-entry positioning | D3 / Phase 6 |
| 3 | Footfall-oriented reach projection for the 20-day window, **with the weekend-versus-weekday impression split shown separately** | D1 §3.5 + D4 |

Item 3 makes the weekend/weekday split a **required output field**, not a nice-to-have
chart — which is precisely where the 0.332× factor becomes visible to the client.
Item 2 requires the price to *respond* to the weekend weighting; given the measured
factor, a defensible answer prices weekend slots **below** weekday.

## 8. Capability gaps this brief exposes

| Gap | Consequence |
|---|---|
| **Weekend ridership is 0.33× weekday** | The brief's core request reduces delivered audience; must be quantified, not absorbed |
| POI footfall has no day-of-week dimension | "Peak weekend shopping" is unevidenced — a client assumption |
| `entrance_exit` exists only on `metro_station` | "Mall entry" means metro entrance near a mall; do not overstate |
| Footfall rank ≠ inventory availability | The #1 mall has 3 screens and 0 entrance positions |
| No apparel / category-level retail POI sub-type | "Competing apparel retailers" is proxy-only |
| `city_scope` ambiguous ("network's" vs "citywide") | Clarification needed; a cross-city bundle is the alternative reading |
| No aspect-ratio or orientation column | "Tall vertical / 9:16" unenforceable |
| Soft negative in §2, not in exclusion form | Must land as a scoring penalty, not a hard filter |
| No date window | "Autumn Collection Launch" and "sale dates" are undated |

## 9. Acceptance assertions (Phase 2.5 / Phase 4 fixtures)

1. `budget_amount == 22000.0`, `duration_days == 20`, `age_min == 20`, `age_max == 40`.
2. `industry_vertical == "retail"`; objective resolves to conversion + awareness.
3. `exclusions == ()`, **and** the §2 residential/industrial negative is retained as a
   soft penalty with direction — not silently dropped, not promoted to a filter.
4. `city_scope` is flagged ambiguous → clarification question raised.
5. The response reports a **weekend-vs-weekday impression split** as a separate figure.
6. The quoted weekend impression figure is materially lower per slot than the weekday
   figure (a plan that shows them equal has not applied `day_of_week`).
7. Weekend slot pricing is **not above** weekday pricing for the same screen.
8. Friday appears in the recommended daypart mix (it is the strongest day measured).
9. Any "mall entry" screen in the response has `position == "entrance_exit"` and
   `screen_type == "metro_station"`, and its explanation names the mall POI it is near.
10. The "peak discretionary shopping" premise is attributed to the client, not
    presented as a modelled finding.
