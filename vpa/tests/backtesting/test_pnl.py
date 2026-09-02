"""Tests for direction-aware per-trade P&L (SP-333).

Covers Correctness Property 4 (Direction-aware P&L) via a Hypothesis property
test.

Code under test: ``vpa/backtesting/pnl.py``.
"""

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.backtesting.models import TradeRecord
from vpa.backtesting.pnl import price_trades, strategy_return
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalDirection,
    SignalType,
)

# Signal types partitioned by their mapped direction (SIGNAL_DIRECTIONS):
# STRONG_BULLISH=UP, STRONG_BEARISH=DOWN, ACCUMULATION=UP, DISTRIBUTION=DOWN,
# ACCUMULATION_TEST_PASS=UP.
_UP_SIGNAL_TYPES = [st for st, d in SIGNAL_DIRECTIONS.items() if d == SignalDirection.UP]
_DOWN_SIGNAL_TYPES = [st for st, d in SIGNAL_DIRECTIONS.items() if d == SignalDirection.DOWN]

_prices = st.floats(min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)
_round_trip_cost = st.floats(min_value=0.0, max_value=0.05, allow_nan=False, allow_infinity=False)
_return_pct = st.floats(min_value=-1.0, max_value=5.0, allow_nan=False, allow_infinity=False)


def _make_trade(
    entry_price: float,
    exit_price: float,
    return_pct: float,
    signal_type: SignalType,
) -> TradeRecord:
    """Build a TradeRecord; dates are positional-only placeholders here."""
    return TradeRecord(
        entry_date="00000000",
        exit_date="00000001",
        entry_price=entry_price,
        exit_price=exit_price,
        return_pct=return_pct,
        signal_type=signal_type,
    )


# Feature: vpa-strategy-backtest-report, Property 4: Direction-aware P&L
@settings(max_examples=100)
@given(
    entry_price=_prices,
    exit_price=_prices,
    return_pct=_return_pct,
    round_trip_cost=_round_trip_cost,
    up_signal_type=st.sampled_from(_UP_SIGNAL_TYPES),
    down_signal_type=st.sampled_from(_DOWN_SIGNAL_TYPES),
)
def test_property_4_direction_aware_pnl(
    entry_price: float,
    exit_price: float,
    return_pct: float,
    round_trip_cost: float,
    up_signal_type: SignalType,
    down_signal_type: SignalType,
) -> None:
    """UP returns equal return_pct; DOWN returns equal the raw short formula.

    Validates: Requirements 8.1, 8.2, 8.3.
    """
    # UP: Strategy_Return equals TradeRecord.return_pct (Req 8.1).
    up_trade = _make_trade(entry_price, exit_price, return_pct, up_signal_type)
    assert math.isclose(
        strategy_return(up_trade, round_trip_cost),
        return_pct,
        abs_tol=1e-9,
    )

    # DOWN: Strategy_Return equals the raw short-equivalent formula computed
    # from raw prices with the round-trip cost applied exactly once (Req 8.2).
    down_trade = _make_trade(entry_price, exit_price, return_pct, down_signal_type)
    expected_down = (entry_price / exit_price) - 1 - round_trip_cost
    assert math.isclose(
        strategy_return(down_trade, round_trip_cost),
        expected_down,
        abs_tol=1e-9,
    )


# Feature: vpa-strategy-backtest-report, Property 4: Direction-aware P&L
@settings(max_examples=100)
@given(
    entry_price=_prices,
    exit_price=_prices,
    return_pct=_return_pct,
    down_signal_type=st.sampled_from(_DOWN_SIGNAL_TYPES),
)
def test_property_4_falling_price_positive_before_cost(
    entry_price: float,
    exit_price: float,
    return_pct: float,
    down_signal_type: SignalType,
) -> None:
    """A falling-price DOWN trade yields a raw short return > 0 before costs.

    When exit_price < entry_price, ``(entry_price / exit_price) - 1`` (the raw
    short-equivalent return, i.e. the strategy return before any round-trip
    cost) must be strictly greater than 0 (Req 8.3).
    """
    # Only exercise the falling-price case this property describes.
    if not exit_price < entry_price:
        return

    down_trade = _make_trade(entry_price, exit_price, return_pct, down_signal_type)
    raw_short_return = strategy_return(down_trade, 0.0)
    assert raw_short_return > 0

# Explicit DOWN signal types per the design (Contrarian_Only set): both map to
# SignalDirection.DOWN in SIGNAL_DIRECTIONS.
_DOWN_SIGNAL_TYPES_EXPLICIT = [SignalType.STRONG_BEARISH, SignalType.DISTRIBUTION]


# Feature: vpa-strategy-backtest-report, Property 5: Round-trip cost applied exactly once for DOWN trades
@settings(max_examples=100)
@given(
    entry_price=_prices,
    exit_price=_prices,
    return_pct=_return_pct,
    round_trip_cost=_round_trip_cost,
    down_signal_type=st.sampled_from(_DOWN_SIGNAL_TYPES_EXPLICIT),
)
def test_property_5_down_cost_applied_exactly_once(
    entry_price: float,
    exit_price: float,
    return_pct: float,
    round_trip_cost: float,
    down_signal_type: SignalType,
) -> None:
    """DOWN Strategy_Return subtracts the round-trip cost exactly once and is
    never derived from ``TradeRecord.return_pct``.

    For a DOWN trade the Strategy_Return equals the raw short-equivalent return
    ``(entry_price / exit_price) - 1`` minus ``round_trip_cost`` applied exactly
    once. The result is independent of whatever value ``return_pct`` holds, and
    the difference between the cost-applied and zero-cost results is exactly
    ``-round_trip_cost`` (the cost is subtracted one time).

    Validates: Requirements 8.4.
    """
    down_trade = _make_trade(entry_price, exit_price, return_pct, down_signal_type)

    # 1. Strategy_Return equals the raw short-equivalent minus the cost once.
    raw_short_return = (entry_price / exit_price) - 1
    expected = raw_short_return - round_trip_cost
    with_cost = strategy_return(down_trade, round_trip_cost)
    assert math.isclose(with_cost, expected, abs_tol=1e-9)

    # 2. The cost is subtracted exactly one time: the gap between the
    #    cost-applied and zero-cost results is exactly -round_trip_cost.
    zero_cost = strategy_return(down_trade, 0.0)
    assert math.isclose(with_cost - zero_cost, -round_trip_cost, abs_tol=1e-9)

    # 3. The DOWN result is not derived from return_pct: varying return_pct
    #    (entry/exit/cost fixed) does not change the Strategy_Return.
    other_return_pct = return_pct + 1.0
    varied_trade = _make_trade(entry_price, exit_price, other_return_pct, down_signal_type)
    assert math.isclose(
        strategy_return(varied_trade, round_trip_cost),
        with_cost,
        abs_tol=1e-9,
    )


# ---------------------------------------------------------------------------
# Example tests for P&L exclusions (Req 8.5, 8.6)
#
# These are explicit example (not property) tests covering the exclusion paths
# of ``price_trades``: exit_price == 0 (Req 8.5) and unknown direction
# (Req 8.6), plus confirmation that a normal valid trade is priced.
#
# Reachability note: every SignalType enum member is present in
# SIGNAL_DIRECTIONS (STRONG_BULLISH/ACCUMULATION/ACCUMULATION_TEST_PASS -> UP,
# STRONG_BEARISH/DISTRIBUTION -> DOWN), so ``direction_for`` never returns None
# for a real SignalType. The ``unknown_direction`` branch is therefore defensive
# and unreachable via a valid enum member. It is still exercised below by
# constructing a TradeRecord with a sentinel signal_type that is absent from the
# map (TradeRecord is a plain frozen dataclass with no runtime type check), which
# is the only way to reach the branch.
# ---------------------------------------------------------------------------


def test_price_trades_excludes_exit_price_zero() -> None:
    """A trade with exit_price == 0 is excluded with reason "exit_price_zero".

    The excluded trade must not appear in the priced list, and ``price_trades``
    must not raise.

    Validates: Requirements 8.5.
    """
    zero_exit_trade = _make_trade(
        entry_price=100.0,
        exit_price=0.0,
        return_pct=-1.0,
        signal_type=SignalType.STRONG_BULLISH,  # valid (UP) direction
    )

    priced, exclusions = price_trades([zero_exit_trade], round_trip_cost=0.001)

    assert priced == []
    assert len(exclusions) == 1
    assert exclusions[0].reason == "exit_price_zero"
    assert exclusions[0].trade is zero_exit_trade


def test_price_trades_excludes_unknown_direction() -> None:
    """A trade whose signal_type is absent from SIGNAL_DIRECTIONS is excluded.

    The exclusion reason must be "unknown_direction", the trade must not be
    priced, and ``price_trades`` must not raise. Reaching this defensive branch
    requires a signal_type outside the SignalType enum (see the module note
    above), so a sentinel object is used as the signal_type here.

    Validates: Requirements 8.6.
    """
    unknown_signal_type = object()  # not a key in SIGNAL_DIRECTIONS
    unknown_trade = TradeRecord(
        entry_date="00000000",
        exit_date="00000001",
        entry_price=100.0,
        exit_price=95.0,
        return_pct=-0.05,
        signal_type=unknown_signal_type,  # type: ignore[arg-type]
    )

    priced, exclusions = price_trades([unknown_trade], round_trip_cost=0.001)

    assert priced == []
    assert len(exclusions) == 1
    assert exclusions[0].reason == "unknown_direction"
    assert exclusions[0].trade is unknown_trade


def test_price_trades_prices_a_valid_trade() -> None:
    """A normal valid trade is priced with the correct direction.

    Confirms the non-excluded path: a valid UP trade appears in the priced list
    with its resolved SignalDirection and is absent from the exclusions.

    Validates: Requirements 8.5, 8.6.
    """
    valid_trade = _make_trade(
        entry_price=100.0,
        exit_price=110.0,
        return_pct=0.10,
        signal_type=SignalType.STRONG_BULLISH,  # UP
    )

    priced, exclusions = price_trades([valid_trade], round_trip_cost=0.001)

    assert exclusions == []
    assert len(priced) == 1
    assert priced[0].trade is valid_trade
    assert priced[0].direction == SignalDirection.UP
    assert math.isclose(priced[0].strategy_return, 0.10, abs_tol=1e-9)


def test_price_trades_mixed_batch_partitions_correctly() -> None:
    """A mixed batch is partitioned into priced trades and exclusions.

    Combines a valid UP trade, a valid DOWN trade, an exit_price == 0 trade, and
    an unknown-direction trade, asserting each lands in the correct bucket with
    the correct exclusion reasons and no exception is raised.

    Validates: Requirements 8.5, 8.6.
    """
    up_trade = _make_trade(100.0, 110.0, 0.10, SignalType.ACCUMULATION)  # UP
    down_trade = _make_trade(100.0, 90.0, -0.10, SignalType.DISTRIBUTION)  # DOWN
    zero_exit_trade = _make_trade(100.0, 0.0, -1.0, SignalType.STRONG_BULLISH)
    unknown_trade = TradeRecord(
        entry_date="00000000",
        exit_date="00000001",
        entry_price=100.0,
        exit_price=95.0,
        return_pct=-0.05,
        signal_type=object(),  # type: ignore[arg-type]
    )

    priced, exclusions = price_trades(
        [up_trade, down_trade, zero_exit_trade, unknown_trade],
        round_trip_cost=0.001,
    )

    priced_source_trades = [p.trade for p in priced]
    assert priced_source_trades == [up_trade, down_trade]

    reasons_by_trade = {id(e.trade): e.reason for e in exclusions}
    assert reasons_by_trade[id(zero_exit_trade)] == "exit_price_zero"
    assert reasons_by_trade[id(unknown_trade)] == "unknown_direction"
    assert len(exclusions) == 2
