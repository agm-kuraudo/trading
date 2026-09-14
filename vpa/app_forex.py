"""Forex VPA entry point for GBPUSD.

Retrieves daily GBPUSD bars via the browserless Dukascopy retriever
(:func:`vpa.forex_data.get_daily_dataframe`) and runs the VPA analysis through
:class:`MarketAnalyzer`. This replaces the old Selenium/Firefox download that
depended on geckodriver being installed on the scheduled Raspberry Pi job.

Runnable as a script (``python app_forex.py``) via the Rundeck job /
``vpa/scripts/start_vpa_forex.sh``.
"""

from vpa.app_runner import MarketAnalyzer
from vpa.forex_data import get_daily_dataframe


def main():
    # Pass the FULL daily history (no .tail(51)): MarketAnalyzer's long-period
    # SMA is 200, so trimming to 51 rows would disable the MA crossover feature.
    # The retriever's min_bars check guarantees at least 200 daily bars.
    my_df = get_daily_dataframe(symbol="GBPUSD")

    analyzer = MarketAnalyzer(
        config_path="config/config.json",
        log_level="INFO",
        fixed_df=my_df,
        ticker_symbol="GBPUSD",
        log_prefix="GBPUSD",
    )
    trade_signal = analyzer.process_data()

    analyzer.graph_intervals()

    if trade_signal >= 15:
        analyzer.log("BUY Recommendation")
    elif trade_signal <= -15:
        analyzer.log("SELL Recommendation")
    else:
        analyzer.log("DO NOT TRADE")


if __name__ == "__main__":
    main()
