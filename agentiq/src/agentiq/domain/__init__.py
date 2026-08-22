"""Domain model — value objects, enums, and the `Explanation` contract (Step 2.1).

Every type here is immutable (`pydantic` frozen models) and validated at
construction. Engines build and return these types; they never hand a
caller a raw dict or a pandas row. See `docs/decisions/0002-domain-model.md`
for the glossary and the rationale behind each type's shape.
"""

from __future__ import annotations

from agentiq.domain.campaign import CampaignBrief, GeographyConstraint
from agentiq.domain.client import ClientSegment
from agentiq.domain.enums import (
    BookingStatus,
    CampaignObjective,
    ClientTier,
    ColdStartRung,
    Confidence,
    DayType,
    IndustryVertical,
    LocationType,
    MarketTier,
    MountPosition,
    NegotiationLeverage,
    RotationType,
    ScreenSize,
    ScreenType,
    TransitDensity,
)
from agentiq.domain.explanation import Contribution, EvidenceRef, Explanation, merge_confidence
from agentiq.domain.inventory import (
    MAX_ROTATION_SLOTS,
    TIME_BLOCK_IDS,
    AudienceProfile,
    Screen,
    SellableUnit,
)
from agentiq.domain.optimizer import Package, PackageLine, ReachEstimate
from agentiq.domain.pricing import DemandSignal, FootfallForecast, PriceQuote
from agentiq.domain.recommendation import Recommendation
from agentiq.domain.rep import RepPerformance, RepSale, SalesRep
from agentiq.domain.scoring import RelevanceScore

__all__ = [
    "MAX_ROTATION_SLOTS",
    "TIME_BLOCK_IDS",
    "AudienceProfile",
    "BookingStatus",
    "CampaignBrief",
    "CampaignObjective",
    "ClientSegment",
    "ClientTier",
    "ColdStartRung",
    "Confidence",
    "Contribution",
    "DayType",
    "DemandSignal",
    "EvidenceRef",
    "Explanation",
    "FootfallForecast",
    "GeographyConstraint",
    "IndustryVertical",
    "LocationType",
    "MarketTier",
    "MountPosition",
    "NegotiationLeverage",
    "Package",
    "PackageLine",
    "PriceQuote",
    "ReachEstimate",
    "Recommendation",
    "RelevanceScore",
    "RepPerformance",
    "RepSale",
    "RotationType",
    "SalesRep",
    "Screen",
    "ScreenSize",
    "ScreenType",
    "SellableUnit",
    "TransitDensity",
    "merge_confidence",
]
