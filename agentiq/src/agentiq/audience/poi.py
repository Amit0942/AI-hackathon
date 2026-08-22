"""POI-pull component of the D1 static exposure model (Step 3.1).

Step 1.6 findings encoded here, not re-derived: `scale` is not an ordinal
footfall proxy (use `est_daily_footfall` for magnitude, `scale` only as a
categorical tag in the explanation); `side_of_road` is an independent
visibility term, not a distance proxy; footfall pull is concentrated in the
POI's own `peak_daypart`, so a POI's contribution is not smeared flat across
the day.
"""

from __future__ import annotations

import pandas as pd

from agentiq.audience.config import PoiConfig
from agentiq.audience.daypart import TIME_BLOCK_DAYPART
from agentiq.domain.inventory import TIME_BLOCK_IDS


def poi_pull_by_block(
    pois: pd.DataFrame,
    *,
    config: PoiConfig,
) -> dict[int, float]:
    """Weighted POI footfall reaching a location, per `time_block_id`.

    *pois* must already be filtered to the query radius (`ContextRepository.pois_near`).
    Each POI contributes its `est_daily_footfall`, scaled by:
    - a side-of-road visibility multiplier (near vs far side of the street),
    - a daypart-alignment weight (full weight in its own `peak_daypart`'s
      block(s), a reduced weight elsewhere) — a POI's pull is not spread flat.
    Any single POI's contribution is capped at `max_single_poi_share` of the
    block total so one flagship anchor cannot dominate a screen's profile
    (Step 1.6 §2's explicit warning).
    """
    if pois.empty:
        return {block: 0.0 for block in TIME_BLOCK_IDS}

    result: dict[int, float] = {}
    for block in TIME_BLOCK_IDS:
        daypart = TIME_BLOCK_DAYPART[block]
        visibility = (
            pois["side_of_road"]
            .astype(str)
            .map(
                {
                    "near_side": config.near_side_visibility_multiplier,
                    "far_side": config.far_side_visibility_multiplier,
                }
            )
            .fillna(config.near_side_visibility_multiplier)
            .astype(float)
        )
        aligned = pois["peak_daypart"].astype(str) == daypart
        daypart_weight = aligned.map({True: 1.0, False: config.off_peak_poi_weight}).astype(float)
        raw = pois["est_daily_footfall"].astype(float) * visibility * daypart_weight

        total = float(raw.sum())
        if total > 0:
            cap_value = config.max_single_poi_share * total
            capped = raw.clip(upper=cap_value)
            total = float(capped.sum())
        result[block] = total
    return result


def dominant_poi_types(pois: pd.DataFrame, top_n: int = 3) -> tuple[str, ...]:
    """The POI types with the most cumulative footfall in range, most-pull first.

    Used by the Step 3.3 semantic-labelling fallback to ground an
    environment label in real evidence rather than the nearest POI alone.
    """
    if pois.empty:
        return ()
    by_type = pois.groupby("poi_type", observed=True)["est_daily_footfall"].sum()
    by_type = by_type.sort_values(ascending=False)
    return tuple(by_type.index[:top_n])
