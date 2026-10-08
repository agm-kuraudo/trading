import argparse
import subprocess
import sys
from pathlib import Path

from vpa.ml_validation.feature_extractor import VPAFeatureExtractor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--days", type=int, default=3650)
    parser.add_argument("--import-config", action="store_true", help="Run analysis and import config after extraction")
    args = parser.parse_args()

    # Normalise once so the feature path, analysis step and config key all agree.
    ticker = args.ticker.upper()

    # VPAFeatureExtractor requires config_path
    config_path = str(Path("vpa") / "config" / "config.json")

    extractor = VPAFeatureExtractor(config_path=config_path, ticker_symbol=ticker, enable_extraction=True)

    print(f"Extracting features for {ticker}...")
    df = extractor.generate_dataset(days=args.days)

    output_dir = Path("ml_validation_output")
    # SignalConditionalAnalyzer.load_dataset expects SPY at the root and every
    # other ticker under its own subfolder; mirror that layout here.
    feature_dir = output_dir if ticker == "SPY" else output_dir / ticker
    feature_dir.mkdir(parents=True, exist_ok=True)
    output_path = feature_dir / f"{ticker}_vpa_features.csv"

    df.to_csv(output_path, index=False)
    print(f"Dataset saved to {output_path}")

    if args.import_config:
        print(f"Running signal analysis and importing config for {ticker}...")

        # 1. Run signal analysis (single-ticker mode)
        subprocess.run([sys.executable, "-m", "vpa.ml_validation.run_signal_analysis", "--ticker", ticker], check=True)

        # 2. Run import script. write_per_ticker_csv writes the analysis CSV to
        # the output_dir root regardless of ticker, so read it from there.
        analysis_csv = output_dir / f"{ticker}_signal_analysis.csv"
        subprocess.run(
            [
                sys.executable,
                "scripts/import_ticker_signals.py",
                "--ticker",
                ticker,
                "--analysis-csv",
                str(analysis_csv),
            ],
            check=True,
        )

        print(f"Configuration successfully updated for {ticker}")


if __name__ == "__main__":
    main()
