"""Browserless forex data retrieval package.

Downloads and decodes the gzipped Dukascopy binary feed from data.forexsb.com
and aggregates M30 intraday bars into daily (D1) bars for MarketAnalyzer.

Public API: import :func:`get_daily_dataframe` (or :class:`Forex_Data_Retriever`)
directly from this package, e.g. ``from vpa.forex_data import get_daily_dataframe``.
The typed error hierarchy is re-exported here as well so callers can catch
retrieval failures without reaching into submodules.
"""

from vpa.forex_data.errors import (
    EmptyFeedError,
    FeedDecodeError,
    FeedHTTPError,
    FeedNetworkError,
    ForexRetrievalError,
    InsufficientDataError,
    InvalidSymbolError,
    SymbolMetadataError,
)
from vpa.forex_data.retriever import Forex_Data_Retriever, get_daily_dataframe

__all__ = [
    "Forex_Data_Retriever",
    "get_daily_dataframe",
    "ForexRetrievalError",
    "InvalidSymbolError",
    "SymbolMetadataError",
    "FeedNetworkError",
    "FeedHTTPError",
    "FeedDecodeError",
    "EmptyFeedError",
    "InsufficientDataError",
]
