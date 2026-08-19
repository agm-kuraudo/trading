"""CLI entry point for VPA signal-conditional analysis."""

import argparse
from pathlib import Path

import numpy as np

from vpa.ml_validation.signal_analysis import SignalConditionalAnalyzer


def main(output_dir: str = "ml_validation_output"):
    """Run the full VPA signal-conditional analysis pipeline."""
    np.random.seed(42)
    analyzer = SignalConditionalAnalyzer(output_dir=Path(output_dir))
    analyzer.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VPA Signal-Conditional Analysis")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="ml_validation_output",
        help="Output directory (default: ml_validation_output)",
    )
    args = parser.parse_args()
    main(output_dir=args.output_dir)
