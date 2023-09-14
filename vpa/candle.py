from typing import List

from vpa_enums import CandleType, Size


class Candle:
    # Class variables for relative values - these could/should maybe start blank
    relative_spread_boundary = {"SHORT": [293.4, 468.0, 759.0, 806.0, 834.2],
                                "MEDIUM": [126.7, 182.5, 557.5, 829.5, 1026.4],
                                "LARGE": [93.4, 213.0, 377.5, 721.0, 1016.8]}

    relative_volume_boundary = {"SHORT": [231718., 236627.5, 244810., 253047., 257989.2],
                                "MEDIUM": [223357.5, 229034., 238311., 257165.5, 265355.7],
                                "LARGE": [226893.7, 243349., 275653., 301675., 312982.6]}

    relative_high_low_spread_boundary = {"SHORT": [293.4, 468.0, 759.0, 806.0, 834.2],
                                         "MEDIUM": [126.7, 182.5, 557.5, 829.5, 1026.4],
                                         "LARGE": [93.4, 213.0, 377.5, 721.0, 1016.8]}

    def __init__(self, time, volume, candle_open, high, low, close):
        self.__volume = volume
        self.__open = candle_open
        self.__high = high
        self.__low = low
        self.__close = close
        self.__time = time
        self.__notes = []

        self.__up_bar = close > candle_open
        self.__spread = abs(close - candle_open)
        self.__high_low_spread = high - low
        self.__high_open_spread = high - candle_open
        self.__low_close_spread = low - close
        self.__high_close_spread = high - close

        self.__relative_volume = self.set_relative_size(self.__volume, Candle.relative_volume_boundary)
        self.__relative_spread = self.set_relative_size(self.__spread, Candle.relative_spread_boundary)
        self.__relative_high_low_spread = self.set_relative_size(abs(self.__high_low_spread),
                                                                 Candle.relative_high_low_spread_boundary)

        self.__volume_anomaly = self.set_volume_anomaly_flags()
        self.__spread_anomaly = self.set_spread_anomaly_flags()

        if self.is_lower_wick():
            self.__notes.append(CandleType.LOWER_WICK)

        if self.is_higher_wick():
            self.__notes.append(CandleType.HIGHER_WICK)

        if self.is_shooting_star():
            self.__notes.append(CandleType.SHOOTING_STAR)

        if self.is_hammer():
            self.__notes.append(CandleType.SHOOTING_STAR)

        if self.is_long_legged_doji():
            self.__notes.append(CandleType.LONG_LEGGED_DOJI)

    def set_volume_anomaly_flags(self) -> List[bool]:
        return_value = []

        for i in range(3):
            return_value.append((self.relative_high_low_spread[i].value - 1) > self.relative_volume[i].value)

        return return_value

    def set_spread_anomaly_flags(self) -> List[bool]:
        return_value = []

        for i in range(3):
            return_value.append((self.relative_volume[i].value - 1) > self.relative_high_low_spread[i].value)

        return return_value

    def is_shooting_star(self):
        # Bar must be an up bar
        if not self.up_bar:
            return False
        # the gap between the high and open must be 2x as large as the "body"
        if abs(self.high_open_spread) < (self.__spread * 2):
            return False

        # Small "tail" - bit of subjective guess work here
        if abs(self.low_close_spread) > (abs(self.high_open_spread) / 2):
            return False

        return True

    def is_hammer(self):
        # There needs to be a tail - so low - close should be negative
        if self.low_close_spread > 0:
            return False

        # The tail should be twice as long as the body
        if abs(self.low_close_spread) < (self.spread * 2):
            return False

        # I guess there shouldn't be a large high/close spread as well for this to be a hammer
        if self.high_open_spread > self.spread:
            return False

        return True

    def is_long_legged_doji(self):
        # There needs to be a tail - so low - close should be negative - TODO: This is repeated code
        if self.low_close_spread > 0:
            return False

        # There needs to be na upbit, so high close spread should be positive
        if self.high_close_spread <= 0:
            return False

        # the gap between the high and close must be 2x as large as the "body"
        if abs(self.high_close_spread) < (self.__spread * 2):
            return False

        # The tail should be twice as long as the body TODO: This is repeated code
        if abs(self.low_close_spread) < (self.spread * 2):
            return False

        return True

    def is_lower_wick(self):
        return self.__low < self.__close

    def is_higher_wick(self):
        return self.__high > self.__close

    @staticmethod
    def set_relative_size(value, relative_boundaries):
        return_value = []
        my_time_periods = ["SHORT", "MEDIUM", "LARGE"]

        for time in my_time_periods:
            if value < relative_boundaries[time][0]:
                return_value.append(Size.VERY_SMALL)
            elif value < relative_boundaries[time][1]:
                return_value.append(Size.SMALL)
            elif value < relative_boundaries[time][2]:
                return_value.append(Size.MEDIUM)
            elif value < relative_boundaries[time][3]:
                return_value.append(Size.LARGE)
            else:
                return_value.append(Size.VERY_LARGE)

        return return_value

    # "To String" stuff
    def __str__(self) -> str:
        if self.__up_bar:
            bar_type = "up_bar"
        else:
            bar_type = "down_bar"
        return "Candle is an {} opened at {} and closed at {}".format(bar_type, self.__open, self.__close)

    # Simple "Getters section"

    @property
    def open(self):
        return self.__open

    @property
    def volume(self):
        return self.__volume

    @property
    def high(self):
        return self.__high

    @property
    def low(self):
        return self.__low

    @property
    def up_bar(self):
        return self.__up_bar

    @property
    def spread(self):
        return self.__spread

    @property
    def high_low_spread(self):
        return self.__high_low_spread

    @property
    def high_open_spread(self):
        return self.__high_open_spread

    @property
    def low_close_spread(self):
        return self.__low_close_spread

    @property
    def high_close_spread(self):
        return self.__high_close_spread

    @property
    def notes(self):
        return self.__notes

    @property
    def relative_volume(self):
        return self.__relative_volume

    @property
    def relative_spread(self):
        return self.__relative_spread

    @property
    def volume_anomaly(self):
        return self.__volume_anomaly

    @property
    def spread_anomaly(self):
        return self.__spread_anomaly

    @property
    def relative_high_low_spread(self):
        return self.__relative_high_low_spread

    @property
    def time(self):
        return self.__time
