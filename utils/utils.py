import os
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import numpy as np
from scipy.optimize import newton
import warnings

def get_live_data_from_yfinance(ticker: str = "SPY", start_days_ago: int = 365, end_days_ago: int = 0) -> pd.DataFrame:

    # Get the current date
    end_date = datetime.now().date() - timedelta(days=end_days_ago)

    # Get the date one year ago from today
    start_date = end_date - timedelta(days=start_days_ago)

    # Suppress specific warning
    warnings.filterwarnings("ignore", message="The default value of auto_adjust will be changed to True")

    # Fetch the data for the last year
    myDF = yf.download(ticker, start=start_date, end=end_date, auto_adjust=True)

    myDF = myDF.reset_index()

    myDF.columns = myDF.columns.get_level_values(0)

    # print(myDF.shape)
    #
    # print(myDF.iloc[0].to_dict())

    myDF.columns = ['Date', 'Close', 'High', 'Low', 'Open', 'Volume']
    return myDF

def return_sample_data():
    absolute_path = os.path.dirname(__file__)
    relative_path = "../vpa/data/"
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

def process_data(data):
    data = data.sort_values(by=['Date'], ascending=False)
    data['Diff'] = data['Close'] / data['Close'].shift(1)
    data.dropna(inplace=True)
    data['LogDiff'] = data['Diff'].apply(lambda x: np.log(x))
    return data

def calculate_volatility(data, trading_days):
    data = data.head(trading_days)
    return data['LogDiff'].std() * np.sqrt(trading_days)

def calculate_binomial_parameters(volatility, trading_days_left, trading_days, pricing_steps, interest_rate, dividend_yield):
    epsilon = 1e-10  # Small value to avoid division by zero
    delta_t = trading_days_left / (trading_days * pricing_steps)
    up_branch_move = np.exp(volatility * np.sqrt(delta_t))
    down_branch_move = 1 / (up_branch_move + epsilon)  # Add epsilon to avoid division by zero
    factor_step_discount = np.exp(-interest_rate * delta_t)
    interest_rate_cost_of_step = np.exp((interest_rate - dividend_yield) * delta_t)
    up_branch_probability = (interest_rate_cost_of_step - down_branch_move) / (up_branch_move - down_branch_move + epsilon)  # Add epsilon to avoid division by zero
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
                       dividend_yield, pricing_steps, option_style, TRADING_DAYS):
    def objective_function(volatility):
        if volatility < 1e-10:  # Avoid extremely small volatility values
            return np.inf
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

    initial_guess = 0.4  # Adjusted initial guess
    tolerance = 1e-6  # Adjusted tolerance
    implied_vol = newton(objective_function, initial_guess, tol=tolerance)
    return implied_vol

def get_asset_data(use_real_data, ticker, start_days_ago, end_days_ago):
    if use_real_data:
        return get_live_data_from_yfinance(ticker=ticker, start_days_ago=start_days_ago, end_days_ago=end_days_ago)
    else:
        return return_sample_data()