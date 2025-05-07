from vpa.app_runner import MarketAnalyzer
import pandas as pd

tickers = []

# Open the file in read mode
with open('D:/projects/trading/vpa/data/SP500-tickers.csv', 'r') as file:
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

# Print the top five rows
print("Top 5 rows:")
print(df_sorted.head(5))

# Print the bottom five rows
print("Bottom 5 rows:")
print(df_sorted.tail(5))
