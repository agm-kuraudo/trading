"""RSI (Relative Strength Index) calculator using Wilder's smoothed moving average method."""


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    """Calculate RSI using Wilder's smoothed moving average method.

    Args:
        closes: List of closing prices (oldest first).
        period: RSI lookback period (default 14).

    Returns:
        RSI value between 0.0 and 100.0 inclusive.
        Returns 50.0 if fewer than period + 1 prices provided.
    """
    if len(closes) < period + 1:
        return 50.0

    # Compute price changes
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Separate gains and losses
    gains = [max(c, 0.0) for c in changes]
    losses = [abs(min(c, 0.0)) for c in changes]

    # Initial averages from the first `period` changes
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Apply Wilder's smoothing for subsequent bars
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    # Handle edge cases
    if avg_gain == 0.0 and avg_loss == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    if avg_gain == 0.0:
        return 0.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi
