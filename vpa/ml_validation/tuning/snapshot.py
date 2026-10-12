"""Pinned raw-OHLCV dataset snapshot for the SP-313 threshold-tuning experiment.

A :class:`DatasetSnapshot` pins the data window at the *raw-OHLCV* boundary so a
sweep over many candidate ``ScoringParams`` is apples-to-apples: every candidate
re-extracts features from the same stored bars over the same ``(data_start,
data_end)`` window, at the same seed. The design (see the ``DatasetSnapshot``
section under *Components and Interfaces* and *Reproducibility: pinning the data
window*) establishes why pinning happens here rather than at the post-extraction
CSV: the tunable thresholds are consumed *during* feature extraction, so each
candidate must re-extract.

:meth:`DatasetSnapshot.extract` is the single seeding point for reproducible
sweeps (Req 1.1, 1.4): it mirrors ``run_analysis.main``, which calls
``np.random.seed(42)`` once before dataset generation. Given a fixed window, a
fixed seed, and fixed ``ScoringParams``, the read-through ``MarketDataRepository``
returns the same stored bars, so the resulting labelled dataset is deterministic:
identical ``(snapshot, params)`` -> identical dataset.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from vpa.ml_validation.feature_extractor import VPAFeatureExtractor
from vpa.ml_validation.tuning.scoring_params import ScoringParams

# Default VPA config path, resolved the way ``run_analysis.main`` does:
# ``vpa/config/config.json``. This module lives at
# ``vpa/ml_validation/tuning/snapshot.py`` so the ``vpa`` package root is
# ``parents[2]``.
DEFAULT_CONFIG_PATH = str(Path(__file__).resolve().parents[2] / "config" / "config.json")


@dataclass(frozen=True)
class DatasetSnapshot:
    """Pins the raw-OHLCV window for one experiment.

    A snapshot is identified by ``(ticker, data_start, data_end, seed)``. The
    experiment layer uses this identity to refuse mixing candidates evaluated
    against different snapshots, keeping a sweep apples-to-apples.

    Attributes:
        ticker: Ticker symbol to analyse (e.g. ``"SPY"``).
        data_start: Inclusive start of the pinned data window.
        data_end: Inclusive end of the pinned data window; passed to
            ``generate_dataset`` as ``end_date`` to pin the window (Req 1.4).
        seed: Fixed random seed set before dataset generation (Req 1.1). Default
            ``42`` matches ``run_analysis.main``.
    """

    ticker: str
    data_start: datetime.date
    data_end: datetime.date
    seed: int = 42

    def extract(
        self,
        params: ScoringParams,
        repo=None,
        config_path: str = DEFAULT_CONFIG_PATH,
    ) -> pd.DataFrame:
        """Re-extract the labelled feature dataset over the pinned window.

        This is the single seeding point for reproducible sweeps (Req 1.1, 1.4):
        it sets the numpy seed to :attr:`seed` *before* generating the dataset,
        mirroring ``run_analysis.main`` (which does ``np.random.seed(42)`` before
        dataset generation), then re-extracts features over the pinned
        ``(data_start, data_end)`` window with the supplied ``params``.

        Because the window and seed are fixed and the read-through
        ``MarketDataRepository`` serves the same stored bars for the same window,
        the result is deterministic: identical ``(snapshot, params)`` produce an
        identical dataset.

        Args:
            params: The ``ScoringParams`` to inject into feature extraction for
                this candidate.
            repo: Optional ``MarketDataRepository`` for dependency injection in
                tests; forwarded to ``generate_dataset``. ``None`` lets the
                extractor construct its own repository.
            config_path: Path to the VPA config JSON. Defaults to
                ``vpa/config/config.json`` (resolved the way
                ``run_analysis.main`` resolves it).

        Returns:
            The labelled feature dataset for the pinned window and ``params``.
        """
        # Req 1.1 — centralise seeding before dataset generation.
        np.random.seed(self.seed)

        extractor = VPAFeatureExtractor(
            config_path=config_path,
            ticker_symbol=self.ticker,
            enable_extraction=True,
            scoring_params=params,
        )

        # Span the window [data_start, data_end]: generate_dataset computes the
        # start as end_date - timedelta(days=days), so days is the inclusive span.
        days = (self.data_end - self.data_start).days
        return extractor.generate_dataset(days=days, repo=repo, end_date=self.data_end)
