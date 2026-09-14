"""Network boundary for the browserless forex retriever.

This module contains the only two network-touching functions in the package:
``fetch_symbol_metadata`` (per-symbol scaling info) and ``fetch_feed`` (the raw
gzipped Dukascopy binary feed). Both use only ``urllib`` from the standard
library and map transport/protocol failures onto the typed
:class:`~vpa.forex_data.errors.ForexRetrievalError` hierarchy so the scheduled
job fails loudly rather than analysing bad data (Requirements 6.1, 6.2).

``fetch_feed`` returns the raw gzipped bytes without decompressing them: the
pure :func:`vpa.forex_data.decoder.decode_feed` owns decompression so it can be
property-tested on synthetic gz buffers (Requirement 9.3).
"""

import gzip
import json
import urllib.error
import urllib.request

from vpa.forex_data.errors import (
    FeedDecodeError,
    FeedHTTPError,
    FeedNetworkError,
)

# Sent on every request; the forexsb UI issues the same Referer for its own
# in-browser downloads and the proof of concept succeeded with it in place.
_REFERER = "https://data.forexsb.com/data-app"

# Default endpoints (Requirements 1.3, 1.4).
_METADATA_URL = "https://data.forexsb.com/datafeed/info/premium.json.gz"
_FEED_BASE_URL = "https://data.forexsb.com/datafeed/data/dukascopy"


def _http_get(url: str) -> bytes:
    """Issue a GET for ``url`` with the shared Referer header and return the body.

    Args:
        url: The absolute URL to fetch.

    Returns:
        The raw response body bytes.

    Raises:
        FeedHTTPError: If the server returns a non-200 HTTP status. The
            ``status_code`` carries the returned code (Requirement 6.2).
        FeedNetworkError: If the request fails with a URL/socket-level error
            such as DNS failure, connection refused, or timeout (Requirement
            6.1).
    """
    request = urllib.request.Request(url, headers={"Referer": _REFERER})
    try:
        with urllib.request.urlopen(request) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        # A non-200 status arrives here as an HTTPError carrying ``.code``.
        raise FeedHTTPError(status_code=exc.code) from exc
    except (urllib.error.URLError, OSError) as exc:
        # URLError (and any bare socket OSError) is a transport failure.
        raise FeedNetworkError(f"Network failure fetching {url}: {exc}") from exc


def fetch_symbol_metadata(url: str = _METADATA_URL) -> dict:
    """Fetch, gunzip, and parse the per-symbol scaling metadata.

    GETs the gzipped ``premium.json.gz`` document, decompresses it, and parses
    the JSON into a dict keyed by symbol (each value holds ``priceScale`` /
    ``volumeScale`` / ``digits``).

    Args:
        url: The metadata endpoint. Defaults to the forexsb premium feed.

    Returns:
        The full metadata dict keyed by symbol.

    Raises:
        FeedHTTPError: Non-200 HTTP status (Requirement 6.2).
        FeedNetworkError: Network/socket failure reaching the endpoint
            (Requirement 6.1).
        FeedDecodeError: The body could not be gunzipped or parsed as JSON.
    """
    body = _http_get(url)
    try:
        return json.loads(gzip.decompress(body))
    except Exception as exc:
        raise FeedDecodeError(f"Failed to decode symbol metadata: {exc}") from exc


def fetch_feed(
    symbol: str,
    period: int = 30,
    base_url: str = _FEED_BASE_URL,
) -> bytes:
    """Fetch the raw gzipped Dukascopy feed for ``symbol`` at ``period``.

    Builds the URL ``{base_url}/{SYMBOL}{period}.lb.gz`` (``SYMBOL`` uppercased)
    and returns the raw gzipped bytes without decompressing them, so the pure
    decoder owns decompression (Requirement 9.3). Only minimal formatting is
    done here (``.upper()``); the orchestrator validates the symbol.

    Args:
        symbol: The currency-pair code (e.g. ``"GBPUSD"``); uppercased for the
            URL.
        period: The intraday period in minutes. Defaults to 30 (M30).
        base_url: The feed base URL. Defaults to the forexsb Dukascopy path.

    Returns:
        The raw gzipped feed bytes (not decompressed).

    Raises:
        FeedHTTPError: Non-200 HTTP status, e.g. 404 for an unsupported
            symbol/period (Requirement 6.2).
        FeedNetworkError: Network/socket failure reaching the endpoint
            (Requirement 6.1).
    """
    url = f"{base_url}/{symbol.upper()}{period}.lb.gz"
    return _http_get(url)
