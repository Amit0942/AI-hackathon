"""Loads `config/rep_scoring.yaml` into a typed, immutable settings object.

CLAUDE.md: "config over code" — the blend weights are a stated design
choice (no historical rep-score ground truth exists to calibrate against,
see the YAML's own header), but they still live in config, not in
`scoring.py`, so changing the trade-off never means touching engine code.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from agentiq.data.paths import ProjectPaths


@dataclass(frozen=True)
class BlendWeights:
    margin_weight: float
    attainment_weight: float


@dataclass(frozen=True)
class RepScoringConfig:
    attainment_cap: float
    blend: BlendWeights


def load_rep_scoring_config(config_path: str | None = None) -> RepScoringConfig:
    path = ProjectPaths().config / "rep_scoring.yaml" if config_path is None else config_path
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return RepScoringConfig(
        attainment_cap=float(raw["target_attainment"]["attainment_cap"]),
        blend=BlendWeights(
            margin_weight=float(raw["blend"]["margin_weight"]),
            attainment_weight=float(raw["blend"]["attainment_weight"]),
        ),
    )
