# Trading Bot — Project Doc

This is the structured Project_Doc for the Trading Bot project (Jira SP-348). It
holds the MLL decision record, the migration record, the Application Inventory,
and — while the consolidation work is in flight — a File Classification scratch
section recording how every reviewed path was triaged.

The narrative entry point / naming overview lives in the repository `README.md`,
which links here.

---

## MLL Decision Record

**Decision:** `archive` — archive the entire MLL_Project (`d:\projects\MLL`) and
migrate nothing into the Trading_Repo.

**Decision date:** 2026-07-27

**MLL_Project status at evaluation:** accessible and non-empty (normal evaluation
path; the Req 3.7 inaccessible/empty edge case does not apply). The stock-ML
source evaluated is the three scripts `get_data.py`, `model_trainer.py`, and
`predictor.py` (plus `config/predictor_up_down.json`); the remaining MLL content
is TensorFlow-course learning material and regenerable stock-data artefacts
(see the File Classification section).

### Measured evidence

| Criterion | Measurement | Result |
|---|---|---|
| **File overlap** | % of MLL source files whose **name AND content** duplicate a Trading_Repo file | **0%** (0 of 3) |
| **Functionality overlap** | Count of MLL capabilities already provided by the Trading_Repo | **3 of 3** |
| **Shared dependencies** | Count of third-party packages used by **both** | **6** |

**File overlap — 0% (0 of 3).** The three MLL stock-ML source files
(`get_data.py`, `model_trainer.py`, `predictor.py`) have no name match in the
Trading_Repo (filename search returns only the MLL copies) and therefore no
name-and-content duplicate. The Trading_Repo also contains no TensorFlow/Keras
code at all (`grep tensorflow|keras` across `trading/**/*.py` → zero hits), so no
content match is possible either.

**Functionality overlap — 3 of 3.** Every stock-ML capability in MLL is already
provided by the Trading_Repo, in a form that supersedes it:

| MLL capability (file) | Trading_Repo equivalent | Relationship |
|---|---|---|
| Download + normalise stock OHLCV (`get_data.py`, yfinance → MinMax-scaled combined CSV) | `vpa/ml_validation/feature_extractor.py` (`VPAFeatureExtractor.generate_dataset`) + yfinance ingest / `vpa/market_data` | superseded — richer VPA feature dataset instead of raw OHLCV + scaler |
| Train a next-direction (UP/DOWN) stock model (`model_trainer.py`, TensorFlow/Keras GRU + Keras-Tuner) | `vpa/ml_validation/walk_forward.py` + `run_analysis.py` (XGBoost `TimeSeriesSplit` walk-forward training) | **superseded** — the XGBoost walk-forward validator is the current, maintained, test-covered direction-model trainer |
| Predict next direction/price from recent data (`predictor.py`) | walk-forward model + `vpa/ml_validation/daily_signal.py` prediction path | superseded — prediction is produced by the same XGBoost pipeline |

The XGBoost-based ML work in `vpa/ml_validation/` (`run_analysis.py`,
`walk_forward.py`) is the maintained successor to MLL's older TensorFlow/Keras
GRU stock-prediction attempts. All three MLL capabilities are already met, so
there is no distinct stock-ML purpose left in MLL to migrate.

**Shared dependencies — 6.** Third-party packages used by both the MLL stock-ML
source and the Trading_Repo: `numpy`, `pandas`, `scikit-learn`, `joblib`,
`matplotlib`, `yfinance`. The only MLL-specific dependencies are `tensorflow`,
`keras-tuner`, and `sqlalchemy` — i.e. the TensorFlow/Keras GRU stack that the
Trading_Repo's XGBoost pipeline deliberately replaces, plus a Postgres/SQLAlchemy
path the Trading_Repo covers with `psycopg2` directly. The high dependency
overlap on the shared data-science stack, combined with MLL's unique deps being
exactly the retired TF stack, reinforces that MLL adds no capability the
Trading_Repo lacks.

### Rationale

The three criteria agree: MLL duplicates no Trading_Repo file, every one of its
stock-ML capabilities is already provided by the Trading_Repo, and its only
non-shared dependencies are the TensorFlow/Keras stack that the current XGBoost
pipeline supersedes. MLL therefore retains no distinct stock-ML purpose. The
settled design direction allowed migrating relevant parts, but on the measured
evidence there is nothing worth migrating — the newer `vpa/ml_validation`
XGBoost work replaces MLL's GRU approach outright. The decision is therefore to
archive all of MLL and migrate nothing.

### Disposition

- **Migrated components:** none. Nothing from MLL is migrated into the
  Trading_Repo.
- **Remainder disposition:** `archive` — the entire MLL_Project (the three
  stock-ML scripts and their config, the TensorFlow-course learning material, and
  the regenerable stock-data artefacts) is archived.
- **Archive location / meaning:** removed from the Kiro workspace and no longer
  maintained (optionally the MLL GitHub repository is archived). This is **not**
  an in-repo `archive/` path in the Trading_Repo.

> Because this is an archive-all decision, Workstream 4 (migration, tasks 6.x) has
> no components to migrate; the Migration Record below records "no components
> migrated".

---

## Migration Record

**No components migrated.**

The MLL Decision Record (above) records an **archive-all** decision backed by the
three measured evidence criteria: MLL duplicates no Trading_Repo file (file
overlap 0%), every one of its stock-ML capabilities is already superseded by the
XGBoost work in `vpa/ml_validation` (functionality overlap 3 of 3), and its only
non-shared dependencies are the retired TensorFlow/Keras stack. No MLL component
retains a distinct purpose worth bringing into the Trading_Repo.

| Migrated component | Source (MLL_Project) | Target (Trading_Repo) | Invocable via | Status |
|---|---|---|---|---|
| _(none)_ | — | — | — | — |

Workstream 4 (migration) therefore has nothing to move: no files were migrated,
no imports rewritten, and no new Run_Process was created from MLL. The entire
MLL_Project is archived per the decision above (removed from the Kiro workspace /
no longer maintained; optionally the MLL GitHub repo archived) — not an in-repo
`archive/` path.

---

## Application Inventory

This inventory lists every distinct Application in the Trading Bot project and,
for each, a complete Run_Process following the `ApplicationEntry` /
`Run_Process` schema in the design Data Models: an exact non-blank invocation
command, a complete list of required inputs (each with its source and
mandatory/optional status), and a complete list of produced outputs (each with
its destination). Where an Application cannot be executed in the Trading_Repo —
because its code was removed or it was archived — it is recorded with an
`undetermined` status and a blocking-reason note rather than blank fields
(Req 5.4, 5.5).

All invocation commands are run from the repository root (`d:\projects\trading`),
which is where the first-party `vpa` package resolves and where the relative
config/output paths used by the apps (`vpa/config/config.json`,
`ml_validation_output/`) are anchored. `python` denotes the project virtualenv
interpreter.

> **Status legend:** `documented` = a verified, runnable Run_Process in the
> Trading_Repo. `undetermined` = cannot be executed in the Trading_Repo (removed
> or archived); recorded with a blocking-reason note per Req 5.5.

### Inventory summary

| # | Application | Invocation | Status |
|---|---|---|---|
| 1 | VPA signal generation (daily signal generator) | `python -m vpa.ml_validation.daily_signal --ticker SPY` | documented |
| 2 | VPA SP-500 scan | `python -m vpa.app_all_shares` | documented |
| 3 | ML validation (XGBoost walk-forward pipeline) | `python -m vpa.ml_validation.run_analysis --ticker SPY` | documented |
| 4 | Signal-conditional analysis | `python -m vpa.ml_validation.run_signal_analysis` | documented |
| 5 | Feature extraction | `python scripts/extract_features.py --ticker SPY` | documented |
| 6 | Backtesting (backtest runner) | `python -m vpa.backtesting.run_backtest --ticker SPY` | documented |
| 7 | Market-data backfill | `python scripts/backfill_market_data.py --ticker SPY --interval 1d` | documented |
| 8 | Market-data store verify/bootstrap | `python scripts/verify_market_data_db.py` | documented |
| 9 | Forex analysis (GBPUSD data strand) | `python -m vpa.app_forex` | documented |
| 10 | Ticker-signal config import | `python scripts/import_ticker_signals.py --ticker SPY --analysis-csv <path>` | documented |
| 11 | Options tooling | _(removed in SP-348 task 3)_ | undetermined |
| 12 | MLL | _(archived; no run process in the Trading_Repo)_ | undetermined |

### 1. VPA signal generation (daily signal generator)

The daily VPA signal generator. Downloads recent OHLCV for one ticker,
runs it through the VPA rolling-window feature pipeline, classifies the latest
candle, applies the contrarian inversion, and appends actionable signals to a
per-ticker CSV log. Entry point: `vpa/ml_validation/daily_signal.py`.

- **Status:** `documented`
- **Invocation:** `python -m vpa.ml_validation.daily_signal --ticker SPY [--lookback-days 200] [--output-dir ml_validation_output]`
  - `--ticker` defaults to `SPY`; `--lookback-days` defaults to `200` (valid range 70–3650); `--output-dir` defaults to `ml_validation_output`.

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| VPA config (`PERIOD_ONE/TWO/THREE_LENGTH`, `PERCENTILE_START`, `PERCENTILE_INCREMENTS`) | `vpa/config/config.json` (resolved relative to the working dir) | Mandatory — raises `InsufficientDataError` if absent |
| OHLCV price history for the ticker | `yfinance` download (network), bounded by `--lookback-days` | Mandatory — raises `InsufficientDataError` if the feed returns < 50 valid rows |
| `--ticker` symbol | CLI argument | Optional (defaults to `SPY`) |
| `--lookback-days` | CLI argument | Optional (defaults to `200`) |
| `--output-dir` | CLI argument | Optional (defaults to `ml_validation_output`) |
| Ticker-specific signal rules | `vpa/config/ticker_signals.json` | Optional — missing/invalid file falls back to default confidence mapping |

**Produced outputs**

| Output | Destination |
|---|---|
| Appended actionable signal rows (deduped on `ticker,date,signal_type`) | `{output-dir}/{ticker-lowercase}_daily_signals.csv` (e.g. `ml_validation_output/spy_daily_signals.csv`) |
| Human-readable signal summary / "No high-conviction signal today" | stdout |
| Error messages (missing config, insufficient data, IO) | stderr (exit code 1); invalid args exit code 2 |

### 2. VPA SP-500 scan

Scans the full SP-500 ticker universe, scoring each with the VPA
`MarketAnalyzer` (sourced through the market-data store) and evaluating the
drawdown-opportunity filter, then writes CSV, HTML, and plain-text daily
reports. Entry point: `vpa/app_all_shares.py`.

- **Status:** `documented`
- **Invocation:** `python -m vpa.app_all_shares`
  - Takes no CLI arguments; paths are module defaults relative to `vpa/`.

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| VPA config (incl. drawdown-opportunity config) | `vpa/config/config.json` (`DEFAULT_CONFIG_PATH`) | Mandatory |
| SP-500 ticker universe | `vpa/data/SP500-tickers.csv` (`DEFAULT_TICKERS_PATH`) | Mandatory |
| Per-ticker OHLCV bars | market-data store via `MarketAnalyzer.load_data` → `repo.load_ohlcv` (stored bars + missing-tail yfinance fetch) | Mandatory (store must be reachable; see app 8) |

**Produced outputs**

| Output | Destination |
|---|---|
| Daily scan reports (CSV, HTML, plain text) | `vpa/log/` (`DEFAULT_OUTPUT_DIR`), e.g. `vpa/log/share_output_YYYYMMDD.{csv,html,txt}` |
| "Reports written: …" confirmation line | stdout |

### 3. ML validation (XGBoost walk-forward pipeline)

The ML validation pipeline. Generates the VPA feature dataset, computes the
baseline VPA accuracy, runs a 5-split walk-forward XGBoost validation, extracts
feature importance, and writes the dataset, importance, and summary artefacts.
This is the maintained successor to MLL's old TensorFlow/Keras GRU work (see
MLL Decision Record). Entry point: `vpa/ml_validation/run_analysis.py`.

- **Status:** `documented`
- **Invocation:** `python -m vpa.ml_validation.run_analysis --ticker SPY [--output-dir ml_validation_output] [--config vpa/config/config.json]`
  - `--ticker` defaults to `SPY`; `--output-dir` defaults to `ml_validation_output`; `--config` defaults to `vpa/config/config.json`.

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| VPA config | `vpa/config/config.json` (via `--config`, auto-resolved if omitted) | Mandatory |
| OHLCV price history (~10 years, `days=3650`) | `yfinance` download (network), via `VPAFeatureExtractor.generate_dataset` | Mandatory |
| `--ticker` symbol | CLI argument | Optional (defaults to `SPY`) |
| `--output-dir` | CLI argument | Optional (defaults to `ml_validation_output`) |
| `--config` path | CLI argument | Optional (defaults to `vpa/config/config.json`) |

**Produced outputs**

| Output | Destination |
|---|---|
| Feature dataset CSV, feature-importance CSV, and summary text (via `AnalysisScript.save_outputs`) | `{output-dir}/` (default `ml_validation_output/`) |
| Pipeline progress, accuracies, top-5 features, conclusion | stdout |

### 4. Signal-conditional analysis

Signal-conditional statistical analysis. For each ticker it classifies VPA
signal events, computes forward returns and hit-rate metrics across horizons,
runs significance testing, and writes per-ticker and cross-ticker summary
artefacts. Runs the full built-in universe by default, or a single ticker with
`--ticker`. Entry point: `vpa/ml_validation/run_signal_analysis.py`.

- **Status:** `documented`
- **Invocation:** `python -m vpa.ml_validation.run_signal_analysis [--ticker SPY] [--output-dir ml_validation_output]`
  - With no `--ticker`, runs the full `TICKER_UNIVERSE` (SPY, AAPL, MSFT, NVDA, TSLA, AMD, KO, JNJ, CAT, BA, XOM); with `--ticker <T>`, single-ticker mode (no cross-ticker summary).

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| Per-ticker VPA feature CSV | `{output-dir}/SPY_vpa_features.csv` (SPY) or `{output-dir}/{ticker}/{ticker}_vpa_features.csv` (others) — produced by app 5 (feature extraction) | Mandatory (full-universe mode skips tickers whose CSV is missing; single-ticker mode fails if its CSV is absent) |
| `--ticker` symbol | CLI argument | Optional (absent ⇒ full-universe mode) |
| `--output-dir` | CLI argument | Optional (defaults to `ml_validation_output`) |

**Produced outputs**

| Output | Destination |
|---|---|
| Per-ticker detail CSV | `{output-dir}/{ticker}_signal_analysis.csv` |
| Cross-ticker comparison CSV (full-universe mode only) | `{output-dir}/signal_comparison_summary.csv` |
| Summary text with interpretation table (full-universe mode only) | `{output-dir}/signal_analysis_summary.txt` |
| Progress / completion messages | stdout |

### 5. Feature extraction

Builds a ticker's VPA feature dataset via `VPAFeatureExtractor` and writes it to
the SP-314 layout that apps 4 and 6 read. With `--import-config` it also runs
signal-conditional analysis (app 4, single-ticker) and the ticker-signal import
(app 10) in sequence. Entry point: `scripts/extract_features.py`.

- **Status:** `documented`
- **Invocation:** `python scripts/extract_features.py --ticker SPY [--days 3650] [--import-config]`
  - `--ticker` is required; `--days` defaults to `3650`; `--import-config` is an optional flag.

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| `--ticker` symbol | CLI argument | Mandatory (`required=True`) |
| VPA config | `vpa/config/config.json` (hard-coded in the script) | Mandatory |
| OHLCV price history | `yfinance` download (network), via `VPAFeatureExtractor.generate_dataset(days=…)` | Mandatory |
| `--days` lookback | CLI argument | Optional (defaults to `3650`) |
| `--import-config` flag | CLI argument | Optional (defaults to off; when set, chains apps 4 and 10) |

**Produced outputs**

| Output | Destination |
|---|---|
| VPA feature dataset CSV | `ml_validation_output/{ticker}_vpa_features.csv` (SPY) or `ml_validation_output/{ticker}/{ticker}_vpa_features.csv` (others) |
| (with `--import-config`) signal-analysis CSV + updated ticker-signal config | `ml_validation_output/{ticker}_signal_analysis.csv` and `vpa/config/ticker_signals.json` (via the chained apps) |
| Progress / "Dataset saved to …" messages | stdout |

### 6. Backtesting (backtest runner)

Thin CLI runner for the VPA backtesting engine (SP-317). Loads a ticker's
feature dataset CSV, builds the signal log and price series, runs
`BacktestEngine`, and prints a trade-count summary. Optionally materialises a
scoped OHLCV CSV from the store first. Entry point:
`vpa/backtesting/run_backtest.py`.

- **Status:** `documented`
- **Invocation:** `python -m vpa.backtesting.run_backtest --ticker SPY [--hold-period 10] [--output-dir ml_validation_output] [--export-start YYYY-MM-DD --export-end YYYY-MM-DD]`
  - `--ticker` defaults to `SPY`; `--hold-period` defaults to `10`; `--output-dir` defaults to `ml_validation_output`. `--export-start`/`--export-end` are optional and only take effect together.

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| Per-ticker VPA feature CSV | `{output-dir}/SPY_vpa_features.csv` (SPY) or `{output-dir}/{ticker}/{ticker}_vpa_features.csv` (others) — produced by app 5 | Mandatory (the runner reads a local CSV; no network by default) |
| `--ticker` symbol | CLI argument | Optional (defaults to `SPY`) |
| `--hold-period` (trading days) | CLI argument | Optional (defaults to `10`) |
| `--output-dir` | CLI argument | Optional (defaults to `ml_validation_output`) |
| `--export-start` / `--export-end` range | CLI arguments | Optional — when both set, triggers an offline scoped OHLCV export from the market-data store before running |

**Produced outputs**

| Output | Destination |
|---|---|
| Backtest summary (ticker, hold period, signal/price/trade counts, skips by reason) | stdout |
| (with `--export-start/--export-end`) scoped OHLCV CSV materialised from the store | `{output-dir}/` (via `export_ohlcv_for_backtest`) |

### 7. Market-data backfill

One-off backfill (SP-349) that seeds the dedicated `market_data` store with the
deepest available OHLCV history (`period="max"`) for a ticker/interval, so later
read-through loads only fetch the missing tail. Idempotent via the
`(ticker, interval, ts)` PK. Entry point: `scripts/backfill_market_data.py`.

- **Status:** `documented`
- **Invocation:** `python scripts/backfill_market_data.py --ticker SPY --interval 1d`
  - `--ticker` is required; `--interval` defaults to `1d`.

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| `--ticker` symbol | CLI argument | Mandatory (`required=True`) |
| Deepest OHLCV history | `yfinance` download with `period="max"` (network) | Mandatory |
| DB connection details | `.env` (consumed by `MarketDataRepository` → `vpa/market_data/db.py`) | Mandatory — the live `market_data` Postgres store (the `my_postgres` container on the Raspberry Pi) must be reachable |
| `--interval` tag | CLI argument | Optional (defaults to `1d`) |

**Produced outputs**

| Output | Destination |
|---|---|
| Upserted OHLCV bars | `market_data.ohlcv` table in the dedicated `market_data` Postgres store |
| "Backfilled … inserted=… updated=…" summary | stdout |

### 8. Market-data store verify/bootstrap

Verifies and idempotently bootstraps the dedicated `market_data` store (SP-349):
validates `.env` DB keys, creates the `market_data` database if absent, and
ensures the schema, `ohlcv` table, index, and TimescaleDB objects
(hypertable + compression policy) exist. Returns a non-zero exit code when
config is missing or the store is unreachable, so a scheduler/deploy step can
gate on it. Entry point: `scripts/verify_market_data_db.py`.

- **Status:** `documented`
- **Invocation:** `python scripts/verify_market_data_db.py`
  - Takes no CLI arguments.

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| DB connection details (`REQUIRED_DB_KEYS`) | `.env` (via `_read_db_config` / `validate_env`) | Mandatory — missing keys abort before connecting (exit code 2) |
| Reachable Postgres server with TimescaleDB available | the `my_postgres` container on the Raspberry Pi | Mandatory — unreachable server exits code 1 |

**Produced outputs**

| Output | Destination |
|---|---|
| `market_data` database, `market_data` schema, `ohlcv` table + index, Timescale hypertable + compression policy (created only if absent; idempotent) | the dedicated `market_data` Postgres store |
| Verification result block (`reachable`, `missing_config`, `db_ready`, `schema_ready`, `created`, `error`) | stdout; failure messages to stderr |
| Exit code (`0` ok, `1` unreachable, `2` missing config) | process exit status |

### 9. Forex analysis (GBPUSD data strand)

The forex strand of the analysis stack: `vpa/app_forex.py` retrieves daily
GBPUSD bars via the browserless Dukascopy retriever (`vpa.forex_data`) and runs
the same VPA `MarketAnalyzer` used for equities. Forex is simply another data
source feeding the one analysis stack — not a standalone concern.

> **IG proof-of-concept — archived (SP-348).** A separate IG REST PoC
> (`ig/ig_poc.py`) that authenticated against the IG demo API was a one-off that
> did not go anywhere and was **removed from the working tree in SP-348**
> (recoverable from Git history; it also carried hard-coded demo credentials).
> The forex analysis app below never depended on it. Reframing forex as a pure
> data strand (and the related package naming) is tracked under Epic SP-364
> (SP-365).

- **Status:** `documented`
- **Invocation:** `python -m vpa.app_forex`
  - Takes no CLI arguments.

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| VPA config | `config/config.json` (resolved relative to the working dir) | Mandatory |
| Daily GBPUSD OHLCV bars (≥200 daily bars) | browserless Dukascopy feed (`data.forexsb.com`) via `vpa.forex_data.get_daily_dataframe` (network) | Mandatory |

**Produced outputs**

| Output | Destination |
|---|---|
| VPA trade signal + BUY/SELL/DO-NOT-TRADE recommendation and interval charts | the `MarketAnalyzer` log / chart output under `vpa/log/` |

### 10. Ticker-signal config import

Collapses a per-ticker signal-analysis CSV (one row per signal_type × horizon)
into a single rule per signal type and writes it into the ticker-signal config
consumed by app 1. Normally chained from app 5 (`--import-config`) but also
runnable standalone. Entry point: `scripts/import_ticker_signals.py`.

- **Status:** `documented`
- **Invocation:** `python scripts/import_ticker_signals.py --ticker SPY --analysis-csv ml_validation_output/SPY_signal_analysis.csv`
  - Both `--ticker` and `--analysis-csv` are required.

**Required inputs**

| Input | Source | Mandatory/Optional |
|---|---|---|
| `--ticker` symbol | CLI argument | Mandatory (`required=True`) |
| `--analysis-csv` path | CLI argument — a per-ticker signal-analysis CSV produced by app 4 | Mandatory (`required=True`) |
| Existing ticker-signal config | `vpa/config/ticker_signals.json` (merged into if present; created if absent) | Optional |

**Produced outputs**

| Output | Destination |
|---|---|
| Updated ticker-signal rules for the ticker | `vpa/config/ticker_signals.json` |
| "Updated config for …" confirmation | stdout |

### 11. Options tooling

Listed per the Req 5.1 minimum set. The options tooling (the whole `options/`
package — `options32.py`, `options_payoffs.py`, `options_four_options.py`,
`options_three_options.py`, `calc_greeks.py`, `price_calc.py`,
`implied_volatility_calc.py`, `chart_pl.py`, plus `options/tests/`) and the
option-pricing helpers in `utils.utils` were **removed from the working tree in
SP-348 task 3** (classified as `One_Off_Experiment_Script` variants of a single
options Application; see the File Classification section).

- **Status:** `undetermined`
- **Invocation:** _none in the current Trading_Repo — the entry points no longer exist in the working tree._
- **Blocking reason:** the `options/` package and the `utils.utils` option
  helpers were deleted in task 3, so there is no live, non-blank invocation
  command, input list, or output list to document. The code is **recoverable
  from Git history** (`git log --diff-filter=D --name-only` locates the removal
  commit; `git checkout <prior-commit> -- options/` restores it). If the options
  tooling is revived, a complete Run_Process must be defined at that point:
  consolidate to one canonical entry point (historically `python options/options32.py`),
  with its pricing/market inputs (sources + mandatory/optional) and its chart/data
  outputs (`options/charts/`, `options/data/`) as destinations.

### 12. MLL

Listed per the Req 5.1 minimum set. MLL (the separate `d:\projects\MLL`
TensorFlow/Keras stock-ML project — `get_data.py`, `model_trainer.py`,
`predictor.py`) was evaluated in SP-348 task 5 and **archived with nothing
migrated** (see the MLL Decision Record and Migration Record above). It is
superseded by the XGBoost walk-forward work under `vpa/ml_validation/`
(apps 3 and 4).

- **Status:** `undetermined`
- **Invocation:** _none in the Trading_Repo — MLL is not part of this repository._
- **Blocking reason:** MLL was archived — removed from the Kiro workspace and no
  longer maintained (optionally its GitHub repo archived) — and migrate-nothing,
  so it has no run process inside the Trading_Repo. Its three stock-ML
  capabilities (download/normalise OHLCV, train a next-direction model, predict
  next direction) are already provided, in a maintained form, by the ML
  validation and signal-conditional analysis Applications (apps 3 and 4), which
  therefore stand in as the Trading_Repo run processes for that capability.
  MLL's own scripts additionally relied on hard-coded `/app/...` paths and a
  TensorFlow/Keras + Postgres stack that is not installed or wired into the
  Trading_Repo, so they are not executable here as-is.

---

---

## File Classification (scratch — Workstream 2)

Produced during task 2.1. Every reviewed path in the Trading_Repo
(`d:\projects\trading`) and the MLL_Project (`d:\projects\MLL`) is assigned
exactly one label, with a justification and an intended action. This section is
scratch working for the rationalisation (task 3) and the MLL decision (task 5);
**task 2.1 performs classification only — nothing is removed, archived, or moved
here.**

> **Actual task-3 outcome (recorded after rationalisation — supersedes the
> "proposed actions" in the Trading_Repo tables below).** On the Maintainer''s
> decision, the options tooling was removed **in full** rather than archived
> piecemeal: the entire `options/` package (all 7 exploratory `options/*.py`
> scripts, the shared `options_payoffs.py`, and both `options/tests/` files) and
> the two legacy tracked CSVs (`options/data/forex_data.csv`,
> `options/data/vix_data.csv`) were deleted via `git rm`
> (commits `306dab3`, `ebbfa59`). Because that left the option-pricing helpers in
> `utils/utils.py` orphaned (used only by the deleted options tests), those were
> also removed, trimming `utils/utils.py` down to `trading_days_between` (still
> used by `vpa.market_data`). All removals are recoverable from Git history. The
> gitignored generated artefacts (`ml_validation_output/`, `log/`, `vpa/log/`,
> `test_data/`, `options/charts/`) were cleaned from the working tree (no commit
> needed). No `Dead_Code` was found, so nothing was removed on that basis. The
> `retained`-labelled first-party `vpa/`, `scripts/`, `ig/`, and remaining
> `utils/` source is unchanged. The per-path tables below are the task-2.1
> *classification* and are preserved as the audit trail of what was reviewed; the
> options rows'' "proposed" dispositions were escalated to full deletion as noted
> here.

**Labels** (per design Component 2 / glossary):

| Label | Meaning |
|---|---|
| `Dead_Code` | Source no longer referenced/executed by any current app or test |
| `One_Off_Experiment_Script` | Exploratory script not part of a documented repeatable workflow |
| `Stale_Artefact` | Generated output no longer needed (e.g. `ml_validation_output/`, old `log/`, superseded generated files) |
| `retained` | Still needed by an application or test |

**Intended action** is one of `kept`, `removed`, or `archived` — recorded as the
*proposed* disposition for task 3; the actual removal/archival and the Git-backed
commits happen there, not here.

### Reference-check method (for `Dead_Code`)

A module/script is labelled `Dead_Code` only if no retained Application entry
point or test imports or invokes it. This was checked by grepping across `vpa/`,
`options/`, `ig/`, `scripts/`, `utils/`, and the test suites
(`vpa/tests/`, `options/tests/`) for imports and invocations.

Findings from the reference check:

- No file in the Trading_Repo imports or invokes any MLL_Project module
  (`get_data`, `model_trainer`, `predictor`) — grep for
  `model_trainer|predictor|get_data|from MLL|import MLL` across all Trading_Repo
  `.py` files returned **zero** hits. The MLL stock-ML code is entirely external
  to the Trading_Repo's live paths.
- Every Trading_Repo first-party module under `vpa/`, `options/`, `ig/`,
  `scripts/`, `utils/` is reachable from an Application entry point or a test
  (confirmed by import/invocation grep). No Trading_Repo source file qualifies as
  `Dead_Code`.
- `ml_validation_output/`, `log/`, `vpa/log/`, `test_data/`, `options/charts/`,
  `options/data/`, all `*.png`, and all `*.pyc`/`__pycache__` are **gitignored**
  (see `.gitignore`) — they are regenerable generated output, not tracked source.
  `git ls-files` confirms zero tracked files under `ml_validation_output/`,
  `log/`, and `test_data/` (the only exceptions are two legacy tracked CSVs,
  `options/data/forex_data.csv` and `options/data/vix_data.csv`, committed before
  the ignore rule).

### Trading_Repo (`d:\projects\trading`)

Grouped by area. Git-tracked source directories are `ig/`, `options/`,
`scripts/`, `utils/`, `vpa/` plus root config/docs. Generated/ignored output
directories are listed separately.

#### Tracked first-party source — all `retained`

| Path | Label | Justification | Action |
|---|---|---|---|
| `vpa/` (package: `__init__.py`, `app.py`, `app_runner.py`, `app_all_shares.py`, `app_forex.py`, `dss_bressert.py`, `rsi.py`, `opportunities.py`, `execution.py`) | `retained` | Core VPA signal generation + app entry points; heavily imported (e.g. `rsi` 283 refs, `dss_bressert` 122, `opportunities` 96, `app_runner` 47) and exercised by `vpa/tests/`. | kept |
| `vpa/backtesting/` (14 modules: `engine.py`, `run_backtest.py`, `report_backtest.py`, `models.py`, `pnl.py`, `metrics.py`, `equity_curve.py`, `exit_strategy.py`, `reporting.py`, `signal_log_builder.py`, `variations.py`, `data_export.py`, `config.py`, `__init__.py`) | `retained` | Backtesting Application; covered by `vpa/tests/backtesting/` (11 test modules). | kept |
| `vpa/ml_validation/` (`analysis.py`, `conclusion.py`, `daily_signal.py`, `exceptions.py`, `feature_extractor.py`, `run_analysis.py`, `run_signal_analysis.py`, `signal_analysis.py`, `walk_forward.py`, `__init__.py`) | `retained` | ML validation + VPA signal Applications; covered by `vpa/tests/ml_validation/` (10 test modules). | kept |
| `vpa/forex_data/` (`aggregator.py`, `decoder.py`, `errors.py`, `feed.py`, `retriever.py`, `__init__.py`) | `retained` | Forex data subsystem feeding `app_forex`; covered by `vpa/tests/forex_data/` (17 test modules). | kept |
| `vpa/market_data/` (`db.py`, `ohlcv_ingest.py`, `repository.py`, `__init__.py`) | `retained` | Market-data store (SP-349); covered by `vpa/tests/test_market_data_*`, `test_ohlcv_ingest_*`, property tests. | kept |
| `vpa/reports/` (`models.py`, `renderers.py`, `writers.py`, `__init__.py`) | `retained` | Report rendering used by apps; covered by `vpa/tests/test_reports.py`. | kept |
| `vpa/config/` (`settings.py`, `__init__.py`) | `retained` | App configuration; covered by `vpa/tests/test_settings.py`. | kept |
| `vpa/tests/` (all `test_*.py`, `conftest.py`, helpers) | `retained` | The regression suite itself — the `pytest -m ""` gate depends on it. | kept |
| `scripts/extract_features.py` | `retained` | Feature-extraction Application entry point (writes `ml_validation_output/<T>/...`); listed in the seed Application Inventory. | kept |
| `scripts/backfill_market_data.py` | `retained` | Market-data backfill tool; covered by `vpa/tests/test_backfill_spy_acceptance.py`. | kept |
| `scripts/verify_market_data_db.py` | `retained` | DB verification tool; covered by `vpa/tests/test_verify_market_data_db_idempotency.py`. | kept |
| `scripts/import_ticker_signals.py` | `retained` | Ticker-signal import tool; referenced by `extract_features.py --import-config` workflow and `test_ticker_config.py`. | kept |
| `utils/utils.py` | `retained` | Shared helpers (`implied_volatility`, `price_option`, `get_asset_data`, …) imported directly by `options/tests/`. | kept |
| `ig/ig_poc.py` | `retained` | IG/forex proof-of-concept — a standalone runnable Application in the seed inventory (Req 5.1 minimum set). Not imported elsewhere by design (it is an entry point). | kept |

#### Options tooling (`options/`)

The options tests import from `utils.utils`, not from the `options/*.py` scripts,
so the scripts are standalone runnable analysis tools rather than imported
libraries. They collectively make up the "options tooling" Application in the
seed inventory (Req 5.1). The numbered/variant scripts are exploratory variants
and are flagged as `One_Off_Experiment_Script` candidates for task 3 to decide
(prefer archiving over deletion for anything ambiguous).

| Path | Label | Justification | Action |
|---|---|---|---|
| `options/tests/test_price_calc.py`, `options/tests/test_implied_volatility.py` | `retained` | Part of the regression suite; import from `utils.utils`. | kept |
| `options/options_payoffs.py` | `retained` | `OptionStrategy` imported by `options_four_options.py` and `options_three_options.py`; shared library for the options tooling. | kept |
| `options/options32.py` | `One_Off_Experiment_Script` | Standalone analysis script; not imported by any module or test; numbered-variant naming indicates exploratory iteration. Candidate options-tooling entry point — task 3 to confirm whether it is the canonical options Application or an archivable variant. | archived (proposed; confirm in task 3) |
| `options/options_four_options.py` | `One_Off_Experiment_Script` | Standalone scenario script (imports `options_payoffs`); exploratory variant, not referenced by tests. | archived (proposed; confirm in task 3) |
| `options/options_three_options.py` | `One_Off_Experiment_Script` | Standalone scenario script (imports `options_payoffs`); exploratory variant, not referenced by tests. | archived (proposed; confirm in task 3) |
| `options/calc_greeks.py` | `One_Off_Experiment_Script` | Standalone greeks calculation script; not imported or tested. | archived (proposed; confirm in task 3) |
| `options/price_calc.py` | `One_Off_Experiment_Script` | Standalone pricing script; the tested pricing logic lives in `utils.utils`, so this is an exploratory duplicate entry point. | archived (proposed; confirm in task 3) |
| `options/implied_volatility_calc.py` | `One_Off_Experiment_Script` | Standalone IV script; the tested IV logic lives in `utils.utils`. | archived (proposed; confirm in task 3) |
| `options/chart_pl.py` | `One_Off_Experiment_Script` | Standalone P/L charting script; not imported or tested. | archived (proposed; confirm in task 3) |

> Note: all `options/*.py` scripts are currently *runnable* and none are broken
> imports, so none meet the strict `Dead_Code` bar (no live path *needs* them,
> but they are themselves entry points). They are labelled
> `One_Off_Experiment_Script` because they are exploratory variants outside a
> single documented repeatable workflow. Task 3 should consolidate the options
> tooling to one canonical entry point and archive the rest.

#### Root config / docs

| Path | Label | Justification | Action |
|---|---|---|---|
| `pyproject.toml`, `requirements.txt` | `retained` | Project/dependency/test configuration (defines the `pytest -m ""` gate). | kept |
| `README.md` | `retained` | Project narrative/entry point (reframed by task 1 — out of scope here). | kept |
| `.gitignore`, `.env.example` | `retained` | Repo hygiene / env template. | kept |
| `.env` | `retained` | Local secrets (gitignored); not committed. Flagged as credential-like — must not be staged. | kept |
| `.github/workflows/ruff.yml` | `retained` | CI lint workflow. | kept |
| `docs/SP-324-historical-data-storage-spike.md` | `retained` | Spike record with persistent value. | kept |
| `docs/project.md` | `retained` | This Project_Doc (created by task 2.1). | kept |

#### Generated / ignored output (not tracked source)

These are `.gitignore`d regenerable outputs. They are `Stale_Artefact` by label,
but because they are untracked they do not appear in Git history and need no
Git-backed removal — task 3 can simply clean the working tree if desired. The
*directory conventions* (`ml_validation_output/`, `vpa/log/`) are retained because
live Applications write to them; only the current *contents* are stale.

| Path | Label | Justification | Action |
|---|---|---|---|
| `ml_validation_output/` contents (68 files/dirs: `*_vpa_features.csv`, `*_signal_analysis.csv`, `*_equity.csv`, `*_trades.csv`, `*_summary.txt`, per-ticker subdirs) | `Stale_Artefact` | Regenerable pipeline output (gitignored); reproduced by the ML validation / backtesting Applications. Directory convention itself is retained. | removed (working-tree clean-up; optional) |
| `log/SPY_dss_bressert.png`, `vpa/log/` contents | `Stale_Artefact` | Generated chart/log output (gitignored `*.png` / `vpa/log`). | removed (optional) |
| `options/charts/` (25 files) | `Stale_Artefact` | Generated option P/L charts (gitignored). | removed (optional) |
| `options/data/` (7 files) | `Stale_Artefact` | Mostly gitignored generated inputs. Exception: `options/data/forex_data.csv` and `options/data/vix_data.csv` are tracked legacy fixtures — task 3 to confirm whether they are needed before any removal. | kept pending confirm |
| `test_data/` (96 files) | `Stale_Artefact` | Gitignored local test fixtures/scratch data; regenerable, zero tracked files. | removed (optional) |
| `__pycache__/`, `*.pyc`, `.coverage`, `.pytest_cache/`, `.ruff_cache/`, `.hypothesis/` | `Stale_Artefact` | Tooling caches / coverage output (gitignored). | removed (optional) |

### MLL_Project (`d:\projects\MLL`)

The MLL_Project splits cleanly into two groups: a small **stock-ML tooling** core
(relevant to the Trading Bot, candidate for migration in Workstream 4) and a large
**ML-course learning** body plus bulk data/image artefacts (not relevant to the
Trading Bot). None of it is imported by the Trading_Repo (confirmed by grep —
zero cross-references).

> The final migrate/archive dispositions for MLL are **recorded in the MLL
> Decision Record (task 5.1) and Migration Record (task 6.1)**, not here. The
> actions below are the proposed labels/dispositions from this review; task 2.1
> does not move or delete anything.

#### Stock-ML tooling (relevant — candidate for migration)

| Path | Label | Justification | Action |
|---|---|---|---|
| `get_data.py` | `retained` (relevant) | Stock OHLCV downloader/normaliser (yfinance → combined/normalised CSV + MinMax scaler). Stock-ML capability overlapping `vpa/ml_validation` concerns; selected as a migration candidate. Hardcoded `/app/...` paths and an embedded Postgres block would need rework on migration. | migrate candidate (task 5/6 to confirm) |
| `model_trainer.py` | `retained` (relevant) | TensorFlow/Keras GRU time-series trainer with Keras-Tuner hyperparameter search; the core stock price/direction model. Migration candidate. Uses hardcoded `/app/...` paths. | migrate candidate (task 5/6 to confirm) |
| `predictor.py` | `retained` (relevant) | Loads a trained model + scalers and predicts next-direction/price from recent yfinance data. Migration candidate. Uses hardcoded `/app/...` paths. | migrate candidate (task 5/6 to confirm) |
| `config/predictor_up_down.json` | `retained` (relevant) | Config consumed by `predictor.py`; moves with it if migrated. | migrate candidate (task 5/6 to confirm) |
| `build/Dockerfile`, `build/build_ml_image.ps1` | `One_Off_Experiment_Script` | Container build for the MLL stock-ML image; infrastructure tied to the `/app/...` layout. Likely superseded by the Trading_Repo's own tooling — task 5/6 to decide keep-on-migrate vs archive. | archived (proposed; confirm in task 5/6) |

#### ML-course learning material (not relevant to Trading Bot)

| Path | Label | Justification | Action |
|---|---|---|---|
| `learning/Chapter1.py` … `Chapter11.py`, `chapter9.py`, `chapter10.py`, `Chapter3_ImageDataGenerator.py`, `Chapter3_TransferLearning.py`, `Ch2_Callback.py`, `main.py` (20 root `.py`/misc) | `One_Off_Experiment_Script` | TensorFlow course exercises (image/NLP chapters); exploratory learning, not part of any Trading Bot workflow and not imported anywhere. | archived (with MLL per task 5) |
| `learning/MLL.ipynb` | `One_Off_Experiment_Script` | Course notebook; exploratory, not a repeatable Trading Bot workflow. | archived (with MLL per task 5) |
| `learning/horse-or-human/` (1283 files), `learning/horse-or-human.zip`, `learning/validation-horse-or-human.zip` | `Stale_Artefact` | Image-classification training dataset for a course exercise; irrelevant to stock trading and large. | archived (with MLL per task 5) |
| `learning/tmp/` (`irish-lyrics-eof.txt`, `sarcasm.json`, …), `learning/newtestdata/`, `learning/meta.tsv`, `learning/vecs.tsv` | `Stale_Artefact` | Course scratch inputs/embeddings output; not relevant. | archived (with MLL per task 5) |

#### MLL stock data / generated artefacts (regenerable)

| Path | Label | Justification | Action |
|---|---|---|---|
| `stock_data/` (65 `*_hourly_data.csv`) | `Stale_Artefact` | Downloaded hourly OHLCV per ticker; regenerable via `get_data.py`. | archived (with MLL per task 5) |
| `new_stock_data/` (62 `*_hourly_data.csv`) | `Stale_Artefact` | Newer downloaded hourly OHLCV; regenerable. | archived (with MLL per task 5) |
| `data/` (`combined_data.csv`, `normalized_combined_data.csv`, `new_normalized_combined_data.csv`, `apple_hourly_data.csv`, `SPY_hourly_data.csv`) | `Stale_Artefact` | Combined/normalised intermediate datasets produced by `get_data.py`; regenerable. | archived (with MLL per task 5) |
| `tmp/` (`training_loss.png`, `learning_rate_tuning.png`, `training_validation_loss.png`, `tsla_adj_close_price.png`) | `Stale_Artefact` | Generated training/plot output. | archived (with MLL per task 5) |
| `.gitignore` | `retained` | MLL repo hygiene (kept with the archived MLL repo). | kept |

### Classification summary

| Area | retained | One_Off_Experiment_Script | Stale_Artefact | Dead_Code |
|---|---|---|---|---|
| Trading_Repo tracked source | all `vpa/`, `scripts/`, `utils/`, `ig/`, `options/tests/`, `options_payoffs.py`, root config/docs | 7 `options/*.py` variant scripts | — | **0** |
| Trading_Repo generated output | directory conventions kept | — | `ml_validation_output/`, `log/`, `vpa/log/`, `test_data/`, `options/charts/`, `options/data/*` (2 tracked CSVs pending confirm), caches | — |
| MLL stock-ML core | `get_data.py`, `model_trainer.py`, `predictor.py`, `config/predictor_up_down.json` (migrate candidates) | `build/` | — | — |
| MLL learning material | — | `learning/*.py`, `MLL.ipynb` | `horse-or-human/`, course scratch data | — |
| MLL stock data | — | — | `stock_data/`, `new_stock_data/`, `data/`, `tmp/` | — |

**Key findings:**

- **No `Dead_Code` found.** Every tracked Trading_Repo source module is reachable
  from an Application entry point or test (verified by import/invocation grep
  across `vpa/`, `options/`, `ig/`, `scripts/`, `utils/`, and the test suites).
- **MLL is fully disjoint** from the Trading_Repo — zero cross-imports — which
  supports the settled "archive + migrate relevant parts" direction (task 5.1).
  The relevant parts are the three stock-ML scripts plus their config.
- **Stale artefacts are overwhelmingly gitignored generated output** in both
  repos, so working-tree cleanup needs no Git-backed removal; the two legacy
  tracked `options/data/*.csv` fixtures are the only tracked artefacts and are
  flagged for confirmation before any removal.
- The 7 `options/*.py` scripts are exploratory variants of one options-tooling
  Application and are proposed for consolidation/archival in task 3.
