"""Property-based test for the Consolidated_Daily_Report JSON snapshot (SP-356, Task 1.3).

**Property 1: Snapshot round-trip is identity.** For any valid
``ConsolidatedReport`` ``r``, serialising it to its primitive dict form and back
reproduces it exactly, and doing so via a full JSON encode/decode round-trip
also reproduces it exactly::

    ∀ r: from_dict(to_dict(r)) == r
    ∀ r: from_dict(json.loads(json.dumps(to_dict(r)))) == r

This encodes the snapshot archival round-trip guarantee: the four Report
Sections and the Report Date are reproduced with no field added, dropped, or
altered (design §Correctness Properties, Property 1).

**Validates: Requirements 7.1, 7.3, 7.6**

The test is pure — no I/O, no network. It exercises ``to_dict`` / ``from_dict``
and every dataclass in ``vpa/reports/consolidated_models.py`` across arbitrary
reports: random report dates, a MarketRegimeSection with N assets that are each
PRESENT (available + signals), EMPTY (available + no signals), or MISSING
(not available), a TopVpaSignalsSection, an OpportunitiesSection, and a
DailySummarySection whose ``primary_direction`` / ``primary_confidence`` may be
None (the no-high-conviction / unavailable case).

Asset keys in the market-regime map must be UNIQUE per report (the snapshot
schema is a dict keyed by asset), so assets are drawn from a *set* of distinct
identifiers — otherwise ``to_dict`` would silently collapse duplicate keys and
the round-trip could not hold.
"""

from __future__ import annotations

import datetime as dt
import json

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.reports.consolidated_models import (
    ConsolidatedReport,
    DailySummarySection,
    MarketRegimeSection,
    OpportunitiesSection,
    Opportunity,
    RegimeAssetEntry,
    RegimeSignalEntry,
    TopVpaSignalsSection,
    VpaSignal,
)

# JSON-safe finite floats (no NaN / inf, which would not survive a JSON round-trip
# as an equal value and are not valid snapshot data anyway).
_FLOATS = st.floats(allow_nan=False, allow_infinity=False, width=64)

# Short, non-empty text for identifiers / categorical fields. Any str survives the
# round-trip, so a small alphabet keeps examples readable without losing coverage.
_TEXT = st.text(min_size=1, max_size=8)


@st.composite
def _regime_signal_entries(draw) -> tuple[RegimeSignalEntry, ...]:
    entries = draw(
        st.lists(
            st.builds(
                RegimeSignalEntry,
                signal_type=_TEXT,
                adjusted_direction=_TEXT,
                confidence_level=_TEXT,
            ),
            max_size=4,
        )
    )
    return tuple(entries)


@st.composite
def _regime_section(draw) -> MarketRegimeSection:
    # Distinct asset identifiers => unique keys in the snapshot's asset map.
    asset_names = draw(st.sets(_TEXT, max_size=5))
    assets: list[RegimeAssetEntry] = []
    for name in asset_names:
        available = draw(st.booleans())
        if available:
            # PRESENT (non-empty signals) or EMPTY (available, no signals).
            signals = draw(_regime_signal_entries())
        else:
            # MISSING: an unavailable asset never carries signals.
            signals = ()
        assets.append(RegimeAssetEntry(asset=name, available=available, signals=signals))
    return MarketRegimeSection(assets=tuple(assets))


@st.composite
def _top_vpa_section(draw) -> TopVpaSignalsSection:
    signals = draw(
        st.lists(
            st.builds(VpaSignal, ticker=_TEXT, signal_score=_FLOATS),
            max_size=5,
        )
    )
    return TopVpaSignalsSection(signals=tuple(signals))


@st.composite
def _opportunities_section(draw) -> OpportunitiesSection:
    opportunities = draw(
        st.lists(
            st.builds(
                Opportunity,
                ticker=_TEXT,
                drawdown_pct=_FLOATS,
                momentum_pct=_FLOATS,
            ),
            max_size=5,
        )
    )
    return OpportunitiesSection(opportunities=tuple(opportunities))


@st.composite
def _daily_summary_section(draw) -> DailySummarySection:
    return DailySummarySection(
        opportunity_count=draw(st.integers(min_value=0, max_value=1000)),
        vpa_signal_count=draw(st.integers(min_value=0, max_value=1000)),
        primary_asset=draw(_TEXT),
        # Both may be None together (no-high-conviction / unavailable) or set.
        primary_direction=draw(st.none() | _TEXT),
        primary_confidence=draw(st.none() | _TEXT),
    )


@st.composite
def _consolidated_reports(draw) -> ConsolidatedReport:
    return ConsolidatedReport(
        report_date=draw(st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31))),
        market_regime=draw(_regime_section()),
        top_vpa_signals=draw(_top_vpa_section()),
        opportunities=draw(_opportunities_section()),
        daily_summary=draw(_daily_summary_section()),
    )


# Feature: daily-market-report, Property 1: Snapshot round-trip is identity
@settings(max_examples=100)
@given(report=_consolidated_reports())
def test_snapshot_round_trip_is_identity(report: ConsolidatedReport) -> None:
    """from_dict(to_dict(r)) == r, and the same holds through a full JSON round-trip.

    Validates: Requirements 7.1, 7.3, 7.6
    """
    from vpa.reports.consolidated_models import from_dict, to_dict

    # Direct dict round-trip.
    assert from_dict(to_dict(report)) == report

    # Full JSON encode/decode round-trip (to_dict output must be JSON-ready).
    rehydrated = from_dict(json.loads(json.dumps(to_dict(report))))
    assert rehydrated == report
