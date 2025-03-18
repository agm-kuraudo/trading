import os
import statistics
from collections import deque
from datetime import datetime
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

    # print(tr_list[:5])  # Print the first 5 TR values
    # print(dm_plus_list[:5])  # Print the first 5 DM+ values
    # print(dm_minus_list[:5])  # Print the first 5 DM- values

    # Smooth the TR, DM+, and DM- values using a moving average
    tr_smooth = [sum(tr_list[:period])]
    dm_plus_smooth = [sum(dm_plus_list[:period])]
    dm_minus_smooth = [sum(dm_minus_list[:period])]

    for i in range(period, len(tr_list)):
        tr_smooth.append(tr_smooth[-1] - (tr_smooth[-1] / period) + tr_list[i])
        dm_plus_smooth.append(dm_plus_smooth[-1] - (dm_plus_smooth[-1] / period) + dm_plus_list[i])
        dm_minus_smooth.append(dm_minus_smooth[-1] - (dm_minus_smooth[-1] / period) + dm_minus_list[i])

    # print(tr_smooth[:5])  # Print the first 5 smoothed TR values
    # print(dm_plus_smooth[:5])  # Print the first 5 smoothed DM+ values
    # print(dm_minus_smooth[:5])  # Print the first 5 smoothed DM- values

    # Calculate the Directional Indicators (DI+ and DI-)
    di_plus = [100 * (dm_plus_smooth[i] / tr_smooth[i]) for i in range(len(tr_smooth))]
    di_minus = [100 * (dm_minus_smooth[i] / tr_smooth[i]) for i in range(len(tr_smooth))]

    # print(di_plus[:5])  # Print the first 5 DI+ values
    # print(di_minus[:5])  # Print the first 5 DI- values

    # Calculate the Directional Movement Index (DX)
    dx = [100 * abs(di_plus[i] - di_minus[i]) / (di_plus[i] + di_minus[i]) for i in range(len(di_plus))]

    # print(dx[:5])  # Print the first 5 DX values

    # Calculate the Average Directional Index (ADX)
    adx = [sum(dx[:period]) / period]
    for i in range(period, len(dx)):
        adx.append((adx[-1] * (period - 1) + dx[i]) / period)

    # print(adx[:5])  # Print the first 5 ADX values

    return [adx[0], statistics.fmean(tr_smooth), statistics.fmean(dm_plus_smooth), statistics.fmean(dm_minus_smooth)]


def identify_acc_or_dist(period_three, period_one):
    volume_stats_list = []
    price_stats_list = []
    for item in period_three:
        volume_stats_list.append(getattr(item, "volume"))
        price_stats_list.append(getattr(item, "close"))

    period_three_volume_percentiles = np.percentile(volume_stats_list, [65, 90])
    period_three_price_percentiles = np.percentile(price_stats_list, [10, 20, 80])

    # print(f"Volume Percentiles (65th, 90th): {period_three_volume_percentiles}")
    # print(f"Price Percentiles (10th, 20th, 80th): {period_three_price_percentiles}")

    high_volume_count = 0
    for item in period_one:
#        logger.log(f"Volume: {getattr(item, 'volume')}", level="DEBUG")
        if getattr(item, "volume") > period_three_volume_percentiles[0]:
            high_volume_count += 1

    # print(f"High Volume Count: {high_volume_count}")
    near_lows = period_one[-1].close < period_three_price_percentiles[1]
    near_highs = period_one[-1].close > period_three_price_percentiles[2]

    # print(f"Near Lows: {near_lows}, Near Highs: {near_highs}")

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

        # Nothing is currently done with the time element, but it may be useful
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
                "Upper Wick was {}. Lower Wick was {}. Pattern was {}.  Spread Percentiles: {}:{}:{}, Volume Percentiles: {}:{}:{}").format(
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
            self.__spread_percentiles.get("period_two"),
            self.__spread_percentiles.get("period_three"),
            self.__volume_percentiles.get("period_one"),
            self.__volume_percentiles.get("period_two"),
            self.__volume_percentiles.get("period_three"))

    def is_candle_pattern(self):
        if self.__shooting_star or self.__hammer or self.__lld:
            return True
        else:
            return False

    @property
    def shooting_star(self):
        return self.__shooting_star

    @property
    def hammer(self):
        return self.__hammer

    @property
    def lld(self):
        return self.__lld

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

    @property
    def time(self):
        return self.__time

    @volume_percentiles.setter
    def volume_percentiles(self, value):
        self.__volume_percentiles = value
        if self.__spread_percentiles is not None:
            for key in self.__volume_percentiles.keys():
                self.__anomaly[key] = self.__volume_percentiles[key] - self.spread_percentiles[key]
                # if Candle.DEBUG:
                #     logger.log(f"Anomaly: {self.__anomaly[key]}")

# class DummyQCTrader:
#     DEBUG = False
#     # Set up the short, medium and long term intervals to use.  A bit arbitrary, Eventually can test and tweak
#     PERIOD_ONE_LENGTH = 5
#     PERIOD_TWO_LENGTH = 25
#     PERIOD_THREE_LENGTH = 50
#     PERCENTILE_START = 5
#     PERCENTILE_INCREMENTS = 5
#
#     # Set up for multiple bar signal checks
#     trading_parameters = {
#         "period_one": {
#             "High_Spread_Threshold": 55,
#             "High_Volume_Threshold": 55,
#             "Anomaly_Threshold": 20,
#             "Signal_Bar_Count": 4,
#             "High_Spread_Count": 3,
#             "High_Volume_Count": 3
#         },
#         "period_two": {
#             "High_Spread_Threshold": 55,
#             "High_Volume_Threshold": 55,
#             "Anomaly_Threshold": 20,
#             "Signal_Bar_Count": 7,
#             "High_Spread_Count": 6,
#             "High_Volume_Count": 6
#         },
#         "period_three": {
#             "High_Spread_Threshold": 55,
#             "High_Volume_Threshold": 55,
#             "Anomaly_Threshold": 20,
#             "Signal_Bar_Count": 16,
#             "High_Spread_Count": 12,
#             "High_Volume_Count": 12
#         }
#     }
#
#     def __init__(self, logger=None):
#         self.all_periods = [DummyQCTrader.PERIOD_ONE_LENGTH,
#                             DummyQCTrader.PERIOD_TWO_LENGTH,
#                             DummyQCTrader.PERIOD_THREE_LENGTH]
#
#         try:
#             logger.log(f"DummyQC Class initialised - all_periods: {self.all_periods}", level="DEBUG")
#         except NameError as e:
#             print(f"DummyQC Class initialised - all_periods: {self.all_periods}")
#
#         self.spread_percentiles = {}
#         self.volume_percentiles = {}
#
#         self.deque_dictionary = {
#             "period_one": deque(maxlen=DummyQCTrader.PERIOD_ONE_LENGTH),
#             "period_two": deque(maxlen=DummyQCTrader.PERIOD_TWO_LENGTH),
#             "period_three": deque(maxlen=DummyQCTrader.PERIOD_THREE_LENGTH)
#         }

    # # This is a dummy version of what will be the OnData method in QC
    # def dummy_on_data(self, time, volume, candle_open, high, low, close):
    #
    #     logger.log(f"dummy_on_data called with data: {time} {volume} {candle_open} {high} {low} {close}", level="DEBUG")
    #
    #     # Make sure we have valid candle data - should always be the case
    #     if np.isnan(candle_open):
    #         logger.log(f"Invalid candle data provided: {time} {volume} {candle_open} {high} {low} {close}",
    #                    level="ERROR")
    #         return
    #
    #     adx_values = None
    #
    #     # Create a new Candle object with the supplied properties
    #     this_candle = Candle(time, volume, candle_open, high, low, close)
    #     logger.log(f"New candle created: {this_candle}", level="INFO")
    #     logger.log(f"Length of deque_dictionary period_three: {len(self.deque_dictionary["period_three"])}", level="DEBUG")
    #
    #     if len(self.deque_dictionary["period_three"]) == DummyQCTrader.PERIOD_THREE_LENGTH:
    #
    #         adx_values = calculate_adx(self.deque_dictionary["period_three"])
    #         logger.log(f"adx_values: {adx_values}")
    #
    #         for period, key in zip(self.all_periods, self.deque_dictionary.keys()):
    #             logger.log(f"Now looking at period: {period}, key: {key}")
    #
    #             self.spread_percentiles[key] = self.get_percentile_stats_legacy_version(
    #                 prop="spread",
    #                 period_key=key,
    #                 period_length=period,
    #                 this_candle=this_candle)
    #
    #             logger.log(f"{key} spread percentile {self.spread_percentiles[key]}")
    #
    #             self.volume_percentiles[key] = self.get_percentile_stats_legacy_version(
    #                 prop="volume",
    #                 period_key=key,
    #                 period_length=period,
    #                 this_candle=this_candle)
    #
    #             logger.log(f"{key} volume percentile {self.volume_percentiles[key]}")
    #
    #             this_candle.spread_percentiles = self.spread_percentiles
    #             this_candle.volume_percentiles = self.volume_percentiles
    #
    #             logger.log(f"This candle spread percentiles: {this_candle.spread_percentiles}")
    #             logger.log(f"This candle volume percentiles: {this_candle.volume_percentiles}")
    #
    #     # Add the new candle to each deque and check signals
    #     for key in self.deque_dictionary.keys():
    #         self.deque_dictionary[key].append(this_candle)
    #
    #         signal = self.multiple_bar_signal(key, self.multiple_bar_check(key))
    #         logger.log(f"{key}_signal: {signal}", level="DEBUG")
    #
    #         if signal == 1:
    #             logger.log(f"{key.upper()}_SIGNAL - BULL", level="INFO")
    #         elif signal == -1:
    #             logger.log(f"{key.upper()}_SIGNAL - BEAR", level="INFO")
    #
    #     if adx_values is not None:
    #         if adx_values[0] > 25:
    #             logger.log("TRENDING ABOVE 25", level="INFO")
    #         else:
    #             #Not trending, check for accumulation phase
    #             logger.log("NOT TRENDING - CHECKING FOR ACCUMULATION", level="DEBUG")
    #
    #             return_val, acc_or_dist = identify_acc_or_dist(self.deque_dictionary["period_three"], self.deque_dictionary["period_one"])
    #
    #             if return_val:
    #                 logger.log(f"{acc_or_dist} IDENTIFIED #####", level="INFO")
    #                 logger.log(f"{this_candle.spread_percentiles} {this_candle.volume_percentiles}", level="DEBUG")
    #
    #         if adx_values[2] > adx_values[3]:
    #             logger.log(f"TRENDING UP: {adx_values[2] / adx_values[3]}", level="DEBUG" )
    #         if adx_values[3] > adx_values[2]:
    #             logger.log(f"TRENDING DOWN: {adx_values[3] / adx_values[2]}", level="DEBUG" )

    # def multiple_bar_signal(self, period_key, bar_check_results) -> int:
    #     momentum = False
    #     return_code = 0
    #
    #     if bar_check_results:
    #         if bar_check_results["up_bars"] >= DummyQCTrader.trading_parameters[period_key]["Signal_Bar_Count"]:
    #             logger.log("Bullish Market", level="DEBUG")
    #             momentum = True
    #             return_code = 1
    #         elif bar_check_results["up_bars"] <= (
    #                 DummyQCTrader.PERIOD_ONE_LENGTH - DummyQCTrader.trading_parameters[period_key]["Signal_Bar_Count"]):
    #             logger.log("Bearish Market", level="DEBUG")
    #             momentum = True
    #             return_code = -1
    #
    #         if not momentum:
    #             return 0
    #
    #         if bar_check_results["high_spread_count"] >= DummyQCTrader.trading_parameters[period_key][
    #             "High_Spread_Count"] and \
    #                 bar_check_results["high_volume_count"] >= DummyQCTrader.trading_parameters[period_key][
    #             "High_Volume_Count"] and \
    #                 bar_check_results["anomaly_count"] <= DummyQCTrader.trading_parameters[period_key][
    #             "Anomaly_Threshold"]:
    #             logger.log("Backed by volume", level="DEBUG")
    #             return return_code
    #         else:
    #             logger.log("Not Backed by volume", level="DEBUG")
    #             return 0

    # def get_percentile_stats_legacy_version(self, prop: str, period_key: str, period_length: int, this_candle: Candle) -> int:
    #     if len(self.deque_dictionary[period_key]) == period_length:
    #         stats_list = [getattr(item, prop) for item in self.deque_dictionary[period_key]]
    #         current_percentiles = np.percentile(stats_list, range(DummyQCTrader.PERCENTILE_START, 100,
    #                                                               DummyQCTrader.PERCENTILE_INCREMENTS))
    #         try:
    #             logger.log(f"Current percentiles: {current_percentiles}", level="DEBUG")
    #         except NameError as e:
    #             print(f"Current percentiles: {current_percentiles}")
    #
    #         upper_percentile = DummyQCTrader.PERCENTILE_START
    #         for data in current_percentiles:
    #             if getattr(this_candle, prop) < data:
    #                 try:
    #                     logger.log(
    #                         f"This candle {prop} is {getattr(this_candle, prop)} which falls below the {upper_percentile} percentile",
    #                         level="DEBUG")
    #                 except NameError as e:
    #                     print(f"This candle {prop} is {getattr(this_candle, prop)} which falls below the {upper_percentile} percentile")
    #                 break
    #             upper_percentile += DummyQCTrader.PERCENTILE_INCREMENTS
    #         return upper_percentile
    #     else:
    #         print(f"Not ready for this check yet {len(self.deque_dictionary[period_key])} {period_length}")
    #         return 0

    # def multiple_bar_check(self, period_key="period_one", high_spread_threshold=55, high_volume_threshold=55,
    #                        anomaly_threshold=20) -> dict:
    #     if period_key == "period_one":
    #         check_period = DummyQCTrader.PERIOD_ONE_LENGTH
    #     elif period_key == "period_two":
    #         check_period = DummyQCTrader.PERIOD_TWO_LENGTH
    #     elif period_key == "period_three":
    #         check_period = DummyQCTrader.PERIOD_THREE_LENGTH
    #     else:
    #         logger.log("Invalid period key provided", level="ERROR")
    #         return {}
    #
    #     if len(self.deque_dictionary[period_key]) != check_period:
    #         logger.log(f"Not ready for this check yet {period_key}", level="DEBUG")
    #         return {}
    #     else:
    #         logger.log(f"Ready for this check {period_key}", level="DEBUG")
    #
    #     high_spread_count = 0
    #     high_volume_count = 0
    #     up_counts = 0
    #     anomaly_count = 0
    #
    #     for individual_candle in self.deque_dictionary[period_key]:
    #         if individual_candle.spread_percentiles.get(period_key) is None:
    #             logger.log(f"No keys in dictionary for {individual_candle}", level="ERROR")
    #             return {}
    #
    #         logger.log(
    #             f"Checking candle {individual_candle.time} - spread: {individual_candle.spread_percentiles.get(period_key)} volume: {individual_candle.volume_percentiles.get(period_key)}",
    #             level="DEBUG")
    #
    #         if individual_candle.up_bar:
    #             up_counts += 1
    #             logger.log(f"Up bar - count now: {up_counts}", level="DEBUG")
    #         else:
    #             logger.log("Not an up bar", level="DEBUG")
    #         if individual_candle.spread_percentiles.get(period_key) > high_spread_threshold:
    #             high_spread_count += 1
    #             logger.log(f"High spread count now: {high_spread_count}", level="DEBUG")
    #         else:
    #             logger.log("Not a high spread", level="DEBUG")
    #         if individual_candle.volume_percentiles.get(period_key) > high_volume_threshold:
    #             high_volume_count += 1
    #             logger.log(f"High volume count now: {high_volume_count}", level="DEBUG")
    #         else:
    #             logger.log("Not a high volume", level="DEBUG")
    #         if abs(individual_candle.spread_percentiles.get(period_key) - individual_candle.volume_percentiles.get(
    #                 period_key)) > anomaly_threshold:
    #             anomaly_count += 1
    #             logger.log(f"Anomaly count now: {anomaly_count}", level="DEBUG")
    #         else:
    #             logger.log("Not an anomaly", level="DEBUG")
    #
    #     logger.log(
    #         f"{period_key}. Up bars: {up_counts}. High Spreads: {high_spread_count}. High Volumes: {high_volume_count}, Anomalies: {anomaly_count}",
    #         level="INFO")
    #     return {"up_bars": up_counts, "high_spread_count": high_spread_count, "high_volume_count": high_volume_count,
    #             "anomaly_count": anomaly_count}


class DebugLog:
    LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

    def __init__(self, level="DEBUG"):
        self.level = self.LEVELS.get(level, 10)
        absolute_path = os.path.dirname(__file__)
        relative_path = "log/"
        full_path = os.path.join(absolute_path, relative_path)

        # Get the current date and time
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"debug_log_{current_time}.txt"

        self.log_file = open(os.path.join(full_path, log_filename), "w")
        print("Writing log messages to: ", self.log_file.name)

    def log(self, message, level="DEBUG"):
        if self.LEVELS.get(level, 10) >= self.level:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_message = f"{timestamp} - {level} - {message}"
            self.log_file.write(log_message + "\n")
            self.log_file.flush()
            print(log_message)

    def __del__(self):
        self.log_file.close()

# if __name__ == "__main__":
#
#     MAX_ROWS = 100
#     logger = DebugLog(level="DEBUG")
#
#     logger.log("This code should only be running if candle.py has been called directly", level="INFO")
#     # Get our test data from CSV file...
#     # this would come from live quant data eventually
#     absolute_path = os.path.dirname(__file__)
#     logger.log(f"absolute_path: {absolute_path}", level="DEBUG")
#     relative_path = "data/"
#     full_path = os.path.join(absolute_path, relative_path)
#     logger.log(f"full_path: {full_path}", level="DEBUG")
#
#     myDF = pd.read_csv(full_path + "spy_data.csv")
#     myDF = myDF.sort_values("Date", axis=0)
#
#     logger.log(f"myDF: {myDF}", level="DEBUG")
#
#     myTrader = DummyQCTrader()
#     # Loop around each item in the data frame and call my dummy on data method
#     for index, row in myDF.iterrows():
#         logger.log(f"processing row: {index}", level="DEBUG")
#         myTrader.dummy_on_data(row['Date'], row['Volume'], row['Open'], row['High'], row['Low'], row['Adj Close'])
#         if MAX_ROWS > 0 and index >= MAX_ROWS:
#             break

