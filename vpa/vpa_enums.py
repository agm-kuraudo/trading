from enum import Enum


# Candle characteristics to track
class CandleType(Enum):
    LOWER_WICK = 1
    HIGHER_WICK = 2
    SHOOTING_STAR = 3
    HAMMER = 4
    LONG_LEGGED_DOJI = 5
    WIDE_SPREAD = 6  # This is already covered by the relative spread elements
    NARROW_SPREAD = 7  # As above
    HANGING_MAN = 8  # This is just a hammer but in an uptrend. can't ascertain on a single candle level
    ANOMALY_HIGH_VOLUME = 9
    ANOMALY_HIGH_SPREAD = 10


# Relative size indicator for volume and spread
class Size(Enum):
    VERY_SMALL = 1
    SMALL = 2
    MEDIUM = 3
    LARGE = 4
    VERY_LARGE = 5


# Which dequeue/lookback period to use
class HistoryPeriod(Enum):
    SHORT = 1
    MEDIUM = 2
    LONG = 3


# Which security data are we interested in
class SecurityData(Enum):
    VOLUME = 1
    OPEN = 2
    CLOSE = 3
    LOW = 4
    HIGH = 5
    SPREAD = 6
    HIGH_LOW_SPREAD = 7
