"""D2 — Campaign<->Screen Relevance Scorer (Phase 5).

Public entrypoint: `RelevanceEngine`. `.rank(brief)` runs the full pipeline —
Step 5.1's eligibility filter, Step 5.2's weighted multi-signal score, and
Step 5.3's bounded rerank — and returns ranked `RelevanceScore`s, each
carrying a full `Explanation` (Step 5.4). Built against D1's
`AudienceProfileEngine` (a real dependency now that D1 exists) and the
repository protocols only, never a raw CSV read.
"""

from __future__ import annotations

import random

from agentiq.audience import AudienceProfileEngine
from agentiq.data.repositories import InMemoryRepositories
from agentiq.domain.campaign import CampaignBrief
from agentiq.domain.enums import Confidence
from agentiq.domain.explanation import Contribution, Direction, Explanation
from agentiq.domain.inventory import AudienceProfile, Screen
from agentiq.domain.scoring import RelevanceScore
from agentiq.relevance.config import (
    ScoringConfig,
    SignalWeights,
    load_industry_environment_affinity,
    load_scoring_config,
)
from agentiq.relevance.eligibility import EligibilityResult, eligible_screens
from agentiq.relevance.rerank import RankedCandidate, bounded_rerank
from agentiq.relevance.signals import (
    audience_affinity,
    build_signal_precompute,
    daypart_alignment,
    environment_poi_fit,
    historical_performance_prior,
    objective_fit,
)

__all__ = [
    "EligibilityResult",
    "RelevanceEngine",
    "ScoringConfig",
    "eligible_screens",
    "load_scoring_config",
]

#: Screens sampled to estimate the network-wide exposure p95 reference
#: (`objective_fit`'s awareness/reach normalisation) — a full `build_all()`
#: over all 11,163 screens costs ~90s just for a single percentile; a
#: 1,000-screen sample estimates the same p95 in seconds with negligible
#: error, and per-screen profiles are still computed exactly (and cached)
#: whenever `.score()` actually needs one.
_EXPOSURE_REFERENCE_SAMPLE_SIZE = 1_000


def _direction_for_magnitude(magnitude: float) -> Direction:
    """`weight * value` with `value` in `[0, 1]` is never negative, so the only
    two reachable directions are positive (nonzero contribution) or neutral
    (exactly zero) — matching `Contribution`'s validator exactly, which
    requires `magnitude == 0` whenever `direction == 'neutral'`."""
    return "positive" if magnitude > 0 else "neutral"


class RelevanceEngine:
    """D2 entrypoint — one instance per `InMemoryRepositories`, reused across briefs.

    All per-screen lookups (age-band demographics, historical booking counts,
    an exposure reference for normalisation) are precomputed once at
    construction; `.score()`/`.rank()` are the cheap online path.
    """

    def __init__(
        self,
        repos: InMemoryRepositories,
        *,
        audience_engine: AudienceProfileEngine | None = None,
        config: ScoringConfig | None = None,
    ) -> None:
        self.repos = repos
        self.audience_engine = audience_engine or AudienceProfileEngine(repos)
        self.config = config or load_scoring_config()
        self.industry_environment_affinity = load_industry_environment_affinity()

        self._screens = repos.screens.all()
        sample_size = min(_EXPOSURE_REFERENCE_SAMPLE_SIZE, len(self._screens))
        exposure_sample = random.Random(0).sample(self._screens, sample_size)
        exposure_by_screen = {
            screen.screen_id: self.audience_engine.profile(screen).est_daily_exposure
            for screen in exposure_sample
        }
        self._precompute = build_signal_precompute(
            zone_demographics=repos.lake["zone_demographics"],
            locations=repos.lake["locations"],
            settled_bookings=repos.bookings.settled(),
            exposure_by_screen=exposure_by_screen,
        )

    def eligible_screens(
        self, brief: CampaignBrief, screens: tuple[Screen, ...] | None = None
    ) -> tuple[EligibilityResult, ...]:
        return eligible_screens(brief, screens or self._screens, self.repos)

    def score(self, brief: CampaignBrief, screen: Screen) -> RelevanceScore:
        """Score one screen against *brief* — assumes eligibility was already checked."""
        profile = self.audience_engine.profile(screen)
        weights = self.config.weights_for(brief.objective)

        age_bands = self._age_bands_for(screen)
        exposure_norm = min(
            profile.est_daily_exposure / self._precompute.exposure_reference_p95, 1.0
        )

        signal_values = {
            "audience_affinity": audience_affinity(brief, age_bands),
            "daypart_alignment": daypart_alignment(brief, profile),
            "environment_poi_fit": environment_poi_fit(brief, profile),
            "objective_fit": objective_fit(
                brief,
                screen,
                profile,
                industry_environment_affinity=self.industry_environment_affinity,
                normalised_exposure=exposure_norm,
            ),
            "historical_performance_prior": historical_performance_prior(
                screen.screen_id,
                brief.industry_vertical,
                self._precompute.settled_by_screen_and_vertical,
                min_bookings_for_full_weight=self.config.historical_prior.min_bookings_for_full_weight,
            ),
        }
        score = sum(getattr(weights, name) * value for name, value in signal_values.items())
        score = max(0.0, min(score, 1.0))

        explanation = self._explanation(brief, screen, profile, weights, signal_values, score)
        return RelevanceScore(
            screen_id=screen.screen_id,
            brief_id=brief.brief_id,
            score=score,
            explanation=explanation,
        )

    def rank(
        self,
        brief: CampaignBrief,
        screens: tuple[Screen, ...] | None = None,
        *,
        top_n: int | None = None,
        require_environment_match: bool = False,
    ) -> tuple[RelevanceScore, ...]:
        """Full Phase 5 pipeline: eligibility filter -> score -> bounded rerank.

        `require_environment_match`, if `True` and `brief.requested_environment_types`
        is non-empty, additionally drops any eligible screen whose D1
        `AudienceProfile.environment_labels` shares nothing with the brief's
        requested types — added for D5 (ADR-0006), which needs a
        deterministic guarantee that a recommended screen actually carries a
        requested environment label, stronger than the Step 5.2 weighted
        signal alone provides. Falls back to no filtering (recording nothing
        dropped) if it would eliminate every eligible screen — e.g. a brief
        requesting only `airport_transit_corridor`, which no POI type in
        this dataset grounds (per D1's own finding) would otherwise return
        zero candidates, which is worse than an unfiltered, ranked list.
        Default `False` preserves this method's original behaviour exactly.
        """
        candidates = screens or self._screens
        eligibility = self.eligible_screens(brief, candidates)
        eligible_ids = {r.screen_id for r in eligibility if r.eligible}

        if require_environment_match and brief.requested_environment_types:
            requested = set(brief.requested_environment_types)
            matching_ids = {
                sid
                for sid in eligible_ids
                if self._environment_overlap_count(sid, requested) > 0
            }
            if matching_ids:
                eligible_ids = matching_ids

        by_id = {s.screen_id: s for s in candidates}

        scores = [self.score(brief, by_id[sid]) for sid in eligible_ids]
        scores.sort(key=lambda rs: rs.score, reverse=True)

        requested = set(brief.requested_environment_types)
        ranked_candidates = tuple(
            RankedCandidate(
                screen_id=rs.screen_id,
                score=rs.score,
                tiebreak=self._environment_overlap_count(rs.screen_id, requested),
            )
            for rs in scores
        )
        if self.config.semantic_rerank.enabled and ranked_candidates:
            order = bounded_rerank(
                ranked_candidates,
                max_band_positions=self.config.semantic_rerank.max_band_positions,
                tie_epsilon=self.config.semantic_rerank.tie_epsilon,
            )
            by_screen_id = {rs.screen_id: rs for rs in scores}
            scores = [by_screen_id[sid] for sid in order]

        return tuple(scores[:top_n]) if top_n is not None else tuple(scores)

    def _environment_overlap_count(self, screen_id: str, requested: set[str]) -> int:
        if not requested:
            return 0
        profile = self.audience_engine.get(screen_id)
        if profile is None:
            return 0
        return len(requested & set(profile.environment_labels))

    def _age_bands_for(self, screen: Screen) -> dict[str, float] | None:
        if screen.is_static and screen.location_id is not None:
            zone = self.repos.geography.zone_for_location(screen.location_id)
            if zone is not None:
                return self._precompute.zone_age_bands.get(zone["zone_id"])
        return self._precompute.city_age_bands.get(screen.city_id)

    def _explanation(
        self,
        brief: CampaignBrief,
        screen: Screen,
        profile: AudienceProfile,
        weights: SignalWeights,
        signal_values: dict[str, float],
        score: float,
    ) -> Explanation:
        contributions = tuple(
            Contribution(
                signal=name,
                direction=_direction_for_magnitude(getattr(weights, name) * value),
                weight=getattr(weights, name),
                magnitude=round(getattr(weights, name) * value, 6),
                detail=_signal_detail(name, value, brief, profile),
            )
            for name, value in signal_values.items()
        )
        has_history = signal_values["historical_performance_prior"] > 0
        return Explanation(
            headline=(
                f"{screen.screen_id} scores {score:.2f} for brief {brief.brief_id} "
                f"({brief.objective.value})."
            ),
            contributions=contributions,
            confidence=Confidence.MEDIUM if has_history else Confidence.LOW,
            confidence_reason=(
                "Blends five measured signals; medium because this screen has some "
                "booking history in the brief's industry vertical."
                if has_history
                else "Blends five measured signals; low because this screen has no "
                "settled-booking history in the brief's industry vertical yet — the "
                "historical_performance_prior signal is a deliberately small factor "
                "so this never buries an otherwise well-matched cold-start screen."
            ),
            fallbacks_used=() if has_history else ("no_historical_performance_data",),
        )


def _signal_detail(name: str, value: float, brief: CampaignBrief, profile: AudienceProfile) -> str:
    if name == "audience_affinity":
        return f"{value:.0%} of the local population falls in the requested age range."
    if name == "daypart_alignment":
        return f"{value:.0%} of this screen's exposure falls in the brief's requested time blocks."
    if name == "environment_poi_fit":
        return (
            f"{value:.0%} of requested environment types match this screen's "
            f"labels {profile.environment_labels}."
        )
    if name == "objective_fit":
        return f"{value:.2f} fit for a {brief.objective.value} objective."
    return f"{value:.2f} normalised settled-booking history in {brief.industry_vertical.value}."
