from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from vpa.reports.consolidated_models import ConsolidatedReport, from_dict, to_dict


def snapshot_path(archive_dir: str | Path, report_date: date) -> Path:
    """Return the dated snapshot path ``<archive_dir>/<YYYY-MM-DD>.json`` (Req 7.2)."""
    return Path(archive_dir) / f"{report_date.isoformat()}.json"


def write_snapshot(report: ConsolidatedReport, archive_dir: str | Path) -> Path:
    """Serialise ``report`` to JSON and atomically replace the dated file.

    Writes exactly one file named ``<YYYY-MM-DD>.json`` under ``archive_dir``
    (Req 7.1, 7.2), creating parent directories as needed (Req 7.4). The write is
    atomic and overwrite-safe (Req 7.5, 7.7): the serialised JSON is written to a
    temp file in the same directory and then moved into place with ``os.replace``,
    which is atomic on the same filesystem. If serialisation or the write fails,
    the temp file is cleaned up and the error is surfaced, leaving any pre-existing
    dated snapshot unchanged (Req 7.7). Reuses ``to_dict`` for serialisation and
    mirrors ``write_reports`` by using ``encoding="utf-8"``.
    """
    final_path = snapshot_path(archive_dir, report.report_date)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    # Temp file in the SAME directory so os.replace is an atomic rename.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{report.report_date.isoformat()}.", suffix=".json.tmp", dir=final_path.parent
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(to_dict(report), indent=2))
        os.replace(tmp_path, final_path)
    except BaseException:
        # Serialise/write failed: remove the temp file and surface the error so a
        # pre-existing dated snapshot for this date is left intact (Req 7.7).
        tmp_path.unlink(missing_ok=True)
        raise
    return final_path


def read_snapshot(path: str | Path) -> ConsolidatedReport:
    """Parse a snapshot file back into a ConsolidatedReport (Req 7.6 round-trip)."""
    with open(path, encoding="utf-8") as handle:
        return from_dict(json.load(handle))
