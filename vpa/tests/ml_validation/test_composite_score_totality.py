"""Property test for Property 4: composite score totality (SP-313 Task 5.3).

**Property 4: Composite score totality** — *for any* valid ``ScoringParams``
(including configurations where ``vol_backed_mult_p1``/``vol_backed_mult_p2`` are
reduced, e.g. to ``0.0`` or ``1.0``, and reduced period weights), every scored
bar in the extracted dataset SHALL still have a non-null ``composite_score``;
reducing a multiplier changes the score's magnitude but never removes the score
term.

**Validates: Requirements 5.3**

Level tested + rationale
------------------------
This property is tested *through* ``VPAFeatureExtractor.generate_dataset`` — the
same path task 1 characterises — because Property 4 is stated in terms of "the
extracted dataset" and its ``composite_score`` column. That column is produced
only by ``generate_dataset`` (via ``_extract_feature_vector``), which assembles
the full per-bar intermediate state (warm-up, rolling percentiles, detected
signals) that ``composite_score`` depends on. There is no public per-bar entry
point that produces a ``composite_score`` in isolation without re-implementing
that assembly, so going through ``generate_dataset`` is the faithful level: it
asserts the invariant exactly as the design states it, over the real extraction
arithmetic, under arbitrary valid ``ScoringParams``.

Cost / runtime
--------------
``generate_dataset`` enforces a ``>= 2000`` labelled-row minimum (raising
``InsufficientDataError`` below that), so the property is exercised over a FIXED
~2100-row synthetic OHLCV frame injected through the ``repo`` dependency-injection
seam (reusing the task-1 ``_make_pinned_ohlcv_dataframe`` helper). Each extraction
over that window is expensive, so this test is marked ``slow`` and Hypothesis is
capped at ``max_examples=10`` with ``deadline=None`` to keep the runtime sane
while still sampling across the valid ``ScoringParams`` space (including the
reduced-multiplier / reduced-weight configurations Property 4 calls out).
"""

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.feature_extractor import VPAFeatureExtractor
from vpa.ml_validation.tuning.scoring_params import ScoringParams
from vpa.tests.ml_validation.test_feature_extraction_characterisation import (
    CONFIG_PATH,
    TICKER,
    _FakeRepo,
    _make_pinned_ohlcv_dataframe,
)

# Build the pinned ~2100-row OHLCV frame ONCE at module import. It is deterministic
# (seeded ``np.random.default_rng(42)``) and reused read-only across every Hypothesis
# example via a fresh ``_FakeRepo`` wrapper, so the data window is identical for every
# sampled ``ScoringParams`` and the only thing that varies is the scoring config.
_PINNED_OHLCV = _make_pinned_ohlcv_dataframe()


@st.composite
def valid_scoring_params(draw) -> ScoringParams:
    """Draw a ``ScoringParams`` whose fields lie within their valid ranges.

    The ranges mirror the ``validate()`` rules (Req 2.5 / 3.1 / 3.2 / 5.1) so almost
    every draw is valid; the ``assume(params.validate() == [])`` guard in the test
    filters any residual edge case. The spans deliberately include the reduced
    configurations Property 4 highlights: ``vol_backed_mult_pN`` down to ``0.0`` and
    ``period_weight_pN`` down to ``0.0``.
    """
    nonneg_mult = st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False)
    weight = st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False)
    return ScoringParams(
        # shooting-star multipliers must be >= 1 (Req 2.5)
        shooting_star_spread_mult=draw(st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False)),
        shooting_star_lower_wick_mult=draw(
            st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False)
        ),
        # acc/dist percentile int 1..99 (Req 3.1); test count int >= 1 (Req 3.2)
        acc_dist_volume_percentile=draw(st.integers(min_value=1, max_value=99)),
        acc_dist_test_count=draw(st.integers(min_value=1, max_value=10)),
        # period weights >= 0 (Req 4), reasonable 0.0..5.0 span incl. reduced weights
        period_weight_p1=draw(weight),
        period_weight_p2=draw(weight),
        period_weight_p3=draw(weight),
        # vol_backed mults >= 0 (Req 5.1), 0.0..5.0 incl. the reduced 0.0 / 1.0 cases
        vol_backed_mult_p1=draw(nonneg_mult),
        vol_backed_mult_p2=draw(nonneg_mult),
        vol_backed_mult_p3=draw(nonneg_mult),
    )


@pytest.mark.slow
class TestCompositeScoreTotality:
    """Every scored bar keeps a non-null composite_score under any valid ScoringParams."""

    @settings(max_examples=10, deadline=None)
    @given(params=valid_scoring_params())
    def test_composite_score_is_total_for_any_valid_params(self, params: ScoringParams):
        """Property 4: ``composite_score`` is present and non-null for every scored bar.

        For an arbitrary valid ``ScoringParams`` (including reduced ``vol_backed_mult``
        and reduced period weights), extract the labelled dataset over the fixed pinned
        window and assert the ``composite_score`` column exists and has no null/NaN
        values. Reducing a multiplier only scales the score's magnitude; it never drops
        the term, so the column must be total.
        """
        # Only exercise genuinely valid configurations (the strategy already constrains
        # to the valid ranges; this is belt-and-braces against any boundary surprise).
        assert params.validate() == []

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
            scoring_params=params,
        )
        dataset = extractor.generate_dataset(days=3650, repo=_FakeRepo(_PINNED_OHLCV))

        # Sanity: a non-empty dataset, otherwise "every scored bar" is vacuous.
        assert not dataset.empty, "pinned window produced an empty dataset"

        # Property 4: the composite_score column exists for every scored bar...
        assert "composite_score" in dataset.columns, "composite_score column is missing"
        # ...and carries no null/NaN value for any bar.
        null_count = dataset["composite_score"].isna().sum()
        assert null_count == 0, (
            f"{null_count} of {len(dataset)} scored bars have a null/NaN composite_score "
            f"under params={params!r}; the score term must never be removed"
        )
        # Guard against a non-numeric column sneaking NaNs past isna (e.g. object dtype
        # strings): the composite_score must be a real numeric series.
        assert pd.api.types.is_numeric_dtype(dataset["composite_score"]), "composite_score must be numeric"
