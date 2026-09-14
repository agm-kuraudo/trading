"""Signal-threshold and wiring tests for ``vpa.app_forex`` (task 9.2).

``vpa.app_forex.main()`` orchestrates the browserless forex pipeline: it calls
:func:`vpa.forex_data.get_daily_dataframe` for the daily GBPUSD history, builds a
:class:`vpa.app_runner.MarketAnalyzer`, runs ``process_data()`` (which yields a
``trade_signal``), plots via ``graph_intervals()``, and finally logs a
recommendation based on the signal thresholds:

- ``trade_signal >= 15``  -> ``"BUY Recommendation"``
- ``trade_signal <= -15`` -> ``"SELL Recommendation"``
- otherwise (``-15 < signal < 15``) -> ``"DO NOT TRADE"``

These tests exercise ``main()`` directly (not via ``__main__``) with NO network
and NO real analysis. Because ``app_forex`` binds ``get_daily_dataframe`` and
``MarketAnalyzer`` into its own module namespace via ``from ... import ...``, the
seams are patched at ``vpa.app_forex.get_daily_dataframe`` and
``vpa.app_forex.MarketAnalyzer``:

- ``get_daily_dataframe`` is replaced with a stub returning a small synthetic
  DataFrame (content is irrelevant since the analyzer is also stubbed).
- ``MarketAnalyzer`` is replaced with a stub whose instance records its
  construction kwargs, returns a configurable ``trade_signal`` from
  ``process_data()``, records that ``graph_intervals()`` ran, and appends every
  ``log(msg)`` to a list.

Covered:

- Threshold BUY: signal 15 (boundary) and 30 -> ``"BUY Recommendation"``.
- Threshold SELL: signal -15 (boundary) and -30 -> ``"SELL Recommendation"``.
- Threshold DO NOT TRADE: signal 0 and the just-inside boundaries 14 / -14 ->
  ``"DO NOT TRADE"``.
- Wiring: ``MarketAnalyzer`` is constructed with the exact expected kwargs
  (``fixed_df`` == the stubbed retriever's DataFrame, ``ticker_symbol="GBPUSD"``,
  ``log_prefix="GBPUSD"``, ``config_path="config/config.json"``,
  ``log_level="INFO"``), and ``process_data()``/``graph_intervals()`` are each
  called exactly once.

Requirements: 4.3, 4.4, 4.5, 4.6, 4.7.
"""

import pandas as pd
import pytest

from vpa import app_forex

# The Analysis_DataFrame column layout produced by the retriever/aggregator.
_DAILY_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]


def _synthetic_df() -> pd.DataFrame:
    """Return a small synthetic daily DataFrame.

    Content is irrelevant to these tests because ``MarketAnalyzer`` is stubbed;
    only its identity (that the exact object flows into ``fixed_df``) matters.
    """
    return pd.DataFrame(
        [
            {"Date": pd.Timestamp("2024-01-01"), "Open": 1.30, "High": 1.31,
             "Low": 1.29, "Close": 1.305, "Volume": 100},
            {"Date": pd.Timestamp("2024-01-02"), "Open": 1.305, "High": 1.32,
             "Low": 1.30, "Close": 1.315, "Volume": 120},
            {"Date": pd.Timestamp("2024-01-03"), "Open": 1.315, "High": 1.33,
             "Low": 1.31, "Close": 1.325, "Volume": 140},
        ],
        columns=_DAILY_COLUMNS,
    )


class _StubAnalyzer:
    """Stand-in for :class:`MarketAnalyzer` that records interactions.

    Each instance captures the kwargs it was constructed with, returns a
    class-level ``_trade_signal`` from ``process_data()``, records that
    ``graph_intervals()`` was called, and appends every ``log`` message to
    ``logged``. The instance is stashed on the class as ``last_instance`` so
    tests can assert on the wiring after calling ``main()``.
    """

    # Configured per-test before calling main().
    _trade_signal = 0
    last_instance = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.process_data_calls = 0
        self.graph_intervals_calls = 0
        self.logged: list[str] = []
        type(self).last_instance = self

    def process_data(self):
        self.process_data_calls += 1
        return type(self)._trade_signal

    def graph_intervals(self):
        self.graph_intervals_calls += 1

    def log(self, msg):
        self.logged.append(msg)


@pytest.fixture
def wired(monkeypatch):
    """Patch the app_forex seams and return the synthetic df + analyzer stub.

    Replaces ``vpa.app_forex.get_daily_dataframe`` with a stub returning a fixed
    synthetic DataFrame (no network) and ``vpa.app_forex.MarketAnalyzer`` with
    :class:`_StubAnalyzer`. Returns ``(df, _StubAnalyzer)`` so tests can set the
    trade signal and inspect the constructed instance.
    """
    df = _synthetic_df()
    monkeypatch.setattr(app_forex, "get_daily_dataframe", lambda symbol="GBPUSD": df)
    monkeypatch.setattr(app_forex, "MarketAnalyzer", _StubAnalyzer)
    # Reset per-test class state.
    _StubAnalyzer.last_instance = None
    _StubAnalyzer._trade_signal = 0
    return df, _StubAnalyzer


# ---------------------------------------------------------------------------
# Threshold: BUY (signal >= 15)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("signal", [15, 30])
def test_buy_threshold_logs_buy_recommendation(wired, signal):
    """A signal at/above the BUY boundary logs ``"BUY Recommendation"`` (Req 4.4)."""
    _df, analyzer_cls = wired
    analyzer_cls._trade_signal = signal

    app_forex.main()

    assert analyzer_cls.last_instance.logged == ["BUY Recommendation"]


# ---------------------------------------------------------------------------
# Threshold: SELL (signal <= -15)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("signal", [-15, -30])
def test_sell_threshold_logs_sell_recommendation(wired, signal):
    """A signal at/below the SELL boundary logs ``"SELL Recommendation"`` (Req 4.5)."""
    _df, analyzer_cls = wired
    analyzer_cls._trade_signal = signal

    app_forex.main()

    assert analyzer_cls.last_instance.logged == ["SELL Recommendation"]


# ---------------------------------------------------------------------------
# Threshold: DO NOT TRADE (-15 < signal < 15)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("signal", [0, 14, -14])
def test_do_not_trade_threshold_logs_do_not_trade(wired, signal):
    """Signals strictly inside the band log ``"DO NOT TRADE"`` (Req 4.6).

    Includes the just-inside boundary values 14 and -14 to pin the strict
    ``>= 15`` / ``<= -15`` comparisons.
    """
    _df, analyzer_cls = wired
    analyzer_cls._trade_signal = signal

    app_forex.main()

    assert analyzer_cls.last_instance.logged == ["DO NOT TRADE"]


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_market_analyzer_is_wired_with_expected_arguments(wired):
    """``MarketAnalyzer`` is constructed and driven exactly as the entry point specifies.

    Asserts the retriever's DataFrame flows into ``fixed_df`` unchanged, the
    GBPUSD ticker/prefix and config/log-level kwargs are passed through, and
    ``process_data()`` and ``graph_intervals()`` are each called once
    (Requirements 4.3, 4.7).
    """
    df, analyzer_cls = wired
    analyzer_cls._trade_signal = 0

    app_forex.main()

    instance = analyzer_cls.last_instance
    assert instance is not None

    # fixed_df is the exact object returned by the stubbed retriever.
    assert instance.kwargs["fixed_df"] is df
    assert instance.kwargs["ticker_symbol"] == "GBPUSD"
    assert instance.kwargs["log_prefix"] == "GBPUSD"
    assert instance.kwargs["config_path"] == "config/config.json"
    assert instance.kwargs["log_level"] == "INFO"

    assert instance.process_data_calls == 1
    assert instance.graph_intervals_calls == 1
