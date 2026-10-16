"""Property-based test for Daily Summary consistency (SP-356, Task 2.5).

**Property 5: Daily Summary is consistent with the rendered sections.** For any
all-shares ``DailyReport`` (present / empty / absent) and any per-asset regime
input, the Consolidated_Daily_Report's Daily Summary section SHALL:

- report an opportunity count equal to the number of tickers rendered in the
  Opportunities section (Req 6.1);
- report a VPA signal count equal to the number of tickers rendered in the Top
  VPA Signals section (Req 6.2);
- reflect the primary asset's highest-confidence regime record's direction and
  confidence — i.e. the primary asset is the FIRST configured asset and its
  highest-confidence record is the first of its High-first ``records`` — or
  indicate no high-conviction via ``None`` / ``None`` when that asset fired
  nothing or could not run (Req 6.3, 6.4);
- show a zero count for any section whose input was unavailable (Req 6.1, 6.2).

**Validates: Requirements 6.1, 6.2, 6.3, 6.4**

The property is exercised through the real builder
``build_consolidated_report(report_date, scan_result, regime_result)``
(``vpa/reports/consolidated_builder.py``) and asserts on the resulting
``ConsolidatedReport.daily_summary`` against the same report's rendered
Opportunities and Top VPA Signals sections — no mocks, no I/O, no network.

The scan input is drawn as one of: ``None`` (VPA_Scan_Result Missing), an empty
``DailyReport`` (ran but produced no rows), or a populated ``DailyReport`` with a
random mix of statuses and opportunity rows. The regime input is a tuple of
``RegimeAssetResult`` with distinct asset identifiers over arbitrary N, each
randomly PRESENT (1+ High-first records), EMPTY, or MISSING, and including the
empty tuple. The primary-asset expectation is derived directly from
``regime_result[0]`` (or the no-high-conviction indication when absent).
"""

from __future__ import annotations

import datetime as dt

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.daily_signal import CONFIDENCE_ORDER, SignalRecord
from vpa.reports.consolidated_builder import build_consolidated_report
from vpa.reports.models import DailyReport, TickerScanResult
from vpa.reports.regime import RegimeAssetResult, RegimeAssetState

# The generator's confidence ordering: "High" first, then down to "Low".
_CONFIDENCE_LEVELS = tuple(CONFIDENCE_ORDER)

# Short ticker symbols from a small alphabet so ties are common.
_TICKERS = st.text(alphabet="ABCDE", min_size=1, max_size=3)

# Finite signal scores (no NaN / inf); None is drawn separately and treated as 0.
_SCORES = st.one_of(
    st.none(),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1000, max_value=1000, width=64),
)

# Finite drawdown / momentum percentages (None treated as 0 by the builder).
_PCTS = st.one_of(
    st.none(),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-100, max_value=100, width=64),
)


def _confidence_rank(level: str) -> int:
    """Sort rank for a confidence level — "High" is rank 0 (highest)."""
    return CONFIDENCE_ORDER.index(level)


@st.composite
def _ticker_scan_results(draw) -> tuple[TickerScanResult, ...]:
    """Random scan rows: mixed status, random score, random opportunity status/pcts."""
    rows = draw(
        st.lists(
            st.builds(
                TickerScanResult,
                source_ticker=_TICKERS,
                report_ticker=_TICKERS,
                status=st.sampled_from(("success", "failed")),
                signal_score=_SCORES,
                opportunity_status=st.sampled_from(("qualifies", "does_not_qualify", "disabled", "unavailable")),
                drawdown_pct=_PCTS,
                momentum_pct=_PCTS,
            ),
            max_size=12,
        )
    )
    return tuple(rows)


@st.composite
def _scan_results(draw) -> DailyReport | None:
    """Draw a scan input: None (Missing), an empty DailyReport, or a populated one."""
    kind = draw(st.sampled_from(("none", "empty", "populated")))
    if kind == "none":
        return None

    report_date = draw(st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31)))
    results = () if kind == "empty" else draw(_ticker_scan_results())
    return DailyReport(
        report_date=report_date,
        results=results,
        opportunity_filter_enabled=draw(st.booleans()),
    )


@st.composite
def _signal_records(draw, ticker: str) -> tuple[SignalRecord, ...]:
    """1+ SignalRecords for a PRESENT asset, sorted High-first like the generator."""
    levels = draw(st.lists(st.sampled_from(_CONFIDENCE_LEVELS), min_size=1, max_size=5))
    directions = draw(st.lists(st.sampled_from(("BUY", "SELL", "HOLD")), min_size=len(levels), max_size=len(levels)))
    records = [
        SignalRecord(
            ticker=ticker,
            date="2026-07-15",
            signal_type=draw(st.sampled_from(("distribution", "strong_bearish", "accumulation"))),
            original_direction=draw(st.sampled_from(("up", "down"))),
            adjusted_direction=direction,
            confidence_level=level,
            suggested_hold_days=10,
        )
        for level, direction in zip(levels, directions, strict=False)
    ]
    # High-first, matching the generator (stable sort preserves draw order on ties).
    records.sort(key=lambda r: _confidence_rank(r.confidence_level))
    return tuple(records)


@st.composite
def _regime_results(draw) -> tuple[RegimeAssetResult, ...]:
    """A tuple of RegimeAssetResult with DISTINCT assets over arbitrary N (incl. 0)."""
    asset_names = draw(st.lists(st.text(min_size=1, max_size=6), min_size=0, max_size=6, unique=True))
    results: list[RegimeAssetResult] = []
    for name in asset_names:
        state = draw(st.sampled_from((RegimeAssetState.PRESENT, RegimeAssetState.EMPTY, RegimeAssetState.MISSING)))
        if state is RegimeAssetState.PRESENT:
            records = draw(_signal_records(name))
            results.append(RegimeAssetResult(asset=name, state=state, records=records))
        elif state is RegimeAssetState.EMPTY:
            results.append(RegimeAssetResult(asset=name, state=state))
        else:  # MISSING
            results.append(RegimeAssetResult(asset=name, state=state, detail="InsufficientDataError: too few bars"))
    return tuple(results)


# Feature: daily-market-report, Property 5: Daily Summary is consistent with the rendered sections
@settings(max_examples=200)
@given(
    report_date=st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31)),
    scan_result=_scan_results(),
    regime_result=_regime_results(),
)
def test_daily_summary_is_consistent_with_rendered_sections(
    report_date: dt.date,
    scan_result: DailyReport | None,
    regime_result: tuple[RegimeAssetResult, ...],
) -> None:
    """Summary counts equal section lengths; primary direction/confidence match the primary asset.

    Validates: Requirements 6.1, 6.2, 6.3, 6.4
    """
    report = build_consolidated_report(report_date, scan_result, regime_result)
    summary = report.daily_summary

    # Req 6.1: opportunity count equals the number of tickers in the Opportunities section.
    assert summary.opportunity_count == len(report.opportunities.opportunities)

    # Req 6.2: VPA signal count equals the number of tickers in the Top VPA Signals section.
    assert summary.vpa_signal_count == len(report.top_vpa_signals.signals)

    # When a section's input is unavailable (scan None or empty), its count is zero.
    if scan_result is None or not scan_result.results:
        assert summary.opportunity_count == 0
        assert summary.vpa_signal_count == 0

    # Req 6.3/6.4: primary asset is the FIRST configured asset; direction/confidence are
    # the highest-confidence (first High-first) record's, else None/None (no-high-conviction).
    primary = regime_result[0] if regime_result else None
    if primary is not None and primary.state is RegimeAssetState.PRESENT and primary.records:
        highest = primary.records[0]
        assert summary.primary_asset == primary.asset
        assert summary.primary_direction == highest.adjusted_direction
        assert summary.primary_confidence == highest.confidence_level
    else:
        # EMPTY / MISSING primary asset, or no configured assets at all -> no high-conviction.
        assert summary.primary_direction is None
        assert summary.primary_confidence is None
        if primary is not None:
            assert summary.primary_asset == primary.asset
