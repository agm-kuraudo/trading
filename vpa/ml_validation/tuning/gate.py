"""Pure decision functions for the SP-313 threshold-change gate.

This module holds the ``ChangeGate`` logic: pure functions that decide whether a
tuned threshold candidate should be *recorded* (per-dimension margins) and
whether it should be *applied* to the production VPA configuration (the Req 6
apply gate). Nothing here performs I/O, trains a model, or mutates global state.

Two distinct comparisons live here, and they are intentionally different:

- :func:`exceeds_margin` is a strict ``>`` comparison, used for the per-dimension
  *recording* margins (Req 3.3 ``+0.1pp``, Req 4.2 ``+0.10pp``). A candidate is
  worth recording when it beats the baseline by strictly more than the margin.
- :func:`should_apply_to_config` is the Req 6 *apply* gate: a ``>=`` comparison
  against ``SP312_ML_STD_PCT`` (3.09pp). A tuned value is written to config only
  when it increases accuracy by at least the SP312 ML std over the value
  currently in effect. This is the function covered by Correctness Property 6,
  whose boundary semantics (``True`` iff ``candidate - in_effect >= 3.09``) must
  be matched exactly.

:func:`record_shooting_star` implements the Req 2.2--2.4 recording-and-selection
logic for the shooting-star dimension and returns a :class:`SelectionOutcome`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Reuse the SP312 ML std constant as the single source of truth for the Req 6
# apply gate (3.09pp). Importing keeps classify.py authoritative for the value.
from vpa.ml_validation.tuning.classify import SP312_ML_STD_PCT

# Per-dimension recording margin for the shooting-star dimension (Req 2.2/2.3).
SHOOTING_STAR_RECORD_MARGIN_PP = 0.5

# The current (in-effect) shooting-star multiplier value; ties in selection are
# broken toward the candidate nearest this value (Req 2.3).
SHOOTING_STAR_CURRENT_VALUE = 2.0


@dataclass(frozen=True)
class SelectionOutcome:
    """Outcome of selecting/retaining a tuned threshold for one dimension.

    Mirrors the design's Data Models ``SelectionOutcome`` entry and captures
    everything Req 6.3 requires to document an applied change, or the
    "no change beneficial" result (Req 2.4/3.5/4.3/5.4).

    Attributes:
        dimension: The tuning dimension, e.g. ``"shooting_star"``.
        changed: ``True`` when a tuned value was selected over the prior value;
            ``False`` means "no change beneficial" (the prior value is retained).
        prior_value: The threshold value in effect before selection.
        applied_value: The selected value; equals ``prior_value`` when
            ``changed`` is ``False``.
        prior_accuracy_pct: Baseline accuracy measured for ``prior_value``.
        new_accuracy_pct: Baseline accuracy measured for ``applied_value``;
            equals ``prior_accuracy_pct`` when ``changed`` is ``False``.
        justifying_delta_pp: The accuracy difference that justified the change
            (``new - prior``), or ``None`` when no change was made.
        note: Human-readable explanation, e.g. "no candidate cleared the apply
            gate".
    """

    dimension: str
    changed: bool
    prior_value: float
    applied_value: float
    prior_accuracy_pct: float
    new_accuracy_pct: float
    justifying_delta_pp: float | None
    note: str


def exceeds_margin(candidate_pct: float, baseline_pct: float, margin_pp: float) -> bool:
    """Return whether a candidate beats the baseline by strictly more than a margin.

    Strict ``>`` comparison used for the per-dimension *recording* margins
    (Req 3.3 ``+0.1pp``, Req 4.2 ``+0.10pp``). The candidate is worth recording
    when ``candidate_pct - baseline_pct`` is strictly greater than ``margin_pp``.
    """
    return (candidate_pct - baseline_pct) > margin_pp


def should_apply_to_config(candidate_pct: float, in_effect_pct: float) -> bool:
    """Return whether a tuned value clears the Req 6 apply gate.

    The gate is a ``>=`` comparison against the SP312 ML std (3.09pp): a tuned
    value is applied to the VPA configuration only when it increases accuracy by
    at least ``SP312_ML_STD_PCT`` over the value currently in effect (Req 6.1).
    Otherwise the in-effect value is retained (Req 6.2).

    This is the function covered by Correctness Property 6: it is ``True`` if and
    only if ``candidate_pct - in_effect_pct >= 3.09``.
    """
    return (candidate_pct - in_effect_pct) >= SP312_ML_STD_PCT


def record_shooting_star(
    current_accuracy_pct: float,
    candidates: list[tuple[float, float]],
    *,
    current_value: float = SHOOTING_STAR_CURRENT_VALUE,
    record_margin_pp: float = SHOOTING_STAR_RECORD_MARGIN_PP,
) -> SelectionOutcome:
    """Select the best shooting-star candidate per Req 2.2--2.4.

    Among the supplied candidates, keep only those whose accuracy exceeds the
    current threshold's accuracy by at least ``record_margin_pp`` (``+0.5pp``,
    Req 2.2). From those, select the one with the highest measured accuracy
    (Req 2.3). An exact tie in accuracy is broken toward the candidate whose
    value is nearest ``current_value`` (2) (Req 2.3). If no candidate clears the
    margin, retain the current value and record that no change was beneficial
    (Req 2.4).

    Args:
        current_accuracy_pct: Baseline accuracy measured for ``current_value``.
        candidates: ``(candidate_value, candidate_accuracy_pct)`` pairs, each
            evaluated on the same dataset as ``current_accuracy_pct``.
        current_value: The threshold value currently in effect (default 2).
        record_margin_pp: The improvement margin a candidate must clear to be
            recorded (default ``+0.5pp``).

    Returns:
        A :class:`SelectionOutcome` describing the selected value (or the
        retained current value) and the justifying accuracy delta.
    """
    dimension = "shooting_star"

    # Req 2.2: keep candidates clearing the +0.5pp recording margin over current.
    clearing = [
        (value, accuracy_pct)
        for value, accuracy_pct in candidates
        if exceeds_margin(accuracy_pct, current_accuracy_pct, record_margin_pp)
    ]

    if not clearing:
        # Req 2.4: no candidate was beneficial; retain the current value.
        return SelectionOutcome(
            dimension=dimension,
            changed=False,
            prior_value=current_value,
            applied_value=current_value,
            prior_accuracy_pct=current_accuracy_pct,
            new_accuracy_pct=current_accuracy_pct,
            justifying_delta_pp=None,
            note="no change beneficial",
        )

    # Req 2.3: highest accuracy wins; break an exact tie toward the candidate
    # nearest the current value. Sorting by (-accuracy, distance-to-current)
    # puts the best accuracy first and, among equal accuracies, the nearest
    # value first.
    best_value, best_accuracy_pct = min(
        clearing,
        key=lambda item: (-item[1], abs(item[0] - current_value)),
    )
    delta_pp = best_accuracy_pct - current_accuracy_pct

    return SelectionOutcome(
        dimension=dimension,
        changed=True,
        prior_value=current_value,
        applied_value=best_value,
        prior_accuracy_pct=current_accuracy_pct,
        new_accuracy_pct=best_accuracy_pct,
        justifying_delta_pp=delta_pp,
        note=f"selected shooting-star multiplier {best_value} (+{delta_pp:.2f}pp over current)",
    )
