# Design Document: VPA Backtesting Engine

## Overview

This design describes the core VPA backtesting engine and its prerequisite dataset change. It covers two sequenced Jira tickets in one document:

- **SP-335** (prerequisite, ~1 pt): Extend the SP-314 feature datasets (`{ticker}_vpa_features.csv`) so each row carries raw `open`, `high`, and `low` columns alongside `close`. This change lives in `vpa/ml_validation/feature_extractor.py` and **blocks SP-317**.
- **SP-317** (the engine, 5 pts): A new `vpa/backtesting/` package that consumes the enriched OHLC series and a signal log, simulating trades entered at the next-day close and exited after a fixed hold period, producing a per-trade log.

The `Backtest_Engine` operates purely on in-memory inputs. It MUST NOT introduce a network or `yfinance` dependency; all price data is supplied by the caller. Strategy variations, the full performance-metrics suite, and reporting are deferred to follow-on ticket SP-333.

Ticket ownership is called out per component so tasks can be tagged later. Sections and components tagged **[SP-335]** belong to the dataset-enrichment ticket; all others belong to **[SP-317]**.

### Design Decisions

1. **`list[PricePoint]` for the engine core, with a DataFrame adapter [SP-317]** — The engine core operates on an immutable `list[PricePoint]` rather than a pandas DataFrame. Although the codebase uses pandas heavily, the engine's simulation loop is index-based (Entry_Index `t+1`, Exit_Index `t+1+N`) and benefits from an explicitly typed, immutable sequence that is trivial to construct in property-based tests and cannot be mutated mid-run (Req 7.6). A thin `build_price_series_from_dataset(df) -> list[PricePoint]` adapter bridges the pandas Feature_Dataset to the engine core, keeping pandas at the boundary and the core logic pure and deterministic.
2. **Frozen dataclasses for all records [SP-317]** — `PricePoint`, `SignalEntry`, `TradeRecord`, and `SkippedSignal` are `@dataclass(frozen=True)`, mirroring the `SignalMetrics`/`SignalRecord` pattern already used in `signal_analysis.py` and `daily_signal.py`. Immutability guarantees inputs are not mutated (Req 7.6) and makes results safe to reuse.
3. **Exit logic behind a pluggable `Exit_Strategy` [SP-317]** — Exit resolution is delegated to an `ExitStrategy` protocol that receives the full forward `Price_Series` (including `open`/`high`/`low`), so future path-based strategies (stop-loss, R-multiple) plug in without changing the engine core (Req 9.3). Only `FixedHoldExitStrategy` is implemented in SP-317 (Req 9.4); everything else is SP-333.
4. **Reuse SP-314 classification, do not duplicate signal logic [SP-317]** — `Signal_Log_Builder` reuses `SignalConditionalAnalyzer.classify_signals`, which returns `dict[SignalType, list[int]]`, to build the Signal_Log (Req 2.1), and reuses `SIGNAL_DIRECTIONS` for direction (Req 2.2). No signal filter logic is re-implemented.
5. **Confidence tie-break reuses `daily_signal` ordering [SP-317]** — The NO_OVERLAP same-Entry_Index tie-break (Req 5.4) reuses `CONFIDENCE_MAP`/`CONFIDENCE_ORDER`/`EXCLUDED_SIGNALS` from `daily_signal.py` to rank SignalType values, with SignalType enum declaration order as a deterministic final tie-break (Req 8.1).
6. **Raw OHLC in metadata, synthesised candle unchanged [SP-335]** — The extractor synthesises a candle `open = previous close` and clamps `high`/`low` for VPA candle logic. SP-335 emits the **raw** yfinance `Open`/`High`/`Low` as metadata columns and leaves the synthesised `Candle` behaviour used for feature computation entirely unchanged.
7. **Deterministic, side-effect-free core [SP-317]** — Given identical inputs and configuration, `run()` produces identical output (Req 8.1). The core does no I/O; the optional CLI runner is the only component that touches the filesystem.

## Architecture

```mermaid
graph TD
    subgraph SP335[SP-335: Dataset Enrichment]
        FE[VPAFeatureExtractor.generate_dataset]
        FE --> CSV[{ticker}_vpa_features.csv\n+ open/high/low columns]
    end

    subgraph SP317[SP-317: Backtesting Engine]
        CSV --> SLB[Signal_Log_Builder]
        SLB --> |list SignalEntry| ENG[BacktestEngine.run]
        SLB --> |list PricePoint| ENG
        PRE[Caller-provided Signal_Log] --> ENG
        ENG --> ES[Exit_Strategy\nFixedHoldExitStrategy]
        ES --> ENG
        ENG --> RES[BacktestResult\ntrades + skipped]
        CFG[BacktestConfig\nhold_period, cost, mode] --> ENG
    end

    RES --> RUN[run_backtest.py CLI\ntrade count summary only]
```

### Data Flow

1. **[SP-335] Enrich** — `generate_dataset` attaches raw `open`/`high`/`low` alongside `close` for each row; the CSV gains three columns.
2. **[SP-317] Build inputs** — `Signal_Log_Builder` reads the Feature_Dataset: `classify_signals` produces one `SignalEntry` per matched SignalType per row (Req 2.2); `build_price_series_from_dataset` produces a sorted `list[PricePoint]` (Req 2.3). Callers may instead supply a pre-built Signal_Log (Req 2.4).
3. **[SP-317] Simulate** — `BacktestEngine.run` builds a `date -> index` map, processes signals in ascending date order (Req 1.6), resolves entry (`t+1`) and exit (via `Exit_Strategy`), validates prices, applies position-mode eligibility, and computes net returns.
4. **[SP-317] Output** — A `BacktestResult` carrying the Trade_Log (ordered by `entry_date` ascending, Req 6.2) and a list of skipped signals with reasons.
5. **[SP-317] Optional run** — `run_backtest.py` builds inputs for a ticker dataset and prints a short trade-count summary (metrics/reporting are SP-333).

## Components and Interfaces

### Part A — SP-335: OHLC Dataset Enrichment

**Module: `vpa/ml_validation/feature_extractor.py` [SP-335]**

The change is confined to two places. First, the metadata column list gains the raw OHLC fields:

```python
class VPAFeatureExtractor:
    # Metadata columns (excluded from the numeric feature array)
    # SP-335: add raw open/high/low alongside close
    METADATA_COLUMNS = ["date", "open", "high", "low", "close"]
```

Second, in the `generate_dataset` row loop, attach the **raw** yfinance values (not the synthesised candle values) alongside the existing `close`:

```python
            # Add metadata (SP-335: emit RAW OHLC, not synthesised candle values)
            date_val = row["Date"]
            date_str = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)

            feature_vector["date"] = date_str
            feature_vector["open"] = float(row["Open"])   # SP-335: raw yfinance open
            feature_vector["high"] = float(row["High"])   # SP-335: raw yfinance high
            feature_vector["low"] = float(row["Low"])     # SP-335: raw yfinance low
            feature_vector["close"] = float(row["Close"])
```

Design notes for SP-335:

- The synthesised `Candle` (`open = previous_close`, `high = max(raw high, open)`, `low = min(raw low, open)`) continues to feed VPA feature computation unchanged. Only the emitted metadata columns gain the raw OHLC. The raw values are read directly from `row["Open"]`/`row["High"]`/`row["Low"]`, which `generate_dataset` already loads from yfinance but previously discarded.
- `next_day_direction` labelling (`close.shift(-1) > close`) and the final-row exclusion are unchanged.
- **Backward compatibility**: existing consumers read by column name (`signal_analysis.load_dataset`, `daily_signal`), so the three extra columns do not affect them. No known consumer relies on positional column order, but the CSV **column order changes** — any positional consumer would be affected, so this is called out explicitly.
- **Regeneration is a run step**: at least `SPY_vpa_features.csv` must be regenerated so downstream SP-317 backtests have the OHLC columns. This is an operational step, not code.

### Part B — SP-317: Backtesting Engine

**Module: `vpa/backtesting/models.py` [SP-317]**

```python
from dataclasses import dataclass, field
from enum import Enum

from vpa.ml_validation.signal_analysis import SignalDirection, SignalType


@dataclass(frozen=True)
class PricePoint:
    """One trading day of raw OHLC price data. Immutable (Req 7.6)."""

    date: str  # ISO 8601 YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class SignalEntry:
    """A single input signal record for the Signal_Log."""

    date: str  # ISO 8601 YYYY-MM-DD
    signal_type: SignalType
    direction: SignalDirection


@dataclass(frozen=True)
class TradeRecord:
    """A single simulated trade in the Trade_Log."""

    entry_date: str  # ISO 8601 YYYY-MM-DD
    exit_date: str  # ISO 8601 YYYY-MM-DD
    entry_price: float
    exit_price: float
    return_pct: float  # Net_Return (Gross_Return - Round_Trip_Cost)
    signal_type: SignalType


class SkipReason(Enum):
    """Reason a Signal_Entry did not produce a trade."""

    MISSING_PRICE_DATE = "missing_price_date"          # Req 1.5
    OVERLAPPING_POSITION = "overlapping_position"       # Req 5.2, 5.5
    INSUFFICIENT_FUTURE_DATA_ENTRY = "insufficient_future_data_entry"  # Req 7.1
    INSUFFICIENT_FUTURE_DATA_EXIT = "insufficient_future_data_exit"    # Req 7.2
    INVALID_ENTRY_PRICE = "invalid_entry_price"         # Req 7.4
    INVALID_EXIT_PRICE = "invalid_exit_price"           # Req 7.5


@dataclass(frozen=True)
class SkippedSignal:
    """Record that a Signal_Entry was skipped, with the reason (Req 1.5, 5.2, 7.x)."""

    signal_date: str
    signal_type: SignalType
    reason: SkipReason


class PositionMode(Enum):
    """Trade-tracking behaviour (Req 5.1)."""

    NO_OVERLAP = "no_overlap"
    STACKING = "stacking"


@dataclass(frozen=True)
class ExitResult:
    """Outcome of an Exit_Strategy resolution."""

    exit_index: int | None
    exit_price: float | None
    reason: SkipReason | None  # set when exit cannot be resolved (Req 7.2)


@dataclass(frozen=True)
class BacktestResult:
    """Engine output: the Trade_Log plus skipped signals."""

    trades: list[TradeRecord] = field(default_factory=list)
    skipped: list[SkippedSignal] = field(default_factory=list)
```

**Module: `vpa/backtesting/exit_strategy.py` [SP-317]**

```python
from typing import Protocol, runtime_checkable

from vpa.backtesting.models import ExitResult, PricePoint, SkipReason


@runtime_checkable
class ExitStrategy(Protocol):
    """Pluggable exit resolver (Req 9.1, 9.3).

    Receives the full forward Price_Series including open/high/low so that
    future path-based strategies (stop-loss, R-multiple) plug in without
    changing the Backtest_Engine core. SP-317 implements only fixed hold.
    """

    def resolve_exit(
        self, entry_index: int, price_series: list[PricePoint], hold_period: int
    ) -> ExitResult: ...


class FixedHoldExitStrategy:
    """Exit N trading days after entry at close[t+1+N] (Req 9.2).

    exit_index = entry_index + hold_period; exit_price = close at that index.
    Returns an ExitResult with reason INSUFFICIENT_FUTURE_DATA_EXIT when the
    exit index is beyond the series (Req 7.2). Stop-loss / R-multiple /
    path-based strategies are OUT OF SCOPE (SP-333); this interface is shaped
    to accept them but only fixed hold is implemented here (Req 9.4).
    """

    def resolve_exit(
        self, entry_index: int, price_series: list[PricePoint], hold_period: int
    ) -> ExitResult:
        exit_index = entry_index + hold_period
        if exit_index > len(price_series) - 1:
            return ExitResult(None, None, SkipReason.INSUFFICIENT_FUTURE_DATA_EXIT)
        return ExitResult(exit_index, price_series[exit_index].close, None)
```

**Module: `vpa/backtesting/config.py` [SP-317]**

```python
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
```

**Module: `vpa/backtesting/signal_log_builder.py` [SP-317]**

```python
import pandas as pd

from vpa.backtesting.models import PricePoint, SignalEntry
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalConditionalAnalyzer,
)


def build_signal_log_from_dataset(df: pd.DataFrame) -> list[SignalEntry]:
    """Build a Signal_Log by reusing SP-314 classify_signals (Req 2.1, 2.2).

    Produces one SignalEntry per matched SignalType per row, using the row
    date, the matched SignalType, and SIGNAL_DIRECTIONS[signal_type]. NaN
    fields are excluded per classify_signals behaviour (Req 2.5).
    """


def build_price_series_from_dataset(df: pd.DataFrame) -> list[PricePoint]:
    """Build a date-ascending Price_Series from date/open/high/low/close (Req 2.3)."""
```

**Module: `vpa/backtesting/engine.py` [SP-317]**

```python
from vpa.backtesting.config import BacktestConfig
from vpa.backtesting.models import (
    BacktestResult,
    PricePoint,
    PositionMode,
    SignalEntry,
)
from vpa.ml_validation.daily_signal import (
    CONFIDENCE_MAP,
    CONFIDENCE_ORDER,
    EXCLUDED_SIGNALS,
)
from vpa.ml_validation.signal_analysis import SignalType


def signal_confidence_rank(signal_type: SignalType) -> tuple[int, int]:
    """Signal_Confidence_Order rank helper (Req 5.4, Glossary).

    Returns a sort key where LOWER is higher priority. Ranked types use their
    CONFIDENCE_ORDER position (High=0 ... Low=3); unranked types (e.g.
    ACCUMULATION_TEST_PASS in EXCLUDED_SIGNALS) rank below every ranked type.
    Ties break by SignalType enum declaration order for full determinism
    (Req 8.1).
    """
    enum_order = list(SignalType).index(signal_type)
    if signal_type in EXCLUDED_SIGNALS or signal_type not in CONFIDENCE_MAP:
        return (len(CONFIDENCE_ORDER), enum_order)  # unranked -> lowest
    return (CONFIDENCE_ORDER.index(CONFIDENCE_MAP[signal_type]), enum_order)


class BacktestEngine:
    """Core VPA backtesting simulation engine (Req 1-9)."""

    def run(
        self,
        signal_log: list[SignalEntry],
        price_series: list[PricePoint],
        config: BacktestConfig,
    ) -> BacktestResult:
        """Simulate trades and return the Trade_Log plus skipped signals.

        Does not mutate inputs (Req 7.6). Deterministic (Req 8.1).
        """
```

### Simulation Loop (BacktestEngine.run) [SP-317]

1. **Copy, do not mutate (Req 7.6)** — Work on local copies. Sort a copy of `price_series` by `date` ascending if not already sorted (Req 1.4); sort a copy of `signal_log` by `date` ascending (Req 1.6, 5.8).
2. **Build date -> index map** — From the sorted Price_Series, `{point.date: index}` for O(1) signal-day lookup.
3. **Group by Entry_Index** — For each SignalEntry, look up signal-day index `t` (record `MISSING_PRICE_DATE` and skip if absent, Req 1.5); compute `entry_index = t + 1`. Group eligible entries by `entry_index` so same-Entry_Index ties can be resolved (Req 5.4).
4. **Iterate entries in ascending Entry_Index order.** For each group:
   - **Bounds check entry (Req 7.1)** — If `entry_index > last index`, record `INSUFFICIENT_FUTURE_DATA_ENTRY` for every entry in the group and skip.
   - **NO_OVERLAP eligibility (Req 5.2)** — If a trade is open and `entry_index <= open_exit_index`, record `OVERLAPPING_POSITION` for every entry in the group and skip.
   - **NO_OVERLAP tie-break (Req 5.4, 5.5)** — When no position is open and the group has 2+ entries, pick the entry whose SignalType has the best `signal_confidence_rank`; open a single trade for it and record `OVERLAPPING_POSITION` for each remaining same-Entry_Index entry (Req 5.5).
   - **STACKING (Req 5.6, 5.7)** — Open a trade for every entry in the group; no tie-break applied.
   - **Resolve exit (Req 9.1)** — Call `config.exit_strategy.resolve_exit(entry_index, price_series, config.hold_period)`. If it returns a skip reason (e.g. exit beyond series), record `INSUFFICIENT_FUTURE_DATA_EXIT` and skip (Req 7.2).
   - **Validate prices (Req 7.4, 7.5)** — `entry_price = close[entry_index]`; if zero or NaN, record `INVALID_ENTRY_PRICE` and skip. If `exit_price` is zero or NaN, record `INVALID_EXIT_PRICE` and skip.
   - **Compute returns** — `gross = exit_price / entry_price - 1` (Req 3.6); `net = gross - config.round_trip_cost` (Req 4.2, applied exactly once, Req 4.5); `return_pct = net` (Req 4.3; equals gross when cost is 0, Req 4.4).
   - **Build TradeRecord** — `entry_date = date[entry_index]`, `exit_date = date[exit_index]` (Req 3.3), `signal_type` from the originating entry (Req 3.4, 6.4).
   - **Update open position (NO_OVERLAP)** — Set `open_exit_index = exit_index` for the newly opened trade.
5. **Order output (Req 6.2)** — Sort the Trade_Log by `entry_date` ascending. Dates are ISO 8601 strings (Req 6.3). An empty or fully-skipped Signal_Log yields an empty Trade_Log (Req 6.5, 7.3).

### Optional Runner: `vpa/backtesting/run_backtest.py` [SP-317]

A thin CLI for manual execution against a ticker dataset. It loads `{ticker}_vpa_features.csv`, builds the Signal_Log and Price_Series, runs the engine with a chosen config, and prints a **short trade-count summary only** (number of trades, number skipped by reason). Full metrics, equity curves, and reporting are **out of scope (SP-333)**.

```python
def main(ticker: str = "SPY", hold_period: int = 10) -> None:
    """Build inputs from {ticker}_vpa_features.csv, run the engine, print counts."""
```

### Key Method Contracts [SP-317]

| Method | Input | Output | Notes |
|--------|-------|--------|-------|
| `build_signal_log_from_dataset` | Feature_Dataset DataFrame | `list[SignalEntry]` | One entry per matched SignalType per row; reuses `classify_signals` + `SIGNAL_DIRECTIONS` (Req 2.1, 2.2, 2.5) |
| `build_price_series_from_dataset` | Feature_Dataset DataFrame | `list[PricePoint]` sorted ascending | From date/open/high/low/close (Req 2.3) |
| `signal_confidence_rank` | `SignalType` | `(rank, enum_order)` sort key | Lower is higher priority; unranked lowest; enum-order tiebreak (Req 5.4, 8.1) |
| `FixedHoldExitStrategy.resolve_exit` | entry_index, price_series, hold_period | `ExitResult` | `exit_index = entry_index + N`; skip reason when beyond series (Req 7.2, 9.2) |
| `BacktestEngine.run` | signal_log, price_series, config | `BacktestResult` | Deterministic, non-mutating; ordered Trade_Log + skipped list (Req 1-9) |

## Data Models

### Input: Feature Dataset CSV (post SP-335)

| Column | Type | Description | Ticket |
|--------|------|-------------|--------|
| `date` | ISO 8601 string | Trading date | existing |
| `open` | float | Raw yfinance open | **SP-335 (new)** |
| `high` | float | Raw yfinance high | **SP-335 (new)** |
| `low` | float | Raw yfinance low | **SP-335 (new)** |
| `close` | float | Closing price | existing |
| `composite_score` | float | VPA composite score | existing |
| `acc_dist_flag` | int (0/1) | Accumulation/distribution detected | existing |
| `acc_dist_type` | int (-1/0/1) | 1=accumulation, -1=distribution | existing |
| `acc_dist_score` | float | Acc/dist strength | existing |
| `next_day_direction` | int (0/1) | Next-day up label (unchanged) | existing |

Column **order** changes because the new columns are emitted after `date` and before `close` in `METADATA_COLUMNS`. Consumers reading by name are unaffected; no known positional consumer exists.

### Engine Data Models [SP-317]

| Model | Fields | Notes |
|-------|--------|-------|
| `PricePoint` | `date:str, open:float, high:float, low:float, close:float` | Frozen; one trading day (Req 1.2) |
| `SignalEntry` | `date:str, signal_type:SignalType, direction:SignalDirection` | Frozen; one input signal (Req 1.1) |
| `TradeRecord` | `entry_date:str, exit_date:str, entry_price:float, exit_price:float, return_pct:float, signal_type:SignalType` | Frozen; Trade_Log element (Req 6.1) |
| `SkippedSignal` | `signal_date:str, signal_type:SignalType, reason:SkipReason` | Frozen; skip audit record (Req 1.5, 5.2, 7.x) |
| `ExitResult` | `exit_index:int\|None, exit_price:float\|None, reason:SkipReason\|None` | Frozen; Exit_Strategy output |
| `BacktestResult` | `trades:list[TradeRecord], skipped:list[SkippedSignal]` | Frozen; engine output |

### Enums [SP-317]

| Enum | Values | Purpose |
|------|--------|---------|
| `PositionMode` | `NO_OVERLAP`, `STACKING` | Position tracking mode (Req 5.1) |
| `SkipReason` | `MISSING_PRICE_DATE`, `OVERLAPPING_POSITION`, `INSUFFICIENT_FUTURE_DATA_ENTRY`, `INSUFFICIENT_FUTURE_DATA_EXIT`, `INVALID_ENTRY_PRICE`, `INVALID_EXIT_PRICE` | Why a signal was skipped (Req 1.5, 5.2/5.5, 7.1, 7.2, 7.4, 7.5) |

### Configuration [SP-317]

| Field | Type | Default | Requirement |
|-------|------|---------|-------------|
| `hold_period` | int (positive) | — (required) | Req 3.5 |
| `round_trip_cost` | float | `0.001` | Req 4.1 |
| `position_mode` | `PositionMode` | `NO_OVERLAP` | Req 5.1 |
| `exit_strategy` | `ExitStrategy` | `FixedHoldExitStrategy()` | Req 9.2 |

### Index Model [SP-317]

For a signal matching Price_Series index `t`: `Entry_Index = t + 1`, `entry_price = close[t+1]` (Req 3.1); `Exit_Index = t + 1 + N`, `exit_price = close[t+1+N]` (Req 3.2, 9.2).

## Correctness Properties

*A property is a characteristic or behaviour that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

The following prework classified each acceptance criterion. UI-free numeric and index logic (entry/exit pricing, return math, cost application, tie-break ranking, position tracking, skip recording, immutability, determinism) is pure and input-varying, so it is well suited to property-based testing. Criteria describing input contracts satisfied by construction (e.g. field presence) and the hand-computed integration case (Req 8.2) are covered by unit tests instead. Redundant properties were consolidated: same-Entry_Index tie-break and single-open-trade invariants are covered by one NO_OVERLAP non-overlap property plus one tie-break property; the gross/net formulas are combined into one return-math property with a cost=0 corollary.

### Property 1: Next-day-close entry pricing

*For any* Price_Series and any signal matching index `t` where `t+1` is within bounds, the resulting trade's `entry_price` SHALL equal `close[t+1]` and `entry_date` SHALL equal `date[t+1]`.

**Validates: Requirements 3.1, 3.3**

### Property 2: Fixed-hold exit pricing

*For any* trade entered at Entry_Index `t+1` with Hold_Period `N` where `t+1+N` is within bounds, the trade's `exit_price` SHALL equal `close[t+1+N]` and `exit_date` SHALL equal `date[t+1+N]`.

**Validates: Requirements 3.2, 3.3, 9.2**

### Property 3: Gross and net return formulas

*For any* trade with valid `entry_price` and `exit_price`, the Gross_Return SHALL equal `exit_price / entry_price - 1` and `return_pct` SHALL equal `Gross_Return - round_trip_cost`, to within floating-point tolerance (1e-9).

**Validates: Requirements 3.6, 4.2, 4.3**

### Property 4: Round-trip cost applied exactly once

*For any* trade, `return_pct` SHALL differ from the Gross_Return by exactly `round_trip_cost`; when `round_trip_cost == 0`, `return_pct` SHALL equal the Gross_Return exactly.

**Validates: Requirements 4.4, 4.5**

### Property 5: NO_OVERLAP produces no overlapping trades

*For any* Signal_Log and Price_Series run in NO_OVERLAP mode, no two Trade_Records SHALL have overlapping holding intervals; that is, for trades sorted by Entry_Index, each trade's Entry_Index SHALL be strictly greater than the previous trade's Exit_Index.

**Validates: Requirements 5.2, 5.3**

### Property 6: NO_OVERLAP same-Entry_Index tie-break is highest confidence and deterministic

*For any* set of two or more eligible Signal_Entry records sharing an Entry_Index with no position open in NO_OVERLAP mode, the single opened trade's `signal_type` SHALL be the one with the best Signal_Confidence_Order rank (unranked lowest, SignalType enum order as tiebreak), each remaining same-Entry_Index entry SHALL be recorded skipped with `OVERLAPPING_POSITION`, and the selection SHALL be identical across repeated runs.

**Validates: Requirements 5.4, 5.5**

### Property 7: STACKING opens a trade per eligible signal

*For any* Signal_Log and Price_Series run in STACKING mode, every eligible Signal_Entry (one whose entry and exit indices are within bounds and prices are valid) SHALL produce exactly one Trade_Record, with no confidence tie-break applied to same-Entry_Index entries.

**Validates: Requirements 5.6, 5.7**

### Property 8: Skip reasons recorded for each edge case

*For any* Signal_Entry that cannot produce a trade, the engine SHALL record exactly one SkippedSignal whose reason matches the cause: missing price date (`MISSING_PRICE_DATE`), entry beyond series (`INSUFFICIENT_FUTURE_DATA_ENTRY`), exit beyond series (`INSUFFICIENT_FUTURE_DATA_EXIT`), zero/NaN entry price (`INVALID_ENTRY_PRICE`), zero/NaN exit price (`INVALID_EXIT_PRICE`), or overlap in NO_OVERLAP (`OVERLAPPING_POSITION`).

**Validates: Requirements 1.5, 7.1, 7.2, 7.4, 7.5**

### Property 9: Input immutability

*For any* Signal_Log and Price_Series, running the engine SHALL leave both inputs equal to deep copies taken before the run (no element or ordering mutated).

**Validates: Requirements 7.6**

### Property 10: Determinism

*For any* Signal_Log, Price_Series, and configuration, running the engine twice SHALL produce identical Trade_Logs and identical skipped lists (same records in the same order).

**Validates: Requirements 8.1**

### Property 11: Trade_Log ordering

*For any* Signal_Log and Price_Series, the produced Trade_Log SHALL be ordered by `entry_date` ascending.

**Validates: Requirements 6.2**

### Property 12: Signal-Log construction from dataset

*For any* Feature_Dataset row that `classify_signals` matches to a set of SignalType values, `build_signal_log_from_dataset` SHALL emit exactly one SignalEntry per matched SignalType, each using the row `date`, the matched SignalType, and `SIGNAL_DIRECTIONS[signal_type]`.

**Validates: Requirements 2.1, 2.2, 2.5**

## Error Handling

The engine favours graceful skipping over raising: individual problem signals are recorded and excluded rather than aborting the run. Only genuinely malformed configuration is rejected up front.

### Skip Handling (recorded, run continues) [SP-317]

| Condition | Trigger | Handling | Requirement |
|-----------|---------|----------|-------------|
| Missing price date | Signal_Entry `date` not in Price_Series | Skip, record `MISSING_PRICE_DATE` | Req 1.5 |
| Entry beyond series | `t+1 > last index` | Skip, record `INSUFFICIENT_FUTURE_DATA_ENTRY` | Req 7.1 |
| Exit beyond series | `t+1+N > last index` | Skip, record `INSUFFICIENT_FUTURE_DATA_EXIT` | Req 7.2 |
| Invalid entry price | `close[t+1]` is 0 or NaN | Skip, record `INVALID_ENTRY_PRICE` | Req 7.4 |
| Invalid exit price | `close[t+1+N]` is 0 or NaN | Skip, record `INVALID_EXIT_PRICE` | Req 7.5 |
| Overlapping position | NO_OVERLAP, `entry_index <= open_exit_index` (incl. same-Entry_Index losers) | Skip, record `OVERLAPPING_POSITION` | Req 5.2, 5.5 |
| Empty Signal_Log | No entries supplied | Return empty Trade_Log, no error | Req 6.5, 7.3 |

### Validation Errors (raised) [SP-317]

| Condition | Trigger | Handling |
|-----------|---------|----------|
| Non-positive hold period | `config.hold_period <= 0` | Raise `ValueError` (Hold_Period must be a positive integer, Req 3.5) |
| Missing OHLC columns | Dataset lacks `open`/`high`/`low`/`close` in the builder | Raise `KeyError`/`ValueError` naming the missing column (SP-335 not applied / dataset not regenerated) |

### Non-goals

No network, `yfinance`, or filesystem access occurs in the engine core (Req 8.3); the optional `run_backtest.py` runner is the only component that reads a CSV.

## Testing Strategy

### Dual Testing Approach

Property-based tests (Hypothesis) exercise the pure computational and index logic across randomised inputs. Unit tests cover specific edge cases, error conditions, and the hand-computed known-signal integration case. PBT is appropriate here because entry/exit pricing, return math, cost application, tie-break ranking, position tracking, and skip classification are pure functions whose behaviour varies meaningfully with input over a large space.

### Property-Based Tests [SP-317]

**Library:** [Hypothesis](https://hypothesis.readthedocs.io/)

**Configuration:** Minimum 100 examples per property test (`@settings(max_examples=100)`).

**Tag format** on each property test: `# Feature: vpa-backtesting-engine, Property {number}: {property_text}`.

| Property | Component Under Test | Generator Strategy |
|----------|----------------------|--------------------|
| 1: Next-day-close entry pricing | `BacktestEngine.run` | Random Price_Series (ascending dates, positive closes) + single in-bounds signal |
| 2: Fixed-hold exit pricing | `FixedHoldExitStrategy` / `run` | Random series + hold_period; assert index/price mapping |
| 3: Gross/net return formulas | `BacktestEngine.run` | Random valid entry/exit prices, random cost |
| 4: Cost applied once | `BacktestEngine.run` | Random cost incl. 0.0; compare to gross |
| 5: NO_OVERLAP no overlap | `BacktestEngine.run` | Random signal dates over a series in NO_OVERLAP |
| 6: Tie-break highest confidence + deterministic | `signal_confidence_rank` / `run` | Random multi-signal same-date clusters |
| 7: STACKING one trade per eligible | `BacktestEngine.run` | Random overlapping signals in STACKING |
| 8: Skip reasons per edge case | `BacktestEngine.run` | Series/signal fixtures forcing each edge (short series, missing dates, zero/NaN prices) |
| 9: Input immutability | `BacktestEngine.run` | Random inputs; compare to pre-run deep copies |
| 10: Determinism | `BacktestEngine.run` | Random inputs, run twice |
| 11: Trade_Log ordering | `BacktestEngine.run` | Random shuffled Signal_Log input |
| 12: Signal-Log construction | `build_signal_log_from_dataset` | Random Feature_Dataset rows with mixed signal fields |

### Unit Tests [SP-317]

Edge cases:
- Signal near end of series — `t+1` valid but `t+1+N` out of bounds (Req 7.2)
- Signal on the last day — `t+1` out of bounds (Req 7.1)
- Empty Signal_Log — empty Trade_Log, no error (Req 6.5, 7.3)
- Zero / NaN entry and exit prices (Req 7.4, 7.5)
- Signal date missing from Price_Series (Req 1.5)
- Unsorted Price_Series and unsorted Signal_Log get sorted (Req 1.4, 1.6)
- NO_OVERLAP overlap skipping across consecutive signals (Req 5.2)
- STACKING opens concurrent trades (Req 5.6)
- Non-positive `hold_period` raises `ValueError` (Req 3.5)

Integration test (Req 8.2):
- A small hand-computed Signal_Log + Price_Series with a fixed Hold_Period, Round_Trip_Cost, and Position_Mode, asserting the Trade_Log matches manually derived entry/exit dates, prices, and net returns exactly.

### SP-335 Tests [SP-335]

Under `vpa/tests/ml_validation/`, a focused test asserting that `generate_dataset` emits `open`, `high`, `low`, and `close` metadata columns and that the emitted values are the **raw** yfinance OHLC (not the synthesised candle open/clamped high/low). yfinance is mocked so the test is offline and deterministic; the synthesised-candle feature computation is asserted unchanged.

### Test File Structure

```
vpa/
  tests/
    backtesting/
      __init__.py
      test_backtest_engine.py     # Properties 1-11 + engine unit/integration tests
      test_exit_strategy.py       # FixedHoldExitStrategy unit tests (Property 2 focus)
      test_signal_log_builder.py  # Property 12 + builder unit tests
    ml_validation/
      test_feature_extractor_ohlc.py  # SP-335: raw open/high/low emitted
```

### Running Tests

```bash
# All backtesting tests
pytest vpa/tests/backtesting/ -v

# Property tests only
pytest vpa/tests/backtesting/ -v -k "property"

# SP-335 dataset enrichment test
pytest vpa/tests/ml_validation/test_feature_extractor_ohlc.py -v

# Full suite for both tickets
pytest vpa/tests/backtesting/ vpa/tests/ml_validation/test_feature_extractor_ohlc.py -v
```

All code follows ruff conventions (line-length 120, double quotes, target py311); `from __future__ import annotations` is not required on Python 3.11 for the `int | None` / `X | None` union syntax used above.
