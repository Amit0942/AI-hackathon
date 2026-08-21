"""Step 6.3 (base rate) — a transparent, fitted model over the empirically confirmed price drivers.

ADR-0003 decision 2/3: regularised linear regression (ElasticNet) over the
Step 1.5 §2 ranked drivers (`city_id`, `screen_type`, `screen_size`,
`time_block_id`, `rotation_type`, `slots_booked_per_day`), with explicit
`screen_type x slots_booked_per_day` interaction terms so the 1.5 §5.2
confound (the slot-count discount is real for bus/metro_station and
*inverts* for bus_stop) is representable, not averaged away. Chosen over a
GBM for interpretability: every coefficient becomes one `Contribution` in
the `Explanation`, so a price is attributable dollar-by-dollar, per the
`Explanation` contract (CLAUDE.md).

Fit only on `settled` (completed) bookings on
`contracted_price_per_slot_per_day` — per 1.5 §1, the only safe training set.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNet
from sklearn.preprocessing import OneHotEncoder, StandardScaler

#: Step 1.5 §2 ranked drivers, in descending effect-size order.
#:
#: `rotation_type` is deliberately **excluded** (removed 2026-08-21,
#: ADR-0003 decision 3 as amended). Step 1.4 §1.3 proves it and
#: `slots_booked_per_day` partition each other *exactly* —
#: `single_rotation` <-> 1 slot, `partial_rotation` <-> 2-4,
#: `full_exclusivity` <-> 5-6 — so it is a deterministic step function of a
#: continuous feature already in the model, carrying zero independent
#: information (1.5 §2 ranks its effect an order of magnitude below every
#: other driver and calls it "a label on a slot count"). One-hot encoding it
#: alongside `slots_booked_per_day` puts perfectly collinear columns into the
#: ElasticNet, whose L1/L2 penalty then splits the shared coefficient
#: arbitrarily between them. That corrupts `contributions()` — the per-feature
#: dollar attribution the `Explanation` contract depends on and the exact
#: reason decision 2 chose a linear model over a GBM. Step 6.3's plan text
#: names `rotation_type` as a driver, but it predates 1.4's partition proof;
#: the measurement supersedes the plan.
#:
#: `position` is included: 1.4 §2.3 shows it is structural rather than random
#: (metro_station splits platform vs. entrance_exit — a waiting audience vs. a
#: moving one; bus splits back/left/right), and Step 6.3 names it as a base-rate
#: driver. Its null on all 1,400 `metro_rail_coach` rows is a *structural* null
#: (interior coach panels have no mount face, 1.7 §2), so it is encoded as an
#: explicit "none" category rather than dropped — dropping those rows would
#: silently remove an entire screen type from the training set.
CATEGORICAL_FEATURES: tuple[str, ...] = (
    "time_block_id",
    "screen_size",
    "screen_type",
    "city_id",
    "position",
)
NUMERIC_FEATURES: tuple[str, ...] = ("slots_booked_per_day",)
TARGET_COLUMN = "contracted_price_per_slot_per_day"

#: Stand-in category for `screens.position`'s structural null (1.7 §2).
POSITION_NONE = "none"


def join_screen_attributes(bookings: pd.DataFrame, screens: pd.DataFrame) -> pd.DataFrame:
    """Attach `screen_type`/`screen_size`/`position` from `screens` onto a bookings frame.

    `bookings.csv` carries only `screen_id` — `screen_type`, `screen_size` and
    `position` all live on `screens.csv` and must be joined in before fitting
    or scoring the base-rate model, since all three are Step 6.3 price drivers.

    `position` is null for every `metro_rail_coach` row by design (1.4 §2.3:
    interior panels have no mount face). That null is filled with an explicit
    `POSITION_NONE` category here rather than left to `dropna` in
    `fit_base_rate_model`, which would drop all 1,400 coach screens from
    training.
    """
    attrs = screens[["screen_id", "screen_type", "screen_size", "position"]]
    merged = bookings.merge(attrs, on="screen_id", how="left")
    # `position` loads as a pandas `category` (catalog.py declares it one);
    # filling a category with an unseen value raises, so cast to plain
    # `object` first. The model one-hot-encodes from `str` anyway.
    merged["position"] = merged["position"].astype("object").fillna(POSITION_NONE)
    return merged


@dataclass(frozen=True)
class FittedBaseRateModel:
    """A fitted base-rate model plus everything needed to explain a prediction.

    Kept as one immutable bundle (encoder + scaler + model + feature names)
    because Step 6.3 needs to reconstruct *which* coefficient produced how
    much of a given prediction — that requires the exact fitted transformers,
    not just the raw `ElasticNet` object.
    """

    encoder: OneHotEncoder
    scaler: StandardScaler
    model: ElasticNet
    screen_type_categories: tuple[str, ...]
    feature_names: tuple[str, ...]

    def _design_row(self, row: pd.Series) -> np.ndarray:
        # Fit-time categorical columns are cast to plain `str` (see
        # `fit_base_rate_model`) — cast here too, since `row` may carry enum
        # values, pandas `category` dtype, or a bare `int` (`time_block_id`),
        # none of which the fitted encoder's `str` categories would match.
        cat_values = pd.DataFrame([{col: str(row[col]) for col in CATEGORICAL_FEATURES}])
        cat_encoded = self.encoder.transform(cat_values)
        slots = float(row["slots_booked_per_day"])

        # Interaction terms: screen_type one-hot columns (a fixed, known slice
        # of the encoder's output) multiplied by slots_booked_per_day.
        screen_type_slice = _screen_type_column_slice(self.encoder, self.screen_type_categories)
        interaction = cat_encoded[:, screen_type_slice] * slots

        numeric = self.scaler.transform(pd.DataFrame([[slots]], columns=["slots_booked_per_day"]))
        design = np.concatenate([cat_encoded, numeric, interaction], axis=1)
        return design[0]

    def predict_one(self, row: pd.Series) -> float:
        design = self._design_row(row).reshape(1, -1)
        return float(self.model.predict(design)[0])

    def contributions(self, row: pd.Series) -> list[tuple[str, float]]:
        """(feature_name, dollar_contribution) pairs for one row, coefficient x value.

        This is what lets Step 6.3's `Explanation` cite a per-feature dollar
        effect rather than a bare predicted number — each entry sums to the
        model's raw linear prediction (before any clamping).
        """
        design = self._design_row(row)
        return list(zip(self.feature_names, design * self.model.coef_, strict=True))


def _screen_type_column_slice(encoder: OneHotEncoder, screen_type_categories: tuple[str, ...]) -> slice:
    """Locate the contiguous block of one-hot columns belonging to `screen_type`.

    `OneHotEncoder` concatenates each categorical column's dummies in the
    order `CATEGORICAL_FEATURES` was given, so the offset is the sum of the
    prior columns' cardinalities.
    """
    offset = 0
    for col, categories in zip(CATEGORICAL_FEATURES, encoder.categories_, strict=True):
        width = len(categories)
        if col == "screen_type":
            return slice(offset, offset + width)
        offset += width
    raise ValueError("screen_type not found in encoder categories")


def fit_base_rate_model(
    settled_bookings: pd.DataFrame,
    *,
    alpha: float = 0.1,
    l1_ratio: float = 0.5,
    random_state: int = 0,
) -> FittedBaseRateModel:
    """Fit the Step 6.3 base-rate model on settled bookings.

    *settled_bookings* must already be filtered to `booking_status ==
    'completed'` (Step 1.5 §1 — the caller's `BookingRepository.settled()`
    guarantees this, so this function does not re-filter and trusts its
    input, per the repository-protocol boundary) **and** must already carry
    `screen_type`/`screen_size` joined in from `screens` — `bookings.csv`
    itself has neither column. `join_screen_attributes()` below is the one
    place that join happens.
    """
    frame = settled_bookings.dropna(
        subset=[*CATEGORICAL_FEATURES, *NUMERIC_FEATURES, TARGET_COLUMN]
    ).copy()
    for col in CATEGORICAL_FEATURES:
        frame[col] = frame[col].astype(str)

    encoder = OneHotEncoder(sparse_output=False, handle_unknown="ignore")
    cat_encoded = encoder.fit_transform(frame[list(CATEGORICAL_FEATURES)])

    slots = frame[["slots_booked_per_day"]].astype(float)
    scaler = StandardScaler()
    numeric_scaled = scaler.fit_transform(slots)

    screen_type_categories = tuple(
        str(c) for c in encoder.categories_[CATEGORICAL_FEATURES.index("screen_type")]
    )
    screen_type_slice = _screen_type_column_slice(encoder, screen_type_categories)
    interaction = cat_encoded[:, screen_type_slice] * slots.to_numpy()

    design = np.concatenate([cat_encoded, numeric_scaled, interaction], axis=1)
    target = frame[TARGET_COLUMN].to_numpy(dtype=float)

    model = ElasticNet(alpha=alpha, l1_ratio=l1_ratio, random_state=random_state, max_iter=10_000)
    model.fit(design, target)

    cat_names = list(encoder.get_feature_names_out(CATEGORICAL_FEATURES))
    numeric_names = ["slots_booked_per_day"]
    interaction_names = [f"screen_type_{c}:slots_booked_per_day" for c in screen_type_categories]
    feature_names = tuple(cat_names + numeric_names + interaction_names)

    return FittedBaseRateModel(
        encoder=encoder,
        scaler=scaler,
        model=model,
        screen_type_categories=screen_type_categories,
        feature_names=feature_names,
    )
