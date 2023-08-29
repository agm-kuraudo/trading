import numpy as np
import pandas as pd
import yfinance as yf
import myplot as pl
import pandas_ta as pta


#apple_ticker = yf.Ticker("APPL")
appl_daily = yf.download("AAPL", start="2023-01-01", end="2023-02-26")
appl_daily.index.name = 'Date'
appl_daily.shape

appl_daily["ADR"] = (appl_daily["High"]-appl_daily["Low"]).abs().rolling(7).mean()
print(appl_daily)

print("############################################################################################################################################\n\n\n")
ADR = appl_daily["ADR"].iloc[-1]
print(ADR)
print("############################################################################################################################################\n\n\n")

#apple_ticker = yf.Ticker("APPL")
appl_df = yf.download("AAPL", period="3d", interval="1m")
appl_df.index.name = 'Date'
appl_df.shape

#appl_df = appl_df.drop(columns=["Adj Close"])

print(appl_df)

appl_df["MA_12"] = appl_df["Adj Close"].rolling(12).mean()
appl_df["std"] = appl_df["Adj Close"].rolling(12).std()
appl_df["BollingerUp"] = appl_df["MA_12"] + (appl_df["std"] * 2)
appl_df["BollingerDown"] = appl_df["MA_12"] - (appl_df["std"] * 2)

appl_df["BollingerUpTrigger"] = appl_df.apply(lambda x : True if x["Adj Close"] > x["BollingerUp"] else False, axis=1)
appl_df["BollingerDownTrigger"] = appl_df.apply(lambda x : True if x["Adj Close"] < x["BollingerDown"] else False, axis=1)

appl_df["bolingerchange1"] = appl_df["BollingerUp"] - appl_df.shift(1)["BollingerUp"]
appl_df["bolingerchange2"] = appl_df.shift(1)["BollingerUp"] - appl_df.shift(2)["BollingerUp"]
appl_df["bolingerchange3"] = appl_df.shift(2)["BollingerUp"] - appl_df.shift(3)["BollingerUp"]

appl_df.loc[(appl_df.bolingerchange1 > 0) & (appl_df.bolingerchange2 > 0) & (appl_df.bolingerchange3 > 0), "Arrow"] = "UP"
appl_df.loc[(appl_df.bolingerchange1 < 0) & (appl_df.bolingerchange2 < 0) & (appl_df.bolingerchange3 < 0), "Arrow"] = "DOWN"

exp1 = appl_df["Adj Close"].ewm(span=12, adjust=False).mean()

print(exp1)

exp2 = appl_df["Adj Close"].ewm(span=26, adjust=False).mean()

print(exp2)

appl_df["MACD"] = exp1 - exp2
appl_df["MACD_Trigger"] = appl_df["MACD"].ewm(span=9, adjust=False).mean()

print(appl_df)

#appl_df["MarketCondition"] = appl_df.apply(lambda x: "BULL" if x["MACD"] > 0 & x["MACD_Trigger"]> 0 else "")

appl_df.loc[(appl_df.MACD > 0) & (appl_df.MACD_Trigger > 0), "Market"] = "Bull"

appl_df.loc[(appl_df.MACD < 0) & (appl_df.MACD_Trigger < 0), "Market"] = "Bear"

appl_df["RSI"] = pta.rsi(appl_df['Close'], length = 7)

#appl_df.loc[(appl_df.MACD < 0) & (appl_df.MACD_Trigger < 0), "Trade"] = "Bear"


appl_df.loc[(appl_df.Market == "Bull") & (appl_df.Arrow == "UP") & (appl_df.RSI > 70) & (appl_df.BollingerUpTrigger ==True), "Trade"] = "Long Trade"

appl_df.loc[(appl_df.Market == "Bear") & (appl_df.Arrow == "DOWN") & (appl_df.RSI < 30)& (appl_df.BollingerDownTrigger ==True), "Trade"] = "Short Trade"


print(appl_df)

appl_df.to_csv("test.csv")

plotter = pl.myplot(appl_df)


#Have the trade triggers working.  Need to log trades - either directly here or move code to quant

#plotter.renko_plot()

