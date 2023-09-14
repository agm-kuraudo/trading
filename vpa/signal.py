class MySignal:
    def __init__(self):
        pass

    @staticmethod
    def calculate_signal(curr_candle, candle_history):

        signal = {"STRENGTH": 0, "Direction": "None"}

        if curr_candle.is_shooting_star():
            signal["STRENGTH"] += 5
            signal["Direction"] = "SHORT"
            print("SHOOTING STAR: " + curr_candle.time)

        if curr_candle.is_hammer():
            signal["STRENGTH"] += 5
            signal["Direction"] = "LONG"
            print("HAMMER: " + curr_candle.time)

        if curr_candle.is_long_legged_doji():
            signal["STRENGTH"] += 5
            print("LONG LEGGED DOJI: " + curr_candle.time)

        # TODO: First this first attempt I am making the quick and probably wrong assumption that anomaly's here make
        #  the signal stronger
        for value in curr_candle.spread_anomaly:
            if value:
                signal["STRENGTH"] += 5

        for value in curr_candle.volume_anomaly:
            if value:
                signal["STRENGTH"] += 5

        return signal
