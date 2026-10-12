"""Pure classification and decision functions for VPA threshold tuning (SP-313).

This module holds the single source of truth for the SP312 reference constants
and the pure band/decision functions used by the SPY re-validation (Req 7),
the multi-ticker edge classification (Req 9), and the pursue decision (Req 8).

Every function here is pure: no I/O, no model, no global state. Boundaries match
Correctness Property 7 exactly:

- ``classify_ml_vs_sp312``: ``increased`` when ``ml_pct > 53.68``, ``decreased``
  when ``ml_pct < 47.50``, else ``within-band`` (47.50 and 53.68 inclusive).
- ``classify_baseline_vs_sp312``: ``increased``/``decreased``/``unchanged`` vs
  52.34 (``unchanged`` only on exact equality).
- ``classify_ticker_edge``: ``stronger`` when the ticker exceeds SPY by more than
  3.09pp, ``weaker`` when below SPY by more than 3.09pp, else ``comparable``
  (within +/-3.09pp inclusive).
- ``pursue_decision``: ``pursue`` when strictly greater than 54.0, ``do not
  pursue`` when ``<= 54.0``; ``None`` yields ``no recommendation`` with a reason.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Constants (single source of truth) ---------------------------------
# These mirror the SP312 baseline and the design's Constants block. They are the
# authoritative values for the band boundaries and the pursue threshold.
SP312_BASELINE_PCT = 52.34
SP312_ML_MEAN_PCT = 50.59
SP312_ML_STD_PCT = 3.09
PURSUE_ML_THRESHOLD_PCT = 54.0
ML_BAND_LOW = 47.50  # SP312_ML_MEAN_PCT - SP312_ML_STD_PCT
ML_BAND_HIGH = 53.68  # SP312_ML_MEAN_PCT + SP312_ML_STD_PCT


@dataclass(frozen=True)
class PursueResult:
    """Outcome of the pursue / do-not-pursue decision (Req 8, 10.4).

    Attributes:
        recommendation: One of ``"pursue"``, ``"do not pursue"``, or
            ``"no recommendation"``.
        supporting_ml_accuracy_pct: The SPY mean ML accuracy that supports the
            recommendation, or ``None`` when unavailable.
        unavailable_reason: Explanation when no recommendation can be made
            (Req 8.4 / 10.6), otherwise ``None``.
    """

    recommendation: str
    supporting_ml_accuracy_pct: float | None
    unavailable_reason: str | None


def classify_ml_vs_sp312(ml_pct: float) -> str:
    """Classify a SPY mean ML accuracy against the SP312 std-dev band (Req 7.4).

    Returns ``"increased"`` when ``ml_pct`` is above ``ML_BAND_HIGH`` (53.68),
    ``"decreased"`` when below ``ML_BAND_LOW`` (47.50), otherwise
    ``"within-band"`` (both boundaries inclusive).
    """
    if ml_pct > ML_BAND_HIGH:
        return "increased"
    if ml_pct < ML_BAND_LOW:
        return "decreased"
    return "within-band"


def classify_baseline_vs_sp312(base_pct: float) -> str:
    """Classify a SPY baseline accuracy against the SP312 baseline (Req 7.4).

    Returns ``"increased"`` when ``base_pct`` is above 52.34, ``"decreased"``
    when below 52.34, and ``"unchanged"`` only on exact equality.
    """
    if base_pct > SP312_BASELINE_PCT:
        return "increased"
    if base_pct < SP312_BASELINE_PCT:
        return "decreased"
    return "unchanged"


def classify_ticker_edge(ticker_base_pct: float, spy_base_pct: float) -> str:
    """Classify an individual ticker's VPA edge against SPY (Req 9.4).

    Returns ``"stronger"`` when the ticker exceeds SPY by more than 3.09pp,
    ``"weaker"`` when below SPY by more than 3.09pp, otherwise ``"comparable"``
    (within +/-3.09pp inclusive).
    """
    delta_pp = ticker_base_pct - spy_base_pct
    if delta_pp > SP312_ML_STD_PCT:
        return "stronger"
    if delta_pp < -SP312_ML_STD_PCT:
        return "weaker"
    return "comparable"


def pursue_decision(spy_ml_pct: float | None) -> PursueResult:
    """Decide whether to pursue a production ML model from SPY ML accuracy (Req 8).

    ``pursue`` when ``spy_ml_pct`` is strictly greater than 54.0; ``do not
    pursue`` when ``<= 54.0``. When ``spy_ml_pct`` is ``None`` (no SPY ML
    accuracy was produced), returns ``no recommendation`` with an
    unavailable reason and no supporting value (Req 8.4).
    """
    if spy_ml_pct is None:
        return PursueResult(
            recommendation="no recommendation",
            supporting_ml_accuracy_pct=None,
            unavailable_reason="SPY ML_Accuracy was unavailable",
        )
    if spy_ml_pct > PURSUE_ML_THRESHOLD_PCT:
        return PursueResult(
            recommendation="pursue",
            supporting_ml_accuracy_pct=spy_ml_pct,
            unavailable_reason=None,
        )
    return PursueResult(
        recommendation="do not pursue",
        supporting_ml_accuracy_pct=spy_ml_pct,
        unavailable_reason=None,
    )
