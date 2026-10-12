"""FAST unit tests for ``SweepRunner`` (SP-313 Task 12.1).

These tests avoid real feature extraction entirely: a tiny fake snapshot stands
in for :class:`DatasetSnapshot`, returning a small in-memory labelled frame (or
raising) from ``extract``. That is enough to exercise the runner's control flow —
baseline anchoring, out-of-range rejection *without* extraction, accuracy/delta
recording for evaluated candidates, and per-candidate error isolation — without
training a model or touching the market-data repository, so none of these carry
the ``slow`` marker. The end-to-end extraction path is covered by the ``slow``
integration test in Task 12.2.

Requirements: 2.1, 2.5, 3.4, 3.6, 5.1
"""

import datetime

import pandas as pd
import pytest

from vpa.ml_validation.exceptions import InsufficientDataError
from vpa.ml_validation.tuning.scoring_params import ScoringParams
from vpa.ml_validation.tuning.sweep import SweepRunner

TICKER = "SPY"
DATA_START = datetime.date(2010, 1, 4)
DATA_END = datetime.date(2018, 2, 1)
SEED = 42


class _FakeSnapshot:
    """Stand-in for ``DatasetSnapshot`` whose ``extract`` returns a fixed frame.

    Carries the same identifying attributes the runner reads for
    ``snapshot_id``. ``extract`` returns a labelled frame built from a per-params
    accuracy map; a params value mapped to an exception is raised instead, to
    simulate a per-candidate evaluation failure.
    """

    def __init__(self, accuracy_by_params: dict[ScoringParams, object]):
        self.ticker = TICKER
        self.data_start = DATA_START
        self.data_end = DATA_END
        self.seed = SEED
        self._accuracy_by_params = accuracy_by_params

    def extract(self, params: ScoringParams, repo=None) -> pd.DataFrame:  # noqa: ARG002
        outcome = self._accuracy_by_params[params]
        if isinstance(outcome, Exception):
            raise outcome
        # Build a labelled frame whose composite-score-sign accuracy equals the
        # requested fraction: `outcome` correct rows out of 100.
        correct = int(round(outcome * 100))
        composite = [1.0] * 100  # predicts UP for every row
        actual = [1] * correct + [0] * (100 - correct)
        return pd.DataFrame({"composite_score": composite, "next_day_direction": actual})


def test_baseline_anchors_delta_and_evaluated_candidate_recorded():
    """An evaluated candidate records its accuracy and signed delta vs baseline (Req 3.4)."""
    baseline = ScoringParams.default()
    candidate = ScoringParams(shooting_star_spread_mult=3.0)
    snapshot = _FakeSnapshot({baseline: 0.50, candidate: 0.55})

    result = SweepRunner().run(snapshot, baseline, [candidate], dimension="shooting_star")

    assert result.snapshot_id == (TICKER, DATA_START, DATA_END, SEED)
    assert result.baseline_accuracy_pct == 50.0
    assert len(result.candidates) == 1
    only = result.candidates[0]
    assert only.status == "evaluated"
    assert only.accuracy_pct == pytest.approx(55.0)
    assert only.delta_pp == pytest.approx(5.0)
    assert result.rejection_messages == []
    assert result.eval_errors == []


def test_non_beneficial_candidate_is_still_recorded():
    """A worse candidate is recorded with a negative delta, not dropped (Req 3.4)."""
    baseline = ScoringParams.default()
    worse = ScoringParams(shooting_star_spread_mult=5.0)
    snapshot = _FakeSnapshot({baseline: 0.52, worse: 0.48})

    result = SweepRunner().run(snapshot, baseline, [worse])

    assert result.candidates[0].status == "evaluated"
    assert result.candidates[0].accuracy_pct == pytest.approx(48.0)
    assert result.candidates[0].delta_pp == pytest.approx(-4.0)


def test_out_of_range_candidate_rejected_without_extraction():
    """An invalid candidate is rejected before extraction (Req 2.5/5.1).

    The fake snapshot deliberately has no entry for the invalid candidate, so if
    the runner tried to extract it the test would raise ``KeyError``.
    """
    baseline = ScoringParams.default()
    invalid = ScoringParams(shooting_star_spread_mult=0.5)  # < 1 -> rejected
    snapshot = _FakeSnapshot({baseline: 0.50})

    result = SweepRunner().run(snapshot, baseline, [invalid])

    assert len(result.candidates) == 1
    assert result.candidates[0].status == "rejected_out_of_range"
    assert result.candidates[0].accuracy_pct is None
    assert result.candidates[0].delta_pp is None
    assert result.rejection_messages, "a rejection message must be recorded"
    assert result.eval_errors == []


def test_per_candidate_error_is_isolated_and_prior_results_retained():
    """One failing candidate records an eval_error but prior results survive (Req 3.6)."""
    baseline = ScoringParams.default()
    good = ScoringParams(shooting_star_spread_mult=3.0)
    bad = ScoringParams(shooting_star_spread_mult=4.0)
    snapshot = _FakeSnapshot(
        {
            baseline: 0.50,
            good: 0.53,
            bad: InsufficientDataError("zero labelled rows for candidate"),
        }
    )

    result = SweepRunner().run(snapshot, baseline, [good, bad])

    assert len(result.candidates) == 2
    assert result.candidates[0].status == "evaluated"
    assert result.candidates[0].accuracy_pct == pytest.approx(53.0)
    assert result.candidates[1].status == "eval_error"
    assert result.candidates[1].accuracy_pct is None
    assert result.candidates[1].delta_pp is None
    assert len(result.eval_errors) == 1
