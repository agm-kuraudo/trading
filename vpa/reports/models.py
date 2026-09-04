from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

ReportStatus = Literal["success", "failed"]
OpportunityStatus = Literal["qualifies", "does_not_qualify", "disabled", "unavailable"]


@dataclass(frozen=True)
class TickerScanResult:
    source_ticker: str
    report_ticker: str
    status: ReportStatus
    signal_score: float | None = None
    signal_components: str = ""
    opportunity_status: OpportunityStatus = "unavailable"
    drawdown_pct: float | None = None
    momentum_pct: float | None = None
    fifty_two_week_high: float | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DailyReport:
    report_date: date
    results: tuple[TickerScanResult, ...]
    opportunity_filter_enabled: bool

    @property
    def successful_results(self) -> list[TickerScanResult]:
        return sorted(
            (result for result in self.results if result.status == "success"),
            key=lambda result: (-(result.signal_score or 0), result.report_ticker),
        )

    @property
    def failed_results(self) -> list[TickerScanResult]:
        return sorted(
            (result for result in self.results if result.status == "failed"),
            key=lambda result: result.report_ticker,
        )

    @property
    def opportunities(self) -> list[TickerScanResult]:
        return sorted(
            (result for result in self.results if result.opportunity_status == "qualifies"),
            key=lambda result: (result.drawdown_pct if result.drawdown_pct is not None else 0, result.report_ticker),
        )

    @property
    def attempted_count(self) -> int:
        return len(self.results)

    @property
    def successful_count(self) -> int:
        return sum(result.status == "success" for result in self.results)

    @property
    def failed_count(self) -> int:
        return sum(result.status == "failed" for result in self.results)

    @property
    def opportunity_count(self) -> int:
        return len(self.opportunities)


CSV_COLUMNS = (
    "report_date",
    "source_ticker",
    "report_ticker",
    "status",
    "signal_score",
    "signal_components",
    "opportunity_status",
    "drawdown_pct",
    "momentum_pct",
    "fifty_two_week_high",
    "error_message",
)
