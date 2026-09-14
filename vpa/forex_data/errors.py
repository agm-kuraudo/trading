"""Typed exception hierarchy for the browserless forex retriever.

All failures raise a subclass of :class:`ForexRetrievalError` and return no
data, so the scheduled job fails loudly rather than analysing bad data.
"""


class ForexRetrievalError(Exception):
    """Base class for all forex retrieval failures."""


class InvalidSymbolError(ForexRetrievalError):
    """Symbol is not a valid 6-character currency pair (Requirement 8.4)."""


class SymbolMetadataError(ForexRetrievalError):
    """Metadata unavailable or no price/volume scales for the symbol (Requirement 1.5)."""


class FeedNetworkError(ForexRetrievalError):
    """Network failure reaching the feed or metadata endpoint (Requirement 6.1)."""


class FeedHTTPError(ForexRetrievalError):
    """Non-200 HTTP status when fetching the feed (Requirement 6.2).

    Stores the HTTP ``status_code`` returned by the server.
    """

    def __init__(self, status_code, message: str | None = None):
        self.status_code = status_code
        if message is None:
            message = f"Feed request failed with HTTP status {status_code}"
        super().__init__(message)


class FeedDecodeError(ForexRetrievalError):
    """Feed bytes could not be gunzipped or have an invalid record size (Requirements 6.4, 2.3)."""


class EmptyFeedError(ForexRetrievalError):
    """Feed decoded to zero records (Requirement 6.3)."""


class InsufficientDataError(ForexRetrievalError):
    """Fewer daily bars than the long-period SMA window requires (Requirement 5.2)."""
