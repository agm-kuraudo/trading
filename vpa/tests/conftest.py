"""Shared test scaffolding for the ``detect_signals`` regression suite (SP-307).

This module provides the builder helper *functions* used by the new
``detect_signals`` tests to construct fully-controlled inputs for
``MarketAnalyzer.detect_signals``:

- :func:`make_candle` derives OHLC values so the resulting :class:`~vpa.app.Candle`
  has exactly the requested ``up_bar``, ``spread``, ``upper_wick``, ``lower_wick``
  and pattern flags (shooting-star / hammer, avoiding an accidental long-legged
  doji unless explicitly requested).
- :func:`set_percentiles` assigns ``spread_percentiles`` *then* ``volume_percentiles``
  (order matters: the ``Candle`` volume setter reads the spread percentiles to build
  its internal anomaly map, so assigning volume first raises ``KeyError``).
- :func:`populate_windows` writes candle lists into the analyzer's name-mangled
  ``_MarketAnalyzer__deque_dictionary`` windows, respecting each deque's ``maxlen``.
- :func:`make_minimal_df` and :func:`load_spy_slice` provide the ``fixed_df`` / ADX
  data paths (reusing the idiom from ``test_rsi.py`` and ``test_alpha.py``).

The hermeticity and construction *fixtures* (``no_network``, ``null_logger``,
``analyzer_factory``, ``populated_analyzer``) are deliberately NOT implemented here
yet -- they belong to task 3.2. See the placeholder section at the end of this file.
"""

import os

import pandas as pd
import pytest

from vpa.app import Candle

# Period names shared across the deque dictionary and the percentile dictionaries.
PERIOD_NAMES = ("period_one", "period_two", "period_three")

# Path to the real config used by the analyzer construction fixtures (task 3.2).
DEFAULT_CONFIG = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "config", "config.json"))


# ---------------------------------------------------------------------------
# Builder helper functions (task 3.1)
# ---------------------------------------------------------------------------


def make_candle(
    *,
    up: bool = True,
    volume: float = 1000,
    spread: float = 1.0,
    upper_wick: float = 0.0,
    lower_wick: float = 0.0,
    time: str = "2023-01-03T00:00:00+00:00",
) -> Candle:
    """Build a :class:`~vpa.app.Candle` with exactly the requested characteristics.

    OHLC values are derived so that the constructed candle has precisely the
    requested ``up_bar``, ``spread``, ``upper_wick`` and ``lower_wick``. Recall from
    ``vpa/app.py``::

        up_bar     = close > open
        spread     = abs(close - open)
        upper_wick = high - close
        lower_wick = close - low

    Pattern flags follow directly from the wick/spread ratios the caller supplies:

    - **Shooting star** requires ``upper_wick > 2 * spread`` and ``upper_wick > 2 * lower_wick``.
    - **Hammer** requires ``lower_wick > 2 * spread`` and ``lower_wick > 2 * upper_wick``.
    - **Long-legged doji** (both wicks ``> 2 * spread``) clears the shooting-star and
      hammer flags.

    Because the flags are derived purely from the arguments, callers request a
    shooting star or hammer through the wick arguments themselves, e.g.::

        make_candle(spread=1.0, upper_wick=3.0, lower_wick=0.0)   # shooting star
        make_candle(spread=1.0, lower_wick=3.0, upper_wick=0.0)   # hammer

    With the default ``upper_wick=0.0``/``lower_wick=0.0`` a plain up/down bar is
    produced with no pattern flags, so an accidental long-legged doji is avoided
    unless a caller explicitly supplies two large wicks.

    :param up: When ``True`` the candle is an up bar (``close > open``); otherwise a
        down bar.
    :param volume: The candle volume (feeds ``identify_acc_or_dist``).
    :param spread: The absolute open-to-close spread (must be non-negative).
    :param upper_wick: ``high - close`` (must be non-negative).
    :param lower_wick: ``close - low`` (must be non-negative).
    :param time: The candle timestamp (never asserted on; determinism-neutral).
    :returns: A fully constructed :class:`~vpa.app.Candle`.
    """
    if spread < 0:
        raise ValueError("spread must be non-negative")
    if upper_wick < 0 or lower_wick < 0:
        raise ValueError("wicks must be non-negative")

    # Anchor the open at a stable, comfortably-positive base price.
    candle_open = 100.0
    if up:
        close = candle_open + spread
    else:
        close = candle_open - spread

    high = close + upper_wick
    low = close - lower_wick

    return Candle(time, volume, candle_open, high, low, close)


def set_percentiles(candle: Candle, *, spread: dict, volume: dict) -> None:
    """Assign spread percentiles then volume percentiles on ``candle``.

    Order matters: the ``Candle`` volume-percentiles setter iterates the volume
    dictionary's keys and reads the matching spread percentile to build its internal
    anomaly map, so the spread percentiles MUST be assigned first (otherwise the
    setter raises ``KeyError``). Both dictionaries should key on the three period
    names ``"period_one"`` / ``"period_two"`` / ``"period_three"``.

    :param candle: The candle to mutate.
    :param spread: Spread-percentile dict keyed by period name.
    :param volume: Volume-percentile dict keyed by period name.
    """
    candle.spread_percentiles = spread
    candle.volume_percentiles = volume


def populate_windows(analyzer, period_one, period_two, period_three) -> None:
    """Write candle lists into the analyzer's rolling windows.

    Accesses the name-mangled private ``_MarketAnalyzer__deque_dictionary`` and
    replaces the contents of each period deque. The provided candles are appended in
    order so each deque naturally honours its ``maxlen`` (the deque discards from the
    left if more candles than ``maxlen`` are supplied).

    :param analyzer: A constructed ``MarketAnalyzer`` instance.
    :param period_one: Iterable of candles for the ``period_one`` window.
    :param period_two: Iterable of candles for the ``period_two`` window.
    :param period_three: Iterable of candles for the ``period_three`` window.
    """
    deque_dictionary = analyzer._MarketAnalyzer__deque_dictionary
    for period_name, candles in (
        ("period_one", period_one),
        ("period_two", period_two),
        ("period_three", period_three),
    ):
        window = deque_dictionary[period_name]
        window.clear()
        for candle in candles:
            window.append(candle)


def make_minimal_df(rows: int = 250) -> pd.DataFrame:
    """Create a minimal OHLCV DataFrame for the ``fixed_df`` construction path.

    Mirrors the idiom used by ``vpa/tests/test_rsi.py``: a gently rising price series
    with enough rows to avoid insufficient-data warnings during analyzer construction.

    :param rows: Number of rows to generate.
    :returns: A DataFrame with ``Date, Close, High, Low, Open, Volume`` columns.
    """
    prices = [100.0 + i * 0.1 for i in range(rows)]
    return pd.DataFrame(
        {
            "Date": pd.date_range("2023-01-01", periods=rows),
            "Close": prices,
            "High": [p + 1 for p in prices],
            "Low": [p - 1 for p in prices],
            "Open": prices,
            "Volume": [1_000_000] * rows,
        }
    )


def load_spy_slice(n: int) -> pd.DataFrame:
    """Load the first ``n`` rows of ``vpa/data/spy_data.csv`` for the trend/ADX path.

    Reuses the ``test_alpha.py`` idiom: reads the CSV relative to this file and sorts
    by ``Date`` so the slice is chronological, then returns the leading ``n`` rows.

    :param n: Number of leading (chronological) rows to return.
    :returns: A DataFrame slice of ``spy_data.csv`` (including the ``Adj Close`` column).
    """
    data_path = os.path.join(os.path.dirname(__file__), "..", "data", "spy_data.csv")
    data_frame = pd.read_csv(data_path)
    data_frame = data_frame.sort_values("Date", axis=0)
    return data_frame.head(n)


# ---------------------------------------------------------------------------
# Hermeticity and construction fixtures (task 3.2)
# ---------------------------------------------------------------------------
#
# Autouse decision: ``no_network`` and ``null_logger`` are implemented as PLAIN
# (non-autouse) fixtures, and ``analyzer_factory`` depends on both. This is the
# factory-dependency approach the design prefers: any analyzer built through the
# factory is hermetic (no network, no log file), while the ~285 existing tests in
# ``vpa/tests`` that do NOT use these fixtures are left completely undisturbed.
# The new detect_signals test modules (tasks 5-10) obtain hermeticity simply by
# depending on ``analyzer_factory`` / ``populated_analyzer``; a module that wants
# the guards applied to every test can still opt in explicitly, e.g.::
#
#     pytestmark = pytest.mark.usefixtures("no_network", "null_logger")
#
# but this file does NOT force autouse, to avoid affecting unrelated tests.


class _NullLogger:
    """Lightweight stand-in for :class:`~vpa.app.DebugLog`.

    Its ``__init__`` opens NO file (the real ``DebugLog`` otherwise opens
    ``vpa/log/<prefix>_<date>.txt`` in append mode on construction), and ``log`` is
    a no-op. This keeps analyzer construction free of any log-file side effect.

    The signature of :meth:`log` mirrors the real logger (``message`` positional,
    ``level`` keyword-defaulted) so the code under test can call it unchanged.
    ``__del__`` is intentionally trivial: unlike the real ``DebugLog`` there is no
    open file handle to close, so garbage collection never fails.
    """

    def __init__(self, level="DEBUG", file_prefix="debug_log"):
        self.level = level
        self.file_prefix = file_prefix

    def log(self, message, level="DEBUG"):  # noqa: ARG002 - no-op stand-in
        return None

    def __del__(self):
        # No file handle to release; defined for parity with DebugLog.__del__.
        return None


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if any code path reaches ``yf.download`` during a test.

    Monkeypatches ``vpa.app_runner.yf.download`` (the exact use site in
    ``MarketAnalyzer.load_data``) so an accidental live-data load raises
    ``AssertionError("network access attempted")`` instead of making a request.
    This is defence-in-depth: analyzer construction through
    :func:`analyzer_factory` always supplies a ``fixed_df``, so the network path is
    never taken -- but if a future test forgets, it fails deterministically rather
    than hitting the network.

    Serves Requirements 6.6, 6.7.
    """

    def _raise_on_download(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr("vpa.app_runner.yf.download", _raise_on_download)


@pytest.fixture
def null_logger(monkeypatch):
    """Replace ``DebugLog`` at its use site with a no-file, no-op stand-in.

    Monkeypatches ``vpa.app_runner.DebugLog`` with :class:`_NullLogger`, whose
    ``__init__`` opens no file, so constructing a ``MarketAnalyzer`` never creates a
    ``vpa/log/<prefix>_<date>.txt`` artifact. Because no file is ever opened, no
    filesystem teardown is required (the design's delete-based ``try/finally``
    fallback only applies to the real-logger path, which this fixture avoids
    entirely).

    Serves Requirement 6.5.
    """
    monkeypatch.setattr("vpa.app_runner.DebugLog", _NullLogger)


@pytest.fixture
def analyzer_factory(no_network, null_logger):
    """Return a ``build(...)`` callable that constructs a hermetic ``MarketAnalyzer``.

    The returned callable has signature
    ``build(*, fixed_df=None, config_path=DEFAULT_CONFIG) -> MarketAnalyzer`` and
    always constructs the analyzer with ``ticker_symbol=None`` against the real
    ``vpa/config/config.json`` (``DEFAULT_CONFIG``), so production thresholds apply.

    Because this fixture depends on :func:`no_network` and :func:`null_logger`,
    every analyzer it builds is hermetic: no network access and no log file.

    Construction detail: the real config has ``use_real_data`` true, so building
    with ``fixed_df=None`` would drive ``load_data()`` into ``yf.download`` (which
    :func:`no_network` would turn into an ``AssertionError``). To keep the
    ``fixed_df=None`` path hermetic, the factory substitutes a
    :func:`make_minimal_df` DataFrame for construction; callers then populate the
    rolling windows directly via :func:`populate_windows`. When a caller supplies an
    explicit ``fixed_df`` (e.g. a :func:`load_spy_slice` for the ADX path), that
    DataFrame is used verbatim.

    Serves Requirements 6.1, 6.4, 6.6, 6.7.

    :returns: A callable building a fully-constructed ``MarketAnalyzer``.
    """
    # Imported lazily so the monkeypatches applied by no_network / null_logger are
    # in force before MarketAnalyzer is referenced.
    from vpa.app_runner import MarketAnalyzer

    def build(*, fixed_df=None, config_path=DEFAULT_CONFIG) -> "MarketAnalyzer":
        # A None fixed_df still constructs from a DataFrame (never the network); the
        # caller replaces the window contents afterwards via populate_windows.
        construction_df = make_minimal_df() if fixed_df is None else fixed_df
        return MarketAnalyzer(
            config_path=config_path,
            ticker_symbol=None,
            fixed_df=construction_df,
        )

    return build


def make_neutral_window_candle(index: int = 0) -> Candle:
    """Build an ADX-safe neutral baseline candle for the rolling windows.

    The shared ``populated_analyzer`` baseline used to fill its windows with perfectly
    flat candles (``open=100, close=101, high=101, low=101`` -> zero high-low range).
    ``detect_signals`` calls ``calculate_adx(period_three)``, which divides by the
    smoothed true range; a window of identical flat candles makes that range zero and
    raises ``ZeroDivisionError``. This helper gives each candle a genuine non-zero
    high-low range and a base price that steps up with ``index`` so the true range
    stays positive and the trend block runs to completion.

    Geometry (with an alternating one-point ``base``)::

        base  = 100 + (1 if index is odd else 0)
        open  = base
        close = base + 1.0        # up bar, spread 1.0
        high  = close + 0.25      # upper_wick 0.25
        low   = open - 0.25       # lower_wick 1.25

    Both wicks stay well under ``2 * spread`` (2.0), so no shooting star / hammer /
    long-legged-doji flag fires. The base steps up by one on odd indices and back
    down on even indices, so successive candles carry a genuine non-zero high-low
    range (no divide-by-zero in ADX) while the directional movement alternates and
    roughly cancels across the window -- keeping ``calculate_adx`` well below the
    trending threshold (25), so the trend block contributes nothing for the baseline.
    Each candle carries mid-range percentile buckets (``50``) for spread then volume
    across all three period keys, below the strict boundary edges the tests probe.

    :param index: Window position; its parity picks a one-point up/down step so the
        series gently zig-zags rather than sitting flat or trending.
    :returns: A neutral, ADX-safe :class:`~vpa.app.Candle`.
    """
    base = 100.0 + (index % 2)
    candle = Candle(
        "2023-01-03T00:00:00+00:00",
        1000,
        base,  # open
        base + 1.0 + 0.25,  # high = close + 0.25
        base - 0.25,  # low = open - 0.25
        base + 1.0,  # close
    )
    set_percentiles(
        candle,
        spread=dict.fromkeys(PERIOD_NAMES, 50),
        volume=dict.fromkeys(PERIOD_NAMES, 50),
    )
    return candle


@pytest.fixture
def populated_analyzer(analyzer_factory):
    """Return an analyzer whose three windows hold a neutral baseline candle set.

    Each period window is filled to its ``maxlen`` with the ADX-safe neutral up bars
    produced by :func:`make_neutral_window_candle`: a small positive spread, wicks
    that never trip a pattern flag, and mid-range percentile buckets (``50``) for both
    spread and volume across all three period keys. Unlike the previous flat baseline
    (identical candles with a zero high-low range, which made ``calculate_adx`` divide
    by zero inside the trend block), each candle here has a genuine non-zero range and
    a base price that gently zig-zags by one point with its window index, so
    ``detect_signals`` runs end to end without a ``ZeroDivisionError`` while the mild
    alternating step keeps ADX below the trending threshold (25) so the trend block
    stays silent. The baseline still
    triggers none of the boundary-sensitive signals (percentile buckets sit at ``50``,
    below the strict ``> 70`` / ``> 65`` / ``< 50`` edges), so individual tests can
    override just the candles or percentiles they care about.

    Serves Requirement 6.1 (construction basis for the regression tests).

    :returns: A ``MarketAnalyzer`` with pre-populated, neutral rolling windows.
    """
    analyzer = analyzer_factory()

    deque_dictionary = analyzer._MarketAnalyzer__deque_dictionary
    period_one = [make_neutral_window_candle(i) for i in range(deque_dictionary["period_one"].maxlen)]
    period_two = [make_neutral_window_candle(i) for i in range(deque_dictionary["period_two"].maxlen)]
    period_three = [make_neutral_window_candle(i) for i in range(deque_dictionary["period_three"].maxlen)]

    populate_windows(analyzer, period_one, period_two, period_three)
    return analyzer
