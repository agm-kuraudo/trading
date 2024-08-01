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

    @property
    def spread(self):
        return self.__spread

class DummyQCTrader:
    # Set up the short, medium and long term intervals to use.  A bit arbitrary, Eventually can test and tweak
    PERIOD_ONE_LENGTH = 5
    PERIOD_TWO_LENGTH = 10
    PERIOD_THREE_LENGTH = 20
    PERCENTILE_START = 10
    PERCENTILE_INCREMENTS = 10

    def __init__(self):
        # We create three "deques" based on those time frames
        self.deque_dictionary = {
            "period_one": deque(maxlen=DummyQCTrader.PERIOD_ONE_LENGTH),
            "period_two": deque(maxlen=DummyQCTrader.PERIOD_TWO_LENGTH),
            "period_three": deque(maxlen=DummyQCTrader.PERIOD_THREE_LENGTH)
        }

    # This is a dummy version of what will be the OnData method in QC
    def dummy_on_data(self, time, volume, candle_open, high, low, close):
        # Make sure we have valid candle data - should always be the case
        if np.isnan(candle_open):
            return

        # Create a new Candle object with the supplied properties
        this_candle = Candle(time, volume, candle_open, high, low, close)
        print(this_candle)

        ## TODO: All this below should be in a function which returns the percentile figure so we can call if for each
        # time period without duplicate code

        # If we have Deque period 1 ready lets work out where the volume and spread fall as a percentile
        # remember we are expecting this on data method to be called frequently - this won't be true on the first
        # iterations
        if len(self.deque_dictionary["period_one"]) == DummyQCTrader.PERIOD_ONE_LENGTH:
            # Get the spread for each candle in the period and save to a list
            spreads = []
            for item in self.deque_dictionary["period_one"]:
                spreads.append(item.spread)
            # Calculate all the percentiles from 10% upwards in increments
            current_percentiles = np.percentile(spreads, [range(DummyQCTrader.PERCENTILE_START, 100, DummyQCTrader.PERCENTILE_INCREMENTS)])
            print(current_percentiles)

            # Loop round and see where the latest figure falls in the percentile list
            start_check = DummyQCTrader.PERCENTILE_START
            for data in current_percentiles[0]:
                if this_candle.spread < data:
                    print(f"This candle spread is {this_candle.spread} which falls below the {start_check} percentile")
                    break
                start_check += DummyQCTrader.PERCENTILE_INCREMENTS

        # Add the new candle to each deque.
        for key in self.deque_dictionary.keys():
            self.deque_dictionary[key].append(this_candle)



# Get our test data from CSV file...
# this would come from live quant data eventually

absolute_path = os.path.dirname(__file__)
relative_path = "../test_data/"
full_path = os.path.join(absolute_path, relative_path)

myDF = pd.read_csv(full_path + "^gbpusd_price-history-08-29-2023.csv")
myDF = myDF.sort_values("Time", axis=0)

print(myDF)

myTrader = DummyQCTrader()




# Loop around each item in the data frame and call my dummy on data method
for index, row in myDF.iterrows():
    myTrader.dummy_on_data(row['Time'], row['Volume'], row['Open'], row['High'], row['Low'], row['Last'])
