"""Step 7.1 — candidate generation and the eligibility filter.

A `Candidate` is a fully-priced, fully-scored decision the allocator may or
may not include in the final `Package`: one screen, one time block, a slot
count, and a date range, together with the `PriceQuote` and `RelevanceScore`
that make it comparable to every other candidate. Building this as its own
type — rather than passing `Screen`/`PriceQuote`/`RelevanceScore` around
separately — is what lets `optimizer/greedy.py` be pure and repository-free
(ADR-0004 §Context): everything the selection algorithm needs is on one
object, with zero dependency on `InMemoryRepositories`.

Eligibility filtering runs *before* any reach computation (`solution_plan.md`
Step 5.1's own reasoning, reused here for D4): it is cheap and exact, and it
shrinks the candidate set before the expensive part runs. Every rejected
candidate carries its own reason, so a caller can report "excluded: X"
exactly the way Step 5.1 does for the relevance scorer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from agentiq.domain.campaign import CampaignBrief
from agentiq.domain.inventory import Screen
from agentiq.domain.pricing import PriceQuote
from agentiq.domain.scoring import RelevanceScore

#: Fallback recorded on a `Package.explanation.fallbacks_used` whenever a
#: candidate had no real `RelevanceScore` supplied (ADR-0004 decision 2).
RELEVANCE_DEFAULTED_FALLBACK = "relevance_score_defaulted_neutral_pending_D2"


@dataclass(frozen=True)
class Candidate:
    """One screen x time-block x slot-count x date-range decision, fully priced and scored."""

    screen: Screen
    time_block_id: int
    slots: int
    start_date: date
    end_date: date
    price_quote: PriceQuote
    relevance_score: float
    relevance_is_defaulted: bool

    @property
    def screen_id(self) -> str:
        return self.screen.screen_id

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def cost(self) -> float:
        """Total budget consumed if this candidate is selected — matches
        `PackageLine.line_value` exactly, computed once here so the
        selection algorithm and the assembled `Package` never disagree."""
        return self.price_quote.recommended * self.slots * self.days


@dataclass(frozen=True)
class Rejection:
    """One candidate excluded before selection, with a stated reason —
    the D4 analogue of Step 5.1's "excluded: bus-rear, brief excludes
    bus-rear" trust surface."""

    screen_id: str
    reason: str


def make_candidate(
    screen: Screen,
    time_block_id: int,
    slots: int,
    start_date: date,
    end_date: date,
    price_quote: PriceQuote,
    *,
    relevance_score: RelevanceScore | None,
    neutral_relevance_score: float,
) -> Candidate:
    """Assemble one `Candidate`, defaulting relevance when D2 has not supplied one.

    `relevance_score` is `None` whenever no `RelevanceScore` exists for this
    screen/brief yet (D2 unbuilt, or the screen fell outside D2's shortlist).
    Defaulting to `neutral_relevance_score` rather than raising or silently
    treating the screen as maximally relevant is the ADR-0004 decision 2
    policy — the default is recorded on the `Candidate`, not hidden.
    """
    if relevance_score is not None:
        return Candidate(
            screen=screen,
            time_block_id=time_block_id,
            slots=slots,
            start_date=start_date,
            end_date=end_date,
            price_quote=price_quote,
            relevance_score=relevance_score.score,
            relevance_is_defaulted=False,
        )
    return Candidate(
        screen=screen,
        time_block_id=time_block_id,
        slots=slots,
        start_date=start_date,
        end_date=end_date,
        price_quote=price_quote,
        relevance_score=neutral_relevance_score,
        relevance_is_defaulted=True,
    )


def filter_eligible(
    candidates: tuple[Candidate, ...],
    brief: CampaignBrief,
) -> tuple[tuple[Candidate, ...], tuple[Rejection, ...]]:
    """Step 7.1's hard-constraint filter: screen-type exclusions and the
    minimum relevance threshold. Geography exclusions are applied by the
    caller during candidate *generation* (they need repository lookups this
    module deliberately does not depend on) — this function only re-applies
    the two constraints expressible on a `Candidate` alone, so a candidate
    list built by any caller is still safe to filter here.
    """
    eligible: list[Candidate] = []
    rejections: list[Rejection] = []
    excluded_types = set(brief.screen_type_exclusions)

    for candidate in candidates:
        screen_type = candidate.screen.screen_type.value
        if screen_type in excluded_types:
            rejections.append(
                Rejection(
                    screen_id=candidate.screen_id,
                    reason=f"excluded: screen_type={screen_type}, brief excludes {screen_type}",
                )
            )
            continue
        if candidate.relevance_score < brief.minimum_relevance_threshold:
            rejections.append(
                Rejection(
                    screen_id=candidate.screen_id,
                    reason=(
                        f"excluded: relevance_score={candidate.relevance_score:.3f} below "
                        f"brief's minimum_relevance_threshold="
                        f"{brief.minimum_relevance_threshold:.3f}"
                    ),
                )
            )
            continue
        eligible.append(candidate)

    return tuple(eligible), tuple(rejections)


__all__ = [
    "RELEVANCE_DEFAULTED_FALLBACK",
    "Candidate",
    "Rejection",
    "filter_eligible",
    "make_candidate",
]
