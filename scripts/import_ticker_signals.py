import argparse
import json
import pandas as pd
from pathlib import Path

def get_rule(row):
    # Mapping logic
    hit_rate = row.get("hit_rate")
    p_value = row.get("p_value")
    
    if pd.isna(hit_rate) or pd.isna(p_value) or p_value >= 0.05:
        return {"adjusted_direction": "NONE"}

    if hit_rate < 0.45:
        # Contrarian: invert
        return {
            "confidence_level": "High" if hit_rate < 0.35 else "Medium-High",
            "adjusted_direction": "BUY", # Assuming bearish signal inversion
            "suggested_hold_days": 10
        }
    elif hit_rate >= 0.60:
        return {
            "confidence_level": "High",
            "adjusted_direction": "BUY",
            "suggested_hold_days": 10
        }
    elif 0.55 < hit_rate < 0.60:
        return {
            "confidence_level": "Low-Medium",
            "adjusted_direction": "BUY",
            "suggested_hold_days": 10
        }
    return {"adjusted_direction": "NONE"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--analysis-csv", required=True)
    args = parser.parse_args()

    config_path = Path("vpa/config/ticker_signals.json")
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)
    else:
        config = {}

    df = pd.read_csv(args.analysis_csv)
    
    ticker_config = {}
    for _, row in df.iterrows():
        sig_type = row["signal_type"]
        ticker_config[sig_type] = get_rule(row)
        
    config[args.ticker.upper()] = ticker_config
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Updated config for {args.ticker}")

if __name__ == "__main__":
    main()
