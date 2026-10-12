"""Multi-ticker selection helpers for the Req 9 individual-ticker runs.

These are pure, deterministic functions used to choose a spread of individual
S&P 500 tickers for the ML_Validation_Harness. They feed the Req 9 multi-ticker
runs: ``realized_daily_volatility`` measures each candidate ticker's realized
daily-return volatility over the run window, and ``volatility_spread_ok``
enforces the Req 9.1 condition that the selected tickers span a sufficient
range of volatility.
"""

from __future__ import annotations

import pandas as pd


def realized_daily_volatility(dataset: pd.DataFrame) -> float:
    """Return the realized daily-return volatility over the dataset window.

    Computes simple daily close-to-close returns (``pct_change``) from the
    dataset's ``"close"`` column and returns their standard deviation. The
    feature datasets produced by :class:`VPAFeatureExtractor` carry a lowercase
    ``"close"`` metadata column, which is the series used here.

    Args:
        dataset: A feature dataset with a ``"close"`` column.

    Returns:
        The standard deviation of the daily close-to-close returns as a float.

    Raises:
        KeyError: If the dataset has no ``"close"`` column.
        ValueError: If the dataset has fewer than 2 rows. At least two closes
            are needed to form a single return, and volatility is undefined for
            a degenerate (0- or 1-row) window, so this is treated as a caller
            error rather than silently returning 0.0.

    Notes:
        pandas computes the sample standard deviation (``ddof=1``) by default,
        which is what is returned here. If every return is identical the std is
        0.0; this is a legitimate (zero-volatility) result, not an error.
    """
    if "close" not in dataset.columns:
        raise ValueError("dataset must contain a 'close' column to compute realized volatility")

    if len(dataset) < 2:
        raise ValueError(f"realized_daily_volatility requires at least 2 rows to form a return; got {len(dataset)}")

    daily_returns = dataset["close"].pct_change().dropna()
    return float(daily_returns.std())


def volatility_spread_ok(vols: list[float]) -> bool:
    """Return True iff the selected tickers' volatilities span enough range.

    Implements the Req 9.1 condition: *each selected ticker's realized
    daily-return volatility differs from every other selected ticker's by at
    least 10 percent of the lowest selected ticker's volatility*. Concretely,
    for every pair ``(i, j)`` the condition requires::

        abs(vols[i] - vols[j]) >= 0.10 * min(vols)

    Args:
        vols: The realized daily-return volatilities of the selected tickers.

    Returns:
        True if the spread condition holds for every pair, False otherwise.

    Notes:
        Edge-case decisions:

        * **Fewer than 2 volatilities** — a single ticker (or none) has no pair
          to compare against, so the condition holds trivially and True is
          returned. (Req 9.1 only constrains how selected tickers differ from
          *each other*.)
        * **Zero or negative minimum** — a non-positive lowest volatility makes
          the 10%-of-min threshold meaningless (zero or negative), so such an
          input is rejected and False is returned. Volatility is a standard
          deviation and should be strictly positive for a usable ticker; a
          zero/negative value signals a degenerate or invalid series rather
          than a genuinely spread set.
    """
    if len(vols) < 2:
        return True

    lowest = min(vols)
    if lowest <= 0:
        return False

    threshold = 0.10 * lowest
    for i in range(len(vols)):
        for j in range(i + 1, len(vols)):
            if abs(vols[i] - vols[j]) < threshold:
                return False
    return True
