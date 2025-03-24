"""
Script to Calculate Implied Volatility of an Option

https://amainit.atlassian.net/browse/SP-166

This script retrieves historical stock data for a specified ticker symbol (e.g., AAPL) and calculates the implied volatility of an option based on various financial parameters.
The script uses real or sample data, processes it, and computes the implied volatility using the binomional pricing method

Key Constants:
- TRADING_DAYS: Number of trading days in a year (typically 252).
- PRICING_STEPS: Number of steps for pricing calculations.
- INTEREST_RATE: Annual risk-free interest rate.
- DIVIDEND_YIELD: Annual dividend yield of the stock.

Option Parameters:
- OPTION_EXPIRATION_DATE: Expiration date of the option.
- TICKER: Stock ticker symbol.
- HISTORY_START_DAYS: Number of days before the current date to start retrieving historical data.
- HISTORY_END_DAYS: Number of days before the current date to end retrieving historical data.
- strike_price: Strike price of the option.
- option_type: Type of the option ('call' or 'put').
- OPTION_STYLE: Style of the option ('AMERICAN' or 'EUROPEAN').
- use_real_data: Boolean flag to use real data or sample data.
- option_price: Market price of the option.

Main Script:
- Retrieves and processes historical stock data.
- Calculates the number of trading days left until the option expiration.
- Computes the implied volatility of the option.

Usage:
Run the script to get the implied volatility of the specified option based on the provided parameters.
"""

from utils.utils import get_live_data_from_yfinance, return_sample_data, trading_days_between, get_asset_data, process_data, implied_volatility

# Constants
TRADING_DAYS = 252
PRICING_STEPS = 100
INTEREST_RATE = 0.045  # 4%
DIVIDEND_YIELD = 0.0042  # 0.42%

# Option parameters
OPTION_EXPIRATION_DATE = '2025-04-17'
TICKER = 'AAPL'
HISTORY_START_DAYS = 380
HISTORY_END_DAYS = 0
strike_price = 235
option_type = 'call'  # 'call' or 'put'
OPTION_STYLE = 'AMERICAN'  # or 'EUROPEAN'
use_real_data = True
option_price = 11.7  # Example option price

# Main script
asset_data_frame = get_asset_data(use_real_data, TICKER, HISTORY_START_DAYS, HISTORY_END_DAYS)
asset_data_frame = process_data(asset_data_frame)
current_stock_price = asset_data_frame.iloc[0]['Close']
TRADING_DAYS_LEFT = trading_days_between(asset_data_frame.iloc[0]['Date'], OPTION_EXPIRATION_DATE)
time_to_expiration = TRADING_DAYS_LEFT / TRADING_DAYS

implied_vol = implied_volatility(option_price, option_type, current_stock_price, strike_price, time_to_expiration,
                                 INTEREST_RATE, DIVIDEND_YIELD, PRICING_STEPS, OPTION_STYLE, TRADING_DAYS)
print(f"Implied Volatility: {implied_vol:.2%}")