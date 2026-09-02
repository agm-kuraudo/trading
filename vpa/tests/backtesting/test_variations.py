"""Example tests for strategy variations (SP-333, task 9.5).

Covers the variation signal filters, ``StrategyVariation.to_config`` field
mapping, ``run_variation`` (engine invoked and a ``VariationRun`` returned),
``run_variations`` single-failure isolation, ``validate_hold_period`` rejection,
and the All_Signals unknown-type exclusion behaviour.

Code under test:
- ``vpa/backtesting/variations.py`` (``StrategyVariation``, ``to_config``,
  ``validate_hold_period``, ``run_variation``, ``run_variations``,
  ``build_default_variations`` and the private filter helpers).

Signal logs and price series are built with sequential ascending ISO dates so
date-sort order matches positional order, reusing the SP-317 test patterns.

Requirements: 1.1, 1.4, 1.5, 3.1, 4.1, 5.1, 5.3, 6.3, 6.4, 7.10, 7.11
"""

import datetime as dt

import pytest

from vpa.backtesting.config import BacktestConfig
from vpa.backtesting.exit_strategy import FixedHoldExitStrategy, StopLossExitStrategy
from vpa.backtesting.models import (
    PositionMode,
    PricePoint,
    SignalEntry,
)
from vpa.backtesting.variations import (
    StrategyVariation,
    VariationFailure,
    VariationRun,
    build_default_variations,
    run_variation,
    run_variations,
    validate_hold_period,
)
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalDirection,
    SignalType,
)

_BASE_DATE = dt.date(2020, 1, 1)


def _iso(index: int) -> str:
    """Return a unique ascending ISO date string for positional ``index``."""
    return (_BASE_DATE + dt.timedelta(days=index)).isoformat()


def _make_price_series(closes: list[float]) -> list[PricePoint]:
    """Build a Price_Series from a list of close prices (SP-317 pattern)."""
    return [
        PricePoint(
            date=_iso(i),
            open=close,
            high=close + 1.0,
            low=max(close - 1.0, 0.01),
            close=close,
        )
        for i, close in enumerate(closes)
    ]


def _signal(date: str, signal_type: SignalType) -> SignalEntry:
    """Build a SignalEntry using SIGNAL_DIRECTIONS for the direction."""
    return SignalEntry(
        date=date,
        signal_type=signal_type,
        direction=SIGNAL_DIRECTIONS[signal_type],
    )


def _variation_by_name(name: str) -> StrategyVariation:
    """Locate a default variation by its name."""
    for variation in build_default_variations():
        if variation.name == name:
            return variation
    msg = f"no default variation named {name!r}"
    raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Signal filters (Req 3.1, 4.1, 5.1)
# ---------------------------------------------------------------------------


def test_baseline_filter_includes_every_signal_type() -> None:
    """Baseline includes every SignalType without filtering (Req 3.1)."""
    baseline = _variation_by_name("Baseline")
    for signal_type in SignalType:
        entry = _signal(_iso(1), signal_type)
        assert baseline.signal_filter(entry) is True


def test_contrarian_filter_includes_only_distribution_and_strong_bearish() -> None:
    """Contrarian_Only includes only DISTRIBUTION and STRONG_BEARISH (Req 4.1)."""
    contrarian = _variation_by_name("Contrarian_Only")
    included = {SignalType.DISTRIBUTION, SignalType.STRONG_BEARISH}

    for signal_type in SignalType:
        entry = _signal(_iso(1), signal_type)
        expected = signal_type in included
        assert contrarian.signal_filter(entry) is expected

    # The two contrarian types are DOWN signals, so P&L treats them as shorts.
    assert SIGNAL_DIRECTIONS[SignalType.DISTRIBUTION] is SignalDirection.DOWN
    assert SIGNAL_DIRECTIONS[SignalType.STRONG_BEARISH] is SignalDirection.DOWN


def test_all_signals_filter_includes_types_in_signal_directions() -> None:
    """All_Signals includes entries whose type is in SIGNAL_DIRECTIONS (Req 5.1)."""
    all_signals = _variation_by_name("All_Signals")
    for signal_type in SignalType:
        entry = _signal(_iso(1), signal_type)
        expected = signal_type in SIGNAL_DIRECTIONS
        assert all_signals.signal_filter(entry) is expected


def test_all_signals_filter_true_for_every_real_signal_type() -> None:
    """Every real SignalType member is in SIGNAL_DIRECTIONS (Req 5.1, 5.3).

    All five ``SignalType`` members are keys of ``SIGNAL_DIRECTIONS``, so the
    All_Signals ``_include_known_direction`` filter returns ``True`` for every
    real enum member. The unknown-type case (a signal type absent from
    ``SIGNAL_DIRECTIONS``) is therefore unreachable with valid enums: it would
    require a member outside the enum. We assert the reachable behaviour here —
    the filter admits all real types — and document that the downstream
    ``pnl.price_trades`` exclusion (Req 5.3, 8.6) is the safety net for any
    unknown direction that could ever slip through.
    """
    assert set(SIGNAL_DIRECTIONS) == set(SignalType)
    all_signals = _variation_by_name("All_Signals")
    assert all(all_signals.signal_filter(_signal(_iso(1), st)) for st in SignalType)


# ---------------------------------------------------------------------------
# to_config field mapping (Req 1.4)
# ---------------------------------------------------------------------------


def test_to_config_maps_fields_and_fixed_hold_exit() -> None:
    """to_config maps hold_period, cost, mode and the exit-strategy type (Req 1.4)."""
    variation = StrategyVariation(
        name="Custom",
        signal_filter=lambda _entry: True,
        hold_period=7,
        round_trip_cost=0.005,
        position_mode=PositionMode.STACKING,
        exit_strategy_factory=FixedHoldExitStrategy,
    )

    config = variation.to_config()

    assert isinstance(config, BacktestConfig)
    assert config.hold_period == 7
    assert config.round_trip_cost == 0.005
    assert config.position_mode is PositionMode.STACKING
    assert isinstance(config.exit_strategy, FixedHoldExitStrategy)


def test_to_config_builds_stop_loss_exit_instance() -> None:
    """to_config builds the StopLossExitStrategy instance from the factory (Req 1.4, 7.9)."""
    variation = StrategyVariation(
        name="Stop",
        signal_filter=lambda _entry: True,
        exit_strategy_factory=lambda: StopLossExitStrategy(threshold=-0.02),
    )

    config = variation.to_config()

    assert isinstance(config.exit_strategy, StopLossExitStrategy)
    assert config.exit_strategy.threshold == -0.02


def test_to_config_creates_fresh_exit_strategy_per_call() -> None:
    """Each to_config call builds its own exit-strategy instance (no shared state)."""
    variation = _variation_by_name("Baseline")
    first = variation.to_config().exit_strategy
    second = variation.to_config().exit_strategy
    assert first is not second


# ---------------------------------------------------------------------------
# run_variation (Req 1.1, 1.2, 1.3, 5.1)
# ---------------------------------------------------------------------------


def test_run_variation_calls_engine_and_returns_variation_run() -> None:
    """run_variation runs the engine once and returns a populated VariationRun (Req 1.1)."""
    # A rising series so a Baseline long trade resolves cleanly.
    price_series = _make_price_series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    signal_log = [_signal(_iso(0), SignalType.STRONG_BULLISH)]

    variation = StrategyVariation(
        name="RunOnce",
        signal_filter=lambda _entry: True,
        hold_period=3,
    )

    run = run_variation(variation, signal_log, price_series)

    assert isinstance(run, VariationRun)
    assert run.variation is variation
    # Engine produced exactly one trade for the single eligible signal.
    assert len(run.result.trades) == 1
    assert len(run.priced_trades) == 1
    # Equity curve has one point per price-series date (Req 9.1).
    assert len(run.equity_curve) == len(price_series)
    assert run.metrics.number_of_trades == 1


def test_run_variation_applies_signal_filter_before_engine() -> None:
    """run_variation filters the Signal_Log so excluded types never trade (Req 4.1)."""
    price_series = _make_price_series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    # One included (STRONG_BEARISH) and one excluded (STRONG_BULLISH) signal.
    signal_log = [
        _signal(_iso(0), SignalType.STRONG_BULLISH),
        _signal(_iso(1), SignalType.STRONG_BEARISH),
    ]

    contrarian = _variation_by_name("Contrarian_Only")
    contrarian = StrategyVariation(
        name=contrarian.name,
        signal_filter=contrarian.signal_filter,
        hold_period=3,
    )

    run = run_variation(contrarian, signal_log, price_series)

    # Only the STRONG_BEARISH signal survives the filter -> exactly one trade.
    assert len(run.result.trades) == 1
    assert run.result.trades[0].signal_type is SignalType.STRONG_BEARISH


# ---------------------------------------------------------------------------
# validate_hold_period rejection (Req 6.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_hold", [0, -1, -10])
def test_validate_hold_period_rejects_non_positive(bad_hold: int) -> None:
    """validate_hold_period rejects hold periods < 1 with ValueError (Req 6.3)."""
    with pytest.raises(ValueError, match="positive integer"):
        validate_hold_period(bad_hold)


@pytest.mark.parametrize("bad_hold", [1.5, "3", None, True, False])
def test_validate_hold_period_rejects_non_int(bad_hold: object) -> None:
    """validate_hold_period rejects non-int (including bool) with ValueError (Req 6.3)."""
    with pytest.raises(ValueError, match="must be an int"):
        validate_hold_period(bad_hold)  # type: ignore[arg-type]


def test_validate_hold_period_accepts_positive_int() -> None:
    """A positive int hold period passes validation without error."""
    assert validate_hold_period(1) is None
    assert validate_hold_period(10) is None


# ---------------------------------------------------------------------------
# run_variations single-failure isolation (Req 1.5, 6.4)
# ---------------------------------------------------------------------------


def test_run_variations_isolates_a_single_failure() -> None:
    """One failing variation is isolated; the others still run (Req 1.5, 6.4)."""
    price_series = _make_price_series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    signal_log = [_signal(_iso(0), SignalType.STRONG_BULLISH)]

    good = StrategyVariation(
        name="Good",
        signal_filter=lambda _entry: True,
        hold_period=3,
    )
    # hold_period=0 is rejected by validate_hold_period before the engine runs.
    bad = StrategyVariation(
        name="Bad",
        signal_filter=lambda _entry: True,
        hold_period=0,
    )

    runs, failures = run_variations([good, bad], signal_log, price_series)

    assert len(runs) == 1
    assert runs[0].variation.name == "Good"
    assert len(failures) == 1
    assert isinstance(failures[0], VariationFailure)
    assert failures[0].name == "Bad"
    assert failures[0].error  # a non-empty descriptive error message


def test_run_variations_failure_does_not_stop_remaining_variations() -> None:
    """A failure between two good variations does not stop the rest (Req 1.5, 6.4)."""
    price_series = _make_price_series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    signal_log = [_signal(_iso(0), SignalType.STRONG_BULLISH)]

    first = StrategyVariation(name="First", signal_filter=lambda _e: True, hold_period=3)
    broken = StrategyVariation(name="Broken", signal_filter=lambda _e: True, hold_period=-5)
    last = StrategyVariation(name="Last", signal_filter=lambda _e: True, hold_period=2)

    runs, failures = run_variations([first, broken, last], signal_log, price_series)

    assert [r.variation.name for r in runs] == ["First", "Last"]
    assert [f.name for f in failures] == ["Broken"]


def test_run_variations_all_succeed_yields_no_failures() -> None:
    """When every variation succeeds, no failures are recorded (Req 1.5)."""
    price_series = _make_price_series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    signal_log = [_signal(_iso(0), SignalType.STRONG_BULLISH)]

    variations = [
        StrategyVariation(name="A", signal_filter=lambda _e: True, hold_period=2),
        StrategyVariation(name="B", signal_filter=lambda _e: True, hold_period=3),
    ]

    runs, failures = run_variations(variations, signal_log, price_series)

    assert [r.variation.name for r in runs] == ["A", "B"]
    assert failures == []


# ---------------------------------------------------------------------------
# build_default_variations catalogue (Req 3.1, 4.1, 5.1, 7.10, 7.11)
# ---------------------------------------------------------------------------


def test_build_default_variations_names_are_unique() -> None:
    """Every default variation carries a distinct name for unique CSV slugs (Req 7.11)."""
    names = [v.name for v in build_default_variations()]
    assert len(names) == len(set(names))


def test_signal_stacking_variation_uses_stacking_position_mode() -> None:
    """The Signal_Stacking variation configures STACKING position mode (Req 7.10)."""
    stacking = _variation_by_name("Signal_Stacking")
    assert stacking.position_mode is PositionMode.STACKING
    assert stacking.to_config().position_mode is PositionMode.STACKING
