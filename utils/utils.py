import pandas as pd


def trading_days_between(start_date, end_date):
    # Convert both dates to pandas Timestamps
    start_date = pd.Timestamp(start_date)
    end_date = pd.Timestamp(end_date)

    # Ensure both dates are in the same timezone
    if start_date.tzinfo is None:
        start_date = start_date.tz_localize("UTC")
    else:
        start_date = start_date.tz_convert("UTC")

    if end_date.tzinfo is None:
        end_date = end_date.tz_localize("UTC")
    else:
        end_date = end_date.tz_convert("UTC")

    # Generate a date range between the start and end dates
    date_range = pd.date_range(start=start_date, end=end_date, freq="B")  # 'B' frequency stands for business days
    return len(date_range)
