from collections import deque
from statistics import mean
import numpy as np

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

    def getPercentiles(self):
        #Return the 10, 25, 50, 75, 90 percentile values for specified area (spread or volume probs)
        return []
    
    def __str__(self):
        return "History object containing data for last number of bars - {}, {}, {}".format(self.__period1, self.__period2, self.__period3)
    
    def stats(self):
        open = []
        for obj in self.__period1_deque:
            open.append(obj.open)

        return "Average open price is {}".format(np.percentile(open, 50))