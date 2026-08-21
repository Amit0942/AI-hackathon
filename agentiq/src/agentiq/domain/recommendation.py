"""D5 output type: `Recommendation` (Step 2.1) — brief in, complete answer out."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from agentiq.domain.campaign import CampaignBrief
from agentiq.domain.optimizer import Package


class Recommendation(BaseModel):
    """The full answer to one campaign brief: alternatives, not one take-it-or-leave-it package.

    `narrative` is composed by the Step 8.4 agent strictly *from* the
    structured `packages` — the hard rule in ADR-0001/CLAUDE.md is that a
    validation pass checks every figure quoted in `narrative` against the
    numbers in `packages` and fails the response on any mismatch, so this
    type deliberately keeps both fields side by side for that check to run.
    """

    model_config = ConfigDict(frozen=True)

    recommendation_id: str
    brief: CampaignBrief
    packages: tuple[Package, ...] = Field(
        min_length=1,
        description="Efficient-frontier variants (Step 7.4): max-reach, best-value, etc.",
    )
    primary_package_id: str = Field(
        description="Which package.package_id is the lead recommendation."
    )
    narrative: str = Field(
        default="", description="Client-ready prose composed from `packages` only (Step 8.4)."
    )
    trace_id: str | None = None
    generated_at: datetime

    @property
    def primary_package(self) -> Package:
        for package in self.packages:
            if package.package_id == self.primary_package_id:
                return package
        raise KeyError(f"primary_package_id {self.primary_package_id!r} not found in packages")
