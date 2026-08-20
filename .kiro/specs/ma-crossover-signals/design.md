# Design Document: MA Crossover Signals

## Overview

This design adds multi-timeframe Moving Average crossover signal detection to the existing `MarketAnalyzer` class. Rather than introducing a new module, the feature extends `MarketAnalyzer` with a new signal category that pre-computes three SMAs (short/medium/long) on the full DataFrame, detects crossover events across three pairs, evaluates graduated price position, and contributes an `ma_crossover_signal_score` to the composite trade signal.

### Design Decisions

1. **Pre-compute SMAs on DataFrame** - Use `df['Close'].rolling(window=N).mean()` to add SMA columns to `self.myDF` before the row-by-row processing loop. This is simpler and more performant than maintaining separate deques, since all historical data is available upfront.

2. **Single new method** - `detect_ma_signals(row_index)` on `MarketAnalyzer` reads pre-computed SMA columns at the given row index and the previous row, detects crossovers and price position, returns a signal dict matching the existing pattern.

3. **No separate state tracking** - Crossover detection compares DataFrame column values at `row[i]` vs `row[i-1]`. The DataFrame itself is the state store.

4. **Config-driven periods and weights** - All MA parameters live under a new `ma_crossover` top-level key in the existing JSON config, with sensible defaults so existing configs work without modification.

5. **Graceful degradation** - When insufficient data exists or MA signals are disabled, the feature contributes zero to the composite score and returns an empty signal list.

## Architecture

```
load_data()
  |-- [Extended] Download ma_data_days instead of 100 days when MA enabled
  v
process_data()
  |-- [New] compute_sma_columns() - adds SMA_short, SMA_medium, SMA_long to self.myDF
  |-- for each row:
  |     |-- detect_signals(candle)  [existing - unchanged]
  |     |-- detect_ma_signals(index) [new]
  |     |-- trade_signal = sum of all 5 signal categories
  v
  return trade_signal
```

### Integration with Existing Signal Flow

The existing `detect_signals()` returns a dict with 4 signal categories. The new `detect_ma_signals()` returns a dict with the same structure for the MA category. The composite score in `process_data()` sums all 5:

```python
trade_signal = (
    signals["single_candle_signal_score"]
    + signals["trend_signal_score"]
    + signals["multiple_bar_signal_score"]
    + signals["acc_dist_signal_score"]
    + ma_signals["ma_crossover_signal_score"]
)
```

## Config Schema

New top-level key `ma_crossover` added to `vpa/config/config.json`:

```json
{
  "ma_crossover": {
    "enabled": true,
    "ma_periods": {
      "short": 10,
      "medium": 50,
      "long": 200
    },
    "ma_data_days": 300,
    "crossover_scores": {
      "short_medium": 5,
      "short_long": 8,
      "medium_long": 10
    },
    "position_scores": {
      "above_all": 5,
      "below_all": 5,
      "above_two": 2,
      "below_two": 2
    }
  }
}
```

| Parameter | Type | Default | Purpose | Req |
|-----------|------|---------|---------|-----|
| `enabled` | bool | true | Master switch for MA signals | 6.2 |
| `ma_periods.short` | int | 10 | Short SMA period | 2.1 |
| `ma_periods.medium` | int | 50 | Medium SMA period | 2.2 |
| `ma_periods.long` | int | 200 | Long SMA period | 2.3 |
| `ma_data_days` | int | 300 | Days of historical data to download | 1.3 |
| `crossover_scores.short_medium` | float | 5 | Score weight for short/medium crossover | 5.5 |
| `crossover_scores.short_long` | float | 8 | Score weight for short/long crossover | 5.5 |
| `crossover_scores.medium_long` | float | 10 | Score weight for medium/long crossover | 5.5 |
| `position_scores.above_all` | float | 5 | Score for price above all 3 SMAs | 4.1 |
| `position_scores.below_all` | float | 5 | Score magnitude for price below all 3 SMAs | 4.2 |
| `position_scores.above_two` | float | 2 | Score for price above 2 of 3 SMAs | 4.3 |
| `position_scores.below_two` | float | 2 | Score magnitude for price below 2 of 3 SMAs | 4.4 |

## Components and Interfaces

### Module: `vpa/app_runner.py` (Modified)

The `MarketAnalyzer` class gains three new methods and modifications to two existing methods.

### Module: `vpa/config/config.json` (Modified)

New `ma_crossover` configuration section.

### Module: `vpa/tests/test_ma_crossover.py` (New)

Complete test suite for MA crossover functionality.

## Component Changes

### Modified: `vpa/app_runner.py`

#### `MarketAnalyzer.__init__()` changes
- Read `ma_crossover` config section (with defaults if missing)
- Validate period ordering (short < medium < long)
- Store MA config in `self.__ma_config`
- Set `self.__ma_enabled` flag

#### `MarketAnalyzer.load_data()` changes
- When `self.__ma_enabled` is True, use `ma_data_days` from config instead of hardcoded 100
- When False, retain existing 100-day behaviour
- After download, check row count >= long period; if not, log warning and set `self.__ma_enabled = False`

#### New: `MarketAnalyzer.compute_sma_columns()`

```python
def compute_sma_columns(self):
    """Pre-compute SMA columns on self.myDF. Called once before row-by-row processing."""
    if not self.__ma_enabled:
        return
    periods = self.__ma_config["ma_periods"]
    self.myDF["SMA_short"] = self.myDF["Close"].rolling(
        window=periods["short"], min_periods=periods["short"]
    ).mean()
    self.myDF["SMA_medium"] = self.myDF["Close"].rolling(
        window=periods["medium"], min_periods=periods["medium"]
    ).mean()
    self.myDF["SMA_long"] = self.myDF["Close"].rolling(
        window=periods["long"], min_periods=periods["long"]
    ).mean()
```

**Requirements:** 2.1-2.7

#### New: `MarketAnalyzer.detect_ma_signals(row_index)`

```python
def detect_ma_signals(self, row_index):
    """Detect MA crossover and price position signals for the given row.

    Args:
        row_index: Integer index into self.myDF

    Returns:
        dict with keys: ma_crossover_signals (list[str]), ma_crossover_signal_score (float)
    """
```

**Logic:**
1. If `self.__ma_enabled` is False, return `{"ma_crossover_signals": [], "ma_crossover_signal_score": 0}`
2. Read SMA_short, SMA_medium, SMA_long for current row and previous row
3. If any current SMA is NaN, return zero score with "unknown" position
4. **Crossover detection** (for each pair):
   - If previous row's faster < slower AND current faster >= slower: Golden Cross
   - If previous row's faster > slower AND current faster <= slower: Death Cross
   - Skip pair if any previous-row SMA is NaN
5. **Price position**:
   - Count how many SMAs the close price is strictly above
   - 3 above: above_all, 0 above: below_all, 2 above: above_two, 1 above: below_two
6. Sum crossover scores + position score = ma_crossover_signal_score
7. Log SMA values, any crossover events, and final score

**Requirements:** 3.1-3.7, 4.1-4.5, 5.1-5.8, 7.1-7.4

#### `MarketAnalyzer.process_data()` changes
- Call `self.compute_sma_columns()` once before the row loop
- After `detect_signals(this_candle)`, call `ma_signals = self.detect_ma_signals(index)`
- Add `ma_signals["ma_crossover_signal_score"]` to the composite `trade_signal`
- Merge `ma_signals` into the signals dict for logging

**Requirements:** 5.5, 5.6

### Modified: `vpa/config/config.json`
- Add `ma_crossover` section with all defaults as shown in Config Schema above

**Requirements:** 6.1

### New: `vpa/tests/test_ma_crossover.py`
- All unit tests for the MA crossover feature

## Data Models

### MA Signal Return Dict

The `detect_ma_signals()` method returns a dictionary with this structure:

| Key | Type | Description |
|-----|------|-------------|
| `ma_crossover_signals` | `list[str]` | List of detected signal names (e.g. "Golden Cross (short/medium)", "Price above_all") |
| `ma_crossover_signal_score` | `float` | Total MA contribution to composite score |

### Config Data Model

The `ma_crossover` config section is loaded as a nested dict:

| Path | Type | Example |
|------|------|---------|
| `ma_crossover.enabled` | bool | `true` |
| `ma_crossover.ma_periods.short` | int | `10` |
| `ma_crossover.ma_periods.medium` | int | `50` |
| `ma_crossover.ma_periods.long` | int | `200` |
| `ma_crossover.ma_data_days` | int | `300` |
| `ma_crossover.crossover_scores.short_medium` | float | `5` |
| `ma_crossover.crossover_scores.short_long` | float | `8` |
| `ma_crossover.crossover_scores.medium_long` | float | `10` |
| `ma_crossover.position_scores.above_all` | float | `5` |
| `ma_crossover.position_scores.below_all` | float | `5` |
| `ma_crossover.position_scores.above_two` | float | `2` |
| `ma_crossover.position_scores.below_two` | float | `2` |

### DataFrame SMA Columns

Added to `self.myDF` by `compute_sma_columns()`:

| Column | Type | Description |
|--------|------|-------------|
| `SMA_short` | float (NaN for warmup rows) | Short-period Simple Moving Average |
| `SMA_medium` | float (NaN for warmup rows) | Medium-period Simple Moving Average |
| `SMA_long` | float (NaN for warmup rows) | Long-period Simple Moving Average |

## Data Flow

```
1. __init__()
   -> Load config
   -> Extract ma_crossover section (or use defaults)
   -> Validate periods: short(10) < medium(50) < long(200)
   -> Set self.__ma_enabled = True/False

2. load_data()
   -> If ma_enabled: start_date = end_date - timedelta(days=ma_data_days)
   -> Else: start_date = end_date - timedelta(days=100)
   -> Download from yfinance
   -> If rows < long_period: log warning, set ma_enabled = False

3. process_data()
   -> compute_sma_columns()  [adds 3 columns to self.myDF]
   -> For each row:
       -> detect_signals(candle)     -> existing 4 signal scores
       -> detect_ma_signals(index)   -> ma_crossover_signal_score
       -> trade_signal = sum of all 5 scores

4. detect_ma_signals(row_index)
   -> Read row[index] SMA values from DataFrame
   -> Read row[index-1] SMA values (skip crossover if index==0 or first row)
   -> Check NaN conditions
   -> Detect crossovers for 3 pairs
   -> Classify price position
   -> Compute total MA score
   -> Log results
   -> Return {"ma_crossover_signals": [...], "ma_crossover_signal_score": N}
```

## Correctness Properties

### Property 1: SMA correctness
*For any* DataFrame with N rows of close prices, SMA_short at row i SHALL equal the arithmetic mean of close[i-short+1 : i+1]. When i < short-1, the value SHALL be NaN.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**

### Property 2: Crossover mutual exclusivity
*For any* single Crossover_Pair on a single trading day, at most one of Golden_Cross or Death_Cross SHALL be detected (never both simultaneously).

**Validates: Requirements 3.5**

### Property 3: Crossover detection correctness
*For any* pair where prev_faster < prev_slower AND curr_faster >= curr_slower, a Golden_Cross SHALL be detected. For prev_faster > prev_slower AND curr_faster <= curr_slower, a Death_Cross SHALL be detected. No other conditions produce crossover events.

**Validates: Requirements 3.2, 3.3**

### Property 4: NaN propagation
*For any* row where any SMA value is NaN, no crossover event SHALL be detected for pairs involving that SMA, and Price_Position SHALL be "unknown" with zero score contribution.

**Validates: Requirements 3.4, 4.5**

### Property 5: Price position exhaustiveness
*For any* row with all three SMAs computed (non-NaN), the Price_Position SHALL be classified as exactly one of: above_all, below_all, above_two, or below_two.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

### Property 6: Score composition
*For any* trading day, MA_Signal_Score SHALL equal the sum of all detected crossover pair scores plus the Price_Position score. When disabled, the score SHALL be exactly zero.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.8**

### Property 7: Config defaults
*When* the `ma_crossover` section is absent from config, all MA parameters SHALL use their documented defaults and MA signals SHALL be enabled.

**Validates: Requirements 6.3**

### Property 8: Period validation
*When* periods are not strictly ordered (short < medium < long), MA signals SHALL be disabled and a warning logged.

**Validates: Requirements 6.4**

## Error Handling

| Condition | Behaviour | Req |
|-----------|-----------|-----|
| `ma_crossover` missing from config | Use all defaults, enable MA signals | 6.3 |
| `ma_periods` not strictly ordered | Log warning, disable MA signals | 6.4 |
| `ma_data_days` <= long period | Auto-correct to long_period + 100 | 6.5 |
| Insufficient data (rows < long period) | Log warning, disable MA for this ticker | 1.4 |
| SMA is NaN at current row | Skip crossover for affected pairs, position = unknown, score = 0 | 3.4, 4.5 |
| First row (no previous row) | Skip crossover detection, still compute price position | 3.6 |
| MA disabled via config | Return empty signals list and zero score | 5.8, 6.2 |

## Testing Strategy

### Test File: `vpa/tests/test_ma_crossover.py`

### Unit Tests

| Test | Description | Requirements |
|------|-------------|---------------|
| `test_sma_short_calculation` | Verify 10-period SMA matches expected values on known data | 2.1 |
| `test_sma_medium_calculation` | Verify 50-period SMA matches expected values | 2.2 |
| `test_sma_long_calculation` | Verify 200-period SMA matches expected values | 2.3 |
| `test_sma_nan_during_warmup` | Verify NaN for rows before sufficient data | 2.4-2.6 |
| `test_golden_cross_short_medium` | Detect golden cross on short/medium pair | 3.1, 3.2 |
| `test_death_cross_short_medium` | Detect death cross on short/medium pair | 3.1, 3.3 |
| `test_golden_cross_medium_long` | Detect golden cross on medium/long pair | 3.1, 3.2 |
| `test_death_cross_medium_long` | Detect death cross on medium/long pair | 3.1, 3.3 |
| `test_golden_cross_short_long` | Detect golden cross on short/long pair | 3.1, 3.2 |
| `test_multiple_crossovers_same_day` | Multiple pairs can cross on same day | 3.7 |
| `test_no_crossover_when_nan` | NaN SMAs prevent crossover detection | 3.4 |
| `test_price_position_above_all` | Close > all 3 SMAs gives above_all score | 4.1 |
| `test_price_position_below_all` | Close < all 3 SMAs gives below_all score | 4.2 |
| `test_price_position_above_two` | Close > 2 of 3 SMAs gives above_two score | 4.3 |
| `test_price_position_below_two` | Close < 2 of 3 SMAs gives below_two score | 4.4 |
| `test_price_position_unknown_nan` | NaN SMA gives unknown, zero score | 4.5 |
| `test_composite_score_integration` | MA score added to trade_signal sum | 5.5, 5.6 |
| `test_crossover_score_weights` | Per-pair scores match config values | 5.2, 5.3, 5.5 |
| `test_ma_disabled_returns_zero` | Disabled config gives zero score, empty list | 5.8, 6.2 |
| `test_config_defaults_when_missing` | No ma_crossover section uses defaults | 6.3 |
| `test_invalid_period_order_disables` | short >= medium gives warning, disabled | 6.4 |
| `test_data_days_auto_correction` | ma_data_days <= long gets corrected | 6.5 |
| `test_insufficient_data_warning` | Few rows gives warning, MA disabled | 1.4 |
| `test_extended_data_window` | MA enabled downloads ma_data_days | 1.1, 1.3 |
| `test_original_window_when_disabled` | MA disabled downloads 100 days | 1.2 |

### Test Data Approach

Tests use fixed pandas DataFrames with known close prices that produce predictable SMA values. No yfinance calls needed - tests inject DataFrames via the `fixed_df` parameter that `MarketAnalyzer.__init__()` already supports.

Example test fixture:

```python
def make_crossover_df():
    """Create a DataFrame where SMA_10 crosses above SMA_50 at a known point."""
    # 60 rows: first 50 rows have declining prices (SMA_10 < SMA_50)
    # last 10 rows have sharply rising prices (SMA_10 > SMA_50)
    prices = [100 - i * 0.5 for i in range(50)] + [90 + i * 3 for i in range(10)]
    df = pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=60),
        "Close": prices,
        "High": [p + 1 for p in prices],
        "Low": [p - 1 for p in prices],
        "Open": prices,
        "Volume": [1000000] * 60,
    })
    return df
```

## Requirement Traceability

| Requirement | Design Element |
|-------------|----------------|
| 1.1-1.3 | `load_data()` modification: conditional data window extension |
| 1.4 | Row count validation after download |
| 2.1-2.7 | `compute_sma_columns()` method |
| 3.1-3.7 | Crossover detection logic in `detect_ma_signals()` |
| 4.1-4.5 | Price position classification in `detect_ma_signals()` |
| 5.1-5.8 | Score computation and integration in `detect_ma_signals()` + `process_data()` |
| 6.1-6.5 | Config schema and validation in `__init__()` |
| 7.1-7.4 | Logger calls within `detect_ma_signals()` |
