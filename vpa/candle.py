from vpa_enums import CandleType, Size, HistoryPeriod

class Candle:     
    #Class variables for relative values - these could/should maybe start blank
    relative_spread_boundarys = {"SHORT": [293.4,468.0,759.0,806.0,834.2], "MEDIUM": [126.7, 182.5, 557.5, 829.5, 1026.4], "LARGE": [93.4, 213.0, 377.5, 721.0, 1016.8]}
    relative_volume_boundarys = {"SHORT": [231718.,236627.5,244810.,253047.,257989.2], "MEDIUM": [223357.5,229034.,238311.,257165.5,265355.7], "LARGE": [226893.7,243349.,275653.,301675.,312982.6]}

    def __init__(self, volume, open, high, low, close):
        self.__volume = volume
        self.__open = open
        self.__high = high
        self.__low = low
        self.__close = close
        self.__notes = []
        
        self.__upbar = close > open
        self.__spread = abs(close - open)

        self.__relativeVolume = self.setRelativeSize(self.__volume, Candle.relative_volume_boundarys)
        self.__relativeSpread = self.setRelativeSize(self.__spread, Candle.relative_spread_boundarys)

        if self.isLowerWick():
            self.__notes.append(CandleType.LOWER_WICK)
        
        if self.isHigherWick():
            self.__notes.append(CandleType.HIGHER_WICK)

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

    def __str__(self) -> str:
        bartype = ""
        if self.__upbar == True:
            bartype = "Upbar"
        else:
            bartype = "Downbar"
        return "Candle is an {} opened at {} and closed at {}".format(bartype, self.__open, self.__close)
    
    @property
    def open(self):
        return self.__open
    
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
    def notes(self):
        return self.__notes
    
    @property
    def relativeVolume(self):
        return self.__relativeVolume
    
    @property
    def relativeSpread(self):
        return self.__relativeSpread