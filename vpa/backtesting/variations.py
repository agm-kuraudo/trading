"""Strategy configuration and per-variation run records (SP-333, Req 1.4, 2.1).

A ``StrategyVariation`` is a fully specified, named backtest configuration. Its
``to_config`` method builds a plain ``BacktestConfig`` from its fields so the
existing ``BacktestEngine`` can be reused unchanged, configured purely through
config fields (Req 1.4). New exit behaviour plugs in via the
``exit_strategy_factory`` rather than by modifying, subclassing, or
monkeypatching the engine.

This module is pure: it operates only on caller-supplied in-memory values and
performs no network, filesystem, or ``yfinance`` access (Req 2.1).
"""

from collections.abc import Callable
from dataclasses import dataclass

from vpa.backtesting import equity_curve, metrics, pnl
from vpa.backtesting.config import BacktestConfig
from vpa.backtesting.engine import BacktestEngine
from vpa.backtesting.exit_strategy import ExitStrategy, FixedHoldExitStrategy, StopLossExitStrategy
from vpa.backtesting.metrics import DEFAULT_RISK_FREE_RATE
from vpa.backtesting.models import (
    BacktestResult,
    EquityPoint,
    MetricsResult,
    PositionMode,
    PricedTrade,
    PricePoint,
    SignalEntry,
    TradeExclusion,
)
from vpa.ml_validation.signal_analysis import SIGNAL_DIRECTIONS, SignalType

SignalFilter = Callable[[SignalEntry], bool]
"""Predicate selecting which ``SignalEntry`` records a variation includes."""


@dataclass(frozen=True)
class StrategyVariation:
    """A fully specified, named backtest configuration (SP-333, Req 3-7).

    ``signal_filter`` selects which ``SignalEntry`` records to include.
    ``exit_strategy_factory`` builds the exit strategy for the run so each
    variation gets its own instance without sharing mutable state. The remaining
    fields map directly onto ``BacktestConfig`` via :meth:`to_config`.
    """

    name: str
    signal_filter: SignalFilter
    hold_period: int = 10  # Req 3.2 default
    round_trip_cost: float = 0.001
    position_mode: PositionMode = PositionMode.NO_OVERLAP
    exit_strategy_factory: Callable[[], ExitStrategy] = FixedHoldExitStrategy
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE

    def to_config(self) -> BacktestConfig:
        """Build a ``BacktestConfig`` from this variation's fields (Req 1.4).

        The engine is configured purely through the config; a fresh exit
        strategy is created via ``exit_strategy_factory`` per run.
        """
        return BacktestConfig(
            hold_period=self.hold_period,
            round_trip_cost=self.round_trip_cost,
            position_mode=self.position_mode,
            exit_strategy=self.exit_strategy_factory(),
        )


@dataclass(frozen=True)
class VariationRun:
    """The full per-variation outcome consumed by reporting (SP-333)."""

    variation: StrategyVariation
    result: BacktestResult
    priced_trades: list[PricedTrade]
    exclusions: list[TradeExclusion]
    equity_curve: list[EquityPoint]
    metrics: MetricsResult


@dataclass(frozen=True)
class VariationFailure:
    """A variation that failed to complete (SP-333, Req 1.5, 6.4, 19.5)."""

    name: str
    error: str


def validate_hold_period(hold_period: int) -> None:
    """Validate a variation's Hold_Period before the engine is invoked (Req 6.3).

    The Hold_Period must be an integer of at least 1. A non-int or a value
    ``< 1`` is rejected with a descriptive ``ValueError`` up front, so the
    failure is attributed to the offending variation rather than surfacing from
    deep inside the engine's simulation loop.

    ``bool`` is a subclass of ``int`` in Python, so ``True``/``False`` would
    otherwise slip through an ``isinstance(..., int)`` check; it is explicitly
    rejected as a non-int.

    Raises:
        ValueError: if ``hold_period`` is not an ``int`` (including ``bool``) or
            is less than 1.
    """
    if isinstance(hold_period, bool) or not isinstance(hold_period, int):
        msg = f"hold_period must be an int, got {type(hold_period).__name__}: {hold_period!r}"
        raise ValueError(msg)
    if hold_period < 1:
        msg = f"hold_period must be a positive integer (>= 1), got {hold_period}"
        raise ValueError(msg)


def run_variation(
    variation: StrategyVariation,
    signal_log: list[SignalEntry],
    price_series: list[PricePoint],
) -> VariationRun:
    """Run one ``StrategyVariation`` end to end into a ``VariationRun`` (Req 1.1-1.3, 5.1).

    The Hold_Period is validated first (Req 6.3), before any engine work, so an
    invalid variation fails fast with a descriptive error. The variation's
    ``signal_filter`` then selects the eligible ``SignalEntry`` records, and the
    engine is invoked exactly once via its public API with the filtered log and
    the variation's config (Req 1.1). The engine is neither modified, subclassed,
    nor monkeypatched — a fresh ``BacktestEngine`` is constructed and called
    through ``run`` (Req 2.1).

    The engine's ``BacktestResult`` is then threaded through the pure reporting
    pipeline: direction-aware pricing (``pnl.price_trades``), the daily equity
    curve (``equity_curve.build_equity_curve``), and the performance-metrics
    suite (``metrics.calculate``), all consistent with the variation's
    ``round_trip_cost`` and ``risk_free_rate``. The assembled ``VariationRun``
    carries the variation, the raw engine result, the priced trades, the P&L
    exclusions, the equity curve, and the metrics for downstream reporting.
    """
    validate_hold_period(variation.hold_period)

    filtered_log = [entry for entry in signal_log if variation.signal_filter(entry)]

    result = BacktestEngine().run(filtered_log, price_series, variation.to_config())

    priced_trades, exclusions = pnl.price_trades(result.trades, variation.round_trip_cost)
    curve = equity_curve.build_equity_curve(price_series, priced_trades)
    computed_metrics = metrics.calculate(priced_trades, curve, price_series, variation.risk_free_rate)

    return VariationRun(
        variation=variation,
        result=result,
        priced_trades=priced_trades,
        exclusions=exclusions,
        equity_curve=curve,
        metrics=computed_metrics,
    )


def run_variations(
    variations: list[StrategyVariation],
    signal_log: list[SignalEntry],
    price_series: list[PricePoint],
) -> tuple[list[VariationRun], list[VariationFailure]]:
    """Run every variation, isolating each one's failure from the rest (Req 1.5, 6.4).

    Each ``run_variation`` call is wrapped individually. If a variation raises —
    whether a ``ValueError`` from :func:`validate_hold_period`, a bad hold period
    reaching the engine, or any other engine error — the offending variation is
    recorded as a ``VariationFailure(name, error)``, the runs already completed
    are retained, and the remaining variations still execute. This per-variation
    isolation ensures one variation's failure never aborts the whole batch.

    A broad ``Exception`` is caught deliberately: the goal is to contain any
    failure a single variation can produce so the batch continues. The exception
    message is captured into ``VariationFailure.error`` for downstream reporting.

    The module stays pure: it only operates on caller-supplied in-memory values.

    Returns:
        A ``(successful_runs, failures)`` tuple. Both lists preserve the order of
        the input ``variations``.
    """
    successful_runs: list[VariationRun] = []
    failures: list[VariationFailure] = []

    for variation in variations:
        try:
            successful_runs.append(run_variation(variation, signal_log, price_series))
        except Exception as exc:  # noqa: BLE001 - per-variation isolation (Req 1.5, 6.4)
            failures.append(VariationFailure(name=variation.name, error=str(exc)))

    return successful_runs, failures


# ---------------------------------------------------------------------------
# Signal filters (Req 3.1, 4.1, 5.1)
# ---------------------------------------------------------------------------
#
# Each filter is a proper named function so its intent is explicit and it binds
# no loop variables. ``SignalFilter`` is ``Callable[[SignalEntry], bool]``; the
# filters branch on ``entry.signal_type`` only.

# The two DOWN, "contrarian" signal types (Req 4.1). Both map to
# ``SignalDirection.DOWN`` in ``SIGNAL_DIRECTIONS``, so P&L treats them as shorts.
_CONTRARIAN_SIGNAL_TYPES = frozenset({SignalType.DISTRIBUTION, SignalType.STRONG_BEARISH})


def _include_all(_entry: SignalEntry) -> bool:
    """Baseline filter: accept every ``SignalEntry`` regardless of type (Req 3.1)."""
    return True


def _include_contrarian(entry: SignalEntry) -> bool:
    """Contrarian_Only filter: accept only DISTRIBUTION / STRONG_BEARISH (Req 4.1)."""
    return entry.signal_type in _CONTRARIAN_SIGNAL_TYPES


def _include_known_direction(entry: SignalEntry) -> bool:
    """All_Signals filter: accept entries whose type is in ``SIGNAL_DIRECTIONS`` (Req 5.1).

    Unknown signal types (absent from ``SIGNAL_DIRECTIONS``) are excluded here so
    they never reach the engine; any that do slip through are further indicated
    as excluded downstream by ``pnl.price_trades`` (Req 5.3).
    """
    return entry.signal_type in SIGNAL_DIRECTIONS


def build_default_variations() -> list[StrategyVariation]:
    """Build the full default catalogue of strategy variations (Req 3-7, 19.4).

    The catalogue covers, in order:

    * **Baseline** — every signal, hold 10, ``FixedHoldExitStrategy``,
      ``NO_OVERLAP`` (Req 3.1-3.4).
    * **Contrarian_Only** — only ``DISTRIBUTION`` / ``STRONG_BEARISH`` (Req 4.1).
    * **All_Signals** — every entry whose type is in ``SIGNAL_DIRECTIONS`` (Req 5.1).
    * **Variable_Hold {5,10,15,20}** — four Baseline-style variations differing
      only in ``hold_period`` (Req 6.1).
    * **Stop_Loss {-0.02,-0.03}** — ``exit_strategy_factory`` builds a
      ``StopLossExitStrategy`` at that threshold (Req 7.9).
    * **Signal_Stacking** — ``position_mode = STACKING`` (Req 7.10).

    Every variation carries a distinct ``name`` so its per-trade and equity CSV
    slugs stay unique downstream (Req 7.11, 19.4).
    """
    variations: list[StrategyVariation] = []

    # Baseline: include every signal, hold 10, fixed-hold exit, no overlap (Req 3.1-3.4).
    variations.append(
        StrategyVariation(
            name="Baseline",
            signal_filter=_include_all,
            hold_period=10,
            position_mode=PositionMode.NO_OVERLAP,
            exit_strategy_factory=FixedHoldExitStrategy,
        )
    )

    # Contrarian_Only: only the two DOWN signal types (Req 4.1).
    variations.append(
        StrategyVariation(
            name="Contrarian_Only",
            signal_filter=_include_contrarian,
        )
    )

    # All_Signals: every entry with a known direction; unknowns excluded (Req 5.1, 5.3).
    variations.append(
        StrategyVariation(
            name="All_Signals",
            signal_filter=_include_known_direction,
        )
    )

    # Variable_Hold {5,10,15,20}: Baseline-style, differing only in hold_period (Req 6.1).
    for hold in (5, 10, 15, 20):
        variations.append(
            StrategyVariation(
                name=f"Variable_Hold_{hold}",
                signal_filter=_include_all,
                hold_period=hold,
                position_mode=PositionMode.NO_OVERLAP,
                exit_strategy_factory=FixedHoldExitStrategy,
            )
        )

    # Stop_Loss {-0.02,-0.03}: Baseline-style but with a stop-loss exit (Req 7.9).
    # ``exit_strategy_factory`` is a zero-arg callable, so the threshold is bound
    # per iteration via a default argument to avoid late-binding in the loop.
    for threshold in (-0.02, -0.03):
        pct = abs(round(threshold * 100))
        variations.append(
            StrategyVariation(
                name=f"Stop_Loss_-{pct}pct",
                signal_filter=_include_all,
                exit_strategy_factory=(lambda t=threshold: StopLossExitStrategy(threshold=t)),
            )
        )

    # Signal_Stacking: Baseline-style but allowing overlapping positions (Req 7.10).
    variations.append(
        StrategyVariation(
            name="Signal_Stacking",
            signal_filter=_include_all,
            position_mode=PositionMode.STACKING,
        )
    )

    return variations
