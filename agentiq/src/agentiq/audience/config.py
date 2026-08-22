"""Loads `config/audience.yaml` into a typed, immutable settings object.

CLAUDE.md: "config over code" — every tunable in the D1 spec (POI radius,
visibility weights, attention-curve growth rate, ...) lives here, read once,
never re-parsed per screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

from agentiq.data.paths import ProjectPaths


@dataclass(frozen=True)
class PoiConfig:
    radius_km_min: float
    radius_km_max: float
    max_single_poi_share: float
    far_side_visibility_multiplier: float
    near_side_visibility_multiplier: float
    off_peak_poi_weight: float


@dataclass(frozen=True)
class MobileConfig:
    interior_capture_rate: float
    exterior_glimpse_discount: float


@dataclass(frozen=True)
class VisibilityConfig:
    position_weight: dict[str, float]
    screen_size_weight: dict[str, float]


@dataclass(frozen=True)
class ReachConfig:
    attention_growth_rate: float
    reach_saturation_scale: float


@dataclass(frozen=True)
class OverlapConfig:
    poi_jaccard_threshold: float
    cross_vehicle_same_corridor: float


@dataclass(frozen=True)
class AudienceConfig:
    poi: PoiConfig
    mobile: MobileConfig
    visibility: VisibilityConfig
    reach: ReachConfig
    overlap: OverlapConfig
    #: Radius actually used for POI queries — the midpoint of the Step 1.6
    #: validated 0.3-0.5km band, not the raw min/max themselves.
    poi_query_radius_km: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "poi_query_radius_km",
            (self.poi.radius_km_min + self.poi.radius_km_max) / 2.0,
        )


def load_audience_config(config_path: str | None = None) -> AudienceConfig:
    path = ProjectPaths().config / "audience.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return AudienceConfig(
        poi=PoiConfig(**raw["poi"]),
        mobile=MobileConfig(**raw["mobile"]),
        visibility=VisibilityConfig(
            position_weight=dict(raw["visibility"]["position_weight"]),
            screen_size_weight=dict(raw["visibility"]["screen_size_weight"]),
        ),
        reach=ReachConfig(**raw["reach"]),
        overlap=OverlapConfig(**raw["overlap"]),
    )
