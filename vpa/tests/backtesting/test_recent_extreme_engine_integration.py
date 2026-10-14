"""Engine integration tests for RecentExtremeExitStrategy (SP-354 task 8).

These tests drive the recent-extreme strategy end-to-end through
``BacktestEngine().run(...)`` -- never by calling ``resolve_exit`` directly --
so they exercise the real engine wiring:

- Task 8.1 (Req 6.4): a recent-extreme ``ExitResult`` carrying a ``SkipReason``
  flows through the engine's existing non-``None``-reason skip path and is
  recorded as a ``SkippedSignal`` in ``BacktestResult.skipped``. Covers both
  new reasons: ``UNAVAILABLE_RECENT_EXTREME`` and ``DEGENERATE_RISK_DISTANCE``.
- Task 8.2 (Req 7.3; design Property 10): a resolved recent-extreme trade has
  its ``stop_loss``, ``profit_target``, and ``exit_reason`` threaded onto the
  ``TradeRecord`` by ``_resolve_trade``. Expected stop/target are hand-computed
  from the fixture.

The engine matches signals to the Price_Series by date-string equality and
indexes positionally with ``entry_index = signal_index + 1``. The strategy's
lookback window is ``price_series[entry_index - lookback : entry_index]``, so a
signal on date index ``t`` reads the ``lookback`` bars ending at index ``t``.

Per the task note, the engine computes ``return_pct`` direction-agnostically;
these tests assert only the stop/target/exit_reason fields and the skip
records, not P&L sign.

Code under test:
- ``vpa/backtesting/engine.py`` (``BacktestEngine.run`` / ``_resolve_trade``)
- ``vpa/backtesting/config.py`` (``BacktestConfig``)
- ``vpa/backtesting/exit_strategy.py`` (``RecentExtremeExitStrategy``)
"""

import datetime as dt

from vpa.backtesting.config import BacktestConfig
from vpa.backtesting.engine import BacktestEngine
from vpa.backtesting.exit_strategy import RecentExtremeExitStrategy
from vpa.backtesting.models import ExitReason, PricePoint, SignalEntry, SkipReason
from vpa.ml_validation.signal_analysis import SIGNAL_DIRECTIONS, SignalType

_BASE_DATE = dt.date(2020, 1, 1)


def _iso(index: int) -> str:
    """Unique ascending ISO date string for positional ``index``."""
    return (_BASE_DATE + dt.timedelta(days=index)).isoformat()


def _bar(index: int, open_: float, high: float, low: float, close: float) -> PricePoint:
    """Build a PricePoint on the ``index``-th ascending ISO date."""
    return PricePoint(date=_iso(index), open=open_, high=high, low=low, close=close)


def _signal(date: str, signal_type: SignalType) -> SignalEntry:
    """Build a SignalEntry using SIGNAL_DIRECTIONS for the direction."""
    return SignalEntry(
        date=date,
        signal_type=signal_type,
        direction=SIGNAL_DIRECTIONS[signal_type],
    )


# A long signal type (SIGNAL_DIRECTIONS -> UP) used throughout. The strategy's
# own ``direction`` field governs geometry; the signal direction only matters
# for downstream P&L, which these tests do not assert.
_LONG_SIGNAL = SignalType.STRONG_BULLISH


# ---------------------------------------------------------------------------
# Task 8.1: skip recording for the two new SkipReasons (Req 6.4)
# ---------------------------------------------------------------------------


def test_unavailable_recent_extreme_is_recorded_as_skip() -> None:
    """A signal so early that entry_index - lookback < 0 is skipped.

    Validates: Requirements 6.4.

    Signal on date index 0 -> entry_index = 1. With lookback = 5 the window
    start is 1 - 5 = -4 < 0, so the strategy returns an ExitResult carrying
    SkipReason.UNAVAILABLE_RECENT_EXTREME. The entry index (1) and entry price
    (valid) both pass the engine's pre-exit checks, so the skip originates
    purely from the strategy's reason flowing through _resolve_trade.
    """
    # Six bars, gently rising; OHLC values are irrelevant because the strategy
    # bails before reading the window (start < 0).
    price_series = [_bar(i, open_=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.0 + i) for i in range(6)]
    signal = _signal(_iso(0), _LONG_SIGNAL)  # entry_index = 1, 1 - 5 < 0
    config = BacktestConfig(
        hold_period=2,
        exit_strategy=RecentExtremeExitStrategy(lookback=5, reward_risk=2.0),
    )

    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    matching = [s for s in result.skipped if s.reason == SkipReason.UNAVAILABLE_RECENT_EXTREME]
    assert len(matching) == 1
    assert matching[0].signal_type == _LONG_SIGNAL
    assert matching[0].signal_date == _iso(0)


def test_degenerate_risk_distance_is_recorded_as_skip() -> None:
    """A long whose recent extreme sits on the non-adverse side is skipped.

    Validates: Requirements 6.4.

    For a long (direction UP, buffer 0) the stop is the lowest ``low`` of the
    prior window. The signal lands on date index 2 -> entry_index = 3, and the
    entry close is 100.0. The lookback = 2 window covers indices 1 and 2, whose
    lows (105.0, 106.0) are both >= the entry close, so stop = 105.0 >=
    entry_price = 100.0. That is a non-adverse stop, so the strategy returns
    SkipReason.DEGENERATE_RISK_DISTANCE, which the engine records.
    """
    price_series = [
        _bar(0, open_=100.0, high=103.0, low=98.0, close=101.0),  # before the window
        _bar(1, open_=106.0, high=108.0, low=105.0, close=107.0),  # window idx 1, low 105
        _bar(2, open_=107.0, high=109.0, low=106.0, close=100.0),  # entry bar, close 100
        _bar(3, open_=100.0, high=102.0, low=98.0, close=100.0),  # entry_index 3 (close 100)
        _bar(4, open_=100.0, high=102.0, low=98.0, close=100.0),
        _bar(5, open_=100.0, high=102.0, low=98.0, close=100.0),
    ]
    signal = _signal(_iso(2), _LONG_SIGNAL)  # entry_index = 3
    config = BacktestConfig(
        hold_period=2,
        exit_strategy=RecentExtremeExitStrategy(lookback=2, reward_risk=2.0),
    )

    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    matching = [s for s in result.skipped if s.reason == SkipReason.DEGENERATE_RISK_DISTANCE]
    assert len(matching) == 1
    assert matching[0].signal_type == _LONG_SIGNAL
    assert matching[0].signal_date == _iso(2)


# ---------------------------------------------------------------------------
# Task 8.2: field population on resolved recent-extreme trades (Req 7.3)
# ---------------------------------------------------------------------------


# Feature: sp-354-recent-extreme-stop-target, Property 10:
# Recent-extreme per-trade output carries stop/target/reason.
def test_resolved_trade_carries_stop_target_and_stop_reason() -> None:
    """A stop-breach trade carries the hand-computed stop/target and STOP reason.

    Validates: Requirements 7.3; Design: Correctness Property 10.

    Fixture (long, buffer 0, lookback 2, reward_risk 2):
      - signal on date index 2 -> entry_index = 3, entry close = 100.0.
      - lookback window = indices 1, 2; lows 97.0 and 98.0 -> extreme = 97.0,
        so stop = 97.0 (buffer 0).
      - risk = |100.0 - 97.0| = 3.0; target = 100.0 + 3.0 * 2 = 106.0.
      - forward scan from index 4: bar 4 has low 94.0 <= stop 97.0 -> STOP
        breach. open 96.0 <= stop 97.0 (gapped through) -> exit_price = 96.0.
    """
    price_series = [
        _bar(0, open_=99.0, high=101.0, low=98.0, close=99.0),  # before the window
        _bar(1, open_=99.0, high=102.0, low=97.0, close=100.0),  # window idx 1, low 97
        _bar(2, open_=100.0, high=103.0, low=98.0, close=100.0),  # entry bar, close 100
        _bar(3, open_=100.0, high=102.0, low=99.0, close=100.0),  # entry_index 3 (close 100)
        _bar(4, open_=96.0, high=101.0, low=94.0, close=97.0),  # stop breach, gap open
        _bar(5, open_=97.0, high=100.0, low=95.0, close=98.0),
    ]
    signal = _signal(_iso(2), _LONG_SIGNAL)  # entry_index = 3
    config = BacktestConfig(
        hold_period=3,
        exit_strategy=RecentExtremeExitStrategy(lookback=2, reward_risk=2.0),
    )

    result = BacktestEngine().run([signal], price_series, config)

    assert len(result.trades) == 1
    trade = result.trades[0]
    # Hand-computed geometry.
    assert trade.stop_loss == 97.0
    assert trade.profit_target == 106.0
    assert trade.exit_reason == ExitReason.STOP
    # Exit landed on index 4 at the gapped-through open.
    assert trade.exit_date == _iso(4)
    assert trade.exit_price == 96.0


# Feature: sp-354-recent-extreme-stop-target, Property 10:
# Recent-extreme per-trade output carries stop/target/reason.
def test_resolved_trade_carries_stop_target_and_target_reason() -> None:
    """A target-breach trade carries the hand-computed stop/target and TARGET reason.

    Validates: Requirements 7.3; Design: Correctness Property 10.

    Same geometry as the stop-breach fixture (stop 97.0, target 106.0) but the
    forward bars never touch the stop; the first bar whose high reaches the
    target resolves as a TARGET breach. Its open (105.0) is below the target
    (106.0) so the exit prices at the target itself, not the open.
    """
    price_series = [
        _bar(0, open_=99.0, high=101.0, low=98.0, close=99.0),  # before the window
        _bar(1, open_=99.0, high=102.0, low=97.0, close=100.0),  # window idx 1, low 97
        _bar(2, open_=100.0, high=103.0, low=98.0, close=100.0),  # entry bar, close 100
        _bar(3, open_=100.0, high=102.0, low=99.0, close=100.0),  # entry_index 3 (close 100)
        _bar(4, open_=105.0, high=107.0, low=104.0, close=106.0),  # target breach, open below target
        _bar(5, open_=106.0, high=108.0, low=105.0, close=107.0),
    ]
    signal = _signal(_iso(2), _LONG_SIGNAL)  # entry_index = 3
    config = BacktestConfig(
        hold_period=3,
        exit_strategy=RecentExtremeExitStrategy(lookback=2, reward_risk=2.0),
    )

    result = BacktestEngine().run([signal], price_series, config)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.stop_loss == 97.0
    assert trade.profit_target == 106.0
    assert trade.exit_reason == ExitReason.TARGET
    # Exit landed on index 4 at the target (open 105 < target 106, no gap).
    assert trade.exit_date == _iso(4)
    assert trade.exit_price == 106.0


# Feature: sp-354-recent-extreme-stop-target, Property 10:
# Recent-extreme per-trade output carries stop/target/reason.
def test_resolved_trade_carries_stop_target_and_fixed_hold_reason() -> None:
    """A no-breach trade falls through to fixed-hold, still carrying stop/target.

    Validates: Requirements 7.3; Design: Correctness Property 10.

    Same geometry (stop 97.0, target 106.0). The forward bars stay strictly
    inside the (stop, target) band, so neither level is breached within the
    hold window; resolution delegates to the fixed-hold fallback. The resulting
    TradeRecord still carries the computed stop/target and exit_reason
    FIXED_HOLD, and exits at close[entry_index + hold_period].
    """
    price_series = [
        _bar(0, open_=99.0, high=101.0, low=98.0, close=99.0),  # before the window
        _bar(1, open_=99.0, high=102.0, low=97.0, close=100.0),  # window idx 1, low 97
        _bar(2, open_=100.0, high=103.0, low=98.0, close=100.0),  # entry bar, close 100
        _bar(3, open_=100.0, high=102.0, low=99.0, close=100.0),  # entry_index 3 (close 100)
        _bar(4, open_=100.0, high=104.0, low=99.0, close=101.0),  # inside band
        _bar(5, open_=101.0, high=105.0, low=99.5, close=102.0),  # fixed-hold exit (close 102)
    ]
    signal = _signal(_iso(2), _LONG_SIGNAL)  # entry_index = 3
    config = BacktestConfig(
        hold_period=2,  # exit_index = 3 + 2 = 5
        exit_strategy=RecentExtremeExitStrategy(lookback=2, reward_risk=2.0),
    )

    result = BacktestEngine().run([signal], price_series, config)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.stop_loss == 97.0
    assert trade.profit_target == 106.0
    assert trade.exit_reason == ExitReason.FIXED_HOLD
    # Fixed-hold exit at index 5 close.
    assert trade.exit_date == _iso(5)
    assert trade.exit_price == 102.0
