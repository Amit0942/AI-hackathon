"""Step 6.2 — Expected-footfall forecast.

Forecasts exposure for a campaign's *future* window — not just a historical
average — as `daypart curve x day-type mix x event uplift`, with a
confidence interval measured from the location/corridor's own observed
day-to-day ridership variability (`NetworkRepository.ridership_cv_for_*`),
never an invented band.

Distinct from Step 6.1's `DemandSignal`: that index is competitive/pipeline
*pricing pressure*; this is a forward-looking *audience* number, built from
D1's `AudienceProfileEngine` (now that D1 exists) rather than from booking
history. `PricingEngine` does not depend on this to build a `PriceQuote` —
it is a separate, citable number a rep sees alongside the quote.

**Holiday gap closed** (`docs/decisions/1.8_holiday_ridership_effect.md`):
a forecast date falling on a real US federal holiday (`pricing/holidays.py`,
computed, not a lookup table) has its exposure scaled by the measured
network-wide holiday ridership ratio (`config/pricing.yaml`
`footfall_forecast.holiday_ridership_multiplier`, ~0.543 — holidays see
*less* transit ridership network-wide, not more; the "malls up, offices
down" hypothesis was tested against real data and found unsupported — see
the decision doc). This is applied to the whole exposure figure as a stated
approximation: the multiplier is measured from transit ridership
specifically, and `AudienceProfile.est_daily_exposure` does not retain a
separate transit-vs-resident-vs-POI breakdown to scale more precisely.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from agentiq.audience import AudienceProfileEngine
from agentiq.audience.daypart import TIME_BLOCK_DAYPART
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.enums import Confidence
from agentiq.domain.explanation import Contribution, EvidenceRef, Explanation
from agentiq.domain.inventory import Screen
from agentiq.domain.pricing import FootfallForecast
from agentiq.pricing.demand import EVENT_TIER_WEIGHT
from agentiq.pricing.holidays import is_us_federal_holiday


@dataclass(frozen=True)
class _DayForecast:
    day_type: str
    base_exposure: float
    event_uplift: float
    is_holiday: bool


def _day_type(day: date) -> str:
    return "weekend" if day.weekday() >= 5 else "weekday"


def _daterange(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _forecast_one_day(
    screen: Screen,
    time_block_id: int,
    day: date,
    repos: InMemoryRepositories,
    audience_engine: AudienceProfileEngine,
    *,
    holiday_ridership_multiplier: float,
) -> _DayForecast:
    day_type = _day_type(day)
    profile = audience_engine.profile(screen)
    weights = (
        profile.daypart_weight_weekday if day_type == "weekday" else profile.daypart_weight_weekend
    )
    base_exposure = profile.est_daily_exposure * weights.get(time_block_id, 0.0)

    is_holiday = is_us_federal_holiday(day)
    if is_holiday:
        base_exposure *= holiday_ridership_multiplier

    active_events = repos.context.events_active(screen.city_id, day, day)
    surge = 0.0
    if not active_events.empty:
        daypart = TIME_BLOCK_DAYPART[time_block_id]
        on_daypart = active_events.loc[active_events["primary_impact_daypart"] == daypart]
        if not on_daypart.empty:
            weights_series = on_daypart["attendance_tier"].astype(str).map(EVENT_TIER_WEIGHT)
            surge = float(weights_series.fillna(0.0).sum())

    return _DayForecast(
        day_type=day_type, base_exposure=base_exposure, event_uplift=surge, is_holiday=is_holiday
    )


def _measured_cv(screen: Screen, repos: InMemoryRepositories, day_types_present: set[str]) -> float:
    """Weighted-average coefficient of variation across the day types actually
    present in the forecast window, from the screen's own location/corridor."""
    cv_lookup: Callable[[str, str], float]
    if screen.is_static and screen.location_id is not None:
        cv_lookup = repos.network.ridership_cv_for_location
        key = screen.location_id
    elif screen.vehicle_id is not None:
        corridor_id = repos.network.corridor_for_vehicle(screen.vehicle_id)
        if corridor_id is None:
            return 0.0
        cv_lookup = repos.network.ridership_cv_for_corridor
        key = corridor_id
    else:
        return 0.0

    cvs = [cv_lookup(key, day_type) for day_type in day_types_present]
    return sum(cvs) / len(cvs) if cvs else 0.0


def forecast_footfall(
    screen: Screen,
    time_block_id: int,
    start_date: date,
    end_date: date,
    repos: InMemoryRepositories,
    audience_engine: AudienceProfileEngine,
    *,
    std_dev_multiplier: float = 1.0,
    holiday_ridership_multiplier: float = 1.0,
) -> FootfallForecast:
    """Expected exposure for *screen* x *time_block_id* over `[start_date, end_date]`.

    The confidence interval assumes day-to-day exposure is independent
    within the window (`std_total = cv * expected_daily * sqrt(n_days)`) — a
    stated approximation; consecutive days' ridership is plausibly
    correlated (a bad-weather week depresses every day alike), which would
    make the true interval wider than this one. Flagged in
    `Explanation.fallbacks_used` rather than presented as exact.
    """
    if end_date < start_date:
        raise ValueError(f"end_date {end_date} before start_date {start_date}")

    days = list(_daterange(start_date, end_date))
    per_day = [
        _forecast_one_day(
            screen,
            time_block_id,
            day,
            repos,
            audience_engine,
            holiday_ridership_multiplier=holiday_ridership_multiplier,
        )
        for day in days
    ]

    base_total = sum(d.base_exposure for d in per_day)
    total = sum(d.base_exposure * (1.0 + d.event_uplift) for d in per_day)
    event_uplift_total = total - base_total
    n_days = len(per_day)
    expected_daily = total / n_days if n_days else 0.0
    holiday_count = sum(1 for d in per_day if d.is_holiday)

    day_types_present = {d.day_type for d in per_day}
    cv = _measured_cv(screen, repos, day_types_present)
    std_daily = cv * expected_daily
    std_total = std_daily * math.sqrt(n_days)
    ci_low = max(0.0, total - std_dev_multiplier * std_total)
    ci_high = total + std_dev_multiplier * std_total

    fallbacks: list[str] = ["independent_days_assumption_for_confidence_interval"]
    if cv == 0.0:
        fallbacks.append("no_measured_ridership_variance_zero_width_band_before_multiplier")

    contributions = [
        Contribution(
            signal="audience_exposure_base",
            direction="positive" if base_total > 0 else "neutral",
            weight=0.6,
            magnitude=base_total,
            detail=(
                f"D1 exposure model x this window's weekday/weekend daypart mix "
                f"({n_days} day(s))."
            ),
        ),
        Contribution(
            signal="event_uplift",
            direction="positive" if event_uplift_total > 0 else "neutral",
            weight=0.2,
            magnitude=event_uplift_total,
            detail="Attendance-tier-weighted uplift from events active on this block's daypart.",
        ),
    ]
    if holiday_count:
        holiday_reduction = sum(
            d.base_exposure / holiday_ridership_multiplier - d.base_exposure
            for d in per_day
            if d.is_holiday
        ) * -1.0
        contributions.append(
            Contribution(
                signal="holiday_ridership_effect",
                direction="negative" if holiday_reduction < 0 else "neutral",
                weight=0.2,
                magnitude=holiday_reduction,
                detail=(
                    f"{holiday_count} US federal holiday day(s) in this window, exposure "
                    f"scaled by the measured network-wide ratio "
                    f"{holiday_ridership_multiplier:.3f} "
                    "(docs/decisions/1.8_holiday_ridership_effect.md)."
                ),
            )
        )

    explanation = Explanation(
        headline=(
            f"{screen.screen_id}: forecast {total:,.0f} exposure over {n_days} day(s) "
            f"({start_date} to {end_date}), +/-{std_dev_multiplier:.1f} sigma band "
            f"[{ci_low:,.0f}, {ci_high:,.0f}]."
        ),
        contributions=tuple(contributions),
        evidence=(
            EvidenceRef(
                table="ridership_actuals",
                row_key={"screen_id": screen.screen_id},
                field="actual_ridership",
                value=round(cv, 4),
                note="Measured coefficient of variation of this location/corridor's own "
                "day-to-day total ridership — the confidence interval's width.",
            ),
        ),
        confidence=Confidence.MEDIUM,
        confidence_reason=(
            "Built from D1's exposure model, a measured (not invented) ridership variance, "
            "and a real holiday calendar with a measured (not invented) holiday multiplier — "
            "but still assumes independent days within the window, so medium, not high."
        ),
        fallbacks_used=tuple(fallbacks),
    )

    return FootfallForecast(
        screen_id=screen.screen_id,
        time_block_id=time_block_id,
        start_date=start_date,
        end_date=end_date,
        expected_total_footfall=total,
        expected_daily_footfall=expected_daily,
        confidence_interval_low=ci_low,
        confidence_interval_high=ci_high,
        explanation=explanation,
    )
