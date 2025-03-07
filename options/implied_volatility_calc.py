

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