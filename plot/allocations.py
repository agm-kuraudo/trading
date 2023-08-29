import numpy as np

odds = [2.12, 4.3, 3.6]

working_allcations = []
best_allocation = []

winmargin = 0
biggest_win = 0

for i in range(2000000):
    my_bets = np.random.randint(low=1, high=2500, size=3)

    starting_cash = my_bets.sum()

    outcome1 = my_bets[0] * odds[0]
    outcome2 = my_bets[1] * odds[1]
    outcome3 = my_bets[2] * odds[2]

    if (outcome1 > starting_cash) and (outcome2 > starting_cash) and (outcome3 > starting_cash):
        working_allcations.append(my_bets)
        winmargin = (outcome1 + outcome2 + outcome3) - (starting_cash * 3)
        if winmargin > biggest_win:
            biggest_win = winmargin
            best_allocation = None
            best_allocation = my_bets

print(working_allcations)
print()
print(best_allocation)
print(biggest_win)

