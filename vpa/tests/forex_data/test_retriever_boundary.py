"""Sufficiency-boundary and error-mapping unit tests for the orchestrator.

Exercises :meth:`vpa.forex_data.retriever.Forex_Data_Retriever.get_daily_dataframe`
end-to-end with the network boundary fully monkeypatched (``feed.fetch_feed`` /
``feed.fetch_symbol_metadata`` on :mod:`vpa.forex_data.retriever`); no real
request is ever made. Synthetic M30 feeds are built with
:func:`vpa.tests.forex_data.helpers.encode_records` from raw Int32 field tuples,
and the *real* :func:`vpa.forex_data.decoder.decode_feed` runs so that decode
failures surface exactly as they would in production.

Covered behaviour:

- The sufficiency boundary is inclusive: a feed aggregating to EXACTLY
  ``min_bars`` (200) daily bars is returned in full (Requirement 5.1), while a
  feed one bar short (199) raises :class:`InsufficientDataError` and returns
  nothing partial (Requirement 5.2).
- Orchestrator error mapping: a network failure from ``fetch_feed`` propagates
  as :class:`FeedNetworkError` (Requirement 6.1); a non-200 status propagates as
  :class:`FeedHTTPError` carrying the status code (Requirement 6.2); a
  zero-record feed raises :class:`EmptyFeedError` (Requirement 6.3); and a body
  that cannot be gunzipped raises :class:`FeedDecodeError` via the real decoder
  (Requirement 6.4).

Requirements: 5.1, 5.2, 6.1, 6.2, 6.3, 6.4.
"""

import gzip

import pandas as pd
import pytest

from vpa.forex_data import feed
from vpa.forex_data.errors import (
    EmptyFeedError,
    FeedDecodeError,
    FeedHTTPError,
    FeedNetworkError,
    InsufficientDataError,
)
from vpa.forex_data.retriever import Forex_Data_Retriever
from vpa.tests.forex_data.helpers import encode_records

# Standard GBPUSD scaling metadata (priceScale=100000, volumeScale=1).
_METADATA = {"GBPUSD": {"priceScale": 100000, "volumeScale": 1}}

# The default sufficiency window (Long_Period_SMA = 200 daily bars).
_MIN_BARS = 200

# One UTC calendar day is 1440 minutes; time_field is minutes since
# 2000-01-01T00:00:00Z (see decoder.EPOCH_BASE_MS).
_MINUTES_PER_DAY = 1440

# A representative raw Int32 open field so decoded prices are deterministic.
_OPEN_FIELD = 150000  # -> 1.5 at priceScale=100000.


def _build_daily_feed(num_days: int) -> bytes:
    """Build a synthetic gzipped M30 feed aggregating to ``num_days`` daily bars.

    Emits exactly one 24-byte M30 record per UTC calendar day for ``num_days``
    consecutive days (``time_field = day * 1440`` minutes), so the daily
    aggregation yields exactly ``num_days`` distinct daily bars.
    """
    records: list[tuple[int, ...]] = []
    for day in range(num_days):
        time_field = day * _MINUTES_PER_DAY
        open_i = _OPEN_FIELD
        high_i = open_i + 500
        low_i = open_i - 500
        close_i = open_i + 100
        volume_i = 1
        records.append((time_field, open_i, high_i, low_i, close_i, volume_i))
    return encode_records(records, size=24)


def _patch_metadata(monkeypatch, metadata: dict = _METADATA) -> None:
    """Monkeypatch ``fetch_symbol_metadata`` to return ``metadata`` (no network)."""
    monkeypatch.setattr(feed, "fetch_symbol_metadata", lambda *a, **k: metadata)


def _patch_fetch_feed(monkeypatch, handler) -> None:
    """Monkeypatch ``fetch_feed`` with ``handler`` (called with symbol/period)."""

    def fake_fetch_feed(symbol, period=30, *args, **kwargs):
        return handler(symbol, period)

    monkeypatch.setattr(feed, "fetch_feed", fake_fetch_feed)


# ---------------------------------------------------------------------------
# Sufficiency boundary (Requirement 5)
# ---------------------------------------------------------------------------


def test_exactly_min_bars_passes_and_returns_all_rows(monkeypatch):
    """A feed of EXACTLY 200 daily bars is returned in full (Requirement 5.1).

    The sufficiency check is inclusive: ``len(daily) >= min_bars`` passes, so a
    feed producing precisely ``min_bars`` distinct UTC daily bars yields a
    DataFrame with exactly that many rows.
    """
    _patch_metadata(monkeypatch)
    synthetic_feed = _build_daily_feed(_MIN_BARS)
    _patch_fetch_feed(monkeypatch, lambda symbol, period: synthetic_feed)

    result = Forex_Data_Retriever(min_bars=_MIN_BARS).get_daily_dataframe("GBPUSD")

    assert isinstance(result, pd.DataFrame)
    assert len(result) == _MIN_BARS


def test_one_below_min_bars_raises_insufficient_and_returns_nothing(monkeypatch):
    """A feed of 199 daily bars raises ``InsufficientDataError`` (Requirement 5.2).

    No partial DataFrame is returned; the error is raised instead.
    """
    _patch_metadata(monkeypatch)
    synthetic_feed = _build_daily_feed(_MIN_BARS - 1)
    _patch_fetch_feed(monkeypatch, lambda symbol, period: synthetic_feed)

    with pytest.raises(InsufficientDataError):
        Forex_Data_Retriever(min_bars=_MIN_BARS).get_daily_dataframe("GBPUSD")


# ---------------------------------------------------------------------------
# Orchestrator error mapping (Requirement 6)
# ---------------------------------------------------------------------------


def test_network_error_from_fetch_feed_propagates(monkeypatch):
    """A ``FeedNetworkError`` raised by ``fetch_feed`` propagates unchanged (Req 6.1)."""
    _patch_metadata(monkeypatch)

    def raise_network(symbol, period):
        raise FeedNetworkError("network is down")

    _patch_fetch_feed(monkeypatch, raise_network)

    with pytest.raises(FeedNetworkError):
        Forex_Data_Retriever(min_bars=_MIN_BARS).get_daily_dataframe("GBPUSD")


def test_http_error_from_fetch_feed_propagates_with_status_code(monkeypatch):
    """A ``FeedHTTPError(404)`` from ``fetch_feed`` propagates with its status (Req 6.2)."""
    _patch_metadata(monkeypatch)

    def raise_http(symbol, period):
        raise FeedHTTPError(status_code=404)

    _patch_fetch_feed(monkeypatch, raise_http)

    with pytest.raises(FeedHTTPError) as exc_info:
        Forex_Data_Retriever(min_bars=_MIN_BARS).get_daily_dataframe("GBPUSD")

    assert exc_info.value.status_code == 404


def test_non_gzip_bytes_raise_feed_decode_error(monkeypatch):
    """Non-gzip garbage bytes fail decompression -> ``FeedDecodeError`` (Req 6.4).

    The real :func:`decode_feed` runs here, so the decode failure surfaces
    exactly as it would in production.
    """
    _patch_metadata(monkeypatch)
    _patch_fetch_feed(monkeypatch, lambda symbol, period: b"not gzip")

    with pytest.raises(FeedDecodeError):
        Forex_Data_Retriever(min_bars=_MIN_BARS).get_daily_dataframe("GBPUSD")


def test_empty_feed_raises_empty_feed_error(monkeypatch):
    """A feed decoding to zero records raises ``EmptyFeedError`` (Req 6.3).

    ``gzip.compress(b"")`` gunzips to an empty buffer, which the decoder maps to
    zero records; the orchestrator treats that as an empty feed.
    """
    _patch_metadata(monkeypatch)
    _patch_fetch_feed(monkeypatch, lambda symbol, period: gzip.compress(b""))

    with pytest.raises(EmptyFeedError):
        Forex_Data_Retriever(min_bars=_MIN_BARS).get_daily_dataframe("GBPUSD")
