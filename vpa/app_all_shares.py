from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path

from vpa.app_runner import MarketAnalyzer
from vpa.opportunities import evaluate_ticker, load_drawdown_config
from vpa.reports import DailyReport, TickerScanResult, write_reports

PROJECT_ROOT = Path(__file__).parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"
DEFAULT_TICKERS_PATH = PROJECT_ROOT / "data" / "SP500-tickers.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "log"


def load_tickers(tickers_path: str | Path = DEFAULT_TICKERS_PATH) -> list[tuple[str, str]]:
    """Load source ticker symbols and their report-safe normalized values."""
    tickers = []
    for line in Path(tickers_path).read_text(encoding="utf-8").splitlines():
        source_ticker = line.strip()
        if source_ticker:
            tickers.append((source_ticker, source_ticker.replace(".", "-")))
    return tickers


def _signal_components(signals: dict[str, object]) -> str:
    component_values = {key: value for key, value in signals.items() if key.endswith("_signals") and value}
    return json.dumps(component_values, sort_keys=True)


def run_scan(
    tickers: Iterable[tuple[str, str]],
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    analyzer_factory: Callable[..., MarketAnalyzer] = MarketAnalyzer,
    opportunity_evaluator: Callable[..., dict | None] = evaluate_ticker,
) -> DailyReport:
    """Run the SP-500 analysis and return one structured result per ticker."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    drawdown_config = load_drawdown_config(config)
    results: list[TickerScanResult] = []

    for source_ticker, report_ticker in tickers:
        try:
            analyzer = analyzer_factory(
                config_path=str(config_path),
                ticker_symbol=report_ticker,
                log_level="ERROR",
            )
            signal_score = round(float(analyzer.process_data()), 1)
            signals = analyzer.get_last_signals()
            opportunity_status = "disabled" if not drawdown_config["enabled"] else "does_not_qualify"
            opportunity = None
            if drawdown_config["enabled"]:
                opportunity = opportunity_evaluator(
                    df=analyzer.get_dataframe(),
                    drawdown_threshold=drawdown_config["drawdown_threshold"],
                    momentum_period=drawdown_config["momentum_period"],
                )
                if opportunity is not None:
                    opportunity_status = "qualifies"

            results.append(
                TickerScanResult(
                    source_ticker=source_ticker,
                    report_ticker=report_ticker,
                    status="success",
                    signal_score=signal_score,
                    signal_components=_signal_components(signals),
                    opportunity_status=opportunity_status,
                    drawdown_pct=opportunity.get("drawdown_pct") if opportunity else None,
                    momentum_pct=opportunity.get("momentum") if opportunity else None,
                    fifty_two_week_high=opportunity.get("fifty_two_week_high") if opportunity else None,
                )
            )
        except Exception as exc:
            results.append(
                TickerScanResult(
                    source_ticker=source_ticker,
                    report_ticker=report_ticker,
                    status="failed",
                    error_message=str(exc),
                )
            )

    return DailyReport(
        report_date=date.today(),
        results=tuple(results),
        opportunity_filter_enabled=bool(drawdown_config["enabled"]),
    )


def main(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    tickers_path: str | Path = DEFAULT_TICKERS_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    report_date: date | None = None,
    tickers: Iterable[tuple[str, str]] | None = None,
) -> dict[str, Path]:
    """Run the scan and write CSV, HTML, and plain-text reports."""
    scan_tickers = load_tickers(tickers_path) if tickers is None else tickers
    report = run_scan(scan_tickers, config_path=config_path)
    if report_date is not None:
        report = DailyReport(report_date, report.results, report.opportunity_filter_enabled)
    paths = write_reports(report, output_dir)
    print(f"Reports written: {', '.join(str(path) for path in paths.values())}")
    return paths


if __name__ == "__main__":
    main()
