"""
Calculate all the greek formula values given the input values
https://amainit.atlassian.net/browse/SP-167

https://www.optionstrading.org/blog/option-greeks-made-simple-cheat-sheet/

Input Parameters:

+ Underlying asset price
+ Strike price
+ Time to expiration (in years)
+ Risk-free interest rate
+ Volatility (standard deviation of the underlying asset's returns)
+ Option type (call or put)

Output:
+ Delta
+ Gamma
+ Theta
+ Vega
+ Rho
"""
import numpy as np
from scipy.stats import norm
from datetime import date

# Existing imports and functions
from utils.utils import get_live_data_from_yfinance, return_sample_data, trading_days_between, get_asset_data, \
    process_data, calculate_volatility, calculate_binomial_parameters, price_option


ASSET_PRICE = 218.27
OPTION_PRICE = 0.71
STRIKE_PRICE = 330
EXPIRATION_DATE = date(2026, 1, 16)
RISK_FREE_INTEREST_RATE = 5 / 100  # Convert percentage to decimal
VOLATILITY = 12.5 / 100  # Convert percentage to decimal
OPTIONS_TYPE = 'call'


def calculate_greeks(S, K, T, r, sigma, option_type='call'):
    """
    Calculate the Greeks of an option using the Black-Scholes model.

    Parameters:
    S (float): Current stock price
    K (float): Strike price
    T (float): Time to expiration in years
    r (float): Risk-free interest rate
    sigma (float): Volatility of the stock
    option_type (str): Type of the option ('call' or 'put')

    Returns:
    dict: Dictionary containing the Greeks (Delta, Gamma, Theta, Vega, Rho)
    """
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == 'call':
        delta = norm.cdf(d1)
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
        rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100
    elif option_type == 'put':
        delta = -norm.cdf(-d1)
        theta = (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365
        rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100
    else:
        raise ValueError("Invalid option type. Use 'call' or 'put'.")

    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    vega = S * norm.pdf(d1) * np.sqrt(T) / 100

    return {
        'Delta': delta,
        'Gamma': gamma,
        'Theta': theta,
        'Vega': vega,
        'Rho': rho
    }

# Calculate Time to Expiration
current_date = date.today()
time_to_expiration = (EXPIRATION_DATE - current_date).days / 365

# Calculate Greeks for the given option
greeks = calculate_greeks(ASSET_PRICE, STRIKE_PRICE, time_to_expiration, RISK_FREE_INTEREST_RATE, VOLATILITY, OPTIONS_TYPE)

# Print the results
for greek, value in greeks.items():
    print(f"{greek}: {value:.4f}")