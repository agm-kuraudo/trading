"""FAST unit tests for the threshold-sweep DRIVER's pure decision logic (Task 15).

The driver's heavy path (``SweepRunner`` re-extracting features per candidate)
is the Analyst's manual step and is deliberately NOT exercised here — that would
re-extract many times. Instead these tests feed synthetic :class:`SweepResult`
data to :func:`decide_sweep_outcome` (the pure gate-application core) and assert
the right per-dimension decision:

- none of the candidates clears the Req 6 gate -> "no change beneficial";
- exactly one candidate clears ``+>=3.09pp`` -> that candidate is selected with
  the correct justifying delta;
- when several clear the gate, the highest-accuracy candidate is selected;
- rejected / errored candidates are never selectable.

All of this is pure (no model, no I/O), so none carry the ``slow`` marker.

Requirements: 2, 3, 4, 5, 6
"""

import datetime

from vpa.ml_validation.tuning.run_sweep import build_sweeps, decide_sweep_outcome
from vpa.ml_validation.tuning.scoring_params import ScoringParams
from vpa.ml_validation.tuning.sweep import CandidateResult, SweepResult

SNAPSHOT_ID = ("SPY", datetime.date(2010, 1, 4), datetime.date(2020, 1, 2), 42)


def _candidate(params: ScoringParams, accuracy_pct, baseline_pct, status="evaluated"):
    """Build a ``CandidateResult`` with ``delta_pp`` derived like the runner does."""
    delta_pp = None if accuracy_pct is None else accuracy_pct - baseline_pct
    return CandidateResult(
        params=params,
        accuracy_pct=accuracy_pct,
        status=status,
        delta_pp=delta_pp,
    )


def _sweep(dimension, baseline_pct, candidates):
    return SweepResult(
        dimension=dimension,
        snapshot_id=SNAPSHOT_ID,
        baseline_accuracy_pct=baseline_pct,
        candidates=candidates,
    )


class TestDecideSweepOutcomeNoneClears:
    """When no candidate clears +>=3.09pp the decision is 'no change beneficial'."""

    def test_flat_candidates_no_change(self):
        baseline = 52.34
        sweep = _sweep(
            "shooting_star",
            baseline,
            [
                _candidate(ScoringParams(shooting_star_spread_mult=1.5), 52.10, baseline),
                _candidate(ScoringParams(shooting_star_spread_mult=3.0), 53.00, baseline),
            ],
        )
        outcome = decide_sweep_outcome(sweep)
        assert outcome.changed is False
        assert outcome.dimension == "shooting_star"
        assert outcome.justifying_delta_pp is None
        assert outcome.prior_accuracy_pct == baseline
        assert outcome.new_accuracy_pct == baseline
        assert "no change beneficial" in outcome.note

    def test_just_below_gate_no_change(self):
        # 55.42 - 52.34 = 3.08pp, just below the 3.09 gate.
        baseline = 52.34
        sweep = _sweep(
            "acc_dist",
            baseline,
            [_candidate(ScoringParams(acc_dist_volume_percentile=55), 55.42, baseline)],
        )
        outcome = decide_sweep_outcome(sweep)
        assert outcome.changed is False


class TestDecideSweepOutcomeOneClears:
    """A single candidate clearing +>=3.09pp is selected with the right delta."""

    def test_exactly_at_gate_selected(self):
        baseline = 50.00
        candidate_params = ScoringParams(acc_dist_test_count=2)
        sweep = _sweep(
            "acc_dist",
            baseline,
            [
                _candidate(ScoringParams(acc_dist_test_count=4), 50.50, baseline),
                _candidate(candidate_params, baseline + 3.09, baseline),
            ],
        )
        outcome = decide_sweep_outcome(sweep)
        assert outcome.changed is True
        assert outcome.dimension == "acc_dist"
        assert round(outcome.justifying_delta_pp, 2) == 3.09
        assert round(outcome.new_accuracy_pct, 2) == 53.09
        assert outcome.prior_accuracy_pct == baseline
        assert "WOULD apply" in outcome.note

    def test_highest_accuracy_selected_among_clearing(self):
        baseline = 50.00
        best_params = ScoringParams(period_weight_p3=2.5)
        sweep = _sweep(
            "period_weight",
            baseline,
            [
                _candidate(ScoringParams(period_weight_p3=1.5), 53.50, baseline),  # +3.50 clears
                _candidate(best_params, 56.00, baseline),  # +6.00 clears, highest
            ],
        )
        outcome = decide_sweep_outcome(sweep)
        assert outcome.changed is True
        assert round(outcome.new_accuracy_pct, 2) == 56.00
        assert round(outcome.justifying_delta_pp, 2) == 6.00
        # The applied params note reflects the best (highest-accuracy) candidate.
        assert "period_weight_p3" in outcome.note


class TestDecideSweepOutcomeIgnoresNonEvaluated:
    """Rejected / errored candidates are never selectable even with high accuracy."""

    def test_rejected_candidate_not_selected(self):
        baseline = 50.00
        sweep = _sweep(
            "shooting_star",
            baseline,
            [
                # Would clear the gate on accuracy, but it was rejected out of range
                # (and so carries no real accuracy) -> excluded from selection.
                _candidate(
                    ScoringParams(shooting_star_spread_mult=0.5),
                    None,
                    baseline,
                    status="rejected_out_of_range",
                ),
            ],
        )
        outcome = decide_sweep_outcome(sweep)
        assert outcome.changed is False

    def test_eval_error_candidate_not_selected(self):
        baseline = 50.00
        sweep = _sweep(
            "vol_backed",
            baseline,
            [
                _candidate(
                    ScoringParams(vol_backed_mult_p1=0.0, vol_backed_mult_p2=0.0),
                    None,
                    baseline,
                    status="eval_error",
                ),
            ],
        )
        outcome = decide_sweep_outcome(sweep)
        assert outcome.changed is False


class TestBuildSweeps:
    """The four sweeps are well-formed and each candidate moves one dimension."""

    def test_four_dimensions_present(self):
        sweeps = build_sweeps()
        dimensions = [name for name, _, _ in sweeps]
        assert dimensions == ["shooting_star", "acc_dist", "period_weight", "vol_backed"]

    def test_all_candidates_valid_and_single_dimension(self):
        default = ScoringParams.default()
        for _name, baseline, candidates in build_sweeps():
            assert baseline == default
            for candidate in candidates:
                # Every candidate must pass validation (so the sweep actually
                # evaluates them rather than rejecting them out of range).
                assert candidate.validate() == []

    def test_period_weight_increases_p3_above_p1_plus_p2(self):
        sweeps = {name: candidates for name, _, candidates in build_sweeps()}
        for candidate in sweeps["period_weight"]:
            combined_p1_p2 = candidate.period_weight_p1 + candidate.period_weight_p2
            assert candidate.period_weight_p3 > combined_p1_p2
