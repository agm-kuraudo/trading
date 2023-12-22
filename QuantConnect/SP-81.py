# region imports
from AlgorithmImports import *
# endregion

class EmotionalLightBrownPanda(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2022, 6, 21)
        self.SetCash(100000)
        self.symbol = self.AddEquity("SPY", Resolution.Daily).Symbol
        self.rsi = self.RSI(self.symbol, 14)


    def OnData(self, data: Slice):

        if not self.rsi.IsReady:
            return

        price = self.Securities[self.symbol].Price
        rsi = self.rsi.Current.Value

        # The current value of self.rsi is represented by self.rsi.Current.Value
        self.Plot("Price", "Price", price)
        self.Plot("RelativeStrengthIndex", "rsi", rsi)
        # Plot all attributes of self.rsi
        self.Plot("RelativeStrengthIndex", "averageloss", self.rsi.AverageLoss.Current.Value)
        self.Plot("RelativeStrengthIndex", "averagegain", self.rsi.AverageGain.Current.Value)

        if (not self.Portfolio[self.symbol].Invested) and rsi < 30:
            self.SetHoldings(self.symbol, 1)
            return

        if (not self.Portfolio[self.symbol].Invested) and rsi > 70:
            self.SetHoldings(self.symbol, -1)
            return

        if (self.Portfolio[self.symbol].IsLong and rsi > 45) or (self.Portfolio[self.symbol].IsShort and rsi < 55):
            self.Liquidate()
            return
