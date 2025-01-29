from alpha.candle import DebugLog, DummyQCTrader, Candle, calculate_adx
import os
import statistics
from collections import deque
from datetime import datetime
import pandas as pd
import numpy as np

logger = DebugLog(level="INFO")

#This defines how many rows/days we are going to run through
MAX_ROWS = 52

#This sets up our rolling windows over short, medium and long period
deque_dictionary = {
    "period_one": deque(maxlen=DummyQCTrader.PERIOD_ONE_LENGTH),
    "period_two": deque(maxlen=DummyQCTrader.PERIOD_TWO_LENGTH),
    "period_three": deque(maxlen=DummyQCTrader.PERIOD_THREE_LENGTH)
}

percentiles_store = {
    "spread": {},
    "volume": {}
}

# Step 1:
# Get our test data from CSV file...
# this would come from live quant data eventually
absolute_path = os.path.dirname(__file__)
logger.log(f"absolute_path: {absolute_path}", level="DEBUG")
relative_path = "data/"
full_path = os.path.join(absolute_path, relative_path)
logger.log(f"full_path: {full_path}", level="DEBUG")

myDF = pd.read_csv(full_path + "spy_data.csv")
myDF = myDF.sort_values("Date", axis=0)

logger.log(f"myDF: {myDF}", level="INFO")


# Step 2:Loop around each item in the data frame

for index, row in myDF.iterrows():
    if MAX_ROWS > 0 and index >= MAX_ROWS:
        break
    logger.log(f"processing row: {index}", level="DEBUG")

    # Step 3: Create a new Candle object with the supplied properties for each new row
    this_candle = Candle(row['Date'], row['Volume'], row['Open'], row['High'], row['Low'], row['Adj Close'])
    logger.log(f"New candle created: {this_candle}", level="DEBUG")
    # Step 3.1: The candle is added to each of our rolling windows
    for key in deque_dictionary.keys():
        deque_dictionary[key].append(this_candle)

    #Step 4: We keep going without further action until we have enough data for all our rolling windows
    logger.log(f"Length of deque_dictionary period_three: {len(deque_dictionary['period_three'])}", level="DEBUG")

    if len(deque_dictionary["period_three"]) < DummyQCTrader.PERIOD_THREE_LENGTH:
        continue
    elif len(deque_dictionary["period_three"]) == DummyQCTrader.PERIOD_THREE_LENGTH:
        logger.log(f"We now have enough data for all our rolling windows", level="INFO")

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