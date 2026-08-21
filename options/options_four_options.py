# Strategy Explanations
# Short Iron Condor: A neutral strategy using a Bear Call Spread and a Bull Put Spread
#   to profit from low volatility.
# Long Iron Condor: A volatility-neutral strategy that profits if the price moves sharply
#   outside the outer strikes, essentially buying two spreads.
# Long Condor Spreads: Unlike the "Iron" versions which mix calls and puts, these use
#   four strikes of the same option type (all calls or all puts).
# Iron Butterfly: A variation of the iron condor where the two short strikes are identical
#   (usually at-the-money), creating a narrower but higher-potential profit peak.
# Long Inverse Skip Butterfly: A "Skip" butterfly typically skips one of the long wings to
#   create a directional bias. An inverse version flips the standard butterfly into a net
#   credit or "short" body position to profit from a move in one direction without the risk
#   of the skipped wing.

from options_payoffs import OptionStrategy


def run_advanced_strategies():
    # Example spot price for the underlying asset
    spot = 100.0

    advanced_strategies = {
        "short_iron_condor": [
            {
                "asset_price": spot,
                "strike_price": 90,
                "position": "long",
                "option_type": "put",
                "option_cost": 1.0,
                "title": "Long OTM Put",
            },
            {
                "asset_price": spot,
                "strike_price": 95,
                "position": "short",
                "option_type": "put",
                "option_cost": 2.5,
                "title": "Short OTM Put",
            },
            {
                "asset_price": spot,
                "strike_price": 105,
                "position": "short",
                "option_type": "call",
                "option_cost": 2.5,
                "title": "Short OTM Call",
            },
            {
                "asset_price": spot,
                "strike_price": 110,
                "position": "long",
                "option_type": "call",
                "option_cost": 1.0,
                "title": "Long OTM Call",
            },
        ],
        "long_iron_condor": [
            {
                "asset_price": spot,
                "strike_price": 90,
                "position": "short",
                "option_type": "put",
                "option_cost": 1.0,
                "title": "Short OTM Put",
            },
            {
                "asset_price": spot,
                "strike_price": 95,
                "position": "long",
                "option_type": "put",
                "option_cost": 2.5,
                "title": "Long OTM Put",
            },
            {
                "asset_price": spot,
                "strike_price": 105,
                "position": "long",
                "option_type": "call",
                "option_cost": 2.5,
                "title": "Long OTM Call",
            },
            {
                "asset_price": spot,
                "strike_price": 110,
                "position": "short",
                "option_type": "call",
                "option_cost": 1.0,
                "title": "Short OTM Call",
            },
        ],
        "long_condor_spread_calls": [
            {
                "asset_price": spot,
                "strike_price": 90,
                "position": "long",
                "option_type": "call",
                "option_cost": 11.0,
                "title": "Long Call 1",
            },
            {
                "asset_price": spot,
                "strike_price": 95,
                "position": "short",
                "option_type": "call",
                "option_cost": 7.0,
                "title": "Short Call 2",
            },
            {
                "asset_price": spot,
                "strike_price": 105,
                "position": "short",
                "option_type": "call",
                "option_cost": 2.0,
                "title": "Short Call 3",
            },
            {
                "asset_price": spot,
                "strike_price": 110,
                "position": "long",
                "option_type": "call",
                "option_cost": 1.0,
                "title": "Long Call 4",
            },
        ],
        "long_condor_spread_puts": [
            {
                "asset_price": spot,
                "strike_price": 90,
                "position": "long",
                "option_type": "put",
                "option_cost": 1.0,
                "title": "Long Put 1",
            },
            {
                "asset_price": spot,
                "strike_price": 95,
                "position": "short",
                "option_type": "put",
                "option_cost": 2.0,
                "title": "Short Put 2",
            },
            {
                "asset_price": spot,
                "strike_price": 105,
                "position": "short",
                "option_type": "put",
                "option_cost": 7.0,
                "title": "Short Put 3",
            },
            {
                "asset_price": spot,
                "strike_price": 110,
                "position": "long",
                "option_type": "put",
                "option_cost": 11.0,
                "title": "Long Put 4",
            },
        ],
        "iron_butterfly": [
            {
                "asset_price": spot,
                "strike_price": 95,
                "position": "long",
                "option_type": "put",
                "option_cost": 2.0,
                "title": "Long Put Wing",
            },
            {
                "asset_price": spot,
                "strike_price": 100,
                "position": "short",
                "option_type": "put",
                "option_cost": 4.5,
                "title": "Short ATM Put",
            },
            {
                "asset_price": spot,
                "strike_price": 100,
                "position": "short",
                "option_type": "call",
                "option_cost": 4.5,
                "title": "Short ATM Call",
            },
            {
                "asset_price": spot,
                "strike_price": 105,
                "position": "long",
                "option_type": "call",
                "option_cost": 2.0,
                "title": "Long Call Wing",
            },
        ],
        "long_inverse_skip_butterfly": [
            # A Skip Butterfly omits one side of a standard butterfly
            # (e.g., Long 1, Short 2, Long 1 at different spacing)
            # Inverse Skip (Call): Short 1 Low, Long 2 Mid, Short 1 High (Skips the highest wing)
            {
                "asset_price": spot,
                "strike_price": 95,
                "position": "short",
                "option_type": "call",
                "option_cost": 8.0,
                "title": "Short Call",
            },
            {
                "asset_price": spot,
                "strike_price": 100,
                "position": "long",
                "option_type": "call",
                "option_cost": 4.5,
                "title": "Long Call x2 (Leg 1)",
            },
            {
                "asset_price": spot,
                "strike_price": 100,
                "position": "long",
                "option_type": "call",
                "option_cost": 4.5,
                "title": "Long Call x2 (Leg 2)",
            },
        ],
    }

    for name, options in advanced_strategies.items():
        print(f"\n--- Processing {name.replace('_', ' ').title()} ---")
        strategy = OptionStrategy(name, options)
        strategy.calculate_payouts()
        strategy.print_summary()
        strategy.plot_payouts(to_screen=False)  # Plots saved to 'charts/' folder


if __name__ == "__main__":
    run_advanced_strategies()
