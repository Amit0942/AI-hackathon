"""D4 — Impressions Optimizer (Phase 7).

This pass builds Steps 7.1 (candidate generation + eligibility filter) and
7.2 (de-duplicated reach maximization under a budget) — see
`docs/decisions/0004-d4-optimizer-scope.md` for why 7.3/7.4 are deferred and
why `relevance_score` is an optional input pending D2. Public entrypoint:
`OptimizerEngine.allocate()`, which takes a `CampaignBrief` and returns a
priced, explained `Package`.

`optimizer/candidates.py` and `optimizer/greedy.py` are pure and
repository-free by design — only this module touches
`InMemoryRepositories`, `AudienceProfileEngine`, and `PricingEngine`
directly, mirroring how `pricing/__init__.py` is the only D3 file that
touches repositories while `pricing/bands.py`/`demand.py`/`base_rate.py`
stay pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import uuid4

import yaml

from agentiq.audience import AudienceProfileEngine
from agentiq.data.paths import ProjectPaths
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.campaign import CampaignBrief
from agentiq.domain.enums import Confidence
from agentiq.domain.explanation import Contribution, Explanation, merge_confidence
from agentiq.domain.inventory import Screen
from agentiq.domain.optimizer import Package, PackageLine
from agentiq.domain.scoring import RelevanceScore
from agentiq.optimizer.candidates import (
    RELEVANCE_DEFAULTED_FALLBACK,
    Candidate,
    Rejection,
    filter_eligible,
    make_candidate,
)
from agentiq.optimizer.greedy import SelectionResult, cost_effective_greedy
from agentiq.pricing import PricingEngine

__all__ = [
    "OptimizerConfig",
    "OptimizerEngine",
    "load_optimizer_config",
]


@dataclass(frozen=True)
class OptimizerConfig:
    max_candidates_considered: int
    neutral_relevance_score: float
    default_day_type: str


def load_optimizer_config(config_path: str | None = None) -> OptimizerConfig:
    """Read `config/optimizer.yaml` — never hardcode these in engine code
    (CLAUDE.md: "config over code")."""
    path = ProjectPaths().config / "optimizer.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return OptimizerConfig(
        max_candidates_considered=int(raw["selection"]["max_candidates_considered"]),
        neutral_relevance_score=float(raw["relevance"]["neutral_relevance_score"]),
        default_day_type=str(raw["allocation"]["default_day_type"]),
    )


class OptimizerEngine:
    """D4 entrypoint — generates eligible candidates for a brief, prices
    them via D3, and selects a budget-constrained, de-duplicated-reach
    package via D4's cost-effective-greedy objective (Step 7.2).
    """

    def __init__(
        self,
        repos: InMemoryRepositories,
        audience_engine: AudienceProfileEngine,
        pricing_engine: PricingEngine,
        *,
        config: OptimizerConfig | None = None,
    ) -> None:
        self.repos = repos
        self.audience_engine = audience_engine
        self.pricing_engine = pricing_engine
        self.config = config or load_optimizer_config()

    def allocate(
        self,
        brief: CampaignBrief,
        *,
        time_block_id: int,
        on_date: date | None = None,
        slots: int = 1,
        relevance_scores: dict[str, RelevanceScore] | None = None,
        day_type: str | None = None,
        label: str = "max-reach",
        candidate_screens: tuple[Screen, ...] | None = None,
    ) -> Package:
        """Return a priced, budget-constrained, de-duplicated-reach `Package`
        for one time block (ADR-0004 decision 4).

        `on_date` defaults to the brief's `start_date` (or today, if the
        brief did not state one — Phase 4's clarification loop is the real
        fix for a missing start date; this default only keeps the engine
        callable in isolation). `relevance_scores` is optional pending D2
        (ADR-0004 decision 2): any screen with no entry is priced as neutral
        and the substitution is recorded in the returned `Package`.

        `candidate_screens`, if supplied, restricts candidate generation to
        exactly this set instead of `repos.screens.all()` — added for D5
        (ADR-0006), which pre-shortlists via D2's `RelevanceEngine.rank()`
        before optimizing, rather than repricing the whole network per
        brief. `None` preserves this method's original behaviour exactly.
        """
        resolved_day_type = day_type or self.config.default_day_type
        resolved_date = on_date or brief.start_date or date.today()
        relevance_scores = relevance_scores or {}

        candidates, generation_rejections = self._generate_candidates(
            brief, time_block_id, resolved_date, slots, relevance_scores, candidate_screens
        )
        eligible, filter_rejections = filter_eligible(candidates, brief)
        rejections = generation_rejections + filter_rejections

        overlap_graph = self.audience_engine.overlap_graph()
        reach_scale = self.audience_engine.config.reach.reach_saturation_scale

        def impressions_for(candidate: Candidate) -> float:
            return self.audience_engine.impressions_for(
                candidate.screen_id,
                candidate.time_block_id,
                candidate.slots,
                day_type=resolved_day_type,
            )

        result = cost_effective_greedy(
            eligible,
            overlap_graph,
            brief.budget,
            reach_saturation_scale=reach_scale,
            impressions_for=impressions_for,
        )

        return self._assemble_package(brief, result, rejections, label)

    def _generate_candidates(
        self,
        brief: CampaignBrief,
        time_block_id: int,
        on_date: date,
        slots: int,
        relevance_scores: dict[str, RelevanceScore],
        candidate_screens: tuple[Screen, ...] | None = None,
    ) -> tuple[tuple[Candidate, ...], tuple[Rejection, ...]]:
        end_date = on_date + timedelta(days=brief.duration_days - 1)
        candidates: list[Candidate] = []
        rejections: list[Rejection] = []

        for screen in candidate_screens or self.repos.screens.all():
            if len(candidates) >= self.config.max_candidates_considered:
                break
            geo_reason = self._geography_rejection_reason(screen, brief)
            if geo_reason is not None:
                rejections.append(Rejection(screen_id=screen.screen_id, reason=geo_reason))
                continue

            price_quote = self.pricing_engine.price(
                screen,
                time_block_id,
                slots,
                on_date,
                industry_vertical=brief.industry_vertical,
            )
            candidates.append(
                make_candidate(
                    screen,
                    time_block_id,
                    slots,
                    on_date,
                    end_date,
                    price_quote,
                    relevance_score=relevance_scores.get(screen.screen_id),
                    neutral_relevance_score=self.config.neutral_relevance_score,
                )
            )

        return tuple(candidates), tuple(rejections)

    def _geography_rejection_reason(self, screen: Screen, brief: CampaignBrief) -> str | None:
        """Step 7.1's cheap, exact pre-filter — applied before any pricing
        call, so an excluded screen never pays for a `PricingEngine.price()`
        call it cannot use. Only the exclusion-typed constraints are
        evaluated here; positive (must-match) geography constraints are a
        D2/relevance concern (Step 5.1), not an eligibility gate."""
        for constraint in brief.geography_constraints:
            if not constraint.is_exclusion:
                continue
            if constraint.city_id and screen.city_id != constraint.city_id:
                continue  # this exclusion doesn't apply outside its stated city
            if constraint.zone_name is not None:
                zone = (
                    self.repos.geography.zone_for_location(screen.location_id)
                    if screen.is_static
                    else None
                )
                if zone is not None and zone.get("zone_name") == constraint.zone_name:
                    return f"excluded: zone={constraint.zone_name}, brief excludes this zone"
        return None

    def _assemble_package(
        self,
        brief: CampaignBrief,
        result: SelectionResult,
        rejections: tuple[Rejection, ...],
        label: str,
    ) -> Package:
        if not result.selected:
            # A real outcome (e.g. budget below every screen's floor price),
            # not an error this engine should swallow into a fake Package —
            # `Package.lines` requires at least one entry (Phase 2 domain
            # invariant), so surfacing this as an adaptive-replanning signal
            # (Step 8.2) is the honest behaviour, not a workaround.
            raise ValueError(
                f"No eligible, affordable candidate exists for brief {brief.brief_id!r} — "
                f"{len(rejections)} candidate(s) rejected before selection. Budget, "
                "eligibility constraints, or availability must be relaxed (Step 8.2)."
            )

        lines = tuple(
            PackageLine(
                screen_id=candidate.screen_id,
                time_block_id=candidate.time_block_id,
                slots=candidate.slots,
                start_date=candidate.start_date,
                end_date=candidate.end_date,
                price_quote=candidate.price_quote,
                relevance_score=candidate.relevance_score,
            )
            for candidate in result.selected
        )

        defaulted_screens = tuple(c.screen_id for c in result.selected if c.relevance_is_defaulted)
        fallbacks_used = (RELEVANCE_DEFAULTED_FALLBACK,) if defaulted_screens else ()

        explanation = self._build_explanation(brief, result, fallbacks_used)

        return Package(
            package_id=f"PKG-{uuid4().hex[:12]}",
            brief_id=brief.brief_id,
            label=label,
            lines=lines,
            reach=result.reach,
            total_budget_used=result.total_cost,
            bundle_discount_pct=0.0,  # Step 7.3, deferred — ADR-0004 decision 1
            optimizer_strategy=result.strategy,
            optimizer_guarantee=result.guarantee,
            explanation=explanation,
        )

    @staticmethod
    def _build_explanation(
        brief: CampaignBrief,
        result: SelectionResult,
        fallbacks_used: tuple[str, ...],
    ) -> Explanation:
        budget_utilisation = result.total_cost / brief.budget if brief.budget > 0 else 0.0
        contributions = (
            Contribution(
                signal="unique_reach_delivered",
                direction="positive" if result.reach.unique_reach > 0 else "neutral",
                weight=0.6,
                magnitude=result.reach.unique_reach,
                detail=(
                    f"{len(result.selected)} screen-slot line(s) selected via "
                    f"'{result.strategy}'."
                ),
            ),
            Contribution(
                signal="budget_utilisation",
                direction="positive" if budget_utilisation > 0 else "neutral",
                weight=0.4,
                magnitude=budget_utilisation,
                detail=f"${result.total_cost:,.2f} of ${brief.budget:,.2f} budget used.",
            ),
        )
        line_confidences = [c.price_quote.confidence for c in result.selected]
        confidence = merge_confidence(*line_confidences)
        confidence_reason = (
            f"Merged (weakest-link) confidence across {len(line_confidences)} priced line(s)."
        )
        if fallbacks_used:
            confidence = Confidence.LOW
            confidence_reason += (
                " Degraded to low: relevance score(s) defaulted to neutral pending D2 "
                "(no Campaign<->Screen Relevance Scorer exists yet)."
            )

        return Explanation(
            headline=(
                f"{result.reach.unique_reach:,.0f} unique reach for "
                f"${result.total_cost:,.2f} via {result.strategy}, guarantee: {result.guarantee}"
            ),
            contributions=contributions,
            confidence=confidence,
            confidence_reason=confidence_reason,
            fallbacks_used=fallbacks_used,
        )
