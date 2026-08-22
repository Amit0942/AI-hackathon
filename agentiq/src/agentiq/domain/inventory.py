"""Inventory-side domain types (Step 2.1): `Screen`, `SellableUnit`, `AudienceProfile`.

These mirror the measured facts in `docs/decisions/1.4_inventory_shape.md` and
`1.6_context_profile.md` — e.g. capacity is 6 rotation slots (proven, not
assumed), and a screen's location XOR vehicle decides its exposure model.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentiq.domain.enums import MarketTier, MountPosition, ScreenSize, ScreenType
from agentiq.domain.explanation import Explanation

#: Measured, proved ceiling (Step 1.4 §1.3) — never a magic number in engine code.
MAX_ROTATION_SLOTS = 6
#: Six four-hour blocks cover the day with no gaps or overlaps (dim_slot).
TIME_BLOCK_IDS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)


class Screen(BaseModel):
    """One physical screen — the unit that is sold (mirrors `screens.csv`)."""

    model_config = ConfigDict(frozen=True)

    screen_id: str
    city_id: str
    screen_type: ScreenType
    position: MountPosition | None = Field(
        default=None, description="Null for metro_rail_coach interior panels — a structural null."
    )
    screen_size: ScreenSize
    location_id: str | None = None
    vehicle_id: str | None = None

    @model_validator(mode="after")
    def _location_xor_vehicle(self) -> Screen:
        has_location = self.location_id is not None
        has_vehicle = self.vehicle_id is not None
        if has_location == has_vehicle:
            raise ValueError(
                f"Screen {self.screen_id!r} must have exactly one of location_id/vehicle_id "
                f"(got location_id={self.location_id!r}, vehicle_id={self.vehicle_id!r}) — "
                "measured invariant, Step 1.1."
            )
        if self.is_static != self.screen_type.is_static:
            raise ValueError(
                f"Screen {self.screen_id!r}: screen_type {self.screen_type} disagrees with the "
                "location/vehicle split — Step 1.4 §2.1 found this to be a measured 1:1 match."
            )
        return self

    @property
    def is_static(self) -> bool:
        return self.location_id is not None

    @property
    def is_mobile(self) -> bool:
        return not self.is_static


class SellableUnit(BaseModel):
    """screen x time_block x date, holding up to `MAX_ROTATION_SLOTS` rotation slots.

    This is the atomic unit Phase 6 prices and Phase 7 allocates — never a
    bare (screen, date) pair, which would silently ignore the time-block and
    slot-count dimensions.
    """

    model_config = ConfigDict(frozen=True)

    screen_id: str
    time_block_id: int = Field(ge=1, le=6)
    unit_date: date

    def slot_count_valid(self, slots: int) -> bool:
        return 1 <= slots <= MAX_ROTATION_SLOTS


class AudienceProfile(BaseModel):
    """D1 output: who is near this screen, when, and why.

    `daypart_weight` sums to ~1.0 across the six time blocks and is the
    normalised exposure curve (Step 1.6 §6) — distinct per weekday/weekend
    per Step 1.6's finding that the two peak on different blocks.
    """

    model_config = ConfigDict(frozen=True)

    screen_id: str
    market_tier: MarketTier
    dominant_occupation: str = Field(
        description="Zone's dominant_occupation — the sharpest categorical audience "
        "discriminator (Step 1.6 §5)."
    )
    daypart_weight_weekday: dict[int, float] = Field(
        description="time_block_id -> normalised exposure share, weekday."
    )
    daypart_weight_weekend: dict[int, float] = Field(
        description="time_block_id -> normalised exposure share, weekend."
    )
    environment_labels: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Semantic labels from config/taxonomy.yaml's environment_types — LLM-assigned, "
        "controlled vocabulary only (Phase 3.3).",
    )
    est_daily_exposure: float = Field(
        ge=0,
        description="Estimated daily audience — footfall (static) or ridership (mobile) based.",
    )
    has_history: bool = Field(
        description="False triggers the D3 cold-start ladder; D1 itself never has a coverage gap "
        "(Step 1.7 §4 — every screen has POI or ridership coverage)."
    )
    explanation: Explanation = Field(
        description="Per CLAUDE.md's Explanation contract — every scored/ranked output must "
        "carry one, including this exposure/audience estimate."
    )

    @model_validator(mode="after")
    def _daypart_weights_cover_known_blocks(self) -> AudienceProfile:
        for name, weights in (
            ("daypart_weight_weekday", self.daypart_weight_weekday),
            ("daypart_weight_weekend", self.daypart_weight_weekend),
        ):
            unknown = set(weights) - set(TIME_BLOCK_IDS)
            if unknown:
                raise ValueError(f"{name} has unknown time_block_id(s): {sorted(unknown)}")
        return self
