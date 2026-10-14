"""Regression tests for backward-compatible engine output (SP-354 task 2.1).

SP-354 threads three optional extras (``stop_loss``, ``profit_target``,
``exit_reason``) off the resolved ``ExitResult`` onto each ``TradeRecord`` in
``BacktestEngine._resolve_trade``. The thread-through is purely additive: a
strategy that leaves the ``ExitResult`` extras at ``None`` (the fixed-hold and
percentage-stop strategies) must yield a ``TradeRecord`` whose three new fields
are ``None`` and whose original six fields are exactly what they were before
SP-354 for the same inputs.

These are example/regression tests (not Hypothesis properties), but they
exercise design **Property 11: Backward-compatible output for non-supplying
strategies**.

Code under test:
- ``vpa/backtesting/engine.py`` (``BacktestEngine.run`` / ``_resolve_trade``)
- ``vpa/backtesting/config.py`` (``BacktestConfig``)
- ``vpa/backtesting/exit_strategy.py`` (``FixedHoldExitStrategy``,
  ``StopLossExitStrategy``)
"""

import datetime as dt

from vpa.backtesting.config import BacktestConfig
from vpa.backtesting.engine import BacktestEngine
from vpa.backtesting.exit_strategy import FixedHoldExitStrategy, StopLossExitStrategy
from vpa.backtesting.models import PricePoint, SignalEntry
from vpa.ml_validation.signal_analysis import SIGNAL_DIRECTIONS, SignalType

_BASE_DATE = dt.date(2020, 1, 1)


def _iso(index: int) -> str:
    """Unique ascending ISO date string for positional ``index``."""
    return (_BASE_DATE + dt.timedelta(days=index)).isoformat()


def _make_price_series(closes: list[float]) -> list[PricePoint]:
    """Build a deterministic Price_Series from a list of close prices.

    ``high``/``low`` straddle the close by a fixed +/-1.0 so no incidental
    percentage-stop breach happens unless we engineer one explicitly.
    """
    return [
        PricePoint(
            date=_iso(i),
            open=close,
            high=close + 1.0,
            low=max(close - 1.0, 0.01),
            close=close,
        )
        for i, close in enumerate(closes)
    ]


def _signal(date: str, signal_type: SignalType) -> SignalEntry:
    """Build a SignalEntry using SIGNAL_DIRECTIONS for the direction."""
    return SignalEntry(
        date=date,
        signal_type=signal_type,
        direction=SIGNAL_DIRECTIONS[signal_type],
    )


# A deterministic, hand-chosen upward-drifting series. Chosen so the two
# signals both produce in-bounds trades under hold_period=2, and so no bar
# dips far enough to trigger the -50% percentage stop used below (the series
# only ever rises, and low is close-1.0).
_CLOSES = [100.0, 102.0, 101.0, 105.0, 110.0, 108.0, 112.0, 115.0]
_HOLD_PERIOD = 2
_ROUND_TRIP_COST = 0.001

# Two signals landing on existing Price_Series dates. Entry_Index = t+1.
# UP signal at index 0 -> entry 1, exit 3; UP signal at index 3 -> entry 4,
# exit 6. Both are long so SIGNAL_DIRECTIONS resolves them consistently.
_SIGNAL_TYPE = SignalType.ACCUMULATION
_SIGNAL_INDICES = (0, 3)


def _run(exit_strategy) -> list:
    """Run the engine over the shared fixture with the given exit strategy."""
    price_series = _make_price_series(_CLOSES)
    signal_log = [_signal(_iso(i), _SIGNAL_TYPE) for i in _SIGNAL_INDICES]
    config = BacktestConfig(
        hold_period=_HOLD_PERIOD,
        round_trip_cost=_ROUND_TRIP_COST,
        exit_strategy=exit_strategy,
    )
    result = BacktestEngine().run(signal_log, price_series, config)
    return result.trades


def _expected_record_fields() -> list[dict]:
    """Hand-computed pre-SP-354 TradeRecord field values for the fixture.

    Entry_Index = signal_index + 1; Exit_Index = Entry_Index + hold_period.
    entry_price = close[entry_index]; exit_price = close[exit_index] (fixed
    hold); return_pct = exit_price/entry_price - 1 - round_trip_cost.
    """
    expected = []
    for sig_index in _SIGNAL_INDICES:
        entry_index = sig_index + 1
        exit_index = entry_index + _HOLD_PERIOD
        entry_price = _CLOSES[entry_index]
        exit_price = _CLOSES[exit_index]
        return_pct = exit_price / entry_price - 1 - _ROUND_TRIP_COST
        expected.append(
            {
                "entry_date": _iso(entry_index),
                "exit_date": _iso(exit_index),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": return_pct,
                "signal_type": _SIGNAL_TYPE,
            }
        )
    return expected


# Feature: sp-354-recent-extreme-stop-target, Property 11:
# Backward-compatible output for non-supplying strategies.
def test_fixed_hold_leaves_extras_none() -> None:
    """FixedHoldExitStrategy trades carry None for all three SP-354 extras.

    Validates: Requirements 7.4, 8.3; Design: Correctness Property 11.
    """
    trades = _run(FixedHoldExitStrategy())

    assert len(trades) == len(_SIGNAL_INDICES)
    for trade in trades:
        assert trade.stop_loss is None
        assert trade.profit_target is None
        assert trade.exit_reason is None


# Feature: sp-354-recent-extreme-stop-target, Property 11:
# Backward-compatible output for non-supplying strategies.
def test_percentage_stop_leaves_extras_none() -> None:
    """StopLossExitStrategy trades carry None for all three SP-354 extras.

    Validates: Requirements 7.4, 8.3; Design: Correctness Property 11.

    A -50% stop is far below the gently rising series, so every trade falls
    through to the fixed-hold fallback -- the percentage-stop strategy still
    supplies no stop/target/reason on its ExitResult.
    """
    trades = _run(StopLossExitStrategy(threshold=-0.5))

    assert len(trades) == len(_SIGNAL_INDICES)
    for trade in trades:
        assert trade.stop_loss is None
        assert trade.profit_target is None
        assert trade.exit_reason is None


# Feature: sp-354-recent-extreme-stop-target, Property 11:
# Backward-compatible output for non-supplying strategies.
def test_thread_through_does_not_disturb_existing_fields() -> None:
    """The original six TradeRecord fields match pre-SP-354 hand-computed values.

    Validates: Requirements 7.4, 8.3; Design: Correctness Property 11.

    Both the fixed-hold and the (never-breached) percentage-stop runs resolve
    every trade via the fixed-hold path, so their records must equal the
    hand-computed baseline exactly. This confirms the additive thread-through
    did not disturb entry_date, exit_date, entry_price, exit_price, return_pct,
    or signal_type.
    """
    expected = _expected_record_fields()

    for exit_strategy in (FixedHoldExitStrategy(), StopLossExitStrategy(threshold=-0.5)):
        trades = _run(exit_strategy)
        assert len(trades) == len(expected)
        # Trades are ordered by entry_date ascending, matching _SIGNAL_INDICES.
        for trade, want in zip(trades, expected, strict=True):
            assert trade.entry_date == want["entry_date"]
            assert trade.exit_date == want["exit_date"]
            assert trade.entry_price == want["entry_price"]
            assert trade.exit_price == want["exit_price"]
            assert trade.return_pct == want["return_pct"]
            assert trade.signal_type == want["signal_type"]
