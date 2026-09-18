"""Property tests for the pure DSS Bressert calculator."""

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.dss_bressert import calculate_dss_bressert


@st.composite
def _ohlc(draw, minimum_length: int = 5):
    close = draw(
        st.lists(
            st.floats(min_value=1, max_value=1000, allow_nan=False, allow_infinity=False),
            min_size=minimum_length,
            max_size=80,
        )
    )
    spreads = draw(
        st.lists(
            st.floats(min_value=0, max_value=10, allow_nan=False, allow_infinity=False),
            min_size=len(close),
            max_size=len(close),
        )
    )
    return (
        [c + s for c, s in zip(close, spreads, strict=True)],
        [max(0, c - s) for c, s in zip(close, spreads, strict=True)],
        close,
    )


@settings(max_examples=100)
@given(_ohlc(minimum_length=20))
def test_outputs_are_bounded(ohlc) -> None:
    oscillator, trigger = calculate_dss_bressert(*ohlc, 3, 2, 2)
    assert all(0.0 <= value <= 100.0 for value in oscillator + trigger)


@settings(max_examples=100)
@given(st.integers(min_value=1, max_value=30))
def test_warmup_is_neutral(period: int) -> None:
    warmup = period + 2 + 2 - 2
    close = [100.0 + index for index in range(warmup + 3)]
    oscillator, trigger = calculate_dss_bressert(
        [value + 1 for value in close],
        [value - 1 for value in close],
        close,
        period,
        2,
        2,
    )
    assert oscillator[:warmup] == [50.0] * warmup
    assert trigger[:warmup] == [50.0] * warmup


@settings(max_examples=100)
@given(_ohlc(minimum_length=1))
def test_calculation_is_deterministic(ohlc) -> None:
    assert calculate_dss_bressert(*ohlc) == calculate_dss_bressert(*ohlc)


@settings(max_examples=100)
@given(st.sampled_from([0, -1, 1.5, "3"]))
def test_invalid_periods_are_neutral(period) -> None:
    close = [100.0 + index for index in range(30)]
    oscillator, trigger = calculate_dss_bressert(
        [value + 1 for value in close], [value - 1 for value in close], close, period
    )
    assert oscillator == [50.0] * len(close)
    assert trigger == [50.0] * len(close)
