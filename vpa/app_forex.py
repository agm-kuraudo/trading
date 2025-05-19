from vpa.app_runner import MarketAnalyzer
import pandas as pd

my_df = pd.read_csv("data/GBPUSD_H1_CutDown.csv", sep="\t", index_col=False)

print(my_df.head(5))
my_df.columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']

print(my_df.head(5))

analyzer = MarketAnalyzer(config_path="config/config.json", log_level="INFO", fixed_df=my_df)
signal_score = analyzer.process_data()