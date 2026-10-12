"""SLOW end-to-end integration test for ``SweepRunner`` (SP-313 Task 12.2).

Unlike the FAST unit tests in ``test_sweep.py`` (which stub ``DatasetSnapshot``
with an in-memory frame and never extract features), this module exercises the
**real** extraction + ``compute_baseline_accuracy`` path end-to-end:

- a real :class:`DatasetSnapshot` is built over a FIXED pinned raw-OHLCV window;
- the window is pinned by injecting the task-1 fake repo
  (``_FakeRepo`` wrapping ``_make_pinned_ohlcv_dataframe``) through ``run()``'s
  ``repo=`` keyword, which ``SweepRunner`` forwards to ``snapshot.extract`` and
  thence to ``VPAFeatureExtractor.generate_dataset`` — so there is no network or
  date dependency and the >= 2100-row frame yields >= 2000 labelled rows;
- ``SweepRunner.run`` evaluates a real baseline (``ScoringParams.default()``) and
  a small set of candidates, re-extracting features per candidate.

What it asserts, through the REAL path:

1. A valid baseline and at least one valid candidate are both evaluated:
   ``baseline_accuracy_pct`` is a float in [0, 100]; the evaluated candidate has
   status ``"evaluated"`` with ``accuracy_pct`` in [0, 100] and
   ``delta_pp == accuracy_pct - baseline`` (Req 3.4).
2. An out-of-range candidate is excluded WITHOUT extraction, recorded as
   ``"rejected_out_of_range"`` with a rejection message, and the sweep still
   completes (Req 2.5 / 5.1 / 3.4).
3. Every evaluated candidate is recorded whether beneficial or not (Req 3.4):
   a candidate chosen to differ from the baseline appears in ``result.candidates``
   regardless of the sign of its delta.

Req 3.6 (per-candidate error isolation) is hard to trigger deterministically
through the real extraction path and is already covered by the FAST unit test in
Task 12.1, so it is not force-triggered here. Property 1 (default params →
consistent extraction) and Property 4 (``composite_score`` always present, so
baseline accuracy is computable) are exercised implicitly by the baseline and
candidate evaluations completing successfully over the real path.

Marked ``slow``: it re-extracts features over a >= 2100-row window once per
evaluated params set (baseline + candidates), so the default ``pytest`` run
deselects it via ``-m 'not slow'``.

Requirements: 2.1, 3.4, 3.6, 4.1, 5.1
Property 1: Default-params behaviour preservation
Property 4: Composite score totality
"""

import datetime

import pytest

from vpa.ml_validation.tuning.scoring_params import ScoringParams
from vpa.ml_validation.tuning.snapshot import DatasetSnapshot
from vpa.ml_validation.tuning.sweep import SweepRunner
from vpa.tests.ml_validation.test_feature_extraction_characterisation import (
    _FakeRepo,
    _make_pinned_ohlcv_dataframe,
)

TICKER = "SPY"

# A pinned window spanning ~9 years so (data_end - data_start).days >= 2100; the
# fake repo ignores these dates and returns the fixed frame, but they are set
# sensibly so DatasetSnapshot.extract passes a large-enough `days` span to
# generate_dataset (days == (data_end - data_start).days).
DATA_START = datetime.date(2010, 1, 4)
DATA_END = datetime.date(2019, 1, 4)


def _build_snapshot() -> DatasetSnapshot:
    """A real snapshot over the pinned window; its `days` span clears 2100."""
    assert (DATA_END - DATA_START).days >= 2100
    return DatasetSnapshot(
        ticker=TICKER,
        data_start=DATA_START,
        data_end=DATA_END,
        seed=42,
    )


@pytest.mark.slow
class TestSweepEndToEndIntegration:
    """End-to-end sweep over the real extraction path (SP-313 Task 12.2)."""

    def test_sweep_evaluates_real_baseline_and_candidates_and_isolates_out_of_range(self):
        """Baseline + valid candidates evaluate; out-of-range is rejected pre-extraction.

        Exercises the REAL extraction + compute_baseline_accuracy path for a
        baseline and valid candidates, and the pre-extraction rejection path for
        an out-of-range candidate, all in a single sweep so the completion of the
        sweep (Req 3.4) is demonstrated alongside the rejection (Req 2.5/5.1).
        """
        frame = _make_pinned_ohlcv_dataframe()
        assert len(frame) >= 2100, "pinned frame must span >= 2100 raw rows"
        repo = _FakeRepo(frame)

        snapshot = _build_snapshot()
        baseline = ScoringParams.default()

        # A valid candidate expected to DIFFER from baseline: a different acc/dist
        # volume percentile changes identify_acc_or_dist and therefore the
        # composite score (and so the baseline accuracy) through the real path.
        differing_candidate = ScoringParams(acc_dist_volume_percentile=80)
        # A second valid candidate on another dimension (shooting-star spread
        # multiplier) — recorded whether or not it is beneficial.
        shooting_star_candidate = ScoringParams(shooting_star_spread_mult=3.0)
        # An out-of-range candidate: a shooting-star multiplier < 1 is rejected by
        # ScoringParams.validate() BEFORE any extraction (Req 2.5 / 5.1).
        out_of_range_candidate = ScoringParams(shooting_star_spread_mult=0.5)

        candidates = [differing_candidate, shooting_star_candidate, out_of_range_candidate]

        result = SweepRunner().run(
            snapshot,
            baseline,
            candidates,
            dimension="integration",
            repo=repo,
        )

        # --- Snapshot identity and baseline (Property 3 range; Property 1/4 implicit) ---
        assert result.snapshot_id == (TICKER, DATA_START, DATA_END, 42)
        assert isinstance(result.baseline_accuracy_pct, float)
        assert 0.0 <= result.baseline_accuracy_pct <= 100.0

        # Every candidate (valid, differing, and rejected) is recorded, in order,
        # and the sweep completed despite the out-of-range candidate (Req 3.4).
        assert len(result.candidates) == 3
        differing_result, shooting_star_result, rejected_result = result.candidates

        # --- 1 & 3: evaluated candidates recorded with accuracy + signed delta (Req 3.4) ---
        for evaluated in (differing_result, shooting_star_result):
            assert evaluated.status == "evaluated"
            assert isinstance(evaluated.accuracy_pct, float)
            assert 0.0 <= evaluated.accuracy_pct <= 100.0
            assert evaluated.delta_pp == pytest.approx(evaluated.accuracy_pct - result.baseline_accuracy_pct)

        # The differing candidate exercised a real alternate scoring configuration;
        # whatever the sign of its delta, it is recorded (Req 3.4). We assert it was
        # actually evaluated via the real path (accuracy present), not dropped.
        assert differing_result.params == differing_candidate
        assert shooting_star_result.params == shooting_star_candidate

        # --- 2: out-of-range candidate rejected WITHOUT extraction (Req 2.5 / 5.1) ---
        assert rejected_result.params == out_of_range_candidate
        assert rejected_result.status == "rejected_out_of_range"
        assert rejected_result.accuracy_pct is None
        assert rejected_result.delta_pp is None
        assert result.rejection_messages, "an out-of-range rejection message must be recorded"

        # No per-candidate evaluation errors were triggered on this real-path run.
        assert result.eval_errors == []
