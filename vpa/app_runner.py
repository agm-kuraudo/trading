import os
import json
import statistics
from collections import deque
import pandas as pd
import numpy as np
import yfinance as yf
import datetime
from vpa.app import DebugLog, Candle, calculate_adx, identify_acc_or_dist
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.dates import DateFormatter

#Passing a ticker_symbol will load data from yfinance. Passing a dataframe will directly use that dataframe
class MarketAnalyzer:
    def __init__(self, config_path, ticker_symbol=None, log_level="INFO", fixed_df=None):
        # Load configuration from the JSON file
        self.__ticker_symbol = ticker_symbol
        self.__config = None
        self.load_config(config_path)
        self.__logger = DebugLog(level=log_level)
        # Set up rolling windows for different periods
        self.__deque_dictionary = {
            "period_one": deque(maxlen=self.__config["PERIOD_ONE_LENGTH"]),
            "period_two": deque(maxlen=self.__config["PERIOD_TWO_LENGTH"]),
            "period_three": deque(maxlen=self.__config["PERIOD_THREE_LENGTH"])
        }
        # Template variable for storing the current percentile numbers for "spread" and "volume"
        self.__percentiles_store = {"spread": {}, "volume": {}}
        self.__rolling_window_complete_msg_display = self.__config["rolling_window_complete_msg_display"]

        if fixed_df is None:
            # Load data from the Yahoo Finance module or CSV file
            self.load_data()
        else:
            # Use the provided dataframe
            self.myDF = fixed_df

    def load_config(self, config_path):
        # Load configuration from JSON file
        with open(config_path, 'r') as file:
            self.__config = json.load(file)

    def load_data(self):
        # Step 1: Get our test data from CSV file or live quant data
        if self.__config["use_real_data"]:

            # Define the ticker symbol

            if self.__ticker_symbol is None:
                ticker_symbol = self.__config["ticker_symbol"]
            else:
                ticker_symbol = self.__ticker_symbol
            # Get the current date
            end_date = datetime.datetime.now().date()
            # Get the date one year ago from today
            start_date = end_date - datetime.timedelta(days=100)
            # Fetch the data for the last year
            self.myDF = yf.download(ticker_symbol, start=start_date, end=end_date, auto_adjust=True, progress=False)
            self.myDF = self.myDF.reset_index()
            self.myDF.columns = ['Date', 'Close', 'High', 'Low', 'Open', 'Volume']
        else:
            absolute_path = os.path.dirname(__file__)
            relative_path = "data/"
            full_path = os.path.join(absolute_path, relative_path)
            self.myDF = pd.read_csv(full_path + "spy_data.csv")
        self.myDF = self.myDF.sort_values("Date", axis=0)
        self.__logger.log(f"Data loaded: {self.myDF.shape} rows", level="INFO")

    def process_data(self):
        # Step 2: Loop around each item in the data frame

        trade_signal = 0

        # Get the last index
        last_index = self.myDF.index[-1]

        for index, row in self.myDF.iterrows():
            if not self.__config["use_real_data"] and 0 < self.__config["MAX_ROWS"] <= index:
                break
            self.__logger.log(f"Processing row: {index}", level="DEBUG")
            # Step 3: Create a new Candle object with the supplied properties for each new row
            this_candle = Candle(row['Date'], row['Volume'], row['Open'], row['High'], row['Low'], row['Close'])
            self.__logger.log(f"New candle created: {this_candle}", level="DEBUG")
            # Step 3.1: The candle is added to each of our rolling windows
            for key in self.__deque_dictionary.keys():
                self.__deque_dictionary[key].append(this_candle)
            # Step 4: We keep going without further action until we have enough data for all our rolling windows
            if len(self.__deque_dictionary["period_three"]) < self.__config["PERIOD_THREE_LENGTH"]:
                continue
            elif len(self.__deque_dictionary["period_three"]) == self.__config["PERIOD_THREE_LENGTH"]:
                if self.__rolling_window_complete_msg_display:
                    self.__logger.log("We now have enough data for all our rolling windows", level="INFO")
                    self.__rolling_window_complete_msg_display = False
            # Step 5: Update the spread and volumetric percentiles to understand relative size and strength of each Candle
            self.update_percentiles()

            if index == last_index:
                self.__logger.log("==================================================================================", level="INFO")
                self.__logger.log(self.myDF.head(5), level="DEBUG")
                self.__logger.log(self.myDF.tail(5), level="DEBUG")

                for key in self.__deque_dictionary.keys():
                    initial_close = self.__deque_dictionary[key][0].close
                    final_close = self.__deque_dictionary[key][-1].close
                    percentage_change = ((final_close - initial_close) / initial_close) * 100
                    self.__logger.log(f"{key} initial close: {initial_close}", level="DEBUG")
                    self.__logger.log(f"{key} final close: {final_close}", level="DEBUG")
                    self.__logger.log(f"{key} change: {percentage_change:.2f}%", level="INFO")

            # Step 6: Detect signals based on the updated data
            signals = self.detect_signals(this_candle)
            self.__logger.log(f"signals: {signals}", level="INFO")
            trade_signal = signals["single_candle_signal_score"] + signals["trend_signal_score"] + signals["multiple_bar_signal_score"] + signals["acc_dist_signal_score"]
            direction = "BUY" if trade_signal > 0 else "SELL"
            self.__logger.log(f"{this_candle.time} - trade_signal: {direction} : {trade_signal}", level="INFO")

        return trade_signal


    def update_percentiles(self):
        # Step 5.1: Working out the Percentiles for each Period for the spread and volume
        props = ["spread", "volume"]
        for prop in props:
            for key in self.__deque_dictionary.keys():
                stats_list = [getattr(item, prop) for item in self.__deque_dictionary[key]]
                self.__percentiles_store[prop][key] = np.percentile(stats_list, range(self.__config["PERCENTILE_START"], 100, self.__config["PERCENTILE_INCREMENTS"]))
                self.__logger.log(f"{prop} percentiles for {key}: {self.__percentiles_store[prop][key]}", level="DEBUG")
        # Step 5.2: Update all Candles in our rolling windows with their relevant percentiles
        for key in self.__deque_dictionary.keys():
            for candle in self.__deque_dictionary[key]:
                for prop in props:
                    upper_percentile = self.__config["PERCENTILE_START"]
                    for step in self.__percentiles_store[prop][key]:
                        if getattr(candle, prop) <= step:
                            upper_percentile += self.__config["PERCENTILE_INCREMENTS"]
                    if prop == "spread":
                        candle.spread_percentiles[key] = upper_percentile
                    elif prop == "volume":
                        candle.volume_percentiles[key] = upper_percentile
                self.__logger.log(f"Updated candle: {candle}", level="DEBUG")

    def detect_signals(self, this_candle):

        all_signals = {}

        single_candle_signals = []
        single_candle_signal_score = 0

        #Is the candle up or down? - score 1
        single_candle_signals.append("Up Bar" if this_candle.up_bar else "Down Bar")
        single_candle_signal_score += 1 if this_candle.up_bar else -1

        # Check for wide spread and high volume for each period, and adjust the score accordingly
        for period in self.__deque_dictionary.keys():
            if this_candle.spread_percentiles[period] > 70:
                single_candle_signals.append(f"Wide Spread ({period})")
                # Adjust score by 2.5 if up bar, otherwise subtract 2.5
                single_candle_signal_score += 2.5 if this_candle.up_bar else -2.5
                # Check for high volume if wide spread condition is met
                if this_candle.volume_percentiles[period] > 70:
                    single_candle_signals.append(f"High Volume ({period})")
                    # Adjust score by 2.5 if up bar, otherwise subtract 2.5
                    single_candle_signal_score += 2.5 if this_candle.up_bar else -2.5

        if this_candle.shooting_star:
            single_candle_signals.append("Shooting Star")
            single_candle_signal_score -= 3
        elif this_candle.hammer:
            single_candle_signals.append("Hammer")
            single_candle_signal_score += 3

        # Log the results
        self.__logger.log(f"Single Candle Signals: {single_candle_signals}", level="INFO")
        self.__logger.log(f"Single Candle Signal Score: {single_candle_signal_score}", level="INFO")

        all_signals["single_candle_signals"] = single_candle_signals
        all_signals["single_candle_signal_score"] = single_candle_signal_score

        trend_signals = []
        trend_signal_score = 0

        # Step 6: Understand if the market is trending and if so, in what direction
        adx_values = calculate_adx(self.__deque_dictionary["period_three"])
        self.__logger.log(f"{this_candle.time} - ADX values: {adx_values}", level="INFO")
        self.__logger.log(f"ADX - over 25 is trending.  Average True Range - Higher is more volatile.  DM+ swings upward. DM- Swings downwards", level="INFO")
        trending = adx_values[0] > 25
        trending_up = adx_values[2] > adx_values[3]
        trending_down = adx_values[3] > adx_values[2]
        if trending:
            self.__logger.log("Market is trending", level="INFO")
            trend_signals.append("Market is trending")
            if trending_up:
                self.__logger.log("Market is trending up", level="INFO")
                trend_signals.append("Trending Up")
                trend_signal_score += 5
            if trending_down:
                self.__logger.log("Market is trending down", level="INFO")
                trend_signals.append("Trending Down")
                trend_signal_score -= 5

        # Log the results
        self.__logger.log(f"Trend Signals: {trend_signals}", level="INFO")
        self.__logger.log(f"Trend Signal Score: {trend_signal_score}", level="INFO")

        all_signals["trend_signals"] = trend_signals
        all_signals["trend_signal_score"] = trend_signal_score

        # Step 7: Count the relevant candle types in each time period
        bar_counts = {}
        signals = {
            "period_one_bull": False,
            "period_one_bear": False,
            "period_one_volume_backed": False,
            "period_two_bull": False,
            "period_two_bear": False,
            "period_two_volume_backed": False,
            "period_three_bull": False,
            "period_three_bear": False,
            "period_three_volume_backed": False,
        }
        for key in self.__deque_dictionary.keys():
            up_bar_count = sum(1 for candle in self.__deque_dictionary[key] if candle.up_bar)
            high_spread_count = sum(1 for candle in self.__deque_dictionary[key] if candle.spread_percentiles[key] > self.__config["trading_parameters"][key]["High_Spread_Threshold"])
            high_volume_count = sum(1 for candle in self.__deque_dictionary[key] if candle.volume_percentiles[key] > self.__config["trading_parameters"][key]["High_Volume_Threshold"])
            anomaly_count = sum(1 for candle in self.__deque_dictionary[key] if abs(candle.spread_percentiles[key] - candle.volume_percentiles[key]) > self.__config["trading_parameters"][key]["Anomaly_Threshold"])
            bar_counts[key] = {
                "up_bars": up_bar_count,
                "high_spread_count": high_spread_count,
                "high_volume_count": high_volume_count,
                "anomaly_count": anomaly_count
            }
            self.__logger.log(f"{key} Bar Counts: {bar_counts[key]}", level="DEBUG")
            # Step 8: Decide whether a signal is being generated on each time period
            if up_bar_count >= self.__config["trading_parameters"][key]["Signal_Bar_Count"]:
                signals[f"{key}_bull"] = True
                self.__logger.log(f"{key} Bullish Signal", level="INFO")
            elif up_bar_count <= (self.__config["PERIOD_ONE_LENGTH"] - self.__config["trading_parameters"][key]["Signal_Bar_Count"]):
                signals[f"{key}_bear"] = True
                self.__logger.log(f"{key} Bearish Signal", level="INFO")
            if signals[f"{key}_bear"] or signals[f"{key}_bull"]:
                if high_spread_count >= self.__config["trading_parameters"][key]["High_Spread_Count"] and high_volume_count >= self.__config["trading_parameters"][key]["High_Volume_Count"] and anomaly_count <= self.__config["trading_parameters"][key]["Anomaly_Threshold"]:
                    signals[f"{key}_volume_backed"] = True
                    self.__logger.log(f"{this_candle.time} {key} Volume Backed Signal", level="INFO")

        # Initialize multiple bar signals and score
        multiple_bar_signals = []
        multiple_bar_signal_score = 0

        # Check for bull and bear signals for each period, and adjust the score accordingly
        for period in self.__deque_dictionary.keys():
            for signal_type in ["bull", "bear"]:
                if signals[f"{period}_{signal_type}"]:
                    multiple_bar_signals.append(f"{signal_type.capitalize()} Signal ({period})")
                    score_adjustment = 2.5 if signal_type == "bull" else -2.5
                    if signals[f"{period}_volume_backed"]:
                        multiple_bar_signal_score += score_adjustment * 2
                        multiple_bar_signals.append(f"Volume Backed ({period})")
                    else:
                        multiple_bar_signal_score += score_adjustment

        # Log the results
        self.__logger.log(f"Multiple Bar Signals: {multiple_bar_signals}", level="INFO")
        self.__logger.log(f"Multiple Bar Signal Score: {multiple_bar_signal_score}", level="INFO")

        all_signals["multiple_bar_signals"] = multiple_bar_signals
        all_signals["multiple_bar_signal_score"] = multiple_bar_signal_score


        # Initialize accumulation/distribution signals and score
        acc_dist_signals = []
        acc_dist_signal_score = 0

        # Step 9: Identify if the market is near accumulation or distribution points
        acc_or_dist_bool, acc_or_dist = identify_acc_or_dist(self.__deque_dictionary["period_three"], self.__deque_dictionary["period_one"])
        if acc_or_dist_bool:
            acc_dist_signals.append(f"Possible {acc_or_dist}")
            acc_dist_signal_score += 10 if acc_or_dist == "Acc" else -10
            self.__logger.log(f"{this_candle.time} Possible {acc_or_dist} IDENTIFIED #####", level="INFO")
            if this_candle.spread_percentiles['period_one'] > 65 or this_candle.is_candle_pattern():
                self.__logger.log(f"Potential Test IDENTIFIED ##########", level="DEBUG")
                if this_candle.volume_percentiles['period_one'] < 50:
                    acc_dist_signals.append("Test Pass")
                    acc_dist_signal_score += 5 if acc_or_dist == "Acc" else -5
                    self.__logger.log(f"Potential TEST PASS IDENTIFIED ##########", level="INFO")
                else:
                    acc_dist_signals.append("Test Fail")
                    # Test fail makes the signal weaker
                    acc_dist_signal_score -= 2 if acc_or_dist == "Acc" else 2
                    self.__logger.log("Potential TEST FAIL IDENTIFIED ##########", level="INFO")
            if this_candle.spread_percentiles['period_two'] < 40 and this_candle.volume_percentiles['period_two'] > 60:
                acc_dist_signals.append("Climax")
                acc_dist_signal_score += 10 if acc_or_dist == "Acc" else -10
                self.__logger.log(f"Potential Climax IDENTIFIED ##########", level="INFO")

        # Log the results
        self.__logger.log(f"Accumulation/Distribution Signals: {acc_dist_signals}", level="INFO")
        self.__logger.log(f"Accumulation/Distribution Signal Score: {acc_dist_signal_score}", level="INFO")

        all_signals["acc_dist_signals"] = acc_dist_signals
        all_signals["acc_dist_signal_score"] = acc_dist_signal_score
        return all_signals

    def graph_intervals(self):

        for period in self.__deque_dictionary.keys():
            fig, ax = plt.subplots()

            for candle in self.__deque_dictionary[period]:
                color = 'green' if candle.close >= candle.open else 'red'
                ax.plot([candle.time, candle.time], [candle.low, candle.high], color='black')  # Wick
                ax.plot([candle.time, candle.time], [candle.open, candle.close], color=color, linewidth=6)  # Body


            # Set x-ticks only for dates with data
            dates = [candle.time for candle in self.__deque_dictionary[period]]
            ax.set_xticks(dates)
            ax.xaxis.set_major_formatter(DateFormatter('%Y-%m-%d'))

            # Rotate and resize x-axis labels
            plt.xticks(rotation=90, fontsize=8)

            ax.set_xlabel('Time')
            ax.set_ylabel('Price')
            ax.set_title(f'{self.__ticker_symbol} - {period} - Candlestick Chart')
            plt.grid()
            plt.tight_layout()  # Adjust layout to prevent clipping
            plt.show()

if __name__ == "__main__":
    analyzer = MarketAnalyzer(config_path="config/config.json", ticker_symbol="SPY")
    trade_signal = analyzer.process_data()

    analyzer.graph_intervals()

    if trade_signal >= 15:
        print("BUY Recommendation")
    elif trade_signal <= -15:
        print("SELL Recommendation")
    else:
        print("DO NOT TRADE")