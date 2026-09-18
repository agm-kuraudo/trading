"""Unit / reference tests for the DSS Bressert calculator (vpa/dss_bressert.py).

These are example-based (plain pytest) tests, NOT Hypothesis property tests. They
cover the reference chain, flat-series neutrality, warmup neutrality, and output bounds.

The reference chain test (test_reference_chain_matches_independent_derivation) is an
INDEPENDENT re-derivation of the documented DSS Bressert algorithm, computed with plain
Python loops inside the test. It is an *internal consistency oracle* that checks the
module reproduces its own documented maths; it is NOT sourced from TradingView. True
TradingView visual parity is the manual verification step in task 9 of the spec.

Validates: Requirements 1.6, 1.9, 9.1, 9.2
"""

from vpa.dss_bressert import calculate_dss_bressert

NEUTRAL_VALUE = 50.0

# Calculator defaults (mirrored here so the tests do not import module internals).
DEFAULT_STOCHASTIC_PERIOD = 10
DEFAULT_SMOOTHING_PERIOD = 9
DEFAULT_TRIGGER_PERIOD = 5


def _warmup(stochastic_period: int, smoothing_period: int, trigger_period: int) -> int:
    """Minimum warmup length as documented: PDS + EMAlen + TriggerLen - 2."""
    return stochastic_period + smoothing_period + trigger_period - 2


# ---------------------------------------------------------------------------
# Independent re-derivation of the documented algorithm (test-local oracle).
# Deliberately re-implemented inline with plain Python loops rather than importing
# the module's private _stochastic_series / _ema_series helpers, so the reference
# is genuinely independent of the implementation under test.
# ---------------------------------------------------------------------------


def _ref_stochastic(high: list[float], low: list[float], close: list[float], period: int) -> list[float]:
    """Trailing-window stochastic %K with flat-range carry-forward (neutral if none)."""
    result: list[float] = []
    for t in range(len(close)):
        start = max(0, t - period + 1)
        highest = max(high[start : t + 1])
        lowest = min(low[start : t + 1])
        span = highest - lowest
        if span == 0:
            result.append(result[-1] if result else NEUTRAL_VALUE)
        else:
            result.append(100.0 * (close[t] - lowest) / span)
    return result


def _ref_ema(values: list[float], length: int) -> list[float]:
    """EMA with alpha = 2 / (length + 1), seeded from the first element."""
    if not values:
        return []
    alpha = 2.0 / (length + 1)
    out: list[float] = [values[0]]
    for i in range(1, len(values)):
        out.append(alpha * values[i] + (1 - alpha) * out[-1])
    return out


def _ref_dss_bressert(
    high: list[float],
    low: list[float],
    close: list[float],
    stochastic_period: int,
    smoothing_period: int,
    trigger_period: int,
) -> tuple[list[float], list[float]]:
    """Independent re-derivation of the full DSS Bressert chain with warmup neutralisation."""
    n = len(close)
    x_pre_calc = _ref_ema(_ref_stochastic(high, low, close, stochastic_period), smoothing_period)
    oscillator = _ref_ema(_ref_stochastic(x_pre_calc, x_pre_calc, x_pre_calc, stochastic_period), smoothing_period)
    trigger = _ref_ema(oscillator, trigger_period)

    warmup = _warmup(stochastic_period, smoothing_period, trigger_period)
    for i in range(min(warmup, n)):
        oscillator[i] = NEUTRAL_VALUE
        trigger[i] = NEUTRAL_VALUE
    return oscillator, trigger


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reference_chain_matches_independent_derivation():
    """The module reproduces the documented ema(stoch(ema(stoch(...)))) chain and trigger.

    Uses a small hand-defined OHLC series longer than the warmup and compares against an
    independently re-derived expectation computed with plain Python loops in this test.

    **Validates: Requirements 1.9**
    """
    stochastic_period = 3
    smoothing_period = 2
    trigger_period = 2
    warmup = _warmup(stochastic_period, smoothing_period, trigger_period)  # 3 + 2 + 2 - 2 = 5

    # Hand-defined, non-monotone series comfortably longer than the warmup (5).
    close = [10.0, 11.0, 10.5, 12.0, 11.5, 13.0, 12.5, 14.0, 13.5, 15.0, 14.0, 16.0]
    high = [c + 0.5 for c in close]
    low = [c - 0.5 for c in close]
    assert len(close) > warmup

    expected_osc, expected_trig = _ref_dss_bressert(
        high, low, close, stochastic_period, smoothing_period, trigger_period
    )
    actual_osc, actual_trig = calculate_dss_bressert(
        high, low, close, stochastic_period, smoothing_period, trigger_period
    )

    assert len(actual_osc) == len(expected_osc) == len(close)
    assert len(actual_trig) == len(expected_trig) == len(close)
    for i, (a, e) in enumerate(zip(actual_osc, expected_osc, strict=True)):
        assert abs(a - e) < 1e-9, f"oscillator[{i}] {a} != expected {e}"
    for i, (a, e) in enumerate(zip(actual_trig, expected_trig, strict=True)):
        assert abs(a - e) < 1e-9, f"trigger[{i}] {a} != expected {e}"


def test_flat_series_yields_neutral_oscillator():
    """A constant OHLC series (length > warmup) yields oscillator exactly 50.0 everywhere.

    **Validates: Requirements 1.6**
    """
    warmup = _warmup(DEFAULT_STOCHASTIC_PERIOD, DEFAULT_SMOOTHING_PERIOD, DEFAULT_TRIGGER_PERIOD)
    n = warmup + 15
    close = [100.0] * n
    high = [100.0] * n
    low = [100.0] * n

    oscillator, trigger = calculate_dss_bressert(high, low, close)

    assert len(oscillator) == n
    assert all(value == NEUTRAL_VALUE for value in oscillator), "flat series oscillator must be all 50.0"
    assert all(value == NEUTRAL_VALUE for value in trigger), "flat series trigger must be all 50.0"


def test_series_shorter_than_warmup_is_all_neutral():
    """A series shorter than the warmup returns all 50.0 for the oscillator.

    **Validates: Requirements 9.2**
    """
    warmup = _warmup(DEFAULT_STOCHASTIC_PERIOD, DEFAULT_SMOOTHING_PERIOD, DEFAULT_TRIGGER_PERIOD)
    n = warmup - 1
    close = [100.0 + i for i in range(n)]
    high = [c + 1.0 for c in close]
    low = [c - 1.0 for c in close]

    oscillator, trigger = calculate_dss_bressert(high, low, close)

    assert len(oscillator) == n
    assert all(value == NEUTRAL_VALUE for value in oscillator), "short series oscillator must be all 50.0"
    assert all(value == NEUTRAL_VALUE for value in trigger), "short series trigger must be all 50.0"


def test_warmup_indices_are_neutral_for_long_series():
    """For a series >= warmup, every index below the warmup equals exactly 50.0.

    **Validates: Requirements 9.2**
    """
    warmup = _warmup(DEFAULT_STOCHASTIC_PERIOD, DEFAULT_SMOOTHING_PERIOD, DEFAULT_TRIGGER_PERIOD)
    n = warmup + 20
    close = [100.0 + i * 0.7 for i in range(n)]
    high = [c + 0.5 for c in close]
    low = [c - 0.5 for c in close]

    oscillator, trigger = calculate_dss_bressert(high, low, close)

    assert len(oscillator) == n
    for i in range(warmup):
        assert oscillator[i] == NEUTRAL_VALUE, f"oscillator[{i}] must be 50.0 during warmup"
        assert trigger[i] == NEUTRAL_VALUE, f"trigger[{i}] must be 50.0 during warmup"


def test_valid_series_stays_within_bounds():
    """A representative valid series keeps every oscillator and trigger value in [0.0, 100.0].

    **Validates: Requirements 9.1**
    """
    warmup = _warmup(DEFAULT_STOCHASTIC_PERIOD, DEFAULT_SMOOTHING_PERIOD, DEFAULT_TRIGGER_PERIOD)
    n = warmup + 40
    # A varied, non-monotone series: sinusoidal-ish drift built without imports.
    close = []
    price = 100.0
    for i in range(n):
        step = ((i * 37) % 11) - 5  # deterministic pseudo-oscillation in [-5, 5]
        price = max(1.0, price + step * 0.5)
        close.append(price)
    high = [c + 1.25 for c in close]
    low = [max(0.5, c - 1.25) for c in close]

    oscillator, trigger = calculate_dss_bressert(high, low, close)

    assert len(oscillator) == n and len(trigger) == n
    for i, value in enumerate(oscillator):
        assert 0.0 <= value <= 100.0, f"oscillator[{i}] {value} out of [0, 100]"
    for i, value in enumerate(trigger):
        assert 0.0 <= value <= 100.0, f"trigger[{i}] {value} out of [0, 100]"
