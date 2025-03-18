import unittest
from alpha.execution import trade_size


class TestTradeSize(unittest.TestCase):
    def test_trade_size(self):
        # Test case 1: Basic test
        cash = 30000
        risk_per_trade_theory = 0.01  # 1% of cash
        risk_per_trade_exposure_max = 0.1  # 10% of cash
        share_price = 50
        stop_price_distance = 2
        expected_trade_size = min((cash * risk_per_trade_theory) / stop_price_distance, (cash * risk_per_trade_exposure_max) / share_price)
        self.assertEqual(trade_size(cash, risk_per_trade_theory, risk_per_trade_exposure_max, share_price, stop_price_distance), expected_trade_size)

        # Test case 2: Debug flag test
        trade_size_result = trade_size(cash, risk_per_trade_theory, risk_per_trade_exposure_max, share_price, stop_price_distance, debug=True)
        self.assertEqual(trade_size_result, expected_trade_size)

        # Test case 3: Different parameters
        cash = 50000
        risk_per_trade_theory = 0.02  # 2% of cash
        risk_per_trade_exposure_max = 0.05  # 5% of cash
        share_price = 100
        stop_price_distance = 5
        expected_trade_size = min((cash * risk_per_trade_theory) / stop_price_distance, (cash * risk_per_trade_exposure_max) / share_price)
        self.assertEqual(trade_size(cash, risk_per_trade_theory, risk_per_trade_exposure_max, share_price, stop_price_distance), expected_trade_size)

if __name__ == '__main__':
    unittest.main()