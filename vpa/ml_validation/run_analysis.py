"""CLI entry point for VPA ML validation analysis pipeline."""

import argparse
from pathlib import Path

import numpy as np

from vpa.ml_validation.analysis import AnalysisScript
from vpa.ml_validation.feature_extractor import VPAFeatureExtractor


def main(ticker: str = "SPY", output_dir: str = "ml_validation_output", config_path: str = None):
    """
    Run the complete VPA ML validation pipeline.

    1. Set random seeds (numpy=42)
    2. Generate dataset via VPAFeatureExtractor
    3. Save dataset CSV
    4. Compute baseline accuracy
    5. Run walk-forward ML validation
    6. Extract feature importance
    7. Generate conclusion
    8. Save all output artefacts
    """
    # Step 1: Set random seeds for reproducibility
    np.random.seed(42)

    # Resolve config path
    if config_path is None:
        config_path = str(Path(__file__).parent.parent / "config" / "config.json")

    output_path = Path(output_dir)

    print("VPA ML Validation Pipeline")
    print("==========================")
    print(f"Ticker: {ticker}")
    print(f"Config: {config_path}")
    print(f"Output: {output_path}")
    print()

    # Step 2: Generate dataset
    print("Generating feature dataset (downloading 10 years of data)...")
    extractor = VPAFeatureExtractor(
        config_path=config_path,
        ticker_symbol=ticker,
        enable_extraction=True,
    )
    dataset = extractor.generate_dataset(days=3650)
    print(f"  Dataset generated: {len(dataset)} labelled rows")

    # Get date range for summary
    date_range_start = dataset["date"].iloc[0]
    date_range_end = dataset["date"].iloc[-1]
    valid_rows = len(dataset)
    print(f"  Date range: {date_range_start} to {date_range_end}")
    print()

    # Step 3-8: Run analysis pipeline
    script = AnalysisScript(dataset=dataset, ticker=ticker, output_dir=output_path)

    # Step 4: Compute baseline accuracy
    print("Computing baseline VPA accuracy...")
    baseline_acc = script.compute_baseline_accuracy()
    baseline_pct = baseline_acc * 100
    print(f"  Baseline VPA Accuracy: {baseline_pct:.2f}%")
    print()

    # Step 5: Run walk-forward ML validation
    print("Running walk-forward XGBoost validation (5 splits)...")
    wf_result = script.run_walk_forward_validation(n_splits=5)
    ml_pct = wf_result.mean_accuracy * 100
    ml_std_pct = wf_result.std_accuracy * 100
    print(f"  ML Walk-Forward Accuracy: {ml_pct:.2f}% (+/- {ml_std_pct:.2f}%)")
    if wf_result.skipped_folds:
        print(f"  Skipped folds: {wf_result.skipped_folds}")
    print()

    # Step 6: Extract feature importance
    print("Extracting feature importance...")
    importance_df = script.extract_feature_importance(wf_result.model)
    top_5 = importance_df.head(5)
    print("  Top 5 Features by Importance:")
    for i, row in top_5.iterrows():
        print(f"    {i + 1}. {row['feature_name']} ({row['importance_score']:.4f})")
    print()

    # Step 7: Generate conclusion
    conclusion = script.generate_conclusion(baseline_acc, wf_result.mean_accuracy)
    print(f"Conclusion: {conclusion}")
    print()

    # Step 8: Build summary text and save all outputs
    top_5_text = "\n".join(
        f"  {i + 1}. {row['feature_name']} ({row['importance_score']:.4f})" for i, row in top_5.iterrows()
    )

    summary_text = (
        f"VPA ML Validation Summary\n"
        f"=========================\n"
        f"Ticker: {ticker}\n"
        f"Data Range: {date_range_start} to {date_range_end}\n"
        f"Valid Feature Rows: {valid_rows}\n"
        f"\n"
        f"Baseline VPA Accuracy: {baseline_pct:.2f}%\n"
        f"ML Walk-Forward Accuracy: {ml_pct:.2f}% (+/- {ml_std_pct:.2f}%)\n"
        f"\n"
        f"Top 5 Features by Importance:\n"
        f"{top_5_text}\n"
        f"\n"
        f"Conclusion: {conclusion}\n"
    )

    print("Saving output artefacts...")
    script.save_outputs(
        dataset=dataset,
        importance_df=importance_df,
        summary_text=summary_text,
    )
    print(f"  Saved to: {output_path}")
    print()
    print("Pipeline complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VPA ML Validation Pipeline")
    parser.add_argument("--ticker", type=str, default="SPY", help="Ticker symbol (default: SPY)")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="ml_validation_output",
        help="Output directory (default: ml_validation_output)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to VPA config.json (default: vpa/config/config.json)",
    )

    args = parser.parse_args()
    main(ticker=args.ticker, output_dir=args.output_dir, config_path=args.config)
