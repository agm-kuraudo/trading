from typing import List
from collections import deque
import numpy as np
from enum import Enum


class Candle:
    # Class variables for relative values - these could/should maybe start blank
    relative_spread_boundary = {"SHORT": [293.4, 468.0, 759.0, 806.0, 834.2],
                                "MEDIUM": [126.7, 182.5, 557.5, 829.5, 1026.4],
                                "LARGE": [93.4, 213.0, 377.5, 721.0, 1016.8]}

    relative_volume_boundary = {"SHORT": [231718., 236627.5, 244810., 253047., 257989.2],
                                "MEDIUM": [223357.5, 229034., 238311., 257165.5, 265355.7],
                                "LARGE": [226893.7, 243349., 275653., 301675., 312982.6]}

    relative_high_low_spread_boundary = {"SHORT": [293.4, 468.0, 759.0, 806.0, 834.2],
                                         "MEDIUM": [126.7, 182.5, 557.5, 829.5, 1026.4],
                                         "LARGE": [93.4, 213.0, 377.5, 721.0, 1016.8]}

    def __init__(self, time, volume, candle_open, high, low, close):
        self.__volume = volume
        self.__candle_start = candle_open
        self.__high = high
        self.__low = low
        self.__close = close
        self.__time = time
        self.__notes = []

        self.__up_bar = close > candle_open
        self.__spread = abs(close - candle_open)
        self.__high_low_spread = high - low
        self.__high_open_spread = high - candle_open
        self.__low_close_spread = low - close
        self.__high_close_spread = high - close

        self.__relative_volume = self.set_relative_size(self.__volume, Candle.relative_volume_boundary)
        self.__relative_spread = self.set_relative_size(self.__spread, Candle.relative_spread_boundary)
        self.__relative_high_low_spread = self.set_relative_size(abs(self.__high_low_spread),
                                                                 Candle.relative_high_low_spread_boundary)

        self.__volume_anomaly = self.set_volume_anomaly_flags()
        self.__spread_anomaly = self.set_spread_anomaly_flags()

        if self.is_lower_wick():
            self.__notes.append(CandleType.LOWER_WICK)

        if self.is_higher_wick():
            self.__notes.append(CandleType.HIGHER_WICK)

        if self.is_shooting_star():
            self.__notes.append(CandleType.SHOOTING_STAR)

        if self.is_hammer():
            self.__notes.append(CandleType.SHOOTING_STAR)

        if self.is_long_legged_doji():
            self.__notes.append(CandleType.LONG_LEGGED_DOJI)

    def set_volume_anomaly_flags(self) -> List[bool]:
        return_value = []

        for i in range(3):
            return_value.append((self.relative_high_low_spread[i].value - 1) > self.relative_volume[i].value)

        return return_value

    def set_spread_anomaly_flags(self) -> List[bool]:
        return_value = []

        for i in range(3):
            return_value.append((self.relative_volume[i].value - 1) > self.relative_high_low_spread[i].value)

        return return_value

    def is_shooting_star(self):
        # Bar must be an up bar
        if not self.up_bar:
            return False
        # the gap between the high and open must be 2x as large as the "body"
        if abs(self.high_open_spread) < (self.__spread * 2):
            return False

        # Small "tail" - bit of subjective guess work here
        if abs(self.low_close_spread) > (abs(self.high_open_spread) / 2):
            return False

        return True

    def is_hammer(self):
        # There needs to be a tail - so low - close should be negative
        if self.low_close_spread > 0:
            return False

        # The tail should be twice as long as the body
        if abs(self.low_close_spread) < (self.spread * 2):
            return False

        # I guess there shouldn't be a large high/close spread as well for this to be a hammer
        if self.high_open_spread > self.spread:
            return False

        return True

    def is_long_legged_doji(self):
        # There needs to be a tail - so low - close should be negative - TODO: This is repeated code
        if self.low_close_spread > 0:
            return False

        # There needs to be na upbit, so high close spread should be positive
        if self.high_close_spread <= 0:
            return False

        # the gap between the high and close must be 2x as large as the "body"
        if abs(self.high_close_spread) < (self.__spread * 2):
            return False

        # The tail should be twice as long as the body TODO: This is repeated code
        if abs(self.low_close_spread) < (self.spread * 2):
            return False

        return True

    def is_lower_wick(self):
        return self.__low < self.__close

    def is_higher_wick(self):
        return self.__high > self.__close

    @staticmethod
    def set_relative_size(value, relative_boundaries):
        return_value = []
        my_time_periods = ["SHORT", "MEDIUM", "LARGE"]

        for time in my_time_periods:
            if value < relative_boundaries[time][0]:
                return_value.append(Size.VERY_SMALL)
            elif value < relative_boundaries[time][1]:
                return_value.append(Size.SMALL)
            elif value < relative_boundaries[time][2]:
                return_value.append(Size.MEDIUM)
            elif value < relative_boundaries[time][3]:
                return_value.append(Size.LARGE)
            else:
                return_value.append(Size.VERY_LARGE)

        return return_value

    # "To String" stuff
    def __str__(self) -> str:
        if self.__up_bar:
            bar_type = "up_bar"
        else:
            bar_type = "down_bar"
        return "Candle is an {} opened at {} and closed at {}".format(bar_type, self.__candle_start, self.__close)

    # Simple "Getters section"

    @property
    def candle_start(self):
        return self.__candle_start

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
    def up_bar(self):
        return self.__up_bar

    @property
    def spread(self):
        return self.__spread

    @property
    def high_low_spread(self):
        return self.__high_low_spread

    @property
    def high_open_spread(self):
        return self.__high_open_spread

    @property
    def low_close_spread(self):
        return self.__low_close_spread

    @property
    def high_close_spread(self):
        return self.__high_close_spread

    @property
    def notes(self):
        return self.__notes

    @property
    def relative_volume(self):
        return self.__relative_volume

    @property
    def relative_spread(self):
        return self.__relative_spread

    @property
    def volume_anomaly(self):
        return self.__volume_anomaly

    @property
    def spread_anomaly(self):
        return self.__spread_anomaly

    @property
    def relative_high_low_spread(self):
        return self.__relative_high_low_spread

    @property
    def time(self):
        return self.__time


class CandleHistory:
    def __init__(self, period1, period2, period3):
        self.__period1 = period1
        self.__period2 = period2
        self.__period3 = period3

        self.__period1_deque = deque(maxlen=self.__period1)
        self.__period2_deque = deque(maxlen=self.__period2)
        self.__period3_deque = deque(maxlen=self.__period3)

    def add_candle(self, candle):
        self.__period1_deque.append(candle)
        self.__period2_deque.append(candle)
        self.__period3_deque.append(candle)

        if self.is_ready(HistoryPeriod.SHORT):
            Candle.relative_spread_boundary["SHORT"] = self.get_percentiles(SecurityData.SPREAD, HistoryPeriod.SHORT)
            Candle.relative_volume_boundary["SHORT"] = self.get_percentiles(SecurityData.VOLUME, HistoryPeriod.SHORT)
            Candle.relative_high_low_spread_boundary["SHORT"] = self.get_percentiles(SecurityData.HIGH_LOW_SPREAD,
                                                                                     HistoryPeriod.SHORT)

        if self.is_ready(HistoryPeriod.MEDIUM):
            Candle.relative_spread_boundary["MEDIUM"] = self.get_percentiles(SecurityData.SPREAD, HistoryPeriod.MEDIUM)
            Candle.relative_volume_boundary["MEDIUM"] = self.get_percentiles(SecurityData.VOLUME, HistoryPeriod.MEDIUM)
            Candle.relative_high_low_spread_boundary["MEDIUM"] = self.get_percentiles(SecurityData.HIGH_LOW_SPREAD,
                                                                                      HistoryPeriod.MEDIUM)

        if self.is_ready(HistoryPeriod.LONG):
            Candle.relative_spread_boundary["LARGE"] = self.get_percentiles(SecurityData.SPREAD, HistoryPeriod.LONG)
            Candle.relative_volume_boundary["LARGE"] = self.get_percentiles(SecurityData.VOLUME, HistoryPeriod.LONG)
            Candle.relative_high_low_spread_boundary["LARGE"] = self.get_percentiles(SecurityData.HIGH_LOW_SPREAD,
                                                                                     HistoryPeriod.LONG)

    def is_ready(self, period):

        if type(period) != HistoryPeriod:
            raise Exception("isReady method requires a History Period Enum - received {}".format(type(period)))

        if period == HistoryPeriod.SHORT:
            return_bool = len(self.__period1_deque) == self.__period1
        elif period == HistoryPeriod.MEDIUM:
            return_bool = len(self.__period2_deque) == self.__period2
        else:
            return_bool = len(self.__period3_deque) == self.__period3

        return return_bool


def get_percentiles(self, stat, period):
    if not isinstance(stat, SecurityData):
        raise Exception("getPercentiles expected Security Data as argument 1, received {}".format(type(stat)))
    if not isinstance(period, HistoryPeriod):
        raise Exception("getPercentiles Expected HistoryPeriod as argument 2, received {}".format(type(period)))

    my_list = []

    if period == HistoryPeriod.SHORT:
        my_deque = self.__period1_deque
    elif period == HistoryPeriod.MEDIUM:
        my_deque = self.__period2_deque
    elif period == HistoryPeriod.LONG:
        my_deque = self.__period3_deque
    else:
        raise Exception("getPercentiles : History Period exception")

    for obj in my_deque:
        if stat == SecurityData.VOLUME:
            my_list.append(obj.volume)
        elif stat == SecurityData.OPEN:
            my_list.append(obj.candle_start)
        elif stat == SecurityData.CLOSE:
            my_list.append(obj.close)
        elif stat == SecurityData.LOW:
            my_list.append(obj.low)
        elif stat == SecurityData.HIGH:
            my_list.append(obj.high)
        elif stat == SecurityData.SPREAD:
            my_list.append(obj.spread)
        elif stat == SecurityData.HIGH_LOW_SPREAD:
            my_list.append(obj.high_low_spread)
        else:
            raise Exception("getPercentiles : SecurityData Exception")

    # Return the 10, 25, 50, 75, 90 percentile values for the specified area
    return np.percentile(my_list, [10, 25, 50, 75, 90])

    def __str__(self):
        return "History object containing data for last number of bars - {}, {}, {}".format(self.__period1,
                                                                                            self.__period2,
                                                                                            self.__period3)

    def stats(self):
        candle_open = []
        for obj in self.__period1_deque:
            candle_open.append(obj.candle_start)

        return "Average open price is {}".format(np.percentile(candle_open, 50))


class MySignal:
    def __init__(self):
        pass

    @staticmethod
    def calculate_signal(curr_candle, candle_history):

        signal = {"STRENGTH": 0, "Direction": "None"}

        if curr_candle.is_shooting_star():
            signal["STRENGTH"] += 5
            signal["Direction"] = "SHORT"
            print("SHOOTING STAR: " + curr_candle.time)

        if curr_candle.is_hammer():
            signal["STRENGTH"] += 5
            signal["Direction"] = "LONG"
            print("HAMMER: " + curr_candle.time)

        if curr_candle.is_long_legged_doji():
            signal["STRENGTH"] += 5
            print("LONG LEGGED DOJI: " + curr_candle.time)

        # TODO: First this first attempt I am making the quick and probably wrong assumption that anomaly's here make
        #  the signal stronger
        for value in curr_candle.spread_anomaly:
            if value:
                signal["STRENGTH"] += 5

        for value in curr_candle.volume_anomaly:
            if value:
                signal["STRENGTH"] += 5

        return signal


class DefaultStrategy:
    def __init__(self):
        self.__risk_per_trade = 100.00
        self.__stop_loss_points = 2.5
        self.__profit_target_points = 4

    # Encapsulation section below
    @property
    def risk_per_trade(self):
        return self.__risk_per_trade

    @risk_per_trade.setter
    def risk_per_trade(self, value):
        if type(value) != float:
            raise Exception("Risk per trade value must be a float")
        self.__risk_per_trade = value

    @property
    def stop_lost_points(self):
        return self.__stop_loss_points

    @stop_lost_points.setter
    def stop_lost_points(self, value):
        if type(value) != int:
            raise Exception("stop loss points must be whole number (int)")
        self.__stop_loss_points = value

    @property
    def profit_target_points(self):
        return self.__profit_target_points

    @profit_target_points.setter
    def profit_target_points(self, value):
        if type(value) != int:
            raise Exception("profit target points must be whole number (int)")
        self.__profit_target_points = value


# Candle characteristics to track
class CandleType(Enum):
    LOWER_WICK = 1
    HIGHER_WICK = 2
    SHOOTING_STAR = 3
    HAMMER = 4
    LONG_LEGGED_DOJI = 5
    WIDE_SPREAD = 6  # This is already covered by the relative spread elements
    NARROW_SPREAD = 7  # As above
    HANGING_MAN = 8  # This is just a hammer but in an uptrend. can't ascertain on a single candle level
    ANOMALY_HIGH_VOLUME = 9
    ANOMALY_HIGH_SPREAD = 10


# Relative size indicator for volume and spread
class Size(Enum):
    VERY_SMALL = 1
    SMALL = 2
    MEDIUM = 3
    LARGE = 4
    VERY_LARGE = 5


# Which dequeue/lookback period to use
class HistoryPeriod(Enum):
    SHORT = 1
    MEDIUM = 2
    LONG = 3


# Which security data are we interested in
class SecurityData(Enum):
    VOLUME = 1
    OPEN = 2
    CLOSE = 3
    LOW = 4
    HIGH = 5
    SPREAD = 6
    HIGH_LOW_SPREAD = 7


#### QUANT CONNECT STUFF BELOW #################

# region imports
from AlgorithmImports import *


# endregion

class SwimmingBrownOwl(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2021, 1, 1)  # Set Start Date
        # self.SetEndDate(2021, 12, 31)
        self.SetCash(10000)  # Set Strategy Cash

        # Create new variables for the security and its associated symbol

        self.sec = self.AddEquity("AAPL", Resolution.Hour)
        self.symbol = self.sec.Symbol

        # Create deques
        self.volumeQueue = deque(maxlen=3)
        self.closeQueue = deque(maxlen=3)
        self.openQueue = deque(maxlen=3)
        self.highQueue = deque(maxlen=3)
        self.lowQueue = deque(maxlen=3)

        # Trigger variables
        self.volume_trigger = False
        self.up_price_trigger = False
        self.down_price_trigger = False

        self.barCountSinceEntry = 0
        self.myStrat = DefaultStrategy()
        self.InvestedLong = False
        self.InvestedShort = False
        self.stop_loss_price = 0
        self.stop_loss_price_short = 0
        self.target_price = 0
        self.target_price_short = 0
        self.spend_per_point = 0
        self.amount_to_buy = 0
        self.quantity = 0

    def OnData(self, data: Slice):

        if data[self.symbol] == None:
            self.Log("Symbol not found")
            return

        # create variables for some of the key stats for this data bar
        volume = data[self.symbol].Volume
        open = data[self.symbol].Open
        close = data[self.symbol].Close
        high = data[self.symbol].High
        low = data[self.symbol].Low

        # add these values to the queues
        self.volumeQueue.append(volume)
        self.closeQueue.append(close)
        self.openQueue.append(open)
        self.highQueue.append(high)
        self.lowQueue.append(low)

        # If we are not currently invested in anything
        if not self.Portfolio.Invested:

            self.stop_loss_price = close - self.myStrat.stop_lost_points
            self.stop_loss_price_short = close + self.myStrat.stop_lost_points

            self.target_price = close + self.myStrat.profit_target_points
            self.Log("{} {} {}".format(self.target_price, close, self.myStrat.profit_target_points))
            self.target_price_short = close - self.myStrat.profit_target_points

            self.spend_per_point = self.myStrat.risk_per_trade / self.myStrat.stop_lost_points
            self.amount_to_buy = close * self.spend_per_point
            if self.amount_to_buy > (self.Portfolio.Cash - 100):
                self.amount_to_buy = self.Portfolio.Cash - 100

            self.quantity = self.amount_to_buy / close

            # Drop out if the queue doesn't have three values yet
            if len(self.volumeQueue) != 3:
                return

            # Check if volume has gone up last 3 candles, then set trigger accordingly
            if self.volumeQueue[2] > self.volumeQueue[1] and self.volumeQueue[1] > self.volumeQueue[0]:
                self.Log("################Volume has ascended over last three bars")
                self.volume_trigger = True
            else:
                self.volume_trigger = False

            # check if close price has gone up last 3 candles and set trigger accordingly
            if self.closeQueue[2] > self.closeQueue[1] and self.closeQueue[1] > self.closeQueue[0]:
                self.Log("################Price has ascended over last three bars")
                self.up_price_trigger = True
            else:
                self.up_price_trigger = False

            # Log details to console
            self.Log(
                "Portfolio cash {}, close price was {}, stop loss should be set at {}, target price long {}, target price short {}, we are risking {}, so we would spending (per point){} and {} overall".format(
                    self.Portfolio.Cash, close, self.stop_loss_price, self.target_price, self.target_price_short,
                    self.myStrat.risk_per_trade, self.spend_per_point, self.amount_to_buy))

            if self.volume_trigger and self.up_price_trigger:
                self.MarketOrder(self.symbol, self.quantity)
                self.barCountSinceEntry = 0
                self.InvestedLong = True
            elif self.volume_trigger and self.down_price_trigger:
                self.MarketOrder(self.symbol, -self.quantity)
                self.barCountSinceEntry = 0
                self.InvestedShort = True
        else:

            self.barCountSinceEntry += 1

        if self.Portfolio.Invested and self.InvestedLong:
            if close < self.stop_loss_price:
                self.Log("Hit stop loss - existing")
                self.InvestedLong = False
                self.Liquidate()
            if close > self.target_price:
                self.Log("Hit profit target")
                self.InvestedLong = False
                self.Liquidate()
        elif self.Portfolio.Invested and self.InvestedShort:
            if close > self.stop_loss_price_short:
                self.Log("Short hit stop loss - exiting")
                self.InvestedShort = False
                self.Liquidate()
            if close < self.target_price_short:
                self.Log("Hit Profit target")
                self.InvestedShort = False
                self.Liquidate()

