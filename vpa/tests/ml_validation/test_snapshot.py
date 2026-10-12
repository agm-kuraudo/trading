"""Tests for ``DatasetSnapshot`` (SP-313 Task 7).

``DatasetSnapshot`` pins the raw-OHLCV window and centralises Req 1.1 seeding so a
sweep over candidate ``ScoringParams`` is apples-to-apples and reproducible
(Req 1.4). Two kinds of test live here:

- A FAST check of the snapshot *identity* — the frozen dataclass is hashable and
  equal by ``(ticker, data_start, data_end, seed)``, which is what the experiment
  layer relies on to refuse mixing snapshots.
- A ``slow`` determinism check that two ``extract()`` calls with the same params
  over the same pinned window produce an identical labelled dataset. It is
  ``slow`` because ``generate_dataset`` requires >=2000 labelled rows, so it
  necessarily re-extracts features over a ~2100-bar frame.

The pinned window is injected through the existing ``repo`` seam (a
``MarketDataRepository`` stub whose ``load_ohlcv`` returns a fixed, seeded frame),
mirroring ``test_feature_extraction_characterisation.py`` — no network access.

Requirements: 1.1, 1.4
"""

import datetime

import numpy as np
import pandas as pd
import pytest

from vpa.ml_validation.tuning.scoring_params import ScoringParams
from vpa.ml_validation.tuning.snapshot import DatasetSnapshot

TICKER = "SPY"
DATA_START = datetime.date(2010, 1, 4)
DATA_END = datetime.date(2018, 2, 1)
# PERIOD_THREE_LENGTH=50 -> warm-up skips 49 rows, final row excluded. 2100 raw
# rows -> 2050 labelled rows, clearing the >=2000 gate in generate_dataset.
N_RAW_ROWS = 2100


class _FakeRepo:
    """Stub ``MarketDataRepository`` returning a fixed canonical OHLCV frame.

    ``load_ohlcv`` returns the same ``Date, Open, High, Low, Close, Volume`` frame
    on every call, pinning the window independently of the requested dates and
    performing no I/O.
    """

    def __init__(self, df: pd.DataFrame):
        self._df = df

    def load_ohlcv(self, ticker, interval, start, end) -> pd.DataFrame:  # noqa: ARG002
        return self._df.copy()


def _make_pinned_ohlcv_dataframe(n_rows: int = N_RAW_ROWS, start_date: str = "2010-01-04") -> pd.DataFrame:
    """Generate the FIXED synthetic OHLCV frame that pins the extraction window.

    Seeded ``np.random.default_rng(42)`` makes the frame bit-for-bit reproducible.
    Mirrors the idiom in ``test_feature_extraction_characterisation.py``.
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


class TestDatasetSnapshotIdentity:
    """FAST checks of the snapshot identity used to keep sweeps apples-to-apples."""

    def test_default_seed_is_42(self):
        snapshot = DatasetSnapshot(ticker=TICKER, data_start=DATA_START, data_end=DATA_END)
        assert snapshot.seed == 42

    def test_identity_is_ticker_start_end_seed(self):
        a = DatasetSnapshot(TICKER, DATA_START, DATA_END, seed=42)
        b = DatasetSnapshot(TICKER, DATA_START, DATA_END, seed=42)
        c = DatasetSnapshot(TICKER, DATA_START, DATA_END, seed=7)
        d = DatasetSnapshot("AAPL", DATA_START, DATA_END, seed=42)

        # Equal by (ticker, data_start, data_end, seed) and hashable (frozen).
        assert a == b
        assert hash(a) == hash(b)
        assert a != c
        assert a != d
        # Usable as set/dict keys so the layer can detect mixed snapshots.
        assert len({a, b, c, d}) == 3


@pytest.mark.slow
class TestDatasetSnapshotExtractDeterminism:
    """``slow`` determinism check: identical (snapshot, params) -> identical dataset."""

    def test_two_extracts_with_same_params_are_identical(self):
        """Two ``extract()`` calls with the same params over the same pinned window
        must produce an identical labelled dataset.

        This exercises the single seeding point (Req 1.1): ``extract`` sets
        ``np.random.seed(seed)`` before generation, so even if intervening code
        perturbs global numpy state the two extractions coincide (Req 1.4).
        """
        pinned_df = _make_pinned_ohlcv_dataframe()
        snapshot = DatasetSnapshot(ticker=TICKER, data_start=DATA_START, data_end=DATA_END)
        params = ScoringParams.default()

        first = snapshot.extract(params, repo=_FakeRepo(pinned_df))

        # Perturb global numpy RNG state between runs to prove extract() reseeds.
        np.random.seed(123)
        _ = np.random.random(10)

        second = snapshot.extract(params, repo=_FakeRepo(pinned_df))

        assert len(first) >= 2000, "pinned window must yield >=2000 labelled rows"
        pd.testing.assert_frame_equal(first, second, check_exact=True)
