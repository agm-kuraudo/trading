"""Construction and conformance tests for RecentExtremeExitStrategy (SP-354).

Covers Task 3.1: construction-time validation (Req 2.3-2.5), the configuration
defaults (Req 2.2, 2.6), and protocol conformance (Req 1.1). Geometry, forward
scan, and fallback behaviour are exercised by the property/oracle tests in a
separate task.

Code under test: ``vpa/backtesting/exit_strategy.py``
(``RecentExtremeExitStrategy``).
"""

import pytest

from vpa.backtesting.exit_strategy import ExitStrategy, RecentExtremeExitStrategy
from vpa.ml_validation.signal_analysis import SignalDirection


@pytest.mark.parametrize(
    "lookback",
    [0, -1, 1.5, True],
)
def test_invalid_lookback_raises_value_error(lookback: object) -> None:
    """A non-positive-int lookback (including bool) is rejected at construction.

    Validates: Requirements 2.3.

    ``bool`` is a subclass of ``int`` in Python, so ``True`` must be rejected as
    a non-int before the positive-int check, mirroring
    ``variations.validate_hold_period``.
    """
    with pytest.raises(ValueError):
        RecentExtremeExitStrategy(lookback=lookback, reward_risk=2.0)  # type: ignore[arg-type]


def test_negative_buffer_raises_value_error() -> None:
    """A negative buffer is rejected at construction.

    Validates: Requirements 2.4.
    """
    with pytest.raises(ValueError):
        RecentExtremeExitStrategy(lookback=5, reward_risk=2.0, buffer=-0.01)


@pytest.mark.parametrize("reward_risk", [0, -1])
def test_non_positive_reward_risk_raises_value_error(reward_risk: float) -> None:
    """A reward_risk that is not strictly > 0 is rejected at construction.

    Validates: Requirements 2.5.
    """
    with pytest.raises(ValueError):
        RecentExtremeExitStrategy(lookback=5, reward_risk=reward_risk)


def test_defaults_direction_up_and_buffer_zero() -> None:
    """The default direction is UP (long) and the default buffer is 0.0.

    Validates: Requirements 2.2, 2.6.
    """
    strategy = RecentExtremeExitStrategy(lookback=5, reward_risk=2.0)

    assert strategy.direction is SignalDirection.UP
    assert strategy.buffer == 0.0


def test_conforms_to_exit_strategy_protocol() -> None:
    """A valid instance conforms to the ExitStrategy protocol.

    Validates: Requirements 1.1.
    """
    assert isinstance(RecentExtremeExitStrategy(lookback=5, reward_risk=2), ExitStrategy)
