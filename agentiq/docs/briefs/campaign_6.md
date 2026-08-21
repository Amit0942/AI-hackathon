# Gold Parse — Brief 6: Lumière Cosmetics, "Glow On Your Terms"

> **Hand-written, authoritative.** Step 1.8 gold fixture for
> `Campaigns/campaign_6.docx`. The Phase 4 extractor is tested against this file.

*Source:* `Campaigns/campaign_6.docx` · 30 paragraphs · 5 sections · brief number 6
*Parser status:* all 6 header fields, all 5 sections, 3 RFP items, **0 unparsed paragraphs.**

The cleanest brief in the set on structure — a single objective, an age band that
matches a demographic column exactly — and the one that asks for the audience
attribute the data does not have at all: **gender**.

---

## 1. Stated header fields (verbatim)

| Label | Verbatim value |
|---|---|
| Company Name | `Lumière Cosmetics Group` |
| Industry Vertical | `BEAUTY & PERSONAL CARE` |
| Campaign Objective | `New Product Launch Awareness` |
| Target Audience | `Young women, beauty-conscious commuters (Ages 18-34)` |
| Campaign Budget | `USD 20,000` |
| Campaign Duration | `25 Days (Proposed: Spring product launch)` |

## 2. Gold parse → `CampaignBrief`

| Field | Gold value | Source | Confidence |
|---|---|---|---|
| `client_name` | Lumière Cosmetics Group | header | high — note the accented character; the parser round-trips it correctly via `unescape` |
| `brand` | Lumière | title | high |
| `industry_vertical_raw` | BEAUTY & PERSONAL CARE | header | high |
| `industry_vertical` | `retail` primary, `cpg` secondary | taxonomy | **low — no token overlap; a packaged good sold through retail sits between two values** |
| `objective_raw` | New Product Launch Awareness | header | high |
| `objective_primary` | `awareness` | taxonomy — direct token match | **high — the only brief with a single, cleanly-binding objective** |
| `objective_secondary` | null | — | high |
| `target_audience_raw` | Young women, beauty-conscious commuters (Ages 18-34) | header | high |
| `age_min` / `age_max` | 18 / 34 | header | **high — matches `pct_age_18_34` exactly (see §3)** |
| `audience_gender` | `female` | header "Young women" | **stated, but unbindable — see §3** |
| `audience_descriptors` | young women, beauty-conscious, metro commuter, frequent mall visitor, trend-following, editorial-responsive | header + §2 | high |
| `budget_amount` / `currency` | 20000.0 / USD | header | high |
| `duration_days` | 25 | header | high |
| `window_hint` | "Spring product launch"; §1 "ahead of in-store availability" | header + §1 | high |
| `start_date` / `end_date` | **null / null** | not stated | — |
| `city_id` | **null — never stated** | — | **gap** |
| `slots_requested` | null | not stated | — |
| `digital_only` | null (not stated) | — | — |
| `creative_format` | 9:16 tall vertical; **static** editorial visual | §4 | high |
| `daypart_weighting` | soft — "ahead of weekend shopping trips" (§3) implies Thu–Fri weighting | §3 | medium |
| `exclusions` | **none stated** | — | high |
| `environment_requirements` | 3 (see §5) | §3 | high |
| `rfp_deliverables` | 3 (see §7) | §5 | high |

**Extractor note.** §1's "positioning the product as a premium addition to an existing
skincare routine **rather than an impulse buy**" is a soft negative on impulse/
convenience context — the mirror image of brief 2's request. It is not in exclusion
form and must not become a filter, but it should penalise `grocery_anchor` adjacency
in the relevance score.

## 3. The audience gap: there is no gender in this dataset

The stated target opens with "**Young women**". `zone_demographics` has 15 columns:

`zone_id`, `city_id`, `zone_name`, `resident_population`,
`population_density_per_sqkm`, `median_age`, `pct_age_under_18`, `pct_age_18_34`,
`pct_age_35_54`, `pct_age_55_plus`, `median_household_income`, `income_index`,
`pct_bachelor_or_higher`, `dominant_occupation`, `daytime_population_multiplier`

**No sex or gender field exists here or in any other table.** No ridership,
POI, client or booking table carries one either. So the primary audience descriptor
of this brief is **unrepresentable**: the system cannot score, rank, filter or report
on it, and cannot claim a female-skewed audience for any screen.

What *can* be done, and must be labelled as such:

- **Age binds exactly.** The stated 18–34 is `pct_age_18_34` verbatim — the only brief
  in the set whose age band needs no fractional overlap arithmetic. Network mean is
  28.8%; the student zones reach 65.8%.
- **Context substitutes for demography.** Beauty-retail adjacency, mall and
  high-street environments are the honest proxy for "beauty-conscious", carried by
  POI type and zone character rather than by any audience attribute.

The response must state that gender is not modelled. Presenting a "young women"
audience figure derived from age-and-mall-adjacency alone would be exactly the kind of
invented number the deterministic-core principle exists to prevent.

## 4. City scope

`city_id` is never stated. Unlike brief 3 there is no "network"/"citywide" tension —
simply an absence. `client_facts` has no Lumière Cosmetics Group among its 520
accounts, so there is no `home_city_id` or `active_cities` prior: a **new prospect**,
with no `negotiation_leverage` or `typical_campaign_budget` for pricing either.

Candidate pools for this brief's asks:

| City | Mall-adjacent `entrance_exit` screens | High-street (`retail_service` zone) screens | Central-zone metro entrance screens |
|---|---|---|---|
| LH | **90** | 451 | 85 (Downtown Core) |
| DAT | 48 | 236 | 35 (Central Yard) |
| ACS | 9 | 122 | 10 (Maple Grove) |

ACS is effectively unbuildable for this brief — 9 mall-entry screens against a budget
that affords ~15. Recommended assumption to state with the question: **LH**.

## 5. Environment requirements — measured bindings

### 5.1 "Mall Beauty-Retail Entry"

> *Premium vertical screens at shopping centre entrances adjacent to beauty and lifestyle retail concessions, reaching shoppers moments before they pass a beauty counter.*

| Element | Binding | Measured |
|---|---|---|
| "shopping centre entrances" | `position = 'entrance_exit'` at a major/flagship `shopping_mall` anchor | **90 LH · 48 DAT · 9 ACS** (147 network-wide) |
| … of which `screen_size = 'L'` | | 88 of 147 |
| "beauty and lifestyle retail concessions" | **no binding** | — |
| "moments before they pass a beauty counter" | **no binding** | — |

Two caveats carry forward from brief 3 and apply identically here: `entrance_exit`
exists **only** on `metro_station` screens (all 1,275), so a "shopping centre entrance"
screen is a metro-station entrance whose nearest POI is a mall; and mall footfall rank
does not track inventory availability.

**Beauty-counter adjacency is the finest-grained ask in the whole brief set and there
is no data at any comparable grain.** `poi_type` stops at `shopping_mall` — there is no
tenant, concession, category or brand table anywhere. The gap is one level below
anything the schema models. Confidence: **low**, and this is the clearest case in the
set for the Phase 3 §3.3 semantic labelling agent: a controlled-vocabulary
environment descriptor such as *premium retail entry* can be inferred from POI mix,
zone income index and scale, cited to evidence, and then matched semantically — which
is precisely the "beauty-counter adjacency vs generic mall" example the plan uses to
justify Phase 5 §5.3 re-ranking. It cannot be answered by a rule.

### 5.2 "High-Street Retail Corridors"

> *Vertical screens along high-street shopping strips with a concentration of competing beauty retailers.*

Identical binding to brief 3 §5.2: `dominant_occupation = 'retail_service'` →
**Market Quarter** (LH, 451 screens), **Cobblestone Village** (ACS, 122),
**Founders Square** (DAT, 236). Confidence **high** on the corridor,
**low** on "competing beauty retailers" (no category-level retail data).

Worth noting the intersection: **108 screens network-wide are both major-mall-adjacent
and in a `retail_service` zone** (54 LH · 48 DAT · 6 ACS) — these satisfy §5.1 and
§5.2 simultaneously and should rank highest. They are also, by construction, an
**overlap risk**: co-located screens serving one shopping catchment, so their combined
unique reach is far below the sum. Exactly the Phase 3 §3.4 case.

### 5.3 "Central Metro Entry Coverage"

> *Supplementary vertical placements at central metro entry points, for repeated commuter exposure ahead of weekend shopping trips.*

Binds to `screen_type = 'metro_station' AND position = 'entrance_exit'` in each city's
highest-daytime-multiplier zone: LH **Downtown Core** (85 screens, 53 of them size L),
DAT **Central Yard** (35, 21 L), ACS **Maple Grove** (10, 5 L). Confidence: **high**.

Like brief 5, this requirement is explicitly labelled **"supplementary"** — a stated
priority ordering the scorer should respect. "Repeated commuter exposure" is a
**frequency** ask sitting under an **awareness** objective, so this subset wants
multiple slots on few screens while the campaign overall wants breadth.

"Ahead of weekend shopping trips" implies Thursday–Friday weighting. Friday is the
strongest day measured in `ridership_actuals` (1.08× the Mon–Thu baseline), so unlike
brief 3's Saturday–Sunday ask, **this brief's implied timing is supported by the
data** — a useful contrast to draw in the response.

## 6. Budget envelope

| Quantity | Value |
|---|---|
| Budget | USD 20,000 |
| Flight | 25 days |
| Budget per day | ~USD 800 |
| Median quoted price/slot/day (`lost_leads`) | LH 98.08 · DAT 62.64 · ACS 39.21 |
| **Screens affordable at 1 slot/day** | **~8 (LH)** · ~13 (DAT) · ~20 (ACS) |
| Candidate pool (LH mall-entry + high-street + central) | 90 + 451 + 85 |

~8 of ~626 in LH. As with brief 1, the budget binds hard and relevance ranking does
nearly all the work. The stated frequency sub-requirement (§5.3) pushes toward fewer
screens with more slots, so a realistic package is ~5 screens.

## 7. RFP deliverables → owning phase

| # | Stated deliverable | Produced by |
|---|---|---|
| 1 | Inventory plan anchored on mall beauty-retail entry points and high-street retail corridors, **with supplementary central metro entry coverage** | D2 / Phase 5 — with the stated priority tiering |
| 2 | Pricing reflecting premium mall-entry positioning and **the value of beauty-retail adjacency** | D3 / Phase 6 |
| 3 | Projected reach for the 25-day window, **with reasoning tied to beauty-audience affinity at each recommended node type** | D4 + narrative |

Item 2 asks us to price an adjacency the data cannot see (§5.1) — so the premium must
be justified by what *is* observable (mall scale, footfall, entrance position, zone
income index, POI mix) with the beauty-specific element declared as an inferred
semantic label, not a measured one.

Item 3 is the most interesting explainability requirement in the set: reasoning is
demanded **per node type**, not per screen. The narrative must aggregate explanations
up to the level of "mall entry", "high street", "central metro entry" and justify each
category's affinity — a grouped `Explanation`, which the Phase 2 §2.2 contract should
be checked against before Phase 8 rather than after.

## 8. Capability gaps this brief exposes

| Gap | Consequence |
|---|---|
| **No gender data in any table** | The primary audience descriptor is unrepresentable; must be stated, never inferred |
| **No mall tenant / concession / retail-category data** | "Beauty-counter adjacency" is one grain below anything modelled; semantic-label territory |
| `entrance_exit` only on `metro_station` | "Shopping centre entrance" means metro entrance near a mall |
| No aspect-ratio or orientation column | "Premium vertical / 9:16" unenforceable; `screen_size = L` is the only proxy |
| Beauty & Personal Care straddles `retail` and `cpg` | Taxonomy must record a primary/secondary mapping, not force a single value |
| `city_id` absent; client not in `client_facts` | Clarification needed; no client prior for pricing (new prospect) |
| Mall-adjacent + retail-zone screens co-locate (108) | High overlap risk; unique reach must be de-duplicated |
| "Supplementary" priority tier | Requirements are ranked by the client, not equal-weighted |
| No date window | "Spring product launch" is undated |

## 9. Acceptance assertions (Phase 2.5 / Phase 4 fixtures)

1. `budget_amount == 20000.0`, `duration_days == 25`, `age_min == 18`, `age_max == 34`.
2. `objective_primary == "awareness"` and `objective_secondary is None`.
3. `audience_gender == "female"` is **parsed and retained**, and reported as
   **not modelled** — no screen carries a gender-derived score or figure.
4. Age matching uses `pct_age_18_34` directly, with no fractional-band arithmetic.
5. `city_id is None` → clarification question raised, with the stated default.
6. `exclusions == ()`; the §1 anti-impulse negative lands as a soft penalty on
   `grocery_anchor` adjacency, not as a filter.
7. Beauty-retail adjacency is presented as an **inferred semantic label with cited
   evidence**, never as a measured POI attribute.
8. Any "mall entry" screen has `position == "entrance_exit"` and
   `screen_type == "metro_station"`.
9. Unique reach for a package drawn from the 108 co-located mall+retail-zone screens is
   **materially below** the sum of individual reaches.
10. The narrative groups its reasoning by **node type** (mall entry / high street /
    central metro), not only per screen.
11. The stated priority order (mall + high-street primary, central metro
    *supplementary*) is reflected in the ranking weights.
