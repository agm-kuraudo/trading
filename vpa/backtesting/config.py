"""Configuration for a single VPA backtest run (SP-317).

``BacktestConfig`` is a plain, frozen data holder. Validation of the
Hold_Period (must be a positive integer, Req 3.5) is performed by
``BacktestEngine.run`` per the design, not here, so the config stays a simple
immutable value object.
"""

from dataclasses import dataclass, field

from vpa.backtesting.exit_strategy import ExitStrategy, FixedHoldExitStrategy
from vpa.backtesting.models import PositionMode


@dataclass(frozen=True)
class BacktestConfig:
    """Configuration for a single backtest run."""

    hold_period: int  # N, positive integer (Req 3.5)
    round_trip_cost: float = 0.001  # Req 4.1 default 0.1%
    position_mode: PositionMode = PositionMode.NO_OVERLAP  # Req 5.1
    exit_strategy: ExitStrategy = field(default_factory=FixedHoldExitStrategy)  # Req 9.2 default
