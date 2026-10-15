"""Read-only IG REST client for intraday OHLCV ingestion (SP-379).

This module provides the thin, read-only IG REST layer that mirrors the existing
``fetch_yf`` -> ``normalise_yf_download`` pipeline but for IG. Its scope is strictly
read-only: session login (``POST /session``) plus historical price retrieval
(``GET /prices``) only. No deal/order/position endpoint is implemented or imported
here, so the read-only guarantee is structural (by omission).

Credentials are read from the project ``.env`` via the existing dependency-light
``vpa.market_data.db._parse_env_file`` (no new dependency, no hardcoded secrets).
Live credentials use ``IG_API_KEY`` / ``IG_USER_ID`` / ``IG_PWD``; the demo set uses
``IG_DEMO_API_KEY`` / ``IG_DEMO_USER_ID`` / ``IG_DEMO_PWD``. A ``demo`` flag selects
both the key set and the base URL. ``validate_ig_env`` reports the full set of
missing/empty keys at once, mirroring ``db.validate_env``.
"""

from __future__ import annotations

import time

import requests

from vpa.market_data.db import _DEFAULT_ENV_PATH, _parse_env_file

# Required IG credential keys read from .env (Req 1.4).
IG_LIVE_KEYS = ["IG_API_KEY", "IG_USER_ID", "IG_PWD"]
IG_DEMO_KEYS = ["IG_DEMO_API_KEY", "IG_DEMO_USER_ID", "IG_DEMO_PWD"]

# IG REST base URLs (live vs demo) — the demo flag selects between them.
IG_LIVE_BASE = "https://api.ig.com/gateway/deal"
IG_DEMO_BASE = "https://demo-api.ig.com/gateway/deal"

# IG session lifetime: ~12 hours, reset-on-use (Req 1.1).
SESSION_TTL_S = 12 * 60 * 60


def read_ig_config(demo: bool, env_path: str | None = None) -> dict:
    """Read the IG credentials from the project ``.env``.

    Reads the live keys (``IG_API_KEY`` / ``IG_USER_ID`` / ``IG_PWD``) or, when
    ``demo`` is true, the demo keys (``IG_DEMO_API_KEY`` / ``IG_DEMO_USER_ID`` /
    ``IG_DEMO_PWD``) via the existing ``db._parse_env_file``. Missing or empty keys
    are returned as empty strings rather than raising, so ``validate_ig_env`` can
    report the full set of offending keys at once (Req 1.4, 1.5). Mirrors
    ``db._read_db_config``. No new dependency, no hardcoded secrets.

    Args:
        demo: When true, read the ``IG_DEMO_*`` key set; otherwise the live keys.
        env_path: Optional explicit path to the ``.env`` file. Defaults to the
            project root ``.env`` used by ``db._parse_env_file``.

    Returns:
        A dict mapping each key in the selected key set to its value (or "").
    """
    keys = IG_DEMO_KEYS if demo else IG_LIVE_KEYS
    parsed = _parse_env_file(env_path if env_path is not None else _DEFAULT_ENV_PATH)
    config = {}
    for key in keys:
        value = parsed.get(key, "")
        config[key] = value if value is not None else ""
    return config


def validate_ig_env(config: dict, required_keys: list[str]) -> list[str]:
    """Return the list of required IG keys whose value is missing or empty.

    Mirrors ``db.validate_env`` so missing credentials are surfaced together rather
    than failing on the first one (Req 1.5).

    Args:
        config: The config dict (typically from ``read_ig_config``).
        required_keys: The keys that must be present and non-empty.

    Returns:
        The subset of ``required_keys`` that are absent or empty in ``config``.
    """
    return [key for key in required_keys if not config.get(key)]


class IGAuthError(Exception):
    """Raised when IG session authentication (``POST /session``) fails.

    Signals a non-200 response from the IG session endpoint (Req 1.6). When raised,
    the ``IGClient`` holds no session tokens, so a subsequent call must re-attempt
    ``login`` with valid credentials before any price fetch can succeed.
    """


class IGClient:
    """Read-only IG REST client for intraday OHLCV ingestion (SP-379).

    Implements ONLY session login (``POST /session``) and historical price retrieval
    (``GET /prices``). No deal/order/position endpoint is implemented or imported, so
    the read-only guarantee is structural — by omission (Req 1.3).

    Credentials are read from the project ``.env`` via the existing dependency-light
    parser (``read_ig_config`` / ``validate_ig_env``). The live key set is
    ``IG_API_KEY`` / ``IG_USER_ID`` / ``IG_PWD``; the demo set is ``IG_DEMO_*``. The
    ``demo`` flag selects both the key set and the base URL.

    The HTTP transport is injectable (``http``) so tests can pass a fake/mock transport
    and the suite stays hermetic (no live IG calls), mirroring the ``no_network``
    defence used for yfinance.
    """

    def __init__(self, *, demo: bool = False, env_path: str | None = None, http=requests):
        """Construct a read-only IG client.

        Args:
            demo: When true, use the ``IG_DEMO_*`` credential set and the demo base URL
                (``IG_DEMO_BASE``); otherwise use the live keys and ``IG_LIVE_BASE``.
            env_path: Optional explicit path to the ``.env`` file. Defaults to the
                project root ``.env`` used by ``db._parse_env_file``.
            http: Injectable HTTP transport exposing ``post``/``get`` (defaults to the
                ``requests`` module). Tests pass a fake transport for hermeticity.
        """
        self._demo = demo
        self._env_path = env_path
        self._http = http
        self._base = IG_DEMO_BASE if demo else IG_LIVE_BASE
        self._keys = IG_DEMO_KEYS if demo else IG_LIVE_KEYS
        # Session state — populated on a successful login(), cleared/absent otherwise.
        self._cst: str | None = None
        self._security_token: str | None = None
        # Monotonic expiry instant; a session is valid while time.monotonic() < this.
        self._session_expiry: float | None = None

    def login(self) -> None:
        """Authenticate against IG and hold the session tokens.

        Validates the required credentials FIRST (no HTTP is performed when any key is
        missing/empty, Req 1.5), then performs ``POST {base}/session`` (Version 2) with
        the ``X-IG-API-KEY`` header and an ``{identifier, password}`` body. On success,
        captures the ``CST`` and ``X-SECURITY-TOKEN`` response headers and holds the
        session with an expiry of ``now + SESSION_TTL_S`` (reset-on-use, Req 1.1).

        Raises:
            RuntimeError: If any required IG credential key is missing or empty. The
                error names the full set of offending keys and no HTTP is performed.
            IGAuthError: If ``POST /session`` returns a non-200 response. No session
                tokens are held when this is raised (Req 1.6).
        """
        config = read_ig_config(self._demo, self._env_path)
        missing = validate_ig_env(config, self._keys)
        if missing:
            raise RuntimeError("Missing or empty IG credential keys: " + ", ".join(missing))

        api_key, user_key, pwd_key = self._keys
        headers = {
            "X-IG-API-KEY": config[api_key],
            "Version": "2",
            "Content-Type": "application/json",
            "Accept": "application/json; charset=UTF-8",
        }
        payload = {
            "identifier": config[user_key],
            "password": config[pwd_key],
        }

        response = self._http.post(f"{self._base}/session", headers=headers, json=payload)
        if response.status_code != 200:
            # Hold no tokens on failure (Req 1.6).
            self._cst = None
            self._security_token = None
            self._session_expiry = None
            raise IGAuthError(f"IG session login failed with status {response.status_code}")

        self._cst = response.headers.get("CST")
        self._security_token = response.headers.get("X-SECURITY-TOKEN")
        self._session_expiry = time.monotonic() + SESSION_TTL_S

    def _session_valid(self) -> bool:
        """Return whether a usable (non-expired) session is currently held.

        A session is valid only when both tokens are held and the reset-on-use expiry
        instant has not yet passed (``time.monotonic() < self._session_expiry``).
        """
        return (
            self._cst is not None
            and self._security_token is not None
            and self._session_expiry is not None
            and time.monotonic() < self._session_expiry
        )

    def fetch_prices(self, epic: str, resolution: str, num_points: int) -> dict:
        """Fetch historical price bars for an epic (read-only, ``GET /prices``).

        Ensures a valid (non-expired) session first, re-logging in via ``login`` when
        the session is absent or expired (reset-on-use, Req 1.1), then performs a single
        ``GET {base}/prices/{epic}/{resolution}/{num_points}`` request with the auth
        headers (``X-IG-API-KEY`` / ``CST`` / ``X-SECURITY-TOKEN``) and ``Version: 2``
        (Req 1.2). On a successful fetch the session expiry is reset (reset-on-use).

        This is the only data-retrieval method on the client; no deal/order/position
        endpoint is called, so the read-only guarantee is structural (Req 1.3).

        Args:
            epic: The IG instrument identifier (e.g. ``IX.D.SPTRD.DAILY.IP``).
            resolution: The IG resolution tag; ``MINUTE_15`` or ``HOUR`` (``HOUR_4`` is
                probed later for the 4h scope addition).
            num_points: The number of most-recent bars to request.

        Returns:
            A dict ``{"prices": [...], "allowance": {...}}`` parsed from the IG JSON
            response: the list of price bars and the allowance block.

        Raises:
            IGAuthError: If a required ``login`` re-attempt fails, or if the price
                request returns a non-200 response.
        """
        if not self._session_valid():
            self.login()

        config = read_ig_config(self._demo, self._env_path)
        api_key = self._keys[0]
        headers = {
            "X-IG-API-KEY": config[api_key],
            "CST": self._cst,
            "X-SECURITY-TOKEN": self._security_token,
            "Version": "2",
            "Accept": "application/json; charset=UTF-8",
        }

        url = f"{self._base}/prices/{epic}/{resolution}/{num_points}"
        response = self._http.get(url, headers=headers)
        if response.status_code != 200:
            raise IGAuthError(f"IG price fetch failed with status {response.status_code}")

        # Reset-on-use: a successful fetch extends the session lifetime (Req 1.1).
        self._session_expiry = time.monotonic() + SESSION_TTL_S

        body = response.json()
        return {
            "prices": body.get("prices", []),
            "allowance": body.get("allowance", {}),
        }
