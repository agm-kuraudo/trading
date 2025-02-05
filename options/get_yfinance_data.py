import yfinance as yf
import matplotlib.pyplot as plt
import pandas as pd
import os
from sklearn.preprocessing import MinMaxScaler
import sys

# Set the download flag
download_ = False
directory = "../test_data"

if download_:
    # Download data for the most traded stocks
    most_traded_stocks = [
        "TSLA", "NVDA", "AAPL", "META", "LLY", "MSFT", "AMZN", "AMD", "GOOG", "NFLX",
        "BABA", "BA", "BAC", "BBBY", "BBY", "BIDU", "BIIB", "BKNG", "BMY", "BRK.B",
        "C", "CAT", "CCL", "CHTR", "CL", "CMCSA", "COF", "COP", "COST", "CRM",
        "CSCO", "CVS", "CVX", "DAL", "DIS", "DISH", "DOW", "DUK", "EA", "EBAY",
        "F", "FDX", "GE", "GM", "GME", "GS", "HAL", "HD", "HON", "IBM",
        "INTC", "JNJ", "JPM", "KO", "LMT", "LOW", "LUV", "MA", "MCD", "MMM",
        "MO", "MRK", "MS", "MU", "NKE"
    ]

    # Create the directory if it doesn't exist
    os.makedirs(directory, exist_ok=True)

    # Download and save data for each ticker
    for ticker in most_traded_stocks:
        data = yf.download(ticker, start='2023-01-18', end='2025-01-14', interval='1h')
        data.to_csv(f"{directory}/{ticker}_hourly_data.csv")

# Create an empty DataFrame to store the combined data
combined_data = pd.DataFrame()

# Iterate over each file in the directory
for filename in os.listdir(directory):
    if filename.endswith(".csv"):
        print(f"Processing file: {filename}")
        # Read the CSV file, skipping the first two rows and setting the third row as header
        file_path = os.path.join(directory, filename)
        data = pd.read_csv(file_path, skiprows=2, header=None)

        # Manually set the column names
        data.columns = ['Datetime', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']

        # Log the column names
        print(f"Column names in {filename}: {data.columns.tolist()}")

        # Check if 'Datetime' or 'Date' column exists and filter accordingly
        if 'Datetime' in data.columns:
            filtered_data = data[['Datetime', 'Adj Close']]
            filtered_data.rename(columns={'Datetime': 'Date'}, inplace=True)
        elif 'Date' in data.columns:
            filtered_data = data[['Date', 'Adj Close']]
        else:
            print(f"Neither 'Datetime' nor 'Date' column found in {filename}. Exiting with failure.")
            sys.exit(1)

        print(f"Filtered DataFrame shape: {filtered_data.shape}")

        # Add a column for the ticker symbol using .loc
        filtered_data.loc[:, 'Ticker'] = filename.split('_')[0]

        # Append the data to the combined DataFrame
        combined_data = pd.concat([combined_data, filtered_data])

# Ensure the index is unique
combined_data.reset_index(drop=True, inplace=True)

# Normalize the data using MinMaxScaler
scaler = MinMaxScaler()
normalized_data = pd.DataFrame(scaler.fit_transform(combined_data[['Adj Close']]), columns=['Adj Close'])

# Add the non-numeric columns back to the normalized DataFrame
normalized_data['Date'] = combined_data['Date'].values
normalized_data['Ticker'] = combined_data['Ticker'].values

# Remove any rows with missing values (if any)
normalized_data.dropna(inplace=True)

# Save the normalized combined data to a new CSV file without extra newlines and remove the first row if it contains garbage data
with open("../tmp/normalized_combined_data.csv", mode='w', newline='') as file:
    normalized_data.to_csv(file, index=False)

print("The normalized combined dataset has been saved to 'normalized_combined_data.csv'.")

# Plot the close price for one of the tickers (e.g., TSLA)
plt.figure(figsize=(15, 7))
tsla_data = combined_data[combined_data['Ticker'] == 'TSLA']
plt.plot(tsla_data['Date'], tsla_data['Adj Close'])

# Set the title and axis label
plt.title('TSLA Adjusted Close Price', fontsize=16)
plt.xlabel('Date', fontsize=15)
plt.ylabel('Adjusted Close Price', fontsize=15)
plt.xticks(fontsize=15)
plt.yticks(fontsize=15)
plt.legend(['Adj Close'], prop={'size': 15})

# Show the plot
plt.savefig("../tmp/tsla_adj_close_price.png")

from sklearn.preprocessing import MinMaxScaler
import joblib

# Normalize the data using MinMaxScaler
scaler = MinMaxScaler()
normalized_data = pd.DataFrame(scaler.fit_transform(combined_data[['Adj Close']]), columns=['Adj Close'])

# Save the scaler to a file
joblib.dump(scaler, '../tmp/scaler.pkl')