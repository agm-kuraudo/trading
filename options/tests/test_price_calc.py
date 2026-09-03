import numpy as np
import pandas as pd
import pytest

# Import the functions from the main script
from utils.utils import calculate_binomial_parameters, calculate_volatility, get_asset_data, price_option, process_data


@pytest.fixture
def constants():
    return {
        "TRADING_DAYS": 252,
        "PRICING_STEPS": 100,
        "INTEREST_RATE": 0.04,
        "OPTION_EXPIRATION_DATE": "2025-02-21",
        "DIVIDEND_YIELD": 0.03,
        "TICKER": "AAPL",
        "HISTORY_START_DAYS": 380,
        "HISTORY_END_DAYS": 0,
        "strike_price": 230,
        "option_type": "call",
        "OPTION_STYLE": "AMERICAN",
        "use_real_data": False,
    }


# Seed for the sample_data fixture so the generated prices are identical on every
# run. Deterministic data keeps the suite non-flaky (see Requirements 6, 9, 12.5).
# With this seed the first-row Close is ~177.4, which is above the ~132.25 threshold
# required for test_option_pricing to price the strike-230 call to a positive value.
SAMPLE_DATA_SEED = 42


@pytest.fixture
def sample_data():
    rng = np.random.default_rng(SAMPLE_DATA_SEED)
    return pd.DataFrame(
        {
            "Date": pd.date_range(start="2023-01-01", periods=380, freq="B"),
            "Close": rng.uniform(100, 200, 380),
        }
    )


def test_data_retrieval(constants):
    data = get_asset_data(
        constants["use_real_data"],
        constants["TICKER"],
        constants["HISTORY_START_DAYS"],
        constants["HISTORY_END_DAYS"],
    )
    assert isinstance(data, pd.DataFrame)
    assert not data.empty


def test_data_processing(sample_data):
    data = process_data(sample_data.copy())
    assert "Diff" in data.columns
    assert "LogDiff" in data.columns


def test_volatility_calculation(constants, sample_data):
    data = process_data(sample_data.copy())
    historic_volatility = calculate_volatility(data, constants["TRADING_DAYS"])
    assert historic_volatility > 0


def test_binomial_model_parameters(constants):
    historic_volatility = 0.23477917329761816
    TRADING_DAYS_LEFT = 14
    up_branch_move, down_branch_move, factor_step_discount, up_branch_probability, down_branch_probability = (
        calculate_binomial_parameters(
            historic_volatility,
            TRADING_DAYS_LEFT,
            constants["TRADING_DAYS"],
            constants["PRICING_STEPS"],
            constants["INTEREST_RATE"],
            constants["DIVIDEND_YIELD"],
        )
    )

    assert up_branch_move > 1
    assert down_branch_move < 1
    assert up_branch_probability + down_branch_probability == pytest.approx(1)


def test_option_pricing(constants, sample_data):
    current_stock_price = sample_data.iloc[0]["Close"]
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
        if constants["option_type"] == "call":
            option_value_tree[PRICING_STEPS, j] = max(0, stock_price_tree[PRICING_STEPS, j] - constants["strike_price"])
        elif constants["option_type"] == "put":
            option_value_tree[PRICING_STEPS, j] = max(0, constants["strike_price"] - stock_price_tree[PRICING_STEPS, j])

    option_price = price_option(
        stock_price_tree,
        option_value_tree,
        PRICING_STEPS,
        up_branch_probability,
        down_branch_probability,
        factor_step_discount,
        constants["option_type"],
        constants["strike_price"],
        constants["OPTION_STYLE"],
    )
    assert option_price > 0
