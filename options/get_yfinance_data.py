import yfinance as yf
import matplotlib.pyplot as plt
# ticker = "^VIX"
# data = yf.download(ticker, start="2020-11-16", end="2021-11-06")
# data.to_csv("vix_data.csv")



data = yf.download('SPY', start='2023-01-02', end='2024-11-12')

data.to_csv("spy_data.csv")

# Plot the close price
plt.figure(figsize=(15, 7))
data['Adj Close'].plot()

# Set the title and axis label
plt.title('SPY Data', fontsize=16)
plt.xlabel('Year-Month', fontsize=15)
plt.ylabel('Price', fontsize=15)
plt.xticks(fontsize=15)
plt.yticks(fontsize=15)
plt.legend(['Close'], prop={'size': 15})

# Show the plot
plt.savefig("spy_data.png")