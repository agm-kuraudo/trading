"""Momentum/Drawdown Filter — identifies tickers with positive momentum trading below 52-week high.

This module contains pure functions for calculating 52-week highs, momentum,
and applying the drawdown threshold to identify opportunity candidates.
All functions operate on pandas DataFrames/Series and config dicts with no
external data-source dependencies.
"""

from typing import Optional

import logging
import pandas as pd

logger = logging.getLogger(__name__)


# --- Configuration ---

DEFAULT_DRAWDOWN_CONFIG = {
    "enabled": True,
    "drawdown_threshold": 20,
    "momentum_period": 20,
    "data_days": 365,
}


def load_drawdown_config(config: dict) -> dict:
    """Extract and validate drawdown_filter config section.

    Reads the ``drawdown_filter`` key from the application config dict.
    Missing keys are filled with defaults. Invalid values are replaced
    with defaults and a warning is logged.

    Args:
        config: Full application config dict.

    Returns:
        Validated drawdown filter config dict with defaults applied.
    """
    section = config.get("drawdown_filter", {})

    result = {
        "enabled": section.get("enabled", DEFAULT_DRAWDOWN_CONFIG["enabled"]),
        "drawdown_threshold": section.get("drawdown_threshold", DEFAULT_DRAWDOWN_CONFIG["drawdown_threshold"]),
        "momentum_period": section.get("momentum_period", DEFAULT_DRAWDOWN_CONFIG["momentum_period"]),
        "data_days": section.get("data_days", DEFAULT_DRAWDOWN_CONFIG["data_days"]),
    }

    # Validate momentum_period
    if result["momentum_period"] < 1:
        logger.warning(
            "drawdown_filter.momentum_period is %s (must be >= 1); using default value 20",
            result["momentum_period"],
        )
        result["momentum_period"] = DEFAULT_DRAWDOWN_CONFIG["momentum_period"]

    # Validate drawdown_threshold
    if result["drawdown_threshold"] < 0 or result["drawdown_threshold"] > 100:
        logger.warning(
            "drawdown_filter.drawdown_threshold is %s (must be 0-100); using default value 20",
            result["drawdown_threshold"],
        )
        result["drawdown_threshold"] = DEFAULT_DRAWDOWN_CONFIG["drawdown_threshold"]

    return result


# --- Core Calculations ---


def compute_52_week_high(closes: pd.Series, window: int = 252) -> Optional[float]:
    """Compute the 52-week high from the last `window` trading days of closes.

    Args:
        closes: Series of closing prices (most recent last).
        window: Number of trading days for the look-back (default 252).

    Returns:
        The maximum closing price in the window, or None if insufficient data.
    """
    if len(closes) < window:
        return None
    return float(closes.iloc[-window:].max())


def compute_drawdown_percentage(current_close: float, fifty_two_week_high: float) -> float:
    """Compute drawdown as percentage decline from peak.

    Formula: ((current_close - fifty_two_week_high) / fifty_two_week_high) * 100
    Result is negative when current price is below peak.

    Args:
        current_close: Latest closing price.
        fifty_two_week_high: Peak price over 252-day window.

    Returns:
        Drawdown percentage (negative value indicates decline from peak).
    """
    return ((current_close - fifty_two_week_high) / fifty_two_week_high) * 100


def compute_momentum(closes: pd.Series, period: int = 20) -> Optional[float]:
    """Compute rate-of-change momentum over the given period.

    Formula: ((current_close - close_n_days_ago) / close_n_days_ago) * 100

    Args:
        closes: Series of closing prices (most recent last).
        period: Look-back period in trading days.

    Returns:
        Momentum percentage, or None if insufficient data or division by zero.
    """
    if len(closes) < period + 1:
        return None

    close_n_days_ago = closes.iloc[-period - 1]

    if close_n_days_ago == 0:
        return None

    current_close = closes.iloc[-1]
    return ((current_close - close_n_days_ago) / close_n_days_ago) * 100


# --- Filter Application ---


def evaluate_ticker(
    df: pd.DataFrame,
    drawdown_threshold: float = 20.0,
    momentum_period: int = 20,
) -> Optional[dict]:
    """Evaluate a single ticker's DataFrame against the filter criteria.

    A ticker qualifies when its current price is at least `drawdown_threshold`
    percent below the 52-week high AND its short-term momentum is positive.

    Args:
        df: DataFrame with at least a 'Close' column, sorted by date ascending.
        drawdown_threshold: Minimum drawdown percentage to qualify (default 20).
        momentum_period: Look-back period for momentum calculation (default 20).

    Returns:
        Dict with keys {drawdown_pct, momentum, fifty_two_week_high} if ticker
        qualifies, or None if it doesn't meet criteria or has insufficient data.
    """
    if len(df) < 252:
        logger.warning(
            "Insufficient data for drawdown filter: got %d rows, need at least 252",
            len(df),
        )
        return None

    closes = df["Close"]

    fifty_two_week_high = compute_52_week_high(closes, 252)
    if fifty_two_week_high is None:
        return None

    current_close = float(closes.iloc[-1])
    drawdown_pct = compute_drawdown_percentage(current_close, fifty_two_week_high)

    momentum = compute_momentum(closes, momentum_period)
    if momentum is None:
        logger.warning(
            "Insufficient data for momentum calculation: need at least %d rows after warm-up, got %d total",
            momentum_period + 1,
            len(closes),
        )
        return None

    if drawdown_pct <= -drawdown_threshold and momentum > 0:
        return {
            "drawdown_pct": drawdown_pct,
            "momentum": momentum,
            "fifty_two_week_high": fifty_two_week_high,
        }

    return None


# --- Report Formatting ---


def format_opportunities_report(opportunities: list[dict]) -> str:
    """Format the opportunities list into the report section text.

    Args:
        opportunities: List of dicts with keys {ticker, drawdown_pct, momentum}.
                      Pre-sorted by drawdown_pct ascending (largest drawdown first).

    Returns:
        Formatted plain-text string for the report section.
    """
    header = "Opportunities\n============="

    if not opportunities:
        return f"{header}\nNo opportunities found\n"

    lines = [header]
    lines.append(f"{'Ticker':<10} {'Drawdown%':>10} {'Momentum%':>10}")
    for entry in opportunities:
        ticker = entry["ticker"]
        drawdown = entry["drawdown_pct"]
        momentum = entry["momentum"]
        lines.append(f"{ticker:<10} {drawdown:>10.1f} {momentum:>10.1f}")
    lines.append("")  # trailing newline

    return "\n".join(lines)


def format_disabled_report() -> str:
    """Format the report section when the drawdown filter is disabled.

    Returns:
        Formatted plain-text string indicating the filter is disabled.
    """
    return "Opportunities\n=============\nOpportunities: disabled\n"
