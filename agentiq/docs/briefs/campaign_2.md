# Gold Parse — Brief 2: Ember Energy, "Ignite Every Hour"

> **Hand-written, authoritative.** Step 1.8 gold fixture for
> `Campaigns/campaign_2.docx`. The Phase 4 extractor is tested against this file.

*Source:* `Campaigns/campaign_2.docx` · 31 paragraphs · 5 sections · brief number 2
*Parser status:* all 6 header fields, all 5 sections, 3 RFP items, **0 unparsed paragraphs.**

This is the hardest brief in the set for three independent reasons: it never names a
city, its primary inventory ask is **mobile** (so it cannot use the static POI path at
all), and its requested daypart is the one time block with no transit service.

---

## 1. Stated header fields (verbatim)

| Label | Verbatim value |
|---|---|
| Company Name | `Ember Beverages LLC` |
| Industry Vertical | `FMCG / BEVERAGES (ENERGY DRINKS)` |
| Campaign Objective | `Trial & Impulse Purchase` |
| Target Audience | `Gen Z and young professionals, gym-goers, night-shift workers (Ages 18-30)` |
| Campaign Budget | `USD 12,000` |
| Campaign Duration | `21 Days (Proposed: Exam season / Fall semester)` |

## 2. Gold parse → `CampaignBrief`

| Field | Gold value | Source | Confidence |
|---|---|---|---|
| `client_name` | Ember Beverages LLC | header | high |
| `brand` | Ember Energy | title | high |
| `industry_vertical_raw` | FMCG / BEVERAGES (ENERGY DRINKS) | header | high |
| `industry_vertical` | `cpg` | taxonomy — FMCG ≡ CPG | medium — **no token overlap; synonym required** |
| `objective_raw` | Trial & Impulse Purchase | header | high |
| `objective_primary` | `conversion` | taxonomy — trial/purchase is a response action | medium — **no token overlap** |
| `objective_secondary` | `frequency` | §5 item 3: "prioritising frequency over broad daytime coverage" | high — stated explicitly, but in the RFP section, not the header |
| `target_audience_raw` | Gen Z and young professionals, gym-goers, night-shift workers (Ages 18-30) | header | high |
| `age_min` / `age_max` | 18 / 30 | header | high |
| `audience_descriptors` | Gen Z, young professional, gym-goer, night-shift worker, student, price-sensitive, occasion-driven | header + §2 | high |
| `budget_amount` / `currency` | 12000.0 / USD | header | high |
| `duration_days` | 21 | header | high |
| `window_hint` | "Exam season / Fall semester" | header | high |
| `start_date` / `end_date` | **null / null** | not stated | — |
| `city_id` | **null — never stated anywhere in the document** | — | **blocking gap** |
| `slots_requested` | null | not stated | — |
| `seconds_per_minute` | null | not stated | — |
| `digital_only` | true | §4 "restricted to digital-only screens" | high |
| `creative_format` | 1:1 square, motion graphic; bus-rear and vertical poster | §4 | high |
| `daypart_weighting` | late evening → early morning; explicitly **not** commute peaks | §3 "Time-of-Day Target" | high |
| `exclusions` | **none stated** | — | high |
| `environment_requirements` | 3 + 1 daypart directive (see §5) | §3 | high |
| `rfp_deliverables` | 3 (see §7) | §5 | high |

**Two extractor traps.**

1. `objective_secondary = frequency` is stated in §5 (the RFP section), not in the
   objective header. An extractor that reads only the header block misses it — and
   frequency-vs-reach is the single biggest lever on this package's shape.
2. `exclusions` is legitimately empty. The eligibility filter must **not** invent
   exclusions; an empty list is a valid parse, distinct from a missing one.

## 3. The city gap (blocking)

No paragraph in this document names a city, a zone, or any city-specific entity.
`city_id` is a **hard eligibility constraint** — every screen, POI and zone key is
city-prefixed — so the pipeline cannot proceed on an assumption.

Per plan Step 4.3 this must produce a **targeted question**, plus the assumption the
agent would otherwise use. The candidate pools differ enough that guessing is not
defensible:

| City | Bus-rear screens | Student-zone screens | Nightlife-corridor bus-rear | Stadium-adjacent (static) |
|---|---|---|---|---|
| LH (premium) | 135 | 510 | 62 | 48 |
| ACS (value) | 132 | 141 | 85 | 21 |
| DAT (standard) | 138 | 251 | 92 | 3 |

`client_facts` offers a defensible default if the client can be matched: `home_city_id`
and `active_cities` per account. Ember Beverages LLC is not in `client_facts`
(520 accounts, no match) — this is a **new prospect**, so no client prior exists
either. Recommended assumption to state alongside the question: **ACS**, whose
value market tier best fits the smallest budget in the set and a price-sensitive
Gen Z audience, and which has the highest nightlife-corridor share of bus-rear
inventory (64%).

## 4. Hard constraints vs soft preferences

**Hard:** budget ceiling USD 12,000 · 21-day flight · digital-only (vacuous — all
inventory is digital) · `city_id` **once resolved**.

**Soft:** bus-rear placement · nightlife-corridor traversal · campus-edge proximity ·
stadium/arena precinct proximity · late-night daypart weighting · frequency over
reach · high-contrast motion creative.

Note that **every one of this brief's inventory asks is soft.** With no exclusions and
no stated city, the only hard constraints are budget and duration. The relevance
scorer, not the eligibility filter, does all the work here — the opposite of brief 4.

## 5. Environment requirements — measured bindings

### 5.1 "Nightlife and Entertainment Corridors" — bus-rear on late-night routes

> *Bus rear screens on routes running through late-night entertainment districts, positioned to catch post-venue crowds heading home.*

| Element | Binding | Measured |
|---|---|---|
| "bus rear screens" | `screen_type = 'bus' AND position = 'back'` | 405 network-wide (135 LH / 132 ACS / 138 DAT) |
| "routes running through …" | **mobile path**: `screens.vehicle_id → vehicles.corridor_id → route_stops.corridor_id → location_id → POI` | 21–23 corridors per city |
| "entertainment districts" | `poi_type = 'entertainment_district'` within 1.2 km of a served stop | 53 LH / 37 ACS / 51 DAT POIs |
| **Bus-rear screens whose corridor traverses a nightlife POI** | | **62 LH (46%) · 85 ACS (64%) · 92 DAT (67%)** |

**This is the structurally important binding in the whole brief set.** A bus screen has
`location_id = NULL` (all 2,615 mobile screens do), so it has no zone, no
demographics and no POI adjacency by the static path. The *only* way to give brief 2
what it asks for is the corridor traversal above — which crosses
`vehicles.corridor_id → route_stops.corridor_id`, a **documented N:N fan-out trap**
(up to 42 parent rows per child key). Locations must be aggregated to a set per
corridor *before* joining, or the counts inflate. Confidence: **high** for the path,
**medium** for the 1.2 km POI radius, which Step 1.6 still has to validate.

### 5.2 "Campus-Edge Transit Nodes"

> *Screens at transit nodes serving large student populations, timed to exam-season late-study patterns.*

| Binding | Measured |
|---|---|
| `zone_demographics.dominant_occupation = 'student'` | LH **Uptown Crescent** (65.8% aged 18–34), ACS **Fallowfield** (65.6%), DAT **Bellwood** (64.8%) |
| Static screens in those zones | 510 LH · 141 ACS · 251 DAT |
| `poi_type = 'university'` adjacency (static screens) | 588 LH · 100 ACS · 339 DAT |
| Bus-rear corridors traversing a university POI | 52 LH (39%) · 37 ACS (28%) · 58 DAT (42%) |

The student zones are an unusually clean binding — the three student zones are the
only zones anywhere with >60% of residents aged 18–34, against a network mean of
28.8%, and the brief's stated band is 18–30. Confidence: **high**.

"Timed to exam-season late-study patterns" has **no data anchor** — there is no
academic calendar, term-date or semester field in any table. Resolvable only as the
daypart weighting in §5.4 plus a client-supplied date window. Confidence: **low**.

### 5.3 "Event-Venue Precincts"

> *Digital boards near major stadium and arena precincts, where footfall spikes sharply on event nights.*

`poi_type = 'stadium_arena'` contains **exactly three rows — one per city.** All three
are `scale = flagship` and `side_of_road = near_side`. "Major stadium and arena
precincts" (plural) resolves to a single venue per city:

| POI | City / zone | Footfall | Peak | Anchor location | Static screens there | Corridors serving |
|---|---|---|---|---|---|---|
| `LH-POI-0590` Summit Stadium | LH / Financial Row | 21,906 | evening | `LH-LOC-0005` (metro_station) | **48** | 3 |
| `ACS-POI-0337` Fallowfield Stadium | ACS / Fallowfield | 11,003 | **night** | `ACS-LOC-0004` (metro_station) | **21** | 3 |
| `DAT-POI-0447` Crescent Central Stadium | DAT / Central Yard | 10,836 | evening | `DAT-LOC-0241` (bus_stop) | **3** | 3 |

Two consequences the recommendation must handle:

- **The bus-rear ask and the stadium ask conflict.** Zero LH and zero ACS bus-rear
  corridors traverse their city's stadium; only DAT has any (16 screens). Stadium
  precinct coverage is almost entirely *static metro-station* inventory — which is
  not what §3 asked for. The package must either mix mobile and static (and say so),
  or drop one requirement (and say which).
- **ACS is the best single-city fit.** Its stadium's `peak_daypart` is `night`
  (the other two peak `evening`) *and* it sits in Fallowfield, the student zone —
  so campus-edge and event-venue coverage collapse onto the same 21-screen node.

**Event surge is well supported here.** 109 event rows are anchored to these three
POIs: 82 `sports_game` + 27 `concert`; 69 evening / 27 afternoon / 13 night; and
**82 of 109 are `recurrence = 'weekly_season'`**, which must be expanded across their
season before any date-window match. That expansion is a prerequisite, not an
optimisation.

### 5.4 "Time-of-Day Target" — and the block-1 problem

> *Heavy weighting on late evening through early morning rather than standard commute peaks.*

Maps to `time_block_id ∈ {6, 1}` — 20:00–24:00 and 00:00–04:00. Both carry
`nearest_daypart = 'night'`, which is exactly why the data dictionary warns that
daypart is **not** a key: filtering on `daypart = 'night'` silently merges two blocks
at opposite ends of the day. Key on `time_block_id`.

**Measured: `time_block 1` (00:00–04:00) has zero scheduled trips network-wide.**

| time_block | Window | Scheduled trips | Mean est. ridership |
|---|---|---|---|
| **1** | **00:00–04:00** | **0** | **—** |
| 2 | 04:00–08:00 | 2,763 | 203.4 |
| 3 | 08:00–12:00 | 4,815 | 163.9 |
| 4 | 12:00–16:00 | 4,092 | 112.5 |
| 5 | 16:00–20:00 | 5,325 | 164.3 |
| 6 | 20:00–24:00 | 2,843 | 103.1 |

The network does not run between midnight and 04:00, yet `dim_slot` sells block 1 and
`bookings` records `time_block_id` values across the full 1–6 range. So block 1 is
**sellable inventory with no transit service**. For this brief that means:

- Mobile (bus / coach) exposure in block 1 is genuinely **zero** — the vehicles are
  in the depot. Selling a bus-rear slot in block 1 would be indefensible.
- Static exposure in block 1 falls back entirely to POI residual pull (nightlife
  venues, `peak_daypart = 'night'`), with no ridership component at all.
- Block 6 (20:00–24:00) is the honest home for "late evening", and it is the
  second-thinnest service block (2,843 trips, mean ridership 103.1 — half of the
  morning peak). Genuinely low-demand inventory, which should price low: good value
  for this budget, and a clean demonstration that the demand index is working.

**The brief's most-wanted daypart is the one with the weakest audience.** The
recommendation must say so rather than quietly selling block 1 at a discount. This is
the strongest honesty test in the brief set.

## 6. Budget envelope

| Quantity | Value |
|---|---|
| Budget | USD 12,000 (smallest but one in the set) |
| Flight | 21 days |
| Budget per day | ~USD 571 |
| Median quoted price/slot/day (`lost_leads`) | LH 98.08 · DAT 62.64 · **ACS 39.21** |
| Screens affordable at 1 slot/day | ~6 (LH) · ~9 (DAT) · **~15 (ACS)** |

City choice moves the deliverable package size by **2.5×** — the clearest possible
argument for asking the city question in §3 rather than assuming. Combined with the
stated frequency preference, the right shape is few screens × multiple slots rather
than many screens × one slot; at 3 slots/day in ACS that is ~5 screens.

## 7. RFP deliverables → owning phase

| # | Stated deliverable | Produced by |
|---|---|---|
| 1 | Inventory package **combining** bus-rear on nightlife corridors with campus-edge and event-venue boards | D4 / Phase 7 — explicitly a mixed mobile+static bundle |
| 2 | Dynamic pricing reflecting **late-night demand patterns** and **event-night surge** near major venues | D3 / Phase 6 §6.1 event-surge component |
| 3 | Reach plan optimised for **unique late-night impressions**, **prioritising frequency over broad daytime coverage** | D4 + D1 §3.5 reach/frequency split |

Item 1 is a bundle by construction ("combining"), so it must be priced and allocated
as **one deal** across modes. Item 3 requires *unique* reach — de-duplicated via the
overlap graph — and buses sharing a corridor are the textbook overlap case: the 62
LH bus-rear screens sit on only 21 corridors, so naive summation would inflate reach
roughly 6×.

## 8. Capability gaps this brief exposes

| Gap | Consequence |
|---|---|
| **`city_id` never stated** | Blocking clarification question; candidate pool varies 2.5× |
| **`time_block 1` has no transit service** | Sellable inventory with zero mobile audience; exposure model must not silently interpolate |
| Mobile screens have no `location_id` | All zone/POI context for bus-rear must come through the N:N corridor path |
| `stadium_arena` has one POI per city | "Precincts" (plural) is unsatisfiable as stated; and bus-rear corridors reach the stadium in DAT only |
| No academic calendar | "Exam season / Fall semester" cannot be dated |
| No gym / fitness POI type | "gym-goers" has no inventory binding; audience descriptor only |
| FMCG and "Trial & Impulse Purchase" have zero token overlap with the data vocabularies | `taxonomy.yaml` synonyms are a hard prerequisite, not a nicety |
| Client absent from `client_facts` | New prospect — no `negotiation_leverage`, `typical_campaign_budget` or city prior for pricing |
| No aspect-ratio column | "1:1 square" unenforceable |

## 9. Acceptance assertions (Phase 2.5 / Phase 4 fixtures)

1. `city_id is None` → the clarification loop **must** ask, and must state its default.
2. `exclusions == ()` — empty, not missing; no screen is filtered on an invented rule.
3. `budget_amount == 12000.0`, `duration_days == 21`, `age_min == 18`, `age_max == 30`.
4. `objective_secondary == "frequency"`, extracted from §5, not the header.
5. `slots_requested is None` → slots are a **decision variable** for D4, not a constraint.
6. Any recommended bus-rear screen resolves its nightlife claim through
   `vehicle → corridor → route_stops`, and the evidence cites the corridor id.
7. No bus-rear (mobile) screen is sold in `time_block 1`; if block 1 appears at all it
   is static-only and the response states that transit service is zero in that window.
8. Reported unique reach for a multi-bus package is **strictly less** than the sum of
   per-screen reach (corridor overlap de-duplication actually applied).
9. Event-surge pricing expands `recurrence = 'weekly_season'` rows before matching dates.
10. The response reconciles the bus-rear ask against the stadium ask instead of
    silently satisfying only one.
