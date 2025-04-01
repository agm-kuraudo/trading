def trade_size(cash, risk_per_trade_theory, risk_per_trade_exposure_max, share_price, stop_price_distance, debug=False):
    # Calculate the theoretical risk per trade
    theoretical_risk = cash * risk_per_trade_theory
    if debug:
        print(f"Theoretical risk per trade: {theoretical_risk}")

    # Calculate the maximum exposure per trade
    max_exposure = cash * risk_per_trade_exposure_max
    if debug:
        print(f"Maximum exposure per trade: {max_exposure}")

    # Calculate the number of shares to buy based on theoretical risk
    shares_theory = theoretical_risk / stop_price_distance
    if debug:
        print(f"Shares based on theoretical risk: {shares_theory}")

    # Calculate the number of shares to buy based on maximum exposure
    shares_exposure = max_exposure / share_price
    if debug:
        print(f"Shares based on maximum exposure: {shares_exposure}")

    # Return the minimum of the two calculated shares to ensure both conditions are met
    trade_size_result = min(shares_theory, shares_exposure)
    if debug:
        print(f"Trade size: {trade_size_result} shares")

    return trade_size_result

if __name__ == "__main__":
    # Example usage
    cash = 30000
    risk_per_trade_theory = 0.01  # 1% of cash
    risk_per_trade_exposure_max = 0.9  # 10% of cash
    share_price = 50
    stop_price_distance = 6

    trade_size_result = trade_size(cash, risk_per_trade_theory, risk_per_trade_exposure_max, share_price,
                                   stop_price_distance, debug=True)
    print(f"Trade size: {trade_size_result} shares")