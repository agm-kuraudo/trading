"""Property 2 (determinism / reproducibility) and Property 3 (baseline accuracy range).

SP-313 Task 6.2.

This module encodes two of the SP-313 correctness properties:

- **Property 2 — Determinism / reproducibility** (``slow``, Req 1.4). Two
  independent extraction-and-evaluation runs over the SAME pinned window with the
  SAME ``ScoringParams`` and the SAME seed (42, set before dataset generation AND
  before model training) yield ``Baseline_Accuracy`` values equal to two decimal
  places AND mean ``ML_Accuracy`` values equal to two decimal places. This trains
  real XGBoost models (two full pipelines), so it carries the ``slow`` marker and
  is deselected from the default ``pytest`` run.

- **Property 3 — Baseline accuracy range** (FAST, Req 1.2).
  ``AnalysisScript.compute_baseline_accuracy()`` returns a value in the closed
  interval ``[0, 1]`` and the recorded ``baseline_accuracy_pct`` (``* 100``) lies
  in ``[0, 100]``. No model training is needed — a small synthetic labelled
  DataFrame (composite_score + next_day_direction, other feature columns zeroed) is
  passed straight to ``AnalysisScript``, so this stays FAST and carries no marker.

Apples-to-apples with task 1 / task 5.2: Property 2 reuses the task-1 oracle
helpers (``_FakeRepo`` + ``_make_pinned_ohlcv_dataframe``) to pin a FIXED, seeded
synthetic OHLCV window, injected through the ``repo`` dependency-injection seam, so
the determinism check neither hits the network nor depends on today's date.

Requirements: 1.4, 1.2
Property 2: Determinism / reproducibility
Property 3: Baseline accuracy range
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.ml_validation.analysis import AnalysisScript
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor

# Reuse the task-1 oracle verbatim so Property 2's pinned window is apples-to-apples
# with the committed regression fixture. See test_feature_extraction_characterisation.py
# (SP-313 Task 1) for the pinned-window mechanism these helpers implement.
from .test_feature_extraction_characterisation import (
    CONFIG_PATH,
    TICKER,
    _FakeRepo,
    _make_pinned_ohlcv_dataframe,
)

# Seed matches run_analysis.main's np.random.seed(42) and WalkForwardValidator's
# random_state=42 (Req 1.1). It is set before BOTH dataset generation and model
# training in each determinism run below.
RANDOM_SEED = 42

# Property 2 uses the design's n_splits=5 (one pair of runs is enough to encode the
# property deterministically — no Hypothesis sweep needed, keeping the slow cost to
# exactly two full pipelines).
N_SPLITS = 5


# =============================================================================
# Property 3 — Baseline accuracy range (FAST)
# =============================================================================


def _make_baseline_dataset(
    composite_scores: list[float],
    next_day_directions: list[int],
) -> pd.DataFrame:
    """Build a minimal labelled dataset for ``AnalysisScript.compute_baseline_accuracy``.

    Includes every feature column (zeroed except ``composite_score``) plus the
    metadata and label columns ``compute_baseline_accuracy`` reads, bypassing
    feature extraction entirely so the test stays FAST.
    """
    n = len(composite_scores)
    data: dict[str, list] = {col: [0.0] * n for col in VPAFeatureExtractor.FEATURE_COLUMNS}
    data["composite_score"] = list(composite_scores)
    data["date"] = [f"2020-01-{(i % 28) + 1:02d}" for i in range(n)]
    data["close"] = [100.0 + i for i in range(n)]
    data["next_day_direction"] = list(next_day_directions)
    return pd.DataFrame(data)


@settings(max_examples=100)
@given(
    rows=st.lists(
        st.tuples(
            st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
            st.integers(min_value=0, max_value=1),
        ),
        min_size=1,
        max_size=60,
    ),
)
def test_property_baseline_accuracy_in_unit_interval(rows: list[tuple[float, int]]) -> None:
    """Property 3: baseline accuracy ∈ [0, 1] and recorded pct ∈ [0, 100].

    For any valid labelled dataset (arbitrary composite scores and 0/1 labels),
    ``compute_baseline_accuracy()`` returns a fraction in the closed interval
    ``[0, 1]``, and multiplying by 100 to record ``baseline_accuracy_pct`` keeps it
    in ``[0, 100]``.

    **Validates: Requirements 1.2**
    """
    composite_scores = [score for score, _ in rows]
    labels = [label for _, label in rows]

    dataset = _make_baseline_dataset(composite_scores, labels)
    script = AnalysisScript(dataset=dataset, ticker="TEST", output_dir=Path("/tmp"))

    accuracy = script.compute_baseline_accuracy()

    assert 0.0 <= accuracy <= 1.0, f"baseline accuracy out of [0, 1]: {accuracy}"

    accuracy_pct = accuracy * 100.0
    assert 0.0 <= accuracy_pct <= 100.0, f"recorded baseline_accuracy_pct out of [0, 100]: {accuracy_pct}"


def test_baseline_accuracy_range_boundary_examples() -> None:
    """Property 3 (examples): all-correct → 1.0 (100%), all-wrong → 0.0 (0%).

    Pins the endpoints of the [0, 1] / [0, 100] intervals with concrete datasets so
    the range property is anchored by exact boundary cases, not only the Hypothesis
    sweep.
    """
    # Composite > 0 predicts UP (1). All labels 1 → every prediction correct → 1.0.
    all_correct = _make_baseline_dataset([5.0, 5.0, 5.0], [1, 1, 1])
    acc = AnalysisScript(dataset=all_correct, ticker="TEST", output_dir=Path("/tmp")).compute_baseline_accuracy()
    assert acc == 1.0
    assert acc * 100.0 == 100.0

    # Composite > 0 predicts UP (1). All labels 0 → every prediction wrong → 0.0.
    all_wrong = _make_baseline_dataset([5.0, 5.0, 5.0], [0, 0, 0])
    acc = AnalysisScript(dataset=all_wrong, ticker="TEST", output_dir=Path("/tmp")).compute_baseline_accuracy()
    assert acc == 0.0
    assert acc * 100.0 == 0.0


# =============================================================================
# Property 2 — Determinism / reproducibility (SLOW: trains real XGBoost models)
# =============================================================================


def _run_pipeline_once() -> tuple[float, float]:
    """Extract + evaluate once over the pinned window at seed 42.

    Mirrors ``run_analysis.main``'s seeding discipline (Req 1.1): set
    ``np.random.seed(42)`` before dataset generation, and ``WalkForwardValidator``
    uses ``random_state=42`` before model training. Returns a ``(baseline_accuracy,
    mean_ml_accuracy)`` pair as fractions in ``[0, 1]``.
    """
    # Seed BEFORE dataset generation (Req 1.1 — matches run_analysis.main).
    np.random.seed(RANDOM_SEED)

    pinned_df = _make_pinned_ohlcv_dataframe()
    extractor = VPAFeatureExtractor(
        config_path=CONFIG_PATH,
        ticker_symbol=TICKER,
        enable_extraction=True,
    )
    dataset = extractor.generate_dataset(days=3650, repo=_FakeRepo(pinned_df))

    script = AnalysisScript(dataset=dataset, ticker=TICKER, output_dir=Path("/tmp"))
    baseline_acc = script.compute_baseline_accuracy()

    # WalkForwardValidator seeds XGBClassifier with random_state=42 before training.
    ml_result = script.run_walk_forward_validation(n_splits=N_SPLITS)
    return baseline_acc, ml_result.mean_accuracy


@pytest.mark.slow
class TestDeterminismReproducibility:
    """Property 2: two seeded runs agree to two decimal places (Req 1.4)."""

    def test_two_runs_agree_to_two_decimal_places(self):
        """Property 2: identical window + params + seed → identical results (2dp).

        Two independent extraction-and-evaluation runs over the SAME pinned window
        with default ``ScoringParams`` and seed 42 must yield ``Baseline_Accuracy``
        equal to two decimal places AND mean ``ML_Accuracy`` equal to two decimal
        places. A single deterministic pair is sufficient to encode the property, so
        this is a plain slow test (not a Hypothesis sweep) — exactly two full
        pipelines.

        **Validates: Requirements 1.4**
        """
        baseline_acc1, ml_mean1 = _run_pipeline_once()
        baseline_acc2, ml_mean2 = _run_pipeline_once()

        # Compare as percentages rounded to 2 decimal places, matching how the
        # harness records Baseline_Accuracy and mean ML_Accuracy (Req 1.2/1.4).
        assert round(baseline_acc1 * 100, 2) == round(baseline_acc2 * 100, 2), (
            f"Baseline_Accuracy not reproducible to 2dp: "
            f"{round(baseline_acc1 * 100, 2)} != {round(baseline_acc2 * 100, 2)}"
        )
        assert round(ml_mean1 * 100, 2) == round(ml_mean2 * 100, 2), (
            f"mean ML_Accuracy not reproducible to 2dp: " f"{round(ml_mean1 * 100, 2)} != {round(ml_mean2 * 100, 2)}"
        )
