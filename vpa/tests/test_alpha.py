import os
from collections import deque, namedtuple

import pandas as pd
import pytest

from vpa.app import Candle, calculate_adx, identify_acc_or_dist

PERIOD_ONE_LENGTH = 5
PERIOD_TWO_LENGTH = 25
PERIOD_THREE_LENGTH = 50


@pytest.fixture
def deque_dictionary():
    return {
        "period_one": deque(maxlen=PERIOD_ONE_LENGTH),
        "period_two": deque(maxlen=PERIOD_TWO_LENGTH),
        "period_three": deque(maxlen=PERIOD_THREE_LENGTH),
    }


@pytest.fixture
def my_data_frame():
    absolute_path = os.path.dirname(__file__)
    relative_path = "../data/"
    full_path = os.path.join(absolute_path, relative_path)

    data_frame = pd.read_csv(full_path + "spy_data.csv")
    data_frame = data_frame.sort_values("Date", axis=0)
    return data_frame


# Step 1: Read CSV file


def test_read_csv(my_data_frame):
    print(f"File Length: {len(my_data_frame)}")
    assert len(my_data_frame)
    print(f"{my_data_frame.columns}")


# Step 2: Make sure the CSV file has correct data


def test_columns_present(my_data_frame):
    expected_columns = ["Date", "Adj Close", "Close", "High", "Low", "Open", "Volume"]
    for column in expected_columns:
        assert column in my_data_frame.columns


# Step 3: Make sure we can create a Candle object from data


def test_create_candle(my_data_frame):
    first_row = my_data_frame.iloc[0]
    this_candle = Candle(
        first_row["Date"],
        first_row["Volume"],
        first_row["Open"],
        first_row["High"],
        first_row["Low"],
        first_row["Adj Close"],
    )
    # print(this_candle)
    assert this_candle is not None


def test_deque_and_adx(deque_dictionary, my_data_frame):
    # Step 4: Make sure we can create a rolling window (deque) for each period length

    for index, row in my_data_frame.iterrows():
        if index == PERIOD_ONE_LENGTH + 1:
            assert len(deque_dictionary["period_one"]) == PERIOD_ONE_LENGTH
            assert len(deque_dictionary["period_two"]) == PERIOD_ONE_LENGTH + 1
            assert len(deque_dictionary["period_three"]) == PERIOD_ONE_LENGTH + 1
            with pytest.raises(ValueError) as context:
                calculate_adx(deque_dictionary["period_three"])
            assert (
                str(context.value)
                == "Not enough data to calculate ADX. At least 15 periods are required."
            )
        elif index == PERIOD_TWO_LENGTH + 1:
            assert len(deque_dictionary["period_one"]) == PERIOD_ONE_LENGTH
            assert len(deque_dictionary["period_two"]) == PERIOD_TWO_LENGTH
            assert len(deque_dictionary["period_three"]) == PERIOD_TWO_LENGTH + 1
        elif index == PERIOD_THREE_LENGTH + 1:
            assert len(deque_dictionary["period_one"]) == PERIOD_ONE_LENGTH
            assert len(deque_dictionary["period_two"]) == PERIOD_TWO_LENGTH
            assert len(deque_dictionary["period_three"]) == PERIOD_THREE_LENGTH
        elif index == 52:
            break

        # Note we are reading only first 52 candles of the CSV here

        this_candle = Candle(row["Date"], row["Volume"], row["Open"], row["High"], row["Low"], row["Adj Close"])
        # This adds the candle to each of the three periods
        for key in deque_dictionary.keys():
            deque_dictionary[key].append(this_candle)

    # Note - now we have 50 candles (period three) additional processing and logic kicks in

    # Step 5: Calculate the ADX based on the last 50 candles with period of 14
    assert calculate_adx(deque_dictionary["period_three"]) == [
        40.48136255393826,
        175.39975020822467,
        27.52034622638257,
        19.060191841982864,
    ]


def test_bar_counting_logic():
    candle1 = Candle("2023-01-03 00:00:00+00:00", 3, 1.0, 2.0, 0.5, 2.0)
    candle2 = Candle("2023-01-03 00:00:00+00:00", 3, 1.0, 2.0, 0.5, 2.0)
    candle3 = Candle("2023-01-03 00:00:00+00:00", 3, 1.0, 2.0, 0.5, 2.0)
    candle4 = Candle("2023-01-03 00:00:00+00:00", 3, 1.0, 2.0, 0.5, 2.0)
    candle5 = Candle("2023-01-03 00:00:00+00:00", 3, 1.0, 2.0, 0.5, 2.0)

    for candle in [candle1, candle2, candle3, candle4, candle5]:
        candle.spread_percentiles["period_one"] = 50
        candle.volume_percentiles["period_one"] = 50

    my_deque = deque([candle1, candle2, candle3, candle4, candle5], maxlen=5)

    high_spread_threshold = 55
    high_volume_threshold = 55
    anomaly_threshold = 20

    up_bar_count = sum(1 for candle in my_deque if candle.up_bar)
    high_spread_count = sum(
        1 for candle in my_deque if candle.spread_percentiles["period_one"] > high_spread_threshold
    )
    high_volume_count = sum(
        1 for candle in my_deque if candle.volume_percentiles["period_one"] > high_volume_threshold
    )
    anomaly_count = sum(
        1
        for candle in my_deque
        if abs(candle.spread_percentiles["period_one"] - candle.volume_percentiles["period_one"])
        > anomaly_threshold
    )

    assert up_bar_count == 5
    assert high_spread_count == 0
    assert high_volume_count == 0
    assert anomaly_count == 0

    # Test with spread threshold below 50
    high_spread_threshold = 45
    high_spread_count = sum(
        1 for candle in my_deque if candle.spread_percentiles["period_one"] > high_spread_threshold
    )

    assert high_spread_count == 5


def test_acc_dist_function():
    # Create a mock class to simulate the data structure
    MockData = namedtuple("MockData", ["volume", "close"])
    # Mock data for period_three
    period_three = [
        MockData(volume=100, close=10),
        MockData(volume=150, close=15),
        MockData(volume=200, close=20),
        MockData(volume=250, close=25),
        MockData(volume=300, close=30),
    ]

    # Mock data for period_one
    period_one_acc = [
        MockData(volume=240, close=12),  # Volume > 230 (65th percentile)
        MockData(volume=250, close=11),  # Volume > 230 (65th percentile)
        MockData(volume=260, close=10),  # Volume > 230 (65th percentile)
        MockData(volume=270, close=9),  # Volume > 230 (65th percentile)
        MockData(volume=280, close=8),  # Volume > 230 (65th percentile)
    ]

    period_one_dist = [
        MockData(volume=240, close=28),  # Volume > 230 (65th percentile)
        MockData(volume=250, close=29),  # Volume > 230 (65th percentile)
        MockData(volume=260, close=30),  # Volume > 230 (65th percentile)
        MockData(volume=270, close=31),  # Volume > 230 (65th percentile)
        MockData(volume=280, close=32),  # Volume > 230 (65th percentile)
    ]

    period_one_neutral = [
        MockData(volume=60, close=18),
        MockData(volume=70, close=19),
        MockData(volume=80, close=20),
        MockData(volume=90, close=21),
        MockData(volume=100, close=22),
    ]

    result = identify_acc_or_dist(period_three, period_one_acc)
    assert result == (True, "Acc")

    result = identify_acc_or_dist(period_three, period_one_dist)
    assert result == (True, "Dist")

    result = identify_acc_or_dist(period_three, period_one_neutral)
    assert result == (False, "")
