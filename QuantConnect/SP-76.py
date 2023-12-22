# region imports
from AlgorithmImports import *
# endregion
from enum import Enum
from collections import deque
from statistics import mean
import numpy as np
import pandas as pd
import os


# Candle charicteristics to track
class CandleType(Enum):
    LOWER_WICK = 1
    HIGHER_WICK = 2
    SHOOTING_STAR = 3
    HAMMER = 4
    LONG_LEGGED_DOJI = 5
    WIDE_SPREAD = 6  # This is already covered by the relative spread elements
    NARROW_SPREAD = 7  # As above
    HANGING_MAN = 8  # This is just a hammer but in an uptrend.. can't ascertain on a single candle level
    ANOMOLY_HIGH_VOLUME = 9
    ANOMOLY_HIGH_SPREAD = 10


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


class CandleHistory:
    def __init__(self, period1, period2, period3):
        self.__period1 = period1
        self.__period2 = period2
        self.__period3 = period3

        self.__period1_deque = deque(maxlen=self.__period1)
        self.__period2_deque = deque(maxlen=self.__period2)
        self.__period3_deque = deque(maxlen=self.__period3)

    def addCandle(self, candle):
        self.__period1_deque.append(candle)
        self.__period2_deque.append(candle)
        self.__period3_deque.append(candle)

        if self.isReady(HistoryPeriod.SHORT):
            Candle.relative_spread_boundarys["SHORT"] = self.getPercentiles(SecurityData.SPREAD, HistoryPeriod.SHORT)
            Candle.relative_volume_boundarys["SHORT"] = self.getPercentiles(SecurityData.VOLUME, HistoryPeriod.SHORT)
            Candle.relative_highlow_spread_boundarys["SHORT"] = self.getPercentiles(SecurityData.HIGH_LOW_SPREAD,
                                                                                    HistoryPeriod.SHORT)

        if self.isReady(HistoryPeriod.MEDIUM):
            Candle.relative_spread_boundarys["MEDIUM"] = self.getPercentiles(SecurityData.SPREAD, HistoryPeriod.MEDIUM)
            Candle.relative_volume_boundarys["MEDIUM"] = self.getPercentiles(SecurityData.VOLUME, HistoryPeriod.MEDIUM)
            Candle.relative_highlow_spread_boundarys["MEDIUM"] = self.getPercentiles(SecurityData.HIGH_LOW_SPREAD,
                                                                                     HistoryPeriod.MEDIUM)

        if self.isReady(HistoryPeriod.LONG):
            Candle.relative_spread_boundarys["LARGE"] = self.getPercentiles(SecurityData.SPREAD, HistoryPeriod.LONG)
            Candle.relative_volume_boundarys["LARGE"] = self.getPercentiles(SecurityData.VOLUME, HistoryPeriod.LONG)
            Candle.relative_highlow_spread_boundarys["LARGE"] = self.getPercentiles(SecurityData.HIGH_LOW_SPREAD,
                                                                                    HistoryPeriod.LONG)

    def isReady(self, period):
        returnBool = False

        if (type(period) != HistoryPeriod):
            raise Exception("isReady method requires a History Period Enum - recieved {}".format(type(period)))

        if (period == HistoryPeriod.SHORT):
            returnBool = len(self.__period1_deque) == self.__period1
        elif (period == HistoryPeriod.MEDIUM):
            returnBool = len(self.__period2_deque) == self.__period2
        else:
            returnBool = len(self.__period3_deque) == self.__period3

        return returnBool

    def getPercentiles(self, stat, period):
        if type(stat) != SecurityData:
            raise Exception("getPercentiles expected Security Data as argument 1, recieved {}".format(type(stat)))
        if type(period) != HistoryPeriod:
            raise Exception("getPercentiles Expected HistoryPeriod as argument 2, recieved {}".format(type(period)))

        myDeque = None
        myList = []

        if period == HistoryPeriod.SHORT:
            myDeque = self.__period1_deque
        elif period == HistoryPeriod.MEDIUM:
            myDeque = self.__period2_deque
        elif period == HistoryPeriod.LONG:
            myDeque = self.__period3_deque
        else:
            raise Exception("getPercentiles : History Period exception")

        if stat == SecurityData.VOLUME:
            for obj in myDeque:
                myList.append(obj.volume)
        elif stat == SecurityData.OPEN:
            for obj in myDeque:
                myList.append(obj.openPrice)
        elif stat == SecurityData.CLOSE:
            for obj in myDeque:
                myList.append(obj.close)
        elif stat == SecurityData.LOW:
            for obj in myDeque:
                myList.append(obj.low)
        elif stat == SecurityData.HIGH:
            for obj in myDeque:
                myList.append(obj.high)
        elif stat == SecurityData.SPREAD:
            for obj in myDeque:
                myList.append(obj.spread)
        elif stat == SecurityData.HIGH_LOW_SPREAD:
            for obj in myDeque:
                myList.append(obj.highLowSpread)
        else:
            raise Exception("getPercentiles : SecurityData Exception")

        # Return the 10, 25, 50, 75, 90 percentile values for specified area
        return np.percentile(myList, [10, 25, 50, 75, 90])

    def __str__(self):
        return "History object containing data for last number of bars - {}, {}, {}".format(self.__period1,
                                                                                            self.__period2,
                                                                                            self.__period3)

    def stats(self):
        open = []
        for obj in self.__period1_deque:
            open.append(obj.openPrice)

        return "Average open price is {}".format(np.percentile(open, 50))


class Candle:
    # Class variables for relative values - these could/should maybe start blank
    relative_spread_boundarys = {"SHORT": [293.4, 468.0, 759.0, 806.0, 834.2],
                                 "MEDIUM": [126.7, 182.5, 557.5, 829.5, 1026.4],
                                 "LARGE": [93.4, 213.0, 377.5, 721.0, 1016.8]}
    relative_volume_boundarys = {"SHORT": [231718., 236627.5, 244810., 253047., 257989.2],
                                 "MEDIUM": [223357.5, 229034., 238311., 257165.5, 265355.7],
                                 "LARGE": [226893.7, 243349., 275653., 301675., 312982.6]}

    relative_highlow_spread_boundarys = {"SHORT": [293.4, 468.0, 759.0, 806.0, 834.2],
                                         "MEDIUM": [126.7, 182.5, 557.5, 829.5, 1026.4],
                                         "LARGE": [93.4, 213.0, 377.5, 721.0, 1016.8]}

    def __init__(self, time, volume, open, high, low, close):
        self.__volume = volume
        self.__openPrice = open
        self.__high = high
        self.__low = low
        self.__close = close
        self.__time = time
        self.__notes = []

        self.__upbar = close > open
        self.__spread = abs(close - open)
        self.__highLowSpread = high - low
        self.__highOpenSpread = high - open
        self.__lowCloseSpread = low - close
        self.__highCloseSpread = high - close

        self.__relativeVolume = self.setRelativeSize(self.__volume, Candle.relative_volume_boundarys)
        self.__relativeSpread = self.setRelativeSize(self.__spread, Candle.relative_spread_boundarys)
        self.__relativeHighLowSpread = self.setRelativeSize(abs(self.__highLowSpread),
                                                            Candle.relative_highlow_spread_boundarys)

        self.__volumeAnomoly = self.setVolumeAnomolyFlags()
        self.__spreadAnomoly = self.setSpreadAnomolyFlags()

        if self.isLowerWick():
            self.__notes.append(CandleType.LOWER_WICK)

        if self.isHigherWick():
            self.__notes.append(CandleType.HIGHER_WICK)

        if self.isShootingStar():
            self.__notes.append(CandleType.SHOOTING_STAR)

        if self.isHammer():
            self.__notes.append(CandleType.SHOOTING_STAR)

        if self.isLongLeggedDoji():
            self.__notes.append(CandleType.LONG_LEGGED_DOJI)

    def setVolumeAnomolyFlags(self):
        return_value = []

        for i in range(3):
            return_value.append((self.relativeHighLowSpread[i].value - 1) > self.relativeVolume[i].value)

        return return_value

    def setSpreadAnomolyFlags(self):
        return_value = []

        for i in range(3):
            return_value.append((self.relativeVolume[i].value - 1) > self.relativeHighLowSpread[i].value)

        return return_value

    def isShootingStar(self):
        # Bar must be an upbar
        if not self.upbar:
            return False
        # the gap between the high and open must be 2x as large as the "body"
        if abs(self.highOpenSpread) < (self.__spread * 2):
            return False

        # Small "tail" - bit of subjective guess work here
        if abs(self.lowCloseSpread) > (abs(self.highOpenSpread) / 2):
            return False

        return True

    def isHammer(self):
        # There needs to be a tail - so low - close should be negative
        if self.lowCloseSpread > 0:
            return False

        # The tail should be twice as long as the body
        if abs(self.lowCloseSpread) < (self.spread * 2):
            return False

        # I guess there shouldn't be a large high/close spread as well for this to be a hammer
        if self.highOpenSpread > self.spread:
            return False

        return True

    def isLongLeggedDoji(self):
        # There needs to be a tail - so low - close should be negative - TODO: This is repeated code
        if self.lowCloseSpread > 0:
            return False

        # There needs to be a upbit, so high close spread should be positive
        if self.highCloseSpread <= 0:
            False

        # the gap between the high and close must be 2x as large as the "body"
        if abs(self.highCloseSpread) < (self.__spread * 2):
            return False

        # The tail should be twice as long as the body TODO: This is repeated code
        if abs(self.lowCloseSpread) < (self.spread * 2):
            return False

        return True

    def isLowerWick(self):
        return self.__low < self.__close

    def isHigherWick(self):
        return self.__high > self.__close

    def setRelativeSize(self, value, relative_boundarys):
        return_value = []
        myTimePeriods = ["SHORT", "MEDIUM", "LARGE"]

        for time in myTimePeriods:
            if value < relative_boundarys[time][0]:
                return_value.append(Size.VERY_SMALL)
            elif value < relative_boundarys[time][1]:
                return_value.append(Size.SMALL)
            elif value < relative_boundarys[time][2]:
                return_value.append(Size.MEDIUM)
            elif value < relative_boundarys[time][3]:
                return_value.append(Size.LARGE)
            else:
                return_value.append(Size.VERY_LARGE)

        return return_value

    # "To String" stuff
    def __str__(self) -> str:
        bartype = ""
        if self.__upbar == True:
            bartype = "Upbar"
        else:
            bartype = "Downbar"
        return "Candle is an {} opened at {} and closed at {}".format(bartype, self.__openPrice, self.__close)

    # Simple "Getters section"

    @property
    def openPrice(self):
        return self.__openPrice

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
    def upbar(self):
        return self.__upbar

    @property
    def spread(self):
        return self.__spread

    @property
    def highLowSpread(self):
        return self.__highLowSpread

    @property
    def highOpenSpread(self):
        return self.__highOpenSpread

    @property
    def lowCloseSpread(self):
        return self.__lowCloseSpread

    @property
    def highCloseSpread(self):
        return self.__highCloseSpread

    @property
    def notes(self):
        return self.__notes

    @property
    def relativeVolume(self):
        return self.__relativeVolume

    @property
    def relativeSpread(self):
        return self.__relativeSpread

    @property
    def volumeAnomoly(self):
        return self.__volumeAnomoly

    @property
    def spreadAnomoly(self):
        return self.__spreadAnomoly

    @property
    def relativeHighLowSpread(self):
        return self.__relativeHighLowSpread

    @property
    def time(self):
        return self.__time


class MySignal:
    def __init__(self, algo_class):
        self.__algoClassPointer = algo_class

    def calculateSignal(self, currCandle, candle_history):

        signal = {"STRENGTH": 0, "Direction": "None"}

        # self.Log(currCandle)

        if currCandle.isShootingStar():
            signal["STRENGTH"] += 5
            signal["Direction"] = "SHORT"
            self.__algoClassPointer.Log("SHOOTING STAR: " + currCandle.time.strftime("%m/%d/%Y, %H:%M:%S"))

        if currCandle.isHammer():
            signal["STRENGTH"] += 5
            signal["Direction"] = "LONG"
            self.__algoClassPointer.Log("HAMMER: " + currCandle.time.strftime("%m/%d/%Y, %H:%M:%S"))

        if currCandle.isLongLeggedDoji():
            signal["STRENGTH"] += 5
            self.__algoClassPointer.Log("LONG LEGGED DOJI: " + currCandle.time.strftime("%m/%d/%Y, %H:%M:%S"))

        # TODO: First this first attempt I am making the quick and probably wrong assumption that anomolys here make the signal stronger
        for value in currCandle.spreadAnomoly:
            if value:
                signal["STRENGTH"] += 5

        for value in currCandle.volumeAnomoly:
            if value:
                signal["STRENGTH"] += 5

        return signal


class CryingFluorescentYellowFly(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2022, 5, 1)
        self.SetCash(100000)
        # self.pair = self.AddForex("GBPUSD", Resolution.Hour, Market.Oanda).Symbol
        self.pair = self.AddEquity("SPY", Resolution.Daily).Symbol

        self.all_history = CandleHistory(3, 10, 50)
        self.mySignal = MySignal(self)

    def OnData(self, data: Slice):

        if data[self.pair] == None:
            return

        open = data[self.pair].Open
        time = data[self.pair].Time
        high = data[self.pair].High
        low = data[self.pair].Low
        close = data[self.pair].Close
        volume = data[self.pair].Volume

        this_candle = Candle(time, volume, open, high, low, close)

        self.all_history.addCandle(this_candle)

        if not self.all_history.isReady(HistoryPeriod.LONG):
            return

        signalDict = self.mySignal.calculateSignal(this_candle, self.all_history)

        if signalDict["STRENGTH"] > 15 and signalDict["Direction"] == "SHORT":
            self.Log("{}, {} Signal, Strength {}".format(this_candle.time.strftime("%m/%d/%Y, %H:%M:%S"),
                                                         signalDict["Direction"], signalDict["STRENGTH"]))
            if self.Portfolio[self.pair].IsLong:
                self.Liquidate()

            self.SetHoldings(self.pair, -1)

        if signalDict["STRENGTH"] > 15 and signalDict["Direction"] == "LONG":
            self.Log("{}, {} Signal, Strength {}".format(this_candle.time.strftime("%m/%d/%Y, %H:%M:%S"),
                                                         signalDict["Direction"], signalDict["STRENGTH"]))
            if self.Portfolio[self.pair].IsShort:
                self.Liquidate()
            self.SetHoldings(self.pair, 1)

        if signalDict["STRENGTH"] > 14 and signalDict["Direction"] == "NONE":
            self.Liquidate()


