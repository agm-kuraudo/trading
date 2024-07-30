import os
from collections import deque

import pandas as pd
import numpy as np


class Candle:
    # Candle is initalised with all the properties that are provided by a a Candlestick - volume, open, high, low, close
    def __init__(self, time, volume, candle_open, high, low, close):
        self.__volume = volume
        self.__open = candle_open
        self.__high = high
        self.__low = low
        self.__close = close

        # Nothing is currently done with the time element but it may be useful
        self.__time = time
        # Nothing done with notes yet either but may be useful for debugging purposes in future
        self.__notes = []

        # The following section are properties that can easily be calculated from the provided properties
        # such as the spread and whether its a an up or down candle.
        self.__up_bar = close > candle_open
        self.__spread = abs(close - candle_open)
        self.__high_low_spread = high - low
        self.__high_open_spread = high - candle_open
        self.__low_close_spread = low - close
        self.__high_close_spread = high - close

    def __str__(self) -> str:
        if self.__up_bar:
            bar_type = "up_bar"
        else:
            bar_type = "down_bar"
        return "Candle is an {} opened at {} and closed at {}".format(bar_type, self.__open, self.__close)


class DummyQCTrader:

    def __init__(self):
        self.__period1_deque = deque(maxlen=5)
        self.__period2_deque = deque(maxlen=10)
        self.__period3_deque = deque(maxlen=20)

    def dummy_on_data(self, time, volume, candle_open, high, low, close):
        if np.isnan(candle_open):
            return

        this_candle = Candle(time, volume, candle_open, high, low, close)
        print(this_candle)

        # TO DO - add candle to deques.  Use queues to work out relative volume/spreads (once they are ready).
        self.__period1_deque.append(this_candle)


# Get our test data from CSV file...
# this would come from live quant data eventually

absolute_path = os.path.dirname(__file__)
relative_path = "../test_data/"
full_path = os.path.join(absolute_path, relative_path)

myDF = pd.read_csv(full_path + "^gbpusd_price-history-08-29-2023.csv")
myDF = myDF.sort_values("Time", axis=0)

print(myDF)

# Loop around each item in the data frame and call my dummy on data method
for index, row in myDF.iterrows():
    dummy_on_data(row['Time'], row['Volume'], row['Open'], row['High'], row['Low'], row['Last'])
