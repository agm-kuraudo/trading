from alpha.candle import DebugLog, DummyQCTrader, Candle, calculate_adx, identify_acc_or_dist
import os
import statistics
from collections import deque
import pandas as pd
import numpy as np
import yfinance as yf
import datetime
# Get up-to-date data? or use CSV file if False
use_real_data = True

rolling_window_complete_msg_display=True

logger = DebugLog(level="INFO")

#This defines how many rows/days we are going to run through
MAX_ROWS = 5002

#This sets up our rolling windows over short, medium and long period
deque_dictionary = {
    "period_one": deque(maxlen=DummyQCTrader.PERIOD_ONE_LENGTH),
    "period_two": deque(maxlen=DummyQCTrader.PERIOD_TWO_LENGTH),
    "period_three": deque(maxlen=DummyQCTrader.PERIOD_THREE_LENGTH)
}

#Template variable for storing the current percentile numbers for "spread" and "volume"
percentiles_store = {
    "spread": {},
    "volume": {}
}

# Set up for multiple bar signal checks
trading_parameters = {
    "period_one": {
        "High_Spread_Threshold": 55,
        "High_Volume_Threshold": 55,
        "Anomaly_Threshold": 20,
        "Signal_Bar_Count": 4,
        "High_Spread_Count": 3,
        "High_Volume_Count": 3
    },
    "period_two": {
        "High_Spread_Threshold": 55,
        "High_Volume_Threshold": 55,
        "Anomaly_Threshold": 20,
        "Signal_Bar_Count": 7,
        "High_Spread_Count": 6,
        "High_Volume_Count": 6
    },
    "period_three": {
        "High_Spread_Threshold": 55,
        "High_Volume_Threshold": 55,
        "Anomaly_Threshold": 20,
        "Signal_Bar_Count": 16,
        "High_Spread_Count": 12,
        "High_Volume_Count": 12
    }
}

# Step 1:
# Get our test data from CSV file...
# this would come from live quant data eventually

if use_real_data:
    # Define the ticker symbol
    ticker_symbol = 'SPY'

    # Get the current date
    end_date = datetime.datetime.now().date()

    # Get the date one year ago from today
    start_date = end_date - datetime.timedelta(days=100)

    # Fetch the data for the last year
    myDF = yf.download(ticker_symbol, start=start_date, end=end_date)

    myDF = myDF.reset_index()

    myDF.columns = myDF.columns.get_level_values(0)

    print(myDF.shape)

    print(myDF.iloc[0].to_dict())

    # myDF.columns = ['Date', 'Adj Close', 'Close', 'High', 'Low', 'Open', 'Volume']
    myDF.columns = ['Date', 'Close', 'High', 'Low', 'Open', 'Volume']
else:
    absolute_path = os.path.dirname(__file__)
    logger.log(f"absolute_path: {absolute_path}", level="DEBUG")
    relative_path = "data/"
    full_path = os.path.join(absolute_path, relative_path)
    logger.log(f"full_path: {full_path}", level="DEBUG")

    myDF = pd.read_csv(full_path + "spy_data.csv")

myDF = myDF.sort_values("Date", axis=0)

logger.log(f"myDF: {myDF}", level="INFO")
# Print out all the column names
logger.log(myDF.columns.tolist(), level="INFO")

# Step 2:Loop around each item in the data frame

for index, row in myDF.iterrows():
    if not use_real_data and 0 < MAX_ROWS <= index:
        break
    logger.log(f"processing row: {index}", level="DEBUG")



    # Step 3: Create a new Candle object with the supplied properties for each new row
    this_candle = Candle(row['Date'], row['Volume'], row['Open'], row['High'], row['Low'], row['Close'])
    logger.log(f"New candle created: {this_candle}", level="DEBUG")
    # Step 3.1: The candle is added to each of our rolling windows
    for key in deque_dictionary.keys():
        deque_dictionary[key].append(this_candle)

    #Step 4: We keep going without further action until we have enough data for all our rolling windows
    logger.log(f"Length of deque_dictionary period_three: {len(deque_dictionary['period_three'])}", level="DEBUG")

    if len(deque_dictionary["period_three"]) < DummyQCTrader.PERIOD_THREE_LENGTH:
        continue
    elif len(deque_dictionary["period_three"]) == DummyQCTrader.PERIOD_THREE_LENGTH:
        if rolling_window_complete_msg_display:
            logger.log(f"We now have enough data for all our rolling windows", level="INFO")
            rolling_window_complete_msg_display=False

    #Step 5: We need to update the spread and volumetric percentiles to understand relative size and strength of each Candle
    #Step 5.1: Working out the Percentiles for each Period for the spread and volume

    props = ["spread", "volume"]
    for prop in props:
        for key in deque_dictionary.keys():
            stats_list = [getattr(item, prop) for item in deque_dictionary[key]]
            logger.log(f"stats_list: {stats_list}", level="DEBUG")
            percentiles_store[prop][key] = np.percentile(stats_list, range(DummyQCTrader.PERCENTILE_START, 100,
                                                                  DummyQCTrader.PERCENTILE_INCREMENTS))
            logger.log(f"{prop}current_percentiles for {key}: {percentiles_store[prop][key]}", level="DEBUG")

    # We should now have dictionary with all the percentiles for spread and volume for each period of our rolling windows
    logger.log(f"percentiles_store: {percentiles_store}", level="DEBUG")

    #Step 5.2: We need to update all Candles in our rolling windows with their relevant percentiles
    for key in deque_dictionary.keys():
        for candle in deque_dictionary[key]:
            for prop in props:
                upper_percentile = DummyQCTrader.PERCENTILE_START
                for step in percentiles_store[prop][key]:
                    if getattr(candle, prop) <= step:
                        upper_percentile += DummyQCTrader.PERCENTILE_INCREMENTS
                if prop == "spread":
                    candle.spread_percentiles[key] = upper_percentile
                elif prop == "volume":
                    candle.volume_percentiles[key] = upper_percentile
            if key == "period_three":
                logger.log(f"candle: {candle}", level="DEBUG")

    #Step 6: Now we are looking for Signals - We start by understanding if the market is trending and if so, in what direction
    adx_values = calculate_adx(deque_dictionary["period_three"])
    logger.log(f"{this_candle.time} - adx_values: {adx_values}", level="INFO")

    trending=False
    trending_up=False
    trending_down=False

    if adx_values[0] > 25:
        trending = True
        logger.log("TRENDING ABOVE 25", level="INFO")
        if adx_values[2] > adx_values[3]:
            trending_up=True
            logger.log(f"TRENDING UP: {adx_values[2] / adx_values[3]}", level="INFO" )
        if adx_values[3] > adx_values[2]:
            trending_down=True
            logger.log(f"TRENDING DOWN: {adx_values[3] / adx_values[2]}", level="INFO" )

    #Step 7: Count the relevant candle types in each time period
    bar_counts = {}
    signals = {
        "period_one_bull": False,
        "period_one_bear": False,
        "period_one_volume_backed": False,
        "period_two_bull": False,
        "period_two_bear": False,
        "period_two_volume_backed": False,
        "period_three_bull": False,
        "period_three_bear": False,
        "period_three_volume_backed": False,
    }

    for key in deque_dictionary.keys():
        up_bar_count = sum(1 for candle in deque_dictionary[key] if candle.up_bar)
        high_spread_count = sum(
            1 for candle in deque_dictionary[key] if candle.spread_percentiles[key] > trading_parameters[key]["High_Spread_Threshold"])
        high_volume_count = sum(
            1 for candle in deque_dictionary[key] if candle.volume_percentiles[key] > trading_parameters[key]["High_Volume_Threshold"])
        anomaly_count = sum(1 for candle in deque_dictionary[key] if
                            abs(candle.spread_percentiles[key] - candle.volume_percentiles[key]) >
                            trading_parameters[key]["Anomaly_Threshold"])

        bar_counts[key] = {
            "up_bars": up_bar_count,
            "high_spread_count": high_spread_count,
            "high_volume_count": high_volume_count,
            "anomaly_count": anomaly_count
        }
        logger.log(f"{key} Bar Counts: {bar_counts[key]}", level="DEBUG")

        # Step 8: We should now have the relevant counts to decide whether a signal is being generated on each time period
        if up_bar_count >= trading_parameters[key]["Signal_Bar_Count"]:
            signals[f"{key}_bull"] = True
            logger.log(f"{key} Bullish Signal", level="DEBUG")
        elif up_bar_count <= (DummyQCTrader.PERIOD_ONE_LENGTH - trading_parameters[key]["Signal_Bar_Count"]):
            signals[f"{key}_bear"] = True
            logger.log(f"{key} Bearish Signal", level="DEBUG")

        if signals[f"{key}_bear"] or signals[f"{key}_bull"]:
            if high_spread_count >= DummyQCTrader.trading_parameters[key][
                "High_Spread_Count"] and \
            high_volume_count >= DummyQCTrader.trading_parameters[key][
                "High_Volume_Count"] and \
            anomaly_count <= DummyQCTrader.trading_parameters[key][
                "Anomaly_Threshold"]:
                signals[f"{key}_volume_backed"] = True
                logger.log(f"{this_candle.time} {key} Volume Backed Signal", level="INFO")

    #Step 9: Try to identify if the market is near accumulation of distribution points
    acc_or_dist_bool, acc_or_dist = identify_acc_or_dist(deque_dictionary["period_three"],
                                                   deque_dictionary["period_one"])

    if acc_or_dist_bool:
        logger.log(f"{this_candle.time} Possible {acc_or_dist} IDENTIFIED #####", level="INFO")

        if this_candle.spread_percentiles['period_one'] > 65 or this_candle.is_candle_pattern():
            logger.log(f"Potential Test IDENTIFIED ##########", level="DEBUG")
            if this_candle.volume_percentiles['period_one'] < 50:
                logger.log(f"Potential TEST PASS IDENTIFIED ##########", level="INFO")
            else:
                logger.log("Potential TEST FAIL IDENTIFIED ##########", level="INFO")

