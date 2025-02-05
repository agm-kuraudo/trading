#INPUTS/CONSTANTS
#GENERAL
TRADING_DAYS = 252
PRICING_STEPS = 100
INTEREST_RATE = 0.04 #This is as percent so 4% is 0.04

#SHARE/OPTION SPECIFIC
OPTION_EXPIRATION_DATE = '2025-07-10'
DIVIDEND_YIELD = 0.03


# 1 Get Live Data Function
    # Copy from alpha app_runner - maybe move to utils file
#2 Read CSV function - as above

#3 Order DataFrame by Date DESC - Newest First
#4 Add a new column that contains difference between close prices
#5 New column (or update previous) that has log value of the difference
#6 Standard Deviation of all values in Column from #5 divided by SQRT of _TRADING_DAYS
# This gives us the Historic Volatility

#7 Up Branch Move Calculation
    #7.1 Work out the period left on options as a Percentage of Year (_TRADING_DAYS)
        # 7.1.1 How many trading days left before option expires
        # 7.1.2 Divide #7.1.1 by 252
    #7.2 Divide #7.1 by _PRICING_STEPS
    #7.3 Square Root of that Value
    #7.4 Times #7.3 by Volatility

#8 Down Branch Calculation - 1 (literal) / #7

#9 Up Branch Probability
    #9.1 Steps as  Percentage of the year - re-use #7.2
    #9.2 Factor Step Discount
        # 9.2.1 -1 * INTEREST_RATE * Steps as Percentage of the year(#9.1)
        # 9.2.2 - EXP of above #9.2.1
    #9.3 Interest Rate as Cost of Step
        # 9.3.1 - INTEREST_RATE - DIVIDEND_YIELD
        # 9.3.2 - #9.3.1 * #9.1
        # 9.3.3 - EXP of above
    #9.4 Return Up Branch Probability
        #9.4.1 - #9.3 * #9.1
        #9.4.2 - #9.4.1 / (#7 - #8)

#10 Down Branch Probability -  1 (literal) - #9


