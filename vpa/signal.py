class MySignal:
    def __init__(self):
        pass

    def calculateSignal(self, currCandle, candle_history):

        signal = {"STRENGTH": 0, "Direction": "None"}

        #print(currCandle)

        if currCandle.isShootingStar():
            signal["STRENGTH"] += 5
            signal["Direction"] = "SHORT"
            print("SHOOTING STAR: " + currCandle.time)
      
        if currCandle.isHammer():
            signal["STRENGTH"] += 5
            signal["Direction"] = "LONG"
            print("HAMMER: " + currCandle.time)

        if currCandle.isLongLeggedDoji():
            signal["STRENGTH"] += 5
            print("LONG LEGGED DOJI: " + currCandle.time)


        #TODO: First this first attempt I am making the quick and probably wrong assumption that anomolys here make the signal stronger
        for value in currCandle.spreadAnomoly:
            if value:
                signal["STRENGTH"] += 5

        for value in currCandle.volumeAnomoly:
            if value:
                signal["STRENGTH"] += 5
        
        return signal

'''
        if True in currCandle.spreadAnomoly:
            print("{} Spread anomly - {}, realtive spreads {}, relative volumes {}".format(currCandle.time, currCandle.spreadAnomoly, currCandle.relativeHighLowSpread, currCandle.relativeVolume))

        if True in currCandle.volumeAnomoly:
            print("{} Volume anomly - {}, realtive spreads {}, relative volumes {}".format(currCandle.time, currCandle.volumeAnomoly, currCandle.relativeHighLowSpread, currCandle.relativeVolume))
'''
