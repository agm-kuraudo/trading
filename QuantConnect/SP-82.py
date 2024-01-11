# region imports
from AlgorithmImports import *
from collections import deque


# endregion

class AdaptableFluorescentYellowDinosaur(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2023, 1, 1)
        self.SetCash(100000)
        self.mySPY = self.AddEquity("SPY", Resolution.Daily).Symbol

        '''
        Series(name, type)
        Series(name, type, index)
        Series(name, type, index, unit)
        Series(name, type, unit)
        Series(name, type, unit, color)
        Series(name, type, unit, color, symbol
        '''

        chart = Chart("SPY")
        self.AddChart(chart)

        series1 = Series("Close", SeriesType.Line, "$", Color.Green)
        series2 = Series("Trade", SeriesType.Scatter, "$", Color.Pink, ScatterMarkerSymbol.Diamond)

        chart.AddSeries(series1)
        chart.AddSeries(series2)

        self.sma_short = self.SMA(self.mySPY, 20)
        self.sma_medium = self.SMA(self.mySPY, 50)
        self.sma_long = self.SMA(self.mySPY, 100)

        self.vwma_20 = deque(maxlen=20)
        self.vwma_50 = deque(maxlen=50)
        self.vwma_100 = deque(maxlen=100)

        self.counter = 1

    def OnData(self, data: Slice):

        self.counter += 1

        if not self.Portfolio.Invested and (self.counter % 10 == 0):
            self.SetHoldings("SPY", 0.33)
            self.Plot("SPY", "Trade", self.Securities[self.mySPY].Price)

        if data[self.mySPY].Volume == 0:  # Once ALGO reaches present day volume is reported as Zero
            return

        self.Plot("SPY", "Close", data[self.mySPY].Close)
        # self.Plot("SPY", self.sma_short, self.sma_medium, self.sma_long)

        self.vwma_20.append({"Price": data[self.mySPY].Close, "Volume": data[self.mySPY].Volume,
                             "VWMA": (data[self.mySPY].Close * data[self.mySPY].Volume) / data[self.mySPY].Volume})
        self.vwma_50.append({"Price": data[self.mySPY].Close, "Volume": data[self.mySPY].Volume,
                             "VWMA": (data[self.mySPY].Close * data[self.mySPY].Volume) / data[self.mySPY].Volume})
        self.vwma_100.append({"Price": data[self.mySPY].Close, "Volume": data[self.mySPY].Volume,
                              "VWMA": (data[self.mySPY].Close * data[self.mySPY].Volume) / data[self.mySPY].Volume})

        if (len(self.vwma_20) > 19):
            self.Log("VMWA 20 Now ready")

            the_value = 0
            for queuevalue in self.vwma_20:
                the_value += queuevalue["VWMA"]

            self.Plot("SPY", "VWMA_20", (the_value / 20))

        if (len(self.vwma_50) > 49):
            self.Log("VWMA 50 Now ready")

            the_value = 0
            for queuevalue in self.vwma_50:
                the_value += queuevalue["VWMA"]

            self.Plot("SPY", "VWMA_50", (the_value / 50))

        if (len(self.vwma_100) > 99):
            self.Log("VWMA 100 Now ready")

            the_value = 0
            for queuevalue in self.vwma_100:
                the_value += queuevalue["VWMA"]

            self.Plot("SPY", "VWMA_100", (the_value / 100))
