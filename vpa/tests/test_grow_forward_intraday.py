"""Smoke test for the grow-forward intraday job (SP-379, Task 9.4).

Hermetic test (no DB, no live IG): drives ``grow_forward`` with a stubbed repository
and a fixed ``now`` and asserts it iterates the intervals, returns the per-interval
summary, derives 4h from the refreshed 1h series (zero extra IG call), and that the
``main`` entrypoint exits non-zero when a fetch raises.
"""

from __future__ import annotations

import pandas as pd
import pytest

from vpa.scripts import grow_forward_intraday as gf

pytestmark = pytest.mark.usefixtures("no_ig_network")


def _canonical_1h(start, n):
    dates = pd.date_range(start=pd.Timestamp(start, tz="UTC"), periods=n, freq="1h")
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [100.0 + i for i in range(n)],
            "High": [110.0 + i for i in range(n)],
            "Low": [90.0 + i for i in range(n)],
            "Close": [105.0 + i for i in range(n)],
            "Volume": [1_000 + i for i in range(n)],
        }
    )


class _FakeRepo:
    """A stubbed repository recording read-through and upsert calls per interval."""

    def __init__(self, one_h_frame=None, fail=False):
        self._one_h = one_h_frame if one_h_frame is not None else _canonical_1h("2024-01-02 12:00:00", 8)
        self._fail = fail
        self.load_calls = []
        self.upsert_calls = []

    def load_ohlcv(self, ticker, interval, start, end):
        if self._fail:
            raise RuntimeError("boom")
        self.load_calls.append(interval)
        # Native read-through returns the stored frame for the interval.
        return self._one_h if interval == "1h" else self._one_h.head(2)

    def get_ohlcv(self, ticker, interval, start, end):
        # Used by the derived-4h path to read the freshly-refreshed 1h series.
        return self._one_h if interval == "1h" else self._one_h.head(0)

    def upsert_bars(self, df, ticker, interval, source=None, adjusted=None):
        self.upsert_calls.append({"interval": interval, "rows": len(df), "source": source})
        return {"inserted": len(df), "updated": 0}


def test_grow_forward_iterates_intervals_and_returns_summary():
    repo = _FakeRepo()
    now = pd.Timestamp("2024-01-05 18:00:00", tz="UTC")  # a Friday

    summary = gf.grow_forward(repo=repo, now=now)

    # Every configured interval appears in the summary.
    assert set(summary) == set(gf.INTERVALS)
    for counts in summary.values():
        assert set(counts) == {"fetched", "inserted", "updated"}

    # 1h was grown (read-through); it is processed before 4h.
    assert "1h" in repo.load_calls
    assert repo.load_calls.index("15m") < repo.load_calls.index("1h")


def test_grow_forward_derives_4h_without_extra_ig_call():
    repo = _FakeRepo()
    now = pd.Timestamp("2024-01-05 18:00:00", tz="UTC")

    gf.grow_forward(repo=repo, now=now, hour4_native=False)

    # Derived path: 4h is NOT read-through (no load for 4h), it is upserted from 1h.
    assert "4h" not in repo.load_calls
    four_h_upserts = [c for c in repo.upsert_calls if c["interval"] == "4h"]
    assert four_h_upserts, "expected a derived 4h upsert"
    assert all(c["source"] == "ig" for c in four_h_upserts)


def test_main_returns_nonzero_on_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("fetch failed")

    monkeypatch.setattr(gf, "grow_forward", boom)
    assert gf.main([]) == 1
