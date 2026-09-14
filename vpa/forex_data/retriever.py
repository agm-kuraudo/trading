"""Orchestrator for the browserless forex retriever.

Wires the network boundary (:mod:`vpa.forex_data.feed`) to the pure decode and
aggregation logic (:mod:`vpa.forex_data.decoder`,
:mod:`vpa.forex_data.aggregator`) and enforces the cross-cutting policy rules:
symbol validation, per-run metadata caching, the empty-feed check, and the
minimum-row (sufficiency) check. Every failure surfaces as a typed
:class:`~vpa.forex_data.errors.ForexRetrievalError` and returns no data, so the
scheduled job fails loudly rather than analysing bad data (Requirement 6).

The feed functions are referenced through the :mod:`vpa.forex_data.feed` module
(``feed.fetch_feed`` / ``feed.fetch_symbol_metadata``) rather than imported by
name, so tests can monkeypatch ``vpa.forex_data.retriever.feed.fetch_feed`` to
drive the orchestrator end-to-end without touching the network (Requirement
9.3).
"""

import pandas as pd

from vpa.forex_data import feed
from vpa.forex_data.aggregator import aggregate_to_daily
from vpa.forex_data.decoder import decode_feed
from vpa.forex_data.errors import (
    EmptyFeedError,
    InsufficientDataError,
    InvalidSymbolError,
    SymbolMetadataError,
)

# A valid symbol is a 6-character currency pair code (e.g. "GBPUSD").
SYMBOL_LENGTH = 6
# Default symbol when the caller does not specify one (Requirement 8.2).
DEFAULT_SYMBOL = "GBPUSD"
# The intraday period downloaded and aggregated to daily bars (Requirement 1.3).
M30_PERIOD = 30
# Default minimum daily bars, matching the Long_Period_SMA window (config
# ``ma_crossover.ma_periods.long`` = 200) (Requirement 5.1).
DEFAULT_MIN_BARS = 200


class Forex_Data_Retriever:
    """Browserless retriever producing a daily-bar Analysis_DataFrame.

    Downloads the gzipped Dukascopy M30 feed for a symbol, decodes it, and
    aggregates it into daily (D1) bars in the exact shape ``MarketAnalyzer``
    consumes. Per-symbol scaling metadata is fetched once and cached on the
    instance for the duration of a run (Requirements 1.4, 8.3).
    """

    def __init__(self, min_bars: int = DEFAULT_MIN_BARS):
        """Initialise the retriever.

        Args:
            min_bars: The minimum number of daily bars that must be produced;
                defaults to the Long_Period_SMA window (200). Fewer bars than
                this raises :class:`InsufficientDataError` (Requirement 5).
        """
        self.min_bars = min_bars
        # Symbol metadata is fetched at most once per instance/run.
        self._metadata_cache: dict | None = None

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Validate and normalise a symbol to an uppercase 6-letter code.

        Strips surrounding whitespace, requires exactly six alphabetic
        characters, and uppercases the result (input is treated
        case-insensitively). Validation happens before any network call
        (Requirements 8.1, 8.4).

        Args:
            symbol: The caller-supplied symbol.

        Returns:
            The normalised uppercase symbol.

        Raises:
            InvalidSymbolError: If ``symbol`` is not exactly six alphabetic
                characters (Requirement 8.4).
        """
        candidate = (symbol or "").strip()
        if len(candidate) != SYMBOL_LENGTH or not candidate.isalpha():
            raise InvalidSymbolError(
                f"Invalid symbol {symbol!r}: expected exactly {SYMBOL_LENGTH} "
                f"alphabetic characters (a currency pair code)"
            )
        return candidate.upper()

    def _get_metadata(self) -> dict:
        """Return the symbol metadata dict, fetching and caching it once.

        Returns:
            The full metadata dict keyed by symbol.
        """
        if self._metadata_cache is None:
            self._metadata_cache = feed.fetch_symbol_metadata()
        return self._metadata_cache

    def _get_scales(self, symbol: str) -> tuple[int, int]:
        """Look up the price and volume scales for ``symbol``.

        Args:
            symbol: The normalised uppercase symbol.

        Returns:
            A ``(price_scale, volume_scale)`` tuple.

        Raises:
            SymbolMetadataError: If the metadata is missing the symbol or does
                not carry both ``priceScale`` and ``volumeScale``
                (Requirement 1.5).
        """
        metadata = self._get_metadata()
        entry = metadata.get(symbol) if isinstance(metadata, dict) else None
        if not isinstance(entry, dict):
            raise SymbolMetadataError(f"Symbol metadata does not contain an entry for {symbol!r}")
        price_scale = entry.get("priceScale")
        volume_scale = entry.get("volumeScale")
        if price_scale is None or volume_scale is None:
            raise SymbolMetadataError(f"Symbol metadata for {symbol!r} is missing priceScale/volumeScale")
        return price_scale, volume_scale

    def get_daily_dataframe(self, symbol: str = DEFAULT_SYMBOL) -> pd.DataFrame:
        """Retrieve, decode, and aggregate daily bars for ``symbol``.

        Executes the full pipeline: validate the symbol, resolve its scaling
        metadata, download the M30 feed, decode it, aggregate to daily bars,
        and enforce the empty-feed and sufficiency checks.

        Args:
            symbol: The 6-character currency pair code, treated
                case-insensitively. Defaults to ``"GBPUSD"`` (Requirement 8.2).

        Returns:
            An Analysis_DataFrame with columns
            ``["Date", "Open", "High", "Low", "Close", "Volume"]``, sorted
            ascending by ``Date`` and containing at least ``min_bars`` rows.

        Raises:
            InvalidSymbolError: If the symbol is not a valid 6-letter code,
                raised before any network call (Requirement 8.4).
            SymbolMetadataError: If the symbol's scaling metadata is missing
                (Requirement 1.5).
            FeedNetworkError: On a network/socket failure fetching the feed
                (Requirement 6.1).
            FeedHTTPError: On a non-200 HTTP status fetching the feed
                (Requirement 6.2).
            FeedDecodeError: If the feed cannot be decompressed or has an
                invalid record size (Requirements 6.4, 2.3).
            EmptyFeedError: If the feed decodes to zero records or produces no
                daily bars (Requirement 6.3).
            InsufficientDataError: If fewer than ``min_bars`` daily bars are
                produced; no partial set is returned (Requirement 5.2).
        """
        # 1. Validate the symbol before any network call (Requirements 8.1, 8.4).
        normalized = self._normalize_symbol(symbol)

        # 2. Resolve the per-symbol scales (Requirements 1.4, 1.5).
        price_scale, volume_scale = self._get_scales(normalized)

        # 3. Fetch the raw gzipped M30 feed; network/HTTP errors propagate
        #    from feed.py per Requirements 6.1/6.2.
        raw_gz_bytes = feed.fetch_feed(normalized, period=M30_PERIOD)

        # 4. Decode the binary feed into intraday records (Requirement 2).
        records = decode_feed(raw_gz_bytes, price_scale, volume_scale)

        # 6. Empty feed is an error at the orchestrator layer (Requirement 6.3).
        if not records:
            raise EmptyFeedError(f"Feed for {normalized!r} decoded to zero records")

        # 5. Aggregate intraday records into daily bars (Requirement 3).
        daily = aggregate_to_daily(records)

        # A non-empty feed that yields no daily bars is still an empty feed.
        if daily.empty:
            raise EmptyFeedError(f"Feed for {normalized!r} produced zero daily bars")

        # 7. Sufficiency check; never return a partial set (Requirements 5.1, 5.2).
        if len(daily) < self.min_bars:
            raise InsufficientDataError(
                f"Only {len(daily)} daily bars available for {normalized!r}; " f"at least {self.min_bars} are required"
            )

        # 8. Return the Analysis_DataFrame.
        return daily


def get_daily_dataframe(
    symbol: str = DEFAULT_SYMBOL,
    min_bars: int = DEFAULT_MIN_BARS,
) -> pd.DataFrame:
    """Retrieve a daily-bar Analysis_DataFrame for ``symbol``.

    Module-level convenience wrapper around :class:`Forex_Data_Retriever` that
    matches the public API used by ``app_forex.py``.

    Args:
        symbol: The 6-character currency pair code, treated case-insensitively.
            Defaults to ``"GBPUSD"`` (Requirement 8.2).
        min_bars: The minimum number of daily bars required; defaults to the
            Long_Period_SMA window (200).

    Returns:
        The Analysis_DataFrame produced by
        :meth:`Forex_Data_Retriever.get_daily_dataframe`.
    """
    return Forex_Data_Retriever(min_bars=min_bars).get_daily_dataframe(symbol)
