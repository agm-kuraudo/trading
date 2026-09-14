"""Centralised OHLCV ingestion/normalisation for the market-data store (SP-349).

This module is the single source of truth for the flatten/rename/dropna/sort logic
that was previously duplicated across ``utils.utils.get_live_data_from_yfinance``,
``MarketAnalyzer.load_data`` and ``VPAFeatureExtractor.generate_dataset``.

``normalise_yf_download`` is pure (no network). ``fetch_yf`` is the thin
``yf.download`` wrapper that delegates here; it is the only network-touching
function in this module.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

CANONICAL_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]

# The OHLCV columns whose absence (NaN) makes a bar unusable.
_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def normalise_yf_download(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalise a raw yfinance download into the canonical OHLCV shape.

    Consolidates the previously-duplicated normalisation:

    1. ``reset_index()`` so the DatetimeIndex becomes a ``Date`` column.
    2. Flatten a MultiIndex column axis via ``columns.get_level_values(0)``
       (matches ``utils.utils.get_live_data_from_yfinance``).
    3. Case-insensitively rename columns to the canonical names.
    4. ``dropna`` on the OHLCV columns.
    5. Sort ascending by ``Date`` and reset the index.
    6. Return exactly ``CANONICAL_COLUMNS`` in order.

    Pure: performs no network I/O.

    Args:
        raw: The raw DataFrame returned by ``yf.download`` (single ticker). May have
            a DatetimeIndex and either flat or MultiIndex columns.

    Returns:
        A DataFrame with exactly ``CANONICAL_COLUMNS`` (``Date, Open, High, Low,
        Close, Volume``), sorted ascending by ``Date`` with a fresh RangeIndex.
    """
    df = raw.reset_index()

    # Flatten a MultiIndex column axis (yfinance returns one for single tickers).
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Case-insensitive rename to canonical names: map lower(col) -> actual col.
    col_map = {str(c).lower(): c for c in df.columns}
    rename_map = {}
    for canonical in CANONICAL_COLUMNS:
        if canonical not in df.columns and canonical.lower() in col_map:
            rename_map[col_map[canonical.lower()]] = canonical
    if rename_map:
        df = df.rename(columns=rename_map)

    # Drop rows missing any OHLCV value.
    df = df.dropna(subset=_OHLCV_COLUMNS)

    # Sort ascending by Date and reset the index.
    df = df.sort_values("Date").reset_index(drop=True)

    # Return exactly the canonical columns, in order.
    return df[CANONICAL_COLUMNS]


def fetch_yf(ticker: str, interval: str, start, end) -> pd.DataFrame:
    """Fetch OHLCV bars from yfinance and return them in canonical shape.

    Thin wrapper around ``yf.download`` (the only network-touching function in this
    module). Delegates all normalisation to ``normalise_yf_download``.

    Args:
        ticker: The instrument symbol (e.g. ``"SPY"``).
        interval: The bar interval passed through to yfinance (e.g. ``"1d"``).
        start: Start of the range (anything ``yf.download`` accepts).
        end: End of the range (anything ``yf.download`` accepts).

    Returns:
        A canonical DataFrame (``CANONICAL_COLUMNS``) from
        ``normalise_yf_download``.
    """
    raw = yf.download(
        ticker,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=True,
        progress=False,
    )
    return normalise_yf_download(raw)


def _to_utc_bar_open(date_value) -> pd.Timestamp:
    """Map a canonical ``Date`` value to a timezone-aware UTC bar-open timestamp.

    For daily bars this is midnight UTC of that date. A naive/date-only value is
    localised to UTC; an already tz-aware value is converted to UTC. The result is
    suitable for a ``TIMESTAMPTZ`` column.
    """
    ts = pd.Timestamp(date_value)
    if ts.tzinfo is None and ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def to_store_rows(
    df: pd.DataFrame,
    ticker: str,
    interval: str,
    source: str,
    adjusted: bool,
) -> list[tuple]:
    """Map canonical OHLCV rows to store-row tuples for the ``ohlcv`` table.

    Each canonical row becomes a tuple:
    ``(ticker, interval, ts, open, high, low, close, volume, adjusted, source)``
    where ``ts`` is the row's ``Date`` mapped to a timezone-aware UTC bar-open
    timestamp (daily bars = midnight UTC).

    OHLC values are coerced to ``float`` and volume to ``float`` (or ``None`` when
    missing; ``normalise_yf_download`` already drops rows lacking OHLCV, so in
    practice they are present).

    Args:
        df: A canonical DataFrame (``CANONICAL_COLUMNS``), e.g. from
            ``normalise_yf_download``.
        ticker: The instrument symbol (e.g. ``"SPY"``).
        interval: The bar interval tag (e.g. ``"1d"``).
        source: The data source tag (e.g. ``"yfinance"``).
        adjusted: Whether the series is adjusted (``auto_adjust``).

    Returns:
        A list of tuples ready for the upsert SQL, one per row.
    """
    rows: list[tuple] = []
    for row in df.itertuples(index=False):
        ts = _to_utc_bar_open(row.Date)
        volume = None if pd.isna(row.Volume) else float(row.Volume)
        rows.append(
            (
                ticker,
                interval,
                ts,
                float(row.Open),
                float(row.High),
                float(row.Low),
                float(row.Close),
                volume,
                adjusted,
                source,
            )
        )
    return rows
