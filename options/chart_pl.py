import matplotlib.pyplot as plt
import numpy as np

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

def generate_chart_single_option(asset_price, strike_price, option_type, option_cost, title, position='long', save_to_file=True, show_chart=False):
    # Generate stock prices from 0 to double the current price
    stock_prices = np.linspace(0, 2 * asset_price, 100)

    # Calculate payoffs for the given stock prices
    payoffs = option_payoff(stock_prices, strike_price, option_type, position)

    # Calculate profit and loss by subtracting the cost of the option
    profit_and_loss = payoffs - option_cost if position == 'long' else payoffs + option_cost

    # Plot the profit and loss chart
    plt.figure(figsize=(10, 6))
    plt.plot(stock_prices, profit_and_loss, label=f'{position.capitalize()} {option_type.capitalize()} Option Profit and Loss')
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

    # Calculate payoffs for stock price at zero and at double the current price
    payoff_at_zero = option_payoff(0, strike_price, option_type, position) - option_cost if position == 'long' else option_payoff(0, strike_price, option_type, position) + option_cost
    payoff_at_double = option_payoff(2 * asset_price, strike_price, option_type, position) - option_cost if position == 'long' else option_payoff(2 * asset_price, strike_price, option_type, position) + option_cost

    print(f"{title} - Profit and Loss at Stock Price Zero: {payoff_at_zero}")
    print(f"{title} - Profit and Loss at Stock Price Double: {payoff_at_double}")

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

# Loop through each set of input parameters and generate charts
for option in options:
    generate_chart_single_option(asset_price=option["asset_price"],
                                 strike_price=option["strike_price"],
                                 option_type=option["option_type"],
                                 option_cost=option["option_cost"],
                                 title=option["title"],
                                 position=option["position"],
                                 save_to_file=True,
                                 show_chart=True)