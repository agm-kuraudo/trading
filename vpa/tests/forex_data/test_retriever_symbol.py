"""Property test for symbol normalization and URL derivation (task 7.3).

Exercises :class:`vpa.forex_data.retriever.Forex_Data_Retriever` at its
orchestrator boundary without touching the network by monkeypatching the two
feed seams referenced through the module
(``vpa.forex_data.retriever.feed.fetch_symbol_metadata`` and
``vpa.forex_data.retriever.feed.fetch_feed``).

This module owns only Property 7 (normalization + URL derivation). The
invalid-symbol rejection property (Property 8, task 7.4) lives in its own file,
``test_retriever_invalid_symbol.py``.

Property 7 asserts that any string of exactly six alphabetic characters in any
letter case is normalized to uppercase before the feed is fetched, and that the
derived feed URL is
``https://data.forexsb.com/datafeed/data/dukascopy/{UPPER}30.lb.gz``.

``fetch_feed`` is the seam that builds that URL from its ``symbol`` argument
(``f"{base_url}/{symbol.upper()}{period}.lb.gz"``), so capturing the symbol the
orchestrator passes to ``fetch_feed`` — and rebuilding the URL the same way
``feed.py`` does — validates normalization and derivation at the boundary.

Requirements: 1.3, 8.1, 8.3.
"""

from hypothesis import given, settings
from hypothesis import strategies as st
from pytest import MonkeyPatch

from vpa.forex_data import feed
from vpa.forex_data.retriever import M30_PERIOD, Forex_Data_Retriever
from vpa.tests.forex_data.helpers import encode_records

# The feed base URL that feed.py derives the download URL from. Kept in sync
# with vpa.forex_data.feed._FEED_BASE_URL so the expected URL is built exactly
# as feed.fetch_feed builds it.
_FEED_BASE_URL = "https://data.forexsb.com/datafeed/data/dukascopy"

# Scales are irrelevant to normalization; any valid positive scales let the
# feed decode without a SymbolMetadataError.
_PRICE_SCALE = 100000
_VOLUME_SCALE = 1

# A single intraday record (raw Int32 fields) that aggregates to one daily bar,
# so a retriever built with min_bars=1 returns data without an
# InsufficientDataError. time_field == 0 lands the bar on the epoch base date.
_ONE_BAR = [(0, 130000, 131000, 129500, 130500, 7)]


def _single_bar_feed() -> bytes:
    """Return a synthetic gzipped 24-byte feed of one intraday record."""
    return encode_records(_ONE_BAR, size=24)


def _mixed_case_symbols() -> st.SearchStrategy[str]:
    """Strings of exactly six ASCII letters in arbitrary (mixed) letter case."""
    return st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
        min_size=6,
        max_size=6,
    ).filter(lambda s: s.isalpha() and len(s) == 6)


# Feature: replace-selenium-forex-scraping, Property 7: Symbol normalization and URL derivation
@settings(max_examples=100)
@given(symbol=_mixed_case_symbols())
def test_symbol_normalized_and_url_derived(symbol):
    """Any 6-letter symbol is uppercased before fetch and drives the feed URL.

    Validates: Requirements 1.3, 8.1, 8.3
    """
    expected_symbol = symbol.upper()
    expected_url = f"{_FEED_BASE_URL}/{expected_symbol}{M30_PERIOD}.lb.gz"

    # Metadata must contain the UPPERCASED symbol with valid scales, since the
    # orchestrator looks up the normalized symbol before fetching the feed.
    metadata = {expected_symbol: {"priceScale": _PRICE_SCALE, "volumeScale": _VOLUME_SCALE}}

    captured: dict[str, object] = {}

    def _capturing_fetch_feed(sym, period=30):
        captured["symbol"] = sym
        captured["period"] = period
        return _single_bar_feed()

    # Use Hypothesis-safe patching: a MonkeyPatch context manager resets between
    # generated inputs, unlike the function-scoped ``monkeypatch`` fixture.
    with MonkeyPatch.context() as mp:
        mp.setattr(feed, "fetch_symbol_metadata", lambda: metadata)
        mp.setattr(feed, "fetch_feed", _capturing_fetch_feed)

        # min_bars=1 keeps the synthetic feed small and fast.
        Forex_Data_Retriever(min_bars=1).get_daily_dataframe(symbol)

    # Normalization: fetch_feed received the uppercased symbol at the M30 period.
    assert captured["symbol"] == expected_symbol
    assert captured["period"] == M30_PERIOD

    # URL derivation: rebuilding the URL exactly as feed.fetch_feed does from the
    # captured symbol yields the dukascopy/{UPPER}30.lb.gz endpoint.
    derived_url = f"{_FEED_BASE_URL}/{str(captured['symbol']).upper()}{captured['period']}.lb.gz"
    assert derived_url == expected_url
