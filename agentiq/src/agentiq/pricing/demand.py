"""Step 6.1 — Demand intensity index.

One interpretable index per screen x time-block x date, built entirely from
signals that exist in the raw tables (`docs/decisions/1.5_demand_profile.md`,
solution_plan.md Phase 6.1). Five components, each independently named so an
`Explanation` can say which one is driving the number rather than reporting
only the blend:

* `committed_occupancy` — scarcity, from `occupancy_events()` (Step 1.5 §3).
* `historical_rhythm` — seasonality/day-of-week/daypart multiplier from
  settled bookings, centred at 1.0.
* `pipeline_pressure` — open leads for this geography/screen, recency-decayed
  (ADR-0003 decision 6 covers the still-deferred segment_heat/brief link;
  pipeline_pressure itself needs no brief and is built now).
* `event_surge` — scheduled events weighted by attendance tier and impact
  radius/daypart (Step 1.6).
* `segment_heat` — recent demand from the brief's industry vertical; an
  *optional* input per ADR-0003 decision 6, since brief intake (D2) doesn't
  exist yet. Defaults to a neutral 1.0 (no uplift, no discount) when no
  vertical is supplied.

`index` is centred on 1.0 = "typical", per `domain/pricing.py`'s docstring,
so Step 6.3 can read a demand multiplier directly off it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from agentiq.domain.enums import Confidence, IndustryVertical
from agentiq.domain.explanation import Contribution, EvidenceRef, Explanation
from agentiq.domain.pricing import DemandSignal

#: Step 6.1: "every pipeline signal is weighted by an explicit decay function
#: of age" — the half-life lives in config/pricing.yaml, not hardcoded here;
#: callers read it from config and pass it in (see `pricing/__init__.py`).
DEFAULT_RECENCY_HALF_LIFE_DAYS = 21.0

#: Event attendance tiers, per 1.6's measured vocabulary — banded so a single
#: outlier attendance figure cannot distort the surge multiplier.
EVENT_TIER_WEIGHT = {"small": 0.10, "medium": 0.25, "large": 0.50}


def recency_decay_weight(age_days: float, *, half_life_days: float) -> float:
    """Exponential decay: a lead `half_life_days` old counts for half as much as fresh.

    Step 6.1: "the decay half-life is a config parameter and is shown in the
    UI — an aged lead visibly counts for less." Never negative; a
    zero-or-negative age (a lead arriving "today" or in the future, which
    should not happen but must not crash) clamps to full weight.
    """
    if age_days <= 0:
        return 1.0
    return float(0.5 ** (age_days / half_life_days))


def historical_rhythm(
    settled_bookings: pd.DataFrame,
    screen_id: str,
    time_block_id: int,
) -> float:
    """Seasonality/day-of-week multiplier for this screen x block, centred at 1.0.

    Uses this screen's own settled-booking count for the block, relative to
    its network-wide average across blocks, as the rhythm signal. A screen
    with no settled history at all returns 1.0 (neutral) — the cold-start
    ladder (Step 6.5), not this function, is responsible for handling a
    screen's overall lack of history.
    """
    screen_rows = settled_bookings.loc[settled_bookings["screen_id"] == screen_id]
    if screen_rows.empty:
        return 1.0

    per_block = screen_rows.groupby("time_block_id").size()
    block_count = float(per_block.get(time_block_id, 0))
    mean_count = float(per_block.mean()) if len(per_block) else 0.0
    if mean_count <= 0:
        return 1.0
    return block_count / mean_count


def pipeline_pressure(
    open_leads: pd.DataFrame,
    *,
    as_of_date: date,
    anchor_screen_id: str | None = None,
    city_id: str | None = None,
    half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
) -> float:
    """Recency-decayed sum of open-lead pressure for this unit's screen or city.

    Step 6.1: "open/lost leads requesting this geography, screen or window ...
    competition for the same inventory that week is exactly the blind spot
    the problem statement names." Filters to leads naming this exact screen
    when `anchor_screen_id` is given (the strongest match); falls back to
    city-wide pressure otherwise. Each lead's contribution is weighted by
    `recency_decay_weight` on its age as of `as_of_date`.
    """
    rows = open_leads
    if anchor_screen_id is not None:
        rows = rows.loc[rows["anchor_screen_id"] == anchor_screen_id]
    elif city_id is not None:
        rows = rows.loc[rows["city_id"] == city_id]

    if rows.empty:
        return 0.0

    lead_dates = pd.to_datetime(rows["lead_date"]).dt.date
    ages = lead_dates.map(lambda d: (as_of_date - d).days)
    weights = ages.map(lambda a: recency_decay_weight(a, half_life_days=half_life_days))
    return float(weights.sum())


def event_surge(
    active_events: pd.DataFrame,
    *,
    time_block_daypart: str,
) -> float:
    """Event-driven uplift for a screen already known to be within an event's reach.

    *active_events* must already be filtered to events whose impact window
    and radius cover this screen's location (`ContextRepository.events_active`
    plus a distance/radius check is the caller's job — this function only
    aggregates attendance-tier weight for events landing on this time block's
    daypart). Zero when no event applies, per `DemandSignal.event_surge`'s
    contract ("0 when no event is in range/window").
    """
    if active_events.empty:
        return 0.0
    on_daypart = active_events.loc[active_events["primary_impact_daypart"] == time_block_daypart]
    if on_daypart.empty:
        return 0.0
    # `.astype(str)` first: `attendance_tier` is a pandas `category` dtype
    # column, and `.map(...)` on a Categorical can return a Categorical
    # result whose `.fillna(0.0)` then raises ("Cannot setitem on a
    # Categorical with a new category") even though every real value maps
    # successfully — found while running D5 end-to-end against a brief with
    # an active event (ADR-0006). Casting to plain strings first avoids any
    # categorical-dtype propagation through `.map`/`.fillna`.
    weights = on_daypart["attendance_tier"].astype(str).map(EVENT_TIER_WEIGHT).fillna(0.0)
    return float(weights.sum())


def segment_heat(
    settled_bookings: pd.DataFrame,
    *,
    industry_vertical: IndustryVertical | None,
    city_id: str,
) -> float:
    """Recent demand from the brief's industry vertical, centred at 1.0 (neutral).

    ADR-0003 decision 6: `industry_vertical` is optional because D2/brief
    intake doesn't exist yet. `None` means "no brief context available" and
    returns a flat 1.0 — no uplift, no discount — rather than guessing.
    """
    if industry_vertical is None:
        return 1.0

    city_rows = settled_bookings.loc[settled_bookings["city_id"] == city_id]
    if city_rows.empty:
        return 1.0

    vertical_share = float((city_rows["industry_vertical"] == industry_vertical.value).mean())
    n_verticals = city_rows["industry_vertical"].nunique() or 1
    baseline_share = 1.0 / n_verticals
    if baseline_share <= 0:
        return 1.0
    return vertical_share / baseline_share


@dataclass(frozen=True)
class DemandIndexInputs:
    """Pre-fetched, per-unit slices the caller assembles from repositories.

    Bundling these as one dataclass keeps `compute_demand_signal`'s
    signature stable as new components are added, and keeps repository
    lookups (which need indexes/filters the caller already has open) out of
    this module — `pricing/` computes, it does not fetch (CLAUDE.md:
    "Repositories, not file paths").
    """

    settled_bookings: pd.DataFrame
    occupancy_timeline: pd.DataFrame
    open_leads: pd.DataFrame
    active_events: pd.DataFrame
    time_block_daypart: str
    city_id: str
    industry_vertical: IndustryVertical | None = None
    recency_half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS


def compute_demand_signal(
    screen_id: str,
    time_block_id: int,
    on_date: date,
    inputs: DemandIndexInputs,
) -> DemandSignal:
    """Assemble the five Step 6.1 components into one `DemandSignal` with its `Explanation`.

    `index` blends the components additively around the 1.0 centre-point:
    `index = historical_rhythm * (1 + pipeline_pressure_norm + event_surge + (segment_heat - 1))`
    adjusted by occupancy separately (occupancy is reported, not blended into
    `index`, since Step 6.3 treats scarcity as a distinct guardrail input —
    see `bands.py`). This keeps the additive/multiplicative structure legible
    for the `Explanation`'s per-signal contributions.
    """
    from agentiq.data.occupancy import committed_occupancy_share

    occ = committed_occupancy_share(inputs.occupancy_timeline, screen_id, time_block_id, on_date)
    rhythm = historical_rhythm(inputs.settled_bookings, screen_id, time_block_id)
    pressure = pipeline_pressure(
        inputs.open_leads,
        as_of_date=on_date,
        anchor_screen_id=screen_id,
        city_id=inputs.city_id,
        half_life_days=inputs.recency_half_life_days,
    )
    surge = event_surge(inputs.active_events, time_block_daypart=inputs.time_block_daypart)
    heat = segment_heat(
        inputs.settled_bookings,
        industry_vertical=inputs.industry_vertical,
        city_id=inputs.city_id,
    )

    # Pipeline pressure is unbounded (sum of decayed lead weights); normalise
    # it onto a comparable 0-1-ish scale via a saturating transform so it
    # cannot dominate the index the way a raw count would with many leads.
    pressure_norm = 1.0 - np.exp(-pressure / 3.0)

    index = rhythm * (1.0 + pressure_norm + surge + (heat - 1.0))
    index = max(index, 0.0)

    contributions = (
        Contribution(
            signal="committed_occupancy",
            direction="positive" if occ > 0 else "neutral",
            weight=0.30,
            magnitude=occ,
            detail="Share of this screen-block's capacity already claimed by committed bookings.",
        ),
        Contribution(
            signal="historical_rhythm",
            direction="positive" if rhythm > 1.0 else ("negative" if rhythm < 1.0 else "neutral"),
            weight=0.25,
            magnitude=rhythm - 1.0,
            detail="This screen's settled-booking share of this time block vs. its own average block.",
        ),
        Contribution(
            signal="pipeline_pressure",
            direction="positive" if pressure_norm > 0 else "neutral",
            weight=0.20,
            magnitude=pressure_norm,
            detail=f"Recency-decayed open-lead pressure (half-life {inputs.recency_half_life_days:.0f}d).",
        ),
        Contribution(
            signal="event_surge",
            direction="positive" if surge > 0 else "neutral",
            weight=0.15,
            magnitude=surge,
            detail="Attendance-tier-weighted uplift from events active on this time block's daypart.",
        ),
        Contribution(
            signal="segment_heat",
            direction="positive" if heat > 1.0 else ("negative" if heat < 1.0 else "neutral"),
            weight=0.10,
            magnitude=heat - 1.0,
            detail=(
                "Recent demand from the brief's industry vertical vs. the city baseline."
                if inputs.industry_vertical is not None
                else "No brief/industry-vertical context supplied yet — neutral (no D2 dependency)."
            ),
        ),
    )

    fallbacks: tuple[str, ...] = ()
    if inputs.industry_vertical is None:
        fallbacks = ("segment_heat_neutral_no_brief_context",)

    headline = (
        f"Demand index {index:.2f} for {screen_id}/block {time_block_id}: "
        f"{'above' if index > 1.0 else 'at or below'} typical pressure."
    )

    explanation = Explanation(
        headline=headline,
        contributions=contributions,
        evidence=(
            EvidenceRef(
                table="bookings",
                row_key={"screen_id": screen_id, "time_block_id": time_block_id},
                field="booking_status",
                value="completed",
                note="Settled-booking rows used for historical_rhythm and segment_heat.",
            ),
        ),
        confidence=Confidence.MEDIUM,
        confidence_reason=(
            "Demand index blends five measured components; medium because segment_heat "
            "has no brief context yet."
            if inputs.industry_vertical is None
            else "Demand index blends five measured, non-fallback components."
        ),
        fallbacks_used=fallbacks,
    )

    return DemandSignal(
        screen_id=screen_id,
        time_block_id=time_block_id,
        index=index,
        committed_occupancy=occ,
        historical_rhythm=rhythm,
        pipeline_pressure=pressure_norm,
        event_surge=surge,
        segment_heat=heat,
        explanation=explanation,
    )
