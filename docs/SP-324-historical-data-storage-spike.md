# SP-324 — Historical Market Data Storage (Spike)

**Type:** Time-boxed spike — decision only, no full build.
**Project/Space:** Side Projects
**Status:** Recommendation ready for review.

## 1. Problem

`yfinance` gives limited historical depth for some intervals, and every run re-fetches from Yahoo rather than accumulating data. By capturing and storing bars as we run, we build a proprietary dataset that grows deeper over time and is not capped by the provider lookback window — improving data for backtesting and ML.

This spike decides *how* to store that data before committing to a build.

> **Roadmap note (drives this spike):** everything today is daily bars, but the **next release adds 15-minute, 1-hour and 4-hour intervals**. Intra-day is exactly where yfinance's lookback wall is real and where volume climbs, so the storage choice is made with intra-day in mind — not just today's daily usage. See §5.1.

## 2. Current data access pattern (as-is)

All market data in the `trading` project comes from `yfinance`, fetched fresh on every run. There is **no persistence layer** today — no CSV cache of fetched data, no SQLite, no Postgres. The only on-disk data files are static fixtures/tickers lists (`vpa/data/*.csv`).

Call sites found:

| File | Function | Interval | Notes |
|---|---|---|---|
| `vpa/app_runner.py` | `MarketAnalyzer.load_data()` | daily (`1d` default) | Main scan path. `yf.download(ticker, start, end, auto_adjust=True)`. Window = `max` of enabled feature lookbacks (`_get_data_days()`). |
| `vpa/app_all_shares.py` | `run_scan()` | daily | Loops the SP500 list, builds a `MarketAnalyzer` per ticker → one `yf.download` per ticker per run. |
| `vpa/ml_validation/feature_extractor.py` | `generate_dataset()` | daily | Downloads ~`days` calendar days for a ticker to build the labelled feature CSV. |
| `vpa/ml_validation/daily_signal.py` | download step | daily | `yf.download(ticker, start, end, auto_adjust=True)`. |
| `utils/utils.py` | `get_live_data_from_yfinance()` | daily | Helper used by options/volatility code. |
| `vpa/app_forex.py` | `get_daily_dataframe()` | daily | GBPUSD comes from the Dukascopy retriever, **not** yfinance. |

Key observations:
- **Everything is daily bars *today*.** No intra-day intervals are used yet, but **15m/1h/4h land next release** (see §5.1). For daily bars the practical constraint is *cumulative history depth* and *repeated re-fetching* rather than a hard wall; for the incoming intra-day intervals the provider lookback wall is real and hard (`yfinance` ≈ 15m 60d, 1h 730d), which is the main driver of this recommendation.
- **Column normalisation is already duplicated** across `app_runner`, `daily_signal`, and `utils` (MultiIndex flatten + rename to `Date, Open, High, Low, Close, Volume`). A storage layer is a natural place to centralise this.
- **The SP500 scan is the heavy caller**: ~500 `yf.download` calls per daily run. Caching/persisting removes most of that network load once history is warm.

## 3. How the daily run works

- Scheduled via **Rundeck** jobs (`vpa/jobs/*.yaml`) — e.g. *Daily VPA Check for SPY* runs every day at 08:30.
- Jobs invoke shell scripts (`vpa/scripts/start_vpa*.sh`) that activate `/usr/local/trading/.venv` and run `app_runner.py` / `app_all_shares.py` / `app_forex.py` on the **always-on Raspberry Pi** (ARM/Linux).
- So the storage target must run cleanly on **ARM Linux (Pi)** and on **Windows x64** (dev). Cross-platform is a hard requirement.

## 4. Backtesting / ML impact (SP-317 and ML work)

- The backtesting engine (SP-317) is **pure and offline**: `run_backtest.py` reads a local feature CSV (`ml_validation_output/{ticker}/{ticker}_vpa_features.csv`) and never touches the network or yfinance. The engine, pnl, metrics, equity_curve modules all explicitly avoid I/O.
- ML feature extraction (`feature_extractor.py`) is the piece that pulls from yfinance today.
- Implication: a storage layer should sit **behind the fetch step** (a repository/loader that returns the same normalised OHLCV DataFrame the callers already expect). The backtester keeps reading its CSVs; the win is that ML/feature generation and the scan read from accumulated storage instead of re-downloading, and can eventually exceed the provider window.

## 5. Storage options compared

Scored against the WORD-relevant axes: work effort, complexity, cross-platform, deployment. Assume the daily-bar OHLCV shape today **plus the incoming intra-day intervals** and the Pi + Windows targets.

### 5.1 Why intra-day changes the stakes (15m / 1h / 4h)

The next release adds 15m, 1h and 4h. This shifts storage from "nice optimisation" to "must capture, and capture promptly":

- **The provider wall is real for intra-day.** yfinance caps intra-day history hard — roughly **15m ≈ 60 days, 1h ≈ 730 days**. (`4h` is **not** a native yfinance interval, so it must be **resampled from 1h**.) Unlike daily bars — which can always be re-pulled over years — an intra-day bar that ages past the window is **gone for good if we didn't capture it**. This makes continuous capture urgent and makes an early backfill valuable before the 60-day 15m window rolls off.
- **Volume rises ~7–26× per ticker per day** (≈7 hourly, ≈26 fifteen-minute bars vs 1 daily). Across ~500 tickers over years this is low tens of millions of rows — comfortable for indexed Postgres, but enough that columnar compression starts to matter (see Timescale in Option E).
- **Timezone and session handling become real.** Daily bars are just dates; intra-day bars need a consistent UTC bar-open timestamp, market-session awareness, and care with the partial in-progress last bar. This is a design point for the build, called out in §7.
- **Disk is constrained on the Pi.** Duplicating intra-day history into a second Parquet/CSV copy alongside the DB is not affordable. That kills the "keep a full flat-file export" idea for intra-day (see §6).

### Option A — Flat files (Parquet, partitioned by ticker/interval)

- **Shape:** one Parquet file (or dataset dir) per ticker+interval, e.g. `data/ohlcv/interval=1d/ticker=SPY.parquet`.
- **Pros:** zero infra; pandas-native (`read_parquet`/`to_parquet`); columnar + compressed so full-history reads are fast; trivially portable; great for the offline backtester and ML which are already file-oriented.
- **Cons:** incremental append means read-modify-write the whole file (Parquet has no in-place append) — fine at daily-bar volumes, clumsy at scale; dedup/gap handling is hand-rolled in pandas; no concurrent-writer safety; no query engine (you load then filter).
- **Cross-platform:** excellent (pure Python via `pyarrow`; ARM wheels exist).
- **Deployment:** nothing to deploy; just a data directory (and a backup rule).
- **Effort:** low.

### Option B — CSV

- **Pros:** simplest possible; human-readable; already the project's lingua franca.
- **Cons:** no types, slow/large at depth, easy to corrupt on partial writes, worst option for dedup/gap handling. Fine as an export format, poor as the system of record.
- **Verdict:** rejected as primary store; keep CSV only as the backtester's existing input/export.

### Option C — SQLite

- **Pros:** real SQL, `UNIQUE(ticker, interval, ts)` constraint gives clean dedup via `INSERT ... ON CONFLICT`; single file, zero server; cross-platform; stdlib driver.
- **Cons:** single-writer locking (okay for one daily job, not for parallel writers); not the existing project DB; another store to back up; analytical scans slower than columnar Parquet for full-history ML pulls.
- **Cross-platform:** excellent.
- **Deployment:** trivial (a file).
- **Effort:** low–medium.

### Option D — PostgreSQL (reuse the existing Betfair instance)  ⭐

- **Context:** Postgres is **already installed and running** as a Docker container `my_postgres` on the `my_trading_network`, DB `bf_trader`, deployed on the same Pi. Betfair connects with `psycopg2.connect(host=DB_HOST, ...)` reading `DB_HOST/PORT/NAME/USER/PWD` from `.env` (see `bf_trader_py/BFDriver.get_local_db_details` and `scripts/verify_db.py`). Deploy is `scripts/deploy.sh` → `docker compose up -d --build`.
- **Pros:** infra already exists and is battle-tested on the Pi; proper concurrency, constraints and upserts (`ON CONFLICT (ticker, interval, ts) DO NOTHING/UPDATE`) make incremental append and dedup trivial; indexed range queries by ticker/date; one backup/monitoring story shared with Betfair; grows well beyond provider limits; SQL is convenient for gap detection.
- **Cons:** cross-project coupling — trading would depend on the Betfair-owned Postgres (use a separate DB/schema, e.g. `trading` schema or a `market_data` DB, to keep ownership clean); network dependency for the offline backtester (mitigate with an **on-demand scoped export**, not a standing flat-file copy — see §6); a little more connection/config plumbing than a file.
- **Cross-platform:** excellent (client is `psycopg2`/`psycopg`; server already runs on the Pi).
- **Deployment:** low marginal cost — the container and compose/deploy tooling already exist; add a schema + `.env` wiring.
- **Effort:** medium (schema, a small repository module, config). Lower *infra* effort than it looks because the server is already there.

### Option E — Dedicated time-series DB (TimescaleDB / InfluxDB / DuckDB)

- **TimescaleDB** is a Postgres extension — bolts onto the existing `my_postgres` instance (not a separate store) and gives hypertables + native columnar compression ideal for intra-day OHLCV. With 15m/1h/4h landing next release, this moves from "later" to a **decision to make now**: whether to enable the extension when provisioning, rather than migrating after the table has grown. Compression also directly addresses the Pi's disk constraint.
- **InfluxDB** — separate server, new ops burden, weaker fit for relational joins; overkill.
- **DuckDB** — excellent analytical companion that queries Parquet directly; better seen as a *query layer* than a system of record.
- **Verdict:** **evaluate TimescaleDB up front** as an extension on the existing Postgres (see follow-up ticket 6). InfluxDB/DuckDB remain out of scope.

### Summary matrix

| Option | Work effort | Complexity | Cross-platform | Deployment | Dedup/append | Fit for depth |
|---|---|---|---|---|---|---|
| A. Parquet | Low | Low | Excellent | None | Manual (pandas) | Good |
| B. CSV | Low | Low | Excellent | None | Poor | Poor |
| C. SQLite | Low–Med | Low | Excellent | Trivial | Native (constraint) | OK |
| **D. Postgres (reuse)** | **Med** | **Med** | **Excellent** | **Low (exists)** | **Native (upsert)** | **Excellent** |
| E. TimescaleDB (extension on D) | Med | Med–High | Excellent | Low (same container) | Native | Excellent (intra-day) |
| InfluxDB / DuckDB | Med–High | Med–High | Good | Higher | Native | Out of scope |

## 6. Recommendation

**Use the existing PostgreSQL instance (Option D) as the system of record, with a thin repository layer, and evaluate enabling the TimescaleDB extension (Option E) on the same instance for the intra-day intervals.**

Rationale:
- The dominant cost of a DB approach — standing up and operating a server on the Pi — is **already paid** by Betfair. We reuse `my_postgres`, the `.env` config convention, and the `docker compose`/`deploy.sh` deployment path.
- Native `ON CONFLICT` upserts make **incremental capture and dedup** clean and correct, which is the crux of this ticket — and matters even more once intra-day bars arrive.
- With **15m/1h/4h coming next release**, the provider lookback wall becomes real: intra-day bars must be captured before they roll off, and continuous capture is the whole point. Postgres (optionally Timescale) is the right fit for that growing, frequently-appended dataset.
- Keeps one backup/monitoring story across Side Projects rather than a new data silo.

Keep ownership clean: create a **separate database or schema** for trading market data (e.g. `market_data` DB or a `trading` schema), not tables inside Betfair's domain.

**On flat-file fallback:** For daily-only data, Parquet would have been a viable self-contained fallback. **We are not taking that path for intra-day.** The Pi's disk is already constrained, and duplicating a growing intra-day dataset into a second flat-file copy alongside the DB is not affordable. The database is the single system of record. If the offline backtester (SP-317) or ML training needs a network-free input, generate a **scoped, on-demand export** (specific ticker/interval/date range) rather than maintaining a standing full-history file copy — so we never keep two full copies of intra-day history.

## 7. Proposed schema (OHLCV + interval + ticker)

Single canonical bars table, keyed to prevent duplicate bars and make incremental append idempotent:

```sql
CREATE TABLE IF NOT EXISTS market_data.ohlcv (
    ticker      TEXT        NOT NULL,
    interval    TEXT        NOT NULL,          -- '1d','4h','1h','15m', ...
    ts          TIMESTAMPTZ NOT NULL,          -- bar OPEN time, UTC (intra-day safe)
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION,
    adjusted    BOOLEAN     NOT NULL DEFAULT TRUE,  -- auto_adjust=True today
    source      TEXT        NOT NULL DEFAULT 'yfinance',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, interval, ts)
);
CREATE INDEX IF NOT EXISTS ix_ohlcv_ticker_interval_ts
    ON market_data.ohlcv (ticker, interval, ts);
```

Incremental append (idempotent):

```sql
INSERT INTO market_data.ohlcv (ticker, interval, ts, open, high, low, close, volume, adjusted, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (ticker, interval, ts) DO UPDATE
    SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
        close=EXCLUDED.close, volume=EXCLUDED.volume, ingested_at=now();
```

- **Duplicates:** prevented by the PK; re-running a day is safe.
- **Gaps:** detected by comparing stored bar timestamps against an expected trading-session calendar; backfill fetches only the missing ranges. Daily gaps can reuse `utils.trading_days_between`; **intra-day gaps need session-aware expected timestamps** (market open/close, holidays), not just business days.
- **Adjusted prices:** current code uses `auto_adjust=True`. Store adjusted as the default; if raw is needed later, add a second `adjusted=FALSE` series rather than mutating rows.
- **The schema is already interval-agnostic:** `(ticker, interval, ts)` with `ts` as `TIMESTAMPTZ` handles 15m/1h/4h with **no structural change** — that is why it is recommended as-is ahead of the intra-day release.
- **Timezone / session handling (intra-day):** store `ts` as the **bar open time in UTC**; do not persist a partial in-progress final bar (wait until it closes, or overwrite it on the next run via the upsert). This is trivial for daily bars but a real design point for 15m/1h.
- **4h is derived, not native:** yfinance does not offer a 4h interval, so store `interval='4h'` by **resampling from stored 1h bars** and tag `source` accordingly (e.g. `'resampled:1h'`) so it is clear the series is derived rather than provider-native.
- **TimescaleDB (if enabled):** make the table a hypertable partitioned on `ts` and turn on native compression for older chunks — keeps intra-day fast and small on the Pi's limited disk without changing the schema or the upsert.

## 8. Backfill vs. incremental capture

- **Backfill (one-off):** for each ticker+interval, pull the deepest history yfinance will give and upsert it — seeds the store. **Intra-day is time-critical:** the 15m window is only ~60 days, so backfill should run **as soon as intra-day capture ships** to bank history before it rolls off. Daily backfill is not urgent (re-pullable any time).
- **Incremental (daily/intra-day):** the scheduled run, after (or instead of) its live fetch, upserts the latest bars. Because the scan already downloads a window per ticker, the cheapest first step is to **persist what it already fetches** — no extra network calls. Intra-day intervals may warrant a **more frequent capture cadence** than the single daily 08:30 job so that 15m bars are banked well within the 60-day window; the exact cadence is a build decision.
- **Serving reads:** a loader returns the normalised `Date, Open, High, Low, Close, Volume` DataFrame (per ticker+interval) from storage, fetching+persisting only the missing tail from yfinance. This centralises the MultiIndex/rename normalisation currently duplicated in `app_runner`, `daily_signal`, and `utils`.

## 9. Definition of Done for this spike

- [x] Options compared with pros/cons (effort, complexity, cross-platform, deployment) — sections 5–6.
- [ ] Recommendation documented in a **Confluence page in the Side Projects space** — this file is the source; paste into Confluence (Atlassian MCP is disabled, so it can't be pushed automatically).
- [ ] Follow-up implementation tickets raised — proposed in section 10.
- [x] Stopped at the recommendation; no full build.

## 10. Proposed follow-up tickets (Side Projects)

1. **Provision trading market-data store in Postgres** — create `market_data` schema/DB on `my_postgres`, add the `ohlcv` table + index, wire `.env` (`DB_*`) into the trading project, add a connection/verify helper mirroring Betfair's. *(Tech Story, ~3 pts)*
2. **Market-data repository + normalisation layer** — a module exposing `get_ohlcv(ticker, interval, start, end)` and `upsert_bars(df)` that returns the existing normalised DataFrame and centralises the MultiIndex/rename logic. *(Tech Story, ~5 pts)*
3. **Persist bars on the daily scan** — have `app_runner`/`app_all_shares` upsert fetched bars (no extra network calls); read-through the repository so warm history isn't re-downloaded. *(Story, ~5 pts)*
4. **Backfill job** — one-off deepest-history pull per ticker/interval into the store, with gap detection. Run intra-day backfill **immediately** once intra-day capture ships (15m window ≈ 60 days). *(Task, ~3 pts)*
5. **On-demand scoped export for offline backtesting/ML** — export a specific ticker/interval/date range to a temp CSV/Parquet on request, so SP-317 and ML training can run network-free **without** keeping a standing full-history copy (Pi disk is constrained). *(Tech Story, ~3 pts)*
6. **Evaluate + enable TimescaleDB on `my_postgres`** — decide up front (ahead of intra-day) whether to enable the extension, make `ohlcv` a hypertable on `ts`, and configure compression for older chunks. *(Spike → Tech Story)*
7. **Intra-day capture support (15m / 1h / 4h)** — extend the fetch/repository layer for intra-day intervals: session-aware gap detection, UTC bar-open timestamps, partial-last-bar handling, **4h resampled from 1h**, and a suitable capture cadence within the yfinance intra-day windows. Aligns with the next release. *(Story, ~8 pts — likely splits)*

## 11. Jira housekeeping (manual — Atlassian MCP disabled)

The following could not be automated and need doing in Jira:
- Add **SP-324** to the current active sprint and move it to **In Progress**.
- SP-324 is a **spike** → time-boxed, no story points.
- On completion: add a comment linking this Confluence page, then move to **Done** (this is a decision spike with no deployable code, so Done — not Mostly Done — is appropriate once the page and follow-up tickets exist).
- Raise the follow-up tickets in section 10 in the **Side Projects** project.
