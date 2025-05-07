import matplotlib.pyplot as plt
import numpy as np
import os

do_section_3_1 = False
do_section_3_2 = True

# Ensure the directory for saving charts exists
if not os.path.exists('charts'):
    os.makedirs('charts')


# Function to calculate option payoff
def option_payoff(S, K, option_type='call', position='long'):
    if option_type == 'call':
        payoff = np.maximum(S - K, 0)
    elif option_type == 'put':
        payoff = np.maximum(K - S, 0)
    else:
        raise ValueError("Invalid option type. Use 'call' or 'put'.")

    if position == 'short':
        payoff = -payoff

    return payoff


def generate_chart_single_option(asset_price, strike_price, option_type, option_cost, title, position='long',
                                 save_to_file=True, show_chart=False):
    # Generate stock prices from 0 to double the current price
    stock_prices = np.linspace(0, 2 * asset_price, 100)

    # Calculate payoffs for the given stock prices
    payoffs = option_payoff(stock_prices, strike_price, option_type, position)

    # Calculate profit and loss by subtracting the cost of the option
    profit_and_loss = payoffs - option_cost if position == 'long' else payoffs + option_cost

    # Plot the profit and loss chart
    plt.figure(figsize=(10, 6))
    plt.plot(stock_prices, profit_and_loss,
             label=f'{position.capitalize()} {option_type.capitalize()} Option Profit and Loss')
    plt.axhline(0, color='black', linestyle='--', linewidth=1)
    plt.axvline(asset_price, color='red', linestyle='--', linewidth=1, label='Current Stock Price')
    plt.title(title)
    plt.xlabel('Stock Price')
    plt.ylabel('Profit and Loss')
    plt.legend()
    plt.grid(True)

    if save_to_file:
        plt.savefig(f"charts/{title.replace(' ', '_').lower()}.png")

    if show_chart:
        plt.show()

# Section 3.1 - Single Options
if do_section_3_1:
    # List of input parameters as dictionaries
    options = [
        {
            "asset_price": 1779,
            "strike_price": 1700,
            "position": 'long',
            "option_type": 'call',
            "option_cost": 144.19,
            "title": "Long Call - Profit and Loss Chart"
        },
        {
            "asset_price": 1779,
            "strike_price": 1700,
            "position": 'long',
            "option_type": 'put',
            "option_cost": 144.19,
            "title": "Long Put - Profit and Loss Chart"
        },
        {
            "asset_price": 1779,
            "strike_price": 1700,
            "position": 'short',
            "option_type": 'call',
            "option_cost": 144.19,
            "title": "Short Call - Profit and Loss Chart"
        },
        {
            "asset_price": 1779,
            "strike_price": 1700,
            "position": 'short',
            "option_type": 'put',
            "option_cost": 144.19,
            "title": "Short Put - Profit and Loss Chart"
        }
    ]
