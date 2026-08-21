"""Property-based and unit tests for the Momentum/Drawdown Filter.

Tests cover:
- Property 1: Insufficient data exclusion (evaluate_ticker returns None for < 252 rows)
- Property 2: 52-week high correctness (equals max of last 252 entries)
- Property 3: Drawdown formula correctness
- Property 4: Momentum formula correctness
- Property 5: Momentum insufficient data exclusion
- Property 6: Filter predicate correctness
- Property 7: Report contains all required fields (ticker, drawdown%, momentum)
- Property 8: Report sorted by drawdown ascending (most negative first)

Requirements: 1.2, 2.1, 2.2, 2.3, 3.1, 3.2, 4.1, 5.1, 5.2
"""

import logging
import re

import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from vpa.opportunities import (
    compute_52_week_high,
    compute_drawdown_percentage,
    compute_momentum,
    evaluate_ticker,
    format_disabled_report,
    format_opportunities_report,
    load_drawdown_config,
)

# ---------------------------------------------------------------------------
# Strategies — Core calculations (Properties 1–6)
# ---------------------------------------------------------------------------

# Random close prices between 1.0 and 1000.0
close_price_strategy = st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False)

# DataFrame with insufficient data (< 252 rows) for Property 1
insufficient_df_strategy = st.integers(min_value=1, max_value=251).flatmap(
    lambda n: st.lists(
        close_price_strategy,
        min_size=n,
        max_size=n,
    ).map(lambda closes: pd.DataFrame({"Close": closes}))
)

# Series with sufficient data (>= 252 entries) for Property 2
sufficient_series_strategy = st.integers(min_value=252, max_value=400).flatmap(
    lambda n: st.lists(
        close_price_strategy,
        min_size=n,
        max_size=n,
    ).map(lambda closes: pd.Series(closes))
)

# DataFrame with sufficient data (>= 252 rows) for Properties 5 and 6
sufficient_df_strategy = st.integers(min_value=252, max_value=400).flatmap(
    lambda n: st.lists(
        close_price_strategy,
        min_size=n,
        max_size=n,
    ).map(lambda closes: pd.DataFrame({"Close": closes}))
)


# ---------------------------------------------------------------------------
# Strategies — Report formatting (Properties 7–8)
# ---------------------------------------------------------------------------

ticker_strategy = st.text(
    alphabet=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    min_size=3,
    max_size=5,
)

opportunity_strategy = st.fixed_dictionaries(
    {
        "ticker": ticker_strategy,
        "drawdown_pct": st.floats(min_value=-99.0, max_value=-0.1, allow_nan=False, allow_infinity=False),
        "momentum": st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False),
    }
)

opportunities_list_strategy = st.lists(
    opportunity_strategy,
    min_size=1,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Property Tests — Core Calculations (Properties 1–6)
# ---------------------------------------------------------------------------


class TestInsufficientDataExclusion:
    """Property 1: Insufficient data exclusion.

    For any DataFrame with fewer than 252 rows, evaluate_ticker() SHALL return
    None, regardless of the closing price values or filter configuration.

    Feature: momentum-drawdown-filter, Property 1: Insufficient data exclusion
    **Validates: Requirements 1.2**
    """

    @given(df=insufficient_df_strategy)
    @settings(max_examples=100, deadline=None)
    def test_evaluate_ticker_returns_none_for_insufficient_data(self, df):
        """evaluate_ticker always returns None when DataFrame has < 252 rows."""
        result = evaluate_ticker(df)
        assert result is None, f"Expected None for DataFrame with {len(df)} rows, got {result}"


class TestFiftyTwoWeekHighCorrectness:
    """Property 2: 52-week high correctness.

    For any Series of closing prices with at least 252 entries,
    compute_52_week_high(closes, 252) SHALL return a value equal to
    max(closes[-252:]).

    Feature: momentum-drawdown-filter, Property 2: 52-week high correctness
    **Validates: Requirements 2.1, 2.3**
    """

    @given(closes=sufficient_series_strategy)
    @settings(max_examples=100, deadline=None)
    def test_52_week_high_equals_max_of_last_252(self, closes):
        """compute_52_week_high returns the maximum of the last 252 entries."""
        result = compute_52_week_high(closes, 252)
        expected = float(closes.iloc[-252:].max())

        assert result is not None
        assert abs(result - expected) < 1e-10, f"Expected {expected}, got {result}"


class TestDrawdownFormulaCorrectness:
    """Property 3: Drawdown formula correctness.

    For any pair of (current_close, fifty_two_week_high) where
    fifty_two_week_high > 0, compute_drawdown_percentage() SHALL return
    ((current_close - fifty_two_week_high) / fifty_two_week_high) * 100.

    Feature: momentum-drawdown-filter, Property 3: Drawdown formula correctness
    **Validates: Requirements 2.2**
    """

    @given(
        current_close=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        fifty_two_week_high=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_drawdown_formula(self, current_close, fifty_two_week_high):
        """compute_drawdown_percentage matches the mathematical formula."""
        result = compute_drawdown_percentage(current_close, fifty_two_week_high)
        expected = ((current_close - fifty_two_week_high) / fifty_two_week_high) * 100

        assert abs(result - expected) < 1e-10, (
            f"Expected {expected}, got {result} for " f"current_close={current_close}, high={fifty_two_week_high}"
        )


class TestMomentumFormulaCorrectness:
    """Property 4: Momentum formula correctness.

    For any Series of closing prices with at least period + 1 entries and where
    closes[-period - 1] > 0, compute_momentum() SHALL return
    ((closes[-1] - closes[-period - 1]) / closes[-period - 1]) * 100.

    Feature: momentum-drawdown-filter, Property 4: Momentum formula correctness
    **Validates: Requirements 3.1**
    """

    @given(
        period=st.integers(min_value=1, max_value=50),
        data=st.data(),
    )
    @settings(max_examples=100, deadline=None)
    def test_momentum_formula(self, period, data):
        """compute_momentum matches the mathematical formula."""
        length = data.draw(st.integers(min_value=period + 1, max_value=period + 100))
        prices = data.draw(
            st.lists(
                close_price_strategy,
                min_size=length,
                max_size=length,
            )
        )
        closes = pd.Series(prices)

        # Ensure close N days ago is not zero (strategy min_value=1.0 handles this)
        assume(closes.iloc[-period - 1] != 0)

        result = compute_momentum(closes, period)
        expected = ((closes.iloc[-1] - closes.iloc[-period - 1]) / closes.iloc[-period - 1]) * 100

        assert result is not None
        assert abs(result - expected) < 1e-10, f"Expected {expected}, got {result} for period={period}"


class TestMomentumInsufficientDataExclusion:
    """Property 5: Momentum insufficient data exclusion.

    For any Series with fewer than period + 1 entries, compute_momentum()
    SHALL return None.

    Feature: momentum-drawdown-filter, Property 5: Momentum insufficient data exclusion
    **Validates: Requirements 3.2**
    """

    @given(
        period=st.integers(min_value=1, max_value=50),
        data=st.data(),
    )
    @settings(max_examples=100, deadline=None)
    def test_momentum_returns_none_for_insufficient_data(self, period, data):
        """compute_momentum returns None when series has fewer than period + 1 entries."""
        # Generate a series that is too short for the given period
        length = data.draw(st.integers(min_value=1, max_value=period))
        prices = data.draw(
            st.lists(
                close_price_strategy,
                min_size=length,
                max_size=length,
            )
        )
        closes = pd.Series(prices)

        result = compute_momentum(closes, period)
        assert result is None, f"Expected None for series with {len(closes)} entries and period={period}, got {result}"


class TestFilterPredicateCorrectness:
    """Property 6: Filter predicate correctness.

    For any DataFrame producing a valid drawdown_pct and momentum,
    evaluate_ticker() SHALL return a non-None result if and only if
    drawdown_pct <= -drawdown_threshold AND momentum > 0.

    Feature: momentum-drawdown-filter, Property 6: Filter predicate correctness
    **Validates: Requirements 4.1**
    """

    @given(
        df=sufficient_df_strategy,
        drawdown_threshold=st.floats(min_value=1.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        momentum_period=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100, deadline=None)
    def test_filter_predicate(self, df, drawdown_threshold, momentum_period):
        """evaluate_ticker returns non-None iff drawdown <= -threshold AND momentum > 0."""
        # Ensure we have enough data for momentum after the 252-day warm-up
        assume(len(df) >= 252 + momentum_period + 1)

        closes = df["Close"]

        # Compute expected values manually
        fifty_two_week_high = float(closes.iloc[-252:].max())
        current_close = float(closes.iloc[-1])
        drawdown_pct = ((current_close - fifty_two_week_high) / fifty_two_week_high) * 100

        close_n_days_ago = float(closes.iloc[-momentum_period - 1])
        assume(close_n_days_ago != 0)
        momentum = ((current_close - close_n_days_ago) / close_n_days_ago) * 100

        # Determine expected outcome
        should_qualify = (drawdown_pct <= -drawdown_threshold) and (momentum > 0)

        result = evaluate_ticker(df, drawdown_threshold=drawdown_threshold, momentum_period=momentum_period)

        if should_qualify:
            assert result is not None, (
                f"Expected non-None result: drawdown_pct={drawdown_pct:.2f} "
                f"(threshold={drawdown_threshold}), momentum={momentum:.2f}"
            )
            assert abs(result["drawdown_pct"] - drawdown_pct) < 1e-10
            assert abs(result["momentum"] - momentum) < 1e-10
        else:
            assert result is None, (
                f"Expected None: drawdown_pct={drawdown_pct:.2f} "
                f"(threshold={drawdown_threshold}), momentum={momentum:.2f}"
            )


# ---------------------------------------------------------------------------
# Property Tests — Report Formatting (Properties 7–8)
# ---------------------------------------------------------------------------


class TestReportContainsAllFields:
    """Property 7: Report contains all required fields.

    For any non-empty opportunity list, output contains every ticker name,
    drawdown percentage, and momentum value.

    Feature: momentum-drawdown-filter, Property 7: Report contains all required fields
    **Validates: Requirements 5.1**
    """

    @given(opportunities=opportunities_list_strategy)
    @settings(max_examples=100, deadline=None)
    def test_report_contains_every_ticker(self, opportunities):
        """Every ticker name from the input appears in the formatted output."""
        report = format_opportunities_report(opportunities)

        for opp in opportunities:
            assert opp["ticker"] in report, f"Ticker '{opp['ticker']}' not found in report output"

    @given(opportunities=opportunities_list_strategy)
    @settings(max_examples=100, deadline=None)
    def test_report_contains_drawdown_values(self, opportunities):
        """Every drawdown percentage (formatted to 1 decimal place) appears in the output."""
        report = format_opportunities_report(opportunities)

        for opp in opportunities:
            formatted_drawdown = f"{opp['drawdown_pct']:.1f}"
            assert formatted_drawdown in report, f"Drawdown value '{formatted_drawdown}' not found in report output"

    @given(opportunities=opportunities_list_strategy)
    @settings(max_examples=100, deadline=None)
    def test_report_contains_momentum_values(self, opportunities):
        """Every momentum value (formatted to 1 decimal place) appears in the output."""
        report = format_opportunities_report(opportunities)

        for opp in opportunities:
            formatted_momentum = f"{opp['momentum']:.1f}"
            assert formatted_momentum in report, f"Momentum value '{formatted_momentum}' not found in report output"


class TestReportSortedByDrawdown:
    """Property 8: Report sorted by drawdown ascending.

    Drawdown values in output appear in ascending order (most negative first).

    Feature: momentum-drawdown-filter, Property 8: Report sorted by drawdown ascending
    **Validates: Requirements 5.2**
    """

    @given(opportunities=opportunities_list_strategy)
    @settings(max_examples=100, deadline=None)
    def test_report_maintains_drawdown_order(self, opportunities):
        """When given a pre-sorted list, drawdown values in output rows are non-decreasing."""
        # Pre-sort by drawdown ascending (most negative first) as per design contract
        sorted_opps = sorted(opportunities, key=lambda x: x["drawdown_pct"])

        report = format_opportunities_report(sorted_opps)

        # Extract numeric drawdown values from the report body lines
        # Skip header lines (first 3 lines: title, separator, column headers)
        lines = report.strip().split("\n")
        # Data lines start after the header ("Opportunities", "=============", column header)
        data_lines = [line for line in lines[2:] if line.strip()]

        # Extract drawdown values from each data line using regex
        # Format is: "TICKER     -45.2       3.8" (columns separated by whitespace)
        drawdown_values = []
        for line in data_lines:
            # Match a negative float (drawdown is always negative for qualifying tickers)
            match = re.search(r"(-?\d+\.\d)", line)
            if match:
                drawdown_values.append(float(match.group(1)))

        # Verify drawdown values are in non-decreasing (ascending) order
        for i in range(len(drawdown_values) - 1):
            assert drawdown_values[i] <= drawdown_values[i + 1], (
                f"Drawdown values not in ascending order: "
                f"{drawdown_values[i]} > {drawdown_values[i + 1]} at index {i}"
            )


# ---------------------------------------------------------------------------
# Unit tests — Report formatting (Task 3.3)
# Validates: Requirements 5.1, 5.2, 5.3
# ---------------------------------------------------------------------------


class TestFormatEmptyList:
    """Validates: Requirement 5.3 — empty list produces 'No opportunities found'."""

    def test_contains_header(self):
        result = format_opportunities_report([])
        assert "Opportunities" in result
        assert "=============" in result

    def test_contains_no_opportunities_message(self):
        result = format_opportunities_report([])
        assert "No opportunities found" in result


class TestFormatDisabled:
    """Validates: Requirement 6.3 — disabled filter produces 'Opportunities: disabled'."""

    def test_contains_header(self):
        result = format_disabled_report()
        assert "Opportunities" in result
        assert "=============" in result

    def test_contains_disabled_message(self):
        result = format_disabled_report()
        assert "Opportunities: disabled" in result


class TestFormatSingleEntry:
    """Validates: Requirement 5.1 — report contains ticker, drawdown%, momentum%."""

    @pytest.fixture
    def single_opportunity(self):
        return [{"ticker": "INTC", "drawdown_pct": -45.2, "momentum": 3.8}]

    def test_contains_ticker(self, single_opportunity):
        result = format_opportunities_report(single_opportunity)
        assert "INTC" in result

    def test_contains_drawdown(self, single_opportunity):
        result = format_opportunities_report(single_opportunity)
        assert "-45.2" in result

    def test_contains_momentum(self, single_opportunity):
        result = format_opportunities_report(single_opportunity)
        assert "3.8" in result

    def test_contains_header(self, single_opportunity):
        result = format_opportunities_report(single_opportunity)
        assert "Opportunities" in result
        assert "=============" in result

    def test_contains_column_headers(self, single_opportunity):
        result = format_opportunities_report(single_opportunity)
        assert "Ticker" in result
        assert "Drawdown%" in result
        assert "Momentum%" in result


class TestFormatMultipleEntries:
    """Validates: Requirements 5.1, 5.2 — all entries present and in drawdown order."""

    @pytest.fixture
    def sorted_opportunities(self):
        """Three entries pre-sorted by drawdown_pct ascending (most negative first)."""
        return [
            {"ticker": "INTC", "drawdown_pct": -45.2, "momentum": 3.8},
            {"ticker": "BA", "drawdown_pct": -38.1, "momentum": 2.1},
            {"ticker": "NKE", "drawdown_pct": -22.5, "momentum": 1.5},
        ]

    def test_contains_all_tickers(self, sorted_opportunities):
        result = format_opportunities_report(sorted_opportunities)
        assert "INTC" in result
        assert "BA" in result
        assert "NKE" in result

    def test_contains_all_drawdowns(self, sorted_opportunities):
        result = format_opportunities_report(sorted_opportunities)
        assert "-45.2" in result
        assert "-38.1" in result
        assert "-22.5" in result

    def test_contains_all_momentums(self, sorted_opportunities):
        result = format_opportunities_report(sorted_opportunities)
        assert "3.8" in result
        assert "2.1" in result
        assert "1.5" in result

    def test_entries_in_drawdown_order(self, sorted_opportunities):
        """Drawdown values appear in ascending order (most negative first)."""
        result = format_opportunities_report(sorted_opportunities)
        intc_pos = result.index("INTC")
        ba_pos = result.index("BA")
        nke_pos = result.index("NKE")
        assert intc_pos < ba_pos < nke_pos

    def test_has_header(self, sorted_opportunities):
        result = format_opportunities_report(sorted_opportunities)
        assert "Opportunities" in result
        assert "=============" in result


# ---------------------------------------------------------------------------
# Unit tests — Config loading and filter edge cases (Task 1.6)
# Validates: Requirements 6.2, 6.3, 6.4, 6.5, 4.1
# ---------------------------------------------------------------------------


def make_price_df(prices: list[float]) -> pd.DataFrame:
    """Create a DataFrame from a list of closing prices."""
    return pd.DataFrame(
        {
            "Date": pd.date_range("2023-01-01", periods=len(prices)),
            "Close": prices,
            "High": [p + 1 for p in prices],
            "Low": [p - 1 for p in prices],
            "Open": prices,
            "Volume": [1_000_000] * len(prices),
        }
    )


class TestConfigDefaults:
    """Validates: Requirement 6.2 — defaults applied when section is missing."""

    def test_missing_section_uses_all_defaults(self):
        config = {}
        result = load_drawdown_config(config)
        assert result["enabled"] is True
        assert result["drawdown_threshold"] == 20
        assert result["momentum_period"] == 20
        assert result["data_days"] == 400

    def test_empty_section_uses_all_defaults(self):
        config = {"drawdown_filter": {}}
        result = load_drawdown_config(config)
        assert result["enabled"] is True
        assert result["drawdown_threshold"] == 20
        assert result["momentum_period"] == 20
        assert result["data_days"] == 400


class TestConfigValidParsing:
    """Validates: Requirement 6.1 — valid config section is parsed correctly."""

    def test_all_fields_parsed(self):
        config = {
            "drawdown_filter": {
                "enabled": False,
                "drawdown_threshold": 30,
                "momentum_period": 10,
                "data_days": 400,
            }
        }
        result = load_drawdown_config(config)
        assert result["enabled"] is False
        assert result["drawdown_threshold"] == 30
        assert result["momentum_period"] == 10
        assert result["data_days"] == 400

    def test_partial_section_fills_missing_with_defaults(self):
        config = {"drawdown_filter": {"drawdown_threshold": 15}}
        result = load_drawdown_config(config)
        assert result["drawdown_threshold"] == 15
        assert result["enabled"] is True
        assert result["momentum_period"] == 20
        assert result["data_days"] == 400


class TestConfigEnabledFlag:
    """Validates: Requirement 6.3 — enabled: false flag is respected."""

    def test_disabled_flag_preserved(self):
        config = {"drawdown_filter": {"enabled": False}}
        result = load_drawdown_config(config)
        assert result["enabled"] is False

    def test_enabled_flag_preserved(self):
        config = {"drawdown_filter": {"enabled": True}}
        result = load_drawdown_config(config)
        assert result["enabled"] is True


class TestConfigInvalidMomentumPeriod:
    """Validates: Requirement 6.4 — invalid momentum_period logs warning and uses default."""

    def test_zero_period_uses_default(self, caplog):
        config = {"drawdown_filter": {"momentum_period": 0}}
        with caplog.at_level(logging.WARNING):
            result = load_drawdown_config(config)
        assert result["momentum_period"] == 20
        assert "momentum_period" in caplog.text

    def test_negative_period_uses_default(self, caplog):
        config = {"drawdown_filter": {"momentum_period": -5}}
        with caplog.at_level(logging.WARNING):
            result = load_drawdown_config(config)
        assert result["momentum_period"] == 20
        assert "momentum_period" in caplog.text


class TestConfigInvalidDrawdownThreshold:
    """Validates: Requirement 6.5 — invalid drawdown_threshold logs warning and uses default."""

    def test_negative_threshold_uses_default(self, caplog):
        config = {"drawdown_filter": {"drawdown_threshold": -1}}
        with caplog.at_level(logging.WARNING):
            result = load_drawdown_config(config)
        assert result["drawdown_threshold"] == 20
        assert "drawdown_threshold" in caplog.text

    def test_over_100_threshold_uses_default(self, caplog):
        config = {"drawdown_filter": {"drawdown_threshold": 101}}
        with caplog.at_level(logging.WARNING):
            result = load_drawdown_config(config)
        assert result["drawdown_threshold"] == 20
        assert "drawdown_threshold" in caplog.text


class TestFilterAllTimeHigh:
    """Validates: Requirement 4.1 — all-time-high ticker (drawdown ≈ 0) not in opportunities."""

    def test_ticker_at_all_time_high_returns_none(self):
        # 260 rows of steadily rising prices — last price IS the max
        prices = [100.0 + i * 0.5 for i in range(260)]
        df = make_price_df(prices)

        result = evaluate_ticker(df, drawdown_threshold=20.0, momentum_period=20)
        assert result is None


class TestFilterExactlyAtThreshold:
    """Validates: Requirement 4.1 — exactly at threshold boundary (drawdown = -20 exactly)."""

    def test_exactly_at_threshold_with_positive_momentum_qualifies(self):
        # Need: current_close = 0.8 * max_close, and momentum > 0
        # Build 260 prices where: peak was 100.0 somewhere in the first 252,
        # current (last) is 80.0 (exactly -20%), and price 20 days ago < 80.0
        # so momentum is positive.
        peak = 100.0
        current = 80.0  # exactly 80% of peak -> drawdown = -20%
        price_20_ago = 75.0  # momentum = ((80 - 75) / 75) * 100 = 6.67% (positive)

        # Build a price series: 252 days with peak=100 somewhere early,
        # then declining, with specific values near the end
        prices = [90.0] * 230  # baseline below peak
        prices[10] = peak  # set the 52-week high at index 10
        # Fill remaining to reach 260 total, with price 20 days ago = 75
        # and last price = 80
        remaining = 260 - len(prices)
        prices.extend([price_20_ago] * remaining)
        prices[-1] = current  # last price = 80.0

        df = make_price_df(prices)

        result = evaluate_ticker(df, drawdown_threshold=20.0, momentum_period=20)

        # drawdown = ((80 - 100) / 100) * 100 = -20.0
        # Condition: drawdown_pct <= -threshold => -20 <= -20 => True
        # momentum > 0 => True
        assert result is not None
        assert result["drawdown_pct"] == pytest.approx(-20.0)
        assert result["momentum"] > 0


class TestFilterZeroMomentum:
    """Validates: Requirement 4.1 — zero momentum excluded (must be strictly > 0)."""

    def test_zero_momentum_returns_none(self):
        # Need: drawdown satisfies threshold, but momentum = 0
        # momentum = 0 when price 20 days ago equals current price
        peak = 100.0
        current = 70.0  # drawdown = -30%, well below -20% threshold
        price_20_ago = 70.0  # momentum = ((70 - 70) / 70) * 100 = 0

        prices = [85.0] * 230
        prices[10] = peak  # 52-week high
        remaining = 260 - len(prices)
        prices.extend([price_20_ago] * remaining)
        prices[-1] = current  # same as price_20_ago => momentum = 0

        df = make_price_df(prices)

        result = evaluate_ticker(df, drawdown_threshold=20.0, momentum_period=20)
        assert result is None


# ---------------------------------------------------------------------------
# Integration tests — End-to-end flow with synthetic DataFrames (Task 6.3)
# Validates: Requirements 1.2, 4.1, 5.1, 5.4, 6.3
# ---------------------------------------------------------------------------


def make_qualifying_df(
    rows: int = 260, peak: float = 100.0, current: float = 75.0, price_20_ago: float = 70.0
) -> pd.DataFrame:
    """Create a DataFrame where the ticker qualifies: drawdown >= 20% and positive momentum.

    Args:
        rows: Total number of rows (must be >= 252).
        peak: The 52-week high price (placed early in the series).
        current: The most recent closing price.
        price_20_ago: The closing price 20 days before current (momentum baseline).

    Returns:
        DataFrame with a 'Close' column that produces qualifying filter results.
    """
    # Build baseline prices below peak
    baseline = peak * 0.85
    prices = [baseline] * (rows - 30)
    prices[10] = peak  # set 52-week high early in the series
    # Fill the last 30 days: 29 days at price_20_ago, then current
    prices.extend([price_20_ago] * 29)
    prices.append(current)
    return pd.DataFrame({"Close": prices})


def make_near_high_df(rows: int = 260, peak: float = 100.0, current: float = 95.0) -> pd.DataFrame:
    """Create a DataFrame where the ticker is near its 52-week high (insufficient drawdown).

    Args:
        rows: Total number of rows.
        peak: The 52-week high price.
        current: The most recent closing price (close to peak).

    Returns:
        DataFrame that does NOT qualify due to insufficient drawdown.
    """
    prices = [peak * 0.9] * (rows - 1)
    prices[10] = peak  # set 52-week high
    prices.append(current)  # near the high → drawdown < 20%
    return pd.DataFrame({"Close": prices})


def make_negative_momentum_df(
    rows: int = 260, peak: float = 100.0, current: float = 70.0, price_20_ago: float = 80.0
) -> pd.DataFrame:
    """Create a DataFrame where drawdown qualifies but momentum is negative.

    Args:
        rows: Total number of rows.
        peak: The 52-week high price.
        current: The most recent closing price (well below peak).
        price_20_ago: The closing price 20 days ago (higher than current → negative momentum).

    Returns:
        DataFrame that does NOT qualify due to negative momentum.
    """
    baseline = peak * 0.85
    prices = [baseline] * (rows - 30)
    prices[10] = peak  # set 52-week high
    # price_20_ago > current → negative momentum
    prices.extend([price_20_ago] * 29)
    prices.append(current)
    return pd.DataFrame({"Close": prices})


class TestIntegrationMixedTickers:
    """Integration test: end-to-end flow with mix of qualifying and non-qualifying tickers.

    Simulates the app_all_shares.py flow:
    1. Load config via load_drawdown_config()
    2. Create synthetic DataFrames for multiple tickers
    3. Call evaluate_ticker() for each
    4. Collect results, sort by drawdown, format report
    5. Verify the final report output

    Validates: Requirements 1.2, 4.1, 5.1, 5.4
    """

    def test_only_qualifying_ticker_appears_in_report(self):
        """Only ticker meeting both criteria (drawdown + positive momentum) appears in report."""
        # 1. Load config
        config = {
            "drawdown_filter": {
                "enabled": True,
                "drawdown_threshold": 20,
                "momentum_period": 20,
                "data_days": 365,
            }
        }
        drawdown_config = load_drawdown_config(config)

        # 2. Create synthetic DataFrames
        tickers_data = {
            "QUAL": make_qualifying_df(rows=260, peak=100.0, current=75.0, price_20_ago=70.0),
            "NEAR": make_near_high_df(rows=260, peak=100.0, current=95.0),
            "NEGM": make_negative_momentum_df(rows=260, peak=100.0, current=70.0, price_20_ago=80.0),
        }

        # 3. Evaluate each ticker
        opportunities = []
        for ticker, ticker_df in tickers_data.items():
            result = evaluate_ticker(
                df=ticker_df,
                drawdown_threshold=drawdown_config["drawdown_threshold"],
                momentum_period=drawdown_config["momentum_period"],
            )
            if result is not None:
                result["ticker"] = ticker
                opportunities.append(result)

        # 4. Sort by drawdown ascending (most negative first)
        opportunities.sort(key=lambda x: x["drawdown_pct"])

        # 5. Format report
        report = format_opportunities_report(opportunities)

        # Verify only QUAL appears
        assert "QUAL" in report
        assert "NEAR" not in report
        assert "NEGM" not in report

    def test_report_has_correct_structure(self):
        """Report includes header, column headers, and data for qualifying ticker."""
        config = {"drawdown_filter": {"enabled": True, "drawdown_threshold": 20, "momentum_period": 20}}
        drawdown_config = load_drawdown_config(config)

        tickers_data = {
            "QUAL": make_qualifying_df(rows=260, peak=100.0, current=75.0, price_20_ago=70.0),
            "NEAR": make_near_high_df(rows=260, peak=100.0, current=95.0),
        }

        opportunities = []
        for ticker, ticker_df in tickers_data.items():
            result = evaluate_ticker(
                df=ticker_df,
                drawdown_threshold=drawdown_config["drawdown_threshold"],
                momentum_period=drawdown_config["momentum_period"],
            )
            if result is not None:
                result["ticker"] = ticker
                opportunities.append(result)

        opportunities.sort(key=lambda x: x["drawdown_pct"])
        report = format_opportunities_report(opportunities)

        assert "Opportunities" in report
        assert "=============" in report
        assert "Ticker" in report
        assert "Drawdown%" in report
        assert "Momentum%" in report
        assert "-25.0" in report  # drawdown = ((75-100)/100)*100 = -25%

    def test_multiple_qualifying_tickers_sorted_correctly(self):
        """When multiple tickers qualify, they are sorted by drawdown ascending."""
        config = {"drawdown_filter": {"enabled": True, "drawdown_threshold": 20, "momentum_period": 20}}
        drawdown_config = load_drawdown_config(config)

        tickers_data = {
            "MILD": make_qualifying_df(rows=260, peak=100.0, current=78.0, price_20_ago=73.0),
            "DEEP": make_qualifying_df(rows=260, peak=100.0, current=55.0, price_20_ago=50.0),
        }

        opportunities = []
        for ticker, ticker_df in tickers_data.items():
            result = evaluate_ticker(
                df=ticker_df,
                drawdown_threshold=drawdown_config["drawdown_threshold"],
                momentum_period=drawdown_config["momentum_period"],
            )
            if result is not None:
                result["ticker"] = ticker
                opportunities.append(result)

        opportunities.sort(key=lambda x: x["drawdown_pct"])
        report = format_opportunities_report(opportunities)

        # DEEP has larger drawdown (-45%) than MILD (-22%), so DEEP appears first
        deep_pos = report.index("DEEP")
        mild_pos = report.index("MILD")
        assert deep_pos < mild_pos


class TestIntegrationDisabledConfig:
    """Integration test: disabled config produces correct output.

    Validates: Requirements 5.4, 6.3
    """

    def test_disabled_config_produces_disabled_message(self):
        """When enabled is false, format_disabled_report produces 'Opportunities: disabled'."""
        config = {"drawdown_filter": {"enabled": False}}
        drawdown_config = load_drawdown_config(config)

        assert drawdown_config["enabled"] is False

        report = format_disabled_report()
        assert "Opportunities" in report
        assert "=============" in report
        assert "Opportunities: disabled" in report

    def test_disabled_config_skips_evaluation(self):
        """When disabled, no tickers should be evaluated (simulating app_all_shares flow)."""
        config = {"drawdown_filter": {"enabled": False}}
        drawdown_config = load_drawdown_config(config)

        # Simulate the app_all_shares.py conditional logic
        if drawdown_config["enabled"]:
            # This block should not execute
            raise AssertionError("Should not evaluate tickers when disabled")
        else:
            report = format_disabled_report()

        assert "Opportunities: disabled" in report


class TestIntegrationNoQualifyingTickers:
    """Integration test: no qualifying tickers produces 'No opportunities found'.

    Validates: Requirements 4.1, 5.1
    """

    def test_no_qualifying_tickers_message(self):
        """When no ticker meets both criteria, report says 'No opportunities found'."""
        config = {"drawdown_filter": {"enabled": True, "drawdown_threshold": 20, "momentum_period": 20}}
        drawdown_config = load_drawdown_config(config)

        # All tickers fail to qualify for different reasons
        tickers_data = {
            "NEAR": make_near_high_df(rows=260, peak=100.0, current=95.0),
            "NEGM": make_negative_momentum_df(rows=260, peak=100.0, current=70.0, price_20_ago=80.0),
        }

        opportunities = []
        for ticker, ticker_df in tickers_data.items():
            result = evaluate_ticker(
                df=ticker_df,
                drawdown_threshold=drawdown_config["drawdown_threshold"],
                momentum_period=drawdown_config["momentum_period"],
            )
            if result is not None:
                result["ticker"] = ticker
                opportunities.append(result)

        opportunities.sort(key=lambda x: x["drawdown_pct"])
        report = format_opportunities_report(opportunities)

        assert "No opportunities found" in report
        assert "NEAR" not in report
        assert "NEGM" not in report


class TestIntegrationInsufficientData:
    """Integration test: tickers with insufficient data are excluded.

    Validates: Requirements 1.2
    """

    def test_insufficient_data_returns_none(self):
        """A DataFrame with only 100 rows causes evaluate_ticker to return None."""
        config = {"drawdown_filter": {"enabled": True, "drawdown_threshold": 20, "momentum_period": 20}}
        drawdown_config = load_drawdown_config(config)

        # Only 100 rows — far below the 252 minimum
        short_df = pd.DataFrame({"Close": [50.0] * 100})

        result = evaluate_ticker(
            df=short_df,
            drawdown_threshold=drawdown_config["drawdown_threshold"],
            momentum_period=drawdown_config["momentum_period"],
        )

        assert result is None

    def test_insufficient_data_excluded_from_report(self):
        """Tickers with insufficient data don't appear in the final report."""
        config = {"drawdown_filter": {"enabled": True, "drawdown_threshold": 20, "momentum_period": 20}}
        drawdown_config = load_drawdown_config(config)

        tickers_data = {
            "SHORT": pd.DataFrame({"Close": [50.0] * 100}),  # insufficient data
            "QUAL": make_qualifying_df(rows=260, peak=100.0, current=75.0, price_20_ago=70.0),
        }

        opportunities = []
        for ticker, ticker_df in tickers_data.items():
            result = evaluate_ticker(
                df=ticker_df,
                drawdown_threshold=drawdown_config["drawdown_threshold"],
                momentum_period=drawdown_config["momentum_period"],
            )
            if result is not None:
                result["ticker"] = ticker
                opportunities.append(result)

        opportunities.sort(key=lambda x: x["drawdown_pct"])
        report = format_opportunities_report(opportunities)

        assert "SHORT" not in report
        assert "QUAL" in report
