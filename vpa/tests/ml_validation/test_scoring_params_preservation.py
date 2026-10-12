"""Property 1 — default-params behaviour preservation (SP-313 Task 5.2).

This is the single most important behaviour-preservation guarantee of the SP-313
refactor. Task 1 locked the current/legacy ``VPAFeatureExtractor.generate_dataset``
output as a committed regression fixture
(``fixtures/spy_feature_extraction_baseline.csv``) over a FIXED, seeded synthetic
OHLCV window injected through the ``repo`` dependency-injection seam. That fixture is
the oracle.

Here we assert **Correctness Property 1**: threading an EXPLICIT
``ScoringParams.default()`` through extraction reproduces today's scoring EXACTLY —
the freshly-extracted dataset must equal the task-1 fixture column-for-column
(including ``composite_score`` and ``next_day_direction``). Because
``VPAFeatureExtractor`` now accepts ``scoring_params`` (default ``None`` →
``ScoringParams.default()``), this proves the injectable-params change is a no-op for
the default configuration.

Apples-to-apples with task 1: this module REUSES the task-1 oracle directly — the same
``_FakeRepo`` and ``_make_pinned_ohlcv_dataframe`` pinned-window mechanism, the same
committed fixture + loader, the same ``EXPECTED_COLUMNS`` schema, and the same float
tolerance (``rtol``/``atol`` 1e-9). The ONLY difference from task 1 is that the
extractor is constructed with an explicit ``scoring_params=ScoringParams.default()``
rather than relying on the implicit default. If this test fails it indicates a real
regression in the refactor — do NOT regenerate the fixture to make it pass.

Marked ``slow`` per the repo convention (it re-extracts features over a ~2100-bar
window); the default ``pytest`` run deselects it via ``-m 'not slow'``.

Requirements: 2, 3, 4, 5 (non-regression)
Property 1: Default-params behaviour preservation
"""

import pandas as pd
import pytest

# Reuse the task-1 oracle verbatim so the comparison is apples-to-apples with the
# committed regression fixture. See test_feature_extraction_characterisation.py
# (SP-313 Task 1) for the pinned-window + fixture mechanism these helpers implement.
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor
from vpa.ml_validation.tuning.scoring_params import ScoringParams

from .test_feature_extraction_characterisation import (
    CONFIG_PATH,
    EXPECTED_COLUMNS,
    FLOAT_ATOL,
    FLOAT_RTOL,
    TICKER,
    _FakeRepo,
    _load_fixture,
    _make_pinned_ohlcv_dataframe,
)


def _extract_with_params(scoring_params: ScoringParams) -> pd.DataFrame:
    """Extract the labelled dataset over the task-1 pinned window with given params.

    Mirrors the task-1 ``_extract_current_dataset`` helper exactly, except the
    extractor is constructed with an EXPLICIT ``scoring_params`` so we exercise the
    injectable-params path rather than the implicit default.
    """
    pinned_df = _make_pinned_ohlcv_dataframe()
    extractor = VPAFeatureExtractor(
        config_path=CONFIG_PATH,
        ticker_symbol=TICKER,
        enable_extraction=True,
        scoring_params=scoring_params,
    )
    return extractor.generate_dataset(days=3650, repo=_FakeRepo(pinned_df))


def _roundtrip_through_csv(dataset: pd.DataFrame) -> pd.DataFrame:
    """Round-trip a frame through CSV, matching how the fixture was serialised.

    This neutralises CSV float-formatting differences and aligns dtypes with the
    committed fixture, exactly as the task-1 characterisation test does.
    """
    return pd.read_csv(pd.io.common.StringIO(dataset.to_csv(index=False)), dtype={"date": str})


@pytest.mark.slow
class TestDefaultParamsPreservation:
    """Property 1: ScoringParams.default() reproduces the task-1 fixture exactly."""

    def test_explicit_default_params_match_committed_fixture(self):
        """Extracting with an EXPLICIT ``ScoringParams.default()`` equals the fixture.

        Column-for-column (including ``composite_score`` and ``next_day_direction``),
        within the same 1e-9 float tolerance task 1 uses. A failure here means the
        injectable-params refactor changed the default scoring behaviour — a real
        regression, not a fixture-staleness issue.
        """
        extracted = _extract_with_params(ScoringParams.default())

        # Guard: schema + minimum-row sanity so the oracle comparison is meaningful.
        assert (
            list(extracted.columns) == EXPECTED_COLUMNS
        ), "extraction schema drifted from the expected 33 features + metadata + label"
        assert len(extracted) >= 2000, "pinned window must yield >=2000 labelled rows"

        expected = _load_fixture()
        extracted_roundtripped = _roundtrip_through_csv(extracted)

        pd.testing.assert_frame_equal(
            extracted_roundtripped,
            expected,
            check_exact=False,
            rtol=FLOAT_RTOL,
            atol=FLOAT_ATOL,
            check_dtype=True,
            check_like=False,
        )

    def test_bare_scoringparams_equals_default_and_same_dataset(self):
        """``ScoringParams()`` is the identity config: equals ``default()`` and yields
        the same dataset as the committed fixture.

        Reinforces that the no-arg constructor is the canonical current configuration.
        Reuses the already-extracted comparison path and stays slow-safe (one extra
        extraction over the pinned window).
        """
        assert ScoringParams() == ScoringParams.default()

        extracted = _extract_with_params(ScoringParams())
        expected = _load_fixture()
        extracted_roundtripped = _roundtrip_through_csv(extracted)

        pd.testing.assert_frame_equal(
            extracted_roundtripped,
            expected,
            check_exact=False,
            rtol=FLOAT_RTOL,
            atol=FLOAT_ATOL,
            check_dtype=True,
            check_like=False,
        )
