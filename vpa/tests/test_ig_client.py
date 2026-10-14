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
- Task 2.6 / Property 7 - read-only surface: ``IGClient`` exposes only ``login`` and
  ``fetch_prices`` and has no deal/order/position method.
"""

from __future__ import annotations

import pytest

from vpa.market_data.ig_client import (
    IG_DEMO_BASE,
    IG_LIVE_BASE,
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
# Task 2.6 / Property 7 - read-only surface
# ---------------------------------------------------------------------------


def test_read_only_surface_exposes_only_login_and_fetch_prices():
    """Property 7: no deal/order/position surface on the client.

    Validates: Requirements 1.3
    """
    public_methods = {name for name in dir(IGClient) if not name.startswith("_") and callable(getattr(IGClient, name))}
    assert public_methods == {"login", "fetch_prices"}

    forbidden = ("deal", "order", "position", "otc", "trade", "close_position", "create_position")
    for name in dir(IGClient):
        lowered = name.lower()
        assert not any(token in lowered for token in forbidden), f"forbidden surface: {name}"
