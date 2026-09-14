"""Mocked unit tests for the network-layer error mapping in ``feed.py`` (task 6.2).

The two network-touching functions ``fetch_feed`` and ``fetch_symbol_metadata``
route every request through the module-private ``_http_get``, which is the sole
caller of ``urllib.request.urlopen``. These tests replace that single seam with
a fake ``urlopen`` (via ``monkeypatch.setattr`` on
``vpa.forex_data.feed.urllib.request.urlopen``) so NO real socket is ever opened
and the transport/protocol failure mapping can be exercised deterministically:

- ``urllib.error.HTTPError`` (non-200) -> :class:`FeedHTTPError` carrying the
  status code, and no bytes returned (Requirement 6.2).
- ``urllib.error.URLError`` / bare ``OSError`` -> :class:`FeedNetworkError`
  (Requirement 6.1).
- ``fetch_symbol_metadata`` additionally maps a non-gzip / garbage body to
  :class:`FeedDecodeError`, and returns the parsed dict on the happy path.

The URL derivation is checked by capturing the ``urllib.request.Request`` passed
to the fake ``urlopen`` and reading its ``.full_url``.

Requirements: 6.1, 6.2.
"""

import gzip
import json
import urllib.error

import pytest

from vpa.forex_data import feed
from vpa.forex_data.errors import (
    FeedDecodeError,
    FeedHTTPError,
    FeedNetworkError,
)


class _FakeResponse:
    """Minimal context-manager stand-in for a ``urlopen`` response.

    ``_http_get`` uses ``with urllib.request.urlopen(request) as response:`` and
    then calls ``response.read()``. This fake supports the context-manager
    protocol and returns the canned ``body`` bytes from ``read()``.
    """

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


def _install_urlopen(monkeypatch, handler):
    """Patch ``feed``'s ``urlopen`` with ``handler`` and capture the request URL.

    ``handler`` is called with the ``urllib.request.Request`` and may return a
    response object or raise. Returns a one-element list that will hold the
    ``full_url`` of the last request seen, so callers can assert on the derived
    URL.
    """
    captured_urls: list[str] = []

    def fake_urlopen(request, *args, **kwargs):
        captured_urls.append(request.full_url)
        return handler(request)

    monkeypatch.setattr(feed.urllib.request, "urlopen", fake_urlopen)
    return captured_urls


# ---------------------------------------------------------------------------
# fetch_feed
# ---------------------------------------------------------------------------


def test_fetch_feed_http_error_maps_to_feed_http_error(monkeypatch):
    """A non-200 ``HTTPError`` becomes ``FeedHTTPError`` with the status code.

    No bytes are returned to the caller on failure (Requirement 6.2).
    """

    def handler(request):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=None)

    _install_urlopen(monkeypatch, handler)

    with pytest.raises(FeedHTTPError) as exc_info:
        feed.fetch_feed("GBPUSD")

    assert exc_info.value.status_code == 404


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("boom"),
        OSError("socket blew up"),
    ],
)
def test_fetch_feed_transport_error_maps_to_feed_network_error(monkeypatch, error):
    """``URLError`` and a bare ``OSError`` both map to ``FeedNetworkError`` (Req 6.1)."""

    def handler(request):
        raise error

    _install_urlopen(monkeypatch, handler)

    with pytest.raises(FeedNetworkError):
        feed.fetch_feed("GBPUSD")


def test_fetch_feed_happy_path_returns_bytes_and_builds_url(monkeypatch):
    """The happy path returns the exact response bytes and builds the M30 URL.

    For symbol ``"GBPUSD"`` the derived URL must be
    ``.../dukascopy/GBPUSD30.lb.gz`` (Requirement 1.3, verified here alongside
    the transport contract).
    """
    raw_bytes = b"\x1f\x8b\x08 raw gzipped feed payload"

    captured_urls = _install_urlopen(monkeypatch, lambda request: _FakeResponse(raw_bytes))

    result = feed.fetch_feed("GBPUSD")

    assert result == raw_bytes
    assert captured_urls == ["https://data.forexsb.com/datafeed/data/dukascopy/GBPUSD30.lb.gz"]


# ---------------------------------------------------------------------------
# fetch_symbol_metadata
# ---------------------------------------------------------------------------


def test_fetch_symbol_metadata_happy_path_returns_dict(monkeypatch):
    """A gzipped JSON body decodes back to the metadata dict keyed by symbol."""
    metadata = {"GBPUSD": {"priceScale": 100000, "volumeScale": 1}}
    body = gzip.compress(json.dumps(metadata).encode())

    _install_urlopen(monkeypatch, lambda request: _FakeResponse(body))

    result = feed.fetch_symbol_metadata()

    assert result == metadata


def test_fetch_symbol_metadata_http_error_maps_to_feed_http_error(monkeypatch):
    """A non-200 ``HTTPError`` from the metadata endpoint becomes ``FeedHTTPError`` (Req 6.2)."""

    def handler(request):
        raise urllib.error.HTTPError(request.full_url, 500, "Server Error", hdrs=None, fp=None)

    _install_urlopen(monkeypatch, handler)

    with pytest.raises(FeedHTTPError) as exc_info:
        feed.fetch_symbol_metadata()

    assert exc_info.value.status_code == 500


def test_fetch_symbol_metadata_url_error_maps_to_feed_network_error(monkeypatch):
    """A ``URLError`` reaching the metadata endpoint becomes ``FeedNetworkError`` (Req 6.1)."""

    def handler(request):
        raise urllib.error.URLError("boom")

    _install_urlopen(monkeypatch, handler)

    with pytest.raises(FeedNetworkError):
        feed.fetch_symbol_metadata()


def test_fetch_symbol_metadata_garbage_body_maps_to_feed_decode_error(monkeypatch):
    """A non-gzip / garbage body cannot be gunzipped and maps to ``FeedDecodeError``."""
    _install_urlopen(monkeypatch, lambda request: _FakeResponse(b"not gzip at all"))

    with pytest.raises(FeedDecodeError):
        feed.fetch_symbol_metadata()
