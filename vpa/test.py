from candle import Candle
from candle_history import CandleHistory
import pandas as pd
import numpy as np
#test data downloaded from https://www.barchart.com/forex/quotes/%5EGBPUSD/price-history/historical?orderBy=tradeTime&orderDir=desc


all_history = CandleHistory(3, 10, 50)

def dummyOnData(volume, open, high, low, close):

    if (np.isnan(open)):
        return
    
    this_candle = Candle(volume,open,high,low,close)
    all_history.addCandle(this_candle)

    print(this_candle)
    #print(all_history)


##Get our test data from CSV file... this would come from live quant data eventually

myDF = pd.read_csv("C:/Users/dogeg/Documents/GitHub/trading/test_data/^gbpusd_price-history-08-29-2023.csv")
print(myDF)

#Loop around each item in the data frame and call my dummy ondata method
for index, row in myDF.iterrows():
    dummyOnData(row['Volume'], row['Open'], row['High'], row['Low'], row['Last'])

print(all_history.stats())
