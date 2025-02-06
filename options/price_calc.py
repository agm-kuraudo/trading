# INPUTS/CONSTANTS
# GENERAL
from utils.utils import get_live_data_from_yfinance, return_sample_data, trading_days_between
import numpy as np
import pandas as pd

TRADING_DAYS = 252
PRICING_STEPS = 100
INTEREST_RATE = 0.04  # This is as percent so 4% is 0.04

# SHARE/OPTION SPECIFIC
OPTION_EXPIRATION_DATE = '2025-02-21'
DIVIDEND_YIELD = 0.03
TICKER = 'AAPL'
HISTORY_START_DAYS = 380  # Number of days to go back for history - will need to be 365 to get a years worth of data
HISTORY_END_DAYS = 0  # 0 is today's date

strike_price = 230  # Example strike price
option_type = 'call'  # 'call' or 'put'
OPTION_STYLE = 'AMERICAN'  # or 'EUROPEAN'

use_real_data = True


def get_asset_data(use_real_data, ticker, start_days_ago, end_days_ago):
    if use_real_data:
        return get_live_data_from_yfinance(ticker=ticker, start_days_ago=start_days_ago, end_days_ago=end_days_ago)
    else:
        return return_sample_data()


def process_data(data):
    data = data.sort_values(by=['Date'], ascending=False)
    data['Diff'] = data['Close'] / data['Close'].shift(1)
    data.dropna(inplace=True)
    data['LogDiff'] = data['Diff'].apply(lambda x: np.log(x))
    return data


def calculate_volatility(data, trading_days):
    data = data.head(trading_days)
    return data['LogDiff'].std() * np.sqrt(trading_days)


def calculate_binomial_parameters(volatility, trading_days_left, trading_days, pricing_steps, interest_rate,
                                  dividend_yield):
    delta_t = trading_days_left / (trading_days * pricing_steps)
    up_branch_move = np.exp(volatility * np.sqrt(delta_t))
    down_branch_move = 1 / up_branch_move
    factor_step_discount = np.exp(-interest_rate * delta_t)
    interest_rate_cost_of_step = np.exp((interest_rate - dividend_yield) * delta_t)
    up_branch_probability = (interest_rate_cost_of_step - down_branch_move) / (up_branch_move - down_branch_move)
    down_branch_probability = 1 - up_branch_probability
    return up_branch_move, down_branch_move, factor_step_discount, up_branch_probability, down_branch_probability


def price_option(stock_price_tree, option_value_tree, pricing_steps, up_branch_probability, down_branch_probability,
                 factor_step_discount, option_type, strike_price, option_style):
    for i in range(pricing_steps - 1, -1, -1):
        for j in range(i + 1):
            option_value = (up_branch_probability * option_value_tree[i + 1, j] +
                            down_branch_probability * option_value_tree[i + 1, j + 1]) * factor_step_discount

            if option_style == 'AMERICAN':
                if option_type == 'call':
                    immediate_exercise_value = max(0, stock_price_tree[i, j] - strike_price)
                elif option_type == 'put':
                    immediate_exercise_value = max(0, strike_price - stock_price_tree[i, j])

                option_value_tree[i, j] = max(option_value, immediate_exercise_value)
            else:
                option_value_tree[i, j] = option_value
    return option_value_tree[0, 0]


# Main script
asset_data_frame = get_asset_data(use_real_data, TICKER, HISTORY_START_DAYS, HISTORY_END_DAYS)
asset_data_frame = process_data(asset_data_frame)
historic_volatility = calculate_volatility(asset_data_frame, TRADING_DAYS)
TRADING_DAYS_LEFT = trading_days_between(asset_data_frame.iloc[0]['Date'], OPTION_EXPIRATION_DATE)
up_branch_move, down_branch_move, factor_step_discount, up_branch_probability, down_branch_probability = calculate_binomial_parameters(
    historic_volatility, TRADING_DAYS_LEFT, TRADING_DAYS, PRICING_STEPS, INTEREST_RATE, DIVIDEND_YIELD)

current_stock_price = asset_data_frame.iloc[0]['Close']
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