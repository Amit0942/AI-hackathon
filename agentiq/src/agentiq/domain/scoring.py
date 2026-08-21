"""D2 output type: `RelevanceScore` (Step 2.1)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agentiq.domain.explanation import Explanation


class RelevanceScore(BaseModel):
    """Why this screen fits this campaign — a ranked, explainable affinity score.

    `score` is always in [0, 1] so it composes uniformly with the Step 7.1
    minimum-relevance-threshold constraint regardless of how many signals
    fed into it.
    """

    model_config = ConfigDict(frozen=True)

    screen_id: str
    brief_id: str
    score: float = Field(ge=0.0, le=1.0)
    explanation: Explanation

    def meets_threshold(self, threshold: float) -> bool:
        return self.score >= threshold
