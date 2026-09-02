"""Tests for the core VPA backtesting engine (SP-317).

Covers Correctness Properties 1, 3-11 via Hypothesis property tests, the
engine edge-case unit tests (task 11.1), and the hand-computed integration
test (task 11.2).

Code under test:
- ``vpa/backtesting/engine.py`` (``BacktestEngine.run``, ``signal_confidence_rank``)
- ``vpa/backtesting/config.py`` (``BacktestConfig``)
- ``vpa/backtesting/models.py`` (records, enums)

The engine matches signals to the Price_Series by date-string equality and
indexes the series positionally (Entry_Index = t+1, Exit_Index = t+1+N). The
helpers below build a Price_Series with sequential, unique, ascending ISO
dates so date-sort order matches positional order, and derive signal dates by
picking existing Price_Series dates.
"""

import copy
import datetime as dt
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.backtesting.config import BacktestConfig
from vpa.backtesting.engine import BacktestEngine, signal_confidence_rank
from vpa.backtesting.models import (
    PositionMode,
    PricePoint,
    SignalEntry,
    SkipReason,
)
from vpa.ml_validation.signal_analysis import SIGNAL_DIRECTIONS, SignalType

_BASE_DATE = dt.date(2020, 1, 1)


def _iso(index: int) -> str:
    """Return a unique ascending ISO date string for positional ``index``.

    Sequential calendar days keep the strings valid ISO YYYY-MM-DD and sorted
    identically to their positional index.
    """
    return (_BASE_DATE + dt.timedelta(days=index)).isoformat()


def _make_price_series(closes: list[float]) -> list[PricePoint]:
    """Build a Price_Series from a list of close prices.

    Dates are sequential ascending ISO strings. open/high/low are derived from
    close but are unused by the fixed-hold strategy under test.
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


def _index_of_date(price_series: list[PricePoint], date: str) -> int:
    """Return the positional index of ``date`` in a date-sorted Price_Series."""
    sorted_prices = sorted(price_series, key=lambda p: p.date)
    for i, point in enumerate(sorted_prices):
        if point.date == date:
            return i
    raise AssertionError(f"date {date} not in price series")


# A modest set of SignalType values for cluster/tie-break generation.
_SIGNAL_TYPES = list(SignalType)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Positive, finite close prices well away from zero to keep entry/exit prices
# valid and return math numerically stable.
_close_strategy = st.floats(
    min_value=1.0,
    max_value=10_000.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)


@st.composite
def _single_signal_case(draw: st.DrawFn) -> tuple[list[PricePoint], SignalEntry, int, int]:
    """Random Price_Series + a single signal whose entry and exit are in bounds.

    Returns (price_series, signal, signal_index t, hold_period N) such that
    t+1 and t+1+N are both valid indices, so exactly one trade is produced.
    """
    length = draw(st.integers(min_value=3, max_value=40))
    closes = draw(st.lists(_close_strategy, min_size=length, max_size=length))
    price_series = _make_price_series(closes)
    hold_period = draw(st.integers(min_value=1, max_value=length - 2))
    # Need t+1+N <= length-1  =>  t <= length-2-N.
    max_t = length - 2 - hold_period
    signal_index = draw(st.integers(min_value=0, max_value=max_t))
    signal_type = draw(st.sampled_from(_SIGNAL_TYPES))
    signal = _signal(_iso(signal_index), signal_type)
    return price_series, signal, signal_index, hold_period


# Feature: vpa-backtesting-engine, Property 1: Next-day-close entry pricing
@settings(max_examples=100)
@given(case=_single_signal_case())
def test_property_1_next_day_close_entry_pricing(
    case: tuple[list[PricePoint], SignalEntry, int, int],
) -> None:
    """entry_price == close[t+1] and entry_date == date[t+1].

    Validates: Requirements 3.1, 3.3; Design: Correctness Property 1.
    """
    price_series, signal, t, hold_period = case
    config = BacktestConfig(hold_period=hold_period)

    result = BacktestEngine().run([signal], price_series, config)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_price == price_series[t + 1].close
    assert trade.entry_date == price_series[t + 1].date


# Feature: vpa-backtesting-engine, Property 3: Gross and net return formulas
@settings(max_examples=100)
@given(
    case=_single_signal_case(),
    cost=st.floats(min_value=0.0, max_value=0.05, allow_nan=False, allow_infinity=False),
)
def test_property_3_gross_and_net_return_formulas(
    case: tuple[list[PricePoint], SignalEntry, int, int],
    cost: float,
) -> None:
    """gross == exit/entry - 1 and return_pct == gross - cost within 1e-9.

    Validates: Requirements 3.6, 4.2, 4.3; Design: Correctness Property 3.
    """
    price_series, signal, t, hold_period = case
    config = BacktestConfig(hold_period=hold_period, round_trip_cost=cost)

    result = BacktestEngine().run([signal], price_series, config)

    assert len(result.trades) == 1
    trade = result.trades[0]
    expected_gross = trade.exit_price / trade.entry_price - 1
    assert math.isclose(trade.return_pct, expected_gross - cost, abs_tol=1e-9)


# Feature: vpa-backtesting-engine, Property 4: Round-trip cost applied exactly once
@settings(max_examples=100)
@given(
    case=_single_signal_case(),
    cost=st.floats(min_value=0.0, max_value=0.05, allow_nan=False, allow_infinity=False),
)
def test_property_4_round_trip_cost_applied_once(
    case: tuple[list[PricePoint], SignalEntry, int, int],
    cost: float,
) -> None:
    """return_pct differs from gross by exactly cost; equals gross when cost is 0.

    Validates: Requirements 4.4, 4.5; Design: Correctness Property 4.
    """
    price_series, signal, t, hold_period = case
    config = BacktestConfig(hold_period=hold_period, round_trip_cost=cost)

    result = BacktestEngine().run([signal], price_series, config)

    assert len(result.trades) == 1
    trade = result.trades[0]
    gross = trade.exit_price / trade.entry_price - 1
    assert math.isclose(gross - trade.return_pct, cost, abs_tol=1e-9)
    if cost == 0.0:
        assert trade.return_pct == gross


@st.composite
def _multi_signal_case(draw: st.DrawFn) -> tuple[list[PricePoint], list[SignalEntry], int]:
    """Random Price_Series + several signals on existing dates + a hold period.

    Signals reference existing Price_Series dates (so none is MISSING) but may
    share dates (creating same-Entry_Index clusters) and may fall near the end
    of the series (creating some skips). Returns (price_series, signals, N).
    """
    length = draw(st.integers(min_value=4, max_value=40))
    closes = draw(st.lists(_close_strategy, min_size=length, max_size=length))
    price_series = _make_price_series(closes)
    hold_period = draw(st.integers(min_value=1, max_value=max(1, length // 3)))

    num_signals = draw(st.integers(min_value=1, max_value=8))
    signals: list[SignalEntry] = []
    for _ in range(num_signals):
        idx = draw(st.integers(min_value=0, max_value=length - 1))
        sig_type = draw(st.sampled_from(_SIGNAL_TYPES))
        signals.append(_signal(_iso(idx), sig_type))
    return price_series, signals, hold_period


# Feature: vpa-backtesting-engine, Property 5: NO_OVERLAP produces no overlapping trades
@settings(max_examples=100)
@given(case=_multi_signal_case())
def test_property_5_no_overlap_no_overlapping_trades(
    case: tuple[list[PricePoint], list[SignalEntry], int],
) -> None:
    """For NO_OVERLAP trades sorted by entry, each entry_index > prev exit_index.

    Validates: Requirements 5.2, 5.3; Design: Correctness Property 5.
    """
    price_series, signals, hold_period = case
    config = BacktestConfig(hold_period=hold_period, position_mode=PositionMode.NO_OVERLAP)

    result = BacktestEngine().run(signals, price_series, config)

    # Derive positional indices via the trade dates and check the invariant.
    trades = sorted(result.trades, key=lambda t: t.entry_date)
    prev_exit_index: int | None = None
    for trade in trades:
        entry_index = _index_of_date(price_series, trade.entry_date)
        exit_index = _index_of_date(price_series, trade.exit_date)
        if prev_exit_index is not None:
            assert entry_index > prev_exit_index
        prev_exit_index = exit_index


# Feature: vpa-backtesting-engine, Property 6: NO_OVERLAP same-Entry_Index tie-break is highest confidence and deterministic  # noqa: E501
@settings(max_examples=100)
@given(
    length=st.integers(min_value=4, max_value=30),
    seed=st.data(),
)
def test_property_6_no_overlap_tie_break_highest_confidence(
    length: int,
    seed: st.DataObject,
) -> None:
    """Same-date cluster opens the best-confidence trade; losers skipped; stable.

    Validates: Requirements 5.4, 5.5; Design: Correctness Property 6.
    """
    closes = seed.draw(st.lists(_close_strategy, min_size=length, max_size=length))
    price_series = _make_price_series(closes)
    hold_period = seed.draw(st.integers(min_value=1, max_value=max(1, length // 3)))

    # Build a single same-date cluster of 2+ distinct signal types on a date
    # whose entry and exit are both in bounds, with no other signals so the
    # slot is guaranteed free.
    max_t = length - 2 - hold_period
    signal_index = seed.draw(st.integers(min_value=0, max_value=max_t))
    cluster_types = seed.draw(
        st.lists(st.sampled_from(_SIGNAL_TYPES), min_size=2, max_size=len(_SIGNAL_TYPES), unique=True)
    )
    date = _iso(signal_index)
    signals = [_signal(date, sig_type) for sig_type in cluster_types]

    config = BacktestConfig(hold_period=hold_period, position_mode=PositionMode.NO_OVERLAP)
    result = BacktestEngine().run(signals, price_series, config)

    # Exactly one trade opens for this free-slot cluster.
    assert len(result.trades) == 1
    best_type = min(cluster_types, key=signal_confidence_rank)
    assert result.trades[0].signal_type == best_type

    # Every loser is skipped with OVERLAPPING_POSITION.
    losers = {t for t in cluster_types if t != best_type}
    overlapping = {
        s.signal_type for s in result.skipped if s.reason == SkipReason.OVERLAPPING_POSITION and s.signal_date == date
    }
    assert overlapping == losers

    # Selection is stable across repeated runs.
    result2 = BacktestEngine().run(signals, price_series, config)
    assert result.trades == result2.trades
    assert result.skipped == result2.skipped


# Feature: vpa-backtesting-engine, Property 7: STACKING opens a trade per eligible signal
@settings(max_examples=100)
@given(case=_multi_signal_case())
def test_property_7_stacking_one_trade_per_eligible_signal(
    case: tuple[list[PricePoint], list[SignalEntry], int],
) -> None:
    """STACKING: every eligible signal produces exactly one trade, no tie-break.

    Validates: Requirements 5.6, 5.7; Design: Correctness Property 7.
    """
    price_series, signals, hold_period = case
    config = BacktestConfig(hold_period=hold_period, position_mode=PositionMode.STACKING)
    last_index = len(price_series) - 1

    result = BacktestEngine().run(signals, price_series, config)

    # Independently count eligible signals: entry and exit both in bounds and
    # prices valid. With our generated finite positive closes all prices are
    # valid, so eligibility is purely the bounds check.
    eligible = 0
    for sig in signals:
        t = _index_of_date(price_series, sig.date)
        entry_index = t + 1
        exit_index = entry_index + hold_period
        if entry_index <= last_index and exit_index <= last_index:
            eligible += 1

    assert len(result.trades) == eligible
    # No tie-break: same-Entry_Index STACKING entries each open their own trade.
    # (Covered by the count matching every eligible signal above.)


# Feature: vpa-backtesting-engine, Property 8: Skip reasons recorded for each edge case
@settings(max_examples=100)
@given(
    length=st.integers(min_value=3, max_value=30),
    reason=st.sampled_from(
        [
            SkipReason.MISSING_PRICE_DATE,
            SkipReason.INSUFFICIENT_FUTURE_DATA_ENTRY,
            SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT,
            SkipReason.INVALID_ENTRY_PRICE,
            SkipReason.INVALID_EXIT_PRICE,
        ]
    ),
    data=st.data(),
)
def test_property_8_skip_reasons_recorded(
    length: int,
    reason: SkipReason,
    data: st.DataObject,
) -> None:
    """A single signal forced into each edge yields exactly one matching skip.

    Validates: Requirements 1.5, 7.1, 7.2, 7.4, 7.5; Design: Correctness Property 8.
    """
    closes = data.draw(st.lists(_close_strategy, min_size=length, max_size=length))
    price_series = _make_price_series(closes)
    last_index = length - 1
    sig_type = data.draw(st.sampled_from(_SIGNAL_TYPES))

    if reason == SkipReason.MISSING_PRICE_DATE:
        # A signal date not present anywhere in the Price_Series.
        hold_period = 1
        signal = _signal(_iso(length + 100), sig_type)

    elif reason == SkipReason.INSUFFICIENT_FUTURE_DATA_ENTRY:
        # Signal on the last day: t+1 is beyond the last index.
        hold_period = 1
        signal = _signal(_iso(last_index), sig_type)

    elif reason == SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT:
        # t+1 valid but t+1+N beyond the last index.
        # Pick t = last_index - 1 (entry_index = last_index, valid) with N large.
        hold_period = data.draw(st.integers(min_value=1, max_value=length))
        t = last_index - 1
        # Ensure exit is out of bounds: entry_index + N > last_index.
        # entry_index = last_index, so any N >= 1 pushes exit past the end.
        signal = _signal(_iso(t), sig_type)

    elif reason == SkipReason.INVALID_ENTRY_PRICE:
        # Zero close at the entry index.
        hold_period = 1
        t = data.draw(st.integers(min_value=0, max_value=last_index - 2))
        mutated = list(closes)
        mutated[t + 1] = 0.0
        price_series = _make_price_series(mutated)
        signal = _signal(_iso(t), sig_type)

    else:  # SkipReason.INVALID_EXIT_PRICE
        # Valid entry price, NaN close at the exit index.
        hold_period = 1
        t = data.draw(st.integers(min_value=0, max_value=last_index - 2))
        mutated = list(closes)
        mutated[t + 1 + hold_period] = math.nan
        # Guard: ensure entry price stays valid (non-zero, non-NaN).
        if not (mutated[t + 1] > 0):
            mutated[t + 1] = 5.0
        price_series = _make_price_series(mutated)
        signal = _signal(_iso(t), sig_type)

    config = BacktestConfig(hold_period=hold_period)
    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    matching = [s for s in result.skipped if s.reason == reason]
    assert len(matching) == 1
    assert matching[0].signal_type == sig_type


# Feature: vpa-backtesting-engine, Property 9: Input immutability
@settings(max_examples=100)
@given(case=_multi_signal_case())
def test_property_9_input_immutability(
    case: tuple[list[PricePoint], list[SignalEntry], int],
) -> None:
    """Running the engine leaves both inputs equal to pre-run deep copies.

    Validates: Requirements 7.6; Design: Correctness Property 9.
    """
    price_series, signals, hold_period = case
    price_copy = copy.deepcopy(price_series)
    signal_copy = copy.deepcopy(signals)
    config = BacktestConfig(hold_period=hold_period)

    BacktestEngine().run(signals, price_series, config)

    assert price_series == price_copy
    assert signals == signal_copy


# Feature: vpa-backtesting-engine, Property 10: Determinism
@settings(max_examples=100)
@given(
    case=_multi_signal_case(),
    mode=st.sampled_from([PositionMode.NO_OVERLAP, PositionMode.STACKING]),
)
def test_property_10_determinism(
    case: tuple[list[PricePoint], list[SignalEntry], int],
    mode: PositionMode,
) -> None:
    """Running twice produces identical trades and skipped lists (same order).

    Validates: Requirements 8.1; Design: Correctness Property 10.
    """
    price_series, signals, hold_period = case
    config = BacktestConfig(hold_period=hold_period, position_mode=mode)

    result_a = BacktestEngine().run(signals, price_series, config)
    result_b = BacktestEngine().run(signals, price_series, config)

    assert result_a.trades == result_b.trades
    assert result_a.skipped == result_b.skipped


# Feature: vpa-backtesting-engine, Property 11: Trade_Log ordering
@settings(max_examples=100)
@given(
    case=_multi_signal_case(),
    data=st.data(),
)
def test_property_11_trade_log_ordering(
    case: tuple[list[PricePoint], list[SignalEntry], int],
    data: st.DataObject,
) -> None:
    """The produced Trade_Log is ordered by entry_date ascending.

    Validates: Requirements 6.2; Design: Correctness Property 11.
    """
    price_series, signals, hold_period = case
    # Shuffle the signal log to prove ordering is independent of input order.
    shuffled = data.draw(st.permutations(signals))
    config = BacktestConfig(hold_period=hold_period, position_mode=PositionMode.STACKING)

    result = BacktestEngine().run(list(shuffled), price_series, config)

    entry_dates = [t.entry_date for t in result.trades]
    assert entry_dates == sorted(entry_dates)


# ---------------------------------------------------------------------------
# Task 11.1: engine edge-case unit tests
# ---------------------------------------------------------------------------


def test_signal_near_end_insufficient_future_data_exit() -> None:
    """t+1 valid but t+1+N out of bounds -> INSUFFICIENT_FUTURE_DATA_EXIT.

    _Requirements: 7.2_
    """
    # Indices 0..4. Signal on index 3 -> entry_index 4 (valid), exit 4+2=6 (oob).
    price_series = _make_price_series([10.0, 11.0, 12.0, 13.0, 14.0])
    signal = _signal(_iso(3), SignalType.STRONG_BULLISH)
    config = BacktestConfig(hold_period=2)

    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT


def test_signal_on_last_day_insufficient_future_data_entry() -> None:
    """Signal on the last day -> t+1 out of bounds -> INSUFFICIENT_FUTURE_DATA_ENTRY.

    _Requirements: 7.1_
    """
    price_series = _make_price_series([10.0, 11.0, 12.0])
    signal = _signal(_iso(2), SignalType.STRONG_BULLISH)  # last index
    config = BacktestConfig(hold_period=1)

    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == SkipReason.INSUFFICIENT_FUTURE_DATA_ENTRY


def test_empty_signal_log_produces_empty_trade_log() -> None:
    """Empty Signal_Log -> empty Trade_Log, no error.

    _Requirements: 6.5, 7.3_
    """
    price_series = _make_price_series([10.0, 11.0, 12.0, 13.0])
    config = BacktestConfig(hold_period=1)

    result = BacktestEngine().run([], price_series, config)

    assert result.trades == []
    assert result.skipped == []


def test_zero_entry_price_invalid_entry_price() -> None:
    """Zero close at the entry index -> INVALID_ENTRY_PRICE.

    _Requirements: 7.4_
    """
    # Signal index 0 -> entry_index 1 has close 0.0.
    price_series = _make_price_series([10.0, 0.0, 12.0, 13.0])
    signal = _signal(_iso(0), SignalType.STRONG_BULLISH)
    config = BacktestConfig(hold_period=1)

    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == SkipReason.INVALID_ENTRY_PRICE


def test_nan_entry_price_invalid_entry_price() -> None:
    """NaN close at the entry index -> INVALID_ENTRY_PRICE.

    _Requirements: 7.4_
    """
    price_series = _make_price_series([10.0, math.nan, 12.0, 13.0])
    signal = _signal(_iso(0), SignalType.STRONG_BULLISH)
    config = BacktestConfig(hold_period=1)

    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == SkipReason.INVALID_ENTRY_PRICE


def test_zero_exit_price_invalid_exit_price() -> None:
    """Zero close at the exit index -> INVALID_EXIT_PRICE.

    _Requirements: 7.5_
    """
    # Signal index 0 -> entry_index 1 (valid 11.0), exit_index 2 has close 0.0.
    price_series = _make_price_series([10.0, 11.0, 0.0, 13.0])
    signal = _signal(_iso(0), SignalType.STRONG_BULLISH)
    config = BacktestConfig(hold_period=1)

    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == SkipReason.INVALID_EXIT_PRICE


def test_nan_exit_price_invalid_exit_price() -> None:
    """NaN close at the exit index -> INVALID_EXIT_PRICE.

    _Requirements: 7.5_
    """
    price_series = _make_price_series([10.0, 11.0, math.nan, 13.0])
    signal = _signal(_iso(0), SignalType.STRONG_BULLISH)
    config = BacktestConfig(hold_period=1)

    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == SkipReason.INVALID_EXIT_PRICE


def test_signal_date_missing_from_price_series() -> None:
    """Signal date absent from the Price_Series -> MISSING_PRICE_DATE.

    _Requirements: 1.5_
    """
    price_series = _make_price_series([10.0, 11.0, 12.0, 13.0])
    signal = _signal("1999-12-31", SignalType.STRONG_BULLISH)  # not in series
    config = BacktestConfig(hold_period=1)

    result = BacktestEngine().run([signal], price_series, config)

    assert result.trades == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == SkipReason.MISSING_PRICE_DATE


def test_unsorted_price_series_and_signal_log_get_sorted() -> None:
    """Unsorted Price_Series and Signal_Log still produce correct ordered output.

    _Requirements: 1.4, 1.6_
    """
    ascending = _make_price_series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    shuffled_prices = [ascending[4], ascending[0], ascending[2], ascending[5], ascending[1], ascending[3]]

    # Two non-overlapping signals supplied out of date order.
    sig_early = _signal(_iso(0), SignalType.STRONG_BULLISH)  # entry 1, exit 2 (N=1)
    sig_late = _signal(_iso(3), SignalType.STRONG_BULLISH)  # entry 4, exit 5 (N=1)
    config = BacktestConfig(hold_period=1, position_mode=PositionMode.NO_OVERLAP)

    result = BacktestEngine().run([sig_late, sig_early], shuffled_prices, config)

    assert len(result.trades) == 2
    # Output ordered by entry_date ascending regardless of input order.
    assert result.trades[0].entry_date == _iso(1)
    assert result.trades[1].entry_date == _iso(4)
    # Entry prices come from the correctly sorted series.
    assert result.trades[0].entry_price == 11.0
    assert result.trades[1].entry_price == 14.0


def test_hold_period_zero_raises_value_error() -> None:
    """hold_period == 0 raises ValueError.

    _Requirements: 3.5_
    """
    price_series = _make_price_series([10.0, 11.0, 12.0])
    with pytest.raises(ValueError):
        BacktestEngine().run([], price_series, BacktestConfig(hold_period=0))


def test_hold_period_negative_raises_value_error() -> None:
    """Negative hold_period raises ValueError.

    _Requirements: 3.5_
    """
    price_series = _make_price_series([10.0, 11.0, 12.0])
    with pytest.raises(ValueError):
        BacktestEngine().run([], price_series, BacktestConfig(hold_period=-3))


def test_stacking_opens_concurrent_trades() -> None:
    """STACKING opens concurrent (overlapping) trades from nearby signals.

    _Requirements: 5.6_
    """
    price_series = _make_price_series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    # Two signals one day apart with N=3 produce overlapping holding intervals.
    sig_a = _signal(_iso(0), SignalType.STRONG_BULLISH)  # entry 1, exit 4
    sig_b = _signal(_iso(1), SignalType.STRONG_BULLISH)  # entry 2, exit 5
    config = BacktestConfig(hold_period=3, position_mode=PositionMode.STACKING)

    result = BacktestEngine().run([sig_a, sig_b], price_series, config)

    assert len(result.trades) == 2
    entry_a = _index_of_date(price_series, result.trades[0].entry_date)
    exit_a = _index_of_date(price_series, result.trades[0].exit_date)
    entry_b = _index_of_date(price_series, result.trades[1].entry_date)
    # Concurrency: the second trade enters before the first one exits.
    assert entry_b <= exit_a
    assert entry_a == 1 and entry_b == 2


# ---------------------------------------------------------------------------
# Task 11.2: hand-computed integration test (Req 8.2)
# ---------------------------------------------------------------------------

# Explicit 10-day Price_Series with known closes. Positional index i maps to
# date _iso(i) = 2020-01-(01+i).
_INTEGRATION_CLOSES = [
    100.0,  # idx0  2020-01-01
    102.0,  # idx1  2020-01-02
    104.0,  # idx2  2020-01-03
    101.0,  # idx3  2020-01-04
    108.0,  # idx4  2020-01-05
    110.0,  # idx5  2020-01-06
    105.0,  # idx6  2020-01-07
    112.0,  # idx7  2020-01-08
    115.0,  # idx8  2020-01-09
    120.0,  # idx9  2020-01-10
]


def test_integration_no_overlap_hand_computed() -> None:
    """Hand-computed NO_OVERLAP scenario: dates, prices, and net returns exact.

    Setup: hold_period N=2, round_trip_cost=0.01, NO_OVERLAP.

    Signals (all STRONG_BULLISH):
      - 2020-01-01 (idx0): entry_index=1, exit_index=3.
            entry=close[1]=102.0, exit=close[3]=101.0. Opens; open until exit 3.
      - 2020-01-03 (idx2): entry_index=3. 3 <= open_exit_index(3) -> OVERLAPPING,
            skipped.
      - 2020-01-05 (idx4): entry_index=5, exit_index=7. 5 > 3 -> opens.
            entry=close[5]=110.0, exit=close[7]=112.0.

    Expected trades (ordered by entry_date ascending):
      Trade 1: entry 2020-01-02 @ 102.0, exit 2020-01-04 @ 101.0,
               net = (101.0/102.0 - 1) - 0.01
      Trade 2: entry 2020-01-06 @ 110.0, exit 2020-01-08 @ 112.0,
               net = (112.0/110.0 - 1) - 0.01

    _Requirements: 8.2_
    """
    price_series = _make_price_series(_INTEGRATION_CLOSES)
    signals = [
        _signal(_iso(0), SignalType.STRONG_BULLISH),
        _signal(_iso(2), SignalType.STRONG_BULLISH),
        _signal(_iso(4), SignalType.STRONG_BULLISH),
    ]
    config = BacktestConfig(
        hold_period=2,
        round_trip_cost=0.01,
        position_mode=PositionMode.NO_OVERLAP,
    )

    result = BacktestEngine().run(signals, price_series, config)

    assert len(result.trades) == 2

    trade1 = result.trades[0]
    assert trade1.entry_date == "2020-01-02"
    assert trade1.exit_date == "2020-01-04"
    assert trade1.entry_price == 102.0
    assert trade1.exit_price == 101.0
    # Hand-computed net return (computed independently, not via engine formula).
    assert math.isclose(trade1.return_pct, (101.0 / 102.0 - 1.0) - 0.01, abs_tol=1e-12)
    assert trade1.signal_type == SignalType.STRONG_BULLISH

    trade2 = result.trades[1]
    assert trade2.entry_date == "2020-01-06"
    assert trade2.exit_date == "2020-01-08"
    assert trade2.entry_price == 110.0
    assert trade2.exit_price == 112.0
    assert math.isclose(trade2.return_pct, (112.0 / 110.0 - 1.0) - 0.01, abs_tol=1e-12)
    assert trade2.signal_type == SignalType.STRONG_BULLISH

    # The middle signal on 2020-01-03 was skipped as an overlapping position.
    overlapping = [s for s in result.skipped if s.reason == SkipReason.OVERLAPPING_POSITION]
    assert len(overlapping) == 1
    assert overlapping[0].signal_date == "2020-01-03"


def test_integration_stacking_hand_computed() -> None:
    """Hand-computed STACKING scenario: overlapping trades both open, cost 0.

    Setup: hold_period N=2, round_trip_cost=0.0, STACKING.

    Signals (all STRONG_BULLISH):
      - 2020-01-01 (idx0): entry_index=1, exit_index=3.
            entry=close[1]=102.0, exit=close[3]=101.0.
      - 2020-01-03 (idx2): entry_index=3, exit_index=5.
            entry=close[3]=101.0, exit=close[5]=110.0.

    Both open (STACKING, no overlap check). Ordered by entry_date ascending.

    Expected trades:
      Trade 1: entry 2020-01-02 @ 102.0, exit 2020-01-04 @ 101.0,
               net = 101.0/102.0 - 1 (cost 0 -> equals gross)
      Trade 2: entry 2020-01-04 @ 101.0, exit 2020-01-06 @ 110.0,
               net = 110.0/101.0 - 1

    _Requirements: 8.2_
    """
    price_series = _make_price_series(_INTEGRATION_CLOSES)
    signals = [
        _signal(_iso(0), SignalType.STRONG_BULLISH),
        _signal(_iso(2), SignalType.STRONG_BULLISH),
    ]
    config = BacktestConfig(
        hold_period=2,
        round_trip_cost=0.0,
        position_mode=PositionMode.STACKING,
    )

    result = BacktestEngine().run(signals, price_series, config)

    assert len(result.trades) == 2

    trade1 = result.trades[0]
    assert trade1.entry_date == "2020-01-02"
    assert trade1.exit_date == "2020-01-04"
    assert trade1.entry_price == 102.0
    assert trade1.exit_price == 101.0
    assert math.isclose(trade1.return_pct, 101.0 / 102.0 - 1.0, abs_tol=1e-12)

    trade2 = result.trades[1]
    assert trade2.entry_date == "2020-01-04"
    assert trade2.exit_date == "2020-01-06"
    assert trade2.entry_price == 101.0
    assert trade2.exit_price == 110.0
    assert math.isclose(trade2.return_pct, 110.0 / 101.0 - 1.0, abs_tol=1e-12)

    # STACKING applies no overlap skip.
    assert all(s.reason != SkipReason.OVERLAPPING_POSITION for s in result.skipped)


def test_signal_confidence_rank_ordering() -> None:
    """DISTRIBUTION > STRONG_BEARISH > STRONG_BULLISH > ACCUMULATION > unranked.

    Confirms the tie-break helper's total ordering used by NO_OVERLAP (Req 5.4).
    """
    ordered = [
        SignalType.DISTRIBUTION,
        SignalType.STRONG_BEARISH,
        SignalType.STRONG_BULLISH,
        SignalType.ACCUMULATION,
        SignalType.ACCUMULATION_TEST_PASS,  # unranked -> lowest priority
    ]
    ranks = [signal_confidence_rank(t) for t in ordered]
    assert ranks == sorted(ranks)
    # Strictly increasing: each is a distinct priority level.
    assert len(set(ranks)) == len(ranks)
