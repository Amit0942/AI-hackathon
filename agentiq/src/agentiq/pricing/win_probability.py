"""Step 6.4 — win probability and the recommended optimal price.

Step 6.4 asks for "the point inside the band that maximises expected value =
price x P(win | price, gap, client, demand)", plus "the trade-off curve so a
rep can see the cost of discounting."

The model is a logistic regression on `lost_leads`, fit on three features
Step 1.5 §6 measured directly:

- `price_gap_pct` — 1.5 §6.2's survival curve. Deals reach
  verbal-agreement-or-later 38-48% of the time up to a 15% gap over the
  client's target, then collapse to 7.7% (15-20%) and 3.5% (>20%).
- `competitor_mentioned` — 1.5 §6.5. Leads naming a competitor died at a
  **3.4%** median gap versus **22.9%** without. Competitive pressure lowers
  the effective ceiling; it is not merely correlated with a larger gap, so it
  enters as its own term rather than being folded into the gap curve.
- `client_tier` — `client_facts.client_tier` (local_business /
  regional_chain / national_chain), the leverage input Step 6.3 names.

ADR-0003 decision 4: logistic regression, not a step function off 1.5 §6.2's
six buckets. `argmax(price x P(win))` needs a smooth curve — a six-step
function has flat regions with no gradient for the search to move along, and
would pin the optimum to a bucket edge as an artifact of bucketing.

**What "win" means here, and why the level is calibrated but the shape is
what matters.** `lost_leads` contains only losses, so a naive "fraction won"
is unavailable from this table alone. The label used is 1.5 §6.1's own
progression measure: a lead that reached `verbal_agreement` or `contract_sent`
came close to converting; one that died at `initial_inquiry` or `quote_sent`
did not. This is a *proxy for deal health*, which 1.5 §6.1 explicitly endorses
("the gap is a real proxy for deal health, not noise"). The absolute
probabilities are therefore calibrated against near-conversion among lost
deals, not against a true base rate; the **shape** — how sharply the curve
falls as the gap widens — is the part the argmax actually consumes, and that
shape is measured. `PriceQuote.win_probability_at_recommended` documents this
reading. This limitation is stated rather than hidden, per the repo's
explainability rule.

Nulls are excluded, never imputed (1.7 §2): the 47.6% of rows with no
`client_target_price_per_slot_per_day` are leads where no counter-offer was
ever made. Imputing one would fabricate a negotiation that never happened.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder

#: Sales stages that count as "close to won" — 1.5 §6.1's progression measure.
NEAR_WIN_STAGES: frozenset[str] = frozenset({"verbal_agreement", "contract_sent"})

#: Client tiers from `client_facts.client_tier`; the fallback when a lead has
#: no `client_id` (44.3% of rows are new prospects, 1.7 §2).
UNKNOWN_TIER = "unknown"

#: Grid resolution for the trade-off curve and the argmax search. 101 points
#: across [floor, cap] is fine enough that the discrete optimum is within
#: ~1% of the continuous one, and cheap enough to stay on the online path.
PRICE_GRID_POINTS = 101


@dataclass(frozen=True)
class FittedWinModel:
    """A fitted win-probability model plus the encoder needed to score a row."""

    encoder: OneHotEncoder
    model: LogisticRegression
    feature_names: tuple[str, ...]
    #: Rows the fit actually used, after excluding null gaps — reported in
    #: the explanation so a reader can judge the evidence base.
    n_training_rows: int

    def _design(self, price_gap_pct: np.ndarray, competitor: bool, tier: str) -> np.ndarray:
        n = len(price_gap_pct)
        cat = pd.DataFrame(
            {
                "competitor_mentioned": [str(bool(competitor))] * n,
                "client_tier": [tier] * n,
            }
        )
        cat_encoded = self.encoder.transform(cat)
        return np.column_stack([price_gap_pct, cat_encoded])

    def probability(
        self,
        price_gap_pct: float | np.ndarray,
        *,
        competitor_mentioned: bool = False,
        client_tier: str = UNKNOWN_TIER,
    ) -> np.ndarray:
        """P(near-win) for one or many price gaps, holding client context fixed."""
        gaps = np.atleast_1d(np.asarray(price_gap_pct, dtype=float))
        design = self._design(gaps, competitor_mentioned, client_tier)
        return self.model.predict_proba(design)[:, 1]


def build_training_frame(lost_leads: pd.DataFrame, client_facts: pd.DataFrame) -> pd.DataFrame:
    """Assemble the `lost_leads` rows usable for the win-probability fit.

    Excludes rows with a null `price_gap_pct` (1.7 §2: no counter-offer was
    ever made, so there is no gap to learn from — exclude, don't impute).
    Joins `client_tier` from `client_facts`, filling `UNKNOWN_TIER` for the
    643 leads that are new prospects identified by `company_name_raw` rather
    than a `client_id` (1.3: this join resolves at 55.7% *by design*).
    """
    frame = lost_leads.loc[lost_leads["price_gap_pct"].notna()].copy()

    tiers = client_facts[["client_id", "client_tier"]]
    frame = frame.merge(tiers, on="client_id", how="left")
    # `client_tier` loads as a pandas `category` (catalog.py declares it a
    # category column), and filling a category with an unseen value raises —
    # cast to plain `str` first, then fill the new-prospect rows.
    frame["client_tier"] = frame["client_tier"].astype("object").fillna(UNKNOWN_TIER).astype(str)

    frame["competitor_mentioned"] = frame["competitor_mentioned"].fillna(False).astype(bool)
    frame["near_win"] = frame["sales_stage_reached"].isin(NEAR_WIN_STAGES).astype(int)
    return frame


def fit_win_model(lost_leads: pd.DataFrame, client_facts: pd.DataFrame) -> FittedWinModel:
    """Fit P(near-win | price_gap, competitor_mentioned, client_tier).

    `price_gap_pct` enters as a raw continuous term (not scaled) so its
    coefficient reads directly as a log-odds change per unit of gap — an
    inspectable number, which is the auditability decision 4 traded a
    black-box classifier away for.
    """
    frame = build_training_frame(lost_leads, client_facts)

    cat = pd.DataFrame(
        {
            "competitor_mentioned": frame["competitor_mentioned"].astype(str),
            "client_tier": frame["client_tier"],
        }
    )
    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    cat_encoded = encoder.fit_transform(cat)

    gaps = frame["price_gap_pct"].to_numpy(dtype=float).reshape(-1, 1)
    design = np.column_stack([gaps, cat_encoded])
    labels = frame["near_win"].to_numpy(dtype=int)

    model = LogisticRegression(max_iter=1_000)
    model.fit(design, labels)

    feature_names = ("price_gap_pct", *encoder.get_feature_names_out(cat.columns).tolist())
    return FittedWinModel(
        encoder=encoder,
        model=model,
        feature_names=tuple(feature_names),
        n_training_rows=len(frame),
    )


def price_gap(price: float, reference_price: float) -> float:
    """`(price - reference) / reference`, matching `lost_leads.price_gap_pct` exactly.

    ADR-0003 decision 5: the reference is the client's target price where one
    is known, so the fitted model applies unchanged at prediction time. Where
    it is not known, the caller passes the band's target as the reference —
    a stated approximation, flagged in the explanation.
    """
    if reference_price <= 0:
        raise ValueError("reference_price must be positive to form a price gap")
    return (price - reference_price) / reference_price


@dataclass(frozen=True)
class TradeOffPoint:
    """One point on the Step 6.4 discounting trade-off curve."""

    price: float
    win_probability: float
    expected_value: float


def trade_off_curve(
    win_model: FittedWinModel,
    *,
    floor: float,
    cap: float,
    reference_price: float,
    competitor_mentioned: bool = False,
    client_tier: str = UNKNOWN_TIER,
    points: int = PRICE_GRID_POINTS,
) -> tuple[TradeOffPoint, ...]:
    """Evaluate `price x P(win)` across [floor, cap] — the curve Step 6.4 asks be shown.

    This is the artifact that lets a rep see *the cost of discounting*: not
    just the recommended number, but how much expected value is given up at
    every other price in the band.
    """
    grid = np.linspace(floor, cap, points)
    gaps = np.array([price_gap(p, reference_price) for p in grid])
    probabilities = win_model.probability(
        gaps, competitor_mentioned=competitor_mentioned, client_tier=client_tier
    )
    return tuple(
        TradeOffPoint(price=float(p), win_probability=float(w), expected_value=float(p * w))
        for p, w in zip(grid, probabilities, strict=True)
    )


def recommend_price(
    win_model: FittedWinModel,
    *,
    floor: float,
    cap: float,
    reference_price: float,
    competitor_mentioned: bool = False,
    client_tier: str = UNKNOWN_TIER,
    points: int = PRICE_GRID_POINTS,
) -> tuple[float, float, tuple[TradeOffPoint, ...]]:
    """Return `(recommended_price, win_probability_there, full_curve)`.

    The recommendation is `argmax(price x P(win))` over the grid — Step 6.4's
    expected-value criterion. Because the search is confined to [floor, cap],
    the result satisfies `PriceQuote`'s band invariant by construction rather
    than needing a clamp afterwards.

    **Expect this to land on the floor often, and that is the honest answer,
    not a bug.** The fitted gap coefficient is about -5.9 (log-odds per unit
    of gap), which means demand is *elastic* across a band this narrow: over
    a 15% span, P(win) falls by roughly 40% while price rises by 15%, so
    expected value declines monotonically and the argmax sits at the low end.
    Measured across a 60-screen sample, ~85% of quotes optimise to the floor.

    Read that as the model saying what 1.5 §6.2 and §6.3 already said: this is
    a price-sensitive market where the top loss reasons are "quoted rate
    exceeded client ceiling" and "rate card premium broke the budget." A
    single-deal expected-value argmax will always chase volume, because
    nothing in `price x P(win)` represents the *cost* of the deal — the floor
    is what encodes margin, and it is doing its job by stopping the search.

    Consequently the floor is not a formality here; it is frequently the
    binding constraint on the recommendation, and `compute_floor()`'s
    percentile and margin guard are what stand between this model and giving
    inventory away. A future pass that wants an interior optimum should add
    the missing term (contribution margin, or a strategic
    win-rate/yield-target weighting) rather than widen the band.
    """
    curve = trade_off_curve(
        win_model,
        floor=floor,
        cap=cap,
        reference_price=reference_price,
        competitor_mentioned=competitor_mentioned,
        client_tier=client_tier,
        points=points,
    )
    best = max(curve, key=lambda point: point.expected_value)
    return best.price, best.win_probability, curve
