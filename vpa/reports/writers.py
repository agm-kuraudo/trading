from __future__ import annotations

from datetime import date
from pathlib import Path

from vpa.reports.models import DailyReport
from vpa.reports.renderers import render_csv, render_html, render_plain_text


def report_paths(output_dir: str | Path, report_date: date) -> dict[str, Path]:
    directory = Path(output_dir)
    stem = f"share_output_{report_date:%Y%m%d}"
    return {extension: directory / f"{stem}.{extension}" for extension in ("csv", "html", "txt")}


def write_reports(report: DailyReport, output_dir: str | Path) -> dict[str, Path]:
    paths = report_paths(output_dir, report.report_date)
    paths["csv"].parent.mkdir(parents=True, exist_ok=True)
    contents = {
        "csv": render_csv(report),
        "html": render_html(report),
        "txt": render_plain_text(report),
    }
    for extension, path in paths.items():
        path.write_text(contents[extension], encoding="utf-8", newline="")
    return paths
