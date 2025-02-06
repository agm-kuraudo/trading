#INPUTS/CONSTANTS
#GENERAL
from utils.utils import get_live_data_from_yfinance, return_sample_data, trading_days_between
import numpy as np
import pandas as pd

TRADING_DAYS = 252
PRICING_STEPS = 100
INTEREST_RATE = 0.04 #This is as percent so 4% is 0.04

#SHARE/OPTION SPECIFIC
OPTION_EXPIRATION_DATE = '2025-02-21'
DIVIDEND_YIELD = 0.03
TICKER = 'AAPL'
HISTORY_START_DAYS = 380 #Number of days to go back for history - will need to be 365 to get a years worth of data
HISTORY_END_DAYS = 0    #0 is today's date

strike_price = 230  # Example strike price
option_type = 'call'  # 'call' or 'put'
OPTION_STYLE = 'AMERICAN'  # or 'EUROPEAN'

use_real_data = True

# 1 Get Live Data Function
    # Copy from alpha app_runner - maybe move to utils file

if use_real_data:
    asset_data_frame = get_live_data_from_yfinance(ticker=TICKER, start_days_ago=HISTORY_START_DAYS, end_days_ago=HISTORY_END_DAYS)
    print(asset_data_frame)
else:
    #2 Read CSV function - as above
    asset_data_frame=return_sample_data()

print(f"DataFrame retrieved. Live data: {use_real_data}")
print(asset_data_frame.head(1))

#3 Order DataFrame by Date DESC - Newest First
asset_data_frame = asset_data_frame.sort_values(by=['Date'], ascending=False)

print("Data Sorted by Date DESC - Newest First:")
print(asset_data_frame.head(1))

#4 Add a new column that contains division from previous two close prices
asset_data_frame['Diff'] = asset_data_frame['Close'] / asset_data_frame['Close'].shift(1)

print("DIFF column added - contains division from previous two close prices:")
print(asset_data_frame.head(1))

#Remove the row that has no value
asset_data_frame.dropna(inplace=True)

#5 New column (or update previous) that has log value of the difference
asset_data_frame['LogDiff'] = asset_data_frame['Diff'].apply(lambda x: np.log(x))

print("LogDiff column added - contains log value of the difference:")
print(asset_data_frame.head(1))

#6 Standard Deviation of all values in Column from #5 divided by SQRT of _TRADING_DAYS

# Limit the DataFrame to the last 252 rows
asset_data_frame = asset_data_frame.head(252)

#Work out standard deviation
historic_volatility = asset_data_frame['LogDiff'].std() * np.sqrt(TRADING_DAYS)

print("Historic Volatility.  Standard Deviation of last 252 values in Column from #5 divided by SQRT of _TRADING_DAYS:")
print(historic_volatility)
# This gives us the Historic Volatility

#7 Up Branch Move Calculation
    #7.1 Work out the period left on options as a Percentage of Year (_TRADING_DAYS)
        # 7.1.1 How many trading days left before option expires
TRADING_DAYS_LEFT = trading_days_between(asset_data_frame.iloc[0]['Date'], OPTION_EXPIRATION_DATE)
print(f"Trading Days Left: {TRADING_DAYS_LEFT}")

#Calculate the time step - this was missing from my original plan
DELTA_T = TRADING_DAYS_LEFT / (TRADING_DAYS * PRICING_STEPS)

UP_BRANCH_MOVE = np.exp(historic_volatility * np.sqrt(DELTA_T))
print(f"Up Branch Move complete: {UP_BRANCH_MOVE}")

#8 Down Branch Calculation - 1 (literal) / #7
DOWN_BRANCH_MOVE = 1 / UP_BRANCH_MOVE
print(f"Down Branch Move: {DOWN_BRANCH_MOVE}")

#9 Up Branch Probability
FACTOR_STEP_DISCOUNT = np.exp(-INTEREST_RATE * DELTA_T)
INTEREST_RATE_COST_OF_STEP = np.exp((INTEREST_RATE - DIVIDEND_YIELD) * DELTA_T)
UP_BRANCH_PROBABILITY = (INTEREST_RATE_COST_OF_STEP - DOWN_BRANCH_MOVE) / (UP_BRANCH_MOVE - DOWN_BRANCH_MOVE)

#10 Down Branch Probability
DOWN_BRANCH_PROBABILITY = 1 - UP_BRANCH_PROBABILITY


print(f"Historic Volatility: {historic_volatility}")
print(f"Trading Days Left: {TRADING_DAYS_LEFT}")
print(f"Time Step (Delta T): {DELTA_T}")
print(f"Up Branch Move: {UP_BRANCH_MOVE}")
print(f"Down Branch Move: {DOWN_BRANCH_MOVE}")
print(f"Factor Step Discount: {FACTOR_STEP_DISCOUNT}")
print(f"Interest Rate Cost of Step: {INTEREST_RATE_COST_OF_STEP}")
print(f"Up Branch Probability: {UP_BRANCH_PROBABILITY}")
print(f"Down Branch Probability: {DOWN_BRANCH_PROBABILITY}")

# Initialize parameters for option pricing
current_stock_price = asset_data_frame.iloc[0]['Close']


# Initialize the stock price tree
stock_price_tree = np.zeros((PRICING_STEPS + 1, PRICING_STEPS + 1))
stock_price_tree[0, 0] = current_stock_price

for i in range(1, PRICING_STEPS + 1):
    stock_price_tree[i, 0] = stock_price_tree[i - 1, 0] * UP_BRANCH_MOVE
    for j in range(1, i + 1):
        stock_price_tree[i, j] = stock_price_tree[i - 1, j - 1] * DOWN_BRANCH_MOVE

# Initialize the option value tree
option_value_tree = np.zeros((PRICING_STEPS + 1, PRICING_STEPS + 1))

# Calculate option value at expiration
for j in range(PRICING_STEPS + 1):
    if option_type == 'call':
        option_value_tree[PRICING_STEPS, j] = max(0, stock_price_tree[PRICING_STEPS, j] - strike_price)
    elif option_type == 'put':
        option_value_tree[PRICING_STEPS, j] = max(0, strike_price - stock_price_tree[PRICING_STEPS, j])

# Backpropagate the option value with early exercise check for American options
for i in range(PRICING_STEPS - 1, -1, -1):
    for j in range(i + 1):
        # Calculate the option value without early exercise
        option_value = (UP_BRANCH_PROBABILITY * option_value_tree[i + 1, j] +
                        DOWN_BRANCH_PROBABILITY * option_value_tree[i + 1, j + 1]) * FACTOR_STEP_DISCOUNT

        if OPTION_STYLE == 'AMERICAN':
            # Calculate the immediate exercise value
            if option_type == 'call':
                immediate_exercise_value = max(0, stock_price_tree[i, j] - strike_price)
            elif option_type == 'put':
                immediate_exercise_value = max(0, strike_price - stock_price_tree[i, j])

            # Set the option value to the maximum of the calculated value and the immediate exercise value
            option_value_tree[i, j] = max(option_value, immediate_exercise_value)
        else:
            # For European options, just use the calculated value
            option_value_tree[i, j] = option_value

# The option price is the value at the root of the tree
option_price = option_value_tree[0, 0]

print(f"Option Price: {option_price}")