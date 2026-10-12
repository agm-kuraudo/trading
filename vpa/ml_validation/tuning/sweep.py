"""Threshold sweep runner for the SP-313 tuning experiment.

A :class:`SweepRunner` evaluates a baseline ``ScoringParams`` and a list of
candidate ``ScoringParams`` against a single pinned :class:`DatasetSnapshot`,
measuring each one's ``Baseline_Accuracy`` via the cheap
``AnalysisScript.compute_baseline_accuracy`` path. It never trains the ML model
(that is the full walk-forward path, used only by the SPY/multi-ticker runs);
sweeps are intentionally the lightweight baseline-accuracy comparison described
in the design's *Sweep execution* section.

The runner enforces the design's two guarding rules:

- **Out-of-range candidates** (Req 2.5, 3.1, 3.2, 5.1) are rejected *before* any
  feature extraction. ``ScoringParams.validate()`` returns rejection messages;
  a non-empty list excludes the candidate, appends its messages to
  :attr:`SweepResult.rejection_messages`, and records a ``CandidateResult`` with
  ``status="rejected_out_of_range"``.
- **Per-candidate evaluation failures** (Req 3.6) never abort the sweep. If a
  validated candidate raises during extraction or baseline computation (e.g.
  :class:`InsufficientDataError` or an empty-dataset error), the candidate is
  excluded from selection, a descriptive message is appended to
  :attr:`SweepResult.eval_errors`, a ``CandidateResult`` with
  ``status="eval_error"`` is recorded, and the sweep continues — all previously
  recorded results are retained.

Every evaluated candidate's accuracy is recorded whether or not it beats the
baseline (Req 3.4). Selection and gating (the per-dimension recording margins
and the Req 6 apply gate) live in ``tuning/gate.py``; this runner only measures
and records.

See the design document's ``SweepRunner`` / ``SweepResult`` / ``CandidateResult``
sections and the *Sweep execution* and *Error Handling* sections.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from vpa.ml_validation.analysis import AnalysisScript
from vpa.ml_validation.tuning.scoring_params import ScoringParams
from vpa.ml_validation.tuning.snapshot import DatasetSnapshot

logger = logging.getLogger(__name__)

CandidateStatus = Literal["evaluated", "rejected_out_of_range", "eval_error"]

# Sweeps compute baseline accuracy only; they never persist artefacts, so the
# AnalysisScript output directory is a throwaway. compute_baseline_accuracy does
# not write anything (only save_outputs does), so this path is never created.
_SWEEP_OUTPUT_DIR = Path(".sweep-no-write")


@dataclass(frozen=True)
class CandidateResult:
    """Outcome of evaluating a single candidate ``ScoringParams`` in a sweep.

    Attributes:
        params: The candidate parameters that were evaluated or rejected.
        accuracy_pct: Measured ``Baseline_Accuracy`` as a percentage (0..100),
            or ``None`` when ``status`` is not ``"evaluated"``.
        status: One of ``"evaluated"`` (accuracy measured),
            ``"rejected_out_of_range"`` (failed ``validate()``, never extracted),
            or ``"eval_error"`` (raised during extraction/accuracy computation).
        delta_pp: Signed difference ``accuracy_pct - baseline_accuracy_pct`` in
            percentage points when evaluated; ``None`` otherwise.
    """

    params: ScoringParams
    accuracy_pct: float | None
    status: CandidateStatus
    delta_pp: float | None


@dataclass
class SweepResult:
    """Aggregate result of one sweep over a pinned snapshot.

    Attributes:
        dimension: The tuning dimension this sweep targets, e.g.
            ``"shooting_star" | "acc_dist" | "period_weight" | "vol_backed"``.
            May be empty when the caller does not label the sweep.
        snapshot_id: The identity of the pinned snapshot used for every
            evaluation, ``(ticker, data_start, data_end, seed)``. Recorded so a
            downstream reader can confirm all candidates were apples-to-apples
            (the design refuses mixing snapshots).
        baseline_accuracy_pct: ``Baseline_Accuracy`` of ``baseline`` as a
            percentage (0..100); the reference every ``delta_pp`` is measured
            against.
        candidates: One :class:`CandidateResult` per candidate, in input order,
            including rejected and errored candidates.
        rejection_messages: Validation messages for out-of-range candidates
            (Req 2.5/3.1/3.2/5.1).
        eval_errors: Descriptive messages for per-candidate evaluation failures
            (Req 3.6).
    """

    dimension: str
    snapshot_id: tuple
    baseline_accuracy_pct: float
    candidates: list[CandidateResult] = field(default_factory=list)
    rejection_messages: list[str] = field(default_factory=list)
    eval_errors: list[str] = field(default_factory=list)


class SweepRunner:
    """Evaluates baseline + candidate ``ScoringParams`` over a pinned snapshot."""

    def run(
        self,
        snapshot: DatasetSnapshot,
        baseline: ScoringParams,
        candidates: list[ScoringParams],
        dimension: str = "",
        *,
        repo=None,
    ) -> SweepResult:
        """Measure ``Baseline_Accuracy`` for the baseline and each candidate.

        The baseline is evaluated first to establish the reference accuracy. Each
        candidate is then validated and, if valid, re-extracted over the *same*
        pinned snapshot and scored. The accuracy of every evaluated candidate is
        recorded regardless of whether it beats the baseline (Req 3.4).

        Args:
            snapshot: The pinned :class:`DatasetSnapshot`. Every evaluation
                re-extracts features from this same window/seed so results are
                comparable.
            baseline: The reference parameters (typically
                ``ScoringParams.default()``). Its accuracy anchors every
                ``delta_pp``.
            candidates: Candidate parameter sets to evaluate.
            dimension: Optional label for the tuning dimension, stored on the
                result for traceability.
            repo: Optional ``MarketDataRepository`` forwarded to
                ``snapshot.extract`` for dependency injection in tests. ``None``
                lets the extractor construct its own repository.

        Returns:
            A :class:`SweepResult` with the baseline accuracy, one
            :class:`CandidateResult` per candidate (in input order), and the
            accumulated rejection and evaluation-error messages.
        """
        snapshot_id = (
            snapshot.ticker,
            snapshot.data_start,
            snapshot.data_end,
            snapshot.seed,
        )

        # 1. Evaluate the baseline first to anchor every delta. A baseline that
        #    cannot be evaluated means the whole sweep has no reference, so this
        #    is allowed to propagate rather than being swallowed per-candidate.
        baseline_pct = self._evaluate(snapshot, baseline, repo=repo)

        result = SweepResult(
            dimension=dimension,
            snapshot_id=snapshot_id,
            baseline_accuracy_pct=baseline_pct,
        )

        for candidate in candidates:
            # 2. Validate before any extraction (Req 2.5/3.1/3.2/5.1). Rejected
            #    candidates never reach feature extraction.
            messages = candidate.validate()
            if messages:
                result.rejection_messages.extend(messages)
                result.candidates.append(
                    CandidateResult(
                        params=candidate,
                        accuracy_pct=None,
                        status="rejected_out_of_range",
                        delta_pp=None,
                    )
                )
                continue

            # 3./4. Evaluate the valid candidate over the SAME pinned snapshot.
            #    A per-candidate failure is isolated (Req 3.6): record the error,
            #    retain prior results, and continue.
            try:
                accuracy_pct = self._evaluate(snapshot, candidate, repo=repo)
            except Exception as exc:  # noqa: BLE001 — isolate one bad candidate
                message = f"candidate could not be evaluated and was excluded: {exc!r}"
                logger.warning("Sweep candidate evaluation failed: %s", exc)
                result.eval_errors.append(message)
                result.candidates.append(
                    CandidateResult(
                        params=candidate,
                        accuracy_pct=None,
                        status="eval_error",
                        delta_pp=None,
                    )
                )
                continue

            result.candidates.append(
                CandidateResult(
                    params=candidate,
                    accuracy_pct=accuracy_pct,
                    status="evaluated",
                    delta_pp=accuracy_pct - baseline_pct,
                )
            )

        return result

    def _evaluate(self, snapshot: DatasetSnapshot, params: ScoringParams, *, repo=None) -> float:
        """Extract over the pinned snapshot and return Baseline_Accuracy as a pct.

        ``compute_baseline_accuracy`` returns a fraction in ``[0, 1]``; scaling by
        100 yields the percentage recorded throughout the experiment. No artefact
        is written — only ``AnalysisScript.save_outputs`` writes, and it is never
        called here.
        """
        dataset = snapshot.extract(params, repo=repo)
        analysis = AnalysisScript(dataset=dataset, ticker=snapshot.ticker, output_dir=_SWEEP_OUTPUT_DIR)
        return analysis.compute_baseline_accuracy() * 100
