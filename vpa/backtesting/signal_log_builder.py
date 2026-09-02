"""Signal_Log and Price_Series builders from a Feature_Dataset (SP-317).

Reuses the SP-314 signal classification (`SignalConditionalAnalyzer.classify_signals`)
and `SIGNAL_DIRECTIONS` rather than re-implementing any signal filter logic, so the
NaN-handling behaviour (Req 2.5) is inherited directly from that classifier.
"""

import pandas as pd

from vpa.backtesting.models import PricePoint, SignalEntry
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalConditionalAnalyzer,
    SignalType,
)

_OHLC_COLUMNS = ("date", "open", "high", "low", "close")


def _normalise_date(value: object) -> str:
    """Normalise a dataset date value to an ISO 8601 YYYY-MM-DD string.

    Datasets already store ISO date strings; pandas Timestamps (or anything
    exposing ``strftime``) are converted consistently for both builders.
    """
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")  # type: ignore[attr-defined]
    return str(value)


def build_signal_log_from_dataset(df: pd.DataFrame) -> list[SignalEntry]:
    """Build a Signal_Log by reusing SP-314 classify_signals (Req 2.1, 2.2).

    Produces one SignalEntry per matched SignalType per row, using the row
    date, the matched SignalType, and ``SIGNAL_DIRECTIONS[signal_type]``. NaN
    fields are excluded per classify_signals behaviour (Req 2.5).

    Ordering is deterministic: SignalType in enum declaration order, then
    ascending row index. The engine re-sorts by date, so this order only needs
    to be stable for testability.
    """
    analyzer = SignalConditionalAnalyzer(output_dir=".")
    matches = analyzer.classify_signals(df)

    entries: list[SignalEntry] = []
    for signal_type in SignalType:
        direction = SIGNAL_DIRECTIONS[signal_type]
        for row_index in sorted(matches[signal_type]):
            date = _normalise_date(df.loc[row_index, "date"])
            entries.append(SignalEntry(date=date, signal_type=signal_type, direction=direction))
    return entries


def build_price_series_from_dataset(df: pd.DataFrame) -> list[PricePoint]:
    """Build a date-ascending Price_Series from date/open/high/low/close (Req 2.3).

    Raises a ``KeyError`` naming the first missing required column when the
    dataset lacks an OHLC/date column (the "SP-335 not applied" guard).
    """
    missing = [column for column in _OHLC_COLUMNS if column not in df.columns]
    if missing:
        raise KeyError(f"Feature_Dataset is missing required column(s): {', '.join(missing)}")

    ordered = df.sort_values("date", ascending=True)
    return [
        PricePoint(
            date=_normalise_date(row["date"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for _, row in ordered.iterrows()
    ]
