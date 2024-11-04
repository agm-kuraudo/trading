import yfinance as yf
ticker = "^VIX"
data = yf.download(ticker, start="2020-11-16", end="2021-11-06")
data.to_csv("vix_data.csv")