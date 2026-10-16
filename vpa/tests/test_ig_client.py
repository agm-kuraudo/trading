"""Unit + property tests for the read-only IG client (SP-379, Tasks 2.5, 2.6).

Exercises ``IGClient.login`` / ``fetch_prices`` against a MOCKED HTTP transport so
no live IG call is ever made (the ``no_ig_network`` guard is applied at module scope
as defence-in-depth). Credentials are supplied via a temporary ``.env`` passed to the
client's ``env_path`` so the real project ``.env`` is never read.

Covers:
- Task 2.5 - ``login`` captures tokens on 200, raises ``IGAuthError`` with no tokens
  on non-200, raises (no HTTP) on missing creds; ``fetch_prices`` builds the right
  URL/headers and parses ``prices`` + ``allowance``, and re-logs in on an absent/
  expired session.
- SP-382 Task 3.2 - ``fetch_prices_range`` builds the new path form
  (``/prices/{epic}/{resolution}/{startDate}/{endDate}``, ``Version: 2``, dates
  ``yyyy-MM-dd HH:mm:ss``), sends auth headers, parses ``prices`` + ``allowance``,
  raises ``IGAuthError`` on non-200 of both forms, falls back to the older
  query-string form (``?startdate=...&enddate=...``, ``Version: 1``, dates
  ``yyyy:MM:dd-HH:mm:ss``) when the new form is unavailable, and re-logs in on an
  absent/expired session.
- Task 2.6 / Property 7 - read-only surface: ``IGClient`` exposes only ``login``,
  ``fetch_prices`` and ``fetch_prices_range`` and has no deal/order/position method.
"""

from __future__ import annotations

import pandas as pd
import pytest

from vpa.market_data.ig_client import (
    IG_DEMO_BASE,
    IG_LIVE_BASE,
    IG_RANGE_FMT_NEW,
    IG_RANGE_FMT_OLD,
    IGAuthError,
    IGClient,
)

pytestmark = pytest.mark.usefixtures("no_ig_network")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeResponse:
    """A minimal requests-like response with status, headers and a JSON body."""

    def __init__(self, status_code=200, headers=None, json_body=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json = json_body if json_body is not None else {}

    def json(self):
        return self._json


class FakeHTTP:
    """A fake HTTP transport recording calls and returning scripted responses."""

    def __init__(self, post_response=None, get_response=None):
        self._post_response = post_response
        self._get_response = get_response
        self.post_calls = []
        self.get_calls = []

    def post(self, url, headers=None, json=None):
        self.post_calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        return self._post_response

    def get(self, url, headers=None):
        self.get_calls.append({"url": url, "headers": headers or {}})
        return self._get_response


class SequencedHTTP(FakeHTTP):
    """A fake transport that returns a scripted sequence of GET responses in order.

    Used for ``fetch_prices_range`` fallback coverage, where the first (new-form) GET
    returns a non-200 and the second (old-form) GET returns 200. The last response is
    reused if more GETs are made than were scripted.
    """

    def __init__(self, post_response=None, get_responses=None):
        super().__init__(post_response=post_response)
        self._get_responses = list(get_responses or [])

    def get(self, url, headers=None):
        self.get_calls.append({"url": url, "headers": headers or {}})
        index = min(len(self.get_calls) - 1, len(self._get_responses) - 1)
        return self._get_responses[index]


def _write_live_env(tmp_path, api_key="live-key", user="live-user", pwd="live-pwd"):
    """Write a temp ``.env`` with the live IG credentials and return its path."""
    path = tmp_path / ".env"
    path.write_text(
        f"IG_API_KEY={api_key}\nIG_USER_ID={user}\nIG_PWD={pwd}\n",
        encoding="utf-8",
    )
    return str(path)


def _ok_session_response():
    return FakeResponse(
        status_code=200,
        headers={"CST": "cst-token", "X-SECURITY-TOKEN": "sec-token"},
    )


# ---------------------------------------------------------------------------
# Task 2.5 - login
# ---------------------------------------------------------------------------


def test_login_captures_tokens_on_200(tmp_path):
    http = FakeHTTP(post_response=_ok_session_response())
    client = IGClient(env_path=_write_live_env(tmp_path), http=http)

    client.login()

    assert len(http.post_calls) == 1
    call = http.post_calls[0]
    assert call["url"] == f"{IG_LIVE_BASE}/session"
    assert call["headers"]["X-IG-API-KEY"] == "live-key"
    assert call["headers"]["Version"] == "2"
    assert call["json"] == {"identifier": "live-user", "password": "live-pwd"}
    # Tokens captured from response headers.
    assert client._cst == "cst-token"
    assert client._security_token == "sec-token"


def test_login_non_200_raises_and_holds_no_tokens(tmp_path):
    http = FakeHTTP(post_response=FakeResponse(status_code=401))
    client = IGClient(env_path=_write_live_env(tmp_path), http=http)

    with pytest.raises(IGAuthError):
        client.login()

    assert client._cst is None
    assert client._security_token is None
    assert client._session_expiry is None


def test_login_missing_credentials_raises_without_http(tmp_path):
    # Empty .env -> all required keys missing.
    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    http = FakeHTTP(post_response=_ok_session_response())
    client = IGClient(env_path=str(path), http=http)

    with pytest.raises(RuntimeError):
        client.login()

    # No HTTP call was performed when credentials are missing.
    assert http.post_calls == []


def test_demo_flag_selects_demo_base_url(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "IG_DEMO_API_KEY=d-key\nIG_DEMO_USER_ID=d-user\nIG_DEMO_PWD=d-pwd\n",
        encoding="utf-8",
    )
    http = FakeHTTP(post_response=_ok_session_response())
    client = IGClient(demo=True, env_path=str(path), http=http)

    client.login()

    assert http.post_calls[0]["url"] == f"{IG_DEMO_BASE}/session"


# ---------------------------------------------------------------------------
# Task 2.5 - fetch_prices
# ---------------------------------------------------------------------------


def test_fetch_prices_builds_url_headers_and_parses_body(tmp_path):
    prices_body = {"prices": [{"snapshotTime": "2024:01:02-14:00:00"}], "allowance": {"remainingAllowance": 9_900}}
    http = FakeHTTP(
        post_response=_ok_session_response(),
        get_response=FakeResponse(status_code=200, json_body=prices_body),
    )
    client = IGClient(env_path=_write_live_env(tmp_path), http=http)
    client.login()

    out = client.fetch_prices("IX.D.SPTRD.DAILY.IP", "HOUR", 10)

    assert len(http.get_calls) == 1
    call = http.get_calls[0]
    assert call["url"] == f"{IG_LIVE_BASE}/prices/IX.D.SPTRD.DAILY.IP/HOUR/10"
    assert call["headers"]["X-IG-API-KEY"] == "live-key"
    assert call["headers"]["CST"] == "cst-token"
    assert call["headers"]["X-SECURITY-TOKEN"] == "sec-token"
    assert call["headers"]["Version"] == "2"
    assert out["prices"] == prices_body["prices"]
    assert out["allowance"] == prices_body["allowance"]


def test_fetch_prices_logs_in_when_session_absent(tmp_path):
    prices_body = {"prices": [], "allowance": {}}
    http = FakeHTTP(
        post_response=_ok_session_response(),
        get_response=FakeResponse(status_code=200, json_body=prices_body),
    )
    client = IGClient(env_path=_write_live_env(tmp_path), http=http)

    # No explicit login() call: fetch_prices must trigger one.
    client.fetch_prices("IX.D.SPTRD.DAILY.IP", "MINUTE_15", 5)

    assert len(http.post_calls) == 1  # auto-login happened
    assert len(http.get_calls) == 1


# ---------------------------------------------------------------------------
# SP-382 Task 3.2 - fetch_prices_range (dated from/to window)
# ---------------------------------------------------------------------------


def _window_bounds():
    """Return a tz-aware UTC (start, end) pair for the dated-window tests."""
    start = pd.Timestamp("2024-01-02 14:00:00", tz="UTC")
    end = pd.Timestamp("2024-01-09 14:00:00", tz="UTC")
    return start, end


def test_fetch_prices_range_builds_new_form_url_headers_and_parses_body(tmp_path):
    """New (path) form: /prices/{epic}/{resolution}/{startDate}/{endDate}, Version 2.

    Validates: Requirements 2.5
    """
    prices_body = {"prices": [{"snapshotTime": "2024:01:02-14:00:00"}], "allowance": {"remainingAllowance": 9_800}}
    http = FakeHTTP(
        post_response=_ok_session_response(),
        get_response=FakeResponse(status_code=200, json_body=prices_body),
    )
    client = IGClient(env_path=_write_live_env(tmp_path), http=http)
    client.login()

    start, end = _window_bounds()
    out = client.fetch_prices_range("IX.D.SPTRD.DAILY.IP", "HOUR", start, end)

    assert len(http.get_calls) == 1
    call = http.get_calls[0]
    expected_start = start.strftime(IG_RANGE_FMT_NEW)
    expected_end = end.strftime(IG_RANGE_FMT_NEW)
    assert call["url"] == f"{IG_LIVE_BASE}/prices/IX.D.SPTRD.DAILY.IP/HOUR/{expected_start}/{expected_end}"
    assert call["headers"]["X-IG-API-KEY"] == "live-key"
    assert call["headers"]["CST"] == "cst-token"
    assert call["headers"]["X-SECURITY-TOKEN"] == "sec-token"
    assert call["headers"]["Version"] == "2"
    assert out["prices"] == prices_body["prices"]
    assert out["allowance"] == prices_body["allowance"]


def test_fetch_prices_range_falls_back_to_old_query_string_form(tmp_path):
    """Old (query-string) form fallback when the new form is unavailable, Version 1.

    Validates: Requirements 2.5
    """
    prices_body = {"prices": [{"snapshotTime": "2024:01:02-14:00:00"}], "allowance": {"remainingAllowance": 9_700}}
    http = SequencedHTTP(
        post_response=_ok_session_response(),
        get_responses=[
            FakeResponse(status_code=404),  # new form unavailable for this epic
            FakeResponse(status_code=200, json_body=prices_body),  # old form succeeds
        ],
    )
    client = IGClient(env_path=_write_live_env(tmp_path), http=http)
    client.login()

    start, end = _window_bounds()
    out = client.fetch_prices_range("IX.D.SPTRD.DAILY.IP", "HOUR", start, end)

    assert len(http.get_calls) == 2
    new_call, old_call = http.get_calls
    new_start = start.strftime(IG_RANGE_FMT_NEW)
    new_end = end.strftime(IG_RANGE_FMT_NEW)
    assert new_call["url"] == f"{IG_LIVE_BASE}/prices/IX.D.SPTRD.DAILY.IP/HOUR/{new_start}/{new_end}"
    assert new_call["headers"]["Version"] == "2"

    old_start = start.strftime(IG_RANGE_FMT_OLD)
    old_end = end.strftime(IG_RANGE_FMT_OLD)
    assert old_call["url"] == (
        f"{IG_LIVE_BASE}/prices/IX.D.SPTRD.DAILY.IP/HOUR?startdate={old_start}&enddate={old_end}"
    )
    assert old_call["headers"]["Version"] == "1"
    assert old_call["headers"]["X-IG-API-KEY"] == "live-key"
    assert old_call["headers"]["CST"] == "cst-token"
    assert old_call["headers"]["X-SECURITY-TOKEN"] == "sec-token"
    assert out["prices"] == prices_body["prices"]
    assert out["allowance"] == prices_body["allowance"]


def test_fetch_prices_range_non_200_on_both_forms_raises(tmp_path):
    """IGAuthError is raised when both the new and old forms return non-200.

    Validates: Requirements 2.5
    """
    http = SequencedHTTP(
        post_response=_ok_session_response(),
        get_responses=[
            FakeResponse(status_code=404),  # new form unavailable
            FakeResponse(status_code=500),  # old form also fails
        ],
    )
    client = IGClient(env_path=_write_live_env(tmp_path), http=http)
    client.login()

    start, end = _window_bounds()
    with pytest.raises(IGAuthError):
        client.fetch_prices_range("IX.D.SPTRD.DAILY.IP", "HOUR", start, end)

    assert len(http.get_calls) == 2


def test_fetch_prices_range_logs_in_when_session_absent(tmp_path):
    """Auto-login (reset-on-use) when no valid session is held.

    Validates: Requirements 2.5
    """
    prices_body = {"prices": [], "allowance": {}}
    http = FakeHTTP(
        post_response=_ok_session_response(),
        get_response=FakeResponse(status_code=200, json_body=prices_body),
    )
    client = IGClient(env_path=_write_live_env(tmp_path), http=http)

    # No explicit login() call: fetch_prices_range must trigger one.
    start, end = _window_bounds()
    client.fetch_prices_range("IX.D.SPTRD.DAILY.IP", "MINUTE_15", start, end)

    assert len(http.post_calls) == 1  # auto-login happened
    assert len(http.get_calls) == 1


# ---------------------------------------------------------------------------
# Task 2.6 / Property 7 - read-only surface
# ---------------------------------------------------------------------------


def test_read_only_surface_exposes_only_login_and_fetch_prices():
    """Property 7: no deal/order/position surface on the client.

    Validates: Requirements 1.3
    """
    public_methods = {name for name in dir(IGClient) if not name.startswith("_") and callable(getattr(IGClient, name))}
    assert public_methods == {"login", "fetch_prices", "fetch_prices_range"}

    forbidden = ("deal", "order", "position", "otc", "trade", "close_position", "create_position")
    for name in dir(IGClient):
        lowered = name.lower()
        assert not any(token in lowered for token in forbidden), f"forbidden surface: {name}"
