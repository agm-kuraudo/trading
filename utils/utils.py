import os
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def get_live_data_from_yfinance(ticker: str = "SPY", start_days_ago: int = 365, end_days_ago: int = 0) -> pd.DataFrame:

    # Get the current date
    end_date = datetime.now().date() - timedelta(days=end_days_ago)

    # Get the date one year ago from today
    start_date = end_date - timedelta(days=start_days_ago)

    # Fetch the data for the last year
    myDF = yf.download(ticker, start=start_date, end=end_date)

    myDF = myDF.reset_index()

    myDF.columns = myDF.columns.get_level_values(0)

    print(myDF.shape)

    print(myDF.iloc[0].to_dict())

    myDF.columns = ['Date', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
    return myDF

def return_sample_data():
    absolute_path = os.path.dirname(__file__)
    relative_path = "../alpha/data/"
    full_path = os.path.join(absolute_path, relative_path)

    myDF = pd.read_csv(full_path + "spy_data.csv")
    return myDF

def trading_days_between(start_date, end_date):
    # Convert both dates to pandas Timestamps
    start_date = pd.Timestamp(start_date)
    end_date = pd.Timestamp(end_date)

    # Ensure both dates are in the same timezone
    if start_date.tzinfo is None:
        start_date = start_date.tz_localize('UTC')
    else:
        start_date = start_date.tz_convert('UTC')

    if end_date.tzinfo is None:
        end_date = end_date.tz_localize('UTC')
    else:
        end_date = end_date.tz_convert('UTC')

    # Generate a date range between the start and end dates
    date_range = pd.date_range(start=start_date, end=end_date, freq='B')  # 'B' frequency stands for business days
    return len(date_range)