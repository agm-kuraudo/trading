import numpy as np
import pandas as pd
from scipy.optimize import newton

from utils.utils import get_live_data_from_yfinance, return_sample_data, trading_days_between

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


def implied_volatility(option_price, option_type, current_stock_price, strike_price, time_to_expiration, interest_rate,
                       dividend_yield, pricing_steps, option_style):
    def objective_function(volatility):
        up_branch_move, down_branch_move, factor_step_discount, up_branch_probability, down_branch_probability = calculate_binomial_parameters(
            volatility, time_to_expiration * TRADING_DAYS, TRADING_DAYS, pricing_steps, interest_rate, dividend_yield)

        stock_price_tree = np.zeros((pricing_steps + 1, pricing_steps + 1))
        stock_price_tree[0, 0] = current_stock_price

        for i in range(1, pricing_steps + 1):
            stock_price_tree[i, 0] = stock_price_tree[i - 1, 0] * up_branch_move
            for j in range(1, i + 1):
                stock_price_tree[i, j] = stock_price_tree[i - 1, j - 1] * down_branch_move

        option_value_tree = np.zeros((pricing_steps + 1, pricing_steps + 1))

        for j in range(pricing_steps + 1):
            if option_type == 'call':
                option_value_tree[pricing_steps, j] = max(0, stock_price_tree[pricing_steps, j] - strike_price)
            elif option_type == 'put':
                option_value_tree[pricing_steps, j] = max(0, strike_price - stock_price_tree[pricing_steps, j])

        calculated_option_price = price_option(stock_price_tree, option_value_tree, pricing_steps,
                                               up_branch_probability,
                                               down_branch_probability, factor_step_discount, option_type, strike_price,
                                               option_style)
        return calculated_option_price - option_price

    initial_guess = 0.2
    implied_vol = newton(objective_function, initial_guess)
    return implied_vol


# Main script
asset_data_frame = get_asset_data(use_real_data, TICKER, HISTORY_START_DAYS, HISTORY_END_DAYS)
asset_data_frame = process_data(asset_data_frame)
current_stock_price = asset_data_frame.iloc[0]['Close']
TRADING_DAYS_LEFT = trading_days_between(asset_data_frame.iloc[0]['Date'], OPTION_EXPIRATION_DATE)
time_to_expiration = TRADING_DAYS_LEFT / TRADING_DAYS

implied_vol = implied_volatility(option_price, option_type, current_stock_price, strike_price, time_to_expiration,
                                 INTEREST_RATE, DIVIDEND_YIELD, PRICING_STEPS, OPTION_STYLE)
print(f"Implied Volatility: {implied_vol:.2%}")