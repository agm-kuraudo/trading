"""Harness and end-to-end pipeline tests for the recent-extreme sweep (SP-354 task 11).

These tests exercise the variation harness and the pure reporting layer
end-to-end, driving the real ``run_variations`` -> ``reporting`` pipeline over a
deterministic Price_Series and Signal_Log that includes both long and short
recent-extreme variations alongside the pre-existing variations:

- Task 11.1 (Req 12.1, 12.2): a deliberately failing variation in a batch is
  recorded as a ``VariationFailure(name, error)`` while the others -- including
  a recent-extreme and a normal variation -- still complete with metrics,
  mirroring the existing failure-isolation tests in
  ``test_combined_variations.py``.
- Task 11.2 (Req 10.2, 12.2): a representative subset of the default catalogue
  (including recent-extreme variations) is run through ``run_variations``;
  recent-extreme variations produce ``VariationRun``s with metrics, and
  ``reporting.per_trade_rows`` / ``reporting.equity_rows`` yield well-formed
  rows (ten-column per-trade header + data, two-column equity). The pure
  ``reporting.format_comparison_table`` table contains both a pre-existing name
  (``Baseline``) and at least one ``Recent_Extreme_`` row, with buy-and-hold /
  annualised computed via ``metrics`` exactly as ``report_backtest.main`` does.
- Task 11.3 (Req 12.4; design Property 11): a fixed-hold and a percentage-stop
  variation run through the full pipeline; every resulting ``TradeRecord`` has
  ``stop_loss`` / ``profit_target`` / ``exit_reason`` == ``None`` and
  ``per_trade_rows`` renders the three appended columns as empty strings while
  the original seven columns stay intact.

Code under test:
- ``vpa/backtesting/variations.py`` (``run_variations``, ``build_default_variations``)
- ``vpa/backtesting/reporting.py`` (``per_trade_rows``, ``equity_rows``, ``format_comparison_table``)
- ``vpa/backtesting/metrics.py`` (``buy_and_hold_return``, ``annualised_return``)

Fixtures follow the SP-317 / SP-333 patterns in ``test_variations.py`` and
``test_combined_variations.py``: sequential ascending ISO dates so date-sort
order matches positional order, and ``SignalEntry`` directions taken from
``SIGNAL_DIRECTIONS``.

Requirements: 10.2, 12.1, 12.2, 12.4
"""

import datetime as dt

from vpa.backtesting import metrics
from vpa.backtesting.exit_strategy import FixedHoldExitStrategy, StopLossExitStrategy
from vpa.backtesting.models import (
    PricePoint,
    SignalEntry,
)
from vpa.backtesting.reporting import (
    EQUITY_HEADER,
    PER_TRADE_HEADER,
    equity_rows,
    format_comparison_table,
    per_trade_rows,
)
from vpa.backtesting.variations import (
    StrategyVariation,
    VariationFailure,
    VariationRun,
    build_default_variations,
    run_variations,
)
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalType,
)

_BASE_DATE = dt.date(2020, 1, 1)

# A long (UP) and a short (DOWN) signal type, so the long recent-extreme
# variations (_include_long) and short recent-extreme variations
# (_include_short) each have signals to trade.
_LONG_SIGNAL = SignalType.STRONG_BULLISH
_SHORT_SIGNAL = SignalType.STRONG_BEARISH


def _iso(index: int) -> str:
    """Return a unique ascending ISO date string for positional ``index``."""
    return (_BASE_DATE + dt.timedelta(days=index)).isoformat()


def _signal(date: str, signal_type: SignalType) -> SignalEntry:
    """Build a SignalEntry using SIGNAL_DIRECTIONS for the direction."""
    return SignalEntry(
        date=date,
        signal_type=signal_type,
        direction=SIGNAL_DIRECTIONS[signal_type],
    )


def _make_oscillating_series(length: int) -> list[PricePoint]:
    """Build a deterministic ascending-date OHLC series that oscillates.

    The close traces a gentle saw-tooth around a rising baseline so that:

    * every bar has a real high/low band (``high = close + 2``,
      ``low = close - 2``), giving the lookback windows (5 and 10) genuine
      extremes strictly below/above the entry price; and
    * prices both rise and fall across the span, so recent-extreme stops sit
      adverse to entry (non-degenerate risk) for longs *and* shorts, and the
      forward scan reaches stops, targets, and fixed-hold fallbacks across the
      twelve-variation sweep.

    The series is fully deterministic (a closed-form function of the index), so
    the pipeline output is reproducible.
    """
    series: list[PricePoint] = []
    for i in range(length):
        # Rising baseline plus a bounded oscillation; closed-form & deterministic.
        baseline = 100.0 + i * 0.5
        wobble = 6.0 * ((i % 6) - 3) / 3.0  # cycles through [-6, +4] each 6 bars
        close = baseline + wobble
        series.append(
            PricePoint(
                date=_iso(i),
                open=close,
                high=close + 2.0,
                low=max(close - 2.0, 0.01),
                close=close,
            )
        )
    return series


def _make_signal_log(length: int) -> list[SignalEntry]:
    """Build a mixed long/short signal log with entries past the lookback window.

    Signals are placed on date indices well beyond 10 so that for both the
    ``lookback=5`` and ``lookback=10`` variations the window
    ``price_series[entry_index - L : entry_index]`` (``entry_index = t + 1``)
    is always fully populated with prior bars. Both UP (long) and DOWN (short)
    signal types appear, so the long and short recent-extreme variations each
    have signals to trade, and they are spaced apart so NO_OVERLAP admits
    several trades per direction.
    """
    log: list[SignalEntry] = []
    # Space signals every 4 bars starting at index 12, alternating direction.
    for n, t in enumerate(range(12, length - 2, 4)):
        signal_type = _LONG_SIGNAL if n % 2 == 0 else _SHORT_SIGNAL
        log.append(_signal(_iso(t), signal_type))
    return log


def _recent_extreme_names(names: list[str]) -> list[str]:
    """Return the Recent_Extreme_* names present in ``names``."""
    return [name for name in names if name.startswith("Recent_Extreme_")]


# ---------------------------------------------------------------------------
# Task 11.1 -- Failure isolation (Req 12.1, 12.2)
# ---------------------------------------------------------------------------


def test_failing_variation_isolated_recent_extreme_and_normal_still_run() -> None:
    """A failing variation is isolated; a recent-extreme and a normal one still run (Req 12.1, 12.2).

    The batch mixes a deliberately failing variation (``hold_period=0``, which
    ``validate_hold_period`` rejects before the engine runs) with one normal
    variation (``Baseline``) and one recent-extreme variation. ``run_variations``
    records the failing one as a ``VariationFailure(name, error)`` and still
    completes the others, including the recent-extreme variation, which appear
    among the successful runs with a populated ``MetricsResult``. This mirrors
    the existing failure-isolation tests in ``test_combined_variations.py``.
    """
    length = 60
    price_series = _make_oscillating_series(length)
    signal_log = _make_signal_log(length)

    defaults = build_default_variations()
    baseline = next(v for v in defaults if v.name == "Baseline")
    # Pick a concrete recent-extreme (long) variation from the default catalogue.
    recent_extreme = next(v for v in defaults if v.name == "Recent_Extreme_Long_R2_LB5")

    # hold_period=0 is rejected by validate_hold_period before the engine runs,
    # so this variation raises and must surface as a VariationFailure.
    bad = StrategyVariation(name="Bad_Hold", signal_filter=lambda _entry: True, hold_period=0)

    runs, failures = run_variations([baseline, bad, recent_extreme], signal_log, price_series)

    # The failing variation is isolated and named (Req 12.1).
    assert len(failures) == 1
    assert isinstance(failures[0], VariationFailure)
    assert failures[0].name == "Bad_Hold"
    assert failures[0].error  # a non-empty descriptive error message

    # The remaining variations completed, order preserved, failing one dropped.
    run_names = [r.variation.name for r in runs]
    assert run_names == ["Baseline", "Recent_Extreme_Long_R2_LB5"]

    # Each successful run carries a populated metrics suite (Req 12.2).
    for run in runs:
        assert isinstance(run, VariationRun)
        assert run.metrics is not None
        assert isinstance(run.metrics.number_of_trades, int)

    # The recent-extreme variation actually traded on this fixture, proving it
    # completed as a real run alongside the others (not merely a zero-trade run).
    recent_run = next(r for r in runs if r.variation.name == "Recent_Extreme_Long_R2_LB5")
    assert recent_run.metrics.number_of_trades >= 1


def test_failure_between_recent_extreme_variations_does_not_stop_the_rest() -> None:
    """A failure between two recent-extreme variations does not abort the batch (Req 12.1)."""
    length = 60
    price_series = _make_oscillating_series(length)
    signal_log = _make_signal_log(length)

    defaults = build_default_variations()
    first = next(v for v in defaults if v.name == "Recent_Extreme_Long_R1_LB5")
    last = next(v for v in defaults if v.name == "Recent_Extreme_Short_R3_LB10")
    broken = StrategyVariation(name="Broken", signal_filter=lambda _e: True, hold_period=-5)

    runs, failures = run_variations([first, broken, last], signal_log, price_series)

    assert [r.variation.name for r in runs] == [
        "Recent_Extreme_Long_R1_LB5",
        "Recent_Extreme_Short_R3_LB10",
    ]
    assert [f.name for f in failures] == ["Broken"]


# ---------------------------------------------------------------------------
# Task 11.2 -- End-to-end comparison output (Req 10.2, 12.2)
# ---------------------------------------------------------------------------


def test_end_to_end_comparison_includes_recent_extreme_alongside_existing() -> None:
    """The full run_variations -> reporting pipeline includes recent-extreme runs (Req 10.2, 12.2).

    A representative subset of the default catalogue (``Baseline`` plus every
    recent-extreme variation) is run over a deterministic Price_Series and mixed
    long/short Signal_Log. Each recent-extreme variation produces a
    ``VariationRun`` with metrics, and ``per_trade_rows`` / ``equity_rows`` yield
    well-formed rows (ten-column per-trade header + data cells, two-column
    equity). The pure ``format_comparison_table`` string carries both a
    pre-existing name (``Baseline``) and at least one ``Recent_Extreme_`` row,
    proving the comparison spans the new strategy and the existing ones.
    """
    length = 70
    price_series = _make_oscillating_series(length)
    signal_log = _make_signal_log(length)

    defaults = build_default_variations()
    all_names = [v.name for v in defaults]
    recent_names = _recent_extreme_names(all_names)
    assert len(recent_names) == 12  # sanity: the full sweep is present (Req 11.1)

    # Representative subset: Baseline + all twelve recent-extreme variations.
    subset = [v for v in defaults if v.name == "Baseline" or v.name.startswith("Recent_Extreme_")]

    runs, failures = run_variations(subset, signal_log, price_series)

    # Every variation in the subset completed (none raised).
    assert failures == []
    run_by_name = {r.variation.name: r for r in runs}
    assert "Baseline" in run_by_name
    for name in recent_names:
        assert name in run_by_name

    # Recent-extreme variations produced VariationRuns with metrics, and at
    # least one of them traded on this fixture (Req 12.2).
    recent_runs = [run_by_name[name] for name in recent_names]
    for run in recent_runs:
        assert isinstance(run, VariationRun)
        assert run.metrics is not None
        assert isinstance(run.metrics.number_of_trades, int)
        # Equity curve carries one point per Price_Series date.
        assert len(run.equity_curve) == len(price_series)
    assert any(run.metrics.number_of_trades >= 1 for run in recent_runs)

    # per_trade_rows / equity_rows yield well-formed rows for a recent-extreme
    # run (ten-column per-trade header + data, two-column equity).
    traded_run = next(run for run in recent_runs if run.metrics.number_of_trades >= 1)
    pt_rows = per_trade_rows(traded_run)
    assert pt_rows[0] == PER_TRADE_HEADER
    assert len(PER_TRADE_HEADER) == 10  # per-trade header is now ten columns (Req 12.3)
    for row in pt_rows:
        assert len(row) == 10
    assert len(pt_rows) == traded_run.metrics.number_of_trades + 1  # header + one row per trade

    eq_rows = equity_rows(traded_run.equity_curve)
    assert eq_rows[0] == EQUITY_HEADER
    for row in eq_rows:
        assert len(row) == 2
    assert len(eq_rows) == len(price_series) + 1  # header + one row per equity point

    # Buy-and-hold / annualised computed exactly as report_backtest.main does.
    buy_and_hold = metrics.buy_and_hold_return(price_series)
    bnh_annualised = metrics.annualised_return(buy_and_hold, price_series)

    table = format_comparison_table(runs, failures, buy_and_hold, bnh_annualised)

    # The comparison table includes a pre-existing variation and at least one
    # recent-extreme row, proving they are compared together (Req 10.2).
    assert "Baseline" in table
    assert "Recent_Extreme_" in table
    assert "Buy_And_Hold_SPY" in table
    assert any(line.startswith("Recent_Extreme_") for line in table.splitlines())


# ---------------------------------------------------------------------------
# Task 11.3 -- Full-pipeline backward compatibility (Req 12.4; Property 11)
# ---------------------------------------------------------------------------


# Feature: sp-354-recent-extreme-stop-target, Property 11: backward-compatible
# output for non-supplying strategies (fixed-hold / percentage-stop) through the
# full run_variations -> reporting pipeline.
def test_full_pipeline_backward_compatible_for_non_supplying_strategies() -> None:
    """Fixed-hold and percentage-stop variations leave the three extras None/empty (Req 12.4, Property 11).

    Running the full pipeline for a ``FixedHoldExitStrategy`` variation and a
    percentage ``StopLossExitStrategy`` variation, every resulting
    ``TradeRecord`` has ``stop_loss`` / ``profit_target`` / ``exit_reason`` equal
    to ``None`` (neither strategy supplies them), and ``per_trade_rows`` renders
    the three appended columns as empty strings while the original seven columns
    stay intact and populated.
    """
    length = 60
    price_series = _make_oscillating_series(length)
    signal_log = _make_signal_log(length)

    fixed_hold = StrategyVariation(
        name="FixedHold_Compat",
        signal_filter=lambda _entry: True,
        exit_strategy_factory=FixedHoldExitStrategy,
    )
    pct_stop = StrategyVariation(
        name="PctStop_Compat",
        signal_filter=lambda _entry: True,
        exit_strategy_factory=(lambda: StopLossExitStrategy(threshold=-0.02)),
    )

    runs, failures = run_variations([fixed_hold, pct_stop], signal_log, price_series)

    assert failures == []
    assert {r.variation.name for r in runs} == {"FixedHold_Compat", "PctStop_Compat"}

    for run in runs:
        # Both strategies must have produced at least one trade for the
        # assertion to be meaningful on this fixture.
        assert run.metrics.number_of_trades >= 1

        # Every TradeRecord leaves the three SP-354 extras at their None default.
        for priced in run.priced_trades:
            trade = priced.trade
            assert trade.stop_loss is None
            assert trade.profit_target is None
            assert trade.exit_reason is None

        # per_trade_rows renders the three appended columns as empty strings and
        # keeps the original seven columns intact and populated.
        rows = per_trade_rows(run)
        assert rows[0] == PER_TRADE_HEADER
        data_rows = rows[1:]
        assert len(data_rows) == run.metrics.number_of_trades
        for row in data_rows:
            assert len(row) == 10
            # Original seven columns are populated (non-empty).
            for cell in row[:7]:
                assert cell != ""
            # The three appended columns render empty for a non-supplying strategy.
            assert row[7:] == ["", "", ""]
