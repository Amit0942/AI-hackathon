"""Step 5.3 — Semantic re-ranking, deterministic fallback.

The plan asks for an LLM agent that "reviews the top-N shortlist with full
evidence and may re-rank within a bounded band, giving a reason... cannot
invent scores or promote an ineligible screen." No LLM endpoint is
configured in this environment, so this is the deterministic fallback
CLAUDE.md requires every agent step to have (the same treatment as
`audience/semantic.py`): it only ever reorders two screens whose Step 5.2
scores are already within `tie_epsilon` of each other, breaking the tie on
a real secondary signal (environment-label overlap count) rather than
reshuffling freely. Swapping in a real LLM call later means replacing
`bounded_rerank`'s internals; the bound (never move outside the tie band,
never touch an ineligible screen — those are filtered out before this runs)
stays identical.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankedCandidate:
    screen_id: str
    score: float
    #: Secondary, evidence-based tiebreaker — higher wins a tie. Currently the
    #: count of the brief's requested environment types this screen carries.
    tiebreak: int


def bounded_rerank(
    candidates: tuple[RankedCandidate, ...],
    *,
    max_band_positions: int,
    tie_epsilon: float,
) -> tuple[str, ...]:
    """Return screen IDs in final rank order.

    *candidates* must already be sorted by `score` descending. Within any
    window of `max_band_positions` consecutive candidates, entries whose
    scores are mutually within `tie_epsilon` are re-sorted by `tiebreak`
    (descending); entries further apart than `tie_epsilon` never move
    relative to each other, so no reorder crosses a real score gap.
    """
    ordered = list(candidates)
    i = 0
    n = len(ordered)
    while i < n:
        j = i
        while (
            j + 1 < n
            and j + 1 - i < max_band_positions
            and ordered[i].score - ordered[j + 1].score <= tie_epsilon
        ):
            j += 1
        if j > i:
            ordered[i : j + 1] = sorted(
                ordered[i : j + 1], key=lambda c: (-c.tiebreak, -c.score)
            )
        i = j + 1
    return tuple(c.screen_id for c in ordered)


__all__ = ["RankedCandidate", "bounded_rerank"]
