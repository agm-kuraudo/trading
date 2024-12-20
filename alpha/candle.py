import os
import statistics
from collections import deque

import pandas as pd
import numpy as np

def calculate_true_range(candle1, candle2):
    # True Range (TR) is the greatest of the following:
    # - Current High minus Current Low
    # - Absolute value of Current High minus Previous Close
    # - Absolute value of Current Low minus Previous Close
    return max(candle2.high - candle2.low, abs(candle2.high - candle1.close), abs(candle2.low - candle1.close))

def calculate_dm_plus(candle1, candle2):
    # Positive Directional Movement (DM+) is calculated as:
    # - Current High minus Previous High if it is greater than Current Low minus Previous Low
    # - Otherwise, it is zero
    return max(candle2.high - candle1.high, 0) if (candle2.high - candle1.high) > (candle1.low - candle2.low) else 0

def calculate_dm_minus(candle1, candle2):
    # Negative Directional Movement (DM-) is calculated as:
    # - Previous Low minus Current Low if it is greater than Current High minus Previous High
    # - Otherwise, it is zero
    return max(candle1.low - candle2.low, 0) if (candle1.low - candle2.low) > (candle2.high - candle1.high) else 0


def calculate_adx(candles, period=14):
    if len(candles) < period + 1:
        raise ValueError(f"Not enough data to calculate ADX. At least {period + 1} periods are required.")

    tr_list = []
    dm_plus_list = []
    dm_minus_list = []

    # Calculate True Range (TR), DM+, and DM- for each pair of candles
    for i in range(1, len(candles)):
        tr_list.append(calculate_true_range(candles[i-1], candles[i]))
        dm_plus_list.append(calculate_dm_plus(candles[i-1], candles[i]))
        dm_minus_list.append(calculate_dm_minus(candles[i-1], candles[i]))

    # Smooth the TR, DM+, and DM- values using a moving average
    tr_smooth = [sum(tr_list[:period])]
    dm_plus_smooth = [sum(dm_plus_list[:period])]
    dm_minus_smooth = [sum(dm_minus_list[:period])]

    for i in range(period, len(tr_list)):
        tr_smooth.append(tr_smooth[-1] - (tr_smooth[-1] / period) + tr_list[i])
        dm_plus_smooth.append(dm_plus_smooth[-1] - (dm_plus_smooth[-1] / period) + dm_plus_list[i])
        dm_minus_smooth.append(dm_minus_smooth[-1] - (dm_minus_smooth[-1] / period) + dm_minus_list[i])

    # Calculate the Directional Indicators (DI+ and DI-)
    di_plus = [100 * (dm_plus_smooth[i] / tr_smooth[i]) for i in range(len(tr_smooth))]
    di_minus = [100 * (dm_minus_smooth[i] / tr_smooth[i]) for i in range(len(tr_smooth))]

    # Calculate the Directional Movement Index (DX)
    dx = [100 * abs(di_plus[i] - di_minus[i]) / (di_plus[i] + di_minus[i]) for i in range(len(di_plus))]

    # Calculate the Average Directional Index (ADX)
    adx = [sum(dx[:period]) / period]
    for i in range(period, len(dx)):
        adx.append((adx[-1] * (period - 1) + dx[i]) / period)

    return [adx[0], statistics.fmean(tr_smooth), statistics.fmean(dm_plus_smooth), statistics.fmean(dm_minus_smooth)]


def identify_acc_or_dist(period_three, period_one):

    volume_stats_list = []
    price_stats_list = []
    for item in period_three:
        volume_stats_list.append(getattr(item, "volume"))
        price_stats_list.append(getattr(item, "close"))

    print(volume_stats_list)
    period_three_volume_percentiles = np.percentile(volume_stats_list, [65, 90])

    print(price_stats_list)
    period_three_price_percentiles = np.percentile(price_stats_list, [10, 20, 80])

    print(period_three_volume_percentiles)
    print(period_three_price_percentiles)

    high_volume_count = 0
    for item in period_one:
        print(getattr(item, "volume"))
        if getattr(item, "volume") > period_three_volume_percentiles[0]:
            high_volume_count+=1
    # Calculate all the percentiles from 10% upwards in increments
    print(high_volume_count)

    near_lows = True
    near_highs = True

    if period_one[-1].close < period_three_price_percentiles[1]:
        print("Price is near recent lows")
        near_lows = True
    else:
        print("Price is not near recent low")
        near_lows = False

    if period_one[-1].close > period_three_price_percentiles[2]:
        print("Price is near recent highs")
        near_highs = True
    else:
        print("Price is not near recent highs")
        near_highs = False


    if high_volume_count >= 3 and near_lows:
        return True, "Acc"
    elif high_volume_count >= 3 and near_highs:
        return True, "Dist"
    else:
        return False, ""

class Candle:
    DEBUG = False

    CONFIG_SHOOTING_STAR_UPPER_WICK_X_TIMES_BIGGER_THAN_SPREAD = 2
    CONFIG_SHOOTING_STAR_UPPER_WICK_X_TIMES_BIGGER_THAN_LOWER_WICK = 2
    CONFIG_HAMMER_LOWER_WICK_X_TIMES_BIGGER_THAN_SPREAD = 2
    CONFIG_HAMMER_LOWER_WICK_X_TIMES_BIGGER_THAN_UPPER_WICK = 2
    CONFIG_LLD_BOTH_WICKS_X_TIMES_BIGGER_THAN_SPREAD = 2

    # Candle is initialised with all the properties that are provided by a Candlestick - volume, open, high, low, close
    def __init__(self, time, volume, candle_open, high, low, close):
        self.__volume_percentiles = {}
        self.__spread_percentiles = {}
        self.__anomaly = {}
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
        # such as the spread and whether it's an up or down candle.
        self.__up_bar = close > candle_open
        self.__spread = abs(close - candle_open)
        self.__high_low_spread = high - low
        self.__high_open_spread = high - candle_open
        self.__low_close_spread = low - close
        self.__high_close_spread = high - close

        self.__upper_wick = high - close
        self.__lower_wick = close - low

        self.__shooting_star = False
        self.__hammer = False
        self.__lld = False

        # If the upper wick is two times bigger than the spread and the lower wick - shooting star candle
        if (self.__upper_wick > (self.__spread * Candle.CONFIG_SHOOTING_STAR_UPPER_WICK_X_TIMES_BIGGER_THAN_SPREAD)
                and self.__upper_wick > (self.__lower_wick *
                                         Candle.CONFIG_SHOOTING_STAR_UPPER_WICK_X_TIMES_BIGGER_THAN_LOWER_WICK)):
            self.__shooting_star = True

        # If the lower wick is two times bigger than the spread and the upper wick - Hammer candle
        if (self.__lower_wick > (self.__spread * Candle.CONFIG_HAMMER_LOWER_WICK_X_TIMES_BIGGER_THAN_SPREAD)
                and self.__lower_wick > (self.__upper_wick *
                                         Candle.CONFIG_HAMMER_LOWER_WICK_X_TIMES_BIGGER_THAN_UPPER_WICK)):
            self.__hammer = True

        # If both the lower wick and the higher wick are double the spread - long-legged Doji
        if (self.__upper_wick > self.__spread * Candle.CONFIG_LLD_BOTH_WICKS_X_TIMES_BIGGER_THAN_SPREAD
                and self.__lower_wick > self.__spread * Candle.CONFIG_LLD_BOTH_WICKS_X_TIMES_BIGGER_THAN_SPREAD):
            self.__lld = True
            # If it's a lld then probably shouldn't also be marked as a Hammer or Shooting star!
            self.__shooting_star = False
            self.__hammer = False

    def __str__(self) -> str:
        if self.__up_bar:
            bar_type = "up_bar"
        else:
            bar_type = "down_bar"

        patterns = ""
        if self.__shooting_star:
            patterns += ":Shooting Star:"
        if self.__hammer:
            patterns += ":Hammer:"
        if self.__lld:
            patterns += ":Long Legged Doji:"

        return ("Candle {} is an {} opened at {} and closed at {}. High was {}. Low was {}. Spread was {}. Volume was {}. "
                "Upper Wick was {}. Lower Wick was {}. Pattern was {}.  Spread Percentiles: {}, Volume Percentiles: {}").format(
            self.__time,
            bar_type,
            self.__open,
            self.__close,
            self.__high,
            self.__low,
            self.spread,
            self.volume,
            self.__upper_wick,
            self.__lower_wick,
            patterns,
            self.__spread_percentiles.get("period_one"),
            self.__volume_percentiles.get("period_one"))


    @property
    def volume(self):
        return self.__volume

    @property
    def high(self):
        return self.__high

    @property
    def low(self):
        return self.__low

    @property
    def open(self):
        return self.__open

    @property
    def close(self):
        return self.__close


    @property
    def up_bar(self):
        return self.__up_bar

    @property
    def spread(self):
        return self.__spread

    @property
    def spread_percentiles(self):
        return self.__spread_percentiles

    @spread_percentiles.setter
    def spread_percentiles(self, value):
        self.__spread_percentiles = value

    @property
    def volume_percentiles(self):
        return self.__volume_percentiles

    @volume_percentiles.setter
    def volume_percentiles(self, value):
        self.__volume_percentiles = value
        if self.__spread_percentiles is not None:
            for key in self.__volume_percentiles.keys():
                # print(key)
                # print(self.__volume_percentiles[key])
                # print(self.__spread_percentiles[key])
                self.__anomaly[key] = self.__volume_percentiles[key] - self.spread_percentiles[key]
                if Candle.DEBUG:
                    print(f"Anomaly: {self.__anomaly[key]}")


class DummyQCTrader:
    DEBUG = False
    # Set up the short, medium and long term intervals to use.  A bit arbitrary, Eventually can test and tweak
    PERIOD_ONE_LENGTH = 5
    PERIOD_TWO_LENGTH = 25
    PERIOD_THREE_LENGTH = 50
    PERCENTILE_START = 5
    PERCENTILE_INCREMENTS = 5

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

    def __init__(self):
        # We create three "deques" based on those time frames

        self.all_periods = [DummyQCTrader.PERIOD_ONE_LENGTH,
                            DummyQCTrader.PERIOD_TWO_LENGTH,
                            DummyQCTrader.PERIOD_THREE_LENGTH]
        self.spread_percentiles = {}
        self.volume_percentiles = {}

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

        adx_values = None

        # Create a new Candle object with the supplied properties
        this_candle = Candle(time, volume, candle_open, high, low, close)
        if len(self.deque_dictionary["period_three"]) == DummyQCTrader.PERIOD_THREE_LENGTH:

            adx_values = calculate_adx(self.deque_dictionary["period_three"])
            print(adx_values)

            for period, key in zip(self.all_periods, self.deque_dictionary.keys()):
                if DummyQCTrader.DEBUG:
                    print(period, key)

                self.spread_percentiles[key] = self.get_percentile_stats(
                    prop="spread",
                    period_key=key,
                    period_length=period,
                    this_candle=this_candle)

                if DummyQCTrader.DEBUG:
                    print(f"{period} spread percentile {self.spread_percentiles[key]}")

                self.volume_percentiles[key] = self.get_percentile_stats(
                    prop="volume",
                    period_key=key,
                    period_length=period,
                    this_candle=this_candle)

                if DummyQCTrader.DEBUG:
                    print(f"{period} volume percentile {self.volume_percentiles[key]}")

                this_candle.spread_percentiles = self.spread_percentiles
                this_candle.volume_percentiles = self.volume_percentiles


        # Add the new candle to each deque.
        for key in self.deque_dictionary.keys():
            self.deque_dictionary[key].append(this_candle)

        print(this_candle)

        period_one_signal = self.multiple_bar_signal("period_one", self.multiple_bar_check("period_one"))

        if period_one_signal == 1:
            print("PERIOD_ONE_SIGNAL - BULL")
        elif period_one_signal == -1:
            print("PERIOD_ONE_SIGNAL - BEAR")

        period_two_signal = self.multiple_bar_signal("period_two", self.multiple_bar_check("period_two"))

        if period_two_signal == 1:
            print("PERIOD_TWO_SIGNAL - BULL")
        elif period_two_signal == -1:
            print("PERIOD_THREE_SIGNAL - BEAR")

        period_three_signal = self.multiple_bar_signal("period_three", self.multiple_bar_check("period_three"))

        if period_three_signal == 1:
            print("PERIOD_THREE_SIGNAL - BULL")
        elif period_three_signal == -1:
            print("PERIOD_THREE_SIGNAL - BEAR")

        if adx_values is not None:
            if adx_values[0] > 25:
                print("TRENDING ABOVE 25")
            else:
                #Not trending, check for accumulation phase
                print("NOT TRENDING - CHECKING FOR ACCUMULATION")

                return_val, acc_or_dist = identify_acc_or_dist(self.deque_dictionary["period_three"], self.deque_dictionary["period_one"])

                if return_val:
                    print(f"{acc_or_dist} IDENTIFIED #####")

            if adx_values[2] > adx_values[3]:
                print(f"TRENDING UP: {adx_values[2] / adx_values[3]}" )
            if adx_values[3] > adx_values[2]:
                print(f"TRENDING DOWN: {adx_values[3] / adx_values[2]}" )


    def multiple_bar_signal(self, period_key, bar_check_results) -> int:

        momentum = False
        return_code = 0

        if bar_check_results:

            if bar_check_results["up_bars"] >= DummyQCTrader.trading_parameters[period_key]["Signal_Bar_Count"]:
                if DummyQCTrader.DEBUG:
                    print("Bullish Market")
                momentum = True
                return_code = 1
            elif bar_check_results["up_bars"] <= (
                    DummyQCTrader.PERIOD_ONE_LENGTH - DummyQCTrader.trading_parameters[period_key]["Signal_Bar_Count"]):
                if DummyQCTrader.DEBUG:
                    print("Bearish Market")
                momentum = True
                return_code = -1

            if not momentum:
                return 0

            if bar_check_results["high_spread_count"] >= DummyQCTrader.trading_parameters[period_key]["High_Spread_Count"] and \
                    bar_check_results["high_volume_count"] >= DummyQCTrader.trading_parameters[period_key]["High_Volume_Count"] and \
                    bar_check_results["anomaly_count"] <= DummyQCTrader.trading_parameters[period_key]["Anomaly_Threshold"]:
                if DummyQCTrader.DEBUG:
                    print("Backed by volume")
                return return_code
            else:
                if DummyQCTrader.DEBUG:
                    print("Not Backed by volume")
                return 0

    def get_percentile_stats(self, prop: str, period_key: str, period_length: int, this_candle: Candle) -> int:
        # If we have Deque period ready lets work out where the volume and spread fall as a percentile
        # remember we are expecting this on data method to be called frequently - this won't be true on the first
        # iterations
        if len(self.deque_dictionary[period_key]) == period_length:
            # Get the spread for each candle in the period and save to a list
            stats_list = []
            for item in self.deque_dictionary[period_key]:
                stats_list.append(getattr(item, prop))
            # Calculate all the percentiles from 10% upwards in increments
            current_percentiles = np.percentile(stats_list, [
                range(DummyQCTrader.PERCENTILE_START, 100, DummyQCTrader.PERCENTILE_INCREMENTS)])
            if DummyQCTrader.DEBUG:
                print(current_percentiles)

            # Loop round and see where the latest figure falls in the percentile list
            upper_percentile = DummyQCTrader.PERCENTILE_START
            for data in current_percentiles[0]:
                if getattr(this_candle, prop) < data:
                    if DummyQCTrader.DEBUG:
                        print(
                            f"This candle {prop} is {getattr(this_candle, prop)} which falls below the {upper_percentile} percentile")
                    break
                upper_percentile += DummyQCTrader.PERCENTILE_INCREMENTS
            return upper_percentile

    def multiple_bar_check(self, period_key="period_one", high_spread_threshold=55, high_volume_threshold=55,
                           anomaly_threshold=20) -> dict:

        if period_key == "period_one":
            check_period = DummyQCTrader.PERIOD_ONE_LENGTH
        elif period_key == "period_two":
            check_period = DummyQCTrader.PERIOD_TWO_LENGTH
        elif period_key == "period_three":
            check_period = DummyQCTrader.PERIOD_THREE_LENGTH
        else:
            print("invalid period key provided")
            return {}

        if len(self.deque_dictionary[period_key]) != check_period:
            print("Not ready for this check yet")
            return {}

        high_spread_count = 0
        high_volume_count = 0
        up_counts = 0
        anomaly_count = 0

        for individual_candle in self.deque_dictionary[period_key]:
            if DummyQCTrader.DEBUG:
                print(type(individual_candle))
                print(individual_candle.spread_percentiles.keys())

            if individual_candle.spread_percentiles.get(period_key) is None:
                print("No keys in dictionary")
                return {}

            if individual_candle.up_bar:
                up_counts += 1
            if individual_candle.spread_percentiles.get(period_key) > high_spread_threshold:
                high_spread_count += 1
            if individual_candle.volume_percentiles.get(period_key) > high_volume_threshold:
                high_volume_count += 1

            if abs(individual_candle.spread_percentiles.get(period_key) -
                   individual_candle.volume_percentiles.get(period_key)) > anomaly_threshold:
                anomaly_count += 1
        print(
            f"{period_key}. Up bars: {up_counts}. High Spreads: {high_spread_count}. High Volumes: {high_volume_count}, Anomalies: {anomaly_count}")
        return {"up_bars": up_counts,
                "high_spread_count": high_spread_count,
                "high_volume_count": high_volume_count,
                "anomaly_count": anomaly_count}




# Get our test data from CSV file...
# this would come from live quant data eventually

absolute_path = os.path.dirname(__file__)
relative_path = "../test_data/"
full_path = os.path.join(absolute_path, relative_path)

# myDF = pd.read_csv(full_path + "^gbpusd_price-history-08-29-2023.csv")
# myDF = myDF.sort_values("Time", axis=0)
#
# print(myDF)
#
# myTrader = DummyQCTrader()
#
# # Loop around each item in the data frame and call my dummy on data method
# for index, row in myDF.iterrows():
#     print(row['Time'], row['Volume'], row['Open'], row['High'], row['Low'], row['Last'])
#     myTrader.dummy_on_data(row['Time'], row['Volume'], row['Open'], row['High'], row['Low'], row['Last'])
#     exit()



myDF = pd.read_csv(full_path + "spy_data.csv")
myDF = myDF.sort_values("Date", axis=0)

print(myDF)

myTrader = DummyQCTrader()

# Loop around each item in the data frame and call my dummy on data method
for index, row in myDF.iterrows():
    myTrader.dummy_on_data(row['Date'], row['Volume'], row['Open'], row['High'], row['Low'], row['Adj Close'])

