"""Sales-rep performance scoring — a simulated layer over D3's real `PriceQuote`
guardrails (see `domain/rep.py` and `config/rep_scoring.yaml` for why this is
explicitly not a measured deliverable like D1-D6).

Public entrypoint: `RepScoringEngine.score(rep, sales)`. Pure, repository-free
computation — a rep and their sales are supplied directly, not fetched from a
data lake (there is nothing to fetch; no rep table exists).
"""

from __future__ import annotations

from agentiq.domain.enums import Confidence
from agentiq.domain.explanation import Contribution, EvidenceRef, Explanation
from agentiq.domain.rep import RepPerformance, RepSale, SalesRep
from agentiq.reps.config import RepScoringConfig, load_rep_scoring_config
from agentiq.reps.scoring import (
    blend_rep_score,
    is_price_anomaly,
    margin_score,
    target_attainment_ratio,
)

__all__ = ["RepScoringConfig", "RepScoringEngine", "load_rep_scoring_config"]


class RepScoringEngine:
    """Scores one rep's performance over their target period from their sales."""

    def __init__(self, config: RepScoringConfig | None = None) -> None:
        self.config = config or load_rep_scoring_config()

    def score(self, rep: SalesRep, sales: tuple[RepSale, ...]) -> RepPerformance:
        relevant = tuple(
            s
            for s in sales
            if s.rep_id == rep.rep_id and rep.period_start <= s.sold_date <= rep.period_end
        )

        total_revenue = sum(s.deal_value for s in relevant)
        margins = [margin_score(s) for s in relevant]
        # No sales yet this period is not the same as "sold everything at
        # the floor" — average_margin_score defaults to neutral 1.0 (no
        # discounting has happened) so a rep who simply hasn't closed
        # anything yet isn't scored as if they gave away margin.
        average_margin = sum(margins) / len(margins) if margins else 1.0
        attainment_ratio = target_attainment_ratio(total_revenue, rep.target_revenue)

        rep_score = blend_rep_score(
            average_margin,
            attainment_ratio,
            attainment_cap=self.config.attainment_cap,
            margin_weight=self.config.blend.margin_weight,
            attainment_weight=self.config.blend.attainment_weight,
        )

        anomalies = tuple(s for s in relevant if is_price_anomaly(s))
        explanation = self._explanation(
            rep, relevant, total_revenue, average_margin, attainment_ratio, rep_score, anomalies
        )

        return RepPerformance(
            rep_id=rep.rep_id,
            period_start=rep.period_start,
            period_end=rep.period_end,
            sale_count=len(relevant),
            total_revenue=total_revenue,
            target_revenue=rep.target_revenue,
            target_attainment_pct=attainment_ratio,
            average_margin_score=average_margin,
            rep_score=rep_score,
            explanation=explanation,
        )

    def _explanation(
        self,
        rep: SalesRep,
        sales: tuple[RepSale, ...],
        total_revenue: float,
        average_margin: float,
        attainment_ratio: float,
        rep_score: float,
        anomalies: tuple[RepSale, ...],
    ) -> Explanation:
        capped_attainment = (
            min(attainment_ratio, self.config.attainment_cap) / self.config.attainment_cap
        )
        contributions = (
            Contribution(
                signal="average_margin_score",
                direction="positive" if average_margin > 0 else "neutral",
                weight=self.config.blend.margin_weight,
                magnitude=round(self.config.blend.margin_weight * average_margin, 6),
                detail=(
                    f"Average of {len(sales)} sale(s)' (sold_price - floor)/(target - floor); "
                    f"1.0 = always sold at/above target, 0.0 = always sold at floor."
                ),
            ),
            Contribution(
                signal="target_attainment",
                direction="positive" if capped_attainment > 0 else "neutral",
                weight=self.config.blend.attainment_weight,
                magnitude=round(self.config.blend.attainment_weight * capped_attainment, 6),
                detail=(
                    f"{total_revenue:,.0f} revenue vs. {rep.target_revenue:,.0f} target "
                    f"({attainment_ratio:.0%}, capped at "
                    f"{self.config.attainment_cap:.0%} for scoring)."
                ),
            ),
        )
        fallbacks: list[str] = []
        if not sales:
            fallbacks.append("no_sales_this_period_margin_score_defaulted_neutral")
        if anomalies:
            fallbacks.append(f"{len(anomalies)}_sale(s)_priced_outside_floor_cap_band")

        evidence = tuple(
            EvidenceRef(
                table="(simulated — no sales_rep_id exists in the raw data)",
                row_key={"screen_id": s.screen_id, "sold_date": str(s.sold_date)},
                field="sold_price",
                value=s.sold_price,
                note="Rep's actual sale price vs. this quote's floor/target/cap.",
            )
            for s in anomalies
        )

        return Explanation(
            headline=(
                f"{rep.name} ({rep.rep_id}): {rep_score:.2f} score from {len(sales)} sale(s), "
                f"{attainment_ratio:.0%} of target, {average_margin:.0%} average margin."
            ),
            contributions=contributions,
            evidence=evidence,
            confidence=Confidence.LOW,
            confidence_reason=(
                "No sales_rep_id exists in the raw data — this score is computed from "
                "simulated/supplied sales against D3's real PriceQuote guardrails, not from "
                "a measured historical rep performance record. Low confidence by construction, "
                "not a data-quality finding."
            ),
            fallbacks_used=tuple(fallbacks),
        )
