"""SP-349 (Task 8.6): consumer-migration regression tests.

These tests lock in the behaviour of the consumer migration (Tasks 8.2/8.3/8.4):
every bar consumer now sources data from the market-data store
(``MarketDataRepository.load_ohlcv``) instead of calling ``yfinance.download``
directly. Each test therefore patches ``yfinance.download`` to raise if it is ever
called, wires a warm store via a fake repository, and asserts the consumer completes
offline against the store.

Because ``vpa.market_data.ohlcv_ingest`` binds yfinance as ``import yfinance as yf``,
``fetch_yf`` calls ``yf.download`` which resolves the same function object as
``yfinance.download``; patching ``yfinance.download`` therefore also neutralises the
read-through fetch path, giving a genuine "no direct network call" guarantee.

Requirements:
- 5.1  VPAFeatureExtractor.generate_dataset sources bars from the repository and
       preserves the 2000-row InsufficientDataError gate.
- 5.2  MarketAnalyzer.load_data sources bars from the repository via read-through,
       preserving the downstream column set.
- 5.3  The all-shares scan sources each ticker's bars through the analyzer/store.
"""

import os

import numpy as np
import pandas as pd
import pytest

from vpa.app_all_shares import run_scan
from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

CONFIG_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "config", "config.json"))
TICKER = "SPY"

# PERIOD_THREE_LENGTH=50 -> warm-up skips 49 rows; final row excluded. 2050 raw rows
# -> 2050 - 49 - 1 = 2000 labelled rows, exactly clearing the >=2000 gate.
WARM_ROWS = 2050


def _make_ohlcv_dataframe(n_rows: int, start_date: str = "2010-01-04") -> pd.DataFrame:
    """Generate a deterministic canonical OHLCV DataFrame (Date, O, H, L, C, V).

    Produces a gently trending random walk so the VPA feature logic yields valid,
    fully-populated features. This is the same canonical shape the store's
    ``load_ohlcv`` returns.
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


class _FakeRepo:
    """Warm-store stand-in for ``MarketDataRepository``.

    ``load_ohlcv`` returns a fixed canonical frame and records each call, so tests can
    assert the consumer read through the store. It performs no network I/O and never
    touches a DB.
    """

    def __init__(self, df: pd.DataFrame):
        self._df = df
        self.calls: list[tuple] = []

    def load_ohlcv(self, ticker, interval, start, end) -> pd.DataFrame:
        self.calls.append((ticker, interval, start, end))
        return self._df.copy()


def _boom_download(*args, **kwargs):
    """Stand-in for ``yfinance.download`` that fails the test if the network is hit."""
    raise AssertionError("network access attempted: yfinance.download was called")


class _NullLogger:
    """No-op, no-file logger stand-in so analyzer construction writes no artifacts."""

    def __init__(self, level="DEBUG", file_prefix="debug_log"):
        self.level = level
        self.file_prefix = file_prefix

    def log(self, message, level="DEBUG"):  # noqa: ARG002 - no-op stand-in
        return None

    def __del__(self):
        return None


# ---------------------------------------------------------------------------
# Requirement 5.1 - VPAFeatureExtractor.generate_dataset sources from the store
# ---------------------------------------------------------------------------


class TestFeatureExtractorSourcesFromStore:
    """Req 5.1: generate_dataset reads the repository, never the network directly."""

    def test_generate_dataset_completes_from_warm_store_without_network(self, monkeypatch):
        """With a warm store, generate_dataset completes and makes no yfinance call."""
        monkeypatch.setattr("yfinance.download", _boom_download)

        warm = _make_ohlcv_dataframe(WARM_ROWS)
        repo = _FakeRepo(warm)

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        # Must not raise (network patched to raise; a network call would fail here).
        result = extractor.generate_dataset(days=3650, repo=repo)

        assert len(result) >= 2000
        # The bars were sourced from the store, for the right ticker/interval.
        assert repo.calls, "generate_dataset must read through the repository"
        assert repo.calls[0][0] == TICKER
        assert repo.calls[0][1] == "1d"

    def test_generate_dataset_raises_insufficient_data_under_2000_rows(self, monkeypatch):
        """A store returning too few usable rows still raises InsufficientDataError,
        and does so via the store (no network fallback)."""
        monkeypatch.setattr("yfinance.download", _boom_download)

        # 2049 raw rows -> 2049 - 49 - 1 = 1999 labelled rows -> under the 2000 gate.
        thin = _make_ohlcv_dataframe(2049)
        repo = _FakeRepo(thin)

        extractor = VPAFeatureExtractor(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            enable_extraction=True,
        )

        with pytest.raises(InsufficientDataError):
            extractor.generate_dataset(days=3650, repo=repo)

        assert repo.calls, "the insufficient-data path must still read the store"


# ---------------------------------------------------------------------------
# Requirement 5.2 - MarketAnalyzer.load_data sources from the store
# ---------------------------------------------------------------------------


class TestMarketAnalyzerSourcesFromStore:
    """Req 5.2: MarketAnalyzer.load_data reads the repository via read-through."""

    def test_load_data_populates_from_store_without_network(self, monkeypatch):
        """With use_real_data=True, load_data fills myDF from the store (no network)
        and preserves the required named columns."""
        # Guard against any direct or read-through network access.
        monkeypatch.setattr("yfinance.download", _boom_download)
        # Keep construction free of log-file side effects.
        monkeypatch.setattr("vpa.app_runner.DebugLog", _NullLogger)

        warm = _make_ohlcv_dataframe(300)
        repo = _FakeRepo(warm)
        # Patch the repository seam used inside MarketAnalyzer.load_data.
        monkeypatch.setattr("vpa.app_runner.MarketDataRepository", lambda *a, **k: repo)

        from vpa.app_runner import MarketAnalyzer

        analyzer = MarketAnalyzer(
            config_path=CONFIG_PATH,
            ticker_symbol=TICKER,
            log_level="ERROR",
        )

        df = analyzer.get_dataframe()

        # Data came from the store, for the right ticker/interval.
        assert repo.calls, "load_data must read through the repository"
        assert repo.calls[0][0] == TICKER
        assert repo.calls[0][1] == "1d"

        # The required named columns survive the migration.
        for col in ("Date", "Open", "High", "Low", "Close", "Volume"):
            assert col in df.columns, f"required column '{col}' missing after load_data"

        assert len(df) == len(warm)


# ---------------------------------------------------------------------------
# Requirement 5.3 - the all-shares scan sources bars through the analyzer/store
# ---------------------------------------------------------------------------


class TestAllSharesScanSourcesFromStore:
    """Req 5.3: run_scan sources each ticker's bars via the analyzer/store, not the
    network. Uses the analyzer_factory seam to inject a stub analyzer wired to a fake
    store so the scan stays lightweight and offline."""

    def test_run_scan_completes_offline_via_analyzer_store(self, monkeypatch):
        monkeypatch.setattr("yfinance.download", _boom_download)

        warm = _make_ohlcv_dataframe(120)
        repo = _FakeRepo(warm)

        # A stub analyzer standing in for MarketAnalyzer: it sources its bars from the
        # fake store (proving the scan reads via the analyzer/store seam) and returns
        # deterministic scan outputs so run_scan can complete without the heavy VPA run.
        class _StubAnalyzer:
            def __init__(self, config_path, ticker_symbol, log_level="INFO"):
                self.ticker_symbol = ticker_symbol
                self._df = repo.load_ohlcv(ticker_symbol, "1d", None, None)

            def process_data(self):
                return 1.0

            def get_last_signals(self):
                return {"single_candle_signals": ["Up Bar"]}

            def get_dataframe(self):
                return self._df

        def _analyzer_factory(config_path, ticker_symbol, log_level="INFO"):
            return _StubAnalyzer(config_path, ticker_symbol, log_level)

        def _opportunity_evaluator(**kwargs):
            return None

        tickers = [("SPY", "SPY"), ("AAPL", "AAPL")]

        report = run_scan(
            tickers,
            config_path=CONFIG_PATH,
            analyzer_factory=_analyzer_factory,
            opportunity_evaluator=_opportunity_evaluator,
        )

        # The scan produced one successful result per ticker...
        assert len(report.results) == 2
        assert all(r.status == "success" for r in report.results)
        # ...and every ticker's bars were sourced through the store, not the network.
        sourced = [call[0] for call in repo.calls]
        assert sourced == ["SPY", "AAPL"]
