"""Tests for pure CSV/stdout rendering helpers (SP-333).

Covers Correctness Property 15 (Per-trade CSV ordering) via a Hypothesis
property test.

Code under test: ``vpa/backtesting/reporting.py``.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from vpa.backtesting.models import (
    BacktestResult,
    MetricsResult,
    PricedTrade,
    TradeRecord,
)
from vpa.backtesting.reporting import PER_TRADE_HEADER, per_trade_rows, select_best
from vpa.backtesting.variations import StrategyVariation, VariationRun
from vpa.ml_validation.signal_analysis import SIGNAL_DIRECTIONS, SignalDirection, SignalType

# A signal_type/direction pair drawn from the known direction map so the
# rendered row's signal_type and direction names are always well defined.
_SIGNAL_CHOICES: list[tuple[SignalType, SignalDirection]] = list(SIGNAL_DIRECTIONS.items())


def _positional_date(index: int) -> str:
    """Zero-padded positional date string so lexical order == chronological order."""
    return f"{index:08d}"


def _no_op_filter(_entry: object) -> bool:
    """Trivial signal filter for the placeholder ``StrategyVariation``."""
    return True


def _empty_metrics() -> MetricsResult:
    """A minimal all-zero ``MetricsResult`` for the placeholder ``VariationRun``.

    ``per_trade_rows`` only reads ``run.priced_trades``; the metrics are never
    inspected, so a trivial zero-valued result keeps construction minimal.
    """
    return MetricsResult(
        total_return=0.0,
        annualised_return=0.0,
        buy_and_hold_return=0.0,
        sharpe_ratio=0.0,
        max_drawdown=0.0,
        win_rate=0.0,
        profit_factor=0.0,
        average_win=0.0,
        average_loss=0.0,
        expectancy=0.0,
        time_in_market=0.0,
        number_of_trades=0,
        trades_per_year=0.0,
    )


def _make_variation_run(priced_trades: list[PricedTrade]) -> VariationRun:
    """Build a ``VariationRun`` carrying ``priced_trades`` in the given order.

    All other fields are minimal placeholders since ``per_trade_rows`` reads
    only ``run.priced_trades``.
    """
    variation = StrategyVariation(name="Test_Variation", signal_filter=_no_op_filter)
    result = BacktestResult(trades=[p.trade for p in priced_trades], skipped=[])
    return VariationRun(
        variation=variation,
        result=result,
        priced_trades=priced_trades,
        exclusions=[],
        equity_curve=[],
        metrics=_empty_metrics(),
    )


# A single generated trade: (entry_index, exit_index, entry_price, exit_price,
# signal_choice_index, strategy_return). entry_index <= exit_index keeps dates
# realistic, though ``per_trade_rows`` sorts purely on the (entry, exit) pair.
_trade_strategy = st.tuples(
    st.integers(min_value=0, max_value=40),
    st.integers(min_value=0, max_value=40),
    st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    st.integers(min_value=0, max_value=len(_SIGNAL_CHOICES) - 1),
    st.floats(min_value=-0.99, max_value=5.0, allow_nan=False, allow_infinity=False),
)


def _make_priced_trade(spec: tuple[int, int, float, float, int, float]) -> PricedTrade:
    """Turn a generated spec tuple into a ``PricedTrade``."""
    entry_index, exit_index, entry_price, exit_price, choice_index, strategy_ret = spec
    lo, hi = sorted((entry_index, exit_index))
    signal_type, direction = _SIGNAL_CHOICES[choice_index]
    trade = TradeRecord(
        entry_date=_positional_date(lo),
        exit_date=_positional_date(hi),
        entry_price=entry_price,
        exit_price=exit_price,
        return_pct=strategy_ret,
        signal_type=signal_type,
    )
    return PricedTrade(trade=trade, direction=direction, strategy_return=strategy_ret)


# Feature: vpa-strategy-backtest-report, Property 15: Per-trade CSV ordering
@settings(max_examples=100)
@given(trade_specs=st.lists(_trade_strategy, max_size=30))
def test_property_15_per_trade_csv_ordering(
    trade_specs: list[tuple[int, int, float, float, int, float]],
) -> None:
    """Per-trade CSV rows are ordered by (entry_date, exit_date) with fixed columns.

    Validates: Requirements 16.2, 16.3.

    Priced trades are supplied to the ``VariationRun`` in arbitrary (unsorted)
    order. ``per_trade_rows`` must emit the fixed seven-column header, order the
    data rows by ``entry_date`` ascending then ``exit_date`` ascending, and give
    every row exactly the seven columns in the documented order.
    """
    priced_trades = [_make_priced_trade(spec) for spec in trade_specs]
    run = _make_variation_run(priced_trades)

    rows = per_trade_rows(run)

    # Req 16.2: the first row is the header with exactly the seven columns in order.
    assert rows[0] == PER_TRADE_HEADER
    assert PER_TRADE_HEADER == [
        "entry_date",
        "exit_date",
        "entry_price",
        "exit_price",
        "signal_type",
        "signal_direction",
        "strategy_return",
    ]

    data_rows = rows[1:]

    # Exactly one data row per priced trade.
    assert len(data_rows) == len(priced_trades)

    # Req 16.3: every row (header + data) has exactly seven columns.
    for row in rows:
        assert len(row) == len(PER_TRADE_HEADER) == 7

    # Req 16.2: data rows are non-decreasing by (entry_date, exit_date).
    order_keys = [(row[0], row[1]) for row in data_rows]
    assert order_keys == sorted(order_keys)

    # The rendered rows correspond to the input trades sorted by (entry, exit):
    # compare against an independently sorted reference of the priced trades.
    expected_sorted = sorted(
        priced_trades,
        key=lambda p: (p.trade.entry_date, p.trade.exit_date),
    )
    expected_rows = [
        [
            p.trade.entry_date,
            p.trade.exit_date,
            str(p.trade.entry_price),
            str(p.trade.exit_price),
            p.trade.signal_type.name,
            p.direction.name,
            str(p.strategy_return),
        ]
        for p in expected_sorted
    ]
    assert data_rows == expected_rows


# ---------------------------------------------------------------------------
# Property 16: Best-variation selection and tie-break ordering (Req 20.1, 20.2)
# ---------------------------------------------------------------------------


def _make_metrics(sharpe_ratio: float, total_return: float) -> MetricsResult:
    """A ``MetricsResult`` with only ``sharpe_ratio`` and ``total_return`` set.

    ``select_best`` inspects only ``metrics.sharpe_ratio`` and
    ``metrics.total_return``; every other field is irrelevant to the selection,
    so they are held at 0.0 to keep construction minimal.
    """
    return MetricsResult(
        total_return=total_return,
        annualised_return=0.0,
        buy_and_hold_return=0.0,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=0.0,
        win_rate=0.0,
        profit_factor=0.0,
        average_win=0.0,
        average_loss=0.0,
        expectancy=0.0,
        time_in_market=0.0,
        number_of_trades=0,
        trades_per_year=0.0,
    )


def _make_scored_run(name: str, sharpe_ratio: float, total_return: float) -> VariationRun:
    """Build a ``VariationRun`` carrying the given name and selection metrics.

    Reuses the ``_no_op_filter`` placeholder and an empty ``BacktestResult`` /
    priced-trade / equity-curve set since ``select_best`` reads only the
    variation name and the two metric fields.
    """
    variation = StrategyVariation(name=name, signal_filter=_no_op_filter)
    result = BacktestResult(trades=[], skipped=[])
    return VariationRun(
        variation=variation,
        result=result,
        priced_trades=[],
        exclusions=[],
        equity_curve=[],
        metrics=_make_metrics(sharpe_ratio, total_return),
    )


# A single generated run spec: (name_index, sharpe_pool_index, total_pool_index).
# Names are made unique via the enumeration index at build time so the
# ascending-name tie-break is deterministic. Sharpe and Total_Return are drawn
# from small pools so ties (and Sharpe+Total ties) occur frequently, exercising
# every tie-break level.
_SHARPE_POOL = (-1.5, 0.0, 0.5, 0.5, 1.0, 2.0)
_TOTAL_POOL = (-0.2, 0.0, 0.1, 0.1, 0.3)

_run_spec = st.tuples(
    st.integers(min_value=0, max_value=25),
    st.integers(min_value=0, max_value=len(_SHARPE_POOL) - 1),
    st.integers(min_value=0, max_value=len(_TOTAL_POOL) - 1),
)


# Feature: vpa-strategy-backtest-report, Property 16: Best-variation selection and tie-break ordering
@settings(max_examples=100)
@given(specs=st.lists(_run_spec, max_size=20))
def test_property_16_best_variation_selection(
    specs: list[tuple[int, int, int]],
) -> None:
    """``select_best`` picks highest Sharpe with the documented tie-breaks.

    Validates: Requirements 20.1, 20.2.

    The best run has the highest ``metrics.sharpe_ratio``; ties on Sharpe are
    broken by the highest ``metrics.total_return``, and any remaining ties by
    ascending ``variation.name``. An empty list yields ``None``. Names are made
    unique (via the enumeration index) so the final name tie-break is
    unambiguous, while Sharpe and Total_Return are drawn from small pools so
    ties at every level are exercised.
    """
    # select_best([]) is None (Req 20.1).
    assert select_best([]) is None

    runs = [
        _make_scored_run(
            name=f"var_{name_index:03d}_{position:03d}",
            sharpe_ratio=_SHARPE_POOL[sharpe_index],
            total_return=_TOTAL_POOL[total_index],
        )
        for position, (name_index, sharpe_index, total_index) in enumerate(specs)
    ]

    best = select_best(runs)

    if not runs:
        assert best is None
        return

    # Independent reference: sort by (Sharpe desc, Total_Return desc, name asc)
    # and take the first. Negating the numeric keys gives descending order while
    # the name sorts ascending as-is.
    expected = min(
        runs,
        key=lambda run: (
            -run.metrics.sharpe_ratio,
            -run.metrics.total_return,
            run.variation.name,
        ),
    )

    assert best is not None
    assert best.variation.name == expected.variation.name
    assert best.metrics.sharpe_ratio == expected.metrics.sharpe_ratio
    assert best.metrics.total_return == expected.metrics.total_return

    # The selected run's key must dominate every other run's key under the
    # documented ordering (Sharpe, then Total_Return, then ascending name).
    for run in runs:
        best_key = (best.metrics.sharpe_ratio, best.metrics.total_return)
        run_key = (run.metrics.sharpe_ratio, run.metrics.total_return)
        if run_key == best_key:
            # Tied on both numeric keys: best must have the lexicographically
            # smallest name among the tied group.
            assert best.variation.name <= run.variation.name
        else:
            assert best_key > run_key


# ---------------------------------------------------------------------------
# Example tests: CSV row builders, filenames, summary, comparison table, and
# the tradeability verdict (Req 16.1, 16.4, 17.1, 17.4, 18.1, 18.3, 18.4,
# 19.1, 19.3, 19.5, 20.3, 20.4).
#
# These are explicit example tests (not property tests) that build small,
# hand-constructed VariationRun / VariationFailure objects and assert the exact
# rendered output. They reuse the helpers defined above: _make_variation_run,
# _make_scored_run, _empty_metrics, _positional_date, and _no_op_filter.
# ---------------------------------------------------------------------------

from vpa.backtesting.models import EquityPoint  # noqa: E402
from vpa.backtesting.reporting import (  # noqa: E402
    EQUITY_HEADER,
    equity_rows,
    format_comparison_table,
    format_summary,
    format_tradeability_conclusion,
    variation_filename,
)
from vpa.backtesting.variations import VariationFailure  # noqa: E402


def _make_priced_trade_explicit(
    entry_index: int,
    exit_index: int,
    entry_price: float,
    exit_price: float,
    signal_type: SignalType,
    direction: SignalDirection,
    strategy_return: float,
) -> PricedTrade:
    """Build one explicit ``PricedTrade`` with positional ISO-like dates."""
    trade = TradeRecord(
        entry_date=_positional_date(entry_index),
        exit_date=_positional_date(exit_index),
        entry_price=entry_price,
        exit_price=exit_price,
        return_pct=strategy_return,
        signal_type=signal_type,
    )
    return PricedTrade(trade=trade, direction=direction, strategy_return=strategy_return)


# --- Req 16.4: header-only per-trade CSV for zero trades --------------------


def test_per_trade_rows_header_only_for_zero_trades() -> None:
    """A variation with no trades yields the header row only (Req 16.4)."""
    run = _make_variation_run([])

    rows = per_trade_rows(run)

    assert rows == [PER_TRADE_HEADER]
    assert len(rows) == 1


# --- Req 17.4: header-only equity CSV for an empty equity curve -------------


def test_equity_rows_header_only_for_empty_curve() -> None:
    """An empty equity curve yields the equity header row only (Req 17.4)."""
    rows = equity_rows([])

    assert rows == [EQUITY_HEADER]
    assert EQUITY_HEADER == ["date", "equity"]
    assert len(rows) == 1


def test_equity_rows_emits_one_ascending_row_per_point() -> None:
    """A populated equity curve emits header + one date-ascending row per point (Req 17.1)."""
    # Supplied out of order to confirm equity_rows sorts by date ascending.
    curve = [
        EquityPoint(date=_positional_date(2), equity=1.05),
        EquityPoint(date=_positional_date(0), equity=1.0),
        EquityPoint(date=_positional_date(1), equity=0.98),
    ]

    rows = equity_rows(curve)

    assert rows[0] == EQUITY_HEADER
    assert rows[1:] == [
        [_positional_date(0), str(1.0)],
        [_positional_date(1), str(0.98)],
        [_positional_date(2), str(1.05)],
    ]


# --- Req 16.1: unique filenames from variation_filename ---------------------


def test_variation_filename_unique_across_kind_and_name() -> None:
    """Filenames are unique per (name, kind); trades vs equity and two names differ (Req 16.1)."""
    baseline_trades = variation_filename("Baseline", "trades")
    baseline_equity = variation_filename("Baseline", "equity")
    contrarian_trades = variation_filename("Contrarian_Only", "trades")

    # trades vs equity for the same variation differ.
    assert baseline_trades != baseline_equity
    assert baseline_trades == "baseline_trades.csv"
    assert baseline_equity == "baseline_equity.csv"

    # Two different variation names produce different filenames.
    assert baseline_trades != contrarian_trades
    assert contrarian_trades == "contrarian_only_trades.csv"

    # All four filenames across two variations x two kinds are unique.
    names = {
        variation_filename("Baseline", "trades"),
        variation_filename("Baseline", "equity"),
        variation_filename("Contrarian_Only", "trades"),
        variation_filename("Contrarian_Only", "equity"),
    }
    assert len(names) == 4


# --- Req 18.1, 18.3, 18.4: format_summary content ---------------------------


def test_format_summary_zero_trades_lists_name_and_all_metric_labels() -> None:
    """Summary names the variation, reports 0 trades, and includes every metric label (Req 18.1, 18.3, 18.4)."""
    run = _make_variation_run([])  # _empty_metrics -> number_of_trades == 0

    summary = format_summary(run)

    # Req 18.1: the variation name appears.
    assert "Strategy_Variation: Test_Variation" in summary
    # Req 18.4: number of trades is 0 for the empty variation.
    assert "Number_Of_Trades: 0" in summary

    # Req 18.3: each metric label is present on its own line.
    for label in (
        "Total_Return",
        "Annualised_Return",
        "Sharpe_Ratio",
        "Max_Drawdown",
        "Win_Rate",
        "Profit_Factor",
        "Average_Win",
        "Average_Loss",
        "Expectancy",
        "Time_In_Market",
        "Trades_Per_Year",
    ):
        assert f"{label}:" in summary


def test_format_summary_reports_non_zero_trade_count() -> None:
    """When the run has trades, the number-of-trades line reflects the count (Req 18.3)."""
    priced = _make_priced_trade_explicit(0, 1, 100.0, 110.0, SignalType.STRONG_BULLISH, SignalDirection.UP, 0.1)
    variation = StrategyVariation(name="Has_Trades", signal_filter=_no_op_filter)
    result = BacktestResult(trades=[priced.trade], skipped=[])
    metrics = MetricsResult(
        total_return=0.1,
        annualised_return=0.05,
        buy_and_hold_return=0.02,
        sharpe_ratio=1.2,
        max_drawdown=-0.03,
        win_rate=1.0,
        profit_factor=float("inf"),
        average_win=0.1,
        average_loss=0.0,
        expectancy=0.1,
        time_in_market=0.5,
        number_of_trades=1,
        trades_per_year=12.0,
    )
    run = VariationRun(
        variation=variation,
        result=result,
        priced_trades=[priced],
        exclusions=[],
        equity_curve=[],
        metrics=metrics,
    )

    summary = format_summary(run)

    assert "Strategy_Variation: Has_Trades" in summary
    assert "Number_Of_Trades: 1" in summary
    # Infinite profit factor renders as a readable "inf" (Req 15.2 rendering).
    assert "Profit_Factor: inf" in summary


# --- Req 19.1, 19.3, 19.5: format_comparison_table --------------------------


def test_format_comparison_table_row_per_run_plus_buy_and_hold() -> None:
    """One row per completed variation plus a Buy_And_Hold_SPY row (Req 19.1, 19.3)."""
    run_a = _make_scored_run("Baseline", sharpe_ratio=1.0, total_return=0.2)
    run_b = _make_scored_run("Contrarian_Only", sharpe_ratio=0.5, total_return=0.1)

    table = format_comparison_table([run_a, run_b], failures=[], buy_and_hold=0.15, bnh_annualised=0.07)

    # Header columns present (Req 19.2).
    assert "Total_Return" in table
    assert "Annualised_Return" in table
    assert "Sharpe_Ratio" in table
    assert "Max_Drawdown" in table

    # One row per completed variation (Req 19.1).
    assert "Baseline" in table
    assert "Contrarian_Only" in table

    # Buy-and-hold SPY row present (Req 19.3).
    assert "Buy_And_Hold_SPY" in table


def test_format_comparison_table_names_failed_variation() -> None:
    """A failed variation is named below the table so it is not silently omitted (Req 19.5)."""
    run_a = _make_scored_run("Baseline", sharpe_ratio=1.0, total_return=0.2)
    failure = VariationFailure(name="Stop_Loss_-2pct", error="hold_period must be a positive integer (>= 1), got 0")

    table = format_comparison_table([run_a], failures=[failure], buy_and_hold=0.1, bnh_annualised=0.05)

    # The completed run and buy-and-hold appear as rows.
    assert "Baseline" in table
    assert "Buy_And_Hold_SPY" in table

    # The failed variation is named (Req 19.5) and its metrics are omitted from
    # the data rows (it has no comparison row of its own).
    assert "Stop_Loss_-2pct" in table
    assert "Failed_Variation: Stop_Loss_-2pct" in table

    # The failed variation is not rendered as a metrics comparison row: it only
    # appears in the trailing "Failed_Variation" annotation, so its name occurs
    # exactly once in the whole table.
    assert table.count("Stop_Loss_-2pct") == 1


# --- Req 20.3, 20.4: format_tradeability_conclusion -------------------------


def test_format_tradeability_conclusion_beats_buy_and_hold() -> None:
    """Names the best variation and states strictly-greater-than buy-and-hold (Req 20.3)."""
    best = _make_scored_run("Baseline", sharpe_ratio=1.5, total_return=0.30)
    other = _make_scored_run("Contrarian_Only", sharpe_ratio=0.5, total_return=0.05)

    verdict = format_tradeability_conclusion([best, other], buy_and_hold=0.20)

    # Names the best variation (highest Sharpe).
    assert "Baseline" in verdict
    # States it is strictly greater than buy-and-hold (Req 20.3).
    assert "strictly greater than" in verdict
    # Should NOT declare the edges untradeable, since Baseline beats buy-and-hold.
    assert "not tradeable after costs" not in verdict


def test_format_tradeability_conclusion_not_tradeable_when_none_beat_bnh() -> None:
    """When no run beats buy-and-hold, states edges are not tradeable after costs (Req 20.4)."""
    run_a = _make_scored_run("Baseline", sharpe_ratio=1.5, total_return=0.10)
    run_b = _make_scored_run("Contrarian_Only", sharpe_ratio=0.5, total_return=0.05)

    verdict = format_tradeability_conclusion([run_a, run_b], buy_and_hold=0.20)

    # The best variation is still named.
    assert "Baseline" in verdict
    # Best does not strictly beat buy-and-hold.
    assert "not strictly greater than" in verdict
    # Req 20.4: the not-tradeable-after-costs wording is present.
    assert "not tradeable after costs" in verdict


def test_format_tradeability_conclusion_tie_with_buy_and_hold_not_tradeable() -> None:
    """A tie with buy-and-hold is not strictly greater, so edges are not tradeable (Req 20.4)."""
    # Best variation's Total_Return exactly equals buy-and-hold: a tie is not a
    # strict win, so the verdict must fall to the not-tradeable wording.
    best = _make_scored_run("Baseline", sharpe_ratio=1.5, total_return=0.20)
    other = _make_scored_run("Contrarian_Only", sharpe_ratio=0.5, total_return=0.20)

    verdict = format_tradeability_conclusion([best, other], buy_and_hold=0.20)

    assert "Baseline" in verdict
    assert "not strictly greater than" in verdict
    assert "not tradeable after costs" in verdict
