import pytest

from utils.utils import implied_volatility


def test_implied_volatility():
    # Test parameters
    option_price = 69.2
    option_type = "call"
    current_stock_price = 238.87
    strike_price = 175
    time_to_expiration = 0.53  # Fixed value for 6.5 months (approx.)
    interest_rate = 0.045  # 4.5%
    dividend_yield = 0.0042  # 0.58%
    pricing_steps = 100
    option_style = "AMERICAN"
    TRADING_DAYS = 252

    # Expected result
    expected_implied_volatility = 0.325  # 32%

    # Calculate implied volatility
    calculated_implied_volatility = implied_volatility(
        option_price,
        option_type,
        current_stock_price,
        strike_price,
        time_to_expiration,
        interest_rate,
        dividend_yield,
        pricing_steps,
        option_style,
        TRADING_DAYS,
    )

    print("Calculated implied volatility is: " + str(calculated_implied_volatility))

    # Assert that the calculated implied volatility is close to the expected value
    assert calculated_implied_volatility == pytest.approx(expected_implied_volatility, abs=1e-2)
