"""Sales-rep performance domain types — a simulated layer, not a measured one.

No `sales_rep_id` (or any rep entity) exists anywhere in the raw data
(`bookings.csv`, `lost_leads.csv`) — Urban Media never captured who sold
what. These types let a rep's actual sales be scored against D3's real
`PriceQuote` guardrails (`floor`/`target`/`cap`) and a stated revenue target,
so the scoring math is grounded in real pricing output even though the rep
identity and target itself are necessarily simulated inputs, not measured
facts. See `config/rep_scoring.yaml` for the stated (not calibrated) blend
weights — there is no historical "this rep's real score was X" ground truth
to fit against.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentiq.domain.explanation import Explanation
from agentiq.domain.pricing import PriceQuote


class SalesRep(BaseModel):
    """A rep and their revenue target for one scoring period."""

    model_config = ConfigDict(frozen=True)

    rep_id: str
    name: str
    target_revenue: float = Field(gt=0)
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def _period_valid(self) -> SalesRep:
        if self.period_end < self.period_start:
            raise ValueError(
                f"period_end {self.period_end} before period_start {self.period_start} "
                f"for rep {self.rep_id!r}"
            )
        return self


class RepSale(BaseModel):
    """One deal a rep actually closed — the real `sold_price` against the
    `PriceQuote` D3 offered as guidance, not necessarily equal to it."""

    model_config = ConfigDict(frozen=True)

    rep_id: str
    screen_id: str
    time_block_id: int = Field(ge=1, le=6)
    slots: int = Field(ge=1, le=6)
    days: int = Field(gt=0)
    sold_price: float = Field(gt=0)
    sold_date: date
    price_quote: PriceQuote

    @property
    def deal_value(self) -> float:
        return self.sold_price * self.slots * self.days

    @property
    def discount_vs_target_pct(self) -> float:
        """Positive when sold below target, negative when sold above it."""
        target = self.price_quote.target
        return (target - self.sold_price) / target if target > 0 else 0.0


class RepPerformance(BaseModel):
    """One rep's scored performance over their target period (Explanation-carrying,
    per CLAUDE.md's rule for every scored output)."""

    model_config = ConfigDict(frozen=True)

    rep_id: str
    period_start: date
    period_end: date
    sale_count: int = Field(ge=0)
    total_revenue: float = Field(ge=0.0)
    target_revenue: float = Field(gt=0)
    target_attainment_pct: float = Field(
        ge=0.0, description="total_revenue / target_revenue, uncapped — can exceed 1.0."
    )
    average_margin_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Mean per-sale margin_score: 1.0 = sold at/above target, 0.0 = sold at floor.",
    )
    rep_score: float = Field(ge=0.0, le=1.0)
    explanation: Explanation

    @property
    def is_over_target(self) -> bool:
        return self.target_attainment_pct >= 1.0
