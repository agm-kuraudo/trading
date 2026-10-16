"""Property-based test for graceful degradation of the consolidated builder (SP-356, Task 2.6).

**Property 6: Graceful degradation never fails and never fabricates.** For any
subset of inputs missing or empty — the all-shares scan absent (``None``), an
empty scan, or a populated scan, combined with per-asset regime results that mix
PRESENT / EMPTY / MISSING (including a MISSING produced by a generator failure,
and including the empty-tuple regime input) — the builder
``build_consolidated_report(report_date, scan_result, regime_result)`` SHALL:

- never raise and always return exactly one ``ConsolidatedReport`` (Req 8.1,
  8.2, 10.3);
- render each unavailable section with its placeholder: no scan / no successful
  rows -> ``top_vpa_signals.signals == ()`` (Req 4.4); no scan / no qualifying
  rows -> ``opportunities.opportunities == ()`` (Req 5.2); each MISSING regime
  asset -> ``available is False`` with no signals (Req 3.5); each EMPTY regime
  asset -> ``available is True`` with no signals and ``no_high_conviction``
  (Req 2.5);
- fabricate nothing: every listed VPA signal ticker comes from a successful
  scan row, every opportunity ticker from a qualifying scan row, and a PRESENT
  asset's rendered signals are drawn only from its own records — no ticker,
  opportunity, or regime record appears that was not in the inputs (Req 8.3).

**Validates: Requirements 2.5, 3.5, 4.4, 5.2, 8.1, 8.2, 8.3, 10.3**

The property is exercised through the real builder — no mocks, no I/O, no
network. The scan input is drawn as ``None`` (Missing), an empty ``DailyReport``
(ran, nothing to show), or a populated ``DailyReport`` with a random mix of
statuses and opportunity statuses. The regime input is a tuple of
``RegimeAssetResult`` with distinct assets over arbitrary N (including N = 0),
each randomly PRESENT / EMPTY / MISSING.
"""

from __future__ import annotations

import datetime as dt

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.daily_signal import CONFIDENCE_ORDER, SignalRecord
from vpa.reports.consolidated_builder import build_consolidated_report
from vpa.reports.consolidated_models import ConsolidatedReport
from vpa.reports.models import DailyReport, TickerScanResult
from vpa.reports.regime import RegimeAssetResult, RegimeAssetState

_CONFIDENCE_LEVELS = tuple(CONFIDENCE_ORDER)

# Short ticker alphabet so collisions / ties are common.
_TICKERS = st.text(alphabet="ABCDE", min_size=1, max_size=3)

# Finite scores only (NaN/inf are not valid scan data); None drawn separately.
_SCORES = st.one_of(
    st.none(),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1000, max_value=1000, width=64),
)

_PCTS = st.one_of(
    st.none(),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1000, max_value=1000, width=64),
)

_OPPORTUNITY_STATUSES = ("qualifies", "does_not_qualify", "disabled", "unavailable")


def _confidence_rank(level: str) -> int:
    return CONFIDENCE_ORDER.index(level)


@st.composite
def _signal_records(draw, ticker: str) -> tuple[SignalRecord, ...]:
    """1+ SignalRecords for a PRESENT asset, sorted High-first like the generator."""
    levels = draw(st.lists(st.sampled_from(_CONFIDENCE_LEVELS), min_size=1, max_size=5))
    records = [
        SignalRecord(
            ticker=ticker,
            date="2026-07-15",
            signal_type=draw(st.sampled_from(("distribution", "strong_bearish", "accumulation"))),
            original_direction=draw(st.sampled_from(("up", "down"))),
            adjusted_direction="BUY",
            confidence_level=level,
            suggested_hold_days=10,
        )
        for level in levels
    ]
    records.sort(key=lambda r: _confidence_rank(r.confidence_level))
    return tuple(records)


@st.composite
def _regime_results(draw) -> tuple[RegimeAssetResult, ...]:
    """A tuple of RegimeAssetResult with DISTINCT assets over arbitrary N (incl. 0).

    Each asset is randomly PRESENT (1+ High-first records), EMPTY (ran, fired
    nothing), or MISSING (generator could not run — a per-asset failure). The
    empty-tuple case (N = 0) is reachable via min_size=0.
    """
    asset_names = draw(st.lists(st.text(min_size=1, max_size=6), min_size=0, max_size=6, unique=True))
    results: list[RegimeAssetResult] = []
    for name in asset_names:
        state = draw(st.sampled_from((RegimeAssetState.PRESENT, RegimeAssetState.EMPTY, RegimeAssetState.MISSING)))
        if state is RegimeAssetState.PRESENT:
            results.append(RegimeAssetResult(asset=name, state=state, records=draw(_signal_records(name))))
        elif state is RegimeAssetState.EMPTY:
            results.append(RegimeAssetResult(asset=name, state=state))
        else:  # MISSING — models a per-asset generator failure
            results.append(RegimeAssetResult(asset=name, state=state, detail="InsufficientDataError: too few bars"))
    return tuple(results)


@st.composite
def _ticker_scan_results(draw) -> tuple[TickerScanResult, ...]:
    """Random scan rows: mixed status, random score/drawdown/momentum, random opp-status."""
    rows = draw(
        st.lists(
            st.builds(
                TickerScanResult,
                source_ticker=_TICKERS,
                report_ticker=_TICKERS,
                status=st.sampled_from(("success", "failed")),
                signal_score=_SCORES,
                opportunity_status=st.sampled_from(_OPPORTUNITY_STATUSES),
                drawdown_pct=_PCTS,
                momentum_pct=_PCTS,
            ),
            max_size=12,
        )
    )
    return tuple(rows)


@st.composite
def _scan_results(draw) -> DailyReport | None:
    """Scan input as one of: None (Missing), empty DailyReport, or populated DailyReport."""
    kind = draw(st.sampled_from(("missing", "empty", "populated")))
    if kind == "missing":
        return None
    report_date = draw(st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31)))
    if kind == "empty":
        return DailyReport(report_date=report_date, results=(), opportunity_filter_enabled=draw(st.booleans()))
    return DailyReport(
        report_date=report_date,
        results=draw(_ticker_scan_results()),
        opportunity_filter_enabled=draw(st.booleans()),
    )


# Feature: daily-market-report, Property 6: Graceful degradation never fails and never fabricates
@settings(max_examples=200)
@given(
    report_date=st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2100, 12, 31)),
    scan_result=_scan_results(),
    regime_result=_regime_results(),
)
def test_graceful_degradation_never_fails_and_never_fabricates(
    report_date: dt.date,
    scan_result: DailyReport | None,
    regime_result: tuple[RegimeAssetResult, ...],
) -> None:
    """The builder always returns a report, placeholders the unavailable, fabricates nothing.

    Validates: Requirements 2.5, 3.5, 4.4, 5.2, 8.1, 8.2, 8.3, 10.3
    """
    # Req 8.1/8.2/10.3: never raises, always exactly one ConsolidatedReport with
    # all four sections present regardless of how degraded the inputs are.
    report = build_consolidated_report(report_date, scan_result, regime_result)
    assert isinstance(report, ConsolidatedReport)
    assert report.report_date == report_date
    assert report.market_regime is not None
    assert report.top_vpa_signals is not None
    assert report.opportunities is not None
    assert report.daily_summary is not None

    # --- Top VPA Signals: placeholder when unavailable; never fabricated (Req 4.4, 8.3) ---
    if scan_result is None:
        # No scan input at all -> empty-section placeholder.
        assert report.top_vpa_signals.signals == ()
    else:
        successful_tickers = [row.report_ticker for row in scan_result.successful_results]
        if not successful_tickers:
            # Scan ran but nothing succeeded -> empty-section placeholder.
            assert report.top_vpa_signals.signals == ()
        # Every listed signal ticker must come from a successful scan row —
        # nothing invented. (multiset containment handles duplicate tickers)
        for signal in report.top_vpa_signals.signals:
            assert signal.ticker in successful_tickers
        assert len(report.top_vpa_signals.signals) <= len(successful_tickers)

    # --- Opportunities: placeholder when unavailable; never fabricated (Req 5.2, 8.3) ---
    if scan_result is None:
        assert report.opportunities.opportunities == ()
    else:
        qualifying_tickers = [row.report_ticker for row in scan_result.opportunities]
        if not qualifying_tickers:
            # Scan ran but nothing qualifies -> empty-section placeholder.
            assert report.opportunities.opportunities == ()
        # Every opportunity ticker must come from a qualifying scan row.
        listed_opp_tickers = [opp.ticker for opp in report.opportunities.opportunities]
        assert sorted(listed_opp_tickers) == sorted(qualifying_tickers)
        for opp in report.opportunities.opportunities:
            assert opp.ticker in qualifying_tickers

    # --- Market Regime: every asset placeholdered per its state; nothing fabricated ---
    section_assets = [entry.asset for entry in report.market_regime.assets]
    expected_assets = [result.asset for result in regime_result]
    # Each configured asset appears exactly once, no extras.
    assert sorted(section_assets) == sorted(expected_assets)
    assert len(section_assets) == len(set(section_assets))

    entries_by_asset = {entry.asset: entry for entry in report.market_regime.assets}
    for result in regime_result:
        entry = entries_by_asset[result.asset]

        if result.state is RegimeAssetState.MISSING:
            # Req 3.5: per-asset generator failure -> unavailable placeholder, no signals.
            assert entry.available is False
            assert entry.signals == ()
            assert entry.no_high_conviction is False

        elif result.state is RegimeAssetState.EMPTY:
            # Req 2.5: ran but fired nothing -> available, no-high-conviction placeholder.
            assert entry.available is True
            assert entry.signals == ()
            assert entry.no_high_conviction is True

        else:  # PRESENT
            assert entry.available is True
            # Req 8.3: the rendered signals are drawn ONLY from this asset's own
            # records — same count, same confidence levels in the same order.
            assert len(entry.signals) == len(result.records)
            assert [sig.confidence_level for sig in entry.signals] == [rec.confidence_level for rec in result.records]
            assert [sig.signal_type for sig in entry.signals] == [rec.signal_type for rec in result.records]
            assert [sig.adjusted_direction for sig in entry.signals] == [
                rec.adjusted_direction for rec in result.records
            ]

    # --- Daily Summary: counts mirror the (possibly empty) rendered sections, never invented ---
    assert report.daily_summary.vpa_signal_count == len(report.top_vpa_signals.signals)
    assert report.daily_summary.opportunity_count == len(report.opportunities.opportunities)
    # Primary direction/confidence only ever reflects a PRESENT primary asset's
    # own first record; otherwise both are None (no-high-conviction / unavailable).
    primary = regime_result[0] if regime_result else None
    if primary is not None and primary.state is RegimeAssetState.PRESENT and primary.records:
        assert report.daily_summary.primary_direction == primary.records[0].adjusted_direction
        assert report.daily_summary.primary_confidence == primary.records[0].confidence_level
    else:
        assert report.daily_summary.primary_direction is None
        assert report.daily_summary.primary_confidence is None
