class Candle:     
    def __init__(self, volume, open, high, low, close):
        self.__volume = volume
        self.__open = open
        self.__high = high
        self.__low = low
        self.__close = close

    def __str__(self) -> str:
        return "Candle opened at {} and closed at {}".format(self.__open, self.__close)
