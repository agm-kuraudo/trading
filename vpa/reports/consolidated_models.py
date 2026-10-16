from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RegimeSignalEntry:
    signal_type: str  # e.g. "distribution", "strong_bearish"
    adjusted_direction: str  # e.g. "BUY"
    confidence_level: str  # "High" | "Medium-High" | "Low-Medium" | "Low"


@dataclass(frozen=True)
class RegimeAssetEntry:
    asset: str  # asset identifier, e.g. "SPY" (asset-neutral)
    available: bool  # False => generator could not run (MISSING)
    signals: tuple[RegimeSignalEntry, ...]  # already High-first; empty => no-high-conviction

    @property
    def no_high_conviction(self) -> bool:
        # configured asset that ran but fired nothing (EMPTY)
        return self.available and len(self.signals) == 0


@dataclass(frozen=True)
class MarketRegimeSection:
    assets: tuple[RegimeAssetEntry, ...]  # one entry per configured asset

    @property
    def available(self) -> bool:
        # the whole regime input is unavailable when no asset is present/empty
        return any(asset.available for asset in self.assets)


@dataclass(frozen=True)
class VpaSignal:
    ticker: str
    signal_score: float


@dataclass(frozen=True)
class TopVpaSignalsSection:
    signals: tuple[VpaSignal, ...]  # already top-5, ordered; empty => placeholder (Req 4.4)


@dataclass(frozen=True)
class Opportunity:
    ticker: str
    drawdown_pct: float
    momentum_pct: float


@dataclass(frozen=True)
class OpportunitiesSection:
    opportunities: tuple[Opportunity, ...]  # deterministic order; empty => placeholder (Req 5.2)


@dataclass(frozen=True)
class DailySummarySection:
    opportunity_count: int  # Req 6.1
    vpa_signal_count: int  # Req 6.2
    primary_asset: str  # the primary asset the summary reflects
    primary_direction: str | None  # highest-confidence record's adjusted_direction, or None
    primary_confidence: str | None  # highest-confidence record's confidence_level, or None
    # primary_direction / primary_confidence are both None => no-high-conviction / unavailable (Req 6.2, 6.4)


@dataclass(frozen=True)
class ConsolidatedReport:
    report_date: date
    market_regime: MarketRegimeSection
    top_vpa_signals: TopVpaSignalsSection
    opportunities: OpportunitiesSection
    daily_summary: DailySummarySection


def to_dict(report: ConsolidatedReport) -> dict:
    """Serialise a ConsolidatedReport to a primitive, JSON-ready dict.

    Pure function, no I/O. The returned structure matches the snapshot schema
    (schema_version 1). ``report_date`` is written as an ISO 8601 string;
    ``market_regime`` is keyed by asset with an ``available`` flag so a MISSING
    asset is distinguishable from an EMPTY one. Inverse of :func:`from_dict`.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "report_date": report.report_date.isoformat(),
        "market_regime": {
            "assets": {
                asset.asset: {
                    "available": asset.available,
                    "signals": [
                        {
                            "signal_type": signal.signal_type,
                            "adjusted_direction": signal.adjusted_direction,
                            "confidence_level": signal.confidence_level,
                        }
                        for signal in asset.signals
                    ],
                }
                for asset in report.market_regime.assets
            }
        },
        "top_vpa_signals": {
            "signals": [
                {"ticker": signal.ticker, "signal_score": signal.signal_score}
                for signal in report.top_vpa_signals.signals
            ]
        },
        "opportunities": {
            "opportunities": [
                {
                    "ticker": opportunity.ticker,
                    "drawdown_pct": opportunity.drawdown_pct,
                    "momentum_pct": opportunity.momentum_pct,
                }
                for opportunity in report.opportunities.opportunities
            ]
        },
        "daily_summary": {
            "opportunity_count": report.daily_summary.opportunity_count,
            "vpa_signal_count": report.daily_summary.vpa_signal_count,
            "primary_asset": report.daily_summary.primary_asset,
            "primary_direction": report.daily_summary.primary_direction,
            "primary_confidence": report.daily_summary.primary_confidence,
        },
    }


def from_dict(data: dict) -> ConsolidatedReport:
    """Rebuild a ConsolidatedReport from its primitive dict form.

    Pure inverse of :func:`to_dict`: ``report_date`` is parsed with
    ``date.fromisoformat`` and each section is rebuilt from its list/map so that
    ``from_dict(to_dict(r)) == r`` holds for all valid ConsolidatedReport values.
    """
    regime_assets = data["market_regime"]["assets"]
    market_regime = MarketRegimeSection(
        assets=tuple(
            RegimeAssetEntry(
                asset=asset_name,
                available=asset_data["available"],
                signals=tuple(
                    RegimeSignalEntry(
                        signal_type=signal["signal_type"],
                        adjusted_direction=signal["adjusted_direction"],
                        confidence_level=signal["confidence_level"],
                    )
                    for signal in asset_data["signals"]
                ),
            )
            for asset_name, asset_data in regime_assets.items()
        )
    )

    top_vpa_signals = TopVpaSignalsSection(
        signals=tuple(
            VpaSignal(ticker=signal["ticker"], signal_score=signal["signal_score"])
            for signal in data["top_vpa_signals"]["signals"]
        )
    )

    opportunities = OpportunitiesSection(
        opportunities=tuple(
            Opportunity(
                ticker=opportunity["ticker"],
                drawdown_pct=opportunity["drawdown_pct"],
                momentum_pct=opportunity["momentum_pct"],
            )
            for opportunity in data["opportunities"]["opportunities"]
        )
    )

    summary = data["daily_summary"]
    daily_summary = DailySummarySection(
        opportunity_count=summary["opportunity_count"],
        vpa_signal_count=summary["vpa_signal_count"],
        primary_asset=summary["primary_asset"],
        primary_direction=summary["primary_direction"],
        primary_confidence=summary["primary_confidence"],
    )

    return ConsolidatedReport(
        report_date=date.fromisoformat(data["report_date"]),
        market_regime=market_regime,
        top_vpa_signals=top_vpa_signals,
        opportunities=opportunities,
        daily_summary=daily_summary,
    )
