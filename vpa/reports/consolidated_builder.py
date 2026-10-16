"""Pure builder for the Consolidated_Daily_Report.

``build_consolidated_report`` assembles exactly one :class:`ConsolidatedReport`
from the in-memory upstream objects — the all-shares ``DailyReport`` and the
per-asset regime results — with the four sections always present in the fixed
order Market Regime, Top VPA Signals, Opportunities, Daily Summary.

The function is pure: no file, network, or logging I/O. All invocation, logging,
and writing is owned by the orchestrator. ``scan_result`` is ``None`` when the
all-shares scan failed (VPA_Scan_Result Missing); the Top VPA Signals and
Opportunities sections then become empty-section placeholders. Each configured
asset appears in the Market Regime section exactly once, classified from its
``RegimeAssetResult``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

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
from vpa.reports.models import DailyReport
from vpa.reports.regime import RegimeAssetResult, RegimeAssetState

# At most this many signals appear in the Top VPA Signals section (Req 4.1).
_TOP_VPA_LIMIT = 5

# Default primary-asset identifier when no assets are configured. Mirrors the
# design's default Configured_Assets of ["SPY"] so the DailySummarySection
# always carries a non-empty asset identifier even when the regime input is
# entirely absent.
_DEFAULT_PRIMARY_ASSET = "SPY"


def build_consolidated_report(
    report_date: date,
    scan_result: DailyReport | None,
    regime_result: Sequence[RegimeAssetResult],
) -> ConsolidatedReport:
    """Assemble exactly one :class:`ConsolidatedReport` with all four sections.

    Pure function, no I/O. Always produces the four sections in the fixed order
    Market Regime -> Top VPA Signals -> Opportunities -> Daily Summary and no
    others (Req 1.1, 1.2, 8.1, 8.2).

    Args:
        report_date: The calendar date the report is generated for.
        scan_result: The in-memory all-shares ``DailyReport``, or ``None`` when
            the scan failed (VPA_Scan_Result Missing). When ``None`` the Top VPA
            Signals and Opportunities sections are empty-section placeholders
            (Req 2.5, 4.4, 5.2, 8.3).
        regime_result: One ``RegimeAssetResult`` per configured asset. Each
            asset maps to exactly one entry in the Market Regime section.

    Returns:
        A ``ConsolidatedReport`` whose sections reflect only the inputs received
        (no VPA signal, opportunity, or regime record is fabricated).
    """
    market_regime = _build_market_regime(regime_result)
    top_vpa_signals = _build_top_vpa_signals(scan_result)
    opportunities = _build_opportunities(scan_result)
    daily_summary = _build_daily_summary(regime_result, top_vpa_signals, opportunities)

    return ConsolidatedReport(
        report_date=report_date,
        market_regime=market_regime,
        top_vpa_signals=top_vpa_signals,
        opportunities=opportunities,
        daily_summary=daily_summary,
    )


def _build_top_vpa_signals(scan_result: DailyReport | None) -> TopVpaSignalsSection:
    """Top 5 of the scan's successful results, already score-desc ordered.

    ``scan_result`` is ``None`` or has no successful rows -> empty section
    (Req 4.1, 4.2, 4.3, 4.4). ``successful_results`` is already sorted
    ``(-(signal_score or 0), report_ticker)`` by ``DailyReport``, so slicing the
    first five preserves that order and keeps every listed score >= every
    omitted score.
    """
    if scan_result is None:
        return TopVpaSignalsSection(signals=())

    signals = tuple(
        VpaSignal(ticker=result.report_ticker, signal_score=result.signal_score or 0.0)
        for result in scan_result.successful_results[:_TOP_VPA_LIMIT]
    )
    return TopVpaSignalsSection(signals=signals)


def _build_opportunities(scan_result: DailyReport | None) -> OpportunitiesSection:
    """Every qualifying opportunity, already drawdown-asc ordered.

    ``scan_result`` is ``None`` or has no qualifying rows -> empty section
    (Req 5.1, 5.2, 5.3). ``opportunities`` is already filtered to
    ``opportunity_status == "qualifies"`` and sorted deterministically by
    ``DailyReport``, so we list every ticker with its drawdown and momentum.
    """
    if scan_result is None:
        return OpportunitiesSection(opportunities=())

    opportunities = tuple(
        Opportunity(
            ticker=result.report_ticker,
            drawdown_pct=result.drawdown_pct or 0.0,
            momentum_pct=result.momentum_pct or 0.0,
        )
        for result in scan_result.opportunities
    )
    return OpportunitiesSection(opportunities=opportunities)


def _build_market_regime(regime_result: Sequence[RegimeAssetResult]) -> MarketRegimeSection:
    """One ``RegimeAssetEntry`` per configured asset (Req 3.1-3.5).

    PRESENT -> available with its records High-first (already ordered by the
    generator); EMPTY -> available with no signals (no-high-conviction);
    MISSING -> unavailable placeholder. Each configured asset appears exactly
    once.
    """
    entries = tuple(
        RegimeAssetEntry(
            asset=asset.asset,
            available=asset.state is not RegimeAssetState.MISSING,
            signals=tuple(
                RegimeSignalEntry(
                    signal_type=record.signal_type,
                    adjusted_direction=record.adjusted_direction,
                    confidence_level=record.confidence_level,
                )
                for record in asset.records
            ),
        )
        for asset in regime_result
    )
    return MarketRegimeSection(assets=entries)


def _build_daily_summary(
    regime_result: Sequence[RegimeAssetResult],
    top_vpa_signals: TopVpaSignalsSection,
    opportunities: OpportunitiesSection,
) -> DailySummarySection:
    """Counts plus the primary asset's highest-confidence direction/confidence.

    Opportunity count = number of Opportunities tickers; VPA signal count =
    number of Top VPA tickers (an unavailable section contributes zero). The
    primary asset is the first configured asset; its highest-confidence fired
    record is the first of its High-first ``records`` (PRESENT). When that asset
    has no fired record (EMPTY/MISSING) both direction and confidence are
    ``None`` (no-high-conviction / unavailable). (Req 6.1-6.4)
    """
    primary = regime_result[0] if regime_result else None
    primary_asset = primary.asset if primary is not None else _DEFAULT_PRIMARY_ASSET

    primary_direction: str | None = None
    primary_confidence: str | None = None
    if primary is not None and primary.state is RegimeAssetState.PRESENT and primary.records:
        highest = primary.records[0]  # records are already High-first
        primary_direction = highest.adjusted_direction
        primary_confidence = highest.confidence_level

    return DailySummarySection(
        opportunity_count=len(opportunities.opportunities),
        vpa_signal_count=len(top_vpa_signals.signals),
        primary_asset=primary_asset,
        primary_direction=primary_direction,
        primary_confidence=primary_confidence,
    )
