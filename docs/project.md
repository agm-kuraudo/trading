# Trading Bot — Project Doc

This is the structured Project_Doc for the Trading Bot project (Jira SP-348). It
holds the MLL decision record, the migration record, the Application Inventory,
and — while the consolidation work is in flight — a File Classification scratch
section recording how every reviewed path was triaged.

The narrative entry point / naming overview lives in the repository `README.md`,
which links here.

---

## MLL Decision Record

> _Placeholder — populated by task 5.1. This section will record the single
> recorded decision on the fate of the separate MLL_Project (`d:\projects\MLL`),
> the three measured evidence criteria (file overlap, functionality overlap,
> shared dependencies), the decision date in ISO 8601, and the decision-specific
> fields._

_Not yet recorded._

---

## Migration Record

> _Placeholder — populated by task 6.1. This section will record each
> Migrated_Component with its source path in the MLL_Project, its target path in
> the Trading_Repo, how it is made invocable, and its migration status._

_Not yet recorded._

---

## Application Inventory

> _Placeholder — populated by task 8.1. This section will list every distinct
> Application (at minimum: MLL, options tooling, IG/forex tooling, VPA signal
> generation, ML validation, backtesting) with a complete Run_Process:
> exact invocation command, required inputs (with source + mandatory/optional),
> and produced outputs (with destination)._

_Not yet recorded._

---

## File Classification (scratch — Workstream 2)

Produced during task 2.1. Every reviewed path in the Trading_Repo
(`d:\projects\trading`) and the MLL_Project (`d:\projects\MLL`) is assigned
exactly one label, with a justification and an intended action. This section is
scratch working for the rationalisation (task 3) and the MLL decision (task 5);
**task 2.1 performs classification only — nothing is removed, archived, or moved
here.**

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
