from collections import deque
from statistics import mean
import numpy as np

from vpa_enums import CandleType, Size, SecurityData, HistoryPeriod
from candle import Candle

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

        if self.isReady(HistoryPeriod.MEDIUM):
            Candle.relative_spread_boundarys["MEDIUM"] = self.getPercentiles(SecurityData.SPREAD, HistoryPeriod.MEDIUM)
            Candle.relative_volume_boundarys["MEDIUM"] = self.getPercentiles(SecurityData.VOLUME, HistoryPeriod.MEDIUM)

        if self.isReady(HistoryPeriod.LONG):
            Candle.relative_spread_boundarys["LARGE"] = self.getPercentiles(SecurityData.SPREAD, HistoryPeriod.LONG)
            Candle.relative_volume_boundarys["LARGE"] = self.getPercentiles(SecurityData.VOLUME, HistoryPeriod.LONG)

    def isReady(self, period):
        returnBool = False

        if (type(period) != HistoryPeriod):
            raise Exception ("isReady method requires a History Period Enum - recieved {}".format(type(period)))
        
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

        match period:
            case HistoryPeriod.SHORT:
                myDeque = self.__period1_deque
            case HistoryPeriod.MEDIUM:
                myDeque = self.__period2_deque
            case HistoryPeriod.LONG:
                myDeque = self.__period3_deque
            case _:
                raise Exception("getPercentiles : History Period exception")
            
        match stat:
            case SecurityData.VOLUME:
                for obj in myDeque:
                    myList.append(obj.volume)
            case SecurityData.OPEN:
                for obj in myDeque:
                    myList.append(obj.open)
            case SecurityData.CLOSE:
                for obj in myDeque:
                    myList.append(obj.close)
            case SecurityData.LOW:
                for obj in myDeque:
                    myList.append(obj.low)
            case SecurityData.HIGH:
                for obj in myDeque:
                    myList.append(obj.high)
            case SecurityData.SPREAD:
                for obj in myDeque:
                    myList.append(obj.spread)
            case _:
                raise Exception("getPercentiles : SecurityData Exception")
    
        #Return the 10, 25, 50, 75, 90 percentile values for specified area
        return np.percentile(myList, [10, 25, 50, 75, 90])
     
    def __str__(self):
        return "History object containing data for last number of bars - {}, {}, {}".format(self.__period1, self.__period2, self.__period3)
    
    def stats(self):
        open = []
        for obj in self.__period1_deque:
            open.append(obj.open)

        return "Average open price is {}".format(np.percentile(open, 50))