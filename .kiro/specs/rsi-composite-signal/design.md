# Design Document

## Overview

This design adds RSI (Relative Strength Index) as the 6th signal component to the VPA MarketAnalyzer composite trading score. The implementation follows the established pattern used by the MA crossover feature: a standalone calculation module, config-driven initialization, pre-computed DataFrame columns, and a per-row signal detection method.

## Architecture

### Component Diagram

```text
+-----------------------------------------------------------------+
|                    MarketAnalyzer                                 |
|                                                                   |
|  __init__()                                                       |
|    +-- _init_ma_config()                                          |
|    +-- _init_drawdown_config()                                    |
|    +-- _init_rsi_config()  <-- NEW                                |
|                                                                   |
|  process_data()                                                   |
|    +-- compute_sma_columns()                                      |
|    +-- compute_rsi_column()  <-- NEW                              |
|    +-- ... row loop ...                                           |
|    |   +-- detect_signals()                                       |
|    |   +-- detect_ma_signals(row_index)                           |
|    |   +-- detect_rsi_signals(row_index)  <-- NEW                 |
|    |   +-- trade_signal = sum of all 6 sub-scores                 |
|    +-- return trade_signal                                        |
|                                                                   |
+-----------------------------------------------------------------+

+---------------------+      +-------------------------------+
|   vpa/rsi.py (NEW)  |      |   VPAFeatureExtractor          |
|                     |      |                               |
|  calculate_rsi()    |<-----|  _extract_feature_vector()    |
|                     |      |    +-- rsi_value              |
|                     |      |    +-- rsi_signal_score        |
|                     |      |    +-- composite_score (+RSI)  |
+---------------------+      +-------------------------------+
```

### Data Flow

1. Config loaded -> `_init_rsi_config()` validates and stores RSI parameters
2. DataFrame loaded -> `compute_rsi_column()` pre-computes RSI for all rows
3. Per-row processing -> `detect_rsi_signals(row_index)` reads pre-computed RSI, applies thresholds
4. Composite score -> RSI signal score added to trade_signal summation

## Components and Interfaces

### RSI Calculator (`vpa/rsi.py`)

Pure function module with no state or dependencies beyond the standard library.

```python
def calculate_rsi(closes: list[float], period: int = 14) -> float:
    """Calculate RSI using Wilder's smoothed moving average method.

    Args:
        closes: List of closing prices (oldest first).
        period: RSI lookback period (default 14).

    Returns:
        RSI value between 0.0 and 100.0 inclusive.
        Returns 50.0 if fewer than period + 1 prices provided.
    """
```

**Algorithm (Wilder's Smoothed MA):**
1. If len(closes) < period + 1: return 50.0
2. Compute price changes: changes[i] = closes[i] - closes[i-1]
3. Separate gains (positive changes) and losses (abs of negative changes)
4. Initial avg_gain = mean(first `period` gains)
5. Initial avg_loss = mean(first `period` losses)
6. For subsequent bars: avg_gain = (prev_avg_gain * (period-1) + current_gain) / period
7. Same smoothing for avg_loss
8. If avg_loss == 0: return 100.0
9. If avg_gain == 0: return 0.0
10. RS = avg_gain / avg_loss
11. RSI = 100 - (100 / (1 + RS))

**Edge cases:**
- All gains -> avg_loss = 0 -> return 100.0
- All losses -> avg_gain = 0 -> return 0.0
- All unchanged -> avg_gain = 0, avg_loss = 0 -> return 50.0

### MarketAnalyzer RSI Methods (`vpa/app_runner.py`)

#### `_init_rsi_config()`

Called from `__init__()` after `_init_drawdown_config()`.

```python
def _init_rsi_config(self):
    """Load and validate the rsi configuration section."""
    rsi_defaults = {
        "enabled": True,
        "period": 14,
        "overbought_threshold": 70,
        "oversold_threshold": 30,
        "scores": {"overbought": -5, "oversold": 5}
    }

    if "rsi" in self.__config:
        self.__rsi_config = self.__config["rsi"]
    else:
        self.__rsi_config = rsi_defaults

    if not self.__rsi_config.get("enabled", True):
        self.__rsi_enabled = False
        return

    oversold = self.__rsi_config.get("oversold_threshold", 30)
    overbought = self.__rsi_config.get("overbought_threshold", 70)

    if oversold >= overbought:
        self.__logger.log(
            f"RSI disabled: invalid thresholds (oversold={oversold} >= overbought={overbought})",
            level="WARN"
        )
        self.__rsi_enabled = False
        return

    self.__rsi_enabled = True
```

#### `compute_rsi_column()`

Called from `process_data()` after `compute_sma_columns()`.

```python
def compute_rsi_column(self):
    """Pre-compute RSI column on self.myDF."""
    if not self.__rsi_enabled:
        return

    from vpa.rsi import calculate_rsi

    period = self.__rsi_config.get("period", 14)
    closes = self.myDF["Close"].tolist()
    rsi_values = []

    for i in range(len(closes)):
        rsi_val = calculate_rsi(closes[:i + 1], period)
        rsi_values.append(rsi_val)

    self.myDF["RSI"] = rsi_values
```

#### `detect_rsi_signals(row_index)`

```python
def detect_rsi_signals(self, row_index: int) -> dict:
    """Detect RSI overbought/oversold signals for the given row.

    Returns:
        dict with keys: rsi_signals (list[str]), rsi_signal_score (float)
    """
    if not self.__rsi_enabled:
        return {"rsi_signals": [], "rsi_signal_score": 0.0}

    current_row = self.myDF.iloc[row_index]
    rsi_value = current_row.get("RSI", 50.0)

    if pd.isna(rsi_value):
        return {"rsi_signals": [], "rsi_signal_score": 0.0}

    overbought = self.__rsi_config.get("overbought_threshold", 70)
    oversold = self.__rsi_config.get("oversold_threshold", 30)
    scores = self.__rsi_config.get("scores", {"overbought": -5, "oversold": 5})

    signals_list = []
    total_score = 0.0

    if rsi_value > overbought:
        signals_list.append("RSI Overbought")
        total_score += scores["overbought"]
    elif rsi_value < oversold:
        signals_list.append("RSI Oversold")
        total_score += scores["oversold"]

    self.__logger.log(f"RSI: {rsi_value:.2f}", level="INFO")
    if signals_list:
        self.__logger.log(f"RSI Signals: {signals_list}, Score: {total_score:.2f}", level="INFO")

    return {"rsi_signals": signals_list, "rsi_signal_score": total_score}
```

#### `process_data()` Changes

Add after MA crossover detection in the row loop:

```python
# Step 6.2: Detect RSI signals
rsi_signals = self.detect_rsi_signals(row_position)
signals["rsi_signals"] = rsi_signals["rsi_signals"]
signals["rsi_signal_score"] = rsi_signals["rsi_signal_score"]

# Updated composite
trade_signal = (
    signals["single_candle_signal_score"]
    + signals["trend_signal_score"]
    + signals["multiple_bar_signal_score"]
    + signals["acc_dist_signal_score"]
    + signals["ma_crossover_signal_score"]
    + signals["rsi_signal_score"]
)
```

### Feature Extractor Changes (`vpa/ml_validation/feature_extractor.py`)

#### FEATURE_COLUMNS Update

Insert `"rsi_value"` and `"rsi_signal_score"` before `"composite_score"`:

```python
FEATURE_COLUMNS = [
    # ... existing 24 columns ...
    "acc_dist_score",
    "rsi_value",           # NEW
    "rsi_signal_score",    # NEW
    "composite_score",
    "up_bar_current",
]
```

#### `_extract_feature_vector()` Update

Add RSI computation using closes from period_three deque:

```python
from vpa.rsi import calculate_rsi

# RSI calculation
period_three_closes = [c.close for c in deque_dictionary["period_three"]]
rsi_period = 14  # or from config
rsi_value = calculate_rsi(period_three_closes, rsi_period)

# RSI signal score
rsi_signal_score = 0.0
if rsi_value > 70:
    rsi_signal_score = -5.0
elif rsi_value < 30:
    rsi_signal_score = 5.0

# Updated composite score
composite_score = (
    single_candle_score + trend_score + multiple_bar_score
    + acc_dist_score + rsi_signal_score
)
```

## Data Models

### RSI Configuration Schema

New `"rsi"` section added to `vpa/config/config.json`:

```json
{
  "rsi": {
    "enabled": true,
    "period": 14,
    "overbought_threshold": 70,
    "oversold_threshold": 30,
    "scores": {
      "overbought": -5,
      "oversold": 5
    }
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `true` | Whether RSI signal scoring is active |
| `period` | integer | `14` | RSI lookback window in bars |
| `overbought_threshold` | numeric | `70` | RSI level above which market is overbought |
| `oversold_threshold` | numeric | `30` | RSI level below which market is oversold |
| `scores.overbought` | numeric | `-5` | Score added when RSI > overbought_threshold |
| `scores.oversold` | numeric | `5` | Score added when RSI < oversold_threshold |

### Updated FEATURE_COLUMNS (29 columns, previously 27)

Two new numeric columns inserted before `composite_score`:
- `rsi_value`: Float 0.0-100.0, the raw RSI reading
- `rsi_signal_score`: Float, the threshold-derived score (-5, 0, or +5 with defaults)

### Signal Detection Return Schema

`detect_rsi_signals()` returns:

```python
{
    "rsi_signals": list[str],       # e.g. ["RSI Overbought"] or []
    "rsi_signal_score": float       # e.g. -5.0, 0.0, or 5.0
}
```

## Error Handling

| Condition | Handling |
|-----------|----------|
| Fewer than period+1 closing prices | `calculate_rsi` returns 50.0 (neutral); no signal generated |
| `rsi` config section missing | Defaults applied (enabled=true, period=14, thresholds 70/30) |
| `rsi.enabled` is false | Skip all RSI computation; return score 0.0 |
| `oversold_threshold >= overbought_threshold` | Log WARN, disable RSI for session |
| NaN in pre-computed RSI column | Return score 0.0, no signal |
| All price changes are zero | `calculate_rsi` returns 50.0 (special-case handled) |

## Testing Strategy

### Property Tests (Hypothesis)

| Property | Strategy | Assertion |
|----------|----------|-----------|
| RSI range bounds | Random positive price sequences (0.01-999999.99), length RSI_Period+1 to 500 | 0.0 <= RSI <= 100.0 |
| Monotonic increasing -> RSI > 50 | Sorted ascending prices, length >= period+1 | RSI > 50.0 |
| Monotonic decreasing -> RSI < 50 | Sorted descending prices, length >= period+1 | RSI < 50.0 |

### Example-Based Tests

| Test | Input | Expected |
|------|-------|----------|
| Insufficient data | 10 prices, period=14 | 50.0 |
| All gains | 15 increasing prices | 100.0 |
| All losses | 15 decreasing prices | 0.0 |
| All flat | 15 identical prices | 50.0 |
| Overbought signal | RSI=75 | score = -5, signals = ["RSI Overbought"] |
| Oversold signal | RSI=25 | score = +5, signals = ["RSI Oversold"] |
| Neutral (between thresholds) | RSI=50 | score = 0, signals = [] |
| Config disabled | enabled=false | score = 0, no RSI computed |
| Invalid thresholds | oversold=80, overbought=30 | RSI disabled with warning |

### Integration Test

Verify that `process_data()` composite score includes RSI contribution by constructing a DataFrame where RSI enters overbought/oversold territory and confirming the trade_signal differs by the expected RSI score.

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `vpa/rsi.py` | New | Standalone RSI calculator function |
| `vpa/app_runner.py` | Modified | Add _init_rsi_config, compute_rsi_column, detect_rsi_signals; update process_data |
| `vpa/ml_validation/feature_extractor.py` | Modified | Add rsi_value/rsi_signal_score to FEATURE_COLUMNS and _extract_feature_vector |
| `vpa/config/config.json` | Modified | Add "rsi" configuration section |
| `vpa/tests/test_rsi.py` | New | Property and example-based tests for RSI |

## Correctness Properties

### Property 1: RSI Boundedness

For any valid sequence of positive closing prices of length >= period+1, `calculate_rsi` returns a value v where 0.0 <= v <= 100.0.

**Validates: Requirements 1.3**

### Property 2: Monotonic Bullish

For any strictly increasing price series of length >= period+1, `calculate_rsi` returns a value > 50.0.

**Validates: Requirements 1.4**

### Property 3: Monotonic Bearish

For any strictly decreasing price series of length >= period+1, `calculate_rsi` returns a value < 50.0.

**Validates: Requirements 1.5**

### Property 4: Insufficient Data Neutrality

For any price series of length < period+1, `calculate_rsi` returns exactly 50.0.

**Validates: Requirements 1.2**

### Property 5: Signal Score Consistency

For any RSI value r, overbought threshold ob, oversold threshold os where os < ob: if r > ob then score < 0; if r < os then score > 0; if os <= r <= ob then score = 0.

**Validates: Requirements 2.1, 2.2, 2.3**

### Property 6: Composite Additivity

The composite trade_signal equals the sum of all 6 individual sub-scores with no interaction terms.

**Validates: Requirements 2.5**