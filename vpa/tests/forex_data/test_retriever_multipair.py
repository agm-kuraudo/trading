"""Multi-pair (non-GBPUSD) orchestrator unit test for the browserless retriever.

This test closes the proof-of-concept gap where ONLY GBPUSD
(``priceScale=100000``) was ever verified end-to-end. It drives
:meth:`vpa.forex_data.retriever.Forex_Data_Retriever.get_daily_dataframe`
against a *different* currency pair (USDJPY) whose ``priceScale`` (1000, since
JPY pairs quote to ~3 decimal places) differs from GBPUSD's, proving:

- the retriever derives the feed URL/symbol from the requested pair rather than
  a hardcoded GBPUSD (the ``fetch_feed`` symbol argument is captured and
  asserted to be the uppercased pair);
- decoding uses *that pair's* ``priceScale`` looked up from the metadata (a raw
  Int32 open field of ``150250`` decodes to ``150.25`` at ``priceScale=1000``,
  not ``1.5025`` as it would under GBPUSD's ``100000``);
- the resulting Analysis_DataFrame carries the standard columns with Volume.

The network boundary is fully monkeypatched (``feed.fetch_symbol_metadata`` and
``feed.fetch_feed`` on :mod:`vpa.forex_data.retriever`); no real request occurs.
The synthetic M30 feed is built with :func:`vpa.tests.forex_data.helpers.encode_records`
from known raw Int32 field tuples.

Requirements: 8.1, 8.3, 2.7.
"""

import pandas as pd

from vpa.forex_data import feed
from vpa.forex_data.aggregator import DAILY_COLUMNS
from vpa.forex_data.retriever import Forex_Data_Retriever
from vpa.tests.forex_data.helpers import encode_records

# USDJPY quotes to ~3 decimals, so its priceScale differs from GBPUSD's 100000.
_USDJPY_PRICE_SCALE = 1000
_USDJPY_VOLUME_SCALE = 1

# Known raw Int32 open field. At priceScale=1000 this decodes to 150.25; under
# GBPUSD's 100000 it would decode to 1.5025, so the assertion distinguishes the
# per-symbol scale lookup from a hardcoded GBPUSD scale (Requirements 2.7, 8.3).
_OPEN_FIELD = 150250
_EXPECTED_OPEN = _OPEN_FIELD / _USDJPY_PRICE_SCALE  # 150.25

# time_field is minutes since 2000-01-01T00:00:00Z. Anchor a run of M30 bars
# inside a single UTC calendar day so aggregation yields exactly one daily bar.
# 2000-01-03 = day index 2 -> 2 * 1440 minutes.
_DAY_START_MIN = 2 * 1440
_M30 = 30  # 30 minutes between successive M30 bars.


def _build_usdjpy_m30_feed() -> bytes:
    """Build a synthetic gzipped M30 feed spanning one UTC day for USDJPY.

    Uses 24-byte records ``(time, open, high, low, close, volume)`` with the
    first bar's open fixed to :data:`_OPEN_FIELD` so the decoded/aggregated
    daily Open is deterministic (``first`` of the day).
    """
    records: list[tuple[int, ...]] = []
    # Four M30 bars within the same UTC day (00:00, 00:30, 01:00, 01:30).
    for i in range(4):
        time_field = _DAY_START_MIN + i * _M30
        if i == 0:
            open_i = _OPEN_FIELD  # -> daily Open (first)
        else:
            open_i = _OPEN_FIELD + i * 10
        high_i = open_i + 500
        low_i = open_i - 500
        close_i = open_i + 100
        volume_i = 5
        records.append((time_field, open_i, high_i, low_i, close_i, volume_i))
    return encode_records(records, size=24)


def test_non_gbpusd_pair_uses_its_own_scale_and_symbol(monkeypatch):
    """USDJPY decodes with its own priceScale and derives the pair's symbol/URL.

    Validates Requirements 8.1, 8.3, 2.7: the retriever looks up the requested
    symbol's scale from metadata (priceScale=1000 -> Open 150.25) and passes the
    uppercased pair symbol to the feed fetch, rather than assuming GBPUSD.
    """
    metadata = {
        "USDJPY": {
            "priceScale": _USDJPY_PRICE_SCALE,
            "volumeScale": _USDJPY_VOLUME_SCALE,
        }
    }
    monkeypatch.setattr(feed, "fetch_symbol_metadata", lambda *a, **k: metadata)

    synthetic_feed = _build_usdjpy_m30_feed()
    captured_symbols: list[str] = []

    def fake_fetch_feed(symbol, period=_M30, *args, **kwargs):
        captured_symbols.append(symbol)
        return synthetic_feed

    monkeypatch.setattr(feed, "fetch_feed", fake_fetch_feed)

    # min_bars=1 so the single synthetic daily bar satisfies the sufficiency
    # check; lowercase input also exercises symbol normalization.
    retriever = Forex_Data_Retriever(min_bars=1)
    result = retriever.get_daily_dataframe("usdjpy")

    # 1. The feed was fetched for the uppercased pair, not a hardcoded GBPUSD
    #    (Requirements 8.1, 8.3).
    assert captured_symbols == ["USDJPY"]

    # 2. Prices reflect priceScale=1000: Open == 150.25 (NOT 1.5025 under the
    #    GBPUSD scale of 100000) (Requirements 2.7, 8.3).
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 1
    assert result["Open"].iloc[0] == _EXPECTED_OPEN

    # 3. Standard Analysis_DataFrame columns with Volume present (Requirement 4.1).
    assert list(result.columns) == DAILY_COLUMNS
    assert "Volume" in result.columns
    # Volume is the sum of the four M30 bars' volumes (4 * 5 = 20).
    assert result["Volume"].iloc[0] == 20
