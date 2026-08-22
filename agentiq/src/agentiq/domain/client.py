"""Client segmentation domain type — measured, not simulated.

Unlike `domain/rep.py`'s sales-rep layer, this one is grounded in real data:
`bookings.client_id` resolves 100% to `client_facts.client_id`, and
`bookings.campaign_objective` has exactly the four values
(awareness/conversion/frequency/reach) that a client's dominant historical
buying pattern maps onto directly — no invented proxy needed for that axis.

One requested segmentation axis has **no data binding and is deliberately
not modelled**: "clients who value ground-level/local footfall
improvements." No column anywhere in the raw data (`client_facts`,
`bookings`, `lost_leads`) measures a client's interest in local-area impact
as distinct from the four `campaign_objective` values — inventing a proxy
for it would be exactly the kind of silent guess this project's convention
warns against. Flagged here as an unresolved capability, not built.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentiq.domain.enums import CampaignObjective, ClientTier, NegotiationLeverage
from agentiq.domain.explanation import Explanation

BudgetPosture = Literal["disciplined", "flexible"]


class ClientSegment(BaseModel):
    """One client's measured segment, over their full settled-booking history.

    `objective_segment` is `None` only for a client with zero settled
    bookings (a genuinely new account) — never guessed at a default.
    """

    model_config = ConfigDict(frozen=True)

    client_id: str
    company_name: str
    objective_segment: CampaignObjective | None = Field(
        description="This client's most-booked campaign_objective, measured from "
        "their settled booking history. None if they have no settled history yet."
    )
    objective_segment_share: float = Field(
        ge=0.0,
        le=1.0,
        description="Share of this client's settled bookings carrying objective_segment "
        "— how dominant the pattern is, not just which objective is most common.",
    )
    budget_posture: BudgetPosture = Field(
        description="'disciplined' if client_facts.budget_variance_pct is at/below the "
        "network median, 'flexible' otherwise — a measured relative comparison, "
        "not an arbitrary absolute threshold."
    )
    client_tier: ClientTier
    negotiation_leverage: NegotiationLeverage
    bundle_affinity: str
    sample_size: int = Field(ge=0, description="Settled bookings behind objective_segment.")
    explanation: Explanation
