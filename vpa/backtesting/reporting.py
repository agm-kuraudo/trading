"""Pure rendering helpers for the VPA backtest report (SP-333, Req 16, 17).

This module builds CSV row lists and filesystem-safe filenames from in-memory
variation results. It performs no filesystem writes and no other I/O: every
function returns plain Python data (row lists / strings) that the CLI
(``report_backtest.py``) is responsible for persisting. Keeping rendering pure
preserves the SP-317 determinism guarantee (Req 2).
"""

import re

from vpa.backtesting.models import EquityPoint, MetricsResult
from vpa.backtesting.variations import VariationFailure, VariationRun

PER_TRADE_HEADER = [
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "signal_type",
    "signal_direction",
    "strategy_return",
]
"""Per-trade CSV column order (Req 16.2)."""

EQUITY_HEADER = ["date", "equity"]
"""Equity-curve CSV column order (Req 17.2)."""


def per_trade_rows(run: VariationRun) -> list[list[str]]:
    """Build the per-trade CSV rows for a completed variation (Req 16.2-16.4).

    Returns the header row followed by one row per ``PricedTrade``, ordered by
    ``entry_date`` ascending and then ``exit_date`` ascending. Every row (and
    the header) contains exactly the seven ``PER_TRADE_HEADER`` columns in that
    order. When the variation produced zero trades, only the header row is
    returned (Req 16.4).

    ``signal_type`` and ``signal_direction`` are rendered via their enum
    ``.name``; all numeric columns are stringified so the result is a pure
    ``list[list[str]]``.
    """
    rows: list[list[str]] = [list(PER_TRADE_HEADER)]

    ordered = sorted(
        run.priced_trades,
        key=lambda priced: (priced.trade.entry_date, priced.trade.exit_date),
    )

    for priced in ordered:
        trade = priced.trade
        rows.append(
            [
                trade.entry_date,
                trade.exit_date,
                str(trade.entry_price),
                str(trade.exit_price),
                trade.signal_type.name,
                priced.direction.name,
                str(priced.strategy_return),
            ]
        )

    return rows


def equity_rows(equity_curve: list[EquityPoint]) -> list[list[str]]:
    """Build the equity-curve CSV rows (Req 17).

    Returns the header row followed by one ``(date, equity)`` row per
    ``EquityPoint``, ordered by date ascending. An empty curve yields the
    header row only (Req 17.4). Equity values are stringified so the result is
    a pure ``list[list[str]]``.
    """
    rows: list[list[str]] = [list(EQUITY_HEADER)]

    ordered = sorted(equity_curve, key=lambda point: point.date)

    for point in ordered:
        rows.append([point.date, str(point.equity)])

    return rows


def variation_filename(name: str, kind: str) -> str:
    """Build a unique, filesystem-safe CSV filename for a variation (Req 16.1).

    The variation ``name`` is slugified (lowercased, non-alphanumeric runs
    collapsed to a single underscore, leading/trailing underscores trimmed) and
    combined with ``kind`` to produce names like ``"baseline_trades.csv"`` or
    ``"baseline_equity.csv"``. Because the slug is derived from the (unique)
    variation name and the ``kind`` distinguishes the two files per variation,
    the resulting filenames are unique across a report run.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    kind_slug = re.sub(r"[^a-z0-9]+", "_", kind.lower()).strip("_")
    return f"{slug}_{kind_slug}.csv"


# ---------------------------------------------------------------------------
# Stdout rendering: summary, comparison table, best selection, verdict
# (Req 18, 19, 20). All functions are pure and return strings; the CLI prints
# them.
# ---------------------------------------------------------------------------

# The metric fields of ``MetricsResult`` rendered in the stdout summary, in the
# order they appear, each on its own line (Req 18.1, 18.2). ``number_of_trades``
# is handled separately as the "Number_Of_Trades" line (Req 18.3, 18.4).
_SUMMARY_METRICS: tuple[tuple[str, str], ...] = (
    ("Total_Return", "total_return"),
    ("Annualised_Return", "annualised_return"),
    ("Sharpe_Ratio", "sharpe_ratio"),
    ("Max_Drawdown", "max_drawdown"),
    ("Win_Rate", "win_rate"),
    ("Profit_Factor", "profit_factor"),
    ("Average_Win", "average_win"),
    ("Average_Loss", "average_loss"),
    ("Expectancy", "expectancy"),
    ("Time_In_Market", "time_in_market"),
    ("Trades_Per_Year", "trades_per_year"),
)


def _format_value(value: float) -> str:
    """Render a metric value readably for stdout.

    ``float("inf")`` / ``-inf`` (a legal ``profit_factor`` when there are wins
    but no losses, Req 15.2) is rendered as ``"inf"`` / ``"-inf"`` rather than a
    locale-specific or overly precise form; ``nan`` is rendered as ``"nan"``.
    Finite values are formatted to six significant-ish decimals with trailing
    zeros trimmed so whole numbers stay compact.
    """
    if value != value:  # NaN
        return "nan"
    if value == float("inf"):
        return "inf"
    if value == float("-inf"):
        return "-inf"
    return f"{value:.6f}".rstrip("0").rstrip(".")


def format_summary(run: VariationRun) -> str:
    """Build the multi-line stdout performance summary for one run (Req 18).

    The summary names the Strategy_Variation and reports the number of trades
    (0 when the variation produced no trades, Req 18.3, 18.4) followed by every
    metric on its own ``name: value`` line (Req 18.1, 18.2): Total_Return,
    Annualised_Return, Sharpe_Ratio, Max_Drawdown, Win_Rate, Profit_Factor,
    Average_Win, Average_Loss, Expectancy, Time_In_Market, and Trades_Per_Year.

    The function is pure: it returns the summary string and performs no I/O.
    """
    metrics_result: MetricsResult = run.metrics

    lines = [
        f"Strategy_Variation: {run.variation.name}",
        f"Number_Of_Trades: {metrics_result.number_of_trades}",
    ]
    for label, field_name in _SUMMARY_METRICS:
        value = getattr(metrics_result, field_name)
        lines.append(f"{label}: {_format_value(value)}")

    return "\n".join(lines)


def format_comparison_table(
    runs: list[VariationRun],
    failures: list[VariationFailure],
    buy_and_hold: float,
    bnh_annualised: float,
) -> str:
    """Build the strategy-vs-buy-and-hold comparison table (Req 19).

    Emits one row per completed variation plus a trailing buy-and-hold SPY row,
    with the Total_Return, Annualised_Return, Sharpe_Ratio, and Max_Drawdown
    columns populated for each variation row (Req 19.1, 19.2). The buy-and-hold
    row carries ``buy_and_hold`` as Total_Return and ``bnh_annualised`` as
    Annualised_Return; its Sharpe_Ratio and Max_Drawdown are shown as ``n/a``
    since only the total and annualised returns are meaningful for a passive
    hold.

    Any failed variations are named below the table so the reader knows a
    variation was omitted rather than silently missing (Req 19.4, 19.5).

    The function is pure: it returns the table string and performs no I/O.
    """
    header = ("Strategy_Variation", "Total_Return", "Annualised_Return", "Sharpe_Ratio", "Max_Drawdown")

    rows: list[tuple[str, str, str, str, str]] = []
    for run in runs:
        metrics_result = run.metrics
        rows.append(
            (
                run.variation.name,
                _format_value(metrics_result.total_return),
                _format_value(metrics_result.annualised_return),
                _format_value(metrics_result.sharpe_ratio),
                _format_value(metrics_result.max_drawdown),
            )
        )

    rows.append(
        (
            "Buy_And_Hold_SPY",
            _format_value(buy_and_hold),
            _format_value(bnh_annualised),
            "n/a",
            "n/a",
        )
    )

    widths = [len(col) for col in header]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def _render(cells: tuple[str, ...]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells))

    lines = [_render(header), _render(tuple("-" * width for width in widths))]
    lines.extend(_render(row) for row in rows)

    if failures:
        lines.append("")
        for failure in failures:
            lines.append(f"Failed_Variation: {failure.name} ({failure.error})")

    return "\n".join(lines)


def select_best(runs: list[VariationRun]) -> VariationRun | None:
    """Select the best variation run by risk-adjusted performance (Req 20.1, 20.2).

    Returns the run with the highest ``metrics.sharpe_ratio``. Ties on Sharpe
    are broken by the highest ``metrics.total_return``, and any remaining ties
    by ascending ``variation.name``. Returns ``None`` for an empty list.
    """
    if not runs:
        return None

    return max(
        runs,
        key=lambda run: (
            run.metrics.sharpe_ratio,
            run.metrics.total_return,
            _NameDescending(run.variation.name),
        ),
    )


class _NameDescending:
    """Sort helper making a string compare as its ascending-name reverse.

    ``select_best`` maximises a key tuple, but the final tie-break should pick
    the *ascending* variation name (Req 20.2). Wrapping the name so that a
    lexicographically smaller name compares as "greater" lets it win under
    ``max`` while keeping the Sharpe/Total_Return components maximised normally.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __lt__(self, other: "_NameDescending") -> bool:
        return self.name > other.name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _NameDescending) and self.name == other.name


def format_tradeability_conclusion(runs: list[VariationRun], buy_and_hold: float) -> str:
    """Build the tradeability verdict for the report (Req 20).

    Names the best-performing variation (via :func:`select_best`, highest Sharpe
    with the documented tie-breaks, Req 20.1, 20.2) and states whether that
    variation's ``metrics.total_return`` is strictly greater than the
    ``buy_and_hold`` return over the same span (Req 20.3). When no variation's
    Total_Return is strictly greater than buy-and-hold, the verdict states the
    detected edges are not tradeable after costs (Req 20.4). The conclusion notes
    that results are net of the engine's round-trip cost and use direction-aware
    P&L (Req 20.5).

    The function is pure: it returns the verdict string and performs no I/O.
    """
    cost_note = "Results are net of the round-trip cost and use direction-aware P&L."

    best = select_best(runs)
    if best is None:
        return "No Strategy_Variation completed, so no tradeability verdict is available. " + cost_note

    beats_bnh = best.metrics.total_return > buy_and_hold
    any_beats_bnh = any(run.metrics.total_return > buy_and_hold for run in runs)

    lines = [
        f"Best Strategy_Variation by Sharpe_Ratio: {best.variation.name} "
        f"(Sharpe_Ratio={_format_value(best.metrics.sharpe_ratio)}, "
        f"Total_Return={_format_value(best.metrics.total_return)}).",
    ]

    if beats_bnh:
        lines.append(
            f"Its Total_Return ({_format_value(best.metrics.total_return)}) is strictly greater than "
            f"buy-and-hold ({_format_value(buy_and_hold)})."
        )
    else:
        lines.append(
            f"Its Total_Return ({_format_value(best.metrics.total_return)}) is not strictly greater than "
            f"buy-and-hold ({_format_value(buy_and_hold)})."
        )

    if not any_beats_bnh:
        lines.append("No Strategy_Variation beats buy-and-hold: the detected edges are not tradeable after costs.")

    lines.append(cost_note)

    return "\n".join(lines)
