"""CLI entry point for VPA signal-conditional analysis."""

import argparse
from pathlib import Path

import numpy as np

from vpa.ml_validation.signal_analysis import SignalConditionalAnalyzer


def main(output_dir: str = "ml_validation_output", ticker: str | None = None):
    """Run the VPA signal-conditional analysis pipeline.

    When ``ticker`` is given, run single-ticker mode: analyse only that ticker
    and write its per-ticker CSV (no cross-ticker summary). Otherwise run the
    full multi-ticker universe pipeline.
    """
    np.random.seed(42)
    analyzer = SignalConditionalAnalyzer(output_dir=Path(output_dir))

    if ticker is None:
        analyzer.run()
        return

    metrics = analyzer.analyse_ticker(ticker)
    analyzer.write_per_ticker_csv(ticker, metrics)
    print(f"Analysis complete for {ticker}. Output written to: {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VPA Signal-Conditional Analysis")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="ml_validation_output",
        help="Output directory (default: ml_validation_output)",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default=None,
        help="Analyse a single ticker instead of the full universe",
    )
    args = parser.parse_args()
    main(output_dir=args.output_dir, ticker=args.ticker)
