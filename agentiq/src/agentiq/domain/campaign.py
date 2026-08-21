"""`CampaignBrief` (Step 2.1) — the resolved, engine-ready form of a brief.

`agentiq.data.briefs.DerivedBriefFields` is the *literal* parse of a document
(what it says). `CampaignBrief` is the *resolved* form (what it means to the
system) — zones, screen types and POI types bound against the real
vocabulary (Step 4.2), with anything unresolved carried forward rather than
dropped. Keeping these as two separate types is deliberate: it keeps the
lossless parse available for audit even after resolution has happened.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentiq.domain.enums import CampaignObjective, IndustryVertical


class GeographyConstraint(BaseModel):
    """A resolved location requirement — e.g. 'ACS: Downtown Core' or a POI-radius rule."""

    model_config = ConfigDict(frozen=True)

    city_id: str
    zone_name: str | None = None
    poi_type: str | None = None
    radius_km: float | None = Field(
        default=None,
        description="Walking-radius limit; validated range is 0.3-0.5 km (Step 1.6 §3).",
    )
    is_exclusion: bool = False


class CampaignBrief(BaseModel):
    """One resolved campaign request — the input to D2/D3/D4/D5."""

    model_config = ConfigDict(frozen=True)

    brief_id: str
    source_file: str
    company: str
    industry_vertical: IndustryVertical
    objective: CampaignObjective
    target_age_min: int | None = None
    target_age_max: int | None = None
    budget: float = Field(gt=0)
    start_date: date | None = None
    duration_days: int = Field(gt=0)
    slots_requested: int | None = Field(default=None, ge=1, le=6)
    time_block_ids: tuple[int, ...] = Field(
        default_factory=tuple,
        description="Requested time blocks; empty means no preference stated.",
    )
    weekend_weighting: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Fraction of exposure weight biased toward weekend dayparts, if requested.",
    )
    geography_constraints: tuple[GeographyConstraint, ...] = Field(default_factory=tuple)
    screen_type_exclusions: tuple[str, ...] = Field(default_factory=tuple)
    minimum_relevance_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Never buy cheap junk to inflate volume (Step 7.1).",
    )
    unresolved_requirements: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Capability gaps this brief exercises that the data doesn't directly support "
        "(Step 1.4 §5) — surfaced to the rep, never silently ignored.",
    )

    @property
    def end_date(self) -> date | None:
        if self.start_date is None:
            return None
        from datetime import timedelta

        return self.start_date + timedelta(days=self.duration_days - 1)

    @model_validator(mode="after")
    def _time_blocks_in_range(self) -> CampaignBrief:
        bad = [b for b in self.time_block_ids if not (1 <= b <= 6)]
        if bad:
            raise ValueError(f"time_block_ids out of range 1-6: {bad}")
        return self
