"""DSS Bressert (Double Smoothed Stochastic) oscillator and trigger-line calculator.

Pure, deterministic functions in the style of ``vpa/rsi.py``. The oscillator is a
double-smoothed stochastic bounded in ``[0.0, 100.0]``; the trigger line is an EMA of
the oscillator. During the warmup window (and on invalid/short input) the calculator
returns the neutral value ``50.0`` and raises no error.
"""

NEUTRAL_VALUE = 50.0


def _is_valid_period(period: object) -> bool:
    """Return True when ``period`` is an integer >= 1.

    ``bool`` is a subclass of ``int`` in Python, so ``True``/``False`` would otherwise
    slip through an ``isinstance(..., int)`` check; it is explicitly rejected as a
    non-int, matching the project's ``validate_hold_period`` style.
    """
    if isinstance(period, bool) or not isinstance(period, int):
        return False
    return period >= 1


def _stochastic_series(high: list[float], low: list[float], close: list[float], period: int) -> list[float]:
    """Trailing-window stochastic %K series over close/high/low.

    For each index ``t``, computes
    ``100 * (close[t] - lowest(low, period)) / (highest(high, period) - lowest(low, period))``
    over the trailing ``period`` bars ending at ``t``. Flat-range windows (max == min)
    carry forward the previous stochastic value, or ``50.0`` when there is no previous
    value. Pure and deterministic.

    Args:
        high: High prices (oldest first).
        low: Low prices (oldest first).
        close: Closing prices (oldest first).
        period: Stochastic lookback length (>= 1).

    Returns:
        A list of stochastic %K values aligned to the input length.
    """
    n = len(close)
    result: list[float] = []
    for t in range(n):
        start = max(0, t - period + 1)
        window_high = high[start : t + 1]
        window_low = low[start : t + 1]
        highest = max(window_high)
        lowest = min(window_low)
        span = highest - lowest
        if span == 0:
            # Flat-range window: carry forward the prior value, or neutral if none.
            result.append(result[-1] if result else NEUTRAL_VALUE)
        else:
            result.append(100.0 * (close[t] - lowest) / span)
    return result


def _ema_series(values: list[float], length: int) -> list[float]:
    """Exponential moving average series with ``alpha = 2 / (length + 1)``.

    Seeded from the first element; index ``t`` depends only on ``values[:t + 1]``. Pure
    and deterministic.

    Args:
        values: Input series (oldest first).
        length: EMA length (>= 1).

    Returns:
        A list of EMA values aligned to the input length.
    """
    if not values:
        return []
    alpha = 2.0 / (length + 1)
    result: list[float] = [values[0]]
    for i in range(1, len(values)):
        result.append(alpha * values[i] + (1 - alpha) * result[-1])
    return result


def calculate_dss_bressert(
    high: list[float],
    low: list[float],
    close: list[float],
    stochastic_period: int = 10,
    smoothing_period: int = 9,
    trigger_period: int = 5,
) -> tuple[list[float], list[float]]:
    """Compute the DSS Bressert oscillator and trigger line for a whole series.

    Applies the chain:
        xPreCalc   = ema(stoch(close, high, low, PDS),            EMAlen)
        oscillator = ema(stoch(xPreCalc, xPreCalc, xPreCalc, PDS), EMAlen)
        trigger    = ema(oscillator,                              TriggerLen)

    The second stochastic uses ``xPreCalc`` as high, low AND close simultaneously.

    Args:
        high: High prices (oldest first).
        low: Low prices (oldest first).
        close: Closing prices (oldest first).
        stochastic_period: Stochastic lookback (PDS), default 10.
        smoothing_period: EMA smoothing length (EMAlen), default 9.
        trigger_period: Trigger EMA length (TriggerLen), default 5.

    Returns:
        A tuple ``(oscillator, trigger)``, each a list aligned to the input length.
        Every index strictly below ``minimum_warmup_length`` is set to the neutral
        value ``50.0`` for BOTH lists. Returns ``(all-50.0, all-50.0)`` with no error
        when the series is shorter than the warmup length, or when any period is not an
        integer >= 1. Deterministic and side-effect free; performs no I/O.
    """
    n = len(close)

    # Invalid periods -> neutral series, no error (Req 1.7).
    if not (
        _is_valid_period(stochastic_period) and _is_valid_period(smoothing_period) and _is_valid_period(trigger_period)
    ):
        neutral = [NEUTRAL_VALUE] * n
        return (neutral, list(neutral))

    minimum_warmup_length = stochastic_period + smoothing_period + trigger_period - 2

    # Empty / degenerate input -> aligned empty lists.
    if n == 0:
        return ([], [])

    # Series shorter than warmup -> all neutral (Req 8.1).
    if n < minimum_warmup_length:
        neutral = [NEUTRAL_VALUE] * n
        return (neutral, list(neutral))

    # Full DSS Bressert chain.
    x_pre_calc = _ema_series(_stochastic_series(high, low, close, stochastic_period), smoothing_period)
    oscillator = _ema_series(
        _stochastic_series(x_pre_calc, x_pre_calc, x_pre_calc, stochastic_period), smoothing_period
    )
    trigger = _ema_series(oscillator, trigger_period)

    # Neutralise every row whose index is below the warmup length (Req 8.2).
    for i in range(min(minimum_warmup_length, n)):
        oscillator[i] = NEUTRAL_VALUE
        trigger[i] = NEUTRAL_VALUE

    return (oscillator, trigger)
