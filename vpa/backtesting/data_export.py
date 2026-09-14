"""On-demand scoped OHLCV export for offline backtesting/ML (SP-349, Task 8.5).

The SP-317 backtesting engine is intentionally **pure and offline**: it reads a
local feature dataset CSV (``ml_validation_output/{ticker}/{ticker}_vpa_features.csv``)
and never touches the network. This module does **not** change that engine.

Instead it gives the offline backtester a network-free way to *materialise* the
exact OHLCV range it needs from the persistent market-data store, by delegating
to :meth:`vpa.market_data.repository.MarketDataRepository.export_ohlcv`. The
export is **scoped to the requested range** (never a standing full-history flat
file — the Pi's disk is constrained, Req 3.6) and is written under the same
``ml_validation_output/{ticker}/`` convention the runner already reads from.

Wiring here is additive and opt-in: existing behaviour (reading an
already-present local CSV) is unchanged. A caller that wants a fresh scoped file
calls :func:`export_ohlcv_for_backtest` first, then points the backtest at the
returned path.

No network / no live DB is required to *import* this module: the repository's
connection factory is only invoked when an export is actually requested.

Requirements: 5.4, 3.5, 3.6.
"""

from __future__ import annotations

import os

from vpa.market_data.repository import MarketDataRepository

# Default root matching the SP-314 dataset convention used by ``run_backtest``.
DEFAULT_OUTPUT_ROOT = "ml_validation_output"


def _default_out_path(ticker: str, interval: str, output_root: str) -> str:
    """Resolve the default scoped-export path for a ticker.

    Mirrors the SP-314 dataset layout: SPY lives directly under the root, every
    other ticker is nested under ``{root}/{ticker}/``. The exported OHLCV file is
    named ``{ticker}_ohlcv.csv`` so it does not collide with the
    ``{ticker}_vpa_features.csv`` feature dataset the engine consumes.
    """
    if ticker == "SPY":
        return os.path.join(output_root, f"{ticker}_ohlcv.csv")
    return os.path.join(output_root, ticker, f"{ticker}_ohlcv.csv")


def export_ohlcv_for_backtest(
    ticker: str,
    interval: str,
    start,
    end,
    out_dir: str | None = None,
    fmt: str = "csv",
    repo: MarketDataRepository | None = None,
) -> str:
    """Export a scoped OHLCV range from the store for an offline backtest run.

    Delegates to :meth:`MarketDataRepository.export_ohlcv`, which reads the range
    **offline** (``get_ohlcv``) and writes only the requested ``[start, end]``
    window — never a standing full-history copy (Req 3.5, 3.6). The backtest
    engine itself is untouched; it simply reads the file this returns.

    Args:
        ticker: Instrument symbol (e.g. ``"SPY"``).
        interval: Bar interval tag (e.g. ``"1d"``).
        start: Inclusive range start (anything the repository accepts).
        end: Inclusive range end.
        out_dir: Optional directory to write into. When provided, the file is
            written as ``{out_dir}/{ticker}_ohlcv.{ext}``. When omitted, the
            SP-314 default layout under ``ml_validation_output/`` is used.
        fmt: Output format — ``"csv"`` (default) or ``"parquet"``.
        repo: Optional repository instance (mainly for tests / injecting a fake
            connection factory). Defaults to a new :class:`MarketDataRepository`.

    Returns:
        The path of the scoped file that was written.
    """
    repo = repo or MarketDataRepository()

    ext = "parquet" if fmt.lower() == "parquet" else "csv"

    if out_dir is not None:
        path = os.path.join(out_dir, f"{ticker}_ohlcv.{ext}")
    else:
        default = _default_out_path(ticker, interval, DEFAULT_OUTPUT_ROOT)
        # Swap the extension if a parquet export was requested.
        path = default if ext == "csv" else f"{os.path.splitext(default)[0]}.{ext}"

    # Ensure the destination directory exists so the export write does not fail on
    # a first-time nested ticker path (scoped, on-demand — no standing structure).
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    return repo.export_ohlcv(ticker, interval, start, end, path, fmt=fmt)
