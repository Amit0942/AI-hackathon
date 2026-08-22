"""Loads `config/scoring.yaml` (Step 5.2/5.3) into typed, immutable settings.

CLAUDE.md: "config over code" — every relevance weight is objective-dependent
and lives here, read once, never hardcoded in `signals.py`/`rerank.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from agentiq.data.paths import ProjectPaths
from agentiq.domain.enums import CampaignObjective

#: The five Step 5.2 signal names, in the fixed order every weights dict must cover.
SIGNAL_NAMES: tuple[str, ...] = (
    "audience_affinity",
    "daypart_alignment",
    "environment_poi_fit",
    "objective_fit",
    "historical_performance_prior",
)


@dataclass(frozen=True)
class SignalWeights:
    audience_affinity: float
    daypart_alignment: float
    environment_poi_fit: float
    objective_fit: float
    historical_performance_prior: float

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in SIGNAL_NAMES}


@dataclass(frozen=True)
class SemanticRerankConfig:
    enabled: bool
    max_band_positions: int
    tie_epsilon: float


@dataclass(frozen=True)
class HistoricalPriorConfig:
    min_bookings_for_full_weight: int


@dataclass(frozen=True)
class ScoringConfig:
    default_weights: SignalWeights
    weights_by_objective: dict[CampaignObjective, SignalWeights]
    semantic_rerank: SemanticRerankConfig
    historical_prior: HistoricalPriorConfig

    def weights_for(self, objective: CampaignObjective) -> SignalWeights:
        return self.weights_by_objective.get(objective, self.default_weights)


def _parse_weights(raw: dict) -> SignalWeights:
    return SignalWeights(**{name: float(raw[name]) for name in SIGNAL_NAMES})


def load_scoring_config(config_path: str | None = None) -> ScoringConfig:
    path = ProjectPaths().config / "scoring.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    default_weights = _parse_weights(raw["default"])
    weights_by_objective = {
        CampaignObjective(name): _parse_weights(weights)
        for name, weights in raw.get("by_objective", {}).items()
    }
    rerank_raw = raw["semantic_rerank"]
    semantic_rerank = SemanticRerankConfig(
        enabled=bool(rerank_raw["enabled"]),
        max_band_positions=int(rerank_raw["max_band_positions"]),
        tie_epsilon=float(rerank_raw["tie_epsilon"]),
    )
    historical_prior = HistoricalPriorConfig(
        min_bookings_for_full_weight=int(raw["historical_prior"]["min_bookings_for_full_weight"])
    )

    return ScoringConfig(
        default_weights=default_weights,
        weights_by_objective=weights_by_objective,
        semantic_rerank=semantic_rerank,
        historical_prior=historical_prior,
    )


def load_industry_environment_affinity(
    config_path: str | None = None,
) -> dict[str, tuple[str, ...]]:
    """`industry -> preferred environment_types` from `config/taxonomy.yaml` — the
    Step 5.2 `objective_fit` prior, shared with `config/taxonomy.yaml`'s own
    stated purpose (Phase 3.3/Phase 5.2)."""
    path = ProjectPaths().config / "taxonomy.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return {
        industry: tuple(environments)
        for industry, environments in raw["industry_environment_affinity"].items()
    }
