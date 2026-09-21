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

    # VPAFeatureExtractor requires config_path
    config_path = str(Path("vpa") / "config" / "config.json")
    
    extractor = VPAFeatureExtractor(
        config_path=config_path,
        ticker_symbol=args.ticker,
        enable_extraction=True
    )
    
    print(f"Extracting features for {args.ticker}...")
    df = extractor.generate_dataset(days=args.days)
    
    output_dir = Path("ml_validation_output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{args.ticker}_vpa_features.csv"
    
    df.to_csv(output_path, index=False)
    print(f"Dataset saved to {output_path}")
    
    if args.import_config:
        print(f"Running signal analysis and importing config for {args.ticker}...")
        
        # 1. Run signal analysis
        subprocess.run([
            sys.executable, "-m", "vpa.ml_validation.run_signal_analysis", 
            "--ticker", args.ticker
        ], check=True)
        
        # 2. Run import script
        analysis_csv = output_dir / f"{args.ticker}_signal_analysis.csv"
        subprocess.run([
            sys.executable, "scripts/import_ticker_signals.py", 
            "--ticker", args.ticker,
            "--analysis-csv", str(analysis_csv)
        ], check=True)
        
        print(f"Configuration successfully updated for {args.ticker}")

if __name__ == "__main__":
    main()
