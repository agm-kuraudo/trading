"""Integration tests for the Combined (confluence) backtest variations (SP-327, task 8.2).

Covers the five ``Combo_*`` ``StrategyVariation``s added in task 8.1
(``_COMBO_FILTER_TYPES`` + ``_make_combo_filter``, appended in
``build_default_variations()``):

- Variation filter admittance (Req 5.3): each combination variation admits only
  its own two ``COMBO_*`` ``SignalType`` members and excludes every other type,
  including the DSS-only (``DSS_BULLISH`` / ``DSS_BEARISH``), the price-vs-SMA
  baseline (``PRICE_ABOVE_SMA`` / ``PRICE_BELOW_SMA``), and the other
  combinations' types.
- Combination run (Req 5.4, 5.5): a mixed signal log + price series run through
  ``run_variation`` invokes the engine once via its public API, prices only that
  combination's entries, and populates the full ``MetricsResult`` suite.
- Zero matches (Req 5.6): a log with no entries for a combination completes
  without error, with ``number_of_trades == 0`` and every trade-derived metric
  ``0.0``.
- Failure isolation (Req 5.7): a deliberately failing variation in a batch is
  recorded as a ``VariationFailure(name, error)`` while the other variations
  still run.
- Comparability (Req 5.3): ``build_default_variations()`` carries the five
  ``Combo_*`` names alongside ``DSS_Bressert_Only`` so combined vs individual
  can be compared in a single batch.

Code under test: ``vpa/backtesting/variations.py``.

Fixtures mirror the SP-325 / SP-333 patterns in ``test_variations.py``:
sequential ascending ISO dates so date-sort order matches positional order, and
``SignalEntry`` directions taken from ``SIGNAL_DIRECTIONS``.

Requirements: 5.3, 5.4, 5.5, 5.6, 5.7
"""

import datetime as dt

import pytest

from vpa.backtesting.models import (
    MetricsResult,
    PricePoint,
    SignalEntry,
)
from vpa.backtesting.variations import (
    _COMBO_FILTER_TYPES,
    StrategyVariation,
    VariationFailure,
    VariationRun,
    build_default_variations,
    run_variation,
    run_variations,
)
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalType,
)

_BASE_DATE = dt.date(2020, 1, 1)

# The five combination variation names added in task 8.1.
_COMBO_NAMES = tuple(_COMBO_FILTER_TYPES)

# Baseline / individual-signal types a combination variation must always exclude.
_NON_COMBO_TYPES = frozenset(
    {
        SignalType.DSS_BULLISH,
        SignalType.DSS_BEARISH,
        SignalType.PRICE_ABOVE_SMA,
        SignalType.PRICE_BELOW_SMA,
    }
)

# Every attribute of the full MetricsResult suite (Req 5.5). ``number_of_trades``
# is an int; the rest are floats (profit_factor may be inf).
_METRICS_SUITE_ATTRS = (
    "total_return",
    "annualised_return",
    "buy_and_hold_return",
    "sharpe_ratio",
    "max_drawdown",
    "win_rate",
    "profit_factor",
    "average_win",
    "average_loss",
    "expectancy",
    "time_in_market",
    "number_of_trades",
    "trades_per_year",
)

# Trade-derived metrics that must all be 0.0 on a zero-match run (Req 5.6).
_ZERO_MATCH_METRICS_ATTRS = (
    "total_return",
    "annualised_return",
    "sharpe_ratio",
    "max_drawdown",
    "win_rate",
    "profit_factor",
    "average_win",
    "average_loss",
    "expectancy",
    "time_in_market",
    "trades_per_year",
)


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
# Variation filter admittance (Req 5.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("combo_name", _COMBO_NAMES)
def test_combo_variation_filter_admits_only_its_two_members(combo_name: str) -> None:
    """Each Combo_* variation admits only its own two COMBO_* members (Req 5.3).

    Every other SignalType — the DSS-only and price-vs-SMA baseline types, and
    the other combinations' types — is excluded.
    """
    variation = _variation_by_name(combo_name)
    allowed = _COMBO_FILTER_TYPES[combo_name]

    # Exactly its own two members are admitted; every other enum member excluded.
    for signal_type in SignalType:
        entry = _signal(_iso(1), signal_type)
        expected = signal_type in allowed
        assert variation.signal_filter(entry) is expected


@pytest.mark.parametrize("combo_name", _COMBO_NAMES)
def test_combo_variation_filter_excludes_baseline_and_dss_types(combo_name: str) -> None:
    """A Combo_* filter rejects the DSS-only and SMA baseline types explicitly (Req 5.3)."""
    variation = _variation_by_name(combo_name)
    for baseline_type in _NON_COMBO_TYPES:
        assert variation.signal_filter(_signal(_iso(1), baseline_type)) is False


def test_combo_variation_filters_exclude_each_others_types() -> None:
    """No combination admits another combination's COMBO_* members (Req 5.3)."""
    for combo_name in _COMBO_NAMES:
        variation = _variation_by_name(combo_name)
        own = _COMBO_FILTER_TYPES[combo_name]
        others = {t for name, types in _COMBO_FILTER_TYPES.items() if name != combo_name for t in types}
        # Any other combination's type that is not shared with this one is rejected.
        for other_type in others - own:
            assert variation.signal_filter(_signal(_iso(1), other_type)) is False


# ---------------------------------------------------------------------------
# Combination run through the engine + full metrics suite (Req 5.4, 5.5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("combo_name", _COMBO_NAMES)
def test_combo_variation_runs_through_engine_and_prices_only_its_entries(combo_name: str) -> None:
    """A combination run prices only its own entries and fills the metrics suite (Req 5.4, 5.5).

    A mixed signal log (two of the combination's COMBO_* entries plus several
    other-type entries) is run via ``run_variation``, which drives the engine
    through its public ``BacktestEngine().run(...)`` interface exactly once. Only
    the combination's own entries are priced, and the full MetricsResult suite is
    populated.
    """
    variation = _variation_by_name(combo_name)
    bull_type, bear_type = sorted(_COMBO_FILTER_TYPES[combo_name], key=lambda t: t.value)
    prices = _make_price_series([100.0 + (index % 4) for index in range(30)])

    # Two of the combination's own entries, interleaved with other-type entries
    # (DSS-only, price-vs-SMA baseline) the filter must drop.
    signal_log = [
        _signal(_iso(0), bull_type),
        _signal(_iso(2), SignalType.DSS_BULLISH),
        _signal(_iso(5), SignalType.PRICE_ABOVE_SMA),
        _signal(_iso(15), bear_type),
        _signal(_iso(18), SignalType.PRICE_BELOW_SMA),
    ]

    run = run_variation(variation, signal_log, prices)

    assert isinstance(run, VariationRun)
    assert run.variation is variation

    # Engine (invoked once via run_variation -> BacktestEngine().run) priced only
    # the combination's own two entries; no other-type entry became a trade.
    assert len(run.result.trades) == 2
    assert run.metrics.number_of_trades == 2
    priced_types = {priced.trade.signal_type for priced in run.priced_trades}
    assert priced_types <= _COMBO_FILTER_TYPES[combo_name]
    assert priced_types == {bull_type, bear_type}

    # The full MetricsResult suite is populated (every attribute present/non-None).
    assert isinstance(run.metrics, MetricsResult)
    for attr in _METRICS_SUITE_ATTRS:
        assert getattr(run.metrics, attr) is not None
    assert isinstance(run.metrics.number_of_trades, int)

    # Equity curve carries one point per price-series date.
    assert len(run.equity_curve) == len(prices)


# ---------------------------------------------------------------------------
# Zero matches (Req 5.6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("combo_name", _COMBO_NAMES)
def test_combo_variation_zero_matches_yields_empty_metrics(combo_name: str) -> None:
    """A combination with no matching entries completes with all-zero metrics (Req 5.6)."""
    variation = _variation_by_name(combo_name)
    prices = _make_price_series([100.0 + (index % 3) for index in range(30)])

    # Only other-type entries -> the combination filter matches nothing.
    signal_log = [
        _signal(_iso(0), SignalType.DSS_BULLISH),
        _signal(_iso(5), SignalType.PRICE_ABOVE_SMA),
        _signal(_iso(10), SignalType.DSS_BEARISH),
    ]

    run = run_variation(variation, signal_log, prices)

    assert run.result.trades == []
    assert run.priced_trades == []
    assert run.metrics.number_of_trades == 0
    for attr in _ZERO_MATCH_METRICS_ATTRS:
        assert getattr(run.metrics, attr) == 0.0


# ---------------------------------------------------------------------------
# Failure isolation (Req 5.7)
# ---------------------------------------------------------------------------


def test_combo_variation_failure_isolated_in_batch() -> None:
    """A failing variation is isolated; the Combo_* variations still run (Req 5.7)."""
    prices = _make_price_series([100.0 + (index % 4) for index in range(30)])
    combo_name = _COMBO_NAMES[0]
    bull_type, bear_type = sorted(_COMBO_FILTER_TYPES[combo_name], key=lambda t: t.value)
    signal_log = [
        _signal(_iso(0), bull_type),
        _signal(_iso(15), bear_type),
    ]

    good = _variation_by_name(combo_name)
    # hold_period=0 is rejected by validate_hold_period before the engine runs.
    bad = StrategyVariation(name="Bad_Hold", signal_filter=lambda _entry: True, hold_period=0)

    runs, failures = run_variations([good, bad], signal_log, prices)

    assert [r.variation.name for r in runs] == [combo_name]
    assert runs[0].metrics.number_of_trades == 2
    assert len(failures) == 1
    assert isinstance(failures[0], VariationFailure)
    assert failures[0].name == "Bad_Hold"
    assert failures[0].error  # a non-empty descriptive error message


def test_combo_variation_failure_does_not_stop_other_combos() -> None:
    """A failure between two Combo_* variations does not stop the rest (Req 5.7)."""
    prices = _make_price_series([100.0 + (index % 4) for index in range(30)])
    first_name, last_name = _COMBO_NAMES[0], _COMBO_NAMES[1]

    first = _variation_by_name(first_name)
    broken = StrategyVariation(name="Broken", signal_filter=lambda _e: True, hold_period=-5)
    last = _variation_by_name(last_name)

    runs, failures = run_variations([first, broken, last], [], prices)

    assert [r.variation.name for r in runs] == [first_name, last_name]
    assert [f.name for f in failures] == ["Broken"]


# ---------------------------------------------------------------------------
# Comparability: combined vs individual in one batch (Req 5.3)
# ---------------------------------------------------------------------------


def test_default_catalogue_has_all_combos_alongside_dss_bressert() -> None:
    """build_default_variations carries the five Combo_* names with DSS_Bressert_Only (Req 5.3)."""
    names = [v.name for v in build_default_variations()]
    for combo_name in _COMBO_NAMES:
        assert combo_name in names
    assert "DSS_Bressert_Only" in names


def test_combined_and_individual_variations_run_in_one_batch() -> None:
    """The five Combo_* and DSS_Bressert_Only variations run together for comparison (Req 5.3)."""
    prices = _make_price_series([100.0 + (index % 4) for index in range(30)])
    combo_name = _COMBO_NAMES[0]
    bull_type, bear_type = sorted(_COMBO_FILTER_TYPES[combo_name], key=lambda t: t.value)
    signal_log = [
        _signal(_iso(0), bull_type),
        _signal(_iso(5), SignalType.DSS_BULLISH),
        _signal(_iso(15), bear_type),
        _signal(_iso(20), SignalType.DSS_BEARISH),
    ]

    batch = [_variation_by_name(name) for name in (*_COMBO_NAMES, "DSS_Bressert_Only")]
    runs, failures = run_variations(batch, signal_log, prices)

    assert failures == []
    run_by_name = {r.variation.name: r for r in runs}
    assert set(run_by_name) == {*_COMBO_NAMES, "DSS_Bressert_Only"}

    # The exercised combination priced its own two entries; DSS_Bressert_Only
    # priced only its own DSS entries (and no COMBO_* entries) — comparable in
    # the same batch via one shared metrics pipeline.
    assert run_by_name[combo_name].metrics.number_of_trades == 2
    dss_run = run_by_name["DSS_Bressert_Only"]
    assert dss_run.metrics.number_of_trades >= 1
    assert all(
        priced.trade.signal_type in {SignalType.DSS_BULLISH, SignalType.DSS_BEARISH} for priced in dss_run.priced_trades
    )
