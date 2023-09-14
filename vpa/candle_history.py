from collections import deque
import numpy as np

from vpa_enums import SecurityData, HistoryPeriod
from candle import Candle


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
        if type(stat) != SecurityData:
            raise Exception("getPercentiles expected Security Data as argument 1, received {}".format(type(stat)))
        if type(period) != HistoryPeriod:
            raise Exception("getPercentiles Expected HistoryPeriod as argument 2, received {}".format(type(period)))

        my_list = []

        match period:
            case HistoryPeriod.SHORT:
                my_deque = self.__period1_deque
            case HistoryPeriod.MEDIUM:
                my_deque = self.__period2_deque
            case HistoryPeriod.LONG:
                my_deque = self.__period3_deque
            case _:
                raise Exception("getPercentiles : History Period exception")

        match stat:
            case SecurityData.VOLUME:
                for obj in my_deque:
                    my_list.append(obj.volume)
            case SecurityData.OPEN:
                for obj in my_deque:
                    my_list.append(obj.open)
            case SecurityData.CLOSE:
                for obj in my_deque:
                    my_list.append(obj.close)
            case SecurityData.LOW:
                for obj in my_deque:
                    my_list.append(obj.low)
            case SecurityData.HIGH:
                for obj in my_deque:
                    my_list.append(obj.high)
            case SecurityData.SPREAD:
                for obj in my_deque:
                    my_list.append(obj.spread)
            case SecurityData.HIGH_LOW_SPREAD:
                for obj in my_deque:
                    my_list.append(obj.high_low_spread)
            case _:
                raise Exception("getPercentiles : SecurityData Exception")

        # Return the 10, 25, 50, 75, 90 percentile values for specified area
        return np.percentile(my_list, [10, 25, 50, 75, 90])

    def __str__(self):
        return "History object containing data for last number of bars - {}, {}, {}".format(self.__period1,
                                                                                            self.__period2,
                                                                                            self.__period3)

    def stats(self):
        candle_open = []
        for obj in self.__period1_deque:
            candle_open.append(obj.open)

        return "Average open price is {}".format(np.percentile(candle_open, 50))
