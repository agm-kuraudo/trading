"""Plain-text renderer for the Consolidated_Daily_Report.

``render_consolidated_text`` turns a :class:`ConsolidatedReport` into a single
human-readable string, following the house ``render_plain_text`` style in
``vpa/reports/renderers.py``: a header line, blank-line-separated sections each
introduced by a title line, item lines beneath, and a trailing newline.

The function is pure: it displays only what the report carries and renders each
unavailable section (and each missing/empty regime asset) with its placeholder,
never fabricating a signal, opportunity, or regime record it did not receive
(Req 1.2-1.4, 3, 4.4, 5.2, 6.4).
"""

from __future__ import annotations

from vpa.reports.consolidated_models import ConsolidatedReport

# Placeholder strings shown when a section or regime asset is unavailable.
_REGIME_UNAVAILABLE = "Market regime signal unavailable"
_REGIME_NO_HIGH_CONVICTION = "no high-conviction signal"
_NO_VPA_SIGNALS = "no VPA signals available"
_NO_OPPORTUNITIES = "no opportunities available"
_SUMMARY_NO_HIGH_CONVICTION = "no high-conviction signal"


def render_consolidated_text(report: ConsolidatedReport) -> str:
    """Render a :class:`ConsolidatedReport` as plain text.

    Displays the ``Report_Date`` in ISO 8601 (``YYYY-MM-DD``) form (Req 1.4) and
    renders all four sections in order — Market Regime, Top VPA Signals,
    Opportunities, Daily Summary — with their placeholders when unavailable
    (Req 3.5, 4.4, 5.2, 6.4). Returns a string ending in a single newline.
    """
    lines = [f"Daily Market Report: {report.report_date.isoformat()}"]

    lines.extend(["", "Market Regime"])
    lines.extend(_render_market_regime(report))

    lines.extend(["", "Top VPA Signals"])
    lines.extend(_render_top_vpa_signals(report))

    lines.extend(["", "Opportunities"])
    lines.extend(_render_opportunities(report))

    lines.extend(["", "Daily Summary"])
    lines.extend(_render_daily_summary(report))

    return "\n".join(lines) + "\n"


def _render_market_regime(report: ConsolidatedReport) -> list[str]:
    """Render the Market Regime section (Req 3.1-3.5).

    Whole section unavailable -> placeholder (Req 3.5). Otherwise one block per
    configured asset: a MISSING asset shows the unavailable placeholder; an
    asset that ran but fired nothing shows the no-high-conviction indication
    (Req 3.4); an asset with records lists each signal's signal_type,
    adjusted_direction and confidence_level in the given High-first order
    (Req 3.1-3.3).
    """
    section = report.market_regime
    if not section.available:
        return [_REGIME_UNAVAILABLE]

    lines: list[str] = []
    for asset in section.assets:
        if not asset.available:
            lines.append(f"{asset.asset}: {_REGIME_UNAVAILABLE}")
        elif asset.no_high_conviction:
            lines.append(f"{asset.asset}: {_REGIME_NO_HIGH_CONVICTION}")
        else:
            lines.append(f"{asset.asset}:")
            for signal in asset.signals:
                lines.append(f"  {signal.signal_type} {signal.adjusted_direction} ({signal.confidence_level})")
    return lines


def _render_top_vpa_signals(report: ConsolidatedReport) -> list[str]:
    """Render the Top VPA Signals section: ticker + score, or placeholder (Req 4.4)."""
    signals = report.top_vpa_signals.signals
    if not signals:
        return [_NO_VPA_SIGNALS]
    return [f"{signal.ticker}: {signal.signal_score}" for signal in signals]


def _render_opportunities(report: ConsolidatedReport) -> list[str]:
    """Render the Opportunities section: ticker + drawdown + momentum, or placeholder (Req 5.2)."""
    opportunities = report.opportunities.opportunities
    if not opportunities:
        return [_NO_OPPORTUNITIES]
    return [
        f"{opportunity.ticker}: drawdown={opportunity.drawdown_pct:.1f}% " f"momentum={opportunity.momentum_pct:.1f}%"
        for opportunity in opportunities
    ]


def _render_daily_summary(report: ConsolidatedReport) -> list[str]:
    """Render the Daily Summary section (Req 6.4).

    Shows the opportunity count, the VPA signal count, and the primary asset's
    direction/confidence — or the no-high-conviction indication when the primary
    asset has no fired record (``primary_direction``/``primary_confidence`` None).
    """
    summary = report.daily_summary
    lines = [
        f"Opportunities: {summary.opportunity_count}",
        f"VPA signals: {summary.vpa_signal_count}",
    ]
    if summary.primary_direction is None or summary.primary_confidence is None:
        lines.append(f"{summary.primary_asset}: {_SUMMARY_NO_HIGH_CONVICTION}")
    else:
        lines.append(f"{summary.primary_asset}: {summary.primary_direction} ({summary.primary_confidence})")
    return lines
