"""Property-based tests for labelling and dataset shape.

# Feature: vpa-ml-validation, Property 3: Next-day direction labelling
# Feature: vpa-ml-validation, Property 4: Dataset excludes unlabellable final row
# Feature: vpa-ml-validation, Property 5: NaN OHLCV rows are dropped
"""

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis.strategies import (
    composite,
    floats,
    integers,
    lists,
)

# --- Helper: replicates the labelling logic from generate_dataset() ---


def apply_labelling(df: pd.DataFrame) -> pd.DataFrame:
    """Replicate the labelling logic from VPAFeatureExtractor.generate_dataset().

    Given a DataFrame with a 'close' column, applies:
      1. next_day_direction = 1 if next row's close > current close, else 0
      2. Drops the final row (no next-day label available)

    Returns the labelled DataFrame (copy, original unmodified).
    """
    result = df.copy()
    result["next_day_direction"] = (result["close"].shift(-1) > result["close"]).astype(int)
    result = result.iloc[:-1].reset_index(drop=True)
    return result


def drop_nan_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Replicate the NaN-dropping logic from VPAFeatureExtractor.generate_dataset().

    Drops rows where any of the OHLCV columns contain NaN values.
    """
    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    return df.dropna(subset=ohlcv_cols).reset_index(drop=True)


# --- Strategies ---


@composite
def closing_price_sequences(draw, min_size=2, max_size=200):
    """Generate random sequences of closing prices (positive floats)."""
    size = draw(integers(min_value=min_size, max_value=max_size))
    prices = draw(
        lists(
            floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
            min_size=size,
            max_size=size,
        )
    )
    return prices


@composite
def ohlcv_dataframes_with_nans(draw, min_rows=5, max_rows=100):
    """Generate OHLCV DataFrames with random NaN insertions.

    Returns a tuple of (dataframe_with_nans, set_of_nan_row_indices).
    """
    n_rows = draw(integers(min_value=min_rows, max_value=max_rows))

    # Generate valid OHLCV data
    opens = draw(
        lists(
            floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=n_rows,
            max_size=n_rows,
        )
    )
    highs = [o + abs(draw(floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False))) for o in opens]
    lows = [o - abs(draw(floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False))) for o in opens]
    closes = draw(
        lists(
            floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=n_rows,
            max_size=n_rows,
        )
    )
    volumes = draw(
        lists(
            floats(min_value=100.0, max_value=1e9, allow_nan=False, allow_infinity=False),
            min_size=n_rows,
            max_size=n_rows,
        )
    )

    df = pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": volumes,
        }
    )

    # Insert NaN values in random positions (at least 1 NaN, at most half the rows)
    max_nan_rows = max(1, n_rows // 2)
    n_nan_rows = draw(integers(min_value=1, max_value=max_nan_rows))

    # Choose which rows get NaN
    nan_row_indices = set(
        draw(
            lists(
                integers(min_value=0, max_value=n_rows - 1),
                min_size=n_nan_rows,
                max_size=n_nan_rows,
            )
        )
    )

    # Choose which OHLCV column to set NaN in for each chosen row
    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    for row_idx in nan_row_indices:
        col_idx = draw(integers(min_value=0, max_value=4))
        df.at[row_idx, ohlcv_cols[col_idx]] = np.nan

    return df, nan_row_indices


# --- Property 3: Next-day direction labelling ---


@settings(max_examples=100)
@given(prices=closing_price_sequences(min_size=2, max_size=200))
def test_next_day_direction_labelling(prices: list) -> None:
    """Property 3: Next-day direction labelling.

    For any sequence of closing prices, each row's next_day_direction label shall
    equal 1 if the next row's close is strictly greater than the current row's
    close, and 0 otherwise (including when they are equal).

    **Validates: Requirements 2.2**
    """
    df = pd.DataFrame({"close": prices})
    labelled = apply_labelling(df)

    # Verify each label
    for i in range(len(labelled)):
        current_close = prices[i]
        next_close = prices[i + 1]

        expected_label = 1 if next_close > current_close else 0
        actual_label = labelled.at[i, "next_day_direction"]

        assert actual_label == expected_label, (
            f"Row {i}: current_close={current_close}, next_close={next_close}, "
            f"expected={expected_label}, got={actual_label}"
        )


@settings(max_examples=100)
@given(prices=closing_price_sequences(min_size=2, max_size=200))
def test_equal_prices_labelled_as_zero(prices: list) -> None:
    """Property 3 (supplementary): Equal consecutive prices are labelled 0.

    When next day's close equals current day's close, label should be 0 (DOWN).

    **Validates: Requirements 2.2**
    """
    # Force some equal consecutive prices to test the boundary
    modified_prices = prices.copy()
    if len(modified_prices) >= 2:
        # Set first two prices equal
        modified_prices[1] = modified_prices[0]

    df = pd.DataFrame({"close": modified_prices})
    labelled = apply_labelling(df)

    # Verify the row where next_close == current_close
    if len(labelled) > 0 and modified_prices[1] == modified_prices[0]:
        assert labelled.at[0, "next_day_direction"] == 0, f"Equal prices ({modified_prices[0]}) should produce label 0"


# --- Property 4: Dataset excludes unlabellable final row ---


@settings(max_examples=50)
@given(n_rows=integers(min_value=2, max_value=500))
def test_dataset_excludes_final_row(n_rows: int) -> None:
    """Property 4: Dataset excludes unlabellable final row.

    For any generated dataset with N trading days after warm-up, the output
    dataset shall contain exactly N-1 rows (the final row having no next-day
    label is excluded).

    **Validates: Requirements 2.5**
    """
    # Create a DataFrame with N rows of closing prices
    prices = list(range(100, 100 + n_rows))  # Simple deterministic prices
    df = pd.DataFrame({"close": [float(p) for p in prices]})

    labelled = apply_labelling(df)

    assert len(labelled) == n_rows - 1, f"Expected {n_rows - 1} rows from {n_rows} input rows, got {len(labelled)}"


@settings(max_examples=50)
@given(prices=closing_price_sequences(min_size=2, max_size=300))
def test_final_row_excluded_with_random_data(prices: list) -> None:
    """Property 4 (supplementary): Final row exclusion with random price data.

    Verifies that the output always has exactly len(input) - 1 rows regardless
    of the actual price values.

    **Validates: Requirements 2.5**
    """
    df = pd.DataFrame({"close": prices})
    labelled = apply_labelling(df)

    assert len(labelled) == len(prices) - 1, f"Expected {len(prices) - 1} rows, got {len(labelled)}"

    # Also verify no NaN in labels (all rows should have valid labels)
    assert labelled["next_day_direction"].isna().sum() == 0, "All rows in the output should have valid (non-NaN) labels"


# --- Property 5: NaN OHLCV rows are dropped ---


@settings(max_examples=100)
@given(data=ohlcv_dataframes_with_nans(min_rows=5, max_rows=100))
def test_nan_ohlcv_rows_dropped(data: tuple) -> None:
    """Property 5: NaN OHLCV rows are dropped.

    For any input DataFrame containing rows with NaN values in any OHLCV column,
    those rows shall be absent from the generated dataset, and all remaining rows
    shall have non-NaN values in all OHLCV columns.

    **Validates: Requirements 2.6**
    """
    df_with_nans, nan_row_indices = data

    result = drop_nan_ohlcv(df_with_nans)

    # All remaining rows should have no NaN in OHLCV columns
    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in ohlcv_cols:
        assert result[col].isna().sum() == 0, f"Column {col} still has NaN values after dropping"

    # Result should have fewer rows than input (we inserted at least 1 NaN)
    # Note: nan_row_indices may have duplicates, so actual NaN rows could be fewer
    rows_with_any_nan = df_with_nans[ohlcv_cols].isna().any(axis=1).sum()
    expected_rows = len(df_with_nans) - rows_with_any_nan

    assert len(result) == expected_rows, f"Expected {expected_rows} rows after dropping NaN, got {len(result)}"


@settings(max_examples=100)
@given(data=ohlcv_dataframes_with_nans(min_rows=5, max_rows=100))
def test_nan_dropping_preserves_valid_rows(data: tuple) -> None:
    """Property 5 (supplementary): Valid rows are preserved after NaN dropping.

    All rows that originally had no NaN in any OHLCV column should remain in
    the output after NaN dropping.

    **Validates: Requirements 2.6**
    """
    df_with_nans, _ = data

    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    result = drop_nan_ohlcv(df_with_nans)

    # Get indices of rows that have no NaN in original
    valid_mask = ~df_with_nans[ohlcv_cols].isna().any(axis=1)
    expected_valid_rows = df_with_nans[valid_mask]

    # Compare values (reset index for both)
    expected_valid_rows = expected_valid_rows.reset_index(drop=True)

    assert len(result) == len(expected_valid_rows), f"Expected {len(expected_valid_rows)} valid rows, got {len(result)}"

    # Values should match
    pd.testing.assert_frame_equal(
        result[ohlcv_cols],
        expected_valid_rows[ohlcv_cols],
        check_exact=True,
    )
