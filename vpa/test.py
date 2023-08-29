from candle import Candle
from candle_history import CandleHistory

first_candle = Candle(1,2,3,4,5)
all_history = CandleHistory(3, 10, 50)

all_history.addCandle(first_candle)

print(first_candle)
print(all_history)
