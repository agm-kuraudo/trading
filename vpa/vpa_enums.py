from enum import Enum

class CandleType(Enum):
    LOWER_WICK=1
    HIGHER_WICK=2
    SHOOTING_STAR=3
    HAMMER=4
    LONG_LEGGED_DOJI=5
    WIDE_SPREAD=6
    NARROW_SPREAD=7
    HANGING_MAN=8

class Size(Enum):
    VERY_SMALL=1
    SMALL=2
    MEDIUM=3
    LARGE=4
    VERY_LARGE=5