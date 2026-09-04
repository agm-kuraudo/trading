from __future__ import annotations

import csv
import io
from html import escape

from vpa.reports.models import CSV_COLUMNS, DailyReport, TickerScanResult


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _row(report: DailyReport, result: TickerScanResult) -> dict[str, str]:
    return {
        "report_date": report.report_date.isoformat(),
        "source_ticker": result.source_ticker,
        "report_ticker": result.report_ticker,
        "status": result.status,
        "signal_score": _csv_value(result.signal_score),
        "signal_components": result.signal_components,
        "opportunity_status": result.opportunity_status,
        "drawdown_pct": _csv_value(result.drawdown_pct),
        "momentum_pct": _csv_value(result.momentum_pct),
        "fifty_two_week_high": _csv_value(result.fifty_two_week_high),
        "error_message": result.error_message or "",
    }


def render_csv(report: DailyReport) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for result in [*report.successful_results, *report.failed_results]:
        writer.writerow(_row(report, result))
    return output.getvalue()


def _table_rows(results: list[TickerScanResult]) -> str:
    if not results:
        return '<tr><td colspan="7">No results</td></tr>'
    rows = []
    for result in results:
        rows.append(
            "<tr>"
            f"<td>{escape(result.report_ticker)}</td>"
            f"<td>{escape(_csv_value(result.signal_score))}</td>"
            f"<td>{escape(result.signal_components)}</td>"
            f"<td>{escape(result.opportunity_status)}</td>"
            f"<td>{escape(_csv_value(result.drawdown_pct))}</td>"
            f"<td>{escape(_csv_value(result.momentum_pct))}</td>"
            f"<td>{escape(result.error_message or '')}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_html(report: DailyReport) -> str:
    top = report.successful_results[:5]
    bottom = list(reversed(report.successful_results[-5:]))
    opportunity_rows = report.opportunities
    failed_rows = report.failed_results
    title_date = escape(report.report_date.isoformat())
    filter_state = "enabled" if report.opportunity_filter_enabled else "disabled"

    def table(title: str, results: list[TickerScanResult]) -> str:
        return (
            f"<section><h2>{escape(title)}</h2>"
            "<table><thead><tr><th>Ticker</th><th>Signal score</th>"
            "<th>Signal components</th><th>Opportunity</th><th>Drawdown %</th>"
            "<th>Momentum %</th><th>Error</th></tr></thead>"
            f"<tbody>{_table_rows(results)}</tbody></table></section>"
        )

    opportunity_section = (
        table("Opportunities", opportunity_rows)
        if report.opportunity_filter_enabled
        else ("<section><h2>Opportunities</h2><p>Opportunity filter disabled.</p></section>")
    )
    failures_section = table("Failed tickers", failed_rows) if failed_rows else ""

    return f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><title>SP-500 VPA report {title_date}</title>
<style>
body{{font-family:Arial,sans-serif;margin:2rem;color:#222}}
table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}
th,td{{border:1px solid #ccc;padding:.45rem;text-align:left}}
th{{background:#eee}}
section{{margin-top:2rem}}
</style>
</head><body><h1>SP-500 VPA report</h1><p>Date: {title_date}</p>
<p>Attempted: {report.attempted_count} | Successful: {report.successful_count} |
Failed: {report.failed_count} | Opportunities: {report.opportunity_count} |
Opportunity filter: {escape(filter_state)}</p>
{table("Top recommendations", top)}
{table("Bottom recommendations", bottom)}
{opportunity_section}
{failures_section}
</body></html>
"""


def render_plain_text(report: DailyReport) -> str:
    lines = [f"SP-500 VPA report: {report.report_date.isoformat()}", "", "Top 5 rows:"]
    for result in report.successful_results[:5]:
        lines.append(f"{result.report_ticker}: {result.signal_score}")
    lines.extend(["", "Bottom 5 rows:"])
    for result in reversed(report.successful_results[-5:]):
        lines.append(f"{result.report_ticker}: {result.signal_score}")
    lines.extend(["", "Opportunities"])
    if not report.opportunity_filter_enabled:
        lines.append("Opportunities: disabled")
    elif not report.opportunities:
        lines.append("No opportunities found")
    else:
        for result in report.opportunities:
            lines.append(
                f"{result.report_ticker}: drawdown={result.drawdown_pct:.1f}% " f"momentum={result.momentum_pct:.1f}%"
            )
    if report.failed_results:
        lines.extend(["", "Failed tickers"])
        lines.extend(f"{result.report_ticker}: {result.error_message}" for result in report.failed_results)
    return "\n".join(lines) + "\n"
