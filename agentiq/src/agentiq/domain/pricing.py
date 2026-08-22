"""D3 output types: `DemandSignal` and `PriceQuote` (Step 2.1).

`PriceQuote` is the structural embodiment of the pricing guardrails the
business currently lacks (problem statement §1): floor, target, cap and a
recommended price, every one of them required to carry an `Explanation` and
every one of them subject to the `floor <= target <= cap` invariant that
Step 6's exit criteria demand as a property test, not a spot check.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentiq.domain.enums import ColdStartRung, Confidence
from agentiq.domain.explanation import Explanation


class FootfallForecast(BaseModel):
    """Step 6.2: expected audience exposure for a screen x time-block over a
    future campaign window, with a measured confidence interval.

    Distinct from `DemandSignal` (Step 6.1, competitive/pipeline pressure):
    this is a forward-looking *exposure* number — how many people are
    expected to see the screen — built from D1's own exposure model plus
    day-type mix and event uplift over the window, not from booking history.
    """

    model_config = ConfigDict(frozen=True)

    screen_id: str
    time_block_id: int = Field(ge=1, le=6)
    start_date: date
    end_date: date
    expected_total_footfall: float = Field(ge=0.0)
    expected_daily_footfall: float = Field(ge=0.0)
    confidence_interval_low: float = Field(ge=0.0)
    confidence_interval_high: float = Field(ge=0.0)
    explanation: Explanation

    @model_validator(mode="after")
    def _window_and_interval_valid(self) -> FootfallForecast:
        if self.end_date < self.start_date:
            raise ValueError(f"end_date {self.end_date} before start_date {self.start_date}")
        if not (
            self.confidence_interval_low
            <= self.expected_total_footfall
            <= self.confidence_interval_high
        ):
            raise ValueError(
                f"expected_total_footfall {self.expected_total_footfall} outside its own "
                f"confidence interval [{self.confidence_interval_low}, "
                f"{self.confidence_interval_high}] for {self.screen_id}/{self.time_block_id}."
            )
        return self

    @property
    def window_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


class DemandSignal(BaseModel):
    """One screen x time-block's demand intensity index (Step 6.1).

    `index` is unbounded-above but centred on 1.0 = "typical" so a demand
    multiplier can be read directly off it (e.g. index=1.3 -> +30% pressure).
    Each component is broken out because Step 6.1 names five distinct
    signals and the explanation must be able to say which one is driving
    the number, not just report the blend.
    """

    model_config = ConfigDict(frozen=True)

    screen_id: str
    time_block_id: int = Field(ge=1, le=6)
    index: float = Field(ge=0.0)
    committed_occupancy: float = Field(
        ge=0.0, le=1.0, description="Share of capacity already claimed."
    )
    historical_rhythm: float = Field(
        description="Seasonality/day-of-week/daypart multiplier, centred at 1.0."
    )
    pipeline_pressure: float = Field(
        ge=0.0, description="Recency-decayed open/lost-lead pressure for this unit."
    )
    event_surge: float = Field(
        ge=0.0, description="Event-driven uplift, 0 when no event is in range/window."
    )
    segment_heat: float = Field(
        ge=0.0, description="Recent demand from the brief's industry vertical."
    )
    explanation: Explanation


class PriceQuote(BaseModel):
    """floor / target / cap + recommended price for one screen-slot (Step 6.3-6.4)."""

    model_config = ConfigDict(frozen=True)

    screen_id: str
    time_block_id: int = Field(ge=1, le=6)
    slots: int = Field(ge=1, le=6)
    floor: float = Field(gt=0)
    target: float = Field(gt=0)
    cap: float = Field(gt=0)
    recommended: float = Field(gt=0)
    win_probability_at_recommended: float = Field(ge=0.0, le=1.0)
    cold_start_rung: ColdStartRung
    confidence: Confidence
    explanation: Explanation
    human_overrides: dict[str, float | str] = Field(
        default_factory=dict,
        description="Logged rep-supplied inputs that adjusted this band (Step 6.6) — "
        "never a silent edit, always visible here and in the trace.",
    )

    @model_validator(mode="after")
    def _band_ordering(self) -> PriceQuote:
        if not (self.floor <= self.target <= self.cap):
            raise ValueError(
                f"Price band invariant violated for {self.screen_id}/{self.time_block_id}: "
                f"floor={self.floor} target={self.target} cap={self.cap} — "
                "floor <= target <= cap must always hold (Step 6 exit criteria)."
            )
        if not (self.floor <= self.recommended <= self.cap):
            raise ValueError(
                f"Recommended price {self.recommended} outside [floor, cap] "
                f"=[{self.floor}, {self.cap}] for {self.screen_id}/{self.time_block_id}."
            )
        return self

    @property
    def total_for_slots(self) -> float:
        return self.recommended * self.slots
