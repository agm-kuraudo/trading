from options_payoffs import OptionStrategy

spot = 100.0

updated_ratio_strategies = {
    # ============================================================
    # 1) CALL BACKSPREAD  (Bullish, long vol, long convexity)
    # Example: Short 1 ATM call, Long 2 OTM calls
    # ============================================================
    "call_backspread": [
        {"asset_price": spot, "strike_price": 100, "position": 'short', "option_type": 'call',
         "option_cost": 5.0, "quantity": 1, "title": "Short 100C"},
        {"asset_price": spot, "strike_price": 105, "position": 'long',  "option_type": 'call',
         "option_cost": 3.0, "quantity": 2, "title": "Long 105C x2"},
    ],

    # ============================================================
    # 2) PUT BACKSPREAD  (Bearish, long vol, long convexity)
    # Example: Short 1 ATM put, Long 2 OTM puts
    # ============================================================
    "put_backspread": [
        {"asset_price": spot, "strike_price": 100, "position": 'short', "option_type": 'put',
         "option_cost": 5.2, "quantity": 1, "title": "Short 100P"},
        {"asset_price": spot, "strike_price": 95, "position": 'long',  "option_type": 'put',
         "option_cost": 2.8, "quantity": 2, "title": "Long 95P x2"},
    ],

    # ============================================================
    # 3) CALL FRONT SPREAD (Bearish/neutral, short vol)
    # Example: Long 1 ATM call, Short 2 OTM calls
    # ============================================================
    "call_frontspread": [
        {"asset_price": spot, "strike_price": 100, "position": 'long', "option_type": 'call',
         "option_cost": 5.0, "quantity": 1, "title": "Long 100C"},
        {"asset_price": spot, "strike_price": 105, "position": 'short', "option_type": 'call',
         "option_cost": 3.0, "quantity": 2, "title": "Short 105C x2"},
    ],

    # ============================================================
    # 4) PUT FRONT SPREAD (Bullish/neutral, short vol)
    # Example: Long 1 ATM put, Short 2 OTM puts
    # ============================================================
    "put_frontspread": [
        {"asset_price": spot, "strike_price": 100, "position": 'long', "option_type": 'put',
         "option_cost": 5.2, "quantity": 1, "title": "Long 100P"},
        {"asset_price": spot, "strike_price": 95, "position": 'short', "option_type": 'put',
         "option_cost": 2.8, "quantity": 2, "title": "Short 95P x2"},
    ],
}

for name, options in updated_ratio_strategies.items():
    print(f"\n--- Processing {name.replace('_', ' ').title()} ---")
    strategy = OptionStrategy(name, options)
    strategy.calculate_payouts()
    strategy.print_summary()
    strategy.plot_payouts(to_screen=False)  # Plots saved to 'charts/' folder