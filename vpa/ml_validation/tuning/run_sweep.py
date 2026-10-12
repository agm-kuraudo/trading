"""Threshold-sweep DRIVER CLI for the SP-313 tuning experiment (Task 15).

This is the runnable entry point an Analyst uses to perform Task 15 of the
``vpa-threshold-tuning-ml-revalidation`` spec: run the FOUR threshold sweeps
(shooting-star, acc/dist, period weighting, vol_backed reduction) on a single
PINNED :class:`DatasetSnapshot` and apply the Requirement 6 apply-gate
(``+>=3.09pp``) to decide, per dimension, which tuned value WOULD be written to
``config.json``.

Run it with::

    python -m vpa.ml_validation.tuning.run_sweep --ticker SPY

Design notes (see ``design.md`` *Sweep execution* and the gating sections):

- The window is pinned via ``--end-date`` so a re-run is reproducible (Req 1.4).
  With no ``--end-date`` the window ends today, which is fine for a one-off.
- Each sweep varies exactly ONE dimension off ``ScoringParams.default()``.
- Selection/gating is a pure function (:func:`decide_sweep_outcome`) so it is
  unit-testable without re-extracting features. For each sweep the "in-effect"
  accuracy is the sweep's baseline accuracy; the best candidate clearing the
  Req 6 gate is reported as the value that WOULD be applied.
- **This driver never edits ``config.json``.** It REPORTS the gated decision so
  the Analyst can apply any beneficial change deliberately (a human-confirmed
  step, per the design). The overall recommendation it feeds (Req 10) — which
  dimensions, if any, had a beneficial change — is printed at the end.

The heavy lifting is delegated to the existing tuning layer: ``SweepRunner``
re-extracts features per candidate over the pinned snapshot and measures
``Baseline_Accuracy``; ``gate.should_apply_to_config`` is the Req 6 gate.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from vpa.ml_validation.tuning.gate import SelectionOutcome, should_apply_to_config
from vpa.ml_validation.tuning.scoring_params import ScoringParams
from vpa.ml_validation.tuning.snapshot import DatasetSnapshot
from vpa.ml_validation.tuning.sweep import SweepResult, SweepRunner

logger = logging.getLogger(__name__)

# Default pinned window span (10 years of daily data), matching
# ``run_analysis.main`` / ``generate_dataset(days=3650)``.
DEFAULT_DAYS = 3650
DEFAULT_OUTPUT_DIR = "ml_validation_sweep_output"


def build_sweeps() -> list[tuple[str, ScoringParams, list[ScoringParams]]]:
    """Return the FOUR threshold sweeps as ``(dimension, baseline, candidates)``.

    Each candidate differs from ``ScoringParams.default()`` on exactly ONE
    dimension so the sweep attributes any accuracy movement to that dimension.
    Candidate counts are kept modest (2-3 per sweep) because every candidate
    re-extracts features over the pinned window.
    """
    default = ScoringParams.default()

    # Req 2 — shooting-star: vary shooting_star_spread_mult around the default
    # 2.0 with one tighter (looser detection) and one looser value, keeping >=1.
    shooting_star = [
        ScoringParams(shooting_star_spread_mult=1.5),
        ScoringParams(shooting_star_spread_mult=3.0),
    ]

    # Req 3 — acc/dist: vary the volume percentile (65 default) and the test
    # count (3 default), higher and lower on each, one dimension-move per
    # candidate.
    acc_dist = [
        ScoringParams(acc_dist_volume_percentile=55),
        ScoringParams(acc_dist_volume_percentile=75),
        ScoringParams(acc_dist_test_count=2),
        ScoringParams(acc_dist_test_count=4),
    ]

    # Req 4 — period weighting: increase the combined period-three contribution
    # above the combined p1+p2 contribution. Both candidates satisfy p3 > p1+p2:
    #   - p3=2.5 with p1=p2=1.0 (2.5 > 2.0): raise p3 above the default sum.
    #   - p3=1.5 with p1=p2=0.5 (1.5 > 1.0): a milder tilt that also damps p1/p2.
    period_weight = [
        ScoringParams(period_weight_p1=1.0, period_weight_p2=1.0, period_weight_p3=2.5),
        ScoringParams(period_weight_p1=0.5, period_weight_p2=0.5, period_weight_p3=1.5),
    ]

    # Req 5 — vol_backed: reduce/remove the p1/p2 doubling (default 2.0) while
    # leaving p3 at 2.0. 1.0 removes the extra bonus; 0.0 removes the term.
    vol_backed = [
        ScoringParams(vol_backed_mult_p1=1.0, vol_backed_mult_p2=1.0),
        ScoringParams(vol_backed_mult_p1=0.0, vol_backed_mult_p2=0.0),
    ]

    return [
        ("shooting_star", default, shooting_star),
        ("acc_dist", default, acc_dist),
        ("period_weight", default, period_weight),
        ("vol_backed", default, vol_backed),
    ]


def decide_sweep_outcome(sweep_result: SweepResult) -> SelectionOutcome:
    """Apply the Req 6 apply-gate to one sweep and return the gated decision.

    This is the pure, unit-testable core of the driver. The "in-effect" accuracy
    is the sweep's ``baseline_accuracy_pct``. Among evaluated candidates, keep
    those clearing the Req 6 gate (``+>=3.09pp`` over baseline via
    :func:`should_apply_to_config`). If any clear it, select the one with the
    highest accuracy as the value that WOULD be applied and record the
    prior/applied value, prior/new accuracy and the justifying delta (Req 6.3).
    If none clear it, record "no change beneficial" (Req 2.4/3.5/4.3/5.4).

    The ``prior_value``/``applied_value`` carried here are the baseline/candidate
    ``ScoringParams`` for the dimension; the driver reports them but never writes
    them to config.

    Args:
        sweep_result: The :class:`SweepResult` produced by ``SweepRunner.run``.

    Returns:
        A :class:`SelectionOutcome` describing the gated decision for the sweep's
        dimension. ``prior_value`` and ``applied_value`` are left as ``0.0``
        placeholders (the dimension's representative value is multi-field and is
        not a single scalar); the human-readable ``note`` names the applied
        ``ScoringParams`` when a change clears the gate.
    """
    dimension = sweep_result.dimension or "unknown"
    baseline_pct = sweep_result.baseline_accuracy_pct

    # Only genuinely evaluated candidates can clear the gate; rejected/errored
    # candidates have no accuracy and are excluded from selection.
    clearing = [
        candidate
        for candidate in sweep_result.candidates
        if candidate.status == "evaluated"
        and candidate.accuracy_pct is not None
        and should_apply_to_config(candidate.accuracy_pct, baseline_pct)
    ]

    if not clearing:
        return SelectionOutcome(
            dimension=dimension,
            changed=False,
            prior_value=0.0,
            applied_value=0.0,
            prior_accuracy_pct=baseline_pct,
            new_accuracy_pct=baseline_pct,
            justifying_delta_pp=None,
            note="no change beneficial (no candidate cleared the +>=3.09pp apply gate)",
        )

    # Among candidates clearing the gate, pick the highest accuracy.
    best = max(clearing, key=lambda candidate: candidate.accuracy_pct)
    delta_pp = best.accuracy_pct - baseline_pct

    return SelectionOutcome(
        dimension=dimension,
        changed=True,
        prior_value=0.0,
        applied_value=0.0,
        prior_accuracy_pct=baseline_pct,
        new_accuracy_pct=best.accuracy_pct,
        justifying_delta_pp=delta_pp,
        note=(f"WOULD apply {best.params.as_dict()} (+{delta_pp:.2f}pp over baseline; clears Req 6 apply gate)"),
    )


@dataclass
class SweepReport:
    """A sweep's result paired with its gated decision, for printing/serialising."""

    dimension: str
    result: SweepResult
    outcome: SelectionOutcome


def _sweep_to_dict(report: SweepReport) -> dict:
    """Serialise a :class:`SweepReport` to a JSON-ready dict (values to 2dp)."""
    result = report.result
    outcome = report.outcome
    ticker, data_start, data_end, seed = result.snapshot_id
    return {
        "dimension": report.dimension,
        "snapshot": {
            "ticker": ticker,
            "data_start": str(data_start),
            "data_end": str(data_end),
            "seed": seed,
        },
        "baseline_accuracy_pct": round(result.baseline_accuracy_pct, 2),
        "candidates": [
            {
                "params": candidate.params.as_dict(),
                "accuracy_pct": (None if candidate.accuracy_pct is None else round(candidate.accuracy_pct, 2)),
                "delta_pp": (None if candidate.delta_pp is None else round(candidate.delta_pp, 2)),
                "status": candidate.status,
            }
            for candidate in result.candidates
        ],
        "rejection_messages": list(result.rejection_messages),
        "eval_errors": list(result.eval_errors),
        "gate_decision": {
            "changed": outcome.changed,
            "prior_accuracy_pct": round(outcome.prior_accuracy_pct, 2),
            "new_accuracy_pct": round(outcome.new_accuracy_pct, 2),
            "justifying_delta_pp": (
                None if outcome.justifying_delta_pp is None else round(outcome.justifying_delta_pp, 2)
            ),
            "applied_params": (outcome.note),
            "note": outcome.note,
        },
    }


def _write_artefact(output_path: Path, report: SweepReport) -> None:
    """Write a per-sweep machine-readable JSON artefact (log-and-continue)."""
    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("Failed to create output directory %s: %s", output_path, e)
        return

    json_path = output_path / f"sweep_{report.dimension}.json"
    try:
        json_path.write_text(
            json.dumps(_sweep_to_dict(report), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  Artefact written: {json_path}")
    except OSError as e:
        logger.error("Failed to write sweep artefact %s: %s", json_path, e)


def _print_sweep_summary(report: SweepReport) -> None:
    """Print a human-readable per-sweep summary to stdout."""
    result = report.result
    outcome = report.outcome

    print(f"Sweep: {report.dimension}")
    print("-" * (7 + len(report.dimension)))
    print(f"  Baseline accuracy: {result.baseline_accuracy_pct:.2f}%")
    print("  Candidates:")
    for candidate in result.candidates:
        changed_fields = {
            name: value
            for name, value in candidate.params.as_dict().items()
            if value != getattr(ScoringParams.default(), name)
        }
        if candidate.status == "evaluated":
            print(
                f"    {changed_fields} -> {candidate.accuracy_pct:.2f}% "
                f"(delta {candidate.delta_pp:+.2f}pp) [{candidate.status}]"
            )
        else:
            print(f"    {changed_fields} -> N/A [{candidate.status}]")

    if result.rejection_messages:
        print("  Rejections:")
        for message in result.rejection_messages:
            print(f"    - {message}")
    if result.eval_errors:
        print("  Evaluation errors:")
        for message in result.eval_errors:
            print(f"    - {message}")

    print("  Gate decision (Req 6, +>=3.09pp):")
    if outcome.changed:
        print(
            f"    BENEFICIAL: {outcome.prior_accuracy_pct:.2f}% -> "
            f"{outcome.new_accuracy_pct:.2f}% (+{outcome.justifying_delta_pp:.2f}pp)"
        )
        print(f"    {outcome.note}")
        print("    NOTE: config.json is NOT edited by this driver; apply deliberately.")
    else:
        print(f"    {outcome.note}")
    print()


def main(
    ticker: str = "SPY",
    output_dir: str = DEFAULT_OUTPUT_DIR,
    config_path: str | None = None,
    end_date: str | None = None,
    days: int = DEFAULT_DAYS,
) -> list[SweepReport]:
    """Run the four threshold sweeps on a pinned snapshot and apply the Req 6 gate.

    Args:
        ticker: Ticker symbol to analyse (default ``"SPY"``).
        output_dir: Directory for per-sweep JSON artefacts.
        config_path: Path to the VPA ``config.json``; ``None`` resolves it the
            way ``run_analysis.main`` does (``vpa/config/config.json``).
        end_date: Optional ISO date (``YYYY-MM-DD``) pinning the window end for
            reproducibility (Req 1.4). ``None`` uses today (fine for a one-off).
        days: Window span in days (default 3650 — ten years).

    Returns:
        A list of :class:`SweepReport`, one per dimension, so a caller/test can
        inspect the gated decisions programmatically.
    """
    data_end = datetime.date.fromisoformat(end_date) if end_date else datetime.date.today()
    data_start = data_end - datetime.timedelta(days=days)

    snapshot = DatasetSnapshot(ticker=ticker, data_start=data_start, data_end=data_end, seed=42)
    output_path = Path(output_dir)

    print("VPA Threshold Sweep Driver (SP-313 Task 15)")
    print("===========================================")
    print(f"Ticker:      {ticker}")
    print(f"Window:      {data_start} -> {data_end} (pinned via {'--end-date' if end_date else 'today'})")
    print(f"Seed:        {snapshot.seed}")
    print(f"Output:      {output_path}")
    print()
    print("Running four threshold sweeps (each candidate re-extracts features)...")
    print()

    runner = SweepRunner()
    reports: list[SweepReport] = []

    # Note: SweepRunner always re-extracts via snapshot.extract, which resolves
    # the config path itself (DEFAULT_CONFIG_PATH). An explicit --config is
    # accepted for CLI parity with run_analysis but is not threaded further here
    # because the sweep path uses the default resolution; it is surfaced in the
    # printed summary below for transparency.
    if config_path is not None:
        print(f"Config:      {config_path} (note: sweeps use default config resolution)")

    for dimension, baseline, candidates in build_sweeps():
        result = runner.run(snapshot, baseline, candidates, dimension=dimension)
        outcome = decide_sweep_outcome(result)
        report = SweepReport(dimension=dimension, result=result, outcome=outcome)
        reports.append(report)
        _print_sweep_summary(report)
        _write_artefact(output_path, report)
        print()

    _print_overall_recommendation(reports)
    return reports


def _print_overall_recommendation(reports: list[SweepReport]) -> None:
    """Print the overall recommendation this feeds (Req 10)."""
    beneficial = [report for report in reports if report.outcome.changed]

    print("Overall recommendation (Req 10)")
    print("===============================")
    if not beneficial:
        print("  No dimension produced a change clearing the Req 6 apply gate (+>=3.09pp).")
        print("  Recommendation: retain all current thresholds (no change beneficial).")
        print("  This matches the SP-312 finding that the rule-based approach is near-optimal.")
    else:
        print("  Dimensions with a beneficial change clearing the Req 6 apply gate:")
        for report in beneficial:
            outcome = report.outcome
            print(
                f"    - {report.dimension}: +{outcome.justifying_delta_pp:.2f}pp "
                f"({outcome.prior_accuracy_pct:.2f}% -> {outcome.new_accuracy_pct:.2f}%)"
            )
        print("  Apply these to config.json deliberately (human-confirmed), then re-document.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VPA Threshold Sweep Driver (SP-313 Task 15)")
    parser.add_argument("--ticker", type=str, default="SPY", help="Ticker symbol (default: SPY)")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for sweep artefacts (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to VPA config.json (default: vpa/config/config.json)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Optional ISO date (YYYY-MM-DD) pinning the window end for a reproducible re-run (Req 1.4)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Window span in days (default: {DEFAULT_DAYS})",
    )

    args = parser.parse_args()
    main(
        ticker=args.ticker,
        output_dir=args.output_dir,
        config_path=args.config,
        end_date=args.end_date,
        days=args.days,
    )
