import json
import os
from datetime import datetime

import pandas as pd

from vpa.app_runner import MarketAnalyzer
from vpa.opportunities import (
    evaluate_ticker,
    format_disabled_report,
    format_opportunities_report,
    load_drawdown_config,
)

tickers = []

# Open the file in read mode

absolute_path = os.path.dirname(__file__)
relative_path = "data/"
full_path = os.path.join(absolute_path, relative_path)

with open(os.path.join(full_path, 'SP500-tickers.csv'), 'r') as file:
    # Read each line in the file
    for line in file:
        # Process the line (e.g., print it)
        tickers.append(line.strip().replace(".", "-"))

print(tickers)

# Load config for drawdown filter
config_full_path = os.path.join(os.path.dirname(__file__), "config", "config.json")
with open(config_full_path, 'r') as f:
    config = json.load(f)

drawdown_config = load_drawdown_config(config)

# Create an empty dataframe with the specified columns
df = pd.DataFrame(columns=['ticker', 'signal_score'])

# Store DataFrames for drawdown filter evaluation
dataframes: dict[str, pd.DataFrame] = {}

for ticker in tickers:
    try:
        analyzer = MarketAnalyzer(config_path="config/config.json", ticker_symbol=ticker, log_level="ERROR")
        signal_score = analyzer.process_data()

        new_row = {'ticker': ticker, 'signal_score': round(signal_score, 1)}
        df.loc[len(df)] = new_row

        # Store DataFrame for drawdown filter evaluation
        dataframes[ticker] = analyzer.get_dataframe()
    except Exception as e:
        print(f"Skipping {ticker}: {e}")

print(df)

# Sort the dataframe by signal_score in descending order
df_sorted = df.sort_values(by='signal_score', ascending=False)

absolute_path = os.path.dirname(__file__)
relative_path = "log/"
full_path = os.path.join(absolute_path, relative_path)
# Get the current date and time
current_time = datetime.now().strftime("%Y%m%d")
log_filename = f"share_output_{current_time}.txt"

log_file = open(os.path.join(full_path, log_filename), "a")

# Print the top five rows
log_file.write("\nTop 5 rows:\n")
log_file.write(df_sorted.head(5).to_string())

# Print the bottom five rows
log_file.write("\nBottom 5 rows:\n")
log_file.write(df_sorted.tail(5).to_string())

# Opportunities section
log_file.write("\n\n")
if drawdown_config["enabled"]:
    opportunities = []
    for ticker, ticker_df in dataframes.items():
        result = evaluate_ticker(
            df=ticker_df,
            drawdown_threshold=drawdown_config["drawdown_threshold"],
            momentum_period=drawdown_config["momentum_period"],
        )
        if result is not None:
            result["ticker"] = ticker
            opportunities.append(result)

    # Sort by drawdown ascending (most negative / largest drawdown first)
    opportunities.sort(key=lambda x: x["drawdown_pct"])

    report_text = format_opportunities_report(opportunities)
    log_file.write(report_text)
else:
    log_file.write(format_disabled_report())

log_file.flush()
log_file.close()






