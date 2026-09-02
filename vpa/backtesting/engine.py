"""Core VPA backtesting engine (SP-317).

Provides the Signal_Confidence_Order rank helper and the ``BacktestEngine``
simulation loop. The engine operates purely on in-memory inputs (no network /
``yfinance`` dependency, Req 8.3), never mutates its inputs (Req 7.6), and is
deterministic (Req 8.1).
"""

import math

from vpa.backtesting.config import BacktestConfig
from vpa.backtesting.models import (
    BacktestResult,
    PositionMode,
    PricePoint,
    SignalEntry,
    SkippedSignal,
    SkipReason,
    TradeRecord,
)
from vpa.ml_validation.daily_signal import (
    CONFIDENCE_MAP,
    CONFIDENCE_ORDER,
    EXCLUDED_SIGNALS,
)
from vpa.ml_validation.signal_analysis import SignalType


def _is_valid_price(value: object) -> bool:
    """Return True when ``value`` is a finite, non-zero float-like price.

    Zero or NaN prices are invalid (Req 7.4, 7.5). Non-numeric or non-finite
    values (inf) are treated as invalid too, guarding against malformed input.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    numeric = float(value)
    if math.isnan(numeric) or math.isinf(numeric):
        return False
    return numeric != 0.0


def signal_confidence_rank(signal_type: SignalType) -> tuple[int, int]:
    """Signal_Confidence_Order rank helper (Req 5.4, Glossary).

    Returns a sort key ``(rank, enum_order)`` where LOWER means HIGHER
    priority. Ranked types use their ``CONFIDENCE_ORDER`` position
    (High=0 ... Low=3); unranked types (e.g. ``ACCUMULATION_TEST_PASS`` in
    ``EXCLUDED_SIGNALS``, or any type absent from ``CONFIDENCE_MAP``) rank
    below every ranked type. Ties break by ``SignalType`` enum declaration
    order for full determinism (Req 8.1).
    """
    enum_order = list(SignalType).index(signal_type)
    if signal_type in EXCLUDED_SIGNALS or signal_type not in CONFIDENCE_MAP:
        return (len(CONFIDENCE_ORDER), enum_order)  # unranked -> lowest
    return (CONFIDENCE_ORDER.index(CONFIDENCE_MAP[signal_type]), enum_order)


class BacktestEngine:
    """Core VPA backtesting simulation engine (Req 1-9).

    Consumes a Signal_Log and a Price_Series and produces a ``BacktestResult``
    carrying the ordered Trade_Log plus an audit list of skipped signals.
    """

    def run(
        self,
        signal_log: list[SignalEntry],
        price_series: list[PricePoint],
        config: BacktestConfig,
    ) -> BacktestResult:
        """Simulate trades and return the Trade_Log plus skipped signals.

        Does not mutate inputs (Req 7.6). Deterministic (Req 8.1).

        Raises:
            ValueError: if ``config.hold_period`` is not a positive integer
                (Req 3.5).
        """
        # --- Task 9.1: input handling and validation ---
        if config.hold_period <= 0:
            raise ValueError("hold_period must be a positive integer")

        # Work on local copies; never mutate the caller's inputs (Req 7.6).
        # Sort the Price_Series by date ascending if not already sorted (Req 1.4).
        sorted_prices = sorted(price_series, key=lambda p: p.date)
        # Sort the Signal_Log by date ascending regardless of input order
        # (Req 1.6, 5.8).
        sorted_signals = sorted(signal_log, key=lambda s: s.date)

        # Build a date -> index map. First occurrence wins if duplicate dates
        # somehow exist (datasets have unique dates, so this is defensive only).
        date_to_index: dict[str, int] = {}
        for index, point in enumerate(sorted_prices):
            if point.date not in date_to_index:
                date_to_index[point.date] = index

        skipped: list[SkippedSignal] = []

        # Map entry_index -> ordered list of eligible SignalEntry records so
        # same-Entry_Index ties can be resolved (Req 5.4). Signals with a date
        # absent from the Price_Series are skipped with MISSING_PRICE_DATE
        # (Req 1.5).
        groups: dict[int, list[SignalEntry]] = {}
        for entry in sorted_signals:
            signal_index = date_to_index.get(entry.date)
            if signal_index is None:
                skipped.append(
                    SkippedSignal(
                        signal_date=entry.date,
                        signal_type=entry.signal_type,
                        reason=SkipReason.MISSING_PRICE_DATE,
                    )
                )
                continue
            entry_index = signal_index + 1
            groups.setdefault(entry_index, []).append(entry)

        trades: list[TradeRecord] = []
        # NO_OVERLAP position tracking: exit index of the currently open trade.
        open_exit_index: int | None = None

        # --- Task 9.3: iterate groups in ascending Entry_Index order ---
        for entry_index in sorted(groups):
            group = groups[entry_index]

            if config.position_mode == PositionMode.STACKING:
                # STACKING: open a trade for every eligible entry; no tie-break
                # (Req 5.6, 5.7). No open_exit_index tracking.
                for entry in group:
                    trade = self._resolve_trade(
                        entry, entry_index, sorted_prices, config, skipped
                    )
                    if trade is not None:
                        trades.append(trade)
                continue

            # NO_OVERLAP mode (Req 5.2, 5.3, 5.4, 5.5).
            if open_exit_index is not None and entry_index <= open_exit_index:
                # A trade is open and this group overlaps it: skip every entry
                # in the group with OVERLAPPING_POSITION (Req 5.2).
                for entry in group:
                    skipped.append(
                        SkippedSignal(
                            signal_date=entry.date,
                            signal_type=entry.signal_type,
                            reason=SkipReason.OVERLAPPING_POSITION,
                        )
                    )
                continue

            # Slot is free. Choose the highest-confidence entry when there are
            # ties on this Entry_Index (Req 5.4); the losers are recorded as
            # OVERLAPPING_POSITION (Req 5.5).
            chosen = min(group, key=lambda e: signal_confidence_rank(e.signal_type))
            losers = [e for e in group if e is not chosen]

            trade = self._resolve_trade(
                chosen, entry_index, sorted_prices, config, skipped
            )
            if trade is None:
                # The chosen entry was skipped for a data reason (its skip is
                # already recorded by _resolve_trade). Do NOT open a position;
                # leave the slot free for subsequent groups. The other
                # same-Entry_Index entries were not opened either, but the
                # slot was available to them only through the confidence
                # tie-break, so they are recorded as overlapping losers.
                for entry in losers:
                    skipped.append(
                        SkippedSignal(
                            signal_date=entry.date,
                            signal_type=entry.signal_type,
                            reason=SkipReason.OVERLAPPING_POSITION,
                        )
                    )
                continue

            # Trade opened successfully. Record the losers and commit the open
            # position's exit index (Req 5.5).
            for entry in losers:
                skipped.append(
                    SkippedSignal(
                        signal_date=entry.date,
                        signal_type=entry.signal_type,
                        reason=SkipReason.OVERLAPPING_POSITION,
                    )
                )
            trades.append(trade)
            # The exit_date was set from sorted_prices[exit_index]; recover the
            # committed exit index from the resolved strategy result.
            open_exit_index = entry_index + config.hold_period

        # --- Task 9.3: order output (Req 6.2) ---
        # Stable sort by entry_date ascending; empty/fully-skipped input yields
        # an empty Trade_Log with no error (Req 6.5, 7.3).
        trades.sort(key=lambda t: t.entry_date)

        return BacktestResult(trades=trades, skipped=skipped)

    def _resolve_trade(
        self,
        entry: SignalEntry,
        entry_index: int,
        price_series: list[PricePoint],
        config: BacktestConfig,
        skipped: list[SkippedSignal],
    ) -> TradeRecord | None:
        """Resolve a single trade for ``entry`` at ``entry_index``.

        Performs bounds checks, exit resolution, price validation, and return
        math (Task 9.2). Appends a ``SkippedSignal`` to ``skipped`` and returns
        ``None`` when the trade cannot be produced; otherwise returns the built
        ``TradeRecord``.
        """
        last_index = len(price_series) - 1

        # Bounds-check entry (Req 7.1).
        if entry_index > last_index:
            skipped.append(
                SkippedSignal(
                    signal_date=entry.date,
                    signal_type=entry.signal_type,
                    reason=SkipReason.INSUFFICIENT_FUTURE_DATA_ENTRY,
                )
            )
            return None

        # Validate entry price (Req 7.4).
        entry_price = price_series[entry_index].close
        if not _is_valid_price(entry_price):
            skipped.append(
                SkippedSignal(
                    signal_date=entry.date,
                    signal_type=entry.signal_type,
                    reason=SkipReason.INVALID_ENTRY_PRICE,
                )
            )
            return None

        # Resolve exit via the pluggable Exit_Strategy (Req 9.1).
        exit_result = config.exit_strategy.resolve_exit(
            entry_index, price_series, config.hold_period
        )
        if exit_result.reason is not None or exit_result.exit_index is None:
            reason = exit_result.reason or SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT
            skipped.append(
                SkippedSignal(
                    signal_date=entry.date,
                    signal_type=entry.signal_type,
                    reason=reason,
                )
            )
            return None

        exit_index = exit_result.exit_index
        exit_price = exit_result.exit_price

        # Validate exit price (Req 7.5).
        if not _is_valid_price(exit_price):
            skipped.append(
                SkippedSignal(
                    signal_date=entry.date,
                    signal_type=entry.signal_type,
                    reason=SkipReason.INVALID_EXIT_PRICE,
                )
            )
            return None

        # Return math: gross, then net with the round-trip cost applied exactly
        # once (Req 3.6, 4.2, 4.3, 4.4, 4.5).
        gross = exit_price / entry_price - 1
        net = gross - config.round_trip_cost

        return TradeRecord(
            entry_date=price_series[entry_index].date,
            exit_date=price_series[exit_index].date,
            entry_price=entry_price,
            exit_price=exit_price,
            return_pct=net,
            signal_type=entry.signal_type,
        )
