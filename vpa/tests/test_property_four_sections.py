"""Property-based test for the Consolidated_Daily_Report four-sections invariant (SP-356, Task 2.4).

**Property 4: Report always has the four sections in order.** For any combination
of present, missing, and empty inputs, ``build_consolidated_report`` SHALL
produce exactly one ``ConsolidatedReport`` containing the four sections in the
order Market Regime, Top VPA Signals, Opportunities, Daily Summary, and no other
sections (design §Correctness Properties, Property 4).

**Validates: Requirements 1.1, 1.2, 8.1, 8.2**

The test is pure — no I/O, no network. It drives the builder across every input
shape:

- ``scan_result`` as one of {``None`` (Missing), an empty ``DailyReport`` (Empty),
  a populated ``DailyReport`` (Present)};
- ``regime_result`` as a tuple of ``RegimeAssetResult`` over an arbitrary number
  N of assets (including the empty tuple) mixing PRESENT / EMPTY / MISSING.

It asserts the builder always returns exactly one ``ConsolidatedReport`` whose
``dataclasses.fields`` are exactly ``report_date`` followed by the four report
sections in the fixed order — so the four sections are always present, always in
order, and no other section exists — and that each section is of its expected
type.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.daily_signal import SignalRecord
from vpa.reports.consolidated_builder import build_consolidated_report
from vpa.reports.consolidated_models import (
    ConsolidatedReport,
    DailySummarySection,
    MarketRegimeSection,
    OpportunitiesSection,
    TopVpaSignalsSection,
)
from vpa.reports.models import DailyReport, TickerScanResult
from vpa.reports.regime import RegimeAssetResult, RegimeAssetState

# The exact field order ConsolidatedReport must expose: the report date followed
# by the four report sections in the fixed order Market Regime, Top VPA Signals,
# Opportunities, Daily Summary (and nothing else).
_EXPECTED_FIELD_NAMES = (
    "report_date",
    "market_regime",
    "top_vpa_signals",
    "opportunities",
    "daily_summary",
)

# JSON-/arithmetic-safe finite floats (no NaN / inf).
_FLOATS = st.floats(allow_nan=False, allow_infinity=False, width=64)
_TEXT = st.text(min_size=1, max_size=6)


@st.composite
def _ticker_scan_results(draw) -> TickerScanResult:
    """A single scan row, either a success (carrying a signal score) or a failure,
    optionally qualifying as an opportunity."""
    status = draw(st.sampled_from(["success", "failed"]))
    opportunity_status = draw(st.sampled_from(["qualifies", "does_not_qualify", "unavailable"]))
    return TickerScanResult(
        source_ticker=draw(_TEXT),
        report_ticker=draw(_TEXT),
        status=status,
        signal_score=draw(st.none() | _FLOATS),
        opportunity_status=opportunity_status,
        drawdown_pct=draw(st.none() | _FLOATS),
        momentum_pct=draw(st.none() | _FLOATS),
    )


@st.composite
def _scan_results(draw) -> DailyReport | None:
    """scan_result as one of: None (Missing), empty DailyReport (Empty), populated."""
    shape = draw(st.sampled_from(["missing", "empty", "populated"]))
    if shape == "missing":
        return None
    if shape == "empty":
        rows: tuple[TickerScanResult, ...] = ()
    else:
        rows = tuple(draw(st.lists(_ticker_scan_results(), min_size=1, max_size=12)))
    return DailyReport(
        report_date=draw(st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31))),
        results=rows,
        opportunity_filter_enabled=draw(st.booleans()),
    )


@st.composite
def _signal_records(draw, ticker: str) -> tuple[SignalRecord, ...]:
    records = draw(
        st.lists(
            st.builds(
                SignalRecord,
                ticker=st.just(ticker),
                date=st.just("2026-01-01"),
                signal_type=_TEXT,
                original_direction=st.sampled_from(["up", "down"]),
                adjusted_direction=st.just("BUY"),
                confidence_level=st.sampled_from(["High", "Medium-High", "Low-Medium", "Low"]),
                suggested_hold_days=st.just(10),
            ),
            min_size=1,
            max_size=4,
        )
    )
    return tuple(records)


@st.composite
def _regime_results(draw) -> tuple[RegimeAssetResult, ...]:
    """regime_result as a tuple of RegimeAssetResult over arbitrary N (incl. empty),
    mixing PRESENT / EMPTY / MISSING."""
    asset_names = draw(st.lists(_TEXT, max_size=5, unique=True))
    results: list[RegimeAssetResult] = []
    for name in asset_names:
        state = draw(st.sampled_from(list(RegimeAssetState)))
        if state is RegimeAssetState.PRESENT:
            records = draw(_signal_records(name))
            results.append(RegimeAssetResult(asset=name, state=state, records=records))
        elif state is RegimeAssetState.EMPTY:
            results.append(RegimeAssetResult(asset=name, state=state))
        else:  # MISSING
            results.append(RegimeAssetResult(asset=name, state=state, detail="unavailable"))
    return tuple(results)


# Feature: daily-market-report, Property 4: Report always has the four sections in order
@settings(max_examples=200)
@given(
    report_date=st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31)),
    scan_result=_scan_results(),
    regime_result=_regime_results(),
)
def test_report_always_has_four_sections_in_order(
    report_date: dt.date,
    scan_result: DailyReport | None,
    regime_result: tuple[RegimeAssetResult, ...],
) -> None:
    """The builder always returns exactly one ConsolidatedReport with the four
    sections present, in the fixed order, and no others.

    Validates: Requirements 1.1, 1.2, 8.1, 8.2
    """
    report = build_consolidated_report(report_date, scan_result, regime_result)

    # Exactly one report of the expected type (Req 1.1, 8.1, 8.2).
    assert isinstance(report, ConsolidatedReport)

    # The dataclass fields are exactly report_date + the four sections, in order,
    # and no other section exists (Req 1.2).
    field_names = tuple(f.name for f in dataclasses.fields(report))
    assert field_names == _EXPECTED_FIELD_NAMES

    # Each section is of its expected type.
    assert isinstance(report.market_regime, MarketRegimeSection)
    assert isinstance(report.top_vpa_signals, TopVpaSignalsSection)
    assert isinstance(report.opportunities, OpportunitiesSection)
    assert isinstance(report.daily_summary, DailySummarySection)
