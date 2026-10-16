"""Orchestrator entrypoint for the Daily Market Report (SP-356).

This module is the single in-memory orchestrator job. In one run it:

1. Resolves the ``Report_Date``, the ``Configured_Assets`` for the SP-315
   market-regime signal, and the ``Historical_Archive`` directory from config
   and environment (with sensible defaults consistent with ``vpa/log/``).
2. Runs the all-shares VPA scan in-process (``app_all_shares.run_scan``) to
   obtain one in-memory ``DailyReport``; on failure the VPA scan input is
   treated as **Missing** (``scan_result = None``).
3. Runs the SP-315 regime wrapper (``regime.collect_regime``) once per
   configured asset.

4. Writes the all-shares scan's individual outputs (``write_reports``), builds
   exactly one ``ConsolidatedReport`` (``build_consolidated_report``), renders
   it to ``vpa/log/consolidated_report_YYYYMMDD.txt`` (``render_consolidated_text``),
   archives a JSON snapshot (``write_snapshot``), and emits exactly one terminal
   ``Report_Status`` line mapped to the process exit code.

The seams below (``scan_fn``, ``generator_factory``) exist so task 8.3's unit
tests can inject fakes and never touch yfinance or the network.

Nothing in this module touches yfinance or the network at import time.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from pathlib import Path

from vpa.app_all_shares import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TICKERS_PATH,
    load_tickers,
    run_scan,
)
from vpa.ml_validation.daily_signal import DailySignalGenerator
from vpa.reports.consolidated_builder import build_consolidated_report
from vpa.reports.consolidated_renderer import render_consolidated_text
from vpa.reports.models import DailyReport
from vpa.reports.regime import RegimeAssetResult, collect_regime
from vpa.reports.snapshot_writer import write_snapshot
from vpa.reports.writers import write_reports

logger = logging.getLogger(__name__)

# --- Config / env resolution constants -------------------------------------

# Top-level key in vpa/config/config.json holding the report's own settings.
# A flat JSON dict today; this NEW optional sub-object carries the
# Configured_Assets list, the regime lookback, and the archive directory.
# Missing/partial config falls back to the defaults below (never an error).
CONFIG_SECTION_KEY = "daily_market_report"

# The current primary asset; default Configured_Assets list when unset.
DEFAULT_CONFIGURED_ASSETS: tuple[str, ...] = ("SPY",)
DEFAULT_REGIME_LOOKBACK_DAYS = 200

# Historical_Archive default: a sibling of vpa/log/ so snapshots sit alongside
# the other report outputs. ``DEFAULT_OUTPUT_DIR`` is ``vpa/log``.
DEFAULT_ARCHIVE_DIR = DEFAULT_OUTPUT_DIR / "history"

# Environment-variable overrides (primarily for tests / ad-hoc runs).
ENV_REPORT_DATE = "DAILY_MARKET_REPORT_DATE"  # ISO 8601 YYYY-MM-DD
ENV_CONFIGURED_ASSETS = "DAILY_MARKET_REPORT_ASSETS"  # comma-separated
ENV_ARCHIVE_DIR = "DAILY_MARKET_REPORT_ARCHIVE_DIR"


def _load_config(config_path: str | Path) -> dict:
    """Load the flat JSON config dict, returning ``{}`` on any read error.

    Resolution must be defensive: a missing or malformed config file must not
    stop the orchestrator from running with its defaults.
    """
    try:
        return json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read config at %s (%s); using defaults.", config_path, exc)
        return {}


def resolve_report_date(argv: Sequence[str] | None, env: dict[str, str]) -> date:
    """Resolve the ``Report_Date``.

    Priority: CLI positional arg > ``DAILY_MARKET_REPORT_DATE`` env var > the
    Pi local date (``date.today()``). CLI arg and env var are ISO 8601
    (YYYY-MM-DD) and exist so tests can pin a deterministic date.
    """
    if argv:
        return date.fromisoformat(argv[0])
    env_value = env.get(ENV_REPORT_DATE)
    if env_value:
        return date.fromisoformat(env_value)
    return date.today()


def resolve_configured_assets(config: dict, env: dict[str, str]) -> tuple[str, ...]:
    """Resolve the ``Configured_Assets`` list.

    Priority: ``DAILY_MARKET_REPORT_ASSETS`` env var (comma-separated) > the
    ``daily_market_report.configured_assets`` config key > the default
    ``["SPY"]``. Supporting an arbitrary number N of assets is a configuration
    change, not a code change (Req 2.4).
    """
    env_value = env.get(ENV_CONFIGURED_ASSETS)
    if env_value:
        assets = tuple(item.strip() for item in env_value.split(",") if item.strip())
        if assets:
            return assets

    section = config.get(CONFIG_SECTION_KEY, {})
    if isinstance(section, dict):
        configured = section.get("configured_assets")
        if isinstance(configured, list):
            assets = tuple(str(item).strip() for item in configured if str(item).strip())
            if assets:
                return assets

    return DEFAULT_CONFIGURED_ASSETS


def resolve_regime_lookback_days(config: dict) -> int:
    """Resolve the regime lookback window (calendar days), default 200."""
    section = config.get(CONFIG_SECTION_KEY, {})
    if isinstance(section, dict):
        lookback = section.get("regime_lookback_days")
        if isinstance(lookback, int) and not isinstance(lookback, bool) and lookback > 0:
            return lookback
    return DEFAULT_REGIME_LOOKBACK_DAYS


def resolve_archive_dir(config: dict, env: dict[str, str]) -> Path:
    """Resolve the ``Historical_Archive`` directory.

    Priority: ``DAILY_MARKET_REPORT_ARCHIVE_DIR`` env var > the
    ``daily_market_report.historical_archive_dir`` config key > the default
    (``vpa/log/history``, consistent with ``vpa/log/``).
    """
    env_value = env.get(ENV_ARCHIVE_DIR)
    if env_value:
        return Path(env_value)

    section = config.get(CONFIG_SECTION_KEY, {})
    if isinstance(section, dict):
        archive = section.get("historical_archive_dir")
        if isinstance(archive, str) and archive.strip():
            return Path(archive)

    return DEFAULT_ARCHIVE_DIR


def _acquire_scan_result(
    scan_fn: Callable[..., DailyReport],
    tickers: Iterable[tuple[str, str]],
    config_path: str | Path,
    report_date: date,
) -> DailyReport | None:
    """Obtain the VPA_Scan_Result, or ``None`` when the scan fails (Missing).

    ``run_scan`` stamps ``report_date=date.today()`` internally, so when the
    resolved ``Report_Date`` differs we rebuild the ``DailyReport`` with the
    resolved date (mirroring ``app_all_shares.main``). A scan failure is caught,
    logged (Req 9.2), and the input is treated as Missing (Req 2.1).
    """
    try:
        report = scan_fn(tickers, config_path=config_path)
    except Exception as exc:  # noqa: BLE001 - a scan failure degrades to a Missing input, not a crash.
        logger.error("VPA scan failed; treating VPA scan input as Missing: %s: %s", type(exc).__name__, exc)
        return None

    if report.report_date != report_date:
        report = DailyReport(report_date, report.results, report.opportunity_filter_enabled)
    return report


def main(
    argv: list[str] | None = None,
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    tickers_path: str | Path = DEFAULT_TICKERS_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    scan_fn: Callable[..., DailyReport] = run_scan,
    generator_factory: Callable[..., object] = DailySignalGenerator,
    env: dict[str, str] | None = None,
) -> int:
    """Run the full orchestrator in-process and return a process exit code.

    Resolves config and inputs, runs the upstream scans, builds/renders/writes
    the Consolidated_Daily_Report plus its JSON snapshot, and emits exactly one
    terminal ``Report_Status`` line (stdout on success, stderr on failure).

    0 = report produced (Req 10.2), INCLUDING partial upstream failure
        (graceful degradation is success, Req 10.3).
    non-zero = the report could not be produced at all (Req 1.7, 10.4).

    Args:
        argv: Optional CLI args; ``argv[0]`` (if present) is the ISO 8601
            Report_Date override.
        config_path: Path to ``vpa/config/config.json``.
        tickers_path: Path to the ticker CSV for the all-shares scan.
        output_dir: Directory for the scan's individual outputs (``vpa/log``).
        scan_fn: Injectable scan callable (defaults to ``run_scan``) so tests
            pass a fake and never touch yfinance/network.
        generator_factory: Injectable SP-315 generator factory passed through to
            the regime wrapper (defaults to ``DailySignalGenerator``).
        env: Optional environment mapping (defaults to ``os.environ``) so tests
            can pin overrides without mutating the real environment.
    """
    environ = dict(os.environ) if env is None else env

    # --- Config resolution (Req 2.4) -------------------------------------
    config = _load_config(config_path)
    report_date = resolve_report_date(argv, environ)
    configured_assets = resolve_configured_assets(config, environ)
    lookback_days = resolve_regime_lookback_days(config)
    archive_dir = resolve_archive_dir(config, environ)

    logger.info(
        "Daily Market Report: report_date=%s, assets=%s, archive_dir=%s",
        report_date.isoformat(),
        list(configured_assets),
        archive_dir,
    )

    # --- Input acquisition -----------------------------------------------
    # VPA_Scan_Result: run the all-shares scan in-process (Req 2.1). On failure
    # the input is Missing (None); both the Top VPA Signals and Opportunities
    # views then degrade to placeholders in the builder.
    tickers = load_tickers(tickers_path)
    scan_result: DailyReport | None = _acquire_scan_result(scan_fn, tickers, config_path, report_date)

    # Market_Regime_Signal: run the SP-315 generator once per configured asset
    # (Req 2.3, 2.4). The wrapper isolates per-asset failures (Req 8.1, 9.2).
    regime_result: tuple[RegimeAssetResult, ...] = collect_regime(
        configured_assets,
        output_dir=Path(output_dir),
        lookback_days=lookback_days,
        generator_factory=generator_factory,
    )

    # --- All-shares individual outputs (Req 1.3) -------------------------
    # write_reports needs a real DailyReport, so only call it when the scan
    # produced one. A failure here is logged (Req 9.3) but MUST NOT fail the run:
    # the consolidated report is the deliverable, and it can still be produced
    # from a Missing scan input. SP-315 writes its own signals-log CSV in .run().
    if scan_result is not None:
        try:
            write_reports(scan_result, Path(output_dir))
        except Exception as exc:  # noqa: BLE001 - individual outputs are non-fatal to the deliverable.
            logger.error(
                "Failed to write all-shares individual outputs to %s: %s: %s",
                Path(output_dir),
                type(exc).__name__,
                exc,
            )

    # --- Build -> render -> write the consolidated report (the deliverable) ---
    # The builder is total/pure and should essentially never fail, but a genuine
    # failure to PRODUCE or WRITE the consolidated report means no report could be
    # produced at all: log the failed target (Req 9.3), emit the single failure
    # Report_Status to stderr, and return non-zero WITHOUT leaving a partial
    # report (Req 1.7, 10.4). The snapshot writer is atomic (temp + os.replace),
    # so a failed snapshot write leaves any pre-existing dated file intact.
    consolidated_text_path = Path(output_dir) / f"consolidated_report_{report_date:%Y%m%d}.txt"
    try:
        report = build_consolidated_report(report_date, scan_result, regime_result)
        rendered = render_consolidated_text(report)

        consolidated_text_path.parent.mkdir(parents=True, exist_ok=True)
        consolidated_text_path.write_text(rendered, encoding="utf-8", newline="")

        write_snapshot(report, archive_dir)
    except Exception as exc:  # noqa: BLE001 - any failure here means no report was produced (Req 1.7, 10.4).
        logger.error(
            "Failed to produce the Consolidated_Daily_Report (target=%s, snapshot_dir=%s): %s: %s",
            consolidated_text_path,
            archive_dir,
            type(exc).__name__,
            exc,
        )
        # Exactly one terminal Report_Status (Req 10.1): failure -> stderr.
        print(
            f"Report_Status: FAILURE - no Daily Market Report produced for {report_date.isoformat()}",
            file=sys.stderr,
        )
        return 1

    # Success, including graceful degradation from partial upstream failure
    # (Req 10.2, 10.3). Exactly one terminal Report_Status (Req 10.1): stdout.
    print(f"Report_Status: SUCCESS - Daily Market Report produced for {report_date.isoformat()}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI shim
    logging.basicConfig(level=logging.INFO)
    sys.exit(main(sys.argv[1:]))
