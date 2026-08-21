# VPA Trading Bot

Volume Price Analysis (VPA) signal detection and trading automation for equities.

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
|   +-- config/config.json      # VPA configuration (thresholds, periods)
|   +-- ml_validation/
|   |   +-- daily_signal.py     # Daily signal generator (SP-315)
|   |   +-- feature_extractor.py # VPA feature extraction pipeline
|   |   +-- signal_analysis.py  # Signal-conditional analysis (SP-314)
|   |   +-- analysis.py         # ML baseline analysis (SP-312)
|   |   +-- walk_forward.py     # Walk-forward validation
|   +-- app_runner.py           # Core MarketAnalyzer
|   +-- app.py                  # Candle class, ADX, acc/dist detection
|   +-- rsi.py                  # RSI calculation
+-- ml_validation_output/       # Signal logs and analysis output
+-- requirements.txt
+-- .kiro/specs/                 # Feature specifications
```
