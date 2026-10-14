"""Tests for the recent-extreme additions to the default variation catalogue (SP-354, task 10.1).

Covers the twelve recent-extreme ``StrategyVariation`` records appended to
``build_default_variations()`` in task 10, plus the ``_include_long`` /
``_include_short`` direction filters:

- Catalogue ordering (Req 10.4): the leading slice of the catalogue still equals
  the known pre-SP-354 variation names, in order — presence and ordering of the
  existing variations are preserved, with the recent-extreme variations added
  after them.
- Sweep coverage (Req 11.1, 11.5): all twelve
  ``Recent_Extreme_{Long,Short}_R{r}_LB{lb}`` names (reward in {1,2,3}, lookback
  in {5,10}, both directions) are present.
- Factory configuration (Req 11.2, 11.3): each new variation's
  ``exit_strategy_factory()`` builds a ``RecentExtremeExitStrategy`` with the
  expected ``lookback``, ``reward_risk``, ``buffer == 0.0``, and ``direction``.
- Slug uniqueness (Req 11.5): every ``reporting.variation_filename`` slug (both
  "trades" and "equity") is unique across the whole catalogue, so no CSV
  collisions are introduced.
- Direction filters (Decision 3, Req 11.2): ``_include_long`` admits only UP
  signals and ``_include_short`` admits only DOWN signals.

Code under test: ``vpa/backtesting/variations.py`` and
``vpa/backtesting/reporting.py``.

Requirements: 10.1, 10.3, 10.4, 11.1, 11.2, 11.3, 11.4, 11.5
"""

import datetime as dt

from vpa.backtesting import reporting
from vpa.backtesting.exit_strategy import RecentExtremeExitStrategy
from vpa.backtesting.models import SignalEntry
from vpa.backtesting.variations import (
    _include_long,
    _include_short,
    build_default_variations,
)
from vpa.ml_validation.signal_analysis import (
    SIGNAL_DIRECTIONS,
    SignalDirection,
    SignalType,
)

_BASE_DATE = dt.date(2020, 1, 1)

# The known pre-SP-354 catalogue, in build order. The recent-extreme sweep is
# appended AFTER these, so this list must remain the leading slice of the
# catalogue names (Req 10.4).
_PRE_SP354_NAMES: tuple[str, ...] = (
    "Baseline",
    "Contrarian_Only",
    "All_Signals",
    "Variable_Hold_5",
    "Variable_Hold_10",
    "Variable_Hold_15",
    "Variable_Hold_20",
    "Stop_Loss_-2pct",
    "Stop_Loss_-3pct",
    "Signal_Stacking",
    "DSS_Bressert_Only",
    "Combo_DSS_Cross_SMA_Position",
    "Combo_DSS_Cross_SMA_Cross",
    "Combo_DSS_Zone_SMA_Cross",
    "Combo_DSS_Cross_From_Zone",
    "Combo_DSS_Cross_SMA_Not_Overbought",
)

# The twelve expected recent-extreme names and their (lookback, reward, direction).
_EXPECTED_RECENT_EXTREME: dict[str, tuple[int, int, SignalDirection]] = {
    f"Recent_Extreme_{'Long' if d is SignalDirection.UP else 'Short'}_R{r}_LB{lb}": (lb, r, d)
    for r in (1, 2, 3)
    for lb in (5, 10)
    for d in (SignalDirection.UP, SignalDirection.DOWN)
}


def _iso(index: int) -> str:
    """Return a unique ascending ISO date string for positional ``index``."""
    return (_BASE_DATE + dt.timedelta(days=index)).isoformat()


def _signal(signal_type: SignalType) -> SignalEntry:
    """Build a SignalEntry using SIGNAL_DIRECTIONS for the direction."""
    return SignalEntry(
        date=_iso(1),
        signal_type=signal_type,
        direction=SIGNAL_DIRECTIONS[signal_type],
    )


# ---------------------------------------------------------------------------
# Catalogue ordering and presence (Req 10.4, 11.1, 11.5)
# ---------------------------------------------------------------------------


def test_existing_variations_remain_the_leading_slice_in_order() -> None:
    """The pre-SP-354 variations still lead the catalogue, unchanged in order (Req 10.4)."""
    names = [v.name for v in build_default_variations()]
    leading = names[: len(_PRE_SP354_NAMES)]
    assert tuple(leading) == _PRE_SP354_NAMES


def test_all_twelve_recent_extreme_variations_are_present() -> None:
    """All twelve Recent_Extreme_{Long,Short}_R{r}_LB{lb} names are present (Req 11.1, 11.5)."""
    names = {v.name for v in build_default_variations()}
    assert len(_EXPECTED_RECENT_EXTREME) == 12
    missing = set(_EXPECTED_RECENT_EXTREME) - names
    assert not missing, f"missing recent-extreme variations: {sorted(missing)}"


def test_catalogue_has_exactly_the_existing_plus_twelve_recent_extreme() -> None:
    """The catalogue is the existing variations plus the twelve recent-extreme ones (Req 10.4, 11.1)."""
    names = [v.name for v in build_default_variations()]
    assert len(names) == len(_PRE_SP354_NAMES) + 12


# ---------------------------------------------------------------------------
# Factory configuration (Req 11.2, 11.3)
# ---------------------------------------------------------------------------


def test_recent_extreme_factories_build_configured_strategies() -> None:
    """Each new factory builds a RecentExtremeExitStrategy with expected params (Req 11.2, 11.3)."""
    by_name = {v.name: v for v in build_default_variations()}

    for name, (lookback, reward, direction) in _EXPECTED_RECENT_EXTREME.items():
        variation = by_name[name]
        strategy = variation.exit_strategy_factory()

        assert isinstance(strategy, RecentExtremeExitStrategy)
        assert strategy.lookback == lookback
        assert strategy.reward_risk == reward
        assert strategy.buffer == 0.0  # Req 11.3
        assert strategy.direction is direction  # Req 11.2


def test_recent_extreme_factories_bind_params_without_late_binding() -> None:
    """Default-arg binding gives each factory its own params (no loop late-binding) (Req 11.2)."""
    by_name = {v.name: v for v in build_default_variations()}
    # Two variations that differ in every bound param must not collapse together.
    long_r1_lb5 = by_name["Recent_Extreme_Long_R1_LB5"].exit_strategy_factory()
    short_r3_lb10 = by_name["Recent_Extreme_Short_R3_LB10"].exit_strategy_factory()

    assert (long_r1_lb5.lookback, long_r1_lb5.reward_risk, long_r1_lb5.direction) == (
        5,
        1,
        SignalDirection.UP,
    )
    assert (short_r3_lb10.lookback, short_r3_lb10.reward_risk, short_r3_lb10.direction) == (
        10,
        3,
        SignalDirection.DOWN,
    )


# ---------------------------------------------------------------------------
# Slug uniqueness across the whole catalogue (Req 11.5)
# ---------------------------------------------------------------------------


def test_variation_filename_slugs_are_unique_across_catalogue() -> None:
    """All trades/equity CSV slugs are unique across the whole catalogue (Req 11.5)."""
    slugs: list[str] = []
    for variation in build_default_variations():
        slugs.append(reporting.variation_filename(variation.name, "trades"))
        slugs.append(reporting.variation_filename(variation.name, "equity"))

    assert len(slugs) == len(set(slugs)), "duplicate CSV slugs introduced"


# ---------------------------------------------------------------------------
# Direction filters (Decision 3, Req 11.2)
# ---------------------------------------------------------------------------


def test_include_long_admits_only_up_signals() -> None:
    """_include_long admits exactly the UP signal types (Req 11.2)."""
    for signal_type in SignalType:
        expected = SIGNAL_DIRECTIONS.get(signal_type) is SignalDirection.UP
        assert _include_long(_signal(signal_type)) is expected


def test_include_short_admits_only_down_signals() -> None:
    """_include_short admits exactly the DOWN signal types (Req 11.2)."""
    for signal_type in SignalType:
        expected = SIGNAL_DIRECTIONS.get(signal_type) is SignalDirection.DOWN
        assert _include_short(_signal(signal_type)) is expected


def test_recent_extreme_variations_carry_direction_matched_filters() -> None:
    """Long variations use _include_long, short variations use _include_short (Decision 3)."""
    by_name = {v.name: v for v in build_default_variations()}
    for name, (_lb, _r, direction) in _EXPECTED_RECENT_EXTREME.items():
        variation = by_name[name]
        expected_filter = _include_long if direction is SignalDirection.UP else _include_short
        assert variation.signal_filter is expected_filter
