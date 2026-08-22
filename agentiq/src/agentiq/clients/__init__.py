"""Client segmentation — measured from real booking history and `client_facts`.

Public entrypoint: `ClientSegmentationEngine`. Deliberately a rule-based
classifier, not a clustering model: with 520 clients and a handful of
already-categorical fields, the requested segments (reach-centric,
conversion/"result"-centric, frequency-centric, awareness-centric,
budget-disciplined vs. flexible) already exist almost verbatim in the raw
data (`bookings.campaign_objective`, `client_facts.budget_variance_pct`) —
fitting an unsupervised model on top of ground truth that's already this
close to categorical would add opacity, not accuracy. See `domain/client.py`
for the one requested axis ("ground-level footfall improvement" affinity)
this deliberately does not model, for lack of any data binding.
"""

from __future__ import annotations

import pandas as pd

from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.client import BudgetPosture, ClientSegment
from agentiq.domain.enums import CampaignObjective, ClientTier, Confidence, NegotiationLeverage
from agentiq.domain.explanation import Contribution, EvidenceRef, Explanation

__all__ = ["ClientSegmentationEngine"]


class ClientSegmentationEngine:
    """Segments a client from their settled-booking history + `client_facts`.

    The network-median `budget_variance_pct` (the `budget_posture` cutoff)
    is computed once at construction — offline precompute, per design
    principle 5 — so `.segment()` stays a cheap per-client lookup.
    """

    def __init__(self, repos: InMemoryRepositories) -> None:
        self.repos = repos
        self._client_facts = repos.lake["client_facts"]
        self._settled = repos.bookings.settled()
        self._median_budget_variance = float(self._client_facts["budget_variance_pct"].median())

    def segment(self, client_id: str) -> ClientSegment:
        row = self.repos.clients.get(client_id)
        if row is None:
            raise ValueError(f"Unknown client_id {client_id!r}")

        bookings = self._settled.loc[self._settled["client_id"] == client_id]
        objective_segment: CampaignObjective | None = None
        share = 0.0
        if not bookings.empty:
            counts = bookings["campaign_objective"].astype(str).value_counts()
            objective_segment = CampaignObjective(counts.idxmax())
            share = float(counts.max() / counts.sum())

        variance = float(row["budget_variance_pct"])
        budget_posture: BudgetPosture = (
            "disciplined" if variance <= self._median_budget_variance else "flexible"
        )

        explanation = self._explanation(
            row, bookings, objective_segment, share, budget_posture, variance
        )

        return ClientSegment(
            client_id=client_id,
            company_name=str(row["company_name"]),
            objective_segment=objective_segment,
            objective_segment_share=share,
            budget_posture=budget_posture,
            client_tier=ClientTier(row["client_tier"]),
            negotiation_leverage=NegotiationLeverage(row["negotiation_leverage"]),
            bundle_affinity=str(row["bundle_affinity"]),
            sample_size=len(bookings),
            explanation=explanation,
        )

    def segment_all(self) -> tuple[ClientSegment, ...]:
        return tuple(self.segment(cid) for cid in self._client_facts["client_id"])

    def _explanation(
        self,
        row: dict,
        bookings: pd.DataFrame,
        objective_segment: CampaignObjective | None,
        share: float,
        budget_posture: str,
        variance: float,
    ) -> Explanation:
        contributions = (
            Contribution(
                signal="objective_segment",
                direction="positive" if objective_segment is not None else "neutral",
                weight=0.6,
                magnitude=share if objective_segment is not None else 0.0,
                detail=(
                    f"{share:.0%} of {len(bookings)} settled booking(s) are "
                    f"'{objective_segment.value}'."
                    if objective_segment is not None
                    else "No settled booking history yet — a new account, not a guessed segment."
                ),
            ),
            Contribution(
                signal="budget_posture",
                direction="positive",
                weight=0.4,
                magnitude=0.4,
                detail=(
                    f"budget_variance_pct {variance:.0%} vs. network median "
                    f"{self._median_budget_variance:.0%} -> '{budget_posture}'."
                ),
            ),
        )
        fallbacks = () if objective_segment is not None else ("no_settled_booking_history",)
        segment_label = objective_segment.value if objective_segment else "unclassified"
        headline = (
            f"{row['company_name']}: {segment_label} ({share:.0%}), "
            f"{budget_posture} budget posture."
        )
        return Explanation(
            headline=headline,
            contributions=contributions,
            evidence=(
                EvidenceRef(
                    table="client_facts",
                    row_key={"client_id": str(row["client_id"])},
                    field="budget_variance_pct",
                    value=variance,
                ),
            ),
            confidence=Confidence.HIGH if len(bookings) >= 10 else Confidence.LOW,
            confidence_reason=(
                f"Measured from {len(bookings)} settled booking(s) — "
                + ("a solid sample." if len(bookings) >= 10 else "too few to be confident.")
            ),
            fallbacks_used=fallbacks,
        )
