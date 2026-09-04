# VPA Trading Bot

Volume Price Analysis (VPA) signal detection and trading automation for equities.

## Architecture & Data Flow

This project grew in stages, and the signal logic now lives in **two separate paths** that do not share code. Knowing which path you are looking at is the key to understanding the codebase.

### The two signal paths

**1. Live path — `MarketAnalyzer` (`vpa/app_runner.py`)**

Used for on-demand / live analysis of a single ticker.

```
config.json ─► vpa.config.settings.load_settings() ─► MarketAnalyzer.process_data()
                 ├─ detect_signals()              (single-candle, trend, multiple-bar, acc/dist)
                 ├─ detect_ma_signals()            (MA crossover + price position)
                 ├─ detect_rsi_signals()           (RSI overbought/oversold)
                 └─ detect_price_vs_sma_signals()  (price vs SMA — SP-326)
                        │
                        ▼
                 composite `trade_signal` = sum of all the sub-scores
```

`config.json` remains the operator-facing format, while `vpa.config.settings.load_settings()` validates it and exposes typed settings to both application paths. `process_data()` walks the DataFrame row by row and returns the final scalar `trade_signal`. Each signal follows the same pattern: an `_init_<x>_config()` method (reads its typed config section, sets an `enabled` flag), a `detect_<x>_signals(row_index)` method returning `{"<x>_signals": [...], "<x>_signal_score": n}`, and a line in the `process_data()` summation.

**2. ML / backtest path — `VPAFeatureExtractor` (`vpa/ml_validation/feature_extractor.py`)**

Used for machine-learning validation and historical backtesting. This path **reimplements** the signal logic independently of `MarketAnalyzer` (it has its own `_detect_signals()` and computes RSI inline). It does **not** call `MarketAnalyzer`.

```
yfinance OHLCV ─► VPAFeatureExtractor.generate_dataset()
                    │  (per row: percentiles, _detect_signals(), ADX, acc/dist,
                    │   RSI, then _extract_feature_vector())
                    ▼
              Feature_Dataset (DataFrame / CSV)
                 columns = FEATURE_COLUMNS + metadata (date, OHLC) + next_day_direction
                    │
        ┌───────────┴───────────────────────────────┐
        ▼                                            ▼
  ML validation                              Backtesting
  (run_analysis.py:                          (run_backtest.py)
   XGBoost, walk-forward)                       │
                                                ├─ signal_analysis.classify_signals()
                                                │     maps feature columns ─► SignalType
                                                │     (e.g. composite_score ≥ threshold
                                                │      ⇒ STRONG_BULLISH)
                                                ├─ signal_log_builder (Signal_Log + Price_Series)
                                                └─ BacktestEngine.run() ─► trades / hit-rates

  Daily signal generator (daily_signal.py) also consumes the Feature_Dataset:
  it reuses VPAFeatureExtractor + classify_last_row() ─► SignalType ─►
  contrarian-inverted SignalRecords ─► CSV log.
```

### Why this matters

Because the two paths are separate implementations, **a signal added to `MarketAnalyzer` does not automatically appear in the ML/backtest path.** To flow a new signal end-to-end you generally have to:

1. Add it to `MarketAnalyzer` (live path).
2. Add matching columns to `VPAFeatureExtractor.FEATURE_COLUMNS` (and its `_extract_feature_vector`) so it lands in the Feature_Dataset.
3. Optionally add a `SignalType` + rule in `signal_analysis.classify_signals()` (and confidence entries in `daily_signal.py`) to make it a first-class backtestable/daily signal.

> **Known drift:** the two "composite" scores are **not** currently identical. `MarketAnalyzer`'s `trade_signal` includes `ma_crossover` and `price_vs_sma`; the feature extractor's `composite_score` sums only single-candle, trend, multiple-bar, acc/dist, and RSI. Reconciling them (and wiring `price_vs_sma` into the ML/backtest path) is tracked in **SP-340**.

### Key files

| File | Path | Role |
|---|---|---|
| `MarketAnalyzer` | `vpa/app_runner.py` | Live signal detection + composite `trade_signal` |
| `VPAFeatureExtractor` | `vpa/ml_validation/feature_extractor.py` | Builds the Feature_Dataset for ML/backtest |
| `SignalConditionalAnalyzer` | `vpa/ml_validation/signal_analysis.py` | Maps feature columns to `SignalType`; hit-rate analysis |
| `daily_signal.py` | `vpa/ml_validation/daily_signal.py` | Daily generator (Feature_Dataset ► contrarian signals) |
| `BacktestEngine` | `vpa/backtesting/engine.py` | Simulates trades from a Signal_Log + Price_Series |
| `run_backtest.py` | `vpa/backtesting/run_backtest.py` | CLI: dataset CSV ► backtest trade-count summary |
| `settings.py` | `vpa/config/settings.py` | Loads and validates JSON into typed configuration settings |
| `app.py` | `vpa/app.py` | `Candle`, ADX, accumulation/distribution helpers |

## Setup

```
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

## Daily Signal Generator

Produces actionable trading signals based on VPA signal-conditional analysis (SP-314).
Key insight: bearish VPA signals on SPY are reliable contrarian indicators.

### Usage

```bash
# Default: analyse SPY with 200 days lookback
python -m vpa.ml_validation.daily_signal

# Specify ticker and lookback
python -m vpa.ml_validation.daily_signal --ticker AAPL --lookback-days 120

# Custom output directory
python -m vpa.ml_validation.daily_signal --ticker SPY --output-dir ./signals
```

### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| --ticker | SPY | Any yfinance-supported ticker symbol |
| --lookback-days | 200 | Calendar days of data to download (70-3650) |
| --output-dir | ml_validation_output | Directory for signal log CSV |

### Signal Interpretation

Signals are based on VPA classification with contrarian inversion applied:

| VPA Signal | Direction | Confidence | Hit Rate (10d) |
|---|---|---|---|
| Distribution | BUY (inverted) | High | 74% |
| Strong Bearish | BUY (inverted) | Medium-High | 69% |
| Strong Bullish | BUY (as-is) | Low-Medium | 66% |
| Accumulation | BUY (as-is) | Low | 60% |
| Acc Test Pass | No signal | Inconclusive | - |

> **Note:** Confidence levels are derived from SPY-specific analysis. Other tickers
> use the same rules as defaults until per-ticker config is available (SP-322).

### Output

**Console:** Prints signal summary or "No high-conviction signal today" with the date.

**CSV Log:** Appends to `ml_validation_output/{ticker}_daily_signals.csv` with columns:
ticker, date, signal_type, original_direction, adjusted_direction, confidence_level, suggested_hold_days

Duplicate signals (same ticker + date + signal_type) are automatically skipped on re-runs.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (signal or no signal) |
| 1 | Fatal error (data unavailable, config missing, IO failure) |
| 2 | Invalid arguments (bad lookback-days range, unrecognized args) |

### Scheduling

The signal generator is designed to run daily after US market close (4pm ET / 9pm GMT).

**Windows Task Scheduler:**

1. Open Task Scheduler, create a new task
2. Trigger: Daily at 21:30 (GMT) or 16:30 (ET)
3. Action: Start a program
   - Program: `d:\projects\trading\.venv\Scripts\python.exe`
   - Arguments: `-m vpa.ml_validation.daily_signal --ticker SPY`
   - Start in: `d:\projects\trading`

**Linux (cron):**

```bash
# Run at 21:30 GMT daily (after US market close)
30 21 * * 1-5 cd /path/to/trading && .venv/bin/python -m vpa.ml_validation.daily_signal --ticker SPY
```

**Multiple tickers:**

```bash
# Run for several tickers sequentially
30 21 * * 1-5 cd /path/to/trading && .venv/bin/python -m vpa.ml_validation.daily_signal --ticker SPY && .venv/bin/python -m vpa.ml_validation.daily_signal --ticker AAPL && .venv/bin/python -m vpa.ml_validation.daily_signal --ticker MSFT
```

> **Future:** SP-319 will determine the long-term scheduling/delivery approach
> (replacing Rundeck, consolidated morning report, etc.)

## Other Modules

| Module | Purpose | CLI |
|--------|---------|-----|
| `vpa/ml_validation/run_analysis.py` | ML validation pipeline (XGBoost, walk-forward) | `python -m vpa.ml_validation.run_analysis` |
| `vpa/ml_validation/run_signal_analysis.py` | Signal-conditional hit-rate analysis | `python -m vpa.ml_validation.run_signal_analysis` |
| `vpa/app_runner.py` | Core VPA MarketAnalyzer | Import only |
| `vpa/opportunities.py` | Momentum/drawdown opportunity filter | Import only |

## Project Structure

```
trading/
+-- vpa/
|   +-- config/config.json       # Operator-facing VPA configuration (thresholds, periods, signal weights)
|   +-- config/settings.py       # Typed configuration models and JSON loader
|   +-- ml_validation/           # ML / backtest signal path
|   |   +-- feature_extractor.py # Builds the Feature_Dataset (reimplements signal logic)
|   |   +-- signal_analysis.py   # Feature columns -> SignalType; hit-rate analysis (SP-314)
|   |   +-- daily_signal.py      # Daily signal generator (SP-315)
|   |   +-- analysis.py          # ML baseline analysis (SP-312)
|   |   +-- walk_forward.py      # Walk-forward validation
|   +-- backtesting/             # Backtesting engine (SP-317)
|   |   +-- engine.py            # BacktestEngine simulation loop
|   |   +-- signal_log_builder.py # Feature_Dataset -> Signal_Log + Price_Series
|   |   +-- run_backtest.py      # CLI runner (trade-count summary)
|   +-- app_runner.py            # Core MarketAnalyzer (live signal path)
|   +-- app.py                   # Candle class, ADX, acc/dist detection
|   +-- rsi.py                   # RSI calculation
+-- ml_validation_output/        # Feature datasets, signal logs, analysis output
+-- requirements.txt
+-- .kiro/specs/                 # Feature specifications
```
