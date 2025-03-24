"""
Script to Calculate Option Price Using Binomial Model
https://amainit.atlassian.net/browse/SP-158

This script retrieves historical stock data for a specified ticker symbol (e.g., AAPL) and calculates the price of an option using the binomial model. The script uses real or sample data, processes it, and computes the option price based on various financial parameters.

Key Constants:
- TRADING_DAYS: Number of trading days in a year (typically 252).
- PRICING_STEPS: Number of steps for pricing calculations.
- INTEREST_RATE: Annual risk-free interest rate.

Option Parameters:
- OPTION_EXPIRATION_DATE: Expiration date of the option.
- DIVIDEND_YIELD: Annual dividend yield of the stock.
- TICKER: Stock ticker symbol.
- HISTORY_START_DAYS: Number of days before the current date to start retrieving historical data.
- HISTORY_END_DAYS: Number of days before the current date to end retrieving historical data.
- strike_price: Strike price of the option.
- option_type: Type of the option ('call' or 'put').
- OPTION_STYLE: Style of the option ('AMERICAN' or 'EUROPEAN').
- use_real_data: Boolean flag to use real data or sample data.

Main Script:
- Retrieves and processes historical stock data.
- Calculates the historical volatility of the stock.
- Computes the binomial parameters for the option pricing model.
- Constructs the stock price tree and option value tree.
- Calculates the option price using the binomial model.

Usage:
Run the script to get the price of the specified option based on the provided parameters.
"""

# INPUTS/CONSTANTS
# GENERAL
from utils.utils import get_live_data_from_yfinance, return_sample_data, trading_days_between, get_asset_data, \
    process_data, calculate_volatility, calculate_binomial_parameters, price_option
import numpy as np
import pandas as pd

TRADING_DAYS = 252
PRICING_STEPS = 100
INTEREST_RATE = 0.045  # This is as percent so 4% is 0.04

# SHARE/OPTION SPECIFIC
OPTION_EXPIRATION_DATE = '2025-09-17'
DIVIDEND_YIELD = 0.0042
TICKER = 'AAPL'
HISTORY_START_DAYS = 380  # Number of days to go back for history - will need to be 365 to get a years worth of data
HISTORY_END_DAYS = 0  # 0 is today's date

strike_price = 175  # Example strike price
option_type = 'call'  # 'call' or 'put'
OPTION_STYLE = 'AMERICAN'  # or 'EUROPEAN'

use_real_data = True

# Main script
asset_data_frame = get_asset_data(use_real_data, TICKER, HISTORY_START_DAYS, HISTORY_END_DAYS)
asset_data_frame = process_data(asset_data_frame)
historic_volatility = calculate_volatility(asset_data_frame, TRADING_DAYS)
TRADING_DAYS_LEFT = trading_days_between(asset_data_frame.iloc[0]['Date'], OPTION_EXPIRATION_DATE)
up_branch_move, down_branch_move, factor_step_discount, up_branch_probability, down_branch_probability = calculate_binomial_parameters(
    historic_volatility, TRADING_DAYS_LEFT, TRADING_DAYS, PRICING_STEPS, INTEREST_RATE, DIVIDEND_YIELD)

current_stock_price = asset_data_frame.iloc[0]['Close']

print('Current stock price:', current_stock_price)

stock_price_tree = np.zeros((PRICING_STEPS + 1, PRICING_STEPS + 1))
stock_price_tree[0, 0] = current_stock_price

for i in range(1, PRICING_STEPS + 1):
    stock_price_tree[i, 0] = stock_price_tree[i - 1, 0] * up_branch_move
    for j in range(1, i + 1):
        stock_price_tree[i, j] = stock_price_tree[i - 1, j - 1] * down_branch_move

option_value_tree = np.zeros((PRICING_STEPS + 1, PRICING_STEPS + 1))

for j in range(PRICING_STEPS + 1):
    if option_type == 'call':
        option_value_tree[PRICING_STEPS, j] = max(0, stock_price_tree[PRICING_STEPS, j] - strike_price)
    elif option_type == 'put':
        option_value_tree[PRICING_STEPS, j] = max(0, strike_price - stock_price_tree[PRICING_STEPS, j])

option_price = price_option(stock_price_tree, option_value_tree, PRICING_STEPS, up_branch_probability,
                            down_branch_probability, factor_step_discount, option_type, strike_price, OPTION_STYLE)

print(f"Option Price: {option_price}")