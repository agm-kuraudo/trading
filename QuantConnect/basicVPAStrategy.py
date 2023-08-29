# region imports
from AlgorithmImports import *
from collections import deque
# endregion

class CalmGreenAlpaca(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2021, 12, 1)  # Set Start Date
        #self.SetEndDate(2021, 12, 31)
        self.SetCash(10000)  # Set Strategy Cash
        
        #Create new variables for the security and its associated symbol

        self.sec = self.AddEquity("AAPL", Resolution.Hour)
        self.symbol = self.sec.Symbol

        #Create deques
        self.volumeQueue = deque(maxlen=3)
        self.closeQueue = deque(maxlen=3)
        self.openQueue = deque(maxlen=3)
        self.highQueue = deque(maxlen=3)
        self.lowQueue = deque(maxlen=3)

        #Trigger variables
        self.volume_trigger = False
        self.up_price_trigger = False
        self.down_price_trigger = False

        self.barCountSinceEntry = 0


    def OnData(self, data: Slice):

        if data[self.symbol] == None:
            self.Log("Symbol not found")
            return

        #create variables for some of the key stats for this data bar
        volume = data[self.symbol].Volume
        open = data[self.symbol].Open
        close = data[self.symbol].Close
        high = data[self.symbol].High
        low = data[self.symbol].Low


        #add these values to the queues
        self.volumeQueue.append(volume)
        self.closeQueue.append(close)
        self.openQueue.append(open)
        self.highQueue.append(high)
        self.lowQueue.append(low)

        #Log the volume to console (for debugging purposes only)
        self.Log(volume)

        #If we are not currently invested in anything
        if not self.Portfolio.Invested:

            #Drop out if the queue doesn't have three values yet
            if len(self.volumeQueue)!=3:
                return
            
            #Check if volume has gone up last 3 candles, then set trigger accordingly
            if self.volumeQueue[2] > self.volumeQueue[1] and self.volumeQueue[1] > self.volumeQueue[0]:
                self.Log("################Volume has ascended over last three bars")
                self.volume_trigger=True
            else:
                self.volume_trigger=False

            #check if close price has gone up last 3 candles and set trigger accordingly
            if self.closeQueue[2] > self.closeQueue[1] and self.closeQueue[1] > self.closeQueue[0]:
                self.Log("################Price has ascended over last three bars")
                self.up_price_trigger=True
            else:
                self.up_price_trigger=False

            if self.volume_trigger and self.up_price_trigger:
                quantity = self.CalculateOrderQuantity(self.symbol, 0.5)
                self.MarketOrder(self.symbol, quantity)
                stopPrice = min(self.lowQueue)
                self.StopMarketOrder(self.symbol, -quantity, stopPrice)
                self.barCountSinceEntry = 0
            elif self.volume_trigger and self.down_price_trigger:
                quantity = self.CalculateOrderQuantity(self.symbol, -0.5)
                self.MarketOrder(self.symbol, quantity)
                stopPrice = max(self.highQueue)
                self.StopMarketOrder(self.symbol, -quantity, stopPrice)
                self.barCountSinceEntry = 0
        else:

            self.barCountSinceEntry += 1

            #else we are already invested
            if self.Portfolio[self.symbol].IsLong:   # If position is long
                if self.barCountSinceEntry >= 10 and self.lowQueue[2] < self.lowQueue[1]:
                    #lower low has been seen
                    self.Liquidate(self.symbol)
            elif self.barCountSinceEntry >= 10 and self.Portfolio[self.symbol].IsShort:   # If position is short
                if self.highQueue[2] > self.highQueue[1]:
                    #higher high has been seen
                    self.Liquidate(self.symbol)



