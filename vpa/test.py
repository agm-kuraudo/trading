from candle import Candle
from candle_history import CandleHistory
from vpa_enums import CandleType, Size, SecurityData, HistoryPeriod
import pandas as pd
import numpy as np
import os
#test data downloaded from https://www.barchart.com/forex/quotes/%5EGBPUSD/price-history/historical?orderBy=tradeTime&orderDir=desc


all_history = CandleHistory(3, 10, 50)
relative_spread_boundarys = [93.4,213.,377.5,721.,1016.8]
relative_volume_boundarys = [223357.5,229034.,238311.,257165.5,265355.7]


def dummyOnData(time, volume, open, high, low, close):



    if (np.isnan(open)):
        return
    
    this_candle = Candle(volume,open,high,low,close)

    all_history.addCandle(this_candle)

    print(this_candle)

    if this_candle.isShootingStar():
        print("SHOOTING STAR: " + time)

    if this_candle.isHammer():
        print("HAMMER: " + time)

    if this_candle.isLongLeggedDoji():
        print("LONG LEGGED DOJI: " + time)

    #print(this_candle.relativeVolume)
    #print(all_history)


##Get our test data from CSV file... this would come from live quant data eventually

absolute_path = os.path.dirname(__file__)
relative_path = "../test_data/"
full_path = os.path.join(absolute_path, relative_path)

myDF = pd.read_csv(full_path + "^gbpusd_price-history-08-29-2023.csv")
myDF = myDF.sort_values("Time", axis=0)

print(myDF)

#Loop around each item in the data frame and call my dummy ondata method
for index, row in myDF.iterrows():
    dummyOnData(row['Time'], row['Volume'], row['Open'], row['High'], row['Low'], row['Last'])
    
print()
print(all_history.getPercentiles(SecurityData.VOLUME, HistoryPeriod.SHORT))
print(all_history.getPercentiles(SecurityData.SPREAD, HistoryPeriod.SHORT))

print()
print(all_history.getPercentiles(SecurityData.VOLUME, HistoryPeriod.MEDIUM))
print(all_history.getPercentiles(SecurityData.SPREAD, HistoryPeriod.MEDIUM))
print()
print(all_history.getPercentiles(SecurityData.VOLUME, HistoryPeriod.LONG))
print(all_history.getPercentiles(SecurityData.SPREAD, HistoryPeriod.LONG))