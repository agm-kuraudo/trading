import os
from vpa.app_runner import MarketAnalyzer
import pandas as pd
from datetime import datetime

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

# Create an empty dataframe with the specified columns
df = pd.DataFrame(columns=['ticker', 'signal_score'])

for ticker in tickers:
    analyzer = MarketAnalyzer(config_path="config/config.json", ticker_symbol=ticker, log_level="ERROR")
    signal_score = analyzer.process_data()

    new_row = {'ticker': ticker, 'signal_score': round(signal_score, 1)}
    df.loc[len(df)] = new_row

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

log_file.flush()
log_file.close()






