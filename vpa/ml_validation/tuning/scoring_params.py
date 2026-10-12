"""Injectable VPA scoring parameters for the SP-313 threshold-tuning experiment.

``ScoringParams`` carries every tunable VPA scoring threshold as an immutable
dataclass. Its defaults equal today's production literals, so constructing
``ScoringParams()`` (or ``ScoringParams.default()``) and threading it through the
feature extractor reproduces current scoring exactly (Correctness Property 1).

See the design document ``ScoringParams`` section and Requirements 2.5, 3.1,
3.2 and 5.1 for the validation rules enforced by :meth:`ScoringParams.validate`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class ScoringParams:
    """Immutable set of tunable VPA scoring thresholds.

    Defaults reproduce the current production configuration exactly:

    - shooting-star multipliers default to ``2.0`` (the ``Candle`` class
      constants);
    - the acc/dist volume percentile defaults to ``65`` and the test count to
      ``3`` (the hardcoded literals in ``identify_acc_or_dist``);
    - the period weights default to ``1.0`` (reproduces the current unweighted
      sum);
    - the volume-backed multipliers default to ``2.0`` (reproduces the current
      ``* 2`` doubling).
    """

    # Requirement 2 — shooting-star detection multipliers
    shooting_star_spread_mult: float = 2.0
    shooting_star_lower_wick_mult: float = 2.0
    # Requirement 3 — accumulation/distribution scoring
    acc_dist_volume_percentile: int = 65  # integer in 1..99 inclusive
    acc_dist_test_count: int = 3  # integer >= 1
    # Requirement 4 — period composite weighting (1.0 == current unweighted sum)
    period_weight_p1: float = 1.0
    period_weight_p2: float = 1.0
    period_weight_p3: float = 1.0
    # Requirement 5 — volume-backed multipliers (2.0 == current doubling)
    vol_backed_mult_p1: float = 2.0
    vol_backed_mult_p2: float = 2.0
    vol_backed_mult_p3: float = 2.0

    @classmethod
    def default(cls) -> ScoringParams:
        """Return the canonical current production configuration."""
        return cls()

    def validate(self) -> list[str]:
        """Return human-readable rejection messages; an empty list means valid.

        Enforces exactly the range rules from the requirements:

        - Req 2.5: ``shooting_star_spread_mult`` and
          ``shooting_star_lower_wick_mult`` must each be a positive number
          ``>= 1``.
        - Req 3.1: ``acc_dist_volume_percentile`` must be an integer in the
          range ``1..99`` inclusive.
        - Req 3.2: ``acc_dist_test_count`` must be an integer ``>= 1``.
        - Req 5.1: each ``vol_backed_mult_pN`` must be ``>= 0`` (non-negative).

        A ``bool`` is never accepted where an integer is required, since
        ``bool`` is a subclass of ``int`` in Python but is not a meaningful
        percentile or count here (Property 5).
        """
        messages: list[str] = []

        # Req 2.5 — shooting-star multipliers must be a positive number >= 1.
        for name in ("shooting_star_spread_mult", "shooting_star_lower_wick_mult"):
            value = getattr(self, name)
            if not _is_real_number(value) or value < 1:
                messages.append(
                    f"{name} must be a positive number >= 1 (got {value!r}); candidate rejected as out of range"
                )

        # Req 3.1 — acc_dist_volume_percentile must be an integer in 1..99.
        percentile = self.acc_dist_volume_percentile
        if not _is_strict_int(percentile) or not (1 <= percentile <= 99):
            messages.append(
                f"acc_dist_volume_percentile must be an integer in 1..99 "
                f"(got {percentile!r}); candidate rejected as out of range"
            )

        # Req 3.2 — acc_dist_test_count must be an integer >= 1.
        test_count = self.acc_dist_test_count
        if not _is_strict_int(test_count) or test_count < 1:
            messages.append(
                f"acc_dist_test_count must be an integer >= 1 (got {test_count!r}); candidate rejected as out of range"
            )

        # Req 5.1 — volume-backed multipliers must be non-negative.
        for name in ("vol_backed_mult_p1", "vol_backed_mult_p2", "vol_backed_mult_p3"):
            value = getattr(self, name)
            if not _is_real_number(value) or value < 0:
                messages.append(f"{name} must be >= 0 (got {value!r}); candidate rejected as out of range")

        return messages

    def as_dict(self) -> dict[str, float | int]:
        """Return a flat dict of the fields (for serialising into artefacts)."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _is_real_number(value: object) -> bool:
    """Return True for a real int/float that is not a bool and not NaN."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, int) and not isinstance(value, float):
        return False
    # Reject NaN (NaN != NaN); any comparison against it is False.
    return value == value


def _is_strict_int(value: object) -> bool:
    """Return True only for a genuine int (bool is rejected)."""
    return isinstance(value, int) and not isinstance(value, bool)
