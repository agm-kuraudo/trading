"""Property test for invalid symbol rejection in the orchestrator (Property 8).

``Forex_Data_Retriever.get_daily_dataframe`` validates the symbol *before* it
performs any I/O: it strips surrounding whitespace and requires exactly six
alphabetic characters, otherwise it raises :class:`InvalidSymbolError`. Because
validation is a pre-fetch guard, a rejected symbol must never trigger a metadata
or feed fetch.

This test drives ``get_daily_dataframe`` with strings that are *not* exactly six
alphabetic characters (wrong length, or six characters containing digits /
punctuation / whitespace) and asserts two things:

1. ``InvalidSymbolError`` is raised.
2. Neither ``feed.fetch_symbol_metadata`` nor ``feed.fetch_feed`` is invoked —
   proven by monkeypatching both to raise ``AssertionError`` if called.

It lives in its own file (distinct from task 7.3's ``test_retriever_symbol.py``)
to avoid collision.

Requirements: 8.4.
"""

import pytest
from _pytest.monkeypatch import MonkeyPatch
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from vpa.forex_data import retriever
from vpa.forex_data.errors import InvalidSymbolError

# The retriever normalises by stripping surrounding whitespace, so a symbol is
# valid iff its stripped form is exactly six alphabetic characters. Any string
# whose stripped form is NOT exactly six alpha chars is a genuine invalid input.
_INVALID_SYMBOL = st.text().filter(
    lambda s: not (len(s.strip()) == 6 and s.strip().isalpha())
)


# Feature: replace-selenium-forex-scraping, Property 8: Invalid symbols are rejected before any retrieval
@settings(max_examples=100)
@given(bad_symbol=_INVALID_SYMBOL)
@example(bad_symbol="")
@example(bad_symbol="GBP")
@example(bad_symbol="GBPUSDX")
@example(bad_symbol="GBP123")
@example(bad_symbol="12 456")
def test_invalid_symbol_rejected(bad_symbol):
    """Property 8: a symbol that is not exactly six alphabetic characters is
    rejected with ``InvalidSymbolError`` before any metadata or feed fetch.

    Both network seams are monkeypatched to raise ``AssertionError`` if invoked,
    so a passing test proves the validation guard runs strictly before any I/O.
    A per-example ``MonkeyPatch.context()`` is used (rather than the
    function-scoped ``monkeypatch`` fixture) so the patches are applied and
    undone independently for every Hypothesis-generated input.

    **Validates: Requirements 8.4**
    """
    # Guard against the (rare) generated string that is actually valid.
    assume(not (len(bad_symbol.strip()) == 6 and bad_symbol.strip().isalpha()))

    def _no_fetch(*args, **kwargs):
        raise AssertionError(
            "no fetch must occur for an invalid symbol; validation is pre-fetch"
        )

    with MonkeyPatch.context() as patch:
        patch.setattr(retriever.feed, "fetch_symbol_metadata", _no_fetch)
        patch.setattr(retriever.feed, "fetch_feed", _no_fetch)

        with pytest.raises(InvalidSymbolError):
            retriever.get_daily_dataframe(bad_symbol)
