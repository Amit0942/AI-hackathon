"""Step 7.2 — the de-duplicated reach objective, maximized under a budget.

Pure, repository-free selection algorithms over `Candidate`s (see
`optimizer/candidates.py`) and D1's `OverlapGraph`. Every function here
takes plain data in and returns plain data out — no `InMemoryRepositories`,
no file I/O — so it is unit-testable against hand-built fixtures exactly
like `audience/reach.py`'s own property tests (ADR-0004 §6).

Reach is computed with `audience.reach.reach_estimate_for_group`, reused
verbatim per Step 3.5's own docstring ("reusable by D4's optimizer without
modification") — this module never re-derives the impressions/overlap math.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agentiq.audience.overlap import OverlapGraph
from agentiq.audience.reach import reach_estimate_for_group
from agentiq.domain.optimizer import ReachEstimate
from agentiq.optimizer.candidates import Candidate

#: Registered so `Package.optimizer_guarantee` can cite exactly what was proven
#: (ADR-0004 decision 3), never a vaguer claim than the algorithm supports.
COST_EFFECTIVE_GREEDY_GUARANTEE = (
    "(1 - 1/e) / 2 ~= 0.316 of optimal (monotone submodular maximization under "
    "one knapsack/budget constraint) — proven by the greedy-vs-best-singleton "
    "comparison, not by greedy alone."
)


@dataclass(frozen=True)
class SelectionResult:
    """The chosen subset of candidates, the reach they deliver, and how they were chosen."""

    selected: tuple[Candidate, ...]
    reach: ReachEstimate
    total_cost: float
    strategy: str
    guarantee: str

    @property
    def screen_ids(self) -> tuple[str, ...]:
        return tuple(candidate.screen_id for candidate in self.selected)


def _impressions_map(
    candidates: tuple[Candidate, ...],
    impressions_for: Callable[[Candidate], float],
) -> dict[str, float]:
    """One screen's impressions, summed if more than one candidate on that
    screen was selected (e.g. two different date ranges on the same block)."""
    result: dict[str, float] = {}
    for candidate in candidates:
        result[candidate.screen_id] = result.get(candidate.screen_id, 0.0) + impressions_for(
            candidate
        )
    return result


def _reach_of(
    candidates: tuple[Candidate, ...],
    overlap_graph: OverlapGraph,
    reach_saturation_scale: float,
    impressions_for: Callable[[Candidate], float],
) -> ReachEstimate:
    impressions_map = _impressions_map(candidates, impressions_for)
    return reach_estimate_for_group(
        impressions_map, overlap_graph, reach_saturation_scale=reach_saturation_scale
    )


def cost_effective_greedy(
    candidates: tuple[Candidate, ...],
    overlap_graph: OverlapGraph,
    budget: float,
    *,
    reach_saturation_scale: float,
    impressions_for: Callable[[Candidate], float],
) -> SelectionResult:
    """Maximize unique reach under a budget constraint.

    Two components, per ADR-0004 decision 3:

    1. **Greedy by cost-effectiveness.** Repeatedly add the affordable,
       not-yet-selected candidate with the highest marginal reach gain per
       dollar, until no affordable candidate improves reach. This alone has
       no worst-case guarantee under a budget constraint.
    2. **Best-singleton comparison.** Also consider the single best
       affordable candidate on its own. Return whichever of the two has
       higher total reach.

    Together, (1) and (2) give the standard (1-1/e)/2 approximation
    guarantee for monotone submodular maximization subject to one knapsack
    constraint — this is *why* the comparison exists, not an incidental
    extra step.

    Complexity note: this reference implementation recomputes the full
    group reach on every marginal-gain check (O(candidates) steps, each
    scanning O(remaining) candidates, each rebuilding an impressions map
    and its O(selected^2) overlap discount) — correct and adequate at the
    "low thousands of candidates" scale Step 1.4 measured, but a lazy-greedy
    priority-queue variant (re-scoring only the candidate whose bound
    changed) is the named Phase 10 performance fast-follow if profiling
    shows this step dominating latency at scale.
    """
    remaining = list(candidates)
    selected: list[Candidate] = []
    spent = 0.0
    current_reach = 0.0

    while remaining:
        best_candidate: Candidate | None = None
        best_ratio = -1.0
        best_gain = 0.0
        for candidate in remaining:
            if candidate.cost > budget - spent:
                continue
            trial_reach = _reach_of(
                (*selected, candidate), overlap_graph, reach_saturation_scale, impressions_for
            ).unique_reach
            gain = trial_reach - current_reach
            if gain <= 0:
                continue
            ratio = gain / candidate.cost if candidate.cost > 0 else float("inf")
            if ratio > best_ratio:
                best_ratio = ratio
                best_candidate = candidate
                best_gain = gain

        if best_candidate is None:
            break

        selected.append(best_candidate)
        spent += best_candidate.cost
        current_reach += best_gain
        remaining.remove(best_candidate)

    greedy_selection = tuple(selected)
    greedy_reach = _reach_of(
        greedy_selection, overlap_graph, reach_saturation_scale, impressions_for
    )

    affordable_singletons = [c for c in candidates if c.cost <= budget]
    if affordable_singletons:
        best_single = max(
            affordable_singletons,
            key=lambda c: _reach_of(
                (c,), overlap_graph, reach_saturation_scale, impressions_for
            ).unique_reach,
        )
        single_reach = _reach_of(
            (best_single,), overlap_graph, reach_saturation_scale, impressions_for
        )
    else:
        best_single, single_reach = None, None

    if single_reach is not None and single_reach.unique_reach > greedy_reach.unique_reach:
        return SelectionResult(
            selected=(best_single,),
            reach=single_reach,
            total_cost=best_single.cost,
            strategy="cost_effective_greedy (best-singleton dominated)",
            guarantee=COST_EFFECTIVE_GREEDY_GUARANTEE,
        )

    return SelectionResult(
        selected=greedy_selection,
        reach=greedy_reach,
        total_cost=spent,
        strategy="cost_effective_greedy",
        guarantee=COST_EFFECTIVE_GREEDY_GUARANTEE,
    )


def _take_while_affordable(
    ordered: list[Candidate],
    budget: float,
    overlap_graph: OverlapGraph,
    reach_saturation_scale: float,
    impressions_for: Callable[[Candidate], float],
    strategy_name: str,
) -> SelectionResult:
    selected: list[Candidate] = []
    spent = 0.0
    for candidate in ordered:
        if spent + candidate.cost > budget:
            continue
        selected.append(candidate)
        spent += candidate.cost

    reach = _reach_of(tuple(selected), overlap_graph, reach_saturation_scale, impressions_for)
    return SelectionResult(
        selected=tuple(selected),
        reach=reach,
        total_cost=spent,
        strategy=strategy_name,
        guarantee="none — naive baseline, kept only for the Step 7.2 comparison",
    )


def cheapest_first(
    candidates: tuple[Candidate, ...],
    overlap_graph: OverlapGraph,
    budget: float,
    *,
    reach_saturation_scale: float,
    impressions_for: Callable[[Candidate], float],
) -> SelectionResult:
    """Baseline: fill the budget with the cheapest candidates first, ignoring
    reach or overlap entirely. The naive status-quo behaviour Step 7.2's
    exit criterion names explicitly ("rank and fill until budget runs out")."""
    ordered = sorted(candidates, key=lambda c: c.cost)
    return _take_while_affordable(
        ordered, budget, overlap_graph, reach_saturation_scale, impressions_for, "cheapest_first"
    )


def greedy_by_relevance(
    candidates: tuple[Candidate, ...],
    overlap_graph: OverlapGraph,
    budget: float,
    *,
    reach_saturation_scale: float,
    impressions_for: Callable[[Candidate], float],
) -> SelectionResult:
    """Baseline: fill the budget by relevance score alone (ties broken by
    cheapest first), with no reach de-duplication reasoning at all."""
    ordered = sorted(candidates, key=lambda c: (-c.relevance_score, c.cost))
    return _take_while_affordable(
        ordered,
        budget,
        overlap_graph,
        reach_saturation_scale,
        impressions_for,
        "greedy_by_relevance",
    )


__all__ = [
    "COST_EFFECTIVE_GREEDY_GUARANTEE",
    "SelectionResult",
    "cheapest_first",
    "cost_effective_greedy",
    "greedy_by_relevance",
]
