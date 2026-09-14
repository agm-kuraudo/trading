"""Unit tests for orchestrator metadata lookup and the default symbol (task 7.5).

Exercises :class:`vpa.forex_data.retriever.Forex_Data_Retriever` end-to-end
without touching the network by monkeypatching the two feed seams referenced
through the module (``vpa.forex_data.retriever.feed.fetch_symbol_metadata`` and
``vpa.forex_data.retriever.feed.fetch_feed``). This module owns only the
metadata-lookup and default-symbol cases; symbol normalization/invalid-symbol,
multi-pair, and the sufficiency boundary live in their own retriever test files.

Covered:

- Happy-path metadata lookup: the per-symbol ``priceScale`` is applied so raw
  Int32 price fields decode to the expected floating-point prices, and the
  returned frame carries the Analysis_DataFrame columns (Requirement 1.4).
- Missing symbol in metadata -> :class:`SymbolMetadataError` (Requirement 1.5).
- Symbol present but missing ``priceScale``/``volumeScale`` ->
  :class:`SymbolMetadataError` (Requirement 1.5).
- No-argument ``get_daily_dataframe()`` targets the default symbol ``"GBPUSD"``
  (Requirement 8.2).

Requirements: 1.4, 1.5, 8.2.
"""

import pandas as pd
import pytest

from vpa.forex_data import feed
from vpa.forex_data.aggregator import DAILY_COLUMNS
from vpa.forex_data.decoder import EPOCH_BASE_MS
from vpa.forex_data.errors import SymbolMetadataError
from vpa.forex_data.retriever import DEFAULT_SYMBOL, Forex_Data_Retriever
from vpa.tests.forex_data.helpers import encode_records

# GBPUSD price scale from the real premium metadata: raw Int32 / 100000 -> price.
_PRICE_SCALE = 100000
_VOLUME_SCALE = 1

# One intraday record's raw Int32 fields. ``time_field`` is minutes since
# 2000-01-01T00:00:00Z; a value of 0 lands the bar exactly on the epoch base so
# the derived timestamp is unambiguous. The four price fields are pre-scaled
# integers (e.g. 130000 / 100000 == 1.3).
_TIME_FIELD = 0
_OPEN_I = 130000
_HIGH_I = 131000
_LOW_I = 129500
_CLOSE_I = 130500
_VOLUME_I = 7


def _single_bar_feed() -> bytes:
    """Return a synthetic gzipped 24-byte feed of one intraday record.

    Aggregates to exactly one daily bar, so a retriever with ``min_bars=1``
    returns a populated DataFrame.
    """
    return encode_records(
        [(_TIME_FIELD, _OPEN_I, _HIGH_I, _LOW_I, _CLOSE_I, _VOLUME_I)],
        size=24,
    )


def test_metadata_lookup_applies_price_scale(monkeypatch):
    """Happy path: GBPUSD scales resolve and prices reflect priceScale=100000.

    The retriever fetches metadata, looks up GBPUSD's ``priceScale``, decodes
    the feed dividing each raw price field by that scale, and aggregates to a
    daily Analysis_DataFrame (Requirement 1.4).
    """
    metadata = {"GBPUSD": {"priceScale": _PRICE_SCALE, "volumeScale": _VOLUME_SCALE}}
    monkeypatch.setattr(feed, "fetch_symbol_metadata", lambda: metadata)
    monkeypatch.setattr(
        feed, "fetch_feed", lambda symbol, period=30: _single_bar_feed()
    )

    result = Forex_Data_Retriever(min_bars=1).get_daily_dataframe("GBPUSD")

    assert list(result.columns) == DAILY_COLUMNS
    assert len(result) == 1

    row = result.iloc[0]
    # Prices are the raw Int32 fields divided by priceScale=100000.
    assert row["Open"] == pytest.approx(_OPEN_I / _PRICE_SCALE)
    assert row["High"] == pytest.approx(_HIGH_I / _PRICE_SCALE)
    assert row["Low"] == pytest.approx(_LOW_I / _PRICE_SCALE)
    assert row["Close"] == pytest.approx(_CLOSE_I / _PRICE_SCALE)
    assert row["Volume"] == _VOLUME_I

    # time_field == 0 lands the single bar on the epoch base date (2000-01-01).
    assert row["Date"] == pd.Timestamp(EPOCH_BASE_MS, unit="ms").normalize()


def test_missing_symbol_raises_symbol_metadata_error(monkeypatch):
    """Metadata without the requested symbol -> ``SymbolMetadataError`` (Req 1.5)."""
    metadata = {"EURUSD": {"priceScale": _PRICE_SCALE, "volumeScale": _VOLUME_SCALE}}
    monkeypatch.setattr(feed, "fetch_symbol_metadata", lambda: metadata)

    def _fail_fetch_feed(symbol, period=30):
        raise AssertionError("fetch_feed must not be called when metadata lookup fails")

    monkeypatch.setattr(feed, "fetch_feed", _fail_fetch_feed)

    with pytest.raises(SymbolMetadataError):
        Forex_Data_Retriever(min_bars=1).get_daily_dataframe("GBPUSD")


def test_missing_scales_raises_symbol_metadata_error(monkeypatch):
    """Symbol present but missing priceScale/volumeScale -> ``SymbolMetadataError``.

    The metadata carries the symbol key but not the scaling fields, so the
    orchestrator cannot decode prices and fails loudly (Requirement 1.5).
    """
    metadata = {"GBPUSD": {"someOtherField": True}}
    monkeypatch.setattr(feed, "fetch_symbol_metadata", lambda: metadata)

    def _fail_fetch_feed(symbol, period=30):
        raise AssertionError("fetch_feed must not be called when scales are missing")

    monkeypatch.setattr(feed, "fetch_feed", _fail_fetch_feed)

    with pytest.raises(SymbolMetadataError):
        Forex_Data_Retriever(min_bars=1).get_daily_dataframe("GBPUSD")


def test_default_symbol_targets_gbpusd(monkeypatch):
    """A no-argument call targets the default symbol ``"GBPUSD"`` (Requirement 8.2)."""
    metadata = {"GBPUSD": {"priceScale": _PRICE_SCALE, "volumeScale": _VOLUME_SCALE}}
    monkeypatch.setattr(feed, "fetch_symbol_metadata", lambda: metadata)

    captured_symbols: list[str] = []

    def _capturing_fetch_feed(symbol, period=30):
        captured_symbols.append(symbol)
        return _single_bar_feed()

    monkeypatch.setattr(feed, "fetch_feed", _capturing_fetch_feed)

    result = Forex_Data_Retriever(min_bars=1).get_daily_dataframe()

    assert captured_symbols == [DEFAULT_SYMBOL]
    assert DEFAULT_SYMBOL == "GBPUSD"
    assert len(result) == 1
