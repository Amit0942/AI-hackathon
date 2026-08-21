# Gold Parse — Brief 4: Basil & Bloom, "Fresh, Fast, Flavorful"

> **Hand-written, authoritative.** Step 1.8 gold fixture for
> `Campaigns/campaign_4.docx`. The Phase 4 extractor is tested against this file.

*Source:* `Campaigns/campaign_4.docx` · 30 paragraphs · 5 sections · brief number 4
*Parser status:* all 6 header fields, all 5 sections, 3 RFP items, **0 unparsed paragraphs.**

The **hyper-local** case, and the only brief in the set where **eligibility, not budget,
is the binding constraint**. It also asks for the one thing the schema cannot give:
distance between a screen and an address.

---

## 1. Stated header fields (verbatim)

| Label | Verbatim value |
|---|---|
| Company Name | `Basil & Bloom Fast-Casual Kitchens` |
| Industry Vertical | `FOOD & BEVERAGE / QSR` |
| Campaign Objective | `Lunch-Hour Footfall & Local Recall` |
| Target Audience | `Office workers and students (Ages 18-35)` |
| Campaign Budget | `USD 9,000` |
| Campaign Duration | `15 Days (Proposed: New-outlet launch window)` |

## 2. Gold parse → `CampaignBrief`

| Field | Gold value | Source | Confidence |
|---|---|---|---|
| `client_name` | Basil & Bloom Fast-Casual Kitchens | header | high |
| `brand` | Basil & Bloom | title | high |
| `industry_vertical_raw` | FOOD & BEVERAGE / QSR | header | high |
| `industry_vertical` | `hospitality` | taxonomy — nearest of the 13 values | **low — no token overlap; QSR has no clean home in the vocabulary** |
| `objective_raw` | Lunch-Hour Footfall & Local Recall | header | high |
| `objective_primary` | `conversion` | taxonomy — §1 "success measured by lunch-hour footfall at the new outlet" | high |
| `objective_secondary` | `awareness` | taxonomy — "Local Recall" | medium |
| `target_audience_raw` | Office workers and students (Ages 18-35) | header | high |
| `age_min` / `age_max` | 18 / 35 | header | high |
| `audience_descriptors` | office worker, student, health-conscious, short-lunch-window, habit-driven, offer-responsive | header + §2 | high |
| `budget_amount` / `currency` | 9000.0 / USD | header | high |
| `duration_days` | 15 | header | high |
| `window_hint` | "New-outlet launch window"; §1 "two-week launch window" | header + §1 | high |
| `start_date` / `end_date` | **null / null** | not stated | — |
| `city_id` | `LH` (Las Hackland) | **§1 prose** — "Las Hackland's business district" | high |
| `target_zone_hint` | business district → Downtown Core / Financial Row | §1 | high |
| `outlet_location` | **"a business-park food court" — no address, no POI id, no location id** | §3 | **blocking gap** |
| `slots_requested` | null | not stated | — |
| `digital_only` | null (not stated) | — | — |
| `creative_format` | 16:9 wide; static; "visible from a distance" in food-court/plaza settings | §4 | high |
| `daypart_weighting` | midday / lunch window | §3 | high |
| `exclusions` | 1 — the radius exclusion (see §4) | §3 | high |
| `environment_requirements` | 2 (see §5) | §3 | high |
| `rfp_deliverables` | 3 (see §7) | §5 | high |

## 3. The blocking gap: there is no geometry in this dataset

The brief's entire inventory requirement is a distance from a point:

> *Screens within a short walking distance of a single new outlet located in a business-park food court — the campaign's entire reach requirement sits inside that radius.*

Three separate obstacles, in order of severity:

1. **`locations.csv` has no coordinates.** Its columns are `location_id`, `city_id`,
   `name`, `city_zone`, `zone_id`, `location_type`. No latitude, no longitude, no
   address, no geometry. **Screen-to-screen and screen-to-address distance is not
   computable anywhere in the 14 tables.**
2. **The outlet is not identified.** "A business-park food court" names a POI *type*,
   not a POI. In LH's business district there are **55** `office_park` /
   `corporate_campus` POIs it could be (109 in LH overall).
3. **The only distance field in the schema is
   `points_of_interest.distance_to_location_km`** — the distance from a POI to *its own*
   `anchor_location_id`, ranging 0.012–1.154 km. It relates a POI to one network node,
   nothing else.

**Consequence: this must be a blocking clarification question**, not a proxy. The
question is precise and easy for a rep to answer: *"which office park or corporate
campus is the outlet in?"* Once the rep names it, the requirement becomes computable:

> eligible = screens at that POI's `anchor_location_id`, where
> `distance_to_location_km` ≤ the agreed radius

…and the "short walking distance" claim rests on a **pre-computed proximity we did not
compute ourselves**, which is honest and citable. Anything wider than that anchor
location is a *stated relaxation*, not a walking radius.

## 4. Exclusion — resolution

| Stated exclusion | Data binding | Confidence |
|---|---|---|
| "Exclude all nodes outside a realistic walking distance of the outlet. Reach beyond that radius is wasted spend for a single-location launch." | `location_id != <outlet anchor>` once the anchor is known; **not computable before then** | high once resolved, **unsatisfiable before** |

This is the strictest exclusion in the brief set and it inverts the usual pipeline
order: the eligibility filter cannot run until the clarification loop closes. It is
also the acceptance test the plan names explicitly — *"the hyper-local brief must
return only screens inside its walking radius."*

## 5. Environment requirements — measured bindings

### 5.1 "Immediate Walking Radius of the New Outlet"

Once an outlet POI is named, the eligible set is small and its size depends entirely
on the **type** of node it anchors to. Measured, screens per static location:

| Location type | Locations | Min | Median | Max |
|---|---|---|---|---|
| `bus_stop` | 719 | **3** | **3** | **3** |
| `metro_station` | 191 | 10 | 34 | 50 |

Every bus stop in the network carries exactly **3** screens — one each at `top`,
`left`, `right`. Metro stations carry 10–50, split `platform` / `entrance_exit`.

Worked candidate sets for the five highest-footfall LH business-district park POIs:

| Outlet POI | Zone | Footfall | Anchor | Anchor type | Dist. | Side | **Eligible screens** |
|---|---|---|---|---|---|---|---|
| `LH-POI-0378` | Downtown Core | 51,195 | `LH-LOC-0206` | bus_stop | 0.42 km | far_side | **3** |
| `LH-POI-0117` | Financial Row | 48,388 | `LH-LOC-0320` | bus_stop | 0.74 km | far_side | **3** |
| `LH-POI-0582` | Financial Row | 45,130 | `LH-LOC-0075` | metro_station | 0.29 km | far_side | **27** |
| `LH-POI-0171` | Financial Row | 36,879 | `LH-LOC-0105` | metro_station | 0.40 km | near_side | **34** |
| `LH-POI-0490` | Downtown Core | 29,008 | `LH-LOC-0011` | metro_station | 0.54 km | far_side | **27** |

The same-zone relaxation, if the rep accepts it, jumps to ~495–500 screens across 36
locations — a **165× widening**. That is not a walking radius and must not be
presented as one; it is a different plan, offered explicitly.

Note also that three of the five highest-footfall candidates are `far_side`: the
audience is across the road from the only node serving them, which weakens the
visibility claim on the campaign's single most important requirement.

### 5.2 "Midday Commercial-District Coverage" — and the block granularity problem

> *Screens in the surrounding commercial district, weighted specifically to the lunch window.*

Binds to LH `Downtown Core` / `Financial Row` (the same daytime-multiplier >3,
`white_collar` zones as brief 1) — **high** confidence, 995 screens combined, subject
to the §5.1 radius exclusion.

The lunch weighting does not bind cleanly. `dim_slot` sells **4-hour blocks**:

| Purchase | Coverage of an 11:00–14:00 lunch target |
|---|---|
| Block 3 (08:00–12:00) + block 4 (12:00–16:00) | all 3 target hours, but 8 hours delivered — **62% of spend outside the target** |
| Block 4 only (12:00–16:00) | misses 11:00–12:00 — 1 of 3 target hours lost |

**The sellable time grain is coarser than the brief's target window**, and on the
smallest budget in the set that waste is material. There is no finer instrument: no
hour-level slot, and no hour-level footfall curve anywhere in the data. The closest
evidence is `points_of_interest.peak_daypart`, and for LH's 109 office-park /
corporate-campus POIs it reads: morning 42, evening 38, **midday 18**, night 7,
afternoon 4 — i.e. only 17% of office-park POIs peak at midday at all. The lunch-hour
premise is weaker in the data than the brief assumes, and block 4 is the defensible
buy with the shortfall stated.

## 6. Budget envelope — where this brief inverts

| Quantity | Value |
|---|---|
| Budget | USD 9,000 — **smallest in the set** |
| Flight | 15 days |
| Budget per day | ~USD 600 |
| LH median quoted price/slot/day (`lost_leads`) | 98.08 |
| **Screens affordable at 1 slot/day** | **~6** |
| Eligible set if the outlet anchors a **bus stop** | **3** |
| Eligible set if the outlet anchors a **metro station** | 27–34 |

If the outlet's node is a bus stop, the eligible set (**3**) is *smaller than the
budget can buy* (**~6**). **Eligibility binds, not budget** — the unique case in the
brief set, and the right behaviour is not to spend the remainder on ineligible
inventory. The correct responses are to increase slots per screen on those 3 screens
(more frequency on a captive local audience — which suits "local recall"), extend the
flight, or offer a stated radius relaxation. Each is a Phase 8 adaptive re-plan, and
this brief is the cleanest demo of one.

If the node is a metro station, the usual selection problem returns: ~6 of 27–34.

## 7. RFP deliverables → owning phase

| # | Stated deliverable | Produced by |
|---|---|---|
| 1 | Tightly-scoped inventory list **limited to screens within realistic walking distance** of the single new outlet | D2 / Phase 5 eligibility filter |
| 2 | Pricing reflecting the **hyper-local, midday-weighted** delivery pattern | D3 / Phase 6 |
| 3 | Footfall-conversion reach estimate for the 15-day window, **explicitly stating the walking-radius logic behind screen selection** | D4 + narrative |

Item 3 is unusual and welcome: the client is asking us to **show the rule**, not just
the result. Given §3, the honest statement is *"screens at the single network node your
outlet's business park anchors to, at a pre-computed proximity of X km; we cannot
measure walking distance directly because the location catalogue has no coordinates."*
That sentence is a trust win, not a weakness.

## 8. Capability gaps this brief exposes

| Gap | Consequence |
|---|---|
| **No coordinates anywhere in `locations`** | Walking distance is not computable; radius is POI→anchor km only |
| **Outlet not identified in the brief** | Blocking clarification question before eligibility can run |
| 4-hour time blocks | Cannot isolate an 11:00–14:00 lunch window; 62% waste or 1 hour lost |
| No hour-level footfall curve | Lunch peak evidenced only by `peak_daypart`, and only 17% of LH office parks peak midday |
| QSR / Food & Beverage has no home in the 13 verticals | `hospitality` is a low-confidence mapping |
| Bus stops carry exactly 3 screens | Single-node packages can be smaller than the budget — eligibility-bound |
| `far_side` on 3 of 5 top candidates | Visibility claim weakened on the campaign's core requirement |
| No aspect-ratio column | "16:9, visible from a distance" → `screen_size = L` proxy only |
| No date window | "New-outlet launch window" is undated |

## 9. Acceptance assertions (Phase 2.5 / Phase 4 fixtures)

1. `city_id == "LH"` — extracted from §1 prose.
2. `budget_amount == 9000.0`, `duration_days == 15`, `age_min == 18`, `age_max == 35`.
3. `exclusions` has exactly 1 entry, the radius exclusion.
4. `outlet_location` is flagged **unresolved** → a blocking clarification question is
   raised naming the candidate POI set; the pipeline does **not** proceed on a guess.
5. Given a named outlet POI, **every** recommended screen sits at that POI's
   `anchor_location_id`. A single screen outside it fails the test.
6. Any widening beyond the anchor location is labelled a stated relaxation with its
   own impression figure — never folded silently into "walking radius".
7. The response states the radius rule and the fact that true walking distance is not
   computable.
8. If the eligible set is smaller than the budget affords, the response proposes more
   slots / longer flight / an explicit relaxation rather than adding ineligible screens.
9. Recommended time blocks are 3 and/or 4, with the coverage shortfall against an
   11:00–14:00 target stated.
10. Budget spent never exceeds 9,000.
