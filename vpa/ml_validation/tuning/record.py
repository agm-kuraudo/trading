"""Experiment record and result writer for VPA threshold tuning (SP-313).

``ExperimentRecord`` is the single per-run artefact that satisfies Requirements
1.2 and 1.3: it captures the ticker, pinned data window, labelled row count,
seed, the exact ``ScoringParams`` in effect, the baseline/ML accuracies, skipped
folds, the top-five feature importances, realized volatility, and the run status
(``run_completed`` / ``error``). All numeric values are stored to at least two
decimal places.

``ResultWriter`` serialises each record to a machine-readable JSON artefact plus
a human-readable summary, mirroring ``AnalysisScript.save_outputs``:

- **Req 1.5 pre-write guard (refuse, do not write).** Before writing anything,
  the writer checks whether the record represents an incomplete run — a run that
  did not complete (``run_completed is False``) or that produced zero labelled
  rows (``labelled_row_count <= 0``). In that case it writes **no** partial
  artefact and raises :class:`InsufficientDataError` with a ticker-identifying
  message. This mirrors the design's "fail without a partial artefact" rule and
  runs *before* the write step.
- **Log-and-continue on write failure.** For a complete, recordable result, a
  genuine disk write failure (``OSError``) is logged and swallowed so one failed
  artefact never aborts the run — exactly as ``AnalysisScript.save_outputs``
  behaves. The two behaviours are distinct: the Req 1.5 guard refuses up front
  and raises; a disk failure for a complete record logs and continues.

``None`` numeric values are preserved through serialisation (they become JSON
``null``) so they can carry the Req 10.6 "unavailable" markers at documentation
time rather than being silently dropped.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.tuning.scoring_params import ScoringParams

logger = logging.getLogger(__name__)

# Numeric values are stored to at least this many decimal places (Req 1.2).
_DECIMAL_PLACES = 2


def _round2(value: float | None) -> float | None:
    """Round a numeric value to two decimal places, preserving ``None``.

    ``None`` is passed through unchanged so it can serialise to JSON ``null``
    and act as a Req 10.6 "unavailable" marker.
    """
    if value is None:
        return None
    return round(float(value), _DECIMAL_PLACES)


@dataclass
class ExperimentRecord:
    """A single per-run record (Requirements 1.2, 1.3).

    One record is written per harness run (baseline, each sweep candidate, SPY
    re-validation, each individual ticker). Numeric values are rounded to two
    decimal places on serialisation; ``None`` is preserved as a null/unavailable
    marker (Req 10.6).

    Attributes:
        ticker: Ticker symbol (e.g. ``"SPY"``).
        data_start: Snapshot first date, ISO ``YYYY-MM-DD`` string.
        data_end: Snapshot last (pinned) date, ISO ``YYYY-MM-DD`` string.
        labelled_row_count: Number of labelled rows in the dataset.
        seed: Integer random seed (42).
        scoring_params: The ``ScoringParams`` in effect for the run.
        baseline_accuracy_pct: Baseline VPA accuracy as a percentage.
        ml_mean_accuracy_pct: Mean walk-forward ML accuracy (percentage) or
            ``None`` when unavailable.
        ml_std_accuracy_pct: Walk-forward ML accuracy std-dev (percentage) or
            ``None`` when unavailable.
        skipped_folds: Indices of skipped walk-forward folds.
        top5_feature_importance: Top-five ranked features as ``{"name", "score"}``
            dicts.
        realized_volatility: Realized daily-return volatility over the window, or
            ``None`` when unavailable.
        run_completed: Whether the run produced a complete, recordable result.
        error: Ticker-identifying failure reason, or ``None`` on success.
    """

    ticker: str
    data_start: str
    data_end: str
    labelled_row_count: int
    seed: int
    scoring_params: ScoringParams
    baseline_accuracy_pct: float | None = None
    ml_mean_accuracy_pct: float | None = None
    ml_std_accuracy_pct: float | None = None
    skipped_folds: list[int] = field(default_factory=list)
    top5_feature_importance: list[dict[str, object]] = field(default_factory=list)
    realized_volatility: float | None = None
    run_completed: bool = True
    error: str | None = None

    def is_incomplete(self) -> bool:
        """Return True when the record represents an incomplete/zero-row run.

        This is the Req 1.5 condition the writer refuses on: a run that did not
        complete, or that produced zero (or fewer) labelled rows. Such a record
        must never be written as a partial artefact.
        """
        return (not self.run_completed) or self.labelled_row_count <= 0

    def to_dict(self) -> dict[str, object]:
        """Serialise to a plain JSON-ready dict.

        ``scoring_params`` is flattened to a dict via ``ScoringParams.as_dict``
        so the exact thresholds in effect are recoverable (Req 1.3, 10.5).
        Numeric accuracy/volatility values are rounded to two decimal places;
        ``None`` values are preserved as ``null`` (Req 10.6). Feature-importance
        scores are likewise rounded while names are left intact.
        """
        top5: list[dict[str, object]] = []
        for item in self.top5_feature_importance:
            name = item.get("name")
            score = item.get("score")
            top5.append(
                {
                    "name": name,
                    "score": _round2(score) if isinstance(score, int | float) else score,
                }
            )

        return {
            "ticker": self.ticker,
            "data_start": self.data_start,
            "data_end": self.data_end,
            "labelled_row_count": self.labelled_row_count,
            "seed": self.seed,
            "scoring_params": self.scoring_params.as_dict(),
            "baseline_accuracy_pct": _round2(self.baseline_accuracy_pct),
            "ml_mean_accuracy_pct": _round2(self.ml_mean_accuracy_pct),
            "ml_std_accuracy_pct": _round2(self.ml_std_accuracy_pct),
            "skipped_folds": list(self.skipped_folds),
            "top5_feature_importance": top5,
            "realized_volatility": _round2(self.realized_volatility),
            "run_completed": self.run_completed,
            "error": self.error,
        }

    def to_summary_text(self) -> str:
        """Render a human-readable summary of the record.

        Unavailable numeric values are rendered as ``N/A`` so a reader can see
        the gap explicitly (the JSON artefact keeps them as ``null`` for
        machine use). This mirrors the Req 10.6 "unavailable" intent.
        """

        def fmt(value: float | None) -> str:
            return "N/A" if value is None else f"{round(float(value), _DECIMAL_PLACES):.2f}"

        lines: list[str] = []
        lines.append(f"Experiment record for {self.ticker}")
        lines.append("=" * (len(self.ticker) + 22))
        lines.append(f"Data window:        {self.data_start} -> {self.data_end}")
        lines.append(f"Labelled rows:      {self.labelled_row_count}")
        lines.append(f"Random seed:        {self.seed}")
        lines.append(f"Run completed:      {self.run_completed}")
        if self.error is not None:
            lines.append(f"Error:              {self.error}")
        lines.append("")
        lines.append(f"Baseline accuracy:  {fmt(self.baseline_accuracy_pct)}%")
        lines.append(f"ML mean accuracy:   {fmt(self.ml_mean_accuracy_pct)}%")
        lines.append(f"ML std accuracy:    {fmt(self.ml_std_accuracy_pct)}%")
        lines.append(f"Realized vol:       {fmt(self.realized_volatility)}")
        lines.append(f"Skipped folds:      {self.skipped_folds if self.skipped_folds else 'none'}")
        lines.append("")
        lines.append("Scoring params (thresholds in effect):")
        for name, value in self.scoring_params.as_dict().items():
            lines.append(f"  {name}: {value}")
        lines.append("")
        lines.append("Top 5 feature importance:")
        if self.top5_feature_importance:
            for rank, item in enumerate(self.top5_feature_importance, start=1):
                name = item.get("name")
                score = item.get("score")
                score_str = fmt(score) if isinstance(score, int | float) else str(score)
                lines.append(f"  {rank}. {name}: {score_str}")
        else:
            lines.append("  N/A")
        lines.append("")
        return "\n".join(lines)


class ResultWriter:
    """Writes an :class:`ExperimentRecord` to a JSON artefact and a summary file.

    The writer enforces the Req 1.5 pre-write guard (refuse incomplete runs,
    raising :class:`InsufficientDataError`) and otherwise mirrors
    ``AnalysisScript.save_outputs`` resilience (log-and-continue on ``OSError``).
    """

    def __init__(self, output_dir: Path | str):
        """
        Args:
            output_dir: Directory for artefacts; created on write if missing.
        """
        self.output_dir = Path(output_dir)

    def write(self, record: ExperimentRecord) -> None:
        """Write the record's JSON artefact and human-readable summary.

        Req 1.5 guard: if the record represents an incomplete run (did not
        complete, or zero labelled rows), nothing is written and
        :class:`InsufficientDataError` is raised with a ticker-identifying
        message. For a complete record, write failures are logged and the writer
        continues (log-and-continue), matching ``AnalysisScript.save_outputs``.

        Args:
            record: The experiment record to persist.

        Raises:
            InsufficientDataError: When the record is an incomplete/zero-row run
                (the Req 1.5 pre-write guard), before any file is written.
        """
        # Req 1.5 pre-write guard: refuse to write a partial artefact.
        if record.is_incomplete():
            reason = record.error or (
                f"zero labelled rows (labelled_row_count={record.labelled_row_count})"
                if record.labelled_row_count <= 0
                else "run did not complete"
            )
            raise InsufficientDataError(
                f"Refusing to write experiment record for {record.ticker}: "
                f"run incomplete and no partial artefact will be written ({reason})."
            )

        # Create output directory if it doesn't exist (mirrors save_outputs).
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("Failed to create output directory %s: %s", self.output_dir, e)
            return

        # Write JSON artefact.
        json_path = self.output_dir / f"{record.ticker}_experiment_record.json"
        try:
            json_path.write_text(
                json.dumps(record.to_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("Failed to write experiment record JSON %s: %s", json_path, e)

        # Write human-readable summary.
        summary_path = self.output_dir / f"{record.ticker}_experiment_summary.txt"
        try:
            summary_path.write_text(record.to_summary_text(), encoding="utf-8")
        except OSError as e:
            logger.error("Failed to write experiment summary %s: %s", summary_path, e)
