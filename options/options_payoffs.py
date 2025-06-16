import numpy as np
import matplotlib.pyplot as plt
import os

class OptionStrategy:
    def __init__(self, strategy_name, options):
        self.strategy_name = strategy_name
        self.options = options
        self.payouts = {}
        self.stock_prices = np.linspace(0, 2 * options[0]["asset_price"], 200)

    def calculate_payouts(self):
        for trade in self.options:
            asset_price = trade["asset_price"]
            strike_price = trade["strike_price"]
            option_type = trade["option_type"]
            option_cost = trade["option_cost"]
            position = trade["position"]
            title = trade["title"]

            self.payouts[title] = []

            for stock_price in self.stock_prices:
                if position == 'long':
                    if option_type == 'share_purchase':
                        payout = stock_price - option_cost
                    elif option_type == 'call':
                        payout = max(((stock_price - strike_price) - option_cost), -option_cost)
                    else:  # put
                        payout = max(((strike_price - stock_price) - option_cost), -option_cost)
                else:  # short position
                    if option_type == 'share_purchase':
                        raise Exception("Cannot be short a Share Purchase")
                    elif option_type == 'call':
                        payout = min((strike_price - stock_price) + option_cost, option_cost)
                    else:  # put
                        payout = min(option_cost - max(strike_price - stock_price, 0), option_cost)

                self.payouts[title].append(payout)

    def plot_payouts(self, to_screen=False):
        if not os.path.exists('charts'):
            os.makedirs('charts')

        plt.figure(figsize=(10, 6))

        for title, payout in self.payouts.items():
            plt.plot(self.stock_prices, payout, label=f'{title} Option Profit and Loss')

        combined_payouts = [sum(payout) for payout in zip(*self.payouts.values())]
        plt.plot(self.stock_prices, combined_payouts, label='Combined Profit and Loss')

        plt.title(f"{self.strategy_name.capitalize()} Strategy")
        plt.xlabel('Stock Price')
        plt.ylabel('Profit and Loss')
        plt.legend()
        plt.axhline(0, color='black', linestyle='--', linewidth=1)
        plt.grid(True)
        plt.savefig(f"charts/{self.strategy_name}.png")
        if to_screen:
            plt.show()

    def print_summary(self):
        combined_payouts = [sum(payout) for payout in zip(*self.payouts.values())]
        max_profit = max(combined_payouts)
        max_loss = min(combined_payouts)

        profitable_ranges = []
        current_range = []

        for i in range(len(combined_payouts)):
            if combined_payouts[i] > 0:
                current_range.append(self.stock_prices[i])
            else:
                if current_range:
                    profitable_ranges.append((current_range[0], current_range[-1]))
                    current_range = []

        if current_range:
            profitable_ranges.append((current_range[0], current_range[-1]))

        has_long_call = any(trade["option_type"] == 'call' and trade["position"] == 'long' for trade in self.options)
        has_short_call = any(trade["option_type"] == 'call' and trade["position"] == 'short' for trade in self.options)

        # Check for spread strategies
        is_spread = (any(trade["option_type"] == 'call' and trade["position"] == 'long' for trade in self.options) and
                     any(trade["option_type"] == 'call' and trade["position"] == 'short' for trade in self.options))

        if is_spread:
            max_profit = max(combined_payouts)
            max_loss = min(combined_payouts)
        else:
            max_profit = 'Infinite' if has_long_call else round(max_profit, 2)
            max_loss = 'Infinite' if has_short_call else round(max_loss, 2)

        print(f"Strategy: {self.strategy_name.capitalize()}")
        print(f"Maximum Profit: {max_profit}")
        print(f"Maximum Loss: {max_loss}")

        if profitable_ranges:
            for start, end in profitable_ranges:
                end_str = "Infinite" if end == self.stock_prices[-1] else f"{round(end, 2)}"
                print(f"Profitable Range: {round(start, 2)} to {end_str}")
        else:
            print("No profitable range.\n")

# Example usage - section 3.2
option_strategies_3_2 = {
    "married_put": [
        {
            "asset_price": 1779,
            "strike_price": 1700,
            "position": 'long',
            "option_type": 'share_purchase',
            "option_cost": 1779,
            "title": "Long Stock"
        },
        {
            "asset_price": 1779,
            "strike_price": 1700,
            "position": 'long',
            "option_type": 'put',
            "option_cost": 144.19,
            "title": "Long Put"
        }
    ],
    "covered_call": [
        {
            "asset_price": 1779,
            "strike_price": 1700,
            "position": 'long',
            "option_type": 'share_purchase',
            "option_cost": 1779,
            "title": "Long Stock"
        },
        {
            "asset_price": 1779,
            "strike_price": 1700,
            "position": 'short',
            "option_type": 'call',
            "option_cost": 144.19,
            "title": "Short Call"
        }
    ]
}

# Example usage - section 3.2
option_strategies_3_3 = {
    "long_straddle": [
        {
            "asset_price": 6018,
            "strike_price": 6015,
            "position": 'long',
            "option_type": 'call',
            "option_cost": 44.01,
            "title": "Long Call"
        },
        {
            "asset_price": 6018,
            "strike_price": 6015,
            "position": 'long',
            "option_type": 'put',
            "option_cost": 40.79,
            "title": "Long Put"
        }
    ],
    "short_straddle": [
        {
            "asset_price": 6018,
            "strike_price": 6015,
            "position": 'short',
            "option_type": 'call',
            "option_cost": 44.01,
            "title": "Short Call"
        },
        {
            "asset_price": 6018,
            "strike_price": 6015,
            "position": 'short',
            "option_type": 'put',
            "option_cost": 40.79,
            "title": "Short Put"
        }
    ],
    "long_strangle": [
        {
            "asset_price": 6018,
            "strike_price": 6000,
            "position": 'long',
            "option_type": 'call',
            "option_cost": 34.58,
            "title": "Long Call"
        },
        {
            "asset_price": 6018,
            "strike_price": 6030,
            "position": 'long',
            "option_type": 'put',
            "option_cost": 35,
            "title": "Long Put"
        }
    ],
    "short_strangle": [
        {
            "asset_price": 6018,
            "strike_price": 6000,
            "position": 'short',
            "option_type": 'call',
            "option_cost": 34.58,
            "title": "Short Call"
        },
        {
            "asset_price": 6018,
            "strike_price": 6030,
            "position": 'short',
            "option_type": 'put',
            "option_cost": 35,
            "title": "Short Put"
        }
    ],
    "bull_call_spread": [
        {
            "asset_price": 6020,
            "strike_price": 6020,
            "position": 'long',
            "option_type": 'call',
            "option_cost": 43.31,
            "title": "Long Call"
        },
        {
            "asset_price": 6020,
            "strike_price": 6080,
            "position": 'short',
            "option_type": 'call',
            "option_cost": 14.22,
            "title": "Short Call"
        }
    ],
    "bear_call_spread": [
        {
            "asset_price": 6020,
            "strike_price": 6020,
            "position": 'short',
            "option_type": 'call',
            "option_cost": 43.31,
            "title": "Short Call"
        },
        {
            "asset_price": 6020,
            "strike_price": 6080,
            "position": 'long',
            "option_type": 'call',
            "option_cost": 14.22,
            "title": "Long Call"
        }
    ],
    "Synthetic_Long": [
        {
            "asset_price": 6018,
            "strike_price": 6020,
            "position": 'long',
            "option_type": 'call',
            "option_cost": 42.39,
            "title": "Long Call"
        },
        {
            "asset_price": 6020,
            "strike_price": 6020,
            "position": 'short',
            "option_type": 'put',
            "option_cost": 42.09,
            "title": "Short Put"
        }
    ],
    "Synthetic_Short": [
        {
            "asset_price": 6018,
            "strike_price": 6020,
            "position": 'short',
            "option_type": 'call',
            "option_cost": 42.39,
            "title": "Short Call"
        },
        {
            "asset_price": 6020,
            "strike_price": 6020,
            "position": 'long',
            "option_type": 'put',
            "option_cost": 42.09,
            "title": "Long Put"
        }
    ]
}


strategy_seperator = "###################################################################################"

print(strategy_seperator)

for strategy_name, options in option_strategies_3_3.items():
    strategy = OptionStrategy(strategy_name, options)
    strategy.calculate_payouts()
    strategy.plot_payouts()
    strategy.print_summary()
    print(strategy_seperator)
