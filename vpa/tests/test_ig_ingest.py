"""Unit + property tests for IG normalisation and 4h resample (SP-379).

Covers spec Tasks 3.2-3.5 and 3.7 - pure-logic tests for
``vpa.market_data.ig_ingest``: ``_mid``, ``normalise_ig_prices``, ``resample_1h_to_4h``
and ``probe_hour4``. No network is touched (``no_ig_network`` applied at module scope);
``probe_hour4`` is driven by a tiny fake client.

Properties validated:
- Property 1 (mid is bracketed)       - Task 3.3
- Property 2 (canonical output shape) - Task 3.4
- Property 3 (UTC bar-open)           - Task 3.5
- Property 9 (4h resample integrity)  - Task 3.7
"""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from vpa.market_data.ig_ingest import (
    IG_SNAPSHOT_FMT,
    _mid,
    normalise_ig_prices,
    probe_hour4,
    resample_1h_to_4h,
)
from vpa.market_data.ohlcv_ingest import CANONICAL_COLUMNS

pytestmark = pytest.mark.usefixtures("no_ig_network")

_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field(bid, ask):
    return {"bid": bid, "ask": ask, "lastTraded": None}


def _bar(snapshot, o, h, low, c, volume):
    """Build an IG /prices bar where each OHLC field has bid=ask=value (mid==value)."""
    return {
        "snapshotTime": snapshot,
        "openPrice": _field(o, o),
        "highPrice": _field(h, h),
        "lowPrice": _field(low, low),
        "closePrice": _field(c, c),
        "lastTradedVolume": volume,
    }


class _FakeClient:
    """Fake IG client returning a scripted /prices payload for probe_hour4."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def fetch_prices(self, epic, resolution, num_points):
        self.calls.append((epic, resolution, num_points))
        return self._payload


# ---------------------------------------------------------------------------
# Task 3.2 - _mid and normalise_ig_prices unit tests
# ---------------------------------------------------------------------------


def test_mid_averages_bid_and_ask():
    assert _mid(_field(100.0, 102.0)) == 101.0


def test_mid_equal_bid_ask():
    assert _mid(_field(100.0, 100.0)) == 100.0


def test_mid_single_sided_uses_present_side():
    assert _mid(_field(None, 102.0)) == 102.0
    assert _mid(_field(100.0, None)) == 100.0


def test_mid_both_none_raises():
    with pytest.raises(ValueError):
        _mid(_field(None, None))


def test_normalise_maps_fields_and_parses_utc():
    raw = {
        "prices": [
            _bar("2024:01:02-14:00:00", 100.0, 110.0, 90.0, 105.0, 37_000),
            _bar("2024:01:02-15:00:00", 106.0, 112.0, 95.0, 108.0, 42_000),
        ]
    }

    df = normalise_ig_prices(raw)

    assert list(df.columns) == CANONICAL_COLUMNS
    assert len(df) == 2
    assert df.loc[0, "Open"] == 100.0
    assert df.loc[0, "High"] == 110.0
    assert df.loc[0, "Low"] == 90.0
    assert df.loc[0, "Close"] == 105.0
    assert df.loc[0, "Volume"] == 37_000
    first_ts = df.loc[0, "Date"]
    assert first_ts == pd.Timestamp("2024-01-02 14:00:00", tz="UTC")


def test_normalise_drops_partial_bars_and_sorts():
    raw = {
        "prices": [
            _bar("2024:01:02-15:00:00", 106.0, 112.0, 95.0, 108.0, 42_000),
            # Partial bar: missing volume -> dropped.
            _bar("2024:01:02-16:00:00", 109.0, 113.0, 100.0, 111.0, None),
            _bar("2024:01:02-14:00:00", 100.0, 110.0, 90.0, 105.0, 37_000),
        ]
    }

    df = normalise_ig_prices(raw)

    assert len(df) == 2  # the None-volume bar dropped
    # Sorted ascending by Date.
    assert list(df["Date"]) == [
        pd.Timestamp("2024-01-02 14:00:00", tz="UTC"),
        pd.Timestamp("2024-01-02 15:00:00", tz="UTC"),
    ]
    assert df["Date"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# Task 3.3 / Property 1 - mid is bracketed
# ---------------------------------------------------------------------------


@given(
    bid=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    ask=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)
def test_property_mid_is_bracketed(bid, ask):
    """Property 1: mid lies within [min(bid, ask), max(bid, ask)].

    Validates: Requirements 2.2
    """
    mid = _mid(_field(bid, ask))
    assert min(bid, ask) <= mid <= max(bid, ask)
    if bid == ask:
        assert mid == bid


# ---------------------------------------------------------------------------
# Task 3.4 / Property 2 - canonical output shape
# ---------------------------------------------------------------------------


@st.composite
def _ig_payloads(draw):
    n = draw(st.integers(min_value=1, max_value=8))
    bars = []
    for _ in range(n):
        hour = draw(st.integers(min_value=0, max_value=23))
        minute = draw(st.sampled_from([0, 15, 30, 45]))
        snap = f"2024:03:0{draw(st.integers(min_value=1, max_value=9))}-{hour:02d}:{minute:02d}:00"
        price = draw(st.floats(min_value=1.0, max_value=10_000.0, allow_nan=False, allow_infinity=False))
        vol = draw(st.integers(min_value=1, max_value=1_000_000))
        bars.append(_bar(snap, price, price + 1, price - 1, price + 0.5, vol))
    return {"prices": bars}


@given(raw=_ig_payloads())
def test_property_canonical_output_shape(raw):
    """Property 2: exact canonical columns, ascending by Date, no NaN in OHLCV.

    Validates: Requirements 2.1, 2.3
    """
    df = normalise_ig_prices(raw)
    assert list(df.columns) == CANONICAL_COLUMNS
    assert df["Date"].is_monotonic_increasing
    assert not df[_OHLCV].isna().any().any()


# ---------------------------------------------------------------------------
# Task 3.5 / Property 3 - UTC bar-open
# ---------------------------------------------------------------------------


@given(raw=_ig_payloads())
def test_property_utc_bar_open(raw):
    """Property 3: every ts is tz-aware UTC equal to the parsed snapshotTime.

    Validates: Requirements 2.4
    """
    df = normalise_ig_prices(raw)
    for ts in df["Date"]:
        assert ts.tzinfo is not None
        assert str(ts.tz) == "UTC"
    # Each ts equals the bar-open instant parsed from its snapshotTime.
    expected = sorted(pd.to_datetime(b["snapshotTime"], format=IG_SNAPSHOT_FMT, utc=True) for b in raw["prices"])
    assert list(df["Date"]) == expected


# ---------------------------------------------------------------------------
# Task 3.7 / Property 9 - 4h resample integrity + probe fallback
# ---------------------------------------------------------------------------


def _hourly_1h(n, start="2024-01-02 12:00:00"):
    """Build a contiguous hourly canonical 1h frame of n bars from start (UTC)."""
    dates = pd.date_range(start=pd.Timestamp(start, tz="UTC"), periods=n, freq="1h")
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [100.0 + i for i in range(n)],
            "High": [110.0 + i for i in range(n)],
            "Low": [90.0 - i for i in range(n)],
            "Close": [105.0 + i for i in range(n)],
            "Volume": [1_000 + i for i in range(n)],
        }
    )


@given(n=st.integers(min_value=1, max_value=40))
def test_property_4h_resample_integrity(n):
    """Property 9: each 4h bar = first Open / max High / min Low / last Close / sum Vol.

    Validates: Requirements 2.6, 3.5, 5.4
    """
    df_1h = _hourly_1h(n)
    df_4h = resample_1h_to_4h(df_1h)

    assert list(df_4h.columns) == CANONICAL_COLUMNS
    assert df_4h["Date"].is_monotonic_increasing

    # Re-group the source the same way (floor to 4h) and verify each window.
    window = pd.to_datetime(df_1h["Date"], utc=True).dt.floor("4h")
    for _, group in df_1h.groupby(window, sort=True):
        first = group.iloc[0]
        last = group.iloc[-1]
        row = df_4h[df_4h["Date"] == first["Date"]]
        assert len(row) == 1
        row = row.iloc[0]
        assert row["Open"] == first["Open"]
        assert row["High"] == group["High"].max()
        assert row["Low"] == group["Low"].min()
        assert row["Close"] == last["Close"]
        assert row["Volume"] == group["Volume"].sum()
        assert row["Date"].tzinfo is not None


def test_resample_empty_in_empty_out():
    out = resample_1h_to_4h(pd.DataFrame(columns=CANONICAL_COLUMNS))
    assert list(out.columns) == CANONICAL_COLUMNS
    assert out.empty


def test_probe_hour4_true_when_usable():
    payload = {
        "prices": [_bar("2024:01:02-12:00:00", 100.0, 110.0, 90.0, 105.0, 5_000)],
        "allowance": {"remainingAllowance": 9_000},
    }
    client = _FakeClient(payload)
    assert probe_hour4(client, "IX.D.SPTRD.DAILY.IP") is True
    assert client.calls[0][1] == "HOUR_4"


def test_probe_hour4_false_when_empty():
    client = _FakeClient({"prices": [], "allowance": {}})
    assert probe_hour4(client, "IX.D.SPTRD.DAILY.IP") is False


def test_probe_hour4_false_when_volume_missing():
    payload = {"prices": [_bar("2024:01:02-12:00:00", 100.0, 110.0, 90.0, 105.0, None)]}
    client = _FakeClient(payload)
    assert probe_hour4(client, "IX.D.SPTRD.DAILY.IP") is False
