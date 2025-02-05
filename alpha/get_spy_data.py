import yfinance as yf
import datetime

# Define the ticker symbol
ticker_symbol = 'SPY'

# Get the current date
end_date = datetime.datetime.now().date()

# Get the date one year ago from today
start_date = end_date - datetime.timedelta(days=365)

# Fetch the data for the last year
data = yf.download(ticker_symbol, start=start_date, end=end_date)

# Display the data
print(data)