import numpy as np
import matplotlib.pyplot as plt

option_strategies = {
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
            "title": "Long Put"
        }
    ]
}

for strategy in option_strategies.keys():
    options = option_strategies[strategy]

    # for trade in options:

    plt.figure(figsize=(10, 6))

    payouts = {}
    stock_prices = np.linspace(0, 2 * options[0]["asset_price"], 200)

    for trade in options:

        asset_price = trade["asset_price"]
        strike_price = trade["strike_price"]
        option_type = trade["option_type"]
        option_cost = trade["option_cost"]
        position = trade["position"]
        title = trade["title"]

        payouts[title] = []


        for stock_price in stock_prices:
            if position == 'long':
                if option_type == 'share_purchase':
                    payout = stock_price - option_cost
                    print(f"Stock: if stock price is {stock_price} then payout is {payout}")
                    payouts[title].append(payout)
                elif option_type == 'call':
                    payout = max(((stock_price - strike_price) - option_cost), -option_cost)
                    print(f"Call: if stock price is {stock_price} then payout is {payout}")
                    payouts[title].append(payout)
                else:
                    payout = max(((strike_price - stock_price) - option_cost), -option_cost)
                    print(f"Put: if stock price is {stock_price} then payout is {payout}")
                    payouts[title].append(payout)
            else: # the position is short
                if option_type == 'share_purchase':
                    raise Exception("Cannot be short a Share Purchase")
                elif option_type == 'call':
                    payout = min((strike_price - stock_price)+option_cost, option_cost)
                    print(f"Call Short: if stock price is {stock_price} then payout is {payout}")
                    payouts[title].append(payout)
                else:
                    payout = min(option_cost - max(strike_price - stock_price, 0), option_cost) #This short put bit wasn't fully tested as wasn't part of this section. Should work though!
                    print(f"Put Short: if stock price is {stock_price} then payout is {payout}")
                    payouts[title].append(payout)

        plt.plot(stock_prices, payouts[title],
                 label=f'{title} Option Profit and Loss')

    # Calculate combined payouts dynamically
    combined_payouts = [sum(payout) for payout in zip(*payouts.values())]
    plt.plot(stock_prices, combined_payouts, label='Combined Profit and Loss')

    print(payouts)

    plt.title(f"{strategy}.png")
    plt.xlabel('Stock Price')
    plt.ylabel('Profit and Loss')
    plt.legend()
    plt.axhline(0, color='black', linestyle='--', linewidth=1)
    plt.grid(True)
    plt.savefig(f"charts/{strategy}.png")
    plt.show()

#print(stock_prices)