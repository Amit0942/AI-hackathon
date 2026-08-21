"""D4 output types: `ReachEstimate`, `PackageLine`, `Package` (Step 2.1)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentiq.domain.explanation import Explanation, merge_confidence
from agentiq.domain.pricing import PriceQuote


class ReachEstimate(BaseModel):
    """Projected audience reach for one unit or a de-duplicated group of units.

    `unique_reach <= gross_impressions` always — the de-duplication is the
    entire point of Step 7.2, so this invariant is enforced at construction
    rather than trusted to whoever computes it.
    """

    model_config = ConfigDict(frozen=True)

    gross_impressions: float = Field(ge=0.0)
    unique_reach: float = Field(ge=0.0)
    frequency: float = Field(
        ge=0.0, description="gross_impressions / unique_reach, i.e. average exposures per person."
    )
    explanation: Explanation

    @model_validator(mode="after")
    def _unique_reach_bounded(self) -> ReachEstimate:
        if self.unique_reach > self.gross_impressions + 1e-6:
            raise ValueError(
                f"unique_reach ({self.unique_reach}) cannot exceed gross_impressions "
                f"({self.gross_impressions}) — de-duplication cannot create audience."
            )
        return self


class PackageLine(BaseModel):
    """One screen x time-block x date-range x slot-count decision within a package."""

    model_config = ConfigDict(frozen=True)

    screen_id: str
    time_block_id: int = Field(ge=1, le=6)
    slots: int = Field(ge=1, le=6)
    start_date: date
    end_date: date
    price_quote: PriceQuote
    relevance_score: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _date_range_valid(self) -> PackageLine:
        if self.end_date < self.start_date:
            raise ValueError(f"end_date {self.end_date} before start_date {self.start_date}")
        return self

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def line_value(self) -> float:
        return self.price_quote.recommended * self.slots * self.days


class Package(BaseModel):
    """A multi-location, multi-slot recommendation, priced and reasoned about as one deal
    (Step 7.3 — a bundle is one deal, not N independent line quotes).
    """

    model_config = ConfigDict(frozen=True)

    package_id: str
    brief_id: str
    label: str = Field(
        description="e.g. 'max-reach', 'best-value', 'premium-quality', "
        "'frequency-heavy' (Step 7.4)."
    )
    lines: tuple[PackageLine, ...] = Field(min_length=1)
    reach: ReachEstimate
    total_budget_used: float = Field(ge=0.0)
    bundle_discount_pct: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Explicit, bounded portfolio adjustment vs. summed line prices.",
    )
    optimizer_strategy: str = Field(
        description="e.g. 'greedy-submodular', 'ilp', 'local-search' — Step 7.2."
    )
    optimizer_guarantee: str = Field(
        default="", description="Stated approximation guarantee for the strategy used, if any."
    )
    explanation: Explanation

    @property
    def screen_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(line.screen_id for line in self.lines))

    @property
    def sum_of_line_values(self) -> float:
        return sum(line.line_value for line in self.lines)

    @property
    def confidence(self):  # -> Confidence
        return merge_confidence(*(line.price_quote.confidence for line in self.lines))
