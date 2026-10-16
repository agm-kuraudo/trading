"""Orchestrator unit tests for the Daily Market Report (SP-356, Task 8.3).

These are example/edge-case unit tests for ``vpa.reports.daily_market_report.main``
driven entirely through its injection seams — a fake ``scan_fn`` and a fake
``generator_factory`` — so nothing here touches yfinance or the network.

Covered:

- **Happy path** (Req 10.1, 10.2): a populated scan plus a per-asset generator
  that fires signals -> ``main() == 0``, exactly one SUCCESS line on stdout, the
  consolidated text report and the dated JSON snapshot both exist, ``write_reports``
  ran for the all-shares scan output (``share_output_*`` files, Req 1.3), and the
  SP-315 generator's ``.run()`` was invoked once per configured asset via the
  injected factory (Req 2.1, 2.3, 7.4).
- **Graceful degradation** (Req 10.3): the scan raises AND one regime asset's
  ``.run()`` raises ``InsufficientDataError`` (the other asset fires) -> ``main()``
  still returns 0, exactly one SUCCESS line, and the consolidated report is still
  produced with placeholder sections.
- **Build/write failure** (Req 1.7, 10.4): the render step is forced to raise, so
  the deliverable cannot be produced -> ``main() != 0``, exactly one FAILURE line
  on stderr, and NO partial consolidated report is left on disk. Forcing the
  failure at *render* (before the text file is written) lets us assert "no partial
  report" directly rather than relying only on the exit-code/stderr contract.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import vpa.reports.daily_market_report as orchestrator
from vpa.ml_validation.daily_signal import SignalRecord
from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.reports.models import DailyReport, TickerScanResult

REPORT_DATE_ISO = "2026-07-15"
REPORT_DATE = date.fromisoformat(REPORT_DATE_ISO)


# --- Fakes -----------------------------------------------------------------


def _populated_report(report_date: date) -> DailyReport:
    """A real DailyReport with one successful/qualifying row and one failure row.

    The success row has a signal_score (so Top VPA Signals populates) and
    ``opportunity_status="qualifies"`` (so Opportunities populates).
    """
    return DailyReport(
        report_date=report_date,
        results=(
            TickerScanResult(
                source_ticker="AAA",
                report_ticker="AAA",
                status="success",
                signal_score=9.5,
                signal_components="{}",
                opportunity_status="qualifies",
                drawdown_pct=-12.0,
                momentum_pct=3.0,
                fifty_two_week_high=100.0,
            ),
            TickerScanResult(
                source_ticker="BBB",
                report_ticker="BBB",
                status="failed",
                error_message="boom",
            ),
        ),
        opportunity_filter_enabled=True,
    )


def _make_fake_scan(report_date: date, *, raises: bool = False):
    """Build a fake scan callable with signature ``fake_scan(tickers, config_path=...)``."""

    def fake_scan(tickers, config_path=None):  # noqa: ANN001 - test fake mirrors run_scan's loose signature
        if raises:
            raise RuntimeError("injected scan failure")
        return _populated_report(report_date)

    return fake_scan


class _FakeGenerator:
    """A fake SP-315 generator whose ``.run()`` returns High-first SignalRecords.

    Constructible with the exact kwargs ``collect_regime`` uses
    (``output_dir=``, ``lookback_days=``, ``ticker=``). Per-ticker run calls are
    recorded on the shared ``calls`` dict so tests can assert ``.run()`` fired
    once per configured asset. ``fail_assets`` names tickers whose ``.run()``
    raises ``InsufficientDataError`` (modelling a per-asset failure -> MISSING).
    """

    def __init__(self, *, calls: dict[str, int], fail_assets: frozenset[str], output_dir, lookback_days, ticker):
        self._calls = calls
        self._fail_assets = fail_assets
        self.output_dir = output_dir
        self.lookback_days = lookback_days
        self.ticker = ticker

    def run(self) -> list[SignalRecord]:
        self._calls[self.ticker] = self._calls.get(self.ticker, 0) + 1
        if self.ticker in self._fail_assets:
            raise InsufficientDataError(f"too few bars for {self.ticker}")
        # High-first: a strong "High" record ahead of a weaker one.
        return [
            SignalRecord(
                ticker=self.ticker,
                date=REPORT_DATE_ISO,
                signal_type="distribution",
                original_direction="down",
                adjusted_direction="BUY",
                confidence_level="High",
                suggested_hold_days=10,
            ),
            SignalRecord(
                ticker=self.ticker,
                date=REPORT_DATE_ISO,
                signal_type="strong_bearish",
                original_direction="down",
                adjusted_direction="BUY",
                confidence_level="Medium-High",
                suggested_hold_days=10,
            ),
        ]


def _make_generator_factory(calls: dict[str, int], fail_assets: frozenset[str] = frozenset()):
    """Return a factory producing ``_FakeGenerator`` instances sharing ``calls``."""

    def factory(*, output_dir, lookback_days, ticker):
        return _FakeGenerator(
            calls=calls,
            fail_assets=fail_assets,
            output_dir=output_dir,
            lookback_days=lookback_days,
            ticker=ticker,
        )

    return factory


# --- Shared fixtures-as-helpers --------------------------------------------


def _write_tickers(tmp_path: Path) -> Path:
    """Write a tiny real tickers CSV so ``load_tickers`` has something to read."""
    tickers_path = tmp_path / "tickers.csv"
    tickers_path.write_text("AAA\nBBB\n", encoding="utf-8")
    return tickers_path


def _env(archive_dir: Path, assets: str = "SPY,QQQ") -> dict[str, str]:
    """Pin a deterministic date, the configured assets, and the archive dir."""
    return {
        orchestrator.ENV_REPORT_DATE: REPORT_DATE_ISO,
        orchestrator.ENV_CONFIGURED_ASSETS: assets,
        orchestrator.ENV_ARCHIVE_DIR: str(archive_dir),
    }


def _status_lines(captured) -> tuple[list[str], list[str]]:
    """Return (stdout Report_Status lines, stderr Report_Status lines)."""
    out = [line for line in captured.out.splitlines() if line.startswith("Report_Status:")]
    err = [line for line in captured.err.splitlines() if line.startswith("Report_Status:")]
    return out, err


# --- Tests -----------------------------------------------------------------


def test_happy_path_returns_zero_and_produces_report(tmp_path, capsys):
    """Populated scan + firing generator -> exit 0, one SUCCESS line, all outputs written.

    Validates: Requirements 1.3, 2.1, 2.3, 7.4, 10.1, 10.2
    """
    output_dir = tmp_path / "log"
    archive_dir = tmp_path / "history"
    tickers_path = _write_tickers(tmp_path)
    config_path = tmp_path / "config.json"  # absent -> defaults; env overrides win anyway
    calls: dict[str, int] = {}

    exit_code = orchestrator.main(
        config_path=config_path,
        tickers_path=tickers_path,
        output_dir=output_dir,
        scan_fn=_make_fake_scan(REPORT_DATE),
        generator_factory=_make_generator_factory(calls),
        env=_env(archive_dir, assets="SPY,QQQ"),
    )

    # Req 10.2: report produced -> exit 0.
    assert exit_code == 0

    # Req 10.1: exactly one terminal Report_Status line, on stdout (success), none on stderr.
    out_lines, err_lines = _status_lines(capsys.readouterr())
    assert len(out_lines) == 1
    assert "SUCCESS" in out_lines[0]
    assert REPORT_DATE_ISO in out_lines[0]
    assert err_lines == []

    # The consolidated text report and the dated JSON snapshot both exist.
    consolidated = output_dir / f"consolidated_report_{REPORT_DATE:%Y%m%d}.txt"
    snapshot = archive_dir / f"{REPORT_DATE_ISO}.json"
    assert consolidated.exists()
    assert snapshot.exists()  # Req 7.4: archive dir created and snapshot written

    # Req 1.3: write_reports ran for the all-shares scan output (share_output_* files).
    share_csv = output_dir / f"share_output_{REPORT_DATE:%Y%m%d}.csv"
    share_txt = output_dir / f"share_output_{REPORT_DATE:%Y%m%d}.txt"
    share_html = output_dir / f"share_output_{REPORT_DATE:%Y%m%d}.html"
    assert share_csv.exists()
    assert share_txt.exists()
    assert share_html.exists()

    # Req 2.1/2.3/7.4: the SP-315 generator's .run() fired once per configured asset.
    assert calls == {"SPY": 1, "QQQ": 1}


def test_graceful_degradation_returns_zero_with_report(tmp_path, capsys):
    """Scan failure + one failing regime asset -> still exit 0 with a report produced.

    Validates: Requirements 10.3
    """
    output_dir = tmp_path / "log"
    archive_dir = tmp_path / "history"
    tickers_path = _write_tickers(tmp_path)
    config_path = tmp_path / "config.json"
    calls: dict[str, int] = {}

    exit_code = orchestrator.main(
        config_path=config_path,
        tickers_path=tickers_path,
        output_dir=output_dir,
        # Scan raises -> VPA scan input is Missing.
        scan_fn=_make_fake_scan(REPORT_DATE, raises=True),
        # SPY's .run() raises InsufficientDataError -> MISSING; QQQ still fires.
        generator_factory=_make_generator_factory(calls, fail_assets=frozenset({"SPY"})),
        env=_env(archive_dir, assets="SPY,QQQ"),
    )

    # Req 10.3: graceful degradation is success.
    assert exit_code == 0

    out_lines, err_lines = _status_lines(capsys.readouterr())
    assert len(out_lines) == 1
    assert "SUCCESS" in out_lines[0]
    assert err_lines == []

    # The consolidated report is still produced despite the partial failures.
    consolidated = output_dir / f"consolidated_report_{REPORT_DATE:%Y%m%d}.txt"
    assert consolidated.exists()

    # The scan was Missing, so write_reports is NOT called (no share_output files).
    assert not (output_dir / f"share_output_{REPORT_DATE:%Y%m%d}.csv").exists()

    # Both assets were still attempted exactly once (per-asset isolation).
    assert calls == {"SPY": 1, "QQQ": 1}


def test_build_write_failure_returns_nonzero_without_partial_report(tmp_path, capsys, monkeypatch):
    """Render failure -> exit non-zero, one FAILURE line on stderr, no partial report.

    The failure is forced at the *render* step (before the consolidated text file
    is written), so we can assert directly that no partial consolidated report was
    left on disk — alongside the exit-code + stderr contract (Req 1.7, 10.4).

    Validates: Requirements 1.7, 10.4
    """
    output_dir = tmp_path / "log"
    archive_dir = tmp_path / "history"
    tickers_path = _write_tickers(tmp_path)
    config_path = tmp_path / "config.json"
    calls: dict[str, int] = {}

    def _boom(_report):
        raise RuntimeError("injected render failure")

    monkeypatch.setattr(orchestrator, "render_consolidated_text", _boom)

    exit_code = orchestrator.main(
        config_path=config_path,
        tickers_path=tickers_path,
        output_dir=output_dir,
        scan_fn=_make_fake_scan(REPORT_DATE),
        generator_factory=_make_generator_factory(calls),
        env=_env(archive_dir, assets="SPY,QQQ"),
    )

    # Req 1.7/10.4: the deliverable could not be produced -> non-zero exit.
    assert exit_code != 0

    # Req 10.1/10.4: exactly one terminal Report_Status line, on stderr (failure), none on stdout.
    out_lines, err_lines = _status_lines(capsys.readouterr())
    assert len(err_lines) == 1
    assert "FAILURE" in err_lines[0]
    assert REPORT_DATE_ISO in err_lines[0]
    assert out_lines == []

    # No partial consolidated report (text or snapshot) was left for that date.
    assert not (output_dir / f"consolidated_report_{REPORT_DATE:%Y%m%d}.txt").exists()
    assert not (archive_dir / f"{REPORT_DATE_ISO}.json").exists()
