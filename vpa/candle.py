from vpa_enums import CandleType

class Candle:     
    def __init__(self, volume, open, high, low, close):
        self.__volume = volume
        self.__open = open
        self.__high = high
        self.__low = low
        self.__close = close
        self.__notes = []
        
        
        self.__upbar = close > open
        self.__spread = abs(close - open)


        if self.isLowerWick():
            self.__notes.append(CandleType.LOWER_WICK)
        
        if self.isHigherWick():
            self.__notes.append(CandleType.HIGHER_WICK)

    def isLowerWick(self):
        return self.__low < self.__close
    
    def isHigherWick(self):
        return self.__high > self.__close

    def __str__(self) -> str:
        return "Candle opened at {} and closed at {}".format(self.__open, self.__close)
    
    @property
    def open(self):
        return self.__open
