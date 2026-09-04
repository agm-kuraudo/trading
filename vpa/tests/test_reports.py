import csv
import io
from datetime import date

from vpa.app_all_shares import run_scan
from vpa.reports import DailyReport, TickerScanResult, render_csv, render_html, write_reports


class FakeAnalyzer:
    def __init__(self, **kwargs):
        self.ticker = kwargs["ticker_symbol"]

    def process_data(self):
        if self.ticker == "FAIL":
            raise RuntimeError("temporary failure <details>")
        return 4.25 if self.ticker == "HIGH" else 1.0

    def get_last_signals(self):
        return {"single_candle_signals": ["Up Bar"]}

    def get_dataframe(self):
        return object()


def fake_opportunity_evaluator(*, df, drawdown_threshold, momentum_period):
    del df, drawdown_threshold, momentum_period
    return {"drawdown_pct": -25.0, "momentum": 4.0, "fifty_two_week_high": 100.0}


def make_report():
    return DailyReport(
        report_date=date(2026, 9, 4),
        results=(
            TickerScanResult("LOW", "LOW", "success", 1.0, '{"signals": ["Up Bar"]}', "does_not_qualify"),
            TickerScanResult(
                "HIGH", "HIGH", "success", 4.25, '{"signals": ["Up Bar"]}', "qualifies", -25.0, 4.0, 100.0
            ),
            TickerScanResult("BAD<", "BAD<", "failed", error_message="broken <script>alert(1)</script>"),
        ),
        opportunity_filter_enabled=True,
    )


def test_report_orders_successes_and_failures_deterministically():
    report = make_report()

    assert [result.report_ticker for result in report.successful_results] == ["HIGH", "LOW"]
    assert [result.report_ticker for result in report.failed_results] == ["BAD<"]
    assert report.attempted_count == 3
    assert report.successful_count == 2
    assert report.failed_count == 1


def test_csv_has_stable_schema_and_escaped_fields():
    rows = list(csv.DictReader(io.StringIO(render_csv(make_report()))))

    assert rows[0]["report_ticker"] == "HIGH"
    assert rows[0]["signal_score"] == "4.25"
    assert rows[-1]["error_message"] == "broken <script>alert(1)</script>"
    assert rows[-1]["signal_score"] == ""


def test_html_contains_sections_and_escapes_dynamic_values():
    html = render_html(make_report())

    assert "Top recommendations" in html
    assert "Bottom recommendations" in html
    assert "Failed tickers" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_write_reports_creates_all_date_stamped_files(tmp_path):
    paths = write_reports(make_report(), tmp_path / "reports")

    assert set(paths) == {"csv", "html", "txt"}
    assert all(path.exists() for path in paths.values())
    assert paths["csv"].name == "share_output_20260904.csv"
    assert paths["html"].read_text(encoding="utf-8").startswith("<!doctype html>")


def test_run_scan_records_success_and_failure_without_network():
    report = run_scan(
        [("HIGH", "HIGH"), ("FAIL", "FAIL")],
        analyzer_factory=FakeAnalyzer,
        opportunity_evaluator=fake_opportunity_evaluator,
    )

    assert report.successful_count == 1
    assert report.failed_count == 1
    assert report.results[0].opportunity_status == "qualifies"
    assert report.results[1].error_message == "temporary failure <details>"
