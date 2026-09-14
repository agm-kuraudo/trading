"""Backfill acceptance test for SPY (SP-349, Task 7.2).

This is the acceptance evidence for the backfill script: backfill ``SPY`` at the
``1d`` interval, read it back **offline** via ``get_ohlcv``, and assert the result
is non-empty, ordered ascending by ``Date``, and idempotent when the backfill is
re-run (no duplicate bars). It exercises the exact ``backfill(ticker, interval)``
flow in ``scripts/backfill_market_data.py`` (``yf.download`` ->
``normalise_yf_download`` -> ``repo.upsert_bars``).

Two layers are provided:

1. **Always-run (no network, no DB)** — the default suite runs this. It monkeypatches
   ``yfinance.download`` (as ``scripts.backfill_market_data.yf.download``) to return a
   small deterministic raw daily SPY-like frame, and monkeypatches
   ``scripts.backfill_market_data.MarketDataRepository`` so ``backfill()`` builds a
   repository bound to an in-memory fake connection (the same fake-connection pattern
   used by ``test_market_data_repository_integration``). This validates Requirements
   6.2 (idempotent re-run) and 6.3 (SPY acceptance evidence) with zero external
   dependencies.

2. **Gated real-DB + real-network** — an opt-in acceptance test guarded by the
   ``MARKET_DATA_TEST_DSN`` environment variable (matching the existing gating
   convention). When enabled it actually backfills ``SPY`` over the network into the
   test DB, reads a recent range back offline, and asserts non-empty, ascending, and
   idempotent-on-re-run. It SKIPS by default.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

import scripts.backfill_market_data as backfill_mod
from vpa.market_data.repository import MarketDataRepository

# Reuse the in-memory psycopg2-like fake-connection pattern from the repository
# integration tests (single source of truth for the fake store).
from vpa.tests.test_market_data_repository_integration import make_conn_factory

# ---------------------------------------------------------------------------
# Deterministic raw SPY-like yfinance download (single-ticker MultiIndex shape)
# ---------------------------------------------------------------------------

# Five consecutive business days (Mon–Fri), matching what yf.download period="max"
# would yield in miniature for a daily series.
FAKE_SPY_DATES = pd.bdate_range("2024-01-02", periods=5)
FAKE_SPY_N = len(FAKE_SPY_DATES)


def _make_raw_yf_download() -> pd.DataFrame:
    """Build a raw single-ticker yfinance-style daily frame for SPY.

    Mirrors ``yf.download("SPY", ...)`` for a single ticker: a ``DatetimeIndex``
    named ``Date`` and a two-level ``MultiIndex`` column axis whose first level is
    the OHLCV field and second level is the ticker. ``normalise_yf_download`` flattens
    this via ``get_level_values(0)``.
    """
    n = FAKE_SPY_N
    data = {
        ("Open", "SPY"): [100.0 + i for i in range(n)],
        ("High", "SPY"): [110.0 + i for i in range(n)],
        ("Low", "SPY"): [90.0 + i for i in range(n)],
        ("Close", "SPY"): [105.0 + i for i in range(n)],
        ("Volume", "SPY"): [1_000_000 + i for i in range(n)],
    }
    df = pd.DataFrame(data, index=FAKE_SPY_DATES)
    df.index.name = "Date"
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


# ===========================================================================
# Layer 1 — ALWAYS-RUN acceptance test (no network, no DB)
# ===========================================================================


@pytest.fixture
def fake_backfill(monkeypatch):
    """Wire ``backfill()`` to a deterministic raw frame and a fake-backed repo.

    Returns ``(store, conn_factory)`` so the test can inspect the shared in-memory
    store. Monkeypatches:

    - ``scripts.backfill_market_data.yf.download`` -> returns the deterministic raw
      SPY frame (no network).
    - ``scripts.backfill_market_data.MarketDataRepository`` -> a factory that builds a
      real ``MarketDataRepository`` bound to the shared fake ``conn_factory`` (no DB).
    """
    store, conn_factory = make_conn_factory()

    def fake_download(*args, **kwargs):
        return _make_raw_yf_download()

    def repo_factory(*args, **kwargs):
        # backfill() calls MarketDataRepository() with no args; ignore any and bind
        # the fake conn_factory so writes land in the shared in-memory store.
        return MarketDataRepository(conn_factory=conn_factory)

    monkeypatch.setattr(backfill_mod.yf, "download", fake_download)
    monkeypatch.setattr(backfill_mod, "MarketDataRepository", repo_factory)

    return store, conn_factory


def test_backfill_spy_first_run_inserts_all_bars(fake_backfill):
    """First backfill of SPY 1d inserts one bar per business day, none updated."""
    result = backfill_mod.backfill("SPY", "1d")

    assert result == {"inserted": FAKE_SPY_N, "updated": 0}


def test_backfill_spy_readback_is_nonempty_and_ordered(fake_backfill):
    """After backfill, an offline get_ohlcv returns a non-empty, ascending frame."""
    store, conn_factory = fake_backfill
    backfill_mod.backfill("SPY", "1d")

    repo = MarketDataRepository(conn_factory=conn_factory)
    out = repo.get_ohlcv("SPY", "1d", "2024-01-01", "2024-01-31")

    # Non-empty, canonical shape, exactly the N business days we backfilled.
    assert not out.empty
    assert len(out) == FAKE_SPY_N
    assert list(out.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]

    # Ordered ascending by Date.
    dates = list(out["Date"])
    assert dates == sorted(dates)


def test_backfill_spy_rerun_is_idempotent_no_duplicates(fake_backfill):
    """Re-running the backfill updates every bar and inserts none (PK invariant)."""
    store, conn_factory = fake_backfill

    first = backfill_mod.backfill("SPY", "1d")
    second = backfill_mod.backfill("SPY", "1d")

    assert first == {"inserted": FAKE_SPY_N, "updated": 0}
    # Idempotent re-run: all rows updated, nothing inserted (Req 6.2).
    assert second == {"inserted": 0, "updated": FAKE_SPY_N}

    # No duplicate (ticker, interval, ts) rows accumulated in the store.
    assert len(store) == FAKE_SPY_N

    # The read-back after re-run is unchanged: still N ordered rows.
    repo = MarketDataRepository(conn_factory=conn_factory)
    out = repo.get_ohlcv("SPY", "1d", "2024-01-01", "2024-01-31")
    assert len(out) == FAKE_SPY_N
    assert list(out["Date"]) == sorted(out["Date"])


# ===========================================================================
# Layer 2 — GATED real-DB + real-network acceptance test (opt-in only)
# Set MARKET_DATA_TEST_DSN (and ensure the market_data schema exists) to run it.
# ===========================================================================


@pytest.mark.skipif(
    not os.environ.get("MARKET_DATA_TEST_DSN"),
    reason="MARKET_DATA_TEST_DSN not set; skipping live-DB + live-network backfill acceptance test",
)
def test_backfill_spy_real_db_acceptance(monkeypatch):  # pragma: no cover - opt-in only
    """Real acceptance: backfill SPY over the network into the test DB, read back.

    Runs the true ``backfill("SPY", "1d")`` flow against the DSN-configured test
    database (hitting the live yfinance network), then reads a recent range back
    offline and asserts it is non-empty and ascending, and that a second backfill
    adds no new rows (idempotent). Opt-in only; never runs in the default suite.
    """
    import psycopg2  # imported lazily so the default suite never needs it.

    dsn = os.environ["MARKET_DATA_TEST_DSN"]

    def conn_factory():
        return psycopg2.connect(dsn)

    # Bind backfill()'s repository to the real test DB (leave yf.download live).
    def repo_factory(*args, **kwargs):
        return MarketDataRepository(conn_factory=conn_factory)

    monkeypatch.setattr(backfill_mod, "MarketDataRepository", repo_factory)

    # First backfill: seeds the deepest SPY history.
    first = backfill_mod.backfill("SPY", "1d")
    assert first["inserted"] > 0

    # Second backfill: idempotent — adds no new rows (Req 6.2).
    second = backfill_mod.backfill("SPY", "1d")
    assert second["inserted"] == 0

    # Read a recent range back offline and assert non-empty + ascending (Req 6.3).
    repo = MarketDataRepository(conn_factory=conn_factory)
    end = pd.Timestamp.utcnow().normalize()
    start = end - pd.Timedelta(days=30)
    out = repo.get_ohlcv("SPY", "1d", start.to_pydatetime(), end.to_pydatetime())

    assert not out.empty
    assert list(out["Date"]) == sorted(out["Date"])
