import unittest
import numpy as np
import pandas as pd
from datetime import datetime
from utils.utils import get_live_data_from_yfinance, return_sample_data, trading_days_between

# Import the functions from the main script
from price_calc import get_asset_data, process_data, calculate_volatility, calculate_binomial_parameters, price_option


class TestOptionPricingModel(unittest.TestCase):

    def setUp(self):
        self.TRADING_DAYS = 252
        self.PRICING_STEPS = 100
        self.INTEREST_RATE = 0.04
        self.OPTION_EXPIRATION_DATE = '2025-02-21'
        self.DIVIDEND_YIELD = 0.03
        self.TICKER = 'AAPL'
        self.HISTORY_START_DAYS = 380
        self.HISTORY_END_DAYS = 0
        self.strike_price = 230
        self.option_type = 'call'
        self.OPTION_STYLE = 'AMERICAN'
        self.use_real_data = False

        self.sample_data = pd.DataFrame({
            'Date': pd.date_range(start='2023-01-01', periods=380, freq='B'),
            'Close': np.random.uniform(100, 200, 380)
        })

    def test_data_retrieval(self):
        data = get_asset_data(self.use_real_data, self.TICKER, self.HISTORY_START_DAYS, self.HISTORY_END_DAYS)
        self.assertIsInstance(data, pd.DataFrame)
        self.assertFalse(data.empty)

    def test_data_processing(self):
        data = process_data(self.sample_data.copy())
        self.assertIn('Diff', data.columns)
        self.assertIn('LogDiff', data.columns)

    def test_volatility_calculation(self):
        data = process_data(self.sample_data.copy())
        historic_volatility = calculate_volatility(data, self.TRADING_DAYS)
        self.assertGreater(historic_volatility, 0)

    def test_binomial_model_parameters(self):
        historic_volatility = 0.23477917329761816
        TRADING_DAYS_LEFT = 14
        up_branch_move, down_branch_move, factor_step_discount, up_branch_probability, down_branch_probability = calculate_binomial_parameters(
            historic_volatility, TRADING_DAYS_LEFT, self.TRADING_DAYS, self.PRICING_STEPS, self.INTEREST_RATE,
            self.DIVIDEND_YIELD)

        self.assertGreater(up_branch_move, 1)
        self.assertLess(down_branch_move, 1)
        self.assertAlmostEqual(up_branch_probability + down_branch_probability, 1)

    def test_option_pricing(self):
        current_stock_price = self.sample_data.iloc[0]['Close']
        PRICING_STEPS = 100
        up_branch_move = 1.0055491379278034
        down_branch_move = 0.9944814850726849
        up_branch_probability = 0.4991185186792394
        down_branch_probability = 0.5008814813207606
        factor_step_discount = 0.9999777780246896

        stock_price_tree = np.zeros((PRICING_STEPS + 1, PRICING_STEPS + 1))
        stock_price_tree[0, 0] = current_stock_price

        for i in range(1, PRICING_STEPS + 1):
            stock_price_tree[i, 0] = stock_price_tree[i - 1, 0] * up_branch_move
            for j in range(1, i + 1):
                stock_price_tree[i, j] = stock_price_tree[i - 1, j - 1] * down_branch_move

        option_value_tree = np.zeros((PRICING_STEPS + 1, PRICING_STEPS + 1))

        for j in range(PRICING_STEPS + 1):
            if self.option_type == 'call':
                option_value_tree[PRICING_STEPS, j] = max(0, stock_price_tree[PRICING_STEPS, j] - self.strike_price)
            elif self.option_type == 'put':
                option_value_tree[PRICING_STEPS, j] = max(0, self.strike_price - stock_price_tree[PRICING_STEPS, j])

        option_price = price_option(stock_price_tree, option_value_tree, PRICING_STEPS, up_branch_probability,
                                    down_branch_probability, factor_step_discount, self.option_type, self.strike_price,
                                    self.OPTION_STYLE)
        self.assertGreater(option_price, 0)


if __name__ == '__main__':
    unittest.main()