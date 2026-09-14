"""One-off backfill of the deepest available OHLCV history (SP-349).

Seeds the dedicated ``market_data`` store with the deepest history yfinance will
give us for a ticker/interval, so subsequent read-through loads only ever fetch the
missing tail. Unlike the read-through path (which fetches bounded ranges), this
script deliberately requests ``period="max"`` — the deepest available history — and
idempotently upserts it. Re-running adds no duplicate bars (guaranteed by the PK
``(ticker, interval, ts)`` in ``MarketDataRepository.upsert_bars``).

The flow mirrors the design's "backfill (seed deepest history)" pseudocode:

    raw    = yf.download(ticker, period="max", auto_adjust=True, progress=False)
    df     = normalise_yf_download(raw)
    repo   = MarketDataRepository()
    result = repo.upsert_bars(df, ticker, interval)

``yf.download`` is called directly (rather than ``ohlcv_ingest.fetch_yf``) because
``fetch_yf`` takes explicit ``start``/``end`` bounds, whereas the backfill wants
``period="max"``; both then delegate to the same ``normalise_yf_download``.

Invocation (run standalone from the repo root; hits the network + live store):

    python scripts/backfill_market_data.py --ticker SPY --interval 1d

Platform note: the config-driven store this writes to is the ``my_postgres``
container on the always-on Raspberry Pi (Linux/ARM), the shared Postgres host.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yfinance as yf

from vpa.market_data.ohlcv_ingest import normalise_yf_download
from vpa.market_data.repository import MarketDataRepository


def backfill(ticker: str, interval: str) -> dict:
    """Backfill the deepest available history for ``ticker``/``interval``.

    Downloads the deepest history yfinance offers (``period="max"``), normalises it
    to the canonical OHLCV shape, and idempotently upserts it into the store.

    Args:
        ticker: The instrument symbol (e.g. ``"SPY"``).
        interval: The bar interval tag (e.g. ``"1d"``).

    Returns:
        The ``{"inserted": n, "updated": m}`` dict from
        :meth:`MarketDataRepository.upsert_bars`.
    """
    raw = yf.download(ticker, period="max", auto_adjust=True, progress=False)
    df = normalise_yf_download(raw)
    repo = MarketDataRepository()
    return repo.upsert_bars(df, ticker, interval)


def _parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments for the backfill script.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        The parsed ``argparse.Namespace`` with ``ticker`` and ``interval``.
    """
    parser = argparse.ArgumentParser(
        description="Backfill the deepest available OHLCV history into the market_data store.",
    )
    parser.add_argument(
        "--ticker",
        required=True,
        help="Instrument symbol to backfill (e.g. SPY).",
    )
    parser.add_argument(
        "--interval",
        default="1d",
        help="Bar interval to store the history under (default: 1d).",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """CLI entry point: backfill the deepest history and print the result.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (``0`` on success).
    """
    args = _parse_args(argv)
    result = backfill(args.ticker, args.interval)
    print(f"Backfilled {args.ticker} ({args.interval}): " f"inserted={result['inserted']}, updated={result['updated']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
