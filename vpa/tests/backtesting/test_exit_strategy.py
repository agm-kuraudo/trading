"""Tests for the fixed-hold exit strategy (SP-317).

Covers Correctness Property 2 (Fixed-hold exit pricing) via a Hypothesis
property test, plus unit tests for the exit-bounds edge cases.

Code under test: ``vpa/backtesting/exit_strategy.py``.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.backtesting.exit_strategy import FixedHoldExitStrategy
from vpa.backtesting.models import PricePoint, SkipReason


def _make_price_series(n: int) -> list[PricePoint]:
    """Build a Price_Series of ``n`` days with ascending distinct dates.

    ``resolve_exit`` indexes positionally and never parses dates, so any
    unique ascending date strings are fine. We use zero-padded sequential
    integers as the date field.
    """
    return [
        PricePoint(
            date=f"{i:08d}",
            open=float(i + 1),
            high=float(i + 2),
            low=float(i + 1) * 0.5,
            close=float(i + 1),
        )
        for i in range(n)
    ]


# Generates a Price_Series length, an entry_index within bounds, and a
# hold_period, then derives concrete values so both the in-bounds and the
# out-of-bounds branches get exercised.
@st.composite
def _exit_case(draw: st.DrawFn) -> tuple[list[PricePoint], int, int]:
    length = draw(st.integers(min_value=2, max_value=50))
    price_series = _make_price_series(length)
    entry_index = draw(st.integers(min_value=0, max_value=length - 1))
    hold_period = draw(st.integers(min_value=1, max_value=length))
    return price_series, entry_index, hold_period


# Feature: vpa-backtesting-engine, Property 2: Fixed-hold exit pricing
@settings(max_examples=100)
@given(case=_exit_case())
def test_fixed_hold_exit_pricing(case: tuple[list[PricePoint], int, int]) -> None:
    """exit_index == entry_index + hold_period maps to close[exit_index].

    Validates: Requirements 3.2, 9.2; Design: Correctness Property 2.
    """
    price_series, entry_index, hold_period = case
    strategy = FixedHoldExitStrategy()
    last_index = len(price_series) - 1
    expected_exit_index = entry_index + hold_period

    result = strategy.resolve_exit(entry_index, price_series, hold_period)

    if expected_exit_index <= last_index:
        # In-bounds: index/price mapping must hold and no skip reason is set.
        assert result.exit_index == expected_exit_index
        assert result.exit_price == price_series[expected_exit_index].close
        assert result.reason is None
    else:
        # Out-of-bounds: exit horizon runs past the series (Req 7.2).
        assert result.exit_index is None
        assert result.exit_price is None
        assert result.reason is SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT


def test_exit_index_one_past_last_returns_insufficient_future_data() -> None:
    """exit_index exactly one past the last index is unresolved.

    _Requirements: 7.2, 9.2_
    """
    price_series = _make_price_series(5)  # valid indices 0..4
    strategy = FixedHoldExitStrategy()

    # entry_index=4, hold_period=1 -> exit_index=5, which is len(series).
    result = strategy.resolve_exit(4, price_series, 1)

    assert result.exit_index is None
    assert result.exit_price is None
    assert result.reason is SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT


def test_exit_index_on_last_valid_index_resolves() -> None:
    """exit_index on the last valid index returns a resolved ExitResult.

    _Requirements: 7.2, 9.2_
    """
    price_series = _make_price_series(5)  # valid indices 0..4
    strategy = FixedHoldExitStrategy()

    # entry_index=2, hold_period=2 -> exit_index=4, the last valid index.
    result = strategy.resolve_exit(2, price_series, 2)

    assert result.exit_index == 4
    assert result.exit_price == price_series[4].close
    assert result.reason is None
