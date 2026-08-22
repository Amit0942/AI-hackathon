# ADR 0005: Phase 4 (Brief Intake & Resolution) build scope

## Status

Accepted

## Context

`agentiq.data.briefs` (Step 1.8) parses a raw `.docx` into `DerivedBriefFields`
— a lossless, literal extraction (budget text, audience text, exclusion
sentences, location-requirement labels) with **no binding to any enum,
zone, or POI type**. Its own docstring says resolution "happens later." No
function anywhere converted that into a real `agentiq.domain.CampaignBrief`
— confirmed by a repo-wide search for `CampaignBrief(` returning only the
class definition and hand-built test fixtures. Every prior `HANDOFF.md`
entry explicitly deferred this as its own scope item, not something D5 can
fill in-line.

This gap blocks D5 (Phase 8): its first tool, `resolve_entities`, has
nothing behind it. This ADR scopes and documents Phase 4's Steps 4.1–4.3
before writing code, per this repo's own discipline (ADR-0003, ADR-0004).

**A load-bearing finding first:** the `CampaignBrief` and `GeographyConstraint`
domain types (Phase 2) already anticipate this work exactly —
`requested_environment_types`'s own docstring reads "Step 4.2 output: brief
location language resolved onto config/taxonomy.yaml's environment_types
vocabulary," and `screen_type_exclusions` already documents a
`"type:position"` convention (e.g. `"bus:back"`) specifically for a
bus-rear exclusion. **No domain-model or repository-protocol change was
needed for this work** — everything Phase 4 needs to populate already
exists as a field with the right shape. This ADR only had to design the
*text → value* resolution logic.

## Decisions

### 1. Resolution lives in `data/resolution.py`, not a new package

Alongside `data/briefs.py` (the literal parser), matching
`CLAUDE.md`'s architecture map, which already treats brief-format concerns
as `data/` content rather than a dedicated engine directory.

### 2. Industry vertical & objective: earliest-keyword-wins, not a fixed priority list

Both are resolved by scanning the raw text for a config-declared
`(keyword, value)` pair and picking whichever keyword's **string position**
is earliest — not whichever rule appears first in the config list. This
was verified, not assumed: all six real briefs state a compound
label ("Brand Awareness & Test-Drive Bookings", "Seasonal Footfall & Sale
Awareness"), and the client's own emphasis order is which phrase comes
first in the sentence. Checked against every real brief
(`docs/briefs/*.md`'s hand-read primary objective) — earliest-position
matching reproduces the hand-read primary objective in all 6/6 cases,
including brief 3 and 4 where "footfall" (→ conversion) precedes
"awareness"/"recall" and correctly wins.

`CampaignBrief.objective` is a single field (no secondary) — this pass
resolves **primary only**. A secondary-objective field is a real, separate
domain-model extension, deferred as out of scope (not needed by any
existing D2/D3/D4 consumer today).

Both vocabularies have a config-declared default (`retail` /
`awareness`) for the case where nothing matches, so `resolve_brief` never
raises on a real brief — falling back is recorded in
`unresolved_requirements`, never silent.

### 3. Environment-type resolution: exact label lookup first, normalization fallback second

Per-brief location-requirement **labels** (the bold heading before the
colon) are checked against an explicit `label -> environment_type` map in
`config/taxonomy.yaml`, built from the six real briefs' own labels.
`HANDOFF.md` already recorded that the `environment_types` vocabulary
itself was derived from this exact language, so an explicit map — not a
fuzzy matcher — correctly resolves all 14 known labels with zero ambiguity.
Anything not in the map falls through a normalization heuristic
(lowercase, strip punctuation, join on underscores, check literal
membership in `environment_types`) before being recorded as unresolved.

**A label resolving onto an environment type does not mean the type is
grounded in real data.** `airport_transit_corridor` and
`auto_retail_arterial_corridor` resolve textually from briefs 5 and 1 even
though D1's semantic labeller (per its own `HANDOFF.md` entry) never
assigns them — no POI type in the 13-value vocabulary grounds either. This
is correct, not a bug: Phase 4's job is to carry the brief's stated intent
forward honestly; whether the data can satisfy it is D1/D2's finding to
surface, not Phase 4's to hide by silently dropping the label.

### 4. City resolution: substring search against `cities.city_name`, no match = no restriction

`city_id` is stated in the labelled header of **zero** of six briefs — the
three that name a city do so only in free-text prose ("launching...in Las
Hackland"). Resolution searches `document.raw_text` for a substring match
against every `cities.city_name` (read once via `repos.lake["cities"]`,
matching the precedent set in `pricing/__init__.py` and
`relevance/__init__.py` of reading `repos.lake[...]` directly for one-time
setup joins that have no repository method yet).

When exactly one city matches, a single non-exclusion
`GeographyConstraint(city_id=...)` is added, narrowing eligibility
correctly (`eligibility.py`'s `required` filter). When zero or more than
one city matches, **no constraint is added** — the brief is left to search
all three cities, which is the actually-correct behaviour for an unstated
city (a wrong single-city guess would silently discard real candidates;
searching everywhere discards nothing) — and the ambiguity is surfaced as
a `ClarificationQuestion`, per Step 4.3's "ask, don't guess."

### 5. Value-tier / high-density-residential exclusion: a zone-level proxy, config-driven

`cities.market_tier` is city-grain (one tier per city) — there is no
within-city inventory tier anywhere in the schema (Step 1.8's finding,
`docs/briefs/campaign_1.md` §4). When an exclusion's text contains a
configured trigger phrase ("value-tier"), the resolver computes
`zone_demographics.income_index < value_tier_residential_income_index_max
AND population_density_per_sqkm > value_tier_residential_density_min`
for the resolved city (via `repos.lake["zone_demographics"]`) and adds one
exclusion `GeographyConstraint` per matching zone. Thresholds live in
`config/taxonomy.yaml`, not code (CLAUDE.md: "config over code"), and every
application of this proxy is recorded as a `ClarificationQuestion` asking
the rep to confirm the derived zone list, since the thresholds are ours,
not the client's.

### 6. Bus-rear exclusion: uses the existing `"type:position"` convention directly

No new mechanism needed — `screen_type_exclusions` already supports
`"bus:back"` (built by the D2 author specifically for this case, per its
own docstring). The resolver just maps the trigger phrase to that string
via `config/taxonomy.yaml`'s `screen_exclusion_phrases`.

### 7. Hyper-local outlet resolution: zone-level default, explicitly short of a true radius

Brief 4 names its outlet only by type ("a business-park food court"), not
by name — there is no POI-name-matching mechanism, and inventing one for a
single brief would be over-fit. **Default:** resolve the city, then pick
the single highest-`est_daily_footfall` POI among
`hyperlocal_outlet_poi_types` in that city, and add a non-exclusion
`GeographyConstraint(city_id=..., zone_name=<that POI's zone>)`.

This is a **stated approximation, not a true walking radius** —
`GeographyConstraint` has no location-level field, only `zone_name`/
`poi_type`+`radius_km` (which matches *any* POI of that type within
range, network-wide, not one specific named outlet). A zone is the
finest granularity the domain model can express without a location-level
extension, which this pass declines to add for one brief. Recorded as a
`ClarificationQuestion` naming the exact assumption and asking the rep to
confirm or name the real outlet.

### 8. Daypart / weekend-weighting resolution: a small, explicit keyword table, not an NLP parser

Covers only the keyword patterns actually present across the six real
briefs (`late evening`, `early morning`, `lunch`/`midday` → block 4 not
block 3 — dim_slot's literal "midday" block (08:00–12:00) is too early for
a stated lunch window; `weekend weighting` / `ahead of the weekend` at two
different confidence tiers). No match → empty `time_block_ids` /
`weekend_weighting=None`, which `relevance/signals.py`'s
`daypart_alignment` already treats as "no stated preference" (neutral
1.0), a safe default. Building a general daypart-language parser is
explicitly out of scope — the six-brief vocabulary is small and closed
enough that a keyword table is the honest, thin-slice answer; extending it
is a config edit, not a code change, when a seventh brief needs a new
phrase.

### 9. Step 4.3 (clarification loop): "ask AND state the assumption," never a hard block

`solution_plan.md` Step 4.3 is explicit: *"the agent asks a targeted
question and states the assumption it would otherwise use."* Every
resolution decision above that involved a judgment call (city ambiguous,
outlet unnamed, value-tier proxy applied, industry/objective fell back to
a default) produces one `ClarificationQuestion` (`question`,
`default_assumption`, `blocking: bool`) alongside the resolved
`CampaignBrief` — never a raised exception, never a silently-guessed value
with no record. `resolve_brief()` returns a `ResolvedBrief` (the
`CampaignBrief` plus its `tuple[ClarificationQuestion, ...]`), so a caller
(D5, or eventually D6's UI) can always inspect what was assumed. `blocking`
is `True` only for the outlet-unnamed and city-ambiguous cases — genuinely
different plans depending on the answer — everything else is
informational (a stated default the pipeline is happy to proceed on).

## Consequences

- `CampaignBrief.unresolved_requirements` carries forward every
  `DerivedBriefFields.unresolved_requirements` entry (Step 1.8's
  capability-probe findings) plus any resolver-specific gap (unmapped
  environment label, defaulted vertical/objective) — nothing from the
  literal parse is dropped during resolution.
- `ClarificationQuestion` is a plain dataclass in `resolution.py`, not a
  `domain/` pydantic type — it carries no scored/priced/ranked number, so
  CLAUDE.md's `Explanation` requirement does not apply to it.
- No domain-model or repository-protocol change was required (see
  §Context) — a genuine, checked finding, not an assumption.
- `daypart_keywords`/`weekend_weighting_*` config is explicitly scoped to
  the six known briefs' language; extending coverage is a config edit.
