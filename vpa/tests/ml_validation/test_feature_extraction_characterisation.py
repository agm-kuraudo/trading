"""Characterisation / regression fixture for the current VPA feature-extraction path.

SP-313 Task 1 (SAFETY NET — before any refactor).

This test LOCKS the current/legacy ``VPAFeatureExtractor.generate_dataset`` output as a
committed regression fixture, so that the later injectable-``ScoringParams`` refactor
(tasks 3, 4, 5) can be proven behaviour-preserving. It is the oracle that
**Property 1 (default-params behaviour preservation)** asserts against: once
``ScoringParams.default()`` is threaded through extraction, re-extracting over this same
pinned window must reproduce this fixture column-for-column.

Reproducibility (Req 1.4): the data window is pinned by injecting a FIXED synthetic
OHLCV frame through the existing ``repo`` dependency-injection seam of
``generate_dataset`` (a ``MarketDataRepository`` stub whose ``load_ohlcv`` always
returns the same frame). The frame is generated once from a fixed seed
(``np.random.default_rng(42)``), so the extracted dataset is deterministic and does not
depend on today's date or any network access. ``generate_dataset`` does not yet accept
an ``end_date`` parameter (that arrives in task 6.1), so pinning the data at the ``repo``
boundary is the correct mechanism for this task.

The expected dataset is stored as a committed CSV under ``fixtures/`` and the test
asserts the freshly-extracted dataset equals the stored fixture column-for-column, with
an explicit tolerance for float columns via ``pandas.testing.assert_frame_equal``.

Marked ``slow`` per the repo convention (it re-extracts features over a ~2100-bar
window); the default ``pytest`` run deselects it via ``-m 'not slow'``.

To regenerate the fixture after an INTENTIONAL, reviewed change to the extraction
output, run this module directly::

    python -m vpa.tests.ml_validation.test_feature_extraction_characterisation

or set ``REGEN_VPA_CHARACTERISATION_FIXTURE=1`` and run the test once; it will rewrite
the CSV and skip the comparison for that run. Never regenerate casually — the whole
point of this fixture is to catch accidental drift.

Requirements: 1.2
Property 1: Default-params behaviour preservation
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

CONFIG_PATH = str(Path(__file__).resolve().parents[2] / "config" / "config.json")
TICKER = "SPY"

# PERIOD_THREE_LENGTH=50 -> warm-up skips the first 49 rows; the final row is excluded
# (no next-day label). 2100 raw rows -> 2100 - 49 - 1 = 2050 labelled rows, comfortably
# clearing the >=2000 gate in generate_dataset.
N_RAW_ROWS = 2100

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_PATH = FIXTURE_DIR / "spy_feature_extraction_baseline.csv"

# Tolerances for the float-column comparison. The fixture is produced by the SAME code
# path, so differences should be exactly zero; a tiny tolerance guards only against
# cross-platform float-formatting round-trips through CSV.
FLOAT_RTOL = 1e-9
FLOAT_ATOL = 1e-9


class _FakeRepo:
    """Stub ``MarketDataRepository`` returning a fixed canonical OHLCV frame.

    ``load_ohlcv`` mirrors the real signature and returns the same
    ``Date, Open, High, Low, Close, Volume`` frame on every call, pinning the data
    window independently of the requested ``start``/``end`` dates. Performs no I/O.
    """

    def __init__(self, df: pd.DataFrame):
        self._df = df

    def load_ohlcv(self, ticker, interval, start, end) -> pd.DataFrame:  # noqa: ARG002
        return self._df.copy()


def _make_pinned_ohlcv_dataframe(n_rows: int = N_RAW_ROWS, start_date: str = "2010-01-04") -> pd.DataFrame:
    """Generate the FIXED synthetic OHLCV frame that pins the extraction window.

    Uses a seeded ``np.random.default_rng(42)`` so the frame — and therefore the whole
    extracted feature dataset — is bit-for-bit reproducible across runs and machines.
    The series is a gentle random-walk with realistic intrabar ranges so the VPA logic
    exercises every scoring branch (shooting-star/hammer detection, acc/dist, volume
    percentiles) rather than degenerate flat data.

    Mirrors the construction idiom already used by ``test_feature_extractor.py``.
    """
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(start=start_date, periods=n_rows)

    base_price = 100.0
    returns = rng.normal(0.0005, 0.01, size=n_rows)
    closes = base_price * np.cumprod(1 + returns)

    opens = closes * (1 + rng.normal(0, 0.002, size=n_rows))
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0.001, 0.01, size=n_rows))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0.001, 0.01, size=n_rows))
    volumes = rng.integers(1_000_000, 100_000_000, size=n_rows).astype(float)

    return pd.DataFrame(
        {
            "Date": dates,
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        }
    )


def _extract_current_dataset() -> pd.DataFrame:
    """Run the current/legacy extraction path over the pinned window.

    Centralises the single source of truth for both fixture generation and the
    in-test comparison so the two can never drift apart.
    """
    pinned_df = _make_pinned_ohlcv_dataframe()
    extractor = VPAFeatureExtractor(
        config_path=CONFIG_PATH,
        ticker_symbol=TICKER,
        enable_extraction=True,
    )
    return extractor.generate_dataset(days=3650, repo=_FakeRepo(pinned_df))


# Expected column order of the stored fixture: all 33 feature columns, the raw-OHLC
# metadata, and the next_day_direction label.
EXPECTED_COLUMNS = [
    *VPAFeatureExtractor.FEATURE_COLUMNS,
    *VPAFeatureExtractor.METADATA_COLUMNS,
    "next_day_direction",
]


def _write_fixture(dataset: pd.DataFrame) -> None:
    """Persist the extracted dataset as the committed oracle CSV."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(FIXTURE_PATH, index=False)


def _load_fixture() -> pd.DataFrame:
    """Load the committed oracle CSV, coercing dtypes to match a fresh extraction.

    The ``date`` column is stored as an ISO string by the extractor, so it is read back
    as ``str`` to compare equal to a freshly-extracted frame.
    """
    return pd.read_csv(FIXTURE_PATH, dtype={"date": str})


@pytest.mark.slow
class TestFeatureExtractionCharacterisation:
    """Lock the current extraction output as a regression oracle (SP-313 Task 1)."""

    def test_extraction_matches_committed_regression_fixture(self):
        """The freshly-extracted dataset must equal the committed fixture column-for-column.

        This is the behaviour-preservation oracle for the SP-313 refactor: if a later
        change to the extraction path alters any of the 33 feature columns (including
        ``composite_score``) or ``next_day_direction``, this test fails and the drift is
        caught before it can silently change production scoring.
        """
        extracted = _extract_current_dataset()

        # Guard: the extracted dataset must carry exactly the expected schema and clear
        # the >=2000 labelled-row minimum, so the oracle is meaningful.
        assert (
            list(extracted.columns) == EXPECTED_COLUMNS
        ), "extraction schema drifted from the expected 33 features + metadata + label"
        assert len(extracted) >= 2000, "pinned window must yield >=2000 labelled rows"

        if os.environ.get("REGEN_VPA_CHARACTERISATION_FIXTURE") == "1" or not FIXTURE_PATH.exists():
            _write_fixture(extracted)
            pytest.skip(f"Regenerated characterisation fixture at {FIXTURE_PATH}; re-run to compare.")

        expected = _load_fixture()

        # Round-trip the freshly-extracted frame through the same CSV serialisation the
        # fixture used, so the comparison is unaffected by CSV float formatting and the
        # two frames share identical dtypes.
        extracted_roundtripped = pd.read_csv(pd.io.common.StringIO(extracted.to_csv(index=False)), dtype={"date": str})

        pd.testing.assert_frame_equal(
            extracted_roundtripped,
            expected,
            check_exact=False,
            rtol=FLOAT_RTOL,
            atol=FLOAT_ATOL,
            check_dtype=True,
            check_like=False,
        )


if __name__ == "__main__":
    # Direct-run convenience: (re)generate the committed fixture from current code.
    dataset = _extract_current_dataset()
    _write_fixture(dataset)
    print(f"Wrote characterisation fixture ({len(dataset)} rows) to {FIXTURE_PATH}")
